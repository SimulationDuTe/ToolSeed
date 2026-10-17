"""Evidence and task-outcome separation (P0-SLIM §6.4, §7, §11.1)."""
from __future__ import annotations

from tests.helpers import CoreTest, candidate


class EvidenceTest(CoreTest):
    case = "evidence"

    def _deliver(self) -> dict:
        saved = self.save()
        return self.core.toolbox_run(saved["capability_id"])

    def test_task_outcome_requires_a_source_and_is_counted(self) -> None:
        delivery = self._deliver()
        result = self.core.record_task_outcome(
            capability_id=delivery["capability_id"],
            version_id=delivery["version_id"],
            invocation_id=delivery["invocation_id"],
            outcome="success",
            source_type="test_runner",
            task_id="task_9",
            summary="integration test passed",
        )
        self.assertTrue(result["ok"], result)

        stats = self.core.toolbox_stats()
        self.assertEqual(stats["task_outcomes"]["signals"], 1)
        self.assertTrue(stats["task_outcomes"]["measured"])
        self.assertEqual(stats["task_outcomes"]["success"], 1)
        self.assertEqual(stats["task_outcomes"]["unknown"], 0)
        self.assertEqual(stats["task_outcomes"]["unknown_ratio"], 0.0)

        row = self.core.store.db.execute(
            "SELECT outcome, source_type, summary FROM evidence_events "
            "WHERE event_type = 'task_outcome_signal'"
        ).fetchone()
        self.assertEqual(row["outcome"], "success")
        self.assertEqual(row["source_type"], "test_runner")
        self.assertEqual(row["summary"], "integration test passed")

    def test_invalid_outcome_is_rejected(self) -> None:
        delivery = self._deliver()
        result = self.core.record_task_outcome(
            capability_id=delivery["capability_id"],
            version_id=delivery["version_id"],
            invocation_id=delivery["invocation_id"],
            outcome="maybe",
            source_type="agent",
        )
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")

    def test_invalid_source_type_is_rejected(self) -> None:
        delivery = self._deliver()
        result = self.core.record_task_outcome(
            capability_id=delivery["capability_id"],
            version_id=delivery["version_id"],
            invocation_id=delivery["invocation_id"],
            outcome="success",
            source_type="vibes",
        )
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")

    def test_missing_ids_are_rejected(self) -> None:
        delivery = self._deliver()
        result = self.core.record_task_outcome(
            capability_id="",
            version_id=delivery["version_id"],
            invocation_id=delivery["invocation_id"],
            outcome="success",
            source_type="agent",
        )
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")

    def test_default_outcome_is_unknown(self) -> None:
        event_id = self.core.evidence.record("custom_event", capability_id="cap_x")
        row = self.core.store.db.execute(
            "SELECT outcome, source_type FROM evidence_events WHERE event_id = ?", (event_id,)
        ).fetchone()
        self.assertEqual(row["outcome"], "unknown")
        self.assertEqual(row["source_type"], "core")

    def test_evidence_rejects_unknown_outcome_and_source(self) -> None:
        with self.assertRaises(ValueError):
            self.core.evidence.record("custom_event", outcome="guessed")
        with self.assertRaises(ValueError):
            self.core.evidence.record("custom_event", source_type="rumor")

    def test_unknown_ratio_is_none_without_signals(self) -> None:
        self._deliver()
        stats = self.core.toolbox_stats()
        self.assertEqual(stats["task_outcomes"]["signals"], 0)
        self.assertFalse(stats["task_outcomes"]["measured"])
        self.assertIsNone(stats["task_outcomes"]["unknown_ratio"])

    def test_unmeasured_cost_is_reported_as_unknown(self) -> None:
        stats = self.core.toolbox_stats()
        self.assertEqual(stats["cost"]["duration_ms"], "unknown")
        self.assertEqual(stats["cost"]["token_measurement"], "unknown")

    def test_events_are_append_only(self) -> None:
        before = self.core.evidence.total_events()
        self._deliver()
        after = self.core.evidence.total_events()
        self.assertEqual(after, before + 2)  # procedure_saved + procedure_delivered
        self.assertEqual(
            self.core.evidence.total_events(),
            self.core.store.db.execute("SELECT COUNT(*) AS n FROM evidence_events").fetchone()["n"],
        )

    def test_duplicate_save_is_recorded_as_an_event(self) -> None:
        self.save()
        second = self.core.toolbox_save(candidate(), "duplicate")
        self.assertTrue(second["duplicate"])
        events = self.core.evidence.event_counts()
        self.assertEqual(events.get("duplicate_save"), 1)
