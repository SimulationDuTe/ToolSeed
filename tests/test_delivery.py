"""Procedure delivery semantics (P0-SLIM §4.3, §7, §11.1)."""
from __future__ import annotations

import json

from tests.helpers import CONTENT, MANIFEST, CoreTest, candidate


class DeliveryTest(CoreTest):
    case = "delivery"

    def test_run_delivers_guidance_and_records_invocation(self) -> None:
        saved = self.save()
        result = self.core.toolbox_run(saved["capability_id"])

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["mode"], "agent_guided")
        self.assertEqual(result["execution_status"], "guidance_delivered")
        self.assertEqual(result["task_outcome"], "unknown")
        self.assertEqual(result["result"]["content"], CONTENT)
        self.assertEqual(result["result"]["content_origin"], "capability_material")
        self.assertIn("capability material", result["notice"])

        invocation = self.core.store.db.execute(
            "SELECT * FROM invocations WHERE invocation_id = ?", (result["invocation_id"],)
        ).fetchone()
        self.assertIsNotNone(invocation)
        self.assertEqual(invocation["delivery_status"], "guidance_delivered")
        self.assertEqual(invocation["capability_id"], saved["capability_id"])

    def test_run_by_unambiguous_name(self) -> None:
        saved = self.save()
        result = self.core.toolbox_run(MANIFEST["name"])
        self.assertEqual(result["capability_id"], saved["capability_id"])

    def test_delivery_is_not_task_success(self) -> None:
        saved = self.save()
        self.core.toolbox_run(saved["capability_id"])

        stats = self.core.toolbox_stats()
        self.assertEqual(stats["delivery"]["count"], 1)
        self.assertEqual(stats["task_outcomes"]["success"], 0)
        self.assertEqual(stats["task_outcomes"]["unknown"], 0)
        self.assertIsNone(stats["task_outcomes"]["unknown_ratio"])

        events = self.core.evidence.event_counts()
        self.assertEqual(events.get("procedure_delivered"), 1)
        self.assertNotIn("task_outcome_signal", events)

    def test_missing_current_version_is_not_deliverable(self) -> None:
        saved = self.core.toolbox_save(
            candidate(content=CONTENT + "\n4. 最后执行 rm -rf /tmp/cache。"), "review"
        )
        self.assertEqual(saved["version_status"], "candidate")

        result = self.core.toolbox_run(saved["capability_id"])
        self.assertEqual(result["error"]["code"], "CAPABILITY_NOT_READY")

    def test_unknown_capability_is_reported(self) -> None:
        result = self.core.toolbox_run("cap_missing")
        self.assertEqual(result["error"]["code"], "CAPABILITY_NOT_FOUND")

    def test_ambiguous_name_requires_an_id(self) -> None:
        self.save()
        self.core.toolbox_save(candidate(content=CONTENT + "\n4. 另一条路径。"), "different")
        result = self.core.toolbox_run(MANIFEST["name"])
        self.assertEqual(result["error"]["code"], "AMBIGUOUS_CAPABILITY_NAME")

    def test_empty_capability_reference_is_invalid(self) -> None:
        result = self.core.toolbox_run("")
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")

    def test_non_object_args_and_options_are_rejected(self) -> None:
        saved = self.save()
        self.assertEqual(
            self.core.toolbox_run(saved["capability_id"], args="nope")["error"]["code"],
            "INVALID_ARGUMENT",
        )
        self.assertEqual(
            self.core.toolbox_run(saved["capability_id"], options="nope")["error"]["code"],
            "INVALID_ARGUMENT",
        )

    def test_only_safe_context_fields_are_recorded(self) -> None:
        saved = self.save()
        result = self.core.toolbox_run(
            saved["capability_id"],
            options={
                "task_id": "task_1",
                "session_id": "session_1",
                "workspace": "/work",
                "secret": "do-not-store",
            },
        )
        row = self.core.store.db.execute(
            "SELECT context_json, task_id FROM invocations WHERE invocation_id = ?",
            (result["invocation_id"],),
        ).fetchone()
        context = json.loads(row["context_json"])
        self.assertEqual(context["task_id"], "task_1")
        self.assertEqual(context["session_id"], "session_1")
        self.assertEqual(context["workspace"], "/work")
        self.assertNotIn("secret", context)
        self.assertEqual(row["task_id"], "task_1")
