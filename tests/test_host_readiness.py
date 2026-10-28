"""A configured snapshot is not active until required runtime checks pass."""
from __future__ import annotations

import unittest
from pathlib import Path
from subprocess import CompletedProcess
from tempfile import TemporaryDirectory
from unittest.mock import patch

from toolseed.hosts_cli import install_host


class HostReadinessTest(unittest.TestCase):
    def install(self, dry, applied=None):
        repo = Path(__file__).resolve().parent.parent
        base = repo / "tests" / ".data"
        base.mkdir(exist_ok=True)
        with TemporaryDirectory(prefix="host-readiness-", dir=base) as directory:
            root = Path(directory)
            tree = root / "snapshot"
            tree.mkdir()
            (tree / "pyproject.toml").write_text('[project]\nversion="0.4.1"\n', encoding="utf-8")
            def git(command, **kwargs):
                return CompletedProcess(command, 0, "a" * 40 if command[-1] == "HEAD" else "", "")
            with (patch("toolseed.hosts_cli._run", side_effect=git),
                  patch("toolseed.hosts_cli.active_install", return_value=None),
                  patch("toolseed.hosts_cli._reusable_tree", return_value=tree),
                  patch("toolseed.hosts_cli._install_codex", side_effect=[dry, applied]) as installer):
                result = install_host("codex", ref=str(repo), root=root / "hosts")
            self.assertFalse((root / "hosts" / "codex" / "current.json").exists())
            return result, installer.call_count

    def test_incompatible_runtime_preflight_cannot_apply_or_activate_a_snapshot(self):
        result, calls = self.install({"checks": {"mcp_runtime": False}, "runtime": {"code": "MCP_RUNTIME_INCOMPATIBLE"}})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "MCP_NOT_READY")
        self.assertEqual(calls, 1)

    def test_zero_exit_without_confirmed_readiness_cannot_mark_the_snapshot_active(self):
        result, calls = self.install({"checks": {"mcp_runtime": True}},
                                     {"_exit_code": 0, "ready": False, "trust": {"status": "written-unverified"}})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "VERIFY_FAILED")
        self.assertEqual(calls, 2)
