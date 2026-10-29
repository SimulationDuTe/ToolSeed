"""An install snapshot must carry every runtime file advertised by its package."""
from __future__ import annotations

import json
import tarfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from toolseed.hosts import fetch_local_tree, fingerprint_tree, package_dsh_plugin

REPO = Path(__file__).resolve().parent.parent


class HostSnapshotTest(unittest.TestCase):
    def test_dsh_runtime_is_complete_and_new_modules_affect_upgrade_identity(self):
        base = REPO / "tests" / ".data"
        base.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="host-snapshot-", dir=base) as directory:
            snapshot = fetch_local_tree(REPO, Path(directory) / "snapshot")
            plugin = snapshot / "integrations" / "dsh"
            self.assertEqual((snapshot / "LICENSE").read_bytes(), (plugin / "LICENSE").read_bytes())
            package = json.loads((plugin / "package.json").read_text(encoding="utf-8"))
            for relative in package["files"]:
                self.assertTrue((plugin / relative).is_file(), relative)
            packed = package_dsh_plugin(plugin)
            original_archive = packed.read_bytes()
            self.assertEqual(package_dsh_plugin(plugin).read_bytes(), original_archive)
            with tarfile.open(packed, "r:gz") as archive:
                self.assertEqual(set(archive.getnames()), {"package/package.json", *("package/" + f for f in package["files"])})
                for relative in package["files"]:
                    self.assertEqual(archive.extractfile("package/" + relative).read(), (plugin / relative).read_bytes())
            initial = fingerprint_tree(snapshot)
            shared = snapshot / "integrations" / "shared" / "learning-state.mjs"
            self.assertEqual(shared.read_bytes(), (plugin / "lib" / "learning-state.mjs").read_bytes())
            shared_content = shared.read_bytes()
            shared.write_bytes(shared_content + b"\n// shared upgrade fixture\n")
            self.assertNotEqual(initial, fingerprint_tree(snapshot))
            package_dsh_plugin(plugin)
            self.assertEqual(shared.read_bytes(), (plugin / "lib" / "learning-state.mjs").read_bytes())
            shared.write_bytes(shared_content)
            package_dsh_plugin(plugin)
            for name in ("learning.js", "recall.js", "revisions.js"):
                path = plugin / name
                content = path.read_bytes()
                path.write_bytes(content + b"\n// upgrade identity fixture\n")
                self.assertNotEqual(initial, fingerprint_tree(snapshot), name)
                path.write_bytes(content)
