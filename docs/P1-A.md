# P1-A：重复阻塞驱动的能力机会提示

后续增量：[默认关闭的触发诊断观测](P1-A-DIAGNOSTICS.md)补充跳过原因、去重和提示提交元数据，
不改变本页的触发阈值或提示内容，也不改变两个原始故障场景仍待真实事件证据的状态。

2026-10-22，本地开发，尚未提交或发布。基线为 `develop` 的
`f63c007284b592bd4c07d0509f1c753d6c7b571f` 和进入本轮前已有的工作区成果。

已实现可运行的 DSH 事件到机会提示切片。**宿主机制与真实 MCP 链路通过验证；真实模型的自主
检索、实际采用、已验证方法沉淀及未来复用行为仍未验收。** 不宣称 P1 整体完成或净收益成立。

## 现状核对与本轮范围

依据 DESIGN §4.3–4.7、§15、§21、§27 及 P0-SLIM、Skill 和实际代码：

| 层次 | 本轮之前已经实现 | 本轮之前缺口 / 仍未实现 |
| --- | --- | --- |
| Core | 四工具；Procedure 契约、关键词检索、适用性硬筛选、namespace；不可变版本、精确去重与重复提示；证据有效性、观察、维护决策、诊断与修复候选、晋升门禁 | 不观察宿主正常任务，不替 Agent 判断复用价值；不执行 Procedure |
| Skill | L0/L1/L2、实际加载宿主 Skill、按需检索、适用性检查、验证后保存和阶段声明纪律 | 静态指令不保证被实际加载或遵循；没有运行时机会信号 |
| 通用 Adapter / MCP | `LocalAdapter` 与官方 MCP stdio，固定四工具；明确声明无 Hook、无可靠任务结束或结果通道 | 不具备自动宿主事件捕获；本轮保持该声明和路径 |
| DSH 插件 | 设置中的只读能力 / 活动页面，共享查询与主题；无 Agent 事件逻辑 | 本轮增加可解释、低成本的事件到提示连接 |
| 完整 P1 设计 | 现有维护/证据机制已实现一部分，不能将设计清单视为全部交付 | 多类型开放域机会发现、结构化解决方案提炼、可靠任务边界/采用/结果关联、真实主动沉淀与成本收益实证仍缺 |

DESIGN §29 的完整 Hook 能力是后续演进方向；本轮按用户明确授权，只实现 §4.5/4.7 允许的
薄 Adapter 提示，不新增通用状态机、模型分类器、维护机制、Schema 或公共协议。

## 宿主契约依据

本机安装包 `F:\DeepSeek Harness\resources\runtime\primary-runtime\runtime.json` 和随包
`@deepseek-ai/dsh-agent` / `dsh-tools` / `dsh-mcp-client` / `dsh-session` 的 README、公开导出及实现，
版本均核对为 **0.2.1-rc.2**。只读检查安装包，没有修改宿主源码或配置。

- `tools/result(exec, result)`：观察冻结的最终工具结果。使用真实 `exec.token` 去重；结构化错误码
  为 **`result.error.info.code`**，不能从错误文本猜测。
- `agent/pre-step(payload, next)`：保留后续策略的 reject、消息与请求系列标记，只在正常 enter
  决策中附加一个有 ID / source 的 user context 消息；不调用 followup、steer 或模型。
- `session/event(session, event)`：**`user/message` 的 `event.data` 就是消息**。只在匹配的消息 ID
  真正提交时记录 `opportunity_prompted`；提出提示不等于提交，也不等于模型已消费或遵循。
- `agent/disposed` 与 Cordis effect：清理本地状态和监听器；稳定 Session ID 用于会话消息关联。
- `tools.get(name, agent)`：沿用宿主可见性筛选。工具不可见时不提示其可用，更不绕过权限调用。
- DSH MCP 的公开名称为 `mcp__<serverName>__<rawName>`；返回 canonical value 包含
  `structuredContent` 或 `content`。仅检查配置的 ToolSeed 服务器的有界 JSON 结果，不收集参数。
- `agent/turn-stopping` 是回合准备结束，不代表原任务达成。未据此伪造任务结果，也未新增结束后的模型回合。

官方参考：[工具运行时](https://deepseek-harness.github.io/deepseek-harness/en/reference/subsystems/tools)、
[Agent 接口与事件](https://deepseek-harness.github.io/deepseek-harness/en/reference/subsystems/core)、
[插件生命周期](https://deepseek-harness.github.io/deepseek-harness/en/develop/basic/)。网站内容会变化，
本轮以安装版本为准。运行时核对副本与本轮原始结果保存在仓库外审查目录
`C:\Users\xiazi\.codex\visualizations\2026\10\21\01a15e1f-173b-7b83-a774-4ac45e99df34\toolseed-p1a-20261022`。

## 实际触发与降级

1. 同一个活跃 Agent 回合内，同一工具与同一结构化错误码累计 **3 个不同执行 token** 的失败，
   记录 `signal_detected`，只说明可能存在重复阻塞，不断言同一根因或能力缺陷。
2. 普通成功、1–2 次失败、非结构化错误、取消、PTC 外层传输、ToolSeed 本身失败都不触发。
   最多观察 256 次执行 / 16 个错误组；达到上限不淘汰 token 后重新计数，而是停止观察。
3. 后续正常步骤若被宿主策略接受且 ToolSeed 检索工具可见，附加一次 **L1** 短提示；已经出现
   的信号后检索抑制另一次提示。同一回合最多提示一次，不在空闲时唤醒 Agent、不自动重试搜索。
4. 提示要求真正加载适用 Skill，按当前问题检索，检查适用条件、权限及证据；无匹配或失败时继续原任务。
   实际解决并验证、有复用价值时才按现有契约保存并确认，可不保存。L2 仍由 Agent 根据成本和风险决定。
5. 使用现有工具观察 `search_completed/failed/result_unknown`、`capability_saved`、
   `existing_version_returned`、`save_failed/result_unknown`、`guidance_delivered` 等阶段。
   同回合相关不等于因果证据；采用、验证和任务结果没有独立证据时保持未知。

机会日志走 DSH 已有 logger，含规则、时间、阶段、关联 ID 和必要计数；不默认记录提示词、
工具参数、错误自由文本、Procedure 正文或推理。固定机会提示由宿主正常消息日志留存。
日志持久化/保留期限服从宿主配置，不承诺新的历史归档。机会元数据不写入 Core 的 evidence_events，
因此不产生新的待评估证据或维护建议；Core 仍记录真正的搜索、保存、交付等现有事件。
GUI 暂不展示这组宿主日志，底层已有证据查询保留。

没有 Agent/tools 服务的宿主不启用这段可选注入；没有 ToolSeed 工具则记录 `prompt_unavailable`。
Codex、Claude Code 和通用 MCP 的现有路径不变，本轮不声称它们新增了自动 Hook 支持。

## 修改文件

| 文件 | 作用 |
| --- | --- |
| `integrations/dsh/opportunities.js` | 独立 DSH 规则、去重、机会提示、真实消息提交及调用阶段观察 |
| `integrations/dsh/index.js` | 保留只读查询，按可选 `agents/tools` 依赖安装 Adapter；配置开关及 MCP server 名 |
| `integrations/dsh/package.json` | 将 Adapter 文件列入原有插件打包清单 |
| `integrations/dsh/test/opportunities.test.mjs` | 17 项信号、负向、去重、安全、失败恢复、隔离及打包定向测试 |
| `integrations/dsh/test/host-opportunities.mjs` | 可复跑的隔离真实 DSH / MCP 集成探针；脚本驱动，无模型请求 |
| `toolseed/skill/SKILL.md`、`tests/test_skill_contract.py` | 修正一处成功保存确认字段偏差，并用真实 Core 回复回归测试 |
| `integrations/dsh/README.md` | 触发路径、配置、可观察性与宿主限制 |
| `README.md`、`docs/ALPHA-STATUS.md`、`docs/P1-A.md` | 增量入口、当前状态与本交付记录 |

本轮没有修改 Core、通用 Adapter、MCP、Schema v6、GUI 样式或只读 HTTP 安全边界。
进入本轮前有 7 个已跟踪修改和 60 个未跟踪文件，均保留；README / Alpha 文档只增加本轮说明。

核对发现既有 Skill 要求成功保存含 `ok: true`，而实际 `ToolSeed._accepted()` 及其调用路径
返回 `status: accepted`、ID、版本状态，不含 `ok`。仅将 Skill 的这一句改为依据实际成功回复确认；
未改写其他规则，也未改工具协议。新增测试真实调用 Core 对照回复与说明。随包资源仍由
`pyproject.toml` 的 `skill/*.md` 直接取源码，无第二份源码副本；没有重建历史发行包或改动已安装副本。
本地 editable 安装通过 `importlib.resources.files('toolseed')` 读取的 Skill 与源码逐字节一致
（8,205 字节，修改前为 8,170 字节）。独立复制到宿主的 Skill 需按原宿主机制更新/重新加载；
本轮没有覆盖这些用户文件，也不声称历史安装副本已自动同步。

## 本地试用

已有插件本地链接可在 DSH 重启后加载增量，不需要重建未修改的前端。已有 ToolSeed MCP
必须使用面板相同的数据目录，并向目标 Agent 暴露原来的四工具。按宿主规则安装并加载 Skill。
在插件原有官方配置中可增加：

```yaml
config:
  python: 'F:/ToolSeed/.venv311/Scripts/python.exe'
  dataDir: 'F:/ToolSeed/.toolseed'
  opportunities: true
  mcpServer: toolseed
```

保留现有 python/dataDir 值；上面只是已有契约的配置示例，不会替用户安装 MCP 或更改权限。
不支持 Hook 的宿主仍使用 CLI / MCP / 可选 GUI。面板继续从 **设置 → ToolSeed** 打开，
独立 GUI 仍用 `toolseed ui --data-dir <同一目录>`。

## 验证证据与成本

| 实际命令 | 结果 | 退出码 |
| --- | --- | ---: |
| `node --test integrations/dsh/test/backend.test.mjs integrations/dsh/test/opportunities.test.mjs` | 28 通过，0 失败，0 跳过（其中新增 17） | 0 |
| `.venv/Scripts/python.exe -X utf8 -m unittest tests.test_adapter tests.test_mcp_server tests.test_search tests.test_delivery tests.test_activity_recording tests.test_ui tests.test_management -q` | 77 项：76 通过，0 失败，1 跳过；跳过的是已安装 SDK 时不适用的 missing-SDK 分支 | 0 |
| `.venv/Scripts/python.exe -X utf8 -m unittest tests.test_skill_contract -q` | 9 通过，0 失败，0 跳过（新增 1 项成功回复契约检查） | 0 |
| `node --check` 分别检查 `opportunities.js`、`index.js`、两个新增测试文件 | 4 个语法检查通过 | 0 |
| 下方安装运行时探针命令 | 真实 DSH AgentLoop / ToolRuntime + 真实 ToolSeed MCP stdio 链路通过，脚本驱动；普通任务 1 步、阻塞任务 4 步 | 0 |

运行宿主探针（PowerShell，Electron-as-Node 与官方 dsh.cmd 使用同一启动方式）：

```powershell
$env:ELECTRON_RUN_AS_NODE = '1'
& 'F:/DeepSeek Harness/DeepSeek Harness.exe' --expose-internals `
  'F:/ToolSeed/integrations/dsh/test/host-opportunities.mjs' `
  'F:/DeepSeek Harness/resources/app.asar' 'F:/ToolSeed/.venv/Scripts/python.exe' | Out-String
exit $LASTEXITCODE
```

探针只读加载安装包公共导出，使用唯一新建的 `tests/.data/p1a-host-*` 数据库，保留该库作为
检查材料；无浏览器/服务监听、无模型网络请求、不接触用户 Desktop 进程、配置或能力库。
真实规则观察到宿主产生的 3 次 UNKNOWN_TOOL 失败；脚本驱动只在收到提示后请求真实 MCP 搜索，
故不需要用户直接提醒 ToolSeed。它还故意提交空 candidate，被真实 Core 拒绝后正常结束回合。

最终探针原始 `host-integration.json`：全程约 **1,428 ms**（包含 MCP 启动和两组脚本任务，不代表
纯规则耗时）；5 次脚本适配器请求，不是 5 次真实模型调用。实际模型/网络调用 **0**。
提示后、检索前 Core evidence 仍为 0；最终只新增真实搜索和失败保存两条事件，
`unassessed=1` 来自搜索事件，失败活动不参与评估。能力/版本、交付、任务结果信号、验证和演进决策
均为 0；这些是临时空库的真实数值，不将其解释为任务失败或成功。

触发器自身直接新增模型调用 **0**；L0 不注入提示。默认 server 名下每次提示 **420 个 Unicode
字符 / 1,018 UTF-8 字节**，每回合最多一次。没有新增常驻 Skill 或 MCP Schema；提示进入宿主
历史后可能在后续请求中被重发，实际累计 Token、模型因采纳提示增加的步骤/检索/保存成本、
规则 CPU/内存实测和净收益均为 **unknown**，不能仅按一次提示字节数计算总成本。

失败记录：最初沙箱中 Python 回归 16 项有 3 个错误、1 个跳过，原因是 MCP 依赖的原生 DLL
加载受限；相应 DSH MCP 子进程也连接关闭，已在获准的沙箱外定向验证。初版探针还暴露了
测试启动生命周期错误，以及错误码嵌套和会话消息形状的假设错误，均按当前公开运行时修正后复跑通过。
新增契约测试后，首次文档检查有 2 项失败，指向套件收录数仍为 289；已同步为实际收录的 290，
并保留“非本轮全量执行结果”的声明，没有重跑全套测试或将收录数冒充通过数。
文本规则测试不作为真实模型行为证据。没有运行全量质量门禁、A/B、真实模型价值实验或发布构建。

## 剩余限制与下一步

- 本轮只识别同回合重复结构化工具失败，不解析 shell 内容/退出码嵌套结果，不识别无失败的
  高成本诊断、跨回合重复劳动或一次性高复用机会。相同工具/错误码未必是同一问题，Agent 可拒绝提示。
- 回合不是可靠业务任务边界。没有可靠任务成功或采用信号；不将结束、保存、ready 或交付改写为这些结论。
- 没有实现自动抽象/自动保存、L2 费用计量、完整 executable / workflow、多主体治理或全文轨迹分析。
- 尚未在用户 live Desktop 会话或真实模型上验收 Skill 加载、主动检索、验证后保存和后续实际复用；
  隔离运行时机制通过不能代替该验收。现有部署需重启并确认目标 Agent 的 MCP 工具可见。

下一项最有价值的 P1 工作是**小规模真实 Agent 行为验收与成本计量**，而不是扩大规则数量：
在隔离数据目录和同一已配置宿主中，分别覆盖已知适用能力、空库但值得验证沉淀、普通一次性任务；
不在用户任务中提醒 ToolSeed。记录宿主真实 Skill 加载、工具调用、执行/验证及后续新输入的采用证据，
分开记录结果来源和 Token/上下文开销；允许不采用/不保存。该验收尚未执行，需人工审查后另行开展。

本轮停止，不提交、不推送、不打 Tag、不发布，等待人工架构审查。

最终工作区核对：本轮实际涉及 **11 个文件**（7 个已有文件做局部修改、4 个新文件），没有
意外修改或缺失；其余进入本轮前的 112 个正式文件内容哈希不变，Core / MCP / GUI 资源均在其中。
Skill 只将本轮确认句逆替换后，其哈希与进入本轮前完全相同，保留了此前尚未提交的整体优化。
分支与 HEAD 不变，`.git/HEAD`、index、config 哈希不变，暂存区为空；最终 8 个已跟踪修改、
64 个未跟踪文件。完整比较见仓库外 `final-worktree.json`，`git diff --check` 退出码为 0。
