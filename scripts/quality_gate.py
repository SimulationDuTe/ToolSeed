"""Run the local quality gate.

Usage: ``python scripts/quality_gate.py``

Always runs compileall and the unittest suite. Optional tools (ruff, mypy) are
run only when installed; otherwise they are reported as skipped, never silently
treated as passed.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(name: str, command: list[str]) -> bool:
    print(f"\n== {name} ==")
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        print(f"FAIL: {name} (exit {result.returncode})")
        return False
    print(f"PASS: {name}")
    return True


def optional_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def main() -> int:
    checks: list[bool] = []
    checks.append(
        run(
            "compileall",
            [sys.executable, "-m", "compileall", "-q", "toolseed", "tests", "benchmarks"],
        )
    )
    checks.append(
        run(
            "unittest",
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
        )
    )

    if optional_module("ruff"):
        checks.append(run("ruff", [sys.executable, "-m", "ruff", "check", "."]))
    else:
        print("\nSKIP: ruff (not installed; install with `pip install ruff`)")

    if optional_module("mypy"):
        checks.append(run("mypy", [sys.executable, "-m", "mypy", "toolseed"]))
    else:
        print("\nSKIP: mypy (not installed; install with `pip install mypy`)")

    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
