"""Deterministic independent-connection interleavings at decision commit boundaries."""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import Any
from unittest.mock import patch

from tests.helpers import CoreTest
from toolseed import ToolSeed

# Immediate process exits exercise the real SQLite transaction, not exception cleanup.
_CRASH_SCRIPT = r"""
import os
import sys
from unittest.mock import patch
from toolseed import ToolSeed
from toolseed.core.evidence import Evidence

core = ToolSeed(sys.argv[1])
decision_id, operation, phase = sys.argv[2:]
method = 'mark_decision_applied' if operation == 'apply' else 'dismiss_decision'
original = getattr(Evidence, method)
seen = []
def write(evidence, *args, **kwargs):
    original(evidence, *args, **kwargs)
    assert evidence.store.db.in_transaction
    seen.append(True)
    if phase == 'before':
        os._exit(27)
with patch.object(Evidence, method, write):
    if operation == 'apply':
        result = core.apply_evolution_decision(decision_id)
    else:
        result = core.dismiss_evolution_decision(decision_id)
assert result['ok'] and seen, result
assert not core.store.db.in_transaction
os._exit(28)
"""


class DecisionConcurrencyTest(CoreTest):
    case = "decision-concurrency"

    def setUp(self) -> None:
        super().setUp()
        self.other = ToolSeed(self.dir)
        self.other.store.db.execute("PRAGMA busy_timeout = 0")
        self.assertIsNot(self.core.store.db, self.other.store.db)

    def tearDown(self) -> None:
        self.other.close()
        super().tearDown()

    def _revalidation(self) -> tuple[dict[str, Any], str]:
        saved = self.save()
        delivery = self.core.toolbox_run(saved["capability_id"])
        event_id = self.core.store.db.execute(
            "SELECT event_id FROM evidence_events WHERE invocation_id = ? "
            "AND event_type = 'procedure_delivered'", (delivery["invocation_id"],),
        ).fetchone()["event_id"]
        self.core.assess_evidence(event_id, "stale", "fixture_environment_changed")
        run = self.core.run_maintenance()
        decision = next(item for item in run["created"] if item["action"] == "revalidate_evidence")
        # Explicit trusted-manager declaration, not an independently executed verification.
        self.core.assess_evidence(event_id, "valid", "fixture_delivery_review_completed")
        return decision, event_id

    def _diagnosis(self) -> dict[str, Any]:
        saved = self.save()
        for index in range(2):
            delivery = self.core.toolbox_run(saved["capability_id"])
            result = self.core.record_task_outcome(
                capability_id=saved["capability_id"], version_id=saved["version_id"],
                invocation_id=delivery["invocation_id"], outcome="failure",
                source_type="test_runner", task_id=f"fixture_failure_{index}",
            )
            self.assertTrue(result["ok"], result)
        return next(item for item in self.core.run_maintenance()["created"]
                    if item["action"] == "diagnose_failure")

    def test_stale_commit_cannot_slip_between_validation_and_application(self) -> None:
        decision, event_id = self._revalidation()
        original = self.core.evidence.mark_decision_applied
        observations: dict[str, Any] = {}

        def mark(*args: Any, **kwargs: Any) -> None:
            observations["in_transaction"] = self.core.store.db.in_transaction
            try:
                result = self.other.assess_evidence(event_id, "stale", "concurrent_invalidation")
            except sqlite3.OperationalError as exc:
                self.assertEqual(exc.sqlite_errorcode, sqlite3.SQLITE_BUSY)
                observations["writer_blocked"] = True
            else:
                self.assertTrue(result["ok"], result)
                observations["stale_committed"] = True
            original(*args, **kwargs)

        with patch.object(self.core.evidence, "mark_decision_applied", mark):
            result = self.core.apply_evolution_decision(decision["decision_id"])
        self.assertTrue(observations, "the real pre-update synchronization point must execute")
        if observations.get("stale_committed"):
            self.assertFalse(result.get("applied", False),
                             "a stale committed before decision UPDATE must block application")
        else:
            self.assertTrue(observations["writer_blocked"])
            self.assertTrue(observations["in_transaction"])
            self.assertTrue(result["applied"], result)
            # An invalidation after the application commits is a legitimate later event.
            self.assertTrue(self.other.assess_evidence(event_id, "stale", "after_commit")["ok"])
        self.assertEqual(self.core.evidence.latest_validity(event_id), "stale")
        self.assertFalse(self.core.store.db.in_transaction)
        self.assertFalse(self.other.store.db.in_transaction)

    def test_application_does_not_overwrite_a_concurrent_dismissal(self) -> None:
        decision, _ = self._revalidation()
        original = self.core.evidence.mark_decision_applied
        concurrent: list[dict[str, Any]] = []

        def mark(*args: Any, **kwargs: Any) -> None:
            concurrent.append(self.other.dismiss_evolution_decision(decision["decision_id"], "B"))
            original(*args, **kwargs)

        with patch.object(self.core.evidence, "mark_decision_applied", mark):
            result = self.core.apply_evolution_decision(decision["decision_id"], "A")
        self.assertEqual(len(concurrent), 1)
        if concurrent[0].get("dismissed"):
            self.assertFalse(result.get("applied", False), "a committed dismissal must not be lost")
            self.assertEqual(self.core.evidence.get_decision(decision["decision_id"])["status"],
                             "dismissed")
        else:
            self.assertEqual(concurrent[0]["error"]["code"], "SAVE_PERSISTENCE_FAILED")
            self.assertTrue(result["applied"], result)

    def test_concurrent_diagnosis_application_has_only_one_side_effect(self) -> None:
        decision = self._diagnosis()
        original = self.core.evidence.get_decision
        concurrent: list[dict[str, Any]] = []
        entered = False

        def get(decision_id: str) -> dict[str, Any] | None:
            nonlocal entered
            snapshot = original(decision_id)
            if not entered:
                entered = True
                concurrent.append(self.other.apply_evolution_decision(decision_id, "B"))
            return snapshot

        with patch.object(self.core.evidence, "get_decision", get):
            result = self.core.apply_evolution_decision(decision["decision_id"], "A")
        self.assertTrue(entered)
        diagnoses = self.core.store.db.execute("SELECT * FROM failure_diagnoses").fetchall()
        self.assertEqual(len(diagnoses), 1, "one decision must not create two diagnoses")
        self.assertEqual(sum(bool(item.get("applied")) for item in [result, *concurrent]), 1)
        retry = self.other.apply_evolution_decision(decision["decision_id"], "retry")
        self.assertTrue(retry["ok"], retry)
        self.assertFalse(retry["applied"])

    def test_concurrent_dismissal_is_idempotent_and_keeps_the_winning_resolution(self) -> None:
        decision, _ = self._revalidation()
        original = self.core.evidence.get_decision
        concurrent: list[dict[str, Any]] = []
        entered = False

        def get(decision_id: str) -> dict[str, Any] | None:
            nonlocal entered
            snapshot = original(decision_id)
            if not entered:
                entered = True
                concurrent.append(self.other.dismiss_evolution_decision(decision_id, "B"))
            return snapshot

        with patch.object(self.core.evidence, "get_decision", get):
            result = self.core.dismiss_evolution_decision(decision["decision_id"], "A")
        self.assertTrue(entered)
        self.assertEqual(sum(bool(item.get("dismissed")) for item in [result, *concurrent]), 1)
        expected = "B" if concurrent[0].get("dismissed") else "A"
        stored = self.core.evidence.get_decision(decision["decision_id"])
        self.assertEqual(stored["resolution"], expected)
        self.assertFalse(self.other.dismiss_evolution_decision(decision["decision_id"], "retry")
                         ["dismissed"])
        self.assertEqual(self.core.evidence.get_decision(decision["decision_id"]), stored)

    def _rows(self, table: str) -> list[dict[str, Any]]:
        assert table in ("evolution_decisions", "failure_diagnoses", "evidence_events",
                         "evidence_validity_assessments")
        return [dict(row) for row in self.core.store.db.execute(f"SELECT * FROM {table} ORDER BY rowid")]

    def test_stale_committed_before_apply_is_rejected_without_writes(self) -> None:
        decision, event_id = self._revalidation()
        self.other.assess_evidence(event_id, "stale", "committed_before_apply")
        before = self._rows("evolution_decisions")
        assessments = self._rows("evidence_validity_assessments")
        with patch.object(self.core.evidence, "mark_decision_applied") as mark:
            result = self.core.apply_evolution_decision(decision["decision_id"])
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")
        mark.assert_not_called()
        self.assertEqual(self._rows("evolution_decisions"), before)
        self.assertEqual(self._rows("evidence_validity_assessments"), assessments)

    def test_busy_conflict_is_safe_and_can_be_retried(self) -> None:
        decision, _ = self._revalidation()
        self.core.store.db.execute("PRAGMA busy_timeout = 0")
        before = self._rows("evolution_decisions")
        with self.other.store.transaction(immediate=True):
            for operation in (self.core.apply_evolution_decision,
                              self.core.dismiss_evolution_decision):
                result = operation(decision["decision_id"])
                self.assertEqual(result["error"]["code"], "SAVE_PERSISTENCE_FAILED")
                self.assertEqual(self._rows("evolution_decisions"), before)
                self.assertEqual(self.core.store._tx_depth, 0)
                self.assertFalse(self.core.store.db.in_transaction)
        self.assertTrue(self.core.apply_evolution_decision(decision["decision_id"])["applied"])

    def test_busy_maintenance_creates_no_partial_decision_and_can_retry(self) -> None:
        decision, _ = self._revalidation()
        self.core.store.db.execute("PRAGMA busy_timeout = 0")
        before = self._rows("evolution_decisions")
        events = self._rows("evidence_events")
        with self.other.store.transaction(immediate=True):
            with self.assertRaises(sqlite3.OperationalError) as error:
                self.core.run_maintenance()
            self.assertEqual(error.exception.sqlite_errorcode, sqlite3.SQLITE_BUSY)
            self.assertEqual(self._rows("evolution_decisions"), before)
            self.assertEqual(self._rows("evidence_events"), events)
        retry = self.core.run_maintenance()
        self.assertTrue(retry["ok"], retry)
        self.assertEqual(retry["created"], [])
        self.assertEqual(self.core.evidence.get_decision(decision["decision_id"]), decision)

    def test_waiting_invalidation_commits_only_after_apply(self) -> None:
        decision, event_id = self._revalidation()
        self.other.store.db.execute("PRAGMA busy_timeout = 5000")
        ready, attempted, committed = Event(), Event(), Event()
        original = self.core.evidence.mark_decision_applied

        def mark(*args: Any, **kwargs: Any) -> None:
            self.assertTrue(self.core.store.db.in_transaction)
            ready.set()
            self.assertTrue(attempted.wait(10))
            self.assertFalse(committed.is_set(), "B cannot commit while A holds the writer slot")
            original(*args, **kwargs)

        def trace(sql: str) -> None:
            if sql.startswith("BEGIN"):
                attempted.set()

        def invalidate() -> dict[str, Any]:
            result = self.other.assess_evidence(event_id, "stale", "waiting_writer")
            committed.set()
            return result

        self.other.store.db.set_trace_callback(trace)
        try:
            with (patch.object(self.core.evidence, "mark_decision_applied", mark),
                  ThreadPoolExecutor(max_workers=2) as pool):
                application = pool.submit(self.core.apply_evolution_decision, decision["decision_id"])
                self.assertTrue(ready.wait(10))
                invalidation = pool.submit(invalidate)
                self.assertTrue(application.result(timeout=10)["applied"])
                self.assertTrue(invalidation.result(timeout=10)["ok"])
        finally:
            self.other.store.db.set_trace_callback(None)
        self.assertTrue(committed.is_set())
        self.assertEqual(self.core.evidence.latest_validity(event_id), "stale")
        self.assertEqual(self.core.evidence.get_decision(decision["decision_id"])["status"], "applied")

    def test_caught_write_failure_rolls_back_diagnosis_and_decision(self) -> None:
        decision = self._diagnosis()
        before = self._rows("evolution_decisions")
        events = self._rows("evidence_events")
        original = self.core.evidence.mark_decision_applied

        def fail(*args: Any, **kwargs: Any) -> None:
            original(*args, **kwargs)
            raise sqlite3.OperationalError("injected after diagnosis and status writes")

        with patch.object(self.core.evidence, "mark_decision_applied", fail):
            result = self.core.apply_evolution_decision(decision["decision_id"])
        self.assertEqual(result["error"]["code"], "SAVE_PERSISTENCE_FAILED")
        self.assertEqual(self._rows("failure_diagnoses"), [])
        self.assertEqual(self._rows("evolution_decisions"), before)
        self.assertEqual(self._rows("evidence_events"), events)
        self.assertFalse(self.core.store.db.in_transaction)
        self.assertTrue(self.other.apply_evolution_decision(decision["decision_id"])["applied"])
        self.assertEqual(len(self._rows("failure_diagnoses")), 1)

    def test_dismissal_write_failure_rolls_back(self) -> None:
        decision, _ = self._revalidation()
        before = self._rows("evolution_decisions")
        original = self.core.evidence.dismiss_decision

        def fail(*args: Any, **kwargs: Any) -> None:
            original(*args, **kwargs)
            raise sqlite3.OperationalError("injected after dismissal UPDATE")

        with patch.object(self.core.evidence, "dismiss_decision", fail):
            result = self.core.dismiss_evolution_decision(decision["decision_id"])
        self.assertEqual(result["error"]["code"], "SAVE_PERSISTENCE_FAILED")
        self.assertEqual(self._rows("evolution_decisions"), before)
        self.assertTrue(self.other.dismiss_evolution_decision(decision["decision_id"])["dismissed"])

    def _commit_failure(self, operation: str) -> None:
        decision = self._diagnosis() if operation == "apply" else self._revalidation()[0]
        before = self._rows("evolution_decisions")
        denied: list[str] = []

        def authorizer(action: int, arg1: str | None, *_args: Any) -> int:
            if action == sqlite3.SQLITE_TRANSACTION and arg1 == "COMMIT":
                denied.append(arg1)
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        self.core.store.db.set_authorizer(authorizer)
        try:
            method = (self.core.apply_evolution_decision if operation == "apply"
                      else self.core.dismiss_evolution_decision)
            result = method(decision["decision_id"])
        finally:
            self.core.store.db.set_authorizer(None)
        self.assertEqual(denied, ["COMMIT"], "SQLite itself must reject the real COMMIT")
        self.assertEqual(result["error"]["code"], "SAVE_PERSISTENCE_FAILED")
        self.assertFalse(self.core.store.db.in_transaction, "failed commit must not remain pending")
        self.assertEqual(self.core.store._tx_depth, 0)
        self.assertEqual(self._rows("evolution_decisions"), before)
        self.assertEqual(self._rows("failure_diagnoses"), [])
        self.assertEqual(self.other.evidence.get_decision(decision["decision_id"]), decision)
        self.assertTrue(method(decision["decision_id"])["ok"])

    def test_apply_commit_failure_rolls_back_instead_of_leaving_pending_writes(self) -> None:
        self._commit_failure("apply")

    def test_dismiss_commit_failure_rolls_back_instead_of_leaving_pending_writes(self) -> None:
        self._commit_failure("dismiss")

    def test_maintenance_commit_failure_rolls_back_and_can_retry(self) -> None:
        saved = self.save()
        delivery = self.core.toolbox_run(saved["capability_id"])
        event_id = self.core.store.db.execute(
            "SELECT event_id FROM evidence_events WHERE invocation_id = ?",
            (delivery["invocation_id"],),
        ).fetchone()["event_id"]
        self.core.assess_evidence(event_id, "stale", "fixture_environment_changed")

        def authorizer(action: int, arg1: str | None, *_args: Any) -> int:
            return (sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_TRANSACTION and arg1 == "COMMIT"
                    else sqlite3.SQLITE_OK)

        self.core.store.db.set_authorizer(authorizer)
        try:
            with self.assertRaises(sqlite3.DatabaseError) as error:
                self.core.run_maintenance()
        finally:
            self.core.store.db.set_authorizer(None)
        self.assertEqual(error.exception.sqlite_errorcode, sqlite3.SQLITE_AUTH)
        self.assertFalse(self.core.store.db.in_transaction, "failed commit must not remain pending")
        self.assertEqual(self._rows("evolution_decisions"), [])
        self.assertEqual(self.other.evidence.list_decisions(), [])
        retry = self.core.run_maintenance()
        self.assertTrue(retry["ok"], retry)
        self.assertTrue(any(row["action"] == "revalidate_evidence" for row in retry["created"]))

    def _crash(self, operation: str, phase: str) -> None:
        decision = self._diagnosis() if operation == "apply" else self._revalidation()[0]
        events = self._rows("evidence_events")
        assessments = self._rows("evidence_validity_assessments")
        root = self.dir.resolve()
        self.core.close()
        self.other.close()
        with (root / "crash.log").open("wb") as log:
            process = subprocess.run(
                [sys.executable, "-c", _CRASH_SCRIPT, str(root), decision["decision_id"], operation, phase],
                cwd=Path(__file__).resolve().parents[1], stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, timeout=30, check=False,
            )
        self.core, self.other = ToolSeed(root), ToolSeed(root)
        self.assertEqual(process.returncode, 27 if phase == "before" else 28,
                         (root / "crash.log").read_text(encoding="utf-8", errors="replace"))
        self.assertEqual(self.core.store.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        stored = self.core.evidence.get_decision(decision["decision_id"])
        expected = "proposed" if phase == "before" else ("applied" if operation == "apply" else "dismissed")
        self.assertEqual(stored["status"], expected)
        self.assertEqual(len(self._rows("failure_diagnoses")), int(operation == "apply" and phase == "after"))
        retry = (self.other.apply_evolution_decision if operation == "apply"
                 else self.other.dismiss_evolution_decision)(decision["decision_id"])
        self.assertTrue(retry["ok"], retry)
        self.assertEqual(retry["applied" if operation == "apply" else "dismissed"], phase == "before")
        self.assertEqual(len(self._rows("failure_diagnoses")), int(operation == "apply"))
        self.assertEqual(self._rows("evidence_events"), events)
        self.assertEqual(self._rows("evidence_validity_assessments"), assessments)

    def test_apply_process_exit_before_commit_has_no_partial_diagnosis(self) -> None:
        self._crash("apply", "before")

    def test_apply_process_exit_after_commit_is_idempotent(self) -> None:
        self._crash("apply", "after")

    def test_dismiss_process_exit_before_commit_is_retryable(self) -> None:
        self._crash("dismiss", "before")

    def test_dismiss_process_exit_after_commit_is_idempotent(self) -> None:
        self._crash("dismiss", "after")

    def test_maintenance_report_recovered_before_capture_is_conservative(self) -> None:
        decision, event_id = self._revalidation()
        self.core.assess_evidence(event_id, "stale", "new_report_cycle")
        original = self.core.evidence.create_decision
        recovered: list[dict[str, Any]] = []

        def create(**kwargs: Any) -> tuple[dict[str, Any], bool]:
            if kwargs["action"] == "revalidate_evidence":
                recovered.append(self.other.assess_evidence(event_id, "valid", "report_became_old"))
            return original(**kwargs)

        with patch.object(self.core.evidence, "create_decision", create):
            result = self.core.run_maintenance()
        self.assertEqual(len(recovered), 1)
        renewed = next(item for item in result["created"] if item["action"] == "revalidate_evidence")
        self.assertNotEqual(renewed["decision_id"], decision["decision_id"])
        self.assertEqual(self.core.evidence.latest_validity(event_id), "valid")
        refused = self.core.apply_evolution_decision(renewed["decision_id"])
        self.assertEqual(refused["error"]["code"], "INVALID_ARGUMENT")
        self.assertFalse(self.core.evidence.has_assessment_after(
            event_id, renewed["payload"]["assessment_watermark"]
        ))
        self.assertFalse(any(item["action"] == "revalidate_evidence"
                             for item in self.core.run_maintenance()["report"]["suggestions"]))

    def test_new_stale_member_after_report_is_discovered_next_scan(self) -> None:
        decision, event_id = self._revalidation()
        delivery = self.core.toolbox_run(decision["capability_id"])
        other_event = self.core.store.db.execute(
            "SELECT event_id FROM evidence_events WHERE invocation_id = ?",
            (delivery["invocation_id"],),
        ).fetchone()["event_id"]
        self.core.assess_evidence(other_event, "valid", "fixture_second_delivery_review")
        self.core.assess_evidence(event_id, "stale", "report_scope_A")
        original = self.core.evidence.create_decision
        changed = False

        def create(**kwargs: Any) -> tuple[dict[str, Any], bool]:
            nonlocal changed
            if kwargs["action"] == "revalidate_evidence" and not changed:
                changed = True
                self.other.assess_evidence(other_event, "stale", "report_scope_added_B")
            return original(**kwargs)

        with patch.object(self.core.evidence, "create_decision", create):
            result = self.core.run_maintenance()
        self.assertTrue(changed)
        first = next(item for item in result["created"] if item["action"] == "revalidate_evidence")
        self.assertEqual(first["payload"]["evidence_ids"], [event_id])
        second = next(item for item in self.core.run_maintenance()["created"]
                      if item["action"] == "revalidate_evidence")
        self.assertEqual(set(second["payload"]["evidence_ids"]), {event_id, other_event})
        self.assertNotEqual(first["dedup_key"], second["dedup_key"])
