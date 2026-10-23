import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {installOpportunityHooks, opportunityHint} from '../opportunities.js';

const searchName = 'mcp__toolseed__toolbox_search';
const saveName = 'mcp__toolseed__toolbox_save';
function harness({visible = true, loggerFails = false} = {}) {
  const events = new Map(), records = [], effects = [];
  const ctx = {
    on: (name, fn) => events.set(name, fn), effect: fn => effects.push(fn),
    tools: {get: name => visible && name === searchName ? {} : undefined},
    logger: {info: (_prefix, text) => {if (loggerFails) throw Error('logging unavailable'); records.push(JSON.parse(text));}},
  };
  installOpportunityHooks(ctx);
  const agent = {id: 'unit-agent', session: {id: 'unit-agent'}};
  const controller = new AbortController();
  async function pre({turn = 1, subject = agent, decision, commit = true, signal = controller.signal} = {}) {
    const original = decision ?? {kind: 'enter', messages: [], startsRequestSeries: true};
    const value = await events.get('agent/pre-step')({agent: subject, turn, signal}, async () => original);
    if (commit && value.kind === 'enter') {
      for (const message of value.messages) events.get('session/event')({id: subject.session.id},
        {type: 'user/message', seq: 11, data: message});
    }
    return value;
  }
  function result({name = 'diagnose', code = 'TOOL_TIMEOUT', isError = true,
    token = Symbol(), subject = agent, signal = controller.signal, value} = {}) {
    const exec = {agent: subject, token, name, signal};
    const body = {isError, error: code === null ? undefined : {info: {code}}, value};
    events.get('tools/result')(exec, body);
    return {exec, body};
  }
  const repeat = (options = {}, count = 3) => {for (let i = 0; i < count; i++) result(options);};
  return {ctx, agent, controller, events, records, effects, pre, result, repeat};
}
const stages = h => h.records.map(record => record.stage);
const mcp = body => ({structuredContent: body});

test('three structured failures produce one L1 hint without any user ToolSeed request', async () => {
  const h = harness();
  const user = {id: 'u1', role: 'user', source: {kind: 'user'}, content: [{type: 'text', text: 'Complete the normal task'}]};
  await h.pre({decision: {kind: 'enter', messages: [user]}});
  h.repeat();
  assert.deepEqual(stages(h), ['signal_detected']);
  const original = {kind: 'enter', messages: [user], startsRequestSeries: true};
  const decision = await h.pre({decision: original});
  assert.equal(original.messages.length, 1);
  assert.equal(decision.messages[0], user);
  assert.equal(decision.startsRequestSeries, true);
  assert.match(decision.messages[1].content[0].text, /L1/);
  assert.match(decision.messages[1].content[0].text, /context 必须为对象/);
  assert.deepEqual(stages(h), ['signal_detected', 'opportunity_proposed', 'opportunity_prompted']);
  assert.ok(h.records.every(record => record.task_outcome === 'unknown' && record.adoption === 'unknown'));
});

test('L0 successes, isolated failures and unstructured error text add no hint', async () => {
  for (const sample of [{isError: false}, {code: null}, {code: 'arbitrary sensitive free text'}]) {
    const h = harness(); await h.pre(); h.repeat(sample, 6);
    assert.equal((await h.pre()).messages.length, 0);
    assert.deepEqual(stages(h), []);
  }
  const h = harness(); await h.pre(); h.repeat({}, 2);
  assert.equal((await h.pre()).messages.length, 0);
});

test('different tools and codes do not combine into a repeated blocker', async () => {
  const h = harness(); await h.pre();
  h.repeat({name: 'first'}, 2); h.repeat({name: 'second'}, 2); h.repeat({code: 'INVALID_ARGUMENT'}, 2);
  assert.deepEqual(stages(h), []);
});

test('execution tokens and per-turn prompt cap prevent duplicate hints', async () => {
  const h = harness(); await h.pre();
  const token = Symbol(); h.repeat({token}, 10);
  assert.deepEqual(stages(h), []);
  h.repeat({}, 2); await h.pre(); h.repeat({}, 8); await h.pre();
  assert.equal(stages(h).filter(stage => stage === 'signal_detected').length, 1);
  assert.equal(stages(h).filter(stage => stage === 'opportunity_prompted').length, 1);
});

test('agents and turns are isolated and no earlier history is reconstructed', async () => {
  const h = harness(); await h.pre(); h.repeat({}, 2);
  const other = {id: 'other-agent', session: {id: 'other-agent'}};
  await h.pre({subject: other}); h.repeat({subject: other}, 2);
  await h.pre({turn: 2}); h.result();
  assert.deepEqual(stages(h), []);
  h.repeat({}, 2); await h.pre({turn: 2});
  assert.equal(h.records[0].turn, 2);
});

test('cancelled work and the outer PTC transport are not independent failure signals', async () => {
  for (const options of [{code: 'ABORTED'}, {code: 'ABORTED_BEFORE_DISPATCH'}, {name: 'run_code'}]) {
    const h = harness(); await h.pre(); h.repeat(options, 5); assert.deepEqual(stages(h), []);
  }
  const h = harness(); await h.pre(); h.controller.abort(); h.repeat();
  assert.deepEqual(stages(h), []);
});

test('no prompt is claimed as admitted when another plugin rejects or drops it', async () => {
  const h = harness(); await h.pre(); h.repeat();
  const denied = {kind: 'reject'};
  assert.equal(await h.pre({decision: denied}), denied);
  assert.deepEqual(stages(h), ['signal_detected']);
  await h.pre({commit: false});
  assert.deepEqual(stages(h), ['signal_detected', 'opportunity_proposed']);
});

test('a hidden or missing ToolSeed tool leaves the existing path usable', async () => {
  const h = harness({visible: false}); await h.pre(); h.repeat();
  assert.equal((await h.pre()).messages.length, 0); await h.pre();
  assert.deepEqual(stages(h), ['signal_detected', 'prompt_unavailable']);
});

test('search observed after the signal avoids another prompt, including failure', async () => {
  for (const options of [
    {isError: false, value: mcp({results: []})},
    {isError: false, value: mcp({ok: false, error: {code: 'INVALID_ARGUMENT'}})},
    {isError: true},
  ]) {
    const h = harness(); await h.pre(); h.repeat(); h.result({name: searchName, ...options});
    assert.equal((await h.pre()).messages.length, 0);
    assert.equal(stages(h).filter(stage => stage === 'signal_detected').length, 1);
  }
});

test('search and save failures neither block the turn nor feed another blocker', async () => {
  const h = harness(); await h.pre(); h.repeat(); await h.pre();
  h.repeat({name: searchName}); h.repeat({name: saveName});
  assert.equal(stages(h).filter(stage => stage === 'signal_detected').length, 1);
  assert.ok(stages(h).includes('search_failed'));
  assert.ok(stages(h).includes('save_failed'));
  assert.equal((await h.pre()).kind, 'enter');
});

test('observed save and delivery do not claim adoption, validation or task success', async () => {
  const h = harness(); await h.pre();
  h.result({name: saveName, isError: false, value: mcp({status: 'accepted', capability_id: 'cap_fixture', version_id: 'ver_fixture', version_status: 'ready'})});
  h.result({name: saveName, isError: false, value: mcp({status: 'accepted', capability_id: 'cap_fixture', version_id: 'ver_fixture', duplicate: true})});
  h.result({name: 'mcp__toolseed__toolbox_run', isError: false, value: mcp({execution_status: 'guidance_delivered', task_outcome: 'unknown'})});
  assert.deepEqual(stages(h), ['capability_saved', 'existing_version_returned', 'guidance_delivered']);
  for (const record of h.records) {
    assert.equal(record.adoption, 'unknown'); assert.equal(record.task_outcome, 'unknown');
    assert.equal(record.verification, undefined);
  }
});

test('only the configured server and documented bounded result shapes are inspected', async () => {
  const h = harness(); await h.pre();
  h.result({name: 'mcp__other__toolbox_search', isError: false, value: mcp({results: []})});
  assert.deepEqual(stages(h), []);
  h.result({name: searchName, isError: false, value: {content: [{type: 'text', text: '{"results":[]}' }]}});
  h.result({name: searchName, isError: false, value: {content: [{type: 'text', text: '{broken' }]}});
  h.result({name: saveName, isError: false, value: mcp({version_status: 'ready'})});
  assert.deepEqual(stages(h), ['search_completed', 'search_result_unknown', 'save_result_unknown']);
});

test('arguments and free-text errors are never read or logged', async () => {
  const h = harness(); await h.pre();
  for (let i = 0; i < 3; i++) {
    const exec = {agent: h.agent, token: Symbol(), name: 'diagnose', signal: h.controller.signal,
      get arguments() {throw Error('SECRET_ARGUMENT');}};
    h.events.get('tools/result')(exec, {isError: true, error: {info: {code: 'TOOL_TIMEOUT'},
      get message() {throw Error('SECRET_ERROR');}}});
  }
  await h.pre();
  assert.doesNotMatch(JSON.stringify(h.records), /SECRET/);
  assert.doesNotMatch((await h.pre()).messages.map(m => m.content[0].text).join(''), /SECRET/);
});

test('hint preserves applicability, actual loading, validation and authorization boundaries', () => {
  const hint = opportunityHint(searchName, saveName);
  for (const rule of [/实际加载/, /命中或 ready 不证明适用/, /实际验证/, /可选择不保存/,
    /不自动执行或扩大权限/, /缺失证据保持未知/, /不盲目重试/]) assert.match(hint, rule);
  assert.ok(Buffer.byteLength(hint) < 1800);
});

test('listener disposal, missing execution identity and observation caps fail safely', async () => {
  const h = harness(); await h.pre();
  h.events.get('tools/result')({agent: h.agent, name: 'diagnose'}, {isError: true, error: {info: {code: 'TOOL_TIMEOUT'}}});
  h.repeat({isError: false}, 256); h.repeat();
  assert.deepEqual(stages(h), []);
  const stopped = harness(); await stopped.pre(); stopped.effects[0]()(); stopped.repeat();
  assert.deepEqual(stages(stopped), []);
});

test('logging failures do not change tool results or original step admission', async () => {
  const h = harness({loggerFails: true}); await h.pre(); h.repeat();
  assert.equal((await h.pre()).messages.length, 1);
  const denied = Error('another policy failed');
  await assert.rejects(h.events.get('agent/pre-step')({agent: h.agent, turn: 1, signal: h.controller.signal},
    async () => {throw denied;}), error => error === denied);
});

test('packaged plugin includes adapter; panel transport stays independent of optional host services', async () => {
  const config = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'));
  assert.ok(config.files.includes('opportunities.js'));
  const source = await readFile(new URL('../index.js', import.meta.url), 'utf8');
  assert.match(source, /ctx\.inject\(\['agents','tools'\]/);
  assert.match(source, /config\.opportunities !== false/);
  assert.match(source, /ctx\.connection\.fetch\.register/);
});
