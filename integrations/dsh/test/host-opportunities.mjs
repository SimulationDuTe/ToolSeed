// Optional integration probe, run with the installed DSH Electron-as-Node
// launcher. Uses only that installation's public exports, a scripted adapter
// (NO model/network requests), real AgentLoop/ToolRuntime and real MCP stdio.
import assert from 'node:assert/strict';
import {mkdtemp, mkdir, readFile} from 'node:fs/promises';
import {join, resolve} from 'node:path';
import {pathToFileURL, fileURLToPath} from 'node:url';
import {installOpportunityHooks} from '../opportunities.js';

const [archive, python] = process.argv.slice(2);
assert.ok(archive && python, 'Pass the installed DSH app.asar and ToolSeed Python executable');
const root = fileURLToPath(new URL('../../../', import.meta.url));
const load = name => import(pathToFileURL(join(archive, 'dsh/node_modules/@deepseek-ai', name, 'lib/index.js')));
const {Context} = await load('cordis');
const {SystemPrompt} = await load('dsh-system-prompt');
const {SessionStore} = await load('dsh-session');
const {SessionProjectionRegistry} = await load('dsh-session-projection');
const {AgentRegistry} = await load('dsh-agent');
const {AgentLoop} = await load('dsh-agent-loop');
const {ToolRuntime} = await load('dsh-tools');
const {LlmRuntime, LlmAdapter, createUserMessage} = await load('dsh-llm');
const mcp = await load('dsh-mcp-client');
const version = JSON.parse(await readFile(join(archive, 'dsh/node_modules/@deepseek-ai/dsh-agent/package.json'), 'utf8')).version;
assert.equal(version, '0.2.1-rc.2');
await mkdir(join(root, 'tests/.data'), {recursive: true});
const data = await mkdtemp(join(root, 'tests/.data/p1a-host-'));
const records = [], requests = [], probeEvents = [];
const ctx = new Context();
const fibers = [];
const use = async (...args) => {
  const fiber = ctx.plugin(...args);
  fibers.push(fiber);
  await fiber.await();
};
async function stats() {
  const result = await ctx.tools.execute({name: 'mcp__toolseed__toolbox_stats',
    callId: `p1a-stats-${Date.now()}`, arguments: {}, signal: new AbortController().signal});
  assert.equal(result.isError, false);
  return result.value.structuredContent ?? JSON.parse(result.value.content[0].text);
}
class ScriptedAdapter extends LlmAdapter {
  calls = new Map();
  async *stream(options) {
    const n = (this.calls.get(options.model) ?? 0) + 1;
    this.calls.set(options.model, n);
    requests.push({model: options.model, step: n});
    const text = options.messages.flatMap(message => message.content ?? [])
      .filter(block => block.type === 'text').map(block => block.text).join('\n');
    if (options.model === 'ordinary') {
      assert.doesNotMatch(text, /ToolSeed 机会提示/);
      yield {type: 'text-delta', index: 0, text: 'ordinary fixture complete'};
      return;
    }
    const call = (name, args, i = 0) => ({type: 'tool-call-delta', index: i,
      id: `p1a-call-${n}-${i}`, name, argumentsDelta: JSON.stringify(args)});
    if (n === 1) {
      // The real registry, not this fixture, produces UNKNOWN_TOOL failures.
      for (let i = 0; i < 3; i++) yield call('diagnostic_probe', {}, i);
    } else if (n === 2) {
      assert.match(text, /ToolSeed 机会提示/);
      const untouched = await stats();
      assert.equal(untouched.evidence.events, 0, 'Host signals and hints must not enter Core evidence');
      assert.equal(untouched.task_outcomes.signals, 0);
      yield call('mcp__toolseed__toolbox_search', {query: 'diagnose repeated failures', context: {}});
    } else if (n === 3) {
      // Deliberate invalid candidate: real Core must reject it. This is a
      // failure-recovery fixture, not a proposed or verified repair method.
      yield call('mcp__toolseed__toolbox_save', {candidate: {}});
    } else {
      assert.equal(n, 4, 'No forced continuation/retry loop');
      yield {type: 'text-delta', index: 0, text: 'continue original task; result unconfirmed'};
    }
  }
}

const started = performance.now();
try {
await use(SystemPrompt, {includeHarnessIdentity: false, includeRuntimeContext: false});
await use(SessionStore);
await use(SessionProjectionRegistry);
await use(AgentRegistry);
await use(LlmRuntime);
await use(ToolRuntime, {mode: 'native'});
await use(AgentLoop, {agents: [], maxParallelToolCalls: 10});
await use({name: 'p1a-scripted-provider', inject: ['llm'], apply(host) {
  host.llm.registerAdapter(['p1a-scripted'], new ScriptedAdapter());
}});
await use(mcp, {transport: 'stdio', serverName: 'toolseed', command: resolve(python),
  args: ['-B', '-X', 'utf8', '-m', 'toolseed.mcp_server', '--data-dir', data],
  cwd: root, failOnStartupError: true});
await use({name: 'p1a-opportunity-probe', inject: ['agents', 'tools'], apply(host) {
  host.on('tools/result', (exec, result) => probeEvents.push({event:'tools/result',
    agent:exec.agent?.id, name:exec.name, code:result.error?.info?.code, isError:result.isError, token:typeof exec.token}));
  host.on('agent/pre-step', (payload, next) => {
    probeEvents.push({event:'agent/pre-step', agent:payload.agent?.id, turn:payload.turn}); return next();
  });
  host.on('session/event', (session, event) => {
    if (event.type === 'user/message') probeEvents.push({event:'session/event', session:session.id,
      messageId:event.data.id, source:event.data.source?.kind});
  });
  installOpportunityHooks({on: host.on.bind(host), effect: host.effect.bind(host), tools: host.tools,
    logger: {info: (_prefix, text) => records.push(JSON.parse(text))}});
}});

  await Promise.all(fibers.map(fiber => fiber.await()));
  assert.ok(ctx.tools.get('mcp__toolseed__toolbox_search'), 'Real MCP tool discovery completed');
  for (const model of ['ordinary', 'blocked']) {
    const handle = await ctx.agents.create({sessionId: `p1a-${model}`,
      agentOptions: {provider: 'p1a-scripted', model}});
    handle.agent.followup(createUserMessage({content: [{type: 'text', text: 'Complete the normal fixture task'}], source: {kind: 'user'}}));
    await handle.agent.whenIdle();
    if (model === 'blocked') {
      const messages = handle.agent.session.deriveMessages();
      assert.equal(messages.filter(message => message.source?.kind === 'toolseed-opportunity').length, 1);
      assert.ok(messages.some(message => message.role === 'tool-result' || message.role === 'tool'));
    }
    await handle.dispose();
  }
  const stages = records.map(record => record.stage);
  assert.deepEqual(stages, ['signal_detected', 'opportunity_proposed', 'opportunity_prompted', 'search_completed', 'save_failed']);
  assert.equal(requests.filter(request => request.model === 'ordinary').length, 1);
  assert.equal(requests.filter(request => request.model === 'blocked').length, 4);
  const coreStats = await stats();
  assert.equal(coreStats.capabilities.total, 0, 'Rejected empty candidate not stored');
  assert.equal(coreStats.search.requests, 1);
  assert.equal(coreStats.delivery.count, 0);
  assert.equal(coreStats.task_outcomes.signals, 0);
  assert.equal(coreStats.evidence.events, 2, 'Only real search and failed-save activity enter Core');
  console.log(JSON.stringify({passed: true, dsh_version: version, stages,
    scripted_driver_requests: requests.length, actual_model_calls: 0, token_count: 'unknown',
    duration_ms: Math.round(performance.now() - started), data_dir: data,
    human_or_model_behaviour_verified: false, core_stats: coreStats, records}, null, 2));
} catch (error) {
  process.exitCode = 1;
  console.error(error);
  console.error(JSON.stringify({requests, records, probeEvents, data_dir: data}));
} finally {
  // Keep this uniquely created database as inspection evidence. Never touches
  // the user's database, profile, provider settings or running Desktop session.
  await ctx.fiber.dispose();
}
