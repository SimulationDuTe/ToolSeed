"""Quality gates for transactions, migrations and evidence ownership."""
from __future__ import annotations

import sqlite3
import unittest
from unittest import mock

from tests.helpers import CoreTest, candidate
from toolseed import ToolSeed


class StorageQualityTest(CoreTest):
    case = "quality-storage"

    def test_schema_version_is_recorded_and_reopen_is_idempotent(self) -> None:
        self.assertEqual(self.core.store.schema_version, 1)
        self.core.close()
        self.core = ToolSeed(str(self.dir))
        self.assertEqual(self.core.store.schema_version, 1)

    def test_nested_transaction_rolls_back_all_writes(self) -> None:
        with self.assertRaises(RuntimeError):
            with self.core.store.transaction():
                self.core.store.db.execute(
                    "INSERT INTO capabilities (capability_id, name, created_at) "
                    "VALUES ('cap_nested', 'nested', 'now')"
                )
                with self.core.store.transaction():
                    self.core.store.db.execute(
                        "INSERT INTO capabilities (capability_id, name, created_at) "
                        "VALUES ('cap_inner', 'inner', 'now')"
                    )
                raise RuntimeError("force rollback")
        count = self.core.store.db.execute(
            "SELECT COUNT(*) AS n FROM capabilities"
        ).fetchone()["n"]
        self.assertEqual(count, 0)


class AtomicOperationQualityTest(CoreTest):
    case = "quality-atomic"

    def _two_ready(self) -> tuple[dict, dict]:
        first = self.save()
        second = self.core.toolbox_save(
            candidate(
                content="1. New version.\n2. Stop here.\n",
                target_capability_id=first["capability_id"],
            ),
            "version two",
        )
        return first, second

    def test_rollback_pointer_and_audit_event_are_atomic(self) -> None:
        first, second = self._two_ready()
        with mock.patch.object(
            self.core.evidence,
            "record",
            side_effect=sqlite3.OperationalError("audit unavailable"),
        ):
            result = self.core.rollback_version(
                first["capability_id"], first["version_id"], "regression"
            )
        self.assertEqual(result["error"]["code"], "SAVE_PERSISTENCE_FAILED")
        capability = self.core.registry.get_capability(first["capability_id"])
        self.assertEqual(capability["current_version_id"], second["version_id"])

    def test_repair_version_and_diagnosis_update_are_atomic(self) -> None:
        saved = self.save()
        delivered = self.core.toolbox_run(saved["capability_id"])
        diagnosis = self.core.diagnose_failure(
            capability_id=saved["capability_id"],
            version_id=saved["version_id"],
            category="procedure_ambiguity",
            summary="needs clarification",
        )["diagnosis"]

        with mock.patch.object(
            self.core.evidence,
            "mark_repair_proposed",
            side_effect=sqlite3.OperationalError("write failed"),
        ):
            result = self.core.propose_repair(
                diagnosis["diagnosis_id"],
                candidate(
                    content="1. Clarified.\n2. Stop here.\n",
                    target_capability_id=saved["capability_id"],
                ),
            )
        self.assertEqual(result["error"]["code"], "SAVE_PERSISTENCE_FAILED")
        self.assertEqual(len(self.core.registry.list_versions(saved["capability_id"])), 1)
        self.assertEqual(
            self.core.evidence.get_diagnosis(diagnosis["diagnosis_id"])["status"], "open"
        )

    def test_task_outcome_requires_a_matching_invocation(self) -> None:
        saved = self.save()
        result = self.core.record_task_outcome(
            capability_id=saved["capability_id"],
            version_id=saved["version_id"],
            invocation_id="inv_missing",
            outcome="success",
            source_type="test_runner",
        )
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")
