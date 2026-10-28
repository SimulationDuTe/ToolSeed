"""Pinned source, side-by-side Core installation and isolated migration checks."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from .hosts import (
    HostInstallError,
    fetch_local_tree,
    fetch_tree,
    fingerprint_tree,
    project_version,
    read_manifest,
    repo_slug,
    resolve_ref,
    write_manifest,
)


def run(command: list[str], *, cwd: Path | None = None, timeout: int = 300,
        env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, check=False,
                                encoding="utf-8", errors="replace", timeout=timeout,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HostInstallError("PROCESS_FAILED", f"无法完成升级步骤：{Path(command[0]).name}") from exc
    if result.returncode:
        raise HostInstallError("PROCESS_FAILED", f"升级步骤失败：{Path(command[0]).name}",
                               detail=(result.stderr or result.stdout)[-2000:])
    return result


@dataclass
class UpdateSource:
    tree: Path
    metadata: dict[str, Any]


def acquire_source(root: Path, host: str, ref: str, repo: str | None) -> UpdateSource:
    local = Path(ref).expanduser()
    if local.is_dir():
        local = local.resolve()
        try:
            sha = run(["git", "-C", str(local), "rev-parse", "HEAD"]).stdout.strip()
        except HostInstallError:
            sha = None
        fingerprint = fingerprint_tree(local)
        commit = sha or f"local-{fingerprint}"
        metadata = {"commit_sha": commit, "ref": ref, "ref_kind": "local", "stable": False,
                    "prerelease": True, "release_tag": None, "source": f"local:{local}",
                    "source_fingerprint": fingerprint}
        try:
            dirty = bool(run(["git", "-C", str(local), "status", "--porcelain"]).stdout.strip()) if sha else None
        except HostInstallError:
            dirty = None
        metadata["local_source"] = {"commit": sha, "dirty": dirty, "fingerprint": fingerprint}
        label = f"local-{(sha or fingerprint)[:12]}-{fingerprint[:12]}"
    else:
        resolved = resolve_ref(ref, repo=repo)
        metadata = {"commit_sha": resolved.commit_sha, "ref": ref, "ref_kind": resolved.kind,
                    "stable": resolved.stable, "prerelease": not resolved.stable,
                    "release_tag": resolved.release_tag, "source_fingerprint": None,
                    "source": f"github:{repo_slug(repo)}"}
        label = f"{resolved.label}-{resolved.commit_sha[:12]}"
    target = root / host / label
    if target.exists():
        manifest = read_manifest(target)
        expected = metadata["source_fingerprint"] or manifest.get("source_fingerprint")
        if (manifest.get("commit_sha") == metadata["commit_sha"] and expected
                and fingerprint_tree(target) == expected):
            metadata["source_fingerprint"] = expected
            metadata["version"] = project_version(target)
            return UpdateSource(target, metadata)
        # Never overwrite a previous/partially modified source tree.
        target = target.with_name(f"{label}-{uuid4().hex[:8]}")
    if local.is_dir():
        fetch_local_tree(local, target)
    else:
        fetch_tree(resolved, target, repo=repo)
    metadata["source_fingerprint"] = fingerprint_tree(target)
    for relative in ("pyproject.toml", "README.md", "toolseed/mcp_server.py",
                     "toolseed/skill/SKILL.md", f"integrations/{host}"):
        if not (target / relative).exists():
            raise HostInstallError("INCOMPLETE_RELEASE", f"目标版本缺少完整升级所需文件：{relative}")
    metadata["version"] = project_version(target)
    # Fetch identity is independent of activation. Failed upgrades can reuse a
    # verified snapshot and its isolated Core without being marked installed.
    write_manifest(target, {**metadata, "host": host, "status": "fetched"})
    return UpdateSource(target, metadata)


def probe_core(python: Path, data: Path) -> dict[str, Any]:
    result = run([str(python), "-I", "-B", "-X", "utf8", "-m", "toolseed.mcp_server",
                  "--probe", "--data-dir", str(data)], timeout=30)
    try:
        body = json.loads(result.stdout)
    except ValueError as exc:
        raise HostInstallError("CORE_NOT_READY", "Core 探测未返回有效 JSON。") from exc
    required = {"toolbox_search", "toolbox_save", "toolbox_run", "toolbox_stats", "toolbox_learn"}
    if (body.get("ok") is not True or not required.issubset(body.get("tools", []))
            or body.get("features", {}).get("revision_base_binding") is not True
            or body.get("features", {}).get("read_only_search") is not True
            or os.path.normcase(body.get("data_dir", "")) != os.path.normcase(str(data))
            or not isinstance(body.get("schema_version"), int)):
        raise HostInstallError("CORE_NOT_READY", "目标 Core 缺少完整升级需要的工具、探测或 schema 信息。")
    return body


def prepare_core(source: UpdateSource, base_python: str, data: Path, *, offline: bool) -> tuple[Path, dict]:
    runtime = source.tree / ".runtime"
    python = runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    marker = runtime / "toolseed-runtime.json"
    base_identity = os.path.normcase(str(Path(base_python).resolve()))
    for candidate in sorted(source.tree.glob(".runtime*/toolseed-runtime.json")):
        if not candidate.resolve().is_relative_to(source.tree.resolve()):
            continue
        try:
            record = json.loads(candidate.read_text(encoding="utf-8"))
            installed_python = candidate.parent / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            if (record.get("source_fingerprint") == source.metadata["source_fingerprint"]
                    and record.get("base_python") == base_identity):
                body = probe_core(installed_python, data)
                verify_core_install(source, installed_python, body)
                return installed_python, body
        except (HostInstallError, OSError, ValueError):
            continue
    if runtime.exists():
        runtime = source.tree / f".runtime-{uuid4().hex[:8]}"
        python = runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        marker = runtime / "toolseed-runtime.json"
    uv = os.environ.get("TOOLSEED_UV") or shutil.which("uv")
    command = [base_python, "-I", "-m", "venv"]
    if uv:
        command.append("--without-pip")
    run([*command, str(runtime)], timeout=180)
    if uv:
        install = [uv, "pip", "install", "--python", str(python), str(source.tree)]
        if offline:
            install.append("--offline")
    else:
        install = [str(python), "-I", "-m", "pip", "install", "--disable-pip-version-check", str(source.tree)]
        if offline:
            install.append("--no-index")
    run(install, timeout=600)
    body = probe_core(python, data)
    verify_core_install(source, python, body)
    marker.write_text(json.dumps({"source_fingerprint": source.metadata["source_fingerprint"],
                                   "base_python": base_identity, "python": str(python)}), encoding="utf-8")
    return python, body


def verify_core_install(source: UpdateSource, python: Path, body: dict) -> None:
    module = Path(body.get("module_path", "")).resolve()
    if not module.is_relative_to(python.parent.parent.resolve()):
        raise HostInstallError("CORE_NOT_ISOLATED", "目标 Core 未从独立运行环境加载。")
    if body.get("core_version") != source.metadata["version"]:
        raise HostInstallError("CORE_VERSION_MISMATCH", "安装的 Core 与目标源码版本不一致。")
    package = source.tree / "toolseed"
    for path in package.rglob("*"):
        if path.is_file() and path.suffix in {".py", ".md", ".js", ".css", ".html"}:
            installed = module.parent / path.relative_to(package)
            if not installed.is_file() or installed.read_bytes() != path.read_bytes():
                raise HostInstallError("CORE_SOURCE_MISMATCH", "独立环境中的 Core 与固定源码不一致。")


MIGRATE_SCRIPT = """
import json, pathlib, sys
from toolseed.core.storage import Store, MIGRATIONS
root = pathlib.Path(sys.argv[1])
if not (root / 'toolseed.sqlite3').is_file():
    raise SystemExit('Refusing to initialize a missing library during update')
store = Store(root)
assert store.schema_version == max(MIGRATIONS)
store.close()
print(json.dumps({'ok': True}))
"""


def migrate(python: Path, data: Path) -> None:
    run([str(python), "-I", "-B", "-X", "utf8", "-c", MIGRATE_SCRIPT, str(data)], timeout=60)


def backup_and_check_database(python: Path, data: Path, backup: Path, schema: int) -> dict:
    database = data / "toolseed.sqlite3"
    if not database.exists():
        return {"state": "uninitialized", "changed": False}
    backup.mkdir(parents=True, exist_ok=True, mode=0o700)
    original = backup / "original.sqlite3"
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        current = connection.execute("PRAGMA user_version").fetchone()[0]
        if current > schema:
            raise HostInstallError("DATABASE_DOWNGRADE_REFUSED", "能力库比目标 Core 更新，拒绝降级。")
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise HostInstallError("DATABASE_INVALID", "能力库完整性检查失败。")
        with closing(sqlite3.connect(original)) as target:
            connection.backup(target)
    if os.name != "nt":
        original.chmod(0o600)
    trial = backup / "trial"
    trial.mkdir()
    shutil.copy2(original, trial / "toolseed.sqlite3")
    migrate(python, trial)
    return {"state": "validated", "schema_before": current, "schema_after": schema,
            "backup": str(original), "migration_needed": current != schema, "changed": False}
