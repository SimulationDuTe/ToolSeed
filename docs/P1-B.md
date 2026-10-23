# P1-B：非脚本能力沉淀与独立任务复用验�?
2026-10-23，本地工作，未提交或发布。分�?develop，HEAD
`f63c007284b592bd4c07d0509f1c753d6c7b571f`，保留全部既有工作区成果�?
**本轮闭环未成立：真实 CLI �?Agent 客户端初始化时被环境访问拒绝阻塞，尚未进入首次任务�?没有发生本轮能力保存、检索、交付或实际采用，不能把校验器通过当作真实 Agent 通过�?*

## 现状核对

已阅�?DESIGN 的机会、成本、安全与表示形式、证据、Skill �?P1 章节，P0-SLIM、P1-A、完整源�?Skill，以及实�?Manifest、Search、Core、LocalAdapter、MCP、存储和任务结果实现�?
| 环节 | 现有实现及其边界 |
| --- | --- |
| 保存 | toolbox_save 接收 protocol_version=1、七字段 manifest �?content；唯一 kind �?procedure。支持诊断顺序、决策规则、操作步骤和检查清单，本来就不限于脚本。新版本不可变，结构门禁、去重及生命周期已存在�?|
| 检索与适用�?| 关键词检索和已有上下文硬筛选；Agent 仍须检查具体输入、条件、权限和证据。命�?ready 不证明适用或成功�?|
| 使用 | toolbox_run 交付完整文本，返�?agent_guided / guidance_delivered / task_outcome=unknown。实际步骤由 Agent 和宿主工具完成，不存�?Procedure 自动执行后端�?|
| 验证 | ready 是结�?内容门禁；独立结果验证要有外部产物和校验。既�?record_version_verification 面向 candidate，不能为了给�?ready 条目贴验证标记而越过门禁�?|
| 证据 | 真实保存、检索、交付有原始事件；record_task_outcome 是现有内部接口，要求真实 invocation 关联。没有通用公共“采用即成功”入口；独立采用判断及校验结果可保留在验收材料，不需要新表或第五工具�?|
| Skill / DSH | 当前 Skill 已要求验证后按需保存、以后重新检索判断采用。P1-A 提示/实际搜索初步通过是用户提供的后续进展；本轮未修改或重新验收其触发机制�?|

现有机制足以开展此闭环验收，没有发现必须修�?Core 的阻塞。必要缺口是当前版本、独立任务�?真实模型、外部结果验证及采用动作之间的实测证据链�?
历史九对试验没有保存/采用。此外仓库还有后续的
[八任务限范围报告](../benchmarks/results/agent-reuse-final-2026-10-21/REPORT.md)，记载一次保存�?三次交付与采用；该报告也承认采用含自报成分、测量不完整和协议偏差，且其供应 wheel �?0.4.0�?本轮没有重跑任一历史实验，也没有把历史报告替代当前版本验收�?
## 本轮最小任务与隔离

新增 [验收脚本](../benchmarks/p1b_acceptance.py)，只作验收接线，不属于产�?Core/Adapter�?
- 首次任务 A�? 个只读发布配置案例，含高优先级覆盖、空数组替换、字符串布尔值、过期运行快照和已确认状态�?- 后续任务 B�? 个不同输入，另含显式 null、不同来源层名和数组内容。期望检验的是可参数化的诊断方法，不是复制固定答案�?- 两任务目录、任务上下文独立，仅配置同一份隔�?ToolSeed 数据目录；不预置能力、不�?B 提供 A 的业务产物或能力 ID。仅两个顺序任务，无对照组�?- 任务提示只有 `Complete task.md in this workspace.`；业务任务没�?ToolSeed 名称或能力提示。源�?Skill 原样复制到每个任务的 `.agents/skills/toolseed/SKILL.md`�?- 每个任务配独立的确定性校验器，核对有效值、来源、类型、运行确认、分类和逐层值轨迹。模型自述或 completed 不参与通过判定。校验器�?Agent 可见，本轮不是盲测�?- 参考校验器只含规则，不包含另一个任务的数据或驱动器。输入和校验器有预先哈希；不允许修改它们。不同目录在同一父仓库下，依�?workspace-write 及明确的目录约束，不宣称是强制保密隔离�?- run B 必须先有 A 的独立校验通过、实际保存调用收据及数据库中已持久化能力。失败时拒绝进入 B，不补写候选�?- MCP 直接使用现有服务器、现有四工具和本轮隔离目录；没有 CLI Bridge、第五工具或新服务�?- Codex CLI 使用 workspace-write / approval=never；没有使�?danger-full-access 或跳过沙箱开关。设置只通过本次命令参数生效，未修改用户配置或复制凭据�?- 事件投影丢弃 reasoning 项，仅保留任务工具动作、结果、最终陈述和 CLI usage；本轮没有事件可供采用判断。没有给 ToolSeed 新建日志系统�?
选择 Codex 是为了利用现有已登录 CLI 做真实模型任务；即便成功，也仅代表该宿主，不能升格为
DSH Desktop 通过。本轮未能启动真实模型，Skill 复制成功也不代表 Agent 实际加载过它�?
## 实际执行及阻塞证�?
`codex login status` 在获准读取正常用户环境后返回 `Logged in using ChatGPT`�?CLI �?0.163.0-alpha.11，请求模�?gpt-6.1-sol / reasoning_effort=medium；实际解析模型未知�?
最初指定的仓库外可写根目录创建失败，普通和获准执行均返�?WinError 5。没有修�?ACL；改�?工作区中新建、已被原�?.gitignore 忽略的唯一目录，保留所有旧材料�?
| 实际尝试 | 隔离材料目录 | SUT CLI 退出码 | 保留事件 | 结果 |
| --- | --- | ---: | ---: | --- |
| 独立进程�?CLI | `.test-data/p1b-20261023-17dfc2a3` | 1 | 0 | 用户级状态数据库只读，客户端初始化拒绝访�?|
| 官方 sqlite_home 临时状态目�?| `.test-data/p1b-20261023-66fe9c40` | 1 | 0 | 临时状态数据库已创建，只读数据库警告消失，客户端初始化仍拒绝访�?|
| 正常 CLI 入口，保留临时状态配�?| `.test-data/p1b-20261023-07424594` | 1 | 0 | 客户端初始化仍拒绝访�?|

三次共同的实际错误：

```text
Error: failed to initialize in-process app-server client: 拒绝访问�?(os error 5)
```

原始 invocation.json、stderr.txt、summary.json、verdict.json 和空 events.jsonl 均保留在各目�?results/A 下；三个 ToolSeed library 目录均没有数据库。首次任务缺 diagnosis.json，外部验�?明确失败，不能据此归因于能力或模型。B 的准入检查返�?`A did not pass independent validation`�?未继续扩大权限、修改宿主状态库、切换为全权限或制�?Chrome/ACL 故障�?
前两次试跑暴露脚手架未把 SUT 失败传播为自身非零退出码，已修正；原结果仍保留，不能将其
包装进程的退出码 0 记为通过。最终脚本失败返�?1。启动失败的精确操作系统访问对象尚未定位�?不能�?tmp 路径警告断言为唯一根因�?
## 验证层级与成�?
| 检�?| 实际结果 / 命令 | 退出码 |
| --- | --- | ---: |
| 校验器有�?无效输出检�?| `python -B -X utf8 benchmarks/p1b_acceptance.py selfcheck --root <第三个目�?`�? 通过�? 失败�? 跳过；覆盖自报完成、null 回退、过期快照、错误来源轨迹�?/false 混淆 | 0 |
| 后续任务准入负向检�?| `python -B -X utf8 benchmarks/p1b_acceptance.py run --root <第三个目�? --task B`：按预期拒绝，未启动后续 CLI | 1（预期） |
| 语法静态检�?| ast.parse 解析验收脚本，通过 | 0 |
| Skill 同步 | 源码、importlib.resources 随包资源�?6 份任务副本逐字节一致，8,205 字节；模型实际加载未验证 | 0 |
| 三次真实 CLI 尝试 | 0 次任务通过�? 次启动失败，第二任务未执�?| CLI 均为 1 |

三次进程墙钟分别 6.019�?.336�?.027 秒，合计 8.382 秒；这是失败启动成本，不是模型推理时间�?CLI reported usage 均缺失。已开始模型回合、ToolSeed 调用、业务产物均没有观测记录；物理模型请求�?Token、计费、提供方内部重试及完整验证人工成本为 unknown，不填零。复制的 Skill 文件大小不等�?实际上下�?Token。未运行维护，未证明节省、摊销或净收益�?
未运行全量质量门禁、历�?A/B、无�?GUI/P1-A 回归。校验器检查只证明其能识别错误输出，不能证�?真实模型会解决、保存或复用。可机读证据见[结果摘要](../benchmarks/results/p1b-acceptance-2026-10-23/result.json)�?
## 后续最短执行路�?
先在可正常启动的、已登录宿主上解决当前唯一�?CLI 启动阻塞，再运行已有两任务；不用修改 Core�?下列命令必须指定全新目录；已有失败目录及证据不重用、不覆盖�?
```powershell
.venv/Scripts/python.exe -B -X utf8 benchmarks/p1b_acceptance.py prepare --root <全新目录>
.venv/Scripts/python.exe -B -X utf8 benchmarks/p1b_acceptance.py selfcheck --root <同一目录>
.venv/Scripts/python.exe -B -X utf8 benchmarks/p1b_acceptance.py run --root <同一目录> --task A
# 先审�?A 的外部校验及实际保存；若无值得保存的方法，接受不保存，不强�?B�?.venv/Scripts/python.exe -B -X utf8 benchmarks/p1b_acceptance.py run --root <同一目录> --task B
```

即使未来 B �?JSON 校验通过，还须审查真�?Skill 读取、search/run 收据、适用性判断及交付�?针对新输入采取的动作，才能确认实际采用；不能自动把交付或校验单独计为复用。必要的任务结果
可由现有内部接口附来源与真实 invocation 关联，本轮没有写入任何此类记录�?
接入方式依据本机 CLI 帮助�?OpenAI Docs �?[本地 Skill 发现](https://learn.chatgpt.com/docs/build-skills)�?[MCP 配置](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)�?[sqlite_home 配置](https://learn.chatgpt.com/docs/config-file/config-reference)。文档支持配置方式，
不证明本机拥有可运行权限或本轮模型行为已经通过�?
最终静态检查：验收脚本语法、结�?JSON、三份新文件的行尾空白及 `git diff --check` 均通过�?退出码均为 0。进入本轮的 126 个正式文件及 3 �?Git 元数据共 129 个指纹全部不变，无缺失；
正式范围仅新增上述三个文件。最�?8 个已跟踪修改�?0 个未跟踪文件，暂存区为空�?
本轮正式新增仅验收脚本、本文和结果摘要；不改生�?Core、Schema v6、索引、四工具协议、Skill�?P1-A、GUI 或宿主配置。没有提交、推送、打 Tag 或发布。到此停止，等待人工架构审查�?