# ToolSeed v0.4.1 — 安装前提、Git 安装型 MCP 配置与已知限制

发布日期：2026-10-21。Tag：`v0.4.1`（本地已创建，**尚未推送**）。

## 1. 安装前提

| 项目 | 要求 | 说明 |
|---|---|---|
| Python | >= 3.11 | pyproject `requires-python = ">=3.11"`；已在 3.11.16 与 3.13.1 验证 |
| Git | 需要 | Git 安装型安装会克隆仓库并检出 tag |
| 网络 | 需要访问 PyPI | 运行时依赖只有 `mcp>=2.3,<3`；若机器不能访问 PyPI，需另行准备本地 wheelhouse |
| 写权限 | 数据目录需可写 | 默认 `~/.toolseed/`，可用 `--data-dir` 或 `TOOLSEED_DATA_DIR` 覆盖 |
| 磁盘 | 数 MB | 一个 SQLite 库（初始化后约 124 KB） |

## 2. Git 安装

```bash
python -m venv .venv-toolseed
.venv-toolseed/Scripts/pip install "git+https://github.com/SimulationDuTe/ToolSeed@v0.4.1"
```

安装后 `pip list` 应显示 `toolseed 0.4.1`；`toolseed` 与 `toolseed-mcp` 两个入口脚本位于
`.venv-toolseed\Scripts\`（POSIX 为 `bin/`）。

## 3. 可直接复制的 MCP 配置

**Claude Code / Cursor（`mcpServers` JSON）**

```json
{
  "mcpServers": {
    "toolseed": {
      "command": "C:\\path\\to\\.venv-toolseed\\Scripts\\toolseed-mcp.exe",
      "args": ["--data-dir", "C:\\path\\to\\.toolseed"]
    }
  }
}
```

**Codex（`~/.codex/config.toml`）**

```toml
[mcp_servers.toolseed]
command = "C:\\path\\to\\.venv-toolseed\\Scripts\\toolseed-mcp.exe"
args = ["--data-dir", "C:\\path\\to\\.toolseed"]
```

**DeepSeek Harness（profile 层 `cordis.patch.yml` 的匿名 `- insert:` 行）**

```yaml
- insert:
    - id: mcp-toolseed
      name: "@deepseek-ai/dsh-mcp-client"
      config:
        serverName: toolseed
        transport: stdio
        command: 'C:\path\to\.venv-toolseed\Scripts\toolseed-mcp.exe'
        args: ['--data-dir', 'C:\path\to\.toolseed']
```

要点：命令写**绝对路径**；数据目录写绝对路径，避免宿主工作目录变化后能力库"看起来丢了"；
Dsh 侧新增/修改 MCP 行后需要**重启 dsh** 才生效。

## 4. 安装后核验（每步都可本地验证）

1. 四个工具名正确：服务端只暴露 `toolbox_search`、`toolbox_save`、`toolbox_run`、`toolbox_stats`。
2. `--data-dir` 生效：握手后 `<data-dir>\toolseed.sqlite3` 存在；未指定数据目录时使用
   `~/.toolseed/`。
3. 最小保存与检索：`toolbox_save` 返回 `status=accepted`、`version_status=ready`；
   `toolbox_search` 能取回该能力；重启服务进程后仍能检索到。
4. 随版本交付的文件确实在安装产物里：`<site-packages>\toolseed\skill\SKILL.md` 存在
   （随包分发的 Agent 行为规约）。

## 5. GitHub Release 与 PyPI 的区别

| | GitHub Release | PyPI |
|---|---|---|
| 触发方式 | 推送 `v*` tag → `.github/workflows/release.yml` | 单独、需授权的发布步骤 |
| 产物 | sdist + wheel + `SHA256SUMS` 作为 Release assets | 同类产物，但需账号与 API token |
| 本次范围 | 准备就绪，等待人工确认后推送 tag | **不发布**；Git 安装是当前唯一受支持路径 |

发布工作流本身不做 PyPI 上传；`gh release create` 只创建 GitHub Release。

## 6. 已知限制（随版本一同声明）

- **净收益未证明**：真实 Agent 工作中观察到跨任务 Procedure 复用，但方法库路径的实测成本
  没有更低；货币净收益为 `unknown`（provider 侧计费 Token 不可观测）。
- 不执行任何代码：无 `executable`、无 Python Runtime、无沙箱；`kind` 非 `procedure` 时返回
  `UNSUPPORTED_CAPABILITY_KIND`。
- Procedure 是**不可信数据**，只作为能力材料交付，不能自我授权。
- 单用户本地存储：不是多租户服务；多宿主指向同一 `--data-dir` 即共享同一能力库。
- 交付的 Procedure 不代表任务成功；缺少可信外部信号时 `task_outcome` 保持 `unknown`。
- 文档（`docs/`）随仓库分发，**不包含在 wheel/sdist 内**；Git 安装用户可直接阅读仓库文档。
- 宿主接入：不同宿主的 MCP 登记方式与生效时机不同（如 DSH 需重启），本包只提供 stdio 服务。
