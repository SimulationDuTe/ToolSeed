"""Automatic recall spends context only on strong, applicable matches."""
from __future__ import annotations

from tests.helpers import CoreTest, candidate
from tests.test_learning import experience


class RecallTest(CoreTest):
    case = "recall"

    def recall(self, query, phase="task", **cues):
        return self.core.toolbox_search(query, {"recall": {"phase": phase, **cues}})

    def test_task_recall_returns_real_candidates_with_match_reasons(self):
        saved = self.core.toolbox_learn(experience())
        cards = self.recall("texture atlas alpha export")["results"]
        self.assertEqual(cards[0]["capability_id"], saved["capability_id"])
        self.assertIn("alpha", cards[0]["recall_match"]["task_terms"])
        self.assertNotIn("content", cards[0])

    def test_single_word_and_generic_overlap_stay_quiet(self):
        self.core.toolbox_learn(experience())
        self.assertEqual(self.recall("alpha")["results"], [])
        self.assertEqual(self.recall("please check the output file using tools")["results"], [])
        self.assertTrue(self.core.toolbox_search("alpha")["results"])

    def test_chinese_phrases_work_without_single_character_matches(self):
        self.save()
        self.assertTrue(self.recall("请求超时分层排查")["results"])
        self.assertEqual(self.recall("时")["results"], [])

    def test_exact_error_code_can_recall_a_failure_lesson(self):
        saved = self.core.toolbox_learn(experience(pitfalls=[{
            "attempt": "Export before source was loaded", "observed": "SOURCE_NOT_READY", "lesson": "Wait for source readiness"}]))
        cards = self.recall("new task", "error", error_codes=["SOURCE_NOT_READY"])["results"]
        self.assertEqual(cards[0]["capability_id"], saved["capability_id"])
        self.assertEqual(cards[0]["recall_match"]["error_codes"], ["SOURCE_NOT_READY"])
        self.assertEqual(self.recall("new task", "error", error_codes=["NOT_READY"])["results"], [])

    def test_tool_recipe_requires_tool_and_task_overlap(self):
        saved = self.core.toolbox_learn(experience())
        cards = self.recall("alpha", "tools", tool_hints=["mcp__images__inspect_alpha"])["results"]
        self.assertEqual(cards[0]["capability_id"], saved["capability_id"])
        self.assertEqual(self.recall("finance", "tools", tool_hints=["inspect_alpha"])["results"], [])
        self.assertEqual(self.recall("alpha", "tools", tool_hints=["inspect"])["results"], [])

    def test_exact_error_match_ranks_ahead_of_general_task_match(self):
        self.core.toolbox_learn(experience())
        specific = self.core.toolbox_learn(experience(name="alpha-error-specific", method="Handle EXPORT_FAILED before checking alpha"))
        cards = self.recall("alpha export", "error", error_codes=["EXPORT_FAILED"])["results"]
        self.assertEqual(cards[0]["capability_id"], specific["capability_id"])

    def test_only_two_candidates_are_returned(self):
        for i in range(4):
            self.core.toolbox_learn(experience(name=f"sprite-export-{i}"))
        self.assertEqual(len(self.recall("sprite alpha export")["results"]), 2)

    def test_recall_preserves_namespace_environment_and_lifecycle_gates(self):
        global_cap = self.core.toolbox_learn(experience())
        self.core.toolbox_learn(experience(name="other-workspace"), {"namespace": "private"})
        self.core.toolbox_learn(experience(name="linux-only", applicability={"operating_systems": ["linux"]}))
        pending = self.core.toolbox_learn(experience(name="pending-review", method="Review rm -rf /tmp/cache before proceeding"))
        self.assertEqual(pending["version_status"], "candidate")
        result = self.core.toolbox_search("sprite alpha export", {"operating_systems": ["windows"], "recall": {"phase": "task"}})
        self.assertEqual([r["capability_id"] for r in result["results"]], [global_cap["capability_id"]])
        self.core.archive(global_cap["capability_id"], "fixture")
        self.assertEqual(self.core.toolbox_search("sprite alpha export", {"operating_systems": ["windows"], "recall": {"phase": "task"}})["results"], [])

    def test_recall_direct_id_does_not_bypass_namespace_filter(self):
        saved = self.core.toolbox_learn(experience(), {"namespace": "private"})
        self.assertEqual(self.recall(saved["capability_id"])["results"], [])

    def test_bad_context_or_oversized_query_fails_without_a_search_event(self):
        for cue in (True, {"phase": "unknown"}, {"phase": "task", "raw_transcript": "text"},
                    {"phase": "tools", "tool_hints": ["x"] * 9}):
            self.assertIn("error", self.core.toolbox_search("sprite alpha", {"recall": cue}))
        self.assertIn("error", self.recall("x" * 601))
        self.assertEqual(self.core.toolbox_stats()["search"]["requests"], 0)

    def test_recall_does_not_save_query_or_claim_adoption(self):
        self.save(candidate())
        self.recall("timeout SECRET_QUERY_MARKER")
        events = str([tuple(row) for row in self.core.store.db.execute("SELECT * FROM evidence_events")])
        self.assertNotIn("SECRET_QUERY_MARKER", events)
        stats = self.core.toolbox_stats()
        self.assertEqual(stats["delivery"]["count"], 0)
        self.assertEqual(stats["task_outcomes"]["signals"], 0)
