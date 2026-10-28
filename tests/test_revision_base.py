"""Full revisions must identify the immutable method actually read by a caller."""
from __future__ import annotations

from tests.helpers import CONTENT, CoreTest, candidate, verify_version
from tests.test_learning import experience
from toolseed import ToolSeed


class RevisionBaseTest(CoreTest):
    case = "revision-base"

    def test_full_save_requires_both_base_fields_without_creating_a_version(self):
        first = self.save()
        for missing in ("base_version_id", "base_content_hash"):
            payload = candidate(revision_of=first, content=CONTENT + "\nA revised method.")
            payload.pop(missing)
            result = self.core.toolbox_save(payload)
            self.assertEqual(result["error"]["reason_code"], "REVISION_BASE_REQUIRED")
        self.assertEqual(len(self.core.registry.list_versions(first["capability_id"])), 1)

    def test_full_learning_requires_the_base_of_the_method_read(self):
        first = self.core.toolbox_learn(experience())
        result = self.core.toolbox_learn(experience(target_capability_id=first["capability_id"],
                                                   method="A complete revised method"))
        self.assertEqual(result["error"]["reason_code"], "REVISION_BASE_REQUIRED")
        revised = self.core.toolbox_learn(experience(target_capability_id=first["capability_id"],
            base_version_id=first["version_id"], base_content_hash=first["content_hash"],
            method="A complete revised method"))
        self.assertEqual(revised["status"], "accepted")
        self.assertEqual(revised["revision_validation"]["base_version_id"], first["version_id"])

    def test_old_read_is_rejected_after_another_connection_promotes_a_revision(self):
        first = self.save()
        old_read = self.core.toolbox_run(first["capability_id"])
        other = ToolSeed(self.dir)
        try:
            revised = other.toolbox_save(candidate(revision_of=first, content=CONTENT + "\nPreserve boundary B."))
            verify_version(other, revised)
            self.assertTrue(other.promote_version(revised["version_id"], "fixture verification")["promoted"])
        finally:
            other.close()
        stale = self.core.toolbox_save(candidate(revision_of=old_read, content=CONTENT + "\nChange A."))
        self.assertEqual(stale["error"]["reason_code"], "CURRENT_VERSION_CONFLICT")
        current = self.core.toolbox_run(first["capability_id"])
        self.assertIn("Preserve boundary B.", current["result"]["content"])
        self.assertEqual(len(self.core.registry.list_versions(first["capability_id"])), 2)

    def test_stale_full_learning_cannot_append_an_observation_or_candidate(self):
        first = self.core.toolbox_learn(experience())
        revised = self.core.toolbox_learn(experience(target_capability_id=first["capability_id"],
            base_version_id=first["version_id"], base_content_hash=first["content_hash"], method="New boundary B."))
        verify_version(self.core, revised)
        self.assertTrue(self.core.promote_version(revised["version_id"], "fixture verification")["promoted"])
        count = self.core.store.db.execute("SELECT COUNT(*) FROM evidence_events WHERE event_type='experience_learned'").fetchone()[0]
        result = self.core.toolbox_learn(experience(target_capability_id=first["capability_id"],
            base_version_id=first["version_id"], base_content_hash=first["content_hash"], method="Old method plus A."))
        self.assertEqual(result["error"]["reason_code"], "CURRENT_VERSION_CONFLICT")
        self.assertEqual(self.core.store.db.execute("SELECT COUNT(*) FROM evidence_events WHERE event_type='experience_learned'").fetchone()[0], count)

    def test_hash_mismatch_and_foreign_base_are_rejected(self):
        first = self.save()
        payload = candidate(revision_of=first, content=CONTENT + "\nRevised.")
        payload["base_content_hash"] = "sha256:" + "0" * 64
        self.assertEqual(self.core.toolbox_save(payload)["error"]["reason_code"], "REVISION_BASE_MISMATCH")
        other = self.save(candidate(manifest={"name": "other"}))
        payload.update(base_version_id=other["version_id"], base_content_hash=other["content_hash"])
        self.assertEqual(self.core.toolbox_save(payload)["error"]["reason_code"], "CURRENT_VERSION_CONFLICT")

    def test_bound_retry_deduplicates_and_baseline_fields_do_not_apply_to_new_capabilities(self):
        first = self.save()
        payload = candidate(revision_of=first, content=CONTENT + "\nRevised.")
        saved = self.core.toolbox_save(payload)
        retry = self.core.toolbox_save(payload)
        self.assertTrue(retry["duplicate"])
        self.assertEqual(retry["version_id"], saved["version_id"])
        payload.pop("target_capability_id")
        self.assertIn("error", self.core.toolbox_save(payload))

    def test_isolated_base_can_receive_a_bound_repair_and_idempotent_retry(self):
        first = self.save()
        self.core.quarantine_version(first["version_id"], "fixture isolation")
        payload = candidate(revision_of=first, content=CONTENT + "\nA repair proposal.")
        revised = self.core.toolbox_save(payload)
        self.assertEqual(revised["version_status"], "candidate")
        self.assertEqual(revised["revision_validation"]["base_version_id"], first["version_id"])
        self.assertEqual(self.core.toolbox_save(payload)["version_id"], revised["version_id"])
