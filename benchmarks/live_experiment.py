"""Live A/B experiment harness for real agents (P0-SLIM §11.2).

The harness itself does not call a model. It runs a pluggable ``AgentRunner``
under conditions A (no ToolSeed) and B (ToolSeed available), verifies the answer
with a programmatic verifier, records one JSONL row per run, and aggregates
paired results.

``ScriptedAgent`` is an oracle used to validate the harness. A real experiment
must use ``CommandAgent`` (or another live AgentRunner) and an independent
verifier; otherwise the result is a mechanism check, not value evidence.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from toolseed import ToolSeed


@dataclass(frozen=True)
class TaskInstance:
    instance_id: str
    family: str
    prompt: str
    expected: dict[str, Any]

    def verify(self, answer: Any) -> bool:
        if not isinstance(answer, dict):
            return False
        return all(answer.get(key) == value for key, value in self.expected.items())


TASKS: tuple[TaskInstance, ...] = (
    TaskInstance(
        instance_id="api_timeout_network",
        family="api_timeout",
        prompt=(
            "Diagnose an API timeout. Evidence:\n"
            "- Client log: request at 10:00:00, no retry.\n"
            "- Server ingress log: no matching request at 10:00:00.\n"
            "- DNS resolution took 3.2s and returned an address.\n"
            "Return only JSON: {\"layer\": \"client\"|\"network\"|\"server\"}."
        ),
        expected={"layer": "network"},
    ),
    TaskInstance(
        instance_id="api_timeout_server",
        family="api_timeout",
        prompt=(
            "Diagnose an API timeout. Evidence:\n"
            "- Client sent one request; no retry.\n"
            "- Server ingress received it at 10:00:00.\n"
            "- The downstream database query took 9s.\n"
            "Return only JSON: {\"layer\": \"client\"|\"network\"|\"server\"}."
        ),
        expected={"layer": "server"},
    ),
    TaskInstance(
        instance_id="port_conflict_old_app",
        family="port_conflict",
        prompt=(
            "A service fails to bind port 8080. The listener is PID 4242, owner "
            "'app-old', and it is still serving traffic. The new service is "
            "'app-new'.\n"
            "Return only JSON: {\"owner\": \"<process owner>\"}."
        ),
        expected={"owner": "app-old"},
    ),
    TaskInstance(
        instance_id="port_conflict_system",
        family="port_conflict",
        prompt=(
            "A service fails to bind port 53. The listener is PID 700, owner "
            "'systemd-resolved', and it is the active DNS resolver.\n"
            "Return only JSON: {\"owner\": \"<process owner>\"}."
        ),
        expected={"owner": "systemd-resolved"},
    ),
    TaskInstance(
        instance_id="flaky_shared_state",
        family="flaky_test",
        prompt=(
            "A test fails about 1 in 20 runs only when run with the full suite. "
            "The test and another test both mutate a module-level cache; both pass "
            "in isolation.\n"
            "Return only JSON: {\"cause\": \"shared_state\"|\"timing\"}."
        ),
        expected={"cause": "shared_state"},
    ),
    TaskInstance(
        instance_id="flaky_timing",
        family="flaky_test",
        prompt=(
            "A test fails about 1 in 30 runs. The failure appears only when the CI "
            "machine is loaded, and the assertion compares timestamps within 50ms. "
            "No shared mutable state is involved.\n"
            "Return only JSON: {\"cause\": \"shared_state\"|\"timing\"}."
        ),
        expected={"cause": "timing"},
    ),
)


def _manifest(name: str, description: str, when: str, tags: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "kind": "procedure",
        "description": description,
        "when_to_use": when,
        "not_for": [],
        "tags": tags,
        "applicability": {
            "harnesses": [],
            "operating_systems": [],
            "required_tools": [],
        },
    }


PROCEDURES: dict[str, dict[str, Any]] = {
    "api_timeout": {
        "protocol_version": 1,
        "manifest": _manifest(
            "triage_api_timeout_live",
            "分层排查 API 请求超时",
            "请求超时且需要区分客户端、网络和服务端原因",
            ["api_timeout", "live"],
        ),
        "content": (
            "1. 对比客户端发起时间与服务端入口时间。\n"
            "2. 服务端未收到请求时，检查 DNS、代理和连接池。\n"
            "3. 服务端收到但处理慢时，检查下游依赖和慢查询。\n"
            "4. 只有客户端重试或本地阻塞时归因客户端。"
        ),
    },
    "port_conflict": {
        "protocol_version": 1,
        "manifest": _manifest(
            "diagnose_port_conflict_live",
            "定位端口占用并确认所有者",
            "服务因端口被占用而启动失败",
            ["port_conflict", "live"],
        ),
        "content": (
            "1. 列出监听目标端口的进程和 PID。\n"
            "2. 确认进程所有者及其用途。\n"
            "3. 系统关键服务不得直接停止，应迁移端口或走受控流程。"
        ),
    },
    "flaky_test": {
        "protocol_version": 1,
        "manifest": _manifest(
            "triage_flaky_test_live",
            "分层排查间歇性失败的测试",
            "测试偶发失败且需要区分共享状态与时序",
            ["flaky_test", "live"],
        ),
        "content": (
            "1. 记录失败频率以及是否只在全量运行时出现。\n"
            "2. 检查测试之间是否共享可变状态。\n"
            "3. 检查时序、负载和过紧的时间断言。"
        ),
    },
}


@dataclass(frozen=True)
class AgentResult:
    answer: Any
    elapsed_ms: float
    raw: str = ""
    error: str | None = None
    tokens: int | None = None


class AgentRunner(Protocol):
    def run(
        self,
        instance: TaskInstance,
        condition: str,
        toolbox_dir: Path | None,
    ) -> AgentResult:
        ...


class ScriptedAgent:
    """Oracle runner that exercises ToolSeed for condition B.

    This validates the harness only. It is not a value experiment.
    """

    def run(
        self,
        instance: TaskInstance,
        condition: str,
        toolbox_dir: Path | None,
    ) -> AgentResult:
        start = time.perf_counter()
        raw = ""
        if condition == "B" and toolbox_dir is not None:
            core = ToolSeed(str(toolbox_dir))
            try:
                found = core.toolbox_search(instance.family)
                results = found.get("results", [])
                if len(results) == 1:
                    delivered = core.toolbox_run(results[0]["capability_id"])
                    raw = json.dumps(delivered, ensure_ascii=False)[:500]
            finally:
                core.close()
        elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
        return AgentResult(answer=dict(instance.expected), elapsed_ms=elapsed_ms, raw=raw)


class CommandAgent:
    """Run an external agent command for each instance/condition.

    The command receives:
      LIVE_PROMPT_FILE, LIVE_OUTPUT, LIVE_INSTANCE_ID, LIVE_FAMILY,
      LIVE_CONDITION, LIVE_TOOLBOX_DIR
    It must write a JSON object to LIVE_OUTPUT (or print it as the last line).
    """

    def __init__(
        self,
        command: str,
        timeout_s: int = 300,
        output_dir: Path | None = None,
    ) -> None:
        if not command.strip():
            raise ValueError("agent command must not be empty")
        self.command = command
        self.timeout_s = timeout_s
        self.output_dir = output_dir or Path(".toolseed") / "live-experiment" / "agent-output"

    def run(
        self,
        instance: TaskInstance,
        condition: str,
        toolbox_dir: Path | None,
    ) -> AgentResult:
        output_dir = self.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex[:8]
        prompt_file = output_dir / f"{instance.instance_id}-{condition}-{token}.prompt.txt"
        output_file = output_dir / f"{instance.instance_id}-{condition}-{token}.json"
        prompt_file.write_text(instance.prompt, encoding="utf-8")

        env = os.environ.copy()
        env.update(
            {
                "LIVE_PROMPT": instance.prompt,
                "LIVE_PROMPT_FILE": str(prompt_file.resolve()),
                "LIVE_OUTPUT": str(output_file.resolve()),
                "LIVE_INSTANCE_ID": instance.instance_id,
                "LIVE_FAMILY": instance.family,
                "LIVE_CONDITION": condition,
                "LIVE_TOOLBOX_DIR": str(toolbox_dir.resolve()) if toolbox_dir else "",
            }
        )

        start = time.perf_counter()
        stdout_file = output_dir / f"{instance.instance_id}-{condition}-{token}.stdout.txt"
        stderr_file = output_dir / f"{instance.instance_id}-{condition}-{token}.stderr.txt"
        try:
            # Redirect to files rather than pipes: some sandboxes deny pipe-based
            # child stdio capture even when file writes are allowed.
            with stdout_file.open("w", encoding="utf-8") as stdout_handle, stderr_file.open(
                "w", encoding="utf-8"
            ) as stderr_handle:
                proc = subprocess.run(
                    self.command,
                    shell=True,
                    env=env,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    text=True,
                    timeout=self.timeout_s,
                )
            stdout = stdout_file.read_text(encoding="utf-8", errors="replace")
            stderr = stderr_file.read_text(encoding="utf-8", errors="replace")
            raw = stdout + stderr
            if output_file.exists():
                answer = json.loads(output_file.read_text(encoding="utf-8"))
            else:
                answer = json.loads(stdout.strip())
            error = None if proc.returncode == 0 else f"exit code {proc.returncode}"
        except Exception as exc:  # noqa: BLE001 - report, don't abort the run
            answer = None
            raw = ""
            error = str(exc)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
        return AgentResult(
            answer=answer,
            elapsed_ms=elapsed_ms,
            raw=raw[:2000],
            error=error,
        )


def _seed_toolbox(path: Path, families: list[str]) -> None:
    core = ToolSeed(str(path))
    try:
        for family in families:
            saved = core.toolbox_save(PROCEDURES[family], "live experiment seed")
            if saved.get("status") != "accepted":
                raise RuntimeError(f"seed save failed for {family}: {saved}")
    finally:
        core.close()


def _toolbox_usage(path: Path) -> tuple[int, int]:
    core = ToolSeed(str(path))
    try:
        stats = core.toolbox_stats()
        return stats["search"]["requests"], stats["delivery"]["count"]
    finally:
        core.close()


def _record_verified_outcome(path: Path, success: bool, task_id: str) -> bool:
    """Attach the verifier result to the last delivery, with an independent source."""
    core = ToolSeed(str(path))
    try:
        row = core.store.db.execute(
            "SELECT capability_id, version_id, invocation_id FROM invocations "
            "ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return False
        result = core.record_task_outcome(
            capability_id=row["capability_id"],
            version_id=row["version_id"],
            invocation_id=row["invocation_id"],
            outcome="success" if success else "failure",
            source_type="test_runner",
            task_id=task_id,
            summary="live experiment verifier",
        )
        return bool(result.get("ok"))
    finally:
        core.close()


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _bootstrap_ci(values: list[float], iterations: int = 2000) -> list[float] | None:
    if not values:
        return None
    rng = random.Random(0)
    means = sorted(
        sum(rng.choice(values) for _ in values) / len(values)
        for _ in range(iterations)
    )
    low = means[int(0.025 * iterations)]
    high = means[int(0.975 * iterations) - 1]
    return [round(low, 4), round(high, 4)]


def _mcnemar_p(b: int, c: int) -> float:
    total = b + c
    if total == 0:
        return 1.0
    tail = sum(math.comb(total, k) for k in range(0, min(b, c) + 1)) / (2**total)
    return round(min(1.0, 2 * tail), 6)


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_condition = {
        condition: [record for record in records if record["condition"] == condition]
        for condition in ("A", "B")
    }
    pairs: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for record in records:
        key = (record["instance_id"], record["seed"])
        pairs.setdefault(key, {})[record["condition"]] = record

    paired = [pair for pair in pairs.values() if "A" in pair and "B" in pair]
    success_deltas = [
        float(pair["B"]["success"]) - float(pair["A"]["success"]) for pair in paired
    ]
    time_saved = [pair["A"]["elapsed_ms"] - pair["B"]["elapsed_ms"] for pair in paired]
    b_discordant = sum(1 for pair in paired if not pair["A"]["success"] and pair["B"]["success"])
    c_discordant = sum(1 for pair in paired if pair["A"]["success"] and not pair["B"]["success"])

    b_records = by_condition["B"]
    adoption_rate = (
        sum(1 for record in b_records if record["deliveries"] > 0) / len(b_records)
        if b_records
        else None
    )

    return {
        "records": len(records),
        "pairs": len(paired),
        "success_rate": {
            condition: (
                sum(1 for record in by_condition[condition] if record["success"])
                / len(by_condition[condition])
                if by_condition[condition]
                else None
            )
            for condition in ("A", "B")
        },
        "mean_elapsed_ms": {
            condition: _mean([record["elapsed_ms"] for record in by_condition[condition]])
            for condition in ("A", "B")
        },
        "adoption_rate": adoption_rate,
        "task_outcomes_recorded": sum(
            1 for record in records if record.get("outcomes_recorded")
        ),
        "paired_success_delta_B_minus_A": {
            "mean": _mean(success_deltas),
            "bootstrap_95ci": _bootstrap_ci(success_deltas),
            "mcnemar_p": _mcnemar_p(b_discordant, c_discordant),
            "discordant_a_fail_b_success": b_discordant,
            "discordant_a_success_b_fail": c_discordant,
        },
        "paired_time_saved_ms_A_minus_B": {
            "mean": _mean(time_saved),
            "bootstrap_95ci": _bootstrap_ci(time_saved),
        },
        "unknown": ["provider_token_cost", "real_agent_productivity", "human_blinding"],
        "note": (
            "Only a real AgentRunner plus an independent verifier can support a "
            "value claim; ScriptedAgent validates the harness."
        ),
    }


def run_experiment(
    agent: AgentRunner,
    tasks: tuple[TaskInstance, ...] = TASKS,
    seeds: int = 1,
    data_root: Path = Path(".toolseed"),
    out_path: Path | None = None,
) -> dict[str, Any]:
    if seeds < 1:
        raise ValueError("seeds must be at least 1")
    data_root.mkdir(parents=True, exist_ok=True)
    run_root = data_root / "live-experiment" / "runs"
    shutil.rmtree(run_root, ignore_errors=True)
    run_root.mkdir(parents=True, exist_ok=True)
    if out_path is None:
        out_path = data_root / "live-experiment" / "records.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("", encoding="utf-8")

    families = sorted({task.family for task in tasks})
    records: list[dict[str, Any]] = []

    for seed in range(seeds):
        for task in tasks:
            for condition in ("A", "B"):
                toolbox_dir = None
                if condition == "B":
                    toolbox_dir = run_root / f"{seed}-{task.instance_id}-B"
                    _seed_toolbox(toolbox_dir, families)

                try:
                    result = agent.run(task, condition, toolbox_dir)
                except Exception as exc:  # noqa: BLE001 - record and continue
                    result = AgentResult(answer=None, elapsed_ms=0.0, error=str(exc))

                success = task.verify(result.answer)
                searches = 0
                deliveries = 0
                outcomes_recorded = 0
                if toolbox_dir is not None:
                    searches, deliveries = _toolbox_usage(toolbox_dir)
                    outcomes_recorded = int(
                        _record_verified_outcome(
                            toolbox_dir, success, f"{task.instance_id}-seed{seed}"
                        )
                    )
                    shutil.rmtree(toolbox_dir, ignore_errors=True)

                record = {
                    "seed": seed,
                    "instance_id": task.instance_id,
                    "family": task.family,
                    "condition": condition,
                    "success": success,
                    "elapsed_ms": result.elapsed_ms,
                    "searches": searches,
                    "deliveries": deliveries,
                    "adoption": deliveries > 0,
                    "outcomes_recorded": outcomes_recorded,
                    "answer": result.answer,
                    "error": result.error,
                    "tokens": result.tokens,
                    "raw": result.raw[:1000],
                }
                records.append(record)
                with out_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    report = aggregate(records)
    report["records_path"] = str(out_path)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("scripted", "command"), default="scripted")
    parser.add_argument("--agent-command", default="", help="required for --mode command")
    parser.add_argument("--seeds", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument(
        "--out",
        default=".toolseed/live-experiment/records.jsonl",
    )
    args = parser.parse_args(argv)

    if args.mode == "command":
        if not args.agent_command.strip():
            parser.error("--agent-command is required for --mode command")
        agent: AgentRunner = CommandAgent(args.agent_command, timeout_s=args.timeout)
    else:
        agent = ScriptedAgent()

    report = run_experiment(
        agent,
        seeds=args.seeds,
        out_path=Path(args.out),
    )
    report["runner"] = args.mode
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
