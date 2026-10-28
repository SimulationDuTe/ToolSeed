# ToolSeed Alpha 状态说明

> 2026-10-28 已拆分 Core 的学习、候选、生命周期、证据、维护与交付服务，保留统一门面；
> DSH/Codex 共用经验提炼及复用反馈状态规则。接口、事务和宿主打包验证见
> [架构重构记录](ARCHITECTURE-REFACTOR.md)。本轮没有新增数据库迁移。

> 2026-10-28 后续已修复同版本运行配置更新，并提供 `--repair`；新经验保留版本绑定结构，
> 高影响错误反例经过独立验证后可复用；召回增加中英文概念和别名，移除按能力逐条读取。
> Schema 升级为 v7；当前源码修复与验证范围见 [后三项修复](LAST-THREE-FIXES.md)。

> 2026-10-28 已加固完整修订的读取基线、DSH 手动采用后的用户纠正反馈、Codex 运行就绪判断，
> 并将可移植宿主测试纳入仓库与 CI。行为和兼容说明见 [前四项修复](FIRST-FOUR-FIXES.md)。

> 2026-10-27 Codex 接入任务召回、经验提炼提示与原能力复用反馈；使用受信 Hook 的本地只读查询。
> 四个原生事件的信任、实际运行及部署范围见 [CODEX-WORKFLOW.md](CODEX-WORKFLOW.md)。

> 2026-10-27 两轮真实模型修复任务已跑通：A 自主提炼方法，B 新会话主动召回、读取并采用，再向原能力追加观察。
> 外部检查共 20 个案例通过，库中保持 1 个能力、1 个版本。范围是隔离的真实 DSH headless，见[实测记录](../benchmarks/results/dsh-experience-2026-10-27/REPORT.md)。

> 2026-10-27 本地 DSH 部署已完成：新版插件、Skill 及实际 MCP 工具注册已核对；
> 部署范围与真实模型行为的验证边界见 [DSH-DEPLOYMENT.md](DSH-DEPLOYMENT.md)。

> 2026-10-26 修订生效增量（未发布）：DSH 原生验证工具通过宿主执行新场景与回归检查，
> 全部通过才切换当前版本；失败保留旧版及检查事实。见 [REVISION-ACTIVATION.md](REVISION-ACTIVATION.md)。

> 2026-10-25 复用更新增量（未发布）：`toolbox_learn` 支持绑定交付记录向原能力追加观察或提出
> 增量修订；后续检索和交付可见近期使用观察。见 [REUSE-UPDATES.md](REUSE-UPDATES.md)。

> 2026-10-25 主动召回增量（未发布）：DSH 在任务开始、工具错误和工具线索变化时通过宿主
> 工具运行时自动检索，并向正常推理步骤注入少量候选。见 [PROACTIVE-RECALL.md](PROACTIVE-RECALL.md)。

> 2026-10-25 学习入口增量（未发布）：新增第五个公共工具 `toolbox_learn`，支持方法、失败教训和
> 工具用法入库；DSH 新增任务活动到提炼提示的接入。范围与使用见 [EXPERIENCE-LEARNING.md](EXPERIENCE-LEARNING.md)。

> P1-A 本地开发增量（2026-10-22，未发布）：已加入 DSH 0.2.1-rc.2 的重复结构化失败信号与
> 单次 L1 机会提示。隔离的真实宿主运行时、MCP 和脚本驱动验证了信号、提示提交、检索及保存失败恢复；
> 真实模型的主动发现、实际采用、已验证方法沉淀和净收益仍未验收。详见 [P1-A.md](P1-A.md)。

日期：2026-10-22。当前包版本 `0.4.1`；本地交互层开发以已发布的 v0.4.1
（`5786f47`）为基线，尚未提交或发布，不代表历史 Release 已包含以下新增面板。

本文件只说明**当前处于什么状态**，不新增契约、不放宽既有约束。实现与验收范围仍以
[P0-SLIM.md](P0-SLIM.md) 为准，长期设计见 [DESIGN.md](DESIGN.md)；两者范围不一致时以
P0-SLIM 为准；第五个学习工具及宿主触发增量以 [经验学习](EXPERIENCE-LEARNING.md) 补充。使用方法见 [README 的 Alpha 快速上手](../README.md#alpha-快速上手)，
Agent 行为规约见随包分发的 [Skill](../toolseed/skill/SKILL.md)。

## 1. 一句话状态

ToolSeed 已是可供真实 Agent 工作使用的 **Alpha**：五个公共工具、经验提炼入口与 Procedure 的保存/检索/交付、
不可变版本与内容哈希、证据分离与 `unknown` 纪律、本地 SQLite 持久化与官方 MCP stdio 服务
都已实现并被验证；真实 Agent 工作中已观察到跨任务 Procedure 复用；但**净收益尚未被证明**，
当前只能声明"机制可运行且复用可发生"。

## 2. 已实现且经过验证的机制

| 机制 | 验证方式 |
|---|---|
| 五个公共工具（`toolbox_search`/`toolbox_save`/`toolbox_run`/`toolbox_stats`/`toolbox_learn`） | 契约测试固定工具名；官方 MCP 客户端枚举与学习 schema/调用测试 |
| 单 candidate 传输格式与 Manifest 契约（含字段长度上限、未知字段拒绝、唯一 `kind=procedure`） | 契约测试与 Core 内唯一权威校验模块 |
| 稳定身份、不可变版本、确定性 `content_hash`、精确重复不新建版本 | 版本与持久化测试 |
| 先硬筛选后关键词排序的检索，允许空结果，默认 3 条 / 上限 5 条 | 检索测试 |
| Procedure 交付语义（`mode=agent_guided`、`guidance_delivered`、`task_outcome=unknown`） | 交付与证据测试 |
| Invocation 与追加式 Evidence；无外部信号时保持 `unknown` | 证据测试；`toolbox_stats` 区分 `signals`/`measured` |
| 能力/版本级隔离、退役、候选提升与回滚、失败诊断与修复候选、维护决策与观察 | P1 相关测试组 |
| 本地 SQLite 持久化、共享数据目录、namespace 隔离、schema 迁移与并发唯一性 | 迁移/并发/持久化测试 |
| `toolseed-mcp` stdio 服务 | 官方 SDK 客户端验证五个工具；本轮本地 stdio 子进程覆盖保存、学习、检索、交付与适用条件门禁；无本轮 CI 运行记录 |
| 发布包形态（wheel 内含 Skill、entry point、非 editable 安装） | `scripts/package_smoke.py`、`scripts/verify_release.py`；CI `package` job 执行同一套检查（工作流配置，本轮无 CI 运行记录） |
| 只读管理 CLI：status / capabilities list、show / activity / evidence / ui | 真实临时库、目录隔离、环境变量优先级、生命周期门禁、无写入、错误与帮助测试 |
| DSH Desktop 0.2.1-rc.2 原生 ToolSeed 插件设置页 | 官方 settings.section、宿主 IPC 查询；同文档原生控件与主题令牌；“已入库能力”/“活动”两页，详情含验证、历史及高级信息；隔离同版 DSH 验证外观同步 |
| 可选独立 Web GUI | 复用两页及详情展示、固定 loopback、HTTP 安全测试；沿用 [GUI.md](GUI.md) 的证据边界 |

本地回归：417 项测试（Python 当前套件收录数，含宿主打包完整性回归；本轮见 [后三项修复](LAST-THREE-FIXES.md)，此前增量见 [修订生效](REVISION-ACTIVATION.md)、[复用后更新](REUSE-UPDATES.md)、[主动召回](PROACTIVE-RECALL.md)、[经验学习](EXPERIENCE-LEARNING.md) 与 [PHASE-ONE.md](PHASE-ONE.md)）。此前基线的 252 项测试已通过
（2 项按条件跳过）；GUI 开发仅执行相关定向测试，见 [GUI 验证说明](GUI.md)。
具体范围见 [README 测试章节](../README.md#测试)。
DSH 插件现有 11 项 Node 定向测试。本轮 UI 简化运行 26 项 GUI/管理 Python 测试及 4 项文档契约测试。
实际截图与本轮检查边界见 [PANEL-SIMPLIFICATION.md](PANEL-SIMPLIFICATION.md)。
范围和宿主契约依据见
[AGENT-INTERFACES.md](AGENT-INTERFACES.md)；未重新开展 A/B 实验或全量质量门禁。

## 3. 已在真实 Agent 中观察到的能力复用

在一轮有明确终点的限范围真实实验中（8 次任务、2 组、每组 1 个初始任务 + 3 个变体），
首次观察到完整的能力复用生命周期：

- B 组在初始任务保存 1 个 Procedure，后续 3 个任务各检索命中并交付（3 次 Invocation），
  3 次都实际采用了交付内容，且**没有**再保存近似副本；
- 同一批 8 个任务在两组都由独立裁判判定通过，交付链路的四工具与结构化 stats 在
  干净安装、外部工作目录、含空格与非 ASCII 路径等形态下均成立；
- A 组未注册方法库，方法库调用为零；能力库与被测软件状态目录保持分离。

完整记录见 [benchmarks/results/agent-reuse-final-2026-10-21/REPORT.md](../benchmarks/results/agent-reuse-final-2026-10-21/REPORT.md)。

**这证明的是机制可运行、复用可发生，不是"复用有正收益"。**
被检索命中、被交付、被采用，三者都不等于任务成功；缺少可信外部结果信号时，
Core 一律保持 `unknown`。

## 4. 尚未证明的净收益

- 上述实验中，使用方法库的 B 组在模型结算次数、请求 Token、工具调用与墙钟时间上
  **均高于**对照组，没有出现可测的成本下降；两组任务结果没有差异。
- provider 侧计费 Token、服务端实际计费、失败/取消尝试的真实用量仍然不可得
  （SDK 规范化用量是派生字段，不是账单）。因此货币净收益为 `unknown`，
  不得以"零值"或"免费路由"充当已证明的成本优势。
- 样本极小（8 个任务、1 个被保存并复用的能力）、执行顺序非随机化、
  失败/重试次数在两组间不均衡，净收益无法归因到方法库本身。
- 结论：**机制闭环成立；收益结论不成立，也不应被表述为成立。**

## 5. 当前不支持的功能

- 不执行代码：不提供 `executable`、Python Runtime、任意代码执行或沙箱；
  `kind` 不是 `procedure` 时返回 `UNSUPPORTED_CAPABILITY_KIND`，不静默降级。
- 不支持多文件或 ZIP 能力包、`workflow`、异步保存队列、多用户 RBAC、检索缓存、
  向量检索或 LLM 重排、自动反思/自动修复。
- 不提供额外的 Agent 管理工具：管理操作（隔离、解除、提升、归档、诊断、维护）只在本地
  管理 CLI/Adapter 侧可用。
- 不提供跨主机的统一可移植性保证：同一能力库可被多个宿主共享，但每次执行仍要检查
  运行时、权限、依赖、工作区与宿主能力兼容性。
- 宿主接入的验证程度有限：DSH 0.2.1-rc.2 的设置页面与主题同步已用同版本隔离 Web 客户端检查，
  没有重启或操作用户当前 Desktop 会话；重启后加载更新。Codex CLI
  0.163.0-alpha.11、Claude Code 2.1.150 保留 MCP 与管理 CLI，未实现原生面板。
  ChatGPT 的组件 UI 不作为 Codex 面板能力的依据；其他客户端尚未逐个人工确认。
- 不做安全沙箱：保存的 Procedure 是**不可信数据**，只作为能力材料交付。

## 6. 已知限制

- **成本与用量不可审计**：宿主不暴露精确 Token 与计费时，相关字段保持 `unknown`；
  失败或取消尝试的规范化用量可能为零值，不能解释为真实零成本。
- **内容检查不等于内容可信**：长度、结构与敏感内容静态检查通过，不代表方法正确、
  已被外部事实核实或适用于所有任务；`version_status: ready` 只表示通过结构门槛。
- **共享目录即共享状态**：多个宿主指向同一 `--data-dir` 会共享同一能力库；
  迁移冲突时 MCP/CLI 会提示并以非零状态退出，需要显式 `migrate-check`/`migrate-repair`。
- **单用户单受信主体**：本地存储受当前用户权限保护，不是多租户服务。
- **版本不可原地修改**：修订必须显式指定 `target_capability_id` 并生成新版本，
  候选版本需独立验证与提升后才成为当前版本。
- **证据成熟度与自动维护有限**：P1 只提供评估、维护报告与观察，不做自动结论合成；
  旧格式维护决策缺记录顺序标记时一律 fail-closed。
- **实验结论的边界**：第 3 节的能力复用来自单一任务族、单一执行顺序与 8 个任务；
  不得外推为普遍泛化、自主进化或长期学习能力。

## 7. Alpha 交付结论

机制、协议与使用路径已达到可交付状态：可作为 Alpha 供真实 Agent 工作试用与评估。
同时明确：本 Alpha **不承诺**净收益、不承诺自治改进、不承诺跨主机可移植；
若要评估收益，需要先补齐 provider 侧用量证据（见
[benchmarks/reviews/usage-evidence-closure-2026-10-21/REPORT.md](../benchmarks/reviews/usage-evidence-closure-2026-10-21/REPORT.md)）。
