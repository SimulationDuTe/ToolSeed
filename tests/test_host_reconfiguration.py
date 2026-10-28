"""Same source can be reconciled against a changed deployment configuration."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from tempfile import TemporaryDirectory
from unittest.mock import patch

from toolseed.hosts import active_install
from toolseed.hosts_cli import install_host
from toolseed.install_cli import _parser


class HostReconfigurationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source = self.base / "source"
        (self.source / "integrations" / "codex" / "src").mkdir(parents=True)
        (self.source / "integrations" / "codex" / "src" / "install.mjs").write_text("// fixture", encoding="utf-8")
        (self.source / "pyproject.toml").write_text('[project]\nversion="0.4.1"\n', encoding="utf-8")
        self.root = self.base / "hosts"
        self.options = {"data_dir": str(self.base / "library"),
                        "codex_home": str(self.base / "codex"),
                        "dsh_home": str(self.base / "dsh"), "cwd": self.base,
                        "python": str(self.base / "python")}
        self.git = patch("toolseed.hosts_cli._run", side_effect=lambda command, **kw:
                         CompletedProcess(command, 0, "a" * 40 if command[-1] == "HEAD" else "", ""))
        self.node = patch("toolseed.hosts_cli._node_path", return_value=str(self.base / "node"))
        self.git.start()
        self.node_mock = self.node.start()
        self.addCleanup(self.git.stop)
        self.addCleanup(self.node.stop)

    def install(self, **overrides):
        return install_host("codex", ref=str(self.source), root=self.root, **(self.options | overrides))

    def test_identical_source_and_effective_config_are_noop_without_another_snapshot(self):
        with patch("toolseed.hosts_cli._install_codex", return_value={
            "ready": True, "checks": {"mcp_runtime": True}, "_exit_code": 0,
        }) as adapter:
            first = self.install()
            second = self.install()
        self.assertTrue(first["ok"], first)
        self.assertFalse(second["changed"])
        self.assertEqual(second["reason"], "already-installed")
        self.assertEqual(adapter.call_count, 2)
        self.assertEqual(first["directory"], second["directory"])

    def test_each_runtime_change_is_applied_on_the_same_source_tree(self):
        with patch("toolseed.hosts_cli._install_codex", return_value={
            "ready": True, "checks": {"mcp_runtime": True}, "_exit_code": 0,
        }) as adapter:
            first = self.install()
            changes = {"data_dir": str(self.base / "other-data"), "python": str(self.base / "other-python"),
                       "codex_home": str(self.base / "other-home"), "mcp_server": "other_server",
                       "cwd": self.base / "other-cwd"}
            for key, value in changes.items():
                with self.subTest(key=key):
                    self.options[key] = value
                    result = self.install()
                    self.assertTrue(result["changed"], result)
                    self.assertEqual(result["directory"], first["directory"])
                    self.assertEqual(adapter.call_args.kwargs[key], Path(value) if key in
                                     ("codex_home", "data_dir") else value)
                    self.assertFalse(self.install()["changed"])
            self.node_mock.return_value = str(self.base / "other-node")
            self.assertTrue(self.install()["changed"])
        record = active_install(self.root, "codex")
        self.assertEqual(record.manifest["data_dir"], changes["data_dir"])
        pointer = json.loads((self.root / "codex" / "current.json").read_text(encoding="utf-8"))
        self.assertIsNone(pointer["previous"])

    def test_repair_and_legacy_manifest_reapply_without_source_duplication(self):
        with patch("toolseed.hosts_cli._install_codex", return_value={
            "ready": True, "checks": {"mcp_runtime": True}, "_exit_code": 0,
        }) as adapter:
            first = self.install()
            result = self.install(repair=True)
            self.assertTrue(result["changed"])
            self.assertEqual(first["directory"], result["directory"])
            record = active_install(self.root, "codex")
            del record.manifest["runtime_config"]
            (record.directory / "install.json").write_text(json.dumps(record.manifest), encoding="utf-8")
            self.assertTrue(self.install()["changed"])
            self.assertEqual(adapter.call_count, 6)

    def test_failed_same_tree_reconfiguration_preserves_last_successful_record(self):
        with patch("toolseed.hosts_cli._install_codex", return_value={
            "ready": True, "checks": {"mcp_runtime": True}, "_exit_code": 0,
        }):
            first = self.install()
        previous = active_install(self.root, "codex").manifest
        with patch("toolseed.hosts_cli._install_codex", return_value={"checks": {"mcp_runtime": False}}):
            failed = self.install(data_dir=str(self.base / "mismatch"))
        self.assertFalse(failed["ok"])
        self.assertFalse(failed["rolled_back"])
        self.assertTrue(failed["previous_active_preserved"])
        self.assertEqual(active_install(self.root, "codex").manifest, previous)
        self.assertEqual(first["directory"], failed["directory"])

    def test_dsh_configuration_changes_are_not_suppressed(self):
        (self.source / "integrations" / "dsh").mkdir()
        with patch("toolseed.hosts_cli._install_dsh", return_value={}) as adapter:
            first = install_host("dsh", ref=str(self.source), root=self.root, **self.options)
            for key, value in {"dsh_home": str(self.base / "new-dsh"), "dsh_command": "another-dsh",
                               "data_dir": str(self.base / "new-data"), "python": str(self.base / "new-python")}.items():
                with self.subTest(key=key):
                    self.options[key] = value
                    result = install_host("dsh", ref=str(self.source), root=self.root, **self.options)
                    self.assertTrue(result["changed"])
                    self.assertEqual(result["directory"], first["directory"])
            self.assertEqual(adapter.call_count, 10)

    def test_both_commands_expose_explicit_drift_repair(self):
        for command in ("install", "update"):
            self.assertTrue(_parser("toolseed").parse_args([command, "codex", "--ref", "v0.4.1", "--repair"]).repair)
