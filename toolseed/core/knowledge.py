"""Version-bound experience structure, rendering and counterexample review.

Only exact, validated renderings can use the structured counterexample gate.
Headings in arbitrary procedure text never exempt an operation from review.
"""
from __future__ import annotations

import json
from typing import Any

from .manifest import (
    _BYPASS_PATTERNS,
    CandidateError,
    _require_text,
    _string_list,
    canonical,
    contains_secret,
    scan_content,
)

STRUCTURE_LISTS = {"triggers": (8, 160), "aliases": (12, 160), "checks": (12, 500),
                   "addenda": (32, 14000)}
STRUCTURE_RECORDS = {
    "pitfalls": {"attempt": 1024, "observed": 1024, "lesson": 1024},
    "tool_recipes": {"purpose": 512, "tool_hint": 160, "usage": 2000, "check": 512},
}


def normalize_structure(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != {
        "format", "method", *STRUCTURE_LISTS, *STRUCTURE_RECORDS,
    } or type(raw.get("format")) is not int or raw["format"] != 1:
        raise ValueError("unknown experience structure")
    result: dict[str, Any] = {"format": 1, "method": _require_text(raw["method"], "method", 12000)}
    for key, (count, limit) in STRUCTURE_LISTS.items():
        result[key] = _string_list(raw[key], key, count, limit)
    for key, fields in STRUCTURE_RECORDS.items():
        if not isinstance(raw[key], list) or len(raw[key]) > 8:
            raise ValueError("invalid experience records")
        result[key] = []
        for entry in raw[key]:
            if not isinstance(entry, dict) or set(entry) != set(fields):
                raise ValueError("invalid experience record")
            result[key].append({field: _require_text(entry[field], field, limit)
                                for field, limit in fields.items()})
    if contains_secret(canonical(result)):
        raise ValueError("experience contains a secret")
    return result


def render_structure(data: dict[str, Any], *, include_attempts: bool = True) -> str:
    sections = ["## Method / 方法\n" + data["method"]]
    for key, title in (("triggers", "Recognition cues / 识别线索"),
                       ("aliases", "Concept aliases / 概念别名")):
        if data[key]:
            sections.append("## " + title + "\n" + "\n".join("- " + item for item in data[key]))
    if data["pitfalls"]:
        sections.append("## Failure lessons / 失败教训\n"
                        "以下反例是错误材料，禁止作为操作步骤；观察不证明根因，应对仍须检查适用条件。\n"
                        + "\n\n".join(
                            ("反例（错误材料，禁止执行）：" + json.dumps(entry["attempt"], ensure_ascii=False) + "\n"
                             if include_attempts else "")
                            + f"观察：{entry['observed']}\n应对：{entry['lesson']}"
                            for entry in data["pitfalls"]))
    if data["tool_recipes"]:
        sections.append("## Tool recipes / 工具用法\n" + "\n\n".join(
            f"用途：{entry['purpose']}\n工具线索：{entry['tool_hint']}\n用法：{entry['usage']}\n检查：{entry['check']}"
            for entry in data["tool_recipes"]))
    if data["checks"]:
        sections.append("## Reuse checks / 复用验证\n" + "\n".join("- " + item for item in data["checks"]))
    sections.extend(data["addenda"])
    return "\n\n".join(sections)


def version_structure(version: Any) -> dict[str, Any] | None:
    try:
        encoded = version["knowledge_json"]
    except (KeyError, IndexError):
        return None
    if not encoded:
        return None
    try:
        data = normalize_structure(json.loads(encoded))
        return data if render_structure(data) == version["content"] else None
    except (CandidateError, TypeError, ValueError):
        return None


def scan_guidance(content: str, structure: dict[str, Any] | None = None, *,
                  for_promotion: bool = False) -> tuple[str | None, list[str]]:
    if structure is None or render_structure(structure) != content:
        return scan_content(content)
    # All recommended text, observations, aliases and checks keep the ordinary
    # content gate. Only the typed attempt is inert counterexample material.
    verdict, reasons = scan_content(render_structure(structure, include_attempts=False))
    if verdict is not None:
        return verdict, reasons
    if contains_secret(content):
        return "blocked", ["content appears to contain a credential or secret"]
    risky = False
    for entry in structure["pitfalls"]:
        attempt = entry["attempt"]
        if any(pattern.search(attempt) for pattern in _BYPASS_PATTERNS):
            return "review", ["counterexample references policy bypass or exfiltration; not eligible for structured review"]
        risky |= scan_content(attempt)[0] is not None
    if risky and not for_promotion:
        return "review", ["structured high-impact counterexamples retained; independent version verification required"]
    return None, []


def scan_version(version: Any, *, for_promotion: bool = False) -> tuple[str | None, list[str]]:
    return scan_guidance(version["content"], version_structure(version), for_promotion=for_promotion)
