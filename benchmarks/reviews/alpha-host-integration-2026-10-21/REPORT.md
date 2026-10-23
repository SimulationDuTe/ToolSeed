# ToolSeed Alpha 实际接入报告（宿主 = DeepSeek Harness 桌面版）

日期：2026-10-21。产品基线 `c0cac12`（Alpha 产品化提交 `277f38f`）。
本轮只做接入，不开发功能：未改 Core、Schema、四工具协议或 Skill 语义；未重跑 A/B；未重跑整套
质量门禁；未提交、未推送、未发布。

## 1. 识别到的实际宿主与配置方式

- 实际宿主：DeepSeek Harness 桌面版（`F:\DeepSeek Harness`），DSH home 为 `C:\Users\xiazi\.dsh`。
- 宿主已经通过 MCP 通道挂载了四个服务：`godot-ai`、`libresprite`、`git`、`drawio`，登记在
  **home 级** `C:\Users\xiazi\.dsh\cordis.patch.yml`，每行是一个
  `@deepseek-ai/dsh-mcp-client` 的 `insert` 行（`serverName` / `transport` / `command` / `args`）。
- 宿主的 MCP 管理插件（`dsh-plugin-capabilities/src/mcp.ts`）确认了受支持的两种作用域：
  **profile 层**（`<profile>/cordis.patch.yml`，只影响本 profile）与**全局层**
  （`DSH_HOME/cordis.patch.yml`，对本机所有 profile 生效）；新增行必须位于匿名 `- insert:`
  列表内（只有该形式会被挂载）；行 id 采用 `mcp-<serverName>`。
- 插件校验规则（`validateMcpInput`）：`serverName` 需匹配 `^[A-Za-z0-9_-]{1,32}$`，stdio 必须有
  非空 `command`；可选 `args` / `env` / `cwd`。
- 插件界面文案明确：**新增/修改/删除 MCP 行后需要重启 dsh 才生效**。

## 2. 最小接入方案（已准备，受权限阻塞未落地）

作用域取最窄的 **profile 层**（`C:\Users\xiazi\.dsh\profiles\desktop\cordis.patch.yml`），
只新增一行，不触碰全局层，不覆盖任何既有行：

```yaml
- insert:
    - id: mcp-toolseed
      name: "@deepseek-ai/dsh-mcp-client"
      config:
        serverName: toolseed
        transport: stdio
        command: 'F:\ToolSeed\.venv\Scripts\toolseed-mcp.exe'
        args: ['--data-dir', 'F:\ToolSeed\.toolseed']
```

- 待应用的完整物料：`F:\ToolSeed\.test-data-alpha-integration\host-mcp-row.yml`（含两种应用方式说明）。
- 一键应用脚本：`F:\ToolSeed\.test-data-alpha-integration\register_toolseed_mcp.py`
  （幂等、先备份原文、只追加、不改既有行；`--scope profile|global`）。
- 宿主 profile 补丁原文已备份到
  `F:\ToolSeed\.test-data-alpha-integration\desktop-cordis.patch.yml.bak`（1294 字节，未改动）。

## 3. 阻塞（权限，非配置错误）

对该文件的写入被拒绝，**且不是宿主配置本身的问题**：

| 检查 | 结果 |
|---|---|
| 工作区内写入 | 允许（`F:\ToolSeed` 正常） |
| `danger-full-access` 重试同一写入 | 仍被拒（该模式不改变进程令牌） |
| 文件与父目录 ACL | `XIA\CodexSandboxUsers` 仅 `ReadAndExecute`；`XIA\xiazi` 为 `FullControl` |
| 同目录新建文件探针 | 同样被拒（目录级只读） |

即：agent 进程以 `CodexSandboxUsers` 身份运行，对宿主 profile 目录只有读权限。
**按约束未修改 ACL、未申请扩大权限、未改动全局配置**，因此该行尚未写入。

人工落地（任选其一，之后**重启 dsh** 才会加载）：

1. 宿主 UI（推荐，插件自身路径）：MCP 服务器管理页 → 新增 → 作用域选"当前 profile" →
   serverName `toolseed`、transport `stdio`、command `F:\ToolSeed\.venv\Scripts\toolseed-mcp.exe`、
   args `--data-dir F:\ToolSeed\.toolseed` → 保存 → 重启 dsh。
   （插件写盘时会把该文件里既有的裸行吸收进它自己的 insert 列表，属插件的既定行为。）
2. 文件方式：以对 `C:\Users\xiazi\.dsh\profiles\desktop\cordis.patch.yml` 有写权限的账号，
   追加第 2 节的 YAML 块，或直接运行
   `python F:\ToolSeed\.test-data-alpha-integration\register_toolseed_mcp.py --scope profile`。

## 4. 已完成的验证（不依赖宿主写权限）

按宿主将要执行的方式，用产品自身的 `toolseed-mcp.exe` 起了真实 stdio 会话
（`toolbox_*` 四工具走 MCP 协议，不是直接调 Core）：

| 验证项 | 结果 |
|---|---|
| 工具清单 | 恰好 `toolbox_search` / `toolbox_save` / `toolbox_run` / `toolbox_stats` |
| `toolbox_stats` | 返回含 `capabilities` 的结构化结果 |
| 最小保存 | `status=accepted`、`version_status=ready`、`capability_id=cap_a93abf611a6c` |
| 同会话检索 | 命中 1 条 |
| **重启服务后检索**（新进程、同一数据目录） | 仍命中 1 条 → **持久化成立** |
| 交付语义 | `mode=agent_guided`、`execution_status=guidance_delivered`、`task_outcome=unknown`（未被误记为成功） |
| 数据目录 | `F:\ToolSeed\.toolseed\toolseed.sqlite3`（126,976 字节）；该目录已被 `.gitignore` 忽略，不进版本库 |
| 服务端 stderr | 空（无告警） |

执行环境的已知限制：agent 自己的 shell 不能创建 asyncio 重叠管道（与仓库里被跳过的那条 stdio
用例同源），因此改用阻塞管道的原始 JSON-RPC 客户端驱动同一个产品服务；宿主进程不受此限——
现有四个 MCP 服务即由宿主以同样方式拉起。

## 5. 仍未闭合的一步

宿主识别需要**两件事**：写入该行 + 重启 dsh。写入当前被权限阻塞（见第 3 节），重启属于人工操作。
完成后可由人工按下列方式确认（不需要新增开发）：

- 重启后宿主工具清单应出现以 `mcp__toolseed__` 为前缀的四个工具
  （前缀规则可由现有 `mcp__git__*`、`mcp__drawio__*` 观察到；**这一条目前是待验证的预期，
  不是既成事实**）；
- 调用 `mcp__toolseed__toolbox_stats` 应看到与本报告第 4 节一致的能力与版本计数；
- 调用 `mcp__toolseed__toolbox_search` 应能检索到 `alpha_integration_smoke`。

## 6. 状态

- 未改动产品代码、Core、Schema、四工具协议与 Skill 语义；未提交、未推送、未发布。
- 本地新增（均在忽略目录或未跟踪目录）：`.test-data-alpha-integration/`（含验证脚本、待应用
  YAML 物料、应用脚本、宿主补丁备份）与 `.toolseed/`（宿主将使用的数据目录，已被 gitignore）。
- 历史实验数据与历史交付物未受影响。
