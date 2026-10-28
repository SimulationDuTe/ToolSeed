import {test} from 'node:test';
import assert from 'node:assert/strict';
import {installLearningHooks} from '../learning.js';

const learnName = 'mcp__toolseed__toolbox_learn';
function harness() {
  const events = new Map(), records = [], effects = [];
  let visible = true;
  const ctx = {on: (name, fn) => events.set(name, fn), effect: fn => effects.push(fn),
    tools: {get: name => visible && name === learnName ? {} : undefined},
    logger: {info: (_prefix, text) => records.push(JSON.parse(text))}};
  installLearningHooks(ctx);
  const agent = {id: 'learning-agent', session: {id: 'session'}};
  const controller = new AbortController();
  async function pre({turn = 1, decision = {kind: 'enter', messages: [], startsRequestSeries: true}, commit = true} = {}) {
    const result = await events.get('agent/pre-step')({agent, turn, signal: controller.signal}, async () => decision);
    if (commit && result.kind === 'enter') {
      for (const message of result.messages) events.get('session/event')(agent.session, {type: 'user/message', data: message});
    }
    return result;
  }
  function result({name = 'inspect', isError = false, value, token = Symbol(), code, subject = agent} = {}) {
    events.get('tools/result')({name, agent: subject, token, signal: controller.signal},
      {isError, value, error: code ? {info: {code}} : undefined});
  }
  function progress() {result({isError: true}); result();}
  function message(kind = 'user') {
    events.get('session/event')(agent.session, {type: 'user/message', data: {
      id: 'followup', source: {kind}, content: [{type: 'text', text: 'SENSITIVE USER TEXT'}]}});
  }
  return {pre, result, progress, message, records, effects, events, agent, controller,
    setVisible: value => {visible = value;}};
}
const text = decision => decision.messages.map(message => message.content[0].text).join('\n');
const delivered = (id = 'one') => ({ok: true, execution_status: 'guidance_delivered',
  capability_id: `cap_${id}`, version_id: `ver_${id}`, invocation_id: `inv_${id}`, content_hash: 'sha256:' + 'a'.repeat(64)});
const runResult = (h, body = delivered()) => h.result({name: 'mcp__toolseed__toolbox_run', value: {structuredContent: body}});

test('failed then returned tool prompts learning in an existing step, once', async () => {
  const h = harness(); await h.pre(); h.progress();
  const decision = await h.pre();
  assert.equal(decision.startsRequestSeries, true);
  assert.match(text(decision), /曾出现失败，随后有工具正常返回/);
  assert.match(text(decision), /pitfalls/);
  assert.match(text(decision), /tool_recipes/);
  assert.deepEqual(h.records.map(r => r.stage), ['learning_proposed', 'learning_prompted']);
  assert.equal((await h.pre()).messages.length, 0);
});

test('ordinary one-off actions and failures alone do not require learning', async () => {
  for (const isError of [true, false]) {
    const h = harness(); await h.pre();
    for (let i = 0; i < 8; i++) h.result({isError});
    assert.equal((await h.pre()).messages.length, 0);
  }
});

test('multi-tool sequence can prompt without errors', async () => {
  const h = harness(); await h.pre();
  for (const name of ['inspect', 'edit', 'export', 'inspect', 'edit', 'export']) h.result({name});
  assert.match(text(await h.pre()), /已完成一段多工具操作/);
});

test('user follow-up cue survives turn boundary without retaining the user text', async () => {
  const h = harness(); await h.pre(); h.result(); h.message();
  const decision = await h.pre({turn: 2});
  assert.match(text(decision), /收到用户补充/);
  assert.doesNotMatch(text(decision), /SENSITIVE/);
  assert.doesNotMatch(JSON.stringify(h.records), /SENSITIVE/);
  assert.equal((await h.pre({turn: 3})).messages.length, 0);
});

test('plugin messages and another agent do not create user-correction signals', async () => {
  const h = harness(); await h.pre(); h.result(); h.message('toolseed-opportunity');
  h.result({isError: true, subject: {id: 'different'}});
  h.result();
  assert.equal((await h.pre()).messages.length, 0);
});

test('structured failure inside a returned envelope is not mistaken for progress', async () => {
  for (const value of [{ok: false}, {exit_code: 1}, {structuredContent: {ok: false}}, {isError: true}]) {
    const h = harness(); await h.pre();
    h.result({isError: true}); h.result({value});
    assert.equal((await h.pre()).messages.length, 0);
    h.result({value: {ok: true}});
    assert.equal((await h.pre()).messages.length, 1);
  }
});

test('duplicate execution, cancellation, PTC transport and own tool failures are excluded', async () => {
  const h = harness(); await h.pre();
  const token = Symbol();
  h.result({isError: true, token}); h.result({token});
  assert.equal((await h.pre()).messages.length, 0);
  const clean = harness(); await clean.pre();
  for (const options of [{name: learnName, isError: true}, {name: 'run_code', isError: true},
    {isError: true, code: 'ABORTED'}]) clean.result(options);
  clean.result();
  assert.equal((await clean.pre()).messages.length, 0);
});

test('accepted proactive learning suppresses a redundant hint; rejected learning is not stored', async () => {
  const h = harness(); await h.pre(); h.progress();
  h.result({name: learnName, value: {structuredContent: {status: 'accepted', capability_id: 'cap_test'}}});
  assert.equal((await h.pre()).messages.length, 0);
  const failed = harness(); await failed.pre(); failed.progress();
  failed.result({name: learnName, value: {structuredContent: {ok: false, error: {code: 'INVALID_ARGUMENT'}}}});
  assert.equal((await failed.pre()).messages.length, 1);
});

test('denial, visibility and abort preserve host policy without consuming the cue', async () => {
  const h = harness(); await h.pre(); h.progress();
  const denied = {kind: 'deny', reason: 'host policy'};
  assert.equal(await h.pre({decision: denied}), denied);
  h.setVisible(false); assert.equal((await h.pre()).messages.length, 0);
  h.setVisible(true); assert.equal((await h.pre()).messages.length, 1);
  const stopped = harness(); await stopped.pre(); stopped.progress(); stopped.controller.abort();
  assert.equal((await stopped.pre()).messages.length, 0);
});

test('proposed context is distinct from a committed prompt', async () => {
  const h = harness(); await h.pre(); h.progress(); await h.pre({commit: false});
  assert.deepEqual(h.records.map(r => r.stage), ['learning_proposed']);
});

test('bounded observation and disposal cannot revive old signals', async () => {
  const h = harness(); await h.pre();
  for (let i = 0; i < 256; i++) h.result({name: 'mcp__toolseed__toolbox_stats'});
  h.progress(); assert.equal((await h.pre()).messages.length, 0);
  const stopped = harness(); await stopped.pre(); stopped.progress(); stopped.effects[0]()();
  assert.equal((await stopped.pre()).messages.length, 0);
  const gone = harness(); await gone.pre(); gone.progress();
  gone.events.get('agent/disposed')({agent: gone.agent});
  assert.equal((await gone.pre()).messages.length, 0);
});

test('guidance alone is not reuse; subsequent activity offers a bound update', async () => {
  const h = harness(); await h.pre(); runResult(h);
  assert.equal((await h.pre()).messages.length, 0);
  h.result();
  const decision = await h.pre();
  assert.match(text(decision), /复用后更新提示/);
  assert.match(text(decision), /inv_one/);
  assert.match(text(decision), /not_applied/);
  assert.match(text(decision), /先后关系不证明采用/);
  assert.deepEqual(h.records.map(r => r.stage), ['reuse_learning_proposed', 'reuse_learning_prompted']);
  h.result(); assert.equal((await h.pre()).messages.length, 0);
});

test('matching accepted feedback suppresses the update but a rejected call does not', async () => {
  const h = harness(); await h.pre(); runResult(h); h.result();
  h.result({name: learnName, value: {structuredContent: {status: 'accepted', capability_id: 'cap_one',
    learning_action: 'observation_added', reuse_source: delivered()}}});
  assert.equal((await h.pre()).messages.length, 0);
  const rejected = harness(); await rejected.pre(); runResult(rejected); rejected.result();
  rejected.result({name: learnName, value: {structuredContent: {ok: false, error: {code: 'REUSE_BINDING_MISMATCH'}}}});
  assert.match(text(await rejected.pre()), /复用后更新提示/);
});

test('feedback for one delivered method does not close another and links stay bounded', async () => {
  const h = harness(); await h.pre();
  for (let i = 0; i < 6; i++) runResult(h, delivered(String(i)));
  h.result();
  h.result({name: learnName, value: {structuredContent: {status: 'accepted', capability_id: 'cap_0', reuse_source: delivered('0')}}});
  const message = text(await h.pre());
  assert.doesNotMatch(message, /inv_0|inv_4|inv_5/);
  assert.match(message, /inv_1/); assert.match(message, /inv_3/);
});

test('failed or malformed deliveries and unrelated agents do not open reuse updates', async () => {
  const h = harness(); await h.pre();
  runResult(h, {...delivered(), ok: false, error: {code: 'CAPABILITY_NOT_READY'}});
  runResult(h, {...delivered(), content_hash: 'PRIVATE HASH'});
  h.result({name: 'mcp__toolseed__toolbox_run', subject: {id: 'other'}, value: {structuredContent: delivered()}});
  h.result(); assert.equal((await h.pre()).messages.length, 0);
});

test('reuse update has one separate opportunity after an earlier general learning cue', async () => {
  const h = harness(); await h.pre(); h.progress(); await h.pre();
  runResult(h); h.result();
  assert.match(text(await h.pre()), /复用后更新提示/);
  h.result(); assert.equal((await h.pre()).messages.length, 0);
  assert.equal(h.records.filter(r => r.stage.endsWith('_proposed')).length, 2);
});

test('user correction can carry a delivered-method link into the next turn only', async () => {
  const h = harness(); await h.pre(); runResult(h); h.result(); await h.pre(); h.message();
  assert.match(text(await h.pre({turn: 2})), /inv_one/);
  assert.equal((await h.pre({turn: 3})).messages.length, 0);
});

test('manual use followed by user correction retains the exact delivery without tool activity', async () => {
  const h = harness(); await h.pre(); runResult(h); h.message();
  const decision = await h.pre({turn: 2});
  assert.match(text(decision), /复用后更新提示/);
  assert.match(text(decision), /inv_one/);
  assert.match(text(decision), /先后关系不证明采用/);
  assert.doesNotMatch(text(decision), /SENSITIVE|userFeedback|activity/);
  assert.equal(h.records[0].rule, 'user_feedback_after_guidance');
  assert.equal((await h.pre({turn: 2})).messages.length, 0);
  assert.equal((await h.pre({turn: 3})).messages.length, 0);
});

test('a user follow-up never reopens acknowledged feedback', async () => {
  const h = harness(); await h.pre(); runResult(h);
  h.result({name: learnName, value: {structuredContent: {status: 'accepted', capability_id: 'cap_one',
    learning_action: 'observation_added', reuse_source: delivered()}}});
  h.message();
  assert.equal((await h.pre({turn: 2})).messages.length, 0);
});

test('manual user correction preserves the reuse cue through host denial or hidden tools', async () => {
  const h = harness(); await h.pre(); runResult(h); h.message();
  const denied = {kind: 'deny'};
  assert.equal(await h.pre({turn: 2, decision: denied}), denied);
  h.setVisible(false); assert.equal((await h.pre({turn: 2})).messages.length, 0);
  h.setVisible(true); assert.match(text(await h.pre({turn: 2})), /inv_one/);
});

test('hidden learn tool, host denial and cancellation preserve pending reuse cue', async () => {
  const h = harness(); await h.pre(); runResult(h); h.result();
  h.setVisible(false); assert.equal((await h.pre()).messages.length, 0);
  h.setVisible(true); const denied = {kind: 'deny'};
  assert.equal(await h.pre({decision: denied}), denied);
  h.controller.abort(); assert.equal((await h.pre()).messages.length, 0);
});
