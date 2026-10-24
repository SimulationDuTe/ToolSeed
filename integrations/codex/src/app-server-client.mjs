import {spawn} from 'node:child_process';
import {createServer} from 'node:net';

const CONNECT_TIMEOUT_MS = 30_000;
const RPC_TIMEOUT_MS = 20_000;

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function freePort() {
  return await new Promise((resolve, reject) => {
    const server = createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      const port = typeof address === 'object' && address ? address.port : 0;
      server.close(() => resolve(port));
    });
  });
}

async function connectWithRetry(url, deadline = Date.now() + CONNECT_TIMEOUT_MS) {
  if (typeof WebSocket !== 'function') {
    throw new Error('This Node.js runtime has no WebSocket API; use Node.js 22+ for install/verify.');
  }
  let lastError;
  while (Date.now() < deadline) {
    try {
      return await new Promise((resolve, reject) => {
        const ws = new WebSocket(url);
        const timer = setTimeout(() => {
          try { ws.close(); } catch {}
          reject(new Error('WebSocket open timed out'));
        }, 1_000);
        ws.addEventListener('open', () => {
          clearTimeout(timer);
          resolve(ws);
        }, {once: true});
        ws.addEventListener('error', () => {
          clearTimeout(timer);
          try { ws.close(); } catch {}
          reject(new Error('WebSocket connection failed'));
        }, {once: true});
      });
    } catch (error) {
      lastError = error;
      await delay(150);
    }
  }
  throw lastError ?? new Error('Could not connect to the Codex app-server');
}

function rpcSession(ws, timeoutMs) {
  let nextId = 1;
  const pending = new Map();
  ws.addEventListener('message', event => {
    let message;
    try { message = JSON.parse(String(event.data)); } catch { return; }
    if (message?.id && pending.has(message.id)) {
      const settle = pending.get(message.id);
      pending.delete(message.id);
      settle(message);
    }
  });
  ws.addEventListener('close', () => {
    for (const settle of pending.values()) settle({closed: true});
    pending.clear();
  });
  return {
    rpc(method, params) {
      return new Promise(resolve => {
        const id = nextId++;
        pending.set(id, resolve);
        ws.send(JSON.stringify({jsonrpc: '2.0', id, method, params}));
        setTimeout(() => {
          if (pending.has(id)) {
            pending.delete(id);
            resolve({timeout: true, id, method});
          }
        }, timeoutMs).unref?.();
      });
    },
    notify(method, params) {
      ws.send(JSON.stringify({jsonrpc: '2.0', method, ...(params === undefined ? {} : {params})}));
    },
  };
}

/**
 * Query the installed Codex app-server over its public loopback WebSocket
 * transport. The child process uses stdio:'ignore' so the installer also works
 * in environments that forbid anonymous pipe creation.
 */
export async function queryCodexAppServer({
  codex,
  codexHome,
  cwd = process.cwd(),
  calls = [],
  connectTimeoutMs = CONNECT_TIMEOUT_MS,
  rpcTimeoutMs = RPC_TIMEOUT_MS,
}) {
  if (!codex) throw new Error('Codex binary is required');
  const port = await freePort();
  if (!port) throw new Error('Could not allocate a loopback port');
  const child = spawn(codex, ['app-server', '--listen', `ws://127.0.0.1:${port}`], {
    cwd,
    env: {...process.env, CODEX_HOME: codexHome},
    stdio: 'ignore',
    windowsHide: true,
  });
  let ws;
  try {
    ws = await connectWithRetry(`ws://127.0.0.1:${port}`, Date.now() + connectTimeoutMs);
    const session = rpcSession(ws, rpcTimeoutMs);
    const init = await session.rpc('initialize', {
      clientInfo: {name: 'toolseed-codex-adapter', version: '0.1.0'},
      capabilities: {experimentalApi: false},
    });
    if (!init || init.timeout || init.closed || init.error) {
      throw new Error(`Codex app-server initialize failed: ${JSON.stringify(init?.error ?? 'no response')}`);
    }
    session.notify('initialized');
    const results = [];
    for (const call of calls) {
      const response = await session.rpc(call.method, call.params);
      results.push({method: call.method, response});
    }
    const version = /(\d+\.\d+\.\d+[A-Za-z0-9.+-]*)/.exec(String(init.result?.userAgent ?? ''))?.[1] ?? null;
    return {version, init: init.result, results};
  } finally {
    try { ws?.close(); } catch {}
    try { child.kill(); } catch {}
  }
}
