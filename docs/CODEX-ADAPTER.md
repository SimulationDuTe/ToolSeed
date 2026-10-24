# Codex Agent Adapter：交付记录与兼容性说明

本地增量，未提交、未推送、未打 Tag、未发布。基线仍是当前工作树中的 v0.4.1
内容；本轮不修改 Core、Schema、公共 MCP 协议或已部署的 DSH 适配层。

## 1. 范围与结论

新增 `integrations/codex`，让 ToolSeed 不只作为 Codex 的一个 MCP Server，而是
接入 Codex 的 Agent 工作流：

- 用 Codex 原生 `PostToolUse` hook 观察完成的结构化工具结果；
- 在同一个 Agent turn 内识别重复阻塞，并通过
  `hookSpecificOutput.additionalContext` 给下一次模型步骤一次 L1 提示；
- 用 `$CODEX_HOME/skills/toolseed/SKILL.md` 提供可复用的行为约定；
- 用 `$CODEX_HOME/AGENTS.md` 的标记块提供常驻、简短的接入说明；
- 用 Codex app-server 的 `hooks/list`、`skills/list`、`config/batchWrite`
  安装、信任和自检；
- 不复制业务逻辑，Core 仍是唯一的能力库与证据来源。

**已验证的是宿主机制和隔离链路；未验证真实模型的自主检索、实际采用和跨任务复用。**

## 2. 核实依据

本机实际使用：

- Codex CLI `0.163.0-alpha.11`（Windows x64）——实际 hook/Skill/AGENTS/`exec`
  验证；
- 本机安装的 Codex App `26.1016.6573.0`——只核对版本与共享安装接口，**未在
  App UI 内运行适配器**；
- 安装包 `codex.exe` 的公开 hook schema 字符串、app-server JSON Schema、
  `hooks/list` / `skills/list` / `config/batchWrite` 响应；
- `codex debug prompt-input` 的实际模型输入；
- 本地 mock Responses API + 真实 ToolSeed MCP stdio 进程（无外部模型/网络请求）。

关键接口事实：

| 能力 | Codex 0.163 实际形态 | 本轮是否使用 |
|---|---|---|
| Hook 配置 | `$CODEX_HOME/hooks.json` 或 `config.toml` 的 `[[hooks.PostToolUse]]`；`matcher` 为 regex | 使用 `hooks.json` |
| Hook 事件 | `PreToolUse`、`PermissionRequest`、`PostToolUse`、`PreCompact`、`PostCompact`、`SessionStart`、`SessionEnd`、`UserPromptSubmit`、`SubagentStart`、`SubagentStop`、`Stop`、`Interrupt` | 只装 `PostToolUse`，降低开销与信任面 |
| PostToolUse 输入 | `session_id`、`turn_id`、`tool_name`、`tool_use_id`、`tool_input`、`tool_response`、`transcript_path` 等 | 使用前五项；不读 transcript |
| PostToolUse 输出 | `hookSpecificOutput.additionalContext`、`systemMessage`、`decision`、`reason` 等 | 只写 `additionalContext` |
| 信任 | `hooks.state."<key>"` 的 `trusted_hash`；TUI 通过 app-server `config/batchWrite` 写入 | 安装器走同一 `config/batchWrite` |
| Skill | `$CODEX_HOME/skills/<name>/SKILL.md`，`skills/list` 返回 `scope=user` / `enabled` | 安装 ToolSeed Skill |
| 指令注入 | `$CODEX_HOME/AGENTS.md` 进入 `agents_md.instructions` | 安装标记块 |
| MCP 工具命名 | 命名空间 `mcp__<server>` + `namespace` 字段；hook 里看到 `mcp__toolseed__toolbox_save` | 支持 `mcp__server__tool` 与 `mcp__server.tool` |
| `notify` | turn 级通知，不能向当前 turn 注入上下文 | 未使用 |
| 原生管理面板 | 本轮未核实到适用于 ToolSeed 的 Codex 公共面板契约 | 未实现，未声称 |

参考：[Codex 官方文档](https://developers.openai.com/codex/) 与
[Codex MCP](https://developers.openai.com/codex/mcp)。官网会变化；本轮判断以本机
0.163.0-alpha.11 安装包中的 app-server JSON Schema、`hooks/list` / `skills/list`
实际输出和 `codex debug prompt-input` 为准。

## 3. 架构与边界

```text
Codex Agent turn
  └─ tool call completes
       └─ PostToolUse hook (cmd /c node toolseed-hook.mjs ...)
            ├─ 读取 stdin JSON
            ├─ 3 次同工具 + 同结构化错误码？
            │    └─ 是：输出 hookSpecificOutput.additionalContext（一次/回合）
            ├─ ToolSeed 调用？
            │    └─ 只记录 search/save/run 阶段，不参与阻塞计数
            └─ 退出 0；失败也只返回 {}，不阻塞任务
```

职责边界：

- **Core**：候选校验、持久化、检索、交付、证据、生命周期门禁；本 Adapter 不复制。
- **MCP**：四个固定工具的唯一传输入口；Adapter 不注册第五个工具。
- **Skill**：行为约定；Adapter 只安装源码树中的同一份 `SKILL.md`，不另写一份。
- **Adapter**：宿主事件到提示的薄翻译层；不执行 Procedure、不判断任务成功、
  不把提示/交付/保存写成采用或成功。
- **DSH Adapter**：保持原样；Codex Adapter 是并列目录，不共享宿主假设。

## 4. DSH / Codex 能力对照

| 维度 | DSH Adapter（已部署 0.2.1-rc.2） | Codex Adapter（本轮 0.163.0-alpha.11） | 适配结果 |
|---|---|---|---|
| 工具结果观察 | `tools/result(exec, result)`；`result.error.info.code`；`exec.token` 去重 | `PostToolUse` stdin；`tool_name` / `tool_use_id` / `tool_response`；无统一错误码 | 已实现；Codex 只能从结构化字段提取 |
| 回合边界 | `agent/pre-step`、`agent/disposed`、`session/event` | `SessionStart/End`、`UserPromptSubmit`、`Stop`、`Interrupt` 等 hooks | Codex 侧只用 `PostToolUse` + 状态文件按 turn 隔离 |
| 上下文注入 | `agent/pre-step` 追加带 ID/source 的 user context message | `PostToolUse` 的 `additionalContext` | 已实现 |
| 提交/接收回执 | `session/event` 的 `user/message` 确认消息被提交 | 无对应公开的“hook 输出已提交”事件 | **不等价**；日志写 `host_receipt: unknown` |
| 工具可见性 | `ctx.tools.get(name, agent)` | hooks 不暴露 per-Agent 工具可见性 | **不等价**；提示要求工具不可用时继续原任务 |
| Skill 加载 | Cordis 宿主 Skill | `$CODEX_HOME/skills` + `skills/list` + `debug prompt-input` | 已实现并核实 |
| 常驻指令 | DSH 插件/Skill 机制 | `AGENTS.md` | 已实现并核实 |
| 任务结果 | 无可靠通道；不把回合结束当成功 | `Stop` 不是成功信号 | 两者都保持 `unknown` |
| MCP | 四个固定工具 | 四个固定工具 | 相同 |
| 原生面板 | `settings.section` 只读面板 | 未核实到公共面板契约 | Codex 不实现，不伪造 |
| Hook 信任 | 插件安装/宿主机制 | `hooks.state` + `config/batchWrite` / TUI 审核 | 安装器使用原生 `config/batchWrite` |
| `notify` | 无 | turn 级通知，不能注入当前步骤 | 未使用 |
| app-server | 无同等公开 JSON-RPC 面 | `hooks/list`、`skills/list`、`config/batchWrite` 等 | 安装/自检使用，运行时不用 |
| `exec --json` | 无 | 事件流；不能中途注入 | 未作为提示通道 |

## 5. 实际实现

### 5.1 运行时 hook

`src/toolseed-hook.mjs`：

- 从 stdin 读取一次 JSON；始终向 stdout 写一个 JSON 对象，退出码 0。
- 只有 `hook_event_name=PostToolUse` 且字段合法时才处理。
- 失败/异常返回 `{}`；诊断只在 opt-in trace 或本地日志中。

`src/opportunities.mjs`：

- 结构化失败提取：`error.info.code`、`error.code`、MCP
  `content`/`structuredContent` 的有界 JSON、非零 `exitCode`；
- 不解析自由文本、shell 输出、prompt 或 Procedure 正文；
- 同 `tool + code` 的第 3 个不同 `tool_use_id` 触发一次；
- 每回合最多一次；状态上限 256 次执行 / 16 个错误组；
- ToolSeed 自身的 `toolbox_*` 调用只记录阶段，不参与阻塞计数；
- ToolSeed 调用阶段：`search_completed`、`save_failed`、
  `existing_version_returned`、`capability_saved`、`guidance_delivered` 等。

`src/state.mjs` / `logging.mjs`：

- 状态按 `session_id + turn_id` 哈希分文件；
- 原子写 + `O_EXCL` 文件锁，锁超时则跳过而不是阻塞任务；
- 24 小时清理；日志 1 MiB 轮转；
- 只写短期/不透明 ID、计数、阶段和阶段相关 ID，不写参数/输出/正文/推理。

### 5.2 安装与自检

`src/install.mjs`：

1. 写 Skill；
2. 合并 `hooks.json`，保留用户已有 hook；
3. 写/替换 `AGENTS.md` 标记块；
4. 启动 Codex app-server，`hooks/list` + `skills/list`；
5. 用 `config/batchWrite` 写 `hooks.state.<key>.trusted_hash`；
6. 再次 `hooks/list` 确认 `trustStatus=trusted`；
7. 输出 JSON/text 计划；写前备份 Skill/hooks/AGENTS。

安装器启动 app-server 可能让 Codex 在该 `CODEX_HOME` 初始化自己的系统
Skill、SQLite 状态等；Adapter 不调用模型、不执行工具。Codex 写 trust 时可能
规范化 `config.toml`。安装器不改 MCP 配置或 DSH 配置。

Windows hook 命令实际使用：

```text
cmd /c "<node>" "<repo>/integrations/codex/src/toolseed-hook.mjs" \
  --mcp-server toolseed \
  --state-dir "<CODEX_HOME>/.toolseed-codex/state" \
  --log-dir "<CODEX_HOME>/.toolseed-codex"
```

该形式已在 0.163.0-alpha.11 实际执行（不是仅 schema 推断）。

`src/verify.mjs` 只读检查：Codex 版本、hook 是否列出/信任、Skill 是否
`scope=user`/enabled、AGENTS.md 标记、MCP 配置、数据库存在性。

### 5.3 兼容性限制

- **Bash**：本版本 `PostToolUse` 的 `tool_response` 对 `tool_name=Bash` 是字符串；
  `cmd /c exit 1` 的 trace 显示 `response_type=string`，没有结构化退出码。
  Adapter 不解析该字符串，因此 shell-only 失败不会触发动态提示。Skill 和
  AGENTS.md 仍提供行为指导。
- **MCP 传输失败**：实测 `status: failed` / `isError: true` 的 MCP 调用没有
  进入 `PostToolUse`；`status: completed` 且 payload 带
  `structuredContent.error.code` 的调用会进入。ToolSeed Core 错误属于后者。
- **无提交回执**：hook 输出是否被 Codex 接收，没有单独的公共 ack。日志写
  `host_receipt: unknown`；隔离 mock 中通过下一次模型请求看到提示，属于测试
  证据，不升级为生产回执。
- **无工具可见性**：提示要求“工具不可用/无匹配就继续”，不假装工具一定可见。
- **任务成功未知**：`Stop` 只是回合结束；不写 `task_outcome=success`。
- **无原生面板**：Codex 侧只有 MCP、管理 CLI/可选 Web GUI；未实现或声称
  Codex 原生面板。
- **版本范围**：仅本机 Codex CLI `0.163.0-alpha.11` 做了实际 hook/exec 验证；
  本机 App `26.1016.6573.0` 只核对版本/共享接口，未在 App UI 内运行。其他
  版本或 App 行为需重新核实。

## 6. 验证证据

### 6.1 本地单元测试

| 命令 | 结果 |
|---|---|
| `node integrations/codex/test/opportunities.test.mjs` | 12 通过，0 失败 |
| `node integrations/codex/test/install.test.mjs` | 9 通过，0 失败 |

覆盖：阈值、不同工具/错误码不合并、重复 token、ToolSeed 调用不计数、搜索
抑制、save/run 阶段、自由文本不解析、MCP 有界 JSON、输入清洗、状态/锁/日志、
hooks 合并幂等、AGENTS 幂等、MCP 表检测、安装 dry-run/apply、可禁用
AGENTS.md。合计 21 项通过。

### 6.2 真实 Codex 机制

隔离 `CODEX_HOME` 中执行安装器：

- `hooks/list`：`postToolUse` 出现，`trustStatus=trusted`；
- `skills/list`：`toolseed`，`scope=user`，`enabled=true`；
- `codex debug prompt-input`：`r0/toolseed/SKILL.md` 出现在
  `<skills_instructions>`，AGENTS 块出现在 `agents_md.instructions`；
- `verify.mjs`：`hook_listed`、`hook_trusted`、`skill_active`、`agents_md`、
  `mcp_server_config`、`toolseed_database` 全部 PASS；
- `config/batchWrite`：返回 `status=ok`，随后信任状态为 `trusted`。

### 6.3 隔离端到端机会链路

使用本地 mock Responses API（非真实模型）和真实 ToolSeed MCP stdio 进程：

1. 测试 MCP server 的 `fail_probe` 连续 3 次返回
   `structuredContent.error.code=PROBE_FAIL`（调用状态 `completed`）；
2. hook 日志：
   - `signal_detected`，`count=3`，`tool=mcp__failprobe__fail_probe`；
   - `hint_emitted`，`delivery=post_tool_use_additional_context`；
3. mock 下一次模型请求 `hint_found=true`，说明 Codex 把
   `additionalContext` 注入了下一次模型输入；
4. 随后 `toolbox_search` 实际执行：`search_completed`，`candidate_count=0`；
5. `toolbox_save` 实际执行并返回 `status=accepted`，
   `capability_id=cap_9ef22e94be0b`，`version_id=ver_a0d18231ad9e`，
   `version_status=ready`；
6. 数据库生成 `toolseed.sqlite3`，`verify` 的 `toolseed_database` PASS。

这是“提示生成 → 宿主接收（通过下一次请求可见）→ 搜索/交付 → 保存”的完整
隔离证据。**它不是真实模型采用，也不是任务成功。**

该端到端测试在隔离目录中使用了
`--dangerously-bypass-approvals-and-sandbox`，只是为了让 mock MCP 写入隔离
数据库和 hook 状态；它不是安装器或生产运行的推荐方式。测试没有向真实
OpenAI 模型发起请求。

### 6.4 失败/降级核对

- `tool_name=Bash` 的 trace：`response_type=string`，无结构化错误码；
- MCP `status=failed` 的调用未触发 hook；同一 payload 改为
  `status=completed` + `structuredContent.error` 后触发；
- 没有 Agent 工具可见性查询时，提示包含“不可用则继续”的降级路径；
- 没有任务结果通道时，`adoption`/`task_outcome` 保持 `unknown`。

## 7. 修改清单

正式新增（本地未提交）：

| 文件 | 作用 |
|---|---|
| `integrations/codex/src/toolseed-hook.mjs` | hook 入口 |
| `integrations/codex/src/opportunities.mjs` | 规则、提示、去重、ToolSeed 阶段 |
| `integrations/codex/src/state.mjs` | 状态、锁、清理 |
| `integrations/codex/src/logging.mjs` | JSONL 阶段日志 |
| `integrations/codex/src/paths.mjs` | `CODEX_HOME` / data dir |
| `integrations/codex/src/install.mjs` | 安装、原生信任、合并 |
| `integrations/codex/src/verify.mjs` | 只读自检 |
| `integrations/codex/src/app-server-client.mjs` | app-server loopback JSON-RPC |
| `integrations/codex/src/host-capabilities.mjs` | 能力声明 |
| `integrations/codex/mcp.toml.example` | MCP 配置模板 |
| `integrations/codex/README.md` | 接入与限制 |
| `docs/CODEX-ADAPTER.md` | 本文件 |
| `README.md` | 指向本适配器的入口说明 |

本地测试（按用户要求不提交）：

- `integrations/codex/test/opportunities.test.mjs`
- `integrations/codex/test/install.test.mjs`
- `.test-data/codex-*` 下的 mock、临时 `CODEX_HOME`、数据库与日志

未修改：Core、Schema、MCP 服务、公共四工具协议、DSH 适配层、DSH 生产配置。
未执行：`git commit`、`git push`、Tag、PyPI/Release 发布。

## 8. 未完成项

- 真实模型/真实 Codex 会话中的自主检索、实际采用、后续独立任务复用；
- 真实模型对提示的忽略率、成本与净收益；
- Bash/命令执行的通用结构化失败通道（本版本没有；不解析自由文本）；
- `status: failed` MCP 调用的 hook 覆盖（本版本未观察到）；
- 其他 Codex 版本/平台/App 与 CLI 差异；
- Codex 原生管理面板（无已核实公共契约）；
- Codex Adapter 的正式发布与跨平台安装矩阵。
