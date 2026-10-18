"""Verify a ToolSeed wheel from outside the source tree.

Run with the interpreter of a clean environment where the wheel was installed.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import importlib.resources
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _console_script() -> Path:
    name = "toolseed-mcp.exe" if os.name == "nt" else "toolseed-mcp"
    script = Path(sys.executable).with_name(name)
    if not script.exists():
        raise AssertionError(f"console script missing: {script}")
    return script


def _clean_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    return env


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", default=None)
    args = parser.parse_args()
    source_root = Path(args.source_root).resolve() if args.source_root else None

    import toolseed

    package_path = Path(toolseed.__file__).resolve()
    if source_root is not None and package_path.is_relative_to(source_root):
        raise AssertionError(f"toolseed was imported from the source tree: {package_path}")

    version = importlib.metadata.version("toolseed")
    skill = importlib.resources.files("toolseed").joinpath("skill/SKILL.md")
    if not skill.is_file():
        raise AssertionError("toolseed/skill/SKILL.md is missing from the wheel")
    if not skill.read_text(encoding="utf-8").strip():
        raise AssertionError("toolseed/skill/SKILL.md is empty")

    entry_points = {
        item.name
        for item in importlib.metadata.distribution("toolseed").entry_points
        if item.group == "console_scripts"
    }
    if "toolseed-mcp" not in entry_points:
        raise AssertionError(f"toolseed-mcp entry point missing: {entry_points}")

    script = _console_script()
    with tempfile.TemporaryDirectory() as temp:
        temp_path = Path(temp)
        help_result = subprocess.run(
            [str(script), "--help"],
            cwd=temp_path,
            env=_clean_env(),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if help_result.returncode != 0:
            raise AssertionError(
                f"toolseed-mcp --help failed: {help_result.stderr or help_result.stdout}"
            )

        from mcp import Client, StdioServerParameters

        params = StdioServerParameters(
            command=str(script),
            args=["--data-dir", str(temp_path / "data")],
            cwd=str(temp_path),
            env=_clean_env(),
        )

        async def inspect() -> tuple[list[str], dict]:
            async with Client(params) as client:
                tools = await client.list_tools()
                stats = await client.call_tool("toolbox_stats", {})
                return (
                    [tool.name for tool in tools.tools],
                    stats.structured_content or {},
                )

        names, stats = asyncio.run(inspect())
        if names != [
            "toolbox_search",
            "toolbox_save",
            "toolbox_run",
            "toolbox_stats",
        ]:
            raise AssertionError(f"unexpected MCP tools: {names}")
        if "capabilities" not in stats:
            raise AssertionError(f"unexpected stats payload: {stats}")

    print(
        f"package={package_path} version={version} "
        f"tools={names} skill={skill} entrypoint={script}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
