import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {handleWorkflow} from '../src/workflow.mjs';
import {compactCards, createRecallSearch, taskQuery} from '../src/recall.mjs';
import {mergeHooksConfig, removeHooksConfig} from '../src/install.mjs';
import {sha256} from '../src/state.mjs';

const base = fileURLToPath(new URL('../../../tests/.data/', import.meta.url));
mkdirSync(base, {recursive: true});
const card = {capability_id: 'cap_one', version_id: 'ver_one', content_hash: 'sha256:' + 'a'.repeat(64),
  kind: 'procedure', name: 'merge configs', description: 'Check explicit overrides', when_to_use: 'config overrides',
  not_for: [], content_excerpt: 'Useful candidate material', recall_match: {task_terms: ['config']},
  applicability_check: {status: 'unknown', unknown_fields: ['required_tools']}};
const delivery = {ok: true, execution_status: 'guidance_delivered', capability_id: 'cap_one', version_id: 'ver_one',
  content_hash: card.content_hash, invocation_id: 'inv_one'};
const fixture = (options = {}) => {
  const root = mkdtempSync(join(base, 'codex-workflow-'));
  const opts = {stateDir: join(root, 'state'), logDir: join(root, 'logs'), mcpServer: 'toolseed',
    search: async () => ({results: []}), ...options};
  let sequence = 0;
  return {root, opts, event: changes => ({session_id: 's', turn_id: 't', hook_event_name: 'PostToolUse',
    tool_name: 'Bash', tool_use_id: 'use-' + ++sequence, tool_response: '', ...changes}),
    run(input) {return handleWorkflow(input, opts);},
    state() {return JSON.parse(readFileSync(join(opts.stateDir, `workflow-${sha256('s').slice(0,32)}.json`), 'utf8'));},
    close() {assert.ok(resolve(root).startsWith(resolve(base))); rmSync(root, {recursive: true, force: true});}};
};
const context = result => result.hookSpecificOutput?.additionalContext ?? '';

test('task prompt executes a bounded scoped query and returns actual candidate material', async () => {
  const calls = [], f = fixture({search: async (...args) => {calls.push(args); return {results: [card]};}});
  try {
    const result = await f.run(f.event({hook_event_name: 'UserPromptSubmit', prompt: 'repair layered config overrides'}));
    assert.match(context(result), /cap_one/); assert.match(context(result), /不可信/);
    assert.deepEqual(calls[0][1].harnesses, ['codex']);
    assert.equal(calls[0][1].required_tools_complete, false);
    assert.equal(result.hookSpecificOutput.hookEventName, 'UserPromptSubmit');
  } finally {f.close();}
});

test('greetings, empty results and incompatible cards produce no context', async () => {
  const f = fixture({search: async () => ({results: [{...card, applicability_check: {status: 'incompatible'}}]})});
  try {
    assert.deepEqual(await f.run(f.event({hook_event_name: 'UserPromptSubmit', prompt: 'hello thanks'})), {});
    assert.deepEqual(await f.run(f.event({hook_event_name: 'UserPromptSubmit', prompt: 'repair config'})), {});
    assert.equal(compactCards({results: [{...card, content_hash: 'wrong'}]}).length, 0);
  } finally {f.close();}
});

test('queries, versions and prompt retries deduplicate with a three-search cap', async () => {
  let calls = 0;
  const f = fixture({search: async () => {calls++; return {results: [card]};}});
  try {
    const prompt = f.event({hook_event_name: 'UserPromptSubmit', prompt: 'repair config'});
    await f.run(prompt); assert.deepEqual(await f.run(prompt), {});
    for (let i = 0; i < 8; i++) await f.run(f.event({tool_name: 'mcp__probe__check_' + i, tool_response: {error: {code: 'BROKEN'}}}));
    assert.equal(calls, 3); assert.equal(f.state().surfaced.length, 1);
  } finally {f.close();}
});

test('a known error recalls once; shell text is never interpreted as an error', async () => {
  const queries = [], f = fixture({search: async (...args) => {queries.push(args); return {results: []};}});
  try {
    await f.run(f.event({tool_response: 'error: SECRET_ERROR'}));
    assert.equal(queries.length, 0);
    const failure = {tool_response: {error: {code: 'PROBE_FAIL'}}};
    await f.run(f.event(failure)); await f.run(f.event(failure));
    assert.equal(queries.length, 1); assert.deepEqual(queries[0][1].recall.error_codes, ['PROBE_FAIL']);
  } finally {f.close();}
});

test('throwing and timed-out queries fail open and disable recall for the turn', async () => {
  for (const search of [() => {throw new Error('private details');}, () => new Promise(() => {})]) {
    const f = fixture({search, timeoutMs: 10});
    try {
      const result = await f.run(f.event({hook_event_name: 'UserPromptSubmit', prompt: 'repair config'}));
      assert.deepEqual(result, {}); assert.equal(f.state().recallFailed, true);
      assert.equal(f.state().searches, 1);
    } finally {f.close();}
  }
});

test('six returned operations across three tools offer one optional learning cue', async () => {
  const f = fixture();
  try {
    const results = [];
    for (let i = 0; i < 8; i++) results.push(await f.run(f.event({tool_name: ['Bash', 'apply_patch', 'inspect'][i % 3]})));
    assert.equal(results.filter(x => context(x).includes('经验提炼提示')).length, 1);
    assert.match(context(results[5]), /toolbox_learn/);
    assert.match(context(results[5]), /不要为积累而积累/);
  } finally {f.close();}
});

test('a failure followed by a return offers learning without claiming success', async () => {
  const f = fixture();
  try {
    assert.deepEqual(await f.run(f.event({tool_response: {error: {code: 'FAIL'}}})), {});
    const result = await f.run(f.event());
    assert.match(context(result), /经验提炼提示/); assert.match(context(result), /有工具正常返回/);
  } finally {f.close();}
});

test('delivery alone does not prove use; later activity carries exact reuse binding', async () => {
  const f = fixture();
  try {
    assert.deepEqual(await f.run(f.event({tool_name: 'mcp__toolseed__toolbox_run', tool_response: delivery})), {});
    const result = await f.run(f.event());
    assert.match(context(result), /inv_one/); assert.match(context(result), /不证明方法已经采用/);
    assert.match(context(result), /部分采用或未采用/);
    assert.deepEqual(await f.run(f.event()), {});
  } finally {f.close();}
});

test('accepted matching feedback closes only its own source delivery', async () => {
  const f = fixture();
  try {
    for (const id of ['one','two']) await f.run(f.event({tool_name: 'mcp__toolseed__toolbox_run',
      tool_response: {...delivery, invocation_id: 'inv_' + id}}));
    await f.run(f.event({tool_name: 'mcp__toolseed__toolbox_learn', tool_response: {status: 'accepted',
      capability_id: delivery.capability_id, reuse_source: {...delivery, content_hash: 'wrong'}}}));
    assert.equal(f.state().learning.deliveries.length, 2);
    await f.run(f.event({tool_name: 'mcp__toolseed__toolbox_learn', tool_response: {status: 'accepted',
      capability_id: delivery.capability_id, reuse_source: delivery}}));
    assert.deepEqual(f.state().learning.deliveries.map(r => r.invocation_id), ['inv_two']);
  } finally {f.close();}
});

test('failed, malformed and duplicate guidance cannot fabricate reuse', async () => {
  const f = fixture();
  try {
    for (const body of [{...delivery, content_hash: 'bad'}, {isError: true, structuredContent: delivery}])
      await f.run(f.event({tool_name: 'mcp__toolseed__toolbox_run', tool_response: body}));
    assert.equal(f.state().learning.deliveries.length, 0);
    for (let i=0;i<5;i++) await f.run(f.event({tool_name: 'mcp__toolseed__toolbox_run', tool_response: delivery}));
    assert.equal(f.state().learning.deliveries.length, 1);
  } finally {f.close();}
});

test('new user follow-up can carry a bounded delivery link across turns', async () => {
  const f = fixture();
  try {
    await f.run(f.event({tool_name: 'mcp__toolseed__toolbox_run', tool_response: delivery}));
    await f.run(f.event());
    const result = await f.run(f.event({turn_id: 'next', hook_event_name: 'UserPromptSubmit', prompt: 'Actually the exporter condition changed'}));
    assert.match(context(result), /inv_one/);
    assert.equal(f.state().learning.deliveries.length, 1);
  } finally {f.close();}
});

test('user correction can refer to a delivery even without intervening tool activity', async () => {
  const f = fixture();
  try {
    await f.run(f.event({tool_name: 'mcp__toolseed__toolbox_run', tool_response: delivery}));
    const result = await f.run(f.event({turn_id: 'correction', hook_event_name: 'UserPromptSubmit',
      prompt: 'This method does not cover the exporter I am using.'}));
    assert.ok(context(result).includes('inv_one'));
    assert.ok(context(result).includes('这不证明方法已经采用'));
    assert.equal(f.state().learning.deliveries.length, 1);
  } finally {f.close();}
});

test('interrupt aborts an in-flight query and suppresses late context', async () => {
  let started;
  const ready = new Promise(resolve => {started=resolve;});
  const f = fixture({timeoutMs: 500, search: () => {started(); return new Promise(() => {});}});
  try {
    const pending = f.run(f.event({hook_event_name: 'UserPromptSubmit', prompt: 'repair config'}));
    await ready;
    const interrupt = f.run(f.event({hook_event_name: 'Interrupt'}));
    assert.deepEqual(await pending, {}); assert.deepEqual(await interrupt, {});
    assert.deepEqual(await f.run(f.event()), {});
    assert.equal(f.state().canceled, true);
  } finally {f.close();}
});

test('session end closes pending reuse without continuing an idle model', async () => {
  const f = fixture();
  try {
    await f.run(f.event({tool_name: 'mcp__toolseed__toolbox_run', tool_response: delivery}));
    assert.deepEqual(await f.run(f.event({hook_event_name: 'SessionEnd', turn_id: undefined})), {});
    assert.equal(f.state().learning.deliveries.length, 0); assert.equal(f.state().canceled, true);
  } finally {f.close();}
});

test('state and logs exclude raw prompts, arguments, results and candidate bodies', async () => {
  const f = fixture({search: async () => ({results: [card]})});
  try {
    await f.run(f.event({hook_event_name: 'UserPromptSubmit', prompt: 'repair config password=NEVER_STORE_SECRET'}));
    await f.run(f.event({tool_input: {private: 'NEVER_STORE_ARGUMENT'}, tool_response: 'NEVER_STORE_RESULT'}));
    const data = readFileSync(join(f.opts.stateDir, `workflow-${sha256('s').slice(0,32)}.json`),'utf8')
      + readFileSync(join(f.opts.logDir,'events.jsonl'),'utf8');
    for (const value of ['NEVER_STORE_SECRET','NEVER_STORE_ARGUMENT','NEVER_STORE_RESULT',card.content_excerpt]) assert.equal(data.includes(value),false);
    assert.equal(taskQuery('fix config ```secret code``` api_key="hidden" /some/path Bearer secret_token').includes('secret'),false);
  } finally {f.close();}
});

test('legacy workflow state retains validated pending references and drops obsolete fields', async () => {
  const f = fixture({recall: false});
  try {
    await f.run(f.event({tool_name: 'mcp__toolseed__toolbox_run', tool_response: delivery}));
    const path = join(f.opts.stateDir, `workflow-${sha256('s').slice(0,32)}.json`);
    const current = JSON.parse(readFileSync(path, 'utf8'));
    const legacy = {...current, v: 1, reuses: [{...delivery}, {...delivery, invocation_id: 'malformed'}],
      hadFailure: true, returned: true, obsolete: 'NEVER_RETAIN_LEGACY_EXTRA'};
    delete legacy.learning;
    writeFileSync(path, JSON.stringify(legacy));
    const result = await f.run(f.event({turn_id: 'next', hook_event_name: 'UserPromptSubmit', prompt: 'A user correction'}));
    assert.match(context(result), /inv_one/);
    const restored = f.state();
    assert.equal(restored.v, 2);
    assert.equal(restored.learning.deliveries.length, 1);
    assert.equal(JSON.stringify(restored).includes('NEVER_RETAIN'), false);
    assert.equal(restored.hadFailure, undefined);
  } finally {f.close();}
});

test('read-only bridge fixes operation and uses explicit arguments without a shell', async () => {
  const f = fixture();
  try {
    writeFileSync(join(f.root,'toolseed.sqlite3'),'fixture');
    let invocation;
    const search = createRecallSearch({python:'fixed-python',dataDir:f.root}, async (...args) => {invocation=args;return {stdout:'{"results":[]}'}});
    await search('$(not-a-command)',{recall:{phase:'task'}});
    assert.equal(invocation[0],'fixed-python');assert.equal(invocation[1][5],'search');
    assert.equal(invocation[2].shell,false);assert.equal(invocation[2].windowsHide,true);
    assert.equal(invocation[1].at(-1),'--read-only');
    assert.deepEqual(JSON.parse(invocation[1][6]).query,'$(not-a-command)');
    assert.deepEqual(await createRecallSearch({python:'python',dataDir:join(f.root,'absent')})('config',{}),undefined);
  } finally {f.close();}
});

test('all four hooks merge and uninstall idempotently without deleting others', () => {
  const original={hooks:{UserPromptSubmit:[{hooks:[{command:'user hook'}]}],PostToolUse:[],SessionEnd:[{hooks:[{command:'user end hook'}]}]}};
  const merged=mergeHooksConfig(original,'node toolseed-hook.mjs');
  assert.equal(merged.config.hooks.UserPromptSubmit.length,2);
  assert.equal(merged.config.hooks.Interrupt.length,1);
  assert.deepEqual(mergeHooksConfig(merged.config,'node toolseed-hook.mjs').config,merged.config);
  const removed=removeHooksConfig(merged.config);
  assert.equal(removed.removed,4);
  assert.equal(removed.config.hooks.UserPromptSubmit[0].hooks[0].command,'user hook');
  assert.equal(removed.config.hooks.SessionEnd[0].hooks[0].command,'user end hook');
});
