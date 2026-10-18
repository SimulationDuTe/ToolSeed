"""Command line entry point for local inspection and management."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, cast

from .core.api import ToolSeed
from .core.migration import (
    flatten_merge_graph,
    inspect_duplicate_identities,
    repair_duplicate_identities,
)
from .core.storage import MigrationConflict


def _payload(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise SystemExit("payload must be a JSON object")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="toolseed")
    parser.add_argument(
        "operation",
        choices=[
            "search",
            "save",
            "run",
            "stats",
            "quarantine",
            "quarantine-version",
            "release",
            "release-version",
            "promote-version",
            "rollback",
            "version-report",
            "maintenance",
            "maintenance-run",
            "list-decisions",
            "dismiss-decision",
            "apply-decision",
            "record-observation",
            "list-observations",
            "set-observation-status",
            "expire-version-observations",
            "archive",
            "record-outcome",
            "record-verification",
            "migrate-check",
            "migrate-repair",
            "migrate-flatten",
        ],
    )
    parser.add_argument("payload", nargs="?", default=None, help="JSON object; omitted reads stdin")
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--canonical", action="append", default=None)
    parser.add_argument("--merge-capability", action="append", default=None)
    parser.add_argument("--no-backup", action="store_true")
    namespace = parser.parse_args(argv)

    if namespace.operation == "migrate-check":
        result = inspect_duplicate_identities(namespace.data_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 2

    if namespace.operation == "migrate-repair":
        if not namespace.canonical:
            print(json.dumps({"ok": False, "error": "--canonical is required"}, indent=2))
            return 2
        result = repair_duplicate_identities(
            namespace.data_dir,
            namespace.canonical,
            merge_capabilities=namespace.merge_capability,
            make_backup=not namespace.no_backup,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 2

    if namespace.operation == "migrate-flatten":
        if not namespace.canonical:
            print(json.dumps({"ok": False, "error": "--canonical is required"}, indent=2))
            return 2
        result = flatten_merge_graph(
            namespace.data_dir,
            namespace.canonical,
            merge_capabilities=namespace.merge_capability,
            make_backup=not namespace.no_backup,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 2

    raw = namespace.payload
    if raw is None and namespace.operation != "stats" and not sys.stdin.isatty():
        raw = sys.stdin.read() or None
    payload = _payload(raw)

    if "candidate" in payload:
        candidate = payload["candidate"]
    else:
        candidate = {k: v for k, v in payload.items() if k not in ("intent", "context")}
    intent = payload.get("intent", "")
    context = payload.get("context")

    try:
        app = ToolSeed(namespace.data_dir)
    except MigrationConflict as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "hint": (
                        "run: python -m toolseed migrate-check "
                        f"--data-dir {namespace.data_dir or '~/.toolseed'}"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    try:
        if namespace.operation == "search":
            result = app.toolbox_search(payload.get("query", ""), context)
        elif namespace.operation == "save":
            result = app.toolbox_save(candidate, intent, context)
        elif namespace.operation == "run":
            result = app.toolbox_run(
                payload.get("capability"), payload.get("args"), payload.get("options")
            )
        elif namespace.operation == "stats":
            result = app.toolbox_stats()
        elif namespace.operation == "quarantine":
            result = app.quarantine(
                payload.get("capability_id"), payload.get("reason", "manual quarantine")
            )
        elif namespace.operation == "quarantine-version":
            result = app.quarantine_version(
                payload.get("version_id"), payload.get("reason", "manual quarantine")
            )
        elif namespace.operation == "release":
            result = app.release_capability(
                payload.get("capability_id"),
                cast(str, payload.get("reason")),
                payload.get("evidence_ref"),
            )
        elif namespace.operation == "release-version":
            result = app.release_version(
                payload.get("version_id"),
                cast(str, payload.get("reason")),
                payload.get("evidence_ref"),
            )
        elif namespace.operation == "promote-version":
            result = app.promote_version(
                payload.get("version_id"),
                cast(str, payload.get("reason")),
                payload.get("evidence_ref"),
            )
        elif namespace.operation == "rollback":
            result = app.rollback_version(
                payload.get("capability_id"),
                payload.get("version_id"),
                payload.get("reason"),
                payload.get("evidence_ref"),
            )
        elif namespace.operation == "version-report":
            result = app.version_report(payload.get("version_id"))
        elif namespace.operation == "maintenance":
            result = app.maintenance_report()
        elif namespace.operation == "maintenance-run":
            result = app.run_maintenance()
        elif namespace.operation == "list-decisions":
            result = app.list_evolution_decisions(
                status=payload.get("status"),
                capability_id=payload.get("capability_id"),
            )
        elif namespace.operation == "dismiss-decision":
            result = app.dismiss_evolution_decision(
                payload.get("decision_id"),
                payload.get("resolution"),
            )
        elif namespace.operation == "apply-decision":
            result = app.apply_evolution_decision(
                payload.get("decision_id"),
                payload.get("resolution"),
            )
        elif namespace.operation == "record-observation":
            result = app.record_observation(
                capability_id=payload.get("capability_id"),
                observation_type=payload.get("observation_type"),
                summary=payload.get("summary"),
                version_id=payload.get("version_id"),
                evidence_ids=payload.get("evidence_ids"),
                applicability=payload.get("applicability"),
                generation_method=payload.get("generation_method", "human"),
                confidence=payload.get("confidence"),
            )
        elif namespace.operation == "list-observations":
            result = app.list_observations(
                capability_id=payload.get("capability_id"),
                version_id=payload.get("version_id"),
                status=payload.get("status"),
            )
        elif namespace.operation == "set-observation-status":
            result = app.set_observation_status(
                payload.get("observation_id"),
                payload.get("status"),
                payload.get("reason"),
            )
        elif namespace.operation == "expire-version-observations":
            result = app.expire_version_observations(
                payload.get("version_id"),
                payload.get("reason_code", "policy_or_environment_changed"),
            )
        elif namespace.operation == "record-verification":
            result = app.record_version_verification(
                version_id=payload.get("version_id"),
                content_hash=payload.get("content_hash"),
                outcome=payload.get("outcome"),
                source_type=payload.get("source_type"),
                verification_ref=payload.get("verification_ref"),
                verification=payload.get("verification"),
            )
        elif namespace.operation == "archive":
            result = app.archive(
                payload.get("capability_id"), payload.get("reason", "manual archive")
            )
        else:
            result = app.record_task_outcome(
                capability_id=payload.get("capability_id"),
                version_id=payload.get("version_id"),
                invocation_id=payload.get("invocation_id"),
                outcome=payload.get("outcome"),
                source_type=payload.get("source_type"),
                task_id=payload.get("task_id"),
                summary=payload.get("summary"),
            )
    finally:
        app.close()

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
