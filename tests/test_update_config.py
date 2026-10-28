"""Native configuration preservation and conservative data-directory selection."""
from __future__ import annotations

import json
import tomllib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from toolseed.hosts import HostInstallError
from toolseed.update_config import load_configuration, replace_toml_server
from toolseed.update_files import FileJournal

BASE = Path(__file__).resolve().parent / ".data"


class UpdateConfigurationTest(unittest.TestCase):
    def setUp(self):
        BASE.mkdir(exist_ok=True)
        self.temp = TemporaryDirectory(dir=BASE)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.cwd = self.root / "work"
        self.cwd.mkdir()
        self.data = self.root / "existing-library"

    def codex(self, extra=""):
        text = ('# keep this comment\n[mcp_servers."toolseed"]\ncommand="old"\n'
                'args=[\n "--data-dir",\n ' + json.dumps(str(self.data)) + ',\n]\n'
                'tool_timeout_sec=60\n[mcp_servers.toolseed.env]\nKEEP="value"\n'
                '[mcp_servers.other]\ncommand="other"\nargs=["keep"]\n' + extra)
        (self.home / "config.toml").write_text(text, encoding="utf-8")
        return text

    def test_toml_replacement_keeps_multiline_args_nested_env_and_other_tables(self):
        text = self.codex('[[agents]]\ncommand="untouched"\n')
        changed = replace_toml_server(text, "toolseed", "new-python", ["-m", "toolseed.mcp_server"])
        before, after = tomllib.loads(text), tomllib.loads(changed)
        before["mcp_servers"]["toolseed"].update(command="new-python", args=["-m", "toolseed.mcp_server"])
        self.assertEqual(before, after)
        self.assertIn("# keep this comment", changed)

    def test_project_override_is_updated_instead_of_shadowed_global_config(self):
        original = self.codex()
        project = self.cwd / ".codex/config.toml"
        project.parent.mkdir()
        project.write_text(original.replace('command="old"', 'command="project"'), encoding="utf-8")
        config = load_configuration("codex", self.home, self.cwd, "toolseed", None, None)
        self.assertEqual(config.path, project)
        self.assertEqual(config.data, self.data)
        self.assertEqual((self.home / "config.toml").read_text(), original)

    def test_explicit_data_mismatch_and_disabled_servers_are_rejected(self):
        self.codex()
        with self.assertRaisesRegex(HostInstallError, "不一致"):
            load_configuration("codex", self.home, self.cwd, "toolseed", str(self.root / "other"), None)
        path = self.home / "config.toml"
        path.write_text(self.codex().replace('command="old"', 'enabled=false\ncommand="old"'))
        with self.assertRaisesRegex(HostInstallError, "禁用"):
            load_configuration("codex", self.home, self.cwd, "toolseed", None, None)
        self.assertFalse(self.data.exists())

    def test_dsh_custom_tags_are_inert_and_existing_node_identity_is_preserved(self):
        profile = self.home / "profiles/desktop"
        profile.mkdir(parents=True)
        (profile / "package.json").write_text('{}')
        original = [{"insert": [{"id": "custom-mcp-id", "name": "@deepseek-ai/dsh-mcp-client", "config": {
            "serverName": "toolseed", "transport": "stdio", "command": "old-pythonw",
            "args": ["-c", "wrapper", "old-mcp", "--data-dir", str(self.data)], "env": {"KEEP": "yes"}}}]}]
        (self.home / "cordis.patch.yml").write_text(yaml.safe_dump(original) + '\n- id: unrelated\n  config: !!js "throw Error(1)"\n')
        patch = profile / "cordis.patch.yml"
        patch.write_text('# original profile comment\n- id: unrelated\n  disabled: false\n')
        config = load_configuration("dsh", self.home, self.cwd, "toolseed", None, None)
        self.assertEqual(config.dsh_id, "custom-mcp-id")
        self.assertEqual(config.data, self.data)
        journal = FileJournal(self.root / "backup")
        journal.watch(patch)
        journal.preflight()
        python = self.root / "runtime/python.exe"
        config.write_runtime(journal, python)
        self.assertIn('# original profile comment', patch.read_text())
        actual = load_configuration("dsh", self.home, self.cwd, "toolseed", None, None)
        self.assertEqual(actual.server["env"], {"KEEP": "yes"})
        self.assertIn(str(python), [actual.server["command"], *actual.server["args"]])
        self.assertEqual(actual.dsh_id, "custom-mcp-id")
        self.assertTrue(journal.rollback()["ok"])

    def test_new_dsh_registration_is_valid_yaml_and_repeated_write_does_not_duplicate(self):
        profile = self.home / "profiles/desktop"
        profile.mkdir(parents=True)
        (profile / "package.json").write_text('{}')
        config = load_configuration("dsh", self.home, self.cwd, "toolseed", str(self.data), None)
        journal = FileJournal(self.root / "backup")
        journal.watch(config.path)
        journal.preflight()
        for _ in range(2):
            config.write_runtime(journal, self.root / "new-python")
            config = load_configuration("dsh", self.home, self.cwd, "toolseed", None, None)
        parsed = yaml.safe_load(config.path.read_text())
        # Once created, the managed block must remain an insertion (not become a
        # dangling id override when the same block is replaced on the next update).
        self.assertIn("insert", parsed[0])
        self.assertEqual(config.path.read_text().count("# BEGIN TOOLSEED MCP"), 1)


class FileJournalTest(unittest.TestCase):
    def test_rollback_restores_exact_bytes_but_preserves_a_later_user_edit(self):
        BASE.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=BASE) as directory:
            root = Path(directory)
            path = root / "config"
            path.write_bytes(b"original\r\n")
            journal = FileJournal(root / "backup")
            journal.watch(path)
            journal.preflight()
            journal.write(path, b"upgrade")
            self.assertTrue(journal.rollback()["ok"])
            self.assertEqual(path.read_bytes(), b"original\r\n")
            journal = FileJournal(root / "backup-again")
            journal.watch(path)
            journal.write(path, b"upgrade")
            path.write_bytes(b"user-edit")
            self.assertFalse(journal.rollback()["ok"])
            self.assertEqual(path.read_bytes(), b"user-edit")

    def test_concurrent_configuration_change_stops_update(self):
        BASE.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=BASE) as directory:
            path = Path(directory) / "config"
            path.write_bytes(b"before")
            journal = FileJournal(Path(directory) / "backup")
            journal.watch(path)
            path.write_bytes(b"user-change")
            with self.assertRaises(HostInstallError):
                journal.write(path, b"installer-change")
            self.assertEqual(path.read_bytes(), b"user-change")
