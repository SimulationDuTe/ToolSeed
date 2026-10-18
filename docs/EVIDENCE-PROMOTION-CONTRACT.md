# ToolSeed Evidence & Promotion Contract v0.1.1

> 状态：v0.4.0 候选实现，验证与晋升主链路已落地；任务信号幂等与完整回归执行器仍未实现  
> 适用：ToolSeed v0.3.0 基线，v0.4.0 实现
> 范围：结果信号、验证证据、候选版本、`promote_version`、版本生命周期  
> 非目标：身份认证体系、自动反思、自动晋升、Workflow、第五个 MCP 工具、数据库选型

---

## 0. 核心原则

1. **保存成功不等于验证成功。**
2. **内容扫描通过不等于能力可复用。**
3. **`source_type` 是来源声明，不是可信性证明。**
4. **证据必须绑定具体版本和内容哈希。**
5. **未知、失败、过期、无法关联的证据不能作为晋升依据。**
6. **新版本只验证新案例，不足以证明旧行为未被破坏。**
7. **旧版本永不原地修改；晋升只改变当前指针，不重写历史。**

---

## 1. 结果证据契约

### 1.1 目标

让一次任务结果能够回答：

- 它关联哪个能力、哪个版本、哪个内容哈希；
- 它关联哪个任务实例或交付调用；
- 它是成功、失败、部分成功还是未知；
- 来源是什么，证据在哪里；
- 同一条结果是否被重复上报。

### 1.2 逻辑字段

| 字段 | 语义 | 现有能力 | 必须补充的约束 | 尚未决定的实现选项 |
|---|---|---|---|---|
| `capability_id` | 能力身份 | 已有 | 必须存在 | 无 |
| `version_id` | 版本身份 | 已有 | 必须属于 capability | 无 |
| `content_hash` | 版本内容哈希 | 版本已有，信号未存 | 必须与 `version_id` 当前哈希完全一致 | 信号事件新增字段，或从版本表派生并校验 |
| `invocation_id` | 交付调用 | 已有 | 必须存在且属于同一 capability/version | 无 |
| `task_id` | 任务实例引用 | 可选 | verified success 至少需要 invocation 或 task；若提供，必须稳定 | 是否加唯一实例表，暂不决定 |
| `outcome` | `success` / `failure` / `partial` / `unknown` | 已有 | 只允许这四个值 | 无 |
| `source_type` | 来源声明 | 已有 | 不能单独把信号升级为“已验证成功” | 是否增加独立 verifier 身份 |
| `verification_ref` | 验证产物引用 | 无 | verified success 必须有可审计引用 | 文件路径、内容哈希、外部记录 ID 或统一引用格式 |
| `verifier` | 验证者/验证器标识 | 无 | 可选但推荐；用于去重和审计 | 字符串、机器 ID 或轻量签名 |
| `signal_key` | 幂等键 | 无 | 相同语义信号只能计数一次 | 新字段、唯一索引或计算表 |

### 1.3 信号来源语义

```text
core             Core 自身事件，不作为独立验证
agent            Agent 自报，不能单独构成 verified success
harness          宿主事件，不能自动视为独立验证
test_runner      测试执行器，可作为独立验证来源
external_system  外部系统，可作为独立验证来源
human            人工检查，可作为独立验证来源
```

`source_type=test_runner` 只表示调用方声明该来源；在本地单用户模式下，它不提供密码学证明，也不证明验证产物真实存在。

### 1.4 verified success 的最小定义

一条结果可视为 `verified success`，至少同时满足：

```text
outcome = success
AND source_type ∈ {test_runner, external_system, human}
AND content_hash 与 version_id 的哈希一致
AND invocation_id 或 task_id 可追溯
AND verification_ref 存在且可审计
AND 该信号未被标记 stale/superseded
```

任何一项不满足，都不能作为候选版本晋升依据。

### 1.5 幂等规则

建议的语义键：

```text
signal_key = sha256(
  capability_id | version_id | content_hash |
  invocation_id | task_id |
  outcome | source_type | verifier | verification_ref
)
```

规则：

- 相同 `signal_key` 重复提交：不新增事件、不增加统计；
- 返回既有结果或明确的 `duplicate_signal`；
- 不同 verifier 或不同 verification_ref 视为独立信号；
- 同一 verifier 对同一证据重复提交不重复计数；
- `unknown` 也使用同一幂等规则，但不能作为成功依据。

### 1.6 冲突信号

- 同一版本可以存在成功、失败、部分成功和未知信号；
- 晋升时不能只挑成功信号；
- 候选版本创建之后产生的失败/未知信号必须参与判断；
- 具体规则见第 4 节。

---

## 2. 验证证据契约

### 2.1 目标

验证证据必须证明：

- 验证对象是哪个候选版本；
- 验证时内容哈希是什么；
- 验证发生在候选创建之后；
- 使用了什么输入、方法和检查；
- 结果是什么；
- 产物在哪里；
- 证据是否仍然有效。

### 2.2 逻辑字段

| 字段 | 语义 | 现有能力 | 必须补充的约束 | 尚未决定的实现选项 |
|---|---|---|---|---|
| `verification_id` | 验证记录身份 | 无 | 全局唯一 | 新事件类型、新表或扩展 evidence_events |
| `version_id` | 被验证版本 | 已有版本 | 必须是 candidate | 无 |
| `content_hash` | 被验证内容 | 版本已有 | 精确匹配候选版本 | 无 |
| `created_at` | 验证时间 | 事件已有 | 必须晚于候选版本创建时间 | 无 |
| `outcome` | `passed` / `failed` / `unknown` | 无独立字段 | 只有 `passed` 可作为晋升依据 | 复用 success/failure 还是新增枚举 |
| `method` | 检查方法/命令/用例 | 无 | 必须可审计 | 字符串、结构化对象或引用 |
| `verifier` | 验证者标识 | 无 | 可选；用于独立性说明 | 身份体系暂不建设 |
| `input_ref` | 输入引用 | 无 | 必须能定位本次验证输入 | 路径、哈希或任务 ID |
| `artifact_ref` | 验证产物引用 | 无 | 必须是可定位的审计引用 | 文件、日志、外部记录 |
| `artifact_hash` | 产物哈希 | 无 | 推荐；用于防止产物被替换 | 必填或可选 |
| `case_ids` | 验证/回归用例 | 无 | 回归要求需要 | 暂不决定用例存储 |
| `validity` | 有效性投影 | 已有 `assess_evidence` | 只接受最新 `valid` | 复用现有有效性模型 |

### 2.3 现有有效性机制

已有：

- `assess_evidence` 支持 `valid` / `stale` / `superseded`；
- 最新评估作为投影；
- `expire_version_evidence` 可显式标记 stale。

契约要求：

- `unassessed` 不能作为有效证据；
- `stale` / `superseded` 不能作为晋升依据；
- 晋升必须读取最新有效性，而不是历史某次 valid；
- 验证证据必须绑定版本内容哈希，不能只绑定 capability。

### 2.4 独立性边界

在当前本地单用户环境：

- 不建设密码学身份认证；
- 可以用 `source_type + verifier + artifact_ref` 形成可审计约定；
- 文档和 API 必须明确这是“审计性来源声明”，不是“密码学可信验证”；
- `agent` 自报和 `core` 自动事件不能单独满足 verified success。

---

## 3. 候选版本验证契约

### 3.1 版本状态要求

```text
候选版本 = candidate
验证通过后才允许 promote 为 ready
旧版本保持原内容和原状态
```

### 3.2 已决定：修订不得绕过候选阶段

现有 `toolbox_save` 带 `target_capability_id` 时，内容扫描通过会直接创建 `ready` 版本。这个行为在 v0.4 起必须改变：

```text
新建 Capability：可以按现有准入规则进入 ready
修订已有 Capability：必须进入 candidate，不自动替换 current
候选晋升：只有 promote_version 可以将其变为 ready
```

完整分类、状态转换和兼容策略见第 7 节。本节其余验证条件只适用于 candidate。

### 3.3 验证条件

候选版本晋升前至少需要：

1. 至少一条绑定该候选版本和内容哈希的验证证据；
2. 验证时间晚于候选版本创建时间；
3. 最新验证结果为 `passed`；
4. 该证据最新有效性为 `valid`；
5. 来源不是 `agent` 自报或 `core` 自动事件；
6. 验证输入和产物可定位；
7. 没有未解释的失败/未知信号阻断；
8. 如果存在旧 ready 版本，满足回归要求。

### 3.4 回归要求

新版本只验证一个新案例，不足以证明旧行为未破坏。

建议规则：

- 首个版本：至少一个新案例验证；
- 修订版本：
  - 必须重新执行旧版本曾经通过的验证案例；
  - 再执行新案例；
  - 或者提供显式人工例外，说明为什么无法回归，并记录风险；
- 用例集合可以为空，但空集合不能自动视为通过；
- manifest 当前没有 `verification` 字段，结构化用例会被拒绝；在实现前，回归用例只能作为外部产物引用。

### 3.5 失败/未知处理

- 最新验证失败：拒绝晋升；
- 最新验证未知：拒绝晋升，除非后续产生新的 passed；
- 旧失败后新成功：新成功必须晚于失败，且旧失败保留在审计中；
- 验证时间早于候选创建：无效；
- 内容哈希不匹配：无效；
- 证据 stale/superseded：无效。

---

## 4. `promote_version` 晋升契约

### 4.1 保留公开 API

继续使用：

```text
promote_version(version_id, reason, evidence_ref?)
```

不新增第五个公开工具。

### 4.2 准入流程

```text
读取 version
→ 必须是 candidate
→ 内容扫描通过
→ 重新确认 content_hash
→ 查找绑定该版本的有效验证证据
→ 检查验证时间、来源、有效性和回归要求
→ 全部通过
→ 事务内标记 ready、更新 current 指针、写 version_promoted 事件
```

### 4.3 拒绝原因

建议的内部 reason 分类：

```text
verification_required
verification_not_bound
verification_before_candidate
content_hash_mismatch
source_not_independent
verification_failed
verification_unknown
verification_stale
regression_required
regression_failed
policy_blocked
```

公开错误码是否新增，暂不决定。可以继续使用现有 `INVALID_ARGUMENT` / `CAPABILITY_NOT_READY`，并在响应中返回结构化 `reason_code`，避免提前扩展稳定错误码集合。

### 4.4 旧版本保留

- 旧版本内容、哈希、状态不变；
- 只移动 `current_version_id`；
- `version_promoted` 事件记录新旧版本和证据引用；
- 晋升后证据失效不自动回滚；由维护流程显式处理；
- `rollback_version` 仍可回到旧 ready 版本。

### 4.5 审计要求

`version_promoted` 事件至少记录：

```text
capability_id
old_version_id
new_version_id
reason
evidence/verification references
promoted_at
```

---

## 5. 现有机制 / 缺失 / 未决汇总

| 项目 | 现有 | 缺失/不足 | 未决 |
|---|---|---|---|
| 结果信号关联版本 | 已有 invocation/version 校验 | content_hash 未入信号；幂等键缺失 | 新字段或派生校验 |
| 失败/未知 | 已有枚举 | 无 | — |
| verified success | 只有 source_type | 无验证产物、验证者、版本哈希绑定 | 身份/审计模型 |
| 验证证据 | 有通用 evidence + validity | 无专用验证对象/方法/产物字段 | 扩展事件或新表 |
| 候选版本 | 有 candidate + propose_repair | 普通 save 修订仍可直接 ready（实现待改） | 方向已定：修订一律 candidate；存储/兼容细节未决 |
| 回归要求 | 无 | manifest 不支持 verification cases | 用例存储/执行方式 |
| 晋升 | 有 promote_version | 只做内容扫描，无证据门槛 | 错误码/响应形状 |
| 旧版本保留 | 不可变版本、rollback | 足够 | — |
| 跨 Harness | MCP 四工具、共享目录 | 无统一行为规则 | 不在本契约内 |

---

## 6. 本契约的验收条件

未来实现必须能证明：

1. 相同结果信号重复提交不会重复计数；
2. verified success 必须绑定具体版本内容哈希；
3. stale/superseded/unassessed 证据不能晋升；
4. 候选创建前生成的验证不能用于晋升；
5. 自报 agent success 不能单独晋升；
6. 修订版本未覆盖旧行为时不能晋升；
7. 晋升失败不改变当前指针；
8. 晋升成功保留旧版本和完整审计；
9. 普通保存不能静默绕过已声明的晋升规则；
10. 跨会话/跨兼容 Harness 读取同一能力与证据语义。

---

## 7. 版本生命周期收敛

### 7.1 `toolbox_save` 操作分类

`toolbox_save` 只负责“创建”或“提交修订候选”，不负责晋升。

| 调用形式 | 操作语义 | 版本状态 | 是否移动 current |
|---|---|---|---|
| 无 `target_capability_id`，名称/内容为新 | 新建 Capability | `ready`（内容扫描 clean） | 是 |
| 无 target，内容触发 review | 新建 Capability | `candidate` | 否 |
| 无 target，命中精确重复 | 返回既有 Capability/Version | 不变 | 否 |
| 有 target，内容哈希不同 | 修订已有 Capability | `candidate` | 否 |
| 有 target，内容哈希相同 | 精确重复，返回既有版本 | 不变 | 否 |
| 有 target，但目标 archived | 拒绝 | 不变 | 否 |
| 有 target，但目标 quarantined | 允许创建 candidate | `candidate` | 否 |

`propose_repair` 也是修订入口，必须产生 `candidate`，不得直接 ready。

`toolbox_save` 在任何情况下都不得：

- 将修订版本直接置为 `ready`；
- 移动当前版本指针；
- 绕过 `promote_version` 的证据检查。

### 7.2 版本状态与可用性

| 状态 | 可搜索 | 可通过 current 交付 | 可晋升 | 说明 |
|---|---|---|---|---|
| `candidate` | 否 | 否 | 是，需证据 | 修订候选或 review 候选 |
| `ready` + current | 是 | 是 | 不适用 | 当前正式版本 |
| `ready` + 非 current | 否 | 否 | 不适用 | 历史正式版本，保留并支持回退 |
| `quarantined` | 否 | 否 | 否，直到 release | 隔离版本 |
| capability archived | 否 | 否 | 否 | 能力级退役 |

说明：

- 搜索和交付只看 current ready；
- candidate 不出现在搜索结果中，也不能通过 capability 名称交付；
- 旧 ready 版本保留，rollback 可以重新指向它；
- 失败、未知、stale/superseded、unassessed 验证证据不会改变 candidate 状态，只会阻止晋升；
- 晋升失败不改变 current 指针。

### 7.3 允许的状态转换

```text
新建 Capability:
  (none) -> ready[current]
  (none) -> candidate          # content review

修订已有 Capability:
  ready[current] + save revision -> candidate
  candidate -> ready[current]   # promote, evidence gate
  candidate -> quarantined      # quarantine
  ready[current] -> quarantined # quarantine + fallback/new current
  quarantined -> candidate      # release
  ready/historical -> ready/current  # rollback, no content change
```

禁止：

```text
candidate -> ready without promote
save revision -> ready directly
save revision -> current pointer movement
promote -> content rewrite
promote -> deletion of old version
```

### 7.4 兼容策略

#### 现有数据

- 已存在的 `ready` 版本和 current 指针保持不变；
- 不因新契约追溯性降级；
- 已存在的 `candidate` 版本保留为 candidate；未来晋升按新门槛检查；
- 不为已有版本伪造验证证据；
- 旧版本内容、哈希和审计不重写。

#### 现有调用方

`toolbox_save(target_capability_id=...)` 的语义发生**有意的行为变化**：

```text
旧行为：clean revision -> ready，可能替换 current
新行为：revision -> candidate，current 不变
```

因此：

- 新建 Capability 的调用方不受影响；
- 精确重复保存不受影响；
- 使用 target 的调用方必须检查 `version_status`，并通过 `promote_version` 完成晋升；
- 不新增第五个工具，也不新增“save 并 promote”的复合入口；
- 这应作为下一个发布版本的明确 breaking semantic change 记录，不静默混入 0.3.x 补丁。

#### 尚未决定的兼容选项

- 是否提升公共协议/API 版本号；
- 是否在响应中增加显式 `operation: create|revision`；
- 是否允许一个显式“兼容模式”临时保持旧行为（不建议默认开启）；
- 已存在 candidate 缺少验证证据时，是保持 candidate、拒绝晋升，还是提供显式人工例外。

### 7.5 与证据契约的衔接

- 结果信号和验证证据仍绑定 version + content_hash；
- `promote_version` 读取最新有效验证证据；
- 失败/未知/过期证据只阻止晋升，不删除证据；
- 幂等键防止重复信号被误计为多次独立成功；
- 旧版本保留，晋升审计记录 old/current/new；
- ToolSeed 自身成本不可测量时仍记 `unknown`。

### 7.6 本节结论

采用以下方向，不再作为未决项：

```text
新建能力：可以按现有规则进入 ready
已有能力修订：必须进入 candidate
候选晋升：必须经过 promote_version 的证据检查
```

实现前仍需确认：协议/API 版本策略、candidate 缺证据时的兼容处理、验证证据的存储形状。

## 8. 明确不做

- 不引入密码学身份认证；
- 不自动反思；
- 不自动晋升；
- 不新增第五个公开工具；
- 不实现 Workflow；
- 不为了通过契约而虚构验证证据；
- 不在没有真实任务案例时创建测试能力来“证明”闭环。

## 9. 存储与事务边界审查（实施前）

### 9.1 现有存储事实

审查确认：

- `evidence_events` 已有 `capability_id/version_id/invocation_id/task_id/outcome/source_type`；
- 没有 `content_hash`、验证方法、产物引用、验证者、幂等键；
- `evidence_validity_assessments` 以 `evidence_id` 为对象，已有 `valid/stale/superseded` 投影；
- `evidence_events` 没有唯一幂等索引；
- `capability_versions.status` 没有数据库 CHECK；
- `current_version_id` 没有外键约束，正确性由应用代码维护；
- SQLite 未启用 `PRAGMA foreign_keys`；
- 版本身份有部分唯一索引，但 evidence 没有对应唯一性约束。

结论：

```text
现有表能表达“某版本发生了某事件”
不能直接表达“某验证证据绑定某内容哈希且可幂等”
```

### 9.2 建议的存储决定

采用**扩展 `evidence_events`**，而不是立即新建验证表：

新增迁移 6 字段：

```text
content_hash TEXT NULL
signal_key TEXT NULL
verification_outcome TEXT NULL   -- passed / failed / unknown
verification_json TEXT NULL
```

新增部分唯一索引：

```sql
CREATE UNIQUE INDEX ... ON evidence_events(signal_key)
WHERE signal_key IS NOT NULL;
```

验证记录使用新的 `event_type`：

```text
version_verification
```

保留：

- `evidence_id` 作为验证记录身份；
- `evidence_validity_assessments` 继续以 evidence_id 判定有效/过期；
- `source_type`、`summary` 和现有审计字段继续使用；
- 验证方法、输入引用、产物引用、artifact hash 放在 `verification_json`，不新增通用执行引擎。

理由：

- 复用现有 append-only 审计和有效性投影；
- 避免新表与 evidence 表双写；
- 迁移小，旧事件保持 NULL，不追溯；
- 本地单用户场景优先最小存储。

未决/风险：

- `verification_json` 是弱类型，查询和约束不如独立表；
- 如果以后需要按验证方法/产物哈希做索引，再迁移到独立表；
- 新增字段是 schema v6，需要原子迁移。

### 9.3 事务边界事实

当前 `Store.transaction()`：

- 只维护嵌套深度；
- 外层成功才 commit，失败才 rollback；
- **没有显式 `BEGIN` / `BEGIN IMMEDIATE`**；
- 嵌套事务没有 savepoint。

当前 `promote_version`：

- 在事务外读取 version、status、content；
- 在事务内更新 status/current 并写事件；
- 存在“读取后、更新前状态变化”的竞态窗口；
- `registry.promote_version` 选择当前最高 ready 版本，不一定等于刚 promote 的候选。

### 9.4 建议的事务决定

- 所有 promotion 的读取、验证证据检查、状态更新、current 更新、审计事件写入必须在**同一个显式 `BEGIN IMMEDIATE` 事务**内完成；
- 不在事务外做“候选是否合法/证据是否存在”的最终判断；
- 更新语句必须带状态条件，例如：

```sql
UPDATE capability_versions
SET status = 'ready'
WHERE version_id = ? AND status = 'candidate';
```

- current 指针更新与状态更新同事务；
- 旧版本内容不更新；
- 如果证据检查失败，回滚且不移动 current；
- 建议为 `Store.transaction()` 增加显式 immediate 模式，而不是无条件改变所有读路径。

### 9.5 current 指针语义决定

promotion 后 current 应该指向：

```text
被 promote 的 candidate
```

但现有实现按 `version_number` 选择最高 ready 版本。需要明确：

- 修订 candidate 总是最高版本，行为一致；
- 如果未来允许 promote 旧 candidate，current 不应被旧版本覆盖；
- 因此 promotion 必须显式决定是否移动 current，不能只依赖“最高 ready”。

建议：

```text
promote 只在该版本成为最高 ready 版本时移动 current；
否则保持 current，并在响应/审计中说明。
```

### 9.6 本阶段结论

```text
证据存储：扩展 evidence_events + 迁移 6
验证记录：event_type=version_verification
幂等：signal_key 部分唯一索引
事务：promotion 使用显式 BEGIN IMMEDIATE
current：由 promotion 显式决定，不依赖隐式最高版本
```

仍未实现；下一步才是按此决定修改存储、`_save_candidate_impl`、`promote_version` 和测试。

## 10. v0.4.0 实现限制

以下限制必须与实现一起保留，不能被宣传成已完成能力：

- `record_version_verification` 记录的是本地声明并留痕的验证结果，不是密码学意义上的可信证明；写入后自动标记为 `valid` 仅表示“该本地证据当前可用”。
- `regression_case_ids` 只证明验证记录引用了回归用例；v0.4.0 不执行回归用例，也不能把晋升门槛描述成“系统已自动执行并验证所有旧行为”。
- `task_outcome_signal` 尚未实现强制 `signal_key` 幂等；重复上报仍可能被计数。本次只实现了 `version_verification` 的幂等。
- 当前没有验证者身份认证；`source_type`、`verifier` 和 `artifact_ref` 是可审计约定，不是身份认证。
