import {existsSync, mkdirSync, readFileSync, writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {appendEvent, shortId} from './logging.mjs';
import {extractStructuredFailure, extractToolseedKind, isPlainObject, toolseedBody} from './opportunities.mjs';
import {compactCards, createRecallSearch, recallHint, taskQuery} from './recall.mjs';
import {pruneStaleStates, saveState, sha256, withStateLock} from './state.mjs';

const NAME = /^[A-Za-z0-9_.:/-]{1,128}$/;
const REF = {capability_id: /^cap_[A-Za-z0-9_-]{1,120}$/,
  version_id: /^ver_[A-Za-z0-9_-]{1,120}$/, invocation_id: /^inv_[A-Za-z0-9_-]{1,120}$/,
  content_hash: /^sha256:[a-f0-9]{64}$/};
export const WORKFLOW_EVENTS = ['UserPromptSubmit', 'PostToolUse', 'Interrupt', 'SessionEnd'];

export function workflowCanceled(input, {stateDir} = {}) {
  if (!stateDir || !input?.session_id || !input?.turn_id) return false;
  return existsSync(join(stateDir, `cancel-${sha256(input.session_id + '\0' + input.turn_id).slice(0, 32)}.json`));
}

function fresh(turn, carry = []) {
  return {v: 1, turn, seen: [], tools: [], actions: 0, hadFailure: false, returned: false,
    learningPrompted: false, reusePrompted: false, generalClosed: false, reuses: carry,
    queries: [], surfaced: [], searches: 0, recallFailed: false, promptHash: null,
    errorGroups: [], canceled: false};
}

function read(path) {
  try {
    const state = JSON.parse(readFileSync(path, 'utf8'));
    if (state.v === 1 && typeof state.turn === 'string' && Array.isArray(state.seen)
        && Array.isArray(state.reuses) && Array.isArray(state.queries)
        && Array.isArray(state.tools) && Array.isArray(state.surfaced) && Array.isArray(state.errorGroups)
        && Number.isSafeInteger(state.actions) && Number.isSafeInteger(state.searches)) return state;
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
        if (state) {state.canceled = true; state.reuses = []; saveState(path, state);}
        return [];
      }
      if (event === 'Interrupt') {
        if (state?.turn === turn) {state.canceled = true; saveState(path, state);}
        log('workflow_interrupted');
        return [];
      }
      if (!state || (event === 'UserPromptSubmit' && state.turn !== turn)) {
        const carry = state && !state.canceled ? state.reuses.slice(-4) : [];
        state = fresh(turn, carry);
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
      function cues(reason) {
        if (options.learning === false) return;
        if (state.reuses.length && !state.reusePrompted) {
          parts.push(reuseHint(mcpServer, state.reuses)); state.reusePrompted = true;
          log('reuse_learning_context_returned', {host_receipt: 'unknown'});
        } else if (reason && !state.learningPrompted && !state.generalClosed) {
          parts.push(learningHint(mcpServer, reason)); state.learningPrompted = true;
          log('learning_context_returned', {host_receipt: 'unknown'});
        }
      }
      if (event === 'UserPromptSubmit') {
        const promptHash = sha256(typeof input.prompt === 'string' ? input.prompt : '');
        if (state.promptHash === promptHash) return [];
        state.promptHash = promptHash;
        await recall(taskQuery(input.prompt), 'task');
        if (state.reuses.length || state.actions > 0) cues('工具活动后收到用户补充，请结合原文判断是否包含新教训');
      } else {
        if (typeof input.tool_use_id !== 'string' || !input.tool_use_id || !NAME.test(input.tool_name ?? '')) return [];
        const token = sha256(input.tool_use_id);
        if (state.seen.includes(token) || state.seen.length >= 256) return [];
        state.seen.push(token);
        const kind = extractToolseedKind(input.tool_name, mcpServer);
        if (kind) {
          const body = toolseedBody(input.tool_response);
          const failed = extractStructuredFailure(input.tool_name, input.tool_response);
          if (!failed && kind === 'run' && body?.ok === true && body.execution_status === 'guidance_delivered'
              && Object.entries(REF).every(([key, pattern]) => pattern.test(body[key] ?? ''))
              && !state.reuses.some(r => r.invocation_id === body.invocation_id)
              && state.reuses.length < 4) {
            state.reuses.push(Object.fromEntries(Object.keys(REF).map(key => [key, body[key]])));
          }
          if (!failed && kind === 'learn' && body?.status === 'accepted') {
            if (body.reuse_source) state.reuses = state.reuses.filter(r => !(r.invocation_id === body.reuse_source.invocation_id
              && r.capability_id === body.capability_id && r.version_id === body.reuse_source.version_id
              && r.content_hash === body.reuse_source.content_hash));
            else state.generalClosed = true;
          }
        } else if (!['run_code', 'functions.exec'].includes(input.tool_name)) {
          state.actions++;
          const isNew = !state.tools.includes(input.tool_name);
          if (isNew && state.tools.length < 64) state.tools.push(input.tool_name);
          const code = extractStructuredFailure(input.tool_name, input.tool_response);
          if (code) {
            state.hadFailure = true;
            const group = input.tool_name + ':' + code;
            if (!state.errorGroups.includes(group) && state.errorGroups.length < 16) {
              state.errorGroups.push(group);
              await recall(input.tool_name + ' ' + code, 'error', {tool_hints: [input.tool_name], error_codes: [code]});
            }
          } else state.returned = true;
          if (isNew && input.tool_name.startsWith('mcp__') && !code) {
            await recall(input.tool_name, 'tools', {tool_hints: [input.tool_name]});
          }
          const reason = state.hadFailure && state.returned ? '曾有结构化失败，随后有工具返回'
            : state.actions >= 6 && state.tools.length >= 2 ? '已完成一段多工具操作'
              : state.actions >= 8 ? '已完成一段较长的工具操作' : undefined;
          cues(reason);
        }
      }
      if (existsSync(cancel)) {state.canceled = true; saveState(path, state); return [];}
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
