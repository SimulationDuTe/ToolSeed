"""Conservative lexical matches for unsolicited capability recall.

Ordinary explicit search keeps its broad matching. Automatic recall needs a
stronger signal before spending the host model's context on a capability.
"""
from __future__ import annotations

import re
from typing import Any

from .errors import INVALID_ARGUMENT
from .manifest import CandidateError, _string_list

WORDS = re.compile(r"[a-z][a-z0-9_]+|[\u3400-\u4dbf\u4e00-\u9fff]{2,}")
STOP = frozenset({
    "the", "this", "that", "with", "from", "for", "and", "then", "into", "please",
    "help", "use", "using", "tool", "tools", "task", "method", "check", "output", "file",
    "result", "a", "an", "to", "of", "in", "on", "is", "are", "be", "can", "do", "make",
    "create", "我们", "请帮", "帮我", "这个", "那个", "一个", "进行", "使用", "工具",
    "任务", "方法", "检查", "输出", "文件", "结果", "继续",
})


def keywords(text: str) -> set[str]:
    found: set[str] = set()
    for word in WORDS.findall(text.casefold()):
        if word in STOP:
            continue
        if '\u3400' <= word[0] <= '\u9fff':
            found.update(word[i:i + 2] for i in range(len(word) - 1) if word[i:i + 2] not in STOP)
        else:
            found.add(word)
    return found


def normalize_recall(raw: Any, query: str) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) - {"phase", "tool_hints", "error_codes"}:
        raise CandidateError(INVALID_ARGUMENT, "context.recall must contain phase, tool_hints and/or error_codes")
    if raw.get("phase") not in ("task", "error", "tools"):
        raise CandidateError(INVALID_ARGUMENT, "context.recall.phase must be task, error or tools")
    if len(query) > 600:
        raise CandidateError(INVALID_ARGUMENT, "automatic recall query exceeds 600 characters")
    return {"phase": raw["phase"],
            "tool_hints": _string_list(raw.get("tool_hints", []), "recall.tool_hints", 8, 160),
            "error_codes": _string_list(raw.get("error_codes", []), "recall.error_codes", 8, 80)}


def match_recall(query: str, cue: dict[str, Any], manifest: dict[str, Any], content: str) -> tuple[float, dict[str, Any]]:
    metadata = " ".join([manifest["name"], manifest["description"], manifest["when_to_use"], *manifest["tags"]])
    goal = keywords(query)
    metadata_matches = goal & keywords(metadata)
    matches = goal & keywords(metadata + " " + content)
    # Identifiers are matched whole. MCP's public leaf alias is a hint, never a
    # declaration that two tools have the same interface or permissions.
    identifiers = set(re.findall(r"[a-z0-9_]+", (metadata + " " + content).casefold()))
    tool_identifiers = {item for item in identifiers if "_" in item}
    tool_identifiers.update(item.casefold() for item in manifest["applicability"].get("required_tools", []))
    for line in re.findall(r"^工具线索：([^\n]+)", content, re.MULTILINE):
        tool_identifiers.update(re.findall(r"[a-z0-9_]+", line.casefold()))
    tools = [name for name in cue["tool_hints"]
             if name.casefold() in tool_identifiers or name.rsplit("__", 1)[-1].casefold() in tool_identifiers]
    errors = [code for code in cue["error_codes"] if code.casefold() in identifiers]
    # No CJK unigram matching and no single generic word as a task-start cue.
    task_fit = len(matches) >= 2 and bool(metadata_matches)
    eligible = task_fit if cue["phase"] == "task" else (
        bool(errors) or task_fit or (bool(tools) and bool(matches))
    )
    if cue["phase"] == "tools":
        eligible = bool(tools) and bool(matches)
    score = (len(matches) + 2 * len(metadata_matches) + 6 * len(tools) + 10 * len(errors)) if eligible else 0
    return float(score), {"phase": cue["phase"], "task_terms": sorted(matches)[:6],
                          "tool_hints": tools[:3], "error_codes": errors[:3]}
