# DSH 本地部署记录

2026-10-27，已通过 DSH 官方包管理器安装新版本地插件，并同步 ToolSeed Skill。
这是未发布的本地快照，不代表已有 Release 包含这些功能。

## 当前安装

- 宿主：已安装的 DeepSeek Harness Desktop 0.2.1-rc.2。
- 快照：`.toolseed/hosts/dsh/local-e4121a8fa6d3-dirty-423832b1`。
- 快照指纹：`423832b10ac7fff45241f6c26f45459d279aff1092c5ef615569d597b0048ec1`。
- 注册形式：快照内 `integrations/dsh-toolseed-b564fc87e2558029.tgz` 的 `file:` 依赖。
- Python：项目原有 `.venv311/Scripts/python.exe`，ToolSeed Core 为当前源码的 editable 安装。
- 能力库：项目原有 `.toolseed`，schema 6。
- Skill：用户 DSH 目录下 `skills/toolseed/SKILL.md`，内容哈希与随包新版一致。

学习提示、主动召回与修订验证使用默认开启配置。已有对话可能保留早先加载的 Skill 内容，
新对话可加载当前指引。模型判断哪些经验值得保留、哪些方法适用；不会要求每次任务都保存能力。

## 已完成的检查

从 DSH 实际安装目录加载完整插件入口，在真实 DSH Agent/ToolRuntime 中连接实际 Python 和能力库，
确认注册以下工具：

- `mcp__toolseed__toolbox_search`
- `mcp__toolseed__toolbox_run`
- `mcp__toolseed__toolbox_save`
- `mcp__toolseed__toolbox_learn`
- `mcp__toolseed__toolbox_stats`
- `toolseed_validate_revision`

设置页的 Connection 使用检查替身；这次检查没有读取运行中会话或证明其模型已采用方法。
实际安装的 11 个包文件逐一与快照核对一致，Skill 与源码核对一致。
验证只枚举工具，没有调用模型或写入测试能力。原库仍为 2 个能力、2 个版本、3 次交付、19 条证据事件。
真实任务中模型自主提炼、采用和改进经验的行为，尚未作为本次部署验收结果。
后续已完成[两轮真实任务实测](../benchmarks/results/dsh-experience-2026-10-27/REPORT.md)：在隔离的 DSH headless 中观察到提炼、召回、实际采用和反馈回流；这不替代运行中 Desktop UI 会话的验收。

机器可读记录、包与文件哈希保存在本地 `dist/dsh-deployment-20261027.json`。
早先失败的安装尝试保存在快照的 `initial-install-attempt.json`；最终管理状态为 `active`。
部署排障脚本、备用快照及旧构建包已归档到 `.test-data/deployment-20261027`，对应关系见其中的 `ARCHIVE.json`。

## 安装中修正的问题

1. 安装器快照清单补齐 `learning.js`、`recall.js`、`revisions.js`，避免升级后缺少模块。
2. 本地插件打包成包含 package.json 和声明文件的固定 `.tgz`，避免包管理器保留开发目录链接。
   包内容决定文件名，压缩内容可重复生成；新增回归覆盖包完整性、内容与升级指纹。
3. 嵌套安装进程遇到 Windows 拒绝访问后，最终通过直接运行官方 DSH 包管理命令完成安装，
   没有修改系统权限。配置与 Skill 的备份保留在各自原目录。

本轮仅更新 DSH。Codex 当前连接的独立 ToolSeed 运行环境未在这次部署中切换。

## 查看状态

```powershell
.venv311/Scripts/python.exe -X utf8 -m toolseed host dsh `
  --install-root F:/ToolSeed/.toolseed/hosts `
  --data-dir F:/ToolSeed/.toolseed --json
```

管理安装根目录为项目内显式配置的目录；省略 `--install-root` 会查询另一个默认位置。
状态中的注册成功与运行中模型是否实际复用方法仍是不同事实。
