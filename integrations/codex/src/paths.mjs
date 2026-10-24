import {homedir} from 'node:os';
import {isAbsolute, join, resolve} from 'node:path';

export function resolveCodexHome(explicit) {
  const value = explicit || process.env.CODEX_HOME || join(homedir(), '.codex');
  return resolve(value);
}

export function adapterDir(codexHome) {
  return join(codexHome, '.toolseed-codex');
}

export function defaultStateDir(codexHome) {
  return join(adapterDir(codexHome), 'state');
}

export function defaultLogDir(codexHome) {
  return adapterDir(codexHome);
}

export function resolveDataDir(explicit) {
  const value = explicit || process.env.TOOLSEED_DATA_DIR || join(homedir(), '.toolseed');
  return resolve(value);
}

export function isAbsolutePath(value) {
  return typeof value === 'string' && isAbsolute(value);
}
