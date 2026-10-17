"""Command line entry point for local inspection and management."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .core.api import ToolSeed


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
            "archive",
            "record-outcome",
        ],
    )
    parser.add_argument("payload", nargs="?", default=None, help="JSON object; omitted reads stdin")
    parser.add_argument("--data-dir", default=".toolseed")
    namespace = parser.parse_args(argv)

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

    app = ToolSeed(namespace.data_dir)
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
                payload.get("reason"),
                payload.get("evidence_ref"),
            )
        elif namespace.operation == "release-version":
            result = app.release_version(
                payload.get("version_id"),
                payload.get("reason"),
                payload.get("evidence_ref"),
            )
        elif namespace.operation == "promote-version":
            result = app.promote_version(
                payload.get("version_id"),
                payload.get("reason"),
                payload.get("evidence_ref"),
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
