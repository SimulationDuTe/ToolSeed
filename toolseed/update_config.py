"""Read native host configuration; update only the selected ToolSeed MCP binding."""
from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .hosts import HostInstallError
from .update_files import FileJournal

SERVER_NAME = re.compile(r"^[A-Za-z0-9_-]{1,32}$")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig") if path.exists() else ""


def replace_toml_server(text: str, name: str, command: str, args: list[str]) -> str:
    """Preserve comments, unrelated tables, env, enable flags and timeout settings."""
    parsed = tomllib.loads(text)
    headings = list(re.finditer(r"(?m)^[ \t]*\[{1,2}[^\n]+\]{1,2}[ \t]*(?:#[^\n]*)?$", text))
    selected = None
    for index, heading in enumerate(headings):
        try:
            section = tomllib.loads(heading.group() + "\n")
        except tomllib.TOMLDecodeError:
            continue
        if section.get("mcp_servers", {}).get(name) == {}:
            selected = (heading.end(), headings[index + 1].start() if index + 1 < len(headings) else len(text))
            break
    values = {"command": command, "args": args}
    if selected is None:
        if name in parsed.get("mcp_servers", {}):
            raise HostInstallError("MCP_CONFIGURATION_UNSUPPORTED", "MCP 配置需使用独立的 TOML server 表。")
        return text.rstrip() + f'\n\n[mcp_servers."{name}"]\n' + "".join(
            f"{key} = {json.dumps(value, ensure_ascii=False)}\n" for key, value in values.items())
    start, end = selected
    lines = text[start:end].splitlines(keepends=True)
    for key, value in values.items():
        for index, line in enumerate(lines):
            if not re.match(rf'''^\s*(?:{key}|"{key}"|'{key}')\s*=''', line):
                continue
            stop = index + 1
            while stop <= len(lines):
                try:
                    tomllib.loads("".join(lines[index:stop]))
                    break
                except tomllib.TOMLDecodeError:
                    stop += 1
            if stop > len(lines):
                raise HostInstallError("MCP_CONFIGURATION_INVALID", "无法解析 MCP 启动参数。")
            lines[index:stop] = [f"{key} = {json.dumps(value, ensure_ascii=False)}\n"]
            break
        else:
            lines.append(f"{key} = {json.dumps(value, ensure_ascii=False)}\n")
    result = text[:start] + "\n" + "".join(lines).lstrip("\r\n") + text[end:]
    actual = tomllib.loads(result)
    expected = parsed
    expected.setdefault("mcp_servers", {}).setdefault(name, {}).update(values)
    if actual != expected:
        raise HostInstallError("CONFIG_CHANGED", "更新会改变其他 TOML 配置，已停止。")
    return result


def _dsh_nodes(paths: list[Path], server: str) -> tuple[str | None, dict]:
    # BaseLoader reads custom !!js tags as inert strings; no expressions execute.
    try:
        import yaml
    except ImportError as exc:
        raise HostInstallError("INSTALLER_DEPENDENCY_MISSING", "完整 DSH 升级需要 PyYAML；请升级 ToolSeed 包。") from exc
    nodes: dict[str, dict] = {}
    for path in paths:
        visited: set[int] = set()

        def walk(value: Any, visited: set[int] = visited) -> None:
            if not isinstance(value, (dict, list)) or id(value) in visited:
                return
            visited.add(id(value))
            if isinstance(value, dict):
                identity = value.get("id")
                if isinstance(identity, str):
                    old = nodes.get(identity, {})
                    old_config, new_config = old.get("config"), value.get("config")
                    nodes[identity] = {**old, **value, "config": {
                        **(old_config if isinstance(old_config, dict) else {}),
                        **(new_config if isinstance(new_config, dict) else {})}}
                for child in value.values():
                    walk(child)
            else:
                for child in value:
                    walk(child)
        if path.exists():
            try:
                walk(yaml.load(read_text(path), Loader=yaml.BaseLoader))
            except yaml.YAMLError as exc:
                raise HostInstallError("HOST_CONFIGURATION_INVALID", f"DSH 配置无法解析：{path}") from exc
    matches = [(key, node) for key, node in nodes.items()
               if node.get("name") == "@deepseek-ai/dsh-mcp-client"
               and node.get("config", {}).get("serverName") == server]
    if len(matches) > 1:
        raise HostInstallError("MCP_CONFIGURATION_AMBIGUOUS", "存在多个同名 DSH MCP 节点，请先消除歧义。")
    if not matches:
        return None, {}
    identity, node = matches[0]
    if str(node.get("disabled", "false")).lower() == "true":
        raise HostInstallError("MCP_DISABLED", "所选 MCP 已禁用；升级不会自动启用。")
    return identity, node["config"]


@dataclass
class HostConfiguration:
    host: str
    home: Path
    path: Path
    server_name: str
    server: dict
    data: Path
    dsh_id: str | None = None

    def watched_files(self) -> list[Path]:
        skill = self.home / "skills" / "toolseed" / "SKILL.md"
        if self.host == "codex":
            return [self.path, self.home / "config.toml", self.home / "hooks.json",
                    self.home / "AGENTS.md", skill]
        profile = self.home / "profiles" / "desktop"
        return [self.path, profile / "package.json", profile / "pnpm-lock.yaml",
                profile / "pnpm-workspace.yaml", skill]

    def write_runtime(self, journal: FileJournal, python: Path) -> None:
        command = str(python)
        args = ["-I", "-B", "-X", "utf8", "-m", "toolseed.mcp_server", "--data-dir", str(self.data)]
        text = read_text(self.path)
        if self.host == "codex":
            updated = replace_toml_server(text, self.server_name, command, args)
        else:
            if os.name == "nt":
                command = str(python.with_name("pythonw.exe"))
                args = ["-c", ("import subprocess,sys; raise SystemExit(subprocess.call(sys.argv[1:], "
                        "stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr, creationflags=0x08000000))"),
                        str(python), *args]
            begin = f"# BEGIN TOOLSEED MCP {self.server_name}"
            end = f"# END TOOLSEED MCP {self.server_name}"
            pattern = rf"(?ms)^{re.escape(begin)}\r?\n.*?^{re.escape(end)}\r?\n?"
            block = f"- id: {json.dumps(self.dsh_id or 'mcp-' + self.server_name)}\n  config:\n"
            block += f"    command: {json.dumps(command)}\n    args: {json.dumps(args, ensure_ascii=False)}\n"
            prior_block = re.search(pattern, text)
            if self.dsh_id is None or (prior_block and "- insert:" in prior_block.group()):
                block = "- insert:\n" + "\n".join("  " + line
                    for line in (
                        f"- id: {json.dumps('mcp-' + self.server_name)}\n"
                        f"  name: '@deepseek-ai/dsh-mcp-client'\n  config:\n"
                        f"    serverName: {json.dumps(self.server_name)}\n    transport: stdio\n"
                        f"    command: {json.dumps(command)}\n    args: {json.dumps(args)}").splitlines()) + "\n"
            updated = re.sub(pattern, "", text).rstrip() + f"\n{begin}\n{block}{end}\n"
        journal.write(self.path, updated.encode("utf-8"))


def load_configuration(host: str, home: Path, cwd: Path, server_name: str,
                       explicit_data: str | None, recorded_data: str | None) -> HostConfiguration:
    if not SERVER_NAME.fullmatch(server_name):
        raise HostInstallError("INVALID_MCP_SERVER", "MCP 名称必须为 1–32 位字母、数字、下划线或连字符。")
    server: dict = {}
    identity = None
    if host == "codex":
        path = home / "config.toml"
        for candidate in [path, cwd / ".codex" / "config.toml", cwd / "config.toml"]:
            parsed = tomllib.loads(read_text(candidate))
            if server_name in parsed.get("mcp_servers", {}):
                path = candidate
                server = parsed["mcp_servers"][server_name]
        if server.get("enabled", True) is not True:
            raise HostInstallError("MCP_DISABLED", "所选 MCP 已禁用；升级不会自动启用。")
    else:
        profile = home / "profiles" / "desktop"
        if not (profile / "package.json").is_file():
            raise HostInstallError("DSH_PROFILE_MISSING", "请先打开 DSH 初始化 desktop profile，再完全退出。")
        path = profile / "cordis.patch.yml"
        identity, server = _dsh_nodes([home / "cordis.yml", home / "cordis.patch.yml",
                                       profile / "cordis.yml", path], server_name)
    if server.get("url") or server.get("transport", "stdio") != "stdio":
        raise HostInstallError("MCP_RUNTIME_UNSUPPORTED", "完整升级仅支持本地 stdio ToolSeed MCP。")
    arguments = server.get("args", [])
    if not isinstance(arguments, list) or any(not isinstance(value, str) for value in arguments):
        raise HostInstallError("MCP_CONFIGURATION_INVALID", "MCP args 必须为字符串数组。")
    paths = [value.split("=", 1)[1] for value in arguments if value.startswith("--data-dir=")]
    paths.extend(arguments[index + 1] for index, value in enumerate(arguments[:-1]) if value == "--data-dir")
    if arguments and arguments[-1] == "--data-dir" or len(paths) > 1:
        raise HostInstallError("MCP_CONFIGURATION_INVALID", "MCP 数据目录参数无效或重复。")
    environment = server.get("env", {})
    if not isinstance(environment, dict):
        raise HostInstallError("MCP_CONFIGURATION_INVALID", "MCP env 必须为对象。")
    configured = paths[0] if paths else environment.get("TOOLSEED_DATA_DIR")
    selected = configured or recorded_data or explicit_data or os.environ.get("TOOLSEED_DATA_DIR") or str(Path.home() / ".toolseed")
    data = Path(selected).expanduser()
    if not data.is_absolute():
        raise HostInstallError("DATA_DIRECTORY_AMBIGUOUS", "升级需要绝对能力库路径，避免改变已有库。")
    data = data.resolve()
    if explicit_data and os.path.normcase(str(Path(explicit_data).expanduser().resolve())) != os.path.normcase(str(data)):
        raise HostInstallError("DATA_DIRECTORY_MISMATCH", "指定目录与宿主现有能力库不一致；升级不会迁移到另一库。")
    return HostConfiguration(host, home, path, server_name, server, data, identity)
