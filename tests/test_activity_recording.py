"""Minimal failed-tool auditing, without changing public response contracts."""
from __future__ import annotations

import json
import sqlite3
from unittest import mock

from tests.helpers import CoreTest, candidate, verify_version
from toolseed.core.inspection import Inspector


class ActivityRecordingTest(CoreTest):
    case = "ui-activity"

    def failures(self):
        return self.core.store.db.execute(
            "SELECT * FROM evidence_events WHERE event_type='tool_call_failed' ORDER BY rowid"
        ).fetchall()

    def test_failed_search_save_and_delivery_record_only_safe_metadata(self) -> None:
        self.core.toolbox_search({"prompt": "never-store-this-prompt"})
        self.core.toolbox_save({"secret": "never-store-this-secret"}, "private intent")
        self.core.toolbox_run("private unknown reference", {"secret": "private args"})
        rows = self.failures()
        self.assertEqual(len(rows), 3)
        self.assertEqual([json.loads(row["summary"])["tool"] for row in rows],
                         ["toolbox_search", "toolbox_save", "toolbox_run"])
        for row in rows:
            payload = json.loads(row["summary"])
            self.assertEqual(set(payload), {"tool", "status", "error_code"})
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(row["outcome"], "unknown")
            self.assertEqual(row["source_type"], "core")
            self.assertIsNone(row["capability_id"])
            self.assertIsNone(row["verification_json"])
            self.assertNotIn("private", row["summary"])
        self.assertEqual(self.core.toolbox_stats()["task_outcomes"]["signals"], 0)

    def test_known_target_is_linked_without_delivering_it(self) -> None:
        saved = self.save()
        self.core.quarantine(saved["capability_id"])
        result = self.core.toolbox_run(saved["capability_id"])
        self.assertEqual(result["error"]["code"], "CAPABILITY_QUARANTINED")
        self.assertEqual(self.failures()[0]["capability_id"], saved["capability_id"])
        self.assertEqual(self.core.toolbox_stats()["delivery"]["count"], 0)

    def test_audit_storage_failure_does_not_replace_original_response(self) -> None:
        with mock.patch.object(self.core.evidence, "record", side_effect=sqlite3.OperationalError()):
            result = self.core.toolbox_save({}, "invalid")
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")
        self.assertFalse(result["ok"])

    def test_persistence_failure_audit_survives_candidate_rollback(self) -> None:
        with mock.patch.object(self.core.registry, "create_with_version",
                               side_effect=sqlite3.OperationalError()):
            result = self.core.toolbox_save(candidate())
        self.assertEqual(result["error"]["code"], "SAVE_PERSISTENCE_FAILED")
        self.assertEqual(len(self.failures()), 1)
        self.assertEqual(self.core.toolbox_stats()["capabilities"]["total"], 0)

    def test_successes_use_existing_events_without_duplicate_audits(self) -> None:
        saved = self.save()
        self.core.toolbox_search("timeout")
        self.core.toolbox_run(saved["capability_id"])
        self.assertEqual(len(self.failures()), 0)
        self.assertEqual(self.core.evidence.event_counts(),
                         {"procedure_saved": 1, "search_performed": 1, "procedure_delivered": 1})

    def _review_existing(self) -> None:
        for row in self.core.store.db.execute("SELECT event_id FROM evidence_events").fetchall():
            result = self.core.assess_evidence(row["event_id"], "valid", "fixture_binding_review")
            self.assertTrue(result["ok"], result)

    def _fail_delivery(self, saved: dict) -> str:
        result = self.core.toolbox_run(saved["capability_id"], args="invalid arguments")
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")
        return self.failures()[-1]["event_id"]

    def test_failure_alone_is_activity_without_pending_evidence_or_maintenance(self) -> None:
        self.core.toolbox_search("")
        self.assertEqual(self.core.evidence.total_events(), 1)
        self.assertEqual(self.core.evidence.validity_counts(),
                         {"valid": 0, "stale": 0, "superseded": 0, "unassessed": 0})
        for _ in range(2):
            result = self.core.run_maintenance()
            self.assertEqual(result["report"]["suggestions"], [])
            self.assertEqual(result["created"], [])
            self.assertEqual(result["skipped"], 0)
        self.assertEqual(self.core.toolbox_stats()["task_outcomes"]["signals"], 0)
        self.assertEqual(self.core.store.schema_version, 6)

    def test_failed_call_only_changes_activity_total_not_existing_projections(self) -> None:
        saved = self.save()
        self.core.toolbox_run(saved["capability_id"])
        self._review_existing()
        before = self.core.toolbox_stats()
        version_before = self.core.version_report(saved["version_id"])
        history_before = list(self.core.store.db.execute(
            "SELECT * FROM evidence_validity_assessments ORDER BY rowid"
        ))
        failure_id = self._fail_delivery(saved)
        after = self.core.toolbox_stats()
        self.assertEqual(after["evidence"]["events"], before["evidence"]["events"] + 1)
        self.assertEqual(after["evidence"]["validity"], before["evidence"]["validity"])
        self.assertEqual(after["evidence"]["assessments"], before["evidence"]["assessments"])
        for field in ("capabilities", "versions", "task_outcomes", "verifications",
                      "failure_diagnoses", "evolution_decisions", "observations", "delivery"):
            self.assertEqual(after[field], before[field], field)
        self.assertEqual(self.core.version_report(saved["version_id"]), version_before)
        self.assertEqual(list(self.core.store.db.execute(
            "SELECT * FROM evidence_validity_assessments ORDER BY rowid"
        )), history_before)
        validity = self.core.evidence_validity(failure_id)
        self.assertFalse(validity["assessable"])
        self.assertFalse(validity["assessed"])
        self.assertIsNone(validity["validity"])
        self.assertEqual(validity["assessments"], [])
        self.assertEqual(self.core.run_maintenance()["created"], [])
        self.assertEqual(self.core.run_maintenance()["created"], [])

    def test_existing_pending_evidence_and_maintenance_dedup_are_preserved(self) -> None:
        saved = self.save()  # Existing unassessed evidence must not be hidden.
        first = self.core.run_maintenance()
        self.assertEqual(len(first["created"]), 1)
        self.assertEqual(first["report"]["validity"]["unassessed"], 1)
        decision = first["created"][0]
        for _ in range(3):
            self._fail_delivery(saved)
            result = self.core.run_maintenance()
            self.assertEqual(result["report"], first["report"])
            self.assertEqual(result["created"], [])
            self.assertEqual(result["skipped"], 1)
            self.assertEqual(self.core.evidence.get_decision(decision["decision_id"]), decision)
        self.assertEqual(self.core.evidence.validity_counts()["unassessed"], 1)
        self.assertEqual(self.core.toolbox_stats()["task_outcomes"]["failure"], 0)

    def test_old_failure_assessments_remain_history_without_validity_authority(self) -> None:
        saved = self.save()
        self._review_existing()
        baseline = self.core.evidence.validity_counts()
        failure_id = self._fail_delivery(saved)
        # Pre-fix managers could assess these events. Insert only that legacy fixture;
        # neither the correction nor the assertions rewrite/delete historical rows.
        with self.core.store.transaction() as db:
            for index, validity in enumerate(("valid", "stale", "valid")):
                db.execute(
                    "INSERT INTO evidence_validity_assessments "
                    "(assessment_id,evidence_id,validity,reason_code,assessed_at) VALUES (?,?,?,?,?)",
                    (f"eva_legacy_failure_{index}", failure_id, validity,
                     "pre_fix_manager_declaration", "2026-01-01T00:00:00+00:00"),
                )
        history = self.core.evidence.assessments(failure_id)
        self.assertEqual([item["validity"] for item in history], ["valid", "stale", "valid"])
        self.assertIsNone(self.core.evidence.latest_assessment(failure_id))
        self.assertIsNone(self.core.evidence.latest_validity(failure_id))
        self.assertEqual(self.core.evidence.validity_counts(), baseline)
        self.assertEqual(self.core.evidence_validity(failure_id)["assessments"], history)
        self.assertFalse(self.core.assess_evidence(failure_id, "valid", "not_evidence")["ok"])
        with self.assertRaises(ValueError):
            self.core.evidence.assess(failure_id, "stale", "not_evidence")
        self.assertEqual(self.core.evidence.assessments(failure_id), history)
        activity = Inspector(self.dir).read("/api/activity", {})["items"][0]
        self.assertIsNone(activity["validity"])
        self.assertIsNone(activity["validity_reason"])
        self.assertEqual(Inspector(self.dir).read("/api/evidence", {})["total"], 0)

    def test_failure_never_satisfies_candidate_promotion_or_task_success(self) -> None:
        saved = self.save()
        revised = self.save(candidate(target_capability_id=saved["capability_id"],
                                      content="Revised procedure"))
        before = self.core.promote_version(revised["version_id"], "must remain gated")
        failure_id = self._fail_delivery(saved)
        self.assertFalse(self.core.assess_evidence(failure_id, "valid", "not_verification")["ok"])
        self.assertEqual(self.core.promote_version(revised["version_id"], "must remain gated"), before)
        self.assertEqual(self.core.registry.get_capability(saved["capability_id"])["current_version_id"],
                         saved["version_id"])
        self.assertEqual(self.core.toolbox_stats()["verifications"]["passed"], 0)
        verified = verify_version(self.core, revised)
        self.core.assess_evidence(verified["event_id"], "stale", "needs_real_review")
        self.assertFalse(self.core.promote_version(revised["version_id"], "stale verification")["ok"])
        self.core.assess_evidence(verified["event_id"], "valid", "reviewed_verification")
        self.assertTrue(self.core.promote_version(revised["version_id"], "real verification")["ok"])
        self.assertEqual(self.core.toolbox_stats()["task_outcomes"]["signals"], 0)

    def test_failure_cannot_revalidate_or_apply_an_existing_decision(self) -> None:
        saved = self.save()
        delivered = self.core.toolbox_run(saved["capability_id"])
        self._review_existing()
        delivery_id = self.core.store.db.execute(
            "SELECT event_id FROM evidence_events WHERE invocation_id=? AND event_type=?",
            (delivered["invocation_id"], "procedure_delivered"),
        ).fetchone()["event_id"]
        self.core.assess_evidence(delivery_id, "stale", "environment_changed")
        first = self.core.run_maintenance()
        self.assertEqual(len(first["created"]), 1)
        decision = first["created"][0]
        before = self.core.apply_evolution_decision(decision["decision_id"])
        self.assertFalse(before["ok"])
        failure_id = self._fail_delivery(saved)
        self.assertFalse(self.core.assess_evidence(failure_id, "valid", "not_revalidation")["ok"])
        self.assertEqual(self.core.apply_evolution_decision(decision["decision_id"]), before)
        self.assertEqual(self.core.evidence.get_decision(decision["decision_id"]), decision)
        repeated = self.core.run_maintenance()
        self.assertEqual(repeated["report"], first["report"])
        self.assertEqual(repeated["created"], [])
        self.assertEqual(repeated["skipped"], 1)
        self.core.assess_evidence(delivery_id, "valid", "reviewed_actual_delivery")
        applied = self.core.apply_evolution_decision(decision["decision_id"])
        self.assertTrue(applied["applied"], applied)
        self.assertFalse(self.core.apply_evolution_decision(decision["decision_id"])["applied"])
        self.assertEqual(self.core.evidence_validity(delivery_id)["validity"], "valid")
        self.assertEqual(self.core.evidence_validity(failure_id)["assessments"], [])
        self.assertEqual(self.core.run_maintenance()["created"], [])
