"""Declared environment checks, not permission grants or proof of task fit."""
from __future__ import annotations

from typing import Any

FIELDS = ("harnesses", "operating_systems", "required_tools")


def assess_applicability(manifest: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Platforms are alternatives; required tools are conjunctive.

    A nonempty tool inventory is complete unless explicitly marked partial.
    Missing/empty inventories remain unknown unless completeness is explicit.
    Malformed context is never coerced into a compatibility claim.
    """
    declared_map = manifest.get("applicability") or {}
    conflicts: list[str] = []
    unknown: list[str] = []
    declared_fields = 0
    for field in FIELDS:
        declared = declared_map.get(field) or []
        if not declared:
            continue
        declared_fields += 1
        current = context.get(field)
        if not isinstance(current, list) or any(
            not isinstance(item, str) or not item.strip() for item in current
        ):
            unknown.append(field)
            continue
        wanted = {item.strip().casefold() for item in declared}
        available = {item.strip().casefold() for item in current}
        if field == "required_tools":
            complete = context.get("required_tools_complete", bool(available))
            if wanted <= available:
                continue
            if complete is True:
                conflicts.append(field)
            else:
                unknown.append(field)
        elif not available:
            unknown.append(field)
        elif not wanted & available:
            conflicts.append(field)
    status = (
        "incompatible" if conflicts else "unknown" if unknown
        else "compatible" if declared_fields else "undeclared"
    )
    return {"status": status, "conflicting_fields": conflicts, "unknown_fields": unknown}
