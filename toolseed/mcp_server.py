"""Official MCP stdio server for ToolSeed.

Uses the Model Context Protocol Python SDK (`mcp`), exposing the five
public ToolSeed tools. The Core remains independent of the SDK; this module is
only a transport adapter.
"""
from __future__ import annotations

import argparse
import sys
import threading
from typing import Annotated, Any

_MCPServer: Any
try:
    from mcp.server import MCPServer as _ImportedMCPServer
except ModuleNotFoundError as exc:  # pragma: no cover - exercised without SDK
    _MCPServer = None
    _MCP_IMPORT_ERROR: ModuleNotFoundError | None = exc
else:
    from pydantic import Field

    _MCPServer = _ImportedMCPServer
    _MCP_IMPORT_ERROR = None

from .core.api import ToolSeed
from .core.learning import EXPERIENCE_SCHEMA
from .core.storage import MigrationConflict

_CORE: ToolSeed | None = None
_CORE_LOCK = threading.Lock()


def get_core() -> ToolSeed:
    global _CORE
    with _CORE_LOCK:
        if _CORE is None:
            _CORE = ToolSeed()
        return _CORE


def create_server(core: ToolSeed | None = None) -> Any:
    if _MCPServer is None:
        raise RuntimeError(
            'official MCP SDK is not installed; run: pip install "mcp[cli]"'
        ) from _MCP_IMPORT_ERROR
    server = _MCPServer("ToolSeed")
    lock = threading.Lock()

    def call(method: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
        target = core if core is not None else get_core()
        # ToolSeed wraps one SQLite connection; serialize calls within this
        # MCP server process. Cross-process access is handled by SQLite WAL.
        with lock:
            return method(target, *args, **kwargs)

    @server.tool()
    def toolbox_search(
        query: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Find ready procedures that may apply to the current sub-problem.

        Normal search accepts query and optional environment/namespace context.
        For automatic recall, context.recall is {phase: task|error|tools,
        tool_hints?: string[], error_codes?: string[]}. This conservative mode
        returns at most two strong lexical matches with recall_match reasons;
        it does not establish applicability or execute the returned methods.
        """
        return call(ToolSeed.toolbox_search, query, context)

    @server.tool()
    def toolbox_save(
        candidate: dict[str, Any],
        intent: str = "",
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Submit one normalized procedure candidate for persistence.

        Full targeted revisions require target_capability_id plus base_version_id
        and base_content_hash from the full method read. A changed base is rejected;
        read the current method and reconcile rather than relabeling an old draft.
        """
        return call(ToolSeed.toolbox_save, candidate, intent, context)

    @server.tool()
    def toolbox_run(
        capability: str,
        args: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Deliver the guidance of a ready procedure capability."""
        return call(ToolSeed.toolbox_run, capability, args, options)

    @server.tool()
    def toolbox_stats() -> dict[str, Any]:
        """Read capability, search, delivery and evidence statistics."""
        return call(ToolSeed.toolbox_stats)

    @server.tool()
    def toolbox_learn(
        experience: Annotated[dict[str, Any], Field(json_schema_extra=EXPERIENCE_SCHEMA)],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Keep a worthwhile observed method, failure lesson or tool recipe.

        Search existing capabilities first; skip trivial work. Required experience:
        problem, when_to_use, method, reuse_reason, validation (actual observations
        and limits, not a claim of general success). Optional pitfalls contain
        attempt/observed/lesson; tool_recipes contain purpose/tool_hint/usage/check.
        Include checks, triggers, not_for, tags, applicability and source_refs as
        useful. To revise, pass target_capability_id, base_version_id and
        base_content_hash from the full method read, and the COMPLETE updated
        method; revisions remain candidates until separately promoted. This tool
        never runs scripts or turns agent observations into verified task success.

        After reuse, instead pass target_capability_id, reuse, validation and
        reuse_reason. reuse requires invocation_id/version_id/content_hash from
        toolbox_run, application (applied|partial|not_applied) and actions (what
        was actually used or why not). Optional amendment adds guidance/checks/
        not_for to that exact current version as a candidate. Without amendment,
        this appends observations only, preserving the method and capability ID.
        """
        return call(ToolSeed.toolbox_learn, experience, context)

    return server


def main() -> None:
    parser = argparse.ArgumentParser(prog="toolseed-mcp")
    parser.add_argument(
        "--data-dir",
        default=None,
        help="override TOOLSEED_DATA_DIR / ~/.toolseed",
    )
    parser.add_argument("--probe", action="store_true",
                        help="report runtime tools and features without opening the capability database")
    args = parser.parse_args()
    if args.probe:
        import asyncio
        import json
        from importlib.metadata import version

        from mcp import Client

        from .core.storage import MIGRATIONS, default_data_dir

        async def probe() -> list[str]:
            async with Client(create_server()) as client:
                return [item.name for item in (await client.list_tools()).tools]

        from pathlib import Path

        print(json.dumps({"ok": True, "tools": asyncio.run(probe()),
                          "core_version": version("toolseed"),
                          "schema_version": max(MIGRATIONS),
                          "module_path": str(Path(__file__).resolve()),
                          "features": {"read_only_search": True, "revision_base_binding": True},
                          "data_dir": str(Path(args.data_dir or default_data_dir()).expanduser().resolve())}))
        return
    try:
        core = ToolSeed(args.data_dir) if args.data_dir else ToolSeed()
    except MigrationConflict as exc:
        print(str(exc), file=sys.stderr)
        print(
            "run: python -m toolseed migrate-check "
            f"--data-dir {args.data_dir or '~/.toolseed'}",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    try:
        create_server(core).run()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
