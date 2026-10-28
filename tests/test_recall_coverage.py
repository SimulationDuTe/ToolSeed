"""Bilingual cues and library-size independent database round trips."""
from __future__ import annotations

import json

from tests.helpers import CoreTest, candidate
from tests.test_learning import experience


class RecallCoverageTest(CoreTest):
    case = "recall-coverage"

    def recall(self, query, **context):
        return self.core.toolbox_search(query, {"recall": {"phase": "task"}, **context})["results"]

    def test_chinese_symptom_recalls_english_experience_and_reports_concepts(self):
        saved = self.core.toolbox_learn(experience())
        cards = self.recall("透明图像导出后出现黑色底图")
        self.assertEqual(cards[0]["capability_id"], saved["capability_id"])
        self.assertIn("transparency", cards[0]["recall_match"]["concepts"])
        self.assertIn("export", cards[0]["recall_match"]["concepts"])
        self.assertTrue(self.core.toolbox_search("透明图片导出")["results"])

    def test_english_symptom_recalls_chinese_guidance(self):
        saved = self.core.toolbox_learn(experience(name="导出透明精灵", problem="图像导出后不透明",
            when_to_use="透明精灵导出后出现黑色背景", method="检查原图透明通道，导出 PNG，再重新打开检查。",
            triggers=[], aliases=[], pitfalls=[], tool_recipes=[], checks=[], tags=[]))
        self.assertEqual(self.recall("export transparent sprite black background")[0]["capability_id"], saved["capability_id"])

    def test_synonyms_of_one_concept_and_unrelated_requests_do_not_trigger_recall(self):
        self.core.toolbox_learn(experience())
        for query in ("透明", "透明 transparency alpha", "export exports 导出", "finance market forecast",
                      "请帮我检查文件输出结果"):
            with self.subTest(query=query):
                self.assertEqual(self.recall(query), [])

    def test_explicit_aliases_support_domain_vocabulary_beyond_builtin_concepts(self):
        saved = self.core.toolbox_learn(experience(name="bridge-cue", problem="Diagnose frobnication",
            when_to_use="Widget needs recalibration", method="Inspect widget state, reset calibration and compare readings.",
            aliases=["量子旋钮偏移复位"], triggers=["旋钮读数漂移"], pitfalls=[], tool_recipes=[], checks=[], tags=[]))
        self.assertEqual(self.recall("量子旋钮偏移复位")[0]["capability_id"], saved["capability_id"])
        delivered = self.core.toolbox_run(saved["capability_id"])
        self.assertEqual(delivered["result"]["experience"]["aliases"], ["量子旋钮偏移复位"])
        self.assertEqual(self.recall("螺丝")[0:1], [])

    def test_aliases_are_bounded_and_cannot_smuggle_new_recommended_instructions(self):
        for aliases in (["x"] * 13, ["x" * 161], "text"):
            self.assertEqual(self.core.toolbox_learn(experience(aliases=aliases))["error"]["code"], "CONTRACT_VIOLATION")
        self.assertEqual(self.core.toolbox_learn(experience(aliases=["绕过权限检查"]))["error"]["code"], "POLICY_BLOCKED")

    def test_cross_language_matches_keep_namespace_applicability_and_lifecycle_filters(self):
        first = self.core.toolbox_learn(experience())
        self.core.toolbox_learn(experience(name="private"), {"namespace": "private"})
        self.core.toolbox_learn(experience(name="linux", applicability={"operating_systems": ["linux"]}))
        self.core.toolbox_learn(experience(name="pending", method="Review rm -rf workspace"))
        query = "透明图像导出后出现黑色底图"
        cards = self.recall(query, operating_systems=["windows"])
        self.assertEqual([c["capability_id"] for c in cards], [first["capability_id"]])
        self.core.quarantine(first["capability_id"], "fixture")
        self.assertEqual(self.recall(query, operating_systems=["windows"]), [])

    def test_error_codes_with_hyphens_are_whole_identifiers_not_partial_matches(self):
        saved = self.core.toolbox_learn(experience(triggers=["ERR-ALPHA-0042"], aliases=[]))
        for code, expected in (("err-alpha-0042", True), ("ALPHA-0042", False)):
            cards = self.core.toolbox_search("irrelevant", {"recall": {"phase": "error", "error_codes": [code]}})["results"]
            self.assertEqual(bool(cards), expected)
            if cards:
                self.assertEqual(cards[0]["capability_id"], saved["capability_id"])

    def test_select_count_does_not_grow_with_library_size(self):
        for index in range(3):
            self.save(candidate(manifest={"name": f"alpha-export-{index}", "description": "sprite alpha export"}))

        def count():
            statements = []
            self.core.store.db.set_trace_callback(statements.append)
            try:
                cards = self.core.toolbox_search("sprite alpha export")["results"]
            finally:
                self.core.store.db.set_trace_callback(None)
            return cards, sum(s.lstrip().upper().startswith("SELECT") for s in statements)

        small, before = count()
        for index in range(100):
            self.save(candidate(manifest={"name": f"other-{index}", "description": "unrelated calibration"}))
        large, after = count()
        self.assertEqual(len(small), 3)
        self.assertEqual(len(large), 3)
        self.assertEqual(before, after)
        self.assertLessEqual(after, 12)
        pairs = self.core.registry.deliverable_capabilities()
        self.assertEqual(len(pairs), 103)
        for capability, version in pairs:
            self.assertEqual(capability["capability_id"], version["capability_id"])
            self.assertEqual(capability["current_version_id"], version["version_id"])
            self.assertEqual(capability["name"], json.loads(version["manifest_json"])["name"])
