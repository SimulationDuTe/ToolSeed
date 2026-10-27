"""CLI management surface (P0-SLIM §4.4, §5, §7)."""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_migrations import _add_cross_capability, _v2_database
from toolseed import cli
from toolseed.core.storage import Store

BASE = Path(__file__).resolve().parent / ".data" / "cli"

CANDIDATE = {
    "protocol_version": 1,
    "manifest": {
        "name": "cli_smoke",
        "kind": "procedure",
        "description": "CLI smoke procedure",
        "when_to_use": "testing the local CLI",
        "not_for": [],
        "tags": ["clismoke"],
        "applicability": {
            "harnesses": [],
            "operating_systems": [],
            "required_tools": [],
        },
    },
    "content": "1. Do the thing.\nRESULT: done",
}


def call(*args: str) -> tuple[int, dict]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = cli.main(list(args))
    return code, json.loads(buffer.getvalue())


class CliTest(unittest.TestCase):
    def setUp(self) -> None:
        shutil.rmtree(BASE, ignore_errors=True)

    def tearDown(self) -> None:
        shutil.rmtree(BASE, ignore_errors=True)

    def test_read_only_search_reuses_core_filters_without_writes(self) -> None:
        data = BASE / "read-only"
        _, saved = call("save", json.dumps(CANDIDATE), "--data-dir", str(data))
        database = data / "toolseed.sqlite3"
        before = database.read_bytes()
        with patch.object(Store, "_migrate", side_effect=AssertionError("must not migrate")):
            code, report = call("search", json.dumps({"query": "clismoke testing",
                                "context": {"recall": {"phase": "task"}}}),
                                "--data-dir", str(data), "--read-only")
        self.assertEqual(code, 0, report)
        self.assertEqual(report["results"][0]["capability_id"], saved["capability_id"])
        self.assertIn("recall_match", report["results"][0])
        self.assertEqual(database.read_bytes(), before)
        store = Store(data, read_only=True)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                store.db.execute("DELETE FROM capabilities")
        finally:
            store.close()

    def test_read_only_search_does_not_create_a_missing_library(self) -> None:
        data = BASE / "missing-read-only"
        code, report = call("search", '{"query":"clismoke"}',
                            "--data-dir", str(data), "--read-only")
        self.assertEqual(code, 2)
        self.assertFalse(report["ok"])
        self.assertFalse(data.exists())

    def test_read_only_search_rejects_old_or_future_schema_without_migration(self) -> None:
        for version in (2, 100):
            data = BASE / str(version)
            _v2_database(data, duplicates=False)
            database = data / "toolseed.sqlite3"
            with sqlite3.connect(database) as db:
                db.execute(f"PRAGMA user_version = {version}")
            before = database.read_bytes()
            code, report = call("search", '{"query":"clismoke"}',
                                "--data-dir", str(data), "--read-only")
            self.assertEqual(code, 2)
            self.assertIn("current schema", report["error"])
            self.assertEqual(database.read_bytes(), before)

    def test_read_only_flag_cannot_route_a_write_operation(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            cli.main(["learn", "{}", "--data-dir", str(BASE), "--read-only"])
        self.assertEqual(error.exception.code, 2)
        self.assertFalse(BASE.exists())

    def test_migrate_repair_cross_capability_from_cli(self) -> None:
        data = BASE / "migrate-cross"
        _v2_database(data, duplicates=True)
        _add_cross_capability(data)

        code, report = call(
            "migrate-repair",
            "--data-dir",
            str(data),
            "--canonical",
            "ver_a",
            "--merge-capability",
            "cap_b",
            "--no-backup",
        )
        self.assertEqual(code, 0)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["merged_capabilities"], ["cap_b"])

        code, report = call("migrate-check", "--data-dir", str(data))
        self.assertEqual(code, 0)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["groups"], [])

    def test_migrate_check_and_repair_are_routed_before_core(self) -> None:
        missing = BASE / "missing"
        code, report = call("migrate-check", "--data-dir", str(missing))
        self.assertEqual(code, 0)
        self.assertTrue(report["read_only"])
        self.assertIn("database does not exist", report["error"])

        code, report = call(
            "migrate-repair",
            "--data-dir",
            str(missing),
            "--canonical",
            "ver_missing",
        )
        self.assertEqual(code, 2)
        self.assertFalse(report["ok"])

    def test_normal_command_reports_migration_conflict(self) -> None:
        data = BASE / "conflict"
        _v2_database(data, duplicates=True)
        code, report = call("stats", "--data-dir", str(data))
        self.assertEqual(code, 2)
        self.assertFalse(report["ok"])
        self.assertIn("migration stopped", report["error"])
        self.assertIn("migrate-check", report["hint"])

    def test_save_run_record_outcome_and_stats(self) -> None:
        code, saved = call(
            "save",
            json.dumps({"candidate": CANDIDATE, "intent": "cli smoke"}),
            "--data-dir",
            str(BASE),
        )
        self.assertEqual(code, 0)
        self.assertEqual(saved["status"], "accepted")
        self.assertEqual(saved["version_status"], "ready")

        code, delivered = call(
            "run",
            json.dumps({"capability": saved["capability_id"]}),
            "--data-dir",
            str(BASE),
        )
        self.assertEqual(code, 0)
        self.assertEqual(delivered["mode"], "agent_guided")
        self.assertEqual(delivered["task_outcome"], "unknown")

        code, outcome = call(
            "record-outcome",
            json.dumps(
                {
                    "capability_id": saved["capability_id"],
                    "version_id": saved["version_id"],
                    "invocation_id": delivered["invocation_id"],
                    "outcome": "success",
                    "source_type": "test_runner",
                    "task_id": "cli_smoke",
                }
            ),
            "--data-dir",
            str(BASE),
        )
        self.assertEqual(code, 0)
        self.assertTrue(outcome["ok"])

        code, stats = call("stats", "--data-dir", str(BASE))
        self.assertEqual(code, 0)
        self.assertEqual(stats["delivery"]["count"], 1)
        self.assertEqual(stats["task_outcomes"]["success"], 1)
        self.assertTrue(stats["task_outcomes"]["measured"])

    def test_archive_blocks_delivery(self) -> None:
        _, saved = call(
            "save",
            json.dumps({"candidate": CANDIDATE, "intent": "cli archive"}),
            "--data-dir",
            str(BASE),
        )
        code, archived = call(
            "archive",
            json.dumps({"capability_id": saved["capability_id"]}),
            "--data-dir",
            str(BASE),
        )
        self.assertEqual(code, 0)
        self.assertTrue(archived["archived"])

        _, delivered = call(
            "run",
            json.dumps({"capability": saved["capability_id"]}),
            "--data-dir",
            str(BASE),
        )
        self.assertEqual(delivered["error"]["code"], "CAPABILITY_ARCHIVED")

    def test_quarantine_then_release_restores_delivery(self) -> None:
        _, saved = call(
            "save",
            json.dumps({"candidate": CANDIDATE, "intent": "cli release"}),
            "--data-dir",
            str(BASE),
        )
        call(
            "quarantine",
            json.dumps({"capability_id": saved["capability_id"], "reason": "incident"}),
            "--data-dir",
            str(BASE),
        )
        _, blocked = call(
            "run",
            json.dumps({"capability": saved["capability_id"]}),
            "--data-dir",
            str(BASE),
        )
        self.assertEqual(blocked["error"]["code"], "CAPABILITY_QUARANTINED")

        code, released = call(
            "release",
            json.dumps(
                {
                    "capability_id": saved["capability_id"],
                    "reason": "incident reviewed",
                    "evidence_ref": "ticket-7",
                }
            ),
            "--data-dir",
            str(BASE),
        )
        self.assertEqual(code, 0)
        self.assertTrue(released["released"])

        _, delivered = call(
            "run",
            json.dumps({"capability": saved["capability_id"]}),
            "--data-dir",
            str(BASE),
        )
        self.assertTrue(delivered["ok"], delivered)

    def test_release_and_promote_version_restores_delivery(self) -> None:
        _, saved = call(
            "save",
            json.dumps({"candidate": CANDIDATE, "intent": "cli version lifecycle"}),
            "--data-dir",
            str(BASE),
        )
        call(
            "quarantine-version",
            json.dumps({"version_id": saved["version_id"], "reason": "incident"}),
            "--data-dir",
            str(BASE),
        )
        _, blocked = call(
            "run",
            json.dumps({"capability": saved["capability_id"]}),
            "--data-dir",
            str(BASE),
        )
        self.assertEqual(blocked["error"]["code"], "CAPABILITY_QUARANTINED")

        code, released = call(
            "release-version",
            json.dumps({"version_id": saved["version_id"], "reason": "reviewed"}),
            "--data-dir",
            str(BASE),
        )
        self.assertEqual(code, 0)
        self.assertTrue(released["released"])

        code, verified = call(
            "record-verification",
            json.dumps(
                {
                    "version_id": saved["version_id"],
                    "content_hash": saved["content_hash"],
                    "outcome": "passed",
                    "source_type": "test_runner",
                    "verification_ref": "cli-test:1",
                    "verification": {
                        "method": "cli-test",
                        "input_ref": "case:cli",
                        "artifact_ref": "artifact:cli",
                        "case_ids": ["case:cli"],
                    },
                }
            ),
            "--data-dir",
            str(BASE),
        )
        self.assertEqual(code, 0)
        self.assertTrue(verified["ok"], verified)

        code, promoted = call(
            "promote-version",
            json.dumps({"version_id": saved["version_id"], "reason": "content rechecked"}),
            "--data-dir",
            str(BASE),
        )
        self.assertEqual(code, 0)
        self.assertTrue(promoted["promoted"])

        _, delivered = call(
            "run",
            json.dumps({"capability": saved["capability_id"]}),
            "--data-dir",
            str(BASE),
        )
        self.assertTrue(delivered["ok"], delivered)

    def test_maintenance_report(self) -> None:
        code, report = call("maintenance", "--data-dir", str(BASE))
        self.assertEqual(code, 0)
        self.assertIn("report", report)
        self.assertIn("validity", report["report"])
