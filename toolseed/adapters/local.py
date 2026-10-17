"""Thin, host-agnostic adapter: exactly four registered tools (P0-SLIM §4).

The adapter declares honestly that it has no hooks, no task-end events and no
reliable task outcome channel. Nothing here may be reported as task success.
"""
from __future__ import annotations

import os
from typing import Any

from ..core.api import ToolSeed
from ..core.errors import INTERNAL_ERROR, INVALID_ARGUMENT, error_response

PROTOCOL_VERSION = 1

TOOL_SPECS: tuple[dict[str, Any], ...] = (
    {
        "name": "toolbox_search",
        "description": "Find ready capabilities that may apply to the current sub-problem.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "context": {"type": "object"}},
            "required": ["query"],
        },
    },
    {
        "name": "toolbox_save",
        "description": "Submit one normalized procedure candidate for persistence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "candidate": {"type": "object"},
                "intent": {"type": "string"},
                "context": {"type": "object"},
            },
            "required": ["candidate"],
        },
    },
    {
        "name": "toolbox_run",
        "description": "Deliver the guidance of a ready procedure capability.",
        "input_schema": {
            "type": "object",
            "properties": {
                "capability": {"type": "string"},
                "args": {"type": "object"},
                "options": {"type": "object"},
            },
            "required": ["capability"],
        },
    },
    {
        "name": "toolbox_stats",
        "description": "Read capability, search, delivery and evidence statistics.",
        "input_schema": {"type": "object", "properties": {}},
    },
)


class LocalAdapter:
    name = "local"
    protocol_version = PROTOCOL_VERSION

    def __init__(self, core: ToolSeed, context: dict[str, Any] | None = None) -> None:
        self.core = core
        self._context = dict(context or {})

    def register_tools(self) -> list[dict[str, Any]]:
        return [dict(spec) for spec in TOOL_SPECS]

    def invoke_tool(self, name: Any, args: Any) -> dict[str, Any]:
        if not isinstance(name, str):
            return error_response(INVALID_ARGUMENT, "tool name must be a string")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            return error_response(INVALID_ARGUMENT, "tool arguments must be an object")
        if name == "toolbox_search":
            return self.core.toolbox_search(args.get("query", ""), args.get("context"))
        if name == "toolbox_save":
            return self.core.toolbox_save(
                args.get("candidate"), args.get("intent", ""), args.get("context")
            )
        if name == "toolbox_run":
            return self.core.toolbox_run(
                args.get("capability"), args.get("args"), args.get("options")
            )
        if name == "toolbox_stats":
            return self.core.toolbox_stats()
        return error_response(INVALID_ARGUMENT, "unknown tool name")

    def get_context(self) -> dict[str, Any]:
        context: dict[str, Any] = {
            "workspace": os.getcwd(),
            "session_id": "unknown",
            "task_id": "unknown",
            "permission_context": "unknown",
        }
        context.update(self._context)
        return context

    def capabilities(self) -> dict[str, Any]:
        return {
            "hooks": False,
            "task_end_events": False,
            "workspace_events": False,
            "permission_confirmation": False,
            "cancellation": False,
            "reliable_task_outcome": False,
            "note": "unsupported host features are reported as unavailable, never simulated",
        }

    def emit_event(self, event: Any) -> dict[str, Any]:
        return {
            "emitted": False,
            "reason": "this adapter has no host event channel",
            "event_type": event.get("type") if isinstance(event, dict) else None,
        }

    def health_check(self) -> dict[str, Any]:
        try:
            self.core.store.db.execute("SELECT 1").fetchone()
            reachable = True
        except Exception:
            reachable = False
        return {
            "ok": reachable,
            "adapter": self.name,
            "protocol_version": self.protocol_version,
            "core_reachable": reachable,
            "error": None
            if reachable
            else {"code": INTERNAL_ERROR, "message": "core storage is not reachable"},
        }

    def translate_error(self, error: Any) -> dict[str, Any]:
        if not isinstance(error, dict):
            return {"code": INTERNAL_ERROR, "message": "unknown error", "retryable": False}
        return {
            "code": error.get("code", INTERNAL_ERROR),
            "message": error.get("message", "unknown error"),
            "retryable": bool(error.get("retryable", False)),
        }
