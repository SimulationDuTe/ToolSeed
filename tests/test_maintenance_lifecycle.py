"""Revalidation decision deduplication follows recorded recovery cycles, not clocks."""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any
from unittest.mock import patch

from tests.helpers import CoreTest
from toolseed import ToolSeed
from toolseed.core.evidence import (
    ASSESSMENT_WATERMARK_KEY,
    EVENT_DEDUP_BASELINE,
    REVALIDATION_GENERATION_KEY,
    make_signal_key,
)


class MaintenanceLifecycleTest(CoreTest):
    case = "maintenance-lifecycle"

    def setUp(self) -> None:
        super().setUp()
        # All assessments/decisions share one tick. Only actual append order changes.
        clock = patch("toolseed.core.evidence.now", return_value="2026-01-01T00:00:00+00:00")
        clock.start()
        self.addCleanup(clock.stop)
        self.saved = self.save()
        delivered = self.core.toolbox_run(self.saved["capability_id"])
        self.assertTrue(delivered["ok"], delivered)
        self.event_id = self.core.store.db.execute(
            "SELECT event_id FROM evidence_events WHERE invocation_id = ? "
            "AND event_type = 'procedure_delivered'",
            (delivered["invocation_id"],),
        ).fetchone()["event_id"]

    def _assess(self, validity: str, reason: str) -> dict[str, Any]:
        result = self.core.assess_evidence(self.event_id, validity, reason)
        self.assertTrue(result["ok"], result)
        return result["assessment"]

    def _review_delivery(self) -> dict[str, Any]:
        """Fixture reviewer checks binding before declaring validity; Core does not verify."""
        event = self.core.store.db.execute(
            "SELECT * FROM evidence_events WHERE event_id = ?", (self.event_id,)
        ).fetchone()
        fingerprint = self.core.evidence.version_fingerprint(self.saved["version_id"])
        self.assertEqual(event["version_id"], self.saved["version_id"])
        self.assertEqual(fingerprint["content_hash"], self.saved["content_hash"])
        # This is an explicit local review of delivery evidence, not task-success proof.
        result = self.core.assess_evidence(
            self.event_id,
            "valid",
            "fixture_review:delivery_binding_and_version_hash_checked",
            fingerprint=fingerprint,
        )
        self.assertTrue(result["ok"], result)
        return result["assessment"]

    def _run(self) -> list[dict[str, Any]]:
        result = self.core.run_maintenance()
        self.assertTrue(result["ok"], result)
        return [item for item in result["created"] if item["action"] == "revalidate_evidence"]

    def test_recovered_then_stale_scope_gets_a_new_decision(self) -> None:
        first_stale = self._assess("stale", "environment_A_needs_review")
        first_run = self._run()
        self.assertEqual(len(first_run), 1)
        first = first_run[0]
        self.assertEqual(self._run(), [], "one outstanding invalidation is idempotent")

        reviewed = self._review_delivery()
        self.assertEqual(self.core.evidence_validity(self.event_id)["validity"], "valid")
        dismissed = self.core.dismiss_evolution_decision(first["decision_id"], "review completed")
        self.assertTrue(dismissed["dismissed"], dismissed)
        second_stale = self._assess("stale", "environment_B_needs_review")
        self.assertEqual(
            [item["validity"] for item in self.core.evidence.assessments(self.event_id)],
            ["stale", "valid", "stale"],
        )
        self.assertEqual(first_stale["assessed_at"], reviewed["assessed_at"])
        self.assertEqual(reviewed["assessed_at"], second_stale["assessed_at"])
        self.assertNotEqual(first_stale["assessment_id"], second_stale["assessment_id"])

        second_run = self._run()
        self.assertEqual(len(second_run), 1, "a real recovery/re-invalidation must renew maintenance")
        second = second_run[0]
        self.assertNotEqual(first["decision_id"], second["decision_id"])
        self.assertNotEqual(first["dedup_key"], second["dedup_key"])
        self.assertEqual(first["payload"]["evidence_ids"], second["payload"]["evidence_ids"])
        self.assertGreater(
            second["payload"]["assessment_watermark"], first["payload"]["assessment_watermark"]
        )
        self.assertEqual(self._run(), [])
        self.assertEqual(
            second["payload"][REVALIDATION_GENERATION_KEY],
            {self.event_id: reviewed["assessment_id"]},
        )
        self.assertEqual(
            second["dedup_key"],
            first["dedup_key"] + ":recovery:" + make_signal_key(
                {self.event_id: reviewed["assessment_id"]}
            ),
        )
        self.assertEqual(
            second["payload"][ASSESSMENT_WATERMARK_KEY],
            self.core.evidence._assessment_watermark(self.core.store.db),
        )
        # The earlier valid belongs to the previous cycle, before the new watermark.
        refused = self.core.apply_evolution_decision(second["decision_id"])
        self.assertEqual(refused["error"]["code"], "INVALID_ARGUMENT")
        self.assertFalse(self.core.evidence.has_assessment_after(
            self.event_id, second["payload"][ASSESSMENT_WATERMARK_KEY]
        ))
        old_snapshot = self.core.evidence.get_decision(first["decision_id"])
        events = self._rows("evidence_events")
        history = self._rows("evidence_validity_assessments")
        self._review_delivery()
        self.assertTrue(self.core.evidence.has_assessment_after(
            self.event_id, second["payload"][ASSESSMENT_WATERMARK_KEY]
        ))
        applied = self.core.apply_evolution_decision(second["decision_id"], "reviewed again")
        self.assertTrue(applied["applied"], applied)
        self.assertEqual(self.core.evidence.get_decision(first["decision_id"]), old_snapshot)
        self.assertEqual(self._rows("evidence_events"), events)
        self.assertEqual(self._rows("evidence_validity_assessments")[:-1], history)
        self.assertEqual(self._run(), [])

    def _rows(self, table: str) -> list[dict[str, Any]]:
        assert table in ("evidence_events", "evidence_validity_assessments", "evolution_decisions")
        return [dict(row) for row in self.core.store.db.execute(f"SELECT * FROM {table} ORDER BY rowid")]

    def test_dismiss_and_repeated_stale_do_not_reset_the_cycle(self) -> None:
        self._assess("stale", "environment_changed")
        first = self._run()[0]
        self.core.dismiss_evolution_decision(first["decision_id"], "deferred")
        snapshot = self.core.evidence.get_decision(first["decision_id"])
        for _ in range(3):
            self._assess("stale", "still_needs_the_same_review")
            self.assertEqual(self._run(), [])
        self._assess("superseded", "replacement_pending")
        self._assess("stale", "replacement_not_validated")
        self.assertEqual(self._run(), [], "without valid there was no recovery")
        # An unrelated valid assessment changes MAX(rowid), not this evidence's cycle.
        saved_event = self.core.store.db.execute(
            "SELECT event_id FROM evidence_events WHERE event_type = 'procedure_saved'"
        ).fetchone()["event_id"]
        self.core.assess_evidence(saved_event, "valid", "unrelated_review")
        self.assertEqual(self._run(), [])
        self.assertEqual(self.core.evidence.get_decision(first["decision_id"]), snapshot)
        self.assertEqual(self.core.store.schema_version, 7)
        self.core.close()
        self.core = ToolSeed(self.dir)
        self.assertEqual(self._run(), [], "deduplication survives a process/connection restart")
        self.assertEqual(self.core.evidence.get_decision(first["decision_id"]), snapshot)

    def test_applied_decision_is_preserved_when_a_new_cycle_is_created(self) -> None:
        self._assess("stale", "environment_A")
        first = self._run()[0]
        self._review_delivery()
        result = self.core.apply_evolution_decision(first["decision_id"], "review done")
        self.assertTrue(result["applied"], result)
        snapshot = self.core.evidence.get_decision(first["decision_id"])
        self._assess("stale", "environment_B")
        second = self._run()
        self.assertEqual(len(second), 1)
        self.assertNotEqual(second[0]["decision_id"], first["decision_id"])
        self.assertEqual(self.core.evidence.get_decision(first["decision_id"]), snapshot)
        self.assertEqual(self._run(), [])

    def test_proposed_decision_is_not_reset_on_recovery_and_recurrence(self) -> None:
        self._assess("stale", "environment_A")
        first = self._run()[0]
        self._review_delivery()
        snapshot = self.core.evidence.get_decision(first["decision_id"])
        self._assess("stale", "environment_B")
        second = self._run()
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]["status"], "proposed")
        self.assertNotEqual(second[0]["decision_id"], first["decision_id"])
        self.assertEqual(self.core.evidence.get_decision(first["decision_id"]), snapshot)

    def _legacy(self, *, with_watermark: bool) -> dict[str, Any]:
        """Insert an old-format fixture without generation metadata, not a production edit."""
        digest = hashlib.sha1(self.event_id.encode("utf-8")).hexdigest()[:12]
        key = ":".join((
            "revalidate_evidence", "stale_evidence", self.saved["capability_id"],
            self.saved["version_id"], digest,
        ))
        payload = {
            "action": "revalidate_evidence", "reason": "stale_evidence",
            "capability_id": self.saved["capability_id"],
            "version_id": self.saved["version_id"], "evidence_ids": [self.event_id],
            "count": 1,
        }
        if with_watermark:
            payload[ASSESSMENT_WATERMARK_KEY] = self.core.evidence._assessment_watermark(
                self.core.store.db
            )
        with self.core.store.transaction() as db:
            db.execute(
                "INSERT INTO evolution_decisions "
                "(decision_id, dedup_key, action, reason, capability_id, version_id, "
                "status, payload_json, created_at, updated_at) "
                "VALUES ('dec_legacy', ?, 'revalidate_evidence', 'stale_evidence', ?, ?, "
                "'proposed', ?, '2026-01-01', '2026-01-01')",
                (key, self.saved["capability_id"], self.saved["version_id"], json.dumps(payload)),
            )
        return self.core.evidence.get_decision("dec_legacy")

    def test_old_watermarked_key_is_reused_until_real_recovery(self) -> None:
        self._review_delivery()  # Existing valid before the first invalidation is not a new cycle.
        self._assess("stale", "environment_A")
        legacy = self._legacy(with_watermark=True)
        original_events = self._rows("evidence_events")
        self.assertEqual(self._run(), [])
        self.assertEqual(self._rows("evidence_events"), original_events)
        reviewed = self._review_delivery()
        self.core.dismiss_evolution_decision(legacy["decision_id"], "review complete")
        snapshot = self.core.evidence.get_decision(legacy["decision_id"])
        self._assess("stale", "environment_B")
        second = self._run()
        self.assertEqual(len(second), 1)
        self.assertEqual(
            second[0]["payload"][REVALIDATION_GENERATION_KEY],
            {self.event_id: reviewed["assessment_id"]},
        )
        self.assertEqual(self.core.evidence.get_decision(legacy["decision_id"]), snapshot)
        self.assertEqual(self._run(), [])

    def test_legacy_without_watermark_stays_closed_and_gets_an_observation_baseline(self) -> None:
        # Even if past recoveries exist, their order relative to an offset-less row is unknown.
        self._assess("stale", "past_environment")
        self._review_delivery()
        self._assess("stale", "current_environment")
        legacy = self._legacy(with_watermark=False)
        events = self._rows("evidence_events")
        history = self._rows("evidence_validity_assessments")
        stats_before = self.core.toolbox_stats()
        self.assertEqual(self._run(), [])
        stats_after = self.core.toolbox_stats()
        self.assertEqual(stats_after["evidence"]["events"], stats_before["evidence"]["events"] + 1)
        self.assertEqual(
            stats_after["evidence"]["validity"]["unassessed"],
            stats_before["evidence"]["validity"]["unassessed"] + 1,
        )
        self.assertEqual(stats_after["task_outcomes"], stats_before["task_outcomes"])
        self.assertEqual(stats_after["verifications"], stats_before["verifications"])
        self.assertEqual(self.core.evidence.get_decision(legacy["decision_id"]), legacy)
        self.assertEqual(self._rows("evidence_validity_assessments"), history)
        baselines = self.core.store.db.execute(
            "SELECT * FROM evidence_events WHERE event_type = ?", (EVENT_DEDUP_BASELINE,)
        ).fetchall()
        self.assertEqual(len(baselines), 1)
        self.assertEqual(self._rows("evidence_events")[:-1], events)
        self.assertEqual(self._run(), [])
        refused = self.core.apply_evolution_decision(legacy["decision_id"])
        self.assertEqual(
            refused["error"]["reason_code"], "DECISION_ASSESSMENT_WATERMARK_MISSING"
        )
        self.core.dismiss_evolution_decision(legacy["decision_id"], "old row cannot prove order")
        snapshot = self.core.evidence.get_decision(legacy["decision_id"])
        self.assertEqual(self._run(), [], "dismiss alone cannot renew a legacy suggestion")
        self.core.close()
        self.core = ToolSeed(self.dir)
        self.assertEqual(self._run(), [], "the observation baseline is persisted")
        self._review_delivery()
        self._assess("stale", "future_environment")
        second = self._run()
        self.assertEqual(len(second), 1)
        self.assertNotEqual(second[0]["dedup_key"], legacy["dedup_key"])
        self.assertNotEqual(second[0]["decision_id"], legacy["decision_id"])
        self.assertGreater(second[0]["payload"][ASSESSMENT_WATERMARK_KEY], 0)
        self.assertEqual(self.core.evidence.get_decision(legacy["decision_id"]), snapshot)
        self.assertNotIn(ASSESSMENT_WATERMARK_KEY, snapshot["payload"])
        self.assertEqual(self._run(), [])
        self._review_delivery()
        self.assertTrue(self.core.apply_evolution_decision(second[0]["decision_id"])["applied"])
        self.assertEqual(self.core.evidence.get_decision(legacy["decision_id"]), snapshot)
        self.assertEqual(self.core.store.db.execute(
            "SELECT COUNT(*) FROM evidence_events WHERE event_type = ?", (EVENT_DEDUP_BASELINE,)
        ).fetchone()[0], 1)

    def test_two_connections_create_only_one_decision_per_generation(self) -> None:
        other = ToolSeed(self.dir)
        try:
            for cycle in range(3):
                self._assess("stale", f"environment_{cycle}")
                start = Barrier(2)

                def run(core: ToolSeed, start: Barrier = start) -> list[dict[str, Any]]:
                    start.wait(timeout=5)
                    result = core.run_maintenance()
                    return [item for item in result["created"]
                            if item["action"] == "revalidate_evidence"]

                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(run, (self.core, other)))
                self.assertEqual(sum(len(items) for items in results), 1)
                created = next(items[0] for items in results if items)
                if cycle == 0:
                    base_key = created["dedup_key"]
                else:
                    self.assertTrue(created["dedup_key"].startswith(base_key + ":recovery:"))
                    self.assertEqual(created["dedup_key"].count(":recovery:"), 1)
                self.assertEqual(self._run(), [])
                self._review_delivery()
            keys = [row["dedup_key"] for row in self._rows("evolution_decisions")]
            self.assertEqual(len(keys), len(set(keys)))
        finally:
            other.close()

    def test_scope_order_is_stable_and_every_member_needs_post_watermark_review(self) -> None:
        delivered = self.core.toolbox_run(self.saved["capability_id"])
        other = self.core.store.db.execute(
            "SELECT event_id FROM evidence_events WHERE invocation_id = ?",
            (delivered["invocation_id"],),
        ).fetchone()["event_id"]
        self._assess("stale", "environment_A")
        self.core.assess_evidence(other, "stale", "environment_A")
        first = self._run()[0]
        # Reversed report order must preserve the same base key and generation hash.
        original_groups = self.core.evidence.stale_evidence_groups()
        original_groups[0]["evidence_ids"].reverse()
        with patch.object(self.core.evidence, "stale_evidence_groups", return_value=original_groups):
            self.assertEqual(self._run(), [])
        self._review_delivery()
        self.core.assess_evidence(other, "valid", "fixture_review:second_delivery_binding")
        self.core.dismiss_evolution_decision(first["decision_id"], "both reviewed")
        self._assess("stale", "environment_B")
        self.core.assess_evidence(other, "stale", "environment_B")
        second = self._run()[0]
        self.assertEqual(set(first["payload"]["evidence_ids"]), set(second["payload"]["evidence_ids"]))
        self._review_delivery()
        refused = self.core.apply_evolution_decision(second["decision_id"])
        self.assertEqual(refused["error"]["code"], "INVALID_ARGUMENT")
        self.assertEqual(self.core.evidence.get_decision(second["decision_id"])["status"], "proposed")
        self.core.assess_evidence(other, "valid", "fixture_review:second_delivery_binding")
        self.assertTrue(self.core.apply_evolution_decision(second["decision_id"])["applied"])
