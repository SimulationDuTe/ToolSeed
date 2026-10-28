"""Unified install / status / update / uninstall for ToolSeed host adapters.

This module never reimplements a host installer. It resolves a pinned source
tree, then invokes the adapter installers that already ship in this repository
(``integrations/codex/src/install.mjs`` and ``integrations/dsh/install.ps1``)
and records what was deployed in a manifest next to the installed tree.

Core, the schema and the public MCP tools are untouched: hosts are
configured around the existing ``toolseed-mcp`` entry point.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

from .hosts import (
    HOSTS,
    MANIFEST_NAME,
    HostInstallError,
    active_install,
    fetch_local_tree,
    fetch_tree,
    fingerprint_tree,
    install_root,
    installed_versions,
    local_resolution,
    project_version,
    prune_staging,
    read_manifest,
    read_pointer,
    remove_tree,
    resolve_ref,
    utc_now,
    write_manifest,
    write_pointer,
)

CODEX_PACKAGE = "dsh-toolseed"
DSH_SKILL_MARKER = "# BEGIN TOOLSEED PANEL"
CODEX_AGENTS_BEGIN = "<!-- toolseed-codex:begin -->"


# ---------------------------------------------------------------- utilities


def _run(command: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise HostInstallError(
            "TOOL_MISSING", f"找不到可执行文件：{command[0]}", detail=str(exc)
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise HostInstallError(
            "TIMEOUT", f"命令超时：{command[0]}", detail=f"{timeout}s"
        ) from exc


def _node_path() -> str:
    explicit = os.environ.get("TOOLSEED_NODE")
    if explicit:
        return explicit
    found = shutil.which("node")
    if not found:
        raise HostInstallError(
            "NODE_MISSING",
            "找不到 Node.js。Codex hook 与 app-server 检查需要 Node.js 22+。",
            detail="设置 TOOLSEED_NODE 或把 node 加入 PATH。",
        )
    return found


def _powershell() -> str:
    for name in ("pwsh", "powershell"):
        found = shutil.which(name)
        if found:
            return found
    raise HostInstallError("POWERSHELL_MISSING", "找不到 PowerShell，无法安装 DSH 插件。")


def _codex_home(explicit: str | None) -> Path:
    value = explicit or os.environ.get("CODEX_HOME")
    return Path(value).expanduser().resolve() if value else (Path.home() / ".codex").resolve()


def _dsh_home(explicit: str | None) -> Path:
    value = explicit or os.environ.get("DSH_HOME")
    return Path(value).expanduser().resolve() if value else (Path.home() / ".dsh").resolve()


def _data_dir(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("TOOLSEED_DATA_DIR")
    return Path(env).expanduser().resolve() if env else (Path.home() / ".toolseed").resolve()


def _tree_host_dir(tree: Path, host: str) -> Path:
    return tree / "integrations" / host


def _require_tree(tree: Path, host: str) -> Path:
    host_dir = _tree_host_dir(tree, host)
    if not host_dir.is_dir():
        raise HostInstallError(
            "ADAPTER_MISSING",
            f"该版本不包含 {host} 适配层：{host_dir}",
            detail="请选择包含该适配层的版本或 commit。",
        )
    return host_dir


def _version_dir(root: Path, host: str, label: str) -> Path:
    base = root / host / label
    candidate = base
    index = 1
    while candidate.exists():
        candidate = base.with_name(f"{label}-{index}")
        index += 1
    return candidate


def _reusable_tree(root: Path, host: str, commit_sha: str,
                   fingerprint: str | None = None) -> Path | None:
    """An already-fetched tree for this commit, so reinstalls stay idempotent."""
    for directory in installed_versions(root, host):
        manifest = read_manifest(directory)
        if manifest.get("commit_sha") != commit_sha or not directory.is_dir():
            continue
        if fingerprint is not None and manifest.get("source_fingerprint") != fingerprint:
            continue
        return directory
    return None


def _executable_identity(command: str) -> str:
    resolved = shutil.which(command)
    if resolved or Path(command).is_absolute() or Path(command).parent != Path("."):
        return os.path.normcase(str(Path(resolved or command).expanduser().resolve()))
    return command


def _runtime_config(host: str, *, data: Path, python: str, codex_home: str | None,
                    dsh_home: str | None, mcp_server: str, dsh_command: str,
                    cwd: Path | None) -> dict[str, str]:
    common = {"data_dir": os.path.normcase(str(data)), "python": _executable_identity(python)}
    if host == "codex":
        return {**common, "codex_home": os.path.normcase(str(_codex_home(codex_home))),
                "mcp_server": mcp_server, "node": _executable_identity(_node_path()),
                "cwd": os.path.normcase(str((cwd or Path.cwd()).resolve()))}
    return {**common, "dsh_home": os.path.normcase(str(_dsh_home(dsh_home))),
            "dsh_command": _executable_identity(dsh_command)}


# ------------------------------------------------------------- host actions


def codex_verify_command(tree: Path, *, codex_home: Path, data_dir: Path,
                         mcp_server: str, cwd: Path | None = None) -> list[str]:
    host_dir = _require_tree(tree, "codex")
    return [
        _node_path(),
        str(host_dir / "src" / "verify.mjs"),
        "--codex-home", str(codex_home),
        "--data-dir", str(data_dir),
        "--mcp-server", mcp_server,
        "--python", sys.executable,
        "--json",
    ] + (["--cwd", str(cwd)] if cwd else [])


def _install_codex(tree: Path, *, codex_home: Path, data_dir: Path, mcp_server: str,
                   cwd: Path | None, dry_run: bool, python: str | None = None) -> dict[str, Any]:
    host_dir = _require_tree(tree, "codex")
    command = [
        _node_path(), str(host_dir / "src" / "install.mjs"),
        "--codex-home", str(codex_home),
        "--data-dir", str(data_dir),
        "--mcp-server", mcp_server,
        "--node", _node_path(),
        "--python", python or sys.executable,
        "--skill-source", str(tree / "toolseed" / "skill" / "SKILL.md"),
        "--hook-script", str(host_dir / "src" / "toolseed-hook.mjs"),
        "--json",
    ]
    if cwd:
        command += ["--cwd", str(cwd)]
    if not dry_run:
        command.append("--apply")
    result = _run(command)
    if result.returncode not in (0, 1):
        raise HostInstallError(
            "CODEX_INSTALL_FAILED",
            f"Codex 安装器失败（退出码 {result.returncode}）。",
            detail=(result.stderr or result.stdout).strip()[:2000],
        )
    try:
        payload = json.loads(result.stdout)
    except ValueError as exc:
        raise HostInstallError(
            "CODEX_INSTALL_FAILED", "Codex 安装器未返回可解析结果。",
            detail=(result.stderr or result.stdout).strip()[:2000],
        ) from exc
    payload["_exit_code"] = result.returncode
    return payload


def _install_dsh(tree: Path, *, dsh_home: Path, data_dir: Path, python: str,
                 dsh_command: str, dry_run: bool, isolated: bool = False) -> dict[str, Any]:
    host_dir = _require_tree(tree, "dsh")
    script = host_dir / "install.ps1"
    if not script.is_file():
        raise HostInstallError("ADAPTER_MISSING", f"缺少 DSH 安装脚本：{script}")
    command = [
        _powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", str(script),
        "-Python", python,
        "-DataDir", str(data_dir),
        "-DshCommand", dsh_command,
        "-DshHome", str(dsh_home),
        "-PluginDir", str(host_dir),
        "-Json",
    ]
    if dry_run:
        command.append("-DryRun")
    # Only an isolated DSH home may be written while the desktop app is running;
    # the live default profile always requires a full quit.
    if isolated and _dsh_home(None) != dsh_home:
        command.append("-SkipRunningCheck")
    result = _run(command, timeout=600)
    if result.returncode != 0:
        raise HostInstallError(
            "DSH_INSTALL_FAILED",
            f"DSH 安装器失败（退出码 {result.returncode}）。",
            detail=(result.stderr or result.stdout).strip()[:2000],
        )
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise HostInstallError(
            "DSH_INSTALL_FAILED", "DSH 安装器未返回可解析结果。",
            detail=(result.stderr or result.stdout).strip()[:2000],
        ) from exc


# ------------------------------------------------------------ public actions


def install_host(
    host: str,
    *,
    ref: str,
    root: Path | None = None,
    data_dir: str | None = None,
    codex_home: str | None = None,
    dsh_home: str | None = None,
    mcp_server: str = "toolseed",
    python: str | None = None,
    dsh_command: str = "dsh",
    cwd: Path | None = None,
    repo: str | None = None,
    update: bool = False,
    repair: bool = False,
) -> dict[str, Any]:
    """Fetch a pinned tree, run the real installer, then activate it."""
    if host not in HOSTS:
        raise HostInstallError("UNKNOWN_HOST", f"未知宿主：{host}")
    root = root or install_root()
    data = _data_dir(data_dir)
    python = python or sys.executable
    runtime = _runtime_config(host, data=data, python=python, codex_home=codex_home,
                              dsh_home=dsh_home, mcp_server=mcp_server,
                              dsh_command=dsh_command, cwd=cwd)
    stale = prune_staging(root, host)
    # Only an explicitly supplied, non-default DSH home counts as isolated.
    isolated_home = bool(dsh_home) and _dsh_home(dsh_home) != _dsh_home(None)

    local_source = Path(ref).expanduser()
    is_local = local_source.is_dir() and (local_source / "integrations").is_dir()
    if is_local:
        head = _run(["git", "-C", str(local_source), "rev-parse", "HEAD"])
        sha = head.stdout.strip() if head.returncode == 0 else None
        dirty = _run(["git", "-C", str(local_source), "status", "--porcelain"])
        fingerprint = fingerprint_tree(local_source)
        resolution = local_resolution(local_source, sha)
        local_state = {
            "source": "local-directory",
            "commit": sha,
            "dirty": bool(dirty.stdout.strip()),
            "fingerprint": fingerprint,
        }
        resolution.release_tag = None
        suffix = "-dirty-" + fingerprint[:8] if local_state["dirty"] else ""
        resolution.label = (
            f"local-{sha[:12]}{suffix}" if sha else f"local-{fingerprint[:12]}"
        )
    else:
        resolution = resolve_ref(ref, repo=repo)
        local_state = None
        fingerprint = None
    previous = active_install(root, host)

    # Source identity alone does not describe a deployment. Legacy manifests
    # without runtime identity are reconciled once; --repair fixes file drift.
    if previous and previous.manifest.get("commit_sha") == resolution.commit_sha:
        same_content = (
            previous.manifest.get("source_fingerprint") == fingerprint
            if is_local else True
        )
        if same_content and previous.manifest.get("runtime_config") == runtime and not repair:
            return {
                "ok": True, "host": host, "changed": False,
                "reason": "already-installed", "install": previous.manifest,
                "directory": str(previous.directory),
                "stale_staging": stale,
            }

    reused = _reusable_tree(
        root, host, resolution.commit_sha,
        fingerprint if is_local else None,
    )
    if reused is not None:
        target = reused
    else:
        target = _version_dir(root, host, resolution.label)
        if is_local:
            fetch_local_tree(local_source, target)
        else:
            fetch_tree(resolution, target, repo=repo)
    manifest: dict[str, Any] = {
        "host": host,
        "version": project_version(target),
        "commit_sha": resolution.commit_sha,
        "ref": resolution.ref,
        "ref_kind": resolution.kind,
        "stable": resolution.stable,
        "prerelease": not resolution.stable,
        "release_tag": resolution.release_tag,
        "source": (
            f"local:{local_source}" if is_local
            else f"https://codeload.github.com/{repo or os.environ.get('TOOLSEED_REPO') or 'SimulationDuTe/ToolSeed'}/tar.gz/{resolution.commit_sha}"
        ),
        "local_source": local_state,
        "source_fingerprint": fingerprint,
        "runtime_config": runtime,
        "data_dir": str(data),
        "mcp_server": mcp_server,
        "directory": str(target),
        "status": "fetched",
    }
    try:
        dry = (
            _install_codex(target, codex_home=_codex_home(codex_home), data_dir=data,
                           mcp_server=mcp_server, cwd=cwd, dry_run=True, python=python)
            if host == "codex"
            else _install_dsh(target, dsh_home=_dsh_home(dsh_home), data_dir=data,
                              python=python, dsh_command=dsh_command, dry_run=True,
                              isolated=isolated_home)
        )
        if host == "codex" and dry.get("checks", {}).get("mcp_runtime") is not True:
            raise HostInstallError("MCP_NOT_READY", "Codex MCP 运行环境未通过只读探测。",
                                   detail=json.dumps(dry.get("runtime"), ensure_ascii=False))
        manifest["preflight"] = {"ok": True, "detail": dry}
        applied = (
            _install_codex(target, codex_home=_codex_home(codex_home), data_dir=data,
                           mcp_server=mcp_server, cwd=cwd, dry_run=False, python=python)
            if host == "codex"
            else _install_dsh(target, dsh_home=_dsh_home(dsh_home), data_dir=data,
                              python=python, dsh_command=dsh_command, dry_run=False,
                              isolated=isolated_home)
        )
        if host == "codex" and (applied.get("_exit_code") == 1 or applied.get("ready") is not True):
            raise HostInstallError(
                "VERIFY_FAILED", "Codex 适配层未就绪；检查 MCP 运行环境、Hook 信任及 Skill。",
                detail=json.dumps(applied.get("error") or applied.get("trust"), ensure_ascii=False),
            )
        manifest["status"] = "active"
    except HostInstallError as exc:
        manifest.update({"status": "failed", "error": {"code": exc.code, "message": exc.message,
                                                       "detail": exc.detail}})
        # Reconfiguring the active source reuses its tree. A failed attempt must
        # not replace the last successful deployment record on that tree.
        if previous is None or target != previous.directory:
            write_manifest(target, manifest)
        if previous is not None:
            # Nothing was activated yet: the previous pointer is still in place.
            return {
                "ok": False, "host": host, "changed": False,
                "error": manifest["error"], "rolled_back": False,
                "previous_active_preserved": True,
                "install": previous.manifest, "directory": str(previous.directory),
                "failed_directory": str(target),
            }
        return {"ok": False, "host": host, "changed": False, "error": manifest["error"],
                "failed_directory": str(target)}

    write_manifest(target, manifest)
    write_pointer(root / host, {
        "host": host, "directory": str(target), "commit_sha": resolution.commit_sha,
        "version": manifest["version"], "activated_at": utc_now(),
        "previous": str(previous.directory) if previous and previous.directory != target else None,
    })
    return {
        "ok": True, "host": host, "changed": True, "install": manifest,
        "directory": str(target),
        "previous": str(previous.directory) if previous else None,
        "installer": applied,
    }


def uninstall_host(host: str, *, root: Path | None = None, purge: bool = False,
                   data_dir: str | None = None, codex_home: str | None = None,
                   dsh_home: str | None = None) -> dict[str, Any]:
    if host not in HOSTS:
        raise HostInstallError("UNKNOWN_HOST", f"未知宿主：{host}")
    root = root or install_root()
    active = active_install(root, host)
    if host == "codex":
        tree = active.directory if active else None
        if tree is None:
            raise HostInstallError("NOT_INSTALLED", "没有已激活的 Codex 适配层。")
        host_dir = _require_tree(tree, "codex")
        command = [_node_path(), str(host_dir / "src" / "install.mjs"), "--uninstall",
                   "--apply", "--json", "--codex-home", str(_codex_home(codex_home))]
        result = _run(command)
        if result.returncode != 0:
            raise HostInstallError("CODEX_UNINSTALL_FAILED", "Codex 卸载器失败。",
                                   detail=(result.stderr or result.stdout).strip()[:2000])
        removed = json.loads(result.stdout)
    else:
        profile = _dsh_home(dsh_home) / "profiles" / "desktop"
        patch = profile / "cordis.patch.yml"
        patch_has_block = False
        if patch.is_file():
            try:
                patch_has_block = DSH_SKILL_MARKER in patch.read_text(encoding="utf-8")
            except OSError:
                patch_has_block = False
        if active is None and not patch_has_block:
            raise HostInstallError("NOT_INSTALLED", "没有已激活的 DSH 适配层。")
        removed = _uninstall_dsh(dsh_home=_dsh_home(dsh_home))

    pointer = read_pointer(root / host)
    if purge:
        for directory in installed_versions(root, host):
            remove_tree(directory)
        remove_tree(root / host)
    else:
        pointer_path = root / host / "current.json"
        if pointer_path.exists():
            pointer_path.unlink()
    return {
        "ok": True, "host": host, "removed": removed, "purged": purge,
        "preserved": "capability database and user configuration",
        "data_dir": str(_data_dir(data_dir)),
        "previous_install": pointer.get("directory"),
    }


def _uninstall_dsh(*, dsh_home: Path) -> dict[str, Any]:
    profile = dsh_home / "profiles" / "desktop"
    patch = profile / "cordis.patch.yml"
    package = profile / "package.json"
    changes: dict[str, Any] = {"patch": False, "package": False, "plugin": None}
    if patch.is_file():
        text = patch.read_text(encoding="utf-8")
        pattern = r"(?ms)^# BEGIN TOOLSEED PANEL\r?\n.*?^# END TOOLSEED PANEL\r?\n?"
        import re

        cleaned = re.sub(pattern, "", text)
        if cleaned != text:
            backup = patch.with_name(patch.name + ".toolseed-backup-" + utc_now().replace(":", ""))
            shutil.copy2(patch, backup)
            patch.write_text(cleaned.rstrip() + "\n", encoding="utf-8")
            changes["patch"] = True
            changes["patch_backup"] = str(backup)
    if package.is_file():
        try:
            data = json.loads(package.read_text(encoding="utf-8"))
        except ValueError:
            data = None
        deps = (data or {}).get("dependencies") or {}
        if CODEX_PACKAGE in deps:
            changes["plugin"] = deps[CODEX_PACKAGE]
            changes["note"] = (
                "Remove the plugin with the official command: "
                f"dsh plugin --profile desktop remove {CODEX_PACKAGE}"
            )
    return changes


# --------------------------------------------------------------- status view


def _schema_state(database: Path) -> dict[str, Any]:
    if not database.is_file():
        return {"state": "absent", "schema": None, "detail": "未创建；MCP 首次使用时会建立"}
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            version = connection.execute("PRAGMA user_version").fetchone()
            tables = connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        return {"state": "error", "schema": None, "detail": str(exc)}
    return {"state": "ok", "schema": version[0] if version else None,
            "tables": tables[0] if tables else 0}


def codex_status(*, tree: Path | None, codex_home: Path, data_dir: Path,
                 mcp_server: str, deep: bool = False) -> dict[str, Any]:
    skill = codex_home / "skills" / "toolseed" / "SKILL.md"
    hooks_path = codex_home / "hooks.json"
    agents = codex_home / "AGENTS.md"
    config = codex_home / "config.toml"
    hook_present = False
    if hooks_path.is_file():
        try:
            text = hooks_path.read_text(encoding="utf-8")
            hook_present = "toolseed-hook.mjs" in text
        except OSError:
            hook_present = False
    agents_ok = False
    if agents.is_file():
        try:
            agents_ok = CODEX_AGENTS_BEGIN in agents.read_text(encoding="utf-8")
        except OSError:
            agents_ok = False
    mcp_ok = False
    if config.is_file():
        try:
            mcp_ok = f"[mcp_servers.{mcp_server}]" in config.read_text(encoding="utf-8")
        except OSError:
            mcp_ok = False

    checks: list[dict[str, Any]] = [
        {"id": "skill", "state": "ok" if skill.is_file() else "missing",
         "detail": str(skill)},
        {"id": "hook", "state": "ok" if hook_present else "missing", "detail": str(hooks_path)},
        {"id": "agents_md", "state": "ok" if agents_ok else "missing", "detail": str(agents)},
        {"id": "mcp_config", "state": "ok" if mcp_ok else "missing",
         "detail": f"[mcp_servers.{mcp_server}]"},
        {"id": "capability_db", **_schema_state(data_dir / "toolseed.sqlite3")},
    ]
    host_check: dict[str, Any] = {
        "state": "unknown",
        "detail": "未执行 app-server 检查（加 --deep 可验证 hooks/list 与 skills/list；该检查会启动 Codex 并可能初始化其状态）",
    }
    if tree is not None and deep:
        try:
            command = codex_verify_command(tree, codex_home=codex_home, data_dir=data_dir,
                                          mcp_server=mcp_server)
            result = _run(command, timeout=180)
            payload = json.loads(result.stdout) if result.stdout.strip() else {}
            host_check = {
                "state": "ok" if payload.get("ok") else "error",
                "codex_version": payload.get("version"),
                "detail": "hooks/list + skills/list",
                "checks": {
                    item["id"]: item["ok"] for item in payload.get("checks", [])
                },
            }
        except (HostInstallError, ValueError) as exc:
            host_check = {"state": "unknown", "detail": str(exc)}
    return {"installed": tree is not None, "checks": checks, "host_verification": host_check}


def dsh_status(*, tree: Path | None, dsh_home: Path, data_dir: Path) -> dict[str, Any]:
    profile = dsh_home / "profiles" / "desktop"
    patch = profile / "cordis.patch.yml"
    package = profile / "package.json"
    patch_ok = False
    if patch.is_file():
        try:
            patch_ok = DSH_SKILL_MARKER in patch.read_text(encoding="utf-8")
        except OSError:
            patch_ok = False
    plugin_version = None
    if package.is_file():
        try:
            deps = (json.loads(package.read_text(encoding="utf-8")).get("dependencies") or {})
            plugin_version = deps.get(CODEX_PACKAGE)
        except ValueError:
            plugin_version = None
    checks = [
        {"id": "profile", "state": "ok" if profile.is_dir() else "missing",
         "detail": str(profile)},
        {"id": "plugin_registered", "state": "ok" if plugin_version else "missing",
         "detail": str(plugin_version) if plugin_version else CODEX_PACKAGE},
        {"id": "panel_config", "state": "ok" if patch_ok else "missing", "detail": str(patch)},
        {"id": "capability_db", **_schema_state(data_dir / "toolseed.sqlite3")},
        {"id": "dsh_running", "state": "unknown",
         "detail": "面板查询依赖已运行的 DSH；配置存在不等于面板已加载"},
    ]
    return {"installed": tree is not None, "checks": checks}


def host_status(*, root: Path | None = None, data_dir: str | None = None,
                codex_home: str | None = None, dsh_home: str | None = None,
                mcp_server: str = "toolseed", deep: bool = False) -> dict[str, Any]:
    root = root or install_root()
    data = _data_dir(data_dir)
    report: dict[str, Any] = {"install_root": str(root), "data_dir": str(data),
                              "mcp_server": mcp_server, "hosts": {}}
    active = {host: active_install(root, host) for host in HOSTS}
    for host in HOSTS:
        record = active[host]
        entry: dict[str, Any] = {
            "installed": record is not None,
            "version": record.manifest.get("version") if record else None,
            "commit_sha": record.manifest.get("commit_sha") if record else None,
            "prerelease": record.manifest.get("prerelease") if record else None,
            "directory": str(record.directory) if record else None,
            "recorded": bool(record and (record.directory / MANIFEST_NAME).is_file()),
        }
        if host == "codex":
            entry.update(codex_status(tree=record.directory if record else None,
                                      codex_home=_codex_home(codex_home),
                                      data_dir=data, mcp_server=mcp_server, deep=deep))
        else:
            entry.update(dsh_status(tree=record.directory if record else None,
                                    dsh_home=_dsh_home(dsh_home), data_dir=data))
        # "installed" means managed by this installer. An existing dev-checkout
        # deployment is real but unmanaged, and must not read as "not installed".
        entry["managed"] = bool(entry.get("recorded"))
        entry["configured"] = any(
            check.get("state") == "ok" for check in entry.get("checks", [])
        )
        report["hosts"][host] = entry
    return report
