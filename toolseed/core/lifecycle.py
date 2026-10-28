"""The single owner of capability lifecycle gates and version activation."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .errors import (
    CAPABILITY_ARCHIVED,
    CAPABILITY_NOT_FOUND,
    CAPABILITY_NOT_READY,
    CAPABILITY_QUARANTINED,
    INVALID_ARGUMENT,
    POLICY_BLOCKED,
    SAVE_PERSISTENCE_FAILED,
    error_response,
)
from .evidence import (
    EVENT_ARCHIVED,
    EVENT_QUARANTINED,
    EVENT_RELEASED,
    EVENT_VERSION_PROMOTED,
    EVENT_VERSION_RELEASED,
    EVENT_VERSION_ROLLED_BACK,
    EVENT_VERSION_VERIFICATION,
    INDEPENDENT_SOURCE_TYPES,
    Evidence,
)
from .knowledge import (
    scan_version,
)
from .registry import STATUS_CANDIDATE, STATUS_QUARANTINED, STATUS_READY, Registry
from .service_support import (
    REASON_CONTENT_HASH_MISMATCH,
    REASON_CURRENT_CONFLICT,
    REASON_REGRESSION_MISSING,
    REASON_VERIFICATION_INVALID,
    REASON_VERIFICATION_MISSING,
    REASON_VERSION_NOT_CANDIDATE,
    _CandidateRejected,
)
from .storage import Store


class LifecycleService:
    def __init__(self, store: Store, registry: Registry, evidence: Evidence) -> None:
        self.store = store
        self.registry = registry
        self.evidence = evidence

    def quarantine(self, capability_id: Any, reason: str = "manual quarantine") -> dict[str, Any]:
        if not isinstance(capability_id, str):
            return error_response(INVALID_ARGUMENT, "capability_id must be a string")
        capability = self.registry.get_capability(capability_id)
        if capability is None:
            return error_response(CAPABILITY_NOT_FOUND, "no capability matches that id")
        try:
            with self.store.transaction():
                self.registry.quarantine_capability(capability_id)
                invalidated = sum(
                    self.evidence.invalidate_evidence_for_version(
                        version["version_id"], "capability_quarantined"
                    )
                    for version in self.registry.list_versions(capability_id)
                )
                observations_invalidated = self.evidence.invalidate_observations_for_capability(
                    capability_id, "capability_quarantined"
                )
                self.evidence.record(
                    EVENT_QUARANTINED,
                    capability_id=capability_id,
                    summary=str(reason)[:200],
                )
        except (sqlite3.Error, OSError):
            return error_response(
                SAVE_PERSISTENCE_FAILED, "quarantine could not be durably recorded"
            )
        return {
            "ok": True,
            "capability_id": capability_id,
            "quarantined": True,
            "evidence_invalidated": invalidated,
            "observations_invalidated": observations_invalidated,
        }

    def quarantine_version(
        self, version_id: Any, reason: str = "manual quarantine"
    ) -> dict[str, Any]:
        if not isinstance(version_id, str):
            return error_response(INVALID_ARGUMENT, "version_id must be a string")
        try:
            with self.store.transaction():
                version = self.registry.quarantine_version(version_id)
                if version is None:
                    raise _CandidateRejected(
                        error_response(CAPABILITY_NOT_FOUND, "that version does not exist")
                    )
                self.evidence.record(
                    EVENT_QUARANTINED,
                    capability_id=version["capability_id"],
                    version_id=version_id,
                    summary=str(reason)[:200],
                )
                invalidated = self.evidence.invalidate_evidence_for_version(
                    version_id, "version_quarantined"
                )
                observations_invalidated = self.evidence.invalidate_observations_for_version(
                    version_id, "version_quarantined"
                )
        except _CandidateRejected as exc:
            return exc.response
        except (sqlite3.Error, OSError):
            return error_response(
                SAVE_PERSISTENCE_FAILED, "quarantine could not be durably recorded"
            )
        return {
            "ok": True,
            "version_id": version_id,
            "status": STATUS_QUARANTINED,
            "evidence_invalidated": invalidated,
            "observations_invalidated": observations_invalidated,
        }

    def release_capability(
        self,
        capability_id: Any,
        reason: str,
        evidence_ref: str | None = None,
    ) -> dict[str, Any]:
        """Lift a whole-capability quarantine after explicit review.

        Archival is permanent and is not undone here. The reason and optional
        evidence reference are recorded as an append-only audit event.
        """
        if not isinstance(capability_id, str):
            return error_response(INVALID_ARGUMENT, "capability_id must be a string")
        if not isinstance(reason, str) or not reason.strip():
            return error_response(INVALID_ARGUMENT, "release reason must be a non-empty string")
        if evidence_ref is not None and not isinstance(evidence_ref, str):
            return error_response(INVALID_ARGUMENT, "evidence_ref must be a string")
        capability = self.registry.get_capability(capability_id)
        if capability is None:
            return error_response(CAPABILITY_NOT_FOUND, "no capability matches that id")
        if capability["archived_at"]:
            return error_response(CAPABILITY_ARCHIVED, "archived capabilities cannot be released")
        if not capability["quarantined_at"]:
            return {
                "ok": True,
                "capability_id": capability_id,
                "released": False,
                "note": "capability was not quarantined",
            }
        summary = f"release: {reason.strip()[:200]}"
        if evidence_ref and evidence_ref.strip():
            summary += f" | evidence: {evidence_ref.strip()[:200]}"
        try:
            with self.store.transaction():
                self.registry.release_capability(capability_id)
                self.evidence.record(
                    EVENT_RELEASED,
                    capability_id=capability_id,
                    summary=summary[:400],
                )
        except (sqlite3.Error, OSError):
            return error_response(SAVE_PERSISTENCE_FAILED, "release could not be durably recorded")
        return {"ok": True, "capability_id": capability_id, "released": True}

    def release_version(
        self,
        version_id: Any,
        reason: str,
        evidence_ref: str | None = None,
    ) -> dict[str, Any]:
        """Release a quarantined version back to candidate (still not deliverable)."""
        if not isinstance(version_id, str):
            return error_response(INVALID_ARGUMENT, "version_id must be a string")
        if not isinstance(reason, str) or not reason.strip():
            return error_response(INVALID_ARGUMENT, "release reason must be a non-empty string")
        if evidence_ref is not None and not isinstance(evidence_ref, str):
            return error_response(INVALID_ARGUMENT, "evidence_ref must be a string")
        version = self.registry.get_version(version_id)
        if version is None:
            return error_response(CAPABILITY_NOT_FOUND, "that version does not exist")
        capability = self.registry.get_capability(version["capability_id"])
        if capability is not None and capability["archived_at"]:
            return error_response(CAPABILITY_ARCHIVED, "archived capabilities cannot be released")
        if version["status"] != STATUS_QUARANTINED:
            return {
                "ok": True,
                "version_id": version_id,
                "released": False,
                "status": version["status"],
                "note": "version was not quarantined",
            }
        summary = f"version release: {reason.strip()[:200]}"
        if evidence_ref and evidence_ref.strip():
            summary += f" | evidence: {evidence_ref.strip()[:200]}"
        try:
            with self.store.transaction():
                self.registry.release_version(version_id)
                self.evidence.record(
                    EVENT_VERSION_RELEASED,
                    capability_id=version["capability_id"],
                    version_id=version_id,
                    summary=summary[:400],
                )
        except (sqlite3.Error, OSError):
            return error_response(
                SAVE_PERSISTENCE_FAILED, "version release could not be durably recorded"
            )
        return {
            "ok": True,
            "version_id": version_id,
            "status": STATUS_CANDIDATE,
            "released": True,
        }

    def promote_version(
        self,
        version_id: Any,
        reason: str,
        evidence_ref: str | None = None,
    ) -> dict[str, Any]:
        """Promote a candidate only if valid independent verification is bound to it."""
        if not isinstance(version_id, str):
            return error_response(INVALID_ARGUMENT, "version_id must be a string")
        if not isinstance(reason, str) or not reason.strip():
            return error_response(INVALID_ARGUMENT, "promotion reason must be a non-empty string")
        if evidence_ref is not None and not isinstance(evidence_ref, str):
            return error_response(INVALID_ARGUMENT, "evidence_ref must be a string")

        try:
            with self.store.transaction(immediate=True) as db:
                version = db.execute(
                    "SELECT * FROM capability_versions WHERE version_id = ?", (version_id,)
                ).fetchone()
                if version is None:
                    return error_response(CAPABILITY_NOT_FOUND, "that version does not exist")
                capability = db.execute(
                    "SELECT * FROM capabilities WHERE capability_id = ?",
                    (version["capability_id"],),
                ).fetchone()
                if capability is not None and capability["archived_at"]:
                    return error_response(
                        CAPABILITY_ARCHIVED, "archived capabilities cannot be promoted"
                    )
                if capability is not None and capability["quarantined_at"]:
                    return error_response(
                        CAPABILITY_QUARANTINED,
                        "release the capability quarantine before promotion",
                    )
                if version["status"] == STATUS_READY:
                    return {
                        "ok": True,
                        "version_id": version_id,
                        "promoted": False,
                        "status": STATUS_READY,
                        "note": "version is already ready",
                    }
                if version["status"] == STATUS_QUARANTINED:
                    return error_response(
                        CAPABILITY_QUARANTINED,
                        "release the version quarantine before promotion",
                    )
                if version["status"] != STATUS_CANDIDATE:
                    return error_response(
                        INVALID_ARGUMENT,
                        "only a candidate version can be promoted",
                        reason_code=REASON_VERSION_NOT_CANDIDATE,
                    )

                verdict, _reasons = scan_version(version, for_promotion=True)
                if verdict is not None:
                    return error_response(
                        POLICY_BLOCKED,
                        "candidate still triggers the content review gate; edit it and save a new version",
                    )

                verification = db.execute(
                    "SELECT * FROM evidence_events "
                    "WHERE event_type = ? AND version_id = ? "
                    "ORDER BY rowid DESC LIMIT 1",
                    (EVENT_VERSION_VERIFICATION, version_id),
                ).fetchone()
                if verification is None:
                    return error_response(
                        INVALID_ARGUMENT,
                        "candidate has no version verification evidence",
                        reason_code=REASON_VERIFICATION_MISSING,
                    )
                if verification["content_hash"] != version["content_hash"]:
                    return error_response(
                        INVALID_ARGUMENT,
                        "verification evidence is bound to a different content hash",
                        reason_code=REASON_CONTENT_HASH_MISMATCH,
                    )
                # Creation order is established structurally at write time, not by the
                # clock: record_version_verification resolves this exact version row
                # before inserting anything, so an event carrying this version_id
                # cannot predate the version it verifies. Ready versions also accept
                # subsequent evidence without changing their lifecycle state.
                # Re-deriving that from `created_at` compared the wall clock
                # against itself, which is not monotonic at the resolution the timestamp
                # is written with -- on Windows/CPython 3.11 consecutive
                # datetime.now(UTC) calls collide, so a valid verification could share
                # the version's exact created_at and be rejected. `created_at` is kept
                # as audit information only.
                if verification["source_type"] not in INDEPENDENT_SOURCE_TYPES:
                    return error_response(
                        INVALID_ARGUMENT,
                        "verification evidence source is not independent",
                        reason_code=REASON_VERIFICATION_INVALID,
                    )
                if verification["verification_outcome"] != "passed":
                    return error_response(
                        INVALID_ARGUMENT,
                        "verification evidence did not pass",
                        reason_code=REASON_VERIFICATION_INVALID,
                    )
                assessment = self.evidence.latest_validity(verification["event_id"])
                if assessment != "valid":
                    return error_response(
                        INVALID_ARGUMENT,
                        "verification evidence is not currently valid",
                        reason_code=REASON_VERIFICATION_INVALID,
                    )
                try:
                    verification_payload = json.loads(verification["verification_json"] or "{}")
                except (TypeError, ValueError):
                    verification_payload = None
                if not isinstance(verification_payload, dict) or not verification_payload.get(
                    "case_ids"
                ):
                    return error_response(
                        INVALID_ARGUMENT,
                        "verification evidence has no reproducible case reference",
                        reason_code=REASON_VERIFICATION_INVALID,
                    )
                if int(version["version_number"]) > 1 and not verification_payload.get(
                    "regression_case_ids"
                ):
                    return error_response(
                        INVALID_ARGUMENT,
                        "revision verification has no regression case reference",
                        reason_code=REASON_REGRESSION_MISSING,
                    )

                highest_ready = db.execute(
                    "SELECT MAX(version_number) AS n FROM capability_versions "
                    "WHERE capability_id = ? AND status = ?",
                    (version["capability_id"], STATUS_READY),
                ).fetchone()
                highest = highest_ready["n"] if highest_ready is not None else None
                if highest is not None and int(highest) > int(version["version_number"]):
                    return error_response(
                        INVALID_ARGUMENT,
                        "a newer ready version already exists; this candidate cannot become current",
                        reason_code=REASON_CURRENT_CONFLICT,
                    )

                cursor = db.execute(
                    "UPDATE capability_versions SET status = ? WHERE version_id = ? AND status = ?",
                    (STATUS_READY, version_id, STATUS_CANDIDATE),
                )
                if cursor.rowcount != 1:
                    return error_response(
                        INVALID_ARGUMENT,
                        "candidate state changed during promotion",
                        reason_code=REASON_CURRENT_CONFLICT,
                    )
                db.execute(
                    "UPDATE capabilities SET current_version_id = ? WHERE capability_id = ?",
                    (version_id, version["capability_id"]),
                )

                summary = f"version promotion: {reason.strip()[:200]}"
                if evidence_ref and evidence_ref.strip():
                    summary += f" | evidence: {evidence_ref.strip()[:200]}"
                self.evidence.record(
                    EVENT_VERSION_PROMOTED,
                    capability_id=version["capability_id"],
                    version_id=version_id,
                    summary=summary[:400],
                )
        except (sqlite3.Error, OSError):
            return error_response(
                SAVE_PERSISTENCE_FAILED, "version promotion could not be durably recorded"
            )
        return {
            "ok": True,
            "version_id": version_id,
            "status": STATUS_READY,
            "promoted": True,
        }

    def rollback_version(
        self,
        capability_id: Any,
        version_id: Any,
        reason: Any,
        evidence_ref: Any = None,
    ) -> dict[str, Any]:
        if not isinstance(capability_id, str):
            return error_response(INVALID_ARGUMENT, "capability_id must be a string")
        if not isinstance(version_id, str):
            return error_response(INVALID_ARGUMENT, "version_id must be a string")
        if not isinstance(reason, str) or not reason.strip():
            return error_response(INVALID_ARGUMENT, "rollback reason must be a non-empty string")
        if evidence_ref is not None and not isinstance(evidence_ref, str):
            return error_response(INVALID_ARGUMENT, "evidence_ref must be a string")
        capability = self.registry.get_capability(capability_id)
        if capability is None:
            return error_response(CAPABILITY_NOT_FOUND, "no capability matches that id")
        if capability["archived_at"]:
            return error_response(
                CAPABILITY_ARCHIVED, "archived capabilities cannot be rolled back"
            )
        if capability["quarantined_at"]:
            return error_response(
                CAPABILITY_QUARANTINED, "release the capability quarantine before rollback"
            )
        version = self.registry.get_version(version_id)
        if version is None or version["capability_id"] != capability_id:
            return error_response(INVALID_ARGUMENT, "version_id does not belong to that capability")
        if version["status"] != STATUS_READY:
            return error_response(CAPABILITY_NOT_READY, "rollback target is not ready")
        previous_id = capability["current_version_id"]
        if previous_id is None:
            return error_response(CAPABILITY_NOT_READY, "capability has no current version")
        if previous_id == version_id:
            return {
                "ok": True,
                "capability_id": capability_id,
                "version_id": version_id,
                "rolled_back": False,
                "note": "version is already current",
            }
        previous = self.registry.get_version(previous_id)
        if previous is None or int(version["version_number"]) >= int(previous["version_number"]):
            return error_response(INVALID_ARGUMENT, "rollback target must be an older version")

        summary = f"rollback: {reason.strip()[:200]}"
        if evidence_ref and evidence_ref.strip():
            summary += f" | evidence: {evidence_ref.strip()[:200]}"
        try:
            with self.store.transaction():
                self.registry.set_current_version(capability_id, version_id)
                self.evidence.record(
                    EVENT_VERSION_ROLLED_BACK,
                    capability_id=capability_id,
                    version_id=version_id,
                    summary=summary[:400],
                )
        except (sqlite3.Error, OSError):
            return error_response(SAVE_PERSISTENCE_FAILED, "rollback could not be durably recorded")
        return {
            "ok": True,
            "capability_id": capability_id,
            "previous_version_id": previous_id,
            "version_id": version_id,
            "rolled_back": True,
        }

    def archive(self, capability_id: Any, reason: str = "manual archive") -> dict[str, Any]:
        if not isinstance(capability_id, str):
            return error_response(INVALID_ARGUMENT, "capability_id must be a string")
        capability = self.registry.get_capability(capability_id)
        if capability is None:
            return error_response(CAPABILITY_NOT_FOUND, "no capability matches that id")
        try:
            with self.store.transaction():
                self.registry.archive(capability_id)
                observations_invalidated = self.evidence.invalidate_observations_for_capability(
                    capability_id, "capability_archived"
                )
                self.evidence.record(
                    EVENT_ARCHIVED,
                    capability_id=capability_id,
                    summary=str(reason)[:200],
                )
        except (sqlite3.Error, OSError):
            return error_response(SAVE_PERSISTENCE_FAILED, "archive could not be durably recorded")
        return {
            "ok": True,
            "capability_id": capability_id,
            "archived": True,
            "observations_invalidated": observations_invalidated,
        }
