import {appendFileSync, existsSync, mkdirSync, renameSync, statSync, unlinkSync} from 'node:fs';
import {join} from 'node:path';
import {sha256} from './state.mjs';

export const MAX_LOG_BYTES = 1024 * 1024;

export function shortId(value) {
  if (typeof value !== 'string' || value.length === 0) return null;
  return sha256(value).slice(0, 16);
}

export function safeId(value) {
  return typeof value === 'string' && /^(cap|ver|inv)_[A-Za-z0-9_-]{1,120}$/.test(value)
    ? value
    : null;
}

export function appendEvent(logDir, event, {maxBytes = MAX_LOG_BYTES} = {}) {
  if (!logDir) return false;
  try {
    mkdirSync(logDir, {recursive: true});
    const path = join(logDir, 'events.jsonl');
    if (existsSync(path) && statSync(path).size >= maxBytes) {
      const rotated = join(logDir, 'events.1.jsonl');
      try {
        unlinkSync(rotated);
      } catch {
        // No previous rotation is fine.
      }
      renameSync(path, rotated);
    }
    appendFileSync(path, `${JSON.stringify({
      time: new Date().toISOString(),
      host: 'codex',
      adapter: 'codex',
      adoption: 'unknown',
      task_outcome: 'unknown',
      ...event,
    })}\n`, {encoding: 'utf8', mode: 0o600});
    return true;
  } catch {
    // Observability failure must never block the user's task.
    return false;
  }
}
