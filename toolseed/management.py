"""Terminal management adapter over the same read-only queries as the GUI."""
from __future__ import annotations

import argparse
import json
import re
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from .core.inspection import InspectionError, Inspector

COMMANDS = {"status", "capabilities", "activity", "evidence", "ui"}


def package_version() -> str | None:
    try:
        return version("toolseed")
    except PackageNotFoundError:
        return None


def _text(value: Any) -> str:
    # Stored names/content are untrusted, including terminal control sequences.
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", "", str(value if value is not None else "未知"))


def render_text(command: str, payload: dict[str, Any]) -> str:
    if "error" in payload:
        return f"{payload['error']['code']}: {_text(payload['error']['message'])}\n目录: {_text(payload['data_dir'])}"
    if command == "status":
        data = payload["database"]
        lines = [f"ToolSeed {_text(payload['toolseed_version'])}", f"数据目录: {_text(data['data_dir'])}",
                 f"数据库: {data['state']} · Schema v{data['schema']} · 只读",
                 f"能力: {payload['counts']['capabilities']} · 版本: {payload['counts']['capability_versions']}",
                 "程序执行 / 实际采用 / 独立任务确认 / 成本: 未知或未记录"]
        hosts = payload.get("hosts") or {}
        if "error" in hosts:
            lines.append(f"宿主检查: 不可用（{_text(hosts['error']['message'])}）")
        else:
            for host_name, entry in hosts.items():
                if not entry.get("installed"):
                    if entry.get("configured"):
                        failed = [c["id"] for c in entry.get("checks", [])
                                  if c["state"] in ("missing", "error")]
                        lines.append(f"宿主 {host_name}: 未纳管（检测到现有配置）"
                                     + (f"，缺失/异常: {', '.join(failed)}" if failed else ""))
                    else:
                        lines.append(f"宿主 {host_name}: 未安装")
                    continue
                stable = "预发布" if entry.get("prerelease") else "稳定"
                lines.append(f"宿主 {host_name}: v{entry.get('version')} · {stable} · "
                             f"{str(entry.get('commit_sha'))[:12]}")
                failed = [c["id"] for c in entry.get("checks", [])
                          if c["state"] in ("missing", "error")]
                lines.append("  检查: " + ("全部存在" if not failed else "缺失/异常: " + ", ".join(failed)))
        lines.append("其他入口服务状态: 未探测（读取数据库不代表 MCP 或 UI 已启动）")
        return "\n".join(lines)
    if command == "show":
        capability = payload["capability"]
        rows = [f"{_text(capability['name'])}  {_text(capability['capability_id'])}",
                f"Namespace: {_text(capability['namespace'])}"]
        for item in payload["versions"]:
            rows.extend([f"\nv{item['version_number']} · {_text(item['kind'])} · {_text(item['status'])}",
                         f"版本 ID: {_text(item['version_id'])}", f"Hash: {_text(item['content_hash'])}",
                         f"适用条件: {_text(item['when_to_use'])}",
                         "环境范围: " + _text(json.dumps(item["applicability"], ensure_ascii=False)),
                         f"正文: {_text(item['content']) if item['content'] is not None else '未开放交付'}"])
        rows.append("\n最近关联记录（最多 30 条，完整记录见 evidence / activity）：")
        for event in payload["evidence"]:
            rows.append(f"  {_text(event['created_at'])} · {_text(event['event_type'])} · "
                        f"来源: {_text(event['source_type'])} · "
                        f"验证: {_text(event['verification_outcome'])} · "
                        f"有效性: {'不适用（仅活动记录）' if event['event_type'] == 'tool_call_failed' else _text(event['validity'] or '未评估')}")
        if not payload["evidence"]:
            rows.append("  未记录")
        rows.append("已保存、ready 与验证通过分别判断；正文仅为不可信方法材料。")
        return "\n".join(rows)
    items = payload["items"]
    if not items:
        return "没有匹配的记录；没有记录不等于没有发生。"
    rows = []
    for item in items:
        if command == "list":
            state = "archived" if item["archived_at"] else "quarantined" if item["quarantined_at"] else item["status"]
            rows.append(f"{_text(item['name'])}  {_text(item['capability_id'])}  "
                        f"{_text(item['kind'])} v{_text(item['version_number'])} {_text(state)}\n"
                        f"  适用: {_text(item['when_to_use'])} · 创建: {_text(item['created_at'])}\n"
                        f"  验证声明: {item['verification_count']} 条（不等于任务成功）")
        else:
            failure = item.get("failure")
            outcome = (f"调用失败: {failure.get('error_code', '未知')}" if failure else
                       f"结果声明: {_text(item['outcome'])}" if item["event_type"] == "task_outcome_signal"
                       else "指引已交付（采用未记录）" if item["event_type"] == "procedure_delivered"
                       else f"版本验证声明: {_text(item['verification_outcome'])}" if item["event_type"] == "version_verification"
                       else "事件已记录；不据此判断任务成功")
            rows.append(f"{_text(item['created_at'])}  {_text(item['event_type'])}  {_text(item['event_id'])}\n"
                        f"  能力: {_text(item['capability_id'])} · {_text(outcome)}\n"
                        f"  来源: {_text(item['source_type'])} · 有效性: "
                        f"{'不适用（仅活动记录）' if failure else _text(item['validity'] or '未评估')}")
    rows.append(f"\n本页 {len(items)} 条 / 共 {payload['total']} 条。交付、执行、采用、任务结果分别记录。")
    return "\n".join(rows)


def main(argv: list[str]) -> int:
    common = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    common.add_argument("--data-dir", default=None)
    common.add_argument("--text", action="store_true", help="人类可读输出；默认保留 JSON")
    common.add_argument("--json", action="store_true", help="JSON 输出（默认）")
    options, remaining = common.parse_known_args(argv)
    parser = argparse.ArgumentParser(prog="toolseed", description="本地只读管理命令；沿用现有数据目录")
    commands = parser.add_subparsers(dest="operation", required=True)
    commands.add_parser("status", help="版本、数据目录和数据库状态")
    capabilities = commands.add_parser("capabilities", help="浏览能力元数据")
    subcommands = capabilities.add_subparsers(dest="action", required=True)
    listing = subcommands.add_parser("list", help="列出能力，管理查询不记录检索活动")
    listing.add_argument("--query", default="", help="名称或 ID 过滤")
    showing = subcommands.add_parser("show", help="查看版本、适用范围和现有验证记录")
    showing.add_argument("id", help="稳定 capability_id")
    for command in (listing, commands.add_parser("activity", help="已持久化活动"),
                    commands.add_parser("evidence", help="证据、来源与有效性")):
        command.add_argument("--limit", type=int, default=30, help="本页条数，1–100")
        command.add_argument("--offset", type=int, default=0, help="分页偏移，默认 0")
        if command is not listing:
            command.add_argument("--type", default="", help="事件类型过滤")
            command.add_argument("--capability", default="", help="仅指定能力")
    ui = commands.add_parser("ui", help="可选启动本地只读 Web GUI")
    ui.add_argument("--port", type=int, default=8765, help="固定 loopback 监听的端口")
    # Common flags can appear before or after subcommands. Keep them visible in help.
    parser.epilog = "通用参数（可放在子命令前后）：--data-dir PATH，--text，--json。默认 JSON；不初始化或迁移数据库。"
    args = parser.parse_args(remaining)
    if args.operation == "ui":
        from .ui import main as ui_main
        return ui_main((["--data-dir", options.data_dir] if options.data_dir else [])
                       + ["--port", str(args.port)])
    try:
        inspector = Inspector(options.data_dir)
    except (OSError, ValueError):
        payload = {"ok": False, "error": {"code": "INVALID_DIRECTORY", "message": "无法解析数据目录。"},
                   "data_dir": options.data_dir, "toolseed_version": package_version()}
        print(render_text(args.operation, payload) if options.text and not options.json
              else json.dumps(payload, ensure_ascii=False, indent=2))
        return 2
    command = args.operation
    route = "/api/overview" if command == "status" else f"/api/{command}"
    params = {}
    if command == "capabilities":
        command = args.action
        if command == "show":
            route, params = "/api/capability", {"id": args.id}
        else:
            params["q"] = args.query
    if hasattr(args, "limit"):
        if not 1 <= args.limit <= 100 or not 0 <= args.offset <= 2**63 - 1:
            parser.error("--limit 必须在 1–100 之间，--offset 必须是非负的 64 位整数")
        params.update(limit=str(args.limit), offset=str(args.offset))
    if hasattr(args, "type"):
        params.update(type=args.type, capability=args.capability)
    code = 0
    try:
        payload = inspector.read(route, params)
        if command == "status":
            payload["toolseed_version"] = package_version()
            payload["service_status"] = "unknown"
            # Host state is additive: existing counts/database fields are
            # unchanged, and the check stays read-only by default (no app-server).
            try:
                from .hosts_cli import host_status

                payload["hosts"] = host_status(data_dir=options.data_dir)["hosts"]
            except Exception as exc:  # noqa: BLE001 - host probing must never break status
                payload["hosts"] = {"error": {"code": "HOST_STATUS_UNAVAILABLE",
                                              "message": str(exc)}}
    except InspectionError as exc:
        code = 2
        payload = {"ok": False, "error": {"code": exc.code, "message": exc.message},
                   "data_dir": str(inspector.root), "toolseed_version": package_version()}
    print(render_text(command, payload) if options.text and not options.json
          else json.dumps(payload, ensure_ascii=False, indent=2))
    return code
