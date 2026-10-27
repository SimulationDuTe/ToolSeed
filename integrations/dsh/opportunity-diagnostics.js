import {randomUUID} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {join} from 'node:path';

export const DIAGNOSTIC_PREFIX = 'toolseed/opportunity-diagnostics';
export const DIAGNOSTIC_LIMITS = Object.freeze({records: 256, bytes: 128 * 1024, recordBytes: 2048});
const SAFE_CODE = /^[A-Z][A-Z0-9_]{0,79}$/;
const SAFE_TOOL = /^[A-Za-z0-9_-]{1,128}$/;
const SAFE_VERSION = /^\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?$/;
const STAGES = new Set(['observer_started', 'observer_stopped', 'tool_result', 'step_seen',
  'step_decision', 'step_failed', 'prompt_decision', 'turn_observation_ended', 'signal_detected',
  'opportunity_proposed', 'opportunity_prompted', 'prompt_unavailable', 'search_failed',
  'search_completed', 'search_result_unknown', 'save_failed', 'capability_saved',
  'existing_version_returned', 'reuse_observation_saved', 'save_result_unknown', 'delivery_failed', 'guidance_delivered',
  'delivery_result_unknown']);
const REASONS = new Set(['limit_reached', 'identity_limit', 'plugin_unloaded', 'next_turn', 'agent_disposed',
  'no_agent', 'execution_cancelled', 'no_turn_state', 'turn_cancelled', 'token_not_symbol',
  'duplicate_token', 'execution_limit', 'toolseed_tool', 'not_tool_error', 'ptc_transport',
  'invalid_tool_name', 'missing_or_nonstring_code', 'invalid_code', 'cancel_code',
  'signal_already_detected', 'group_limit', 'counted', 'awaiting_host_decision',
  'host_policy_error', 'host_decision', 'no_signal', 'already_proposed', 'search_observed',
  'step_not_entered', 'search_tool_not_visible', 'eligible', 'host_interface_unavailable']);
const noop = () => {};
const DISABLED = Object.freeze({enabled: false, bindTurn: noop, tool: noop, step: noop,
  lifecycle: noop, endTurn: noop, close: noop});

function installedHostVersion() {
  // Public package export. A supported-version declaration is NOT evidence of
  // the running version. Failed resolution stays unknown; no paths/errors log.
  try {
    const url = import.meta.resolve('@deepseek-ai/dsh-agent/package.json');
    return {version: JSON.parse(readFileSync(new URL(url), 'utf8')).version, source: 'agent_package'};
  } catch {
    // This installed Desktop's shipped metadata was checked read-only. It is
    // a fallback, not a guessed SDK property or a copy of engines.dsh.
    if (typeof process.resourcesPath !== 'string') throw new Error('metadata unavailable');
    const file = join(process.resourcesPath, 'runtime', 'primary-runtime', 'runtime.json');
    return {version: JSON.parse(readFileSync(file, 'utf8')).desktopVersion, source: 'desktop_runtime_metadata'};
  }
}

/** Opt-in, bounded logger projection. It never changes a trigger decision. */
export function createOpportunityDiagnostics(logger, {enabled = false,
  versionReader = installedHostVersion} = {}) {
  if (enabled !== true) return DISABLED;
  let hostVersion = 'unknown', versionSource = 'unavailable';
  try {
    const metadata = versionReader();
    const version = typeof metadata === 'string' ? metadata : metadata?.version;
    if (typeof version === 'string' && version.length <= 48 && SAFE_VERSION.test(version)) {
      hostVersion = version;
      versionSource = ['agent_package', 'desktop_runtime_metadata'].includes(metadata?.source)
        ? metadata.source : 'metadata_reader';
    }
  } catch { /* No claimed version if the installed public metadata is unavailable. */ }
  const capture = randomUUID();
  let active = true, records = 0, bytes = 0;
  let turnObjects = new WeakMap();
  const agents = new Map(), sessions = new Map(), tokens = new Map();
  let agentCounter = 0, sessionCounter = 0, turnCounter = 0, tokenCounter = 0;
  function clear() {
    agents.clear(); sessions.clear(); tokens.clear();
    turnObjects = new WeakMap();
  }
  function write(stage, fields, terminal = false) {
    if (!active) return;
    const body = {schema: 1, capture, seq: records + 1, host_version: hostVersion,
      host_version_source: versionSource, time: new Date().toISOString(),
      stage: STAGES.has(stage) ? stage : 'unknown_stage', ...fields};
    if (Object.hasOwn(body, 'reason') && !REASONS.has(body.reason)) body.reason = 'unknown_reason';
    const text = JSON.stringify(body);
    const size = Buffer.byteLength(`${DIAGNOSTIC_PREFIX} ${text}\n`);
    if (!terminal && (records >= DIAGNOSTIC_LIMITS.records - 1
        || size > DIAGNOSTIC_LIMITS.recordBytes
        || bytes + size > DIAGNOSTIC_LIMITS.bytes - DIAGNOSTIC_LIMITS.recordBytes)) {
      write('observer_stopped', {reason: 'limit_reached'}, true);
      return;
    }
    try { logger.info(DIAGNOSTIC_PREFIX, text); }
    catch { active = false; clear(); return; }
    records++; bytes += size;
    if (terminal) { active = false; clear(); }
  }
  const safe = fn => (...args) => {
    if (!active) return;
    try { fn(...args); } catch { /* Diagnostic errors cannot affect the task. */ }
  };
  function identity(map, key, prefix, next) {
    if (!map.has(key)) {
      if (map.size >= DIAGNOSTIC_LIMITS.records) {
        write('observer_stopped', {reason: 'identity_limit'}, true);
        return 'unknown';
      }
      map.set(key, `${prefix}${next()}`);
    }
    return map.get(key);
  }
  function scope(agent, state) {
    if (!active) return {agent: 'unknown', session: 'unknown', turn: 'unknown'};
    if (state && turnObjects.has(state)) return turnObjects.get(state);
    let a = 'unknown', s = 'unknown';
    if (agent && typeof agent === 'object') {
      const id = agent.id;
      if (typeof id === 'string') {
        a = identity(agents, id, 'a', () => ++agentCounter);
      }
      if (!active) return {agent: a, session: s, turn: 'unknown'};
      const sid = agent.session?.id;
      if (typeof sid === 'string') {
        s = identity(sessions, sid, 's', () => ++sessionCounter);
      }
    }
    return {agent: a, session: s, turn: 'unknown'};
  }
  function tokenId(token) {
    if (typeof token !== 'symbol') return 'unknown';
    return identity(tokens, token, 'e', () => ++tokenCounter);
  }
  function promptState(state) {
    return state?.committed ? 'committed' : state?.prompted ? 'commit_not_observed' : 'not_proposed';
  }
  const api = {
    // Remains true after exhaustion: never fall back to the normal, raw-ID
    // opportunity logger when this capture's budget has been consumed.
    enabled: true,
    bindTurn: safe((agent, state) => {
      turnObjects.set(state, {...scope(agent), turn: `r${++turnCounter}`});
    }),
    tool: safe((exec, result, state, reason, count) => {
      const info = result?.error?.info;
      const present = Boolean(info && Object.hasOwn(info, 'code'));
      const code = present ? info.code : undefined;
      const codeValid = typeof code === 'string' && SAFE_CODE.test(code);
      const numericCode = Number.isSafeInteger(code) && code >= 0 && code <= 0xffffffff;
      const nameValid = typeof exec?.name === 'string' && SAFE_TOOL.test(exec.name);
      const groupCount = count ?? (nameValid && codeValid ? state?.groups.get(`${exec.name}:${code}`) : undefined);
      write('tool_result', {...scope(exec?.agent, state), token: tokenId(exec?.token),
        tool: nameValid ? exec.name : 'redacted_invalid_name',
        is_error: typeof result?.isError === 'boolean' ? result.isError : 'unknown',
        code_present: present, code_valid: codeValid,
        code_type: !present ? 'absent' : code === null ? 'null' : Array.isArray(code) ? 'array' : typeof code,
        error_code: codeValid || numericCode ? code : present ? 'redacted_non_code' : null,
        token_duplicate: ['no_agent', 'no_turn_state', 'execution_cancelled', 'turn_cancelled',
          'token_not_symbol'].includes(reason) ? 'unknown' : reason === 'duplicate_token',
        group_count: Number.isSafeInteger(groupCount) ? groupCount : null,
        execution_cancelled: typeof exec?.signal?.aborted === 'boolean' ? exec.signal.aborted : 'unknown',
        turn_cancelled: typeof state?.signal?.aborted === 'boolean' ? state.signal.aborted : 'unknown',
        reason, transport_origin: 'unknown'});
    }),
    step: safe((agent, state, stage, reason, entered = null, visible = null) => {
      write(stage, {...scope(agent, state), reason, entered, search_visible: visible,
        prompt: promptState(state)});
    }),
    lifecycle: safe((stage, state, extra = {}) => {
      // All normal opportunity logs are projected through this whitelist while
      // enabled: no raw Agent/turn/message/capability/opportunity identifiers.
      const fields = {...scope(undefined, state), prompt: promptState(state)};
      if (Number.isSafeInteger(extra.count)) fields.group_count = extra.count;
      if (Number.isSafeInteger(extra.candidate_count)) fields.candidate_count = extra.candidate_count;
      if (typeof extra.tool === 'string' && SAFE_TOOL.test(extra.tool)) fields.tool = extra.tool;
      if (typeof extra.error_code === 'string' && SAFE_CODE.test(extra.error_code)) fields.error_code = extra.error_code;
      if (['search_tool_not_visible', 'host_interface_unavailable'].includes(extra.reason)) fields.reason = extra.reason;
      write(stage, fields);
    }),
    endTurn: safe((state, reason) => {
      write('turn_observation_ended', {...scope(undefined, state), reason, prompt: promptState(state)});
    }),
    close: safe(() => write('observer_stopped', {reason: 'plugin_unloaded'}, true)),
  };
  write('observer_started', {limits: DIAGNOSTIC_LIMITS});
  return api;
}
