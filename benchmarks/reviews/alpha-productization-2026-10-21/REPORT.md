# ToolSeed Alpha 产品化收尾：改动与验证报告

日期：2026-10-21。基线 `c0cac122c1a149e3f6c1a2501a683db323fc5131`，分支 `develop`。
本轮只做文档/Skill 收尾与必要回归；未改 Core、Schema、四个公共工具协议或数据模型，
未新增能力类型/自动反思/语义检索/基础设施，未重跑 A/B 实验。

## 1. 实际修改文件

| 文件 | 性质 | 改动 |
|---|---|---|
| `toolseed/skill/SKILL.md` | 修改 | §5 增补"提交前自检"字段上限表、"保存被拒如何最小修正"处置规则、"不是每个任务都要保存"的明确表述 |
| `README.md` | 修改 | 修正过时声明"MCP 层尚未实现"；新增《Alpha 快速上手》七步（安装、MCP stdio 配置、核验四工具、设置并核验数据目录、搜索/保存/交付、Invocation/Evidence/unknown、支持范围）；修正测试数量声明；测试覆盖列表补入新的文档一致性用例 |
| `docs/ALPHA-STATUS.md` | 新增 | Alpha 状态说明：已验证机制、已观察到的能力复用、尚未证明的净收益、当前不支持的功能、已知限制、交付结论 |
| `tests/test_skill_contract.py` | 新增 | 7 条防漂移回归：Skill 写明的字段上限必须等于 Core 权威常量、Skill 必须说明契约错误恢复、README 不得再出现"未实现"式过时声明、两份文档的测试数量必须与实际套件一致 |
| `benchmarks/reviews/alpha-productization-2026-10-21/REPORT.md` | 新增 | 本报告 |

未改动：`toolseed/core/**`、`toolseed/adapters/**`、`toolseed/mcp_server.py`、`toolseed/cli.py`、
`docs/P0-SLIM.md`、`docs/DESIGN.md`、`docs/EVIDENCE-PROMOTION-CONTRACT.md`、
`pyproject.toml`、工作流与全部实验数据目录。

## 2. 解决的用户体验问题

**（a）保存被拒时 Agent 不知道该改什么（真实发生过的摩擦）**
上轮真实实验中 `toolbox_save` 因 `manifest.description` 超过 280 字符返回
`CONTRACT_VIOLATION`，Agent 只能盲改。Skill 现在写明全部字段上限（name ≤ 80、
description ≤ 280、when_to_use ≤ 500、not_for ≤ 10×160、tags ≤ 12×40、
applicability ≤ 20×120、content ≤ 32 KiB、整体 ≤ 64 KiB，并区分字符上限与字节上限）、
要求提交前自检，并规定：读 `error.code`/`error.message` → 只改被点名的字段 → 只提交一次 →
不重发未改动的候选、不靠删 `content` 来满足 manifest 上限；`POLICY_BLOCKED` 是拒绝而非格式
问题，不得改写措辞绕过。**未放宽 Core 任何既有契约**（上限常量与校验逻辑一字未动），
仅让 Agent 侧知道契约。

**（b）"是否每个任务都要保存"没有明确口径**
Skill 明确：不是每个任务都以保存结束；没有可复用方法的任务可以不保存，这是正常结果。
保存的触发仍由既有 L0/L1/L2 成本分层与"具体信号"决定。

**（c）安装/接入/核验步骤散落，Alpha 用户难以走通**
README 新增《Alpha 快速上手》，把七件事各给一条可本地核验的路径：安装并确认入口、
按 `mcpServers`/`mcp_servers` 配置 stdio、用官方 MCP 客户端连一次并确认恰好四个工具与
含 `capabilities`/`versions` 的 stats、设置并**核验**数据目录（确认 `<data-dir>/toolseed.sqlite3`
生成、确认默认 `~/.toolseed` 未被误建）、搜索/保存/交付的最小 JSON 序列、
Invocation/Evidence/`unknown` 的含义与"找到→交付→采用→成功"四层区分、支持范围与限制入口。

**（d）文档自相矛盾与过时数字**
README 曾写"MCP 层尚未实现"（MCP stdio 层早已实现并用官方 SDK 2.3.0 验证），
且测试数量停在 175（实际 251）。两处已更正，并由新测试锁死。

## 3. 回归验证结果

| 验证 | 结果 |
|---|---|
| 完整单元测试 | **252 项通过，2 项按条件跳过**（`TOOLSEED_SKIP_STDIO_TEST=1`，本机沙箱限制）；连续 3 次重复运行结果一致 |
| 项目质量门禁 `scripts/quality_gate.py` | **四项全 PASS**：compileall、unittest、ruff、mypy（mypy 范围为 `toolseed`，15 个源文件无问题） |
| 新增文档/契约回归 | 7 项通过：Skill 字段上限 == Core 权威常量、manifest 七字段齐备、契约错误恢复指导齐备、"不是每个任务都要保存"表述存在、README 无过时"未实现"声明、两份文档的测试数量 == 实际套件数量 |
| 契约错误行为复现（产品实跑） | 300 字符 `description` → `ok:false`、`code=CONTRACT_VIOLATION`、`message="manifest.description exceeds 280 characters"`、`retryable=false`；仅缩短该字段后 → `status=accepted`、`version_status=ready`。**与 Skill 所写逐字一致** |
| 打包形态 | 进程内构建 wheel：22 个条目，`toolseed/skill/SKILL.md` 已打包（5,323 字节），且包含 280 上限与 `CONTRACT_VIOLATION`/`POLICY_BLOCKED` 处置规则 |
| 文档链接与锚点 | 三份文档的相对链接全部可达（0 处断链）；README 新增的 5 个锚点均命中真实标题 |
| 静态检查 | ruff 全通过；新增测试文件 mypy 无问题 |

**未通过项说明（与本轮改动无关）**：不设 `TOOLSEED_SKIP_STDIO_TEST=1` 时，
`tests/test_mcp_server.py::test_stdio_subprocess_exposes_the_same_tools` 因本机沙箱禁止
子进程管道而报 `PermissionError`。这是 README 已记载的本机限制，CI 工作流在三个平台定义了该
用例；**本轮没有 CI 运行记录，因此不声称 CI 已通过**。

### 3.1 交付审查阶段对"偶发 unittest 失败"的追查

审查阶段复核了收尾阶段记录到的两次门禁 unittest 失败：

- **第一次已完全定位**：该次调用未设置文档化的 `TOOLSEED_SKIP_STDIO_TEST=1`，输出为
  `errors=1, skipped=1`（正常跳过时为 2）。用**单用例定向复跑**
  （`python -m unittest tests.test_mcp_server.MCPServerTest.test_stdio_subprocess_exposes_the_same_tools`）
  得到的 traceback 与当时记录的 stderr 片段**逐字一致**：
  `asyncio/windows_utils.py` 的 `pipe()` → `_winapi.CreateFile(..., _winapi.OPEN_EXISTING, ...)`
  → `PermissionError: [WinError 5]`。即沙箱拒绝创建重叠管道句柄，属已记载的本机限制，
  不是代码缺陷，也未申请扩大权限。
- **第二次未定位，保留为未解决项**：该次发生在"文档测试数量与实际套件数量同步"的那一轮编辑
  窗口内，其 unittest stderr 被终端过滤截断，**没有留下可恢复的错误信息**（本机也没有落盘的
  门禁日志；仓库内两个 `.log` 均为 2026-10-18 的旧文件，且 `*.log` 已被忽略）。
  随后连续 5 次运行（3 次直接单测 + 2 次门禁）均为 252 项 OK / 门禁四项全 PASS，未再复现。
  按审查要求，不为重复证明已有结果而再跑多轮完整测试，**此项保留为未解决的偶发问题**，
  不记作已修复、也不记作已定位。
- 顺带核对了进程环境传播：shell 设定的环境变量能到达孙进程（探针验证），
  因此跳过标志在门禁子进程中有效。

## 3.2 交付审查阶段修正的缺陷

审查发现并仅修复以下三处表述/命名缺陷（未重构、未改行为）：

1. `docs/ALPHA-STATUS.md`：两处把 CI 工作流**配置**写得像"CI 已通过"，改为"由 CI 工作流在三个
   平台执行（本轮无 CI 运行记录）"；并补一句"被检索命中、被交付、被采用都不等于任务成功"。
2. `README.md`：《Alpha 快速上手》第六步原写"三层要分开说"但实际列了四层（找到→交付→采用→成功），
   改为"四层"。
3. `tests/test_skill_contract.py`：`test_skill_requires_exactly_the_manifest_fields` 的名称
   强于其断言（只校验七字段均出现），更名为 `test_skill_lists_every_manifest_field`。

修正后运行针对性回归：新测试文件 8 项通过；一次完整套件 252 项通过（2 项按条件跳过）；
一次门禁四项全 PASS。

## 4. 仍然存在的产品限制

- **净收益仍未证明**：真实实验中方法库组在模型结算、请求 Token、工具调用与墙钟上均高于对照组；
  provider 侧计费 Token 与货币成本不可得，净收益为 `unknown`。
- **成本与用量不可审计**：宿主不暴露精确 Token 与计费时相关字段保持 `unknown`；
  失败/取消尝试的规范化用量可能是零值，不能解释为真实零成本。
- **内容检查不等于内容可信**：结构与敏感内容静态检查通过不代表方法正确或已核实；
  `version_status: ready` 只表示通过结构门槛。
- **保存受信任主体限制**：Procedure 是不可信数据，只作能力材料交付；不执行代码、无沙箱。
- **共享目录即共享状态**：多宿主指向同一 `--data-dir` 会共享能力库；迁移冲突需显式
  `migrate-check`/`migrate-repair`。
- **宿主接入验证不完整**：MCP stdio 与配置格式已用官方客户端验证，Claude Code / Cursor / Codex
  的客户端 UI 接入尚未逐个人工确认。
- **不支持**：代码执行/沙箱、`executable`/`workflow`、多文件或 ZIP 能力包、异步保存队列、
  多用户 RBAC、检索缓存、向量检索与 LLM 重排、自动反思/自动修复。
- **单用户本地**：本地存储受当前用户权限保护，不是多租户服务。

以上限制已写入 `docs/ALPHA-STATUS.md` §5、§6，与 P0-SLIM 的范围声明一致。

## 5. Alpha 是否具备交付条件

**具备，但带明确边界。** 交付条件判定：

- 四个公共工具、Procedure 保存/检索/交付、不可变版本与内容哈希、证据分离与 `unknown` 纪律、
  本地持久化与官方 MCP stdio 服务：已实现且经测试与实跑验证；
- 使用路径可由使用者自行核验（安装 → 配置 → 确认四工具 → 核验数据目录 → 保存/检索/交付）；
- 使用摩擦（保存被拒无指引）已在 Skill 层修复，且不改动 Core 契约；
- 产品状态（已验证机制 / 已观察复用 / 未证明净收益 / 不支持 / 限制）已成文，可被审阅。

不随 Alpha 承诺的事项：净收益为正、自主改进、跨主机无条件可移植、代码执行安全。
若要评估收益，前置条件是补齐 provider 侧用量证据（见
[用量证据关闭报告](../usage-evidence-closure-2026-10-21/REPORT.md)）。

## 6. Git 与历史资产状态

- 提交：`277f38fddbcf2d8e32b1fc746ff750eb07b4846f`（分支 `develop`，父提交 `c0cac12`），
  标题 `docs: state the Alpha delivery boundary and the save-usage rules`。
- 提交内容**仅四个正式产品文件**：`README.md`、`toolseed/skill/SKILL.md`、
  `docs/ALPHA-STATUS.md`、`tests/test_skill_contract.py`（4 files changed, 353 insertions(+), 3 deletions(-)）。
- **审查报告未纳入提交**：仓库既有惯例是 `benchmarks/` 与 `docs/` 只跟踪代码与规范文档
  （`git ls-files` 仅有 `benchmarks/README.md`、`benchmarks/__init__.py`、
  `benchmarks/live_experiment.py`、`benchmarks/value_experiment.py` 与三份 docs 规范），
  从未跟踪评审或实验报告；且本报告引用的实验工件同样未跟踪，若纳入提交会形成指向
  仓库外文件的悬挂引用。故报告与全部实验产物保留在工作区、未提交，此处明确记录该决定。
- 15 份此前受保护的历史文件复核 0 处变化；18 份已登记交付物哈希 0 处漂移；
  三个实验数据目录与原始 `experiment-artifacts.zip` 均在原位，未修改、删除或公开。
- 提交后工作树仅剩三个未跟踪目录：`benchmarks/plans/`、`benchmarks/results/`、
  `benchmarks/reviews/`（历轮实验与评审产物，按上条理由不纳入提交）。
- `git diff --check` 干净；未推送、未打 tag、未创建 Release、未发布 PyPI；
  未修改 Core、Schema、四工具协议与正式预注册。

到此停止，等待人工架构审查。
