"""Candidate creation, immutable revisions and baseline checks."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .errors import (
    CAPABILITY_ARCHIVED,
    CAPABILITY_NOT_FOUND,
    CONTRACT_VIOLATION,
    INVALID_ARGUMENT,
    POLICY_BLOCKED,
    SAVE_PERSISTENCE_FAILED,
    error_response,
)
from .evidence import (
    EVENT_DUPLICATE,
    EVENT_PROCEDURE_SAVED,
    Evidence,
)
from .knowledge import (
    normalize_structure,
    render_structure,
    scan_guidance,
)
from .manifest import (
    CandidateError,
    canonical,
    content_hash,
    normalize_candidate,
)
from .registry import STATUS_CANDIDATE, STATUS_READY, Registry
from .search import tokens
from .service_support import (
    REASON_CURRENT_CONFLICT,
    accepted,
    context_namespace,
    origin_summary,
)
from .storage import Store


class CandidateService:
    def __init__(self, store: Store, registry: Registry, evidence: Evidence) -> None:
        self.store = store
        self.registry = registry
        self.evidence = evidence

    def _possible_duplicates(
        self,
        manifest: dict[str, Any],
        exclude_capability_id: str,
        namespace: str,
    ) -> list[dict[str, Any]]:
        """Deterministic similarity hints; never merges or blocks a save."""
        target_tokens = tokens(manifest["name"])
        for tag in manifest["tags"]:
            target_tokens |= tokens(tag)
        target_tokens |= tokens(manifest["description"])
        target_tokens |= tokens(manifest["when_to_use"])
        target_tags = set(manifest["tags"])

        rows = self.store.db.execute(
            "SELECT c.capability_id, v.manifest_json "
            "FROM capabilities c JOIN capability_versions v "
            "  ON v.capability_id = c.capability_id "
            "WHERE c.capability_id != ? AND c.namespace = ? "
            "  AND v.version_number = ("
            "    SELECT MAX(v2.version_number) FROM capability_versions v2 "
            "    WHERE v2.capability_id = c.capability_id)",
            (exclude_capability_id, namespace),
        ).fetchall()

        hints: list[dict[str, Any]] = []
        for row in rows:
            other = json.loads(row["manifest_json"])
            reasons: list[str] = []
            score = 0.0
            if other.get("name") == manifest["name"]:
                score = 1.0
                reasons.append("same_name")

            shared_tags = target_tags & set(other.get("tags") or [])
            if len(shared_tags) >= 2:
                score = max(score, 0.6)
                reasons.append("shared_tags")

            other_tokens = tokens(other.get("name", ""))
            for tag in other.get("tags") or []:
                other_tokens |= tokens(tag)
            other_tokens |= tokens(other.get("description", ""))
            other_tokens |= tokens(other.get("when_to_use", ""))
            union = target_tokens | other_tokens
            if union:
                overlap = len(target_tokens & other_tokens) / len(union)
                if overlap >= 0.3:
                    score = max(score, overlap)
                    reasons.append("similar_metadata")

            if score > 0:
                hints.append(
                    {
                        "capability_id": row["capability_id"],
                        "name": other.get("name"),
                        "score": round(score, 3),
                        "reasons": reasons,
                    }
                )

        hints.sort(key=lambda item: (-item["score"], item["name"] or ""))
        return hints[:3]

    def save(
        self,
        candidate: Any,
        intent: Any = "",
        context: Any = None,
        *,
        force_candidate: bool = False,
    ) -> dict[str, Any]:
        try:
            with self.store.transaction(immediate=True):
                return self.save_in_transaction(
                    candidate,
                    intent,
                    context,
                    force_candidate=force_candidate,
                )
        except sqlite3.IntegrityError:
            duplicate = self._duplicate_from_conflict(candidate, context)
            if duplicate is not None:
                return duplicate
            return error_response(
                SAVE_PERSISTENCE_FAILED, "candidate could not be durably persisted"
            )
        except (sqlite3.Error, OSError):
            return error_response(
                SAVE_PERSISTENCE_FAILED, "candidate could not be durably persisted"
            )

    def _duplicate_from_conflict(
        self,
        candidate: Any,
        context: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        try:
            normalized = normalize_candidate(candidate)
        except CandidateError:
            return None
        manifest = normalized["manifest"]
        digest = content_hash(normalized["protocol_version"], manifest, normalized["content"])
        target_id = normalized.get("target_capability_id")
        namespace = context_namespace(context)
        if target_id is not None:
            capability = self.registry.get_capability(target_id)
            if capability is None:
                return None
            if self._revision_base_error(normalized, capability) is not None:
                return None
            namespace = capability["namespace"]
            version = self.registry.find_version_by_hash(target_id, digest)
            if version is None:
                return None
        else:
            capability, version = self.registry.find_by_identity(
                namespace, manifest["name"], digest
            )
            if capability is None or version is None:
                return None
        try:
            self.evidence.record(
                EVENT_DUPLICATE,
                capability_id=capability["capability_id"],
                version_id=version["version_id"],
                quantity=1,
            )
        except (sqlite3.Error, OSError):
            pass
        return {
            **accepted(self.store, capability, version, duplicate=True),
            "possible_duplicates": [],
        }

    def save_in_transaction(
        self,
        candidate: Any,
        intent: Any = "",
        context: Any = None,
        *,
        force_candidate: bool = False,
        knowledge: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Write under the caller's transaction so learning/repair can roll back together."""
        if not self.store.transaction_active:
            raise RuntimeError("candidate writes require an active transaction")
        if not isinstance(intent, str):
            return error_response(INVALID_ARGUMENT, "intent must be a string")
        if context is not None and not isinstance(context, dict):
            return error_response(INVALID_ARGUMENT, "context must be an object")

        origin = origin_summary(intent, context)

        try:
            normalized = normalize_candidate(candidate)
            if knowledge is not None:
                knowledge = normalize_structure(knowledge)
                if render_structure(knowledge) != normalized["content"]:
                    return error_response(
                        CONTRACT_VIOLATION,
                        "experience structure does not match the rendered method",
                    )
        except CandidateError as exc:
            return error_response(exc.code, exc.message)
        except ValueError:
            return error_response(CONTRACT_VIOLATION, "invalid experience structure")

        verdict, reasons = scan_guidance(normalized["content"], knowledge)
        if verdict == "blocked":
            return error_response(POLICY_BLOCKED, reasons[0])

        manifest = normalized["manifest"]
        content = normalized["content"]
        digest = content_hash(normalized["protocol_version"], manifest, content)

        target_id = normalized.get("target_capability_id")
        status = (
            STATUS_CANDIDATE
            if force_candidate or verdict == "review" or target_id is not None
            else STATUS_READY
        )

        target_capability = None
        namespace = context_namespace(context)
        if target_id is not None:
            target_capability = self.registry.get_capability(target_id)
            if target_capability is None:
                return error_response(CAPABILITY_NOT_FOUND, "target_capability_id does not exist")
            if target_capability["archived_at"]:
                return error_response(CAPABILITY_ARCHIVED, "target capability is archived")
            if manifest["name"] != target_capability["name"]:
                return error_response(
                    INVALID_ARGUMENT,
                    "target version name must match capability name",
                )
            conflict = self._revision_base_error(normalized, target_capability)
            if conflict is not None:
                return conflict
            namespace = target_capability["namespace"]
            existing = self.registry.find_version_by_hash(target_id, digest)
            if existing is not None:
                self.evidence.record(
                    EVENT_DUPLICATE,
                    capability_id=target_id,
                    version_id=existing["version_id"],
                    quantity=1,
                )
                return {
                    **accepted(self.store, target_capability, existing, duplicate=True),
                    "possible_duplicates": [],
                }
        else:
            existing_capability, existing_version = self.registry.find_capability_by_name_and_hash(
                manifest["name"], digest, namespace
            )
            if existing_capability is not None and existing_version is not None:
                self.evidence.record(
                    EVENT_DUPLICATE,
                    capability_id=existing_capability["capability_id"],
                    version_id=existing_version["version_id"],
                    quantity=1,
                )
                return {
                    **accepted(self.store, existing_capability, existing_version, duplicate=True),
                    "possible_duplicates": [],
                }

        if target_capability is not None:
            capability = target_capability
            version = self.registry.add_version(
                capability["capability_id"],
                manifest,
                content,
                digest,
                status=status,
                origin=origin,
                knowledge=knowledge,
            )
        else:
            capability, version = self.registry.create_with_version(
                manifest["name"],
                manifest,
                content,
                digest,
                status=status,
                origin=origin,
                namespace=namespace,
                knowledge=knowledge,
            )

        self.evidence.record(
            EVENT_PROCEDURE_SAVED,
            capability_id=capability["capability_id"],
            version_id=version["version_id"],
            quantity=1,
            summary=canonical({"base_version_id": normalized["base_version_id"]})
            if target_capability is not None
            else None,
        )
        response = accepted(self.store, capability, version, duplicate=False)
        response["possible_duplicates"] = self._possible_duplicates(
            manifest, capability["capability_id"], capability["namespace"]
        )
        if verdict == "review":
            response["notes"] = reasons
            response["content_review"] = {
                "status": "verification_required"
                if knowledge is not None
                and scan_guidance(content, knowledge, for_promotion=True)[0] is None
                else "edit_required",
                "counterexamples_are_instructions": False,
            }
        return response

    def _revision_base_error(
        self, candidate: dict[str, Any], capability: Any
    ) -> dict[str, Any] | None:
        if not candidate.get("base_version_id") or not candidate.get("base_content_hash"):
            return error_response(
                CONTRACT_VIOLATION,
                "full revisions require base_version_id and base_content_hash from the method you read",
                reason_code="REVISION_BASE_REQUIRED",
            )
        base = self.registry.current_version(capability)
        if base is None:
            # With no active method, explicit admin repair proposals may share
            # the same isolated base. Later promotion retains its own gates.
            base = self.registry.get_version(candidate["base_version_id"])
        if (
            base is None
            or base["capability_id"] != capability["capability_id"]
            or candidate["base_version_id"] != base["version_id"]
        ):
            return error_response(
                CONTRACT_VIOLATION,
                "revision base changed; read the current method and reconcile your changes",
                reason_code=REASON_CURRENT_CONFLICT,
            )
        if candidate["base_content_hash"] != base["content_hash"]:
            return error_response(
                CONTRACT_VIOLATION,
                "revision base hash does not match the method read",
                reason_code="REVISION_BASE_MISMATCH",
            )
        return None
