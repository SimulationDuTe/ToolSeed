# 本地管理入口与宿主支持（更新于 2026-10-22）

本轮以已发布的 v0.4.1（`5786f47`）为基线，在现有未提交 GUI 上增量开发。
Python 包版本保持 0.4.1；本地 DSH 插件标识 0.1.0，不代表新版本已发布。
没有提交、推送、覆盖 Tag、修改 Release 或发布 PyPI。

## 入口与事实来源

| 入口 | 实现与范围 | 数据来源 |
|---|---|---|
| Core / 四个 MCP 工具 | 原业务、安全与证据语义；本轮未修改 | 同一数据目录的 Store / Evidence |
| 管理 CLI | `status`、`capabilities list/show`、`activity`、`evidence` | 既有只读 `Inspector`，SQLite `mode=ro` + `query_only` |
| DSH 原生面板 | 官方 `settings.section`；设置 → ToolSeed；已入库能力 / 活动；证据在详情中展开 | 宿主 owner-admitted Connection 通道调用固定 Python 的只读 CLI |
| 独立 Web GUI | 可选 `toolseed ui` / `toolseed-ui`，固定 `127.0.0.1` | 同一个 Inspector 和 GUI 静态资源 |

所有入口使用 `--data-dir`，或原有 `TOOLSEED_DATA_DIR` / `~/.toolseed` 默认规则。
DSH 插件只允许安装配置选定 Python 和数据目录，请与 MCP 使用同一绝对路径。面板查询不能改目录。
本机既有 MCP 指向 `F:\ToolSeed\.toolseed`，新面板也配置为此目录，未另建宿主专属能力库。

管理查询不调用 `toolbox_search/run`，不会把浏览统计写为使用记录，不初始化 Store、不迁移数据库。
顶部能力数和指引交付数来自既有 overview 查询；状态分布等完整管理数据仍可从 CLI 查询。
status 中的服务状态为 `unknown`，读库成功不表示 MCP 或独立 UI 正在运行。面板只提示当前查询错误。

能力列表包含实际存在的 ready / candidate、整体隔离与归档元数据；只有当前 ready 且能力未隔离、
未归档时才显示正文，与既有 Inspector 的交付限制相同。面板和新增 CLI 不提供执行、删除、提升、
回滚或修改权限。既有显式管理 CLI 未被改写。

证据继续区分指引交付、程序执行、实际采用和任务结果。Core 当前不执行 Procedure，执行与采用无
结构化事实来源；结果与验证显示来源、有效性、哈希绑定等已有字段，不声称独立核验。失败事件仅为
活动，不进入 Evidence 白名单或待评估证据。Schema 仍为 v6，无新表或迁移；四个公共 MCP 工具不变。
失败记录落盘失败、旧版遗漏、未关联检索命中/任务、实际执行与采用等缺口见 [GUI.md](GUI.md)。

## CLI 使用

安装当前工作树后，以下命令也可写为 `python -m toolseed ...`：

```bash
toolseed status --data-dir /abs/data --text
toolseed capabilities list --query timeout --limit 30 --offset 0 --data-dir /abs/data
toolseed capabilities show cap_xxx --data-dir /abs/data --text
toolseed activity --type tool_call_failed --capability cap_xxx --data-dir /abs/data --text
toolseed evidence --type version_verification --data-dir /abs/data --text
toolseed ui --data-dir /abs/data --port 8765
```

默认 JSON，符合既有 CLI 输出约定；`--json` 显式选择 JSON，优先于 `--text`。
通用参数可放在子命令前后。`list/activity/evidence` 支持 limit 1–100 与 offset，空结果明确提示。
管理读取失败退出 2，JSON 含错误码；缺库不创建、旧 Schema 不迁移、损坏库不修复。
`capabilities list --help` 等提供子命令帮助，既有 `search/save/run/stats <JSON>` 用法保持。

## DSH 安装与实现

已核实本机 `F:\DeepSeek Harness\DeepSeek Harness.exe` 的实际版本为 **0.2.1-rc.2**；
安装目录的 `version` 文件记录的是 Electron 版本，不能作为 DSH 版本。
公开 SDK 依据来自该版本随包的模块 README、包导出和公共接口实现：

- `dsh-client-ui-settings` / `dsh-client-ui-settings-general`：公开 `settings.section` 插槽。
- `dsh-client-ui-theme`：当前主题令牌与字体变量，由宿主布局应用到同一文档；
  `dsh-client-ui-primitives`：官方 Web 前端基线中的原生控件导出。
- `dsh-client-modules`：`dsh.client` 声明、React 基线模块、lazy-CJS 客户端加载格式。
- `dsh-client-connection`：公开 `connection.rpc.call`；`dsh-connection`：`connection.fetch.register`，
  精确路径 Fetch 分发前检查 owner 身份，统一承载 Web HTTP 与 Desktop IPC。
- `dsh-app-boot` / `dsh-plugin-manager`：本地 bundle、profile patch 与官方插件安装命令。

当前官网入口：[插件开发](https://deepseek-harness.github.io/deepseek-harness/en/develop/basic/)、
[客户端模块](https://deepseek-harness.github.io/deepseek-harness/en/reference/subsystems/client-modules)。
官网会更新，因此版本声明仅覆盖本机已核验的 0.2.1-rc.2；插件声明精确 DSH engine。

安装命令及参数见 [integrations/dsh/README.md](../integrations/dsh/README.md)。
本机已通过官方 `dsh plugin --profile desktop add <本地目录>` 安装并启用 `dsh-toolseed`。
安装器备份并只维护 desktop `cordis.patch.yml` 内的标记配置块，保留其余条目及原 MCP 配置。
依赖和 lockfile 由官方 pnpm 操作管理；无需修改宿主源码或安装目录。
更新后重启 DSH，从 **设置 → ToolSeed** 打开；主界面左侧不再有一级 ToolSeed 项。
不需手工启动 Python 服务或浏览器。

原生客户端在宿主同一文档内使用 `Button`、`Input`、`SegmentedTabs`、`Modal`，
不再嵌入 iframe。构建器直接复用 `toolseed/ui_assets/app.js` 的转义展示函数；范围限定的布局 CSS
只消费宿主 `--dsw-*`、正文/代码字号和字体变量，内容背景透明，不带独立 Web GUI 的配色或布局外壳。
无需复制主题或操作宿主内部元素，宿主应用外观后由 CSS 级联立即同步。详情使用宿主原生 Modal。
取消 iframe 后，能力数据仍由既有 HTML 转义函数处理，不将数据库文本解释为脚本、样式或宿主组件。
宿主只提供固定只读查询白名单；参数不能指定命令、Python 或目录，不用 shell，不回传 stderr。
Python 子进程隐藏窗口、10 秒超时、2 MiB 输出上限、最多 4 个并发；卸载/取消会中止查询。
桌面走 IPC，不注册 HTTP 服务；独立 GUI 的 Host/Origin/Fetch-Site、只读方法与 frame 禁令未放宽。

DSH 官方安装输出对本地 link 依赖给出 peer resolution 提醒；本机实际启动后 Python 查询、
主面板和侧栏均成功加载。其他环境如遇解析失败，按宿主官方包管理方式使用 `file:` 本地依赖，
不要向宿主源码复制模块。更新共享 GUI 后重新构建并重装插件；保留源码路径直至解除本地链接。

## 其他宿主的核实边界

| 宿主 | 本机核实 | 本轮支持声明 |
|---|---|---|
| DSH Desktop | 0.2.1-rc.2，公开设置插槽与 Connection；设置/外观修复使用同版隔离 Web 客户端验证 | 原生 ToolSeed 设置页 + MCP + CLI |
| Codex CLI | 0.163.0-alpha.11 | MCP + 管理 CLI；未实现原生自定义面板 |
| Claude Code | 2.1.150 | MCP + 管理 CLI；未实现原生自定义面板 |

核对 [OpenAI MCP/UI quickstart](https://developers.openai.com/plugins/build/app-quickstart)
及 [troubleshooting](https://developers.openai.com/plugins/deploy/troubleshooting)：MCP 工具可供 Codex
使用，而其中的组件/widget UI 说明针对 ChatGPT，不能作为 Codex 桌面/CLI 通用面板契约。
本轮未核实到适用于 ToolSeed 的 Codex 自定义管理面板公开接口；不把此结论外推为所有版本永不支持。

[Claude Code 官方插件契约](https://code.claude.com/docs/en/plugins-reference)定义 commands、
hooks、MCP、LSP 等组件；本轮未核实到 CLI 的通用管理 WebView 契约。
不借用 Claude Desktop 的 UI 能力，也未伪造宿主页面。后续若官方提供适用的 UI 扩展机制，需单独适配。

## 首次管理入口集成验证（历史记录）

仅执行相关定向检查，不跑完整 A/B 或全量质量门禁：

- CLI、GUI、失败活动：45 项 Python 测试通过（含新增 9 项管理测试）。
- 证据、有效性、维护生命周期/基线、版本与晋升：59 项 Python 测试通过。
- 固定 MCP 四工具枚举和结构化 stats：2 项通过（沙箱 DLL 加载失败后在沙箱外重跑）。
- README / Alpha 文档契约：4 项通过；合计 110 项 Python 定向检查。新增 CLI 三文件的 Ruff
  检查及 `git diff --check` 通过。
- DSH Node：首次集成时 6 项通过，覆盖参数/命令白名单、安全错误、并发、RPC envelope、真实临时 Core
  写入可见、slot 注册和 iframe 限制。新行为测试全部使用临时数据库。
- DSH 首次实际桌面检查（旧入口）：官方安装并启用，点击侧栏；Overview / Capabilities / Activity / Evidence
  读取已有真实库，能力搜索与详情成功，检查中无 JavaScript 异常。未发送 Agent 任务或执行能力。

本地 wheel 构建通过，核对含管理模块、Inspector、共享 GUI 资源和三个启动入口。setuptools
仍提示静态资源目录的 namespace 发现配置警告，资源已实查包含，未为此重构包结构。
Python 套件当前收录 289 项，并非本轮全量运行。
原生 UI 未覆盖其他 DSH 版本、其他操作系统或打包分发。本地试用条件已具备，等待人工架构审查。

本机既有 `.venv311` 的已安装发行元数据仍为 0.4.0（editable 源码指向本工作树）；
`status` 读取安装元数据，不从当前目录猜测版本。运行中的 MCP 锁定启动文件，因此未强行覆盖
该环境；更新元数据需完全退出 DSH 后重新安装工作树。已确认原启动器、editable 指针与元数据仍在。
项目 `.venv` 与当前 wheel 的版本为 0.4.1，使用
`./.venv/Scripts/python.exe -X utf8 -m toolseed status --data-dir F:/ToolSeed/.toolseed --text`
已实际读库验证。此差异不改变各入口使用的同一数据库或 Core 语义。

## 本轮修改清单

| 文件 | 作用 |
|---|---|
| `toolseed/cli.py` | 在既有入口增加管理子命令分派，保留原操作 |
| `toolseed/management.py` | 共享 Inspector 的只读 CLI、JSON/文本、帮助和错误 |
| `toolseed/ui_assets/app.js`、`index.html` | 共享转义展示函数、能力详情与只读传输适配；当前两页改版见后文 |
| `integrations/dsh/package.json`、`cordis.patch.yml` | 版本限定的官方本地插件 bundle 与客户端声明 |
| `integrations/dsh/index.js`、`backend.js` | 公开 Connection 路由和固定只读 Python 查询白名单 |
| `integrations/dsh/src/client.cjs`、`src/native.css`、`build.mjs`、`lib/client.js` | 原生设置页与控件、宿主令牌布局、共享展示函数构建器及可安装产物 |
| `integrations/dsh/install.ps1`、`README.md` | 官方安装、数据目录配置、备份和说明 |
| `tests/test_management.py`、`integrations/dsh/test/backend.test.mjs` | 管理 CLI 与宿主适配定向回归 |
| `README.md`、`docs/ALPHA-STATUS.md`、本文件 | 各入口用法、事实来源、支持范围和验证 |

此前 GUI 和失败事件架构核查的未提交文件保持原成果，清单见 [GUI.md](GUI.md)。
本轮未修改 Core、Schema、MCP 服务或历史实验文件。

## 设置入口与外观修复验证（2026-10-22，简化前）

仅修复入口和外观。参考本机普通插件的 `settings.section` 注册，以及随包的主题和原生控件接口，
移除 `main` / `sidebar.panellist` 注册和 iframe 消息桥。未修改宿主源码、主题状态或全局样式。
独立 Web GUI 的 HTML、CSS、HTTP 安全边界不变；共享 JS 仅提取原详情展示函数，并让空搜索提示接收
显式查询参数，原有独立 GUI 调用方式保持有效。只读后端、Core、Schema v6 和四工具协议未改动。

- 8 项 Node 定向测试通过：包含仅设置入口、原生控件、无独立配色、共享展示转义和空搜索提示回归。
- 26 项 Python GUI/管理定向测试及 4 项文档契约测试通过，合计 30 项。
- 使用官方 `dsh web` 和本机 0.2.1-rc.2 客户端、组件，在项目内独立 DSH_HOME/profile 与临时
  Core 数据库验证；没有重启用户 Desktop、修改其全局外观或读取其数据库进行测试。
- 浏览器验证设置侧栏入口、无一级 ToolSeed 项/iframe，四页、30 条分页、能力搜索/详情、失败类型筛选、
  证据未知项、Overview 活动链接及 Core 新写入后的自动刷新。
- 第二个宿主页面通过“通用设置”切换浅色/深色、跟随系统及正文/代码字体和字号；已打开的 ToolSeed
  页与详情同步，原挂载节点不变，颜色与原生控件随宿主变化。内容背景透明，沿用设置容器背景。
  所有主题变更仅发生在临时测试 profile；检查中无 JavaScript 异常。

实际修改：`integrations/dsh/src/client.cjs`、新增 `src/native.css`、`build.mjs`、`lib/client.js`、
`package.json`、`install.ps1` 的入口提示、`test/backend.test.mjs`、`toolseed/ui_assets/app.js`，
以及插件 README、项目 README、Alpha 文档和本说明。用户现有本地插件链接继续有效，重启 DSH 加载新客户端。
本次未提交、推送或发布，等待人工审查。

## 两页信息架构简化（2026-10-22，当前）

原生设置页和独立 GUI 共用“已入库能力”与“活动”卡片；证据、版本、历史和原始字段放入详情。
内部名称优先取已有描述生成可读标题，测试能力明确标记。已入库、指引已交付、实际采用与任务确认
分开呈现；交付数从 `procedure_delivered` 查询取值，不当作采用或成功次数。
Core、Inspector、管理 CLI、只读后端、HTTP 服务、Schema v6 和四工具协议均未修改。

本轮 11 项 Node、30 项 Python 定向检查通过；使用同版官方 DSH 隔离 Web 客户端读取现有库，
验证两页、搜索、详情、高级信息、窄屏及宿主主题/字体自动同步。实际截图、文件清单和限制见
[PANEL-SIMPLIFICATION.md](PANEL-SIMPLIFICATION.md)。用户当前 Desktop 未重启，现有本地链接在重启后加载更新。
