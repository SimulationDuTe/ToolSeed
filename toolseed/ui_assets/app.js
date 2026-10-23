"use strict";
// TOOLSEED_SHARED_VIEWS_START
const text = value => typeof value === 'string' ? value.replace(/[\x00-\x1f\x7f]/g,' ').replace(/\s+/g,' ').trim() : '';
const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const short = (value,length=64) => {const s=text(value);return s.length>length?s.slice(0,length).trimEnd()+'…':s;};
const publicText = value => text(value).replace(/\b(?:cap|ver|ev|evt|inv)_[A-Za-z0-9_-]+\b/g,'相关记录');
const count = value => Number.isFinite(value)?value.toLocaleString('zh-CN'):'尚未记录';
const time = value => {const d=new Date(value);return value&&!Number.isNaN(d.getTime())?d.toLocaleString('zh-CN',{month:'long',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}):'时间尚未记录';};
const json = value => esc(JSON.stringify(value,null,2));
const testMarked = item => /(?:^|[^a-z0-9])(?:tests?|smoke|fixture|demo|e2e)(?:[^a-z0-9]|$)|测试|自检|演示/i.test([item?.name,item?.description,...(Array.isArray(item?.tags)?item.tags:[])].join(' '));
const technicalName = value => /_|\b(?:cap|ver|ev|evt|inv)_[\w-]+\b/.test(value);
function capabilityTitle(item={}) {
  const description=publicText(item.description),name=publicText(item.name);
  if(description&&(technicalName(name)||testMarked(item)||!name))return short(description.split(/[。！？.!?：:\n]/)[0]||description,42);
  return short(name&&!technicalName(name)?name:description||'未命名能力',42);
}
function capabilityDescription(item={}) {
  const description=publicText(item.description),title=capabilityTitle(item);
  if(description.startsWith(title)&&description.length>title.length)return short(description.slice(title.length).replace(/^[：:。.!\s]+/,''),100);
  return description&&description!==title?short(description,100):'已保存的操作指引';
}
function capabilityState(item={}) {
  if(item.archived_at)return {label:'已停用',tone:'muted'};
  if(item.quarantined_at||item.status==='quarantined')return {label:'暂不可用',tone:'warning'};
  if(item.status==='ready'&&item.current_version_id)return {label:'可提供指引',tone:'available'};
  if(item.status==='candidate')return {label:'待验证',tone:'muted'};
  return {label:'状态尚未确认',tone:'muted'};
}
const tag = (label,tone='muted') => `<span class="ts-tag ts-${tone}">${esc(label)}</span>`;
const testTag = item => testMarked(item)?tag('测试能力','test'):'';
const empty = (title,description) => `<div class="ts-empty"><h3>${esc(title)}</h3><p>${esc(description)}</p></div>`;
function summary(data,catalog=[]) {
  if(!data)return '';
  return `<div class="ts-summary"><span><strong>${count(data.counts?.capabilities)}</strong> 项能力已入库</span><span><strong>${count(data.guidance_deliveries)}</strong> 次指引交付</span></div>`;
}
function filterCapabilities(items,query='') {
  const q=text(query).toLocaleLowerCase();
  return !q?items:items.filter(item=>[capabilityTitle(item),item.name,item.description,item.when_to_use,item.capability_id,...(Array.isArray(item.tags)?item.tags:[])].some(value=>text(value).toLocaleLowerCase().includes(q)));
}
function capabilityCards(items,query='') {
  if(!items.length)return empty(query?'没有找到匹配的能力':'还没有入库能力',query?'试试能力名称、说明或适用场景。':'保存一项真实的方法后，就会显示在这里。');
  return `<div class="ts-record-list">${items.map(item=>{const state=capabilityState(item);return `<article class="ts-record-card"><button type="button" class="ts-record-open" data-capability="${esc(item.capability_id)}"><span class="ts-record-head"><strong class="ts-card-title">${esc(capabilityTitle(item))}</strong><span class="ts-tags">${testTag(item)}${tag(state.label,state.tone)}</span></span><span class="ts-description">${esc(capabilityDescription(item))}</span><span class="ts-scenario"><span class="ts-muted">适用场景</span> ${esc(short(publicText(item.when_to_use)||'尚未记录',120))}</span><span class="ts-record-hint">查看详情<span aria-hidden="true"> →</span></span></button></article>`;}).join('')}</div>`;
}
const eventNames={procedure_saved:'保存了能力',search_performed:'检索了能力库',procedure_delivered:'交付了操作指引',duplicate_save:'保留了已有能力',tool_call_failed:'调用未完成',task_outcome_signal:'收到了任务结果记录',version_verification:'记录了版本验证',capability_quarantined:'暂停了能力',capability_released:'解除了能力暂停',capability_archived:'停用了能力',version_released:'版本回到待验证状态',version_promoted:'更新了可用版本',version_rolled_back:'恢复了先前版本',maintenance_dedup_baseline:'记录了维护检查'};
const sourceNames={core:'ToolSeed',agent:'Agent 自报',harness:'宿主',test_runner:'测试执行器',human:'人工',external_system:'外部系统'};
const errorNames={INVALID_ARGUMENT:'调用参数不符合要求',CONTRACT_VIOLATION:'保存内容未通过格式检查',POLICY_BLOCKED:'内容未通过安全检查',CAPABILITY_NOT_FOUND:'没有找到这项能力',CAPABILITY_NOT_READY:'这项能力还不能提供指引',CAPABILITY_ARCHIVED:'这项能力已停用',CAPABILITY_QUARANTINED:'这项能力已暂停使用',AMBIGUOUS_CAPABILITY_NAME:'名称对应了多项能力',UNSUPPORTED_CAPABILITY_KIND:'暂不支持这种能力类型',SAVE_PERSISTENCE_FAILED:'保存未完成',INTERNAL_ERROR:'调用时遇到内部错误'};
function relatedCapability(event,catalog=[]) {return catalog.find(item=>item.capability_id===event.capability_id)||{name:event.capability_name};}
function eventTitle(event,catalog=[]) {
  const item=relatedCapability(event,catalog),name=capabilityTitle(item);
  const action=eventNames[event.event_type]||'记录了一次活动';
  return event.capability_id&&name!=='未命名能力'?`${action}：${name}`:action;
}
function eventDescription(event) {
  if(event.failure)return errorNames[event.failure.error_code]||'具体原因尚未记录，可在详情中查看已有信息。';
  if(event.event_type==='search_performed')return Number.isFinite(event.quantity)?`返回了 ${event.quantity} 条结果。`:'检索结果数量尚未记录。';
  if(event.event_type==='procedure_delivered')return '已提供操作指引；是否被采用、任务是否完成，尚未确认。';
  if(event.event_type==='procedure_saved')return '内容已保存，可以查看适用场景和验证记录。';
  if(event.event_type==='duplicate_save')return '这份内容已入库，没有重复创建版本。';
  if(event.event_type==='version_verification')return `验证记录：${event.verification_outcome==='passed'?'通过':event.verification_outcome==='failed'?'未通过':'结果尚未记录'}；不表示任务已完成。`;
  if(event.event_type==='task_outcome_signal')return `结果记录：${({success:'成功',failure:'失败',partial:'部分完成',unknown:'尚未确认'})[event.outcome]||'尚未确认'}；来自${sourceNames[event.source_type]||'尚未记录的来源'}，尚未独立核验。`;
  return '已有持久化记录，详情中可查看具体内容。';
}
function activityCards(items,catalog=[]) {
  if(!items.length)return empty('还没有对应的活动','这里只显示已经记录的事情，未记录不代表没有发生。');
  return `<div class="ts-record-list">${items.map(event=>`<article class="ts-record-card"><button type="button" class="ts-record-open" data-event="${esc(event.event_id)}"><span class="ts-record-head"><strong class="ts-card-title">${esc(eventTitle(event,catalog))}</strong><time class="ts-time">${esc(time(event.created_at))}</time></span><span class="ts-description">${esc(eventDescription(event))}</span><span class="ts-record-foot">${testTag(relatedCapability(event,catalog))}<span class="ts-record-hint">查看记录<span aria-hidden="true"> →</span></span></span></button></article>`).join('')}</div>`;
}
const field = (label,value) => `<div class="ts-field"><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`;
const advanced = data => `<details class="ts-advanced"><summary>高级信息</summary><pre>${json(data)}</pre></details>`;
function verificationText(version,checks=[],complete=true) {
  const check=checks.find(event=>event.version_id===version.version_id&&event.content_hash===version.content_hash);
  if(!check)return complete?'尚未记录验证':'验证记录尚未加载完整';
  const outcome=check.verification_outcome==='passed'?'有通过验证的记录':check.verification_outcome==='failed'?'有未通过的验证记录':'验证结果尚未记录';
  const validity={valid:'记录当前有效',stale:'需要重新核验',superseded:'记录已被替代'}[check.validity]||'记录有效性尚未评估';
  return `${outcome} · ${validity}（${sourceNames[check.source_type]||'来源尚未记录'}）`;
}
function capabilityDetail(data) {
  const c=data.capability,versions=data.versions||[],current=versions.find(v=>v.version_id===c.current_version_id),latest=current||versions[0]||{};
  const item={...c,...latest},history=data.evidence||[],checks=data.verifications||[],state=capabilityState(item);
  const delivered=data.delivery_record_count;
  return `<div class="ts-detail-intro"><span class="ts-tags">${testTag(item)}${tag(state.label,state.tone)}</span><p>${esc(publicText(latest.description)||'能力说明尚未记录。')}</p></div><dl class="ts-facts">${field('适用场景',publicText(latest.when_to_use)||'尚未记录')}${field('验证记录',verificationText(latest,checks,data.verifications_complete===true))}</dl><section class="ts-detail-section"><h3>使用与结果</h3><dl class="ts-facts ts-stages">${field('能力保存','已入库')}${field('指引交付',Number.isFinite(delivered)?`${delivered} 条交付记录`:'尚未完整统计')}${field('Agent 实际采用','尚未记录')}${field('任务结果确认','尚未确认')}</dl><p class="ts-note">可提供指引与验证记录分别判断。交付次数不代表实际采用或任务成功。</p></section><details class="ts-detail-section"><summary>方法内容与版本</summary>${versions.map(v=>`<section class="ts-version"><h4>第 ${esc(v.version_number)} 版${v.version_id===c.current_version_id?' · 当前版本':' · 历史版本'}</h4><p>${esc(verificationText(v,checks,data.verifications_complete===true))}</p>${v.content!=null?`<details><summary>查看操作指引</summary><pre>${esc(v.content)}</pre></details>`:'<p class="ts-muted">此版本暂不提供指引正文。</p>'}${v.applicability?`<details><summary>适用范围</summary><dl class="ts-facts">${field('宿主',(v.applicability.harnesses||[]).join('、')||'未限定')}${field('操作系统',(v.applicability.operating_systems||[]).join('、')||'未限定')}${field('所需工具',(v.applicability.required_tools||[]).join('、')||'未记录')}</dl></details>`:''}</section>`).join('')}</details><details class="ts-detail-section"><summary>验证与结果记录${checks.length?`（${checks.length} 条验证记录）`:''}</summary>${checks.length?checks.map(event=>`<div class="ts-evidence"><p>${esc(eventDescription(event))}</p><span class="ts-muted">${esc(time(event.created_at))} · ${esc(sourceNames[event.source_type]||'来源尚未记录')}</span></div>`).join(''):`<p class="ts-muted">${data.verifications_complete?'尚未记录版本验证。':'验证记录尚未加载完整。'}</p>`}${history.filter(e=>e.event_type==='task_outcome_signal').map(e=>`<p>${esc(eventDescription(e))}</p>`).join('')}<p class="ts-note">结果来源是记录中的声明；面板没有独立核验任务产物。</p></details><details class="ts-detail-section"><summary>最近历史记录</summary>${activityCards(history,data.catalog||[])}${history.length>=30?'<p class="ts-note">这里只列出最近 30 条。</p>':''}<button class="ts-text-button" type="button" data-history="${esc(c.capability_id)}">查看此能力的全部活动</button></details>${advanced({capability:c,versions,verification_records:checks,recent_history:history})}`;
}
function activityDetail(event,catalog=[]) {
  const item=relatedCapability(event,catalog),source=sourceNames[event.source_type]||'尚未记录';
  const validity=event.failure?'仅活动记录，不参与证据评估':({valid:'当前有效',stale:'需要重新核验',superseded:'已被替代'})[event.validity]||'尚未评估';
  return `<div class="ts-detail-intro">${testTag(item)}<p>${esc(eventDescription(event))}</p></div><dl class="ts-facts">${field('发生时间',time(event.created_at))}${field('记录来源',source)}${event.capability_id?`<div class="ts-field"><dt>关联能力</dt><dd><button class="ts-text-button" type="button" data-capability="${esc(event.capability_id)}">${esc(capabilityTitle(item))}</button></dd></div>`:''}</dl>${event.event_type==='procedure_delivered'?`<section class="ts-detail-section"><h3>这条记录能说明什么</h3><dl class="ts-facts ts-stages">${field('指引交付','已交付')}${field('Agent 实际采用','尚未记录')}${field('任务结果确认','尚未确认')}</dl></section>`:''}${['procedure_delivered','task_outcome_signal','version_verification'].includes(event.event_type)?`<details class="ts-detail-section"><summary>证据与来源</summary><dl class="ts-facts">${field('记录有效性',validity)}${field('版本关联',event.hash_bound?'已关联相同内容的版本':'关联信息尚未记录或不匹配')}</dl><p class="ts-note">来源和有效性是已有记录，不能替代独立的任务结果确认。</p></details>`:''}${advanced(event)}`;
}
async function readAll(read,path,params,signal) {
  const items=new Map();let expected=null,complete=true;
  for(let offset=0;expected===null||offset<expected;offset+=100){
    signal?.throwIfAborted();const page=await read(path,{...params,limit:100,offset},signal);
    if(expected===null)expected=page.total;else if(page.total!==expected)complete=false;
    for(const item of page.items)items.set(item.capability_id&&path==='/api/capabilities'?item.capability_id:item.event_id,item);
    if(!page.items.length)break;
  }
  return {items:[...items.values()],complete:complete&&items.size===expected};
}
async function readScreen(read,page,offset=0,capability='',signal) {
  const [overview,catalog]=await Promise.all([read('/api/overview',{},signal),readAll(read,'/api/capabilities',{},signal)]);
  const activity=page==='activity'?await read('/api/activity',{limit:30,offset,capability},signal):null;
  return {overview,catalog:catalog.items,catalogComplete:catalog.complete,activity};
}
async function readCapability(read,id,catalog,signal) {
  const [data,checks]=await Promise.all([read('/api/capability',{id},signal),readAll(read,'/api/evidence',{type:'version_verification',capability:id},signal)]);
  const deliveries=await read('/api/evidence',{type:'procedure_delivered',capability:id,limit:1,offset:0},signal);
  return {...data,catalog,verifications:checks.items,verifications_complete:checks.complete,delivery_record_count:deliveries.total};
}
// TOOLSEED_SHARED_VIEWS_END

const main=document.getElementById('main'),dialog=document.getElementById('detail');
const state={page:'capabilities',query:'',offset:0,capability:'',screen:null,busy:false,sequence:0};
let request,detailRequest,detailState=null;
async function api(path,params={},signal) {
  const response=await fetch(path+'?'+new URLSearchParams(params),{cache:'no-store',signal});
  const payload=await response.json();
  if(!response.ok)throw Object.assign(new Error(payload.error?.message||'读取暂不可用'),{payload});
  return payload;
}
function showEvent(id) {
  const event=state.screen?.activity?.items.find(e=>e.event_id===id)||detailState?.data?.evidence?.find(e=>e.event_id===id);
  if(!event)return;
  detailRequest?.abort();detailState={kind:'event',event};
  document.getElementById('detail-title').textContent=eventTitle(event,state.screen?.catalog);
  document.getElementById('detail-body').innerHTML=activityDetail(event,state.screen?.catalog);
  if(!dialog.open)dialog.showModal();
}
async function showCapability(id) {
  detailRequest?.abort();const controller=new AbortController();detailRequest=controller;
  detailState={kind:'capability',id};
  document.getElementById('detail-title').textContent='能力详情';document.getElementById('detail-body').textContent='正在读取…';
  if(!dialog.open)dialog.showModal();
  try{
    const data=await readCapability(api,id,state.screen?.catalog||[],controller.signal);
    if(controller.signal.aborted)return;detailState={kind:'capability',id,data};
    document.getElementById('detail-title').textContent=capabilityTitle({...data.capability,...(data.versions.find(v=>v.version_id===data.capability.current_version_id)||data.versions[0])});
    document.getElementById('detail-body').innerHTML=capabilityDetail(data);
  }catch(error){if(!controller.signal.aborted)document.getElementById('detail-body').textContent=error.message;}
}
function closeDetail(){detailRequest?.abort();detailState=null;dialog.close();}
function render() {
  const s=state.screen;if(!s)return;
  document.getElementById('summary').innerHTML=summary(s.overview,s.catalog);
  const filtered=filterCapabilities(s.catalog,state.query),items=state.page==='capabilities'?filtered.slice(state.offset,state.offset+30):s.activity?.items||[];
  const total=state.page==='capabilities'?filtered.length:s.activity?.total||0;
  document.getElementById('records').innerHTML=state.page==='capabilities'?capabilityCards(items,state.query):activityCards(items,s.catalog);
  document.getElementById('page-range').textContent=total?`${state.offset+1}–${Math.min(state.offset+30,total)} / ${total}`:'没有对应记录';
  document.getElementById('pagination').hidden=total<=30&&state.offset===0;
  document.getElementById('previous').disabled=state.offset===0;document.getElementById('next').disabled=state.offset+30>=total;
  const focus=s.catalog.find(item=>item.capability_id===state.capability);
  document.getElementById('activity-focus').textContent=state.capability?`正在查看${focus?'“'+capabilityTitle(focus)+'”':'相关能力'}的活动`:'';
  document.getElementById('clear-focus').hidden=!state.capability;
  document.getElementById('catalog-note').hidden=s.catalogComplete;
}
async function load() {
  request?.abort();const controller=new AbortController();request=controller;state.busy=true;
  main.setAttribute('aria-busy','true');document.getElementById('sync-status').textContent='正在更新…';
  try{const data=await readScreen(api,state.page,state.page==='activity'?state.offset:0,state.capability,controller.signal);
    if(controller.signal.aborted)return;state.screen=data;document.getElementById('read-error').hidden=true;render();document.getElementById('sync-status').textContent='已更新';
  }catch(error){if(controller.signal.aborted)return;const box=document.getElementById('read-error');box.hidden=false;box.textContent=error.message;document.getElementById('sync-status').textContent='读取暂不可用';}
  finally{if(!controller.signal.aborted){state.busy=false;main.setAttribute('aria-busy','false');}}
}
function navigate() {
  state.page=location.hash==='#activity'?'activity':'capabilities';state.query='';state.offset=0;
  document.querySelectorAll('nav a').forEach(a=>{a.classList.toggle('active',a.dataset.page===state.page);if(a.dataset.page===state.page)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  document.getElementById('search-box').hidden=state.page!=='capabilities';document.getElementById('search').value='';
  document.getElementById('page-title').textContent=state.page==='capabilities'?'已入库能力':'活动';load();
}
document.addEventListener('click',event=>{
  const capability=event.target.closest('[data-capability]');if(capability)showCapability(capability.dataset.capability);
  const record=event.target.closest('[data-event]');if(record)showEvent(record.dataset.event);
  const history=event.target.closest('[data-history]');if(history){state.capability=history.dataset.history;closeDetail();if(location.hash!=='#activity')location.hash='activity';else navigate();}
});
document.getElementById('search').addEventListener('input',event=>{state.query=event.target.value;state.offset=0;render();});
document.getElementById('previous').addEventListener('click',()=>{state.offset=Math.max(0,state.offset-30);state.page==='activity'?load():render();});
document.getElementById('next').addEventListener('click',()=>{state.offset+=30;state.page==='activity'?load():render();});
document.getElementById('refresh').addEventListener('click',()=>{load();if(detailState?.kind==='capability')showCapability(detailState.id);});
document.getElementById('close-detail').addEventListener('click',closeDetail);
dialog.addEventListener('cancel',()=>{detailRequest?.abort();detailState=null;});
document.getElementById('clear-focus').addEventListener('click',()=>{state.capability='';state.offset=0;load();});
window.addEventListener('hashchange',navigate);
setInterval(()=>{if(!document.hidden&&!state.busy&&!dialog.open&&!main.querySelector('details[open]')&&document.activeElement?.tagName!=='INPUT')load();},5000);
navigate();
