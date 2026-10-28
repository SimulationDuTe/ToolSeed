"""Complete, pinned host upgrades: Core, Skill, MCP binding and native adapter."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from .hosts import HOSTS, HostInstallError, active_install, install_root, read_pointer, utc_now
from .hosts_cli import (
    _codex_home,
    _dsh_home,
    _install_codex,
    _install_dsh,
    _powershell,
    _runtime_config,
    codex_verify_command,
)
from .update_config import HostConfiguration, load_configuration
from .update_files import FileJournal
from .update_runtime import (
    UpdateSource,
    acquire_source,
    backup_and_check_database,
    migrate,
    prepare_core,
    probe_core,
    run,
    verify_core_install,
)


@contextmanager
def update_lock(root: Path, host: str) -> Iterator[None]:
    directory = root / host
    directory.mkdir(parents=True, exist_ok=True)
    lock = directory / ".update.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise HostInstallError("UPDATE_IN_PROGRESS", "该宿主已有升级任务；异常退出后请确认进程已结束再移除 .update.lock。") from exc
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        lock.unlink(missing_ok=True)


def check_dsh_closed() -> None:
    if os.name == "nt":
        result = run([_powershell(), "-NoProfile", "-NonInteractive", "-Command",
                      "[bool](Get-Process -Name 'DeepSeek Harness' -ErrorAction SilentlyContinue)"])
        if result.stdout.strip().lower() == "true":
            raise HostInstallError("DSH_RUNNING", "请完全退出 DSH Desktop 后再运行同一 update 命令。")


def verify_host(tree: Path, config: HostConfiguration, python: Path, cwd: Path) -> dict:
    expected_skill = (tree / "toolseed/skill/SKILL.md").read_bytes()
    skill = config.home / "skills/toolseed/SKILL.md"
    if not skill.is_file() or skill.read_bytes() != expected_skill:
        raise HostInstallError("SKILL_NOT_CURRENT", "宿主 ToolSeed Skill 未同步到目标版本。")
    actual = load_configuration(config.host, config.home, cwd, config.server_name, str(config.data), None)
    if str(python) not in [actual.server.get("command"), *actual.server.get("args", [])]:
        raise HostInstallError("MCP_RUNTIME_MISMATCH", "宿主实际 MCP 未指向新 Core。")
    core = probe_core(python, config.data)
    import tomllib

    metadata = tomllib.loads((tree / "pyproject.toml").read_text(encoding="utf-8"))
    verify_core_install(UpdateSource(tree, {"version": metadata["project"]["version"]}), python, core)
    if config.host == "codex":
        response = run(codex_verify_command(tree, codex_home=config.home, data_dir=config.data,
                                            mcp_server=config.server_name, cwd=cwd), timeout=180)
        result = json.loads(response.stdout)
        if result.get("ready") is not True:
            raise HostInstallError("VERIFY_FAILED", "Codex 原生 Hook、Skill 或实际 MCP 未就绪。")
        return {"ready": True, "codex_version": result.get("version"), "activation": "new_chat_required"}
    plugin = tree / "integrations/dsh"
    package = json.loads((plugin / "package.json").read_text(encoding="utf-8"))
    installed = config.home / "profiles/desktop/node_modules/dsh-toolseed"
    for relative in ["package.json", *package["files"]]:
        expected = (plugin / relative).resolve()
        target = (installed / relative).resolve()
        if not expected.is_relative_to(plugin.resolve()) or not target.is_relative_to(installed.resolve()):
            raise HostInstallError("INVALID_PACKAGE", "DSH 包文件越过插件目录。")
        if not target.is_file() or target.read_bytes() != expected.read_bytes():
            raise HostInstallError("VERIFY_FAILED", f"DSH 实际安装文件不匹配：{relative}")
    return {"ready": True, "installed_artifacts_match": True, "activation": "open_dsh_required"}


def _restore_dsh(config: HostConfiguration, command: str, old_spec: str | None) -> bool:
    try:
        env = {**os.environ, "DSH_HOME": str(config.home)}
        operation = ["add", old_spec] if old_spec else ["remove", "dsh-toolseed"]
        run([command, "plugin", "--profile", "desktop", *operation], env=env, timeout=600)
        return True
    except HostInstallError:
        return False


def _update(host: str, *, root: Path, ref: str, repo: str | None, data_dir: str | None,
            codex_home: str | None, dsh_home: str | None, mcp_server: str | None,
            python: str | None, dsh_command: str | None, cwd: Path, repair: bool,
            offline: bool, plan: bool) -> dict[str, Any]:
    previous = active_install(root, host)
    record = previous.manifest if previous else {}
    prior_runtime = record.get("runtime_config", {})
    home = (_codex_home(codex_home or prior_runtime.get("codex_home")) if host == "codex" else
            _dsh_home(dsh_home or prior_runtime.get("dsh_home")))
    server = mcp_server or record.get("mcp_server") or "toolseed"
    config = load_configuration(host, home, cwd, server, data_dir, record.get("data_dir"))
    if host == "dsh" and not plan:
        check_dsh_closed()
    source = acquire_source(root, host, ref, repo)
    if plan:
        return {"ok": True, "action": "update", "host": host, "changed": False, "plan": True,
                "source": source.metadata, "directory": str(source.tree), "data_dir": str(config.data),
                "home": str(home), "mcp_config": str(config.path),
                "steps": ["check_permissions", "install_isolated_core", "probe_core", "trial_migration",
                          "sync_mcp_skill_adapter", "native_verification", "migrate_existing_db", "activate"]}

    # Healthy repeated updates do no package/config writes. Source is always resolved
    # once first, so a branch moving to a new commit cannot hit this path.
    recorded_python = record.get("core", {}).get("python")
    if (record.get("full_update") and not repair and recorded_python
            and record.get("commit_sha") == source.metadata["commit_sha"]
            and record.get("directory") == str(source.tree)
            and record.get("source_fingerprint") == source.metadata["source_fingerprint"]
            and record.get("runtime_config", {}).get("cwd", os.path.normcase(str(cwd))) == os.path.normcase(str(cwd))
            and (not python or record.get("core", {}).get("base_python") == os.path.normcase(str(Path(python).resolve())))
            and (not dsh_command or prior_runtime.get("dsh_command") == os.path.normcase(str(Path(dsh_command).resolve())))
            and record.get("data_dir") == str(config.data)
            and record.get("mcp_server") == server
            and prior_runtime.get(f"{host}_home") == os.path.normcase(str(home))):
        try:
            verified = verify_host(source.tree, config, Path(recorded_python), cwd)
            return {"ok": True, "action": "update", "host": host, "changed": False,
                    "reason": "already-current", "install": record, "directory": str(source.tree),
                    "verification": verified}
        except (HostInstallError, OSError, ValueError):
            pass

    backup = root / host / "backups" / uuid4().hex
    journal = FileJournal(backup)
    for path in [*config.watched_files(), root / host / "current.json", source.tree / "install.json"]:
        journal.watch(path)
    # Permissions fail before Core installation, config edits or any migration.
    journal.preflight()
    database: dict[str, Any] = {"state": "not_checked", "changed": False}
    plugin_attempted = False
    old_spec = None
    dsh_cmd = dsh_command or prior_runtime.get("dsh_command") or "dsh"
    try:
        base_python = python or sys.executable
        core_python, core_probe = prepare_core(source, base_python, config.data, offline=offline)
        database = backup_and_check_database(core_python, config.data, backup / "database",
                                             core_probe["schema_version"])
        if host == "dsh":
            package = json.loads((home / "profiles/desktop/package.json").read_text(encoding="utf-8"))
            old_spec = package.get("dependencies", {}).get("dsh-toolseed")
        config.write_runtime(journal, core_python)
        try:
            if host == "codex":
                dry = _install_codex(source.tree, codex_home=home, data_dir=config.data,
                    mcp_server=server, cwd=cwd, dry_run=True, python=str(core_python))
                if dry.get("checks", {}).get("mcp_runtime") is not True:
                    raise HostInstallError("MCP_NOT_READY", "新 MCP 配置未通过宿主只读探测。")
                applied = _install_codex(source.tree, codex_home=home, data_dir=config.data,
                    mcp_server=server, cwd=cwd, dry_run=False, python=str(core_python))
                if applied.get("ready") is not True or applied.get("_exit_code", 0) != 0:
                    raise HostInstallError("VERIFY_FAILED", "Codex 适配层未通过原生就绪检查。")
            else:
                plugin_attempted = True
                applied = _install_dsh(source.tree, dsh_home=home, data_dir=config.data,
                    python=str(core_python), dsh_command=dsh_cmd, dry_run=False)
                if applied.get("ok") is not True or applied.get("installed") is not True:
                    raise HostInstallError("VERIFY_FAILED", "DSH 官方安装器未确认插件安装。")
        finally:
            journal.accept()
        skill = home / "skills/toolseed/SKILL.md"
        journal.write(skill, (source.tree / "toolseed/skill/SKILL.md").read_bytes())
        verification = verify_host(source.tree, config, core_python, cwd)
        if database.get("migration_needed"):
            migrate(core_python, config.data)
            database["changed"] = True
        runtime = _runtime_config(host, data=config.data, python=str(core_python),
            codex_home=str(home) if host == "codex" else None,
            dsh_home=str(home) if host == "dsh" else None, mcp_server=server, dsh_command=dsh_cmd, cwd=cwd)
        manifest = {**source.metadata, "schema": 1, "host": host, "status": "active", "full_update": True,
            "installed_at": utc_now(), "directory": str(source.tree), "data_dir": str(config.data),
            "mcp_server": server, "runtime_config": runtime, "core": {"python": str(core_python),
            "version": core_probe["core_version"], "schema": core_probe["schema_version"],
            "base_python": os.path.normcase(str(Path(base_python).resolve()))},
            "verification": verification, "database": database, "backup": str(backup)}
        journal.write(source.tree / "install.json", (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode())
        old_pointer = read_pointer(root / host)
        pointer = {"host": host, "directory": str(source.tree), "commit_sha": manifest["commit_sha"],
                   "version": manifest["version"], "activated_at": utc_now(), "previous":
                   old_pointer.get("directory") if old_pointer.get("directory") != str(source.tree) else old_pointer.get("previous")}
        journal.write(root / host / "current.json", (json.dumps(pointer, indent=2) + "\n").encode())
        return {"ok": True, "action": "update", "host": host, "changed": True, "install": manifest,
                "directory": str(source.tree), "previous": str(previous.directory) if previous else None,
                "verification": verification, "database": database}
    except (HostInstallError, OSError, ValueError, sqlite3.Error) as exc:
        plugin_restored = _restore_dsh(config, dsh_cmd, old_spec) if plugin_attempted else True
        # Official rollback may modify package/lock files: accept only its final
        # native state before restoring the exact original configuration bytes.
        if plugin_attempted:
            journal.accept()
        rollback = journal.rollback()
        if database.get("migration_needed"):
            try:
                with closing(sqlite3.connect((config.data / "toolseed.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
                    database["changed"] = db.execute("PRAGMA user_version").fetchone()[0] != database["schema_before"]
            except sqlite3.Error:
                database["changed"] = "unknown"
        error = {"code": exc.code, "message": exc.message, "detail": exc.detail} if isinstance(exc, HostInstallError) else {
            "code": "UPDATE_FAILED", "message": "完整升级失败。", "detail": str(exc)}
        return {"ok": False, "action": "update", "host": host, "changed": False, "error": error,
            "previous_active_preserved": bool(previous), "rolled_back": rollback["ok"] and plugin_restored and not database["changed"],
            "configuration_rollback": rollback, "dsh_package_restored": plugin_restored,
            "database": database, "failed_directory": str(source.tree),
            "recovery": "重试同一 update 命令；新运行环境作为缓存保留，能力库不自动倒回备份。"}


def update_host(host: str, *, ref: str, root: Path | None = None, repo: str | None = None,
                data_dir: str | None = None, codex_home: str | None = None,
                dsh_home: str | None = None, mcp_server: str | None = None,
                python: str | None = None, dsh_command: str | None = None,
                cwd: Path | None = None, repair: bool = False, offline: bool = False,
                plan: bool = False) -> dict[str, Any]:
    if host not in HOSTS:
        raise HostInstallError("UNKNOWN_HOST", f"未知宿主：{host}")
    selected_root = (root or install_root()).expanduser().resolve()
    previous = active_install(selected_root, host)
    recorded_cwd = previous.manifest.get("runtime_config", {}).get("cwd") if previous else None
    with update_lock(selected_root, host):
        return _update(host, root=selected_root, ref=ref, repo=repo, data_dir=data_dir,
            codex_home=codex_home, dsh_home=dsh_home, mcp_server=mcp_server, python=python,
            dsh_command=dsh_command, cwd=(cwd or Path(recorded_cwd) if recorded_cwd else cwd or Path.cwd()).resolve(), repair=repair,
            offline=offline, plan=plan)
