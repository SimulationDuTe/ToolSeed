"""Atomic schema migration and duplicate-identity preflight."""
from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from toolseed import ToolSeed
from toolseed.core import storage
from toolseed.core.migration import (
    flatten_merge_graph,
    inspect_duplicate_identities,
    repair_duplicate_identities,
)


def _v2_database(
    path: Path,
    *,
    duplicates: bool,
    current_version_id: str = "ver_a",
) -> None:
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
        "version_number INTEGER NOT NULL, manifest_json TEXT NOT NULL, "
        "content TEXT NOT NULL, content_hash TEXT NOT NULL, "
        "status TEXT NOT NULL, origin TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    db.execute(
        "CREATE TABLE evidence_events ("
        "event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, created_at TEXT NOT NULL, "
        "source_type TEXT NOT NULL, capability_id TEXT, version_id TEXT, "
        "invocation_id TEXT, task_id TEXT, outcome TEXT NOT NULL DEFAULT 'unknown', "
        "quantity INTEGER NOT NULL DEFAULT 0, summary TEXT)"
    )
    db.execute(
        "CREATE TABLE invocations ("
        "invocation_id TEXT PRIMARY KEY, capability_id TEXT NOT NULL, "
        "version_id TEXT NOT NULL, created_at TEXT NOT NULL, "
        "context_json TEXT, delivery_status TEXT NOT NULL, task_id TEXT)"
    )
    db.execute(
        "INSERT INTO capabilities "
        "(capability_id, name, namespace, created_at, current_version_id) "
        "VALUES ('cap_a', 'same_name', 'global', 'now', ?)",
        (current_version_id,),
    )
    rows = [
        ("ver_a", "cap_a", 1, "sha256:same"),
        ("ver_b", "cap_a", 2, "sha256:same"),
    ]
    if not duplicates:
        rows = rows[:1]
    db.executemany(
        "INSERT INTO capability_versions "
        "(version_id, capability_id, version_number, manifest_json, content, "
        " content_hash, status, origin, created_at) "
        "VALUES (?, ?, ?, '{}', '', ?, 'ready', '', 'now')",
        rows,
    )
    db.execute("PRAGMA user_version = 2")
    db.commit()
    db.close()


def _add_second_group(path: Path) -> None:
    db = sqlite3.connect(path / "toolseed.sqlite3")
    try:
        db.execute(
            "INSERT INTO capabilities "
            "(capability_id, name, namespace, created_at, current_version_id) "
            "VALUES ('cap_b', 'other_name', 'global', 'now', 'ver_c')"
        )
        db.executemany(
            "INSERT INTO capability_versions "
            "(version_id, capability_id, version_number, manifest_json, content, "
            " content_hash, status, origin, created_at) "
            "VALUES (?, 'cap_b', ?, '{}', '', ?, 'ready', '', 'now')",
            [("ver_c", 1, "sha256:other"), ("ver_d", 2, "sha256:other")],
        )
        db.commit()
    finally:
        db.close()


def _add_cross_capability(path: Path) -> None:
    db = sqlite3.connect(path / "toolseed.sqlite3")
    try:
        db.execute(
            "INSERT INTO capabilities "
            "(capability_id, name, namespace, created_at, current_version_id) "
            "VALUES ('cap_b', 'same_name', 'global', 'now', 'ver_c')"
        )
        db.execute(
            "INSERT INTO capability_versions "
            "(version_id, capability_id, version_number, manifest_json, content, "
            " content_hash, status, origin, created_at) "
            "VALUES ('ver_c', 'cap_b', 1, '{}', '', 'sha256:same', 'ready', '', 'now')"
        )
        db.commit()
    finally:
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

    def test_inspect_reports_duplicate_groups_without_writing(self) -> None:
        data = self.root / "inspect"
        _v2_database(data, duplicates=True)

        report = inspect_duplicate_identities(data)
        self.assertFalse(report["ok"], report)
        self.assertTrue(report["read_only"])
        self.assertEqual(report["schema_version"], 2)
        self.assertEqual(report["group_count"], 1)
        self.assertEqual(report["duplicate_version_count"], 2)
        group = report["groups"][0]
        self.assertEqual(group["name"], "same_name")
        self.assertEqual(group["count"], 2)
        self.assertEqual(group["suggested_canonical"], "ver_a")
        self.assertEqual(len(group["versions"]), 2)
        self.assertTrue(group["versions"][0]["is_current"])
        self.assertEqual(group["versions"][0]["references"]["invocations"], 0)

        db = sqlite3.connect(data / "toolseed.sqlite3")
        try:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
        finally:
            db.close()
        self.assertNotIn("namespace", _column_names(data, "capability_versions"))

    def test_inspect_clean_database_is_ok(self) -> None:
        data = self.root / "clean"
        _v2_database(data, duplicates=False)
        report = inspect_duplicate_identities(data)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["groups"], [])
        self.assertEqual(report["duplicate_version_count"], 0)

    def test_repair_merges_one_group_without_changing_lifecycle_or_refs(self) -> None:
        data = self.root / "repair"
        _v2_database(data, duplicates=True)

        report = repair_duplicate_identities(
            data, "ver_a", make_backup=False
        )
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["groups_before"], 1)
        self.assertEqual(report["groups_after"], 0)
        self.assertEqual(report["schema_version"], 6)
        self.assertEqual([item["version_id"] for item in report["merged"]], ["ver_b"])

        db = sqlite3.connect(data / "toolseed.sqlite3")
        db.row_factory = sqlite3.Row
        try:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 6)
            row = db.execute(
                "SELECT status, duplicate_of FROM capability_versions "
                "WHERE version_id = 'ver_b'"
            ).fetchone()
            self.assertEqual(row["status"], "ready")
            self.assertEqual(row["duplicate_of"], "ver_a")
            audit = db.execute(
                "SELECT COUNT(*) AS n FROM evidence_events WHERE event_type = 'version_merged'"
            ).fetchone()["n"]
            self.assertEqual(audit, 1)
        finally:
            db.close()

        core = ToolSeed(str(data))
        try:
            capability, version = core.registry.find_by_identity(
                "global", "same_name", "sha256:same"
            )
            self.assertIsNotNone(capability)
            self.assertIsNotNone(version)
            self.assertEqual(version["version_id"], "ver_a")
        finally:
            core.close()

        again = repair_duplicate_identities(data, "ver_a", make_backup=False)
        self.assertTrue(again["ok"], again)
        self.assertTrue(again.get("already_repaired"))

    def test_repair_rejects_canonical_outside_group(self) -> None:
        data = self.root / "repair-bad"
        _v2_database(data, duplicates=True)
        report = repair_duplicate_identities(data, "ver_missing", make_backup=False)
        self.assertFalse(report["ok"])
        self.assertIn("not in any duplicate group", report["error"])

    def test_repair_multiple_groups_in_one_transaction(self) -> None:
        data = self.root / "repair-multi"
        _v2_database(data, duplicates=True)
        _add_second_group(data)
        before = inspect_duplicate_identities(data)
        self.assertEqual(before["group_count"], 2)

        report = repair_duplicate_identities(
            data, ["ver_a", "ver_c"], make_backup=False
        )
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["groups_before"], 2)
        self.assertEqual(report["groups_after"], 0)
        self.assertEqual(
            {item["version_id"] for item in report["merged"]}, {"ver_b", "ver_d"}
        )

        db = sqlite3.connect(data / "toolseed.sqlite3")
        db.row_factory = sqlite3.Row
        try:
            rows = {
                row["version_id"]: row["duplicate_of"]
                for row in db.execute(
                    "SELECT version_id, duplicate_of FROM capability_versions"
                )
            }
            self.assertEqual(rows["ver_b"], "ver_a")
            self.assertEqual(rows["ver_d"], "ver_c")
            self.assertIsNone(rows["ver_a"])
            self.assertIsNone(rows["ver_c"])
        finally:
            db.close()

        core = ToolSeed(str(data))
        try:
            self.assertEqual(core.store.schema_version, 6)
        finally:
            core.close()

    def test_repair_requires_all_groups_and_one_canonical_per_group(self) -> None:
        data = self.root / "repair-missing"
        _v2_database(data, duplicates=True)
        _add_second_group(data)

        missing = repair_duplicate_identities(data, ["ver_a"], make_backup=False)
        self.assertFalse(missing["ok"])
        self.assertIn("missing canonical", missing["error"])

        duplicate = repair_duplicate_identities(
            data, ["ver_a", "ver_b"], make_backup=False
        )
        self.assertFalse(duplicate["ok"])
        self.assertIn("multiple canonicals", duplicate["error"])

        db = sqlite3.connect(data / "toolseed.sqlite3")
        try:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
        finally:
            db.close()

    def _v5_after_repair(self, name: str) -> Path:
        data = self.root / name
        _v2_database(data, duplicates=True)
        report = repair_duplicate_identities(data, "ver_a", make_backup=False)
        self.assertTrue(report["ok"], report)
        return data

    def _set_duplicate_of(self, data: Path, version_id: str, target: str) -> None:
        db = sqlite3.connect(data / "toolseed.sqlite3")
        try:
            db.execute(
                "UPDATE capability_versions SET duplicate_of = ? WHERE version_id = ?",
                (target, version_id),
            )
            db.commit()
        finally:
            db.close()

    def test_merge_graph_reports_self_and_missing_links(self) -> None:
        data = self._v5_after_repair("graph-self")
        self._set_duplicate_of(data, "ver_b", "ver_b")
        report = inspect_duplicate_identities(data)
        self.assertFalse(report["ok"])
        self.assertEqual(report["merge_issue_count"], 1)
        self.assertEqual(report["merge_issues"][0]["kind"], "self")

        missing = self.root / "graph-missing"
        _v2_database(missing, duplicates=True)
        self.assertTrue(
            repair_duplicate_identities(missing, "ver_a", make_backup=False)["ok"]
        )
        self._set_duplicate_of(missing, "ver_b", "ver_missing")
        report = inspect_duplicate_identities(missing)
        self.assertEqual(report["merge_issues"][0]["kind"], "missing_target")

    def test_merge_graph_reports_cycle_and_chain(self) -> None:
        cycle = self._v5_after_repair("graph-cycle")
        self._set_duplicate_of(cycle, "ver_a", "ver_b")
        self._set_duplicate_of(cycle, "ver_b", "ver_a")
        report = inspect_duplicate_identities(cycle)
        kinds = {issue["kind"] for issue in report["merge_issues"]}
        self.assertIn("cycle", kinds)
        refused = repair_duplicate_identities(cycle, "ver_a", make_backup=False)
        self.assertFalse(refused["ok"])
        self.assertIn("invalid links", refused["error"])

        chain = self._v5_after_repair("graph-chain")
        db = sqlite3.connect(chain / "toolseed.sqlite3")
        try:
            db.execute(
                "INSERT INTO capability_versions "
                "(version_id, capability_id, version_number, manifest_json, content, "
                " content_hash, status, origin, created_at, namespace, name) "
                "VALUES ('ver_c', 'cap_a', 3, '{}', '', 'sha256:third', "
                "'ready', '', 'now', 'global', 'same_name')"
            )
            db.commit()
        finally:
            db.close()
        self._set_duplicate_of(chain, "ver_b", "ver_c")
        self._set_duplicate_of(chain, "ver_c", "ver_a")
        report = inspect_duplicate_identities(chain)
        kinds = {issue["kind"] for issue in report["merge_issues"]}
        self.assertIn("chain", kinds)

    def test_repair_cross_capability_requires_explicit_archive(self) -> None:
        data = self.root / "repair-cross"
        _v2_database(data, duplicates=True)
        _add_cross_capability(data)

        blocked = repair_duplicate_identities(data, "ver_a", make_backup=False)
        self.assertFalse(blocked["ok"])
        self.assertIn("--merge-capability", blocked["error"])

        unknown = repair_duplicate_identities(
            data,
            "ver_a",
            merge_capabilities=["cap_missing"],
            make_backup=False,
        )
        self.assertFalse(unknown["ok"])
        self.assertIn("not part of any duplicate group", unknown["error"])

        report = repair_duplicate_identities(
            data,
            "ver_a",
            merge_capabilities=["cap_b"],
            make_backup=False,
        )
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["merged_capabilities"], ["cap_b"])

        db = sqlite3.connect(data / "toolseed.sqlite3")
        db.row_factory = sqlite3.Row
        try:
            capability = db.execute(
                "SELECT archived_at FROM capabilities WHERE capability_id = 'cap_b'"
            ).fetchone()
            self.assertIsNotNone(capability["archived_at"])
            version = db.execute(
                "SELECT duplicate_of FROM capability_versions WHERE version_id = 'ver_c'"
            ).fetchone()
            self.assertEqual(version["duplicate_of"], "ver_a")
        finally:
            db.close()

        core = ToolSeed(str(data))
        try:
            blocked_run = core.toolbox_run("cap_b")
            self.assertEqual(blocked_run["error"]["code"], "CAPABILITY_ARCHIVED")
        finally:
            core.close()

    def test_merge_graph_reports_cross_capability_until_source_is_archived(self) -> None:
        data = self._v5_after_repair("graph-cross")
        db = sqlite3.connect(data / "toolseed.sqlite3")
        try:
            db.execute(
                "INSERT INTO capabilities "
                "(capability_id, name, namespace, created_at, current_version_id) "
                "VALUES ('cap_b', 'same_name', 'global', 'now', 'ver_c')"
            )
            db.execute(
                "INSERT INTO capability_versions "
                "(version_id, capability_id, version_number, manifest_json, content, "
                " content_hash, status, origin, created_at, namespace, name, duplicate_of) "
                "VALUES ('ver_c', 'cap_b', 1, '{}', '', 'sha256:same', "
                "'ready', '', 'now', 'global', 'same_name', 'ver_a')"
            )
            db.commit()
        finally:
            db.close()

        report = inspect_duplicate_identities(data)
        self.assertEqual(report["merge_issue_count"], 1)
        self.assertEqual(report["merge_issues"][0]["kind"], "cross_capability")

        db = sqlite3.connect(data / "toolseed.sqlite3")
        try:
            db.execute(
                "UPDATE capabilities SET archived_at = 'now' WHERE capability_id = 'cap_b'"
            )
            db.commit()
        finally:
            db.close()
        report = inspect_duplicate_identities(data)
        self.assertEqual(report["merge_issue_count"], 0)

    def test_flatten_cycle_and_chain(self) -> None:
        cycle = self._v5_after_repair("flatten-cycle")
        self._set_duplicate_of(cycle, "ver_a", "ver_b")
        self._set_duplicate_of(cycle, "ver_b", "ver_a")
        report = flatten_merge_graph(cycle, "ver_a", make_backup=False)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["components_after"], 0)
        db = sqlite3.connect(cycle / "toolseed.sqlite3")
        db.row_factory = sqlite3.Row
        try:
            rows = {
                row["version_id"]: row["duplicate_of"]
                for row in db.execute(
                    "SELECT version_id, duplicate_of FROM capability_versions"
                )
            }
            self.assertIsNone(rows["ver_a"])
            self.assertEqual(rows["ver_b"], "ver_a")
        finally:
            db.close()

        chain = self._v5_after_repair("flatten-chain")
        db = sqlite3.connect(chain / "toolseed.sqlite3")
        try:
            db.execute(
                "INSERT INTO capability_versions "
                "(version_id, capability_id, version_number, manifest_json, content, "
                " content_hash, status, origin, created_at, namespace, name) "
                "VALUES ('ver_c', 'cap_a', 3, '{}', '', 'sha256:third', "
                "'ready', '', 'now', 'global', 'same_name')"
            )
            db.commit()
        finally:
            db.close()
        self._set_duplicate_of(chain, "ver_b", "ver_c")
        self._set_duplicate_of(chain, "ver_c", "ver_a")
        report = flatten_merge_graph(chain, "ver_a", make_backup=False)
        self.assertTrue(report["ok"], report)
        report = inspect_duplicate_identities(chain)
        self.assertEqual(report["merge_issue_count"], 0)

    def test_flatten_rejects_missing_component_canonical(self) -> None:
        data = self._v5_after_repair("flatten-missing")
        self._set_duplicate_of(data, "ver_b", "ver_missing")
        report = flatten_merge_graph(data, "ver_unknown", make_backup=False)
        self.assertFalse(report["ok"])
        self.assertIn("does not exist", report["error"])

    def test_repair_preserves_current_pointer_and_references(self) -> None:
        data = self.root / "repair-current"
        _v2_database(data, duplicates=True, current_version_id="ver_b")
        db = sqlite3.connect(data / "toolseed.sqlite3")
        try:
            db.execute(
                "INSERT INTO invocations "
                "(invocation_id, capability_id, version_id, created_at, delivery_status) "
                "VALUES ('inv_b', 'cap_a', 'ver_b', 'now', 'guidance_delivered')"
            )
            db.execute(
                "INSERT INTO evidence_events "
                "(event_id, event_type, created_at, source_type, capability_id, "
                " version_id, outcome, quantity) "
                "VALUES ('ev_b', 'procedure_delivered', 'now', 'core', "
                "'cap_a', 'ver_b', 'unknown', 1)"
            )
            db.commit()
        finally:
            db.close()

        report = repair_duplicate_identities(data, "ver_a", make_backup=False)
        self.assertTrue(report["ok"], report)
        merged = report["merged"][0]
        self.assertTrue(merged["is_current"])
        self.assertEqual(merged["references"]["invocations"], 1)
        self.assertEqual(merged["references"]["evidence_events"], 1)

        db = sqlite3.connect(data / "toolseed.sqlite3")
        db.row_factory = sqlite3.Row
        try:
            capability = db.execute(
                "SELECT current_version_id FROM capabilities WHERE capability_id = 'cap_a'"
            ).fetchone()
            self.assertEqual(capability["current_version_id"], "ver_b")
            invocation = db.execute(
                "SELECT version_id FROM invocations WHERE invocation_id = 'inv_b'"
            ).fetchone()
            self.assertEqual(invocation["version_id"], "ver_b")
            evidence = db.execute(
                "SELECT version_id FROM evidence_events WHERE event_id = 'ev_b'"
            ).fetchone()
            self.assertEqual(evidence["version_id"], "ver_b")
        finally:
            db.close()

    def test_repair_creates_backup_when_requested(self) -> None:
        data = self.root / "repair-backup"
        _v2_database(data, duplicates=True)
        report = repair_duplicate_identities(data, "ver_a", make_backup=True)
        self.assertTrue(report["ok"], report)
        backup = Path(report["backup"])
        self.assertTrue(backup.exists())
        backup_db = sqlite3.connect(backup)
        try:
            self.assertEqual(backup_db.execute("PRAGMA user_version").fetchone()[0], 2)
        finally:
            backup_db.close()

    def test_v3_full_index_upgrades_to_partial_index(self) -> None:
        data = self.root / "v3-upgrade"
        _v2_database(data, duplicates=False)
        db = sqlite3.connect(data / "toolseed.sqlite3")
        try:
            db.execute(
                "ALTER TABLE capability_versions ADD COLUMN namespace "
                "TEXT NOT NULL DEFAULT 'global'"
            )
            db.execute(
                "ALTER TABLE capability_versions ADD COLUMN name "
                "TEXT NOT NULL DEFAULT ''"
            )
            db.execute(
                "UPDATE capability_versions SET namespace = 'global', name = 'same_name'"
            )
            db.execute(
                "CREATE UNIQUE INDEX idx_versions_identity "
                "ON capability_versions(namespace, name, content_hash)"
            )
            db.execute("PRAGMA user_version = 3")
            db.commit()
        finally:
            db.close()

        core = ToolSeed(str(data))
        try:
            self.assertEqual(core.store.schema_version, 6)
            columns = {
                row["name"]
                for row in core.store.db.execute(
                    "PRAGMA table_info(capability_versions)"
                )
            }
            self.assertIn("duplicate_of", columns)
            sql = core.store.db.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type = 'index' AND name = 'idx_versions_identity'"
            ).fetchone()["sql"]
            self.assertIn("WHERE duplicate_of IS NULL", sql)
        finally:
            core.close()
