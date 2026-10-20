"""Evidence-bound promotion contract tests (v0.4 candidate lifecycle)."""
from __future__ import annotations

import sqlite3
from unittest import mock

from tests.helpers import CONTENT, CoreTest, candidate, verify_version
from toolseed import ToolSeed
from toolseed.core.storage import MIGRATIONS, SCHEMA, _statements


class PromotionContractTest(CoreTest):
    case = "promotion-contract"

    def _revision(self) -> tuple[dict, dict]:
        first = self.save()
        second = self.core.toolbox_save(
            candidate(
                content=CONTENT + "\n4. verified revision.\n",
                target_capability_id=first["capability_id"],
            ),
            "revision",
        )
        return first, second

    def test_revision_save_is_candidate_and_keeps_current(self) -> None:
        first, second = self._revision()
        self.assertEqual(second["version_status"], "candidate")
        capability = self.core.registry.get_capability(first["capability_id"])
        self.assertEqual(capability["current_version_id"], first["version_id"])
        self.assertEqual(self.core.registry.get_version(second["version_id"])["status"], "candidate")

    def test_promotion_requires_verification(self) -> None:
        _, second = self._revision()
        result = self.core.promote_version(second["version_id"], "promote")
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")
        self.assertEqual(result["error"]["reason_code"], "VERIFICATION_EVIDENCE_MISSING")
        self.assertEqual(self.core.registry.get_version(second["version_id"])["status"], "candidate")

    def test_content_hash_mismatch_is_rejected(self) -> None:
        _, second = self._revision()
        result = self.core.record_version_verification(
            version_id=second["version_id"],
            content_hash="sha256:" + "0" * 64,
            outcome="passed",
            source_type="test_runner",
            verification_ref="bad-hash",
            verification={
                "method": "pytest",
                "input_ref": "case",
                "artifact_ref": "artifact",
                "case_ids": ["case"],
                "regression_case_ids": ["old"],
            },
        )
        self.assertEqual(result["error"]["reason_code"], "CONTENT_HASH_MISMATCH")

    def test_failed_and_unknown_verification_block_promotion(self) -> None:
        _, second = self._revision()
        for outcome in ("failed", "unknown"):
            result = self.core.record_version_verification(
                version_id=second["version_id"],
                content_hash=second["content_hash"],
                outcome=outcome,
                source_type="test_runner",
                verification_ref=f"test:{outcome}",
                verification={
                    "method": "pytest",
                    "input_ref": "case",
                    "artifact_ref": "artifact",
                    "case_ids": ["case"],
                    "regression_case_ids": ["old"],
                },
            )
            self.assertTrue(result["ok"], result)
        promoted = self.core.promote_version(second["version_id"], "promote")
        self.assertEqual(promoted["error"]["reason_code"], "VERIFICATION_EVIDENCE_INVALID")

    def test_stale_verification_blocks_promotion(self) -> None:
        _, second = self._revision()
        verified = verify_version(self.core, second)
        self.core.assess_evidence(verified["event_id"], "stale", "evidence_expired")
        result = self.core.promote_version(second["version_id"], "promote")
        self.assertEqual(result["error"]["reason_code"], "VERIFICATION_EVIDENCE_INVALID")

    def test_backwards_clock_does_not_unmask_a_stale_verification(self) -> None:
        """The projection is the newest assessment recorded, not the newest stamp."""
        _, second = self._revision()
        verified = verify_version(self.core, second)
        stale = self.core.assess_evidence(verified["event_id"], "stale", "evidence_expired")
        self.core.store.db.execute(
            "UPDATE evidence_validity_assessments SET assessed_at = ? WHERE assessment_id = ?",
            ("2000-01-01T00:00:00+00:00", stale["assessment"]["assessment_id"]),
        )
        self.core.store.db.commit()
        # The stale report carries the older stamp, but it was recorded last.
        self.assertEqual(self.core.evidence.latest_validity(verified["event_id"]), "stale")
        result = self.core.promote_version(second["version_id"], "promote")
        self.assertEqual(result["error"]["reason_code"], "VERIFICATION_EVIDENCE_INVALID")

    def test_agent_source_does_not_satisfy_promotion(self) -> None:
        _, second = self._revision()
        verify_version(self.core, second, source_type="agent")
        result = self.core.promote_version(second["version_id"], "promote")
        self.assertEqual(result["error"]["reason_code"], "VERIFICATION_EVIDENCE_INVALID")

    def test_revision_requires_regression_reference(self) -> None:
        _, second = self._revision()
        result = self.core.record_version_verification(
            version_id=second["version_id"],
            content_hash=second["content_hash"],
            outcome="passed",
            source_type="test_runner",
            verification_ref="no-regression",
            verification={
                "method": "pytest",
                "input_ref": "case",
                "artifact_ref": "artifact",
                "case_ids": ["new-case"],
            },
        )
        self.assertTrue(result["ok"], result)
        promoted = self.core.promote_version(second["version_id"], "promote")
        self.assertEqual(promoted["error"]["reason_code"], "REGRESSION_VERIFICATION_MISSING")

    def test_valid_verification_promotes_and_preserves_old_version(self) -> None:
        first, second = self._revision()
        verified = verify_version(self.core, second)
        self.assertFalse(verified["duplicate"])
        promoted = self.core.promote_version(second["version_id"], "verified")
        self.assertTrue(promoted["promoted"], promoted)
        self.assertEqual(self.core.registry.get_version(second["version_id"])["status"], "ready")
        old = self.core.registry.get_version(first["version_id"])
        self.assertEqual(old["status"], "ready")
        self.assertEqual(old["content"], CONTENT)
        capability = self.core.registry.get_capability(first["capability_id"])
        self.assertEqual(capability["current_version_id"], second["version_id"])
        delivered = self.core.toolbox_run(first["capability_id"])
        self.assertEqual(delivered["version"], 2)

    def test_duplicate_verification_is_idempotent(self) -> None:
        _, second = self._revision()
        first = verify_version(self.core, second)
        second_call = verify_version(self.core, second)
        self.assertTrue(second_call["duplicate"])
        self.assertEqual(second_call["event_id"], first["event_id"])
        count = self.core.store.db.execute(
            "SELECT COUNT(*) AS n FROM evidence_events WHERE event_type = 'version_verification'"
        ).fetchone()["n"]
        self.assertEqual(count, 1)

    def test_equal_timestamps_do_not_block_promotion(self) -> None:
        """A clock that cannot resolve the gap must not invalidate bound evidence."""
        first, second = self._revision()
        verified = verify_version(self.core, second)
        version = self.core.registry.get_version(second["version_id"])
        # Reproduce the collision a coarse clock produces: the verification event
        # ends up carrying exactly the same created_at as the candidate it verifies.
        self.core.store.db.execute(
            "UPDATE evidence_events SET created_at = ? WHERE event_id = ?",
            (version["created_at"], verified["event_id"]),
        )
        self.core.store.db.commit()
        stored = self.core.store.db.execute(
            "SELECT created_at FROM evidence_events WHERE event_id = ?",
            (verified["event_id"],),
        ).fetchone()
        self.assertEqual(stored["created_at"], version["created_at"])

        promoted = self.core.promote_version(second["version_id"], "promote")
        self.assertTrue(promoted["promoted"], promoted)
        self.assertEqual(self.core.registry.get_version(second["version_id"])["status"], "ready")
        capability = self.core.registry.get_capability(first["capability_id"])
        self.assertEqual(capability["current_version_id"], second["version_id"])

    def test_promotion_does_not_consult_the_wall_clock(self) -> None:
        """Order comes from the write path, so created_at magnitude decides nothing."""
        _, second = self._revision()
        verified = verify_version(self.core, second)
        self.core.store.db.execute(
            "UPDATE evidence_events SET created_at = ? WHERE event_id = ?",
            ("2000-01-01T00:00:00+00:00", verified["event_id"]),
        )
        self.core.store.db.commit()
        promoted = self.core.promote_version(second["version_id"], "promote")
        self.assertTrue(promoted["promoted"], promoted)

    def test_verification_cannot_be_recorded_for_a_missing_version(self) -> None:
        """The write path is what makes 'verification after candidate' structural."""
        _, second = self._revision()
        result = self.core.record_version_verification(
            version_id="ver_missing",
            content_hash=second["content_hash"],
            outcome="passed",
            source_type="test_runner",
            verification_ref="missing-version",
            verification={
                "method": "pytest",
                "input_ref": "case",
                "artifact_ref": "artifact",
                "case_ids": ["case"],
            },
        )
        self.assertEqual(result["error"]["code"], "CAPABILITY_NOT_FOUND")
        stored = self.core.store.db.execute(
            "SELECT COUNT(*) AS n FROM evidence_events WHERE event_type = 'version_verification'"
        ).fetchone()["n"]
        self.assertEqual(stored, 0)

    def test_verification_cannot_be_recorded_for_a_non_candidate_version(self) -> None:
        """A version must exist as a candidate before evidence can bind to it."""
        first = self.save()
        self.assertEqual(first["version_status"], "ready")
        result = self.core.record_version_verification(
            version_id=first["version_id"],
            content_hash=first["content_hash"],
            outcome="passed",
            source_type="test_runner",
            verification_ref="non-candidate",
            verification={
                "method": "pytest",
                "input_ref": "case",
                "artifact_ref": "artifact",
                "case_ids": ["case"],
            },
        )
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")
        self.assertEqual(result["error"]["reason_code"], "VERSION_NOT_CANDIDATE")

    def test_verification_of_an_earlier_version_does_not_carry_over(self) -> None:
        """Evidence stays bound to its own version and never satisfies a later one."""
        first, second = self._revision()
        verify_version(self.core, second)
        self.assertTrue(self.core.promote_version(second["version_id"], "verified")["promoted"])
        third = self.core.toolbox_save(
            candidate(
                content=CONTENT + "\n5. third revision.\n",
                target_capability_id=first["capability_id"],
            ),
            "third revision",
        )
        result = self.core.promote_version(third["version_id"], "promote")
        self.assertEqual(result["error"]["reason_code"], "VERIFICATION_EVIDENCE_MISSING")
        self.assertEqual(self.core.registry.get_version(third["version_id"])["status"], "candidate")

    def test_tampered_content_hash_is_rejected_at_promotion(self) -> None:
        """The promotion-time hash binding still rejects mismatched evidence."""
        _, second = self._revision()
        verified = verify_version(self.core, second)
        self.core.store.db.execute(
            "UPDATE evidence_events SET content_hash = ? WHERE event_id = ?",
            ("sha256:" + "1" * 64, verified["event_id"]),
        )
        self.core.store.db.commit()
        result = self.core.promote_version(second["version_id"], "promote")
        self.assertEqual(result["error"]["reason_code"], "CONTENT_HASH_MISMATCH")

    def test_superseded_verification_blocks_promotion(self) -> None:
        _, second = self._revision()
        verified = verify_version(self.core, second)
        self.core.assess_evidence(
            verified["event_id"],
            "superseded",
            "evidence_superseded",
            superseded_by="ev_newer",
        )
        result = self.core.promote_version(second["version_id"], "promote")
        self.assertEqual(result["error"]["reason_code"], "VERIFICATION_EVIDENCE_INVALID")

    def test_promotion_audit_failure_rolls_back_status_and_pointer(self) -> None:
        first, second = self._revision()
        verify_version(self.core, second)
        with mock.patch.object(
            self.core.evidence,
            "record",
            side_effect=sqlite3.OperationalError("audit unavailable"),
        ):
            result = self.core.promote_version(second["version_id"], "verified")
        self.assertEqual(result["error"]["code"], "SAVE_PERSISTENCE_FAILED")
        self.assertEqual(self.core.registry.get_version(second["version_id"])["status"], "candidate")
        capability = self.core.registry.get_capability(first["capability_id"])
        self.assertEqual(capability["current_version_id"], first["version_id"])

    def test_schema_v6_has_verification_fields_and_signal_index(self) -> None:
        columns = {
            row["name"]
            for row in self.core.store.db.execute("PRAGMA table_info(evidence_events)")
        }
        self.assertTrue(
            {"content_hash", "signal_key", "verification_outcome", "verification_json"}
            <= columns
        )
        indexes = {
            row["name"]
            for row in self.core.store.db.execute("PRAGMA index_list(evidence_events)")
        }
        self.assertIn("idx_evidence_signal_key", indexes)

    def test_schema_v6_upgrades_a_v5_database(self) -> None:
        legacy = self.dir / "legacy-v5"
        legacy.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(legacy / "toolseed.sqlite3")
        try:
            for statement in _statements(SCHEMA):
                db.execute(statement)
            for version in (2, 3, 4, 5):
                for statement in _statements(MIGRATIONS[version]):
                    db.execute(statement)
            db.execute("PRAGMA user_version = 5")
            db.commit()
        finally:
            db.close()
        upgraded = ToolSeed(str(legacy))
        try:
            self.assertEqual(upgraded.store.schema_version, 6)
            columns = {
                row["name"]
                for row in upgraded.store.db.execute("PRAGMA table_info(evidence_events)")
            }
            self.assertTrue(
                {"content_hash", "signal_key", "verification_outcome", "verification_json"}
                <= columns
            )
        finally:
            upgraded.close()

    def test_signal_key_is_unique_but_null_is_allowed(self) -> None:
        self.core.evidence.record("custom_event", signal_key="sha256:duplicate")
        with self.assertRaises(sqlite3.IntegrityError):
            self.core.evidence.record("custom_event", signal_key="sha256:duplicate")
        self.core.evidence.record("custom_event")
        self.core.evidence.record("custom_event")
        count = self.core.store.db.execute(
            "SELECT COUNT(*) AS n FROM evidence_events WHERE signal_key IS NULL"
        ).fetchone()["n"]
        self.assertGreaterEqual(count, 2)
