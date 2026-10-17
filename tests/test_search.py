"""Deterministic keyword retrieval and hard filters (P0-SLIM §4.1, §8, §11.1)."""
from __future__ import annotations

from tests.helpers import CONTENT, CoreTest, candidate
from toolseed import ToolSeed

REVIEW_CONTENT = CONTENT + "\n4. 执行前确认 rm -rf /tmp/cache 的影响。"


class SearchTest(CoreTest):
    case = "search"

    def test_keyword_match_returns_a_card(self) -> None:
        saved = self.save()
        results = self.core.toolbox_search("timeout")["results"]
        self.assertEqual(len(results), 1)
        card = results[0]
        self.assertEqual(card["capability_id"], saved["capability_id"])
        self.assertEqual(card["version"], 1)
        self.assertEqual(card["kind"], "procedure")
        self.assertIn("when_to_use", card)
        self.assertIn("not_for", card)
        self.assertIn("content_excerpt", card)
        self.assertNotIn("content", card)

    def test_chinese_keywords_match_chinese_manifest(self) -> None:
        saved = self.save()
        for query in ("超时", "分层排查", "请求超时"):
            results = self.core.toolbox_search(query)["results"]
            self.assertEqual(
                [card["capability_id"] for card in results],
                [saved["capability_id"]],
                query,
            )

    def test_chinese_query_does_not_match_unrelated_content(self) -> None:
        self.save()
        self.assertEqual(self.core.toolbox_search("凭据无效")["results"], [])

    def test_no_match_returns_an_empty_list(self) -> None:
        self.save()
        self.assertEqual(self.core.toolbox_search("kubernetes operator")["results"], [])

    def test_direct_id_lookup_returns_only_that_capability(self) -> None:
        first = self.save()
        self.save(candidate(manifest={"name": "another_method"}, content=CONTENT + "\n4. 别的路径。"))
        results = self.core.toolbox_search(first["capability_id"])["results"]
        self.assertEqual([card["capability_id"] for card in results], [first["capability_id"]])

    def test_default_results_are_capped_at_three(self) -> None:
        for index in range(6):
            self.save(candidate(manifest={"name": f"timeout_method_{index}"}))
        results = self.core.toolbox_search("timeout")["results"]
        self.assertEqual(len(results), 3)

    def test_max_results_can_be_configured_up_to_five(self) -> None:
        self.core.close()
        self.core = ToolSeed(str(self.dir), max_results=5)
        for index in range(6):
            self.save(candidate(manifest={"name": f"timeout_method_{index}"}))
        results = self.core.toolbox_search("timeout")["results"]
        self.assertEqual(len(results), 5)

    def test_invalid_max_results_is_rejected(self) -> None:
        for value in (0, 6, True, "3"):
            with self.assertRaises(ValueError):
                ToolSeed(str(self.dir / "invalid"), max_results=value)

    def test_candidate_versions_are_filtered_out(self) -> None:
        self.save(candidate(content=REVIEW_CONTENT))
        self.assertEqual(self.core.toolbox_search("timeout")["results"], [])

    def test_applicability_conflict_is_filtered_before_ranking(self) -> None:
        self.save(candidate(manifest={"applicability": {"harnesses": ["cursor"]}}))
        blocked = self.core.toolbox_search("timeout", {"harnesses": ["vscode"]})
        allowed = self.core.toolbox_search("timeout", {"harnesses": ["cursor"]})
        unknown = self.core.toolbox_search("timeout")
        self.assertEqual(blocked["results"], [])
        self.assertEqual(len(allowed["results"]), 1)
        self.assertEqual(len(unknown["results"]), 1)

    def test_name_matches_rank_before_content_matches(self) -> None:
        name_match = self.save(candidate(manifest={"name": "timeout_primary"}))
        content_match = self.save(
            candidate(
                manifest={"name": "unrelated_method", "tags": [], "description": "generic"},
                content="timeout\ntimeout\ntimeout\n",
            )
        )
        results = self.core.toolbox_search("timeout")["results"]
        self.assertEqual(results[0]["capability_id"], name_match["capability_id"])
        self.assertIn(
            content_match["capability_id"], [card["capability_id"] for card in results]
        )

    def test_empty_query_is_invalid(self) -> None:
        self.assertEqual(self.core.toolbox_search("")["error"]["code"], "INVALID_ARGUMENT")
        self.assertEqual(self.core.toolbox_search("   ")["error"]["code"], "INVALID_ARGUMENT")

    def test_non_string_query_is_invalid(self) -> None:
        self.assertEqual(self.core.toolbox_search(None)["error"]["code"], "INVALID_ARGUMENT")

    def test_non_object_context_is_invalid(self) -> None:
        result = self.core.toolbox_search("timeout", context="not an object")
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")

    def test_search_is_recorded_as_an_event(self) -> None:
        self.save()
        self.core.toolbox_search("timeout")
        self.core.toolbox_search("no match here")
        stats = self.core.toolbox_stats()
        self.assertEqual(stats["search"]["requests"], 2)
        self.assertEqual(stats["search"]["exposed_candidates"], 1)
        self.assertEqual(self.core.evidence.event_counts().get("search_performed"), 2)
