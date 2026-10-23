import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
const execute = promisify(execFile);

// This is a UI adapter allowlist, not an extra Agent/MCP tool.
export function queryArguments(route, params = {}) {
  if (!params || typeof params !== 'object' || Array.isArray(params)) throw new Error('INVALID_ARGUMENT');
  const commands = {'/api/overview':['status'], '/api/capabilities':['capabilities','list'],
    '/api/capability':['capabilities','show'], '/api/activity':['activity'], '/api/evidence':['evidence']};
  if (!Object.hasOwn(commands,route)) throw new Error('READ_ONLY');
  const args = [...commands[route]];
  const allowed = route === '/api/capability' ? ['id'] : route === '/api/capabilities'
    ? ['q','limit','offset'] : route === '/api/overview' ? [] : ['type','capability','limit','offset'];
  // The existing shared UI sends these empty cross-page filters. Ignore empty values,
  // but reject any populated field outside the route's own fixed contract.
  for (const [key,value] of Object.entries(params)) {
    if (!['q','id','limit','offset','type','capability'].includes(key)) throw new Error('INVALID_ARGUMENT');
    if (typeof value !== 'string' && typeof value !== 'number') throw new Error('INVALID_ARGUMENT');
    if (String(value).length > 2048 || String(value).includes('\0')) throw new Error('INVALID_ARGUMENT');
    if (!allowed.includes(key)) {
      if (value === '' || (route === '/api/overview' && ['limit','offset'].includes(key))) continue;
      throw new Error('INVALID_ARGUMENT');
    }
  }
  if (route === '/api/capability') {
    if (!/^cap_[A-Za-z0-9_-]{1,120}$/.test(params.id || '')) throw new Error('INVALID_ARGUMENT');
    args.push(params.id);
  }
  for (const key of ['limit','offset']) {
    if (!allowed.includes(key) || params[key] === undefined || params[key] === '') continue;
    const n = Number(params[key]);
    if (!Number.isSafeInteger(n) || n < (key === 'limit' ? 1 : 0) || n > (key === 'limit' ? 100 : 2147483647)) throw new Error('INVALID_ARGUMENT');
    args.push(`--${key}=${n}`);
  }
  for (const [key,flag] of [['q','query'],['type','type'],['capability','capability']]) {
    if (allowed.includes(key) && params[key]) args.push(`--${flag}=${params[key]}`);
  }
  return args;
}

export function createReader(config, run = execute) {
  let active = 0;
  return async (route, params, signal) => {
    const args = queryArguments(route,params);
    if (active >= 4) return {error:{code:'UI_BUSY',message:'只读查询正忙，请稍后刷新。'}};
    active++;
    try {
      const result = await run(config.python || 'python', ['-X','utf8','-m','toolseed',...args,
        ...(config.dataDir ? ['--data-dir',config.dataDir] : [])],
      {windowsHide:true, shell:false, timeout:10000, maxBuffer:2*1024*1024, signal});
      return JSON.parse(result.stdout);
    } catch (error) {
      // The CLI uses exit 2 for structured read failures. Preserve its safe envelope.
      if (typeof error.stdout === 'string') {
        try {const body=JSON.parse(error.stdout);if(body.error?.code && body.error?.message)return body;} catch {}
      }
      return {error:{code:'QUERY_UNAVAILABLE',message:'无法运行 ToolSeed 只读查询。检查插件配置中的 Python、ToolSeed 安装和数据目录。'}};
    } finally {active--;}
  };
}

export function createFetchHandler(read, lifetime) {
  return async request => {
    const headers={'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'};
    let body;
    try {
      if (request.method !== 'POST') return new Response('read-only query transport',{status:405});
      if ((request.headers.get('content-type') || '').split(';')[0] !== 'application/json') return new Response('JSON required',{status:415});
      const raw=await request.text();
      if (raw.length>8192) return new Response('request too large',{status:413});
      body=JSON.parse(raw);
      if (body.type !== 'client-request' || body.method !== 'toolseed.read' || typeof body.rpcId !== 'string' || body.rpcId.length>160) throw new Error('INVALID_ARGUMENT');
      const payload=body.payload;
      if (!payload || Object.keys(payload).some(key=>!['route','params'].includes(key))) throw new Error('INVALID_ARGUMENT');
      const value=await read(payload.route,payload.params,AbortSignal.any([request.signal,lifetime]));
      return new Response(JSON.stringify({type:'server-response',rpcId:body.rpcId,result:{ok:true,value}}),{headers});
    } catch {
      if (typeof body?.rpcId !== 'string') return new Response('invalid read request',{status:400});
      return new Response(JSON.stringify({type:'server-response',rpcId:body.rpcId,
        result:{ok:false,error:{code:'toolseed/invalid-read',message:'仅允许预定义的只读管理查询。',details:{}}}}),{headers});
    }
  };
}
