"""Build-isolated install check for a released ToolSeed wheel.

Usage: python scripts/verify_release.py --dist dist
"""
from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
import venv
from pathlib import Path


def _venv_python(root: Path) -> Path:
    if os.name == "nt":
        return root / "Scripts" / "python.exe"
    return root / "bin" / "python"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", default="dist")
    parser.add_argument("--source-root", default=".")
    args = parser.parse_args()
    source_root = Path(args.source_root).resolve()
    dist = Path(args.dist).resolve()
    wheels = sorted(dist.glob("toolseed-*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"expected exactly one wheel in {dist}, found {len(wheels)}")
    wheel = wheels[0]

    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)

    with tempfile.TemporaryDirectory(prefix="toolseed-release-") as temp:
        temp_path = Path(temp)
        venv_dir = temp_path / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(venv_dir)
        python = _venv_python(venv_dir)
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-input",
                str(wheel),
            ],
            cwd=temp_path,
            env=env,
            check=True,
        )
        subprocess.run(
            [
                str(python),
                str(source_root / "scripts" / "package_smoke.py"),
                "--source-root",
                str(source_root),
            ],
            cwd=temp_path,
            env=env,
            check=True,
        )
    print(f"verified wheel: {wheel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
