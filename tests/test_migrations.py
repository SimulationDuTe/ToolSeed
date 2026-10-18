"""Atomic schema migration and duplicate-identity preflight."""
from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from toolseed import ToolSeed
from toolseed.core import storage


def _v2_database(path: Path, *, duplicates: bool) -> None:
    path.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path / "toolseed.sqlite3")
    db.execute(
        "CREATE TABLE capabilities ("
        "capability_id TEXT PRIMARY KEY, name TEXT NOT NULL, "
        "namespace TEXT NOT NULL DEFAULT 'global', created_at TEXT NOT NULL, "
        "current_version_id TEXT, archived_at TEXT, quarantined_at TEXT)"
    )
    db.execute(
        "CREATE TABLE capability_versions ("
        "version_id TEXT PRIMARY KEY, capability_id TEXT NOT NULL, "
        "content_hash TEXT NOT NULL)"
    )
    db.execute(
        "INSERT INTO capabilities (capability_id, name, namespace, created_at) "
        "VALUES ('cap_a', 'same_name', 'global', 'now')"
    )
    rows = [
        ("ver_a", "cap_a", "sha256:same"),
        ("ver_b", "cap_a", "sha256:same"),
    ]
    if not duplicates:
        rows = rows[:1]
    db.executemany(
        "INSERT INTO capability_versions (version_id, capability_id, content_hash) "
        "VALUES (?, ?, ?)",
        rows,
    )
    db.execute("PRAGMA user_version = 2")
    db.commit()
    db.close()


def _column_names(path: Path, table: str) -> set[str]:
    db = sqlite3.connect(path / "toolseed.sqlite3")
    try:
        return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
    finally:
        db.close()


class MigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parent / ".data" / "migration-atomic"
        if self.root.exists():
            import shutil

            shutil.rmtree(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.root, ignore_errors=True)

    def test_duplicate_identity_stops_before_v3(self) -> None:
        data = self.root / "duplicate"
        _v2_database(data, duplicates=True)

        with self.assertRaises(storage.MigrationConflict):
            ToolSeed(str(data))

        db = sqlite3.connect(data / "toolseed.sqlite3")
        try:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
            indexes = {
                row[1]
                for row in db.execute(
                    "SELECT * FROM sqlite_master WHERE type = 'index'"
                )
            }
            self.assertNotIn("idx_versions_identity", indexes)
        finally:
            db.close()
        self.assertNotIn("namespace", _column_names(data, "capability_versions"))

    def test_failed_v3_rolls_back_ddl_and_version(self) -> None:
        data = self.root / "failed"
        _v2_database(data, duplicates=False)
        broken = (
            "ALTER TABLE capability_versions ADD COLUMN namespace "
            "TEXT NOT NULL DEFAULT 'global'; NOT VALID SQL;"
        )

        with (
            mock.patch.dict(storage.MIGRATIONS, {3: broken}),
            self.assertRaises(sqlite3.OperationalError),
        ):
            ToolSeed(str(data))

        db = sqlite3.connect(data / "toolseed.sqlite3")
        try:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
        finally:
            db.close()
        self.assertNotIn("namespace", _column_names(data, "capability_versions"))
