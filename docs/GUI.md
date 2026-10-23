# ToolSeed GUI v0.1

以发布 Tag `v0.4.1`（`5786f47`）为基线的本地只读 Web 面板。包版本与数据库 Schema 保持不变。

## 启动

无需额外 GUI 依赖，可直接从仓库启动：

```powershell
.\.venv\Scripts\python.exe -m toolseed.ui --data-dir F:\ToolSeed\.toolseed
```

或在所选 Python 环境安装当前工作树后使用入口：

```bash
python -m pip install -e .
toolseed-ui --data-dir /absolute/path/to/.toolseed --port 8765
```

浏览器打开终端打印的 `http://127.0.0.1:8765`。不自动打开浏览器；Ctrl+C 关闭服务。
`--port 0` 可选择空闲端口。地址固定为 `127.0.0.1`，不提供公网监听配置。
数据目录优先级：显式 `--data-dir`，其次 `TOOLSEED_DATA_DIR`，最后 `~/.toolseed/`。
默认每 5 秒刷新，也可手动刷新；查看详情、展开记录或输入过滤条件期间暂停自动刷新。

## 页面和事实来源

| 页面 | 内容 | 数据来源 |
| --- | --- | --- |
| 已入库能力 | 名称、简短说明、可用状态和场景；搜索名称/描述/场景；详情展开版本、验证、近期历史与高级信息 | capabilities、capability_versions；既有只读能力查询 |
| 活动 | 分页卡片呈现检索、保存、交付、失败与其他实际事件；可从能力详情查看关联活动，点击查看证据与来源 | evidence_events，关联能力/版本；按追加 rowid 倒序 |
| 顶部统计与详情证据（非独立页面） | 能力总量、指引交付总量；详情区分已保存、已交付、实际采用与任务确认 | 既有 overview / capability / evidence 查询；最新追加有效性评估 |

能力详情仅对当前 ready 且未归档/整体隔离的版本显示正文；其他版本保留管理元数据。
正文以文本呈现，始终是不可信能力材料。浏览和界面搜索不调用 `toolbox_run` / `toolbox_search`，
不增加 Invocation 或检索计数。详情的近期关联记录最多 30 条，可跳转分页活动；版本验证按既有
证据接口分页读取。全部证据查询仍保留在内部接口和 `toolseed evidence`，没有删除底层记录。
内部 ID 和原始字段默认折叠在“高级信息”；描述生成标题仅做展示，不改能力名称或关联关系。
具体行为和实际截图见 [PANEL-SIMPLIFICATION.md](PANEL-SIMPLIFICATION.md)。

证据成熟度以实际存在的层次和来源表达，不合成全局分数：结构准入、指引交付、版本验证声明、
Agent 自报任务结果、外部来源任务结果。`ready`、`valid`、测试执行器来源声明都不能独立证明任务成功。
外部结果也保留原始来源、版本及调用关联；GUI 不执行验证器或读取外部产物以认证其真实性。
原 overview 查询仍保留“未有外部结果的交付”等管理统计；Agent 自报不会把它变成已确认结果。
结果信号可能重复上报，数量不等于独立任务数。

## 只读边界

使用 SQLite `mode=ro` + `PRAGMA query_only=ON`，每次请求独立连接与读快照，可读取 Core/MCP
新提交的 WAL 记录。不会实例化 `Store`，因此不创建数据目录、不建表、不迁移、不修复能力记录。
SQLite 读取 WAL 时可能使用其共享内存辅助文件；这不等于修改权威能力数据。

只提供 GET/HEAD 查询和静态资源，拒绝写请求；不开放删除、修改、晋升、回滚或执行入口。
只允许 loopback Host 与同源请求，拒绝跨站 Origin / Sec-Fetch-Site；无跨域读取授权。
资源全部随包提供，无 CDN、第三方前端依赖或模型调用；响应不缓存，正文和元数据转义显示。

缺少数据库时显示等待提示而不创建文件；已初始化的空库显示真实零条目；无效目录、损坏文件、
结构异常及非 Schema v6 的数据库均明确提示。GUI 不自动修复，迁移仍由对应版本 Core 管理。

## 最小活动补充与历史缺口

检查到 v0.4.1 已有 `procedure_saved`、`search_performed`、`procedure_delivered`、`duplicate_save`、
任务信号、版本验证和管理事件。成功路径直接复用这些记录，不重复写一套分析事件。

新增 `tool_call_failed` 复用现有 `evidence_events`，无需迁移（仍为 Schema v6）：

- 仅在 Core 四工具中的 search/save/run 返回结构化失败时，尽力追加事件。
- 仅保存时间、事件 ID、Core 来源、固定工具名、`status=failed`、错误码，以及能核验存在的目标能力 ID。
- 错误码映射为简短原因；不持久化错误消息原文，避免未知字段名夹带秘密。
- 不保存查询、提示词、候选正文、参数、保存理由、原始名称或隐藏推理。
- 事件的 `outcome=unknown`：工具调用失败不自动代表原任务失败。
- 类型为仅活动记录：计入 `total_events()` 和 Activity，但不进入有效性投影、`unassessed`、通用证据评估建议或重新验证范围。
- 记录失败不替换原来的公共响应；存储不可用时事件可能无法落盘，不承诺完整故障遥测。

以下内容仍未知或未记录：

- 旧版公共调用失败历史、未进入 Core 的 MCP 参数校验/传输失败、进程崩溃、stats 异常及管理调用失败；
- 存储故障导致无法落盘的活动；
- 历史检索的查询、具体命中能力、任务因果关联（不补造）；
- Agent 是否实际采用方法、程序是否执行（当前 Core 只交付 Procedure）；
- 无结果信号的任务结局，以及 Token、账单和净收益。

重复交付仅是可观察的重复交付，不推断已确认采用或收益。没有证据的层次显示“未知/未记录”。

## 首轮 GUI 验证（历史记录）

GUI 累计新增 28 项测试（首轮 22 项，本次架构核查 6 项），覆盖只读查询/HTTP、真实 Core 写入后的可见性、空库/缺库/损坏库/旧 Schema、
候选与隔离门禁、分页搜索、来源与有效性分离、跨站拦截及最小失败事件。
首轮 146 项定向测试全部通过，包含当时的 22 项新增测试和受影响的公共契约、交付、存储、
版本、生命周期、namespace、并发及官方 MCP 四工具检查；未重跑 A/B 实验或完整套件。

```bash
python -m unittest tests.test_ui tests.test_activity_recording tests.test_contract tests.test_evidence tests.test_persistence tests.test_delivery tests.test_search tests.test_adapter tests.test_versions tests.test_lifecycle tests.test_namespace tests.test_concurrency tests.test_skill_contract tests.test_mcp_server.MCPServerTest.test_server_exposes_exactly_four_tools tests.test_mcp_server.MCPServerTest.test_tool_call_returns_structured_stats -q
```

浏览器检查覆盖真实本地库四页、搜索、能力详情与 390px 移动布局；独立测试库用于检查后续 Core
写入自动刷新，测试数据不混入用户能力库。wheel 在项目内临时虚拟环境离线安装，验证入口及静态资源。

实现未提交、未推送、未覆盖 Tag 或历史 Release，也未发布新版本。完成后等待人工架构审查。

## 实际修改文件

- `pyproject.toml`：新增 toolseed-ui 入口与随包静态资源。
- `toolseed/ui.py`：本地 HTTP 服务、固定 loopback 监听、只读路由及启动参数。
- `toolseed/core/inspection.py`：独立只读数据库查询，不初始化 Store。
- `toolseed/core/api.py`、`toolseed/core/evidence.py`：复用证据表记录最小公共调用失败。
- `toolseed/ui_assets/index.html`、`app.css`、`app.js`：当前两页界面、搜索、详情、分页和刷新。
- `tests/test_ui.py`、`tests/test_activity_recording.py`：累计新增 28 项测试。
- `README.md`、`docs/ALPHA-STATUS.md`：启动入口与套件规模说明，明确本轮仅定向验证。
- `docs/GUI.md`：使用、数据语义、历史缺口与交付记录。

## 最后架构核查：失败活动与证据评估隔离

全部验证使用临时数据库，未读取真实用户数据库。核查发现原先的失败事件会经
`validity_counts()` 的全事件范围进入 `unassessed`，并由 `maintenance_report()` 生成
`assess_evidence` 建议。`run_maintenance()` 会持久化该误建议；重复运行虽去重，但首次污染确实存在。

最小修复只将新增的 `tool_call_failed` 分类为仅活动记录，不改变任何既有事件类型的评估规则：

- `total_events()` 继续统计所有真实事件，包括失败活动，不隐藏记录。
- 有效性计数的事件范围与评估投影都排除该类型；保留原有最新追加记录规则与计数公式，未顺带修改孤立评估等既有处理。
- `assess_evidence` 和底层 `Evidence.assess` 拒绝对此类型新增评估；`evidence_validity` 返回 `assessable=false`、空当前投影，并保留既有评估历史供审计。
- 版本级投影及版本证据过期查询使用同一类型排除；原有重新验证事件白名单保持不变。
- 活动继续展示失败且不当作能力证据；不会将旧评估声明展示为当前有效证据。底层 evidence 查询仍只展示原有证据类型。
- 不删除或重写历史事件、评估、维护决策；旧误建议不自动结案。候选晋升仍须绑定真实版本验证记录，决策应用仍检查原 scope、最新有效性与创建后的重评 watermark。

在相同临时场景中，先保存并交付能力，明确评估已有两条证据，再通过真实 Core 调用传入无效参数制造一次失败：

| 指标 | 失败前 | 失败后（修复前） | 失败后（修复后） |
| --- | --- | --- | --- |
| 原始事件总数 | 2 | 3 | 3 |
| valid / stale / superseded | 2 / 0 / 0 | 2 / 0 / 0 | 2 / 0 / 0 |
| unassessed / 待评估证据 | 0 | 1 | 0 |
| 版本有效性投影 | valid=2 | valid=2 | valid=2 |
| 维护建议 / 首次新增决策 | 0 / 0 | 1 / 1 | 0 / 0 |
| 再次维护新增 / 去重跳过 | 0 / 0 | 0 / 1 | 0 / 0 |
| 任务结果信号（成功、失败、未知） | 均为 0，未测量 | 不变 | 不变 |

另行验证已有待评估证据仍为 1，原维护建议与决策 ID 不变，连续失败不会增加建议，重复维护仍按原规则去重。
六项新增回归还覆盖：空库仅失败活动、已有投影与历史不变、旧失败评估保留但无授权效力、候选晋升门禁、维护决策应用门禁。
本次共运行 131 项相关定向测试，全部通过（统计、证据、维护生命周期/并发、晋升门禁、失败活动、GUI 和固定工具面）。
Schema v6、四个公共工具协议及只读 HTTP 安全边界均保持不变；本次未执行全量套件、A/B 实验或全量质量门禁。
