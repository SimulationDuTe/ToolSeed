"""Version-level lifecycle and capability-level retirement (P0-SLIM §5, §11.1)."""
from __future__ import annotations

from tests.helpers import CONTENT, CoreTest, candidate

REVIEW_CONTENT = CONTENT + "\n4. 清理前确认后执行 rm -rf /tmp/cache。"


class VersionRollbackTest(CoreTest):
    case = "version-rollback"

    def _two_ready(self) -> tuple[dict, dict]:
        first = self.save()
        second = self.core.toolbox_save(
            candidate(
                content=CONTENT + "\n4. 新版本。",
                target_capability_id=first["capability_id"],
            ),
            "version two",
        )
        return first, second

    def test_rollback_to_older_ready_restores_delivery_and_records_event(self) -> None:
        first, second = self._two_ready()
        self.assertEqual(self.core.toolbox_run(first["capability_id"])["version"], 2)

        result = self.core.rollback_version(
            first["capability_id"], first["version_id"], "regression in v2"
        )
        self.assertTrue(result["rolled_back"], result)
        self.assertEqual(result["previous_version_id"], second["version_id"])

        delivered = self.core.toolbox_run(first["capability_id"])
        self.assertEqual(delivered["version"], 1)
        self.assertEqual(delivered["result"]["content"], CONTENT)
        card = self.core.toolbox_search("timeout")["results"][0]
        self.assertEqual(card["version"], 1)

        event = self.core.store.db.execute(
            "SELECT summary FROM evidence_events WHERE event_type = 'version_rolled_back'"
        ).fetchone()
        self.assertIsNotNone(event)
        self.assertIn("regression in v2", event["summary"])

    def test_rollback_rejects_invalid_targets(self) -> None:
        first, second = self._two_ready()
        no_op = self.core.rollback_version(
            first["capability_id"], second["version_id"], "no-op"
        )
        self.assertFalse(no_op["rolled_back"])

        self.core.rollback_version(
            first["capability_id"], first["version_id"], "back to one"
        )
        newer = self.core.rollback_version(
            first["capability_id"], second["version_id"], "not older"
        )
        self.assertEqual(newer["error"]["code"], "INVALID_ARGUMENT")

        self.assertEqual(
            self.core.rollback_version(first["capability_id"], "ver_missing", "x")[
                "error"
            ]["code"],
            "INVALID_ARGUMENT",
        )
        self.assertEqual(
            self.core.rollback_version(first["capability_id"], first["version_id"], " ")[
                "error"
            ]["code"],
            "INVALID_ARGUMENT",
        )

        self.core.archive(first["capability_id"], "retired")
        archived = self.core.rollback_version(
            first["capability_id"], first["version_id"], "x"
        )
        self.assertEqual(archived["error"]["code"], "CAPABILITY_ARCHIVED")


class LifecycleTest(CoreTest):
    case = "lifecycle"

    def test_candidate_version_is_not_searchable_or_deliverable(self) -> None:
        saved = self.core.toolbox_save(candidate(content=REVIEW_CONTENT), "needs review")
        self.assertEqual(saved["status"], "accepted")
        self.assertEqual(saved["version_status"], "candidate")

        self.assertEqual(self.core.toolbox_search("timeout")["results"], [])
        self.assertEqual(
            self.core.toolbox_run(saved["capability_id"])["error"]["code"],
            "CAPABILITY_NOT_READY",
        )

    def test_new_candidate_does_not_replace_a_ready_version(self) -> None:
        first = self.save()
        updated = self.core.toolbox_save(
            candidate(content=REVIEW_CONTENT, target_capability_id=first["capability_id"]),
            "new version awaiting review",
        )
        self.assertEqual(updated["version"], 2)
        self.assertEqual(updated["version_status"], "candidate")

        delivered = self.core.toolbox_run(first["capability_id"])
        self.assertTrue(delivered["ok"], delivered)
        self.assertEqual(delivered["version"], 1)
        self.assertEqual(delivered["result"]["content"], CONTENT)

    def test_new_ready_version_moves_the_current_pointer(self) -> None:
        first = self.save()
        updated = self.core.toolbox_save(
            candidate(
                content=CONTENT + "\n4. 新增一步。",
                target_capability_id=first["capability_id"],
            ),
            "improved version",
        )
        self.assertEqual(updated["version_status"], "ready")

        delivered = self.core.toolbox_run(first["capability_id"])
        self.assertEqual(delivered["version"], 2)
        self.assertIn("新增一步", delivered["result"]["content"])

    def test_quarantined_version_cannot_be_delivered_or_searched(self) -> None:
        saved = self.save()
        result = self.core.quarantine_version(saved["version_id"], "content risk")
        self.assertTrue(result["ok"])

        capability = self.core.registry.get_capability(saved["capability_id"])
        self.assertIsNone(capability["current_version_id"])
        self.assertEqual(
            self.core.toolbox_run(saved["capability_id"])["error"]["code"],
            "CAPABILITY_QUARANTINED",
        )
        self.assertEqual(self.core.toolbox_search("timeout")["results"], [])

    def test_quarantining_current_version_falls_back_to_older_ready(self) -> None:
        first = self.save()
        second = self.core.toolbox_save(
            candidate(
                content=CONTENT + "\n4. 新版本。",
                target_capability_id=first["capability_id"],
            ),
            "version two",
        )
        self.core.quarantine_version(second["version_id"], "bad version two")

        capability = self.core.registry.get_capability(first["capability_id"])
        self.assertEqual(capability["current_version_id"], first["version_id"])
        delivered = self.core.toolbox_run(first["capability_id"])
        self.assertTrue(delivered["ok"], delivered)
        self.assertEqual(delivered["version"], 1)

    def test_capability_quarantine_blocks_all_versions(self) -> None:
        saved = self.save()
        result = self.core.quarantine(saved["capability_id"], "cannot verify content")
        self.assertTrue(result["ok"])

        self.assertEqual(
            self.core.toolbox_run(saved["capability_id"])["error"]["code"],
            "CAPABILITY_QUARANTINED",
        )
        self.assertEqual(self.core.toolbox_search("timeout")["results"], [])

    def test_release_capability_restores_delivery_and_records_audit(self) -> None:
        saved = self.save()
        self.core.quarantine(saved["capability_id"], "temporary incident")

        released = self.core.release_capability(
            saved["capability_id"], "incident reviewed", "ticket-42"
        )
        self.assertTrue(released["ok"], released)
        self.assertTrue(released["released"])

        delivered = self.core.toolbox_run(saved["capability_id"])
        self.assertTrue(delivered["ok"], delivered)
        self.assertEqual(len(self.core.toolbox_search("timeout")["results"]), 1)

        event = self.core.store.db.execute(
            "SELECT summary FROM evidence_events WHERE event_type = 'capability_released'"
        ).fetchone()
        self.assertIsNotNone(event)
        self.assertIn("incident reviewed", event["summary"])
        self.assertIn("ticket-42", event["summary"])

    def test_release_is_idempotent_and_rejects_archived_capabilities(self) -> None:
        saved = self.save()
        not_quarantined = self.core.release_capability(saved["capability_id"], "no-op")
        self.assertFalse(not_quarantined["released"])

        self.core.quarantine(saved["capability_id"], "incident")
        self.assertTrue(self.core.release_capability(saved["capability_id"], "reviewed")["released"])
        self.core.archive(saved["capability_id"], "retired")

        archived = self.core.release_capability(saved["capability_id"], "cannot")
        self.assertEqual(archived["error"]["code"], "CAPABILITY_ARCHIVED")

    def test_release_requires_a_reason_and_valid_ids(self) -> None:
        saved = self.save()
        self.core.quarantine(saved["capability_id"], "incident")
        self.assertEqual(
            self.core.release_capability(saved["capability_id"], "   ")["error"]["code"],
            "INVALID_ARGUMENT",
        )
        self.assertEqual(
            self.core.release_capability(1, "reason")["error"]["code"],
            "INVALID_ARGUMENT",
        )
        self.assertEqual(
            self.core.release_capability("cap_missing", "reason")["error"]["code"],
            "CAPABILITY_NOT_FOUND",
        )

    def test_release_then_promote_version_restores_delivery(self) -> None:
        saved = self.save()
        self.core.quarantine_version(saved["version_id"], "false positive")

        released = self.core.release_version(
            saved["version_id"], "reviewed", "ticket-9"
        )
        self.assertTrue(released["released"])
        self.assertEqual(released["status"], "candidate")
        self.assertEqual(
            self.core.toolbox_run(saved["capability_id"])["error"]["code"],
            "CAPABILITY_NOT_READY",
        )

        promoted = self.core.promote_version(
            saved["version_id"], "content rechecked", "ticket-9"
        )
        self.assertTrue(promoted["promoted"])
        self.assertEqual(promoted["status"], "ready")
        delivered = self.core.toolbox_run(saved["capability_id"])
        self.assertTrue(delivered["ok"], delivered)

        events = self.core.evidence.event_counts()
        self.assertEqual(events.get("version_released"), 1)
        self.assertEqual(events.get("version_promoted"), 1)

    def test_promote_rejects_review_candidates(self) -> None:
        saved = self.core.toolbox_save(candidate(content=REVIEW_CONTENT), "review")
        self.assertEqual(saved["version_status"], "candidate")

        promoted = self.core.promote_version(saved["version_id"], "please promote")
        self.assertEqual(promoted["error"]["code"], "POLICY_BLOCKED")
        self.assertEqual(
            self.core.registry.get_version(saved["version_id"])["status"], "candidate"
        )

    def test_promote_requires_release_for_quarantined_versions(self) -> None:
        saved = self.save()
        self.core.quarantine_version(saved["version_id"], "risk")
        promoted = self.core.promote_version(saved["version_id"], "promote")
        self.assertEqual(promoted["error"]["code"], "CAPABILITY_QUARANTINED")

    def test_promote_older_version_keeps_newest_ready_current(self) -> None:
        first = self.save()
        second = self.core.toolbox_save(
            candidate(
                content=CONTENT + "\n4. 新版本。",
                target_capability_id=first["capability_id"],
            ),
            "version two",
        )
        self.core.quarantine_version(first["version_id"], "old version risk")
        self.core.release_version(first["version_id"], "reviewed")
        self.core.promote_version(first["version_id"], "reviewed")

        delivered = self.core.toolbox_run(first["capability_id"])
        self.assertEqual(delivered["version"], second["version"])

    def test_version_management_requires_reason_and_valid_ids(self) -> None:
        saved = self.save()
        self.assertEqual(
            self.core.release_version(saved["version_id"], " ")["error"]["code"],
            "INVALID_ARGUMENT",
        )
        self.assertEqual(
            self.core.promote_version(saved["version_id"], " ")["error"]["code"],
            "INVALID_ARGUMENT",
        )
        self.assertEqual(
            self.core.release_version("ver_missing", "reason")["error"]["code"],
            "CAPABILITY_NOT_FOUND",
        )
        self.assertEqual(
            self.core.promote_version("ver_missing", "reason")["error"]["code"],
            "CAPABILITY_NOT_FOUND",
        )

        self.core.archive(saved["capability_id"], "retired")
        self.assertEqual(
            self.core.release_version(saved["version_id"], "reason")["error"]["code"],
            "CAPABILITY_ARCHIVED",
        )
        self.assertEqual(
            self.core.promote_version(saved["version_id"], "reason")["error"]["code"],
            "CAPABILITY_ARCHIVED",
        )

    def test_archived_capability_is_blocked_even_by_direct_id(self) -> None:
        saved = self.save()
        self.assertTrue(self.core.archive(saved["capability_id"], "retired")["ok"])

        self.assertEqual(
            self.core.toolbox_run(saved["capability_id"])["error"]["code"],
            "CAPABILITY_ARCHIVED",
        )
        self.assertEqual(self.core.toolbox_search(saved["capability_id"])["results"], [])
        self.assertEqual(self.core.toolbox_search("timeout")["results"], [])

    def test_archived_capability_rejects_new_versions(self) -> None:
        saved = self.save()
        self.core.archive(saved["capability_id"])
        result = self.core.toolbox_save(
            candidate(
                content=CONTENT + "\n4. 新内容。",
                target_capability_id=saved["capability_id"],
            ),
            "should fail",
        )
        self.assertEqual(result["error"]["code"], "CAPABILITY_ARCHIVED")

    def test_state_changes_are_recorded_as_events(self) -> None:
        saved = self.save()
        self.core.quarantine(saved["capability_id"], "risk")
        self.core.archive(saved["capability_id"], "retired")
        events = self.core.evidence.event_counts()
        self.assertEqual(events.get("capability_quarantined"), 1)
        self.assertEqual(events.get("capability_archived"), 1)

    def test_stats_distinguishes_version_states_and_capability_flags(self) -> None:
        first = self.save()
        self.core.toolbox_save(candidate(content=REVIEW_CONTENT), "candidate")
        self.core.archive(first["capability_id"])

        stats = self.core.toolbox_stats()
        self.assertEqual(stats["capabilities"]["total"], 2)
        self.assertEqual(stats["capabilities"]["archived"], 1)
        self.assertEqual(stats["capabilities"]["quarantined"], 0)
        self.assertEqual(stats["versions"]["by_status"]["ready"], 1)
        self.assertEqual(stats["versions"]["by_status"]["candidate"], 1)

    def test_management_operations_validate_ids(self) -> None:
        self.assertEqual(self.core.quarantine(1)["error"]["code"], "INVALID_ARGUMENT")
        self.assertEqual(self.core.quarantine("cap_missing")["error"]["code"], "CAPABILITY_NOT_FOUND")
        self.assertEqual(self.core.quarantine_version(None)["error"]["code"], "INVALID_ARGUMENT")
        self.assertEqual(
            self.core.quarantine_version("ver_missing")["error"]["code"], "CAPABILITY_NOT_FOUND"
        )
        self.assertEqual(self.core.archive(1)["error"]["code"], "INVALID_ARGUMENT")
        self.assertEqual(self.core.archive("cap_missing")["error"]["code"], "CAPABILITY_NOT_FOUND")
