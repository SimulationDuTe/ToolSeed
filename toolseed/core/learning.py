"""Turn host-model experience into reusable guidance; never infer it with an LLM."""
from __future__ import annotations

import hashlib
from typing import Any

from .errors import CONTRACT_VIOLATION, INVALID_ARGUMENT, POLICY_BLOCKED
from .knowledge import render_structure
from .manifest import (
    CandidateError,
    _require_text,
    _string_list,
    canonical,
    contains_secret,
    normalize_candidate,
    normalize_newlines,
)
from .reuse import REUSE_SCHEMA

TEXT_FIELDS = {
    "problem": 280, "when_to_use": 500, "method": 12000,
    "reuse_reason": 500, "validation": 2000, "name": 80,
    "target_capability_id": 160, "base_version_id": 160, "base_content_hash": 80,
}
REQUIRED = {"problem", "when_to_use", "method", "reuse_reason", "validation"}
LIST_FIELDS = {"triggers": (8, 160), "aliases": (12, 160), "checks": (12, 500), "source_refs": (10, 240)}
RECORD_FIELDS = {
    "pitfalls": {"attempt": 1024, "observed": 1024, "lesson": 1024},
    "tool_recipes": {"purpose": 512, "tool_hint": 160, "usage": 2000, "check": 512},
}
FIELDS = set(TEXT_FIELDS) | set(LIST_FIELDS) | set(RECORD_FIELDS) | {
    "not_for", "tags", "applicability",
}


def _text_schema(maximum: int) -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "maxLength": maximum}


# Also used by the transports: the host model should see the actual input shape.
NEW_EXPERIENCE_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": sorted(REQUIRED),
    "dependentRequired": {"target_capability_id": ["base_version_id", "base_content_hash"]},
    "properties": {
        **{key: _text_schema(limit) for key, limit in TEXT_FIELDS.items()},
        **{key: {"type": "array", "maxItems": count, "items": _text_schema(limit)}
           for key, (count, limit) in {**LIST_FIELDS, "not_for": (10, 160), "tags": (12, 40)}.items()},
        **{key: {"type": "array", "maxItems": 8, "items": {
            "type": "object", "additionalProperties": False, "required": list(fields),
            "properties": {field: _text_schema(limit) for field, limit in fields.items()},
        }} for key, fields in RECORD_FIELDS.items()},
        "applicability": {"type": "object", "additionalProperties": False,
            "properties": {key: {"type": "array", "maxItems": 20, "items": _text_schema(120)}
                           for key in ("harnesses", "operating_systems", "required_tools")}},
    },
}
EXPERIENCE_SCHEMA: dict[str, Any] = {"oneOf": [NEW_EXPERIENCE_SCHEMA, REUSE_SCHEMA]}


def prepare_experience(raw: Any, *, target_name: str | None = None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Return a v1 candidate and agent-declared observations, separately hashed.

    Source references and validation observations must not produce new methods
    just because a different task used the same method. They remain append-only
    learning events, not independent verification or task-success evidence.
    """
    if not isinstance(raw, dict):
        raise CandidateError(INVALID_ARGUMENT, "experience must be an object")
    if set(raw) - FIELDS:
        raise CandidateError(CONTRACT_VIOLATION, "experience has undefined fields")
    if REQUIRED - set(raw):
        raise CandidateError(CONTRACT_VIOLATION, "experience is missing: " + ", ".join(sorted(REQUIRED - set(raw))))
    try:
        serialized = canonical(raw)
        if len(serialized.encode("utf-8")) > 65536:
            raise CandidateError(CONTRACT_VIOLATION, "experience exceeds 64 KiB")
    except (TypeError, ValueError, UnicodeError) as exc:
        if isinstance(exc, CandidateError):
            raise
        raise CandidateError(INVALID_ARGUMENT, "experience must contain JSON values") from exc
    if contains_secret(serialized):
        raise CandidateError(POLICY_BLOCKED, "experience appears to contain a credential or secret")

    data: dict[str, Any] = {}
    for key, maximum in TEXT_FIELDS.items():
        if key in raw:
            data[key] = normalize_newlines(_require_text(raw[key], key, maximum))
    for key, (count, limit) in LIST_FIELDS.items():
        data[key] = [normalize_newlines(item) for item in _string_list(raw.get(key, []), key, count, limit)]
    for key, fields in RECORD_FIELDS.items():
        entries = raw.get(key, [])
        if not isinstance(entries, list) or len(entries) > 8:
            raise CandidateError(CONTRACT_VIOLATION, f"{key} must be an array of at most 8 objects")
        data[key] = []
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != set(fields):
                raise CandidateError(CONTRACT_VIOLATION, f"{key} items require exactly: {', '.join(fields)}")
            data[key].append({field: normalize_newlines(_require_text(entry[field], f"{key}.{field}", limit))
                              for field, limit in fields.items()})

    problem = data["problem"]
    name = data.get("name") or target_name or (
        problem[:65] + "-" + hashlib.sha256(problem.encode("utf-8")).hexdigest()[:8]
    )
    structure = {"format": 1, **{key: data[key] for key in
                 ("method", "triggers", "aliases", "pitfalls", "tool_recipes", "checks")}, "addenda": []}
    candidate = normalize_candidate({
        "protocol_version": 1,
        "manifest": {"name": name, "kind": "procedure", "description": problem,
                     "when_to_use": data["when_to_use"], "not_for": raw.get("not_for", []),
                     "tags": raw.get("tags", []), "applicability": raw.get("applicability", {})},
        "content": render_structure(structure),
        **({"target_capability_id": data["target_capability_id"]} if "target_capability_id" in data else {}),
        **{key: data[key] for key in ("base_version_id", "base_content_hash") if key in data},
    })
    observation = {key: data[key] for key in ("reuse_reason", "validation", "source_refs")}
    return candidate, observation, structure
