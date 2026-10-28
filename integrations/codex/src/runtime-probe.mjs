import {execFile} from 'node:child_process';
import {join, resolve} from 'node:path';
import {promisify} from 'node:util';

const execute = promisify(execFile);
const REQUIRED = ['search', 'save', 'run', 'stats', 'learn'].map(name => 'toolbox_' + name);
// Read trusted configuration with the standard TOML parser. Only local Python
// or toolseed-mcp commands are probed; package-manager wrappers are not started.
// The configured environment stays inside this process and is never returned.
const SCRIPT = String.raw`
import json, os, pathlib, shutil, subprocess, sys, tomllib
try:
    paths, name = json.loads(sys.argv[1]), sys.argv[2]
    server = None
    for value in paths:
        path = pathlib.Path(value)
        if path.is_file():
            config = tomllib.loads(path.read_text(encoding='utf-8-sig'))
            if name in config.get('mcp_servers', {}):
                server = config['mcp_servers'][name]
    if not isinstance(server, dict) or server.get('enabled', True) is not True:
        raise ValueError('MCP_NOT_CONFIGURED')
    command, args = server.get('command'), server.get('args', [])
    if not isinstance(command, str) or not isinstance(args, list) or any(not isinstance(v, str) for v in args):
        raise ValueError('MCP_CONFIGURATION_INVALID')
    leaf = pathlib.Path(command).name.lower()
    python = leaf in ('python', 'python3', 'python.exe', 'python3.exe') or (leaf.startswith('python3.') and leaf.removesuffix('.exe').replace('.', '').isalnum())
    if leaf not in ('toolseed-mcp', 'toolseed-mcp.exe') and not (python and '-m' in args and args[args.index('-m')+1:args.index('-m')+2] == ['toolseed.mcp_server']):
        raise ValueError('MCP_RUNTIME_PROBE_UNSUPPORTED')
    env = dict(os.environ)
    extra = server.get('env', {})
    if not isinstance(extra, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k,v in extra.items()):
        raise ValueError('MCP_CONFIGURATION_INVALID')
    env.update(extra)
    if not shutil.which(command, path=env.get('PATH')) and not pathlib.Path(command).is_file():
        raise ValueError('MCP_RUNTIME_MISSING')
    result = subprocess.run([command, *args, '--probe'], capture_output=True, text=True, encoding='utf-8',
                            timeout=3, check=False, env=env)
    if result.returncode != 0:
        raise ValueError('MCP_RUNTIME_PROBE_FAILED')
    body = json.loads(result.stdout)
    print(json.dumps(body))
except Exception as error:
    code = str(error) if isinstance(error, ValueError) and str(error).startswith('MCP_') else 'MCP_RUNTIME_PROBE_FAILED'
    print(json.dumps({'ok': False, 'code': code}))
`;

export function assessRuntime(body, dataDir) {
  if (!body?.ok) return {ok: false, code: body?.code ?? 'MCP_RUNTIME_PROBE_FAILED'};
  if (!Array.isArray(body.tools) || !REQUIRED.every(name => body.tools.includes(name))) {
    return {ok: false, code: 'MCP_TOOLS_INCOMPLETE'};
  }
  if (body.features?.read_only_search !== true || body.features?.revision_base_binding !== true) {
    return {ok: false, code: 'MCP_RUNTIME_INCOMPATIBLE'};
  }
  const normalize = value => process.platform === 'win32' ? resolve(value).toLowerCase() : resolve(value);
  if (typeof body.data_dir !== 'string' || normalize(body.data_dir) !== normalize(dataDir)) {
    return {ok: false, code: 'MCP_DATA_DIRECTORY_MISMATCH'};
  }
  return {ok: true, tools: body.tools, features: body.features, data_dir: body.data_dir};
}

export async function probeRuntime({python = 'python', codexHome, cwd, dataDir, mcpServer}, run = execute) {
  const paths = [join(codexHome, 'config.toml'), join(cwd, '.codex', 'config.toml'), join(cwd, 'config.toml')];
  try {
    const result = await run(python, ['-B', '-X', 'utf8', '-c', SCRIPT, JSON.stringify(paths), mcpServer],
      {cwd, windowsHide: true, shell: false, timeout: 5000, maxBuffer: 65536});
    return assessRuntime(JSON.parse(result.stdout), dataDir);
  } catch {return {ok: false, code: 'MCP_RUNTIME_PROBE_FAILED'};}
}
