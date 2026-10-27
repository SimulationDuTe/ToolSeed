# Codex 经验与能力工作流

日期：2026-10-27。本地未发布增量，保留五个公共 MCP 工具与现有 Schema。
DSH 的真实模型任务记录仍见[原实测](../benchmarks/results/dsh-experience-2026-10-27/REPORT.md)；不能用它代替 Codex 的行为验收。

## 接入

Codex 的四个原生事件连接“当前任务 → 本地检索 → 交付方法 → 实际工作 → 原能力观察”。
Hook 只提供有界材料和机会，宿主模型通过 Skill 判断复用价值、权限、条件及验证要求，并调用 MCP 完成提炼和反馈。

- `UserPromptSubmit` 对任务做保守匹配；新结构化错误或 MCP 工具线索可以补充检索。
- `PostToolUse` 观察复杂操作后，提示选择跳过、复用、修订或提炼。普通工作不强制保存。
- `toolbox_run` 的真实交付 ID / 版本 / 哈希保留为后续反馈绑定，交付本身不算采用。
- `Interrupt` 中止 Hook 的查询并丢弃迟到材料；`SessionEnd` 关闭待反馈状态，不追加模型轮次。

检索使用配置的 Python 执行固定 `search --read-only`。SQLite 只读事务不创建或迁移数据库，沿用 Core 的检索规则；这是受信本地 Hook 查询，不是宿主 MCP 派发。每轮最多 3 次，每次 1500 ms、最多 2 张卡，查询失败不阻断任务。
模型仍须调用 `toolbox_run` 阅读完整方法，再用获得授权的宿主工具应用并验证。

Hook 无法获知每个 Agent 的完整工具可见性，因此未知适用条件不视为通过；候选正文是不可信材料。
只保留安全计数、工具名、查询哈希及交付引用，不持久化原始任务、参数、结果、正文或 transcript。

复用反馈通过 `toolbox_learn` 追加到原能力；新版本仍是候选。DSH 的宿主修订执行工具没有作为 Codex 工具注册，生效继续遵守现有管理与验证门禁。

## 验证记录

目标：Windows Codex CLI `0.164.0-alpha.11.1`，隔离验收 Node `24.14.0`，实际 Hook 使用 Codex 自带 Node `24.22.1` 的持久绝对路径。
原生 `hooks/list` 在隔离 CODEX_HOME 中列出四个处理器；`config/batchWrite` 后四项均为 trusted，`skills/list` 确认 user Skill 启用。

自动化检查包含真实 Core 的只读查询、缺库不建库、旧/未来 Schema 不迁移、SQLite 拒绝写入、提示去重、查询超时、中断、交付绑定和反馈关闭。宿主测试按仓库现有策略保留在本地测试目录。

本轮 Python 383 项（382 通过、1 项条件跳过）、Node 128 项全部通过；Ruff 通过，mypy 26 个源文件通过。Codex 定向用例 38 项，包含仅交付后收到用户纠正时仍能绑定原能力、取消后的迟到输出与精确反馈关闭。

隔离的原生 Codex CLI 两任务链路通过：A 在固定 JSON 测试工具产生结构化错误并恢复后，下一请求收到学习提示，再通过真实 MCP 保存方法；B 新会话的首个请求包含实际召回卡，随后 `toolbox_run` 交付完整方法，固定工具处理另一份 BOM JSON，再收到反馈提示，并通过 `toolbox_learn` 向原能力追加绑定原交付的观察。最终 1 个能力、1 个版本、1 次交付、1 条复用观察，无重复能力。原生 Hook 使用正常持久信任，没有绕过 Hook 信任。

这里的模型响应由本地 Responses 测试服务按脚本产生，验证的是宿主链路、真实查询与持久化，不是模型自主判断能力；测试数据与用户库隔离。shell 执行在该隔离环境受到策略限制，最终验收只使用固定 MCP JSON 样例工具，没有绕过 shell 策略。未在 Codex App UI 中单独操作，不声称已证明 Codex 真实模型会主动积累或产生净收益。

## 实际部署

- 已升级原 Codex MCP 运行环境的 ToolSeed 包，恢复缺失的 ToolSeed MCP 配置；从项目外、按实际配置启动新 MCP 客户端，确认五工具及新的学习 schema。
- 已同步四个 Hook、Skill、AGENTS.md 自有标记块，并验证四项均为 trusted、Skill 为 user / enabled。
- 继续使用 `F:/CodingFolder/ToolSeed-codex-runtime/data`，不切换到 DSH 库；升级前后库计数一致。其他 MCP、非 ToolSeed 配置与用户美术规范核对一致。
- 源码快照：`.toolseed/hosts/codex/local-7c85106be7f1-dirty-10040478`。统一安装器的嵌套进程备份被 Windows 权限阻止后，直接运行同一快照的安装器完成安装和原生验证，再更新安装状态。
- 部署凭据：`dist/codex-deployment-20261027.json`；本地详细验收材料：`.test-data/codex-workflow-20261027/`。

现有聊天的 MCP 工具清单不会由安装器强行替换。新建 Codex 聊天加载新工具与 Skill；本轮没有重启用户 Desktop 会话。

接口依据：[OpenAI 官方 Hooks 文档](https://learn.chatgpt.com/docs/hooks)。安装和开关见 [Codex adapter](../integrations/codex/README.md)。
