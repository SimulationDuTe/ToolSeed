"""LocalAdapter: fixed tool surface and honest capability reporting (P0-SLIM §4)."""
from __future__ import annotations

from tests.helpers import CoreTest, candidate
from toolseed.adapters import LocalAdapter
from toolseed.core.api import ToolSeed


class AdapterTest(CoreTest):
    case = "adapter"

    def setUp(self) -> None:
        super().setUp()
        self.adapter = LocalAdapter(self.core, {"harness": "test"})

    def test_four_tools_are_registered(self) -> None:
        names = [spec["name"] for spec in self.adapter.register_tools()]
        self.assertEqual(
            names,
            ["toolbox_search", "toolbox_save", "toolbox_run", "toolbox_stats"],
        )

    def test_invoke_save_then_search_and_run(self) -> None:
        saved = self.adapter.invoke_tool(
            "toolbox_save",
            {"candidate": candidate(), "intent": "adapter path"},
        )
        self.assertEqual(saved["status"], "accepted", saved)

        found = self.adapter.invoke_tool("toolbox_search", {"query": "timeout"})
        self.assertEqual(len(found["results"]), 1, found)

        delivered = self.adapter.invoke_tool(
            "toolbox_run", {"capability": saved["capability_id"]}
        )
        self.assertEqual(delivered["mode"], "agent_guided", delivered)
        self.assertEqual(delivered["execution_status"], "guidance_delivered")
        self.assertEqual(delivered["task_outcome"], "unknown")

    def test_invoke_stats(self) -> None:
        result = self.adapter.invoke_tool("toolbox_stats", {})
        self.assertIn("capabilities", result)
        self.assertIn("versions", result)
        self.assertIn("task_outcomes", result)

    def test_unknown_tool_is_rejected(self) -> None:
        result = self.adapter.invoke_tool("toolbox_unknown", {})
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")

    def test_non_object_arguments_are_rejected(self) -> None:
        result = self.adapter.invoke_tool("toolbox_search", ["not", "an", "object"])
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")

    def test_non_string_tool_name_is_rejected(self) -> None:
        result = self.adapter.invoke_tool(123, {})
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")

    def test_capabilities_are_reported_honestly(self) -> None:
        capabilities = self.adapter.capabilities()
        for key in (
            "hooks",
            "task_end_events",
            "workspace_events",
            "permission_confirmation",
            "cancellation",
            "reliable_task_outcome",
        ):
            self.assertFalse(capabilities[key], key)
        self.assertIn("never simulated", capabilities["note"])

    def test_health_check_reports_reachable_core(self) -> None:
        health = self.adapter.health_check()
        self.assertTrue(health["ok"])
        self.assertTrue(health["core_reachable"])
        self.assertEqual(health["adapter"], "local")

    def test_health_check_reports_closed_core(self) -> None:
        another = ToolSeed(str(self.dir / "closed"))
        another.close()
        adapter = LocalAdapter(another)
        health = adapter.health_check()
        self.assertFalse(health["ok"])
        self.assertEqual(health["error"]["code"], "INTERNAL_ERROR")

    def test_translate_error_preserves_code_and_retryable(self) -> None:
        translated = self.adapter.translate_error(
            {"code": "SAVE_PERSISTENCE_FAILED", "message": "disk", "retryable": True}
        )
        self.assertEqual(translated["code"], "SAVE_PERSISTENCE_FAILED")
        self.assertTrue(translated["retryable"])

    def test_translate_unknown_error_is_internal(self) -> None:
        translated = self.adapter.translate_error("boom")
        self.assertEqual(translated["code"], "INTERNAL_ERROR")
        self.assertFalse(translated["retryable"])

    def test_context_reports_unknown_host_facts(self) -> None:
        context = self.adapter.get_context()
        self.assertEqual(context["harness"], "test")
        self.assertEqual(context["session_id"], "unknown")
        self.assertFalse(self.adapter.emit_event({"type": "task_end"})["emitted"])
