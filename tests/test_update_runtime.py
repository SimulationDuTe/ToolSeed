"""Pinned GitHub snapshots, runtime isolation and non-destructive migration trials."""
from __future__ import annotations

import io
import json
import sqlite3
import sys
import tarfile
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from toolseed.hosts import HostInstallError, fingerprint_tree
from toolseed.update_runtime import (
    UpdateSource,
    acquire_source,
    backup_and_check_database,
    migrate,
    verify_core_install,
)

BASE = Path(__file__).resolve().parent / ".data"


class UpdateRuntimeTest(unittest.TestCase):
    def setUp(self):
        BASE.mkdir(exist_ok=True)
        self.temp = TemporaryDirectory(dir=BASE)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_github_branch_is_resolved_once_and_archive_uses_that_exact_commit(self):
        commit = 'a' * 40
        stream = io.BytesIO()
        payloads = {'README.md': 'release fixture', 'pyproject.toml': '[project]\nversion="0.4.1"\n',
                    'toolseed/mcp_server.py': '# complete Core fixture', 'toolseed/skill/SKILL.md': '# skill',
                    'integrations/codex/src/install.mjs': '// adapter'}
        with tarfile.open(fileobj=stream, mode='w:gz') as archive:
            for relative, text in payloads.items():
                content = text.encode()
                member = tarfile.TarInfo('repo-' + commit + '/' + relative)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
        def request(url, *args):
            return json.dumps({'sha': commit}).encode() if '/commits/' in url else stream.getvalue()
        with patch('toolseed.hosts._request', side_effect=request) as http:
            result = acquire_source(self.root, 'codex', 'develop', 'owner/repo')
        self.assertEqual(http.call_count, 2)
        self.assertEqual(http.call_args_list[1].args[0], 'https://codeload.github.com/owner/repo/tar.gz/' + commit)
        self.assertEqual(result.metadata['commit_sha'], commit)
        self.assertEqual((result.tree / 'toolseed/mcp_server.py').read_text(), '# complete Core fixture')
        self.assertFalse(result.metadata['stable'])

    def test_core_changes_affect_source_identity_but_python_cache_does_not(self):
        source = self.root / 'source'
        module = source / 'toolseed/core/example.py'
        module.parent.mkdir(parents=True)
        module.write_text('original')
        initial = fingerprint_tree(source)
        cache = module.parent / '__pycache__/example.cpython-311.pyc'
        cache.parent.mkdir()
        cache.write_bytes(b'cache')
        self.assertEqual(fingerprint_tree(source), initial)
        module.write_text('changed-core')
        self.assertNotEqual(fingerprint_tree(source), initial)

    def test_runtime_must_match_package_location_version_and_source_bytes(self):
        tree = self.root / 'source'
        module = tree / 'toolseed/mcp_server.py'
        module.parent.mkdir(parents=True)
        module.write_bytes(b'expected')
        runtime = self.root / 'runtime'
        python = runtime / 'Scripts/python.exe'
        installed = runtime / 'Lib/site-packages/toolseed/mcp_server.py'
        installed.parent.mkdir(parents=True)
        installed.write_bytes(b'expected')
        source = UpdateSource(tree, {'version': '0.4.1'})
        body = {'module_path': str(installed), 'core_version': '0.4.1'}
        verify_core_install(source, python, body)
        for changed in ({**body, 'module_path': str(module)}, {**body, 'core_version': 'old'}):
            with self.assertRaises(HostInstallError):
                verify_core_install(source, python, changed)
        installed.write_bytes(b'wrong-same-version')
        with self.assertRaisesRegex(HostInstallError, '不一致'):
            verify_core_install(source, python, body)

    def test_trial_migrates_a_copy_and_real_migration_preserves_existing_records(self):
        data = self.root / 'library'
        data.mkdir()
        database = data / 'toolseed.sqlite3'
        with closing(sqlite3.connect(database)) as db, db:
            db.execute('CREATE TABLE capability_versions(version_id TEXT, content TEXT)')
            db.execute("INSERT INTO capability_versions VALUES ('existing', 'preserve this')")
            db.execute('PRAGMA user_version=6')
        result = backup_and_check_database(Path(sys.executable), data, self.root / 'backup', 7)
        self.assertTrue(result['migration_needed'])
        with closing(sqlite3.connect(database)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 6)
        with closing(sqlite3.connect(result['backup'])) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 6)
        migrate(Path(sys.executable), data)
        with closing(sqlite3.connect(database)) as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 7)
            self.assertEqual(db.execute('SELECT * FROM capability_versions').fetchone(), ('existing', 'preserve this', None))

    def test_newer_database_is_not_downgraded_and_missing_database_is_not_created(self):
        data = self.root / 'newer'
        data.mkdir()
        with closing(sqlite3.connect(data / 'toolseed.sqlite3')) as db, db:
            db.execute('PRAGMA user_version=99')
        with self.assertRaisesRegex(HostInstallError, '拒绝降级'):
            backup_and_check_database(Path(sys.executable), data, self.root / 'backup', 7)
        missing = self.root / 'missing'
        result = backup_and_check_database(Path(sys.executable), missing, self.root / 'missing-backup', 7)
        self.assertEqual(result['state'], 'uninitialized')
        self.assertFalse(missing.exists())
