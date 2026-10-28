"""Complete upgrade ordering, rollback, pinned source and CLI routing contracts."""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tomllib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from toolseed.hosts import HostInstallError, active_install, write_manifest, write_pointer
from toolseed.install_cli import main
from toolseed.update_config import load_configuration
from toolseed.updater import update_host, update_lock
from toolseed.updater import verify_host as actual_verify_host

BASE = Path(__file__).resolve().parent / ".data"


class FullUpdateTest(unittest.TestCase):
    def setUp(self):
        BASE.mkdir(exist_ok=True)
        self.temp = TemporaryDirectory(dir=BASE)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.source = self.base / "source"
        for path, content in {
            "README.md": "fixture", "pyproject.toml": '[project]\nversion="0.4.1"\n',
            "toolseed/mcp_server.py": "# source fixture", "toolseed/skill/SKILL.md": "# new skill",
            "integrations/codex/src/install.mjs": "// native fixture",
        }.items():
            target = self.source / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        self.home, self.root = self.base / "home", self.base / "hosts"
        self.home.mkdir()
        self.data = self.base / "existing-data"
        self.config = self.home / "config.toml"
        self.original = '[mcp_servers.toolseed]\ncommand="old"\nargs=' + json.dumps([
            '--data-dir', str(self.data)]) + '\ntool_timeout_sec=90\n[mcp_servers.other]\ncommand="keep"\n'
        self.config.write_text(self.original, encoding="utf-8")
        old = self.root / "codex/old"
        old.mkdir(parents=True)
        write_manifest(old, {"host": "codex", "version": "old", "status": "active", "data_dir": str(self.data)})
        write_pointer(self.root / "codex", {"directory": str(old)})
        self.old_pointer = (self.root / "codex/current.json").read_bytes()
        self.steps = []
        self.probe = {"schema_version": 7, "core_version": "0.4.1"}
        self.options = {"ref": str(self.source), "root": self.root, "codex_home": str(self.home), "cwd": self.base}
        self.patches = [
            patch('toolseed.updater.prepare_core', side_effect=self.prepare),
            patch('toolseed.updater.backup_and_check_database', side_effect=self.backup),
            patch('toolseed.updater._install_codex', side_effect=self.adapter),
            patch('toolseed.updater.verify_host', side_effect=self.verify),
            patch('toolseed.updater._runtime_config', side_effect=lambda host, **kw: {
                'codex_home': os.path.normcase(str(self.home)), 'cwd': os.path.normcase(str(self.base)),
                'python': kw['python']})]
        self.mocks = [item.start() for item in self.patches]
        self.addCleanup(lambda: [item.stop() for item in reversed(self.patches)])

    def prepare(self, *args, **kwargs):
        self.steps.append('core')
        self.assertEqual(self.config.read_text(), self.original)
        return Path(sys.executable), self.probe

    def backup(self, *args, **kwargs):
        self.steps.append('trial')
        return {'state': 'uninitialized', 'changed': False}

    def adapter(self, tree, **kwargs):
        self.steps.append('dry' if kwargs['dry_run'] else 'apply')
        config = load_configuration('codex', self.home, self.base, 'toolseed', None, None)
        self.assertEqual(config.server['command'], sys.executable)
        self.assertEqual(config.server['tool_timeout_sec'], 90)
        if not kwargs['dry_run']:
            (self.home / 'hooks.json').write_text('{"native": "installed"}')
        return {'ready': True, 'checks': {'mcp_runtime': True}, '_exit_code': 0}

    def verify(self, tree, *args):
        self.steps.append('verify')
        self.assertEqual((self.home / 'skills/toolseed/SKILL.md').read_text(), '# new skill')
        self.assertEqual((self.root / 'codex/current.json').read_bytes(), self.old_pointer)
        return {'ready': True, 'activation': 'new_chat_required'}

    def test_success_activates_only_after_core_skill_mcp_and_native_verification(self):
        result = update_host('codex', **self.options)
        self.assertTrue(result['ok'], result)
        self.assertEqual(self.steps, ['core', 'trial', 'dry', 'apply', 'verify'])
        manifest = active_install(self.root, 'codex').manifest
        self.assertTrue(manifest['full_update'])
        self.assertEqual(manifest['core']['python'], sys.executable)
        self.assertEqual(manifest['data_dir'], str(self.data))
        self.assertFalse(self.data.exists())
        self.assertFalse((self.root / 'codex/.update.lock').exists())
        # A second healthy update verifies actual files and avoids reinstall.
        self.mocks[3].side_effect = lambda *a: {'ready': True}
        self.mocks[0].reset_mock()
        again = update_host('codex', **self.options)
        self.assertTrue(again['ok'], again)
        self.assertFalse(again['changed'])
        self.mocks[0].assert_not_called()

    def test_permission_error_precedes_runtime_and_library_changes(self):
        with (patch('toolseed.updater.FileJournal.preflight', side_effect=HostInstallError('HOST_NOT_WRITABLE', 'fixture')),
              self.assertRaises(HostInstallError)):
            update_host('codex', **self.options)
        self.mocks[0].assert_not_called()
        self.assertEqual(self.config.read_text(), self.original)
        self.assertEqual((self.root / 'codex/current.json').read_bytes(), self.old_pointer)

    def test_dependency_failure_preserves_active_record_and_config(self):
        self.mocks[0].side_effect = HostInstallError('PROCESS_FAILED', 'fixture dependency failure')
        result = update_host('codex', **self.options)
        self.assertFalse(result['ok'])
        self.assertTrue(result['rolled_back'])
        self.assertTrue(result['previous_active_preserved'])
        self.assertEqual(self.config.read_text(), self.original)
        self.mocks[2].assert_not_called()

    def test_retry_reuses_fetched_source_without_activating_failed_upgrade(self):
        self.mocks[0].side_effect = HostInstallError('PROCESS_FAILED', 'fixture dependency failure')
        first = update_host('codex', **self.options)
        self.assertFalse(first['ok'])
        self.assertEqual(active_install(self.root, 'codex').manifest['version'], 'old')
        self.mocks[0].side_effect = self.prepare
        second = update_host('codex', **self.options)
        self.assertTrue(second['ok'], second)
        self.assertEqual(first['failed_directory'], second['directory'])

    def test_native_failure_restores_all_changed_files_and_keeps_previous_pointer(self):
        def failed(tree, **kwargs):
            if not kwargs['dry_run']:
                (self.home / 'hooks.json').write_text('partial-native-write')
                raise HostInstallError('VERIFY_FAILED', 'fixture')
            return {'checks': {'mcp_runtime': True}}
        self.mocks[2].side_effect = failed
        result = update_host('codex', **self.options)
        self.assertFalse(result['ok'])
        self.assertTrue(result['rolled_back'], result)
        self.assertEqual(self.config.read_text(), self.original)
        self.assertFalse((self.home / 'hooks.json').exists())
        self.assertFalse((self.home / 'skills/toolseed/SKILL.md').exists())
        self.assertEqual((self.root / 'codex/current.json').read_bytes(), self.old_pointer)

    def test_failed_final_verification_restores_skill_and_never_migrates_database(self):
        self.mocks[3].side_effect = HostInstallError('VERIFY_FAILED', 'fixture')
        with patch('toolseed.updater.migrate') as migration:
            result = update_host('codex', **self.options)
        self.assertFalse(result['ok'])
        migration.assert_not_called()
        self.assertEqual(self.config.read_text(), self.original)
        self.assertFalse((self.home / 'skills/toolseed/SKILL.md').exists())

    def test_plan_pins_source_without_runtime_configuration_or_library_writes(self):
        result = update_host('codex', **self.options, plan=True)
        self.assertTrue(result['plan'])
        self.assertFalse(result['changed'])
        self.mocks[0].assert_not_called()
        self.assertEqual(self.config.read_text(), self.original)
        self.assertFalse(self.data.exists())

    def test_second_update_cannot_enter_a_host_with_an_active_update(self):
        with update_lock(self.root, 'codex'), self.assertRaisesRegex(HostInstallError, '已有升级'):
            update_host('codex', **self.options)

    def test_cli_defaults_to_full_update_and_keeps_adapter_only_opt_in(self):
        with (patch('toolseed.install_cli.update_host', return_value={'ok': True}) as complete,
              contextlib.redirect_stdout(io.StringIO())):
            self.assertEqual(main(['update', 'codex', '--ref', 'develop', '--plan']), 0)
        self.assertTrue(complete.call_args.kwargs['plan'])
        self.assertIsNone(complete.call_args.kwargs['data_dir'])
        with (patch('toolseed.install_cli.install_host', return_value={'ok': True}) as adapter,
              contextlib.redirect_stdout(io.StringIO())):
            self.assertEqual(main(['update', 'codex', '--ref', 'v0.4.1', '--adapter-only']), 0)
        self.assertTrue(adapter.call_args.kwargs['update'])

    def test_configuration_values_other_than_command_and_args_are_preserved(self):
        result = update_host('codex', **self.options)
        self.assertTrue(result['ok'])
        before, after = tomllib.loads(self.original), tomllib.loads(self.config.read_text())
        after['mcp_servers']['toolseed'].update({key: before['mcp_servers']['toolseed'][key] for key in ('command', 'args')})
        self.assertEqual(after, before)

    def dsh_profile(self):
        profile = self.home / 'profiles/desktop'
        profile.mkdir(parents=True)
        (profile / 'package.json').write_text('{"dependencies":{"other":"1"}}')
        patch_file = profile / 'cordis.patch.yml'
        patch_file.write_text('# keep profile\n')
        global_file = self.home / 'cordis.patch.yml'
        global_file.write_text('- insert:\n  - id: actual-existing-id\n    name: "@deepseek-ai/dsh-mcp-client"\n'
            '    config:\n      serverName: toolseed\n      transport: stdio\n      command: old\n'
            '      args: ' + json.dumps(['--data-dir', str(self.data)]) + '\n')
        plugin = self.source / 'integrations/dsh'
        plugin.mkdir()
        (plugin / 'package.json').write_text('{"files":["index.js"]}')
        (plugin / 'index.js').write_text('// new installed artifact')
        return profile, patch_file, global_file

    def test_dsh_full_update_syncs_actual_mcp_skill_and_installed_package(self):
        profile, patch_file, global_file = self.dsh_profile()
        global_before = global_file.read_bytes()
        self.mocks[3].side_effect = actual_verify_host
        def install(tree, **kwargs):
            installed = profile / 'node_modules/dsh-toolseed'
            installed.mkdir(parents=True)
            for relative in ('package.json', 'index.js'):
                (installed / relative).write_bytes((tree / 'integrations/dsh' / relative).read_bytes())
            return {'ok': True, 'installed': True}
        with (patch('toolseed.updater._install_dsh', side_effect=install),
              patch('toolseed.updater.probe_core', return_value=self.probe),
              patch('toolseed.updater.verify_core_install'), patch('toolseed.updater.check_dsh_closed')):
            result = update_host('dsh', ref=str(self.source), root=self.root, dsh_home=str(self.home), cwd=self.base)
        self.assertTrue(result['ok'], result)
        self.assertTrue(result['verification']['installed_artifacts_match'])
        self.assertEqual(global_file.read_bytes(), global_before)
        self.assertIn('# keep profile', patch_file.read_text())
        self.assertIn('actual-existing-id', patch_file.read_text())
        self.assertEqual(active_install(self.root, 'dsh').manifest['data_dir'], str(self.data))

    def test_dsh_rollback_failure_is_reported_instead_of_claiming_success(self):
        _, patch_file, _ = self.dsh_profile()
        before = patch_file.read_bytes()
        with (patch('toolseed.updater._install_dsh', side_effect=HostInstallError('DSH_INSTALL_FAILED', 'fixture')),
              patch('toolseed.updater._restore_dsh', return_value=False), patch('toolseed.updater.check_dsh_closed')):
            result = update_host('dsh', ref=str(self.source), root=self.root, dsh_home=str(self.home), cwd=self.base)
        self.assertFalse(result['ok'])
        self.assertFalse(result['rolled_back'])
        self.assertFalse(result['dsh_package_restored'])
        self.assertEqual(patch_file.read_bytes(), before)
        self.assertIsNone(active_install(self.root, 'dsh'))

    def test_running_dsh_is_refused_before_package_or_config_changes(self):
        self.dsh_profile()
        with (patch('toolseed.updater.check_dsh_closed', side_effect=HostInstallError('DSH_RUNNING', 'fixture')),
              self.assertRaises(HostInstallError)):
            update_host('dsh', ref=str(self.source), root=self.root, dsh_home=str(self.home), cwd=self.base)
        self.mocks[0].assert_not_called()
