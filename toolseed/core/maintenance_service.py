"""Maintenance decisions and diagnosis, with atomic candidate repair."""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Any

from .candidates import CandidateService
from .errors import (
    CAPABILITY_NOT_FOUND,
    INVALID_ARGUMENT,
    SAVE_PERSISTENCE_FAILED,
    error_response,
)
from .evidence import (
    ASSESSMENT_WATERMARK_KEY,
    FAILURE_CATEGORIES,
    Evidence,
)
from .registry import Registry
from .service_support import (
    REASON_WATERMARK_MISSING,
    _CandidateRejected,
)
from .storage import Store


class MaintenanceService:
    def __init__(
        self, store: Store, registry: Registry, evidence: Evidence, candidates: CandidateService
    ) -> None:
        self.store = store
        self.registry = registry
        self.evidence = evidence
        self.candidates = candidates

    def maintenance_report(self) -> dict[str, Any]:
        return {"ok": True, "report": self.evidence.maintenance_report()}

    def version_report(self, version_id: Any) -> dict[str, Any]:
        if not isinstance(version_id, str):
            return error_response(INVALID_ARGUMENT, "version_id must be a string")
        report = self.evidence.version_stats(version_id)
        if report is None:
            return error_response(INVALID_ARGUMENT, "version_id does not exist")
        return {"ok": True, "report": report}

    def run_maintenance(self) -> dict[str, Any]:
        report = self.evidence.maintenance_report()
        created: list[dict[str, Any]] = []
        skipped = 0
        for suggestion in report["suggestions"]:
            action = str(suggestion.get("action"))
            reason = str(suggestion.get("reason"))
            capability_id = suggestion.get("capability_id")
            version_id = suggestion.get("version_id")
            dedup_key = ":".join(
                (
                    action,
                    reason,
                    str(capability_id or "-"),
                    str(version_id or "-"),
                )
            )
            if action == "revalidate_evidence":
                evidence_ids = suggestion.get("evidence_ids") or []
                digest = hashlib.sha1(
                    "|".join(sorted(str(item) for item in evidence_ids)).encode("utf-8")
                ).hexdigest()[:12]
                dedup_key += f":{digest}"
            decision, is_new = self.evidence.create_decision(
                action=action,
                reason=reason,
                dedup_key=dedup_key,
                capability_id=capability_id,
                version_id=version_id,
                payload=suggestion,
            )
            if is_new:
                created.append(decision)
            else:
                skipped += 1
        return {
            "ok": True,
            "report": report,
            "created": created,
            "skipped": skipped,
        }

    def list_evolution_decisions(
        self,
        *,
        status: Any = None,
        capability_id: Any = None,
    ) -> dict[str, Any]:
        if status is not None and status not in ("proposed", "applied", "dismissed"):
            return error_response(INVALID_ARGUMENT, "unsupported decision status")
        if capability_id is not None and not isinstance(capability_id, str):
            return error_response(INVALID_ARGUMENT, "capability_id must be a string")
        return {
            "ok": True,
            "decisions": self.evidence.list_decisions(
                status=status,
                capability_id=capability_id,
            ),
        }

    def dismiss_evolution_decision(
        self,
        decision_id: Any,
        resolution: Any = None,
    ) -> dict[str, Any]:
        if not isinstance(decision_id, str):
            return error_response(INVALID_ARGUMENT, "decision_id must be a string")
        if resolution is not None and not isinstance(resolution, str):
            return error_response(INVALID_ARGUMENT, "resolution must be a string")
        try:
            with self.store.transaction(immediate=True):
                decision = self.evidence.get_decision(decision_id)
                if decision is None:
                    return error_response(INVALID_ARGUMENT, "decision_id does not exist")
                if decision["status"] == "dismissed":
                    return {"ok": True, "decision": decision, "dismissed": False}
                self.evidence.dismiss_decision(decision_id, resolution)
                return {
                    "ok": True,
                    "decision": self.evidence.get_decision(decision_id),
                    "dismissed": True,
                }
        except (sqlite3.Error, OSError):
            return error_response(
                SAVE_PERSISTENCE_FAILED, "decision dismissal could not be durably recorded"
            )

    def apply_evolution_decision(
        self,
        decision_id: Any,
        resolution: Any = None,
    ) -> dict[str, Any]:
        if not isinstance(decision_id, str):
            return error_response(INVALID_ARGUMENT, "decision_id must be a string")
        if resolution is not None and not isinstance(resolution, str):
            return error_response(INVALID_ARGUMENT, "resolution must be a string")
        try:
            # Acquire the writer slot before reading state or validity. Other connections
            # cannot commit an invalidation/dismissal between this check and its UPDATE.
            with self.store.transaction(immediate=True):
                result = self._apply_evolution_decision(decision_id, resolution)
                if not result.get("ok"):
                    # Inner management helpers may translate a write error into a result.
                    # Do not commit their partial side effects just because it was caught.
                    raise _CandidateRejected(result)
                return result
        except _CandidateRejected as exc:
            return exc.response
        except (sqlite3.Error, OSError):
            return error_response(
                SAVE_PERSISTENCE_FAILED, "decision application could not be durably recorded"
            )

    def _apply_evolution_decision(
        self,
        decision_id: str,
        resolution: str | None,
    ) -> dict[str, Any]:
        """Decision checks and effects; called with the outer IMMEDIATE transaction held."""
        decision = self.evidence.get_decision(decision_id)
        if decision is None:
            return error_response(INVALID_ARGUMENT, "decision_id does not exist")
        if decision["status"] == "applied":
            return {"ok": True, "decision": decision, "applied": False}
        if decision["status"] != "proposed":
            return error_response(INVALID_ARGUMENT, "only proposed decisions can be applied")

        payload = decision["payload"] or {}
        if decision["action"] == "diagnose_failure":
            capability_id = payload.get("capability_id")
            version_id = payload.get("version_id")
            if not isinstance(capability_id, str) or not isinstance(version_id, str):
                return error_response(
                    INVALID_ARGUMENT, "diagnose_failure decision is missing capability/version"
                )
            current = next(
                (
                    item
                    for item in self.evidence.maintenance_report()["repeated_failures"]
                    if item["capability_id"] == capability_id and item["version_id"] == version_id
                ),
                None,
            )
            if current is None:
                return error_response(
                    INVALID_ARGUMENT,
                    "repeated failure evidence no longer meets the threshold",
                    reason_code="FAILURE_EVIDENCE_CHANGED",
                )
            failures = current["failures"]

            try:
                with self.store.transaction():
                    diagnosis = self.diagnose_failure(
                        capability_id=capability_id,
                        version_id=version_id,
                        category=current["suggested_category"],
                        summary=f"repeated failures: {failures}",
                    )
                    if not diagnosis.get("ok"):
                        raise _CandidateRejected(diagnosis)
                    diagnosis_id = diagnosis["diagnosis"]["diagnosis_id"]
                    self.evidence.mark_decision_applied(
                        decision_id,
                        resolution or f"diagnosis:{diagnosis_id}",
                    )
            except _CandidateRejected as exc:
                return exc.response
            except (sqlite3.Error, OSError):
                return error_response(
                    SAVE_PERSISTENCE_FAILED,
                    "decision application could not be durably recorded",
                )

            return {
                "ok": True,
                "decision": self.evidence.get_decision(decision_id),
                "diagnosis": diagnosis["diagnosis"],
                "applied": True,
            }

        if decision["action"] == "revalidate_evidence":
            evidence_ids = payload.get("evidence_ids")
            version_id = payload.get("version_id")
            if (
                not isinstance(version_id, str)
                or not isinstance(evidence_ids, list)
                or not evidence_ids
                or not all(isinstance(item, str) for item in evidence_ids)
            ):
                return error_response(
                    INVALID_ARGUMENT,
                    "revalidate_evidence decision is missing version/evidence scope",
                )
            watermark = payload.get(ASSESSMENT_WATERMARK_KEY)
            if isinstance(watermark, bool) or not isinstance(watermark, int) or watermark < 0:
                # A decision recorded before assessment offsets existed cannot prove that
                # its scope was revalidated afterwards, and the wall clock must not stand
                # in for that proof. Fail closed; never backfill the offset from the
                # current MAX(rowid), which would invent an order that never happened.
                return error_response(
                    INVALID_ARGUMENT,
                    "revalidate_evidence decision carries no usable assessment offset and "
                    "cannot be applied; re-assess the scoped evidence, dismiss this "
                    "decision, and let maintenance raise a new one",
                    reason_code=REASON_WATERMARK_MISSING,
                )
            for evidence_id in evidence_ids:
                latest = self.evidence.latest_assessment(evidence_id)
                if latest is None or latest["validity"] != "valid":
                    fresh = False
                else:
                    # Freshness is structural, not temporal: the decision froze the
                    # assessment offset it was created at, and rowid is monotonic inside
                    # that one table, so a revalidation recorded after the decision
                    # always carries a greater rowid. The wall clock is not consulted,
                    # so a colliding timestamp can neither reject a real revalidation nor
                    # accept an assessment that predates the decision.
                    fresh = self.evidence.has_assessment_after(evidence_id, watermark)
                if not fresh:
                    return error_response(
                        INVALID_ARGUMENT,
                        "all scoped evidence must be reassessed as valid after the decision was created",
                    )
                event = self.store.db.execute(
                    "SELECT version_id FROM evidence_events WHERE event_id = ?",
                    (evidence_id,),
                ).fetchone()
                if event is None or event["version_id"] != version_id:
                    return error_response(
                        INVALID_ARGUMENT,
                        "evidence does not belong to the decision's version",
                    )

            try:
                with self.store.transaction():
                    self.evidence.mark_decision_applied(
                        decision_id,
                        resolution or f"revalidated:{len(evidence_ids)} evidence",
                    )
            except (sqlite3.Error, OSError):
                return error_response(
                    SAVE_PERSISTENCE_FAILED,
                    "decision application could not be durably recorded",
                )
            return {
                "ok": True,
                "decision": self.evidence.get_decision(decision_id),
                "applied": True,
                "revalidated": len(evidence_ids),
            }

        return error_response(
            INVALID_ARGUMENT,
            "this decision action still requires manual handling",
        )

    def diagnose_failure(
        self,
        *,
        capability_id: Any,
        version_id: Any,
        category: Any,
        summary: Any,
        invocation_id: Any = None,
        task_id: Any = None,
        evidence_ids: Any = None,
    ) -> dict[str, Any]:
        if not isinstance(capability_id, str):
            return error_response(INVALID_ARGUMENT, "capability_id must be a string")
        if not isinstance(version_id, str):
            return error_response(INVALID_ARGUMENT, "version_id must be a string")
        if category not in FAILURE_CATEGORIES:
            return error_response(
                INVALID_ARGUMENT,
                "unsupported failure category: " + str(category),
            )
        if not isinstance(summary, str) or not summary.strip():
            return error_response(INVALID_ARGUMENT, "summary must be a non-empty string")
        for name, value in (("invocation_id", invocation_id), ("task_id", task_id)):
            if value is not None and not isinstance(value, str):
                return error_response(INVALID_ARGUMENT, f"{name} must be a string")

        capability = self.registry.get_capability(capability_id)
        if capability is None:
            return error_response(CAPABILITY_NOT_FOUND, "no capability matches that id")
        version = self.registry.get_version(version_id)
        if version is None or version["capability_id"] != capability_id:
            return error_response(INVALID_ARGUMENT, "version_id does not belong to that capability")
        if invocation_id is not None:
            invocation = self.store.db.execute(
                "SELECT capability_id, version_id FROM invocations WHERE invocation_id = ?",
                (invocation_id,),
            ).fetchone()
            if invocation is None:
                return error_response(INVALID_ARGUMENT, "invocation_id does not exist")
            if (
                invocation["capability_id"] != capability_id
                or invocation["version_id"] != version_id
            ):
                return error_response(
                    INVALID_ARGUMENT,
                    "invocation does not belong to that capability/version",
                )

        if evidence_ids is None:
            ids: list[str] = []
        elif isinstance(evidence_ids, list) and all(isinstance(item, str) for item in evidence_ids):
            ids = evidence_ids
        else:
            return error_response(INVALID_ARGUMENT, "evidence_ids must be an array of strings")
        for evidence_id in ids:
            if not self.evidence.evidence_exists(evidence_id):
                return error_response(
                    INVALID_ARGUMENT, f"evidence_id does not exist: {evidence_id}"
                )

        diagnosis = self.evidence.create_diagnosis(
            capability_id=capability_id,
            version_id=version_id,
            category=category,
            summary=summary.strip()[:1000],
            invocation_id=invocation_id,
            task_id=task_id,
            evidence_ids=ids,
        )
        return {"ok": True, "diagnosis": diagnosis}

    def list_failure_diagnoses(
        self,
        *,
        capability_id: Any = None,
        status: Any = None,
    ) -> dict[str, Any]:
        if capability_id is not None and not isinstance(capability_id, str):
            return error_response(INVALID_ARGUMENT, "capability_id must be a string")
        if status is not None and status not in ("open", "repair_proposed", "dismissed"):
            return error_response(INVALID_ARGUMENT, "unsupported diagnosis status")
        return {
            "ok": True,
            "diagnoses": self.evidence.list_diagnoses(
                capability_id=capability_id,
                status=status,
            ),
        }

    def dismiss_diagnosis(self, diagnosis_id: Any) -> dict[str, Any]:
        if not isinstance(diagnosis_id, str):
            return error_response(INVALID_ARGUMENT, "diagnosis_id must be a string")
        diagnosis = self.evidence.get_diagnosis(diagnosis_id)
        if diagnosis is None:
            return error_response(INVALID_ARGUMENT, "diagnosis_id does not exist")
        if diagnosis["status"] == "dismissed":
            return {"ok": True, "diagnosis": diagnosis, "dismissed": False}
        self.evidence.dismiss_diagnosis(diagnosis_id)
        return {
            "ok": True,
            "diagnosis": self.evidence.get_diagnosis(diagnosis_id),
            "dismissed": True,
        }

    def propose_repair(
        self,
        diagnosis_id: Any,
        candidate: Any,
        intent: Any = "repair candidate",
        context: Any = None,
    ) -> dict[str, Any]:
        if not isinstance(diagnosis_id, str):
            return error_response(INVALID_ARGUMENT, "diagnosis_id must be a string")
        diagnosis = self.evidence.get_diagnosis(diagnosis_id)
        if diagnosis is None:
            return error_response(INVALID_ARGUMENT, "diagnosis_id does not exist")
        if diagnosis["status"] != "open":
            return error_response(INVALID_ARGUMENT, "only open diagnoses can receive a repair")
        if not isinstance(candidate, dict):
            return error_response(INVALID_ARGUMENT, "candidate must be an object")

        payload = dict(candidate)
        target = payload.get("target_capability_id")
        if target is not None and target != diagnosis["capability_id"]:
            return error_response(
                INVALID_ARGUMENT,
                "repair candidate target_capability_id does not match the diagnosis",
            )
        payload["target_capability_id"] = diagnosis["capability_id"]
        diagnosed_version = self.registry.get_version(diagnosis["version_id"])
        if diagnosed_version is not None:
            payload.setdefault("base_version_id", diagnosed_version["version_id"])
            payload.setdefault("base_content_hash", diagnosed_version["content_hash"])

        try:
            with self.store.transaction():
                response = self.candidates.save(
                    payload,
                    intent if isinstance(intent, str) else "repair candidate",
                    context,
                    force_candidate=True,
                )
                if response.get("status") != "accepted":
                    raise _CandidateRejected(response)
                self.evidence.mark_repair_proposed(diagnosis_id, response["version_id"])
        except _CandidateRejected as exc:
            return exc.response
        except (sqlite3.Error, OSError):
            return error_response(
                SAVE_PERSISTENCE_FAILED, "repair candidate could not be durably persisted"
            )

        return {
            "ok": True,
            "diagnosis": self.evidence.get_diagnosis(diagnosis_id),
            "repair": response,
        }
