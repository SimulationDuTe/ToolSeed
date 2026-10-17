"""Duplicate-candidate hints (P1: suggest, never merge)."""
from __future__ import annotations

from tests.helpers import CONTENT, CoreTest, candidate


class DuplicateHintTest(CoreTest):
    case = "duplicate-hints"

    def test_same_name_different_content_is_reported_but_not_merged(self) -> None:
        first = self.save()
        second = self.core.toolbox_save(
            candidate(content=CONTENT + "\n4. A different implementation path."),
            "similar method",
        )

        self.assertEqual(second["status"], "accepted")
        self.assertFalse(second["duplicate"])
        self.assertEqual(len(second["possible_duplicates"]), 1)
        hint = second["possible_duplicates"][0]
        self.assertEqual(hint["capability_id"], first["capability_id"])
        self.assertIn("same_name", hint["reasons"])
        self.assertGreaterEqual(hint["score"], 0.9)

        count = self.core.store.db.execute(
            "SELECT COUNT(*) AS n FROM capabilities"
        ).fetchone()["n"]
        self.assertEqual(count, 2)

    def test_unrelated_candidate_has_no_hints(self) -> None:
        self.save()
        unrelated = self.core.toolbox_save(
            candidate(
                manifest={
                    "name": "render_pdf_invoice",
                    "description": "render a PDF invoice from structured input",
                    "when_to_use": "a billing document must be produced",
                    "not_for": [],
                    "tags": ["pdf", "invoice", "billing"],
                    "applicability": {
                        "harnesses": [],
                        "operating_systems": [],
                        "required_tools": [],
                    },
                },
                content="1. Validate input.\n2. Render the document.\n",
            ),
            "unrelated",
        )
        self.assertEqual(unrelated["possible_duplicates"], [])

    def test_exact_duplicate_returns_no_hints(self) -> None:
        self.save()
        duplicate = self.core.toolbox_save(candidate(), "same thing")
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["possible_duplicates"], [])
