# ToolSeed 实验运行器：模型与遥测测量准入

日期：2026-10-21。产品基线 `c0cac122c1a149e3f6c1a2501a683db323fc5131`。

**测量准入：PARTIAL。** 现有授权会话证明了实际路由、SDK usage、逻辑重试与工具事件的可观测性，
但失败/取消的真实用量、底层传输请求覆盖及部分成本口径仍不完整，不能判为 READY。
这不是“因 CLI 不在 PATH 而 BLOCKED”，也不授权正式 A/B 或新的计费 canary。

本轮只做静态文档/源码核对和既有日志的只读元数据审计。没有启动 SDK、发送新 session/prompt、
运行子 Agent/canary/正式任务、构建工件、扩大权限或更改认证/模型配置。
[既有可行性审查](../../plans/agent-reuse-round2/FEASIBILITY.md)、
[预注册](../../plans/agent-reuse-round2/PREREGISTRATION.md)及历史结果保持原样。

## 1. 官方支持的 SDK/CLI 与导出方式

### 静态确认

[官方 CLI 说明](<F:/DeepSeek Harness/resources/app.asar/dsh/node_modules/@deepseek-ai/dsh/README.md#L5-L20>)
明确 `dsh` 是受支持的应用入口，SDK 是 profile，不是另一个私有启动 bin：

```text
dsh --profile sdk
```

这是一条**官方文档中的启动方式，不是本轮已执行命令**。SDK 客户端通过 stdio JSON-RPC：

- `initialize`：选择 cwd、provider、model、可选 reasoningEffort/maxTokens，并验证注册路由；
- `session/prompt`：提交任务，会产生模型调用，本轮没有发送；
- `session.event` / `session.status`：获得持久事件和生命周期；
- `session/wait`：等待 session/后代工作结束，不等于按 prompt 自动划定计费边界；
- `shutdown`：排空并释放运行时。

[SDK 说明](<F:/DeepSeek Harness/resources/app.asar/dsh/node_modules/@deepseek-ai/dsh-sdk-jsonrpc-server/README.md#L50-L58>)
和[普通 SDK profile](<F:/DeepSeek Harness/resources/app.asar/dsh/node_modules/@deepseek-ai/dsh-sdk-app/README.md#L24-L34>)
确认这些契约。普通 SDK 默认关闭模型生成标题，并使用启动期配置；仍需审定用户叠加配置。
未找到 PATH 命令不能否定受支持入口；本轮未新启进程验证本机外部 SDK 的部署/认证配置。
也未复制 sdk-minimal 的全权限默认配置。

官方 Web 导出为 Session Header 的 `Download session log` 或 `/export`：
[导出契约](<F:/DeepSeek Harness/resources/app.asar/dsh/node_modules/@deepseek-ai/dsh-session-log-export/README.md#L25-L62>)
说明它不启动模型轮，但默认导出会话树及附件。
**为避免无关会话和私有载荷，本轮没有整树导出**，而是只打开明确白名单中的既存会话文件。

### 实际已验证的接入范围

实际证据来自上一轮主试验的 18 个本地 Harness 子会话，不是新外部 SDK 启动测试。
所以“官方外部接入契约存在”和“某个新 SDK 部署已验证可启动”必须分开；后者本轮没有验证。

## 2. 实际模型标识、可固定性与参数缺口

既有 18 会话的 26 个 request/header 快照均记录：

- provider：`openai-codex`
- model：`gpt-6.1-sol`
- reasoningEffort：前 12 个任务为 `high`，后 6 个任务为 `max`；快照数分别为 18 和 8。

这确认了**请求与 assistant source 的实际记录路由**，不是使用父会话显示标签猜测。
未观察到 provider 返回的独立 responseModel 字段，后端不可见模型构建版本仍为 unknown。
本轮未切换路由，也未从其他模型挑选更容易测量的结果。

| 参数 | 已知能力/证据 | 尚不能声称什么 |
|---|---|---|
| provider/model | SDK initialize 明确选择，真实 header/source 可核对 | 未新启同路由外部 SDK；服务端内部别名/权重版本未锁定 |
| reasoningEffort | SDK 可明确设置；真实记录有 high/max | 历史试验并未全程固定同一 effort |
| maxTokens | SDK 握手接受正整数 | 当前 Codex 请求组装未见 max_output_tokens；不能承诺它是计费硬上限 |
| temperature | LLM 词汇支持，Codex 请求构建有条件透传 | SDK initialize 未提供该字段，历史 header 未记录；本轮未证实固定方式 |
| top_p / seed | 当前 LLM/SDK 公共词汇未提供这些控制 | 不虚构可固定 seed 或靠未支持字段锁采样 |
| adapter/profile 版本 | 审计时捆绑 Harness 为 0.2.1-rc.2、pi-ai 1.1.0 | 不等于已经得到历史调用时的完整版本/配置快照 |

依据：[SDK 握手](<F:/DeepSeek Harness/resources/app.asar/dsh/node_modules/@deepseek-ai/dsh-sdk-jsonrpc-server/lib/index.js#L120-L146>)、
[LLM 参数范围](<F:/DeepSeek Harness/resources/app.asar/dsh/node_modules/@deepseek-ai/dsh-llm/README.md#L169-L178>)、
[Codex 请求组装](<F:/DeepSeek Harness/resources/app.asar/dsh/node_modules/@earendil-works/pi-ai/dist/api/openai-codex-responses.js#L373-L430>)。
SDK 接受参数不能替代对真实发送语义的核验。

## 3. 授权范围、真实记录与隐私处理

白名单来自既有主试验 Agent ID 登记，仅对应 env/data/debug 的 0/1/2 各 A/B，合计 18。
定位到的文件为其 V4 压缩日志；没有打开父会话或其他项目/任务的会话正文。

方法与保全：

- 本地只读处理既有日志，不通过 persistence 写入、恢复、迁移或重放会话。
- 只投影事件类型、序号/时间、路由/控制、usage、哈希化标识、状态及载荷存在性/长度/哈希。
- 系统/开发者提示整体词法跳过；text、reasoning、thinking、认证字段的值不解码、不回显、不落盘。
  工具参数/结果文本仅保留存在性、字节长度与指纹，不公开原内容。
- 原始日志没有复制到新交付目录；私有的本地审计中间件与原数据分离。
- 压缩日志由独立 Zstd 帧串联，已逐帧处理；双帧和排除敏感字符串的本地自检不是模型 canary。
  审计器早期遇到流哈希结束及只解首帧的问题，在出具本报告前已纠正，未据不完整解码作数据结论。
- 校验各文件读取期间未变，并在结束时核对来源哈希；持久事件序号连续。

实证汇总见[测量 JSON](measurement-summary.json)和[逐任务覆盖表](measurement-per-task.csv)。
这些是允许字段派生数据，不是新的实验结果，也没有回写上轮 Token/成本 unknown 字段。
覆盖表中 raw_* 字段名只指持久 SDK 记录里的原字段，不表示已取得 provider 原始 HTTP usage 对象。

## 4. 请求、重试、工具、失败与取消的覆盖

| 项目 | 实证结果 | 边界 |
|---|---|---|
| 持久事件 | 2,050 条，18/18 会话序号连续 | 证明已提交日志的连续性，不证明服务端所有网络请求都被记录 |
| 模型尝试结算 | 313：非错误 259、失败 54 | 是逻辑尝试结算，不是 HTTP/WebSocket 请求总数 |
| 显式重试启动 | 45 个 llm/retry-started | 与失败结算可关联；内部传输重连/回退另列 unknown |
| 失败类型 | TRANSPORT 48，PI_AI_ERROR 6 | 仅稳定错误码，不展开错误全文 |
| usage 字段 | 313/313 有 input/output/total；直接与流内重复样本无矛盾 | 字段存在不保证错误路径的零值是真实 provider 用量 |
| 工具账本 | 282 call、282 result，全部 ID 唯一配对，无孤立或重复；282 组模型/派发参数指纹一致 | 参数/结果载荷存在，正文未回显；底层 stdout 全量附件未逐个回放 |
| 异步工作 | 64 registered、64 settled，64 对 job ID 匹配 | 不把工具返回“已启动”当后台工作已完成 |
| 工具错误 | 2 个结果 isError=true | 不是所有子进程失败总数；退出码可能只在未展开的文本载荷中 |
| 回合终态 | completed 17，error 9 | 生命周期终态与原 18 个文件任务的独立验收结果不是同一个指标 |
| 取消/abort | 未观察到取消样本 | 不推断为取消路径完整或取消免费 |
| 步骤/时间边界 | 无未闭合 step；313 个逻辑尝试窗口、282 个工具窗口均可取得且非负 | 部分跨度包括准备、排队/网络等待，不是 provider CPU 时间 |

仅看工具次数相等不够；本轮实际比较了 ID 集合、唯一性、模型工具参数与派发参数指纹，
并补查异步 job 配对。仍不宣称已审查全部载荷语义、外部输出文件和原始网络通信。

现有 Codex 传输实现允许在部分阶段自动 WebSocket→SSE 回退；本次日志没有证明每个物理请求
都与一个 settlement 一一对应。显式重试计数不能冒充所有网络尝试计数。

## 5. Token、时间、费用及固定注入成本

### Token 来源：真实记录加静态映射，不是密度估算

成功路径的来源链已定位为：provider response.usage → pi-ai usage → Harness 规范化 usage →
持久结算事件。真实日志使用该格式，但本轮没有完整原始 HTTP 回包或账户对账资料。
静态源码是审计时安装版本，对历史映射的归因须保留版本未冻结这一限制。

[provider usage 映射](<F:/DeepSeek Harness/resources/app.asar/dsh/node_modules/@earendil-works/pi-ai/dist/api/openai-responses-shared.js#L434-L453>)
从 input_tokens 中扣除缓存读写，形成未缓存输入；output_tokens 形成输出，保留 total_tokens。
[Harness 映射](<F:/DeepSeek Harness/resources/app.asar/dsh/node_modules/@deepseek-ai/dsh-llm-pi-ai/lib/index.js#L1433-L1446>)
将 input/output/total 写入规范化字段，只保留正值缓存字段，未转发独立 reasoningTokens。
因此不能把规范化 inputTokens 误当包含缓存的原始 input_tokens 后再重复加算。

| 维度 | 能测部分 | 缺口/对净收益的影响 |
|---|---|---|
| 正常结算输入/输出/总量 | 259 个非错误结算有实际 SDK 数值，非字符/4 估算 | provider 原始字段完整保真未独立取得；不代表全任务费用已知 |
| 缓存读 | 243 个结算保留 cacheReadTokens | 缺省字段的 provider 原始存在性不可反推；不能机械补零 |
| 缓存写/独立推理 | 记录中均未出现对应规范化字段 | 缺失与被映射省略不能混淆；输出总数可含推理，但分项 unknown |
| 失败用量 | 54 个失败结算的规范化 input/output/total 全为 0，其中 5 个先有流活动 | **不能当作真实零成本**；完整任务 Token/费用 unknown |
| 取消用量 | 无实证样本 | unknown |
| 时间 | 逻辑步骤、显式重试、工具及后台 job 的时间边界可复核 | 真正网络/计算区间、硬进程丢失尾部 unknown；重叠不能盲加 |
| 货币 | 未取得授权价格/账单证据 | unknown；库的 cost=0 或价目表估算不等于真实账单 |

失败零值的具体风险有源码机制支持：
[Codex 适配器初始化 usage 为零](<F:/DeepSeek Harness/resources/app.asar/dsh/node_modules/@earendil-works/pi-ai/dist/api/openai-codex-responses.js#L145-L160>)，
正常终止回包才更新；[异常路径仍返回 output](<F:/DeepSeek Harness/resources/app.asar/dsh/node_modules/@earendil-works/pi-ai/dist/api/openai-codex-responses.js#L330-L350>)，
[Harness 再映射 error.usage](<F:/DeepSeek Harness/resources/app.asar/dsh/node_modules/@deepseek-ai/dsh-llm-pi-ai/lib/index.js#L1638-L1648>)。
这说明存在未获得终止 usage 而沿用默认零的路径；不能证明 54 次历史零值逐次对应多少实际费用。
不能删除这些失败后，仅用 259 个正常结算声称完整净收益。

现有 sessionStats 主要按 step/start→assistant/message 计模型时间，
[取消/未组装消息的部分时间可能不计](<F:/DeepSeek Harness/resources/app.asar/dsh/node_modules/@deepseek-ai/dsh-session-stats/lib/index.js#L16-L24>)。
本轮保留失败结算的原始窗口，不把 UI 汇总直接当活跃计算总量。

### MCP 描述与 Skill 注入

26 个 header 快照均有 142 个工具定义；未展开 description 正文。
成功请求的 provider 来源总输入应覆盖模型实际接收的整个 prompt/工具上下文，但工具 schema、
私有系统内容、Skill 的 Token 分项不能从一个 usage 总量精确拆出，单列 unknown。

旧试验 B 使用 CLI 桥接和本地指导，不是原生注册的 ToolSeed 四工具；本次在原生工具调用名中
未发现 toolbox_* 调用。因而不能用旧样本估出未来四个原生 MCP 工具的边际注入费用。
指导的字节数不能换算成已计费 Token；正常可见读取会进入后续总输入，但分项和失败尾部仍缺证据。

**结论：有可用的事件、工具与正常路径 Token 数据；完整 Token/工具/时间成本向量尚未闭环。
即使允许货币净收益 unknown，仍不能将本测量层判为 READY。**

## 6. 是否需要最小 canary：需要条件式验收，不获授权不运行

再做一个普通成功请求不能解决既已观察到的失败零值问题。最低成本优先项是：让用户/平台提供
同一路由的脱敏 provider 用量/请求标识或可回查记录，确认错误、取消和传输回退如何计量。
不得索要密钥、完整响应正文、私有提示或隐藏推理。
若没有这样的现成证据或窄字段导出能力，先保持 PARTIAL，不为“拿到成功数据”反复收费测试。

如人工随后批准，建议一个一次性、无业务数据的 canary：

1. 使用官方普通 sdk profile、现有认证和现有权限，保持 `openai-codex/gpt-6.1-sol`，
   由用户明确固定一个支持的 reasoningEffort；不换路由、不用 minimal 全权限配置。
2. 一个短任务读取已批准的无敏感夹具并返回校验值，观察一次工具调用及最终输出。
   预计需要两次逻辑模型尝试；控制器在两次后停止，不允许自由追加委派。
3. 在可一次性销毁的 SDK 进程中，另一次请求开始输出后调用受支持的 shutdown，以观察取消。
   SDK 没有逐 prompt cancel 方法，不虚构接口；取消后不得误记为成功或零成本。
4. 合计预算至多三次**逻辑**尝试；自动重试关闭或先审定。必须能记录/限制内部传输回退，
   否则不能承诺三次物理请求或硬性费用上限。
5. 用原始窄字段 usage、请求相关标识、工具 ID、终态及对账记录核验，不只检查字段是否存在。

必要授权须明确：同一路由及固定参数、最多三次逻辑尝试/允许的重试和回退、取消动作、
现有 SDK 权限与认证使用、允许采集的非敏感用量字段、任务墙钟限制及费用/额度风险。
本轮没有发出此授权请求，也没有执行该 canary。

可能费用：成功、工具轮和取消请求都可能消耗订阅额度或计费；金额及取消用量当前 unknown。
SDK 的 maxTokens 在这条 Codex 发送路径上尚未证明是硬上限，不能承诺“最多某 Token/某金额”。
若用户要求严格货币上限，须先有服务端预算机制或可核验限制，否则 canary 继续不准入。
现有沙箱/认证不允许启动时应停止，不申请扩大权限或绕过机制。

## 7. 下一阶段：能否进入 MCP / 工作区接线

**不能凭本报告进入带计费 Agent 的完整接线验收，更不能运行正式 8 次任务。**

后续最低条件：

- 批准并冻结同一模型路由与 effort，取得可复核外部 SDK 部署配置；
- 对失败/取消的默认零与真实用量作区分，补齐必要的服务端/原始 usage 证据；
- 明确物理重连/回退、辅助模型请求、时间及费用范围；
- 对完整工具返回/附件可取回性作限定范围核对，不扩大到无关会话。

不产生模型费用的 MCP/工作区静态配置审查可以单独提出，但本轮没有执行接线、MCP 启动或权限测试。
构建工件、原生 MCP 和 A/B 工作区的原有准入项仍未验证，不在本报告偷换为已解决。
也不修改既有预注册来迁就当前缺口。

## 8. Git 与历史资产状态

HEAD 保持指定基线。原九个结果文件、第二轮三份方案/审查文件共 12 个内容哈希保持不变；
授权会话源日志仍保留原位，读取前后及结束时校对其压缩文件哈希，不做写开、修复或迁移。

本轮仅新增本目录的报告、派生 JSON 和逐任务覆盖 CSV；没有公开原始日志、私有载荷或认证材料。
临时的只读投影/分析脚本留在忽略目录，既不是 AgentRunner，也不调用网络/模型或启动 Harness。
未修改产品、四工具、Schema、正式任务或预注册假设，未重跑旧 18 任务。
未提交、推送、打 tag、改 Release 或发布。至此停止，等待人工架构审查。
