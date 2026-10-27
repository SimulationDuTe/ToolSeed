"""Two real-agent Procedure acceptance tasks; no A/B runner or product changes.

Run prepare first, then run A and B separately. B is refused until A has an
independently checked result and a real save receipt. Model reasoning is dropped
from the CLI stream. Workspaces and the one shared test library use a new run
directory. No credentials are copied and no user configuration is written.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import shutil
import sqlite3
import subprocess
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MODEL = "gpt-6.1-sol"


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_case(key: str, kind: str, wanted: object, layers: list, snapshot=None) -> dict:
    return {"id": key, "type": kind, "desired": wanted, "layers": layers,
            "runtime_snapshot": snapshot}


def fixtures(task: str) -> list[dict]:
    if task == "A":
        return [
            make_case("preview", "boolean", True, [["defaults", False], ["project", True], ["user", False]]),
            make_case("extensions", "array", ["spellcheck"], [["defaults", ["spellcheck"]], ["project", []]]),
            make_case("offline", "boolean", False, [["defaults", True], ["user", "false"]]),
            make_case("notifications", "boolean", True, [["defaults", False], ["project", True]], {"value": False, "fresh": False}),
            make_case("autosave", "boolean", True, [["defaults", False], ["project", True]], {"value": True, "fresh": True}),
        ]
    return [
        make_case("indexing", "boolean", False, [["base", True], ["team", False], ["session", True]]),
        make_case("formatters", "array", ["formatter-z"], [["base", ["formatter-z"]], ["team", ["formatter-k"]], ["session", []]]),
        make_case("telemetry", "boolean", False, [["base", True], ["team", False], ["session", None]]),
        make_case("lint", "boolean", False, [["base", True], ["team", False]], {"value": True, "fresh": False}),
        make_case("watch", "boolean", False, [["base", True], ["team", False]], {"value": False, "fresh": True}),
        make_case("integrations", "array", ["lint-b"], [["base", ["lint-a"]], ["team", ["lint-b"]]], {"value": ["lint-b"], "fresh": True}),
    ]


def expected(case: dict) -> dict:
    source, value = case["layers"][-1]
    valid = type(value) is bool if case["type"] == "boolean" else isinstance(value, list)
    snapshot = case["runtime_snapshot"]
    confirmed = bool(valid and snapshot and snapshot["fresh"] and snapshot["value"] == value)
    if not valid:
        diagnosis = "invalid_type"
    elif value != case["desired"]:
        diagnosis = "empty_array_override" if value == [] else "higher_priority_override"
    elif not confirmed:
        diagnosis = "runtime_unconfirmed"
    else:
        diagnosis = "in_sync"
    return {"id": case["id"], "effective_value": value, "winning_layer": source,
            "value_valid": valid, "runtime_confirmed": confirmed, "diagnosis": diagnosis,
            "trace": [{"layer": name, "value": item} for name, item in case["layers"]]}


def verify(workspace: Path) -> dict:
    cases = json.loads((workspace / "cases.json").read_text(encoding="utf-8"))
    wanted = [expected(case) for case in cases]
    try:
        actual = json.loads((workspace / "diagnosis.json").read_text(encoding="utf-8-sig"))
        rows = actual["cases"]
        if len(rows) != len(wanted) or len({row["id"] for row in rows}) != len(wanted):
            raise ValueError("case count / duplicate IDs")
        by_id = {row["id"]: row for row in rows}
        failures = []
        for target in wanted:
            row = by_id.get(target["id"], {})
            for key, value in target.items():
                # In particular, false/0 and null/absent must not be equated.
                if key not in row or json.dumps(row[key], sort_keys=True) != json.dumps(value, sort_keys=True):
                    failures.append(f"{target['id']}.{key}")
        return {"passed": not failures, "case_count": len(wanted), "failures": failures}
    except (OSError, ValueError, KeyError, TypeError) as error:
        return {"passed": False, "case_count": len(wanted), "failures": [type(error).__name__]}


TASK = """# Recurring release configuration review

Our team repeats this read-only review before releases. Review every case in
cases.json and produce diagnosis.json plus a short review.md for maintainers.
Do not change any input, validator or actual service configuration. There is no
live service to restart. Use observable facts; a saved value is not proof that a
running process applied it. Run the supplied check_result.py on your output.

Data contract (not an ordered diagnostic method): layers are listed from lowest
to highest priority; each is a [source label, value] pair. Every listed value is
explicit, including false, null and empty arrays. A higher layer replaces the
entire value; arrays do not concatenate. Desired is the requested setting, not a
configuration layer. Boolean means a JSON boolean; array means a JSON array.
runtime_snapshot is absent/null or has value and fresh; fresh=false predates the
configuration change and cannot confirm the current runtime.

Output: {"cases": [...]} with exactly one row per input ID. Each row has id,
effective_value, winning_layer, value_valid (boolean), runtime_confirmed (boolean),
diagnosis, and trace (all input layers in order as {"layer":..., "value":...}).
Diagnosis is invalid_type for a schema mismatch; otherwise when effective differs
from desired use empty_array_override for [] and higher_priority_override for
other values; otherwise use runtime_unconfirmed unless a fresh, matching runtime
snapshot confirms it, in which case use in_sync. Invalid values never confirm the
runtime. review.md should explain the observed causes, safe next steps and limits.
"""


def prepare(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=False)
    (root / "results").mkdir()
    (root / "library").mkdir()
    skill = REPO / "toolseed/skill/SKILL.md"
    checker = '''from pathlib import Path
import importlib.util,json
spec=importlib.util.spec_from_file_location("acceptance", Path(__file__).with_name("acceptance_reference.py"))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
result=module.verify(Path(__file__).parent)
print(json.dumps(result));raise SystemExit(0 if result["passed"] else 1)
'''
    for task in ("A", "B"):
        ws = root / f"task-{task}"
        ws.mkdir()
        installed = ws / ".agents/skills/toolseed"
        installed.mkdir(parents=True)
        shutil.copyfile(skill, installed / "SKILL.md")
        (ws / "AGENTS.md").write_text(
            "Work only in this task directory. Inputs and validators are read-only. "
            "Do not inspect parent/sibling directories or other sessions. Do not use "
            "subagents, browse the internet, change permissions, install packages or "
            "change user/repository configuration. Use existing authorized tools. "
            "Write only the requested output and task-local working files.\n", encoding="utf-8")
        (ws / "task.md").write_text(TASK, encoding="utf-8")
        dump(ws / "cases.json", fixtures(task))
        (ws / "check_result.py").write_text(checker, encoding="utf-8")
        # The agent sees the checker, not this driver or the other task's cases.
        (ws / "acceptance_reference.py").write_text(
            "from pathlib import Path\nimport json\n\n" + inspect.getsource(expected)
            + "\n" + inspect.getsource(verify), encoding="utf-8")
    paths = [path for task in ("A", "B") for path in (root / f"task-{task}").rglob("*") if path.is_file()]
    dump(root / "setup.json", {"model_requested": MODEL, "reasoning_effort": "medium",
        "skill_sha256": digest(skill), "protected_inputs": {str(p.relative_to(root)): digest(p) for p in paths},
        "task_prompt": "Complete task.md in this workspace.", "synthetic_tasks": True,
        "library": str(root / "library"), "product_code_changed": False})
    print(json.dumps({"prepared": str(root), "tasks": 2, "preseeded_capabilities": 0}))


def cli_command(root: Path, task: str) -> list[str]:
    python = (REPO / ".venv/Scripts/python.exe").as_posix()
    server = {"command": python, "args": ["-B", "-m", "toolseed.mcp_server", "--data-dir", (root / "library").as_posix()],
              "cwd": REPO.as_posix(), "required": True, "startup_timeout_sec": 30,
              "enabled_tools": ["toolbox_search", "toolbox_save", "toolbox_run", "toolbox_stats"],
              "default_tools_approval_mode": "approve"}
    toml = "{" + ",".join(f"{key}={json.dumps(value)}" for key, value in server.items()) + "}"
    return [shutil.which("codex") or "codex", "-a", "never", "exec", "--ignore-user-config",
            "--ephemeral", "--skip-git-repo-check", "--color", "never", "--json", "-s", "workspace-write",
            "-m", MODEL, "-c", 'model_reasoning_effort="medium"', "-c", "mcp_servers.toolseed=" + toml,
            "-c", "sqlite_home=" + json.dumps((root / "codex-state").as_posix()),
            "-C", str(root / f"task-{task}"), "Complete task.md in this workspace."]


def selfcheck(root: Path) -> None:
    """Check that completion claims and plausible but wrong outputs are rejected."""
    workspace = root / "validator-selfcheck"
    workspace.mkdir(exist_ok=False)
    checks = []
    for task in ("A", "B"):
        cases = fixtures(task)
        dump(workspace / "cases.json", cases)
        dump(workspace / "diagnosis.json", {"cases": [expected(c) for c in cases]})
        assert verify(workspace)["passed"]
        checks.append(f"valid_{task}")
    dump(workspace / "diagnosis.json", {"completed": True})
    assert not verify(workspace)["passed"]
    checks.append("completion_claim_rejected")
    for index, field, wrong, name in (
        (2, "effective_value", False, "null_fallback_rejected"),
        (3, "runtime_confirmed", True, "stale_snapshot_rejected"),
        (1, "trace", [{"layer": "invented", "value": []}], "wrong_trace_rejected"),
        (4, "effective_value", 0, "zero_is_not_false"),
    ):
        rows = [expected(c) for c in fixtures("B")]
        rows[index][field] = wrong
        dump(workspace / "diagnosis.json", {"cases": rows})
        assert not verify(workspace)["passed"]
        checks.append(name)
    result = {"passed": len(checks), "failed": 0, "skipped": 0, "checks": checks}
    dump(root / "validator-selfcheck.json", result)
    print(json.dumps(result))


def project_event(event: dict) -> dict | None:
    kind = event.get("type")
    if kind == "thread.started":
        return {"type": kind, "context_hash": hashlib.sha256(event["thread_id"].encode()).hexdigest()}
    if kind in ("turn.started", "turn.completed", "turn.failed", "error"):
        return event
    if kind != "item.completed":
        return None
    item = event.get("item", {})
    if item.get("type") in ("mcp_tool_call", "command_execution", "file_change", "agent_message"):
        return event
    return None  # Includes reasoning: never persist it.


def run(root: Path, task: str) -> bool:
    destination = root / "results" / task
    destination.mkdir(exist_ok=False)
    if task == "B":
        previous = json.loads((root / "results/A/verdict.json").read_text(encoding="utf8"))
        if not previous["passed"]:
            raise SystemExit("A did not pass independent validation")
        events = [json.loads(line) for line in (root / "results/A/events.jsonl").read_text(encoding="utf8").splitlines()]
        if not any(e.get("item", {}).get("type") == "mcp_tool_call" and e["item"].get("tool") == "toolbox_save"
                   and e["item"].get("status") == "completed" for e in events):
            raise SystemExit("No actual A save call; do not manufacture a capability")
        database = root / "library/toolseed.sqlite3"
        with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
            stored = db.execute("SELECT COUNT(*) FROM capabilities").fetchone()[0]
        if not stored:
            raise SystemExit("A save call did not persist a capability; B is not admitted")
    command = cli_command(root, task)
    dump(destination / "invocation.json", {"argv": command, "cwd": str(root / f"task-{task}"),
                                          "timeout_seconds": 600})
    started = time.perf_counter()
    process = subprocess.Popen(command, cwd=root / f"task-{task}", stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace")
    timed_out = []
    def stop():
        timed_out.append(True)
        # Terminate this test's owned process tree, never other Desktop/Agent processes.
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False)
    timer = threading.Timer(600, stop)
    timer.start()
    stderr_parts = []
    def stderr_reader():
        for line in process.stderr:
            # Transport diagnostics only; the CLI's reasoning is in dropped JSON items.
            if len(stderr_parts) < 80:
                stderr_parts.append(line[:1500])
    reader = threading.Thread(target=stderr_reader, daemon=True)
    reader.start()
    usage = None
    count = 0
    try:
        with (destination / "events.jsonl").open("x", encoding="utf-8") as output:
            for line in process.stdout:
                try:
                    row = project_event(json.loads(line))
                except (ValueError, KeyError):
                    continue
                if row is not None:
                    count += 1
                    output.write(json.dumps(row, ensure_ascii=False) + "\n")
                    output.flush()
                    if row["type"] == "turn.completed":
                        usage = row.get("usage")
                    item = row.get("item", {})
                    print(json.dumps({"task": task, "event": row["type"], "item_type": item.get("type"),
                                      "tool": item.get("tool"), "status": item.get("status")}), flush=True)
        code = process.wait()
    finally:
        timer.cancel()
        reader.join(timeout=5)
    (destination / "stderr.txt").write_text("".join(stderr_parts), encoding="utf-8")
    verdict = verify(root / f"task-{task}")
    setup = json.loads((root / "setup.json").read_text(encoding="utf8"))
    changed = [key for key, value in setup["protected_inputs"].items() if digest(root / key) != value]
    verdict.update({"protected_inputs_unchanged": not changed, "modified_inputs": changed})
    verdict["passed"] = verdict["passed"] and not changed
    dump(destination / "verdict.json", verdict)
    summary = {"task": task, "cli_exit_code": code, "timed_out": bool(timed_out),
               "duration_seconds": round(time.perf_counter() - started, 3), "retained_events": count,
               "cli_reported_usage": usage, "physical_model_calls": "unknown", "billing_cost": "unknown",
               "independent_verdict": verdict}
    dump(destination / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return code == 0 and verdict["passed"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "run", "verify", "selfcheck"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--task", choices=["A", "B"], default="A")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.action == "prepare":
        prepare(root)
    elif args.action == "selfcheck":
        selfcheck(root)
    elif args.action == "run":
        raise SystemExit(0 if run(root, args.task) else 1)
    else:
        result = verify(root / f"task-{args.task}")
        print(json.dumps(result)); raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
