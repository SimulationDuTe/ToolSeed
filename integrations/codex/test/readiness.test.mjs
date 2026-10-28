import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, mkdirSync, writeFileSync, rmSync, existsSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {verifyCodexAdapter} from '../src/verify.mjs';
import {installCodexAdapter, HOOK_STATUS} from '../src/install.mjs';
import {assessRuntime, probeRuntime} from '../src/runtime-probe.mjs';

const tools = ['search', 'save', 'run', 'stats', 'learn'].map(name => 'toolbox_' + name);
function fixture(configured = true) {
  const root = mkdtempSync(join(tmpdir(), 'toolseed-ready-'));
  const home = join(root, 'home'), cwd = join(root, 'work'), dataDir = join(root, 'data');
  mkdirSync(home); mkdirSync(cwd);
  writeFileSync(join(home, 'AGENTS.md'), '<!-- toolseed-codex:begin -->\n<!-- toolseed-codex:end -->');
  if (configured) writeFileSync(join(home, 'config.toml'), '[mcp_servers.toolseed]\ncommand="fixture"\n');
  const hooks = ['postToolUse', 'userPromptSubmit', 'interrupt', 'sessionEnd'].map(eventName => ({
    eventName, key: eventName, currentHash: 'fixture-hash', sourcePath: join(home, 'hooks.json'),
    command: 'node toolseed-hook.mjs', statusMessage: HOOK_STATUS, trustStatus: 'trusted'}));
  const runtime = {ok: true, tools, data_dir: dataDir, features: {read_only_search: true, revision_base_binding: true}};
  const query = async ({calls}) => ({version: 'fixture', results: calls.map(call => ({response: {result:
    call.method === 'hooks/list' ? {data: [{hooks}]} : call.method === 'skills/list'
      ? {data: [{skills: [{name: 'toolseed', enabled: true, scope: 'user'}]}]} : {status: 'ok'}}}))});
  return {root, hooks, runtime, options: {codexHome: home, cwd, dataDir, codex: 'fixture',
    query, probe: async () => runtime}, close() {
      assert.ok(resolve(root).startsWith(resolve(tmpdir()) + (process.platform === 'win32' ? '\\' : '/')));
      rmSync(root, {recursive: true, force: true});
    }};
}

test('trusted hooks and a Skill do not make a missing MCP runtime ready', async () => {
  const f = fixture(false);
  try {
    let probes = 0;
    const result = await verifyCodexAdapter({...f.options, probe: async () => {probes++;return f.runtime;}});
    assert.equal(result.adapter_ok, true); assert.equal(result.ok, false); assert.equal(result.ready, false);
    assert.equal(result.runtime.code, 'MCP_NOT_CONFIGURED'); assert.equal(probes, 0);
    assert.equal(result.database_state, 'uninitialized');
  } finally {f.close();}
});

test('a compatible configured runtime can be ready before the first database is created', async () => {
  const f = fixture();
  try {
    const result = await verifyCodexAdapter(f.options);
    assert.equal(result.ok, true); assert.equal(result.database_state, 'uninitialized');
    assert.equal(existsSync(f.options.dataDir), false);
  } finally {f.close();}
});

test('old runtimes, runtime probe failures and four duplicate hook events are not ready', async () => {
  const f = fixture();
  try {
    for (const code of ['MCP_RUNTIME_INCOMPATIBLE', 'MCP_RUNTIME_PROBE_FAILED']) {
      const result = await verifyCodexAdapter({...f.options, probe: async () => ({ok: false, code})});
      assert.equal(result.ok, false); assert.equal(result.runtime.code, code);
    }
    f.hooks.forEach(h => h.eventName = 'postToolUse');
    assert.equal((await verifyCodexAdapter(f.options)).adapter_ok, false);
  } finally {f.close();}
});

test('installer refuses missing or incompatible MCP before changing user files', async () => {
  for (const configured of [false, true]) {
    const f = fixture(configured);
    try {
      const result = await installCodexAdapter({...f.options, apply: true,
        probe: async () => ({ok: false, code: 'MCP_RUNTIME_INCOMPATIBLE'})});
      assert.equal(result.applied, false); assert.equal(result.ready, false);
      assert.equal(existsSync(join(f.options.codexHome, 'hooks.json')), false);
      assert.equal(existsSync(join(f.options.codexHome, 'skills')), false);
    } finally {f.close();}
  }
});

test('only verified native trust and compatible MCP can complete a ready installation', async () => {
  const f = fixture();
  try {
    assert.equal((await installCodexAdapter({...f.options, apply: true})).ready, true);
    const untrusted = await installCodexAdapter({...f.options, apply: true, trust: false});
    assert.equal(untrusted.applied, true); assert.equal(untrusted.ready, false);
    assert.equal(untrusted.trust.status, 'skipped');
  } finally {f.close();}
});

test('runtime reports require all tools, both features and the same actual library', () => {
  const f = fixture();
  try {
    assert.equal(assessRuntime(f.runtime, f.options.dataDir).ok, true);
    assert.equal(assessRuntime({...f.runtime, tools: tools.slice(0, 4)}, f.options.dataDir).code, 'MCP_TOOLS_INCOMPLETE');
    assert.equal(assessRuntime({...f.runtime, features: {}}, f.options.dataDir).code, 'MCP_RUNTIME_INCOMPATIBLE');
    assert.equal(assessRuntime({...f.runtime, data_dir: join(f.root, 'another')}, f.options.dataDir).code, 'MCP_DATA_DIRECTORY_MISMATCH');
  } finally {f.close();}
});

test('runtime probe uses fixed process arguments, bounded output, no shell and sanitized failures', async () => {
  const f = fixture();
  try {
    let args;
    const result = await probeRuntime({...f.options, python: 'fixed-python', mcpServer: 'toolseed'}, async (...items) => {
      args = items; return {stdout: JSON.stringify(f.runtime)};
    });
    assert.equal(result.ok, true); assert.equal(args[0], 'fixed-python');
    assert.equal(args[2].shell, false); assert.equal(args[2].windowsHide, true);
    assert.deepEqual(JSON.parse(args[1][5]), [join(f.options.codexHome, 'config.toml'), join(f.options.cwd, '.codex', 'config.toml'), join(f.options.cwd, 'config.toml')]);
    const failed = await probeRuntime({...f.options, mcpServer: 'toolseed'}, async () => {throw new Error('secret stderr');});
    assert.deepEqual(failed, {ok: false, code: 'MCP_RUNTIME_PROBE_FAILED'});
  } finally {f.close();}
});
