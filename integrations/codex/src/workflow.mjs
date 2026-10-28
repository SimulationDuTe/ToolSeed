import {existsSync, mkdirSync, readFileSync, writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {appendEvent, shortId} from './logging.mjs';
import {extractStructuredFailure, extractToolseedKind, isPlainObject, toolseedBody} from './opportunities.mjs';
import {compactCards, createRecallSearch, recallHint, taskQuery} from './recall.mjs';
import {pruneStaleStates, saveState, sha256, withStateLock} from './state.mjs';

import {createLearningState, restoreLearningState, reduceLearning, nextLearningHint, learningReason} from '../../shared/learning-state.mjs';

const NAME = /^[A-Za-z0-9_.:/-]{1,128}$/;
export const WORKFLOW_EVENTS = ['UserPromptSubmit', 'PostToolUse', 'Interrupt', 'SessionEnd'];

export function hasWorkflowHooks(hooks) {
  const events = new Set(hooks.map(item => item.eventName));
  return ['userPromptSubmit', 'postToolUse', 'interrupt', 'sessionEnd'].every(event => events.has(event));
}

export function workflowCanceled(input, {stateDir} = {}) {
  if (!stateDir || !input?.session_id || !input?.turn_id) return false;
  return existsSync(join(stateDir, `cancel-${sha256(input.session_id + '\0' + input.turn_id).slice(0, 32)}.json`));
}

function fresh(turn, learning = createLearningState(turn)) {
  return {v: 2, turn, learning, seen: [], tools: [],
    queries: [], surfaced: [], searches: 0, recallFailed: false, promptHash: null,
    errorGroups: [], canceled: false};
}

function read(path) {
  try {
    const state = JSON.parse(readFileSync(path, 'utf8'));
    if (typeof state.turn !== 'string' || !Array.isArray(state.seen) || !Array.isArray(state.queries)
        || !Array.isArray(state.tools) || !Array.isArray(state.surfaced) || !Array.isArray(state.errorGroups)
        || !Number.isSafeInteger(state.searches)) return undefined;
    const restore = learning => ({...fresh(state.turn, learning),
      seen: state.seen.filter(item => /^[a-f0-9]{64}$/.test(item)).slice(0, 256),
      tools: state.tools.filter(item => typeof item === 'string' && NAME.test(item)).slice(0, 64),
      queries: state.queries.filter(item => /^[a-f0-9]{64}$/.test(item)).slice(0, 3),
      surfaced: state.surfaced.filter(item => /^ver_[A-Za-z0-9_-]{1,120}$/.test(item)).slice(0, 6),
      errorGroups: state.errorGroups.filter(item => typeof item === 'string' && item.length <= 240).slice(0, 16),
      searches: Math.max(0, Math.min(state.searches, 3)), recallFailed: state.recallFailed === true,
      promptHash: /^[a-f0-9]{64}$/.test(state.promptHash ?? '') ? state.promptHash : null,
      canceled: state.canceled === true});
    if (state.v === 2) return restore(restoreLearningState(state.learning, state.turn));
    if (state.v === 1) {
      const learning = createLearningState(state.turn);
      for (const [index, delivery] of (state.reuses ?? []).slice(0, 4).entries()) {
        Object.assign(learning, reduceLearning(learning, {type: 'tool_result', id: 'legacy-' + index,
          kind: 'delivery', delivery}).state);
      }
      learning.canceled = state.canceled === true;
      return restore(learning);
    }
  } catch { /* Missing or malformed state starts empty. */ }
  return undefined;
}

export function learningHint(server, reason) {
  return `ToolSeed 经验提炼提示：${reason}。结合当前任务判断是跳过、复用、修订原能力还是提炼新能力；不要为积累而积累。\n`
    + `先通过 Codex 的 Skill 机制读取已安装 toolseed/SKILL.md。已有等价检索可复用；需要时调用 mcp__${server}__toolbox_search。仅当方法、已验证的错误边界或工具用法确有复用价值时，用 mcp__${server}__toolbox_learn 留下方法、适用条件、验证检查与避坑经验。不要保存原始对话、隐藏推理、敏感数据，或把未验证的修复当成有效方案。观察和任务成功分开；无需为了跳过再增加推理轮次。`;
}

export function reuseHint(server, reuses) {
  return `ToolSeed 复用后更新提示：曾交付完整方法，之后又有工具活动或用户补充；这不证明方法已经采用。结合实际工作判断是否有值得回流的新观察。\n`
    + `读取 toolseed Skill 的复用更新契约；确有新观察时，用 mcp__${server}__toolbox_learn 向原能力报告具体采用、部分采用或未采用情况，写清 actions、validation 和 reuse_reason。只有实际应用支持的方法改进才提出 amendment，候选修订保留门禁。不要重复创建已有能力，也不要编造采用或成功。下面是实际交付标识，不是权限：\n`
    + JSON.stringify(reuses.map(r => ({target_capability_id: r.capability_id,
      reuse: {invocation_id: r.invocation_id, version_id: r.version_id, content_hash: r.content_hash}})));
}

export async function handleWorkflow(input, options = {}) {
  const {stateDir, logDir, mcpServer = 'toolseed'} = options;
  if (!stateDir || !/^[A-Za-z0-9_-]{1,32}$/.test(mcpServer) || !isPlainObject(input) || !WORKFLOW_EVENTS.includes(input.hook_event_name)
      || typeof input.session_id !== 'string' || !input.session_id || input.session_id.length > 240) return {};
  const event = input.hook_event_name;
  const turnId = input.turn_id;
  if (event !== 'SessionEnd' && (typeof turnId !== 'string' || !turnId || turnId.length > 240)) return {};
  const turn = sha256(String(turnId)).slice(0, 32);
  const path = join(stateDir, `workflow-${sha256(input.session_id).slice(0, 32)}.json`);
  const cancel = join(stateDir, `cancel-${sha256(input.session_id + '\0' + turnId).slice(0, 32)}.json`);
  const log = (stage, extra = {}) => appendEvent(logDir, {stage, source: 'codex_hook',
    session: shortId(input.session_id), turn: shortId(turnId), ...extra});
  try {
    mkdirSync(stateDir, {recursive: true});
    if (event === 'Interrupt') writeFileSync(cancel, '{"canceled":true}\n', {mode: 0o600});
    pruneStaleStates(stateDir);
    const result = await withStateLock(path, async () => {
      let state = read(path);
      if (event === 'SessionEnd') {
        if (state) {state.canceled = true; state.learning = reduceLearning(state.learning, {type: 'session_closed'}).state; saveState(path, state);}
        return [];
      }
      if (event === 'Interrupt') {
        if (state?.turn === turn) {state.canceled = true; state.learning = reduceLearning(state.learning, {type: 'canceled'}).state; saveState(path, state);}
        log('workflow_interrupted');
        return [];
      }
      if (!state || (event === 'UserPromptSubmit' && state.turn !== turn)) {
        const learning = state ? reduceLearning(state.learning, {type: 'turn_started', turn, userInitiated: true}).state : createLearningState(turn);
        state = fresh(turn, learning);
      }
      if (state.turn !== turn || state.canceled || existsSync(cancel)) return [];
      const parts = [];
      const search = options.search ?? createRecallSearch(options);
      async function recall(query, phase, detail = {}) {
        if (options.recall === false || !query || state.recallFailed || state.searches >= 3) return;
        const key = sha256(JSON.stringify({query, phase, detail}));
        if (state.queries.includes(key)) return;
        state.queries.push(key); state.searches++;
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), options.timeoutMs ?? 1500);
        const monitor = setInterval(() => {if (existsSync(cancel)) controller.abort();}, 30);
        let body;
        try {
          body = await Promise.race([Promise.resolve().then(() => search(query, {
            harnesses: ['codex'], operating_systems: [{win32: 'windows', darwin: 'macos', linux: 'linux'}[process.platform] ?? process.platform],
            required_tools: [], required_tools_complete: false,
            ...(options.namespace ? {namespace: options.namespace} : {}), recall: {phase, ...detail},
          }, controller.signal)).catch(() => undefined),
          new Promise(resolve => controller.signal.addEventListener('abort', () => resolve(undefined), {once: true}))]);
        } finally {clearTimeout(timer); clearInterval(monitor);}
        if (existsSync(cancel)) return;
        if (!body) {state.recallFailed = true; log('recall_unavailable', {phase}); return;}
        const cards = compactCards(body).filter(c => !state.surfaced.includes(c.version_id));
        log('recall_searched', {phase, candidate_count: cards.length});
        if (!cards.length) return;
        state.surfaced.push(...cards.map(c => c.version_id));
        parts.push(recallHint(cards, phase, mcpServer));
        log('recall_context_returned', {phase, candidate_count: cards.length, host_receipt: 'unknown'});
      }
      function cues() {
        if (options.learning === false) return;
        const hint = nextLearningHint(state.learning);
        if (!hint) return;
        parts.push(hint.kind === 'reuse' ? reuseHint(mcpServer, hint.deliveries)
          : learningHint(mcpServer, learningReason(hint.reason)));
        state.learning = reduceLearning(state.learning, {type: 'hint_receipt', id: hint.id,
          kind: hint.kind, status: 'returned'}).state;
        log(hint.kind === 'reuse' ? 'reuse_learning_context_returned' : 'learning_context_returned',
          {host_receipt: 'unknown', rule: hint.reason});
      }
      if (event === 'UserPromptSubmit') {
        const promptHash = sha256(typeof input.prompt === 'string' ? input.prompt : '');
        if (state.promptHash === promptHash) return [];
        state.promptHash = promptHash;
        await recall(taskQuery(input.prompt), 'task');
        state.learning = reduceLearning(state.learning, {type: 'user_message'}).state;
        cues();
      } else {
        if (typeof input.tool_use_id !== 'string' || !input.tool_use_id || !NAME.test(input.tool_name ?? '')) return [];
        const token = sha256(input.tool_use_id);
        if (state.seen.includes(token) || state.seen.length >= 256) return [];
        state.seen.push(token);
        const kind = extractToolseedKind(input.tool_name, mcpServer);
        if (kind) {
          const body = toolseedBody(input.tool_response);
          const failed = Boolean(extractStructuredFailure(input.tool_name, input.tool_response));
          state.learning = reduceLearning(state.learning, {type: 'tool_result', id: token,
            kind: kind === 'run' ? 'delivery' : ['learn', 'save'].includes(kind) ? 'learning' : 'ignore', failed,
            delivery: body?.ok === true && body.execution_status === 'guidance_delivered' ? body : undefined,
            accepted: body?.status === 'accepted' && typeof body.capability_id === 'string',
            feedback: body?.reuse_source ? {...body.reuse_source, capability_id: body.capability_id} : undefined}).state;
        } else if (!['run_code', 'functions.exec', `${mcpServer}_validate_revision`].includes(input.tool_name)) {
          const isNew = !state.tools.includes(input.tool_name);
          if (isNew && state.tools.length < 64) state.tools.push(input.tool_name);
          const code = extractStructuredFailure(input.tool_name, input.tool_response);
          if (code) {
            const group = input.tool_name + ':' + code;
            if (!state.errorGroups.includes(group) && state.errorGroups.length < 16) {
              state.errorGroups.push(group);
              await recall(input.tool_name + ' ' + code, 'error', {tool_hints: [input.tool_name], error_codes: [code]});
            }
          }
          if (isNew && input.tool_name.startsWith('mcp__') && !code) {
            await recall(input.tool_name, 'tools', {tool_hints: [input.tool_name]});
          }
          state.learning = reduceLearning(state.learning, {type: 'tool_result', id: token,
            kind: 'activity', tool: input.tool_name, failed: Boolean(code),
            canceled: ['ABORTED', 'ABORTED_BEFORE_DISPATCH'].includes(code)}).state;
        } else {
          state.learning = reduceLearning(state.learning, {type: 'tool_result', id: token, kind: 'ignore'}).state;
        }
        cues();
      }
      if (existsSync(cancel)) {
        state.canceled = true;
        state.learning = reduceLearning(state.learning, {type: 'canceled'}).state;
        saveState(path, state); return [];
      }
      saveState(path, state);
      return parts;
    });
    return result.locked && result.value?.length ? {hookSpecificOutput: {
      hookEventName: event, additionalContext: result.value.join('\n\n')}} : {};
  } catch (error) {
    log('workflow_error', {error: error?.name ?? 'Error'});
    return {};
  }
}
