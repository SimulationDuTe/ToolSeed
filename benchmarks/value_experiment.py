"""Repeatable P0 value experiment (P0-SLIM §11.2).

This harness compares a deterministic reference agent solving tasks from
scratch (A) with one that saves procedures once and then searches/delivers
them through ToolSeed (B).

The reference agent is scripted: operation counts and task completion are
simulated. The harness verifies reuse mechanics and accounting; it is **not**
evidence of real LLM productivity or net benefit. See ``benchmarks/README.md``.
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from toolseed import ToolSeed


@dataclass(frozen=True)
class Task:
    task_id: str
    query: str
    manifest: dict[str, Any]
    content: str
    expected_marker: str
    baseline_steps: tuple[str, ...]
    reuse_steps: tuple[str, ...]


def _manifest(
    name: str,
    description: str,
    when_to_use: str,
    tags: list[str],
) -> dict[str, Any]:
    return {
        "name": name,
        "kind": "procedure",
        "description": description,
        "when_to_use": when_to_use,
        "not_for": [],
        "tags": tags,
        "applicability": {
            "harnesses": [],
            "operating_systems": [],
            "required_tools": [],
        },
    }


TASKS: tuple[Task, ...] = (
    Task(
        task_id="api_timeout",
        query="apitimeout",
        manifest=_manifest(
            "triage_api_timeout",
            "分层排查 API 请求超时",
            "请求间歇性超时，需要区分客户端、网络和服务端原因",
            ["apitimeout", "debugging"],
        ),
        content=(
            "1. 确认请求是否到达服务端，对比客户端与服务端入口时间。\n"
            "2. 检查 DNS、代理与连接池配置。\n"
            "3. 检查下游依赖与慢查询。\n"
            "RESULT: layer_identified"
        ),
        expected_marker="layer_identified",
        baseline_steps=(
            "read_symptom",
            "list_hypotheses",
            "check_client_logs",
            "check_server_logs",
            "check_dns",
            "check_connection_pool",
            "check_downstream",
            "write_conclusion",
        ),
        reuse_steps=(
            "apply_step_1",
            "apply_step_2",
            "apply_step_3",
            "write_conclusion",
        ),
    ),
    Task(
        task_id="port_conflict",
        query="portconflict",
        manifest=_manifest(
            "diagnose_port_conflict",
            "定位端口占用并确认所有者",
            "服务因端口被占用而启动失败",
            ["portconflict", "network"],
        ),
        content=(
            "1. 列出监听目标端口的进程。\n"
            "2. 确认进程所有者与其用途。\n"
            "3. 通过受控流程停止或迁移进程。\n"
            "RESULT: owner_identified"
        ),
        expected_marker="owner_identified",
        baseline_steps=(
            "read_error",
            "list_listeners",
            "inspect_process",
            "check_owner",
            "decide_action",
            "apply_action",
            "verify_port",
        ),
        reuse_steps=(
            "apply_step_1",
            "apply_step_2",
            "apply_step_3",
            "verify_port",
        ),
    ),
    Task(
        task_id="log_rotation",
        query="logrotation",
        manifest=_manifest(
            "plan_log_rotation",
            "制定磁盘日志轮转与清理方案",
            "日志占用磁盘空间且需要安全轮转",
            ["logrotation", "disk"],
        ),
        content=(
            "1. 统计日志目录占用与增长速率。\n"
            "2. 确认保留期限与合规要求。\n"
            "3. 使用受控轮转策略并验证空间释放。\n"
            "RESULT: rotation_plan"
        ),
        expected_marker="rotation_plan",
        baseline_steps=(
            "measure_usage",
            "identify_large_files",
            "check_retention_policy",
            "design_rotation",
            "apply_rotation",
            "verify_free_space",
        ),
        reuse_steps=(
            "apply_step_1",
            "apply_step_2",
            "apply_step_3",
            "verify_free_space",
        ),
    ),
    Task(
        task_id="flaky_test",
        query="flakytest",
        manifest=_manifest(
            "triage_flaky_test",
            "分层排查间歇性失败的测试",
            "测试偶发失败且需要区分环境、时序和真实缺陷",
            ["flakytest", "triage"],
        ),
        content=(
            "1. 收集失败频率与最近变更。\n"
            "2. 在隔离环境中重复运行。\n"
            "3. 检查共享状态与时序依赖。\n"
            "RESULT: cause_candidate"
        ),
        expected_marker="cause_candidate",
        baseline_steps=(
            "read_failure",
            "count_failures",
            "check_recent_changes",
            "rerun_isolated",
            "inspect_shared_state",
            "inspect_timing",
            "form_cause",
            "write_conclusion",
        ),
        reuse_steps=(
            "apply_step_1",
            "apply_step_2",
            "apply_step_3",
            "write_conclusion",
        ),
    ),
)


def _candidate(task: Task) -> dict[str, Any]:
    return {
        "protocol_version": 1,
        "manifest": task.manifest,
        "content": task.content,
    }


def _reference_apply(task: Task, content: str) -> bool:
    """Deterministic completion check for the scripted reference agent."""
    return task.expected_marker in content


def _run_baseline(tasks: tuple[Task, ...], repetitions: int) -> dict[str, Any]:
    start = time.perf_counter()
    task_operations = 0
    completed_runs = 0
    for _ in range(repetitions):
        for task in tasks:
            task_operations += len(task.baseline_steps)
            completed_runs += 1
    elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
    return {
        "runs": len(tasks) * repetitions,
        "completed_runs": completed_runs,
        "completion_source": "reference_executor_simulated",
        "task_operations": task_operations,
        "api_operations": 0,
        "total_operations": task_operations,
        "elapsed_ms": elapsed_ms,
    }


def _run_toolseed(tasks: tuple[Task, ...], repetitions: int) -> dict[str, Any]:
    # Keep the run inside the workspace. ``tempfile`` on this host creates a
    # directory the sandboxed SQLite process cannot open.
    run_root = Path(".toolseed") / "value-experiment" / "run"
    shutil.rmtree(run_root, ignore_errors=True)
    core = ToolSeed(str(run_root))
    try:
        start = time.perf_counter()
        saves = 0
        for task in tasks:
            saved = core.toolbox_save(_candidate(task), "value experiment seed")
            if saved.get("status") != "accepted":
                raise RuntimeError(f"seed save failed for {task.task_id}: {saved}")
            saves += 1
        creation_ms = round((time.perf_counter() - start) * 1000, 3)

        searches = 0
        content_reads = 0
        adopted_runs = 0
        fallback_runs = 0
        task_operations = 0
        outcomes = 0

        for repetition in range(repetitions):
            for task in tasks:
                found = core.toolbox_search(task.query)
                searches += 1
                results = found.get("results", [])
                adopted = False

                if len(results) == 1:
                    delivered = core.toolbox_run(results[0]["capability_id"])
                    content_reads += 1
                    if (
                        delivered.get("ok")
                        and delivered.get("execution_status") == "guidance_delivered"
                    ):
                        adopted = _reference_apply(
                            task, delivered["result"]["content"]
                        )

                if adopted:
                    adopted_runs += 1
                    task_operations += len(task.reuse_steps)
                    core.record_task_outcome(
                        capability_id=delivered["capability_id"],
                        version_id=delivered["version_id"],
                        invocation_id=delivered["invocation_id"],
                        outcome="success",
                        source_type="test_runner",
                        task_id=f"{task.task_id}_r{repetition}",
                        summary="reference executor verified expected marker",
                    )
                    outcomes += 1
                else:
                    fallback_runs += 1
                    task_operations += len(task.baseline_steps)

        elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
        stats = core.toolbox_stats()
        api_operations = saves + searches + content_reads
        return {
            "runs": len(tasks) * repetitions,
            "completed_runs": adopted_runs + fallback_runs,
            "completion_source": "reference_executor_simulated",
            "adopted_runs": adopted_runs,
            "fallback_runs": fallback_runs,
            "adoption_rate": adopted_runs / (len(tasks) * repetitions),
            "saves": saves,
            "creation_ms": creation_ms,
            "searches": searches,
            "content_reads": content_reads,
            "task_operations": task_operations,
            "api_operations": api_operations,
            "total_operations": task_operations + api_operations,
            "elapsed_ms": elapsed_ms,
            "duplicate_hits": stats["duplicates"]["hits"],
            "task_outcomes": stats["task_outcomes"],
            "outcomes_recorded": outcomes,
        }
    finally:
        core.close()
        shutil.rmtree(run_root, ignore_errors=True)
        try:
            run_root.parent.rmdir()
        except OSError:
            pass
        try:
            run_root.parent.parent.rmdir()
        except OSError:
            pass


def run_experiment(
    tasks: tuple[Task, ...] = TASKS,
    repetitions: int = 3,
) -> dict[str, Any]:
    if repetitions < 1:
        raise ValueError("repetitions must be at least 1")
    baseline = _run_baseline(tasks, repetitions)
    toolseed = _run_toolseed(tasks, repetitions)

    operation_delta = baseline["total_operations"] - toolseed["total_operations"]
    baseline_operations = baseline["total_operations"]
    expected_adoptions = len(tasks) * repetitions
    verified = (
        toolseed["adoption_rate"] == 1.0
        and toolseed["fallback_runs"] == 0
        and toolseed["outcomes_recorded"] == expected_adoptions
        and toolseed["task_outcomes"]["success"] == expected_adoptions
    )

    return {
        "experiment": "P0-SLIM §11.2 deterministic reference-agent comparison",
        "kind": "deterministic_reference_agent",
        "tasks": [task.task_id for task in tasks],
        "repetitions": repetitions,
        "baseline": baseline,
        "toolseed": toolseed,
        "delta": {
            "operations": operation_delta,
            "operation_savings_ratio": (
                operation_delta / baseline_operations if baseline_operations else None
            ),
            "elapsed_ms": round(baseline["elapsed_ms"] - toolseed["elapsed_ms"], 3),
        },
        "mechanism_status": "verified" if verified else "not_verified",
        "unknown": [
            "provider_token_cost",
            "llm_latency",
            "real_agent_productivity",
            "long_term_learning",
        ],
        "limitations": [
            "Task completion and operation counts are simulated by a scripted reference executor.",
            "No LLM or external task verifier is involved; elapsed time measures local API calls only.",
            "The result verifies the reuse mechanism and accounting; it is not proof of net benefit.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args(argv)

    report = run_experiment(TASKS, args.repetitions)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["mechanism_status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
