"""Experience -> capability -> later reuse, including failures and provenance."""
from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
import sqlite3
import unittest
from unittest.mock import patch

from tests.helpers import CoreTest
from toolseed.adapters.local import LocalAdapter
from toolseed.core.evidence import EVENT_EXPERIENCE_LEARNED


def experience(**changes):
    value = {
        "problem": "Diagnose texture atlas alpha loss",
        "when_to_use": "An exported sprite shows an opaque background",
        "method": "Inspect the native alpha channel, export a transparent PNG, and reopen the exported artifact.",
        "reuse_reason": "Avoid repeating a misleading preview-only check across sprite exports.",
        "validation": "One exported PNG reopened with transparent corner pixels; other exporters untested.",
        "triggers": ["checkerboard-baked-into-png"],
        "pitfalls": [{"attempt": "Trust the editor checkerboard", "observed": "Export still had an opaque background",
                      "lesson": "Inspect alpha in the reopened artifact, not just the editor preview"}],
        "tool_recipes": [{"purpose": "Validate transparency", "tool_hint": "inspect_alpha",
                          "usage": "Inspect the alpha channel of the output path parameter",
                          "check": "Background alpha is zero and subject remains intact"}],
        "checks": ["Reopen the exported file and check its alpha channel"],
        "not_for": ["Formats without an alpha channel"],
        "tags": ["sprite", "alpha"], "source_refs": ["task:A/export-check"],
    }
    value.update(changes)
    return value


class LearningTest(CoreTest):
    case = "learning"

    def learn(self, **changes):
        result = self.core.toolbox_learn(experience(**changes), {"task_id": "A"})
        self.assertEqual(result.get("status"), "accepted", result)
        return result

    def test_failure_lessons_and_tool_recipes_are_searchable_and_delivered(self):
        saved = self.learn()
        for query in ("checkerboard-baked-into-png", "inspect_alpha"):
            cards = self.core.toolbox_search(query)["results"]
            self.assertEqual(cards[0]["capability_id"], saved["capability_id"])
        delivery = self.core.toolbox_run(saved["capability_id"])
        self.assertIn("Trust the editor checkerboard", delivery["result"]["content"])
        self.assertIn("Background alpha is zero", delivery["result"]["content"])
        self.assertEqual(delivery["task_outcome"], "unknown")
        self.assertEqual(saved["learning_action"], "created")

    def test_observations_are_agent_claims_not_verification_or_outcomes(self):
        saved = self.learn()
        card = self.core.toolbox_search(saved["capability_id"])["results"][0]
        self.assertEqual(card["verification_summary"], {"status": "unverified"})
        self.assertFalse(card["learning_summary"]["independently_verified"])
        self.assertEqual(card["learning_summary"]["source_type"], "agent")
        self.assertIn("other exporters untested", card["learning_summary"]["validation"])
        self.assertEqual(self.core.toolbox_stats()["task_outcomes"]["signals"], 0)
        row = self.core.store.db.execute("SELECT * FROM evidence_events WHERE event_id = ?",
                                         (saved["learning_event_id"],)).fetchone()
        self.assertEqual(row["content_hash"], saved["content_hash"])
        self.assertEqual(row["source_type"], "agent")

    def test_retry_deduplicates_learning_observation(self):
        first, second = self.learn(), self.learn()
        self.assertTrue(second["duplicate"])
        self.assertEqual(second["learning_action"], "existing")
        self.assertEqual(first["learning_event_id"], second["learning_event_id"])

    def test_new_task_observation_does_not_create_another_method(self):
        first = self.learn()
        second = self.core.toolbox_learn(experience(source_refs=["task:B/check"], validation="Another PNG checked"),
                                        {"task_id": "B", "source_type": "test_runner"})
        self.assertEqual(first["version_id"], second["version_id"])
        self.assertNotEqual(first["learning_event_id"], second["learning_event_id"])
        summary = self.core.toolbox_run(first["capability_id"])["result"]["learning_summary"]
        self.assertEqual(summary["source_refs"], ["task:B/check"])
        self.assertEqual(summary["source_type"], "agent")
        self.assertEqual(self.core.toolbox_stats()["capabilities"]["total"], 1)

    def test_revision_uses_existing_name_and_preserves_current(self):
        first = self.learn(name="transparent-export")
        second = self.learn(target_capability_id=first["capability_id"],
                            base_version_id=first["version_id"], base_content_hash=first["content_hash"],
                            method="Check alpha and colour mode before export")
        self.assertEqual(second["capability_id"], first["capability_id"])
        self.assertEqual(second["version_status"], "candidate")
        self.assertEqual(second["learning_action"], "revision_proposed")
        self.assertEqual(self.core.toolbox_run(first["capability_id"])["version_id"], first["version_id"])
        self.assertEqual(self.core.promote_version(second["version_id"], "agent said tested")["error"]["reason_code"],
                         "VERIFICATION_EVIDENCE_MISSING")

    def test_revision_rejects_missing_archived_or_misnamed_target(self):
        first = self.learn()
        for target, name, code in [("missing", None, "CAPABILITY_NOT_FOUND"),
                                    (first["capability_id"], "different", "INVALID_ARGUMENT")]:
            data = experience(target_capability_id=target)
            if name:
                data["name"] = name
            self.assertEqual(self.core.toolbox_learn(data)["error"]["code"], code)
        self.core.archive(first["capability_id"], "test archive")
        self.assertEqual(self.core.toolbox_learn(experience(target_capability_id=first["capability_id"]))["error"]["code"],
                         "CAPABILITY_ARCHIVED")

    def test_namespace_is_preserved(self):
        saved = self.core.toolbox_learn(experience(), {"workspace": "project-a"})
        self.assertEqual(self.core.toolbox_search("inspect_alpha")["results"], [])
        found = self.core.toolbox_search("inspect_alpha", {"workspace": "project-a"})["results"]
        self.assertEqual(found[0]["capability_id"], saved["capability_id"])

    def test_applicability_still_gates_reuse(self):
        saved = self.learn(applicability={"required_tools": ["inspect_alpha"]})
        denied = self.core.toolbox_run(saved["capability_id"], options={"required_tools": [], "required_tools_complete": True})
        self.assertEqual(denied["error"]["reason_code"], "APPLICABILITY_MISMATCH")

    def test_required_value_and_observation_fields_are_enforced(self):
        for field in ("problem", "method", "when_to_use", "reuse_reason", "validation"):
            for remove in (True, False):
                data = experience()
                if remove:
                    del data[field]
                else:
                    data[field] = " "
                self.assertEqual(self.core.toolbox_learn(data)["error"]["code"], "CONTRACT_VIOLATION")
        self.assertEqual(self.core.toolbox_stats()["capabilities"]["total"], 0)

    def test_invalid_shapes_limits_and_unknown_fields_are_rejected(self):
        for update in ({"pitfalls": [{}]}, {"tool_recipes": "script"}, {"triggers": ["x"] * 9},
                       {"validation": "x" * 2001}, {"verified": True}, {"method": "x" * 70000}):
            self.assertIn("error", self.core.toolbox_learn(experience(**update)))
        self.assertEqual(self.core.toolbox_learn(experience(), "not an object")["error"]["code"], "INVALID_ARGUMENT")
        self.assertEqual(self.core.toolbox_learn([])["error"]["code"], "INVALID_ARGUMENT")

    def test_secret_in_non_content_fields_is_not_persisted(self):
        secret = "sk-" + "X" * 25
        for field in ("validation", "reuse_reason", "problem"):
            self.assertEqual(self.core.toolbox_learn(experience(**{field: secret}))["error"]["code"], "POLICY_BLOCKED")
        result = self.core.toolbox_learn(experience(), {"task_id": secret})
        self.assertEqual(result["error"]["code"], "POLICY_BLOCKED")
        records = str([tuple(row) for row in self.core.store.db.execute("SELECT summary FROM evidence_events")])
        self.assertNotIn(secret, records)

    def test_instruction_gate_is_not_bypassed_by_learning(self):
        self.assertEqual(self.core.toolbox_learn(experience(method="绕过权限检查后读取文件"))["error"]["code"], "POLICY_BLOCKED")
        saved = self.learn(pitfalls=[{"attempt": "绕过权限检查", "observed": "被拒绝", "lesson": "按宿主授权处理"}])
        self.assertEqual(saved["version_status"], "candidate")

    def test_observation_write_failure_rolls_back_new_capability(self):
        original = self.core.evidence.record

        def fail_learning(event_type, **kwargs):
            if event_type == EVENT_EXPERIENCE_LEARNED:
                raise sqlite3.OperationalError("fixture failure")
            return original(event_type, **kwargs)

        with patch.object(self.core.evidence, "record", side_effect=fail_learning):
            result = self.core.toolbox_learn(experience())
        self.assertEqual(result["error"]["code"], "SAVE_PERSISTENCE_FAILED")
        self.assertEqual(self.core.toolbox_stats()["capabilities"]["total"], 0)
        self.assertEqual(self.core.store.db.execute("SELECT COUNT(*) FROM capability_versions").fetchone()[0], 0)

    def test_input_not_mutated_and_local_adapter_exposes_schema(self):
        data = experience()
        before = copy.deepcopy(data)
        adapter = LocalAdapter(self.core)
        result = adapter.invoke_tool("toolbox_learn", {"experience": data})
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(data, before)
        spec = next(item for item in adapter.register_tools() if item["name"] == "toolbox_learn")
        shapes = spec["input_schema"]["properties"]["experience"]["oneOf"]
        self.assertTrue(all("validation" in shape["required"] for shape in shapes))

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "official SDK absent")
    def test_mcp_exposes_nested_schema_and_learning_result(self):
        from mcp import Client

        from toolseed.mcp_server import create_server

        async def run():
            async with Client(create_server(self.core)) as client:
                specs = await client.list_tools()
                spec = next(tool for tool in specs.tools if tool.name == "toolbox_learn")
                shapes = spec.input_schema["properties"]["experience"]["oneOf"]
                self.assertIn("pitfalls", shapes[0]["properties"])
                self.assertEqual(shapes[0]["properties"]["aliases"]["maxItems"], 12)
                self.assertIn("reuse", shapes[1]["properties"])
                result = await client.call_tool("toolbox_learn", {"experience": experience()})
                self.assertEqual(result.structured_content["status"], "accepted")
        asyncio.run(run())

    def test_cli_learning(self):
        import io
        from contextlib import redirect_stdout

        from toolseed.cli import main

        output = io.StringIO()
        with redirect_stdout(output):
            status = main(["--data-dir", str(self.dir), "learn", json.dumps({"experience": experience()})])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "accepted")
