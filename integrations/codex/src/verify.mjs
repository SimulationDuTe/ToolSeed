import {existsSync, readFileSync} from 'node:fs';
import {join, resolve} from 'node:path';
import {parseArgs} from 'node:util';
import {queryCodexAppServer} from './app-server-client.mjs';
import {AGENTS_BEGIN, AGENTS_END, findCodexBinary, HOOK_STATUS, readMcpServerConfigured} from './install.mjs';
import {resolveCodexHome, resolveDataDir} from './paths.mjs';
import {WORKFLOW_EVENTS, hasWorkflowHooks} from './workflow.mjs';
import {probeRuntime} from './runtime-probe.mjs';

function readOptional(path) {
  try {
    return readFileSync(path, 'utf8');
  } catch (error) {
    if (error?.code === 'ENOENT') return '';
    throw error;
  }
}

function flatten(data, key) {
  if (!Array.isArray(data)) return [];
  return data.flatMap(entry => Array.isArray(entry?.[key]) ? entry[key] : []);
}

export async function verifyCodexAdapter(options = {}) {
  const codexHome = resolveCodexHome(options.codexHome);
  const dataDir = resolveDataDir(options.dataDir);
  const mcpServer = String(options.mcpServer ?? 'toolseed');
  const codex = options.codex === null ? null : (options.codex ?? findCodexBinary());
  const cwd = resolve(options.cwd ?? process.cwd());
  const hooksPath = join(codexHome, 'hooks.json');
  const agentsPath = join(codexHome, 'AGENTS.md');
  const configPath = join(codexHome, 'config.toml');
  const checks = [];
  let version = null;
  let hooks = [];
  let skills = [];

  if (codex) {
    try {
      const query = await (options.query ?? queryCodexAppServer)({
        codex,
        codexHome,
        cwd,
        calls: [
          {method: 'hooks/list', params: {cwds: [cwd]}},
          {method: 'skills/list', params: {cwds: [cwd], forceReload: true}},
        ],
      });
      version = query.version;
      hooks = flatten(query.results[0]?.response?.result?.data, 'hooks');
      skills = flatten(query.results[1]?.response?.result?.data, 'skills');
    } catch (error) {
      checks.push({id: 'app_server', ok: false, detail: error.message});
    }
  } else {
    checks.push({id: 'codex_binary', ok: false, detail: 'Codex binary not found'});
  }

  if (version) checks.push({id: 'codex_version', ok: true, detail: version});
  const selectedHooks = hooks.filter(item => resolve(String(item?.sourcePath ?? '')) === resolve(hooksPath)
    && (String(item?.command ?? '').includes('toolseed-hook.mjs')
      || String(item?.commandWindows ?? '').includes('toolseed-hook.mjs')
      || item?.statusMessage === HOOK_STATUS));
  checks.push({
    id: 'hook_listed',
    ok: hasWorkflowHooks(selectedHooks),
    detail: hasWorkflowHooks(selectedHooks) ? `all ${WORKFLOW_EVENTS.length} required workflow events listed`
      : 'one or more required workflow events are missing',
  });
  checks.push({
    id: 'hook_trusted',
    ok: hasWorkflowHooks(selectedHooks) && selectedHooks.every(item => item.trustStatus === 'trusted'),
    detail: selectedHooks.length ? selectedHooks.map(item => `${item.key}: ${item.trustStatus}`).join('; ') : 'hooks not listed',
  });
  const skill = skills.find(item => item?.name === 'toolseed');
  checks.push({
    id: 'skill_active',
    ok: Boolean(skill?.enabled && skill?.scope === 'user'),
    detail: skill ? `scope=${skill.scope} enabled=${skill.enabled} path=${skill.path}` : 'toolseed skill not found',
  });

  const agents = readOptional(agentsPath);
  checks.push({
    id: 'agents_md',
    ok: agents.includes(AGENTS_BEGIN) && agents.includes(AGENTS_END),
    detail: agentsPath,
  });

  const config = readOptional(configPath);
  const projectConfig = [join(cwd, '.codex', 'config.toml'), join(cwd, 'config.toml')]
    .filter(path => existsSync(path))
    .map(path => readOptional(path));
  checks.push({
    id: 'mcp_server_config',
    ok: readMcpServerConfigured(config, mcpServer)
      || projectConfig.some(text => readMcpServerConfigured(text, mcpServer)),
    detail: `[mcp_servers.${mcpServer}]`,
  });
  const runtime = checks.find(check => check.id === 'mcp_server_config').ok
    ? await (options.probe ?? probeRuntime)({python: options.python, codexHome, cwd, dataDir, mcpServer})
    : {ok: false, code: 'MCP_NOT_CONFIGURED'};
  checks.push({id: 'mcp_runtime', ok: runtime.ok === true,
    detail: runtime.ok ? 'five tools, read-only recall and revision binding; matching data directory' : runtime.code});

  const database = join(dataDir, 'toolseed.sqlite3');
  checks.push({
    id: 'toolseed_database',
    ok: existsSync(database),
    detail: database,
  });

  const adapterRequired = new Set(['app_server', 'codex_binary', 'hook_listed', 'hook_trusted', 'skill_active', 'agents_md']);
  const adapterOk = checks.filter(check => adapterRequired.has(check.id)).every(check => check.ok);
  const ready = adapterOk && runtime.ok === true;
  return {
    ok: ready,
    ready,
    adapter_ok: adapterOk,
    database_state: existsSync(database) ? 'present' : 'uninitialized',
    runtime,
    codex_home: codexHome,
    data_dir: dataDir,
    mcp_server: mcpServer,
    codex,
    version,
    checks,
    hooks,
    skills,
  };
}

function textReport(result) {
  const lines = [
    `Codex adapter verification${result.version ? ` (Codex ${result.version})` : ''}`,
    `  Codex home: ${result.codex_home}`,
    `  Data dir:   ${result.data_dir}`,
  ];
  for (const check of result.checks) {
    const status = check.id === 'toolseed_database' && !check.ok ? 'INFO' : check.ok ? 'PASS' : 'FAIL';
    lines.push(`  ${status}  ${check.id}: ${check.detail}`);
  }
  lines.push(result.ready ? 'Adapter and configured MCP runtime are ready.' : 'Adapter or configured MCP runtime is not ready.');
  return lines.join('\n');
}

async function main() {
  const {values} = parseArgs({
    strict: false,
    options: {
      'codex-home': {type: 'string'},
      'data-dir': {type: 'string'},
      'mcp-server': {type: 'string', default: 'toolseed'},
      codex: {type: 'string'},
      cwd: {type: 'string'},
      python: {type: 'string'},
      json: {type: 'boolean', default: false},
    },
  });
  const result = await verifyCodexAdapter({
    codexHome: values['codex-home'],
    dataDir: values['data-dir'],
    mcpServer: values['mcp-server'],
    codex: values.codex,
    cwd: values.cwd,
    python: values.python,
  });
  process.stdout.write(values.json ? `${JSON.stringify(result, null, 2)}\n` : `${textReport(result)}\n`);
  process.exitCode = result.ok ? 0 : 1;
}

if (process.argv[1]?.endsWith('verify.mjs')) await main();
