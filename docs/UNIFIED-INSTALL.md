# 统一安装与生命周期管理

`toolseed install|update|uninstall|host` 为 DSH 与 Codex 提供同一套安装入口。
安装器**复用** `integrations/codex/src/install.mjs` 与
`integrations/dsh/install.ps1`。`install` 保留适配器安装行为；`update` 默认升级
同一固定源码中的 Core、Skill、MCP 配置与适配器。五个公共 MCP 工具保持不变。

## 命令

```bash
# 首次安装：按固定 commit 获取源码，装到独立目录
toolseed install codex --ref <tag|sha|本地源码目录>
toolseed install dsh   --ref <tag|sha|本地源码目录> --python <MCP 使用的 Python>

# 只读检查宿主、版本、Skill、Hook、MCP 配置与能力库
toolseed status
toolseed host --text
toolseed host codex --deep     # 额外启动 Codex app-server 核验 hooks/skills

# 完整升级：显式指定版本；沿用宿主现有能力库和已记录的 Home
toolseed update codex --ref <tag|sha>
toolseed update dsh   --ref <tag|sha>
toolseed update codex --ref develop --plan
toolseed update codex --ref <tag|sha> --adapter-only  # 兼容原适配器升级

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
    toolseed/...               # 完整的同版本 Core 源码与 Skill
    .runtime/...               # 完整升级安装的独立 Core 环境
  backups/<operation>/         # 原配置映射、数据库原始备份与试迁移副本
```

安装树只复制适配层实际需要的白名单文件，不包含仓库元数据，也不引用开发工作区。

## 安全升级

1. 将 GitHub tag/branch 固定为 commit，获取完整的构建所需文件；
2. 读取实际 MCP 配置与现有库路径，拒绝静默换库、禁用服务和无法确定的配置；
3. 检查全部配置目标的写权限，在独立环境安装同版本 Core 并检查实际导入内容；
4. 备份已有库，在副本上验证迁移；
5. 同步 MCP、Skill、原生适配器，检查 Codex Hook 信任或 DSH 实际安装文件；
6. 需要时迁移原库；全部通过才写 `current.json`。缺库保持未初始化。

升级前会对将被修改的用户文件（`hooks.json`、`AGENTS.md`、SKILL、DSH patch）
生成备份。完整升级使用配置文件日志，失败时恢复未被其他进程再次修改的原文件；
DSH 包注册通过官方 CLI 尝试恢复。恢复失败、并发修改、数据库已迁移分别报告，
不会把保留旧指针等同于完整回滚。运行环境保留为缓存。见[完整升级与恢复边界](FULL-UPDATE.md)。

## 卸载边界

- Codex：移除 `skills/toolseed/`、`hooks.json` 中 ToolSeed 的 PostToolUse 组、
  `AGENTS.md` 标记块与适配层状态/日志；**保留** MCP 配置、其他 hooks、无关
  Skill、能力库。
- DSH：移除 `cordis.patch.yml` 标记块并备份；插件包通过官方
  `dsh plugin --profile desktop remove dsh-toolseed` 处理（命令由卸载结果提示，
  因为移除包属于宿主包管理）。**保留**其他插件、用户 patch 与能力库。
- 完整升级后 Core 位于安装树中。`--purge` 会拒绝删除这类树，避免保留的 MCP 配置引用被删环境；
  使用普通卸载保留 Core，确认所有 MCP 引用已移除后再单独清理。

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
- 只读状态与适配器安装不迁移能力库；完整 `update` 可备份并迁移已有库，不合并两个宿主的库，
  不创建缺失的空库。目标 schema 比现有库更旧时拒绝降级。
