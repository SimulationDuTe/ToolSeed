import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {installOpportunityHooks, opportunityHint} from '../opportunities.js';
import {createOpportunityDiagnostics, DIAGNOSTIC_LIMITS, DIAGNOSTIC_PREFIX} from '../opportunity-diagnostics.js';

const search = 'mcp__toolseed__toolbox_search';
function fixture(enabled = true, {visible = true, loggerFails = false} = {}) {
  const events = new Map(), rows = [], effects = [];
  let toolLookups = 0;
  const ctx = {
    on: (name, fn) => events.set(name, fn), effect: fn => effects.push(fn),
    tools: {get: name => {toolLookups++; return visible && name === search ? {} : undefined;}},
    logger: {info(prefix, text) {
      if (loggerFails) throw Error('PRIVATE_LOGGER_PATH');
      rows.push({prefix, body: JSON.parse(text), text});
    }},
  };
  installOpportunityHooks(ctx, {opportunityDiagnostics: enabled});
  const agent = {id: 'PRIVATE_AGENT_ID', session: {id: 'F:/PRIVATE_SESSION_PATH'}};
  const controller = new AbortController();
  async function step({turn = 91731, commit = true, decision, signal = controller.signal} = {}) {
    const value = await events.get('agent/pre-step')({agent, turn, step: 6721, signal},
      async () => decision ?? {kind: 'enter', messages: [], startsRequestSeries: true});
    if (commit && value.kind === 'enter') for (const message of value.messages) {
      events.get('session/event')({id: agent.session.id}, {type: 'user/message', seq: 928312, data: message});
    }
    return value;
  }
  function result({name = 'diagnose', code = 'TOOL_TIMEOUT', token = Symbol('PRIVATE_TOKEN_PATH'),
    isError = true, subject = agent, signal = controller.signal, body} = {}) {
    const exec = {agent: subject, token, name, signal,
      get arguments() {throw Error('PRIVATE_ARGUMENTS');}};
    events.get('tools/result')(exec, body ?? {isError, error: {
      ...(code === null ? {} : {info: {code}}),
      get message() {throw Error('PRIVATE_FREE_TEXT');}},
      get value() {throw Error('PRIVATE_RESULT');},
      get content() {throw Error('PRIVATE_PROMPT');}});
  }
  const repeat = (options = {}, count = 3) => {for (let i = 0; i < count; i++) result(options);};
  const diagnostics = stage => rows.filter(row => row.prefix === DIAGNOSTIC_PREFIX
    && (!stage || row.body.stage === stage)).map(row => row.body);
  return {events, rows, effects, agent, controller, step, result, repeat, diagnostics,
    lookups: () => toolLookups};
}

test('diagnostics require explicit true; disabled mode does not resolve version or add logs', async () => {
  let reads = 0;
  const observer = createOpportunityDiagnostics({info() {throw Error('must not log');}},
    {enabled: false, versionReader: () => {reads++;}});
  observer.tool({}, {}); observer.close(); assert.equal(reads, 0);
  for (const enabled of [false, undefined, 'true', 1]) {
    const h = fixture(enabled === undefined ? false : enabled); await h.step(); h.repeat({}, 2);
    assert.equal(h.rows.length, 0);
    h.result(); assert.equal(h.diagnostics().length, 0);
    assert.equal(h.rows[0].body.stage, 'signal_detected');
  }
});

test('structured failures log actual code, distinct tokens and counts without raw identities', async () => {
  const h = fixture(); await h.step(); h.repeat(); await h.step();
  const results = h.diagnostics('tool_result');
  assert.deepEqual(results.map(row => row.group_count), [1, 2, 3]);
  assert.deepEqual(results.map(row => row.token_duplicate), [false, false, false]);
  assert.equal(new Set(results.map(row => row.token)).size, 3);
  for (const row of results) {
    assert.equal(row.is_error, true); assert.equal(row.code_present, true);
    assert.equal(row.error_code, 'TOOL_TIMEOUT'); assert.equal(row.reason, 'counted');
    assert.match(row.agent, /^a\d+$/); assert.match(row.session, /^s\d+$/); assert.match(row.turn, /^r\d+$/);
  }
  assert.equal(h.diagnostics('opportunity_prompted').length, 1);
  assert.doesNotMatch(JSON.stringify(h.rows), /PRIVATE|91731|6721|928312/);
  assert.ok(h.rows.every(row => row.prefix === DIAGNOSTIC_PREFIX));
});

test('command-output-only errors are not inspected or promoted to structured failure', async () => {
  const h = fixture(); await h.step();
  h.result({body: {isError: false,
    get value() {throw Error('SetNamedSecurityInfoW failed (Win32 5)');},
    get content() {throw Error('Chrome sandbox crash');}}});
  const row = h.diagnostics('tool_result')[0];
  assert.equal(row.reason, 'not_tool_error'); assert.equal(row.is_error, false);
  assert.equal(row.code_present, false); assert.equal(row.error_code, null);
  assert.equal(row.transport_origin, 'unknown');
  assert.equal((await h.step()).messages.length, 0);
});

test('cancelled execution, cancelled turn and cancellation codes have separate reasons', async () => {
  const h = fixture(); await h.step();
  const cancelled = new AbortController(); cancelled.abort();
  h.result({signal: cancelled.signal});
  h.result({code: 'ABORTED'}); h.result({code: 'ABORTED_BEFORE_DISPATCH'});
  // The final signal is independently cancelled; use a live execution signal.
  h.controller.abort(); h.result({signal: new AbortController().signal});
  assert.deepEqual(h.diagnostics('tool_result').map(row => row.reason),
    ['execution_cancelled', 'cancel_code', 'cancel_code', 'turn_cancelled']);
  assert.equal(h.diagnostics('signal_detected').length, 0);
});

test('transport errors retain actual structured fields; no inference from free text', async () => {
  const h = fixture(); await h.step();
  h.result({body: {isError: true, error: {message: 'PRIVATE transport connection closed'}}});
  const missing = h.diagnostics('tool_result')[0];
  assert.equal(missing.reason, 'missing_or_nonstring_code');
  assert.equal(missing.transport_origin, 'unknown');
  h.repeat({code: 'CONNECTION_CLOSED'});
  assert.equal(h.diagnostics('signal_detected').length, 1); // original generic rule, no new exclusion
  assert.equal(h.diagnostics('tool_result').at(-1).error_code, 'CONNECTION_CLOSED');
  assert.doesNotMatch(JSON.stringify(h.rows), /PRIVATE|transport connection closed/);
});

test('an actual numeric code is recorded as numeric, without making it an eligible trigger code', async () => {
  const h = fixture(); await h.step(); h.repeat({code: 5});
  for (const row of h.diagnostics('tool_result')) {
    assert.equal(row.code_present, true); assert.equal(row.code_type, 'number');
    assert.equal(row.error_code, 5); assert.equal(row.code_valid, false);
    assert.equal(row.reason, 'missing_or_nonstring_code');
  }
  assert.equal(h.diagnostics('signal_detected').length, 0);
});

test('excluded tools, missing state/identity and duplicate token decisions are observable', async () => {
  const h = fixture(); h.result(); await h.step();
  h.result({subject: undefined}); // default fixture agent; explicit no-agent below
  h.events.get('tools/result')({name: 'diagnose'}, {isError: true});
  h.result({token: null});
  h.result({name: 'run_code'});
  h.result({name: search, body: {isError: true, error: {info: {code: 'CONNECTION_CLOSED'}}}});
  const token = Symbol('PRIVATE_DUPLICATE');
  h.result({token}); h.result({token});
  const results = h.diagnostics('tool_result');
  for (const reason of ['no_turn_state', 'no_agent', 'token_not_symbol', 'ptc_transport', 'toolseed_tool', 'duplicate_token']) {
    assert.ok(results.some(row => row.reason === reason), reason);
  }
  const duplicate = results.at(-1), first = results.at(-2);
  assert.equal(duplicate.token, first.token); assert.equal(duplicate.token_duplicate, true);
  assert.equal(duplicate.group_count, first.group_count);
});

test('proposal, rejection, visibility and committed context remain distinct', async () => {
  const h = fixture(); await h.step(); h.repeat();
  await h.step({decision: {kind: 'reject'}});
  assert.equal(h.diagnostics('step_decision').at(-1).entered, false);
  assert.equal(h.diagnostics('prompt_decision').at(-1).reason, 'step_not_entered');
  await h.step({commit: false});
  assert.equal(h.diagnostics('prompt_decision').at(-1).search_visible, true);
  assert.equal(h.diagnostics('opportunity_proposed').length, 1);
  assert.equal(h.diagnostics('opportunity_prompted').length, 0);
  h.events.get('agent/disposed')({agent: h.agent});
  assert.equal(h.diagnostics('turn_observation_ended').at(-1).prompt, 'commit_not_observed');
  const committed = fixture(); await committed.step(); committed.repeat(); await committed.step();
  assert.equal(committed.diagnostics('opportunity_prompted')[0].prompt, 'committed');
  const hidden = fixture(true, {visible: false}); await hidden.step(); hidden.repeat(); await hidden.step();
  assert.equal(hidden.diagnostics('prompt_decision').at(-1).search_visible, false);
  assert.equal(hidden.diagnostics('opportunity_proposed').length, 0);
});

test('no result is not labelled transport failure; raw steps and same tokens use opaque scopes', async () => {
  const h = fixture(); await h.step();
  assert.equal(h.diagnostics('tool_result').length, 0);
  const first = h.diagnostics('step_seen')[0];
  await h.step({turn: 91732});
  const next = h.diagnostics('step_seen').at(-1);
  assert.equal(first.agent, next.agent); assert.equal(first.session, next.session);
  assert.notEqual(first.turn, next.turn);
  assert.equal(h.diagnostics().filter(row => row.transport_origin === true).length, 0);
  assert.doesNotMatch(JSON.stringify(h.rows), /91731|91732|PRIVATE/);
});

test('invalid code/name and version metadata are redacted, never clipped into misleading values', async () => {
  const h = fixture(); await h.step();
  h.result({code: 'C:/PRIVATE_SECRET'}); h.result({name: 'C:/PRIVATE_TOOL'});
  h.result({code: 'A'.repeat(81)});
  assert.equal(h.diagnostics('tool_result')[0].error_code, 'redacted_non_code');
  assert.equal(h.diagnostics('tool_result')[1].tool, 'redacted_invalid_name');
  assert.doesNotMatch(JSON.stringify(h.rows), /PRIVATE|A{81}/);
  const rows = [];
  createOpportunityDiagnostics({info: (_p, text) => rows.push(JSON.parse(text))},
    {enabled: true, versionReader: () => 'F:/PRIVATE_VERSION'});
  assert.equal(rows[0].host_version, 'unknown');
  const known = [];
  createOpportunityDiagnostics({info: (_p, text) => known.push(JSON.parse(text))},
    {enabled: true, versionReader: () => '0.2.1-rc.2'});
  assert.equal(known[0].host_version, '0.2.1-rc.2');
});

test('metadata sources and arbitrary stage/reason values cannot leak paths', () => {
  const rows = [];
  const observer = createOpportunityDiagnostics({info: (_p, text) => rows.push(JSON.parse(text))},
    {enabled: true, versionReader: () => ({version: '0.2.1-rc.2', source: 'desktop_runtime_metadata'})});
  observer.step(undefined, undefined, 'F:/PRIVATE_STAGE', 'C:/PRIVATE_REASON');
  assert.equal(rows[0].host_version_source, 'desktop_runtime_metadata');
  assert.equal(rows[1].stage, 'unknown_stage'); assert.equal(rows[1].reason, 'unknown_reason');
  assert.doesNotMatch(JSON.stringify(rows), /PRIVATE/);
});

test('bounded capture stops permanently without falling back to raw-ID normal logging', async () => {
  const h = fixture(); await h.step();
  h.repeat({isError: false}, 1200);
  const before = h.rows.length;
  h.repeat(); await h.step(); h.effects[0]()();
  assert.equal(h.rows.length, before);
  const rows = h.diagnostics();
  assert.ok(rows.length <= DIAGNOSTIC_LIMITS.records);
  assert.equal(rows.at(-1).stage, 'observer_stopped'); assert.equal(rows.at(-1).reason, 'limit_reached');
  const sizes = h.rows.map(row => Buffer.byteLength(`${row.prefix} ${row.text}\n`));
  assert.ok(sizes.every(size => size <= DIAGNOSTIC_LIMITS.recordBytes));
  assert.ok(sizes.reduce((a, b) => a + b, 0) <= DIAGNOSTIC_LIMITS.bytes);
  assert.ok(h.rows.every(row => row.prefix === DIAGNOSTIC_PREFIX));
  assert.doesNotMatch(JSON.stringify(h.rows), /PRIVATE/);
});

test('identity maps are bounded even when malformed scope metadata prevents result records', () => {
  const rows = [];
  const observer = createOpportunityDiagnostics({info: (_p, text) => rows.push(JSON.parse(text))},
    {enabled: true, versionReader: () => '0.2.1-rc.2'});
  for (let i = 0; i < 1000; i++) {
    observer.bindTurn({id: `PRIVATE_SCOPE_${i}`, get session() {throw Error('PRIVATE_SCOPE_ERROR');}}, {});
  }
  assert.equal(rows.length, 2);
  assert.equal(rows.at(-1).reason, 'identity_limit');
  assert.doesNotMatch(JSON.stringify(rows), /PRIVATE/);
});

test('logger failure and host rejection do not affect original decisions or emit private errors', async () => {
  const h = fixture(true, {loggerFails: true}); await h.step(); h.repeat();
  assert.equal((await h.step()).messages.length, 1);
  const failing = fixture(); const error = Error('PRIVATE_POLICY_ERROR');
  await assert.rejects(failing.events.get('agent/pre-step')({agent: failing.agent, turn: 1,
    signal: failing.controller.signal}, async () => {throw error;}), e => e === error);
  assert.equal(failing.diagnostics('step_failed')[0].reason, 'host_policy_error');
  assert.doesNotMatch(JSON.stringify(failing.rows), /PRIVATE/);
});

test('on/off modes produce the same hints, tool lookups and opportunity stages', async () => {
  async function scenario(enabled, type) {
    const h = fixture(enabled); await h.step();
    if (type === 'ordinary') h.repeat({isError: false});
    else if (type === 'two_failures') h.repeat({}, 2);
    else if (type === 'duplicate') h.repeat({token: Symbol()}, 3);
    else if (type === 'unstructured') h.repeat({code: null});
    else h.repeat();
    const value = await h.step();
    const businessStages = ['signal_detected', 'opportunity_proposed', 'opportunity_prompted'];
    return {messages: value.messages.map(({id, ...message}) => message),
      series: value.startsRequestSeries, lookups: h.lookups(),
      stages: h.rows.map(row => row.body.stage).filter(stage => businessStages.includes(stage))};
  }
  for (const type of ['ordinary', 'two_failures', 'duplicate', 'unstructured', 'three_failures']) {
    assert.deepEqual(await scenario(true, type), await scenario(false, type), type);
  }
  assert.equal(opportunityHint(search, 'mcp__toolseed__toolbox_save').includes('3 次'), true);
});

test('switch defaults off and observer file is included in the plugin package', async () => {
  const source = await readFile(new URL('../index.js', import.meta.url), 'utf8');
  assert.match(source, /opportunityDiagnostics:z\.boolean\(\)\.default\(false\)/);
  const pkg = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'));
  assert.ok(pkg.files.includes('opportunity-diagnostics.js'));
});
