import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, readFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {
  extractStructuredFailure,
  extractToolseedKind,
  handlePostToolUse,
  opportunityHint,
  reducePostToolUse,
  toolseedBody,
} from '../src/opportunities.mjs';
import {emptyState} from '../src/state.mjs';

function input(overrides = {}) {
  return {
    hook_event_name: 'PostToolUse',
    session_id: 'session-1',
    turn_id: 'turn-1',
    tool_name: 'shell',
    tool_use_id: `use-${Math.random().toString(16).slice(2)}`,
    tool_response: {exitCode: 1},
    ...overrides,
  };
}

function reduceAll(items, options = {}) {
  let state = emptyState('session-1', 'turn-1');
  const results = [];
  for (const item of items) {
    const result = reducePostToolUse(state, item, options);
    state = result.state;
    results.push(result);
  }
  return {state, results};
}

test('third distinct structured failure emits one L1 hint', () => {
  const {results} = reduceAll([input(), input(), input()]);
  assert.equal(results[0].hint, undefined);
  assert.equal(results[1].hint, undefined);
  assert.match(results[2].hint, /ToolSeed opportunity/);
  assert.match(results[2].hint, /mcp__toolseed__toolbox_search/);
  assert.equal(results[2].events[0].stage, 'signal_detected');
  assert.equal(results[2].events[1].stage, 'hint_emitted');
});

test('different structured codes and tools do not combine', () => {
  const differentCode = reduceAll([
    input({tool_response: {exitCode: 1}}),
    input({tool_response: {exitCode: 1}}),
    input({tool_response: {exitCode: 2}}),
  ]);
  assert.equal(differentCode.results[2].hint, undefined);
  const differentTool = reduceAll([
    input({tool_name: 'shell'}),
    input({tool_name: 'shell'}),
    input({tool_name: 'unified_exec'}),
  ]);
  assert.equal(differentTool.results[2].hint, undefined);
});

test('duplicate execution tokens are counted once', () => {
  const repeated = input({tool_use_id: 'same-token'});
  const {results} = reduceAll([repeated, repeated, repeated]);
  assert.equal(results[2].hint, undefined);
});

test('ToolSeed calls are observed, not counted as blockers', () => {
  let state = emptyState('session-1', 'turn-1');
  let hint;
  for (let index = 0; index < 3; index += 1) {
    const result = reducePostToolUse(state, input({
      tool_name: 'mcp__toolseed__toolbox_search',
      tool_response: {isError: true, structuredContent: {error: {code: 'INVALID_ARGUMENT'}}},
    }));
    state = result.state;
    hint = result.hint;
    assert.equal(result.events[0].stage, 'search_failed');
  }
  assert.equal(hint, undefined);
  assert.equal(state.groups['mcp__toolseed__toolbox_search:INVALID_ARGUMENT'], undefined);
});

test('post-signal search sets search_observed without rewriting the signal', () => {
  const first = reduceAll([input(), input(), input()]);
  const signal = first.results[2];
  const observed = reducePostToolUse(signal.state, input({
    tool_name: 'mcp__toolseed__toolbox_search',
    tool_response: {structuredContent: {results: [{name: 'x'}]}},
  }));
  assert.equal(observed.state.opportunity_id, signal.state.opportunity_id);
  assert.equal(observed.state.search_observed, true);
  assert.equal(observed.events[0].stage, 'search_completed');
});

test('save and run observations use the real Core response fields', () => {
  let state = emptyState('session-1', 'turn-1');
  const saved = reducePostToolUse(state, input({
    tool_name: 'mcp__toolseed__toolbox_save',
    tool_response: {
      structuredContent: {
        status: 'accepted',
        capability_id: 'cap_abc',
        version_id: 'ver_def',
      },
    },
  }));
  state = saved.state;
  assert.equal(saved.events[0].stage, 'capability_saved');
  assert.equal(saved.events[0].capability_id, 'cap_abc');

  const duplicate = reducePostToolUse(state, input({
    tool_name: 'mcp__toolseed__toolbox_save',
    tool_response: {
      structuredContent: {
        status: 'accepted',
        duplicate: true,
        capability_id: 'cap_abc',
        version_id: 'ver_def',
      },
    },
  }));
  assert.equal(duplicate.events[0].stage, 'existing_version_returned');

  const delivered = reducePostToolUse(duplicate.state, input({
    tool_name: 'mcp__toolseed__toolbox_run',
    tool_response: {
      structuredContent: {
        execution_status: 'guidance_delivered',
        capability_id: 'cap_abc',
        version_id: 'ver_def',
      },
    },
  }));
  assert.equal(delivered.events[0].stage, 'guidance_delivered');
  assert.equal(delivered.events[0].task_outcome, undefined);
});

test('structured failure extraction never parses free text', () => {
  assert.equal(extractStructuredFailure('shell', {output: 'boom: failed'}), undefined);
  assert.equal(extractStructuredFailure('shell', {exitCode: 0}), undefined);
  assert.equal(extractStructuredFailure('shell', {exitCode: 1}), 'SHELL_EXIT_1');
  assert.equal(extractStructuredFailure('shell', {status: 'failed'}), 'TOOL_FAILED');
  assert.equal(extractStructuredFailure('shell', {error: {info: {code: 'E_TOOL'}}}), 'E_TOOL');
  assert.equal(
    extractStructuredFailure('mcp__other__tool', {structuredContent: {error: {code: 'E_MCP'}}}),
    'E_MCP',
  );
});

test('MCP text envelopes are parsed only as bounded JSON objects', () => {
  assert.deepEqual(
    toolseedBody({content: [{type: 'text', text: '{"status":"accepted"}'}]}),
    {status: 'accepted'},
  );
  assert.equal(toolseedBody({content: [{type: 'text', text: 'not json'}]}), undefined);
  assert.equal(
    toolseedBody({content: [{type: 'text', text: '{"a":'.padEnd(70_000, ' ') + '}'}]}),
    undefined,
  );
});

test('structured experience deliveries fit the bounded ToolSeed text fallback', () => {
  const body = {execution_status: 'guidance_delivered', capability_id: 'cap_fixture',
    result: {content: 'c'.repeat(32000), experience: {method: 'm'.repeat(12000),
      tool_recipes: Array.from({length: 8}, () => ({purpose: 'inspect', tool_hint: 'fixture',
        usage: 'u'.repeat(2000), check: 'verify output'})), checks: Array.from({length: 6}, () => 'x'.repeat(500))},
      applicability: {required_tools: Array.from({length: 20}, () => 'tool'.repeat(30))}}};
  const text = JSON.stringify(body);
  assert.ok(text.length > 65536 && text.length < 131072);
  assert.equal(toolseedBody({content: [{type: 'text', text}]}).capability_id, 'cap_fixture');
  assert.equal(toolseedBody(JSON.stringify({a: 'x'.repeat(131072)})), undefined);
});

test('hint construction sanitizes tool and code fields', () => {
  const hint = opportunityHint({
    searchTool: 'mcp__toolseed__toolbox_search',
    saveTool: 'mcp__toolseed__toolbox_save',
    tool: 'shell',
    code: 'E_TOOL',
  });
  assert.match(hint, /shell/);
  assert.match(hint, /E_TOOL/);
  assert.ok(!hint.includes('tool_input'));
});

test('handler persists state, emits valid hook JSON once and logs bounded stages', async () => {
  const root = mkdtempSync(join(tmpdir(), 'toolseed-codex-'));
  try {
    const options = {stateDir: join(root, 'state'), logDir: root, mcpServer: 'toolseed'};
    const outputs = [];
    for (let index = 0; index < 4; index += 1) {
      outputs.push(await handlePostToolUse(input({tool_use_id: `hook-${index}`}), options));
    }
    assert.deepEqual(outputs[0], {});
    assert.deepEqual(outputs[1], {});
    assert.equal(outputs[2].hookSpecificOutput.hookEventName, 'PostToolUse');
    assert.match(outputs[2].hookSpecificOutput.additionalContext, /ToolSeed opportunity/);
    assert.deepEqual(outputs[3], {});
    const log = readFileSync(join(root, 'events.jsonl'), 'utf8');
    assert.match(log, /"stage":"signal_detected"/);
    assert.match(log, /"stage":"hint_emitted"/);
    assert.ok(!log.includes('tool_input'));
    assert.ok(!log.includes('use-'));
  } finally {
    rmSync(root, {recursive: true, force: true});
  }
});

test('malformed or non-PostToolUse input is ignored', async () => {
  const root = mkdtempSync(join(tmpdir(), 'toolseed-codex-'));
  try {
    const options = {stateDir: join(root, 'state'), logDir: root};
    assert.deepEqual(await handlePostToolUse({}, options), {});
    assert.deepEqual(await handlePostToolUse({hook_event_name: 'Stop'}, options), {});
    assert.deepEqual(await handlePostToolUse(input({tool_name: 'bad name'}), options), {});
  } finally {
    rmSync(root, {recursive: true, force: true});
  }
});

test('toolseed server-name matching supports the public MCP name shape', () => {
  assert.equal(extractToolseedKind('mcp__toolseed__toolbox_search', 'toolseed'), 'search');
  assert.equal(extractToolseedKind('toolseed__toolbox_save', 'toolseed'), 'save');
  assert.equal(extractToolseedKind('mcp__other__toolbox_search', 'toolseed'), undefined);
});
