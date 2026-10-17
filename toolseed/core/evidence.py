"""Append-only evidence events and invocation records (P0-SLIM §6.3, §6.4, §7).

Delivery is recorded as a delivery, never as task success. Only an explicit
`task_outcome_signal` event may report a task outcome, and its source is
always stored alongside it.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .registry import new_id, now
from .storage import Store

OUTCOMES = ("success", "failure", "partial", "unknown")
SOURCE_TYPES = ("core", "agent", "harness", "test_runner", "external_system", "human")
VALIDITIES = ("valid", "stale", "superseded")
OBSERVATION_METHODS = ("rule", "model", "human")
OBSERVATION_STATUSES = ("active", "stale", "retracted")
FAILURE_CATEGORIES = (
    "retrieval_mismatch",
    "applicability_mismatch",
    "contract_error",
    "procedure_ambiguity",
    "implementation_error",
    "dependency_or_runtime_error",
    "permission_denied",
    "timeout_or_resource_limit",
    "output_protocol_error",
    "workflow_child_failure",
    "security_or_integrity_violation",
    "task_outcome_unknown",
    "task_failure_attributed",
    "external_environment_failure",
)

EVENT_PROCEDURE_SAVED = "procedure_saved"
EVENT_SEARCH = "search_performed"
EVENT_DELIVERED = "procedure_delivered"
EVENT_TASK_OUTCOME = "task_outcome_signal"
EVENT_QUARANTINED = "capability_quarantined"
EVENT_RELEASED = "capability_released"
EVENT_ARCHIVED = "capability_archived"
EVENT_VERSION_RELEASED = "version_released"
EVENT_VERSION_PROMOTED = "version_promoted"
EVENT_VERSION_ROLLED_BACK = "version_rolled_back"
EVENT_DUPLICATE = "duplicate_save"


class Evidence:
    def __init__(self, store: Store) -> None:
        self.store = store

    def record(
        self,
        event_type: str,
        *,
        source_type: str = "core",
        outcome: str = "unknown",
        capability_id: str | None = None,
        version_id: str | None = None,
        invocation_id: str | None = None,
        task_id: str | None = None,
        quantity: int = 0,
        summary: str | None = None,
    ) -> str:
        if outcome not in OUTCOMES:
            raise ValueError(f"unsupported outcome: {outcome}")
        if source_type not in SOURCE_TYPES:
            raise ValueError(f"unsupported source_type: {source_type}")
        event_id = new_id("ev")
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO evidence_events (event_id, event_type, created_at, source_type, "
                "capability_id, version_id, invocation_id, task_id, outcome, quantity, summary) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id,
                    event_type,
                    now(),
                    source_type,
                    capability_id,
                    version_id,
                    invocation_id,
                    task_id,
                    outcome,
                    int(quantity),
                    summary,
                ),
            )
        return event_id

    def record_invocation(
        self,
        capability_id: str,
        version_id: str,
        *,
        context: dict[str, Any] | None = None,
        task_id: str | None = None,
        delivery_status: str = "guidance_delivered",
    ) -> str:
        invocation_id = new_id("inv")
        safe_context = {}
        if isinstance(context, dict):
            for key in ("task_id", "session_id", "harness", "workspace"):
                value = context.get(key)
                if isinstance(value, str) and value:
                    safe_context[key] = value
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO invocations (invocation_id, capability_id, version_id, created_at, "
                "context_json, delivery_status, task_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    invocation_id,
                    capability_id,
                    version_id,
                    now(),
                    json.dumps(safe_context, ensure_ascii=False) if safe_context else None,
                    delivery_status,
                    task_id,
                ),
            )
        return invocation_id

    def event_counts(self) -> dict[str, int]:
        return {
            row["event_type"]: int(row["n"])
            for row in self.store.db.execute(
                "SELECT event_type, COUNT(*) AS n FROM evidence_events GROUP BY event_type"
            )
        }

    def quantity_sum(self, event_type: str) -> int:
        row = self.store.db.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS n FROM evidence_events WHERE event_type = ?",
            (event_type,),
        ).fetchone()
        return int(row["n"] or 0)

    def outcome_counts(self) -> dict[str, int]:
        counts = {outcome: 0 for outcome in OUTCOMES}
        for row in self.store.db.execute(
            "SELECT outcome, COUNT(*) AS n FROM evidence_events WHERE event_type = ? GROUP BY outcome",
            (EVENT_TASK_OUTCOME,),
        ).fetchall():
            counts[row["outcome"]] = int(row["n"])
        return counts

    def total_events(self) -> int:
        return int(
            self.store.db.execute("SELECT COUNT(*) AS n FROM evidence_events").fetchone()["n"]
        )

    # -- evidence validity (P1) ------------------------------------------
    def evidence_exists(self, evidence_id: str) -> bool:
        row = self.store.db.execute(
            "SELECT 1 FROM evidence_events WHERE event_id = ?", (evidence_id,)
        ).fetchone()
        return row is not None

    def assess(
        self,
        evidence_id: str,
        validity: str,
        reason_code: str,
        *,
        fingerprint: dict[str, Any] | None = None,
        invalidated_by: str | None = None,
        superseded_by: str | None = None,
    ) -> dict[str, Any]:
        if validity not in VALIDITIES:
            raise ValueError(f"unsupported validity: {validity}")
        assessment_id = new_id("eva")
        assessed_at = now()
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO evidence_validity_assessments "
                "(assessment_id, evidence_id, validity, reason_code, fingerprint_json, "
                "assessed_at, invalidated_by, superseded_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    assessment_id,
                    evidence_id,
                    validity,
                    reason_code,
                    json.dumps(fingerprint, ensure_ascii=False, sort_keys=True)
                    if fingerprint is not None
                    else None,
                    assessed_at,
                    invalidated_by,
                    superseded_by,
                ),
            )
        return {
            "assessment_id": assessment_id,
            "evidence_id": evidence_id,
            "validity": validity,
            "reason_code": reason_code,
            "fingerprint": fingerprint,
            "assessed_at": assessed_at,
            "invalidated_by": invalidated_by,
            "superseded_by": superseded_by,
        }

    def latest_validity(self, evidence_id: str) -> str | None:
        latest = self.latest_assessment(evidence_id)
        return latest["validity"] if latest is not None else None

    def latest_assessment(self, evidence_id: str) -> dict[str, Any] | None:
        row = self.store.db.execute(
            "SELECT * FROM evidence_validity_assessments "
            "WHERE evidence_id = ? ORDER BY assessed_at DESC, rowid DESC LIMIT 1",
            (evidence_id,),
        ).fetchone()
        return self._assessment_dict(row) if row is not None else None

    def assessments(self, evidence_id: str) -> list[dict[str, Any]]:
        rows = self.store.db.execute(
            "SELECT * FROM evidence_validity_assessments "
            "WHERE evidence_id = ? ORDER BY assessed_at, rowid",
            (evidence_id,),
        ).fetchall()
        return [self._assessment_dict(row) for row in rows]

    def assessment_count(self) -> int:
        return int(
            self.store.db.execute(
                "SELECT COUNT(*) AS n FROM evidence_validity_assessments"
            ).fetchone()["n"]
        )

    def validity_counts(self) -> dict[str, int]:
        counts = {validity: 0 for validity in VALIDITIES}
        rows = self.store.db.execute(
            "SELECT a.validity AS validity, COUNT(*) AS n "
            "FROM evidence_validity_assessments a "
            "JOIN (SELECT evidence_id, MAX(rowid) AS max_id "
            "      FROM evidence_validity_assessments GROUP BY evidence_id) latest "
            "  ON a.rowid = latest.max_id "
            "GROUP BY a.validity"
        ).fetchall()
        for row in rows:
            counts[row["validity"]] = int(row["n"])
        assessed = sum(counts.values())
        counts["unassessed"] = max(0, self.total_events() - assessed)
        return counts

    def version_fingerprint(self, version_id: str) -> dict[str, Any] | None:
        row = self.store.db.execute(
            "SELECT version_id, version_number, content_hash, manifest_json "
            "FROM capability_versions WHERE version_id = ?",
            (version_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "version_id": row["version_id"],
            "version_number": int(row["version_number"]),
            "content_hash": row["content_hash"],
            "manifest_hash": hashlib.sha256(
                row["manifest_json"].encode("utf-8")
            ).hexdigest(),
        }

    def invalidate_evidence_for_version(
        self,
        version_id: str,
        reason_code: str = "version_quarantined",
    ) -> int:
        """Append stale assessments for evidence tied to a version.

        Raw evidence is never rewritten; this only appends the current
        validity projection.
        """
        fingerprint = self.version_fingerprint(version_id)
        if fingerprint is None:
            return 0
        rows = self.store.db.execute(
            "SELECT event_id FROM evidence_events WHERE version_id = ? ORDER BY rowid",
            (version_id,),
        ).fetchall()
        changed = 0
        for row in rows:
            latest = self.latest_assessment(row["event_id"])
            if latest is not None and latest["validity"] in ("stale", "superseded"):
                continue
            self.assess(
                row["event_id"],
                "stale",
                reason_code,
                fingerprint=fingerprint,
                invalidated_by=version_id,
            )
            changed += 1
        return changed

    def maintenance_report(self, failure_threshold: int = 2) -> dict[str, Any]:
        validity = self.validity_counts()
        repeated = [
            {
                "capability_id": row["capability_id"],
                "version_id": row["version_id"],
                "failures": int(row["n"]),
                "suggested_category": "task_failure_attributed",
            }
            for row in self.store.db.execute(
                "SELECT capability_id, version_id, COUNT(*) AS n "
                "FROM evidence_events "
                "WHERE event_type = ? AND outcome = 'failure' AND version_id IS NOT NULL "
                "GROUP BY capability_id, version_id HAVING COUNT(*) >= ? "
                "ORDER BY n DESC",
                (EVENT_TASK_OUTCOME, failure_threshold),
            ).fetchall()
        ]

        suggestions: list[dict[str, Any]] = []
        if validity["unassessed"] > 0:
            suggestions.append(
                {
                    "action": "assess_evidence",
                    "reason": "unassessed_evidence",
                    "count": validity["unassessed"],
                }
            )
        if validity["stale"] > 0:
            suggestions.append(
                {
                    "action": "revalidate_evidence",
                    "reason": "stale_evidence",
                    "count": validity["stale"],
                }
            )
        for item in repeated:
            suggestions.append(
                {
                    "action": "diagnose_failure",
                    "reason": "repeated_failures",
                    "capability_id": item["capability_id"],
                    "version_id": item["version_id"],
                    "failures": item["failures"],
                    "suggested_category": item["suggested_category"],
                }
            )

        counts = self.diagnosis_counts()
        if counts["open"] > 0:
            suggestions.append(
                {
                    "action": "review_diagnosis",
                    "reason": "open_diagnoses",
                    "count": counts["open"],
                }
            )

        return {
            "validity": validity,
            "repeated_failures": repeated,
            "open_diagnoses": counts["open"],
            "suggestions": suggestions,
        }

    # -- failure diagnosis and repair candidates (P1) --------------------
    def create_diagnosis(
        self,
        *,
        capability_id: str,
        version_id: str,
        category: str,
        summary: str,
        invocation_id: str | None = None,
        task_id: str | None = None,
        evidence_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        diagnosis_id = new_id("diag")
        stamp = now()
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO failure_diagnoses "
                "(diagnosis_id, capability_id, version_id, invocation_id, task_id, "
                "category, summary, evidence_ids_json, status, repair_version_id, "
                "created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', NULL, ?, ?)",
                (
                    diagnosis_id,
                    capability_id,
                    version_id,
                    invocation_id,
                    task_id,
                    category,
                    summary,
                    json.dumps(evidence_ids or [], ensure_ascii=False),
                    stamp,
                    stamp,
                ),
            )
        return self.get_diagnosis(diagnosis_id)  # type: ignore[return-value]

    def get_diagnosis(self, diagnosis_id: str) -> dict[str, Any] | None:
        row = self.store.db.execute(
            "SELECT * FROM failure_diagnoses WHERE diagnosis_id = ?", (diagnosis_id,)
        ).fetchone()
        return self._diagnosis_dict(row) if row is not None else None

    def list_diagnoses(
        self,
        *,
        capability_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM failure_diagnoses WHERE 1 = 1"
        params: list[Any] = []
        if capability_id is not None:
            query += " AND capability_id = ?"
            params.append(capability_id)
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at, rowid"
        rows = self.store.db.execute(query, params).fetchall()
        return [self._diagnosis_dict(row) for row in rows]

    def mark_repair_proposed(self, diagnosis_id: str, version_id: str) -> None:
        with self.store.transaction() as db:
            db.execute(
                "UPDATE failure_diagnoses SET status = 'repair_proposed', "
                "repair_version_id = ?, updated_at = ? WHERE diagnosis_id = ?",
                (version_id, now(), diagnosis_id),
            )

    def dismiss_diagnosis(self, diagnosis_id: str) -> None:
        with self.store.transaction() as db:
            db.execute(
                "UPDATE failure_diagnoses SET status = 'dismissed', updated_at = ? "
                "WHERE diagnosis_id = ?",
                (now(), diagnosis_id),
            )

    def diagnosis_counts(self) -> dict[str, int]:
        counts = {"open": 0, "repair_proposed": 0, "dismissed": 0}
        for row in self.store.db.execute(
            "SELECT status, COUNT(*) AS n FROM failure_diagnoses GROUP BY status"
        ).fetchall():
            counts[row["status"]] = int(row["n"])
        return counts

    # -- evolution decisions (P1 maintenance) ----------------------------
    def create_decision(
        self,
        *,
        action: str,
        reason: str,
        dedup_key: str,
        capability_id: str | None = None,
        version_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        existing = self.get_decision_by_dedup(dedup_key)
        if existing is not None:
            return existing, False
        decision_id = new_id("dec")
        stamp = now()
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO evolution_decisions "
                "(decision_id, dedup_key, action, reason, capability_id, version_id, "
                "status, payload_json, resolution, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'proposed', ?, NULL, ?, ?)",
                (
                    decision_id,
                    dedup_key,
                    action,
                    reason,
                    capability_id,
                    version_id,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True)
                    if payload is not None
                    else None,
                    stamp,
                    stamp,
                ),
            )
        return self.get_decision(decision_id), True  # type: ignore[return-value]

    def get_decision(self, decision_id: str) -> dict[str, Any] | None:
        row = self.store.db.execute(
            "SELECT * FROM evolution_decisions WHERE decision_id = ?", (decision_id,)
        ).fetchone()
        return self._decision_dict(row) if row is not None else None

    def get_decision_by_dedup(self, dedup_key: str) -> dict[str, Any] | None:
        row = self.store.db.execute(
            "SELECT * FROM evolution_decisions WHERE dedup_key = ?", (dedup_key,)
        ).fetchone()
        return self._decision_dict(row) if row is not None else None

    def list_decisions(
        self,
        *,
        status: str | None = None,
        capability_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM evolution_decisions WHERE 1 = 1"
        params: list[Any] = []
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        if capability_id is not None:
            query += " AND capability_id = ?"
            params.append(capability_id)
        query += " ORDER BY created_at, rowid"
        rows = self.store.db.execute(query, params).fetchall()
        return [self._decision_dict(row) for row in rows]

    def dismiss_decision(self, decision_id: str, resolution: str | None = None) -> None:
        with self.store.transaction() as db:
            db.execute(
                "UPDATE evolution_decisions SET status = 'dismissed', resolution = ?, "
                "updated_at = ? WHERE decision_id = ?",
                (resolution, now(), decision_id),
            )

    def decision_counts(self) -> dict[str, int]:
        counts = {"proposed": 0, "applied": 0, "dismissed": 0}
        for row in self.store.db.execute(
            "SELECT status, COUNT(*) AS n FROM evolution_decisions GROUP BY status"
        ).fetchall():
            counts[row["status"]] = int(row["n"])
        return counts

    # -- capability observations (P1) ------------------------------------
    def create_observation(
        self,
        *,
        capability_id: str,
        observation_type: str,
        summary: str,
        version_id: str | None = None,
        evidence_ids: list[str] | None = None,
        applicability: dict[str, Any] | None = None,
        generation_method: str = "human",
        confidence: float | None = None,
    ) -> dict[str, Any]:
        observation_id = new_id("obs")
        stamp = now()
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO capability_observations "
                "(observation_id, capability_id, version_id, evidence_ids_json, "
                "observation_type, applicability_json, generation_method, status, "
                "confidence, summary, status_reason, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, NULL, ?, ?)",
                (
                    observation_id,
                    capability_id,
                    version_id,
                    json.dumps(evidence_ids or [], ensure_ascii=False),
                    observation_type,
                    json.dumps(applicability, ensure_ascii=False, sort_keys=True)
                    if applicability is not None
                    else None,
                    generation_method,
                    confidence,
                    summary,
                    stamp,
                    stamp,
                ),
            )
        return self.get_observation(observation_id)  # type: ignore[return-value]

    def get_observation(self, observation_id: str) -> dict[str, Any] | None:
        row = self.store.db.execute(
            "SELECT * FROM capability_observations WHERE observation_id = ?",
            (observation_id,),
        ).fetchone()
        return self._observation_dict(row) if row is not None else None

    def list_observations(
        self,
        *,
        capability_id: str | None = None,
        version_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM capability_observations WHERE 1 = 1"
        params: list[Any] = []
        if capability_id is not None:
            query += " AND capability_id = ?"
            params.append(capability_id)
        if version_id is not None:
            query += " AND version_id = ?"
            params.append(version_id)
        if status is not None:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY created_at, rowid"
        rows = self.store.db.execute(query, params).fetchall()
        return [self._observation_dict(row) for row in rows]

    def set_observation_status(
        self,
        observation_id: str,
        status: str,
        reason: str | None = None,
    ) -> None:
        with self.store.transaction() as db:
            db.execute(
                "UPDATE capability_observations SET status = ?, status_reason = ?, "
                "updated_at = ? WHERE observation_id = ?",
                (status, reason, now(), observation_id),
            )

    def observation_counts(self) -> dict[str, int]:
        counts = {"active": 0, "stale": 0, "retracted": 0}
        for row in self.store.db.execute(
            "SELECT status, COUNT(*) AS n FROM capability_observations GROUP BY status"
        ).fetchall():
            counts[row["status"]] = int(row["n"])
        return counts

    def version_stats(self, version_id: str) -> dict[str, Any] | None:
        version = self.store.db.execute(
            "SELECT version_id, capability_id, version_number, content_hash, status "
            "FROM capability_versions WHERE version_id = ?",
            (version_id,),
        ).fetchone()
        if version is None:
            return None

        deliveries = int(
            self.store.db.execute(
                "SELECT COUNT(*) AS n FROM invocations WHERE version_id = ?",
                (version_id,),
            ).fetchone()["n"]
        )
        outcomes = {outcome: 0 for outcome in OUTCOMES}
        for row in self.store.db.execute(
            "SELECT outcome, COUNT(*) AS n FROM evidence_events "
            "WHERE event_type = ? AND version_id = ? GROUP BY outcome",
            (EVENT_TASK_OUTCOME, version_id),
        ).fetchall():
            outcomes[row["outcome"]] = int(row["n"])

        diagnoses = {"open": 0, "repair_proposed": 0, "dismissed": 0}
        for row in self.store.db.execute(
            "SELECT status, COUNT(*) AS n FROM failure_diagnoses "
            "WHERE version_id = ? GROUP BY status",
            (version_id,),
        ).fetchall():
            diagnoses[row["status"]] = int(row["n"])

        observations = {"active": 0, "stale": 0, "retracted": 0}
        for row in self.store.db.execute(
            "SELECT status, COUNT(*) AS n FROM capability_observations "
            "WHERE version_id = ? GROUP BY status",
            (version_id,),
        ).fetchall():
            observations[row["status"]] = int(row["n"])

        validity = {validity: 0 for validity in VALIDITIES}
        validity["unassessed"] = 0
        for row in self.store.db.execute(
            "SELECT event_id FROM evidence_events WHERE version_id = ?", (version_id,)
        ).fetchall():
            latest = self.latest_assessment(row["event_id"])
            if latest is None:
                validity["unassessed"] += 1
            else:
                validity[latest["validity"]] += 1

        rollbacks = int(
            self.store.db.execute(
                "SELECT COUNT(*) AS n FROM evidence_events "
                "WHERE event_type = ? AND version_id = ?",
                (EVENT_VERSION_ROLLED_BACK, version_id),
            ).fetchone()["n"]
        )

        return {
            "version_id": version["version_id"],
            "capability_id": version["capability_id"],
            "version_number": int(version["version_number"]),
            "content_hash": version["content_hash"],
            "status": version["status"],
            "deliveries": deliveries,
            "task_outcomes": outcomes,
            "diagnoses": diagnoses,
            "observations": observations,
            "evidence_validity": validity,
            "rollbacks": rollbacks,
        }

    @staticmethod
    def _observation_dict(row: Any) -> dict[str, Any]:
        return {
            "observation_id": row["observation_id"],
            "capability_id": row["capability_id"],
            "version_id": row["version_id"],
            "evidence_ids": json.loads(row["evidence_ids_json"] or "[]"),
            "observation_type": row["observation_type"],
            "applicability": json.loads(row["applicability_json"])
            if row["applicability_json"]
            else None,
            "generation_method": row["generation_method"],
            "status": row["status"],
            "confidence": row["confidence"],
            "summary": row["summary"],
            "status_reason": row["status_reason"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _decision_dict(row: Any) -> dict[str, Any]:
        return {
            "decision_id": row["decision_id"],
            "dedup_key": row["dedup_key"],
            "action": row["action"],
            "reason": row["reason"],
            "capability_id": row["capability_id"],
            "version_id": row["version_id"],
            "status": row["status"],
            "payload": json.loads(row["payload_json"]) if row["payload_json"] else None,
            "resolution": row["resolution"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _assessment_dict(row: Any) -> dict[str, Any]:
        return {
            "assessment_id": row["assessment_id"],
            "evidence_id": row["evidence_id"],
            "validity": row["validity"],
            "reason_code": row["reason_code"],
            "fingerprint": json.loads(row["fingerprint_json"])
            if row["fingerprint_json"]
            else None,
            "assessed_at": row["assessed_at"],
            "invalidated_by": row["invalidated_by"],
            "superseded_by": row["superseded_by"],
        }

    @staticmethod
    def _diagnosis_dict(row: Any) -> dict[str, Any]:
        return {
            "diagnosis_id": row["diagnosis_id"],
            "capability_id": row["capability_id"],
            "version_id": row["version_id"],
            "invocation_id": row["invocation_id"],
            "task_id": row["task_id"],
            "category": row["category"],
            "summary": row["summary"],
            "evidence_ids": json.loads(row["evidence_ids_json"] or "[]"),
            "status": row["status"],
            "repair_version_id": row["repair_version_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
