"""Small operation contracts and response builders shared by domain services."""

from __future__ import annotations

import json
from typing import Any

from .errors import (
    AMBIGUOUS_CAPABILITY_NAME,
    CAPABILITY_NOT_FOUND,
)
from .evidence import EVENT_PROCEDURE_SAVED, EVENT_REUSE_LEARNED
from .registry import STATUS_CANDIDATE
from .storage import Store

REASON_VERSION_NOT_CANDIDATE = "VERSION_NOT_CANDIDATE"

REASON_VERIFICATION_MISSING = "VERIFICATION_EVIDENCE_MISSING"

REASON_VERIFICATION_INVALID = "VERIFICATION_EVIDENCE_INVALID"

REASON_CONTENT_HASH_MISMATCH = "CONTENT_HASH_MISMATCH"

REASON_REGRESSION_MISSING = "REGRESSION_VERIFICATION_MISSING"

REASON_CURRENT_CONFLICT = "CURRENT_VERSION_CONFLICT"

REASON_WATERMARK_MISSING = "DECISION_ASSESSMENT_WATERMARK_MISSING"

ORIGIN_INTENT_MAX = 500
ORIGIN_CONTEXT_MAX = 1000
ORIGIN_CONTEXT_FIELDS = (
    "source",
    "source_type",
    "task_id",
    "session_id",
    "harness",
    "workspace",
    "related_capability_ids",
)


class _CandidateRejected(Exception):
    def __init__(self, response: dict[str, Any]) -> None:
        super().__init__("candidate rejected")
        self.response = response


def context_namespace(context: dict[str, Any] | None) -> str:
    if not context:
        return "global"
    value = context.get("namespace") or context.get("workspace")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return "global"


def namespace_scope(namespace: str) -> tuple[str, ...]:
    return ("global",) if namespace == "global" else ("global", namespace)


def origin_summary(intent: str, context: dict[str, Any] | None) -> str:
    """Persist only caller-known provenance, never arbitrary context keys."""
    text = intent.strip()[:ORIGIN_INTENT_MAX]
    safe: dict[str, Any] = {}
    if context:
        for key in ORIGIN_CONTEXT_FIELDS:
            value = context.get(key)
            if isinstance(value, str) and value.strip():
                safe[key] = value.strip()[:200]
            elif isinstance(value, list):
                items = [
                    item.strip()[:120] for item in value if isinstance(item, str) and item.strip()
                ][:10]
                if items:
                    safe[key] = items
    if not safe:
        return text
    payload = json.dumps(
        {"intent": text, "context": safe},
        ensure_ascii=False,
        sort_keys=True,
    )
    if len(payload) > ORIGIN_CONTEXT_MAX:
        return text[:ORIGIN_CONTEXT_MAX]
    return payload


def revision_base_version(store: Store, version_id: str) -> str | None:
    row = store.db.execute(
        "SELECT summary FROM evidence_events WHERE event_type = ? AND version_id = ? LIMIT 1",
        (EVENT_PROCEDURE_SAVED, version_id),
    ).fetchone()
    if row and row["summary"]:
        try:
            data = json.loads(row["summary"])
        except (TypeError, ValueError):
            data = None
        if isinstance(data, dict) and data.get("base_version_id"):
            return str(data["base_version_id"])
    # Older reuse revisions retain immutable source-delivery lineage.
    row = store.db.execute(
        "SELECT version_id FROM evidence_events WHERE event_type = ? "
        "AND json_extract(summary, '$.revision_version_id') = ? ORDER BY rowid LIMIT 1",
        (EVENT_REUSE_LEARNED, version_id),
    ).fetchone()
    return str(row["version_id"]) if row else None


def accepted(store: Store, capability: Any, version: Any, *, duplicate: bool) -> dict[str, Any]:
    result = {
        "status": "accepted",
        "capability_id": capability["capability_id"],
        "namespace": capability["namespace"],
        "version_id": version["version_id"],
        "version": version["version_number"],
        "version_status": version["status"],
        "content_hash": version["content_hash"],
        "duplicate": duplicate,
    }
    if version["status"] == STATUS_CANDIDATE:
        base = revision_base_version(store, version["version_id"])
        if base:
            result["revision_validation"] = {
                "capability_id": capability["capability_id"],
                "version_id": version["version_id"],
                "content_hash": version["content_hash"],
                "base_version_id": base,
            }
    return result


def resolve_message(code: str) -> str:
    if code == CAPABILITY_NOT_FOUND:
        return "no capability matches that id or name"
    if code == AMBIGUOUS_CAPABILITY_NAME:
        return "capability name is ambiguous; use the capability_id"
    return "capability reference is not valid"
