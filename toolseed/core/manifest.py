"""Authoritative P0 candidate and Manifest contract.

This module is the single source of truth for the P0 transport shape: one JSON
object with ``protocol_version``, an object ``manifest`` and ``content`` text.
No directory, zip, source-code field or adapter-specific extension is accepted.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any

from .errors import CONTRACT_VIOLATION, INVALID_ARGUMENT, UNSUPPORTED_CAPABILITY_KIND

PROTOCOL_VERSION = 1
KIND_PROCEDURE = "procedure"
SUPPORTED_KINDS = frozenset({KIND_PROCEDURE})

CANDIDATE_FIELDS = frozenset({"protocol_version", "manifest", "content", "target_capability_id"})
MANIFEST_FIELDS = frozenset(
    {"name", "kind", "description", "when_to_use", "not_for", "tags", "applicability"}
)
APPLICABILITY_FIELDS = frozenset({"harnesses", "operating_systems", "required_tools"})

NAME_MAX = 80
DESCRIPTION_MAX = 280
WHEN_TO_USE_MAX = 500
NOT_FOR_MAX_ITEMS = 10
NOT_FOR_ITEM_MAX = 160
TAGS_MAX_ITEMS = 12
TAG_MAX = 40
APPLICABILITY_MAX_ITEMS = 20
APPLICABILITY_ITEM_MAX = 120
CONTENT_MAX_BYTES = 32_768
CANDIDATE_MAX_BYTES = 65_536


class CandidateError(ValueError):
    """A rejected candidate carrying a stable public error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text.strip())


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(protocol_version: int, manifest: dict[str, Any], content: str) -> str:
    payload = canonical({"protocol_version": protocol_version, "manifest": manifest, "content": content})
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _require_text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise CandidateError(CONTRACT_VIOLATION, f"{field} must be a string")
    text = nfc(value)
    if not text:
        raise CandidateError(CONTRACT_VIOLATION, f"{field} must not be empty")
    if len(text) > maximum:
        raise CandidateError(CONTRACT_VIOLATION, f"{field} exceeds {maximum} characters")
    return text


def _string_list(value: Any, field: str, max_items: int, item_max: int) -> list[str]:
    if not isinstance(value, list):
        raise CandidateError(CONTRACT_VIOLATION, f"{field} must be an array of strings")
    if len(value) > max_items:
        raise CandidateError(CONTRACT_VIOLATION, f"{field} has more than {max_items} items")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise CandidateError(CONTRACT_VIOLATION, f"{field} items must be strings")
        text = nfc(item)
        if not text:
            raise CandidateError(CONTRACT_VIOLATION, f"{field} items must not be empty")
        if len(text) > item_max:
            raise CandidateError(CONTRACT_VIOLATION, f"{field} items exceed {item_max} characters")
        items.append(text)
    return items


def normalize_manifest(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CandidateError(INVALID_ARGUMENT, "candidate.manifest must be an object")

    unknown = sorted(set(raw) - MANIFEST_FIELDS)
    if unknown:
        raise CandidateError(
            CONTRACT_VIOLATION, "manifest has undefined fields: " + ", ".join(unknown)
        )
    missing = sorted(MANIFEST_FIELDS - set(raw))
    if missing:
        raise CandidateError(
            CONTRACT_VIOLATION, "manifest is missing required fields: " + ", ".join(missing)
        )

    kind = raw["kind"]
    if not isinstance(kind, str):
        raise CandidateError(CONTRACT_VIOLATION, "manifest.kind must be a string")
    if kind not in SUPPORTED_KINDS:
        raise CandidateError(
            UNSUPPORTED_CAPABILITY_KIND,
            "this Core version supports only kind=procedure; other kinds are not silently downgraded",
        )

    applicability_raw = raw["applicability"]
    if not isinstance(applicability_raw, dict):
        raise CandidateError(CONTRACT_VIOLATION, "manifest.applicability must be an object")
    unknown_applicability = sorted(set(applicability_raw) - APPLICABILITY_FIELDS)
    if unknown_applicability:
        raise CandidateError(
            CONTRACT_VIOLATION,
            "applicability has undefined fields: " + ", ".join(unknown_applicability),
        )
    applicability: dict[str, list[str]] = {}
    for field in APPLICABILITY_FIELDS:
        applicability[field] = _string_list(
            applicability_raw.get(field, []),
            f"applicability.{field}",
            APPLICABILITY_MAX_ITEMS,
            APPLICABILITY_ITEM_MAX,
        )

    return {
        "name": _require_text(raw["name"], "manifest.name", NAME_MAX),
        "kind": KIND_PROCEDURE,
        "description": _require_text(raw["description"], "manifest.description", DESCRIPTION_MAX),
        "when_to_use": _require_text(raw["when_to_use"], "manifest.when_to_use", WHEN_TO_USE_MAX),
        "not_for": _string_list(raw["not_for"], "manifest.not_for", NOT_FOR_MAX_ITEMS, NOT_FOR_ITEM_MAX),
        "tags": _string_list(raw["tags"], "manifest.tags", TAGS_MAX_ITEMS, TAG_MAX),
        "applicability": applicability,
    }


def normalize_candidate(raw: Any) -> dict[str, Any]:
    """Validate and normalize one P0 candidate. Raises ``CandidateError``."""
    if not isinstance(raw, dict):
        raise CandidateError(INVALID_ARGUMENT, "candidate must be a JSON object")

    unknown = sorted(set(raw) - CANDIDATE_FIELDS)
    if unknown:
        raise CandidateError(INVALID_ARGUMENT, "candidate has undefined fields: " + ", ".join(unknown))

    protocol_version = raw.get("protocol_version")
    if (
        not isinstance(protocol_version, int)
        or isinstance(protocol_version, bool)
        or protocol_version != PROTOCOL_VERSION
    ):
        raise CandidateError(
            INVALID_ARGUMENT, f"protocol_version must be the integer {PROTOCOL_VERSION}"
        )

    if "manifest" not in raw:
        raise CandidateError(INVALID_ARGUMENT, "candidate.manifest is required")
    manifest = normalize_manifest(raw["manifest"])

    content_raw = raw.get("content")
    if not isinstance(content_raw, str):
        raise CandidateError(INVALID_ARGUMENT, "candidate.content must be a string")
    content = normalize_newlines(content_raw)
    if not content.strip():
        raise CandidateError(CONTRACT_VIOLATION, "candidate.content must not be empty")
    if len(content.encode("utf-8")) > CONTENT_MAX_BYTES:
        raise CandidateError(
            CONTRACT_VIOLATION, f"candidate.content exceeds {CONTENT_MAX_BYTES} bytes"
        )

    candidate: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "manifest": manifest,
        "content": content,
    }

    target = raw.get("target_capability_id")
    if target is not None:
        if not isinstance(target, str) or not target.strip():
            raise CandidateError(
                INVALID_ARGUMENT, "target_capability_id must be a non-empty string"
            )
        candidate["target_capability_id"] = target.strip()

    if len(canonical(candidate).encode("utf-8")) > CANDIDATE_MAX_BYTES:
        raise CandidateError(CONTRACT_VIOLATION, f"candidate exceeds {CANDIDATE_MAX_BYTES} bytes")

    return candidate


_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(password|passwd|secret|api_key|token)\s*[:=]\s*[^\s'\"]{8,}"),
)
_BYPASS_PATTERNS = (
    re.compile(r"绕过(权限|策略|安全)"),
    re.compile(r"忽略.{0,4}(权限|策略|安全)"),
    re.compile(r"(?i)bypass\s+(the\s+)?(policy|permission|safety)"),
    re.compile(r"(?i)ignore\s+(the\s+)?(policy|permission|safety)"),
    re.compile(r"泄露.{0,8}(密钥|令牌|凭据|密码)"),
    re.compile(r"(?i)exfiltrat\w+"),
)
_REVIEW_PATTERNS = (
    re.compile(r"(?i)\brm\s+-rf\b"),
    re.compile(r"(?i)\bdrop\s+table\b"),
    re.compile(r"(?i)\bformat\s+[a-z]:"),
    re.compile(r"(?i)\bshutdown\b"),
    re.compile(r"(?i)\bdelete\s+from\s+\w+"),
)


def scan_content(content: str) -> tuple[str | None, list[str]]:
    """Static content check.

    Returns ``(verdict, reasons)`` where verdict is ``None`` (publishable),
    ``"review"`` (keep as candidate) or ``"blocked"`` (refuse to store).
    Matched text is never echoed back.
    """
    for pattern in _SECRET_PATTERNS:
        if pattern.search(content):
            return "blocked", ["content appears to contain a credential or secret"]
    for pattern in _BYPASS_PATTERNS:
        if pattern.search(content):
            return "blocked", [
                "content contains instructions intended to bypass policy or leak secrets"
            ]
    for pattern in _REVIEW_PATTERNS:
        if pattern.search(content):
            return "review", [
                "content references a destructive or high-impact operation; manual review required"
            ]
    return None, []
