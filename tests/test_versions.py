"""Immutable versions and exact-duplicate handling (P0-SLIM §4.2, §5)."""
from __future__ import annotations

from tests.helpers import CONTENT, CoreTest, candidate

EXTENDED = CONTENT + "4. 复核修复结果并记录耗时。\n"


class VersionTest(CoreTest):
    case = "versions"

    def test_first_save_creates_version_one(self) -> None:
        saved = self.save()
        self.assertEqual(saved["version"], 1)
        self.assertEqual(saved["version_status"], "ready")
        self.assertFalse(saved["duplicate"])
        self.assertTrue(saved["content_hash"].startswith("sha256:"))

    def test_target_id_creates_new_version(self) -> None:
        first = self.save()
        second = self.core.toolbox_save(
            candidate(target_capability_id=first["capability_id"], content=EXTENDED),
            "extend the method",
        )
        self.assertEqual(second["capability_id"], first["capability_id"])
        self.assertEqual(second["version"], 2)
        self.assertNotEqual(second["version_id"], first["version_id"])

    def test_old_version_is_immutable(self) -> None:
        first = self.save()
        self.core.toolbox_save(
            candidate(target_capability_id=first["capability_id"], content=EXTENDED),
            "extend the method",
        )
        versions = self.core.registry.list_versions(first["capability_id"])
        self.assertEqual([v["version_number"] for v in versions], [1, 2])
        self.assertEqual(versions[0]["content"], CONTENT)
        self.assertEqual(versions[1]["content"], EXTENDED)

    def test_current_pointer_follows_the_new_ready_version(self) -> None:
        first = self.save()
        second = self.core.toolbox_save(
            candidate(target_capability_id=first["capability_id"], content=EXTENDED),
            "extend the method",
        )
        capability = self.core.registry.get_capability(first["capability_id"])
        self.assertEqual(capability["current_version_id"], second["version_id"])
        run = self.core.toolbox_run(first["capability_id"])
        self.assertEqual(run["result"]["content"], EXTENDED)

    def test_identical_content_is_not_duplicated(self) -> None:
        first = self.save()
        again = self.core.toolbox_save(candidate(), "reuse the timeout triage method")
        self.assertTrue(again["duplicate"])
        self.assertEqual(again["version_id"], first["version_id"])
        self.assertEqual(len(self.core.registry.list_versions(first["capability_id"])), 1)

    def test_identical_content_with_target_is_not_duplicated(self) -> None:
        first = self.save()
        again = self.core.toolbox_save(
            candidate(target_capability_id=first["capability_id"]), "again"
        )
        self.assertTrue(again["duplicate"])
        self.assertEqual(again["version"], 1)

    def test_near_duplicate_is_not_merged(self) -> None:
        first = self.save()
        other = self.core.toolbox_save(
            candidate(content=EXTENDED), "a different variant"
        )
        self.assertEqual(other["status"], "accepted")
        self.assertFalse(other["duplicate"])
        self.assertNotEqual(other["capability_id"], first["capability_id"])
        self.assertEqual(len(self.core.registry.list_versions(first["capability_id"])), 1)

    def test_hash_ignores_manifest_key_order(self) -> None:
        first = self.save()
        payload = candidate()
        payload["manifest"] = dict(reversed(list(payload["manifest"].items())))
        again = self.core.toolbox_save(payload, "same request, different key order")
        self.assertTrue(again["duplicate"])
        self.assertEqual(again["content_hash"], first["content_hash"])

    def test_hash_tracks_content_changes(self) -> None:
        first = self.save()
        other = self.core.toolbox_save(candidate(content=EXTENDED), "variant")
        self.assertNotEqual(first["content_hash"], other["content_hash"])

    def test_target_must_exist(self) -> None:
        result = self.core.toolbox_save(
            candidate(target_capability_id="cap_missing"), "extend"
        )
        self.assertEqual(result["error"]["code"], "CAPABILITY_NOT_FOUND")
