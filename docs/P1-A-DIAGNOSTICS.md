# P1-A 触发诊断观测

2026-10-22，本地开发，未提交或发布。用途仅为下一次自然故障补足判断依据；不修改触发规则，
不复现 Chrome/ACL 故障，不调整权限，不把合成测试当作真实场景或模型行为验收。

## 为什么需要补充

既有 `toolseed/opportunity` logger 只记录信号达到阈值、提示提出/提交以及部分 ToolSeed 调用阶段。
大多数 `tools/result` 早退没有日志，不能还原 1/2 次失败、取消、去重和计数上限。
旧日志含原始 Agent / turn / message 等关联标识；新的观测模式需要独立的脱敏投影。

| 需要的证据 | 原有日志 | 本次补充 |
| --- | --- | --- |
| 运行宿主版本 | 未记录；engine 声明不是实际版本 | 读取已安装 Agent 包元数据，或当前 Desktop 的 `runtime/primary-runtime/runtime.json`；记录来源；不可读取则 unknown |
| 事件阶段、Agent/Session/回合 | 只覆盖部分阶段、部分原始 ID | 捕获阶段及仅本次捕获内稳定的不透明编号 |
| isError、结构化 code 存在性/类型/值 | 阈值前和早退时缺失 | 记录最终结果的实际元数据，不读取错误正文 |
| token 去重、同组失败计数 | 未完整记录 | Symbol 按身份编号，记录实际去重判定和已知组计数 |
| 不计数原因 | 多数未记录 | 对现有判断分支记录固定原因枚举 |
| 步骤进入、工具可见、提示提交 | 部分记录 | 保留看到步骤、宿主决策、提示判断、提出和实际提交的区别 |

观测只复用已核实的 DSH 0.2.1-rc.2 公开 `tools/result`、`agent/pre-step`、`session/event`、
`agent/disposed` 和 Cordis logger。没有添加 Hook 类型、Core 写入、数据库表、MCP 工具、服务或网络请求。

## 启用、获取与关闭

在 ToolSeed 插件**现有官方配置**中显式增加以下布尔字段，保留原来的 Python、dataDir、mcpServer：

```yaml
opportunityDiagnostics: true
```

默认是 `false`，字符串或其他 truthy 值不会通过内部的显式 true 检查。需要原有
`opportunities` 功能启用，且宿主已提供 Agent/tools 服务；它不自动启用服务或安装 MCP。
按原宿主方式重载插件或重启 DSH，前端资源没有变化，不需要重建 GUI。

日志交给 **当前宿主的 logger exporter/日志出口**，前缀为
`toolseed/opportunity-diagnostics`，级别为 `info`。已检查的 Cordis logger 支持公开 exporter，
基础 logger 还保留有限内存 buffer（该版本默认 1,000 条，包含其他插件日志）。
本实现不增加 exporter 或文件写入，不承诺独立 Desktop 文件路径；启动控制台/日志文件是否
持久化、info 是否被过滤，取决于当前 DSH 启动器和已配置 exporter。
仓库已有 `.test-data/host-audit/desktop.log`、`.test-data/dsh-appearance/host.log`
是以往启动器指定的输出文件，**不是新的默认位置，本轮不使用、覆盖或清理它们**。

下一次自然故障前，先在当前日志出口按前缀确认 `observer_started`，检查实际 `host_version`
和来源。看不到这条记录时，不能认定观测可用；先检查既有日志出口、info 级别和服务加载状态，
不要通过修改权限或重试故障来检查。若现有启动命令已经把 logger 输出到终端，可在用户自行
选择的输出位置只保留此前缀的行，例如在**原有启动命令的输出管道**使用：

```powershell
# 接在你已经使用的 DSH 启动命令后；这不是新的宿主启动 API。
# 最后可写入一个全新的、用户自己指定的独立摘录文件。
Select-String -SimpleMatch 'toolseed/opportunity-diagnostics' |
  ForEach-Object { $_.Line }
```

不应为本模式打开完整参数/提示词调试日志。若宿主只有内存日志且无现成导出出口，本模式不会
擅自增加持久化；需先解决日志收集方式，不能宣称下一次故障已经可持久采证。
本轮没有验证用户 live Desktop 的日志收集或启动任何新宿主进程。

将 `opportunityDiagnostics` 改为 `false` 并重载，停止新增诊断。配置重载/进程重启会丢弃临时身份映射；
**关闭此模式不关闭原有机会功能和普通阶段日志**。不要为了采证反复启停或制造失败。

清理顺序：先关闭模式，再按宿主已有保留/轮转方式清理 exporter 日志；仅删除本次用户自行
创建的独立诊断摘录，不能删除整个共享日志、历史实验、数据库或用户配置。完全重启可清除该进程
的内存 buffer，但不会自动删除已落盘的 exporter 文件。本轮未执行任何清理。

## 字段与判断

每条 JSON 记录包含 `schema`、随机 `capture`、递增 `seq`、时间、`host_version`、
`host_version_source` 和固定枚举 `stage`。每次加载产生新的 capture，编号不可用于跨捕获追踪。

| 字段 | 含义 |
| --- | --- |
| agent / session / turn | a1 / s1 / r1 等临时编号；原值只在有界进程内映射中使用，不输出 |
| token | e1 等按 Symbol 身份映射的编号，不调用 Symbol.toString，不记录描述；不同 Symbol 即使描述相同也不同编号 |
| is_error | 实际 boolean；缺失或其他类型是 unknown |
| code_present / code_type | 最终 `error.info` 是否自有 code 字段及其实际类型；不从命令输出推导 |
| code_valid | 是否具有现有触发规则允许的字符串码格式，仅为观测，不改变规则 |
| error_code | 符合现有格式的实际字符串码；或实际存在的 uint32 数字码。数字 5 会保持数字 5，仍不满足现有字符串触发条件 |
| token_duplicate | 现有规则是否把该次执行判为已见 token；未走到去重判断时为 unknown |
| group_count | 已知的实际同组计数；不适用/未知为 null，不补成 0 |
| execution_cancelled / turn_cancelled | 实际信号的 aborted；缺少信号则 unknown |
| reason | 为什么计数/不计数，或为什么没有提出提示的固定枚举 |
| transport_origin | 当前公开结果没有足够分层来源，本模式固定为 unknown，不从错误码/文本推断传输层 |
| entered / search_visible | 宿主是否接受步骤；既有流程实际检查过的工具可见性。未检查为 null，不为观测额外查工具 |
| prompt | not_proposed、commit_not_observed、committed；只有原有会话提交关联成功才是 committed |

工具名仅在现有允许的名称格式内输出。任意路径形式名称、非码格式字符串、复杂 code 值均脱敏；
不会截断原值后冒充另一个真实错误码。版本仅保留符合版本格式的值，阶段和原因只允许固定枚举。
不序列化完整 execution/result，不读 arguments、result.value/content、error.message、提示或推理。
ToolSeed 原本解析自身调用回复的逻辑保持原样，观测输出只保留阶段/必要计数，不附带回复正文或关联原始 ID。

主要 `tools/result` 原因包括：

- `counted`、`duplicate_token`、`no_agent`、`no_turn_state`、`token_not_symbol`；
- `execution_cancelled`、`turn_cancelled`、`cancel_code`；
- `not_tool_error`、`missing_or_nonstring_code`、`invalid_code`、`invalid_tool_name`；
- `toolseed_tool`、`ptc_transport`、`execution_limit`、`group_limit`、`signal_already_detected`。

步骤记录包含 `step_seen`、`step_decision`、`step_failed`；提示判断区分无信号、已经提出、
已观察到检索、取消、步骤被拒绝、搜索不可见和符合既有条件。提出提示与会话提交分开记录。
回合变化、Agent 销毁或插件卸载时，可记录 `commit_not_observed`，它不是“已证明永远未提交”。

只有命令输出报错、外层 isError=false 的事件会按原规则不计数，观测不会检查里面究竟是 Chrome
还是 ACL。传输错误如果没有结构化码，记录缺码；若确实带合格结构化码，仍按原来的通用规则计数，
**没有添加传输失败排除规则**。没有收到最终事件时也不会凭空记录一次传输失败。
审批等待不是这里的最终结果事件，本模式不监听新审批接口、不改变审批或授权。

## 数量、大小与保留

- 每次插件加载最多 **256 条 logger 记录**，包括开始/结束记录；自有前缀、JSON 与换行合计
  最多 **128 KiB**，单条最多 **2 KiB**。为结束记录预留额度；达到限制后永久停止这次捕获。
- 开启时，原来的 `toolseed/opportunity` 阶段日志也通过同一脱敏投影和额度，不再另发原始 ID。
  额度耗尽不会回退到普通日志。固定的 Agent 提示消息本身不变，宿主正常会话持久化不受本模式接管。
- 这些限制针对本模块生成的数据，不包含宿主 formatter 增加的前缀或多个 exporter 的复制成本。
  多次重载是多次捕获，文件总保留空间仍服从宿主策略，不能把每次 128 KiB 当作永久磁盘总上限。
- 强引用身份映射也单独限制为每类 256 个，防止异常元数据导致记录被跳过时持续增长；达到上限
  以 `identity_limit` 停止捕获。映射在额度耗尽、logger 抛错或插件卸载时释放；不写入 Core evidence_events 或任何文件。
- 宿主过滤/丢日志、其他日志挤出内存 buffer、logger 故障都可能导致不完整记录。capture+seq 可辅助
  判断缺口，不能用“没有日志”推出“没有发生”。logger 抛错时安全停止，可能无法输出结束记录。

## 改动与验证

| 文件 | 作用 |
| --- | --- |
| `integrations/dsh/opportunity-diagnostics.js` | 默认关闭的有界、脱敏 logger 投影和临时身份映射 |
| `integrations/dsh/opportunities.js` | 在原有判断分支增加诊断调用，保留阈值、排除条件、状态更新和提示内容 |
| `integrations/dsh/index.js` | 配置布尔开关，默认 false |
| `integrations/dsh/package.json` | 打包清单包含新投影模块 |
| `integrations/dsh/test/diagnostics.test.mjs` | 合成分类、字段脱敏、限额及观测开/关行为对照 |
| `integrations/dsh/README.md`、`docs/P1-A.md`、本文 | 启停、采集、保留及验收边界 |

验证只使用 Node 合成事件和源码静态检查，没有真实故障、浏览器、MCP 子进程、权限申请或模型请求。
既有 P1-A 的通过记录仍是历史结果，没有冒充本轮重跑。

| 本轮实际命令 / 检查 | 通过 | 失败 | 跳过 | 退出码 |
| --- | ---: | ---: | ---: | ---: |
| `node --test integrations/dsh/test/diagnostics.test.mjs integrations/dsh/test/opportunities.test.mjs` | 33（新增 16，原有 17） | 0 | 0 | 0 |
| `node --check` 分别检查新投影模块、opportunities.js、index.js 和新测试文件 | 4 | 0 | 0 | 0 |
| `git --no-optional-locks -c core.safecrlf=false diff --check` | 1 | 0 | 0 | 0 |
| `node --input-type=module` 从 stdin 加载改动前源码和当前模块进行行为比较 | 130 次比较 | 0 | 0 | 0 |

静态空白检索没有命中（`rg` 的退出码 1 表示无匹配，不是测试失败）。没有运行 Python/Core、
真实 DSH/MCP、真实模型、A/B 或全量质量门禁，也没有申请沙箱外权限。首次合成检查及后续检查
没有出现测试失败；编排一次性比较脚本时曾遇到工具环境缺少 btoa，改为 Node 的 Buffer 编码后
才执行比较，该编排错误未记为测试通过。

另以进入本轮前的原始模块在内存中加载，与当前模块关闭/开启观测分别做 **130 次行为比较**，
覆盖 0–4 次失败、重复 token、缺码/数字码/无效码、取消、PTC、已检索、回合变化、工具不可见和步骤拒绝。
比较消息内容、步骤决策、request-series 标记、工具可见性查询次数和原有机会阶段，全部一致；
提示字符串逐字节一致，阈值仍为 3。该检查不涉及真实模型或故障复现。

真实 DSH/用户 Desktop 中本模式的接收与持久化未验证；两个原始 Chrome / ACL 场景仍为未知。
本轮新增模型调用、模型上下文和网络请求均为 0；诊断 CPU/内存实际开销未测量，不报为 0。
不提交、不推送、不打 Tag、不发布，完成后停止等待人工架构审查。

工作区保护核对：进入本轮的 123 个正式文件中，仅上表对应的 5 个已有目标文件发生本轮修改，
其余 118 个文件内容哈希不变；另新增投影模块、测试和本文 3 个文件，无缺失文件。
`.git/HEAD`、index、config 哈希不变，分支仍为 `develop`，HEAD 仍是
`f63c007284b592bd4c07d0509f1c753d6c7b571f`，暂存区为空。最终 8 个已跟踪修改、67 个未跟踪文件。
