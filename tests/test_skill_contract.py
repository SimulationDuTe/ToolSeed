"""The packaged Skill must state the contract the Core actually enforces.

A real run rejected a candidate because ``manifest.description`` exceeded its
limit: the Core was right and the Skill was silent. These tests pin the
documented limits to the authoritative constants so the two cannot drift, and
keep the usage documents free of stale "not implemented" claims.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from toolseed.core import manifest as manifest_module

REPO = Path(__file__).resolve().parent.parent
SKILL = (REPO / "toolseed" / "skill" / "SKILL.md").read_text(encoding="utf-8")
README = (REPO / "README.md").read_text(encoding="utf-8")
# The documents wrap prose across lines; compare on flattened whitespace.
SKILL_FLAT = " ".join(SKILL.split())


def flat(text: str) -> str:
    return " ".join(text.split())


class SkillContractTest(unittest.TestCase):
    def test_save_confirmation_matches_the_actual_success_envelope(self) -> None:
        from tempfile import TemporaryDirectory

        from tests.helpers import candidate
        from toolseed import ToolSeed

        # Unique fixture, never an existing library or another test's directory.
        fixture_base = (REPO / "tests" / ".data").resolve()
        fixture_base.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="p1a-skill-", dir=fixture_base) as root:
            self.assertTrue(Path(root).resolve().is_relative_to(fixture_base))
            core = ToolSeed(root)
            try:
                saved = core.toolbox_save(candidate(), "contract fixture")
                self.assertEqual(saved["status"], "accepted")
                self.assertNotIn("ok", saved)
                self.assertIn("Confirm `status: accepted`, returned IDs and `version_status`", SKILL)
                self.assertIn("do not include an `ok` field", SKILL_FLAT)
                self.assertNotIn("Confirm `ok: true`", SKILL)
            finally:
                core.close()

    def test_skill_states_every_enforced_field_limit(self) -> None:
        expected = [
            f"| `name` | ≤ {manifest_module.NAME_MAX} characters |",
            f"| `description` | ≤ {manifest_module.DESCRIPTION_MAX} characters |",
            f"| `when_to_use` | ≤ {manifest_module.WHEN_TO_USE_MAX} characters |",
            (f"| `not_for` | ≤ {manifest_module.NOT_FOR_MAX_ITEMS} items, "
             f"each ≤ {manifest_module.NOT_FOR_ITEM_MAX} characters |"),
            (f"| `tags` | ≤ {manifest_module.TAGS_MAX_ITEMS} items, "
             f"each ≤ {manifest_module.TAG_MAX} characters |"),
            (f"| `applicability.*` | ≤ {manifest_module.APPLICABILITY_MAX_ITEMS} items per array, "
             f"each ≤ {manifest_module.APPLICABILITY_ITEM_MAX} characters |"),
            f"`content` | 1–{manifest_module.CONTENT_MAX_BYTES:,} UTF-8 bytes",
            f"whole candidate | ≤ {manifest_module.CANDIDATE_MAX_BYTES // 1024} KiB",
        ]
        for fragment in expected:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, SKILL)

    def test_skill_lists_every_manifest_field(self) -> None:
        for field in sorted(manifest_module.MANIFEST_FIELDS):
            with self.subTest(field=field):
                self.assertIn(f"`{field}`", SKILL)

    def test_skill_explains_how_to_recover_from_a_rejected_save(self) -> None:
        for fragment in (
            "CONTRACT_VIOLATION",
            "POLICY_BLOCKED",
            "Change only the field the message names",
            "Never resend an unchanged candidate",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(flat(fragment), SKILL_FLAT)

    def test_skill_does_not_require_saving_in_every_task(self) -> None:
        self.assertIn("Not every task", SKILL_FLAT)
        self.assertIn("ends with no", SKILL_FLAT)


class UsageDocumentTest(unittest.TestCase):
    def test_readme_has_no_stale_unimplemented_claims(self) -> None:
        self.assertNotIn("MCP 层尚未实现", README)

    def test_readme_links_the_alpha_status_and_quickstart(self) -> None:
        self.assertIn("docs/ALPHA-STATUS.md", README)
        self.assertIn("## Alpha 快速上手", README)

    def test_readme_test_count_matches_the_suite(self) -> None:
        loader = unittest.TestLoader()
        discovered = loader.discover(str(REPO / "tests"), top_level_dir=str(REPO))
        count = discovered.countTestCases()
        match = re.search(r"当前 \*\*(\d+) 项\*\*测试", README)
        self.assertIsNotNone(match, "README must state the current test count")
        assert match is not None
        self.assertEqual(int(match.group(1)), count)

    def test_alpha_status_test_count_matches_the_suite(self) -> None:
        status = (REPO / "docs" / "ALPHA-STATUS.md").read_text(encoding="utf-8")
        loader = unittest.TestLoader()
        discovered = loader.discover(str(REPO / "tests"), top_level_dir=str(REPO))
        count = discovered.countTestCases()
        match = re.search(r"本地回归：(\d+) 项测试", status)
        self.assertIsNotNone(match, "Alpha status must state the current test count")
        assert match is not None
        self.assertEqual(int(match.group(1)), count)


if __name__ == "__main__":
    unittest.main()
