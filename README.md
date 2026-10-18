# ToolSeed

面向 Agent 的本地**程序性能力库**（P0-Slim）。核心对象是 **Capability**：一个可复用、可检索、
可版本化的 `procedure`。P0 只保存和交付程序性指引，**不执行代码**。

- 实现与验收依据：[docs/P0-SLIM.md](docs/P0-SLIM.md)
- 长期设计：[docs/DESIGN.md](docs/DESIGN.md)
- 两者范围不一致时，以 P0-SLIM 为准。

这是一个本地单用户能力库，已包含 P0 闭环与部分 P1：四个固定公共 API、不可变版本、内容哈希、
关键词检索、Procedure 交付、证据分离、证据有效性、失败诊断与修复候选。它不是安全沙箱，
也不是完整 MVP。

规划中的首发形态是一个通用 Python 包 + `toolseed-mcp` stdio 服务，让 Codex、Claude Code、
Cursor 等 Agent 共享同一能力库；MCP 层尚未实现。

## 快速开始

```python
from toolseed import ToolSeed

box = ToolSeed()  # 默认用户级共享目录 ~/.toolseed/，可用 TOOLSEED_DATA_DIR 覆盖
# 或显式隔离：box = ToolSeed("./project-data")

candidate = {
    "protocol_version": 1,
    "manifest": {
        "name": "triage_api_timeout",
        "kind": "procedure",
        "description": "对 API 请求超时进行分层排查",
        "when_to_use": "请求间歇性超时，需要区分客户端、网络和服务端原因",
        "not_for": ["已确认是凭据无效"],
        "tags": ["api", "debugging", "timeout"],
        "applicability": {"harnesses": [], "operating_systems": [], "required_tools": []},
    },
    "content": (
        "1. 先确认请求是否到达服务端，对比客户端发起时间与服务端入口时间。\n"
        "2. 若服务端未收到请求，检查 DNS、代理与连接池配置。\n"
        "3. 若服务端收到但处理缓慢，检查下游依赖与慢查询。\n"
    ),
}

saved = box.toolbox_save(candidate, "这套超时排查流程会反复用到")
box.toolbox_search("API 请求超时怎么分层排查")
box.toolbox_run(saved["capability_id"])   # 只交付 procedure 文本，不执行任何步骤
box.toolbox_stats()
box.close()
```

`status: "accepted"` 只表示已可靠持久化，**不等于** `version_status: "ready"`。

## 四个公共 API

| API | 说明 |
|---|---|
| `toolbox_search(query, context?)` | 先硬筛选（版本 `ready`、能力未退役/整体隔离、适用条件不冲突），再按名称/标签/描述/内容关键词排序；默认最多 3 条，可用 `ToolSeed(..., max_results=5)` 调到硬上限 5，允许空结果 |
| `toolbox_save(candidate, intent, context?)` | 接收唯一一种 JSON `candidate`；规范化、校验、哈希、查重后持久化，返回 `accepted` 与 `version_status` |
| `toolbox_run(capability, args?, options?)` | 解析稳定 `capability_id` 或无歧义名称，交付当前 `ready` 版本的 Procedure 正文，并记录 Invocation |
| `toolbox_stats()` | 只读统计：能力/版本状态、搜索、交付、重复命中、证据事件与任务结果信号（`signals`/`measured` 区分“没有信号”和“零结果”） |

所有 API 返回结构化结果。失败返回与 DESIGN §9 稳定语义一致的核心错误码（P0 实现 11 个），
例如 `INVALID_ARGUMENT`、`CAPABILITY_NOT_FOUND`、`CAPABILITY_NOT_READY`、
`UNSUPPORTED_CAPABILITY_KIND`、`CONTRACT_VIOLATION`、`POLICY_BLOCKED`、
`CAPABILITY_QUARANTINED`、`CAPABILITY_ARCHIVED`、`SAVE_PERSISTENCE_FAILED`。
不使用缩短的错误码别名，以免后续协议迁移。

## Candidate 格式

P0 只有一种候选传输格式：一个 JSON 对象，包含对象形式的 `manifest` 和文本 `content`。
不接受源码文件、目录、ZIP、`implementation.source` 或 Adapter 私有字段。

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
    "applicability": {
      "harnesses": [],
      "operating_systems": [],
      "required_tools": []
    }
  },
  "content": "1. 先确认请求是否到达服务端……\n2. 对比同一时间段的客户端与服务端日志……"
}
```

- `protocol_version` 必须是整数 `1`。
- 顶层只允许 `protocol_version`、`manifest`、`content` 和可选的 `target_capability_id`。
- `manifest` 必须恰好包含上述 7 个字段；`kind` 只能是 `procedure`。
- Manifest 中的文本字段按 NFC 规范化并去首尾空白；`content` 只统一换行为 LF，不改写正文。
- 提供 `target_capability_id` 时，为该能力创建新版本；省略时创建新 Capability（精确重复直接返回既有版本）。

字段上限：

| 字段 | 限制 |
|---|---|
| `name` | 非空，≤ 80 字符 |
| `description` | 非空，≤ 280 字符 |
| `when_to_use` | 非空，≤ 500 字符 |
| `not_for` | ≤ 10 项，每项 ≤ 160 字符 |
| `tags` | ≤ 12 项，每项 ≤ 40 字符 |
| `applicability.*` | 每个数组 ≤ 20 项，每项 ≤ 120 字符 |
| `content` | 1–32,768 UTF-8 字节 |
| 整个 candidate | ≤ 64 KiB |

`applicability` 的空数组表示**未声明限制**，不代表已验证兼容。只有当前上下文和能力声明都明确时，
才会因冲突做硬过滤。

## 保存语义

- 只有内容与版本记录都持久化成功后才返回 `status: "accepted"`；持久化失败返回
  `SAVE_PERSISTENCE_FAILED`，不会假装成功。
- 精确重复的判断是：规范化后的 `name` 与 `content_hash` 都相同。命中时返回既有
  Capability/Version，`duplicate: true`，不创建重复版本。
- 提供 `target_capability_id` 时，该能力必须存在且未 `archived`；相同内容哈希返回既有版本，
  否则新增版本。
- 非精确重复的新保存会在响应中返回 `possible_duplicates`，按同名、共享标签和元数据相似度
  给出最多 3 条提示；它只用于人工判断，不阻塞保存，也不自动合并。
- 内容检查分三档：
  - 明显的凭据/密钥或“绕过策略/泄露秘密”指令 → 拒绝保存，返回 `POLICY_BLOCKED`；
  - 破坏性或高风险操作（如 `rm -rf`、`drop table`）→ 允许保存，但版本保持 `candidate`，
    响应里附 `notes`；
  - 未命中 → 版本进入 `ready`。
- 保存的 Procedure 是**不可信数据**。交付时只作为能力材料，不得覆盖系统/开发者策略，
  也不得凭内容自我授权。
- 保存时的 `intent` 与已知来源字段（`source`、`task_id`、`session_id`、`harness`、
  `workspace`、`related_capability_ids`）会脱敏后写入版本的 `origin`；未知 context 字段忽略，
  不写入能力库。
- 旧版本永不原地改写。新版本只有成为 `ready` 后才替换当前版本指针。

## 交付语义

`toolbox_run` 对 `procedure` 只做指引交付：

- 只交付能力未退役/整体隔离时，该能力的当前 `ready` 版本；直接 ID 也不能绕过状态检查。
- 返回 `mode: "agent_guided"`、`execution_status: "guidance_delivered"`、
  `task_outcome: "unknown"`，以及 `result.content`、`when_to_use`、`not_for`。
- 同时记录一次 Invocation 和 `procedure_delivered` 事件；**交付本身不是任务成功证据**。
- `args` 目前只做对象类型校验，不参与 procedure 交付；`options` 中只有
  `task_id`、`session_id`、`harness`、`workspace` 会进入 Invocation 上下文。
- 不执行 Procedure 中的命令、不调用 Shell、不自动完成步骤。

## 状态模型

状态分为以下几类，彼此独立，不混用：

- **版本生命周期**：`candidate` / `ready` / `quarantined`（状态挂在版本上）
- **能力级退役/整体隔离**：`archived` / `quarantined_at`（作用于该能力的全部版本）
- **任务结果信号**：`success` / `failure` / `partial` / `unknown`（单独事件，不是版本状态）

只有当前版本为 `ready` 且能力未退役、未被整体隔离时，才能被检索和交付。`candidate`、
`quarantined` 版本以及 `archived` / 整体隔离的能力都会被普通入口拒绝。当前版本被隔离时，
指针回退到仍为 `ready` 的较旧版本；没有可回退版本时清空指针。

P0 不建立证据成熟度状态机，也不保存全局证据有效性投影；证据适用性按版本哈希与当前上下文实时判断。
没有可信任务结果信号时，`task_outcome` 保持 `unknown`。

## 安全边界

- P0 不执行任何代码，因此不需要 OS/容器沙箱作为启动前置条件。
- Procedure 文本始终按不可信内容处理，交付时明确标记为 `capability_material`。
- 保存时只做基本长度、结构与敏感内容静态检查；**检查器通过不等于内容已被证明安全**。
- 不把完整会话、密钥、令牌或原始凭据写入能力库。
- 本地存储位于当前用户可访问的数据目录；当前仍是单用户/单受信主体，不是多租户服务。
- `executable`、Runtime 与沙箱是独立的后续安全项目，不属于 P0。

## P1 证据有效性与失败诊断

P1 第一块已实现：

- `evidence_validity_assessments`：对原始证据追加 `valid` / `stale` / `superseded` 评估，
  保留原因、指纹快照与失效/替代引用；原始 `evidence_events` 不被改写；
- `failure_diagnoses`：按稳定失败类别记录能力/版本级诊断，关联调用、任务和证据；
- `propose_repair`：基于开放诊断生成**候选**修复版本，强制保持 `candidate`，不会自动替换当前
  `ready` 版本；高风险内容仍会被拒绝；
- 版本/能力隔离时自动把该版本相关证据追加为 `stale`，原始事件不改写；
- `maintenance_report()`：汇总未评估/失效证据、重复失败与开放诊断，给出建议动作但不自动改能力；
- `run_maintenance()`：把建议转成去重的 `evolution_decisions`，供人工查看/驳回；
- `apply_evolution_decision()`：自动应用 `diagnose_failure` 决策并原子写入诊断；
  对 `revalidate_evidence` 决策，必须先对决策范围内的每条证据重新评估为 `valid`，
  且评估时间晚于决策创建时间，Core 才允许应用；其他动作仍要求人工处理；
- 重新验证不会自动把旧证据“洗白”：新的 `valid` 评估必须来自显式 `assess_evidence` 调用；
- `capability_observations`：保存从证据提炼的适用性、失败模式、依赖/环境敏感性和待验证假设，
  可标记 `active` / `stale` / `retracted`，但不会直接修改能力或激活指针；
- 版本隔离、能力隔离或归档时自动把相关活跃观察标记为 `stale`，并记录原因；
- `expire_version_observations(...)`：策略/环境变化时显式让某版本观察失效；
- `rollback_version`：受控回滚到更旧的 `ready` 版本，记录 `version_rolled_back` 事件；
- `version_report()`：按版本汇总交付、任务结果、诊断、观察、证据有效性与回滚次数；
- 保存候选时返回 `possible_duplicates`（同名、共享标签、元数据相似），只提示，不自动合并；
- `toolbox_stats()` 增加评估计数、有效性分布、诊断状态、维护决策与观察计数。

### 重新验证流程

1. 证据被标记 `stale`（指纹/策略变化或隔离）后，`run_maintenance()` 生成
   `revalidate_evidence` 决策，payload 记录 `version_id` 和需要复核的 `evidence_ids`
   （只包含交付/任务结果类证据）；
2. 人工或外部验证器重新执行检查，并对每条证据显式调用 `assess_evidence(..., "valid", ...)`；
3. `apply_evolution_decision()` 逐条检查：
   - 最新评估必须是 `valid`；
   - 评估时间必须晚于决策创建时间；
   - 证据必须属于该决策对应的版本；
4. 全部通过才把决策标记为 `applied`；任一条不满足则拒绝，决策保持 `proposed`；
5. Core 不会自动把旧证据改成 `valid`，也不会因为“决策存在”就默认通过。

## 存储

默认数据目录是当前用户的 `~/.toolseed/`（可用 `TOOLSEED_DATA_DIR` 或显式路径覆盖），里面是一个
SQLite 文件。这样不同 MCP 客户端可以共享同一能力库；项目隔离通过 `namespace` 完成。
显式传入独立 `data_dir` 可做完全隔离。

- `toolseed.sqlite3`
  - `capabilities`：稳定身份、名称、namespace、当前版本指针、能力级 `archived_at` / `quarantined_at`
  - `capability_versions`：不可变版本、规范化 Manifest、Procedure 正文、`content_hash`、版本状态
  - `invocations`：每次 Procedure 交付记录
  - `evidence_events`：追加式事件，原始事件不被静默改写
  - `evidence_validity_assessments`：P1 证据有效性评估（追加式）
  - `failure_diagnoses`：P1 失败诊断与修复候选关联
  - `evolution_decisions`：P1 维护建议/决策及去重键
  - `capability_observations`：P1 可修订观察（适用性、失败模式、环境敏感性等）

没有 `save_jobs`、`search_index`、`audit_events` 或 `cost_observations` 表；版本正文存在数据库中，
不写 `content/` 文件。`content_hash` 由 `protocol_version`、Manifest 和 `content` 的确定性 JSON
（键按字典序、无多余空白）计算 SHA-256，格式为 `sha256:...`。

Schema 使用 `PRAGMA user_version` 迁移，当前为 v3：

- v2 增加 `capabilities.namespace`；
- v3 在版本上记录 `namespace` / `name`，并建立 `(namespace, name, content_hash)` 唯一索引，
  防止并发保存产生重复能力；
- 迁移在单个事务内逐条执行；v3 建索引前先做重复身份预检，发现冲突时停在 v2，
  不留下半迁移 Schema；
- 启动时通过跨进程迁移锁串行化，SQLite 启用 WAL 与 `busy_timeout`，支持多个 MCP 进程共享目录。

## 管理操作与 CLI

以下方法面向本地管理/Adapter，**不会注册成第五个 Agent 工具**：

- `quarantine(capability_id, reason)`：整体隔离一个能力；
- `release_capability(capability_id, reason, evidence_ref?)`：审核后解除能力级隔离，写入审计事件；
- `quarantine_version(version_id, reason)`：隔离单个版本；
- `release_version(version_id, reason, evidence_ref?)`：解除版本隔离，回到 `candidate`；
- `promote_version(version_id, reason, evidence_ref?)`：重新检查内容后把候选版本提升为 `ready`，高风险内容会被拒绝；
- `rollback_version(capability_id, version_id, reason, evidence_ref?)`：回滚到更旧的 `ready` 版本并记录事件；
- `version_report(version_id)`：按版本汇总交付、任务结果、诊断、观察、证据有效性与回滚；
- `archive(capability_id, reason)`：退役一个能力；
- `record_task_outcome(...)`：显式记录带来源的任务结果信号；
- `assess_evidence(...)` / `evidence_validity(...)`：追加证据有效性评估并读取当前投影；
- `expire_version_evidence(...)`：策略/环境变化时显式让某版本证据失效；
- `maintenance_report()`：维护扫描，返回未评估/失效证据、重复失败和开放诊断；
- `run_maintenance()`：把维护建议落地为去重的 `evolution_decisions`；
- `list_evolution_decisions(...)` / `dismiss_evolution_decision(...)`：查看与驳回维护决策；
- `apply_evolution_decision(...)`：应用可自动执行的维护决策；
- `diagnose_failure(...)` / `list_failure_diagnoses(...)` / `dismiss_diagnosis(...)`：失败诊断管理；
- `record_observation(...)` / `list_observations(...)` / `set_observation_status(...)`：能力观察管理；
- `expire_version_observations(...)`：显式让某版本观察失效；
- `propose_repair(...)`：根据开放诊断生成候选修复版本，不自动激活。

CLI 接受 JSON 参数或从 stdin 读取：

```bash
python -m toolseed stats --data-dir .toolseed
python -m toolseed search '{"query": "API 超时"}'
python -m toolseed save '{"candidate": {...}, "intent": "..."}'
python -m toolseed run '{"capability": "cap_xxx"}'
python -m toolseed quarantine '{"capability_id": "cap_xxx", "reason": "manual"}'
python -m toolseed quarantine-version '{"version_id": "ver_xxx"}'
python -m toolseed release '{"capability_id": "cap_xxx", "reason": "incident reviewed", "evidence_ref": "ticket-1"}'
python -m toolseed release-version '{"version_id": "ver_xxx", "reason": "reviewed"}'
python -m toolseed promote-version '{"version_id": "ver_xxx", "reason": "content rechecked"}'
python -m toolseed rollback '{"capability_id": "cap_xxx", "version_id": "ver_xxx", "reason": "regression"}'
python -m toolseed version-report '{"version_id": "ver_xxx"}'
python -m toolseed maintenance
python -m toolseed maintenance-run
python -m toolseed list-decisions '{"status": "proposed"}'
python -m toolseed dismiss-decision '{"decision_id": "dec_xxx", "resolution": "handled"}'
python -m toolseed apply-decision '{"decision_id": "dec_xxx", "resolution": "confirmed"}'
python -m toolseed record-observation '{"capability_id": "cap_xxx", "observation_type": "applicability", "summary": "仅在本地 Harness 适用", "generation_method": "human"}'
python -m toolseed list-observations '{"capability_id": "cap_xxx", "status": "active"}'
python -m toolseed set-observation-status '{"observation_id": "obs_xxx", "status": "stale", "reason": "environment changed"}'
python -m toolseed expire-version-observations '{"version_id": "ver_xxx", "reason_code": "runtime_changed"}'
python -m toolseed archive '{"capability_id": "cap_xxx"}'
python -m toolseed record-outcome '{"capability_id": "cap_xxx", "version_id": "ver_xxx", "invocation_id": "inv_xxx", "outcome": "success", "source_type": "test_runner"}'
```

## Adapter

`LocalAdapter` 注册固定的四个工具，并如实报告宿主能力缺口：没有 hooks、任务结束事件、
工作区事件、权限确认、取消或可靠任务结果通道。不支持的能力返回 `False`，不模拟。
它另外提供 `health_check()` 与 `translate_error()`，不改变 Core 的错误语义。

## MCP Server

官方 Model Context Protocol Python SDK（PyPI 包 `mcp`，锁定 2.3.x）提供 stdio 服务：

```bash
toolseed-mcp
# 或
python -m toolseed.mcp_server
```

已用官方 SDK 2.3.0 验证：服务只暴露四个工具，`Client(server)` 能列出工具并取得结构化统计。
stdio 子进程测试在 CI 中运行；本地 DSH 沙箱禁止创建子进程管道，可设
`TOOLSEED_SKIP_STDIO_TEST=1` 跳过该用例。缺少 SDK 时会输出可操作错误并以非零状态退出，
不抛裸 traceback。正式安装：

```bash
pip install -e .
```

- 只暴露 `toolbox_search`、`toolbox_save`、`toolbox_run`、`toolbox_stats`；
- 默认 stdio，不监听端口；
- 默认使用用户级共享目录；可用 `TOOLSEED_DATA_DIR` 或 `--data-dir` 覆盖；
- 同一进程内串行访问 SQLite，跨进程依赖 WAL/`busy_timeout`；
- 调用失败返回 Core 的结构化错误，不把错误伪装成成功。

Claude Code：

```bash
claude mcp add toolseed -- toolseed-mcp
```

Cursor `.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "toolseed": {
      "command": "toolseed-mcp",
      "args": []
    }
  }
}
```

不同客户端的配置格式不同，但启动命令相同。以下为官方文档形式的接入示例；当前环境尚未安装
SDK，因此还没有做端到端验证，实际配置请使用绝对路径并按客户端版本调整。

## 测试

```bash
python -m unittest discover -s tests -t . -v
```

当前 **156 项**测试；MCP 集成测试依赖官方 SDK，未安装时自动 skip。覆盖：

- Candidate/Manifest 契约、字段上限、未知字段拒绝、固定四工具；
- 版本身份、不可变版本、内容哈希稳定性、精确重复与近似不合并；
- 本地持久化、重开恢复、持久化失败返回 `SAVE_PERSISTENCE_FAILED`；
- 保存来源上下文的脱敏持久化与长度上限；
- 版本/能力级生命周期门禁、退役与隔离、解除隔离、候选版本提升与审计、当前版本指针与旧版本回退；
- 检索硬筛选、适用性冲突、中英文关键词排序、默认 3 条与可配置上限 5；
- Procedure 交付、Invocation、证据事件追加与任务结果分离；
- 统计中的未测量耗时/Token 保持 `unknown`，无任务信号时 `measured=false`；
- LocalAdapter 工具映射、健康检查与错误翻译；
- CLI 的 save/run/record-outcome/stats/archive/release/release-version/promote-version/quarantine；
- 价值实验骨架的采用率、计数与任务结果记录；
- live A/B harness 的任务验证器、条件隔离、JSONL 记录、外部命令执行与配对聚合；
- schema v2/v3 迁移、共享数据目录、namespace 隔离、迁移锁与 `busy_timeout`；
- v3 重复身份预检、迁移失败整体回滚且 `user_version` 保持一致；
- 两个连接并发保存同一候选时只生成一个能力/版本（唯一身份索引兜底）；
- P1 证据与观察自动失效、维护报告、去重维护决策与应用、重新验证决策闭环、能力观察、版本报告与回滚、失败诊断、修复候选、重复候选提示与统计；
- schema 版本迁移、嵌套事务回滚、回滚/修复候选原子性、invocation 归属校验；
- MCP Server 固定四工具与结构化统计调用（官方 SDK 2.3.0 已验证）；
- MCP stdio 子进程启动与四工具枚举（CI 验证，本地沙箱可跳过）；
- 缺少官方 SDK 时的可操作错误与非零退出。

## 质量门禁

```bash
python scripts/quality_gate.py
```

- 始终运行 `compileall` + unittest；
- 本机 `.venv` 已安装 `ruff` / `mypy`，当前四项全部 PASS；未安装时明确显示 `SKIP`，不会伪装成通过；
- `.github/workflows/quality.yml` 在 Linux/Windows/macOS 和 Python 3.11/3.13 上安装 `.[dev]`
  与官方 MCP SDK，然后运行完整质量门禁；
- 开发依赖：`pip install -e .[dev]` 或 `uv pip install ruff mypy`。

## 价值对照实验

[benchmarks/value_experiment.py](benchmarks/value_experiment.py) 提供固定的 A/B 对照：

- A：参考执行器不使用 ToolSeed，从零完成任务；
- B：先保存 Procedure，再通过 `toolbox_search` / `toolbox_run` 复用。

```bash
python -m benchmarks.value_experiment --repetitions 3
```

报告记录任务操作量、搜索/内容读取/保存次数、采用率、回退次数、重复命中、任务结果信号与耗时。
参考执行器是脚本化模拟，时间只反映本地 API 开销；它验证复用机制与计数，**不证明真实 LLM 收益**。
真实实验的替换点见 [benchmarks/README.md](benchmarks/README.md)。

## Live A/B 实验框架

[benchmarks/live_experiment.py](benchmarks/live_experiment.py) 是真实 Agent 的 A/B 框架：

- 固定 3 个任务族、6 个实例，每个实例有程序化验证器；
- A 条件不提供 ToolSeed；B 条件每次运行前预置 Procedure，并通过 `LIVE_TOOLBOX_DIR` 提供数据目录；
- 每个 Agent 运行写一条 JSONL：condition、instance、seed、success、elapsed、searches、deliveries、adoption、tokens、answer；
- 聚合输出配对成功率差、McNemar、bootstrap 置信区间、采用率与时间差。

```bash
python -m benchmarks.live_experiment --mode scripted --seeds 1
python -m benchmarks.live_experiment --mode command \
  --agent-command "your-agent-command" --seeds 3
```

外部命令通过 `LIVE_PROMPT_FILE`、`LIVE_OUTPUT`、`LIVE_CONDITION`、`LIVE_TOOLBOX_DIR` 等环境变量接入。
`scripted` 模式只验证 harness，不能当作价值结论；Token 成本在外部 Agent 未上报时保持 `unknown`。

## 当前范围与未实现项

已实现（P0 + P1 第一块）：四个固定 API、Capability/Version/Invocation/Evidence 模型、不可变版本与
内容哈希、唯一 `procedure` 表示、Manifest 校验、关键词检索与硬筛选、Procedure 交付、
本地 SQLite 持久化、用户级共享数据目录与 namespace、schema v3 迁移、并发保存唯一身份约束、能力/版本隔离与退役、
能力级隔离解除、版本解除与候选提升、证据有效性评估、自动失效与维护报告、维护决策、能力观察与
观察自动失效、版本报告与受控回滚、失败诊断与修复候选、`LocalAdapter` 与 Skill、价值对照实验骨架、
live A/B 实验框架、MCP stdio 适配层（官方 SDK 2.3.0 已验证）。

尚未实现：MCP 各客户端实际配置的端到端验证、`executable` / `workflow`（`kind` 不是 `procedure`
时返回 `UNSUPPORTED_CAPABILITY_KIND`）、代码执行与沙箱、多文件/ZIP 能力包、向量检索或 LLM 重排、
异步保存队列、证据成熟度状态机、多用户 RBAC、检索缓存、自动反思/自动修复、真实 LLM 或
独立验证器参与的价值实验。
