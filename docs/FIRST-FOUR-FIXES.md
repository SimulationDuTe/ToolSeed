# 前四项正确性与回归修复

日期：2026-10-28。本地未发布增量，五个公开工具保持不变，数据库 Schema 不变。

本记录对应第一批四项修复；后续结构化经验带来的 Schema v7 增量见 [后三项修复](LAST-THREE-FIXES.md)。

## 修订必须绑定实际读取的基线

`toolbox_save` 的完整 target candidate，以及 `toolbox_learn` 的完整 target experience，必须包含：

```json
{
  "target_capability_id": "cap_实际能力",
  "base_version_id": "ver_实际读取版本",
  "base_content_hash": "sha256:实际读取内容哈希"
}
```

两个基线字段来自同一次完整读取，不进入方法内容哈希。保存事务检查当前版本仍匹配；缺少绑定返回 `REVISION_BASE_REQUIRED`，版本变化返回 `CURRENT_VERSION_CONFLICT`，哈希不一致返回 `REVISION_BASE_MISMATCH`。冲突后必须重新读取、合并，不能只把旧稿换绑新 ID。

新能力不填写基线字段。绑定原 invocation 的 reuse/amendment 形态不变，Core 从已验证的交付绑定构造候选基线。隔离能力的管理修复可以引用明确的隔离版本，但继续遵守提升门禁。此前仅传 target 的完整修订调用会被拒绝，应同步更新 Core 和 Skill；没有自动猜测旧客户端基线的兼容分支。

## DSH 保留用户手动采用后的纠正

存在待反馈交付时，真实用户补充也会产生反馈线索，即使中间没有普通工具调用。下一回合保留有限的原交付引用，并提示模型判断是否有值得更新的采用、部分采用或未采用观察。用户消息不自动证明采用或成功；原文不复制到状态或日志中。

已接受的反馈不会因新用户消息重新打开。宿主拒绝、学习工具暂不可见和取消仍保留各自语义，不额外唤醒模型。

## 自检区分适配接入与实际就绪

`verify` 返回 `adapter_ok`、`ready`、`database_state`。`ok` 等于 `ready`，必须同时满足四类原生 Hook/信任、Skill/指引，以及实际 MCP 运行环境检查。

安装前调用配置命令的 `--probe`，确认实际五工具、只读检索与修订基线功能，并核对 MCP 和 Hook 的数据目录一致。探测不创建或迁移数据库。缺库可显示为未首用；缺 MCP、旧 Core、禁用条目、路径不一致或未确认信任不能标记 active。只探测本地 Python 模块或 toolseed-mcp 命令；未知包管理器包装命令保持未验证，不进行安装。

## 宿主测试纳管

移除对整个宿主 test 目录的忽略，保留私人 `host-*.mjs` 运行脚本及 `.test-data/` 的隔离。可移植 Node 测试只使用内置模块、公开源码与合成数据。

CI 新增 Linux、Windows、macOS × Node 22/24 的测试作业，并显式配置 Python 3.11 来运行真实 Core/面板适配用例。默认使用 PATH 中的 `python`，也可通过 `TOOLSEED_TEST_PYTHON` 指定；不依赖开发机的 Windows 虚拟环境路径。配置已添加，本轮未在远程触发 CI。

本地检查：Python 393 项（392 通过、1 项条件跳过），Node 138 项；包含旧读取与另一连接晋升的冲突、缺失/错误基线、隔离修复、用户手动纠正、已反馈不重开、宿主拒绝、缺 MCP、旧运行环境、库路径不一致和重复事件伪装四类 Hook。

不带本地虚拟环境及私人运行脚本的独立源码副本也通过了全部 138 项 Node 测试；Ruff 和 mypy 通过。

隔离原生 Codex CLI 验证：四类 Hook 正常信任，配置中的实际 Core 探测通过；未创建能力库；禁用配置、路径不一致和包装命令均未误报就绪。私人材料位于 `.test-data/fix-first-four-20261028/`。
