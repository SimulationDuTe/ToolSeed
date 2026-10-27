"""Reuse feedback enriches the original capability, never inventing adoption."""
from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
import sqlite3
import unittest
from unittest.mock import patch

from tests.helpers import CoreTest, candidate, verify_version
from tests.test_learning import experience
from toolseed.core.evidence import EVENT_REUSE_LEARNED


def feedback(delivery, **changes):
    data = {"target_capability_id": delivery["capability_id"],
            "reuse": {key: delivery[key] for key in ("invocation_id", "version_id", "content_hash")},
            "validation": "Reopened PNG has transparent background; one exporter tested.",
            "reuse_reason": "Retain the exported-file check that prevented another preview mistake."}
    data["reuse"].update(application="applied", actions="Used the alpha inspection and reopened the exported file.")
    data.update(changes)
    return data


class ReuseLearningTest(CoreTest):
    case = "reuse-learning"

    def setUp(self):
        super().setUp()
        self.saved = self.core.toolbox_learn(experience())
        self.delivery = self.core.toolbox_run(self.saved["capability_id"], options={"task_id": "A", "session_id": "session-A"})

    def submit(self, **changes):
        result = self.core.toolbox_learn(feedback(self.delivery, **changes))
        self.assertEqual(result.get("status"), "accepted", result)
        return result

    def test_observation_updates_original_capability_without_new_version(self):
        result = self.submit()
        self.assertEqual(result["learning_action"], "observation_added")
        self.assertEqual(result["version_id"], self.saved["version_id"])
        stats = self.core.toolbox_stats()
        self.assertEqual(stats["capabilities"]["total"], 1)
        self.assertEqual(stats["versions"]["total"], 1)
        self.assertEqual(stats["task_outcomes"]["signals"], 0)
        self.assertEqual(stats["verifications"]["passed"], 0)
        row = self.core.store.db.execute("SELECT * FROM evidence_events WHERE event_id = ?", (result["learning_event_id"],)).fetchone()
        self.assertEqual(row["invocation_id"], self.delivery["invocation_id"])
        self.assertEqual(row["task_id"], "A")
        self.assertEqual(row["source_type"], "agent")
        self.assertEqual(row["outcome"], "unknown")

    def test_later_search_and_delivery_show_prior_reuse_observation(self):
        self.submit()
        card = self.core.toolbox_search("sprite alpha")["results"][0]
        summary = card["reuse_summary"]
        self.assertFalse(summary["independently_verified"])
        self.assertEqual(summary["observations"][0]["application"], "applied")
        later = self.core.toolbox_run(self.saved["capability_id"])
        self.assertEqual(later["result"]["reuse_summary"], summary)
        self.assertEqual(later["result"]["verification_summary"], {"status": "unverified"})

    def test_retry_is_idempotent_even_when_context_annotations_change(self):
        first = self.submit()
        second = self.core.toolbox_learn(feedback(self.delivery), {"harness": "dsh"})
        self.assertEqual(first["learning_event_id"], second["learning_event_id"])
        self.assertTrue(second["feedback_duplicate"])
        self.assertEqual(self.core.store.db.execute("SELECT COUNT(*) FROM evidence_events WHERE event_type = ?", (EVENT_REUSE_LEARNED,)).fetchone()[0], 1)

    def test_amendment_preserves_original_method_and_requires_promotion(self):
        result = self.submit(amendment={"guidance": "Check the exported colour mode before inspecting alpha.",
                                        "checks": ["Verify RGBA mode"], "not_for": ["Indexed-colour output"]})
        self.assertEqual(result["learning_action"], "revision_proposed")
        self.assertEqual(result["capability_id"], self.saved["capability_id"])
        self.assertEqual(result["version_status"], "candidate")
        revised = self.core.registry.get_version(result["version_id"])
        original = self.core.registry.get_version(self.saved["version_id"])
        self.assertTrue(revised["content"].startswith(original["content"]))
        self.assertIn("Check the exported colour mode", revised["content"])
        self.assertEqual(json.loads(revised["manifest_json"])["not_for"], ["Formats without an alpha channel", "Indexed-colour output"])
        self.assertEqual(self.core.toolbox_run(self.saved["capability_id"])["version_id"], self.saved["version_id"])
        self.assertEqual(self.core.promote_version(result["version_id"], "fixture")["error"]["reason_code"], "VERIFICATION_EVIDENCE_MISSING")

    def test_repeated_amendment_reuses_candidate_and_source_binding(self):
        amendment = {"guidance": "Verify colour mode before alpha inspection."}
        first = self.submit(amendment=amendment)
        second = self.submit(amendment=amendment)
        self.assertEqual(first["learning_event_id"], second["learning_event_id"])
        self.assertEqual(first["version_id"], second["version_id"])
        self.assertEqual(first["reuse_source"]["version_id"], self.saved["version_id"])
        self.assertEqual(self.core.toolbox_stats()["versions"]["total"], 2)

    def test_same_amendment_from_another_use_does_not_duplicate_version(self):
        first = self.submit(amendment={"checks": ["Verify colour mode"]})
        later = self.core.toolbox_run(self.saved["capability_id"])
        second = self.core.toolbox_learn(feedback(later, amendment={"checks": ["Verify colour mode"]}))
        self.assertEqual(first["version_id"], second["version_id"])
        self.assertNotEqual(first["learning_event_id"], second["learning_event_id"])
        self.assertEqual(self.core.toolbox_stats()["versions"]["total"], 2)

    def test_changed_current_version_blocks_stale_amendment_but_keeps_observations(self):
        proposed = self.submit(amendment={"guidance": "Verify colour mode."})
        verify_version(self.core, proposed)
        self.assertTrue(self.core.promote_version(proposed["version_id"], "verified fixture")["ok"])
        replay = self.submit(amendment={"guidance": "Verify colour mode."})
        self.assertTrue(replay["feedback_duplicate"])
        stale = self.core.toolbox_learn(feedback(self.delivery, amendment={"guidance": "Different addition"}))
        self.assertEqual(stale["error"]["reason_code"], "REUSE_VERSION_CHANGED")
        self.assertEqual(self.submit(validation="Additional old-version observation")["learning_action"], "observation_added")
        current = self.core.toolbox_run(self.saved["capability_id"])
        self.assertEqual(current["result"]["reuse_summary"]["observations"], [])

    def test_mismatched_capability_version_hash_and_invocation_are_rejected(self):
        other = self.core.toolbox_learn(experience(name="other"))
        for field, value in [("version_id", other["version_id"]), ("content_hash", "sha256:" + "0" * 64),
                             ("invocation_id", "inv_missing")]:
            data = feedback(self.delivery)
            data["reuse"][field] = value
            self.assertIn("error", self.core.toolbox_learn(data))
        self.assertIn("error", self.core.toolbox_learn(feedback(self.delivery, target_capability_id=other["capability_id"])))
        self.assertEqual(self.core.evidence.reuse_summary(self.saved["version_id"])["observations"], [])

    def test_conflicting_known_task_or_session_is_rejected(self):
        for context in ({"task_id": "B"}, {"session_id": "B"}):
            self.assertEqual(self.core.toolbox_learn(feedback(self.delivery), context)["error"]["code"], "CONTRACT_VIOLATION")

    def test_not_applied_is_retained_without_claiming_adoption_or_allowing_repair(self):
        data = feedback(self.delivery)
        data["reuse"].update(application="not_applied", actions="The exporter was unsupported, so I did not apply the method.")
        result = self.core.toolbox_learn(data)
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(self.core.evidence.reuse_summary(self.saved["version_id"])["observations"][0]["application"], "not_applied")
        data["amendment"] = {"guidance": "An untested alternative"}
        self.assertIn("error", self.core.toolbox_learn(data))

    def test_latest_observation_per_invocation_is_shown_without_deleting_history(self):
        self.submit(validation="First observation")
        self.submit(validation="Corrected observation")
        summary = self.core.evidence.reuse_summary(self.saved["version_id"])
        self.assertEqual(len(summary["observations"]), 1)
        self.assertEqual(summary["observations"][0]["validation"], "Corrected observation")
        self.assertEqual(self.core.store.db.execute("SELECT COUNT(*) FROM evidence_events WHERE event_type = ?", (EVENT_REUSE_LEARNED,)).fetchone()[0], 2)

    def test_summary_is_bounded_to_three_distinct_uses(self):
        for i in range(5):
            delivery = self.core.toolbox_run(self.saved["capability_id"])
            self.core.toolbox_learn(feedback(delivery, validation="x" * 2000))
        observations = self.core.evidence.reuse_summary(self.saved["version_id"])["observations"]
        self.assertEqual(len(observations), 3)
        self.assertTrue(all(len(item["validation"]) == 500 for item in observations))

    def test_storage_failure_rolls_back_amendment_and_feedback_together(self):
        original = self.core.evidence.record

        def fail(event_type, **kwargs):
            if event_type == EVENT_REUSE_LEARNED:
                raise sqlite3.OperationalError("fixture failure")
            return original(event_type, **kwargs)

        with patch.object(self.core.evidence, "record", side_effect=fail):
            result = self.core.toolbox_learn(feedback(self.delivery, amendment={"guidance": "Verify colour mode"}))
        self.assertEqual(result["error"]["code"], "SAVE_PERSISTENCE_FAILED")
        self.assertEqual(self.core.toolbox_stats()["versions"]["total"], 1)
        self.assertEqual(self.core.evidence.reuse_summary(self.saved["version_id"])["observations"], [])

    def test_bad_shapes_limits_secrets_and_active_bypass_are_rejected(self):
        for change in ({"amendment": {}}, {"amendment": {"method": "replace"}}, {"validation": "x" * 2001},
                       {"validation": "sk-" + "X" * 25}, {"validation": "绕过权限检查"},
                       {"amendment": {"guidance": "绕过权限检查"}}, {"method": "do not silently mix modes"}, {"reuse": {}}):
            self.assertIn("error", self.core.toolbox_learn(feedback(self.delivery, **change)))
        excessive = feedback(self.delivery, amendment={"not_for": [f"New exclusion {i}" for i in range(10)]})
        self.assertIn("error", self.core.toolbox_learn(excessive))
        self.assertEqual(self.core.toolbox_stats()["versions"]["total"], 1)

    def test_ambiguous_feedback_stays_in_audit_not_future_guidance(self):
        result = self.submit(validation="反例：绕过权限检查")
        self.assertEqual(self.core.evidence.reuse_summary(self.saved["version_id"])["observations"], [])
        row = self.core.store.db.execute("SELECT summary FROM evidence_events WHERE event_id = ?", (result["learning_event_id"],)).fetchone()
        self.assertIn("反例", row["summary"])

    def test_archived_or_quarantined_capability_cannot_receive_amendment(self):
        self.core.quarantine(self.saved["capability_id"], "fixture")
        self.assertEqual(self.core.toolbox_learn(feedback(self.delivery, amendment={"checks": ["new check"]}))["error"]["code"], "CAPABILITY_QUARANTINED")
        self.core.archive(self.saved["capability_id"], "fixture")
        self.assertEqual(self.core.toolbox_learn(feedback(self.delivery, amendment={"checks": ["new check"]}))["error"]["code"], "CAPABILITY_ARCHIVED")
        self.assertEqual(self.submit()["learning_action"], "observation_added")

    def test_old_directly_saved_procedure_can_be_amended_without_reformatting(self):
        saved = self.save(candidate())
        delivery = self.core.toolbox_run(saved["capability_id"])
        result = self.core.toolbox_learn(feedback(delivery, amendment={"checks": ["Compare the server timestamps"]}))
        updated = self.core.registry.get_version(result["version_id"])
        self.assertTrue(updated["content"].startswith(candidate()["content"]))
        self.assertEqual(updated["capability_id"], saved["capability_id"])

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "official SDK absent")
    def test_mcp_reuse_union_preserves_normal_learning_and_accepts_feedback(self):
        from mcp import Client

        from toolseed.mcp_server import create_server

        async def run():
            async with Client(create_server(self.core)) as client:
                result = await client.call_tool("toolbox_learn", {"experience": feedback(self.delivery)})
                self.assertEqual(result.structured_content["learning_action"], "observation_added")
        before = copy.deepcopy(self.delivery)
        asyncio.run(run())
        self.assertEqual(self.delivery, before)
