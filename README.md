# ToolSeed

**让 Agent 把经验变成能力，在合适的时候用起来。**

把任务中的有效方法、错误教训和工具用法，沉淀为带有适用条件与验证检查的能力。
下一次遇到相关问题，召回已有方法，交给宿主 Agent 应用，再把新经验补回原能力。

**解决问题 → 提炼经验 → 按需召回 → 实际应用 → 反馈改进**

- **有用才留**：由模型判断跳过、复用、修订或创建，避免重复积累。
- **积累方法**：保留怎么做、何时适用、踩过什么坑，以及如何验证。脚本是可选产物。
- **边用边改**：观察回到原能力；方法修订经过验证后再生效。

## 快速开始

需要 Python 3.11+。

```bash
python -m pip install --upgrade toolseed
```

接入宿主（使用其现有能力库目录）：

```bash
toolseed update codex --ref v0.5.0
# DSH 用户先完全退出 Desktop
toolseed update dsh --ref v0.5.0
```

选择自己的宿主执行一条命令，完成后新建 Codex 聊天或重新打开 DSH。
首次接入、路径配置与其他 MCP 客户端见 [安装说明](docs/UNIFIED-INSTALL.md)和[使用参考](docs/REFERENCE.md)。

## 已经能做什么

经验学习、主动召回、原能力反馈、候选修订，以及本地能力与活动查看。
提供 Codex / DSH 适配，通过 MCP 交付指引，实际操作与权限检查由宿主完成。

在两轮真实 DSH 模型任务中，观察到了自主提炼、跨会话召回、实际采用与反馈回流。
项目目前为 **Alpha**；案例与支持范围见[实测记录](benchmarks/results/dsh-experience-2026-10-27/REPORT.md)和
[Alpha 状态](docs/ALPHA-STATUS.md)。

## 了解更多

- [经验学习](docs/EXPERIENCE-LEARNING.md) · [主动召回](docs/PROACTIVE-RECALL.md) · [复用与修订](docs/REUSE-UPDATES.md)
- [接口与开发参考](docs/REFERENCE.md) · [完整升级](docs/FULL-UPDATE.md)
- [宣传演示素材](DEMO.md) · [版本发布](https://github.com/SimulationDuTe/ToolSeed/releases) · [PyPI](https://pypi.org/project/toolseed/)

## 许可证

[MIT](LICENSE)
