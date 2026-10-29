# ToolSeed 宣传演示扫描入口

这份说明用于了解产品、编排演示和制作视频。先读本文，再按下方文件核对实现。
当前发布目标为 2026-10-29 的 v0.5.0，产品仍处于 Alpha 阶段；下载与安装以对应发布记录为准。

## 产品主线

**让 Agent 把值得重复利用的任务方法、错误教训和工具用法，变成下次用得上的能力。**

Agent 在执行任务时判断是否值得保留经验，选择跳过、复用、修订或创建。
能力包含方法、适用条件、不适用范围、错误教训和验证检查；脚本可以是任务产物，能力无需附带脚本。
后续遇到相关任务，宿主先取得少量候选；模型核对条件、读取完整方法，使用自己的工具执行，
再把有价值的使用观察回到原能力。方法需要改进时提出候选修订，经过验证再生效。

推荐围绕一个连续场景展示：

1. 任务 A 中遇到错误，Agent 排查并完成检查。
2. 提炼一张经验卡：问题、适用条件、方法、踩坑教训、复用检查。
3. 新任务 B 出现相关线索，召回候选；模型判断是否适用。
4. 读取完整方法，由宿主工具完成任务和验证。
5. 新观察回到原卡片；有改进时进入候选修订与验证流程。

可用旁白：**“解决一次，留下方法；下次遇见，在合适的时候用起来。”**

## 功能与实现对应

| 演示内容 | 主要实现或说明 |
| --- | --- |
| 方法、错误教训与工具用法入库 | `toolseed/core/learning.py`、`learning_service.py`、[经验学习](docs/EXPERIENCE-LEARNING.md) |
| 任务、结构化错误和工具线索触发召回 | `integrations/dsh/recall.js`、`integrations/codex/src/recall.mjs`、[主动召回](docs/PROACTIVE-RECALL.md) |
| 交付完整指引，供宿主应用 | `toolseed/core/delivery.py`、`toolseed/mcp_server.py` |
| 复用观察回到原能力，避免重复建卡 | `toolseed/core/reuse.py`、[复用后更新](docs/REUSE-UPDATES.md) |
| 修订候选经过检查后启用 | `toolseed/core/revisions.py`、[修订生效](docs/REVISION-ACTIVATION.md) |
| DSH 设置中的能力和活动页面 | `integrations/dsh/src/client.cjs`、`toolseed/ui_assets/` |
| Core、Skill 和适配器统一升级 | `toolseed/updater.py`、[完整升级](docs/FULL-UPDATE.md) |

五个公共 MCP 工具为 `toolbox_search`、`toolbox_save`、`toolbox_run`、`toolbox_stats`、`toolbox_learn`。
`toolbox_run` 交付方法，实际操作通过宿主 Agent 的工具完成。DSH 另有可选的原生修订验证工具；
两种宿主保留各自的权限与事件接入，不能把 DSH 专用工具画成 Codex 的既有界面。

## 可以引用的实测

[两轮真实模型任务记录](benchmarks/results/dsh-experience-2026-10-27/REPORT.md)
观察到：任务 A 自主提炼方法，任务 B 在新会话召回并实际采用，使用观察回到同一能力。
两项任务各通过 10 个外部检查，最终保留 1 个能力、1 个版本。
这是隔离的 DSH headless 修复任务，属于受控案例；两轮耗时不可直接当成复用提效百分比。
原始记录、[能力正文](benchmarks/results/dsh-experience-2026-10-27/capability.md)和
[结果摘要](benchmarks/results/dsh-experience-2026-10-27/result.json)可供核对。

2026-10-28 的 Python 442 项检查为 441 通过、1 项条件跳过；Node 157 项通过。
Codex 和 DSH 的隔离原生升级检查通过。Codex 的脚本驱动链路与安装自检，
不能描述成已证明真实模型会稳定主动学习；各项验证的日期和范围以对应记录为准。

## 画面材料

`docs/screenshots/toolseed-capabilities.png` 和 `toolseed-activity.png` 是历史隔离环境的真实面板截图。
其中卡片明确标记为“测试能力”，适合展示布局和操作入口。拍摄当前版本时请保留真实状态和标记；
用图形重现学习与复用流程时标注“流程示意”。原始截图中的测试卡不能被改称为真实业务成果。

展示重点放在经验卡、适用条件、召回、实际应用和反馈；测试总数、内部 ID、数据库 schema 和安装命令
可作为补充，不必占据主画面。工具活动计数和方法交付本身不能写成“任务成功”。

## 扫描范围与使用方式

源码扫描清单为 [scan.json](docs/demo/scan.json)。生成独立材料目录：

```powershell
python scripts/export_demo_context.py
```

将生成的 `demo-context/` 交给视频 AI，先读取其中的 `DEMO.md`，再读取 `SCAN-INDEX.json` 和相关源码。
输出是阅读材料，不是可运行发行包；导出包含所选源码、说明、案例摘要和上述两张截图，
不会复制能力库、运行环境、私有配置、原始会话或完整测试目录。已有输出目录不会被覆盖，
再次导出可用 `--output <新目录>`。索引记录基线 commit 和各文件哈希，方便核对材料来源。

如需直接扫描完整仓库，也应按同一清单选择文件；`.test-data/` 是历史验收资料，`.toolseed/` 是本地能力库
及安装状态，虚拟环境与缓存服务于运行和开发，均不作为宣传素材。

给视频 AI 的简短任务可写为：

> 先读取 DEMO.md 和 SCAN-INDEX.json，理解 ToolSeed 的真实能力与证据范围。
> 围绕“任务经验 → 能力卡 → 合适时机召回 → 宿主应用 → 反馈改进”编排宣传演示。
> 使用真实截图说明已有页面，用明确标注的示意动画解释内部流程；先提交分镜与旁白供审阅。
