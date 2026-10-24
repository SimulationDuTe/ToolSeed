# 统一安装与生命周期管理

`toolseed install|update|uninstall|host` 为 DSH 与 Codex 提供同一套安装入口。
安装器**复用** `integrations/codex/src/install.mjs` 与
`integrations/dsh/install.ps1`，不重写 Core、Schema 或四工具协议。

## 命令

```bash
# 首次安装：按固定 commit 获取源码，装到独立目录
toolseed install codex --ref <tag|sha|本地源码目录>
toolseed install dsh   --ref <tag|sha|本地源码目录> --python <MCP 使用的 Python>

# 只读检查宿主、版本、Skill、Hook、MCP 配置与能力库
toolseed status
toolseed host --text
toolseed host codex --deep     # 额外启动 Codex app-server 核验 hooks/skills

# 升级：必须显式指定目标版本；失败保留原安装
toolseed update codex --ref <tag|sha>
toolseed update dsh   --ref <tag|sha>

# 卸载：只移除 ToolSeed 自己的文件与配置
toolseed uninstall codex
toolseed uninstall dsh
toolseed uninstall codex --purge   # 另删本适配层历史版本目录，不动能力库
```

通用参数可放在子命令前后：`--data-dir`、`--install-root`、`--text`、`--json`。
默认 JSON。`--install-root` 默认 `~/.toolseed/hosts`，与能力库目录相互独立。

## 版本固定

- 每次安装解析成**不可变 commit SHA**，写入 `install.json`，同时记录
  `version`、`ref`、`ref_kind`、`prerelease`、来源 URL 与安装时间。
- Tag 记录为稳定版本；分支或裸 SHA 记录为**预发布**，不会伪装成稳定版。
- 已发布 Tag 目前最高为 `v0.4.1`，**没有任何 Release 包含 Codex Adapter**；
  因此 Codex Adapter 只能以预发布 SHA 安装。`update` 不会跟随 `develop` 漂移，
  必须显式给出 `--ref`。
- 本地源码目录会额外记录 `dirty` 与内容指纹；脏工作区不会被误判为已安装版本。

## 安装布局

```
~/.toolseed/hosts/<host>/
  current.json                 # 当前激活目录 + SHA + 版本
  <label>/
    install.json               # 清单：版本、SHA、来源、指纹、preflight
    integrations/...           # 该 commit 的适配层代码（独立副本）
    toolseed/skill/SKILL.md
```

安装树只复制适配层实际需要的白名单文件，不包含仓库元数据，也不引用开发工作区。

## 安全升级

1. 获取新版本到**新目录**，先跑安装器 dry-run 预检；
2. 再实际安装；成功后写 `current.json` 切换指针；
3. 失败时**不切换指针**，原安装保持激活，并返回失败目录便于诊断。

升级前会对将被修改的用户文件（`hooks.json`、`AGENTS.md`、SKILL、DSH patch）
生成 `.bak-toolseed-*` 备份。

## 卸载边界

- Codex：移除 `skills/toolseed/`、`hooks.json` 中 ToolSeed 的 PostToolUse 组、
  `AGENTS.md` 标记块与适配层状态/日志；**保留** MCP 配置、其他 hooks、无关
  Skill、能力库。
- DSH：移除 `cordis.patch.yml` 标记块并备份；插件包通过官方
  `dsh plugin --profile desktop remove dsh-toolseed` 处理（命令由卸载结果提示，
  因为移除包属于宿主包管理）。**保留**其他插件、用户 patch 与能力库。

## 已知限制

- 安装需要访问 GitHub（`codeload` 与 API）或本地源码目录；离线环境请用
  `--ref <本地目录>`。
- `install`/`update` 会调用宿主安装器：DSH 默认要求完全退出 Desktop，
  只有显式传入**非默认** `--dsh-home` 的隔离配置才允许在运行时写入。
- `toolseed status` 默认**不启动** Codex app-server，因此
  `host_verification` 为 `unknown`；`--deep` 才会核验 hooks/skills，且该检查
  可能初始化 Codex 自身状态。
- 配置存在不等于面板已加载或任务成功；状态检查区分 `ok` / `missing` /
  `error` / `unknown`，不会把未知项显示为正常。
- 不创建空能力库，不迁移或合并数据；数据库缺失时显示 `absent`。
