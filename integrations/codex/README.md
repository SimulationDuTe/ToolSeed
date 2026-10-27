# ToolSeed Codex adapter

接入 Codex CLI / App 共享的 Hook、Skill 和 MCP 接口，让宿主模型在合适时机复用方法、记录错误教训和工具用法，并向原能力回流观察。当前为本地未发布增量。

## 工作方式

| 事件 | 行为 |
|---|---|
| `UserPromptSubmit` | 从当前任务提取短查询，实际检索本地能力库，返回少量候选 |
| `PostToolUse` | 新结构化错误或 MCP 工具线索触发检索；复杂操作后提示选择跳过、复用、修订或提炼 |
| `PostToolUse` | 捕获 `toolbox_run` 的真实交付标识；后续操作后提示向原能力提交复用观察 |
| `Interrupt` | 取消 Hook 自己启动的查询，禁止该轮迟到上下文 |
| `SessionEnd` | 关闭待反馈状态，不唤醒模型 |

自动召回通过受信 Hook 调用显式 Python 的 `toolseed search --read-only`。这是本地只读 Core 查询，**不是模型发起的 MCP 调用**。使用与 MCP 相同的绝对数据目录及支持新接口的 Python 环境。

能力是否适用、是否采用、是否值得沉淀，由宿主模型判断。读取完整方法用 `toolbox_run`；提炼或追加反馈用第五个公共工具 `toolbox_learn`。脚本可有可无。交付、活动计数、模型自述都不能代替独立验证。

## 安装

先配置 ToolSeed MCP（见 [示例](mcp.toml.example)），再安装适配层。Python 必须能导入当前 ToolSeed，Node 22+ 用于 app-server 的 WebSocket 查询。

默认只展示计划：

```powershell
node integrations/codex/src/install.mjs `
  --codex-home "$env:USERPROFILE\.codex" `
  --python "C:/absolute/runtime/Scripts/python.exe" `
  --data-dir "C:/absolute/capability-library" `
  --codex "C:/absolute/path/codex.exe"
```

确认计划后同一命令加 `--apply`。统一安装器的 `--python` 也会传入 Hook：

```powershell
toolseed install codex --ref F:/ToolSeed `
  --python "C:/absolute/runtime/Scripts/python.exe" `
  --data-dir "C:/absolute/capability-library"
```

安装器备份被改动的 Skill、hooks.json 与 AGENTS.md；保留其他 Hook 和 AGENTS.md 未标记内容。它合并四个事件处理器，复制 Skill，然后通过 Codex `hooks/list` 获取每个处理器的真实 key/hash，用 `config/batchWrite` 记录原生信任，并复查四项均为 trusted。不会修改 MCP 或 DSH 配置。Codex 可能在写信任时规范化 config.toml，并初始化该 CODEX_HOME 的状态。

可用选项：`--json`、`--no-trust`（由 Codex 正常批准）、`--no-agents-md`、`--mcp-server`、`--node`、`--python`、`--skill-source`、`--hook-script`。Hook 入口另支持 `--no-recall`、`--no-learning`、`--namespace`、`--no-log`。不要把绕过 Hook 信任作为安装方式。

新建 Codex 会话加载新 Skill / MCP 工具；安装器不重启用户会话。

## 约束与数据

每轮最多 3 次查询、每次最多 2 张卡片；单次查询默认 1500 ms。查询失败关闭该轮自动召回，原任务继续。相同提示、查询、错误组、版本及工具执行标识去重。

只读连接使用 SQLite `mode=ro`、`query_only` 和事务快照，不建库、不迁移、不创建交付或证据。缺库、结构不兼容或不可读时不输出候选。查询沿用 Core 的 namespace、生命周期、适用条件和保守匹配过滤。Hook 无法读取每个 Agent 的工具可见性，因此传入的是不完整工具清单，未知条件仍需模型核对。

复杂操作提示：已观察到结构化失败且另有正常返回，或至少 6 次操作涉及至少 2 个工具，或单工具至少 8 次操作。普通返回不代表成功。一次提示后可跳过，无需为学习增加推理轮次；没有 Stop 驱动的自动续跑。

完整方法交付后，最多保留 4 组 capability / invocation / version / hash 标识。后续有实际工具活动或用户补充才提示复用反馈。`toolbox_learn` 仍校验原交付绑定，匹配的已接受反馈才关闭对应项。修订保留候选及原验证门禁，DSH 专用修订执行工具没有移植为 Codex 原生工具。

状态与阶段日志位于 `$CODEX_HOME/.toolseed-codex/`。仅保留计数、工具名、查询哈希和交付标识；不保存原始提示、工具参数或结果、候选正文、transcript 或隐藏推理。任务查询在内存中提取有限关键词并去掉常见凭据格式；本地只读查询不发送网络请求。日志轮转，状态 24 小时后清理。不要在正常使用中设置诊断用的 `TOOLSEED_CODEX_TRACE`。

## 验证与限制

```powershell
node integrations/codex/src/verify.mjs --codex-home "$env:USERPROFILE\.codex" `
  --data-dir "C:/absolute/capability-library" --json
node --test integrations/codex/test/*.test.mjs
```

当前验证目标为 Windows Codex CLI `0.164.0-alpha.11.1`。具体执行范围和部署记录见 [Codex 工作流](../../docs/CODEX-WORKFLOW.md)。旧版 `0.163.0-alpha.11` 的机会提示记录见 [历史交付](../../docs/CODEX-ADAPTER.md)。App 当前 UI 不单独声称已经验收。

Hook 返回上下文没有宿主确认回执，日志记为 `host_receipt=unknown`。原生端到端测试可以检查内容是否进入模型请求，但不能据此推断真实模型会主动提炼或采用。Codex 不保证所有传输失败都产生 PostToolUse；不解析自由文本 shell 错误。无自定义原生设置面板、通用权限确认接口或可靠任务结果通道。

契约依据：[OpenAI 官方 Hooks 文档](https://learn.chatgpt.com/docs/hooks)。
