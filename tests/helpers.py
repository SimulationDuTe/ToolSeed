"""Shared fixtures for the P0 test suite."""
from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from typing import Any

from toolseed import ToolSeed

BASE = Path(__file__).resolve().parent / ".data"

MANIFEST: dict[str, Any] = {
    "name": "triage_api_timeout",
    "kind": "procedure",
    "description": "对 API 请求超时进行分层排查",
    "when_to_use": "请求间歇性超时，需要区分客户端、网络和服务端原因",
    "not_for": ["已确认是凭据无效"],
    "tags": ["api", "debugging", "timeout"],
    "applicability": {"harnesses": [], "operating_systems": [], "required_tools": []},
}

CONTENT = (
    "1. 先确认请求是否到达服务端，对比客户端发起时间与服务端入口时间。\n"
    "2. 若服务端未收到请求，检查 DNS、代理与连接池配置。\n"
    "3. 若服务端收到但处理缓慢，检查下游依赖与慢查询。\n"
)


def candidate(**overrides: Any) -> dict[str, Any]:
    manifest = dict(MANIFEST)
    manifest.update(overrides.pop("manifest", {}))
    payload: dict[str, Any] = {
        "protocol_version": 1,
        "manifest": manifest,
        "content": CONTENT,
    }
    payload.update(overrides)
    return payload


class CoreTest(unittest.TestCase):
    case = "case"

    def setUp(self) -> None:
        self.dir = BASE / self.case
        shutil.rmtree(self.dir, ignore_errors=True)
        self.core = ToolSeed(str(self.dir))

    def tearDown(self) -> None:
        self.core.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def save(
        self,
        payload: Any = None,
        intent: str = "reuse the timeout triage method",
        context: Any = None,
    ) -> dict[str, Any]:
        result = self.core.toolbox_save(payload if payload is not None else candidate(), intent, context)
        self.assertEqual(result.get("status"), "accepted", result)
        return result


def verification_payload(
    version_number: int,
    *,
    outcome: str = "passed",
    source_type: str = "test_runner",
    method: str = "pytest",
    case_ids: list[str] | None = None,
    regression_case_ids: list[str] | None = None,
    ref: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "method": method,
        "input_ref": f"case-input:v{version_number}",
        "artifact_ref": f"artifact:v{version_number}",
        "case_ids": case_ids or [f"new-case-v{version_number}"],
    }
    if version_number > 1:
        payload["regression_case_ids"] = regression_case_ids or [f"regression-v{version_number - 1}"]
    return {
        "outcome": outcome,
        "source_type": source_type,
        "verification_ref": ref or f"test-run:v{version_number}",
        "verification": payload,
    }


def verify_version(core: ToolSeed, saved: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    payload = verification_payload(int(saved["version"]), **overrides)
    result = core.record_version_verification(
        version_id=saved["version_id"],
        content_hash=saved["content_hash"],
        **payload,
    )
    if not result.get("ok"):
        raise AssertionError(result)
    return result
