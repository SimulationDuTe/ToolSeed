import {createHash} from 'node:crypto';
import {
  closeSync,
  existsSync,
  mkdirSync,
  openSync,
  readFileSync,
  readdirSync,
  renameSync,
  statSync,
  unlinkSync,
  writeFileSync,
} from 'node:fs';
import {dirname, join} from 'node:path';
import {adapterDir, defaultStateDir} from './paths.mjs';

export const STATE_VERSION = 1;
export const STALE_STATE_MS = 24 * 60 * 60 * 1000;
const LOCK_STALE_MS = 30_000;
const LOCK_WAIT_MS = 3_000;

export function sha256(value) {
  return createHash('sha256').update(String(value)).digest('hex');
}

export function statePath(stateDir, sessionId, turnId) {
  const key = sha256(`${String(sessionId)}\u0000${String(turnId)}`).slice(0, 32);
  return join(stateDir, `${key}.json`);
}

export function emptyState(sessionId, turnId) {
  return {
    v: STATE_VERSION,
    session_hash: sha256(String(sessionId)).slice(0, 16),
    turn_hash: sha256(String(turnId)).slice(0, 16),
    executions: 0,
    seen: [],
    groups: {},
    opportunity_id: null,
    prompted: false,
    search_observed: false,
    updated_at: new Date().toISOString(),
  };
}

export function loadState(path, sessionId, turnId) {
  try {
    const parsed = JSON.parse(readFileSync(path, 'utf8'));
    if (parsed?.v !== STATE_VERSION || !Array.isArray(parsed.seen) || typeof parsed.groups !== 'object') {
      return emptyState(sessionId, turnId);
    }
    return {
      ...emptyState(sessionId, turnId),
      ...parsed,
      seen: parsed.seen.filter(value => typeof value === 'string').slice(-256),
      groups: Object.fromEntries(
        Object.entries(parsed.groups)
          .filter(([key, value]) => typeof key === 'string' && Number.isSafeInteger(value) && value > 0)
          .slice(0, 16),
      ),
    };
  } catch {
    return emptyState(sessionId, turnId);
  }
}

export function saveState(path, state) {
  mkdirSync(dirname(path), {recursive: true});
  const tmp = `${path}.tmp-${process.pid}-${Math.random().toString(16).slice(2)}`;
  writeFileSync(tmp, `${JSON.stringify(state)}\n`, {mode: 0o600});
  renameSync(tmp, path);
}

export async function withStateLock(path, action) {
  mkdirSync(dirname(path), {recursive: true});
  const lock = `${path}.lock`;
  const deadline = Date.now() + LOCK_WAIT_MS;
  let fd;
  while (fd === undefined) {
    try {
      fd = openSync(lock, 'wx');
      writeFileSync(fd, `${process.pid} ${Date.now()}\n`);
    } catch (error) {
      if (error?.code !== 'EEXIST') throw error;
      try {
        const stat = statSync(lock);
        if (Date.now() - stat.mtimeMs > LOCK_STALE_MS) {
          unlinkSync(lock);
          continue;
        }
      } catch {
        // Another process removed the lock between open and stat.
      }
      if (Date.now() >= deadline) return {locked: false, value: undefined};
      await new Promise(resolve => setTimeout(resolve, 25));
    }
  }
  try {
    return {locked: true, value: await action()};
  } finally {
    try {
      closeSync(fd);
    } catch {
      // Best effort.
    }
    try {
      unlinkSync(lock);
    } catch {
      // Best effort.
    }
  }
}

export function pruneStaleStates(stateDir, now = Date.now(), maxAgeMs = STALE_STATE_MS) {
  if (!existsSync(stateDir)) return 0;
  let removed = 0;
  try {
    for (const entry of readdirSync(stateDir, {withFileTypes: true})) {
      if (!entry.isFile() || !entry.name.endsWith('.json')) continue;
      const path = join(stateDir, entry.name);
      try {
        if (now - statSync(path).mtimeMs > maxAgeMs) {
          unlinkSync(path);
          removed += 1;
        }
      } catch {
        // A concurrent hook may have removed it.
      }
    }
  } catch {
    // State pruning is best effort and must not block the task.
  }
  return removed;
}

export function ensureAdapterDirs(codexHome) {
  const root = adapterDir(codexHome);
  mkdirSync(defaultStateDir(codexHome), {recursive: true});
  mkdirSync(root, {recursive: true});
  return {root, stateDir: defaultStateDir(codexHome), logDir: root};
}
