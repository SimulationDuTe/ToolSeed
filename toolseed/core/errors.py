"""P0 error protocol.

Code names follow DESIGN §9 exactly so a later phase does not have to migrate
public error semantics.
"""
from __future__ import annotations

from typing import Any

INVALID_ARGUMENT = "INVALID_ARGUMENT"
CAPABILITY_NOT_FOUND = "CAPABILITY_NOT_FOUND"
AMBIGUOUS_CAPABILITY_NAME = "AMBIGUOUS_CAPABILITY_NAME"
CAPABILITY_NOT_READY = "CAPABILITY_NOT_READY"
UNSUPPORTED_CAPABILITY_KIND = "UNSUPPORTED_CAPABILITY_KIND"
CONTRACT_VIOLATION = "CONTRACT_VIOLATION"
POLICY_BLOCKED = "POLICY_BLOCKED"
CAPABILITY_QUARANTINED = "CAPABILITY_QUARANTINED"
CAPABILITY_ARCHIVED = "CAPABILITY_ARCHIVED"
SAVE_PERSISTENCE_FAILED = "SAVE_PERSISTENCE_FAILED"
INTERNAL_ERROR = "INTERNAL_ERROR"

ALL_CODES = frozenset(
    {
        INVALID_ARGUMENT,
        CAPABILITY_NOT_FOUND,
        AMBIGUOUS_CAPABILITY_NAME,
        CAPABILITY_NOT_READY,
        UNSUPPORTED_CAPABILITY_KIND,
        CONTRACT_VIOLATION,
        POLICY_BLOCKED,
        CAPABILITY_QUARANTINED,
        CAPABILITY_ARCHIVED,
        SAVE_PERSISTENCE_FAILED,
        INTERNAL_ERROR,
    }
)

RETRYABLE = frozenset({SAVE_PERSISTENCE_FAILED, INTERNAL_ERROR})


def error_response(
    code: str,
    message: str,
    *,
    reason_code: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if code not in ALL_CODES:
        raise ValueError(f"unknown error code: {code}")
    error = {
        "code": code,
        "message": message,
        "retryable": code in RETRYABLE,
    }
    if reason_code is not None:
        error["reason_code"] = reason_code
    if details is not None:
        error["details"] = details
    return {
        "ok": False,
        "error": error,
    }
