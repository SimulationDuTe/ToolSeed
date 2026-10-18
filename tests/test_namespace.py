"""Project/workspace namespace isolation on a shared database."""
from __future__ import annotations

import os
from unittest import mock

from tests.helpers import CONTENT, CoreTest, candidate
from toolseed import ToolSeed


class NamespaceTest(CoreTest):
    case = "namespace"

    def test_default_data_dir_can_be_overridden_by_env(self) -> None:
        shared = self.dir / "shared"
        with mock.patch.dict(os.environ, {"TOOLSEED_DATA_DIR": str(shared)}):
            core = ToolSeed()
            try:
                self.assertEqual(
                    core.store.root, shared.resolve()
                )
            finally:
                core.close()

    def test_global_and_workspace_saves_are_isolated_but_share_database(self) -> None:
        global_save = self.core.toolbox_save(candidate(), "global method")
        project_save = self.core.toolbox_save(
            candidate(manifest={"name": "project_method"}),
            "project method",
            context={"namespace": "project-a"},
        )

        self.assertEqual(global_save["namespace"], "global")
        self.assertEqual(project_save["namespace"], "project-a")

        global_results = self.core.toolbox_search("timeout")["results"]
        self.assertEqual(
            [card["capability_id"] for card in global_results],
            [global_save["capability_id"]],
        )

        project_results = self.core.toolbox_search(
            "timeout", context={"namespace": "project-a"}
        )["results"]
        self.assertEqual(
            {card["capability_id"] for card in project_results},
            {global_save["capability_id"], project_save["capability_id"]},
        )

    def test_exact_duplicate_detection_is_namespace_scoped(self) -> None:
        first = self.core.toolbox_save(candidate(), "global")
        second = self.core.toolbox_save(
            candidate(), "project", context={"namespace": "project-a"}
        )
        self.assertFalse(second["duplicate"])
        self.assertNotEqual(first["capability_id"], second["capability_id"])

        duplicate = self.core.toolbox_save(
            candidate(), "project again", context={"namespace": "project-a"}
        )
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["capability_id"], second["capability_id"])

    def test_duplicate_hints_do_not_cross_namespaces(self) -> None:
        self.core.toolbox_save(candidate(), "global")
        project = self.core.toolbox_save(
            candidate(content=CONTENT + "\n4. project variant."),
            "project",
            context={"namespace": "project-a"},
        )
        self.assertEqual(project["possible_duplicates"], [])

    def test_run_by_name_uses_namespace_scope(self) -> None:
        global_save = self.core.toolbox_save(candidate(), "global")
        project_save = self.core.toolbox_save(
            candidate(manifest={"name": "project_timeout_method"}),
            "project",
            context={"namespace": "project-a"},
        )

        global_run = self.core.toolbox_run(
            "triage_api_timeout", options={"namespace": "project-a"}
        )
        self.assertEqual(global_run["capability_id"], global_save["capability_id"])

        project_run = self.core.toolbox_run(
            "project_timeout_method", options={"namespace": "project-a"}
        )
        self.assertEqual(project_run["capability_id"], project_save["capability_id"])

        outside = self.core.toolbox_run(
            "project_timeout_method", options={"namespace": "project-b"}
        )
        self.assertEqual(outside["error"]["code"], "CAPABILITY_NOT_FOUND")
