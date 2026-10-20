"""Legacy maintenance baselines are observations, atomic and restart-safe."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any
from unittest.mock import patch

from tests.helpers import CoreTest
from toolseed import ToolSeed
from toolseed.core.evidence import (
    ASSESSMENT_WATERMARK_KEY,
    EVENT_DEDUP_BASELINE,
    REVALIDATION_GENERATION_KEY,
    Evidence,
    make_signal_key,
)

# Deliberately do not close the connection: exercise SQLite recovery, not teardown.
_CRASH_SCRIPT = r"""
import os
import sys
from unittest.mock import patch
from toolseed import ToolSeed
from toolseed.core.evidence import EVENT_DEDUP_BASELINE, Evidence

core = ToolSeed(sys.argv[1])
exit_code = int(sys.argv[2])
original_record = Evidence.record
seen = []

def record(evidence, event_type, **kwargs):
    event_id = original_record(evidence, event_type, **kwargs)
    if event_type == EVENT_DEDUP_BASELINE:
        assert evidence.store.db.in_transaction, 'baseline already committed'
        assert evidence.store.db.execute(
            'SELECT COUNT(*) FROM evidence_events WHERE event_type = ?',
            (EVENT_DEDUP_BASELINE,),
        ).fetchone()[0] == 1
        seen.append(event_id)
        if exit_code == 23:
            os._exit(23)
    return event_id

with patch('toolseed.core.evidence.now', return_value='2026-01-01T00:00:00+00:00'):
    with patch.object(Evidence, 'record', record):
        result = core.run_maintenance()
assert result['ok'], result
assert len(seen) == 1, seen
assert not core.store.db.in_transaction, 'maintenance did not commit'
assert exit_code == 24
os._exit(24)
"""


class MaintenanceBaselineTest(CoreTest):
    case = "maintenance-baseline"

    def setUp(self) -> None:
        super().setUp()
        clock = patch("toolseed.core.evidence.now", return_value="2026-01-01T00:00:00+00:00")
        clock.start()
        self.addCleanup(clock.stop)
        self.saved = self.save()
        delivered = self.core.toolbox_run(self.saved["capability_id"])
        self.assertTrue(delivered["ok"], delivered)
        self.event_id = self.core.store.db.execute(
            "SELECT event_id FROM evidence_events WHERE invocation_id = ? "
            "AND event_type = 'procedure_delivered'", (delivered["invocation_id"],),
        ).fetchone()["event_id"]

    def _rows(self, table: str) -> list[dict[str, Any]]:
        assert table in ("evidence_events", "evidence_validity_assessments", "evolution_decisions")
        return [dict(row) for row in self.core.store.db.execute(
            f"SELECT * FROM {table} ORDER BY rowid"
        )]

    def _baselines(self) -> list[dict[str, Any]]:
        return [row for row in self._rows("evidence_events")
                if row["event_type"] == EVENT_DEDUP_BASELINE]

    def _assess(self, validity: str, reason: str = "fixture_environment_changed") -> dict[str, Any]:
        result = self.core.assess_evidence(self.event_id, validity, reason)
        self.assertTrue(result["ok"], result)
        return result["assessment"]

    def _review_delivery(self) -> dict[str, Any]:
        event = self.core.store.db.execute(
            "SELECT * FROM evidence_events WHERE event_id = ?", (self.event_id,),
        ).fetchone()
        fingerprint = self.core.evidence.version_fingerprint(self.saved["version_id"])
        self.assertEqual(event["version_id"], self.saved["version_id"])
        self.assertEqual(fingerprint["content_hash"], self.saved["content_hash"])
        # A local binding review is not an independent verification or task outcome.
        result = self.core.assess_evidence(
            self.event_id, "valid", "fixture_review:delivery_binding_and_version_hash_checked",
            fingerprint=fingerprint,
        )
        self.assertTrue(result["ok"], result)
        return result["assessment"]

    def _assess_original_events(self) -> None:
        for event in self._rows("evidence_events"):
            if event["event_id"] == self.event_id:
                self._review_delivery()
            else:
                result = self.core.assess_evidence(
                    event["event_id"], "valid", "fixture_review:original_event_checked",
                )
                self.assertTrue(result["ok"], result)
        self.assertEqual(self.core.evidence.validity_counts()["unassessed"], 0)

    def _legacy(self) -> dict[str, Any]:
        """INSERT a genuine old-format fixture; never rewrite a new decision."""
        digest = hashlib.sha1(self.event_id.encode("utf-8")).hexdigest()[:12]
        key = ":".join((
            "revalidate_evidence", "stale_evidence", self.saved["capability_id"],
            self.saved["version_id"], digest,
        ))
        payload = {
            "action": "revalidate_evidence", "reason": "stale_evidence",
            "capability_id": self.saved["capability_id"],
            "version_id": self.saved["version_id"], "evidence_ids": [self.event_id], "count": 1,
        }
        with self.core.store.transaction() as db:
            db.execute(
                "INSERT INTO evolution_decisions "
                "(decision_id, dedup_key, action, reason, capability_id, version_id, "
                "status, payload_json, created_at, updated_at) "
                "VALUES ('dec_legacy', ?, 'revalidate_evidence', 'stale_evidence', ?, ?, "
                "'proposed', ?, '2026-01-01', '2026-01-01')",
                (key, self.saved["capability_id"], self.saved["version_id"], json.dumps(payload)),
            )
        legacy = self.core.evidence.get_decision("dec_legacy")
        self.assertNotIn(ASSESSMENT_WATERMARK_KEY, legacy["payload"])
        self.assertNotIn(REVALIDATION_GENERATION_KEY, legacy["payload"])
        return legacy

    def _run(self) -> dict[str, Any]:
        result = self.core.run_maintenance()
        self.assertTrue(result["ok"], result)
        return result

    def _revalidations(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        return [item for item in result["created"] if item["action"] == "revalidate_evidence"]

    def _assert_legacy_closed(self, legacy: dict[str, Any]) -> None:
        result = self.core.apply_evolution_decision(legacy["decision_id"])
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")
        self.assertEqual(result["error"]["reason_code"], "DECISION_ASSESSMENT_WATERMARK_MISSING")
        self.assertEqual(self.core.evidence.get_decision(legacy["decision_id"]), legacy)

    def _reopen(self) -> None:
        self.core.close()
        self.core = ToolSeed(self.dir)

    def test_legacy_repeats_one_baseline_without_backfill(self) -> None:
        self._review_delivery()  # Recovery order relative to an offset-less row is unknowable.
        self._assess("stale")
        legacy = self._legacy()
        raw_legacy = self._rows("evolution_decisions")
        for _ in range(3):
            self.assertEqual(self._revalidations(self._run()), [])
            self.assertEqual(len(self._baselines()), 1)
            self._assert_legacy_closed(legacy)
        baseline = self._baselines()
        self._reopen()
        self.assertEqual(self._revalidations(self._run()), [])
        self.assertEqual(self._baselines(), baseline)
        self._review_delivery()
        self._assert_legacy_closed(legacy)  # Even a new valid cannot invent the old watermark.
        self.assertEqual(self._rows("evolution_decisions")[:1], raw_legacy)

    def test_two_connections_race_first_legacy_baseline(self) -> None:
        self._assess("stale")
        legacy = self._legacy()
        other = ToolSeed(self.dir)
        start = Barrier(2)

        def run(core: ToolSeed) -> dict[str, Any]:
            start.wait(timeout=10)
            return core.run_maintenance()

        try:
            self.assertIsNot(self.core.store.db, other.store.db)
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(run, (self.core, other)))
            for result in results:
                self.assertTrue(result["ok"], result)
                self.assertEqual(self._revalidations(result), [])
            self.assertEqual(len(self._baselines()), 1)
            self.assertEqual(other.store.db.execute(
                "SELECT COUNT(*) FROM evidence_events WHERE event_type = ?", (EVENT_DEDUP_BASELINE,),
            ).fetchone()[0], 1)
            self.assertEqual(self._revalidations(other.run_maintenance()), [])
            self.assertEqual(len(self._baselines()), 1)
            self._assert_legacy_closed(legacy)
        finally:
            other.close()

    def test_baseline_is_only_unknown_core_observation(self) -> None:
        self._assess_original_events()
        self._assess("stale")
        legacy = self._legacy()
        events = self._rows("evidence_events")
        assessments = self._rows("evidence_validity_assessments")
        validity = {event["event_id"]: self.core.evidence_validity(event["event_id"])
                    for event in events}
        before = self.core.toolbox_stats()
        self.assertEqual(self._revalidations(self._run()), [])
        after = self.core.toolbox_stats()
        self.assertEqual(self._rows("evidence_events")[:-1], events)
        self.assertEqual(self._rows("evidence_validity_assessments"), assessments)
        for event_id, original in validity.items():
            self.assertEqual(self.core.evidence_validity(event_id), original)
        for key in ("task_outcomes", "verifications"):
            self.assertEqual(after[key], before[key])
        self.assertEqual(after["evidence"]["events"], before["evidence"]["events"] + 1)
        self.assertEqual(after["evidence"]["assessments"], before["evidence"]["assessments"])
        for key in ("valid", "stale", "superseded"):
            self.assertEqual(after["evidence"]["validity"][key], before["evidence"]["validity"][key])
        self.assertEqual(after["evidence"]["validity"]["unassessed"], 1)
        baseline, = self._baselines()
        self.assertEqual(baseline["source_type"], "core")
        self.assertEqual(baseline["outcome"], "unknown")
        for key in ("capability_id", "version_id", "invocation_id", "task_id"):
            self.assertIsNone(baseline[key], key)
        self.assertEqual(json.loads(baseline["summary"]), {
            "decision_id": legacy["decision_id"],
            "generation": self.core.evidence._revalidation_generation([self.event_id]),
        })
        self.assertEqual(baseline["signal_key"], make_signal_key({
            "kind": EVENT_DEDUP_BASELINE, "decision": legacy["decision_id"],
        }))
        self.assertIsNone(self.core.evidence_validity(baseline["event_id"])["validity"])
        self.assertEqual(self.core.evidence.get_decision(legacy["decision_id"]), legacy)

    def test_baseline_unassessed_feedback_is_bounded_even_after_dismissal(self) -> None:
        self._assess_original_events()
        self.assertEqual(self._rows("evolution_decisions"), [])
        self._assess("stale")
        self._legacy()
        events_before = len(self._rows("evidence_events"))
        first = self._run()
        self.assertEqual(first["report"]["validity"]["unassessed"], 0)
        self.assertEqual(first["created"], [])
        self.assertEqual(self.core.evidence.validity_counts()["unassessed"], 1)
        second = self._run()
        self.assertEqual([item["action"] for item in second["created"]], ["assess_evidence"])
        generic = second["created"][0]
        self.assertEqual(generic["payload"]["count"], 1)
        for _ in range(3):
            self.assertEqual(self._run()["created"], [])
        dismissed = self.core.dismiss_evolution_decision(generic["decision_id"], "advice reviewed")
        self.assertTrue(dismissed["dismissed"], dismissed)
        snapshot = self._rows("evolution_decisions")
        self._reopen()
        for _ in range(3):
            self.assertEqual(self._run()["created"], [])
        self.assertEqual(self._rows("evolution_decisions"), snapshot)
        self.assertEqual(sum(row["action"] == "assess_evidence" for row in snapshot), 1)
        self.assertEqual(len(self._baselines()), 1)
        self.assertEqual(len(self._rows("evidence_events")), events_before + 1)
        self.assertEqual(self.core.evidence.validity_counts()["unassessed"], 1)

    def test_recovery_then_stale_creates_new_generation_requiring_post_watermark_valid(self) -> None:
        self._assess("stale")
        legacy = self._legacy()
        self.assertEqual(self._revalidations(self._run()), [])
        baseline = self._baselines()
        recovered = self._review_delivery()
        dismissed = self.core.dismiss_evolution_decision(legacy["decision_id"], "old row lacks offset")
        self.assertTrue(dismissed["dismissed"], dismissed)
        legacy_snapshot = self.core.evidence.get_decision(legacy["decision_id"])
        stale = self._assess("stale", "fixture_environment_changed_again")
        renewed, = self._revalidations(self._run())
        generation = {self.event_id: recovered["assessment_id"]}
        self.assertEqual(renewed["payload"][REVALIDATION_GENERATION_KEY], generation)
        self.assertEqual(renewed["dedup_key"], legacy["dedup_key"] + ":recovery:" + make_signal_key(generation))
        watermark = renewed["payload"][ASSESSMENT_WATERMARK_KEY]
        self.assertIs(type(watermark), int)
        self.assertEqual(watermark, self.core.evidence._assessment_watermark(self.core.store.db))
        recovered_rowid = self.core.store.db.execute(
            "SELECT rowid FROM evidence_validity_assessments WHERE assessment_id = ?",
            (recovered["assessment_id"],),
        ).fetchone()[0]
        self.assertLess(recovered_rowid, watermark)
        self.assertEqual(recovered["assessed_at"], stale["assessed_at"])
        self.assertFalse(self.core.evidence.has_assessment_after(self.event_id, watermark))
        refused = self.core.apply_evolution_decision(renewed["decision_id"])
        self.assertEqual(refused["error"]["code"], "INVALID_ARGUMENT")
        self.assertEqual(self.core.evidence.get_decision(renewed["decision_id"]), renewed)
        self.assertEqual(self._revalidations(self._run()), [])
        self._review_delivery()
        self.assertTrue(self.core.evidence.has_assessment_after(self.event_id, watermark))
        applied = self.core.apply_evolution_decision(renewed["decision_id"])
        self.assertTrue(applied["applied"], applied)
        self.assertEqual(self.core.evidence.get_decision(legacy["decision_id"]), legacy_snapshot)
        self.assertEqual(self._baselines(), baseline)

    def test_record_failure_after_baseline_insert_rolls_back_and_retries(self) -> None:
        self._assess_original_events()
        self._assess("stale")
        legacy = self._legacy()
        tables = ("evidence_events", "evidence_validity_assessments", "evolution_decisions")
        before = {table: self._rows(table) for table in tables}
        original_record = Evidence.record
        inserted = []

        def record(evidence: Evidence, event_type: str, **kwargs: Any) -> str:
            event_id = original_record(evidence, event_type, **kwargs)
            if event_type == EVENT_DEDUP_BASELINE:
                self.assertTrue(evidence.store.db.in_transaction)
                self.assertEqual(len(self._baselines()), 1)
                inserted.append(event_id)
                raise RuntimeError("injected after baseline INSERT")
            return event_id

        with (
            patch.object(Evidence, "record", record),
            self.assertRaisesRegex(RuntimeError, "injected after baseline INSERT"),
        ):
            self.core.run_maintenance()
        self.assertEqual(len(inserted), 1)
        self.assertFalse(self.core.store.db.in_transaction)
        self.assertEqual(self.core.store._tx_depth, 0)
        for table in tables:
            self.assertEqual(self._rows(table), before[table])
        self._reopen()
        self.assertEqual(self._baselines(), [])
        self.assertEqual(self._revalidations(self._run()), [])
        self.assertEqual(len(self._baselines()), 1)
        self.assertNotEqual(self._baselines()[0]["event_id"], inserted[0])
        self.assertEqual(self._revalidations(self._run()), [])
        self.assertEqual(len(self._baselines()), 1)
        self._assert_legacy_closed(legacy)

    def _crash_and_recover(self, exit_code: int, committed_baselines: int) -> None:
        self._assess_original_events()
        self._assess("stale")
        legacy = self._legacy()
        events = self._rows("evidence_events")
        assessments = self._rows("evidence_validity_assessments")
        decisions = self._rows("evolution_decisions")
        root = self.dir.resolve()
        self.core.close()  # The child has an independent connection and owns its transaction.
        stdout_path = root / "crash.stdout.log"
        stderr_path = root / "crash.stderr.log"
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.run(
                [sys.executable, "-c", _CRASH_SCRIPT, str(root), str(exit_code)],
                cwd=Path(__file__).resolve().parents[1],
                stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, timeout=30, check=False,
            )
        self.assertEqual(process.returncode, exit_code, (
            stdout_path.read_text(encoding="utf-8", errors="replace"),
            stderr_path.read_text(encoding="utf-8", errors="replace"),
        ))
        self.core = ToolSeed(root)
        self.assertEqual(self.core.store.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        self.assertEqual(len(self._baselines()), committed_baselines)
        self.assertEqual(self._rows("evidence_events")[:len(events)], events)
        self.assertEqual(len(self._rows("evidence_events")), len(events) + committed_baselines)
        self.assertEqual(self._rows("evidence_validity_assessments"), assessments)
        self.assertEqual(self._rows("evolution_decisions"), decisions)
        self._assert_legacy_closed(legacy)
        persisted = self._baselines()
        for _ in range(3):
            self.assertEqual(self._revalidations(self._run()), [])
            self.assertEqual(len(self._baselines()), 1)
        if committed_baselines:
            self.assertEqual(self._baselines(), persisted)
        self.assertEqual(self._rows("evidence_validity_assessments"), assessments)
        self._reopen()
        self.assertEqual(self._revalidations(self._run()), [])
        self.assertEqual(len(self._baselines()), 1)
        self._assert_legacy_closed(legacy)

    def test_process_exit_before_baseline_commit_recovers_and_retries(self) -> None:
        self._crash_and_recover(23, 0)

    def test_process_exit_after_baseline_commit_reuses_durable_baseline(self) -> None:
        self._crash_and_recover(24, 1)
