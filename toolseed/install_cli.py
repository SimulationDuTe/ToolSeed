"""Adapter for the ``toolseed install|update|uninstall|host`` subcommands."""
from __future__ import annotations

import argparse
import json
from typing import Any

from .hosts import HOSTS, HostInstallError, install_root
from .hosts_cli import host_status, install_host, uninstall_host
from .updater import update_host

COMMANDS = {"install", "update", "uninstall", "host"}


def _render(payload: dict[str, Any]) -> str:
    if "error" in payload:
        error = payload["error"]
        lines = [f"{error['code']}: {error['message']}"]
        if error.get("detail"):
            lines.append(f"  {error['detail']}")
        if payload.get("rolled_back"):
            lines.append("  已保留原有安装，未切换版本。")
        return "\n".join(lines)
    if payload.get("action") == "status":
        lines = ["ToolSeed 宿主状态", f"安装根目录: {payload['install_root']}",
                 f"数据目录:   {payload['data_dir']}"]
        for host, entry in payload["hosts"].items():
            if not entry["installed"]:
                if entry.get("configured"):
                    lines.append(f"\n[{host}] 未纳管（检测到现有配置，未记录版本）")
                    for check in entry.get("checks", []):
                        lines.append(f"  {check['id']}: {check['state']}")
                else:
                    lines.append(f"\n[{host}] 未安装")
                continue
            stable = "预发布" if entry.get("prerelease") else "稳定"
            lines.append(f"\n[{host}] v{entry.get('version')} · {stable} · "
                         f"{str(entry.get('commit_sha'))[:12]}")
            lines.append(f"  目录: {entry.get('directory')}")
            for check in entry.get("checks", []):
                lines.append(f"  {check['id']}: {check['state']}"
                             + (f" ({check['detail']})" if check.get("detail") else ""))
            host_check = entry.get("host_verification")
            if host_check:
                lines.append(f"  宿主核验: {host_check['state']}"
                             + (f" — {host_check['detail']}" if host_check.get("detail") else ""))
        lines.append("\n配置存在不等于面板已加载或任务成功；未知项不会显示为正常。")
        return "\n".join(lines)
    host = payload.get("host")
    version = payload.get("install", {}).get("version")
    commit = payload.get("install", {}).get("commit_sha")
    action = payload.get("action")
    if action == "install":
        return (f"{host} 已安装 v{version} ({str(commit)[:12]})\n"
                f"  目录: {payload.get('directory')}\n"
                + (f"  上一版本: {payload['previous']}\n" if payload.get("previous") else "")
                + "  重新运行 install 会更新到指定版本；update 用于显式升级。")
    if action == "update":
        if payload.get("plan"):
            return (f"{host} 升级计划（未应用）\n  commit: {payload['source']['commit_sha']}\n"
                    f"  能力库: {payload['data_dir']}\n  步骤: " + " → ".join(payload["steps"]))
        return (f"{host} {'已是当前版本' if not payload.get('changed') else '完整升级完成'} "
                f"v{version} ({str(commit)[:12]})\n"
                f"  Core: {payload.get('install', {}).get('core', {}).get('python')}\n"
                f"  能力库: {payload.get('install', {}).get('data_dir')}\n"
                + ("  新建 Codex 聊天加载新版。" if host == "codex" else "  打开 DSH 加载新版。"))
    if action == "uninstall":
        removed = payload.get("removed", {})
        return (f"{host} 已卸载\n"
                f"  移除: {json.dumps(removed, ensure_ascii=False)}\n"
                f"  保留: {payload.get('preserved')}\n"
                + (f"  提示: {removed.get('note')}\n" if removed.get("note") else ""))
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _parser(prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="安装、升级与卸载 ToolSeed 宿主适配层（复用仓库内现有安装器）",
    )
    parser.add_argument("--data-dir", default=None, help="能力库目录；默认沿用 TOOLSEED_DATA_DIR 或 ~/.toolseed")
    parser.add_argument("--install-root", default=None, help="适配层安装根目录；默认 ~/.toolseed/hosts")
    parser.add_argument("--text", action="store_true", help="人类可读输出")
    parser.add_argument("--json", action="store_true", help="JSON 输出（默认）")
    sub = parser.add_subparsers(dest="operation", required=True)

    install = sub.add_parser("install", help="安装指定版本的适配层")
    install.add_argument("host", choices=list(HOSTS))
    install.add_argument("--ref", required=True,
                         help="tag、分支、commit SHA，或本地源码目录；分支会立即解析为固定 SHA 并记录为预发布")
    install.add_argument("--repo", default=None, help="GitHub 仓库 owner/name")
    install.add_argument("--codex-home", default=None)
    install.add_argument("--dsh-home", default=None)
    install.add_argument("--mcp-server", default="toolseed")
    install.add_argument("--python", default=None, help="MCP 使用的 Python；默认当前解释器")
    install.add_argument("--dsh-command", default="dsh")
    install.add_argument("--repair", action="store_true", help="相同源码和配置也重新应用，修复配置漂移")

    update = sub.add_parser("update", help="完整升级 Core、Skill、MCP 和宿主适配器")
    update.add_argument("host", choices=list(HOSTS))
    update.add_argument("--ref", required=True, help="目标版本；必须显式指定，不会跟随分支漂移")
    update.add_argument("--repo", default=None)
    update.add_argument("--codex-home", default=None)
    update.add_argument("--dsh-home", default=None)
    update.add_argument("--mcp-server", default=None, help="默认沿用已记录的 MCP 名称")
    update.add_argument("--python", default=None)
    update.add_argument("--dsh-command", default=None)
    update.add_argument("--cwd", default=None, help="Codex 项目目录；默认沿用已记录目录")
    update.add_argument("--offline", action="store_true", help="Core 依赖仅使用本地缓存；源码仍按 --ref 获取")
    update.add_argument("--plan", action="store_true", help="获取并固定源码，只展示升级计划")
    update.add_argument("--adapter-only", action="store_true", help="兼容旧用法：仅升级适配器，不升级 Core 或 MCP 配置")
    update.add_argument("--repair", action="store_true", help="相同源码和配置也重新应用，修复配置漂移")

    uninstall = sub.add_parser("uninstall", help="卸载适配层，保留能力库与用户配置")
    uninstall.add_argument("host", choices=list(HOSTS))
    uninstall.add_argument("--purge", action="store_true",
                           help="同时删除本适配层安装的历史版本目录（不影响能力库）")
    uninstall.add_argument("--codex-home", default=None)
    uninstall.add_argument("--dsh-home", default=None)

    host = sub.add_parser("host", help="只读检查宿主、版本、Skill、Hook、MCP 与能力库")
    host.add_argument("host", nargs="?", choices=list(HOSTS), default=None,
                      help="只显示某个宿主；省略则全部")
    host.add_argument("--codex-home", default=None)
    host.add_argument("--dsh-home", default=None)
    host.add_argument("--mcp-server", default="toolseed")
    host.add_argument("--deep", action="store_true",
                      help="启动 Codex app-server 核验 hooks/list 与 skills/list（可能初始化 Codex 状态）")
    return parser


def main(argv: list[str]) -> int:
    # The shared flags belong to the top-level parser, so argparse only accepts
    # them before the subcommand. Users naturally write them after, so hoist
    # every recognised shared flag (and its value) to the front first.
    shared = {"--data-dir", "--install-root", "--text", "--json"}
    hoisted: list[str] = []
    rest: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in shared:
            hoisted.append(token)
            if token in ("--data-dir", "--install-root") and index + 1 < len(argv):
                hoisted.append(argv[index + 1])
                index += 2
                continue
            index += 1
            continue
        rest.append(token)
        index += 1
    parser = _parser("toolseed")
    args = parser.parse_args(hoisted + rest)
    root = install_root(args.install_root) if args.install_root else install_root()
    wants_text = getattr(args, "text", False) and not getattr(args, "json", False)
    try:
        if args.operation == "host":
            report = host_status(root=root, data_dir=args.data_dir,
                                 codex_home=args.codex_home, dsh_home=args.dsh_home,
                                 mcp_server=args.mcp_server, deep=getattr(args, "deep", False))
            report["action"] = "status"
            if args.host:
                report["hosts"] = {args.host: report["hosts"][args.host]}
            payload: dict[str, Any] = report
            code = 0
        elif args.operation == "uninstall":
            payload = uninstall_host(args.host, root=root, purge=args.purge,
                                     data_dir=args.data_dir, codex_home=args.codex_home,
                                     dsh_home=args.dsh_home)
            payload["action"] = "uninstall"
            code = 0
        elif args.operation == "update" and not args.adapter_only:
            from pathlib import Path

            payload = update_host(args.host, ref=args.ref, root=root, repo=args.repo,
                data_dir=args.data_dir, codex_home=args.codex_home, dsh_home=args.dsh_home,
                mcp_server=args.mcp_server, python=args.python, dsh_command=args.dsh_command,
                cwd=Path(args.cwd) if args.cwd else None, repair=args.repair,
                offline=args.offline, plan=args.plan)
            code = 0 if payload.get("ok") else 2
        else:
            payload = install_host(
                args.host, ref=args.ref, root=root, data_dir=args.data_dir,
                codex_home=args.codex_home, dsh_home=args.dsh_home,
                mcp_server=args.mcp_server or "toolseed", python=args.python,
                dsh_command=args.dsh_command or "dsh", update=args.operation == "update", repair=args.repair,
            )
            payload["action"] = "install"
            code = 0 if payload.get("ok") else 2
    except HostInstallError as exc:
        payload = {"ok": False, "action": args.operation,
                   "error": {"code": exc.code, "message": exc.message, "detail": exc.detail}}
        code = 2
    except OSError as exc:
        payload = {"ok": False, "action": args.operation,
                   "error": {"code": "FILESYSTEM_ERROR", "message": "文件系统操作失败。",
                             "detail": str(exc)}}
        code = 2
    except (ValueError, KeyError, TypeError):
        payload = {"ok": False, "action": args.operation, "error": {
            "code": "HOST_CONFIGURATION_INVALID", "message": "宿主配置或安装记录格式无效，请检查后重试。"}}
        code = 2
    print(_render(payload) if wants_text else json.dumps(payload, ensure_ascii=False, indent=2))
    return code
