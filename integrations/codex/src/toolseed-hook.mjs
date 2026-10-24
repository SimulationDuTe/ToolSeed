#!/usr/bin/env node
import {appendFileSync, readFileSync} from 'node:fs';
import {parseArgs} from 'node:util';
import {handlePostToolUse} from './opportunities.mjs';
import {defaultLogDir, defaultStateDir, resolveCodexHome} from './paths.mjs';

function trace(line) {
  const path = process.env.TOOLSEED_CODEX_TRACE;
  if (!path) return;
  try {
    appendFileSync(path, `${new Date().toISOString()} ${line}\n`);
  } catch {
    // Trace output is diagnostic only.
  }
}

function parseOptions(argv) {
  const {values} = parseArgs({
    args: argv,
    strict: false,
    options: {
      'mcp-server': {type: 'string', default: 'toolseed'},
      threshold: {type: 'string', default: '3'},
      'state-dir': {type: 'string'},
      'log-dir': {type: 'string'},
      'codex-home': {type: 'string'},
      'no-log': {type: 'boolean', default: false},
    },
  });
  const threshold = Number(values.threshold);
  return {
    mcpServer: String(values['mcp-server'] || 'toolseed'),
    threshold: Number.isSafeInteger(threshold) && threshold >= 1 && threshold <= 20 ? threshold : 3,
    codexHome: resolveCodexHome(values['codex-home']),
    stateDir: values['state-dir'] ? String(values['state-dir']) : defaultStateDir(resolveCodexHome(values['codex-home'])),
    logDir: values['no-log'] ? undefined
      : values['log-dir'] ? String(values['log-dir']) : defaultLogDir(resolveCodexHome(values['codex-home'])),
  };
}

function readInput() {
  try {
    const text = readFileSync(0, 'utf8').replace(/^\uFEFF/, '');
    trace(`stdin_bytes=${Buffer.byteLength(text)}`);
    if (!text.trim()) return {};
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      trace(`event=${parsed.hook_event_name} tool=${parsed.tool_name} `
        + `response_type=${typeof parsed.tool_response} `
        + `response_keys=${parsed.tool_response && typeof parsed.tool_response === 'object'
          ? JSON.stringify(Object.keys(parsed.tool_response).slice(0, 12)) : 'none'}`);
      return parsed;
    }
    return {};
  } catch (error) {
    trace(`stdin_error=${error?.name ?? 'Error'}`);
    return {};
  }
}

async function main() {
  let output = {};
  let options;
  trace(`invoked ${JSON.stringify(process.argv.slice(2))}`);
  try {
    options = parseOptions(process.argv.slice(2));
  } catch {
    process.stdout.write('{}');
    return;
  }
  try {
    output = await handlePostToolUse(readInput(), options);
    trace(`output=${JSON.stringify(output).slice(0, 240)}`);
  } catch (error) {
    trace(`handler_error=${error?.name ?? 'Error'}`);
    output = {};
  }
  process.stdout.write(JSON.stringify(output));
}

await main();
