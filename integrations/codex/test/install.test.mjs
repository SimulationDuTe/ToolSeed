import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {
  agentBlock,
  buildHookCommand,
  installCodexAdapter,
  mergeHooksConfig,
  readMcpServerConfigured,
  replaceAgentsBlock,
  AGENTS_BEGIN,
  AGENTS_END,
} from '../src/install.mjs';

test('hook merge preserves user hooks and is idempotent', () => {
  const existing = {
    hooks: {
      PostToolUse: [
        {matcher: 'Bash', hooks: [{type: 'command', command: 'echo user'}]},
      ],
    },
  };
  const command = 'node toolseed-hook.mjs --mcp-server toolseed';
  const first = mergeHooksConfig(existing, command);
  assert.equal(first.config.hooks.PostToolUse.length, 2);
  assert.equal(first.groupIndex, 1);
  assert.equal(first.config.hooks.PostToolUse[0].hooks[0].command, 'echo user');
  const second = mergeHooksConfig(first.config, command);
  assert.equal(second.config.hooks.PostToolUse.length, 2);
  assert.equal(second.groupIndex, 1);
});

test('hook merge accepts separate cross-platform commands', () => {
  const result = mergeHooksConfig({}, {
    command: '"/usr/bin/node" "/repo/toolseed-hook.mjs"',
    commandWindows: 'cmd /c "C:\\node.exe" "C:\\repo\\toolseed-hook.mjs"',
  });
  const handler = result.config.hooks.PostToolUse[0].hooks[0];
  assert.match(handler.command, /usr\/bin\/node/);
  assert.match(handler.commandWindows, /^cmd \/c /);
});

test('hook merge rejects malformed existing shapes', () => {
  assert.throws(() => mergeHooksConfig([], 'x'), /JSON object/);
  assert.throws(() => mergeHooksConfig({hooks: {PostToolUse: {}}}, 'x'), /non-array/);
});

test('AGENTS block append and replacement are idempotent', () => {
  const block = agentBlock('toolseed');
  const first = replaceAgentsBlock('# Existing\n', block);
  assert.match(first, /# Existing/);
  assert.equal((first.match(new RegExp(AGENTS_BEGIN, 'g')) ?? []).length, 1);
  const second = replaceAgentsBlock(first, block);
  assert.equal((second.match(new RegExp(AGENTS_BEGIN, 'g')) ?? []).length, 1);
  assert.ok(second.includes(AGENTS_END));
});

test('MCP server table detection covers bare and quoted names', () => {
  assert.equal(readMcpServerConfigured('[mcp_servers.toolseed]\ncommand = "x"', 'toolseed'), true);
  assert.equal(readMcpServerConfigured('[mcp_servers."toolseed"]\ncommand = "x"', 'toolseed'), true);
  assert.equal(readMcpServerConfigured("[mcp_servers.'toolseed']\ncommand = 'x'", 'toolseed'), true);
  assert.equal(readMcpServerConfigured('[mcp_servers.other]\ncommand = "x"', 'toolseed'), false);
});

test('hook command quotes paths and carries explicit adapter options', () => {
  const command = buildHookCommand({
    nodePath: 'C:\\Program Files\\nodejs\\node.exe',
    hookScript: 'F:\\Repo With Space\\toolseed-hook.mjs',
    mcpServer: 'toolseed',
    stateDir: 'C:\\Users\\me\\.codex\\.toolseed-codex\\state',
    logDir: 'C:\\Users\\me\\.codex\\.toolseed-codex',
    platform: 'win32',
  });
  assert.match(command, /^cmd \/c /);
  assert.match(command, /"C:\\Program Files\\nodejs\\node.exe"/);
  assert.match(command, /--mcp-server toolseed/);
  assert.match(command, /--state-dir/);
});

test('dry-run plan does not write and apply writes skill, hooks and AGENTS.md', async () => {
  const root = mkdtempSync(join(tmpdir(), 'toolseed-codex-install-'));
  const home = join(root, 'codex-home');
  const cwd = join(root, 'workspace');
  mkdirSync(cwd, {recursive: true});
  mkdirSync(home, {recursive: true});
  writeFileSync(join(home, 'config.toml'), '[mcp_servers.toolseed]\ncommand = "fixture"\n');
  const options = {
    apply: false,
    codexHome: home,
    dataDir: join(root, 'data'),
    mcpServer: 'toolseed',
    codex: null,
    trust: false,
    cwd,
    probe: async () => ({ok: true}),
  };
  try {
    const dry = await installCodexAdapter(options);
    assert.equal(dry.applied, false);
    assert.equal(existsSync(join(home, 'hooks.json')), false);

    const applied = await installCodexAdapter({...options, apply: true});
    assert.equal(applied.applied, true);
    assert.ok(existsSync(join(home, 'skills', 'toolseed', 'SKILL.md')));
    assert.ok(existsSync(join(home, 'hooks.json')));
    assert.ok(existsSync(join(home, 'AGENTS.md')));
    const hooks = JSON.parse(readFileSync(join(home, 'hooks.json'), 'utf8'));
    assert.equal(hooks.hooks.PostToolUse.length, 1);
    const agents = readFileSync(join(home, 'AGENTS.md'), 'utf8');
    assert.ok(agents.includes(AGENTS_BEGIN));
    assert.ok(agents.includes(AGENTS_END));
    assert.equal(applied.trust.status, 'skipped');

    const again = await installCodexAdapter({...options, apply: true});
    assert.equal(again.changes.skill, false);
    assert.equal(again.changes.hooks, false);
    assert.equal(again.changes.agents, false);
  } finally {
    rmSync(root, {recursive: true, force: true});
  }
});

test('installer detects project-level MCP configuration', async () => {
  const root = mkdtempSync(join(tmpdir(), 'toolseed-codex-install-'));
  const home = join(root, 'codex-home');
  const cwd = join(root, 'workspace');
  mkdirSync(join(cwd, '.codex'), {recursive: true});
  writeFileSync(join(cwd, '.codex', 'config.toml'), '[mcp_servers.toolseed]\ncommand = "x"\n');
  try {
    const plan = await installCodexAdapter({
      apply: false,
      codexHome: home,
      dataDir: join(root, 'data'),
      codex: null,
      cwd,
      probe: async () => ({ok: true}),
    });
    assert.equal(plan.checks.mcp_server_configured, true);
    assert.equal(plan.checks.mcp_config_path, join(cwd, '.codex', 'config.toml'));
  } finally {
    rmSync(root, {recursive: true, force: true});
  }
});

test('AGENTS.md installation can be disabled without touching the file', async () => {
  const root = mkdtempSync(join(tmpdir(), 'toolseed-codex-install-'));
  const home = join(root, 'codex-home');
  const cwd = join(root, 'workspace');
  mkdirSync(cwd, {recursive: true});
  mkdirSync(home, {recursive: true});
  writeFileSync(join(home, 'config.toml'), '[mcp_servers.toolseed]\ncommand="fixture"\n');
  try {
    const plan = await installCodexAdapter({
      apply: true,
      codexHome: home,
      dataDir: join(root, 'data'),
      codex: null,
      trust: false,
      agentsMd: false,
      probe: async () => ({ok: true}),
      cwd,
    });
    assert.equal(plan.checks.agents_md, false);
    assert.equal(plan.changes.agents, false);
    assert.equal(existsSync(join(home, 'AGENTS.md')), false);
  } finally {
    rmSync(root, {recursive: true, force: true});
  }
});
