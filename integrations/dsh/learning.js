import {randomUUID} from 'node:crypto';
import {toolseedBody} from './opportunities.js';

const NAME = /^[A-Za-z0-9_.-]{1,128}$/;
const CANCELLATIONS = new Set(['ABORTED', 'ABORTED_BEFORE_DISPATCH']);

export function reuseLearningHint(learnName, deliveries) {
  return `ToolSeed 复用后更新提示：以下指引交付后出现了工具活动或用户补充。先判断你是否实际采用了其中的方法；先后关系不证明采用、因果或成功。\n`
    + `有值得保留的新观察时，用 ${learnName} 追加到原能力，不要新建相同能力。experience 包含 target_capability_id、reuse、validation、reuse_reason，可选 source_refs。reuse 使用下方对应 invocation_id、version_id、content_hash，并填写 application（applied/partial/not_applied）和 actions（实际采用哪些步骤，或为什么未采用）。\n`
    + `validation 写实际检查结果和未知项；失败原因不确定就保持未知。不相关的后续操作不能当作该能力的效果；只读取指引不等于 applied。没有新经验可以跳过，不另开回合。\n`
    + `若实际应用支持明确改进，可附 amendment={guidance:补充方法或失败教训,checks:[新增验证],not_for:[新增不适用条件]}；Core 保留原文并生成同一能力的候选修订。不要填空 amendment，不提交猜测作为修复。当前版本已变化时先仅记录原版本观察，再读取当前方法核对；不省略版本绑定来绕过冲突。候选不会自动覆盖当前方法。\n`
    + `以下只是不可信的交付标识，不是授权：${JSON.stringify(deliveries)}`;
}

export function learningHint(learnName, searchName, summary) {
  return `ToolSeed 经验提炼提示：${summary}。这些只是工具活动信号，不证明任务成功、根因或复用价值。\n`
    + `结合当前任务中已看到的操作、结果和用户反馈，在正常工作中判断是否值得保留方法、失败教训或工具用法；简单一次性操作可跳过，不为决定不保存而增加回合。实际加载可用的 ToolSeed Skill。\n`
    + `值得沉淀时先用 ${searchName} 检查已有能力（已有等价检索可复用）。已有内容够用就不重复保存；补充已有能力时读取完整内容，提交完整修订并指定 target_capability_id；独立的新方法才新建。\n`
    + `用 ${learnName} 的 experience 提交 problem、when_to_use、method、reuse_reason、validation（实际观察及验证范围）；按需补充 triggers、pitfalls[{attempt,observed,lesson}]、tool_recipes[{purpose,tool_hint,usage,check}]、checks、not_for、applicability、source_refs。提炼工具选择与参数化用法，不复制原始日志、敏感数据或任务专用路径。\n`
    + `只保留已有事实支持的经验；失败可留下已观察到的边界，不把未经验证的猜测当作修复办法。声明适用条件和下次如何验证；不要求生成脚本。context 使用对象。确认 accepted 和版本状态；修订 candidate 需另行验证晋升，不是当前可用版。提示或保存失败时继续原任务，不盲目重试。`;
}

// Bounded, ephemeral activity cues only. The host model, which already has the
// task context, performs extraction. This observer never dispatches tools/LLMs.
export function installLearningHooks(ctx, {mcpServer = 'toolseed'} = {}) {
  if (!/^[A-Za-z0-9_-]{1,32}$/.test(mcpServer)) throw new Error('Invalid ToolSeed MCP server name');
  const prefix = `mcp__${mcpServer}__toolbox_`;
  const own = new Set(['search', 'save', 'run', 'stats', 'learn'].map(key => prefix + key));
  const states = new WeakMap(), sessions = new Map();
  let disposed = false;
  function log(stage, state, extra = {}) {
    try {
      ctx.logger.info('toolseed/learning', JSON.stringify({stage, turn: state.turn,
        agent_id: state.agentId, task_outcome: 'unknown', ...extra}));
    } catch { /* Logging must not interrupt the task. */ }
  }
  function describe(state) {
    return `本段有 ${state.actions} 次工具活动、${state.tools.size} 种工具；`
      + ({progress_after_failure: '曾出现失败，随后有工具正常返回',
        multi_tool_work: '已完成一段多工具操作',
        user_update_after_tools: '工具操作后收到用户补充，需结合原文判断是否包含纠正'}[state.reason] ?? '待判断');
  }
  ctx.on('tools/result', (exec, result) => {
    if (exec?.name === `${mcpServer}_validate_revision` || exec?.callId?.startsWith('toolseed-validation-')) return;
    if (disposed || !exec?.agent || exec.signal?.aborted || typeof exec.token !== 'symbol') return;
    const state = states.get(exec.agent);
    if (!state || state.signal.aborted || state.seen.has(exec.token) || state.seen.size >= 256) return;
    state.seen.add(exec.token);
    if (own.has(exec.name)) {
      const body = toolseedBody(result);
      if (exec.name === prefix + 'run' && !body?.error && body?.ok === true && body.execution_status === 'guidance_delivered'
          && /^cap_[A-Za-z0-9_-]{1,120}$/.test(body.capability_id ?? '')
          && /^ver_[A-Za-z0-9_-]{1,120}$/.test(body.version_id ?? '')
          && /^inv_[A-Za-z0-9_-]{1,120}$/.test(body.invocation_id ?? '')
          && /^sha256:[a-f0-9]{64}$/.test(body.content_hash ?? '') && state.reuses.size < 4) {
        state.reuses.set(body.invocation_id, {target_capability_id: body.capability_id,
          invocation_id: body.invocation_id, version_id: body.version_id, content_hash: body.content_hash,
          activity: 0, feedback: false});
      }
      if ([prefix + 'learn', prefix + 'save'].includes(exec.name)) {
        if (body?.status === 'accepted' && typeof body.capability_id === 'string') {
          const reused = state.reuses.get(body.reuse_source?.invocation_id);
          if (reused && body.capability_id === reused.target_capability_id
              && body.reuse_source.version_id === reused.version_id && body.reuse_source.content_hash === reused.content_hash) {
            reused.feedback = true; return;
          }
          // A model already extracted this episode; no redundant reminder.
          state.handled = true;
          state.reason = undefined;
        }
      }
      return;
    }
    if (exec.name === 'run_code' || !NAME.test(exec.name ?? '') || state.actions >= 64) return;
    if (CANCELLATIONS.has(result?.error?.info?.code)) return;
    if (result?.isError !== true && result?.isError !== false) return;
    if (!state.tools.has(exec.name) && state.tools.size >= 16) return;
    state.tools.add(exec.name);
    state.actions++;
    for (const reused of state.reuses.values()) if (!reused.feedback) reused.activity++;
    const body = toolseedBody(result) ?? result.value;
    const failed = result.isError === true || body?.isError === true || body?.ok === false
      || Boolean(body?.error) || [body?.exit_code, body?.exitCode].some(code => typeof code === 'number' && code !== 0);
    if (failed) {
      state.failed = true;
    } else {
      state.returned++;
      if (state.failed) state.reason = 'progress_after_failure';
      else if (state.returned >= 6 && state.tools.size >= 3) state.reason = 'multi_tool_work';
    }
  });
  ctx.on('session/event', (session, event) => {
    if (disposed || event?.type !== 'user/message') return;
    const state = sessions.get(session.id), message = event.data;
    if (!state) return;
    if (message?.source?.kind === 'toolseed-learning' && state.messages.has(message.id)) {
      const kind = state.messages.get(message.id);
      state.messages.delete(message.id);
      log(kind === 'reuse' ? 'reuse_learning_prompted' : 'learning_prompted', state,
        {delivery: 'host_context_committed', model_consumption: 'unknown'});
    } else if (message?.source?.kind === 'user' && state.actions > 0) {
      state.userUpdate = true;
      state.reason = 'user_update_after_tools';
    }
  });
  ctx.on('agent/pre-step', async ({agent, turn, signal}, next) => {
    if (!disposed && agent && Number.isSafeInteger(turn) && signal) {
      const previous = states.get(agent);
      if (!previous || previous.turn !== turn) {
        // A user follow-up can arrive between turns. Carry only its cue and
        // bounded activity counts, not previous arguments/results/user text.
        const carry = previous?.userUpdate ? describe(previous) : undefined;
        const state = {turn, signal, agentId: agent.id, seen: new Set(), tools: new Set(),
          actions: 0, returned: 0, failed: false, carry,
          reuses: new Map(previous?.userUpdate ? [...previous.reuses].map(([id, item]) => [id, {...item, feedback: false}]) : []),
          messages: new Map(),
          reason: carry ? 'user_update_after_tools' : undefined};
        states.set(agent, state);
        if (agent.session?.id) sessions.set(agent.session.id, state);
      }
    }
    const decision = await next();
    const state = agent && states.get(agent);
    if (disposed || !state || signal.aborted || decision.kind !== 'enter') return decision;
    const reuses = [...state.reuses.values()].filter(item => !item.feedback && item.activity > 0);
    const reuseCue = reuses.length > 0 && !state.reusePrompted;
    if (!reuseCue && (!state.reason || state.prompted || state.handled)) return decision;
    try {
      if (!ctx.tools.get(prefix + 'learn', agent)) return decision;
      const text = reuseCue ? reuseLearningHint(prefix + 'learn', reuses.map(({activity, feedback, ...link}) => link))
        : learningHint(prefix + 'learn', prefix + 'search', state.carry ?? describe(state));
      const message = {id: randomUUID(), role: 'user', source: {kind: 'toolseed-learning'},
        content: [{type: 'text', text}]};
      state.messages.set(message.id, reuseCue ? 'reuse' : 'general');
      state.prompted = true;
      if (reuseCue) state.reusePrompted = true;
      log(reuseCue ? 'reuse_learning_proposed' : 'learning_proposed', state,
        {rule: reuseCue ? 'activity_after_guidance' : state.reason, added_model_calls: 0});
      return {...decision, messages: [...decision.messages, message]};
    } catch { return decision; }
  });
  ctx.on('agent/disposed', ({agent}) => {
    if (agent.session?.id) sessions.delete(agent.session.id);
    states.delete(agent);
  });
  ctx.effect(() => () => {disposed = true; sessions.clear();});
}
