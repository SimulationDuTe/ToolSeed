"""Export an allowlisted reading snapshot for demonstration/video preparation."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent


def git(*arguments: str) -> str:
    result = subprocess.run(["git", "-C", str(ROOT), *arguments], check=True,
                            capture_output=True, text=True, encoding="utf-8")
    return result.stdout


def select_files(config: dict) -> list[str]:
    tracked = git("ls-files", "-z").split("\0")
    selected = set(config["include_files"])
    for relative in tracked:
        path = Path(relative)
        if (path.suffix in config["source_extensions"]
                and not set(path.parts).intersection(config["excluded_parts"])
                and any(relative.startswith(tree.rstrip("/") + "/") for tree in config["include_trees"])):
            selected.add(relative)
    for relative in selected:
        path = ROOT / relative
        if not path.resolve().is_relative_to(ROOT) or not path.is_file() or path.is_symlink():
            raise ValueError(f"Not a regular project file: {relative}")
    return sorted(selected)


def export(output: Path) -> dict:
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise ValueError(f"Output already exists; choose a new directory: {output}")
    config = json.loads((ROOT / "docs/demo/scan.json").read_text(encoding="utf-8"))
    selected = select_files(config)
    output.parent.mkdir(parents=True, exist_ok=True)
    staged = output.with_name(f".demo-context-staging-{uuid4().hex}")
    staged.mkdir()
    try:
        entries = []
        for relative in selected:
            target = staged / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
            content = target.read_bytes()
            entries.append({"path": relative, "bytes": len(content),
                            "sha256": hashlib.sha256(content).hexdigest()})
        index = {"schema_version": 1, "entrypoint": config["entrypoint"],
                 "purpose": "Reading material for a product demonstration; not an installable release",
                 "generated_at_utc": datetime.now(UTC).isoformat(),
                 "source_commit": git("rev-parse", "HEAD").strip(),
                 "source_has_local_changes": bool(git("status", "--porcelain").strip()),
                 "files": entries}
        (staged / "SCAN-INDEX.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        staged.rename(output)
    except Exception:
        # Only this newly created, link-free staging tree may be removed.
        if staged.exists() and staged.resolve().parent == output.parent.resolve():
            shutil.rmtree(staged)
        raise
    return {"directory": str(output), "entrypoint": str(output / config["entrypoint"]),
            "file_count": len(entries), "bytes": sum(entry["bytes"] for entry in entries),
            "source_commit": index["source_commit"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "demo-context")
    arguments = parser.parse_args()
    try:
        result = export(arguments.output)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(2, f"Export failed: {error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
