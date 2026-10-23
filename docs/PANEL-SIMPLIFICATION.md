# ToolSeed 面板简化交付记录

2026-10-22，基于当前未提交的 GUI 和 DSH 设置页增量修改。包版本仍为 0.4.1，
Schema 仍为 v6；未提交、推送、打 Tag 或发布。

## 当前交互

DSH 从 **设置 → ToolSeed** 进入，只有“已入库能力”和“活动”两页，不注册主界面一级导航。
顶部保留已入库数量和实际指引交付数量。独立 Web GUI 使用相同卡片、详情及只读查询编排。

能力卡片只呈现可读名称、简短说明、可用状态和适用场景。已有内部名称包含下划线等技术形式时，
从数据库中已有描述取首句/短句作标题，不调用模型、不改数据库名称。接入自检、smoke、fixture、
test 等明确元数据标记显示为“测试能力”，不能作为真实业务成果展示。

能力详情将验证、方法版本、近期历史和高级信息分层展开；活动卡片用简短动作、时间和已有原因
说明记录，点击查看关联能力、证据来源及原始字段。内部 ID 保留在关联数据和折叠的“高级信息”，
默认不进入可见标题。长文本可换行，状态标签保持完整，窄屏沿用记录卡片而非密集表格。

DSH 继续使用已核实的 0.2.1-rc.2 公共 `settings.section`、`Button`、`Input`、`SegmentedTabs`、
`Modal`。共享 CSS 只定义布局，原生层将颜色、字体、字号映射到宿主实际 `--dsw-*` / `--dsh-*`
令牌；背景透明，无主题状态或切换按钮。独立网页的外壳和配色不进入 DSH 构建产物。

## 数据和证据边界

- 能力、版本、事件、验证、结果与有效性全部来自既有 Inspector。浏览和搜索不调用公共 MCP 工具。
- 搜索只读分页取得现有能力元数据，在客户端匹配名称、描述、场景和标签；既有 Core 查询未改动。
- 能力详情的交付数来自 `procedure_delivered` 证据总量，不使用一般 Invocation 数量代替交付。
- “已入库”“可提供指引”“有验证记录”分别表达保存、生命周期可用与已有验证，不表示任务成功。
- “Agent 实际采用”保持“尚未记录”；没有独立确认时，“任务结果确认”保持“尚未确认”。
  已有任务结果信号仍展示其原始结果和来源，并说明尚未独立核验。
- 验证摘要检查版本 ID 和内容哈希，显示通过/未通过及当前有效性；失效或被替代记录不会冒充当前验证。
- 调用失败只展示工具调用原因，不解释成原任务失败。历史未记录的活动不补造。
- 原 evidence 查询和 CLI 仍可用，证据数据、关联关系与安全/生命周期门禁未删除或改变。

本轮对 Core、Inspector、MCP 服务、管理 CLI、HTTP 服务和 DSH 只读后端均无修改；
开发前后对这些文件的 SHA-256 比对一致。没有迁移、新服务、模型调用或新公共工具。

## 实际修改文件

| 文件 | 作用 |
| --- | --- |
| `toolseed/ui_assets/app.js` | 共享两页卡片、可读名称、测试标记、详情、证据分层、搜索与只读查询编排；独立网页交互 |
| `toolseed/ui_assets/app.css` | 共享响应式卡片/详情布局与独立网页外壳；共享区不带固定配色 |
| `toolseed/ui_assets/index.html` | 独立网页的两页导航、简短统计、搜索及详情容器 |
| `integrations/dsh/src/client.cjs` | 原生两页、宿主控件、能力/活动详情及关联历史导航 |
| `integrations/dsh/src/native.css` | 宿主实际主题令牌映射、设置页与原生弹窗布局 |
| `integrations/dsh/build.mjs` | 从同一 GUI 提取展示、查询和共享布局，生成 DSH 客户端 |
| `integrations/dsh/lib/client.js` | 已重建的本地插件客户端产物 |
| `integrations/dsh/test/backend.test.mjs` | 更新两页契约，补充名称/测试标记、跨分页描述搜索及证据真实性回归 |
| `README.md`、`integrations/dsh/README.md` | 当前入口、两页说明、构建和使用方式 |
| `docs/GUI.md`、`docs/AGENT-INTERFACES.md`、`docs/ALPHA-STATUS.md` | 同步当前状态，保留既有历史验证记录 |
| 本文件及 `docs/screenshots/toolseed-*.png` | 本轮交付说明与实际浏览器截图 |

## 定向验证

```powershell
node integrations/dsh/build.mjs
node --test integrations/dsh/test/backend.test.mjs
./.venv/Scripts/python.exe -X utf8 -m unittest tests.test_ui tests.test_management tests.test_skill_contract.UsageDocumentTest -q
```

11 项 Node 测试、30 项 Python 定向测试通过。覆盖设置插槽、原生控件、仅宿主令牌、转义、
名称/测试标记、101 条元数据的跨页搜索、精确交付计数、验证状态、失败语义，以及现有只读
HTTP、空/缺失/异常数据库、目录隔离和生命周期门禁。构建、JavaScript 语法检查与
`git diff --check` 通过。没有运行全量套件、A/B 实验或全量质量门禁。

使用本机官方 DSH **0.2.1-rc.2** 的 `dsh web`、同版客户端和原生组件，在独立
DSH_HOME/profile 中检查实际设置页，未重启用户当前 Desktop，未改用户全局外观。
截图通过原生面板只读访问现有 `F:/ToolSeed/.toolseed`：1 项真实存在的接入自检能力、
2 条指引交付记录；没有为截图伪造业务成果，没有修改用户数据。

浏览器检查通过：两个页面、设置侧栏且无一级入口、可读名称与测试标记、描述/场景搜索、
能力和活动详情、折叠高级字段、实际指针点击可达性、窄屏无横向溢出。第二个宿主页面切换
浅色/深色/跟随系统、正文字体/代码字体和字号后，已挂载面板立即继承且挂载节点不变。
同次干净浏览器检查无 JavaScript 异常。独立网页另检查了 390px 布局、搜索、详情与活动。

以下为实际 DSH 设置窗口或详情窗口的裁取截图；颜色由宿主设置产生。

| 截图 | 内容 |
| --- | --- |
| [已入库能力](screenshots/toolseed-capabilities.png) | 浅色，现有自检能力 |
| [活动](screenshots/toolseed-activity.png) | 浅色，实际检索及交付历史 |
| [能力详情](screenshots/toolseed-capability-detail.png) | 交付记录、采用/任务确认缺口、折叠详情 |
| [活动详情](screenshots/toolseed-activity-detail.png) | 实际交付事件与证据分层 |
| [深色能力页](screenshots/toolseed-capabilities-dark.png) | 宿主深色主题 |
| [深色活动页](screenshots/toolseed-activity-dark.png) | 同一挂载面板随宿主切换 |
| [DSH 窄屏](screenshots/toolseed-narrow.png) | 1000×800 宿主视口中的设置页 |
| [独立网页窄屏](screenshots/toolseed-mobile-web.png) | 390px 视口中的同源真实活动 |

## 本地试用与剩余限制

现有本地插件链接仍有效，重建后重启 DSH，从 **设置 → ToolSeed** 打开；不需要 Python 常驻服务。
独立网页可选运行：

```powershell
./.venv/Scripts/python.exe -X utf8 -m toolseed ui --data-dir F:/ToolSeed/.toolseed
```

只监听 `127.0.0.1`。所有入口继续使用同一已配置目录；不新建宿主专属能力库。

可读标题和测试标记依据已有元数据，描述缺失或含糊时不会凭空补写业务含义。客户端搜索须先分页
加载能力元数据，大库首次加载可能较慢；并发变化时提示数据可能尚未完整。近期历史只预览 30 条，
可跳转关联活动分页；完整原始证据继续通过既有查询/CLI 获取。当前证据源仍无法证明 Agent 实际采用
或无外部信号的任务结果，界面如实保留未知。

实际宿主验证覆盖同版本官方隔离 Web 运行环境，用户当前 Desktop 的重启后人工观感检查尚待审查；
其他 DSH 版本、系统与打包分发未扩展验证。本轮完成后停止，等待人工架构审查。
