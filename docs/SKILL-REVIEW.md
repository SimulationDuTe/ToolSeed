# ToolSeed Skill 审查与优化（2026-10-22�?
本轮只修�?`toolseed/skill/SKILL.md` 和本报告。保留开始时已有�?GUI、CLI、Core 等未提交成果�?未修�?Core、Schema v6、索引、四个公共工具、打包配置或宿主配置；未提交、推送、打 Tag 或发布�?
## 修改前记录与设计依据

修改前已保存原文、字节数、章节和哈希于本地忽略目�?`.test-data/skill-audit/`�?以下�?UTF-8 文件原始字节计量，行数使�?`splitlines()`，不计末尾空行分隔产生的额外元素�?
| 项目 | 修改�?| 修改�?|
| --- | --- | --- |
| 字节�?| 5,323 B | 7,960 B（增�?2,637 B，约 49.5%�?|
| 行数 | 117 | 146 |
| 一级业务章节（`##`�?| 7 | 6 |
| 二级小节（`###`�?| 2 | 2 |
| 发现元数�?| �?| `name: toolseed` 与按触发条件描述�?`description` |
| SHA-256 | `08450cd3038fd0d8a3d288ee70a7b42ea24a7874beb6aae0cdd8eb0f1e9bda81` | `c916284513cfd663e302cc444f955379c81456928e65d076bc1f401f91187f0b` |

原结构依次为 Decide first、Cost tiers、Search、Run、Save、Report accurately、Hard constraints�?Save 内包含提交前上限表和拒绝处置。原主要规则为：先�?inline / temporary / reuse / propose�?L0 跳过搜索和提炼、L1 一次短搜索、L2 设计后保存；写新能力前搜索且上下文不变时不重复搜索；
读适用条件；交付不代表执行；只保存有复用价值的方法；修订为候选、拒绝时局部纠正；准确报告并遵守安全约束�?
已完整阅�?Skill，并核对�?
- `docs/DESIGN.md` §4.3�?.7 的按需检索、任务结束评估、成本分层和领域无关原则，以�?P0 范围�?- `toolseed/core/manifest.py` 的完整候选校验、归一化、大小上限与静态内容检查�?- `toolseed/core/api.py` 的检索、保存、交付、统计、修�?晋升与结果信号；`search.py` 的实际返回卡片�?- `adapters/local.py`、`mcp_server.py` 的四工具、参数、宿主能力声明和实际注册方式�?- `pyproject.toml`、`scripts/package_smoke.py`、`scripts/verify_release.py`、质量门禁与相关测试�?- 现有发布、宿主接入、产品化审查报告及本机已有安装；没有读取真实用户数据库进行测试�?
## 发现、依据和修改

| 实际问题 | 依据与影响范�?| 修改位置与理�?|
| --- | --- | --- |
| inline 的“open-ended judgement”过宽；L0 无重新评估条�?| Procedure 本身就是判断型方法；�?§1�? 可能把首次但高成�?可复用的问题固定为一次性。这里只能判断文本存在误导风险，不能证明某次 Agent 因此跳过搜索 | �?§1 合并模式与成本表，只让简单、低成本且无复用信号的任务直�?L0；阻塞重复或价值出现时重新分层 |
| 搜索主要绑定“准备写新能力”，缺少主动复用的明确顺�?| �?§3 只明确要求写新能力前搜索；有宿主 Skill 或临时处理已成功时，没有明确如何继续判断 | �?§1�? 以反复阻塞、高成本诊断、重复操作和复用价值触�?L1/L2；实际加载宿�?Skill 后检索，并保留同任务同上下文搜索去重 |
| 缺少实际加载宿主 Skill 的要求；工具注册容易被误认为加载指导 | 旧文未提宿主 Skill；当�?MCP 服务只注册四工具，没有把本文件注册为自动注入的上下文；LocalAdapter 声明不支持任务结束钩�?| �?§2 说明按宿主机制实际加载、二者互补，MCP 注册本身不加�?Skill。新增标准发现元数据，但不声称它会安装或自动注入 |
| 适用性检查不完整，且所需数据不一定在卡片�?| 旧文只列 when_to_use / not_for / kind；实�?Search 卡片没有完整 applicability 或验证记录，关键词和 ready 不构成环境、权限或验证证明 | �?§2 要求核对环境、权限、工具、限制及可得验证；缺失数据不得编造，必要前提应从已授权来源核实，不引入第五工�?|
| 没有显式“解决后验证并决定保存”的检查点 | �?L2 直接从设计到保存；Save 只说可复用、可描述，缺少实测和保存结果确认 | �?§3�? 把应用、验证、范围限制与按需保存连接起来；已有覆盖避免近似副本，未验证方法暂缓保存，不强迫普通任务积�?|
| 契约说明缺项及局部不准确 | 缺少必需整数 protocol_version=1、候选顶层结构与 applicability �?类型；run 实现始终返回 unknown；相同修订可返回已有版本；并非所有保存错误都指明某字段长�?| �?§3�? 补齐已有实际契约，纠�?unknown 表述、修订重复例外及错误分类，不改变实现 |
| 重复命中混在“保存被拒”步骤中 | duplicate 是成功响应上的信息，不是错误；原流程没有明确核对 ok / accepted / IDs / version_status | �?§4 将纠错与结果确认分开；只重交一次纠正后的候选，保留拒绝和持久化失败的诚实处�?|
| 报告链条缺少“已保存”，且缺少未来复用动�?| 原报告链条从 found 开始；没有说明保存后下一次任务仍需重新检索、判断、采�?| �?§5 区分找到、保存、交付、实际采用、结果确认；重搜命中不算采用，统计交付数不算任务成功 |

规则处理清单�?
- **合并�?* 原模式表与成本分层合�?§1；重复的七字段说明�?2 KiB 描述合入唯一契约/上限区；
  多处“文本不能授权”的重复合到安全边界。没有增加第二套独立流程�?- **调整�?* 搜索从“写新方法前”移�?L1/L2 的前置发现；Save 分成验证后选择、契约自检、纠错和确认�?  duplicate 从拒绝处理中移出；报告包含保存及未来实际采用�?- **保留�?* L0/L1/L2、四种处理模式、一次短搜索及同上下文去重、正常解决空匹配、P0 不执行�?  所有字段上限、局部修正且不重发原候选、POLICY_BLOCKED 不得改写绕过、版本不可覆盖与单独验证晋升�?  不存敏感信息、不�?ready/交付/unknown 当作成功、不过度积累和不为决策新增模型回合�?- **删除/替换�?* 删除无条件“L0 跳过搜索”的固定化表达、把开放判断直接归为一次性的宽泛分类�?  “交付结果可能因已有外部信号而改�?unknown”的错误暗示，以及重复表述。没有删除有效门禁或字段限制�?- **补齐�?* 通用触发与重新判断、真实加载宿�?Skill、可观测验证、确认持久化、未来复用，及原来漏写的实际契约�?
文件增长用于补齐这些缺口，并没有以压缩字数为目标删减有效约束。未加入 Windows ACL、Chrome 或其他单场景策略�?未新增辅助引用树、模型调用、自动提炼系统或能力数量目标�?
## Windows ACL 案例：证据与未知

用户描述的现象是：多次阻塞后仍反复使用临时权限处理，直到提醒才完成检索、修复、验证、保存和再次检索�?本轮没有独立重演该次经历，也没有取得这段完整工具调用时间线、当时实际加载的 Skill 内容/版本�?权限审批记录、实际采用动作及产物验证链，不能认定单一根因�?
仓库中可核实的相关材料：

- [宿主接入报告 §3](../benchmarks/reviews/alpha-host-integration-2026-10-21/REPORT.md)记录 profile 目录
  ACL 只读、写入及权限模式重试失败，且按当时约束没有改 ACL；这证明该次接入有权限阻塞，不证明它就是用户所指完整案例�?- [发布准备报告 §2](../benchmarks/reviews/release-0.4.1-2026-10-21/REPORT.md)记载构建临时目录 ACL 问题曾采�?  临时 sitecustomize 处理；它没有给出完整 Agent 的检�?加载/采用决策日志�?
因此，早�?L0 分类固化、搜索触发过窄、宿�?Skill 未实际加载、Skill 未进入上下文、工�?安装版本漂移�?临时处理造成任务已完成的判断，都只能作为待验假设。文本确有上述缺口，不代表已经证明这些缺口导致了那次行为�?修复范围是通用决策流程，不能用指导文本替代授权；安全策略与沙箱限制始终优先�?
本轮构建检查也出现实际环境阻塞，已保留失败记录：标�?build 前端收尾时失败；沙箱外重试明确报
`os.remove(result_path)` �?WinError 5。没有修�?ACL、放宽宿主策略或�?Python 打补丁�?改用同一 setuptools �?`bdist_wheel` 命令输出到新的审查目录后成功，这是本地工件检查的替代路径�?不能据此宣称标准构建前端问题已经解决。本会话工具发现结果中没�?ToolSeed MCP，未伪造检�?保存事件�?
## 源码、打包与安装一致�?
`pyproject.toml` 仍通过 `toolseed = ["skill/*.md", ...]` 打包本文件，配置没有改动�?在忽略目录复制当前包源码与实际配置构�?wheel，没有写入历�?dist、Tag �?Release�?
| 对象 | 实查结果 |
| --- | --- |
| 当前源码 | 7,960 B；SHA-256 为上�?after �?|
| 本轮 wheel�?.4.1�?| `toolseed/skill/SKILL.md` 与源码逐字节相同；ZIP CRC 全部有效；Twine 检查通过 |
| 新临时非 editable 安装 | �?wheel 离线 `--no-deps` 安装；在中�?cwd 导入，路径确�?`.test-data/skill-audit/installed/Lib/site-packages/toolseed`；版�?0.4.1，Skill 与源码逐字节相�?|
| 既有 `.venv` �?`.venv311` | 均为 editable，实际导入当前源码，修改�?Skill 相同；发行元数据仍显�?0.4.0。这是本轮实查结果，未为修文档覆盖运行环�?|
| 既有 `.test-data/release-0.4.1/clean-venv` | �?editable �?0.4.1，旧 Skill �?5,440 B（CRLF）；换行归一后与修改前源码相同，与新 Skill 不同，未更新该历史安�?|

发现元数据通过标准 Skill 校验，但包内携带文件不等于注册宿�?Skill，更不证�?Agent 已读到它�?既有�?editable 用户安装、宿主复制件和已加载的会话不会因修改工作树自动刷新；本轮没有安装宿主副本或改接入配置�?本机两个常见原生路径 `~/.codex/skills/toolseed/SKILL.md`、`~/.claude/skills/toolseed/SKILL.md` 未发现文件，
这不代表已检查全部宿主路径。实�?DSH/Agent 会话是否加载�?Skill 仍待运行验收�?
## 自动化检查与实际命令

均在 `F:/ToolSeed` 执行，另注明的中�?cwd �?`.test-data/skill-audit`�?临时审查脚本和构�?安装产物留在同名忽略目录，不进入产品包�?
| 命令 | 结果与退出码 |
| --- | --- |
| `.venv/Scripts/python.exe -X utf8 -m unittest tests.test_skill_contract tests.test_contract tests.test_delivery tests.test_search tests.test_versions -q` | 62 通过�? 失败�? 跳过；exit 0 |
| `.venv/Scripts/python.exe -X utf8 -m unittest tests.test_mcp_server.MCPServerTest.test_server_exposes_exactly_four_tools tests.test_mcp_server.MCPServerTest.test_tool_call_returns_structured_stats -q` | 2 通过�? 失败�? 跳过；exit 0，真实官�?SDK 进程内枚�?调用 |
| `F:/python/python.exe -X utf8 C:/Users/xiazi/.codex/skills/.system/skill-creator/scripts/quick_validate.py F:/ToolSeed/toolseed/skill` | 1 项格式检查通过，exit 0；只验证结构、元数据，不验证 Agent 行为 |
| `.venv/Scripts/python.exe -X utf8 -m compileall -q toolseed tests/test_skill_contract.py` | 通过，exit 0 |
| `.venv/Scripts/python.exe -X utf8 -m build --wheel --no-isolation .test-data-skill-audit/source --outdir .test-data-skill-audit/dist` | 沙箱内、沙箱外各一次，�?exit 1；第二次�?WinError 5 的明�?traceback，未记作通过 |
| `.venv/Scripts/python.exe -X utf8 .test-data-skill-audit/build_direct.py` | 在同一 staged source 调用 `setuptools.setup(script_args=['bdist_wheel', '--dist-dir', ...])`，exit 0；保留既有静态资�?namespace 配置及命令弃用提醒，未为此改打包配置 |
| `F:/python/python.exe -X utf8 -m venv --without-pip F:/ToolSeed/.test-data-skill-audit/installed` | 新隔离环境创建成功，exit 0 |
| `F:/python/python.exe -X utf8 -m pip --python F:/ToolSeed/.test-data-skill-audit/installed/Scripts/python.exe install --no-deps --no-index --no-cache-dir --disable-pip-version-check F:/ToolSeed/.test-data-skill-audit/direct-dist/toolseed-0.4.1-py3-none-any.whl` | 首次（未�?no-cache-dir）在沙箱内因用户注册表查询失败，exit 1；沙箱外离线安装成功，exit 0 |
| `.venv/Scripts/python.exe -X utf8 -m ruff check --no-cache tests/test_skill_contract.py` | 首次沙箱内未�?no-cache，exit 1 且无诊断，不认定代码错误；沙箱外重跑通过，exit 0 |
| `.venv/Scripts/python.exe -X utf8 -m mypy --cache-dir .test-data-skill-audit/mypy-cache toolseed` | 首次沙箱内未指定缓存目录，因 `_ctypes` DLL 加载失败，exit 1；沙箱外 18 个源文件通过，exit 0 |
| `.venv/Scripts/python.exe -X utf8 -m twine check .test-data-skill-audit/direct-dist/toolseed-0.4.1-py3-none-any.whl` | 首次沙箱内同�?DLL 加载失败，exit 1；沙箱外 1 �?wheel 检查通过，exit 0 |
| `F:/ToolSeed/.test-data-skill-audit/installed/Scripts/python.exe -X utf8 F:/ToolSeed/.test-data-skill-audit/verify.py`（中�?cwd�?| 最�?exit 0：源�?wheel/安装字节相同、CRC/版本/导入路径正确�?5 个受保护文件哈希未变。脚本首次假�?METADATA �?LF �?exit 1，改用标准邮件元数据解析后通过；未改产品修正该测试辅助脚本错误 |
| `git diff --check` | 通过，exit 0；仅�?Git 换行提示 |

最终定向单元测试合�?**64 通过�? 失败�? 跳过**。上表中的构建和环境阻塞是实际失败命令，
没有计入“测试通过”或隐藏为跳过。没有新增与实现镜像的流程措辞测试，已有字段上限测试仍与 Core 权威常量比较�?本轮测试文件没有修改；现�?Python 套件收录数未变化�?
**未验证：** 完整 `scripts/quality_gate.py`（会运行全套）、全量单元测试、sdist、CI�?新安装环境的完整依赖/stdio package_smoke、真实宿主自动发�?加载�?Agent 自主行为�?没有重新运行 A/B、调用模型或新增付费实验。自动化通过只说明格式、契约和受测实现成立，不能证�?Agent 会执行该流程�?
## 安全与契约复�?
人工逐条对照保留的限制；使用改动前快照比�?`toolseed` 中除 Skill 外的文件、pyproject �?DSH 只读后端/客户端，
�?25 个受保护文件 SHA-256 均未变化。原�?GUI、CLI、Core 的未提交差异并非本轮新增�?64 项定向测试覆盖固定工具面、候选字�?边界、凭据和策略拒绝、检索状�?适用性筛选、交付非执行非成功�?修订和验证门禁。Skill 新增宿主政策/沙箱优先，并将不持久化敏感数据明确覆�?manifest、intent、context�?没有授权绕过、自动晋升、自动执行或写入不存在的证据字段�?
## 最小后续运行验收（本轮未执行）

在宿主支持的实际 Skill 加载机制、同一�?Skill 哈希和三个隔离临时能力库下，保留最小可审查的工具结果�?加载动作和任务验证产物；不要持久化完整提示词、秘密或隐藏推理。固定简单的任务成本边界，不开展完�?A/B�?
| 场景 | 最小准备与任务 | 验收证据 |
| --- | --- | --- |
| 已有能力适用 | 临时库预置一项带明确范围、前提、验证参考的安全 Procedure；给一个范围内变体任务，并提供适用宿主 Skill | 观察实际加载动作 �?search �?判断 �?run；再由命�?改动和独立结果检查证明实际采用。保存数不应无故增长；run 返回本身只证明交�?|
| 无匹配但值得积累 | 空库，提供具有明确未来变体、需要一定诊断和验证的方法任�?| 观察 search 为空后仍解决 �?可观测验�?�?合规 save/accepted/IDs/status；第二个独立任务重新 search/判断/run，再以动作与产物证明实际采用，不把再次命中当作复�?|
| 不值得积累 | 简单、低成本、无重复阻塞或后续复用价值的一次性任�?| 正常完成且没有无理由搜索/保存或深度提炼；如果过程中新增真正触发信号，应改�?L1/L2 判断，不能把固定“零调用”变成不许重新评�?|

每个场景分别记录：Skill 是否实际加载、能力是否检索到、是否已存储、是否交付、是否实际采用、任务结果是否有独立检查�?工具不可用时标记“运行条件不满足”，不当作空库；阶段证据不足时保留未知，不用 Agent 总结替代动作/结果证据�?还应核对未匹配或权限不足时能正常拒用而继续安全解决；不能为验收扩大权限�?
本轮没有发现还需修改 Skill 的明确缺陷；真实行为与既有安装更新留作上述运行验收�?已完成文本审查、必要修改及定向自动化检查，停止等待人工架构审查�?