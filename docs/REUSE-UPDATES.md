# 复用后的经验回流与能力修订

2026-10-25，本地开发增量，未发布。沿用 `toolbox_learn`，公共工具仍为五个。

后续增量已接上[宿主执行验证与修订生效](REVISION-ACTIVATION.md)：实际检查通过后启用新版，失败保留旧版和检查事实。

流程现在可以贯通：**召回已有方法 → 宿主实际应用 → 关联使用观察 → 补充原能力 → 后续任务看到新经验**。
宿主模型判断采用了什么、观察是否有价值、是否足以支持修订；插件只提供有交付标识的提醒。

## 两种更新

只有新观察时，追加到原能力的具体版本和交付记录，不创建能力或版本。
有实际应用支持的方法改进时，在原方法上补充步骤、失败教训、验证检查或不适用范围，创建
同一能力的候选修订。原文、已有限制和当前版本均保留；完整改写仍使用既有的完整定向修订入口。

```json
{
  "experience": {
    "target_capability_id": "cap_实际返回值",
    "reuse": {
      "invocation_id": "inv_实际返回值",
      "version_id": "ver_实际返回值",
      "content_hash": "sha256:实际返回值",
      "application": "applied",
      "actions": "采用了检查 alpha 与重新打开导出 PNG 的步骤。"
    },
    "validation": "背景 alpha 正确，但这次发现索引色输出丢失了部分颜色；仅验证了当前导出器。",
    "reuse_reason": "后续交付需要同时核对透明度与颜色模式。",
    "amendment": {
      "guidance": "导出后同时检查颜色模式及主体颜色，不只检查背景透明度。",
      "checks": ["核对输出颜色模式和主体颜色"],
      "not_for": ["未经验证的索引色导出"]
    }
  }
}
```

`target_capability_id` 与 `reuse` 中三个标识必须来自同一次 `toolbox_run`。
`application` 为 `applied` / `partial` / `not_applied`，`actions` 写具体采用情况或没有采用的原因。
`not_applied` 可以留观察，但不能提交声称经过应用验证的修订。没有新经验时可以不调用。

`amendment` 可省略；非空时只接受 `guidance`、`checks`、`not_for`。字段上限及恢复方法见
[随包 Skill](../toolseed/skill/SKILL.md)。修订内容仍经过既有内容扫描、大小限制及候选晋升门禁。

## 关联与后续复用

- Core 验证能力、版本、哈希与交付记录的对应关系；已知 task/session 冲突会拒绝。
- 观察追加为 `reuse_learned` 事件，绑定当时版本，来源固定为 `agent`；不写任务成功或独立验证。
- 相同反馈重试返回同一事件；同一增量修订在不同使用中再次提出时复用相同候选版本。
- 修订与反馈在同一事务中提交，反馈写入失败时不会遗留孤立修订。
- 当时使用的版本已不是当前版时，仍可记录历史观察；增量修订返回 `REUSE_VERSION_CHANGED`，
  需读取当前方法核对，不自动把旧建议接到新方法。
- Search/run 增加 `reuse_summary`，只展示该版本最近三次使用的模型观察，每次使用只展示最新一条。
  历史记录不删除；摘要有长度限制，并标明未经独立验证。主动召回卡片还会带最多两条简短观察。
- 尚未晋升的修订只提供候选标识与状态，不当成当前方法交付；含模糊高风险教学内容的观察保留在
  记录中，不直接进入复用摘要。记录可通过已有 evidence 管理入口查看。

确认返回的 `learning_action` 为 `observation_added` 或 `revision_proposed`，并检查
`learning_event_id`、`version_status`、`feedback_duplicate`。返回 `accepted` 仅表示记录成功。

## DSH 提醒如何工作

`learning: true` 下，观察到完整指引交付后，暂存最多四份交付标识。出现后续工具活动或用户补充时，
在下一正常获准步骤提示宿主判断是否有值得回流的经验。只读到方法不触发“已采用”结论，工具先后
关系也不自动归因；模型需填写真实的采用说明。反馈被接受后关闭对应提醒，不影响其他能力。

每回合最多一条普通学习提示和一条复用更新提示；复用提示可替代尚未发出的普通提示。没有额外
模型调用、强制任务结束回合或自动写库。用户补充可把有限交付标识带到同一 Agent 的下一回合；
其他回合切换、Agent 销毁或插件重载会清理临时状态。没有下一推理步骤时，模型可依据 Skill 主动回流。

需重启更新后的 MCP、重载 DSH 插件并同步新版 Skill。Codex 可直接调用同一学习接口；本轮事件提醒
接入 DSH。候选修订仍需现有验证晋升流程，不宣称已实现无人监督的自动晋升。

## 本轮验证范围

Python 覆盖关联校验、纯观察、增量修订、重复去重、旧版本冲突、后续摘要、事务回滚、生命周期及 MCP。
Node 覆盖交付与采用区分、多能力关联、提醒预算、用户补充、宿主拒绝、取消与召回摘要。
真实 DSH/MCP 测试使用隔离库和脚本驱动，跑通交付、示例应用、反馈修订与后续读取；真实模型调用为零。
它证明接线和数据行为可运行，不证明模型会稳定做出正确归因。

本地结果：Python 364 项（363 通过、1 项按条件跳过），Node 98 项通过；Ruff、Mypy
（25 个源文件）与 Skill 校验通过。真实 DSH/MCP 脚本驱动在 10 个步骤内完成学习、后续应用、
原能力候选修订及再次交付；真实模型调用为零。

复跑隔离宿主测试：

```powershell
$env:ELECTRON_RUN_AS_NODE = '1'
& 'F:/DeepSeek Harness/DeepSeek Harness.exe' --expose-internals `
  'F:/ToolSeed/integrations/dsh/test/host-learning.mjs' `
  'F:/DeepSeek Harness/resources/app.asar' 'F:/ToolSeed/.venv/Scripts/python.exe' | Out-String
exit $LASTEXITCODE
```
