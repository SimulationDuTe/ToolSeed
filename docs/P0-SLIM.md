# ToolSeed P0-Slim — 当前实现规范

> **本文件是 P0 的唯一实现与验收依据。** 长期设计见 [`DESIGN.md`](DESIGN.md)。若范围不一致，以本文件为准。不得仅因为 DESIGN 中描述未来能力，就把它们添加到 P0。
>
> **目标：** 用最小实现验证程序性能力能否被可靠保存、检索、交付，并在后续任务中产生可测量的复用收益。
>
> **非目标：** P0 不执行 Python 或其他不可信代码，不建设通用沙箱，不做多用户/多租户、不引入向量数据库/图数据库、持久缓存、复杂兼容矩阵或自动 LLM 反思流水线。

## 1. P0 的五条承重约束

1. **Capability 不等于脚本。** P0 唯一支持的形式是 `procedure`：由 Agent 读取并按指引执行的程序性方法。
2. **稳定身份、不可变版本、内容哈希。** 已保存版本不原地覆盖，内容变化产生新版本。
3. **先硬筛选后检索排序，允许空结果。** 不适用或不可用能力不能因文本相似而被推荐。
4. **未知结果如实记录。** 指引交付不等于任务完成；没有可信任务结果信号时 `task_outcome=unknown`。
5. **固定四个 Agent 工具，能力目录动态扩展。** 新增能力不得新增 Harness 原生工具。

## 2. 范围与非目标

### 2.1 必须实现

- 一个 Harness Adapter；
- 固定四个 API：`toolbox_search`、`toolbox_save`、`toolbox_run`、`toolbox_stats`；
- 单 JSON `candidate` 传输格式；只含对象形式 `manifest` 和 `content` 文本；
- 单一权威 Manifest 校验规则，内嵌在 Core 代码的一个模块/常量中；不单独交付 `manifest.schema.json`；
- 本地持久化、稳定身份、不可变版本和规范化内容哈希；
- 简单关键词/字段检索和硬约束过滤；
- `procedure` 交付语义；
- 原始证据事件与 `unknown` 结果纪律；
- 最小统计与一次可重复的复用价值测试。

### 2.2 明确不做

- `executable`、Python Runtime、任意代码执行、Runtime SDK 与沙箱；
- `workflow`、多文件或 ZIP 能力包；
- 独立 `save_jobs` 表、异步保存队列或分布式恢复系统；
- 独立证据有效性投影；证据适用性在使用时根据原始事件与当前上下文实时判断；
- `index_revision` 和跨会话搜索缓存；P0 不实现检索缓存；
- 三套独立 SemVer 与兼容矩阵；P0 使用一个整数 `protocol_version`；
- 完整的 `toolseed_sdk`、`errors.py` / `protocol.py` 包、Python 模板与 AUTHORING 子系统；
- 多用户 RBAC、四权独立的访问控制系统；P0 是本地单用户/单受信主体，不是多租户服务；
- 图数据库、能力知识图谱、预计算能力地图、LLM 重排、自动合并和每任务反思；
- 用能力数量或调用频率代替价值评估。

## 3. 架构与模块上限

P0 采用单进程本地 Core + 一个 Harness Adapter + 一个本地持久化后端。建议核心逻辑控制在 **10 个以内模块、约 1000 行以内实现代码**；这是要求实现者审慎解释的工程预算目标，不是为了满足行数而删掉正确性或必要测试。

建议模块职责（可合并，不要求一职责一个文件）：

1. `api`：四个公共 API 与参数校验；
2. `manifest`：唯一的 Manifest 规范化和校验；
3. `registry`：能力身份与版本；
4. `search`：硬筛选和关键词召回；
5. `evidence`：追加式事件及结果来源；
6. `storage`：事务和持久化；
7. `adapter`：一个 Harness 的工具注册与映射；
8. `cli`（可选）：本地诊断、隔离和归档操作。

不要仅为“未来可能需要”创建服务、抽象层或独立包。先让一个完整流程在单进程中可测试地运行。

## 4. 公共 API

四个工具名固定，不因能力数量或内部模块数量改变。每个 API 接收结构化参数并返回结构化结果。

### 4.1 `toolbox_search(query, context?)`

- `query` 为非空任务描述、目标或问题。
- `context` 可提供已知环境/适用条件；没有的数据必须保持未知，不得猜测。
- 先过滤非 `ready` 版本、已退役/整体隔离的能力与明确不适用条件，再按名称、标签、描述和内容关键词进行本地检索；P0 不调用 LLM。
- 默认返回 1–3 条，最多 5 条；结果不足时可返回空数组。
- 每条结果只包含 ID、名称、短描述、适用/不适用摘要、版本号和简短内容摘要，不返回全量历史或不相关源码。
- 明确的 `capability_id` 直接查询；同一任务在查询和上下文未变时由 Agent 复用已返回结果，不强制 Core 建缓存。

示例：

```json
{
  "results": [
    {
      "capability_id": "cap_abc",
      "version_id": "ver_abc_1",
      "name": "triage_api_timeout",
      "description": "对 API 超时进行分层排查",
      "when_to_use": "请求间歇性超时且需要定位故障层级",
      "not_for": ["已确认是凭据无效"],
      "kind": "procedure"
    }
  ]
}
```

### 4.2 `toolbox_save(candidate, intent, context?)`

同步接收并保存候选。若持久化未成功，不得返回成功。P0 候选格式只有一种：

```json
{
  "protocol_version": 1,
  "manifest": {
    "name": "triage_api_timeout",
    "kind": "procedure",
    "description": "对 API 请求超时进行分层排查",
    "when_to_use": "请求间歇性超时，需要区分客户端、网络和服务端原因",
    "not_for": ["已确认是凭据无效"],
    "tags": ["api", "debugging"],
    "applicability": {"harnesses": [], "operating_systems": [], "required_tools": []}
  },
  "content": "1. 先确认请求是否到达服务端……\n2. 对比同一时间段的客户端与服务端日志……"
}
```

规范：

- `protocol_version` 必须是整数 `1`；其他值拒绝处理，不猜测兼容性。
- `candidate` 顶层只允许 `protocol_version`、`manifest`、`content` 和可选的 `target_capability_id`；未知字段拒绝处理，避免各实现私自扩展。未提供目标 ID 表示创建新 Capability；提供目标 ID 表示为该 Capability 创建新版本。
- `manifest` 必须是 JSON 对象。权威校验规则只定义一次，位于 Core 的 `manifest` 模块/常量中；Manifest 只允许下述字段，不接受未定义字段。
- `manifest` 必须包含 `name`、`kind`、`description`、`when_to_use`、`not_for`、`tags`、`applicability`。`kind` 固定为 `procedure`；其他 kind 返回 `UNSUPPORTED_CAPABILITY_KIND`，不得静默降级。
- `name`、`description`、`when_to_use` 都必须是非空字符串；`name` 不超过 80 字符，`description` 不超过 280 字符，`when_to_use` 不超过 500 字符；`not_for` 是最多 10 个字符串、每项不超过 160 字符的数组；`tags` 是最多 12 个非空字符串、每项不超过 40 字符的数组。
- `applicability` 只允许 `harnesses`、`operating_systems`、`required_tools` 三个字符串数组；每个数组最多 20 项。空数组表示未声明限制，不代表已验证兼容。只有当当前上下文和能力声明都明确时才能根据二者冲突做硬过滤。
- `content` 必须是 1–32,768 UTF-8 字节的非空文本；整个序列化 candidate 不超过 64 KiB。不接收源码文件、目录、ZIP 或嵌套文件。
- 所有文本字段必须是合法 Unicode；名称、描述、用途和数组项按 NFC 规范化并去除首尾空白；内容仅将换行统一为 LF，不改写其余正文。
- `intent` 是简短的保存理由，不是可信验证证明。
- `context` 只记录调用者实际知道的来源；P0 持久化 `source`、`source_type`、`task_id`、`session_id`、`harness`、`workspace` 和 `related_capability_ids`，其他字段忽略。不得要求完整对话或思维链。
- 创建新 Capability 时，精确重复判断为规范化后的 `name` 与 `content_hash` 都相同；命中时返回既有 Capability/Version，不再创建重复版本。若提供 `target_capability_id`，该 ID 必须存在且未归档；相同内容哈希返回该能力的既有版本，否则新增版本。P0 不接受客户端幂等键，也不做语义相似合并。
- 保存的 Procedure 内容是不可信数据。交付给 Agent 时必须作为能力材料处理，不能覆盖系统/开发者约束，不能凭内容自我授权。
- 不同内容不得自动覆盖或模糊合并。
- 修改已有能力时必须显式提供 `target_capability_id` 并生成新版本；旧版本内容不改写。新版本只有通过最低门槛后才能替换当前可用版本。

最低响应：

```json
{
  "status": "accepted",
  "capability_id": "cap_abc",
  "version_id": "ver_abc_1",
  "version": 1,
  "version_status": "ready",
  "content_hash": "sha256:...",
  "duplicate": false
}
```

`status` 只使用 `accepted`（不得使用 `saved` 等别名）；`version_status` 是版本级状态，取值为 `candidate|ready|quarantined`。

`ready` 只表示通过 P0 的结构门槛并允许被作为指引发现，不表示其内容经过外部事实核实，也不保证它适用于所有任务。缺少必要字段或需要人工判断的内容可保留为 `candidate`。发现明显安全/完整性风险时必须拒绝或隔离，不能为了闭环而自动发布。

### 4.3 `toolbox_run(capability, args?, options?)`

P0 中，`toolbox_run` **只交付 procedure 指引，不执行代码、不调用 Shell、不自动执行指引中的步骤**。

- 解析稳定 `capability_id`；含糊名称不得猜测。
- 只交付能力未退役/整体隔离时该能力的当前 `ready` 版本；旧结果或直接 ID 不得绕过当前状态检查。
- 返回 `mode=agent_guided`、`execution_status=guidance_delivered`、能力/版本/调用 ID 与 Procedure 正文。
- 交付前记录一次 invocation；交付行为本身不是任务成功证据。
- Procedure 文本须明确标识为能力内容，不得执行其中要求违反更高优先级指令、泄露秘密或绕过授权的内容。

### 4.4 `toolbox_stats()`

至少返回：能力数、版本状态分布、能力级退役/整体隔离数、搜索次数、返回候选数、Procedure 交付次数、重复保存命中数、已有证据事件数、各类任务结果信号计数与 `unknown` 比例，以及可以可靠测得的耗时/成本。

缺失 Token、任务结果或成本数据应标记为 `unknown`，不得当成零。P0 不要求在线模型 Token 遥测或复杂仪表板。

## 5. 能力状态与版本

P0 只实现以下状态语义：

- 版本状态 `candidate`：已保存，但不进入正常搜索；
- 版本状态 `ready`：通过最低结构门槛，可作为指引交付；
- 版本状态 `quarantined`：因该版本的内容风险、完整性问题或明确的严重错误而隔离；
- Capability 级 `archived`：不参与正常搜索。若安全事件影响所有版本，可通过 Capability 级 `quarantined_at` 整体隔离。

Capability 本身不具有 `candidate` / `ready` / `quarantined` 状态；这三个状态只属于版本。该状态层级与 DESIGN §11.1 一致。

Capability 的当前版本指针只能指向一个可用于正常交付的 `ready` 版本。新版本尚未就绪时，不自动替换仍然可用的旧版本；当前版本被隔离时，指针应回退到仍为 `ready` 的较旧版本，若没有则清空。

状态门槛：

- `ready` 不代表事实正确或任务成功；它只表示内容结构、必需字段和基本安全检查满足 P0 的指引交付要求。
- 新版本不可修改旧版本。新版本通过基础校验后才能成为当前 `ready` 版本；若尚未通过，旧的可用版本可以继续保持当前版本，除非存在安全原因需要隔离整个能力。
- 内容哈希基于确定性规范化后的 `protocol_version`、Manifest 和 Procedure 内容计算；将对象序列化为 UTF-8 JSON、键按字典序排列、不含无意义空白，再计算 SHA-256。时间戳、统计值和事件不进入内容哈希。
- P0 不建证据成熟度状态机，也不保存全局证据有效性投影。证据适用性按版本哈希及当前已知上下文实时判断。
- 可选的本地 CLI 可以实现隔离、解除能力级/版本级隔离、候选版本提升与归档操作；不得为这些管理功能增加第五个 Agent 公共工具。解除隔离、提升版本必须提供 reason，并可附带 evidence 引用，操作写入追加式事件。版本提升前必须重新通过内容检查；高风险候选不得直接提升。

## 6. 最小持久化模型

P0 使用四个核心实体。可用 SQLite 或等价的本地事务存储；不要为了架构形式拆成服务。

### 6.1 `capabilities`

稳定身份：`capability_id`、规范化名称、创建时间、当前可用版本指针（若有）、`archived_at` 与可选的能力级 `quarantined_at`。P0 是单用户本地使用，不建多主体权限系统。

### 6.2 `capability_versions`

每个不可变版本包含：`version_id`、`capability_id`、递增版本号、规范化 Manifest、Procedure 内容、`content_hash`、版本状态（`candidate|ready|quarantined`）、创建时间、来源/创建意图摘要。

### 6.3 `invocations`

每次搜索后明确交付 Procedure 的调用记录：`invocation_id`、`capability_id`、`version_id`、时间、上下文引用（若可用）、交付状态和关联任务 ID（若有）。不要记录不必要的敏感输入。

### 6.4 `evidence_events`

追加式事件：`event_id`、事件类型、时间、来源类型、关联的能力/版本/调用/任务 ID（如有）、`outcome`（`success|failure|partial|unknown`）、脱敏摘要或来源引用。原始事件不可静默改写；纠正通过新事件表达。

### 6.5 P0 不建立的实体

不建 `save_jobs`、`evidence_validity_assessments`、`registry_state`、`capability_map`、独立 observations 表或 task cost 表。相关的轻量信息可在调用/事件记录中表示。只有出现可复现的性能或治理问题后，才考虑新实体。

## 7. 证据和结果纪律

最低事件语义：

- `procedure_saved`
- `search_performed`
- `procedure_delivered`
- `task_outcome_signal`
- `capability_quarantined` / `capability_released` / `capability_archived`（发生时）
- `version_released` / `version_promoted`（发生版本级管理操作时）

任务结果 `outcome` 只能是 `success`、`failure`、`partial` 或 `unknown`。信号须记录来源，例如 `agent`、`harness`、`test_runner`、`external_system`、`human`。来源不代表同等可信度。

- `procedure_delivered` 不是成功；
- Agent 自我报告可记录，但不能冒充外部验证；
- 没有可靠结果信号时使用 `unknown`；
- 不收集完整思维链作为证据；优先保存外部动作、测试结果和必要摘要；
- 不把一次任务结果泛化为所有上下文中的通用成功率；
- P0 不做自动观察综合或自动修复。

## 8. 检索规范

P0 使用数据库字段与关键词检索，不需要向量数据库、远程嵌入或 LLM 重排。

执行顺序：

1. 明确 ID 查询时直接查找；
2. 过滤非 `ready` 能力；
3. 过滤与任务显式上下文冲突的适用条件；
4. 按名称、标签、描述和内容关键词检索；
5. 返回少量卡片，最多 5 条；无匹配返回空数组。

搜索缓存、`index_revision`、语义重排和预计算能力地图不属于 P0。未测量到性能问题前不要先实现缓存失效系统。

## 9. 错误协议

P0 在一个 Core 模块集中定义实际会返回的错误码和消息，不要求提前交付独立 `errors.py` SDK，也不在 P0 固化完整未来 20 码注册表。错误码名称必须与 `DESIGN.md` 第 9 节的稳定公共语义一致，不得使用缩写别名，以免后续协议迁移；P0 至少区分：

- `INVALID_ARGUMENT`：公共 API 参数结构或类型错误；
- `CAPABILITY_NOT_FOUND`：目标能力不存在或调用者无法发现；
- `AMBIGUOUS_CAPABILITY_NAME`：名称解析到多个能力，必须要求显式 ID；
- `CAPABILITY_NOT_READY`：目标版本未达到交付条件；
- `UNSUPPORTED_CAPABILITY_KIND`：请求使用 P0 不支持的 Representation；
- `CONTRACT_VIOLATION`：候选 Manifest/能力内容违反 P0 契约；
- `POLICY_BLOCKED`：内容因明确的本地安全规则被阻止；
- `CAPABILITY_QUARANTINED`：目标能力或版本已被隔离；
- `CAPABILITY_ARCHIVED`：目标能力已退役；
- `SAVE_PERSISTENCE_FAILED`：本地持久化失败；
- `INTERNAL_ERROR`：其他未预期内部错误。

各错误码含义稳定，不得在不同 API 中改变含义。P0 不定义客户端幂等键；精确重复由内容哈希与名称/目标 ID 判断。错误文本不得泄露本地秘密、凭据或不必要的文件系统细节。可在未来有可执行 Runtime 时再定义运行时专用错误体系。

## 10. 本地安全边界

P0 不执行代码，因此不需要把 OS/容器沙箱作为启动前置条件。但必须：

- 将保存的 Procedure 视为不可信内容，而不是高优先级指令；
- 交付指引时，不允许其覆盖系统/开发者策略或自动授予权限；
- 对内容执行基本长度、结构和敏感信息检查；检查器无法确定时不得声称内容已安全验证；
- 本地存储权限应限制在当前用户可访问的目录；
- 不把完整会话、密钥或原始凭据写入能力库；
- 在需要时可隔离内容或退役能力，并保留事件记录。

可执行能力是单独的安全项目。未来只有在具体平台的执行后端能够从不可信代码外部真实强制文件、网络、进程、凭据和资源限制后，才可设计执行型 P1/P2；不允许在宿主权限下直接执行 Agent 生成的代码。

## 11. 测试与验收

### 11.1 必须有的契约测试

- 四个工具名称固定，新增 Capability 不改变工具列表；
- 候选格式只有一种；缺字段、错误类型、未知 `protocol_version` 和不支持的 kind 被明确拒绝；
- Manifest 规范化具有确定性；相同规范化内容产生相同 `content_hash`；
- 版本内容不可原地覆盖；修改创建新版本；
- 版本 `candidate` / `quarantined` 与能力级 `archived` / 整体隔离不进入正常搜索或交付；
- 搜索先筛选再排序，返回不超过 5 条，并允许空结果；
- `toolbox_run` 只交付 Procedure，永不执行其中的代码；
- Procedure 交付事件不能被误记成任务成功；
- 无可信结果信号时 `task_outcome=unknown`；
- 精确重复保存不会意外生成大量重复版本；近似但不同的内容不会自动合并；
- 失败持久化返回 `SAVE_PERSISTENCE_FAILED`，不得返回 `accepted`；
- 读取/交付的 Procedure 不得覆盖更高优先级策略。

### 11.2 最小价值实验

用固定、可重复的任务集比较：

A. 不使用 ToolSeed；
B. 使用 ToolSeed 保存与复用 Procedure。

至少记录任务是否完成及其证据来源、完成耗时或操作量、搜索和内容读取次数、创建成本与后续复用情况。若不能测得某项成本，标记为 `unknown`，不可当作零。

实验应回答：保存的 Procedure 是否被后续任务真正采用，是否改善任务结果或减少操作成本，净收益是否为正。P0 只验证这个有限假设，不证明自主进化、任意代码执行安全或对未见任务的普遍泛化。

仓库中的 `benchmarks/value_experiment.py` 提供确定性参考执行器机制检查，`benchmarks/live_experiment.py` 提供真实 Agent 的 A/B 实验框架；两者都不替代真实任务集上的价值实验。

## 12. P0 完成定义

P0 完成必须同时满足：

1. 一个 Harness 注册固定四工具；
2. 一个 Procedure 可以保存、规范化、产生稳定身份/版本/哈希并持久化；
3. 合适的后续任务能通过关键词检索找到它；
4. `toolbox_run` 能向 Agent 交付其指引并记录 Invocation/Evidence；
5. 任务结果被单独记录，缺少可信信号时保持 `unknown`；
6. 契约和失败路径测试通过；
7. 一组可重复任务完成基础对照测试，并报告已知成本、未知数据与限制。

不得把“保存、检索和交付跑通”表述为已证明长期学习或净收益。若没有完成价值实验，只能声明产品闭环机制可运行。

## 13. 何时允许扩展

每项新增机制都需先写出触发证据与最低成本替代方案。

- 增加 SDK/统一脚本模板：至少在准备支持可执行能力，并已看到重复样板后；
- 增加证据有效性投影：实时判断被测量证明成为性能/治理瓶颈后；
- 增加缓存和 `index_revision`：确有跨会话缓存且失效语义需要它时；
- 增加兼容矩阵：出现多个独立协议版本或真实兼容问题后；
- 增加多用户权限：产品实际成为多主体共享服务时；
- 增加语义检索/LLM 重排：关键词检索质量有可测不足，且收益大于 Token/延迟成本时；
- 增加 observations/自动维护：积累到足够证据，且能展示其对复用质量或净收益的实际改善时；
- 增加 executable 与沙箱：单独完成威胁模型、平台方案和真实隔离验收后。

没有触发证据时，保持系统小而可理解，不预先建设未来规模的基础设施。
