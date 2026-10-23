import {test} from 'node:test';
import assert from 'node:assert/strict';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {mkdtemp,mkdir,rm,readFile} from 'node:fs/promises';
import {join,resolve,sep} from 'node:path';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';
import {createReader,queryArguments,createFetchHandler} from '../backend.js';
const execute=promisify(execFile);
const root=fileURLToPath(new URL('../../../',import.meta.url));

test('query allowlist cannot invoke mutation, execution, a shell or select a data directory',()=>{
  assert.deepEqual(queryArguments('/api/capabilities',{q:'--data-dir=other'}),['capabilities','list','--query=--data-dir=other']);
  assert.deepEqual(queryArguments('/api/capability',{id:'cap_safe'}),['capabilities','show','cap_safe']);
  assert.deepEqual(queryArguments('/api/overview',{q:'',type:'',limit:30,offset:0}),['status']);
  for(const [route,params] of [['/api/run',{}],['/api/capability',{id:'--help'}],
    ['/api/activity',{dataDir:'elsewhere'}],['/api/activity',{limit:101}],['/api/activity',{offset:-1}],
    ['/api/evidence',{type:{bad:true}}],['/api/overview',{type:'tool_call_failed'}],['/api/capabilities',{q:'\0'}]]) {
    assert.throws(()=>queryArguments(route,params));
  }
});

test('subprocess uses fixed executable and data directory without shell; errors are safe',async()=>{
  let invocation;
  const read=createReader({python:'fixed-python',dataDir:'fixed-dir'},async(...args)=>{invocation=args;return {stdout:'{"items":[],"total":0}'};});
  await read('/api/activity',{type:'$(secret)',limit:10});
  assert.equal(invocation[0],'fixed-python');
  assert.deepEqual(invocation[1],['-X','utf8','-m','toolseed','activity','--limit=10','--type=$(secret)','--data-dir','fixed-dir']);
  assert.equal(invocation[2].shell,false);
  assert.equal(invocation[2].windowsHide,true);
  assert.equal(invocation[2].timeout,10000);
  const unavailable=createReader({},async()=>{throw new Error('secret stderr');});
  assert.equal((await unavailable('/api/overview',{})).error.code,'QUERY_UNAVAILABLE');
  const missing=createReader({},async()=>{throw {stdout:'{"error":{"code":"DATABASE_MISSING","message":"missing"}}'};});
  assert.equal((await missing('/api/overview',{})).error.code,'DATABASE_MISSING');
});

test('concurrent reads are bounded and recover after completion',async()=>{
  const complete=[];
  const read=createReader({},()=>new Promise(resolve=>complete.push(()=>resolve({stdout:'{}'}))));
  const active=Array.from({length:4},()=>read('/api/overview',{}));
  assert.equal((await read('/api/overview',{})).error.code,'UI_BUSY');
  complete.forEach(done=>done());await Promise.all(active);
  const next=read('/api/overview',{});complete.at(-1)();assert.deepEqual(await next,{});
});

test('public Connection Fetch route uses its RPC envelope and rejects malformed requests',async()=>{
  const lifetime=new AbortController();let calls=0;
  const handler=createFetchHandler(async(route,params)=>{calls++;queryArguments(route,params);return {items:[]};},lifetime.signal);
  const request=(body,method='POST',contentType='application/json')=>new Request('http://localhost/api/toolseed.read',
    {method,headers:{'content-type':contentType},...(method==='GET'?{}:{body:JSON.stringify(body)})});
  const body={type:'client-request',rpcId:'r1',method:'toolseed.read',payload:{route:'/api/activity',params:{}}};
  const response=await handler(request(body));
  assert.equal(response.headers.get('cache-control'),'no-store');
  assert.deepEqual(await response.json(),{type:'server-response',rpcId:'r1',result:{ok:true,value:{items:[]}}});
  assert.equal((await handler(request(body,'GET'))).status,405);
  assert.equal((await handler(request(body,'POST','text/plain'))).status,415);
  assert.equal((await handler(request({...body,payload:{route:'/api/run',params:{}}}))).status,200);
  const rejected=await (await handler(request({...body,method:'toolbox_run'}))).json();
  assert.equal(rejected.result.ok,false);
  assert.equal((await handler(request({}))).status,400);
  assert.equal((await handler(request({...body,payload:{route:'/api/activity',dataDir:'other'}}))).status,200);
  assert.equal(calls,2); // invalid route reaches only the fixed query allowlist
});

test('real Python Core commits become visible through the native read adapter',async()=>{
  const base=resolve(root,'tests/.data');
  await mkdir(base,{recursive:true});
  const dir=await mkdtemp(join(base,'dsh-'));
  assert.ok(resolve(dir).startsWith(base+sep));
  const python=process.env.TOOLSEED_TEST_PYTHON||resolve(root,'.venv/Scripts/python.exe');
  const seed=`from toolseed import ToolSeed
from tests.helpers import candidate
import sys,json
c=ToolSeed(sys.argv[1]); s=c.toolbox_save(candidate(),'native fixture'); c.toolbox_run(s['capability_id']); c.toolbox_run('cap_missing'); c.close(); print(json.dumps(s))`;
  try{
    const saved=JSON.parse((await execute(python,['-X','utf8','-c',seed,dir],{cwd:root,windowsHide:true})).stdout);
    const read=createReader({python,dataDir:dir});
    const status=await read('/api/overview',{});
    assert.equal(status.counts.capabilities,1);assert.equal(status.database.schema,6);
    assert.equal(status.adoption,null);
    const caps=await read('/api/capabilities',{q:saved.capability_id});assert.equal(caps.total,1);
    const detail=await read('/api/capability',{id:saved.capability_id});assert.equal(detail.versions[0].content_hash,saved.content_hash);
    assert.equal((await read('/api/activity',{})).total,3);
    const evidence=await read('/api/evidence',{});assert.equal(evidence.total,1);
    assert.equal(evidence.items[0].event_type,'procedure_delivered');
    await execute(python,['-X','utf8','-m','toolseed','search','{"query":"timeout"}','--data-dir',dir],{cwd:root,windowsHide:true});
    assert.equal((await read('/api/activity',{})).total,4);
    const missing=await createReader({python,dataDir:join(dir,'missing')})('/api/overview',{});
    assert.equal(missing.error.code,'DATABASE_MISSING');
  }finally{await rm(dir,{recursive:true,force:true});}
});

test('generated client registers only the official settings section and uses native controls',async()=>{
  const source=await readFile(new URL('../lib/client.js',import.meta.url),'utf8');
  let module;const effects=[];const registers=[];
  const primitives=Object.fromEntries(['Button','Input','Checkbox','SegmentedTabs','Menu','Modal'].map(name=>[name,`Native${name}`]));
  const React={createElement:(type,props,...children)=>({type,props,children}),useRef:()=>({current:null}),
    useState:value=>[typeof value==='function'?value():value,()=>{}],useEffect:effect=>effects.push(effect),useCallback:fn=>fn};
  const window={__ModuleLoader__:{load:entry=>{assert.equal(entry.id,'dsh-toolseed');module=entry.factory(name=>{
    if(name==='react')return React;
    assert.equal(name,'@deepseek-ai/dsh-client-ui-primitives');return primitives;
  });}}};
  vm.runInNewContext(source,{window,crypto,AbortController});
  module.apply({effect:fn=>effects.push(fn),connection:{rpc:{}},slots:{inject:(name,fn)=>fn(),register:(meta,component)=>registers.push({meta,component})}});
  assert.equal(registers.length,1);
  assert.equal(registers[0].meta.name,'settings.section');assert.equal(registers[0].meta.id,'toolseed');
  assert.equal(registers[0].meta.label,'ToolSeed');
  const panel=registers[0].component({connection:{}});
  assert.equal(panel.props.className,'toolseed-native ts-panel');
  assert.ok(panel.children.some(child=>child?.type===primitives.SegmentedTabs));
  const tabs=panel.children.find(child=>child?.type===primitives.SegmentedTabs);
  assert.deepEqual(Array.from(tabs.props.items,item=>item.label),['已入库能力','活动']);
  assert.ok(panel.children.some(child=>child?.type===primitives.Modal));
  assert.doesNotMatch(source,/sidebar\.panellist|srcDoc|createDocument|postMessage/);
});

test('native appearance only consumes host tokens and does not ship the standalone palette',async()=>{
  const styles=await readFile(new URL('../src/native.css',import.meta.url),'utf8');
  const source=await readFile(new URL('../lib/client.js',import.meta.url),'utf8');
  assert.doesNotMatch(styles,/:root|#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(|prefers-color-scheme|data-ds-dark-theme/);
  assert.doesNotMatch(source,/#f5f6f3|Segoe UI|installBridge|ThemeRuntime|setPreference/);
  assert.match(styles,/var\(--dsw-alias-label-primary\)/);
  assert.match(styles,/var\(--dsw-font-family\)/);
  assert.match(styles,/var\(--ds-font-family-code\)/);
  assert.match(styles,/var\(--dsh-content-font-size\)/);
});

test('shared native views escape stored data and distinguish an empty search from an empty library',async()=>{
  const source=(await readFile(new URL('../lib/client.js',import.meta.url),'utf8'))
    .replace('return module.exports;}});','window.testViews=views;return module.exports;}});');
  const window={__ModuleLoader__:{load:entry=>entry.factory(()=>({}))}};
  vm.runInNewContext(source,{window});
  const views=window.testViews;
  assert.match(views.capabilityCards([],'needle'),/没有找到匹配的能力/);
  assert.match(views.capabilityCards([],''),/还没有入库能力/);
  const unsafe='<script>window.injected=true</script>';
  const html=views.capabilityCards([{name:unsafe,capability_id:'cap_test',kind:'procedure',version_number:1}],'');
  assert.ok(html.includes('&lt;script&gt;'));assert.ok(!html.includes('<script>'));
  const detail=views.capabilityDetail({capability:{name:unsafe,capability_id:'cap_test'},
    versions:[{version_number:1,version_id:'ver_test',content:unsafe}],evidence:[]});
  assert.ok(detail.includes('&lt;script&gt;'));assert.ok(!detail.includes('<script>'));
});

async function sharedViews(){
  const source=(await readFile(new URL('../lib/client.js',import.meta.url),'utf8'))
    .replace('return module.exports;}});','window.testViews=views;return module.exports;}});');
  const window={__ModuleLoader__:{load:entry=>entry.factory(()=>({}))}};
  vm.runInNewContext(source,{window});return window.testViews;
}

test('ordinary cards use existing descriptions, mark tests, and hide identifiers in visible text',async()=>{
  const views=await sharedViews();
  const item={name:'alpha_integration_smoke',capability_id:'cap_internal',current_version_id:'ver_internal',
    description:'ToolSeed 接入自检：登记、检索、交付一次最小程序',when_to_use:'确认能力库可持久化',status:'ready'};
  assert.equal(views.capabilityTitle(item),'ToolSeed 接入自检');assert.equal(views.testMarked(item),true);
  const html=views.capabilityCards([item]);const visible=html.replace(/<[^>]*>/g,'');
  assert.match(visible,/测试能力/);assert.match(visible,/可提供指引/);
  assert.doesNotMatch(visible,/alpha_integration_smoke|cap_internal|ver_internal|已验证|任务成功/);
  assert.doesNotMatch(html,/<table/);
  const event={event_id:'ev_internal',capability_id:item.capability_id,event_type:'procedure_delivered',created_at:'2026-10-22T00:00:00Z'};
  const activity=views.activityCards([event],[item]);
  assert.match(activity,/交付了操作指引：ToolSeed 接入自检/);
  assert.doesNotMatch(activity.replace(/<[^>]*>/g,''),/ev_internal|alpha_integration_smoke|复用/);
  const detail=views.activityDetail(event,[item]);assert.match(detail,/高级信息/);
  assert.match(detail,/尚未记录/);assert.match(detail,/尚未确认/);
  assert.ok(detail.includes('ev_internal')); // retained in optional advanced data
});

test('description search covers later metadata pages without invoking public search or changing Core queries',async()=>{
  const views=await sharedViews();const calls=[];
  const items=Array.from({length:101},(_,i)=>({capability_id:'cap_'+i,name:'internal_'+i,description:i===100?'排查网络超时':'其他方法'}));
  const read=async(route,params)=>{calls.push({route,params});
    if(route==='/api/overview')return {counts:{capabilities:101},guidance_deliveries:0};
    assert.equal(route,'/api/capabilities');assert.equal(params.limit,100);
    return {items:items.slice(params.offset,params.offset+100),total:101};};
  const screen=await views.readScreen(read,'capabilities',0,'',new AbortController().signal);
  assert.equal(screen.catalogComplete,true);
  assert.equal(views.filterCapabilities(screen.catalog,'网络超时')[0].capability_id,'cap_100');
  assert.equal(calls.length,3);
  assert.equal(calls.some(call=>/search|save|run/.test(call.route)),false);
});

test('delivery and verification facts remain separate from readiness and unknown task results',async()=>{
  const views=await sharedViews();
  const catalog=[{capability_id:'cap_a',delivery_count:99}];
  const base={capability:{capability_id:'cap_a',name:'internal_method',current_version_id:'ver_a'},
    versions:[{version_id:'ver_a',version_number:1,content_hash:'hash',description:'排查超时',status:'ready',content:null}],evidence:[]};
  const read=async(route,params)=>{
    if(route==='/api/capability')return base;
    assert.equal(route,'/api/evidence');assert.equal(params.capability,'cap_a');
    return params.type==='procedure_delivered'?{total:2,items:[]}:{total:0,items:[]};
  };
  const data=await views.readCapability(read,'cap_a',catalog,new AbortController().signal);
  assert.equal(data.delivery_record_count,2);
  const html=views.capabilityDetail(data),ordinary=html.split('<details class="ts-advanced">')[0].replace(/<[^>]*>/g,'');
  assert.match(ordinary,/2 条交付记录/);assert.match(ordinary,/尚未记录验证/);assert.match(ordinary,/尚未确认/);
  assert.doesNotMatch(ordinary,/99|ver_a|cap_a|internal_method|复用次数/);
  const stale=views.verificationText(base.versions[0],[{version_id:'ver_a',content_hash:'hash',verification_outcome:'passed',validity:'stale',source_type:'test_runner'}]);
  assert.match(stale,/需要重新核验/);
  const failure=views.activityDetail({event_id:'ev_f',event_type:'tool_call_failed',outcome:'failure',failure:{error_code:'CAPABILITY_NOT_FOUND'}},[]);
  assert.match(failure,/没有找到这项能力/);assert.doesNotMatch(failure.split('<details class="ts-advanced">')[0],/任务失败|CAPABILITY_NOT_FOUND/);
});
