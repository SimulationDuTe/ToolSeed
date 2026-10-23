# P1-B：DSH 真实模型验收记录�?026-10-23�?
**闭环未成立�?* 真实 DSH Agent 完成任务 A，外部校�?5 个案例通过；自主检索一次、结果为空，
没有保存能力。任�?B 不具备复用前提，未启动。不能据此宣称非脚本能力沉淀、实际采用或跨任务复用成功�?
## 环境与隔�?
- 仓库 `F:/ToolSeed`，分�?develop，HEAD `f63c007284b592bd4c07d0509f1c753d6c7b571f`�?  开始时 8 个已跟踪修改�?0 个未跟踪文件，全部保留�?- 使用本机 DSH 0.2.1-rc.2 的官�?`dsh.cmd --profile headless --patch ... --json`�?  **这是实际 DSH Agent 运行，不是模拟，也不�?Desktop UI 对话验收�?*
  Desktop profile 明确拒绝 CLI 使用：`profile "desktop" is managed exclusively by the Electron application`�?  本轮没有转用 Codex CLI，也没有修改 Desktop 的宿主文件或接入权限�?- 核对�?Desktop �?ToolSeed 插件、现�?stdio MCP 和数据目录：正式能力库为 `F:/ToolSeed/.toolseed`�?  测试使用全新�?`.test-data/p1b-dsh-20261023-61cc9a69`；DSH_HOME、profile、Skill 根目录、spill
  �?MCP 数据目录全部独立。唯一接入�?MCP �?toolseed，其四工具由源码服务器提供：
  `.venv311/Scripts/python.exe -B -m toolseed.mcp_server --data-dir <隔离目录>/library`�?  未导入、预置或补写能力�?- 复用 `benchmarks/p1b_acceptance.py` �?prepare、任务输入和确定�?verify；未调用�?Codex run�?  只在忽略目录内增�?DSH 接线脚本、声明式配置和结果，不改原验收脚本或生产代码�?  A/B 各有独立目录；B 输入不同且未泄露 A 的结果或能力 ID。B 实际未运行�?- 使用现有提供�?`@jiesou/dsh-opencode-zen-free-provider` 0.1.28 的声明式 profile bundle，链接已安装包，
  未下载或修改提供方。固定请�?`deepseek-v4.1-flash-free` / max，与验收开始时 Desktop 选择一致�?  未复制凭据。提供方内部实际路由、重试及计费未知�?- 原样复制源码 Skill�?,205 字节）至私有 customSkillDirs，关闭默�?Skill 根目录�?  用户安装�?Skill �?8,650 字节，存在部署漂移：缺少 context 对象说明，仍要求成功保存返回 `ok: true`�?  当前源码及实现要求检�?`status: accepted`，成功响应没�?`ok` 字段�?  没有覆盖用户 Skill�?*配置 Skill 不等于模型实际加�?*；本轮未观测�?skill 调用或读取其正文�?  保留的事件也不足以证�?Skill 目录实际送达模型，不能据此确定跳过的原因�?- 内层 DSH 保持 workspace-write / ask；禁用与此任务无关的�?Agent、Web、标题模型和遥测�?  没有挂载依赖 connection �?ToolSeed 设置面板/P1-A 插件；本轮不重新验收机会 Hook �?Desktop 面板�?
## 实际运行与证�?
任务是重复发布前的只读配置诊断，要求辨认优先级覆盖、空数组替换、类型错误及运行快照可信度�?这是具有潜在复用价值的非脚本诊断流程；业务提示只有 `Complete task.md in this workspace.`�?没有要求使用 ToolSeed、指定能力或要求保存�?
| 阶段 | 实际证据 | 结论 |
| --- | --- | --- |
| 首次解决 | A 写出 diagnosis.json �?review.md�? 个结构化案例通过原有 verify�?2 个受保护输入指纹不变 | 通过该任务的外部校验，不能推广为通用方法验证 |
| 自主搜索 | events.jsonl �?75�?6 行：`mcp__toolseed__toolbox_search`，查询验证器运行问题，返�?`results: []` | 确有自主调用；不是业务诊断方法命�?|
| Agent 内验�?| pwsh 执行检查被宿主锁文件访问拒绝阻断；后台调用仅返回作业句柄，没有成功结果收据 | 未执行成功；最终自述的手工比对不代替独立校�?|
| 外部验证 | 接线脚本�?Agent 结束后调用现�?verify，verdict.json：passed=true、case_count=5、failures=[] | 5 通过�? 失败；结果未回注原对话，不能声称 Agent 已收到校验通过 |
| 保存 | 全部 94 条保留事件中没有 toolbox_save；只读数据库查询 capabilities=0、versions=0 | 未发生；不能归因于保存接口拒�?|
| 独立复用 | A 无保存，未启�?B，不预置或代存能�?| 未验收，不算通过或任务失�?|
| 实际采用/任务结果入库 | invocations=0；只有一�?search_performed、outcome=unknown | 无交付、采用或任务结果证据；外部校验没有伪写入 Core |

真实运行�?21 次工具调用中�?1 �?completed�?0 �?error。pwsh �?9 次调用中�? 次返�?`CreateFileW failed (Win32 5): %TEMP%/dsh-acl-locks/<opaque>.lock`�? 次仅交付后台作业句柄�?�?1 次申�?danger-full-access，因没有审批通道被宿主拒绝（�?71�?2 行）。另�?glob 启动失败�?读取锁文件失败�?*没有批准扩大权限，也没有修改 ACL�?* 这是此次运行实际遇到的环境错误，
并非为验收制造原�?Chrome/ACL 故障；错误文本不能冒充结构化错误码或既有 P1-A 覆盖证据�?
前一次独立接入尝试保留在 `.test-data/p1b-dsh-20261023-7f44df06`：直接文件导入提供方导致
`RetryPolicySchema.volatile is not a function` / NO_ADAPTER，模型前退�?1，缺产物，校验失败�?改用该包声明�?bundle 并配置私�?spill 后，当前尝试已真实运行模型。未修改任何宿主或提供方源码�?
## 命令、成本与验证范围

本轮执行既有 prepare 两次，分别准备上述两个全新目录；未覆盖旧目录。接入探针包括官�?`--dump-config`、`--dump-config-schema`：隔离配�?Schema 探针退�?0，确认独�?MCP 数据目录、Skill
配置及提供方装载；Desktop profile CLI 探针退�?1（宿主的明确限制）�?
实际任务命令�?
```powershell
.venv/Scripts/python.exe -B -X utf8 F:/ToolSeed/.test-data-p1b-dsh-20261023-61cc9a69/dsh-run.py A
```

该脚本在 task-A 中启动官�?DSH headless，外层正常进程执行不改变 DSH 内层沙箱策略�?DSH 退�?0，接线脚本退�?0；这两个退出码只与 A 的独立校验一起解释，**不是 P1-B 验收通过**�?Schema v6、真实统计及事件通过 SQLite mode=ro 查询，未执行维护或写入评估�?
| 可测项目 | 实际�?限制 |
| --- | --- |
| 当前 A 运行墙钟 | 118.129 秒，含模型、工具、启动及外部校验；不是纯模型耗时 |
| DSH step_end usage 条数 | 22；不等于物理 HTTP 请求数或独立模型调用计费�?|
| usage.inputTokens 累加 | 17,253 |
| usage.cacheReadTokens 累加 | 200,704（字段缺失的第一步不另造缓存记录） |
| usage.outputTokens 累加 | 7,311 |
| usage.totalTokens 累加 | 225,268，含反复发送上下文和缓存；采用宿主报告口径 |
| 首次模型前失败墙�?| 5.539 秒；没有 usage，Token/物理请求�?unknown |
| 物理模型请求、计费、净收益、维护摊销 | unknown；没有无复用基线或任�?B，不能推断节�?|

未重跑原 A/B 实验、已有校验器 selfcheck、P1-A、GUI 或全量质量门禁。外�?verify 是真实产物检查，
不是 Agent 行为模拟。保留事件投影丢�?thinking，保留任务工具动作、结果、usage 和最终答复；
不新�?ToolSeed 日志机制。宿主自身的会话持久化仍�?DSH 负责�?
交付前以 `.venv/Scripts/python.exe -B -X utf8 -` 执行只读材料核对：外�?verdict、真实工具调用�?usage 算术、数据库事实、私�?Skill 同步�?2 个输入指纹、报告格式及脚本语法�? 通过�? 失败�?0 跳过、退出码 0。这些是材料一致性检查，不是 8 项真实行为验收。`git diff --check` 退�?0�?只有既有文件�?LF/CRLF 提示。最�?8 个已跟踪修改�?2 个未跟踪文件，暂存区为空�?
本轮正式新增仅本文和 `benchmarks/results/p1b-dsh-2026-10-23/result.json`；原始证据留在忽略目录，
包括 invocation.json、events.jsonl、verdict.json、summary.json、输入及 Agent 产物，未清理�?
## 工作区保护与剩余阻塞

132 个既有文件指纹（129 个正式文件及 3 �?Git 元数据）全部不变；暂存区为空�?生产数据库、WAL、SHM、用�?Skill 及用户全局 MCP patch �?5 个指纹不变�?Desktop profile patch 在验收期间变更：开�?SHA256 �?`0ce8ae3cdfe70b04df6fa5b0d1369241105368a1b23c496e819b31950b0cf104`，结束核对为
`167712571d5893dae311470f5f517893e68f5c76008b09157ae04c4553b9cb59`，默认模型已变为
commandcode / deepseek/deepseek-v4.1-flash；其 ToolSeed 数据目录未变。本轮命令没有写入该文件�?外部变更来源未知，未恢复或覆盖。此次固定模型结果不能冒充变更后 Desktop 配置的验收结果�?
已确认的运行阻塞�?DSH 命令工具无法提供校验执行结果；未加载 Skill 和未保存的因果仍未知�?没有证据证明 Core、Schema、搜�?保存协议存在必须修复的缺陷，不改生产代码�?
**下一步仅建议：在能正常执行现有校验器的隔�?DSH 会话中，确认最�?Skill 可发现，再原样重�?同一对任务�?* 不在业务提示中提�?ToolSeed，不以手动加�?代存替代自主行为；只�?A 真正完成
验证后保存，才进入全�?B。当前不修改权限或宿主配置，不继续换模型抽样，不把未验收包装成通过�?
未提交、推送、打 Tag 或发布。到此停止，等待人工架构审查�?