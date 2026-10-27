"""Invocation-bound reuse observations and additive method amendments."""
from __future__ import annotations

import json
from typing import Any

from .errors import CONTRACT_VIOLATION, INVALID_ARGUMENT, POLICY_BLOCKED
from .manifest import (
    CandidateError,
    _require_text,
    _string_list,
    canonical,
    contains_secret,
    normalize_candidate,
    normalize_newlines,
    scan_content,
)


def text_schema(limit: int) -> dict[str, Any]:
    return {"type": "string", "minLength": 1, "maxLength": limit}


def list_schema(count: int, limit: int) -> dict[str, Any]:
    return {"type": "array", "maxItems": count, "items": text_schema(limit)}


REUSE_FIELDS = {"invocation_id": 160, "version_id": 160, "content_hash": 80, "actions": 2000}
REUSE_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": ["target_capability_id", "reuse", "validation", "reuse_reason"],
    "properties": {
        "target_capability_id": text_schema(160), "validation": text_schema(2000),
        "reuse_reason": text_schema(500), "source_refs": list_schema(10, 240),
        "reuse": {"type": "object", "additionalProperties": False,
            "required": [*REUSE_FIELDS, "application"], "properties": {
                **{key: text_schema(limit) for key, limit in REUSE_FIELDS.items()},
                "application": {"type": "string", "enum": ["applied", "partial", "not_applied"]},
            }},
        "amendment": {"type": "object", "additionalProperties": False, "properties": {
            "guidance": text_schema(6000), "checks": list_schema(12, 500), "not_for": list_schema(10, 160),
        }},
    },
}


def normalize_reuse(raw: dict[str, Any]) -> dict[str, Any]:
    fields = set(REUSE_SCHEMA["properties"])
    if set(raw) - fields or set(REUSE_SCHEMA["required"]) - set(raw):
        raise CandidateError(CONTRACT_VIOLATION, "reuse feedback requires target_capability_id, reuse, validation and reuse_reason; only source_refs and amendment are optional")
    try:
        serialized = canonical(raw)
        if len(serialized.encode("utf-8")) > 65536:
            raise CandidateError(CONTRACT_VIOLATION, "reuse feedback exceeds 64 KiB")
    except (TypeError, ValueError, UnicodeError) as exc:
        if isinstance(exc, CandidateError):
            raise
        raise CandidateError(INVALID_ARGUMENT, "reuse feedback must contain JSON values") from exc
    if contains_secret(serialized):
        raise CandidateError(POLICY_BLOCKED, "reuse feedback appears to contain a credential or secret")
    reuse = raw["reuse"]
    if not isinstance(reuse, dict) or set(reuse) != set(REUSE_FIELDS) | {"application"}:
        raise CandidateError(CONTRACT_VIOLATION, "reuse requires invocation_id, version_id, content_hash, application and actions")
    if reuse["application"] not in ("applied", "partial", "not_applied"):
        raise CandidateError(CONTRACT_VIOLATION, "reuse.application must be applied, partial or not_applied")
    result = {key: normalize_newlines(_require_text(raw[key], key, limit)) for key, limit in
              {"target_capability_id": 160, "validation": 2000, "reuse_reason": 500}.items()}
    normalized: dict[str, Any] = {**result,
        "reuse": {**{key: normalize_newlines(_require_text(reuse[key], f"reuse.{key}", limit)) for key, limit in REUSE_FIELDS.items()},
                  "application": reuse["application"]},
        "source_refs": _string_list(raw.get("source_refs", []), "source_refs", 10, 240)}
    if "amendment" in raw:
        amendment = raw["amendment"]
        if not isinstance(amendment, dict) or set(amendment) - {"guidance", "checks", "not_for"}:
            raise CandidateError(CONTRACT_VIOLATION, "amendment accepts guidance, checks and not_for")
        normalized["amendment"] = {
            "checks": _string_list(amendment.get("checks", []), "amendment.checks", 12, 500),
            "not_for": _string_list(amendment.get("not_for", []), "amendment.not_for", 10, 160),
            **({"guidance": normalize_newlines(_require_text(amendment["guidance"], "amendment.guidance", 6000))}
               if "guidance" in amendment else {}),
        }
        if not any(normalized["amendment"].values()):
            raise CandidateError(CONTRACT_VIOLATION, "amendment must contain a substantive addition")
        if reuse["application"] == "not_applied":
            raise CandidateError(CONTRACT_VIOLATION, "not_applied feedback cannot propose a validated method amendment")
    # Feedback is later surfaced beside guidance, so it must not be a second
    # channel for active bypass instructions. Ambiguous examples stay in audit.
    rendered = "\n".join([normalized["reuse"]["actions"], normalized["validation"], normalized["reuse_reason"]])
    verdict, reasons = scan_content(rendered)
    if verdict == "blocked":
        raise CandidateError(POLICY_BLOCKED, reasons[0])
    normalized["surface_allowed"] = verdict is None
    return normalized


def amended_candidate(base: Any, capability_id: str, amendment: dict[str, Any]) -> dict[str, Any]:
    manifest = json.loads(base["manifest_json"])
    manifest["not_for"] = list(dict.fromkeys([*manifest["not_for"], *amendment["not_for"]]))
    sections = []
    if amendment.get("guidance"):
        sections.append("## Reuse amendment / 复用修订\n" + amendment["guidance"])
    if amendment["checks"]:
        sections.append("## Additional reuse checks / 补充验证\n" + "\n".join("- " + check for check in amendment["checks"]))
    content = base["content"] + ("\n\n" + "\n\n".join(sections) if sections else "")
    return normalize_candidate({"protocol_version": 1, "target_capability_id": capability_id,
                                "manifest": manifest, "content": content})
