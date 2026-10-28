"""Experience and invocation-bound feedback as atomic learning operations."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .candidates import CandidateService
from .errors import (
    CAPABILITY_ARCHIVED,
    CAPABILITY_QUARANTINED,
    CONTRACT_VIOLATION,
    INVALID_ARGUMENT,
    POLICY_BLOCKED,
    SAVE_PERSISTENCE_FAILED,
    error_response,
)
from .evidence import (
    EVENT_EXPERIENCE_LEARNED,
    EVENT_REUSE_LEARNED,
    Evidence,
    make_signal_key,
)
from .knowledge import (
    version_structure,
)
from .learning import prepare_experience
from .manifest import (
    CandidateError,
    canonical,
    contains_secret,
)
from .registry import STATUS_QUARANTINED, Registry
from .reuse import amended_candidate, normalize_reuse
from .service_support import (
    _CandidateRejected,
    accepted,
)
from .storage import Store


class LearningService:
    def __init__(
        self, store: Store, registry: Registry, evidence: Evidence, candidates: CandidateService
    ) -> None:
        self.store = store
        self.registry = registry
        self.evidence = evidence
        self.candidates = candidates

    def learn(self, experience: Any, context: Any) -> dict[str, Any]:
        if context is not None and not isinstance(context, dict):
            return error_response(INVALID_ARGUMENT, "context must be an object")
        try:
            # Keep bounded task identity even when other caller context is large.
            # Caller-supplied source_type cannot upgrade an agent observation.
            origin = {
                key: value.strip()[:200]
                for key in ("task_id", "session_id", "harness", "workspace", "namespace")
                if isinstance(value := (context or {}).get(key), str) and value.strip()
            }
            if contains_secret(canonical(origin)):
                return error_response(
                    POLICY_BLOCKED, "context appears to contain a credential or secret"
                )
            with self.store.transaction(immediate=True):
                if isinstance(experience, dict) and "reuse" in experience:
                    return self._learn_from_reuse(experience, context, origin)
                target = (
                    experience.get("target_capability_id") if isinstance(experience, dict) else None
                )
                cap = self.registry.get_capability(target) if isinstance(target, str) else None
                candidate, observation, structure = prepare_experience(
                    experience, target_name=cap["name"] if cap else None
                )
                result = self.candidates.save_in_transaction(
                    candidate, observation["reuse_reason"], context, knowledge=structure
                )
                if result.get("status") != "accepted":
                    raise _CandidateRejected(result)
                observation["origin"] = origin
                key = make_signal_key(
                    {
                        "event": EVENT_EXPERIENCE_LEARNED,
                        "version_id": result["version_id"],
                        "observation": observation,
                    }
                )
                previous = self.store.db.execute(
                    "SELECT event_id FROM evidence_events WHERE signal_key = ?",
                    (key,),
                ).fetchone()
                event_id = (
                    previous["event_id"]
                    if previous
                    else self.evidence.record(
                        EVENT_EXPERIENCE_LEARNED,
                        source_type="agent",
                        capability_id=result["capability_id"],
                        version_id=result["version_id"],
                        content_hash=result["content_hash"],
                        task_id=origin.get("task_id"),
                        summary=canonical(observation),
                        signal_key=key,
                    )
                )
                return {
                    **result,
                    "learning_event_id": event_id,
                    "learning_action": "existing"
                    if result["duplicate"]
                    else "revision_proposed"
                    if target
                    else "created",
                    "observation_source": "agent",
                    "task_outcome": "unknown",
                }
        except CandidateError as exc:
            return error_response(exc.code, exc.message)
        except _CandidateRejected as exc:
            return exc.response
        except (sqlite3.Error, OSError):
            return error_response(
                SAVE_PERSISTENCE_FAILED, "experience could not be durably persisted"
            )

    def _learn_from_reuse(
        self, raw: dict[str, Any], context: Any, origin: dict[str, str]
    ) -> dict[str, Any]:
        """Called under the learning write transaction; bind first, then amend."""
        data = normalize_reuse(raw)
        reuse = data["reuse"]
        cap = self.registry.get_capability(data["target_capability_id"])
        base = self.registry.get_version(reuse["version_id"])
        invocation = self.store.db.execute(
            "SELECT * FROM invocations WHERE invocation_id = ?",
            (reuse["invocation_id"],),
        ).fetchone()
        if cap is None or base is None or invocation is None:
            return error_response(
                INVALID_ARGUMENT,
                "reuse must reference an existing capability, version and invocation",
            )
        if (
            base["capability_id"] != cap["capability_id"]
            or invocation["capability_id"] != cap["capability_id"]
            or invocation["version_id"] != base["version_id"]
            or base["content_hash"] != reuse["content_hash"]
            or invocation["delivery_status"] != "guidance_delivered"
        ):
            return error_response(
                CONTRACT_VIOLATION,
                "reuse references do not identify the delivered method",
                reason_code="REUSE_BINDING_MISMATCH",
            )
        if (
            invocation["task_id"]
            and origin.get("task_id")
            and invocation["task_id"] != origin["task_id"]
        ):
            return error_response(CONTRACT_VIOLATION, "reuse task_id conflicts with the invocation")
        invocation_context = json.loads(invocation["context_json"] or "{}")
        if (
            invocation_context.get("session_id")
            and origin.get("session_id")
            and invocation_context["session_id"] != origin["session_id"]
        ):
            return error_response(
                CONTRACT_VIOLATION, "reuse session_id conflicts with the invocation"
            )
        key = make_signal_key({"event": EVENT_REUSE_LEARNED, "feedback": data})
        previous = self.store.db.execute(
            "SELECT event_id, summary FROM evidence_events WHERE signal_key = ?",
            (key,),
        ).fetchone()
        if previous:
            observation = json.loads(previous["summary"])
            revision = (
                self.registry.get_version(observation["revision_version_id"])
                if observation["revision_version_id"]
                else None
            )
            result = accepted(
                self.store, cap, revision if revision is not None else base, duplicate=True
            )
            return {
                **result,
                "learning_action": "revision_proposed"
                if revision is not None
                else "observation_added",
                "learning_event_id": previous["event_id"],
                "reuse_source": reuse,
                "feedback_duplicate": True,
                "observation_source": "agent",
                "task_outcome": "unknown",
            }
        revision_id = None
        result = accepted(self.store, cap, base, duplicate=False)
        if "amendment" in data:
            if cap["archived_at"]:
                return error_response(
                    CAPABILITY_ARCHIVED, "archived capability cannot receive a revision"
                )
            if cap["quarantined_at"] or base["status"] == STATUS_QUARANTINED:
                return error_response(
                    CAPABILITY_QUARANTINED,
                    "quarantined capability/version cannot receive a reuse revision",
                )
            if cap["current_version_id"] != base["version_id"]:
                return error_response(
                    CONTRACT_VIOLATION,
                    "the reused version is no longer current; record observations without amendment or reconcile against the current method",
                    reason_code="REUSE_VERSION_CHANGED",
                )
            candidate = amended_candidate(base, cap["capability_id"], data["amendment"])
            structure = version_structure(base)
            if structure is not None and candidate["content"] != base["content"]:
                structure["addenda"].append(candidate["content"][len(base["content"]) + 2 :])
            result = self.candidates.save_in_transaction(
                candidate, data["reuse_reason"], context, knowledge=structure
            )
            if result.get("status") != "accepted":
                raise _CandidateRejected(result)
            if result["version_id"] != base["version_id"]:
                revision_id = result["version_id"]
        event_id = self.evidence.record(
            EVENT_REUSE_LEARNED,
            source_type="agent",
            capability_id=cap["capability_id"],
            version_id=base["version_id"],
            invocation_id=invocation["invocation_id"],
            content_hash=base["content_hash"],
            task_id=invocation["task_id"] or origin.get("task_id"),
            summary=canonical({**data, "origin": origin, "revision_version_id": revision_id}),
            signal_key=key,
        )
        return {
            **result,
            "learning_action": "revision_proposed" if revision_id else "observation_added",
            "learning_event_id": event_id,
            "reuse_source": reuse,
            "feedback_duplicate": False,
            "observation_source": "agent",
            "task_outcome": "unknown",
        }
