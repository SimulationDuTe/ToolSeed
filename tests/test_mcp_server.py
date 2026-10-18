"""Official MCP SDK integration smoke tests (skipped when mcp is absent)."""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import unittest
from pathlib import Path

from tests.helpers import CoreTest

HAS_MCP = importlib.util.find_spec("mcp") is not None


@unittest.skipIf(HAS_MCP, "official SDK is installed; missing-SDK path is not applicable")
class MissingMCPSdkTest(unittest.TestCase):
    def test_missing_sdk_has_actionable_error(self) -> None:
        from toolseed.mcp_server import create_server

        with self.assertRaisesRegex(RuntimeError, "mcp"):
            create_server()


@unittest.skipUnless(HAS_MCP, "official mcp Python SDK is not installed")
class MCPServerTest(CoreTest):
    case = "mcp"

    def test_server_exposes_exactly_four_tools(self) -> None:
        from mcp import Client

        from toolseed.mcp_server import create_server

        server = create_server(self.core)

        async def inspect() -> list[str]:
            async with Client(server) as client:
                result = await client.list_tools()
                return [tool.name for tool in result.tools]

        names = asyncio.run(inspect())
        self.assertEqual(
            names,
            ["toolbox_search", "toolbox_save", "toolbox_run", "toolbox_stats"],
        )

    def test_tool_call_returns_structured_stats(self) -> None:
        from mcp import Client

        from toolseed.mcp_server import create_server

        server = create_server(self.core)

        async def stats() -> dict:
            async with Client(server) as client:
                result = await client.call_tool("toolbox_stats", {})
                return result.structured_content or {}

        payload = asyncio.run(stats())
        self.assertIn("capabilities", payload)
        self.assertIn("versions", payload)

    @unittest.skipIf(
        os.environ.get("TOOLSEED_SKIP_STDIO_TEST") == "1",
        "sandbox blocks subprocess pipe creation; run in CI or outside the sandbox",
    )
    def test_stdio_subprocess_exposes_the_same_tools(self) -> None:
        from mcp import Client, StdioServerParameters

        params = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "toolseed.mcp_server",
                "--data-dir",
                str(self.dir / "stdio"),
            ],
            cwd=str(Path.cwd()),
        )

        async def inspect() -> tuple[list[str], dict]:
            async with Client(params) as client:
                tools = await client.list_tools()
                stats = await client.call_tool("toolbox_stats", {})
                return (
                    [tool.name for tool in tools.tools],
                    stats.structured_content or {},
                )

        names, payload = asyncio.run(inspect())
        self.assertEqual(
            names,
            ["toolbox_search", "toolbox_save", "toolbox_run", "toolbox_stats"],
        )
        self.assertIn("capabilities", payload)
