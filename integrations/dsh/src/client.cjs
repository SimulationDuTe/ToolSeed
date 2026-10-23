const React = require('react');
const {Button,Input,SegmentedTabs,Modal} = require('@deepseek-ai/dsh-client-ui-primitives');
const h=React.createElement;
const pages=['capabilities','activity'],titles=['已入库能力','活动'],pageSize=30;
// Both entry points use the same HTML escapers and card/detail presentation.
function Content({html,onCapability,onEvent,onHistory,className=''}) {
  return h('div',{className,onClick:event=>{
    const target=event.target.closest('[data-capability],[data-event],[data-history]');
    if(!target||!event.currentTarget.contains(target))return;
    if(target.dataset.capability)onCapability?.(target.dataset.capability);
    else if(target.dataset.event)onEvent?.(target.dataset.event);
    else if(target.dataset.history)onHistory?.(target.dataset.history);
  },dangerouslySetInnerHTML:{__html:html}});
}
function Panel({connection}) {
  const root=React.useRef(null),detailRequest=React.useRef(null);
  const [view,setView]=React.useState({page:'capabilities',query:'',offset:0,capability:''});
  const [revision,refresh]=React.useState(0);
  const [result,setResult]=React.useState({screen:null,error:null,busy:true});
  const [detail,setDetail]=React.useState(null);
  const read=React.useCallback(async(route,params,signal)=>{
    const response=await connection.rpc.call('/api','toolseed.read',{route,params},signal);
    const payload=response.ok?response.value:{error:{message:'宿主暂时无法完成读取，请稍后刷新。'}};
    if(payload.error)throw Object.assign(new Error(payload.error.message),{payload});
    return payload;
  },[connection]);
  const activityOffset=view.page==='activity'?view.offset:0;
  React.useEffect(()=>{
    const request=new AbortController();setResult(previous=>({...previous,busy:true,error:null}));
    (async()=>{
      try{const screen=await views.readScreen(read,view.page,activityOffset,view.capability,request.signal);
        if(!request.signal.aborted)setResult({screen:{...screen,page:view.page},error:null,busy:false});
      }catch(error){if(!request.signal.aborted)setResult(previous=>({...previous,error,busy:false}));}
    })();
    return()=>request.abort();
  },[read,view.page,activityOffset,view.capability,revision]);
  React.useEffect(()=>{
    const timer=setInterval(()=>{
      if(!document.hidden&&!result.busy&&!detail&&root.current?.getClientRects().length
        &&!root.current.querySelector('details[open]')&&document.activeElement?.tagName!=='INPUT')refresh(n=>n+1);
    },5000);
    return()=>clearInterval(timer);
  },[result.busy,detail]);
  React.useEffect(()=>()=>detailRequest.current?.abort(),[]);
  const screen=result.screen,catalog=screen?.catalog||[];
  const openCapability=async id=>{
    detailRequest.current?.abort();const request=new AbortController();detailRequest.current=request;
    setDetail({kind:'capability',id,data:null,error:null});
    try{const data=await views.readCapability(read,id,catalog,request.signal);
      if(!request.signal.aborted)setDetail({kind:'capability',id,data,error:null});
    }catch(error){if(!request.signal.aborted)setDetail({kind:'capability',id,data:null,error});}
  };
  const openEvent=id=>{
    const event=screen?.activity?.items.find(e=>e.event_id===id)||detail?.data?.evidence?.find(e=>e.event_id===id);
    if(event){detailRequest.current?.abort();setDetail({kind:'event',event});}
  };
  const closeDetail=()=>{detailRequest.current?.abort();setDetail(null);};
  const navigate=page=>setView({page,query:'',offset:0,capability:''});
  const openHistory=id=>{closeDetail();setView({page:'activity',query:'',offset:0,capability:id});};
  const filtered=views.filterCapabilities(catalog,view.query),ready=screen?.page===view.page;
  const items=view.page==='capabilities'?filtered.slice(view.offset,view.offset+pageSize):screen?.activity?.items||[];
  const total=view.page==='capabilities'?filtered.length:screen?.activity?.total;
  const html=ready?(view.page==='capabilities'?views.capabilityCards(items,view.query):views.activityCards(items,catalog)):'';
  const focus=catalog.find(item=>item.capability_id===view.capability);
  let detailTitle='能力详情',detailHtml='';
  if(detail?.kind==='event'){detailTitle=views.eventTitle(detail.event,catalog);detailHtml=views.activityDetail(detail.event,catalog);}
  else if(detail?.data){const data=detail.data;detailTitle=views.capabilityTitle({...data.capability,...(data.versions.find(v=>v.version_id===data.capability.current_version_id)||data.versions[0])});detailHtml=views.capabilityDetail(data);}
  return h('section',{ref:root,className:'toolseed-native ts-panel','aria-label':'ToolSeed 只读管理'},
    h('header',{className:'toolseed-native-header'},h('h2',null,'ToolSeed'),
      h(Button,{variant:'outline',size:'sm',onClick:()=>{refresh(n=>n+1);if(detail?.kind==='capability')openCapability(detail.id);}},'刷新')),
    h(SegmentedTabs,{label:'ToolSeed 页面',value:view.page,onChange:navigate,
      items:pages.map((value,index)=>({value,label:titles[index],id:`toolseed-tab-${value}`,panelId:'toolseed-page'}))}),
    h(Content,{html:views.summary(screen?.overview,catalog)}),
    h('div',{className:'toolseed-native-toolbar'},
      view.page==='capabilities'?h(Input,{type:'search','aria-label':'搜索能力',placeholder:'搜索名称、说明或适用场景',
        value:view.query,onChange:event=>setView(previous=>({...previous,query:event.target.value,offset:0}))}):
        h('span',{className:'ts-muted'},view.capability?`正在查看${focus?'“'+views.capabilityTitle(focus)+'”':'相关能力'}的活动`:'最近发生的事情'),
      view.capability?h(Button,{variant:'outline',size:'sm',onClick:()=>setView(previous=>({...previous,capability:'',offset:0}))},'查看全部活动'):null,
      h('span',{role:'status',className:'ts-muted'},result.busy||!ready?'正在更新…':result.error?'读取暂不可用':'')),
    screen&&!screen.catalogComplete?h('p',{className:'ts-note'},'能力库正在更新，部分结果可能稍后显示。'):null,
    h('div',{id:'toolseed-page',role:'tabpanel','aria-labelledby':`toolseed-tab-${view.page}`,'aria-busy':result.busy||!ready},
      result.error?h('p',{role:'alert'},result.error.message):null,
      h(Content,{html,onCapability:openCapability,onEvent:openEvent,onHistory:openHistory}),
      ready&&(total>pageSize||view.offset>0)?h('div',{className:'toolseed-native-pagination'},
        h('span',{className:'ts-muted'},total?`${view.offset+1}–${Math.min(view.offset+pageSize,total)} / ${total}`:'没有对应记录'),
        h(Button,{variant:'outline',size:'sm',disabled:view.offset===0,onClick:()=>setView(previous=>({...previous,offset:Math.max(0,previous.offset-pageSize)}))},'上一页'),
        h(Button,{variant:'outline',size:'sm',disabled:view.offset+pageSize>=total,onClick:()=>setView(previous=>({...previous,offset:previous.offset+pageSize}))},'下一页')):null),
    h(Modal,{open:detail!==null,onClose:closeDetail,title:detailTitle,closeLabel:'关闭详情',className:'toolseed-native-detail',
      footer:h(Button,{variant:'outline',size:'sm',onClick:closeDetail},'关闭')},
      detail?.error?h('p',{role:'alert'},detail.error.message):detailHtml?
        h(Content,{className:'ts-panel',html:detailHtml,onCapability:openCapability,onEvent:openEvent,onHistory:openHistory}):h('p',null,'正在读取…')));
}
module.exports={name:'toolseed-panel',inject:['slots','connection'],apply(ctx){
  ctx.effect(()=>{const style=document.createElement('style');style.dataset.plugin='dsh-toolseed';style.dataset.pluginCss='dsh-toolseed/native.css';style.textContent=nativeStyles;document.head.appendChild(style);return()=>style.remove();});
  ctx.slots.inject('settings.section',()=>ctx.slots.register({name:'settings.section',id:'toolseed',order:510,label:'ToolSeed',inject:()=>({connection:ctx.connection})},Panel));
}};
