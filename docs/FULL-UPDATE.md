# Core 与宿主的完整升级

`toolseed update <codex|dsh> --ref <tag|commit|branch|本地源码目录>` 现在是完整升级入口。
它复用现有原生安装器，更新同一 commit 的 Core、ToolSeed Skill、MCP 指向与适配器。
源码只在本次命令开始解析一次；完整源码快照和运行环境不依赖开发目录。

```powershell
toolseed update codex --ref <已发布的 tag 或 commit>
toolseed update dsh --ref <已发布的 tag 或 commit>
toolseed update codex --ref develop --plan --text
```

升级功能本身必须先安装到调用命令的 ToolSeed 包；尚未推送的本地改动使用
`--ref F:/ToolSeed` 验证。旧发布包或缺少新探测接口的目标会明确失败，不伪装为已升级。

实际 MCP 配置中的绝对能力库目录优先，沿用已记录 Home、MCP 名称、Codex 工作目录和
DSH 命令；可显式指定 `--install-root`、`--codex-home`、`--dsh-home`、`--cwd` 等。
`--data-dir` 与已有 MCP 指向不一致时拒绝，不自动搬迁或合并能力库。

每个源码树内建立单独的 Python 环境，优先用可用的 uv 安装，无 uv 时使用 venv + pip。
`--python` 指定创建环境的基础解释器；不会原地卸载正在被宿主占用的 Core 或入口程序。
`TOOLSEED_UV` 可显式选择 uv；`TOOLSEED_NODE` 可选择稳定安装的 Node 22+。
默认允许包管理器安装所需依赖；`--offline` 仅限制 Core 依赖安装，GitHub 下载仍需要网络，
完全离线请同时使用本地 `--ref`。该版本增加 PyYAML，用于按宿主节点读取 DSH YAML；
`!!js` 等自定义标签作为惰性文本读取，不执行表达式。

执行顺序：

1. 取得固定源码，读取实际生效的 MCP 配置；Codex 项目级覆盖优先于全局配置。
2. 检查所有目标文件和父目录写权限。权限失败发生在 Core 安装、配置修改与迁移之前。
3. 安装独立 Core，检查实际注册的五工具、功能、版本、schema 和安装文件与源码的一致性。
4. 只读备份已有 SQLite 数据库，在独立副本上试迁移；更高版本的库拒绝降级。
5. 仅调整所选 MCP 的启动命令和参数；保留其余配置、环境变量、超时与其他 MCP。
   DSH 保留原 MCP 节点 id，在 desktop patch 中写入自己的标记块，面板与 MCP 使用相同 Python/库。
6. 同步 Skill，并调用现有官方适配器安装器。DSH 仍要求完全退出 Desktop。
7. Codex 核验实际 Hook 列表、原生信任、Skill 与配置的 MCP；DSH 比对实际安装包各文件。
8. 需要时迁移已有原库，最后才写成功清单和当前指针。缺失的库留待首次正常使用初始化。

成功结果包含 `core`、`runtime_config`、`verification`、`database` 和配置备份目录。
再次更新同一固定源码会检查当前文件与宿主就绪情况；健康时返回 `already-current`，
不会重复安装环境。`--repair` 强制重新应用。

失败处理以实际结果为准：

- 一个宿主同时只允许一个升级进程；异常终止留下 `.update.lock` 时，确认进程结束后再移除该文件。
- 配置备份位于 `backups/<operation>/`，`files.json` 映射原路径与备份；原库备份与迁移试验分开。
- 失败时尝试恢复配置原始字节；若文件已被另一个写入者再次修改，保留其修改并报告恢复不完整。
- DSH 包注册通过官方 CLI 恢复；失败会使 `dsh_package_restored=false`，不会只恢复元数据后宣称成功。
- 数据库迁移是单独事务。迁移已经提交后，不自动倒回备份，以免覆盖其他进程的新数据；结果明确报告
  `database.changed`。升级跨越不可逆迁移时，不能把保留旧指针视为已恢复全部状态。
- 新环境留作缓存，旧运行环境保留。完整升级记录存在时拒绝 `uninstall --purge` 删除可能仍被 MCP 引用的环境。

`--adapter-only` 保留历史适配器升级行为，不管理 Core 或 MCP 配置。
完整更新不会重启用户桌面或增加模型轮次；成功后新建 Codex 聊天、打开 DSH 加载新版。
安装就绪检查不能证明模型会主动学习、采用方法或完成任务。

验证包含 GitHub 请求的固定 SHA、完整源码打包、MCP 配置与用户字段保全、DSH 自定义 YAML 标签、
独立 Core 导入、数据库副本试迁移、依赖/权限/原生验证失败恢复、并发写入和重复升级。

当前 DSH 安装器实际版本为 `0.2.1-rc.3`。本轮使用其原生 AgentLoop、ToolRuntime 与实际 MCP
通过学习、复用观察、修订失败保持旧版/通过后激活以及主动召回探针；均为隔离库和脚本驱动，
不调用真实模型。插件兼容声明因此限定为已核验的 `rc.2 || rc.3`，没有授予版本豁免。

本地最终结果：Python 442 项（441 通过、1 项条件跳过），Node 157 项通过，编译、Ruff、mypy
（39 个源文件）通过。Codex `0.165.0-alpha.1.2` 与 DSH `0.2.1-rc.3` 均在隔离 Home 完成真实
Core 安装、宿主自检及再次升级不重复安装；Codex 验证 v6→v7 保留方法及 hash，DSH 验证缺库不创建。
GitHub 固定请求由归档契约测试覆盖；原生完整安装使用本地同版本源码，尚未推送的版本未作远端发布验收。
材料位于 `.test-data/full-update-20261028/`；本轮未修改用户实际宿主配置或能力库。
