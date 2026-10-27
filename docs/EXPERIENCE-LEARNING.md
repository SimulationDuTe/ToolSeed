# 从任务经验到可复用能力

2026-10-25，本地开发增量，尚未发布。新增 `toolbox_learn`；现有四个工具继续兼容。
这份文档补充 P0 的接口范围，不改变现有版本门禁和交付语义。

后续已加入[复用后更新](REUSE-UPDATES.md)：`toolbox_learn` 还可接收绑定交付记录的反馈，
仅追加观察，或向原能力提出增量修订，不要求重交整份方法。

本轮实现的路径是：**任务中的工具活动 → 宿主提示 → 宿主模型提炼 → 能力入库 → 后续检索与应用**。
Core 不另调模型，也不要求先产生脚本。模型负责判断哪些事实构成经验，以及是否值得保留。

## 能留下什么

`toolbox_learn(experience, context?)` 接受一个经验对象：

- 必填：`problem`、`when_to_use`、`method`、`reuse_reason`、`validation`。
- 可选：`triggers`（可识别的问题线索）、`pitfalls`（尝试/观察/教训）、
  `tool_recipes`（用途/工具线索/用法/检查）、`checks`（下次复用的验证办法）。
- 可选：`name`、`not_for`、`tags`、`applicability`、`source_refs`、`target_capability_id`。

方法、错误边界与工具用法整理为现有 `procedure`，全部参与内容检索。来源和这次验证观察作为
绑定版本哈希的 `experience_learned` 事件追加，同一方法换任务复用不会仅因来源改变而复制一份。
重复提交同一观察返回同一学习事件。搜索卡片和交付结果中的 `learning_summary` 给出最近的
模型观察，明确标注 `source_type=agent`，不会替代独立验证或写成任务成功。

```json
{
  "experience": {
    "problem": "导出的精灵 PNG 出现实色背景",
    "when_to_use": "编辑器看似透明，但交付文件的透明度未确认",
    "method": "检查原图 alpha；导出透明 PNG；重新打开导出文件并检查背景与主体像素。",
    "reuse_reason": "避免在后续精灵交付中重复把编辑器预览当成导出验证。",
    "validation": "已检查一次导出，背景 alpha 为零且主体完整；其他导出器尚未验证。",
    "pitfalls": [{
      "attempt": "仅查看编辑器棋盘格",
      "observed": "棋盘格可见，但导出文件仍有实色背景",
      "lesson": "验证必须覆盖实际导出文件"
    }],
    "checks": ["重新打开交付 PNG，检查背景 alpha 与主体完整性"],
    "not_for": ["不支持透明通道的格式"]
  },
  "context": {"task_id": "sprite-export-1", "harness": "dsh"}
}
```

也可通过 `toolseed learn '<JSON>'` 或 LocalAdapter 调用。完整字段上限由工具 schema 和
[随包 Skill](../toolseed/skill/SKILL.md) 提供。这里的 `validation` 是必要的实际观察说明，
Core 能校验结构，不能证明模型声明属实。

## 何时让模型想起提炼

DSH 插件新增默认启用的 `learning: true`，普通经验提炼在每回合正常获准的下一推理步骤中最多提示一次：

1. 工具失败后出现正常返回，提示模型判断是否已经形成有用教训。
2. 至少六次正常返回、涉及至少三种工具，提示检查是否形成可复用流程。
3. 工具操作后收到用户补充，提示结合原文判断是否包含应保留的纠正。

信号只说明活动发生，不认定恢复、因果或成功。插件不保存原始参数、输出或用户文字，只保留
有限的工具标识和计数；每段最多 64 次活动、16 种工具、256 个去重标识。用户补充线索可带入
同一 Agent 的下一回合；其他未处理线索在回合切换时丢弃，重启不恢复。不额外唤醒空闲 Agent，
因此任务结束后没有下一步骤时，仍需模型在结束前主动提炼。

模型在 **跳过、复用已有、修订已有、新建** 之间判断。保存前先检索，已有内容足够就不再存。
修订时提交完整方法并指定目标 ID；沿用候选验证晋升流程，不静默覆盖当前方法。
工具不可见、调用失败或没有值得保存的经验时继续原任务。

## 使用与边界

- MCP 服务需重启以发现第五个工具；DSH 插件重载后启用学习提示。面板与 MCP 使用同一数据目录。
- `learning: false` 关闭学习提示；同时设置 `opportunities: false` 才是仅保留管理面板。
- 随项目 Skill 已更新；已安装到用户目录的旧 Skill 需通过现有安装流程同步。本次未改用户配置。
- Codex 可以调用新工具；本轮自动学习提示接入 DSH。Codex 的观察器仅补充识别 `toolbox_learn`，
  不宣称已具有 DSH 的新触发机制。
- 后续已接入 DSH 的[主动召回](PROACTIVE-RECALL.md)，在任务开始、工具错误和工具线索变化时自动检索。
  语义检索、脚本附件及执行、跨会话未提炼经验队列仍未实现。
  实际复用继续走 `search → 检查适用条件 → run → 宿主实际应用`。

本轮验证涵盖经验保存、精确去重、来源追加、失败教训及工具用法检索、版本与适用条件门禁、
原子回滚、公开 MCP schema/stdio 及 DSH 事件提示。脚本驱动宿主测试只能证明接线可用，
不能证明真实模型会稳定提炼或主动采用。

本地结果：Python 335 项，334 通过、1 项按条件跳过（缺失 SDK 分支）；Node 76 项全部通过；
Ruff、Mypy（23 个源文件）与 Skill 校验通过。真实 DSH 0.2.1-rc.2 / MCP 集成中，脚本驱动
以 9 个步骤完成提炼入库和另一任务的检索、交付与示例应用；真实模型调用为零。
可用以下命令复跑这个隔离测试，数据库创建在 `tests/.data/learning-host-*`：

```powershell
$env:ELECTRON_RUN_AS_NODE = '1'
& 'F:/DeepSeek Harness/DeepSeek Harness.exe' --expose-internals `
  'F:/ToolSeed/integrations/dsh/test/host-learning.mjs' `
  'F:/DeepSeek Harness/resources/app.asar' 'F:/ToolSeed/.venv/Scripts/python.exe' | Out-String
exit $LASTEXITCODE
```
