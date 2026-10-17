"""Value-experiment harness (P0-SLIM §11.2)."""
from __future__ import annotations

import unittest

from benchmarks.value_experiment import TASKS, run_experiment


class ValueExperimentTest(unittest.TestCase):
    def test_reference_run_verifies_the_mechanism(self) -> None:
        report = run_experiment(TASKS, repetitions=2)

        self.assertEqual(report["mechanism_status"], "verified", report)
        self.assertEqual(report["toolseed"]["saves"], len(TASKS))
        self.assertEqual(report["toolseed"]["adoption_rate"], 1.0)
        self.assertEqual(report["toolseed"]["fallback_runs"], 0)
        self.assertEqual(
            report["toolseed"]["task_outcomes"]["success"], len(TASKS) * 2
        )
        self.assertEqual(report["toolseed"]["task_outcomes"]["unknown"], 0)
        self.assertTrue(report["toolseed"]["task_outcomes"]["measured"])
        self.assertEqual(report["toolseed"]["duplicate_hits"], 0)
        self.assertGreater(
            report["baseline"]["total_operations"],
            report["toolseed"]["total_operations"],
        )
        self.assertGreater(report["delta"]["operations"], 0)
        self.assertIn("real_agent_productivity", report["unknown"])
