"""Management adapters use real temporary Core data without producing usage."""
from __future__ import annotations

import contextlib
import io
import json
import os
from unittest import mock

from tests.helpers import CoreTest, candidate, verify_version
from toolseed import ToolSeed, cli


class ManagementTest(CoreTest):
    case = "management"

    def call(self, *args, directory=None):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli.main([*args, "--data-dir", str(directory or self.dir)])
        return code, output.getvalue()

    def read(self, *args, **kwargs):
        code, text = self.call(*args, **kwargs)
        self.assertEqual(code, 0, text)
        return json.loads(text)

    def test_all_views_share_live_data_without_core_writes(self):
        saved = self.save()
        revised = self.save(candidate(revision_of=saved, content="revision"))
        verified = verify_version(self.core, revised)
        self.core.toolbox_search("timeout")
        self.core.toolbox_run(saved["capability_id"])
        self.core.toolbox_run("cap_missing")
        before = list(self.core.store.db.iterdump())
        # A management query must not initialize Store or call a public tool.
        with mock.patch("toolseed.core.api.ToolSeed", side_effect=AssertionError("Core write path")):
            status = self.read("status")
            self.assertEqual(status["counts"]["capabilities"], 1)
            self.assertEqual(status["database"]["schema"], 6)
            self.assertEqual(status["service_status"], "unknown")
            self.assertIsNone(status["adoption"])
            self.assertEqual(self.read("capabilities", "list", "--query", saved["capability_id"])["total"], 1)
            details = self.read("capabilities", "show", saved["capability_id"])
            self.assertEqual(details["versions"][0]["content_hash"], revised["content_hash"])
            events = self.read("activity")["items"]
            self.assertIn("tool_call_failed", [x["event_type"] for x in events])
            evidence = self.read("evidence")["items"]
            self.assertNotIn("tool_call_failed", [x["event_type"] for x in evidence])
            self.assertIn(verified["event_id"], [x["event_id"] for x in evidence])
        self.assertEqual(before, list(self.core.store.db.iterdump()))
        self.core.toolbox_search("new committed activity")
        self.assertEqual(self.read("activity")["total"], len(events) + 1)

    def test_common_flags_before_and_after_subcommands(self):
        saved = self.save()
        self.assertIn("ToolSeed", self.call("--text", "status")[1])
        self.assertIn("程序执行 / 实际采用", self.call("status", "--text")[1])
        self.assertEqual(json.loads(self.call("--text", "status", "--json")[1])["service_status"], "unknown")
        details = self.call("capabilities", "show", saved["capability_id"], "--text")[1]
        self.assertIn(saved["capability_id"], details)
        self.assertIn("最近关联记录", details)
        self.assertIn("没有匹配", self.call("evidence", "--text")[1])

    def test_directory_environment_precedence_and_isolation(self):
        saved = self.save()
        other = self.dir / "空 格库"
        second = ToolSeed(other)
        try:
            second.toolbox_save(candidate(manifest={"name": "isolated"}), "isolation")
        finally:
            second.close()
        with mock.patch.dict(os.environ, {"TOOLSEED_DATA_DIR": str(other)}):
            self.assertEqual(self.read("capabilities", "list")["items"][0]["capability_id"], saved["capability_id"])
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(["capabilities", "list"]), 0)
            self.assertEqual(json.loads(output.getvalue())["items"][0]["name"], "isolated")

    def test_missing_invalid_and_corrupt_directories_do_not_initialize(self):
        missing = self.dir / "missing"
        code, text = self.call("status", directory=missing)
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(text)["error"]["code"], "DATABASE_MISSING")
        self.assertFalse(missing.exists())
        bad = self.dir / "file"
        bad.write_text("not a directory")
        self.assertEqual(json.loads(self.call("status", directory=bad)[1])["error"]["code"], "INVALID_DIRECTORY")
        corrupt = self.dir / "corrupt"
        corrupt.mkdir()
        db = corrupt / "toolseed.sqlite3"
        db.write_bytes(b"not sqlite")
        self.assertEqual(json.loads(self.call("activity", directory=corrupt)[1])["error"]["code"], "DATABASE_UNAVAILABLE")
        self.assertEqual(db.read_bytes(), b"not sqlite")

    def test_old_schema_does_not_migrate(self):
        self.core.store.db.execute("PRAGMA user_version=5")
        self.core.store.db.commit()
        code, text = self.call("status")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(text)["error"]["code"], "SCHEMA_UNSUPPORTED")
        self.assertEqual(self.core.store.schema_version, 5)

    def test_detail_obeys_lifecycle_gate_and_missing_id(self):
        saved = self.save()
        self.save(candidate(revision_of=saved, content="candidate secret"))
        data = self.read("capabilities", "show", saved["capability_id"])
        self.assertIsNone(data["versions"][0]["content"])
        self.core.quarantine(saved["capability_id"])
        data = self.read("capabilities", "show", saved["capability_id"])
        self.assertTrue(all(v["content"] is None for v in data["versions"]))
        code, text = self.call("capabilities", "show", "cap_missing")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(text)["error"]["code"], "NOT_FOUND")

    def test_filters_pagination_and_safe_terminal_text(self):
        self.save()
        self.core.toolbox_search("timeout")
        self.assertEqual(self.read("activity", "--type", "search_performed")["total"], 1)
        self.assertEqual(len(self.read("activity", "--limit", "1", "--offset", "1")["items"]), 1)
        self.assertEqual(self.read("capabilities", "list", "--query=--help")["total"], 0)
        self.core.store.db.execute("UPDATE capabilities SET name=?", ("unsafe\x1b[31m",))
        self.core.store.db.commit()
        self.assertNotIn("\x1b", self.call("capabilities", "list", "--text")[1])
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            self.call("activity", "--limit", "101")
        self.assertEqual(caught.exception.code, 2)

    def test_ui_delegates_to_existing_loopback_server(self):
        with mock.patch("toolseed.ui.main", return_value=0) as ui:
            self.assertEqual(self.call("ui", "--port", "9876")[0], 0)
        ui.assert_called_once_with(["--data-dir", str(self.dir), "--port", "9876"])

    def test_subcommand_help(self):
        with contextlib.redirect_stdout(io.StringIO()) as output, self.assertRaises(SystemExit) as caught:
            cli.main(["capabilities", "list", "--help"])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn("--query", output.getvalue())
