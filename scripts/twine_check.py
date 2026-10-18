"""Cross-platform twine check for dist artifacts."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    files = [
        str(path)
        for path in sorted(Path("dist").iterdir())
        if path.suffix in {".whl", ".gz"}
    ]
    if not files:
        raise SystemExit("no dist artifacts found")
    return subprocess.run(
        [sys.executable, "-m", "twine", "check", *files],
        check=False,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
