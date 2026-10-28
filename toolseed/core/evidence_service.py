"""Trusted evidence, observations and verification use cases."""

from __future__ import annotations

import sqlite3
from typing import Any

from .errors import (
    CAPABILITY_ARCHIVED,
    CAPABILITY_NOT_FOUND,
    CAPABILITY_QUARANTINED,
    INVALID_ARGUMENT,
    SAVE_PERSISTENCE_FAILED,
    error_response,
)
from .evidence import (
    OBSERVATION_METHODS,
    OBSERVATION_STATUSES,
    OUTCOMES,
    SOURCE_TYPES,
    VALIDITIES,
    VERIFICATION_OUTCOMES,
    Evidence,
)
from .registry import STATUS_CANDIDATE, STATUS_QUARANTINED, STATUS_READY, Registry
from .service_support import (
    REASON_CONTENT_HASH_MISMATCH,
)
from .storage import Store


class EvidenceService:
    def __init__(self, store: Store, registry: Registry, evidence: Evidence) -> None:
        self.store = store
        self.registry = registry
        self.evidence = evidence

    def assess_evidence(
        self,
        evidence_id: Any,
        validity: Any,
        reason_code: Any,
        *,
        fingerprint: dict[str, Any] | None = None,
        invalidated_by: Any = None,
        superseded_by: Any = None,
    ) -> dict[str, Any]:
        """Append a trusted local manager's declaration, not independent verification.

        Fingerprints are optional audit snapshots, not checked attestations. This
        management method is not exposed through the public Agent tools.
        """
        if not isinstance(evidence_id, str):
            return error_response(INVALID_ARGUMENT, "evidence_id must be a string")
        if validity not in VALIDITIES:
            return error_response(
                INVALID_ARGUMENT,
                "validity must be one of: " + ", ".join(VALIDITIES),
            )
        if not isinstance(reason_code, str) or not reason_code.strip():
            return error_response(INVALID_ARGUMENT, "reason_code must be a non-empty string")
        if fingerprint is not None and not isinstance(fingerprint, dict):
            return error_response(INVALID_ARGUMENT, "fingerprint must be an object")
        for name, value in (
            ("invalidated_by", invalidated_by),
            ("superseded_by", superseded_by),
        ):
            if value is not None and not isinstance(value, str):
                return error_response(INVALID_ARGUMENT, f"{name} must be a string")
        if not self.evidence.evidence_exists(evidence_id):
            return error_response(INVALID_ARGUMENT, "evidence_id does not exist")
        if self.evidence.is_activity_only(evidence_id):
            return error_response(
                INVALID_ARGUMENT, "tool call activity is not assessable capability evidence"
            )
        assessment = self.evidence.assess(
            evidence_id,
            validity,
            reason_code.strip(),
            fingerprint=fingerprint,
            invalidated_by=invalidated_by,
            superseded_by=superseded_by,
        )
        return {"ok": True, "assessment": assessment}

    def evidence_validity(self, evidence_id: Any) -> dict[str, Any]:
        if not isinstance(evidence_id, str):
            return error_response(INVALID_ARGUMENT, "evidence_id must be a string")
        if not self.evidence.evidence_exists(evidence_id):
            return error_response(INVALID_ARGUMENT, "evidence_id does not exist")
        latest = self.evidence.latest_validity(evidence_id)
        result = {
            "ok": True,
            "evidence_id": evidence_id,
            "validity": latest,
            "assessed": latest is not None,
            "assessments": self.evidence.assessments(evidence_id),
        }
        if self.evidence.is_activity_only(evidence_id):
            result["assessable"] = False
        return result

    def expire_version_evidence(
        self,
        version_id: Any,
        reason_code: Any = "policy_or_environment_changed",
    ) -> dict[str, Any]:
        if not isinstance(version_id, str):
            return error_response(INVALID_ARGUMENT, "version_id must be a string")
        if not isinstance(reason_code, str) or not reason_code.strip():
            return error_response(INVALID_ARGUMENT, "reason_code must be a non-empty string")
        if self.registry.get_version(version_id) is None:
            return error_response(INVALID_ARGUMENT, "version_id does not exist")
        changed = self.evidence.invalidate_evidence_for_version(version_id, reason_code.strip())
        return {
            "ok": True,
            "version_id": version_id,
            "invalidated": changed,
            "reason_code": reason_code.strip(),
        }

    def expire_version_observations(
        self,
        version_id: Any,
        reason_code: Any = "policy_or_environment_changed",
    ) -> dict[str, Any]:
        if not isinstance(version_id, str):
            return error_response(INVALID_ARGUMENT, "version_id must be a string")
        if not isinstance(reason_code, str) or not reason_code.strip():
            return error_response(INVALID_ARGUMENT, "reason_code must be a non-empty string")
        if self.registry.get_version(version_id) is None:
            return error_response(INVALID_ARGUMENT, "version_id does not exist")
        changed = self.evidence.invalidate_observations_for_version(version_id, reason_code.strip())
        return {
            "ok": True,
            "version_id": version_id,
            "invalidated": changed,
            "reason_code": reason_code.strip(),
        }

    def record_observation(
        self,
        *,
        capability_id: Any,
        observation_type: Any,
        summary: Any,
        version_id: Any = None,
        evidence_ids: Any = None,
        applicability: Any = None,
        generation_method: Any = "human",
        confidence: Any = None,
    ) -> dict[str, Any]:
        if not isinstance(capability_id, str):
            return error_response(INVALID_ARGUMENT, "capability_id must be a string")
        if not isinstance(observation_type, str) or not observation_type.strip():
            return error_response(INVALID_ARGUMENT, "observation_type must be a non-empty string")
        if not isinstance(summary, str) or not summary.strip():
            return error_response(INVALID_ARGUMENT, "summary must be a non-empty string")
        if version_id is not None and not isinstance(version_id, str):
            return error_response(INVALID_ARGUMENT, "version_id must be a string")
        if generation_method not in OBSERVATION_METHODS:
            return error_response(
                INVALID_ARGUMENT,
                "generation_method must be one of: " + ", ".join(OBSERVATION_METHODS),
            )
        if applicability is not None and not isinstance(applicability, dict):
            return error_response(INVALID_ARGUMENT, "applicability must be an object")
        if confidence is not None and (
            isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0 <= float(confidence) <= 1
        ):
            return error_response(INVALID_ARGUMENT, "confidence must be between 0 and 1")

        capability = self.registry.get_capability(capability_id)
        if capability is None:
            return error_response(CAPABILITY_NOT_FOUND, "no capability matches that id")
        if version_id is not None:
            version = self.registry.get_version(version_id)
            if version is None or version["capability_id"] != capability_id:
                return error_response(
                    INVALID_ARGUMENT,
                    "version_id does not belong to that capability",
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

        observation = self.evidence.create_observation(
            capability_id=capability_id,
            version_id=version_id,
            observation_type=observation_type.strip(),
            summary=summary.strip()[:2000],
            evidence_ids=ids,
            applicability=applicability,
            generation_method=generation_method,
            confidence=float(confidence) if confidence is not None else None,
        )
        return {"ok": True, "observation": observation}

    def list_observations(
        self,
        *,
        capability_id: Any = None,
        version_id: Any = None,
        status: Any = None,
    ) -> dict[str, Any]:
        for name, value in (("capability_id", capability_id), ("version_id", version_id)):
            if value is not None and not isinstance(value, str):
                return error_response(INVALID_ARGUMENT, f"{name} must be a string")
        if status is not None and status not in OBSERVATION_STATUSES:
            return error_response(INVALID_ARGUMENT, "unsupported observation status")
        return {
            "ok": True,
            "observations": self.evidence.list_observations(
                capability_id=capability_id,
                version_id=version_id,
                status=status,
            ),
        }

    def set_observation_status(
        self,
        observation_id: Any,
        status: Any,
        reason: Any = None,
    ) -> dict[str, Any]:
        if not isinstance(observation_id, str):
            return error_response(INVALID_ARGUMENT, "observation_id must be a string")
        if status not in OBSERVATION_STATUSES:
            return error_response(INVALID_ARGUMENT, "unsupported observation status")
        if reason is not None and not isinstance(reason, str):
            return error_response(INVALID_ARGUMENT, "reason must be a string")
        observation = self.evidence.get_observation(observation_id)
        if observation is None:
            return error_response(INVALID_ARGUMENT, "observation_id does not exist")
        if observation["status"] == status:
            return {"ok": True, "observation": observation, "changed": False}
        self.evidence.set_observation_status(observation_id, status, reason)
        return {
            "ok": True,
            "observation": self.evidence.get_observation(observation_id),
            "changed": True,
        }

    def record_version_verification(
        self,
        *,
        version_id: Any,
        content_hash: Any,
        outcome: Any,
        source_type: Any,
        verification_ref: Any,
        verification: Any,
    ) -> dict[str, Any]:
        """Append version-bound evidence without changing lifecycle state."""
        try:
            with self.store.transaction(immediate=True):
                return self._record_version_verification(
                    version_id=version_id,
                    content_hash=content_hash,
                    outcome=outcome,
                    source_type=source_type,
                    verification_ref=verification_ref,
                    verification=verification,
                )
        except (sqlite3.Error, OSError):
            return error_response(
                SAVE_PERSISTENCE_FAILED, "version verification could not be durably recorded"
            )

    def _record_version_verification(
        self,
        *,
        version_id: Any,
        content_hash: Any,
        outcome: Any,
        source_type: Any,
        verification_ref: Any,
        verification: Any,
    ) -> dict[str, Any]:
        """Validate evidence under the same write lock as the event and assessment."""
        for name, value in (
            ("version_id", version_id),
            ("content_hash", content_hash),
            ("outcome", outcome),
            ("source_type", source_type),
            ("verification_ref", verification_ref),
        ):
            if not isinstance(value, str) or not value:
                return error_response(INVALID_ARGUMENT, f"{name} must be a non-empty string")
        if outcome not in VERIFICATION_OUTCOMES:
            return error_response(
                INVALID_ARGUMENT,
                "verification outcome must be passed, failed or unknown",
            )
        if source_type not in SOURCE_TYPES:
            return error_response(INVALID_ARGUMENT, "source_type is not recognized")
        if not isinstance(verification, dict):
            return error_response(INVALID_ARGUMENT, "verification must be an object")

        normalized = self._normalize_verification(verification)
        if normalized is None:
            return error_response(
                INVALID_ARGUMENT,
                "verification requires method, input_ref, artifact_ref and non-empty case_ids",
            )

        version = self.registry.get_version(version_id)
        if version is None:
            return error_response(CAPABILITY_NOT_FOUND, "that version does not exist")
        capability = self.registry.get_capability(version["capability_id"])
        if capability is not None and capability["archived_at"]:
            return error_response(CAPABILITY_ARCHIVED, "archived capabilities cannot be verified")
        if capability is not None and capability["quarantined_at"]:
            return error_response(
                CAPABILITY_QUARANTINED, "release the capability quarantine before verification"
            )
        if version["content_hash"] != content_hash:
            return error_response(
                INVALID_ARGUMENT,
                "content_hash does not match the version",
                reason_code=REASON_CONTENT_HASH_MISMATCH,
            )
        if version["status"] == STATUS_QUARANTINED:
            return error_response(
                CAPABILITY_QUARANTINED, "release the version quarantine before verification"
            )
        if version["status"] not in (STATUS_CANDIDATE, STATUS_READY):
            return error_response(
                INVALID_ARGUMENT,
                "verification requires a candidate or ready version",
            )

        event_id, duplicate = self.evidence.record_verification(
            capability_id=version["capability_id"],
            version_id=version_id,
            content_hash=content_hash,
            outcome=outcome,
            source_type=source_type,
            verification_ref=verification_ref,
            verification=normalized,
        )
        return {
            "ok": True,
            "version_id": version_id,
            "event_id": event_id,
            "duplicate": duplicate,
            "verification_outcome": outcome,
            "source_type": source_type,
        }

    @staticmethod
    def _normalize_verification(raw: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {
            "method",
            "input_ref",
            "artifact_ref",
            "artifact_hash",
            "verifier",
            "case_ids",
            "regression_case_ids",
            "notes",
        }
        if set(raw) - allowed:
            return None
        for key in ("method", "input_ref", "artifact_ref"):
            if not isinstance(raw.get(key), str) or not raw[key].strip():
                return None
        for key in ("artifact_hash", "verifier", "notes"):
            if key in raw and (not isinstance(raw[key], str) or not raw[key].strip()):
                return None
        case_ids = raw.get("case_ids")
        if (
            not isinstance(case_ids, list)
            or not case_ids
            or any(not isinstance(item, str) or not item.strip() for item in case_ids)
        ):
            return None
        regression_ids = raw.get("regression_case_ids")
        if regression_ids is not None and (
            not isinstance(regression_ids, list)
            or any(not isinstance(item, str) or not item.strip() for item in regression_ids)
        ):
            return None
        normalized = {
            "method": raw["method"].strip(),
            "input_ref": raw["input_ref"].strip(),
            "artifact_ref": raw["artifact_ref"].strip(),
            "case_ids": list(case_ids),
        }
        for key in ("artifact_hash", "verifier", "notes"):
            if key in raw:
                normalized[key] = raw[key].strip()
        if regression_ids is not None:
            normalized["regression_case_ids"] = list(regression_ids)
        return normalized

    def record_task_outcome(
        self,
        *,
        capability_id: Any,
        version_id: Any,
        invocation_id: Any,
        outcome: Any,
        source_type: Any,
        task_id: str | None = None,
        summary: str | None = None,
    ) -> dict[str, Any]:
        """Record a task-result signal together with its source (never inferred)."""
        if outcome not in OUTCOMES:
            return error_response(
                INVALID_ARGUMENT, "outcome must be success, failure, partial or unknown"
            )
        if source_type not in SOURCE_TYPES:
            return error_response(INVALID_ARGUMENT, "source_type is not recognized")
        for name, value in (
            ("capability_id", capability_id),
            ("version_id", version_id),
            ("invocation_id", invocation_id),
        ):
            if not isinstance(value, str) or not value:
                return error_response(INVALID_ARGUMENT, f"{name} must be a non-empty string")
        if task_id is not None and not isinstance(task_id, str):
            return error_response(INVALID_ARGUMENT, "task_id must be a string")
        if summary is not None and not isinstance(summary, str):
            return error_response(INVALID_ARGUMENT, "summary must be a string")

        capability = self.registry.get_capability(capability_id)
        if capability is None:
            return error_response(CAPABILITY_NOT_FOUND, "no capability matches that id")
        version = self.registry.get_version(version_id)
        if version is None or version["capability_id"] != capability_id:
            return error_response(INVALID_ARGUMENT, "version_id does not belong to that capability")
        invocation = self.store.db.execute(
            "SELECT capability_id, version_id, task_id FROM invocations WHERE invocation_id = ?",
            (invocation_id,),
        ).fetchone()
        if invocation is None:
            return error_response(INVALID_ARGUMENT, "invocation_id does not exist")
        if invocation["capability_id"] != capability_id or invocation["version_id"] != version_id:
            return error_response(
                INVALID_ARGUMENT, "invocation does not belong to that capability/version"
            )

        if invocation["task_id"] and task_id and invocation["task_id"] != task_id:
            return error_response(INVALID_ARGUMENT, "task_id conflicts with the invocation")
        try:
            event_id, duplicate = self.evidence.record_outcome(
                source_type=source_type,
                outcome=outcome,
                capability_id=capability_id,
                version_id=version_id,
                invocation_id=invocation_id,
                task_id=invocation["task_id"] or task_id or None,
                summary=(summary[:200] if summary else None),
                content_hash=version["content_hash"],
            )
        except (sqlite3.Error, OSError):
            return error_response(SAVE_PERSISTENCE_FAILED, "task outcome could not be persisted")
        return {
            "ok": True,
            "outcome": outcome,
            "source_type": source_type,
            "event_id": event_id,
            "duplicate": duplicate,
        }
