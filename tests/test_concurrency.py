"""Concurrent save behaviour on the shared database."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from tests.helpers import CoreTest, candidate
from toolseed import ToolSeed


class ConcurrentSaveTest(CoreTest):
    case = "concurrency"

    def test_simultaneous_same_candidate_creates_one_capability(self) -> None:
        payload = candidate()
        barrier = threading.Barrier(2)
        first = ToolSeed(str(self.dir))
        second = ToolSeed(str(self.dir))

        def save(core: ToolSeed) -> dict:
            barrier.wait(timeout=10)
            return core.toolbox_save(payload, "concurrent writer")

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(save, [first, second]))
        finally:
            first.close()
            second.close()

        self.assertTrue(all(item["status"] == "accepted" for item in results), results)
        self.assertEqual(sum(item["duplicate"] for item in results), 1, results)
        self.assertEqual(
            self.core.store.db.execute(
                "SELECT COUNT(*) AS n FROM capabilities"
            ).fetchone()["n"],
            1,
        )
        self.assertEqual(
            self.core.store.db.execute(
                "SELECT COUNT(*) AS n FROM capability_versions"
            ).fetchone()["n"],
            1,
        )
