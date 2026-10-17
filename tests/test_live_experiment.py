"""Live A/B harness validation (P0-SLIM §11.2)."""
from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

from benchmarks.live_experiment import (
    TASKS,
    CommandAgent,
    ScriptedAgent,
    run_experiment,
)

BASE = Path(__file__).resolve().parent / ".data" / "live-experiment"


class LiveExperimentTest(unittest.TestCase):
    def setUp(self) -> None:
        shutil.rmtree(BASE, ignore_errors=True)

    def tearDown(self) -> None:
        shutil.rmtree(BASE, ignore_errors=True)

    def test_task_verifiers(self) -> None:
        for task in TASKS:
            self.assertTrue(task.verify(dict(task.expected)), task.instance_id)
            wrong = {key: "wrong" for key in task.expected}
            self.assertFalse(task.verify(wrong), task.instance_id)
            self.assertFalse(task.verify(None), task.instance_id)

    def test_scripted_run_records_and_adopts(self) -> None:
        report = run_experiment(
            ScriptedAgent(),
            seeds=1,
            data_root=BASE,
            out_path=BASE / "records.jsonl",
        )

        self.assertEqual(report["records"], len(TASKS) * 2)
        self.assertEqual(report["pairs"], len(TASKS))
        self.assertEqual(report["success_rate"]["A"], 1.0)
        self.assertEqual(report["success_rate"]["B"], 1.0)
        self.assertEqual(report["adoption_rate"], 1.0)
        self.assertEqual(report["task_outcomes_recorded"], len(TASKS))
        self.assertEqual(report["paired_success_delta_B_minus_A"]["mean"], 0.0)

        lines = (BASE / "records.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), len(TASKS) * 2)
        first = json.loads(lines[0])
        for key in (
            "condition",
            "instance_id",
            "success",
            "elapsed_ms",
            "searches",
            "deliveries",
            "adoption",
            "outcomes_recorded",
            "tokens",
        ):
            self.assertIn(key, first)
        self.assertIsNone(first["tokens"])

    def test_command_agent_runs_external_command(self) -> None:
        script = BASE / "agent.py"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(
            "import json, os\n"
            "with open(os.environ['LIVE_OUTPUT'], 'w', encoding='utf-8') as f:\n"
            "    json.dump({'layer': 'network'}, f)\n",
            encoding="utf-8",
        )
        agent = CommandAgent(
            f'"{sys.executable}" "{script.resolve()}"',
            output_dir=BASE / "agent-output",
        )
        result = agent.run(TASKS[0], "A", None)
        self.assertEqual(result.answer, {"layer": "network"})
        self.assertIsNone(result.error)

    def test_command_agent_requires_a_command(self) -> None:
        with self.assertRaises(ValueError):
            CommandAgent("   ")
