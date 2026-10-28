import {test, mock} from 'node:test';
import assert from 'node:assert/strict';
import {createRevisionBridge, installRevisionValidation} from '../revisions.js';

const binding = {capability_id: 'cap_fixture', version_id: 'ver_new', content_hash: 'sha256:fixture', base_version_id: 'ver_base'};
function plan() {
  return {mode: 'validate', binding, cases: ['new', 'regression'].map(role => ({id: role, role,
    purpose: `Check ${role} behaviour`, tool: 'fixture_probe', arguments: {scenario: role},
    assertions: [{path: ['payload', 'ok'], equals: true}]}))};
}
function fixture({run = async () => ({isError: false, value: {payload: {ok: true}}}), prepare = {ok: true, already_active: false}, bridge} = {}) {
  let definition, dispose;
  const calls = [], receipts = [], prepares = [], agent = {}, abort = new AbortController();
  const ctx = {effect: fn => {dispose = fn();}, tools: {
    register: def => {definition = def;}, schemas: () => [{name: 'fixture_probe'}],
    get: name => name === 'fixture_probe', execute: async args => {calls.push(args); return run(args);},
  }};
  installRevisionValidation(ctx, {}, bridge ?? (async (op, payload) => {
    if (op.startsWith('prepare')) {prepares.push(payload); return prepare;}
    receipts.push(payload.receipt); return {ok: true, activated: payload.receipt.cases.every(c => c.status === 'passed')};
  }));
  return {calls, receipts, prepares, ctx, abort, agent, dispose: () => dispose(),
    invoke: (args = plan()) => definition.execute(args, {agent, signal: abort.signal, callId: 'fixture-outer'})};
}

test('inspect only returns material and passes actual host inventory', async () => {
  const f = fixture();
  await f.invoke({mode: 'inspect', binding});
  assert.equal(f.calls.length, 0); assert.equal(f.receipts.length, 0);
  assert.deepEqual(f.prepares[0].environment.harnesses, ['dsh']);
  assert.deepEqual(f.prepares[0].environment.required_tools, ['fixture_probe']);
});

test('successful validation dispatches each case through host with agent and signal', async () => {
  const f = fixture();
  assert.equal((await f.invoke()).activated, true);
  assert.equal(f.calls.length, 2);
  assert.equal(f.calls[0].agent, f.agent);
  assert.ok(f.calls[0].signal instanceof AbortSignal);
  assert.match(f.calls[0].callId, /^toolseed-validation-/);
  assert.deepEqual(f.receipts[0].cases.map(c => c.status), ['passed', 'passed']);
  assert.equal(JSON.stringify(f.receipts).includes('arguments'), false);
});

test('assertion failure stops remaining calls and submits failed/skipped facts', async () => {
  const f = fixture({run: async () => ({isError: false, value: {payload: {ok: false}}})});
  const result = await f.invoke();
  assert.equal(result.activated, false);
  assert.equal(result.diagnostics[0].checks[0].value, false);
  assert.equal(result.diagnostics[0].checks[0].expected, true);
  assert.equal(JSON.stringify(f.receipts).includes('expected'), false);
  assert.equal(f.calls.length, 1);
  assert.deepEqual(f.receipts[0].cases.map(c => c.status), ['failed', 'skipped']);
  assert.deepEqual(f.receipts[0].cases[0].failed_assertions, [0]);
});

test('host denial, tool exceptions, MCP isError and nonzero exits cannot pass', async () => {
  for (const run of [async () => ({isError: true, value: {payload: {ok: true}}}),
    async () => {throw new Error('private details');},
    async () => ({isError: false, value: {isError: true, payload: {ok: true}}}),
    async () => ({isError: false, value: {exit_code: 1, payload: {ok: true}}})]) {
    const f = fixture({run});
    assert.equal((await f.invoke()).activated, false);
    assert.equal(JSON.stringify(f.receipts).includes('private details'), false);
  }
});

test('MCP structured output assertions are interpreted without executing text', async () => {
  const f = fixture({run: async () => ({isError: false, value: {structuredContent: {payload: {ok: true}}, content: [{type: 'text', text: 'untrusted'}]}})});
  assert.equal((await f.invoke()).activated, true);
});

test('missing fields never match null and inherited properties never pass', async () => {
  const f = fixture({run: async () => ({isError: false, value: Object.create({payload: {ok: true}})})});
  assert.equal((await f.invoke()).activated, false);
  const p = plan(); p.cases[0].assertions[0].equals = null;
  const empty = fixture({run: async () => ({isError: false, value: {}})});
  assert.equal((await empty.invoke(p)).activated, false);
});

test('invalid or recursive plans do not run tools or bridge', async () => {
  for (const alter of [p => p.cases.pop(), p => p.cases[1].role = 'new', p => p.cases[1].id = 'new',
    p => p.cases[0].tool = 'toolseed_validate_revision', p => p.cases[0].tool = 'mcp__toolseed__toolbox_run',
    p => p.cases[0].tool = 'run_code', p => p.cases[0].assertions = [],
    p => p.cases[0].assertions[0].path = ['__proto__'], p => p.outcome = 'passed']) {
    const f = fixture(), p = plan(); alter(p);
    assert.equal((await f.invoke(p)).error.code, 'INVALID_VALIDATION_PLAN');
    assert.equal(f.calls.length + f.prepares.length, 0);
  }
});

test('preflight conflict, already active and unavailable tools avoid side effects', async () => {
  for (const prepare of [{ok: false, error: {code: 'CURRENT_VERSION_CONFLICT'}}, {ok: true, already_active: true}]) {
    const f = fixture({prepare}); await f.invoke(); assert.equal(f.calls.length, 0);
  }
  const f = fixture(); f.ctx.tools.get = () => undefined;
  assert.equal((await f.invoke()).error.code, 'VALIDATION_TOOL_UNAVAILABLE');
  assert.equal(f.calls.length, 0); assert.equal(f.receipts.length, 0);
});

test('cancellation and plugin disposal prevent subsequent checks and finalization', async () => {
  for (const cancel of [f => f.abort.abort(), f => f.dispose()]) {
    const f = fixture({run: async () => {cancel(f); return {isError: false, value: {payload: {ok: true}}};}});
    await assert.rejects(f.invoke());
    assert.equal(f.calls.length, 1); assert.equal(f.receipts.length, 0);
  }
});

test('a result arriving after its case deadline cannot pass', async () => {
  const timer = mock.method(AbortSignal, 'timeout', () => AbortSignal.abort());
  try {
    const f = fixture();
    const result = await f.invoke();
    assert.equal(result.activated, false);
    assert.equal(f.calls.length, 1);
    assert.equal(f.receipts[0].cases[0].status, 'failed');
  } finally {timer.mock.restore();}
});

test('only one validation of a capability dispatches at a time', async () => {
  let release;
  const f = fixture({run: () => new Promise(resolve => {release = resolve;})});
  const pending = f.invoke();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal((await f.invoke()).error.code, 'VALIDATION_BUSY');
  release({isError: true}); await pending;
});

test('bridge uses bounded fixed operations without shell interpolation', async () => {
  let call;
  const bridge = createRevisionBridge({python: 'fixed-python', dataDir: 'fixed-db'}, async (...args) => {call = args; return {stdout: '{"ok":true}'};});
  const payload = {binding: {...binding, version_id: '$(not-a-command)'}};
  await bridge('prepare-revision-validation', payload);
  assert.equal(call[0], 'fixed-python'); assert.equal(call[1][4], 'prepare-revision-validation');
  assert.deepEqual(JSON.parse(call[1][5]), payload);
  assert.equal(call[2].shell, false); assert.equal(call[2].windowsHide, true);
  await assert.rejects(bridge('promote-version', {}));
});

test('bridge preserves structured failure but never leaks raw stderr', async () => {
  const structured = createRevisionBridge({}, async () => {throw {stdout: '{"ok":false,"error":{"code":"CONFLICT"}}'};});
  assert.equal((await structured('complete-revision-validation', {})).error.code, 'CONFLICT');
  const unavailable = createRevisionBridge({}, async () => {throw new Error('private stderr');});
  const result = await unavailable('complete-revision-validation', {});
  assert.equal(result.error.code, 'VALIDATION_BRIDGE_UNAVAILABLE');
  assert.equal(JSON.stringify(result).includes('private stderr'), false);
});
