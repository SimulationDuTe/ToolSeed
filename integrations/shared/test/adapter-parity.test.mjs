import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {dirname, join, resolve} from 'node:path';
import {installLearningHooks} from '../../dsh/learning.js';
import {handleWorkflow} from '../../codex/src/workflow.mjs';

const ref = {ok: true, execution_status: 'guidance_delivered', capability_id: 'cap_one',
  version_id: 'ver_one', invocation_id: 'inv_one', content_hash: 'sha256:' + 'a'.repeat(64)};
const classify = text => text.includes('复用后更新提示') ? 'reuse:' + [...new Set(text.match(/inv_\w+/g))].sort().join(',')
  : text.includes('经验提炼提示') ? 'general' : '';

async function replay(trace, host) {
  const temporaryRoot = resolve(tmpdir());
  const directory = mkdtempSync(join(temporaryRoot, 'toolseed-parity-'));
  const events = new Map(), tokens = new Map(), agent = {id: 'a', session: {id: 's'}};
  const controller = new AbortController();
  const options = {stateDir: join(directory, 'state'), logDir: join(directory, 'logs'), recall: false};
  installLearningHooks({on: (name, fn) => events.set(name, fn), effect: () => {},
    tools: {get: () => ({})}, logger: {info: () => {}}});
  let sequence = 0, turn = 1;
  const pre = async () => {
    const result = await events.get('agent/pre-step')({agent, turn, signal: controller.signal},
      async () => ({kind: 'enter', messages: []}));
    for (const message of result.messages) events.get('session/event')(agent.session, {type: 'user/message', data: message});
    return result.messages.map(message => message.content[0].text).join('\n');
  };
  const codex = async changes => {
    const result = await handleWorkflow({session_id: 's', turn_id: String(turn),
      hook_event_name: 'PostToolUse', tool_name: 'inspect', tool_use_id: 'e-' + sequence, ...changes}, options);
    return result.hookSpecificOutput?.additionalContext ?? '';
  };
  try {
    if (host === 'dsh') await pre();
    else await codex({hook_event_name: 'UserPromptSubmit', prompt: ''});
    const observed = [];
    for (const event of trace) {
      sequence++;
      if (event.user) {
        if (host === 'dsh') {
          events.get('session/event')(agent.session, {type: 'user/message', data: {source: {kind: 'user'}}});
          turn++; observed.push(classify(await pre()));
        } else {turn++; observed.push(classify(await codex({hook_event_name: 'UserPromptSubmit', prompt: 'A correction'})));}
        continue;
      }
      const name = event.run ? 'mcp__toolseed__toolbox_run' : event.learn || event.save
        ? 'mcp__toolseed__toolbox_' + (event.save ? 'save' : 'learn') : event.tool ?? 'inspect';
      const body = event.run ? ref : event.learn || event.save ? {status: event.rejected ? 'rejected' : 'accepted',
        capability_id: ref.capability_id, ...(event.feedback ? {reuse_source: ref} : {})}
        : event.failed ? {error: {code: 'FAIL'}} : {ok: true};
      const id = event.id ?? String(sequence);
      if (host === 'dsh') {
        if (!tokens.has(id)) tokens.set(id, Symbol());
        events.get('tools/result')({name, token: tokens.get(id), agent, signal: controller.signal},
          {isError: Boolean(event.failed), value: {structuredContent: body}});
        observed.push(classify(await pre()));
      } else observed.push(classify(await codex({tool_name: name, tool_use_id: id,
        tool_response: name.startsWith('mcp__') ? {structuredContent: body} : body})));
    }
    return observed;
  } finally {
    controller.abort();
    assert.equal(dirname(resolve(directory)), temporaryRoot);
    rmSync(directory, {recursive: true, force: true});
  }
}

const cases = [
  ['ordered failure and return', [{}, {failed: true}, {}], ['', '', 'general']],
  ['shared multi-tool threshold', ['inspect', 'edit', 'export', 'inspect', 'edit', 'export'].map(tool => ({tool})), ['', '', '', '', '', 'general']],
  ['failures alone', Array.from({length: 8}, (_, index) => ({tool: ['inspect', 'edit', 'export'][index % 3], failed: true})), Array(8).fill('')],
  ['manual correction after guidance', [{run: true}, {user: true}], ['', 'reuse:inv_one']],
  ['accepted feedback closes its source', [{run: true}, {learn: true, feedback: true}, {user: true}], ['', '', '']],
  ['rejected feedback preserves its source', [{run: true}, {learn: true, feedback: true, rejected: true}, {}], ['', '', 'reuse:inv_one']],
  ['accepted direct save closes general extraction', [{save: true}, {failed: true}, {}], ['', '', '']],
  ['duplicate results are not new observations', [{id: 'same'}, {id: 'same', failed: true}, {}], ['', '', '']],
  ['transport wrappers are not learning activity', [{tool: 'run_code', failed: true}, {tool: 'functions.exec', failed: true}, {}], ['', '', '']],
  ['general cue and subsequent reuse have separate budgets', [{failed: true}, {}, {run: true}, {}], ['', 'general', '', 'reuse:inv_one']],
];
for (const [name, trace, expected] of cases) test(`DSH/Codex share decisions: ${name}`, async () => {
  assert.deepEqual(await replay(trace, 'dsh'), expected);
  assert.deepEqual(await replay(trace, 'codex'), expected);
});
