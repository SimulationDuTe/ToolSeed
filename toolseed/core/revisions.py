"""Local host-runner bridge. Not a model-facing verification assertion API.

The host executes checks; Core binds their receipt and activation in one write
transaction. Like existing management APIs, this trusts the local caller, not
cryptographic attestation. It never executes procedure text or test commands.
"""
from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING, Any

from .applicability import assess_applicability
from .errors import (
    CONTRACT_VIOLATION,
    INVALID_ARGUMENT,
    POLICY_BLOCKED,
    SAVE_PERSISTENCE_FAILED,
    error_response,
)
from .evidence import EVENT_PROCEDURE_SAVED, EVENT_REUSE_LEARNED, make_signal_key
from .manifest import canonical, contains_secret, scan_content

if TYPE_CHECKING:
    from .api import ToolSeed

EVENT_REVISION_VALIDATED = "revision_validated"
BINDING = ("capability_id", "version_id", "content_hash", "base_version_id")


def rejected(message: str, reason: str = "REVISION_VALIDATION_INVALID") -> dict[str, Any]:
    return error_response(CONTRACT_VIOLATION, message, reason_code=reason)


def base_version(core: ToolSeed, version_id: str) -> str | None:
    row = core.store.db.execute(
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
    # Older reuse revisions already retain immutable source-delivery lineage.
    row = core.store.db.execute(
        "SELECT version_id FROM evidence_events WHERE event_type = ? "
        "AND json_extract(summary, '$.revision_version_id') = ? ORDER BY rowid LIMIT 1",
        (EVENT_REUSE_LEARNED, version_id),
    ).fetchone()
    return str(row["version_id"]) if row else None


def prepare(core: ToolSeed, binding: Any, environment: Any = None) -> dict[str, Any]:
    if not isinstance(binding, dict) or set(binding) != set(BINDING) or any(
        not isinstance(binding[k], str) or not 1 <= len(binding[k]) <= 160 for k in BINDING
    ):
        return error_response(INVALID_ARGUMENT, "exact capability/version/hash/base binding required")
    if environment is not None and not isinstance(environment, dict):
        return error_response(INVALID_ARGUMENT, "environment must be an object")
    version = core.registry.get_version(binding["version_id"])
    cap = core.registry.get_capability(binding["capability_id"])
    if not version or not cap or version["capability_id"] != cap["capability_id"] or version["content_hash"] != binding["content_hash"]:
        return rejected("candidate identity or content hash does not match", "REVISION_BINDING_MISMATCH")
    if cap["archived_at"] or cap["quarantined_at"] or version["status"] == "quarantined":
        return rejected("archived or quarantined capability/version cannot be validated")
    base = base_version(core, version["version_id"])
    if not base or base != binding["base_version_id"]:
        return rejected("candidate base is unknown or does not match", "REVISION_BASE_MISMATCH")
    if cap["current_version_id"] == version["version_id"] and version["status"] == "ready":
        return {"ok": True, **binding, "already_active": True}
    if cap["current_version_id"] != base:
        return rejected("current version changed; reconcile the revision first", "CURRENT_VERSION_CONFLICT")
    base_row = core.registry.get_version(base)
    if version["status"] != "candidate" or not base_row or base_row["status"] != "ready":
        return rejected("validation requires a candidate and a ready current base")
    if scan_content(version["content"])[0] is not None:
        return error_response(POLICY_BLOCKED, "candidate still requires content review")
    manifest = json.loads(version["manifest_json"])
    applicability = assess_applicability(manifest, environment or {})
    if applicability["status"] == "incompatible":
        return rejected("candidate does not fit the supplied host environment", "APPLICABILITY_MISMATCH")
    latest = core.store.db.execute(
        "SELECT summary FROM evidence_events WHERE event_type = ? AND version_id = ? ORDER BY rowid DESC LIMIT 1",
        (EVENT_REVISION_VALIDATED, version["version_id"]),
    ).fetchone()
    return {"ok": True, **binding, "already_active": False, "purpose": "candidate_validation_only",
            "content": version["content"], "manifest": manifest, "applicability_check": applicability,
            "previous_validation": json.loads(latest["summary"])["receipt"] if latest else None}


def _receipt(raw: Any) -> dict[str, Any] | None:
    keys = {"binding", "run_id", "plan_hash", "cases"}
    if not isinstance(raw, dict) or set(raw) != keys:
        return None
    try:
        encoded = canonical(raw)
    except (TypeError, ValueError):
        return None
    if len(encoded.encode("utf-8")) > 16384 or contains_secret(encoded):
        return None
    for key, limit in (("run_id", 160), ("plan_hash", 80)):
        if not isinstance(raw[key], str) or not 1 <= len(raw[key]) <= limit:
            return None
    cases = raw["cases"]
    if not isinstance(cases, list) or not 2 <= len(cases) <= 8:
        return None
    ids: set[str] = set()
    roles = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != {"id", "role", "purpose", "tool", "status", "assertion_count", "failed_assertions", "result_hash"}:
            return None
        for key, limit in (("id", 80), ("purpose", 240), ("tool", 160), ("result_hash", 80)):
            if not isinstance(case[key], str) or not 1 <= len(case[key]) <= limit:
                return None
        if case["id"] in ids or case["role"] not in ("new", "regression") or case["status"] not in ("passed", "failed", "skipped"):
            return None
        count, failures = case["assertion_count"], case["failed_assertions"]
        if type(count) is not int or not 1 <= count <= 8 or not isinstance(failures, list) or len(failures) > count:
            return None
        if any(type(n) is not int or not 0 <= n < count for n in failures):
            return None
        if case["status"] != "failed" and failures:
            return None
        ids.add(case["id"])
        roles.add(case["role"])
    if roles != {"new", "regression"} or all(c["status"] == "skipped" for c in cases):
        return None
    return raw


class _Aborted(Exception):
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response


def complete(core: ToolSeed, receipt: Any) -> dict[str, Any]:
    report = _receipt(receipt)
    if report is None:
        return error_response(INVALID_ARGUMENT, "invalid bounded host validation receipt")
    key = make_signal_key({"kind": EVENT_REVISION_VALIDATED, "run_id": report["run_id"]})
    try:
        with core.store.transaction(immediate=True):
            existing = core.store.db.execute("SELECT * FROM evidence_events WHERE signal_key = ?", (key,)).fetchone()
            if existing:
                stored = json.loads(existing["summary"])
                if stored["receipt"] != report:
                    return rejected("run_id already has a different receipt", "VALIDATION_RECEIPT_CONFLICT")
                cap = core.registry.get_capability(existing["capability_id"])
                version = core.registry.get_version(existing["version_id"])
                return {**stored["result"], "duplicate": True,
                        "current_version_id": cap["current_version_id"] if cap else None,
                        "active": bool(cap and version and version["status"] == "ready" and not cap["archived_at"] and not cap["quarantined_at"] and cap["current_version_id"] == existing["version_id"])}
            checked = prepare(core, report["binding"])
            if not checked.get("ok"):
                return checked
            if checked["already_active"]:
                return rejected("revision is already active; no new activation receipt needed")
            binding, cases = report["binding"], report["cases"]
            passed = all(c["status"] == "passed" for c in cases)
            outcome = "passed" if passed else "failed" if any(c["status"] == "failed" for c in cases) else "unknown"
            verification = core.record_version_verification(
                version_id=binding["version_id"], content_hash=binding["content_hash"], outcome=outcome,
                source_type="test_runner", verification_ref=report["run_id"], verification={
                    "method": "dsh_tool_assertions", "verifier": "toolseed-dsh-revision-runner",
                    "input_ref": report["plan_hash"], "artifact_ref": "revision-validation:" + report["run_id"],
                    "case_ids": [c["id"] for c in cases if c["status"] != "skipped"],
                    "regression_case_ids": [c["id"] for c in cases if c["role"] == "regression" and c["status"] != "skipped"],
                    "notes": canonical({"cases": cases, "scope": "host-executed assertions; model-selected coverage"}),
                },
            )
            if not verification.get("ok"):
                raise _Aborted(verification)
            if passed:
                promoted = core.promote_version(binding["version_id"], "host checks passed", report["run_id"])
                if not promoted.get("ok") or not promoted.get("promoted"):
                    raise _Aborted(promoted)
            result = {"ok": True, **binding, "validation_outcome": outcome, "activated": passed,
                      "active": passed, "duplicate": False, "run_id": report["run_id"], "cases": cases,
                      "current_version_id": binding["version_id"] if passed else binding["base_version_id"]}
            core.evidence.record(EVENT_REVISION_VALIDATED, capability_id=binding["capability_id"],
                                 version_id=binding["version_id"], content_hash=binding["content_hash"],
                                 source_type="test_runner", signal_key=key,
                                 summary=canonical({"receipt": report, "result": result}))
            return result
    except _Aborted as exc:
        return exc.response
    except (sqlite3.Error, OSError):
        return error_response(SAVE_PERSISTENCE_FAILED, "revision validation could not be durably completed")
