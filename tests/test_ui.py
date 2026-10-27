"""HTTP/read-only integration tests against real Core databases, no demo data."""
from __future__ import annotations

import hashlib
import http.client
import json
import sqlite3
import threading
from importlib.resources import files
from unittest import mock

from tests.helpers import CoreTest, candidate, verify_version
from toolseed.core.inspection import InspectionError, Inspector
from toolseed.ui import create_server, main


class InspectionTest(CoreTest):
    case = "ui-inspection"

    def read(self, route, **params):
        return Inspector(self.dir).read("/api/" + route, params)

    def test_empty_database_has_real_zero_counts_and_unknown_unmeasured_fields(self) -> None:
        data = self.read("overview")
        self.assertEqual(data["counts"]["capabilities"], 0)
        self.assertEqual(data["recent_activity"], [])
        for field in ("execution", "adoption", "token_cost"):
            self.assertIsNone(data[field])
        self.assertEqual(self.read("capabilities")["items"], [])

    def test_existing_history_and_new_commits_are_visible_without_backfill(self) -> None:
        saved = self.save()
        inspector = Inspector(self.dir)
        before = inspector.read("/api/activity", {})
        self.assertEqual(before["total"], 1)
        self.core.toolbox_search("timeout")
        self.core.toolbox_run(saved["capability_id"])
        self.core.toolbox_run(saved["capability_id"])
        self.core.toolbox_run("cap_missing")
        data = inspector.read("/api/overview", {})
        self.assertEqual(data["event_counts"]["search_performed"], 1)
        self.assertEqual(data["event_counts"]["tool_call_failed"], 1)
        self.assertEqual(data["repeated_delivery_capabilities"], 1)
        self.assertEqual(data["unknown_delivery_results"], 2)
        self.assertIsNone(data["adoption"])

    def test_read_only_queries_never_write_or_invoke_the_core(self) -> None:
        saved = self.save()
        before = list(self.core.store.db.iterdump())
        for route in ("overview", "capabilities", "activity", "evidence"):
            self.read(route)
        self.read("capabilities", q="timeout")
        self.read("capability", id=saved["capability_id"])
        self.assertEqual(before, list(self.core.store.db.iterdump()))
        with (Inspector(self.dir).snapshot() as db,
              self.assertRaises(sqlite3.OperationalError)):
            db.execute("DELETE FROM capabilities")

    def test_missing_database_does_not_create_files(self) -> None:
        path = self.dir / "missing"
        with self.assertRaises(InspectionError) as caught:
            Inspector(path).read("/api/overview", {})
        self.assertEqual(caught.exception.code, "DATABASE_MISSING")
        self.assertFalse(path.exists())

    def test_invalid_directory_and_corrupt_database_are_explained(self) -> None:
        path = self.dir / "file"
        path.write_text("not a directory")
        with self.assertRaises(InspectionError) as caught:
            Inspector(path).read("/api/overview", {})
        self.assertEqual(caught.exception.code, "INVALID_DIRECTORY")
        root = self.dir / "corrupt"
        root.mkdir()
        (root / "toolseed.sqlite3").write_text("not sqlite")
        with self.assertRaises(InspectionError) as caught:
            Inspector(root).read("/api/overview", {})
        self.assertEqual(caught.exception.code, "DATABASE_UNAVAILABLE")

    def test_old_schema_is_rejected_without_migration(self) -> None:
        self.core.store.db.execute("PRAGMA user_version=5")
        self.core.store.db.commit()
        with self.assertRaises(InspectionError) as caught:
            self.read("overview")
        self.assertEqual(caught.exception.code, "SCHEMA_UNSUPPORTED")
        self.assertEqual(self.core.store.schema_version, 5)

    def test_search_filter_and_pagination_do_not_record_usage(self) -> None:
        first = self.save()
        self.save(candidate(manifest={"name": "other_method"}))
        self.assertEqual(self.read("capabilities", q=first["capability_id"])["total"], 1)
        self.assertEqual(self.read("capabilities", q="' OR 1=1 --")["total"], 0)
        self.assertEqual(len(self.read("capabilities", limit="1", offset="1")["items"]), 1)
        self.assertNotIn("search_performed", self.core.evidence.event_counts())
        with self.assertRaises(InspectionError):
            self.read("activity", limit="invalid")

    def test_candidates_quarantined_and_archived_versions_never_deliver_content(self) -> None:
        saved = self.save()
        revised = self.save(candidate(target_capability_id=saved["capability_id"], content="Revised"))
        data = self.read("capability", id=saved["capability_id"])
        self.assertEqual(data["versions"][0]["version_id"], revised["version_id"])
        self.assertIsNone(data["versions"][0]["content"])
        self.assertIsNotNone(data["versions"][1]["content"])
        self.core.quarantine(saved["capability_id"])
        self.assertTrue(all(v["content"] is None for v in
                            self.read("capability", id=saved["capability_id"])["versions"]))
        self.core.archive(saved["capability_id"])
        self.assertEqual(self.read("capabilities")["total"], 1)
        self.assertTrue(all(v["content"] is None for v in
                            self.read("capability", id=saved["capability_id"])["versions"]))

    def test_task_sources_and_verification_validity_remain_separate(self) -> None:
        saved = self.save()
        delivery = self.core.toolbox_run(saved["capability_id"])
        self.core.record_task_outcome(
            capability_id=saved["capability_id"], version_id=saved["version_id"],
            invocation_id=delivery["invocation_id"], outcome="success", source_type="agent",
        )
        self.assertEqual(self.read("overview")["unknown_delivery_results"], 1)
        revised = self.save(candidate(target_capability_id=saved["capability_id"], content="Revised"))
        verified = verify_version(self.core, revised)
        evidence_id = verified["event_id"]
        self.core.assess_evidence(evidence_id, "stale", "test invalidation")
        evidence = self.read("evidence")["items"]
        verification = next(item for item in evidence if item["event_type"] == "version_verification")
        self.assertEqual(verification["validity"], "stale")
        self.assertTrue(verification["hash_bound"])
        agent = next(item for item in evidence if item["event_type"] == "task_outcome_signal")
        self.assertFalse(agent["independent_source_claim"])
        self.assertEqual(agent["outcome"], "success")

    def test_malformed_manifest_is_flagged_instead_of_hiding_the_record(self) -> None:
        saved = self.save()
        self.core.store.db.execute("UPDATE capability_versions SET manifest_json='[]' WHERE version_id=?",
                                   (saved["version_id"],))
        self.core.store.db.commit()
        item = self.read("capabilities")["items"][0]
        self.assertIsNone(item["kind"])
        self.assertIsNotNone(item["record_warning"])

    def test_data_directory_env_and_explicit_override(self) -> None:
        with mock.patch.dict("os.environ", {"TOOLSEED_DATA_DIR": str(self.dir)}):
            self.assertEqual(Inspector().root, self.dir.resolve())
            self.assertEqual(Inspector(self.dir / "other").root, (self.dir / "other").resolve())


class UIServerTest(CoreTest):
    case = "ui-server"

    def setUp(self) -> None:
        super().setUp()
        self.server = create_server(str(self.dir), 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        super().tearDown()

    def request(self, path, method="GET", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        data = response.read()
        result = response.status, dict(response.getheaders()), data
        connection.close()
        return result

    def test_loopback_assets_and_structured_endpoints(self) -> None:
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        for path in ("/", "/app.css", "/app.js", "/api/overview", "/api/capabilities",
                     "/api/activity", "/api/evidence"):
            with self.subTest(path=path):
                status, headers, body = self.request(path)
                self.assertEqual(status, 200)
                self.assertGreater(len(body), 0)
                self.assertEqual(headers["Cache-Control"], "no-store")
                self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])

    def test_dns_rebinding_and_cross_origin_access_are_rejected(self) -> None:
        for headers in ({"Host": "attacker.example"}, {"Origin": "https://attacker.example"},
                        {"Sec-Fetch-Site": "cross-site"}):
            self.assertEqual(self.request("/api/overview", headers=headers)[0], 403)

    def test_no_writes_or_file_traversal(self) -> None:
        before = list(self.core.store.db.iterdump())
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            self.assertEqual(self.request("/api/capability", method)[0], 405)
        for path in ("/../pyproject.toml", "/api/run", "/api/capability?id=cap_missing"):
            self.assertEqual(self.request(path)[0], 404)
        self.assertEqual(before, list(self.core.store.db.iterdump()))

    def test_invalid_pagination_returns_a_safe_error(self) -> None:
        status, _, body = self.request("/api/activity?limit=NaN")
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"]["code"], "INVALID_ARGUMENT")

    def test_packaged_assets_and_cli(self) -> None:
        for asset in ("index.html", "app.js", "app.css"):
            self.assertTrue(files("toolseed").joinpath("ui_assets", asset).is_file())
        with self.assertRaises(SystemExit) as caught:
            main(["--help"])
        self.assertEqual(caught.exception.code, 0)

    def test_reads_preserve_the_main_database_bytes(self) -> None:
        self.save()
        self.core.store.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        database = self.dir / "toolseed.sqlite3"
        before = hashlib.sha256(database.read_bytes()).hexdigest()
        self.request("/api/overview")
        self.request("/api/activity")
        self.assertEqual(before, hashlib.sha256(database.read_bytes()).hexdigest())
