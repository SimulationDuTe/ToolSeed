// Canonical, host-independent learning rules. No IO, host calls or raw task data.
export const LEARNING_POLICY = Object.freeze({returns: 6, tools: 3, actions: 64,
  observedTools: 16, executions: 256, deliveries: 4});
const REF = {capability_id: /^cap_[A-Za-z0-9_-]{1,120}$/,
  version_id: /^ver_[A-Za-z0-9_-]{1,120}$/, invocation_id: /^inv_[A-Za-z0-9_-]{1,120}$/,
  content_hash: /^sha256:[a-f0-9]{64}$/};
const TOOL = /^[A-Za-z0-9_.:/-]{1,128}$/;

export function deliveryReference(value) {
  return value && Object.entries(REF).every(([key, pattern]) => pattern.test(value[key] ?? ''))
    ? Object.fromEntries(Object.keys(REF).map(key => [key, value[key]])) : undefined;
}

export function createLearningState(turn) {
  return {v: 1, turn: String(turn), seen: [], tools: [], actions: 0, returned: 0,
    sequence: 0, failureSequence: 0, reason: null, userUpdate: false,
    generalClosed: false, canceled: false, deliveries: [], closedInvocations: [], hints: {general: null, reuse: null}};
}

export function restoreLearningState(raw, turn) {
  const state = createLearningState(turn);
  if (raw?.v !== 1 || raw.turn !== state.turn || !Array.isArray(raw.seen) || !Array.isArray(raw.tools)
      || !Array.isArray(raw.deliveries) || !raw.hints) return state;
  state.seen = [...new Set(raw.seen.filter(item => typeof item === 'string' && item.length <= 240))].slice(0, LEARNING_POLICY.executions);
  state.tools = [...new Set(raw.tools.filter(item => typeof item === 'string' && TOOL.test(item)))].slice(0, LEARNING_POLICY.observedTools);
  for (const key of ['actions', 'returned', 'sequence', 'failureSequence']) {
    state[key] = Number.isSafeInteger(raw[key]) ? Math.max(0, Math.min(LEARNING_POLICY.actions, raw[key])) : 0;
  }
  state.reason = learningReason(raw.reason) ? raw.reason : null;
  for (const key of ['userUpdate', 'generalClosed', 'canceled']) state[key] = raw[key] === true;
  for (const item of raw.deliveries) {
    const ref = deliveryReference(item);
    if (ref && !state.deliveries.some(old => old.invocation_id === ref.invocation_id)
        && state.deliveries.length < LEARNING_POLICY.deliveries) state.deliveries.push({...ref,
      activity: Number.isSafeInteger(item.activity) ? Math.max(0, Math.min(item.activity, LEARNING_POLICY.actions)) : 0,
      userFeedback: item.userFeedback === true});
  }
  state.closedInvocations = (Array.isArray(raw.closedInvocations) ? raw.closedInvocations : [])
    .filter(item => REF.invocation_id.test(item)).slice(0, LEARNING_POLICY.executions);
  for (const kind of ['general', 'reuse']) {
    const hint = raw.hints[kind];
    if (hint?.id === state.turn + ':' + kind && ['proposed', 'returned', 'committed'].includes(hint.status)) {
      state.hints[kind] = {id: hint.id, status: hint.status};
    }
  }
  return state;
}

export function nextLearningHint(state) {
  if (state.canceled) return undefined;
  const deliveries = state.deliveries.filter(item => item.activity > 0 || item.userFeedback);
  if (deliveries.length && !state.hints.reuse) return {id: state.turn + ':reuse', kind: 'reuse',
    reason: deliveries.some(item => item.userFeedback) ? 'user_feedback_after_guidance' : 'activity_after_guidance',
    deliveries: deliveries.map(deliveryReference)};
  if (state.reason && !state.hints.general && !state.generalClosed) return {
    id: state.turn + ':general', kind: 'general', reason: state.reason, deliveries: []};
  return undefined;
}

export function reduceLearning(state, event) {
  // All state is JSON data; a reduction never mutates a host's prior snapshot.
  let next = structuredClone(state);
  if (event.type === 'turn_started') {
    if (String(event.turn) === state.turn) return {state: next};
    next = createLearningState(event.turn);
    if (!state.canceled && (state.userUpdate || event.userInitiated === true)) {
      next.deliveries = state.deliveries.slice(-LEARNING_POLICY.deliveries)
        .map(item => ({...item, userFeedback: true}));
      next.closedInvocations = state.closedInvocations.slice(-LEARNING_POLICY.executions);
      if (state.actions > 0) next.reason = 'user_update_after_tools';
    }
    return {state: next};
  }
  if (event.type === 'canceled' || event.type === 'session_closed') {
    next.canceled = true; next.deliveries = []; return {state: next};
  }
  if (state.canceled) return {state: next};
  if (event.type === 'user_message') {
    if (next.actions > 0 || next.deliveries.length) {
      next.userUpdate = true;
      if (next.actions > 0) next.reason = 'user_update_after_tools';
      next.deliveries.forEach(item => {item.userFeedback = true;});
    }
  } else if (event.type === 'hint_receipt') {
    const previous = next.hints[event.kind];
    if (!['general', 'reuse'].includes(event.kind) || event.id !== next.turn + ':' + event.kind) return {state: next};
    if (event.status === 'rejected' && previous?.status === 'proposed') next.hints[event.kind] = null;
    else if (['proposed', 'returned', 'committed'].includes(event.status)
        && (!previous || ({proposed: 1, returned: 2, committed: 3}[event.status]
          >= {proposed: 1, returned: 2, committed: 3}[previous.status]))) {
      next.hints[event.kind] = {id: event.id, status: event.status};
    }
  } else if (event.type === 'tool_result') {
    if (typeof event.id !== 'string' || !event.id || event.id.length > 240 || next.seen.includes(event.id)
        || next.seen.length >= LEARNING_POLICY.executions || event.canceled) return {state: next};
    next.seen.push(event.id);
    if (event.kind === 'delivery') {
      const ref = !event.failed && deliveryReference(event.delivery);
      if (ref && next.deliveries.length < LEARNING_POLICY.deliveries
          && !next.closedInvocations.includes(ref.invocation_id)
          && !next.deliveries.some(item => item.invocation_id === ref.invocation_id)) {
        next.deliveries.push({...ref, activity: 0, userFeedback: false});
      }
    } else if (event.kind === 'learning' && event.accepted === true && !event.failed) {
      if (event.feedback) {
        const ref = deliveryReference(event.feedback);
        if (ref) next.deliveries = next.deliveries.filter(item => {
          const matches = Object.keys(REF).every(key => item[key] === ref[key]);
          if (matches && !next.closedInvocations.includes(ref.invocation_id)) next.closedInvocations.push(ref.invocation_id);
          return !matches;
        });
      } else {next.generalClosed = true; next.reason = null;}
    } else if (event.kind === 'activity') {
      if (!TOOL.test(event.tool ?? '') || next.actions >= LEARNING_POLICY.actions
          || (!next.tools.includes(event.tool) && next.tools.length >= LEARNING_POLICY.observedTools)) return {state: next};
      if (!next.tools.includes(event.tool)) next.tools.push(event.tool);
      next.actions++; next.sequence++;
      next.deliveries.forEach(item => {item.activity = Math.min(LEARNING_POLICY.actions, item.activity + 1);});
      if (event.failed) next.failureSequence = next.sequence;
      else {
        next.returned++;
        if (next.failureSequence && next.sequence > next.failureSequence) next.reason = 'progress_after_failure';
        else if (next.returned >= LEARNING_POLICY.returns && next.tools.length >= LEARNING_POLICY.tools) next.reason = 'multi_tool_work';
      }
    }
  }
  return {state: next, effect: nextLearningHint(next)};
}

export function learningReason(reason) {
  return {progress_after_failure: '曾出现失败，随后有工具正常返回',
    multi_tool_work: '已完成一段多工具操作',
    user_update_after_tools: '工具操作后收到用户补充，需结合原文判断是否包含纠正'}[reason];
}
