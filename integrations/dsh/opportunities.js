import {randomUUID} from 'node:crypto';
import {createOpportunityDiagnostics} from './opportunity-diagnostics.js';

export const FAILURE_THRESHOLD = 3;
const MAX_EXECUTIONS = 256;
const MAX_GROUPS = 16;
const CODE = /^[A-Z][A-Z0-9_]{0,79}$/;
const NAME = /^[A-Za-z0-9_-]{1,128}$/;
const CANCELLATIONS = new Set(['ABORTED', 'ABORTED_BEFORE_DISPATCH']);

export function opportunityHint(searchName, saveName) {
  return `ToolSeed 机会提示（L1，非任务结论）：本回合已观察到同一工具与结构化错误码的 3 次不同调用失败，可能存在重复阻塞。\n`
    + `在当前任务中实际加载适用的宿主 Skill 和可用的 ToolSeed Skill；不能只提及名称。若已有等价检索且上下文未变，复用结果；否则用 ${searchName} 做一次简短检索，query 根据当前问题填写，context 必须为对象或省略。\n`
    + `检查候选的适用条件、权限、验证证据和限制；命中或 ready 不证明适用。只在适用且安全时交付并实际采用指引，不自动执行或扩大权限。无匹配、工具不可用或检索/保存失败时继续原任务，不盲目重试。\n`
    + `解决方案经实际验证且有明确复用价值后，才按已加载的契约调用 ${saveName} 并确认返回；可选择不保存。保存、指引交付、实际采用、任务成功是不同阶段；缺失证据保持未知，工具失败不等于任务失败。`;
}

// The installed DSH MCP adapter returns {content, structuredContent?} as its
// canonical value. Inspect only this configured server's bounded JSON envelope;
// never retain arguments, error messages, prompts, procedure bodies or results.
function toolseedBody(result) {
  if (result?.isError !== false) return undefined;
  const value = result.value;
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
  if (value.structuredContent && typeof value.structuredContent === 'object') {
    return value.structuredContent;
  }
  if (!Array.isArray(value.content) || value.content.length !== 1) return undefined;
  const block = value.content[0];
  if (block?.type !== 'text' || typeof block.text !== 'string' || block.text.length > 65536) return undefined;
  try {
    const body = JSON.parse(block.text);
    return body && typeof body === 'object' && !Array.isArray(body) ? body : undefined;
  } catch { return undefined; }
}

/** DSH 0.2.1-rc.2 public events only; no Core writes, tool dispatch or LLM calls. */
export function installOpportunityHooks(ctx, {mcpServer = 'toolseed', opportunityDiagnostics = false} = {}) {
  // These clean, short names do not enter DSH's hashed-name normalization path.
  if (!/^[A-Za-z0-9_-]{1,32}$/.test(mcpServer)) throw new Error('Invalid ToolSeed MCP server name');
  const names = Object.fromEntries(['search', 'save', 'run', 'stats'].map(
    key => [key, `mcp__${mcpServer}__toolbox_${key}`]));
  const states = new WeakMap();
  // Cordis may trace Session objects through different scoped proxies. Correlate
  // on the public stable Session id, not JavaScript wrapper identity.
  const sessions = new Map();
  let disposed = false;
  const hint = opportunityHint(names.search, names.save);
  const diagnostics = createOpportunityDiagnostics(ctx.logger, {enabled: opportunityDiagnostics});
  function log(stage, state, extra = {}) {
    if (diagnostics.enabled) { diagnostics.lifecycle(stage, state, extra); return; }
    try {
      ctx.logger.info('toolseed/opportunity', JSON.stringify({
        stage, time: new Date().toISOString(), source: 'dsh', turn: state.turn,
        opportunity_id: state.opportunityId ?? null,
        correlation: 'same_agent_turn', agent_id: state.agentId,
        adoption: 'unknown', task_outcome: 'unknown', ...extra,
      }));
    } catch { /* Observability failure must never block the user's task. */ }
  }
  function observeToolseed(exec, result, state) {
    const kind = Object.keys(names).find(key => names[key] === exec.name);
    if (!kind) return false;
    if (kind === 'stats') return true;
    const body = toolseedBody(result);
    const failed = result?.isError === true || Boolean(body?.error);
    const links = {};
    for (const key of ['capability_id', 'version_id', 'invocation_id']) {
      if (typeof body?.[key] === 'string' && /^(cap|ver|inv)_[A-Za-z0-9_-]{1,120}$/.test(body[key])) {
        links[key] = body[key];
      }
    }
    if (kind === 'search') {
      log(failed ? 'search_failed' : Array.isArray(body?.results) ? 'search_completed' : 'search_result_unknown', state,
        Array.isArray(body?.results) ? {candidate_count: body.results.length} : {});
      // A post-signal search in the same turn already supplied the opportunity.
      // This does not assert its query was relevant, or that any hit was adopted.
      if (state.opportunityId) state.searchObserved = true;
    } else if (kind === 'save') {
      const stored = !failed && body?.status === 'accepted'
        && typeof body.capability_id === 'string' && typeof body.version_id === 'string';
      log(failed ? 'save_failed' : stored ? (body.duplicate === true ? 'existing_version_returned' : 'capability_saved') : 'save_result_unknown', state, links);
    } else {
      log(failed ? 'delivery_failed' : body?.execution_status === 'guidance_delivered'
        ? 'guidance_delivered' : 'delivery_result_unknown', state, links);
    }
    return true;
  }

  ctx.on('tools/result', (exec, result) => {
    if (disposed) return;
    if (!exec?.agent) { diagnostics.tool(exec, result, undefined, 'no_agent'); return; }
    if (exec.signal?.aborted) { diagnostics.tool(exec, result, states.get(exec.agent), 'execution_cancelled'); return; }
    const state = states.get(exec.agent);
    if (!state) { diagnostics.tool(exec, result, state, 'no_turn_state'); return; }
    if (state.signal.aborted) { diagnostics.tool(exec, result, state, 'turn_cancelled'); return; }
    if (typeof exec.token !== 'symbol') { diagnostics.tool(exec, result, state, 'token_not_symbol'); return; }
    if (state.seen.has(exec.token)) { diagnostics.tool(exec, result, state, 'duplicate_token'); return; }
    // Bound memory even on pathological turns; stop observing at the cap rather
    // than evicting tokens and treating a repeated notification as a new call.
    if (state.seen.size >= MAX_EXECUTIONS) { diagnostics.tool(exec, result, state, 'execution_limit'); return; }
    state.seen.add(exec.token);
    if (observeToolseed(exec, result, state)) { diagnostics.tool(exec, result, state, 'toolseed_tool'); return; }
    // No parsing of free-text errors, shell output, arguments or reasoning.
    // The outer PTC transport is not another independent blocker.
    const code = result?.error?.info?.code;
    if (result?.isError !== true) { diagnostics.tool(exec, result, state, 'not_tool_error'); return; }
    if (exec.name === 'run_code') { diagnostics.tool(exec, result, state, 'ptc_transport'); return; }
    if (typeof exec.name !== 'string' || !NAME.test(exec.name)) { diagnostics.tool(exec, result, state, 'invalid_tool_name'); return; }
    if (typeof code !== 'string') { diagnostics.tool(exec, result, state, 'missing_or_nonstring_code'); return; }
    if (!CODE.test(code)) { diagnostics.tool(exec, result, state, 'invalid_code'); return; }
    if (CANCELLATIONS.has(code)) { diagnostics.tool(exec, result, state, 'cancel_code'); return; }
    if (state.opportunityId) { diagnostics.tool(exec, result, state, 'signal_already_detected'); return; }
    const key = `${exec.name}:${code}`;
    if (!state.groups.has(key) && state.groups.size >= MAX_GROUPS) { diagnostics.tool(exec, result, state, 'group_limit'); return; }
    const count = (state.groups.get(key) ?? 0) + 1;
    state.groups.set(key, count);
    diagnostics.tool(exec, result, state, 'counted', count);
    if (count !== FAILURE_THRESHOLD) return;
    state.opportunityId = randomUUID();
    log('signal_detected', state, {rule: 'repeated_structured_tool_failure', tier: 'L1', count,
      tool: exec.name, error_code: code});
  });

  ctx.on('agent/pre-step', async (payload, next) => {
    const {agent, turn, signal} = payload;
    if (!disposed && agent && Number.isSafeInteger(turn) && signal) {
      const previous = states.get(agent);
      if (!previous || previous.turn !== turn) {
        if (previous) diagnostics.endTurn(previous, 'next_turn');
        const state = {turn, signal, agentId: agent.id, seen: new Set(), groups: new Map()};
        states.set(agent, state);
        if (agent.session?.id) sessions.set(agent.session.id, state);
        diagnostics.bindTurn(agent, state);
      }
    }
    // Preserve other plugins' denial, messages, request-series flags and errors.
    diagnostics.step(agent, agent && states.get(agent), 'step_seen', 'awaiting_host_decision');
    let decision;
    try { decision = await next(); }
    catch (error) {
      diagnostics.step(agent, agent && states.get(agent), 'step_failed', 'host_policy_error');
      throw error;
    }
    const state = agent && states.get(agent);
    if (diagnostics.enabled) diagnostics.step(agent, state, 'step_decision', 'host_decision', decision.kind === 'enter');
    if (disposed) return decision;
    if (!state?.opportunityId) { diagnostics.step(agent, state, 'prompt_decision', 'no_signal'); return decision; }
    if (state.prompted) { diagnostics.step(agent, state, 'prompt_decision', 'already_proposed'); return decision; }
    if (state.searchObserved) { diagnostics.step(agent, state, 'prompt_decision', 'search_observed'); return decision; }
    if (signal.aborted) { diagnostics.step(agent, state, 'prompt_decision', 'turn_cancelled'); return decision; }
    if (decision.kind !== 'enter') { diagnostics.step(agent, state, 'prompt_decision', 'step_not_entered', false); return decision; }
    try {
      if (!ctx.tools.get(names.search, agent)) {
        diagnostics.step(agent, state, 'prompt_decision', 'search_tool_not_visible', true, false);
        if (!state.unavailable) log('prompt_unavailable', state, {reason: 'search_tool_not_visible'});
        state.unavailable = true;
        return decision;
      }
      diagnostics.step(agent, state, 'prompt_decision', 'eligible', true, true);
      const message = {id: randomUUID(), role: 'user', content: [{type: 'text', text: hint}],
        source: {kind: 'toolseed-opportunity'}};
      state.prompted = true;
      state.messageId = message.id;
      log('opportunity_proposed', state, {tier: 'L1', context_utf8_bytes: Buffer.byteLength(hint),
        context_characters: [...hint].length, token_count: 'unknown', added_model_calls: 0});
      return {...decision, messages: [...decision.messages, message]};
    } catch {
      log('prompt_unavailable', state, {reason: 'host_interface_unavailable'});
      return decision;
    }
  });
  // A pre-step proposal can still be rejected, cancelled or replaced by another
  // plugin. Only the host's committed message is evidence of admitted context;
  // it still does not prove the model consumed or followed the suggestion.
  ctx.on('session/event', (session, event) => {
    if (disposed || event?.type !== 'user/message') return;
    const state = sessions.get(session.id);
    const message = event.data;
    if (!state || state.committed || !state.messageId || message?.id !== state.messageId
        || message.source?.kind !== 'toolseed-opportunity') return;
    state.committed = true;
    log('opportunity_prompted', state, {message_id: message.id, session_seq: event.seq,
      delivery: 'host_context_committed', model_consumption: 'unknown'});
  });
  ctx.on('agent/disposed', ({agent}) => {
    const state = states.get(agent);
    if (state) diagnostics.endTurn(state, 'agent_disposed');
    if (agent.session?.id) sessions.delete(agent.session.id);
    states.delete(agent);
  });
  ctx.effect(() => () => {
    disposed = true;
    for (const state of sessions.values()) diagnostics.endTurn(state, 'plugin_unloaded');
    diagnostics.close();
    sessions.clear();
  });
}
