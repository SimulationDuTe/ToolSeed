# ToolSeed 第二轮跨任务复用：可行性与资产审查

审查窗口：2026-10-20 至 2026-10-21，Asia/Shanghai。
指定及实查基线：`c0cac122c1a149e3f6c1a2501a683db323fc5131`，分支 `develop`。

**结论：NOT READY / 不准入正式执行。** 已找到真实重复工作流，以及有希望复用的现成 Harness
能力，但尚未验证选定模型路由的完整日志与用量闭环；当前构建工件也不匹配基线。
本轮没有运行正式实验、接入 canary、LLM 子会话、构建、安装、产品测试或发布操作。
交付的是静态审查和[条件式预注册](PREREGISTRATION.md)，不是第二轮结果。

## 1. 上轮九个文件：保全、内容核对和敏感信息

保留[上轮目录](../../results/agent-reuse-pilot-2026-10-20/)，不重置、不覆盖、不清理。
已在审查前记录全部九个文件的 SHA-256，结束时再核对；指纹及筛查结果见
[资产审查数据](PRIOR_RESULTS_REVIEW.json)。

核对范围包括完整的报告、预注册、中断说明，以及程序化解析的任务规格、逐任务 CSV、
主运行 JSONL、接入试跑 JSONL、汇总及归档索引：

- 主运行记录 18、任务规格 18、CSV 行 18；A/B 各 9 个独立验收通过。
- 保存尝试 0，检索 5，交付与采用 0；18 行均缺 provider Token 与完整 Harness 工具总量。
- 中断任务 8；汇总的净收益为 `unknown`，模型配置一致性未验证。
- 上轮 A 不保留前任务普通工件，B 仅保留空方法库；本方案必须修正这项比较条件。

敏感信息审查结论：

| 项目 | 结果 | 解释 |
|---|---|---|
| 私钥、Bearer、常见 API key/密码字段、sk- 前缀筛查 | 九个文件均无所用模式命中 | 不是秘密不存在的证明，只是静态模式筛查 |
| 本机绝对路径 | 4 个文件、151 处模式引用 | 含工作区路径、解释器路径及本地归档位置；公开前需审定脱敏 |
| UUID | 九个文件未命中 UUID 模式 | 不代表归档中没有会话标识 |
| 运行元数据 | 含模型标签、命令、错误、时间及任务标识 | 可关联本机运行，应纳入公开范围审查 |
| 原始 ZIP 全文 | 未做完整隐私审计 | 不能从九文件筛查推断全部 387 个工件可公开 |

**暂不决定归档或公开提交。** 原件继续本地保留；若人工决定公开，应另建脱敏派生副本，
保留原件哈希和转换说明，尤其复核 ZIP 中的会话标识、日志、附件及 SQLite 内容。
本轮没有脱敏改写原文件，也没有复制整个 ZIP 到新的受跟踪目录。

## 2. 现有运行器和遥测：能力存在，不等于已经就绪

### 2.1 ToolSeed 的现有框架

[CommandAgent](../../live_experiment.py#L224-L308) 能保存任务提示、完整命令 stdout/stderr 文件、
退出/异常信息及命令墙钟时间。但当前实现：

- 不注入或记录完整模型配置，不解析 provider usage，AgentResult.tokens 保持缺省值。
- subprocess 未设置独立任务 cwd；不能仅凭 LIVE_* 环境变量证明 A/B 工作副本隔离。
- raw 字段截断；完整工具账本必须由外部 Agent 本身输出，不能从最终 JSON 反推。
- [run_experiment](../../live_experiment.py#L444-L513) 每个 B 实例手工预置并删除库，
  把交付标成采用，异常路径还有 elapsed=0；均不适合直接用于本轮。
- 本轮 PATH 检查未发现可直接调用的 codex、claude、opencode、aider 或 dsh。
  这不等于宿主没有 Agent 引擎或没有捆绑 CLI。

没有运行该框架：不能让其清理逻辑碰旧数据，也不能用 ScriptedAgent 代替真实测量。

### 2.2 当前 Harness 的只读源码证据

已通过 ASAR 可感知的文件读取核对当前捆绑版本 `0.2.1-rc.2`。普通 glob/rg 不能遍历该
ASAR 虚拟路径，不能据此推断实现不存在。没有读取账户密钥或修改宿主配置。

| 能力 | 实查实现 | 尚缺什么 |
|---|---|---|
| 模型/provider 选择 | [默认选择实现](<F:/DeepSeek Harness/resources/app.asar/dsh/node_modules/@deepseek-ai/dsh-agent-default-model/lib/index.js#L21-L44>)含 provider、model、reasoningEffort | 当前实验专用非敏感配置快照、解析后模型标识及防漂移证明 |
| 独立 SDK 会话 | [SDK initialize](<F:/DeepSeek Harness/resources/app.asar/dsh/node_modules/@deepseek-ai/dsh-sdk-jsonrpc-server/lib/index.js#L120-L146>)接受 cwd/provider/model/reasoningEffort/maxTokens；[新建会话](<F:/DeepSeek Harness/resources/app.asar/dsh/node_modules/@deepseek-ai/dsh-sdk-jsonrpc-server/lib/index.js#L320-L339>)使用这些选择 | 官方支持的本机启动方式、目标 adapter/认证可用性、配置审定 |
| 会话和工具事件 | [SDK 事件转发](<F:/DeepSeek Harness/resources/app.asar/dsh/node_modules/@deepseek-ai/dsh-sdk-jsonrpc-server/lib/index.js#L68-L99>)输出 session.event/status；[日志导出](<F:/DeepSeek Harness/resources/app.asar/dsh/node_modules/@deepseek-ai/dsh-session-log-export/lib/index.js#L8-L22>)可导出规范 JSONL 和子会话 | 选定路由的实际、脱敏样例，完整性/序号及工具 call/result 配对核验 |
| provider Token | [usage 投影](<F:/DeepSeek Harness/resources/app.asar/dsh/node_modules/@deepseek-ai/dsh-token-meter/lib/index.js#L316-L344>)含输入、输出和缓存桶；[重试处理](<F:/DeepSeek Harness/resources/app.asar/dsh/node_modules/@deepseek-ai/dsh-token-meter/lib/index.js#L365-L425>)处理 attempt 与 retry | 实际目标 provider 是否返回每次尝试的 usage，失败/取消是否有缺口，字段口径及计费映射 |
| 工具/模型时间 | [sessionStats](<F:/DeepSeek Harness/resources/app.asar/dsh/node_modules/@deepseek-ai/dsh-session-stats/lib/index.js#L5-L24>)有 step/tool 时间折叠 | 取消的部分模型区间不计入现有投影；完整活跃区间须用原始边界核对，不能直接当总耗时 |
| 工作目录 | [SDK cwd 接口](<F:/DeepSeek Harness/resources/app.asar/dsh/node_modules/@deepseek-ai/dsh-sdk-jsonrpc-server/lib/index.js#L289-L297>)支持会话目录 | 不等于访问控制或工件保留策略已配置、生效 |

重要区别：Token-meter 的上下文占用估算使用字符密度启发式；这**不是** provider 计费 Token。
usage 投影又会对缺省缓存字段取 0。实验必须保留原字段及支持性，不能把缺失字段机械解释为零。
SDK 握手没有展示 temperature/top_p/seed 设置口；不能声称已固定这些参数。

当前供本会话使用的普通 subagent 工具只暴露 prompt/cwd 等，没有模型锁定、原始 usage 和
完整账本返回。workflow 的 provider/model 选项也不自行构成计费/日志闭环。
本轮没有调用任何一种来补做试验。

此外，[sdk-minimal 配置](<F:/DeepSeek Harness/resources/app.asar/dsh/node_modules/@deepseek-ai/dsh-sdk-minimal/cordis.patch.yml#L26-L74>)默认使用 API-key adapter 和 danger-full-access。
**不能原样启动它来绕过本机限制**，也不能假定桌面订阅可直接转成该 SDK 的可计费路由。

### 2.3 当前可用环境的具体缺口

- 审查用解释器为 Python 3.13.1，MCP 分发版本 2.3.0；3.11 解释器文件存在，但本轮没有启动测试。
- [当前元数据](../../../pyproject.toml#L5-L15)版本为 0.4.0，要求 Python >=3.11、mcp>=2.3,<3。
  构建目录实际只有 0.3.0 wheel/sdist，**不能作为 c0cac12 的被测包**。没有构建新包。
- 没有本轮选定 provider/解析后 model/可配置参数、价格与账单映射的冻结记录。
- 没有选定路由的完整事件及失败重试 usage 样例；不能证明当前 UI 显示数字足够。
- 原生 MCP、临时目录及进程管道权限没有完成实验环境准入。
  [现有 smoke](../../../scripts/package_smoke.py#L60-L104)使用 subprocess 捕获和 MCP stdio；
  [测试](../../../tests/test_mcp_server.py#L63-L79)明确记录本地沙箱管道限制。
  skip 不能替代本轮独立通过，不自动申请扩大权限或修权限。

## 3. 不超过三个候选任务族

| 候选 | 真实重复需求与证据 | 可测成本、Procedure 适合度和验收 | 常规复用/限制 | 结论 |
|---|---|---|---|---|
| 干净安装、外部 cwd 与 MCP stdio 交付验收 | [质量 CI](../../../.github/workflows/quality.yml#L13-L51)在 push/PR 做 Python/OS 矩阵；[发布包检查](../../../scripts/verify_release.py)和[smoke](../../../scripts/package_smoke.py)已存在；上轮实际发生外部目录导入失败 | 导入来源、依赖、解释器、入口、环境清洗和协议检查是稳定诊断次序；独立程序可验证；尚未测本族 Token/时间，不声称历史成本数值 | 两组均可复用已有脚本；固定机械检查应继续自动化，Procedure 只处理诊断判断。验收对 ToolSeed 被测软件的调用必须与 B 记忆库分离 | **条件首选** |
| 证据生命周期/决议原子性的回归定位 | Git 历史 0f1648c、c0cac12 是实际已提交修复 | 问题定位、最小复现、事务边界/回滚检查可形成方法，独立测试可验证 | 两类旧修复不等于四个新待办；补丁历史容易泄题，且修复常需要可执行代码/改 Core，不适合当前边界 | 不选 |
| 实验结果与归档的证据审计 | 当前九文件、18+6 记录和 ZIP 是真实审查对象，本次也确有归档审查请求 | 证据资格、unknown、采用链路判断适合 Procedure；数量/哈希检查应脚本化 | 尚无四批独立待审数据。把同一集合任意切四份不能冒充真实重复需求；旧报告也已包含答案 | 保留为以后候选，不选 |

选择理由：首选来自实际维护管线，涉及多步环境判断和独立进程，比两行闭包修复更可能让
Agent 认为保存方法值得；本次明确有三个后续任务，而不只泛称“工作会重复”。
但不承诺其一定保存，更不删除已有验收脚本来人为制造 ToolSeed 优势。

真实性边界：发现的是**现有、会重复的交付流程**，不是四起未披露生产事故或四张已排期待办。
预注册中的后续任务是设计的受控负例/历史错误回放/支持路径验收，不能称为四次真实事故。
如人工只接受四个已在途实际请求，则当前没有足够已确认任务，应继续保持不执行。

## 4. 最低成本替代方案与必要性

不新建通用平台。按优先次序：

1. **先复用 Harness 现成导出能力**：经人工授权，从一个相关、已存在且使用拟选路由的会话取得
   脱敏事件样例及非敏感模型配置；检查请求、usage、工具、重试、失败/取消覆盖，不运行新正式任务。
   不导出无关会话、账户密钥、隐藏推理或私有系统提示。
2. 获取官方支持的 SDK/CLI 启动方式，审定同一 provider/model、工作区权限与原生 MCP 配置。
   优先普通 SDK 配置，而不是直接套用 minimal 的全权限默认值。
3. 若满足要求，只需实验专用薄接线：已有会话/事件导出、按组 cwd、持久工件、B 库及独立验收。
   修正实验调用层的预置/删库和“交付即采用”；不改 Core 或扩建调度/记忆平台。
   **本轮不实现这层接线。**
4. 若宿主路由确实不提供可用 usage，再由人工选择已有、能输出 JSONL 工具事件和 usage 的
   Agent CLI/计费 API 路由；固定配置并附原始样例。不擅自换模型，不用字符估算充当 Token。
5. 若连上述替代条件也拿不到，停止价值执行，保留本方案；普通父子会话只能行为观察，不能
   升格为完整增量成本验证。

## 5. 准入决定与需人工审查的事项

当前：**NO-GO**。不是“已经证明 Harness 不支持”，而是可用运行器与测量闭环尚未得到验证。

必须在任何正式样本前补齐：

- 同一固定路由的模型/参数清单，以及含失败尝试的原始日志与 provider usage 覆盖证明；
- 支持明确工作目录、取消清理、A/B 保留工件及 B 初始空库的运行配置；
- 本轮基线 wheel、依赖锁定/缓存清单与可信独立验收器哈希；
- 能运行 stdio 和临时目录操作的现成权限环境，不绕过或偷偷跳过验收；
- 接受这项受控重复任务计划，并确认：A 可运行对 ToolSeed **被测软件**的共同验收，
  但不把 ToolSeed 当作 Agent 方法库；若“A 不使用”连被测软件调用也禁止，首选任务族不成立；
- 对完整方案的人工架构批准。

货币价格若仍不可获得，应预先声明货币净收益 unknown，最多比较完整 Token/工具/时间成本向量；
若连任务/重试 Token 和完整账本也不可核对，则不准入本轮价值执行。

本轮停止在文档与审查阶段，未改产品或运行器代码，未归档旧件，未提交、推送、打 tag 或发布。
