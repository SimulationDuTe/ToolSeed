"""Local persistence, reopen and failure semantics (P0-SLIM §4.2, §6, §11.1)."""
from __future__ import annotations

import json
import sqlite3
from unittest import mock

from tests.helpers import CONTENT, CoreTest, candidate
from toolseed.core.api import ToolSeed


class PersistenceTest(CoreTest):
    case = "persistence"

    def test_saved_capability_survives_reopen(self) -> None:
        saved = self.save()
        self.core.close()

        self.core = ToolSeed(str(self.dir))
        found = self.core.toolbox_search("timeout")
        self.assertEqual(len(found["results"]), 1, found)

        delivered = self.core.toolbox_run(saved["capability_id"])
        self.assertTrue(delivered["ok"], delivered)
        self.assertEqual(delivered["result"]["content"], CONTENT)

    def test_content_hash_is_stable_across_reopen(self) -> None:
        saved = self.save()
        digest = saved["content_hash"]
        self.core.close()

        self.core = ToolSeed(str(self.dir))
        delivered = self.core.toolbox_run(saved["capability_id"])
        version = self.core.registry.get_version(delivered["version_id"])
        self.assertEqual(version["content_hash"], digest)
        self.assertTrue(digest.startswith("sha256:"))

    def test_exact_duplicate_returns_the_existing_version(self) -> None:
        first = self.save()
        second = self.core.toolbox_save(candidate(), "same candidate again")

        self.assertTrue(second["duplicate"])
        self.assertEqual(second["capability_id"], first["capability_id"])
        self.assertEqual(second["version_id"], first["version_id"])
        self.assertEqual(len(self.core.registry.list_versions(first["capability_id"])), 1)

    def test_duplicate_under_a_target_returns_the_existing_version(self) -> None:
        first = self.save()
        second = self.core.toolbox_save(
            candidate(revision_of=first), "same content, target path"
        )
        self.assertTrue(second["duplicate"])
        self.assertEqual(second["version_id"], first["version_id"])

    def test_persistence_failure_is_reported_and_not_partially_written(self) -> None:
        with mock.patch.object(
            self.core.registry,
            "create_with_version",
            side_effect=sqlite3.OperationalError("disk full"),
        ):
            result = self.core.toolbox_save(candidate(), "must fail")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "SAVE_PERSISTENCE_FAILED")
        self.assertTrue(result["error"]["retryable"])
        count = self.core.store.db.execute("SELECT COUNT(*) AS n FROM capabilities").fetchone()["n"]
        self.assertEqual(count, 0)

    def test_invalid_candidate_does_not_persist(self) -> None:
        result = self.core.toolbox_save({"protocol_version": 1}, "bad")
        self.assertFalse(result["ok"])
        count = self.core.store.db.execute("SELECT COUNT(*) AS n FROM capabilities").fetchone()["n"]
        self.assertEqual(count, 0)

    def test_core_and_p1_tables_exist(self) -> None:
        tables = {
            row["name"]
            for row in self.core.store.db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        self.assertTrue(
            {
                "capabilities",
                "capability_versions",
                "invocations",
                "evidence_events",
            }
            <= tables
        )
        self.assertTrue(
            {
                "evidence_validity_assessments",
                "failure_diagnoses",
                "evolution_decisions",
                "capability_observations",
            }
            <= tables
        )

    def test_save_context_is_sanitized_into_origin(self) -> None:
        saved = self.core.toolbox_save(
            candidate(),
            "provenance test",
            {
                "task_id": "task_1",
                "workspace": "/repo",
                "related_capability_ids": ["cap_a", "cap_b"],
                "secret": "do-not-store",
            },
        )
        origin = json.loads(self.core.registry.get_version(saved["version_id"])["origin"])
        self.assertEqual(origin["intent"], "provenance test")
        self.assertEqual(origin["context"]["task_id"], "task_1")
        self.assertEqual(origin["context"]["workspace"], "/repo")
        self.assertEqual(
            origin["context"]["related_capability_ids"], ["cap_a", "cap_b"]
        )
        self.assertNotIn("secret", origin["context"])

    def test_plain_intent_is_stored_when_context_has_no_known_fields(self) -> None:
        saved = self.core.toolbox_save(
            candidate(), "plain intent", {"secret": "do-not-store"}
        )
        origin = self.core.registry.get_version(saved["version_id"])["origin"]
        self.assertEqual(origin, "plain intent")

    def test_oversized_context_stays_bounded(self) -> None:
        saved = self.core.toolbox_save(
            candidate(),
            "x" * 800,
            {
                "task_id": "t" * 500,
                "workspace": "w" * 500,
                "related_capability_ids": [f"cap_{index}" * 50 for index in range(20)],
            },
        )
        origin = self.core.registry.get_version(saved["version_id"])["origin"]
        self.assertLessEqual(len(origin), ToolSeed._ORIGIN_CONTEXT_MAX)
        if origin.startswith("{"):
            json.loads(origin)

    def test_evidence_survives_reopen(self) -> None:
        saved = self.save()
        self.core.toolbox_run(saved["capability_id"])
        self.core.close()

        self.core = ToolSeed(str(self.dir))
        events = self.core.evidence.event_counts()
        self.assertEqual(events.get("procedure_saved"), 1)
        self.assertEqual(events.get("procedure_delivered"), 1)
