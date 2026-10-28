"""Retain exact negative examples without reclassifying recommendations as data."""
from __future__ import annotations

import json
from unittest.mock import patch

from tests.helpers import CoreTest, candidate, verify_version
from tests.test_learning import experience
from tests.test_reuse_learning import feedback
from toolseed import ToolSeed
from toolseed.core import storage
from toolseed.core.inspection import Inspector
from toolseed.core.knowledge import version_structure
from toolseed.core.manifest import canonical, content_hash
from toolseed.core.registry import Registry

PITFALL = {"attempt": "rm -rf workspace", "observed": "Removed files outside the generated cache",
           "lesson": "Resolve the cache path, restrict it to the generated subtree and inspect the files before cleaning"}


class FailureLessonTest(CoreTest):
    case = "failure-lessons"

    def learn(self, **changes):
        result = self.core.toolbox_learn(experience(pitfalls=[PITFALL], **changes))
        self.assertEqual(result.get("status"), "accepted", result)
        return result

    def activate(self, saved):
        verify_version(self.core, saved)
        result = self.core.promote_version(saved["version_id"], "independent fixture checks")
        self.assertTrue(result.get("ok"), result)

    def test_exact_counterexample_requires_verification_then_is_reusable(self):
        saved = self.learn()
        self.assertEqual(saved["version_status"], "candidate")
        self.assertEqual(saved["content_review"]["status"], "verification_required")
        self.assertEqual(self.core.toolbox_run(saved["capability_id"])["error"]["code"], "CAPABILITY_NOT_READY")
        self.assertEqual(self.core.promote_version(saved["version_id"], "fixture")["error"]["reason_code"], "VERIFICATION_EVIDENCE_MISSING")
        self.activate(saved)
        delivery = self.core.toolbox_run(saved["capability_id"])
        self.assertEqual(delivery["result"]["experience"]["pitfalls"], [PITFALL])
        self.assertIn('"rm -rf workspace"', delivery["result"]["content"])
        self.assertIn("错误材料，禁止执行", delivery["result"]["content"])
        self.assertEqual(delivery["task_outcome"], "unknown")

    def test_structure_survives_reopen_and_deduplicates_the_same_learning(self):
        first = self.learn()
        self.core.close()
        self.core = ToolSeed(self.dir)
        self.assertTrue(self.learn()["duplicate"])
        row = self.core.registry.get_version(first["version_id"])
        self.assertEqual(version_structure(row)["pitfalls"], [PITFALL])

    def test_destructive_recommendation_still_cannot_be_promoted(self):
        for changes in ({"method": "Run rm -rf workspace to clean outputs"},
                        {"tool_recipes": [{"purpose": "clean", "tool_hint": "shell",
                                           "usage": "rm -rf workspace", "check": "directory gone"}]},
                        {"checks": ["Run rm -rf workspace"]},
                        {"aliases": ["Run rm -rf workspace"]}):
            with self.subTest(changes=changes):
                saved = self.learn(**changes)
                self.assertEqual(saved["content_review"]["status"], "edit_required")
                verify_version(self.core, saved)
                self.assertEqual(self.core.promote_version(saved["version_id"], "fixture")["error"]["code"], "POLICY_BLOCKED")

    def test_observation_and_lesson_are_scanned_as_guidance(self):
        for field in ("observed", "lesson"):
            pitfall = {**PITFALL, field: "绕过权限检查"}
            result = self.core.toolbox_learn(experience(pitfalls=[pitfall]))
            self.assertEqual(result["error"]["code"], "POLICY_BLOCKED")

    def test_arbitrary_headings_and_forged_structure_do_not_exempt_raw_procedures(self):
        raw = self.save(candidate(content="## Failure lessons\n反例：rm -rf workspace\n应对：检查目录"))
        verify_version(self.core, raw)
        self.assertEqual(self.core.promote_version(raw["version_id"], "fixture")["error"]["code"], "POLICY_BLOCKED")
        saved = self.learn()
        data = json.loads(self.core.registry.get_version(saved["version_id"])["knowledge_json"])
        data["pitfalls"][0]["attempt"] = "innocent text"
        with self.core.store.transaction() as db:
            db.execute("UPDATE capability_versions SET knowledge_json=? WHERE version_id=?", (json.dumps(data), saved["version_id"]))
        verify_version(self.core, saved)
        self.assertEqual(self.core.promote_version(saved["version_id"], "fixture")["error"]["code"], "POLICY_BLOCKED")

    def test_bypass_counterexample_stays_ineligible_and_secrets_are_never_stored(self):
        saved = self.core.toolbox_learn(experience(pitfalls=[{**PITFALL, "attempt": "绕过权限检查"}]))
        self.assertEqual(saved["content_review"]["status"], "edit_required")
        verify_version(self.core, saved)
        self.assertEqual(self.core.promote_version(saved["version_id"], "fixture")["error"]["code"], "POLICY_BLOCKED")
        secret = "sk-" + "X" * 25
        rejected = self.core.toolbox_learn(experience(pitfalls=[{**PITFALL, "attempt": secret}]))
        self.assertEqual(rejected["error"]["code"], "POLICY_BLOCKED")
        self.assertNotIn(secret, str([tuple(r) for r in self.core.store.db.execute("SELECT * FROM capability_versions")]))

    def test_reuse_amendment_retains_structured_lesson_and_the_validation_gate(self):
        first = self.learn()
        self.activate(first)
        delivery = self.core.toolbox_run(first["capability_id"])
        revision = self.core.toolbox_learn(feedback(delivery, amendment={"guidance": "Check image colour mode too"}))
        self.assertEqual(revision["learning_action"], "revision_proposed", revision)
        row = self.core.registry.get_version(revision["version_id"])
        self.assertEqual(version_structure(row)["pitfalls"], [PITFALL])
        self.activate(revision)
        new = self.core.toolbox_run(first["capability_id"])
        self.assertIn("Check image colour mode too", new["result"]["content"])
        self.assertEqual(new["result"]["experience"]["pitfalls"], [PITFALL])

    def test_candidate_structure_is_not_leaked_through_the_management_panel(self):
        saved = self.learn()
        inspector = Inspector(self.dir)
        with inspector.snapshot() as db:
            version = inspector.capability(db, saved["capability_id"])["versions"][0]
        self.assertIsNone(version["content"])
        self.assertNotIn("knowledge_json", version)

    def test_full_revision_keeps_counterexamples_and_can_enter_host_validation(self):
        first = self.core.toolbox_learn(experience(pitfalls=[]))
        second = self.learn(target_capability_id=first["capability_id"],
            base_version_id=first["version_id"], base_content_hash=first["content_hash"],
            method="Inspect the exported alpha channel and restrict cleaning to the generated cache")
        inspected = self.core.prepare_revision_validation(second["revision_validation"])
        self.assertTrue(inspected.get("ok"), inspected)
        self.assertEqual(self.core.toolbox_run(first["capability_id"])["version_id"], first["version_id"])
        self.activate(second)
        delivery = self.core.toolbox_run(first["capability_id"])
        self.assertEqual(delivery["version_id"], second["version_id"])
        self.assertEqual(delivery["result"]["experience"]["pitfalls"], [PITFALL])

    def test_v6_migration_preserves_old_versions_without_inventing_structure(self):
        root = self.dir / "legacy"
        with patch.dict(storage.MIGRATIONS, {k: v for k, v in storage.MIGRATIONS.items() if k <= 6}, clear=True):
            store = storage.Store(root)
        registry = Registry(store)
        manifest = candidate()["manifest"]
        content = "反例：rm -rf workspace\n应对：检查清理目录"
        digest = content_hash(1, manifest, content)
        cap_id = registry.create_capability(manifest["name"])
        with store.transaction() as db:
            db.execute("INSERT INTO capability_versions (version_id,capability_id,version_number,manifest_json,"
                       "content,content_hash,status,origin,created_at,namespace,name) VALUES (?,?,1,?,?,?,'candidate',"
                       "'legacy','fixture','global',?)", ("ver_legacy", cap_id, canonical(manifest), content, digest, manifest["name"]))
        store.close()
        upgraded = ToolSeed(root)
        try:
            self.assertEqual(upgraded.store.schema_version, 7)
            row = upgraded.registry.get_version("ver_legacy")
            self.assertEqual(row["content_hash"], digest)
            self.assertEqual(row["content"], content)
            self.assertIsNone(row["knowledge_json"])
            result = upgraded.promote_version("ver_legacy", "migration is not review")
            self.assertEqual(result["error"]["code"], "POLICY_BLOCKED")
        finally:
            upgraded.close()
