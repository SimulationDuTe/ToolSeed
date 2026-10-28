import {randomUUID} from 'node:crypto';
import {appendEvent, safeId, shortId} from './logging.mjs';
import {
  loadState,
  pruneStaleStates,
  saveState,
  sha256,
  statePath,
  withStateLock,
} from './state.mjs';

export const FAILURE_THRESHOLD = 3;
export const MAX_EXECUTIONS = 256;
export const MAX_GROUPS = 16;
export const MAX_TEXT_BYTES = 65_536;
const MAX_TOOLSEED_TEXT_BYTES = 131_072;

const TOOL_NAME = /^[A-Za-z0-9_.:/-]{1,128}$/;
const CODE = /^[A-Za-z0-9_.:-]{1,80}$/;
const EXIT_CODE = /^-?\d{1,6}$/;

export function isPlainObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

export function opportunityHint({searchTool, saveTool, tool, code}) {
  const safeTool = typeof tool === 'string' && TOOL_NAME.test(tool) ? tool.slice(0, 128) : 'the tool';
  const safeCode = typeof code === 'string' && CODE.test(code) ? code : 'a structured error';
  return `ToolSeed opportunity (L1 hint, not a task result): 3 distinct calls to ${safeTool} failed with the same structured code (${safeCode}) in this turn. This may be a repeated blocker.
Load the installed ToolSeed skill through Codex's Skill mechanism (for example skills.read; do not merely mention it). Then make one short ${searchTool} call with a query describing the current problem and an object context when useful. Reuse an equivalent search already made in this turn if the context is unchanged. Check each candidate's when_to_use, not_for, permissions, limits and available verification evidence; a ready hit does not prove fit.
Apply a delivered procedure only when it is safe and applicable; do not auto-execute it or widen permissions. If nothing fits, the tool is unavailable, or search/save fails, continue the original task without blind retries.
After the method is actually validated and worth reusing, follow the loaded Skill contract to call ${saveTool} and confirm the response; saving is optional. Search hit, guidance delivery, actual adoption and task success are different stages; keep missing evidence unknown.`;
}

export function extractToolseedKind(toolName, mcpServer = 'toolseed') {
  if (typeof toolName !== 'string' || typeof mcpServer !== 'string') return undefined;
  const escaped = mcpServer.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const patterns = [
    new RegExp(`^mcp__${escaped}__toolbox_(search|save|run|stats|learn)$`),
    new RegExp(`^mcp__${escaped}\\.toolbox_(search|save|run|stats|learn)$`),
    new RegExp(`^${escaped}__toolbox_(search|save|run|stats|learn)$`),
    new RegExp(`^${escaped}[._]toolbox_(search|save|run|stats|learn)$`),
    /^toolseed__toolbox_(search|save|run|stats|learn)$/,
  ];
  for (const pattern of patterns) {
    const match = pattern.exec(toolName);
    if (match) return match[1];
  }
  return undefined;
}

function parseJsonObject(text, maximum = MAX_TEXT_BYTES) {
  if (typeof text !== 'string' || text.length > maximum) return undefined;
  const trimmed = text.replace(/^\uFEFF/, '').trim();
  if (!trimmed.startsWith('{')) return undefined;
  try {
    const parsed = JSON.parse(trimmed);
    return isPlainObject(parsed) ? parsed : undefined;
  } catch {
    return undefined;
  }
}

function contentBody(content, maximum = MAX_TEXT_BYTES) {
  if (!Array.isArray(content) || content.length !== 1) return undefined;
  const block = content[0];
  if (block?.type !== 'text' || typeof block.text !== 'string' || block.text.length > maximum) {
    return undefined;
  }
  return parseJsonObject(block.text, maximum);
}

export function toolseedBody(toolResponse) {
  const direct = isPlainObject(toolResponse) ? toolResponse : undefined;
  if (direct) {
    if (isPlainObject(direct.structuredContent)) return direct.structuredContent;
    if (isPlainObject(direct.result?.structuredContent)) return direct.result.structuredContent;
    const nested = contentBody(direct.content, MAX_TOOLSEED_TEXT_BYTES)
      ?? contentBody(direct.result?.content, MAX_TOOLSEED_TEXT_BYTES);
    if (nested) return nested;
    if ('status' in direct || 'results' in direct || 'execution_status' in direct
        || 'capability_id' in direct || 'error' in direct) {
      return direct;
    }
  }
  if (typeof toolResponse === 'string') return parseJsonObject(toolResponse, MAX_TOOLSEED_TEXT_BYTES);
  return undefined;
}

function normalizedCode(value) {
  if (typeof value === 'number' && Number.isSafeInteger(value)) {
    return `SHELL_EXIT_${value}`;
  }
  if (typeof value !== 'string') return undefined;
  const trimmed = value.trim();
  return CODE.test(trimmed) ? trimmed : undefined;
}

function failureCode(value) {
  if (!isPlainObject(value)) return undefined;
  const explicit = normalizedCode(value?.error?.info?.code)
    ?? normalizedCode(value?.error?.code);
  if (explicit) return explicit;
  const exit = value.exitCode ?? value.exit_code;
  if (typeof exit === 'number' && Number.isSafeInteger(exit) && exit !== 0) {
    return `SHELL_EXIT_${exit}`;
  }
  if (typeof exit === 'string' && EXIT_CODE.test(exit.trim()) && Number(exit) !== 0) {
    return `SHELL_EXIT_${Number(exit)}`;
  }
  const failed = value.status === 'failed' || value.success === false || value.ok === false
    || value.isError === true || value.is_error === true;
  if (!failed) return undefined;
  // A bare `code` field is accepted only once another structured failure flag
  // is present, so successful results that happen to carry a code are ignored.
  return normalizedCode(value.code) ?? 'TOOL_FAILED';
}

/**
 * Best-effort structured failure extraction. Free-text error messages and
 * command output are never parsed. MCP envelopes may be parsed as bounded JSON
 * because their canonical content is structured data.
 */
export function extractStructuredFailure(toolName, toolResponse) {
  if (typeof toolName !== 'string') return undefined;
  const isMcp = toolName.startsWith('mcp__') || toolName.includes('__toolbox_');
  if (isMcp) {
    const body = toolseedBody(toolResponse);
    const code = normalizedCode(body?.error?.info?.code)
      ?? normalizedCode(body?.error?.code)
      ?? normalizedCode(body?.code);
    if (code) return code;
    if (body?.error || body?.isError === true || body?.status === 'failed') return 'MCP_TOOL_ERROR';
    if (isPlainObject(toolResponse) && (toolResponse.error || toolResponse.isError === true
        || toolResponse.status === 'failed')) {
      return 'MCP_TOOL_ERROR';
    }
    return undefined;
  }
  if (!isPlainObject(toolResponse)) return undefined;
  return failureCode(toolResponse);
}

function toolseedObservation(kind, body, toolResponse) {
  const failed = toolResponse?.isError === true || Boolean(body?.error);
  const links = {};
  for (const key of ['capability_id', 'version_id', 'invocation_id']) {
    const value = safeId(body?.[key]);
    if (value) links[key] = value;
  }
  if (kind === 'stats') return undefined;
  if (kind === 'search') {
    const count = Array.isArray(body?.results) ? body.results.length : undefined;
    return {
      stage: failed ? 'search_failed' : count !== undefined ? 'search_completed' : 'search_result_unknown',
      ...(count !== undefined ? {candidate_count: count} : {}),
      ...links,
    };
  }
  if (kind === 'save' || kind === 'learn') {
    const stored = !failed && body?.status === 'accepted'
      && typeof body?.capability_id === 'string' && typeof body?.version_id === 'string';
    return {
      stage: failed ? 'save_failed' : stored
        ? (body?.learning_action === 'observation_added' ? 'reuse_observation_saved'
          : body?.duplicate === true ? 'existing_version_returned' : 'capability_saved')
        : 'save_result_unknown',
      ...links,
    };
  }
  return {
    stage: failed ? 'delivery_failed' : body?.execution_status === 'guidance_delivered'
      ? 'guidance_delivered' : 'delivery_result_unknown',
    ...links,
  };
}

export function reducePostToolUse(state, input, {threshold = FAILURE_THRESHOLD, mcpServer = 'toolseed'} = {}) {
  const next = structuredClone(state);
  const events = [];
  if (!isPlainObject(input) || input.hook_event_name !== 'PostToolUse') {
    return {state: next, events, hint: undefined};
  }
  const {session_id, turn_id, tool_name, tool_use_id, tool_response} = input;
  if (typeof session_id !== 'string' || session_id.length === 0
      || typeof turn_id !== 'string' || turn_id.length === 0
      || typeof tool_name !== 'string' || !TOOL_NAME.test(tool_name)
      || typeof tool_use_id !== 'string' || tool_use_id.length === 0) {
    return {state: next, events, hint: undefined};
  }
  const token = sha256(tool_use_id).slice(0, 32);
  if (next.seen.includes(token)) {
    return {state: next, events, hint: undefined};
  }
  if (next.seen.length >= MAX_EXECUTIONS) {
    events.push({stage: 'execution_limit', tool: tool_name});
    return {state: next, events, hint: undefined};
  }
  next.seen.push(token);
  next.executions += 1;
  next.updated_at = new Date().toISOString();

  const kind = extractToolseedKind(tool_name, mcpServer);
  if (kind) {
    const body = toolseedBody(tool_response);
    if (kind === 'search' && next.opportunity_id) {
      // A search already started after the signal. It neither proves relevance
      // nor suppresses a hint that was already emitted.
      next.search_observed = true;
    }
    const observation = toolseedObservation(kind, body, tool_response);
    if (observation) events.push({...observation, tool: tool_name});
    return {state: next, events, hint: undefined};
  }

  const code = extractStructuredFailure(tool_name, tool_response);
  if (!code) return {state: next, events, hint: undefined};
  if (next.opportunity_id) return {state: next, events, hint: undefined};

  const key = `${tool_name}:${code}`;
  if (!(key in next.groups) && Object.keys(next.groups).length >= MAX_GROUPS) {
    events.push({stage: 'group_limit', tool: tool_name, error_code: code});
    return {state: next, events, hint: undefined};
  }
  const count = (next.groups[key] ?? 0) + 1;
  next.groups[key] = count;
  if (count !== threshold) return {state: next, events, hint: undefined};

  next.opportunity_id = randomUUID();
  next.prompted = true;
  const hint = opportunityHint({
    searchTool: `mcp__${mcpServer}__toolbox_search`,
    saveTool: `mcp__${mcpServer}__toolbox_save`,
    tool: tool_name,
    code,
  });
  events.push(
    {stage: 'signal_detected', rule: 'repeated_structured_tool_failure', tier: 'L1',
      count, tool: tool_name, error_code: code},
    {stage: 'hint_emitted', delivery: 'post_tool_use_additional_context',
      host_receipt: 'unknown', model_consumption: 'unknown',
      context_characters: [...hint].length, context_utf8_bytes: Buffer.byteLength(hint)},
  );
  return {state: next, events, hint};
}

export async function handlePostToolUse(input, options = {}) {
  const {
    stateDir,
    logDir,
    mcpServer = 'toolseed',
    threshold = FAILURE_THRESHOLD,
  } = options;
  if (!stateDir || !isPlainObject(input) || input.hook_event_name !== 'PostToolUse') {
    return {};
  }
  const sessionId = typeof input.session_id === 'string' ? input.session_id : '';
  const turnId = typeof input.turn_id === 'string' ? input.turn_id : '';
  if (!sessionId || !turnId) return {};
  pruneStaleStates(stateDir);
  const path = statePath(stateDir, sessionId, turnId);
  try {
    const result = await withStateLock(path, () => {
      const state = loadState(path, sessionId, turnId);
      const reduced = reducePostToolUse(state, input, {threshold, mcpServer});
      saveState(path, reduced.state);
      for (const event of reduced.events) {
        appendEvent(logDir, {
          ...event,
          session: shortId(sessionId),
          turn: shortId(turnId),
        });
      }
      return reduced;
    });
    if (!result.locked) {
      appendEvent(logDir, {stage: 'state_lock_unavailable'});
      return {};
    }
    return result.value?.hint
      ? {hookSpecificOutput: {hookEventName: 'PostToolUse', additionalContext: result.value.hint}}
      : {};
  } catch (error) {
    appendEvent(logDir, {stage: 'adapter_error', error: error?.name ?? 'Error'});
    return {};
  }
}
