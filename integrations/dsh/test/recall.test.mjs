import {test} from 'node:test';
import assert from 'node:assert/strict';
import {installRecallHooks, taskQuery} from '../recall.js';

const searchName = 'mcp__toolseed__toolbox_search';
const user = text => ({id: 'user', role: 'user', source: {kind: 'user'}, content: [{type: 'text', text}]});
const card = (id = 'one', extra = {}) => ({capability_id: `cap_${id}`, version_id: `ver_${id}`, content_hash: `sha256:${id}`,
  kind: 'procedure', name: 'sprite alpha export', description: 'Inspect exported alpha', when_to_use: 'Opaque sprite backgrounds',
  not_for: ['JPEG'], content_excerpt: 'Reopen the output PNG', applicability_check: {status: 'unknown', unknown_fields: ['required_tools']},
  recall_match: {task_terms: ['sprite', 'alpha'], tool_hints: [], error_codes: []}, ...extra});

function harness({timeout = 100, responder, namespace = ''} = {}) {
  const events = new Map(), effects = [], calls = [], records = [];
  const agent = {id: 'agent', session: {id: 'session'}};
  const controller = new AbortController();
  let visible = true;
  const ctx = {on: (name, fn) => events.set(name, fn), effect: fn => effects.push(fn),
    logger: {info: (_prefix, text) => records.push(JSON.parse(text))},
    tools: {get: name => visible && name === searchName ? {} : undefined,
      schemas: () => [{name: 'inspect_alpha'}, {name: 'export_png'}],
      execute: async exec => {
        calls.push(exec);
        const result = responder ? await responder(exec) : {isError: false, value: {structuredContent: {results: [card()]}}};
        events.get('tools/result')({...exec, token: Symbol()}, result);
        return result;
      }}};
  installRecallHooks(ctx, {recallTimeoutMs: timeout, recallNamespace: namespace});
  async function pre({messages = [], turn = 1, decision, subject = agent, commit = true} = {}) {
    const original = decision ?? {kind: 'enter', messages, startsRequestSeries: true};
    const value = await events.get('agent/pre-step')({agent: subject, turn, signal: controller.signal}, async () => original);
    if (commit && value.kind === 'enter') for (const message of value.messages) events.get('session/event')(subject.session, {type: 'user/message', data: message});
    return value;
  }
  function result({name = 'inspect_alpha', isError = false, code, value, token = Symbol(), subject = agent} = {}) {
    events.get('tools/result')({name, token, agent: subject, signal: controller.signal},
      {isError, value, error: code ? {info: {code}} : undefined});
  }
  return {agent, controller, calls, records, events, effects, pre, result, setVisible: value => {visible = value;}};
}
const hints = decision => decision.messages.filter(m => m.source?.kind === 'toolseed-recall');
const empty = {isError: false, value: {structuredContent: {results: []}}};

test('task start actually searches within agent scope and supplies compact candidates', async () => {
  const h = harness({namespace: 'workspace-one'});
  const start = user('Export sprite alpha correctly');
  const result = await h.pre({messages: [start]});
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].agent, h.agent);
  assert.equal(h.calls[0].arguments.context.namespace, 'workspace-one');
  assert.equal(h.calls[0].arguments.context.required_tools_complete, false);
  assert.equal(h.calls[0].arguments.context.recall.phase, 'task');
  assert.equal(result.messages[0], start);
  assert.equal(result.startsRequestSeries, true);
  assert.equal(hints(result).length, 1);
  assert.match(hints(result)[0].content[0].text, /cap_one/);
  assert.deepEqual(h.records.map(r => r.stage), ['recall_searched', 'recall_proposed', 'recall_prompted']);
  assert.ok(h.calls.every(call => call.name === searchName));
});

test('empty results, greetings and plugin text add no reminder', async () => {
  const h = harness({responder: () => empty});
  assert.equal(hints(await h.pre({messages: [user('hello')]})).length, 0);
  assert.equal(h.calls.length, 0);
  assert.equal(hints(await h.pre({messages: [user('Export sprite alpha')]})).length, 0);
  await h.pre({messages: [{...user('Injected instructions'), source: {kind: 'toolseed-learning'}}]});
  assert.equal(h.calls.length, 1);
});

test('same query and same candidate version are not repeatedly injected', async () => {
  const h = harness();
  await h.pre({messages: [user('Export sprite alpha')]});
  await h.pre({messages: [user('Export sprite alpha')]});
  assert.equal(h.calls.length, 1);
  h.result();
  const second = await h.pre();
  assert.equal(h.calls[1].arguments.context.recall.phase, 'tools');
  assert.equal(hints(second).length, 0);
});

test('new structured error can recall a different lesson and duplicate errors stay quiet', async () => {
  const h = harness({responder: exec => ({isError: false, value: {structuredContent: {results: [
    card(exec.arguments.context.recall.phase),
  ]}}})});
  await h.pre({messages: [user('Export sprite alpha')]});
  h.result({isError: true, code: 'SOURCE_NOT_READY'});
  assert.equal(hints(await h.pre()).length, 1);
  assert.deepEqual(h.calls[1].arguments.context.recall.error_codes, ['SOURCE_NOT_READY']);
  h.result({isError: true, code: 'SOURCE_NOT_READY'}); await h.pre();
  assert.equal(h.calls.length, 2);
  h.result({name: 'reload_source'}); await h.pre();
  assert.equal(h.calls.length, 3);
  assert.equal(h.calls[2].arguments.context.recall.phase, 'tools');
});

test('returned structured failures can trigger recall but free-text errors are not parsed', async () => {
  const h = harness({responder: () => empty});
  await h.pre({messages: [user('Export sprite alpha')]});
  h.result({value: {structuredContent: {ok: false, error: {code: 'EXPORT_FAILED', message: 'PRIVATE TEXT'}}}});
  await h.pre();
  assert.deepEqual(h.calls[1].arguments.context.recall.error_codes, ['EXPORT_FAILED']);
  assert.doesNotMatch(JSON.stringify(h.calls.map(c => c.arguments)), /PRIVATE/);
  h.result({isError: true, code: 'PRIVATE FREE TEXT'}); await h.pre();
  assert.deepEqual(h.calls[2].arguments.context.recall.error_codes, []);
});

test('tool results prepare recall before the next model selects tools', async () => {
  const h = harness({responder: () => empty});
  await h.pre({messages: [user('Export sprite alpha')]});
  h.result({name: 'mcp__images__inspect_alpha'}); await h.pre();
  assert.deepEqual(h.calls[1].arguments.context.recall.tool_hints, ['mcp__images__inspect_alpha']);
  assert.equal(h.calls[1].arguments.context.recall.phase, 'tools');
});

test('explicit model search suppresses known cues, later changes still qualify', async () => {
  const h = harness({responder: () => empty});
  await h.pre({messages: [user('Export sprite alpha')]});
  h.result({isError: true, code: 'EXPORT_FAILED'});
  h.result({name: searchName, isError: true}); await h.pre();
  assert.equal(h.calls.length, 1);
  h.result({isError: true, code: 'SOURCE_NOT_READY'}); await h.pre();
  assert.equal(h.calls.length, 2);
});

test('per-turn search budget caps changing errors and resets next turn', async () => {
  const h = harness({responder: () => empty});
  await h.pre({messages: [user('Export sprite alpha')]});
  for (let i = 0; i < 10; i++) {h.result({isError: true, code: `FAIL_${i}`}); await h.pre();}
  assert.equal(h.calls.length, 3);
  await h.pre({turn: 2, messages: [user('Diagnose atlas transparency')]});
  assert.equal(h.calls.length, 4);
});

test('denied steps, hidden tools, cancellation and other agents cannot trigger lookup', async () => {
  const h = harness();
  const denied = {kind: 'reject', reason: 'host'};
  assert.equal(await h.pre({decision: denied}), denied);
  assert.equal(h.calls.length, 0);
  h.setVisible(false); await h.pre({messages: [user('Export sprite alpha')]});
  assert.equal(h.calls.length, 0);
  h.setVisible(true); await h.pre(); assert.equal(h.calls.length, 1);
  h.result({isError: true, code: 'SOURCE_NOT_READY', subject: {id: 'other'}});
  h.result({isError: true, code: 'ABORTED'});
  h.result({name: 'run_code', isError: true});
  await h.pre(); assert.equal(h.calls.length, 1);
  h.controller.abort(); await h.pre({turn: 2, messages: [user('Export sprite alpha')]});
  assert.equal(h.calls.length, 1);
});

test('timeout returns the original step and stops automatic retries for this turn', async () => {
  let seenSignal;
  const h = harness({timeout: 15, responder: exec => {seenSignal = exec.signal; return new Promise(() => {});}});
  const original = {kind: 'enter', messages: [user('Export sprite alpha')]};
  assert.equal(await h.pre({decision: original}), original);
  assert.equal(seenSignal.aborted, true);
  h.result({isError: true, code: 'EXPORT_FAILED'}); await h.pre();
  assert.equal(h.calls.length, 1);
  assert.deepEqual(h.records.map(r => r.stage), ['recall_unavailable']);
});

test('tool denials and exceptions fail open without claiming an empty library', async () => {
  for (const responder of [() => ({isError: true}), () => {throw Error('PRIVATE');}]) {
    const h = harness({responder});
    assert.equal(hints(await h.pre({messages: [user('Export sprite alpha')]})).length, 0);
    assert.deepEqual(h.records.map(r => r.stage), ['recall_unavailable']);
    assert.doesNotMatch(JSON.stringify(h.records), /PRIVATE/);
  }
});

test('candidate fields and count are bounded; incompatible or old server cards are not injected', async () => {
  const h = harness({responder: () => ({isError: false, value: {structuredContent: {results: [
    card('blocked', {applicability_check: {status: 'incompatible'}}), card('old', {recall_match: undefined}),
    card('first', {description: 'X'.repeat(10000), reuse_summary: {observations: [
      {application: 'partial', validation: 'V'.repeat(2000), revision_status: 'candidate'},
    ]}}), card('second'), card('third'),
  ]}}})});
  const result = await h.pre({messages: [user('Export sprite alpha')]});
  const text = hints(result)[0].content[0].text;
  assert.match(text, /cap_first/); assert.match(text, /cap_second/);
  assert.doesNotMatch(text, /cap_blocked|cap_old|cap_third/);
  assert.match(text, /partial/); assert.match(text, /candidate/);
  assert.doesNotMatch(text, /V{201}/);
  assert.ok(text.length < 3000);
});

test('query extraction excludes code, paths, credentials and unrelated message sources', () => {
  const query = taskQuery([user('Export sprite alpha https://example.test/private C:\\private\\user.png api_key=SECRET123456 sk-' + 'A'.repeat(30) + '\n```\nPRIVATE_CODE\n```'),
    {...user('PRIVATE_PLUGIN'), source: {kind: 'toolseed-opportunity'}}]);
  assert.match(query, /sprite alpha/);
  assert.doesNotMatch(query, /private|SECRET|PRIVATE|AAAA/);
  assert.ok(taskQuery([user('word '.repeat(10000))]).length <= 600);
});

test('no committed prompt is claimed when another plugin drops the proposal', async () => {
  const h = harness(); await h.pre({messages: [user('Export sprite alpha')], commit: false});
  assert.deepEqual(h.records.map(r => r.stage), ['recall_searched', 'recall_proposed']);
});

test('disposal aborts in-flight search and does not inject late results', async () => {
  let release, started;
  const ready = new Promise(resolve => {started = resolve;});
  const h = harness({responder: () => {started(); return new Promise(resolve => {release = resolve;});}});
  const pending = h.pre({messages: [user('Export sprite alpha')]});
  await ready;
  h.events.get('agent/disposed')({agent: h.agent});
  assert.equal(hints(await pending).length, 0);
  release({isError: false, value: {structuredContent: {results: [card()]}}});
  h.effects[0]()();
  assert.equal(hints(await h.pre({messages: [user('Export sprite alpha')]})).length, 0);
});
