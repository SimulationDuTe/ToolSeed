# ToolSeed v0.4.1 发布准备报告（待人工确认，尚未发布）

日期：2026-10-21。产品基线 `c0cac12`；Alpha 产品化提交 `277f38f`。
本轮只做版本核对、安装路径验证与发布材料准备：**未推送、未创建 GitHub Release、未发布 PyPI**。

## 1. 版本核对结果与定版依据

| 检查项 | 实际状态 |
|---|---|
| `pyproject.toml` 版本 | `0.4.0`（HEAD `277f38f` 时） |
| 本地 Tags | `v0.3.0` → `455cdec`；`v0.4.0` → 附注标签 `12f7cea` → 提交 `5a46954` |
| 远端 refs（`git ls-remote`，实测可达） | `refs/heads/main` = `refs/heads/develop` = `5a46954`；`refs/tags/v0.3.0`、`v0.4.0` 已存在；**无 `v0.4.1`** |
| HEAD 与 Alpha 提交 | HEAD = `277f38f`（= Alpha 提交），其父链含 `c0cac12` → `0f1648c` → `5a46954`（= `v0.4.0`） |
| 本地相对远端 | 领先 `origin/develop` **3 个提交**（`0f1648c`、`c0cac12`、`277f38f`）——Alpha 成果尚未推送 |
| `v0.4.0`..HEAD 差异 | 2 个修复提交 + 1 个文档/Skill/测试提交；`toolseed/adapters/local.py`（四工具协议）与 `toolseed/core/manifest.py`（候选契约）**零差异**；`toolseed/core/storage.py` 仅事务提交失败回滚一处修复，**无 schema 迁移** |
| 最新 GitHub Release | **本机无法核验**：`api.github.com` 的 DNS 在本机解析到非公网地址（HTTPS 不可达），因此只能依据远端 git refs 判断"v0.4.0 已存在且指向 `5a46954`" |

**定版：`0.4.1`。** 依据：源码版本已是 0.4.0 且 `v0.4.0` 已发布到远端，故不能沿用 0.4.0；
`0.3.2` 属旧版本线的补丁、与当前源码（0.4.x）不符；`v0.4.1` 远端未占用；本版相对
`v0.4.0` 只有向后兼容的修复与文档，不含 schema 迁移或协议变更 → 补丁版本号正确。

## 2. Git 安装路径验证（干净临时环境）

环境：全新 venv `F:\ToolSeed\.test-data-release-0.4.1\clean-venv`（Python 3.11.16，由 uv 创建，
**与开发机 `F:\ToolSeed\.venv` 无关**）。

| 验收项 | 结果 |
|---|---|
| 安装来源 | 由 **tag `v0.4.1` 的内容**构建安装（`toolseed==0.4.1`，非 editable） |
| 导入位置 | `<clean-venv>\Lib\site-packages\toolseed\__init__.py` —— 位于干净环境内，**不在源码树**（在不含 `toolseed` 的中性 cwd 下复核，排除 cwd 遮蔽） |
| 版本 | `0.4.1`；依赖 `mcp 2.3.0` |
| 入口脚本 | 干净环境 `Scripts\toolseed.exe`、`Scripts\toolseed-mcp.exe` 均存在 |
| 随版本交付文件 | 安装产物含 `toolseed/skill/SKILL.md`（5,440 字节），与 tag/HEAD 内容一致（换行归一后哈希相同） |
| 四个 MCP 工具 | 服务端只列出 `toolbox_search`、`toolbox_save`、`toolbox_run`、`toolbox_stats` |
| `--data-dir` | 指定目录内生成 `toolseed.sqlite3`（126,976 字节） |
| 最小保存 | `status=accepted`、`version_status=ready`（`cap_7acfea42b95d`） |
| 检索 | 同会话命中 1 条；**服务进程重启后仍命中 1 条** → 持久化成立 |
| 交付语义 | `agent_guided` / `guidance_delivered` / `task_outcome=unknown` |
| 服务 stderr | 空 |

**本机环境限制（如实记录）**：
- 本机到 PyPI 的 HTTPS 不通，依赖 `mcp` 及其依赖从本地 wheelhouse 解析；产品本体来自 Git Tag。
- `git clone` / `git+file://` 传输在本机被 git 的 `sh.exe` 管道限制拒绝，因此用
  `git archive v0.4.1` 导出 tag 内容后构建安装——这与 pip 的 git 安装在取得源码后的步骤等价，
  但**字面的 `git+https://…@v0.4.1` 传输未能在本机跑通**（远端 git 协议本身可达：`ls-remote` 成功）。
- 构建期的临时目录 ACL 问题用仅存在于干净环境、构建后即删除的 `sitecustomize.py` 绕过
  （宿主怪癖，未改产品代码，运行期环境保持原样）。

## 3. 发布工件核对（tag 构建）

| 工件 | 大小 | SHA-256 | `twine check` |
|---|---|---|---|
| `toolseed-0.4.1-py3-none-any.whl` | 68,818 B | `2598d3d36216b8ad430b6cd8966770a6f2277b7aa367b6b3e8d7c5b1c0343d27` | PASSED |
| `toolseed-0.4.1.tar.gz` | 131,003 B | `267a7824cfca49475175d73a6b0cec33d34e0ea786c321c7886edf1d745b7331` | PASSED |

wheel 内容（22 条目）：9 个 `toolseed/core/*.py`、`toolseed/adapters/*`、`toolseed/mcp_server.py`、
`toolseed/skill/SKILL.md`、dist-info（含两个 console script：`toolseed`、`toolseed-mcp`）。
sdist（57 条目）含 README 与 Skill；**不含 `docs/`**（与 `v0.4.0` 一致，属既有打包特征，
不阻塞 Git 安装路径，已写入已知限制）。

## 4. 最终变更清单（本轮）

| 变更 | 位置 | 状态 |
|---|---|---|
| `version = "0.4.0"` → `"0.4.1"` | `pyproject.toml` | 已提交 `5786f47`（本地） |
| 附注标签 `v0.4.1` | 本地 tag → `5786f47` | 已创建，**未推送** |
| 产品代码 / Schema / 四工具协议 / Skill 语义 | — | **未改动** |
| 临时日志、凭据、本地数据库 | — | 未进入提交（`.test-data-*/`、`.toolseed/` 已被 .gitignore 忽略） |

发布材料（未跟踪，仅供人工取用）：
[Release Notes](RELEASE-NOTES.md)、[安装前提与限制](INSTALL-AND-LIMITS.md)、
以及本报告。

## 5. 等待人工确认的操作

确认后需由人工执行（每一步都会改变远端状态）：

1. `git push origin develop` —— 推送 3 个 Alpha 提交 + 版本提交；
2. `git push origin v0.4.1` —— 推送 tag，触发 `.github/workflows/release.yml`（构建 sdist/wheel、
   `twine check`、`SHA256SUMS`、创建 GitHub Release）；
3. GitHub Release 正文使用 [Release Notes](RELEASE-NOTES.md)（工作流默认 `--generate-notes`，
   可改为粘贴该文件内容）；
4. **不发布 PyPI**（本轮不申请该操作）。

## 6. 状态

- 已完成：版本核对与定版依据、干净环境从 Tag 安装验证、发布工件与内容核对、发布材料准备。
- 未完成且需人工：推送分支与 tag、创建 GitHub Release、（可选）后续再评估 PyPI。
- 未做：未改产品代码、未改 Core/Schema/四工具协议、未重跑整套质量门禁或 A/B 实验、
  未提交任何临时数据或凭据。
