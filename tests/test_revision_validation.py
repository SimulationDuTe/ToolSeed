"""Host-runner receipts activate only the exact candidate against its base."""
from __future__ import annotations

import copy
import json
import sqlite3
from unittest.mock import patch

from tests.helpers import CoreTest, candidate, verify_version
from tests.test_learning import experience
from tests.test_reuse_learning import feedback
from toolseed.core.evidence import EVENT_PROCEDURE_SAVED
from toolseed.core.revisions import EVENT_REVISION_VALIDATED


class RevisionValidationTest(CoreTest):
    case = "revision-validation"

    def setUp(self):
        super().setUp()
        self.saved = self.core.toolbox_learn(experience())
        self.delivery = self.core.toolbox_run(self.saved["capability_id"])
        self.revised = self.core.toolbox_learn(feedback(self.delivery, amendment={"checks": ["Confirm RGBA mode"]}))
        self.binding = self.revised["revision_validation"]

    def receipt(self):
        return {"binding": self.binding, "run_id": "host-run-1", "plan_hash": "sha256:fixture-plan",
                "cases": [{"id": role, "role": role, "purpose": "Check alpha output in " + role,
                           "tool": "fixture_check", "status": "passed", "assertion_count": 1,
                           "failed_assertions": [], "result_hash": "sha256:fixture-result"}
                          for role in ("new", "regression")]}

    def current(self):
        return self.core.registry.get_capability(self.saved["capability_id"])["current_version_id"]

    def test_inspection_returns_candidate_material_without_delivery(self):
        before = self.core.store.db.execute("SELECT COUNT(*) FROM invocations").fetchone()[0]
        result = self.core.prepare_revision_validation(self.binding)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["purpose"], "candidate_validation_only")
        self.assertIn("Confirm RGBA mode", result["content"])
        self.assertEqual(before, self.core.store.db.execute("SELECT COUNT(*) FROM invocations").fetchone()[0])
        self.assertEqual(self.current(), self.saved["version_id"])

    def test_passing_checks_activate_and_later_run_delivers_revision(self):
        result = self.core.complete_revision_validation(self.receipt())
        self.assertTrue(result["activated"], result)
        self.assertEqual(self.current(), self.revised["version_id"])
        later = self.core.toolbox_run(self.saved["capability_id"])
        self.assertEqual(later["version_id"], self.revised["version_id"])
        self.assertIn("Confirm RGBA mode", later["result"]["content"])
        self.assertEqual(later["task_outcome"], "unknown")
        self.assertTrue(self.core.prepare_revision_validation(self.binding)["already_active"])

    def test_failed_assertion_keeps_current_and_is_available_for_next_revision(self):
        receipt = self.receipt()
        receipt["cases"][0].update(status="failed", failed_assertions=[0])
        receipt["cases"][1].update(status="skipped", result_hash="not-executed")
        result = self.core.complete_revision_validation(receipt)
        self.assertFalse(result["activated"])
        self.assertEqual(self.current(), self.saved["version_id"])
        self.assertEqual(self.core.prepare_revision_validation(self.binding)["previous_validation"], receipt)
        later = self.core.toolbox_run(self.saved["capability_id"])
        summary = later["result"]["reuse_summary"]["observations"][0]["revision_verification"]
        self.assertEqual(summary["outcome"], "failed")

    def test_regression_failure_before_new_case_invalidates_earlier_pass_evidence(self):
        verify_version(self.core, self.revised)
        receipt = self.receipt()
        receipt["cases"].reverse()
        receipt["cases"][0]["status"] = "failed"
        receipt["cases"][1]["status"] = "skipped"
        self.assertTrue(self.core.complete_revision_validation(receipt)["ok"])
        self.assertFalse(self.core.promote_version(self.revised["version_id"], "must not use earlier evidence")["ok"])

    def test_retry_is_idempotent_and_cannot_undo_later_rollback(self):
        receipt = self.receipt()
        self.assertTrue(self.core.complete_revision_validation(receipt)["activated"])
        self.assertTrue(self.core.complete_revision_validation(receipt)["duplicate"])
        self.assertTrue(self.core.rollback_version(self.saved["capability_id"], self.saved["version_id"], "fixture rollback")["ok"])
        replay = self.core.complete_revision_validation(receipt)
        self.assertTrue(replay["duplicate"])
        self.assertFalse(replay["active"])
        self.assertEqual(self.current(), self.saved["version_id"])

    def test_same_run_id_cannot_change_receipt(self):
        receipt = self.receipt()
        self.core.complete_revision_validation(receipt)
        receipt["cases"][0]["purpose"] = "Changed evidence"
        result = self.core.complete_revision_validation(receipt)
        self.assertEqual(result["error"]["reason_code"], "VALIDATION_RECEIPT_CONFLICT")

    def test_binding_mismatch_is_rejected_without_evidence(self):
        for key in self.binding:
            with self.subTest(key=key):
                receipt = copy.deepcopy(self.receipt())
                receipt["binding"][key] = "wrong"
                self.assertFalse(self.core.complete_revision_validation(receipt)["ok"])
        self.assertEqual(self.core.store.db.execute("SELECT COUNT(*) FROM evidence_events WHERE event_type = ?", (EVENT_REVISION_VALIDATED,)).fetchone()[0], 0)

    def test_current_version_change_between_execution_and_completion_blocks_activation(self):
        self.assertTrue(self.core.prepare_revision_validation(self.binding)["ok"])
        other = self.core.toolbox_learn(feedback(self.delivery, amendment={"checks": ["Another valid output check"]}))
        verify_version(self.core, other)
        self.core.promote_version(other["version_id"], "another host finished first")
        result = self.core.complete_revision_validation(self.receipt())
        self.assertEqual(result["error"]["reason_code"], "CURRENT_VERSION_CONFLICT")
        self.assertEqual(self.current(), other["version_id"])

    def test_quarantine_between_execution_and_completion_blocks_activation(self):
        self.core.quarantine_version(self.revised["version_id"], "fixture")
        self.assertFalse(self.core.complete_revision_validation(self.receipt())["ok"])
        self.assertEqual(self.current(), self.saved["version_id"])

    def test_receipt_requires_coverage_real_assertions_and_bounded_data(self):
        for alter in (lambda r: r["cases"].pop(),
                      lambda r: r["cases"][1].update(role="new"),
                      lambda r: r["cases"][1].update(id="new"),
                      lambda r: r["cases"][0].update(assertion_count=0),
                      lambda r: r["cases"][0].update(failed_assertions=[0]),
                      lambda r: r.update(outcome="passed"),
                      lambda r: r["cases"][0].update(purpose="x" * 241)):
            receipt = self.receipt()
            alter(receipt)
            self.assertFalse(self.core.complete_revision_validation(receipt)["ok"])

    def test_targeted_save_revisions_also_have_base_lineage(self):
        saved = self.save()
        revised = self.save(candidate(revision_of=saved, content="Check request timings, then compare the transport counters."))
        self.assertEqual(revised["revision_validation"]["base_version_id"], saved["version_id"])
        self.assertTrue(self.core.prepare_revision_validation(revised["revision_validation"])["ok"])

    def test_older_reuse_candidates_recover_lineage_from_the_feedback(self):
        with self.core.store.transaction() as db:
            db.execute("UPDATE evidence_events SET summary = NULL WHERE event_type = ? AND version_id = ?", (EVENT_PROCEDURE_SAVED, self.revised["version_id"]))
        self.assertTrue(self.core.prepare_revision_validation(self.binding)["ok"])

    def test_persistence_failure_after_promotion_rolls_back_both_evidence_and_switch(self):
        original = self.core.evidence.record
        def fail(event, **kwargs):
            if event == EVENT_REVISION_VALIDATED:
                raise sqlite3.OperationalError("fixture persistence failure")
            return original(event, **kwargs)
        with patch.object(self.core.evidence, "record", side_effect=fail):
            result = self.core.complete_revision_validation(self.receipt())
        self.assertEqual(result["error"]["code"], "SAVE_PERSISTENCE_FAILED")
        self.assertEqual(self.current(), self.saved["version_id"])
        self.assertEqual(self.core.registry.get_version(self.revised["version_id"])["status"], "candidate")
        self.assertEqual(self.core.evidence.verification_summary(self.revised["version_id"])["status"], "unverified")

    def test_known_environment_conflict_is_rejected_before_validation(self):
        row = self.core.registry.get_version(self.revised["version_id"])
        manifest = json.loads(row["manifest_json"])
        manifest["applicability"] = {"harnesses": ["codex"]}
        revision = self.save({"protocol_version": 1, "manifest": manifest, "content": row["content"],
                              "target_capability_id": self.saved["capability_id"],
                              "base_version_id": self.saved["version_id"],
                              "base_content_hash": self.saved["content_hash"]})
        result = self.core.prepare_revision_validation(revision["revision_validation"], {"harnesses": ["dsh"]})
        self.assertEqual(result["error"]["reason_code"], "APPLICABILITY_MISMATCH")
