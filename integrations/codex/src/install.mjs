import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  readdirSync,
  rmSync,
  rmdirSync,
  unlinkSync,
  writeFileSync,
} from 'node:fs';
import {homedir} from 'node:os';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {parseArgs} from 'node:util';
import {queryCodexAppServer} from './app-server-client.mjs';
import {HOST_CAPABILITIES} from './host-capabilities.mjs';
import {defaultLogDir, defaultStateDir, resolveCodexHome, resolveDataDir} from './paths.mjs';
import {hasWorkflowHooks, WORKFLOW_EVENTS} from './workflow.mjs';
import {probeRuntime} from './runtime-probe.mjs';

export const AGENTS_BEGIN = '<!-- toolseed-codex:begin -->';
export const AGENTS_END = '<!-- toolseed-codex:end -->';
export const HOOK_STATUS = 'ToolSeed learning and recall adapter';

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function quoteCommandPart(value) {
  return `"${String(value).replace(/"/g, '\\"')}"`;
}

export function buildHookCommand({
  nodePath,
  hookScript,
  mcpServer,
  stateDir,
  logDir,
  python,
  dataDir,
  platform = process.platform,
}) {
  const args = `--mcp-server ${mcpServer} --state-dir ${quoteCommandPart(stateDir)} --log-dir ${quoteCommandPart(logDir)}`
    + (python ? ` --python ${quoteCommandPart(python)}` : '')
    + (dataDir ? ` --data-dir ${quoteCommandPart(dataDir)}` : '');
  const direct = `${quoteCommandPart(nodePath)} ${quoteCommandPart(hookScript)} ${args}`;
  // Windows hook processes are launched through cmd; this form was verified
  // against Codex 0.163.0-alpha.11 with both a mapped drive and PATH lookup.
  return platform === 'win32' ? `cmd /c ${direct}` : direct;
}

function isToolseedGroup(group) {
  try {
    const text = JSON.stringify(group);
    return text.includes('toolseed-hook.mjs') || text.includes(HOOK_STATUS);
  } catch {
    return false;
  }
}

export function mergeHooksConfig(existing, command) {
  const config = isPlainObject(existing) ? structuredClone(existing) : {};
  if (existing !== undefined && existing !== null && !isPlainObject(existing)) {
    throw new Error('hooks.json must contain a JSON object');
  }
  const hooks = config.hooks === undefined ? {} : config.hooks;
  if (!isPlainObject(hooks)) throw new Error('hooks.json has a non-object "hooks" value');
  if (hooks.PostToolUse !== undefined && !Array.isArray(hooks.PostToolUse)) {
    throw new Error('hooks.json has a non-array "hooks.PostToolUse" value');
  }
  const commandText = typeof command === 'string' ? command : command?.command;
  const commandWindows = typeof command === 'string' ? command : (command?.commandWindows ?? commandText);
  if (typeof commandText !== 'string' || commandText.length === 0) {
    throw new Error('A hook command is required');
  }
  const group = {
    matcher: '.*',
    hooks: [{
      type: 'command',
      command: commandText,
      commandWindows,
      timeout: 10,
      statusMessage: HOOK_STATUS,
    }],
  };
  config.hooks = {...hooks};
  let groupIndex = 0;
  for (const event of WORKFLOW_EVENTS) {
    if (hooks[event] !== undefined && !Array.isArray(hooks[event])) throw new Error(`hooks.json has a non-array "hooks.${event}" value`);
    const kept = (hooks[event] ?? []).filter(item => !isToolseedGroup(item));
    if (event === 'PostToolUse') groupIndex = kept.length;
    const current = structuredClone(group);
    if (event !== 'PostToolUse') delete current.matcher;
    if (['Interrupt', 'SessionEnd'].includes(event)) current.hooks[0].timeout = 3;
    config.hooks[event] = [...kept, current];
  }
  return {config, groupIndex, handlerIndex: 0, events: WORKFLOW_EVENTS};
}

export function replaceAgentsBlock(text, block) {
  const source = typeof text === 'string' ? text : '';
  const pattern = new RegExp(`${escapeRegExp(AGENTS_BEGIN)}[\\s\\S]*?${escapeRegExp(AGENTS_END)}`, 'm');
  if (pattern.test(source)) return source.replace(pattern, block);
  const trimmed = source.replace(/\s+$/u, '');
  return trimmed ? `${trimmed}\n\n${block}\n` : `${block}\n`;
}

export function agentBlock(mcpServer) {
  const prefix = `mcp__${mcpServer}__`;
  return `${AGENTS_BEGIN}
## ToolSeed capability reuse

When repeated blockers, costly diagnosis or clear future reuse justify it, load the installed \`toolseed\` Skill. Consider Hook recall cards before choosing a method; they are actual local searches, so reuse an equivalent search already supplied. Read full guidance through \`${prefix}toolbox_run\`, check applicability and permissions, then apply it with authorized host tools. Use \`${prefix}toolbox_learn\` to retain validated methods, failure lessons or tool recipes only when worthwhile. After actual reuse, append observations or propose an amendment on the original capability using the delivered invocation/version/hash. Prefer updating existing capabilities to duplicates. Search hits, delivery and activity alone do not prove adoption or task success.
${AGENTS_END}`;
}

export function findCodexBinary(explicit) {
  if (explicit && existsSync(explicit)) return resolve(explicit);
  if (explicit) return explicit;
  for (const key of ['CODEX_BIN', 'CODEX_CLI_PATH']) {
    const value = process.env[key];
    if (value && existsSync(value)) return resolve(value);
  }
  const path = process.env.PATH ?? '';
  for (const directory of path.split(';')) {
    if (!directory) continue;
    for (const name of ['codex.exe', 'codex.cmd', 'codex.bat', 'codex']) {
      const candidate = join(directory, name);
      if (existsSync(candidate)) return candidate;
    }
  }
  const localAppData = process.env.LOCALAPPDATA;
  if (localAppData) {
    const root = join(localAppData, 'OpenAI', 'Codex', 'bin');
    try {
      for (const entry of readdirSync(root, {withFileTypes: true})) {
        if (!entry.isDirectory()) continue;
        const candidate = join(root, entry.name, 'codex.exe');
        if (existsSync(candidate)) return candidate;
      }
    } catch {
      // Not installed in the usual per-user location.
    }
  }
  const userBin = join(homedir(), '.codex', 'bin');
  try {
    for (const entry of readdirSync(userBin, {withFileTypes: true})) {
      if (!entry.isDirectory()) continue;
      const candidate = join(userBin, entry.name, 'codex.exe');
      if (existsSync(candidate)) return candidate;
    }
  } catch {
    // Not installed in the usual CODEX_HOME location.
  }
  return null;
}

export function readMcpServerConfigured(text, mcpServer) {
  if (typeof text !== 'string') return false;
  const escaped = escapeRegExp(mcpServer);
  const patterns = [
    new RegExp(`^\\s*\\[mcp_servers\\.${escaped}\\]\\s*$`, 'm'),
    new RegExp(`^\\s*\\[mcp_servers\\."${escaped}"\\]\\s*$`, 'm'),
    new RegExp(`^\\s*\\[mcp_servers\\.'${escaped}'\\]\\s*$`, 'm'),
  ];
  return patterns.some(pattern => pattern.test(text));
}

function readOptional(path) {
  try {
    // Windows editors and PowerShell commonly write a UTF-8 BOM; JSON.parse
    // rejects it, so strip it before parsing user-owned configuration.
    return readFileSync(path, 'utf8').replace(/^\uFEFF/, '');
  } catch (error) {
    if (error?.code === 'ENOENT') return '';
    throw error;
  }
}

function backupFile(path) {
  if (!existsSync(path)) return null;
  const stamp = new Date().toISOString().replace(/[:-]/g, '').replace(/\.\d+Z$/, 'Z');
  let target = `${path}.bak-toolseed-${stamp}`;
  let index = 1;
  while (existsSync(target)) target = `${path}.bak-toolseed-${stamp}-${index++}`;
  copyFileSync(path, target);
  return target;
}

function writeText(path, content) {
  mkdirSync(dirname(path), {recursive: true});
  writeFileSync(path, content, {encoding: 'utf8', mode: 0o600});
}

function readJson(path) {
  const text = readOptional(path);
  if (!text.trim()) return null;
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(`Cannot parse ${path}: ${error.message}`);
  }
}

function entriesOf(result, key) {
  const entries = result?.response?.result?.data;
  if (!Array.isArray(entries)) return [];
  return entries.flatMap(entry => Array.isArray(entry?.[key]) ? entry[key] : []);
}

function findHooks(hooks, hooksPath) {
  const normalizedPath = resolve(hooksPath);
  return hooks.filter(hook => resolve(String(hook?.sourcePath ?? '')) === normalizedPath
    && (String(hook?.command ?? '').includes('toolseed-hook.mjs')
      || String(hook?.commandWindows ?? '').includes('toolseed-hook.mjs')
      || hook?.statusMessage === HOOK_STATUS));
}

function checkProjectMcp(cwd, mcpServer) {
  const candidates = [
    join(cwd, '.codex', 'config.toml'),
    join(cwd, 'config.toml'),
  ];
  for (const path of candidates) {
    if (existsSync(path) && readMcpServerConfigured(readOptional(path), mcpServer)) {
      return {ok: true, path};
    }
  }
  return {ok: false, path: null};
}

function skillIsActive(skills) {
  return skills.some(skill => skill?.name === 'toolseed' && skill?.enabled === true
    && skill?.scope === 'user');
}

export async function installCodexAdapter(options = {}) {
  const apply = options.apply === true;
  const codexHome = resolveCodexHome(options.codexHome);
  const dataDir = resolveDataDir(options.dataDir);
  const mcpServer = String(options.mcpServer ?? 'toolseed');
  if (!/^[A-Za-z0-9_-]{1,32}$/.test(mcpServer)) {
    throw new Error('mcpServer must be 1-32 letters, digits, underscores or hyphens');
  }
  const codex = options.codex === null ? null : (options.codex ?? findCodexBinary());
  const nodePath = options.nodePath ?? process.execPath;
  const cwd = resolve(options.cwd ?? process.cwd());
  const hookScript = resolve(options.hookScript
    ?? fileURLToPath(new URL('./toolseed-hook.mjs', import.meta.url)));
  const skillSource = resolve(options.skillSource
    ?? fileURLToPath(new URL('../../../toolseed/skill/SKILL.md', import.meta.url)));
  if (!existsSync(hookScript)) throw new Error(`Hook script not found: ${hookScript}`);
  if (!existsSync(skillSource)) throw new Error(`ToolSeed skill not found: ${skillSource}`);
  const skillTarget = join(codexHome, 'skills', 'toolseed', 'SKILL.md');
  const hooksPath = join(codexHome, 'hooks.json');
  const agentsPath = join(codexHome, 'AGENTS.md');
  const configPath = join(codexHome, 'config.toml');
  const stateDir = resolve(options.stateDir ?? defaultStateDir(codexHome));
  const logDir = resolve(options.logDir ?? defaultLogDir(codexHome));
  const python = options.python ?? process.env.TOOLSEED_PYTHON ?? 'python';
  const command = buildHookCommand({nodePath, hookScript, mcpServer, stateDir, logDir, python, dataDir});
  const agentText = agentBlock(mcpServer);
  const agentsEnabled = options.agentsMd !== false;
  const skillText = readFileSync(skillSource, 'utf8');

  const existingHooks = readJson(hooksPath);
  const merged = mergeHooksConfig(existingHooks, command);
  const hooksText = `${JSON.stringify(merged.config, null, 2)}\n`;
  const existingAgents = readOptional(agentsPath);
  const agentsText = agentsEnabled ? replaceAgentsBlock(existingAgents, agentText) : existingAgents;
  const existingSkill = readOptional(skillTarget);
  const changes = {
    skill: existingSkill !== skillText,
    hooks: readOptional(hooksPath) !== hooksText,
    agents: agentsEnabled && existingAgents !== agentsText,
  };

  const globalMcp = readMcpServerConfigured(readOptional(configPath), mcpServer);
  const projectMcp = checkProjectMcp(cwd, mcpServer);
  const databasePath = join(dataDir, 'toolseed.sqlite3');
  const plan = {
    applied: false,
    ready: false,
    codex_home: codexHome,
    data_dir: dataDir,
    mcp_server: mcpServer,
    codex: codex ?? null,
    codex_version: null,
    node: nodePath,
    python,
    hook_command: command,
    files: {
      skill: skillTarget,
      hooks: hooksPath,
      agents: agentsPath,
      config: configPath,
      state_dir: stateDir,
      log_dir: logDir,
    },
    changes,
    checks: {
      mcp_server_configured: globalMcp || projectMcp.ok,
      mcp_config_path: globalMcp ? configPath : projectMcp.path,
      toolseed_database: existsSync(databasePath),
      toolseed_database_path: databasePath,
      skill_file_exists: existsSync(skillTarget),
      agents_md: agentsEnabled,
      agents_block: existingAgents.includes(AGENTS_BEGIN) && existingAgents.includes(AGENTS_END),
    },
    trust: {status: codex ? 'pending' : 'skipped', reason: codex ? null : 'Codex binary not found'},
    host_capabilities: HOST_CAPABILITIES,
  };

  const runtime = globalMcp || projectMcp.ok
    ? await (options.probe ?? probeRuntime)({python, codexHome, cwd, dataDir, mcpServer})
    : {ok: false, code: 'MCP_NOT_CONFIGURED'};
  plan.runtime = runtime;
  plan.checks.mcp_runtime = runtime.ok === true;
  if (!apply) return plan;
  if (!runtime.ok) {
    plan.error = {code: runtime.code, message: 'Configure a compatible ToolSeed MCP runtime before applying the adapter.'};
    return plan;
  }

  if (changes.skill) backupFile(skillTarget);
  if (changes.hooks) backupFile(hooksPath);
  if (changes.agents) backupFile(agentsPath);
  writeText(skillTarget, skillText);
  writeText(hooksPath, hooksText);
  if (agentsEnabled) writeText(agentsPath, agentsText);
  plan.applied = true;

  if (codex) {
    const query = await (options.query ?? queryCodexAppServer)({
      codex,
      codexHome,
      cwd,
      calls: [
        {method: 'hooks/list', params: {cwds: [cwd]}},
        {method: 'skills/list', params: {cwds: [cwd], forceReload: true}},
      ],
    });
    plan.codex_version = query.version;
    const hooks = entriesOf(query.results[0], 'hooks');
    const selectedHooks = findHooks(hooks, hooksPath);
    const hook = selectedHooks[0];
    const skills = entriesOf(query.results[1], 'skills');
    plan.checks.hook_listed = hasWorkflowHooks(selectedHooks);
    plan.checks.hook_count = selectedHooks.length;
    plan.checks.skill_active = skillIsActive(skills);
    if (!hook || !plan.checks.hook_listed) {
      plan.trust = {status: 'skipped', reason: 'hook was not listed by Codex'};
    } else if (options.trust === false) {
      plan.trust = {status: 'skipped', key: hook.key, hash: hook.currentHash,
        reason: 'trust disabled by --no-trust; approve the hook in Codex'};
    } else {
      try {
        const write = await (options.query ?? queryCodexAppServer)({
          codex,
          codexHome,
          cwd,
          calls: [
            {method: 'config/batchWrite', params: {
              edits: selectedHooks.map(item => ({keyPath: `hooks.state.${JSON.stringify(item.key)}.trusted_hash`,
                mergeStrategy: 'upsert', value: item.currentHash})),
              reloadUserConfig: true,
            }},
            {method: 'hooks/list', params: {cwds: [cwd]}},
          ],
        });
        const status = write.results[0]?.response?.result?.status;
        const verifiedHooks = findHooks(entriesOf(write.results[1], 'hooks'), hooksPath);
        if (status !== 'ok' || !hasWorkflowHooks(verifiedHooks) || verifiedHooks.some(item => item.trustStatus !== 'trusted')) {
          plan.trust = {status: 'failed', key: hook.key, hash: hook.currentHash,
            method: 'app_server.config/batchWrite',
            reason: 'Codex did not report trustStatus=trusted after config/batchWrite'};
        } else {
          plan.trust = {status: 'trusted', key: hook.key, hash: hook.currentHash,
            method: 'app_server.config/batchWrite', trust_status: 'trusted',
            keys: verifiedHooks.map(item => ({key: item.key, hash: item.currentHash}))};
        }
      } catch (error) {
        plan.trust = {status: 'written-unverified', key: hook.key, hash: hook.currentHash,
          method: 'app_server.config/batchWrite', reason: error.message};
      }
    }
  }

  plan.checks.agents_block = readOptional(agentsPath).includes(AGENTS_BEGIN)
    && readOptional(agentsPath).includes(AGENTS_END);
  plan.checks.skill_file_exists = existsSync(skillTarget);
  plan.checks.toolseed_database = existsSync(databasePath);
  plan.ready = plan.checks.mcp_runtime && plan.checks.hook_listed === true
    && plan.checks.skill_active === true && plan.checks.agents_block === true
    && plan.trust.status === 'trusted';
  return plan;
}

export function removeAgentsBlock(text) {
  const source = typeof text === 'string' ? text : '';
  const pattern = new RegExp(
    `\\n?${escapeRegExp(AGENTS_BEGIN)}[\\s\\S]*?${escapeRegExp(AGENTS_END)}\\n?`, 'm');
  if (!pattern.test(source)) return source;
  const stripped = source.replace(pattern, '\n').replace(/\n{3,}/g, '\n\n');
  return stripped.replace(/\s+$/u, '') ? `${stripped.replace(/\s+$/u, '')}\n` : '';
}

export function removeHooksConfig(existing) {
  const config = isPlainObject(existing) ? structuredClone(existing) : {};
  const hooks = isPlainObject(config.hooks) ? config.hooks : {};
  let removed = 0;
  const remaining = {...hooks};
  for (const event of WORKFLOW_EVENTS) {
    const groups = Array.isArray(hooks[event]) ? hooks[event] : [];
    const kept = groups.filter(group => !isToolseedGroup(group));
    removed += groups.length - kept.length;
    if (kept.length) remaining[event] = kept;
    else delete remaining[event];
  }
  if (Object.keys(remaining).length) config.hooks = remaining;
  else delete config.hooks;
  return {config, removed};
}

export function uninstallCodexAdapter(options = {}) {
  const apply = options.apply === true;
  const codexHome = resolveCodexHome(options.codexHome);
  const skillPath = join(codexHome, 'skills', 'toolseed', 'SKILL.md');
  const skillDir = dirname(skillPath);
  const hooksPath = join(codexHome, 'hooks.json');
  const agentsPath = join(codexHome, 'AGENTS.md');
  const stateDir = resolve(options.stateDir ?? defaultStateDir(codexHome));
  const logDir = resolve(options.logDir ?? defaultLogDir(codexHome));

  let hooksConfig = null;
  let removedHooks = 0;
  try {
    const current = JSON.parse(readOptional(hooksPath) || 'null');
    const result = removeHooksConfig(current);
    hooksConfig = result.config;
    removedHooks = result.removed;
  } catch (error) {
    throw new Error(`Cannot parse ${hooksPath}: ${error.message}`);
  }
  const existingAgents = readOptional(agentsPath);
  const nextAgents = removeAgentsBlock(existingAgents);
  const agentsChanged = nextAgents !== existingAgents;

  const plan = {
    applied: false,
    host: 'codex',
    codex_home: codexHome,
    removed: {
      skill: existsSync(skillPath),
      hooks: removedHooks,
      agents: agentsChanged,
      adapter_state: existsSync(stateDir) || existsSync(logDir),
    },
    files: {skill: skillPath, hooks: hooksPath, agents: agentsPath,
      state_dir: stateDir, log_dir: logDir},
    preserved: 'MCP configuration, other hooks, unrelated skills and the capability database',
  };
  if (!apply) return plan;

  if (existsSync(skillPath)) unlinkSync(skillPath);
  try { rmdirSync(skillDir); } catch { /* Keep a non-empty user-owned directory. */ }
  if (removedHooks > 0 || hooksConfig) writeText(hooksPath, `${JSON.stringify(hooksConfig, null, 2)}\n`);
  if (agentsChanged) {
    if (nextAgents) writeText(agentsPath, nextAgents);
    else try { unlinkSync(agentsPath); } catch { /* Best effort. */ }
  }
  for (const directory of [stateDir, logDir]) {
    try { rmSync(directory, {recursive: true, force: true}); } catch { /* Best effort. */ }
  }
  plan.applied = true;
  return plan;
}

function textReport(plan) {
  const lines = [
    `${plan.applied ? 'Applied' : 'Dry run'} Codex adapter for ToolSeed`,
    `  Codex home: ${plan.codex_home}`,
    `  Data dir:   ${plan.data_dir}`,
    `  MCP server: ${plan.mcp_server}`,
    `  Codex:      ${plan.codex ?? 'not found'}${plan.codex_version ? ` (${plan.codex_version})` : ''}`,
    `  Skill:      ${plan.files.skill}`,
    `  Hooks:      ${plan.files.hooks}`,
    `  AGENTS.md:  ${plan.files.agents}`,
    `  Trust:      ${plan.trust.status}${plan.trust.reason ? ` (${plan.trust.reason})` : ''}`,
    `  Runtime:    ${plan.runtime?.ok ? 'compatible' : plan.runtime?.code ?? 'unverified'}`,
    `  Ready:      ${plan.ready ? 'yes' : 'no'}`,
    `  MCP config: ${plan.checks.mcp_server_configured ? 'found' : 'not found (add an [mcp_servers.' + plan.mcp_server + '] block)'}`,
    `  Database:   ${plan.checks.toolseed_database ? 'found' : 'not found (MCP will create it on first use)'}`,
  ];
  if (!plan.applied) lines.push('', 'Run again with --apply to write these files.');
  return lines.join('\n');
}

async function main() {
  const {values} = parseArgs({
    strict: false,
    options: {
      apply: {type: 'boolean', default: false},
      uninstall: {type: 'boolean', default: false},
      'codex-home': {type: 'string'},
      'data-dir': {type: 'string'},
      'mcp-server': {type: 'string', default: 'toolseed'},
      codex: {type: 'string'},
      node: {type: 'string'},
      python: {type: 'string'},
      'skill-source': {type: 'string'},
      'hook-script': {type: 'string'},
      'no-agents-md': {type: 'boolean', default: false},
      'no-trust': {type: 'boolean', default: false},
      json: {type: 'boolean', default: false},
      cwd: {type: 'string'},
    },
  });
  try {
    if (values.uninstall) {
      const plan = uninstallCodexAdapter({
        apply: values.apply,
        codexHome: values['codex-home'],
      });
      process.stdout.write(values.json ? `${JSON.stringify(plan, null, 2)}\n` : `${plan.applied
        ? 'Removed the ToolSeed Codex adapter'
        : 'Dry run: would remove the ToolSeed Codex adapter'}\n  Skill: ${plan.removed.skill}\n`
        + `  Hook handlers: ${plan.removed.hooks}\n  AGENTS.md: ${plan.removed.agents}\n`
        + `  Adapter state: ${plan.removed.adapter_state}\n  Preserved: ${plan.preserved}\n`);
      return;
    }
    const plan = await installCodexAdapter({
      apply: values.apply,
      codexHome: values['codex-home'],
      dataDir: values['data-dir'],
      mcpServer: values['mcp-server'],
      codex: values.codex,
      nodePath: values.node,
      python: values.python,
      skillSource: values['skill-source'],
      hookScript: values['hook-script'],
      trust: values['no-trust'] ? false : true,
      agentsMd: values['no-agents-md'] ? false : true,
      cwd: values.cwd,
    });
    process.stdout.write(values.json ? `${JSON.stringify(plan, null, 2)}\n` : `${textReport(plan)}\n`);
    process.exitCode = values.apply && !plan.ready ? 1 : 0;
  } catch (error) {
    process.stderr.write(`toolseed-codex install failed: ${error.message}\n`);
    process.exitCode = 1;
  }
}

if (import.meta.url === `file://${process.argv[1]?.replace(/\\/g, '/')}` || process.argv[1]?.endsWith('install.mjs')) {
  await main();
}
