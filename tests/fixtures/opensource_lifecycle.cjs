// Deterministic synthetic DOM, fetches and clock; no browser or networking.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const web=path.resolve(__dirname,'../../template/web/current');
class Element {
  constructor(tag='div'){
    this.tagName=tag.toUpperCase();this.children=[];this.parentNode=null;this.attrs={};this.dataset={};this.events=new Map();this.value='';this.scrollTop=0;this._html='';this._text='';
    this.classList={remove:()=>{},toggle:()=>{}};
  }
  attr(k,v){this.attrs[k]=v;if(k==='id')this.id=v;if(k==='class')this.className=v;if(k==='value')this.value=v;if(k.startsWith('data-'))this.dataset[k.slice(5)]=v;}
  append(...children){for(const c of children){c.parentNode=this;this.children.push(c);}}
  replaceChildren(...children){for(const c of this.children)c.parentNode=null;this.children=[];this._html='';this._text='';this.append(...children);}
  contains(node){return node===this||this.children.some(c=>c.contains(node));}
  set innerHTML(html){
    this.replaceChildren();this._html=html;const stack=[this];
    for(const token of html.match(/<[^>]*>|[^<]+/g)||[]){
      if(token.startsWith('</')){if(stack.length>1)stack.pop();continue;}
      if(!token.startsWith('<')){const n=new Element('#text');n._text=token;stack.at(-1).append(n);continue;}
      if(token.startsWith('<!'))continue;
      const tag=token.match(/^<([\w-]+)/)?.[1];if(!tag)continue;const n=new Element(tag);
      for(const a of token.matchAll(/([\w-]+)="([^"]*)"/g))n.attr(a[1],a[2]);
      stack.at(-1).append(n);if(!['input','br','img','link','meta','hr'].includes(tag))stack.push(n);
    }
  }
  get innerHTML(){return this._html;}
  set textContent(v){this.replaceChildren();this._text=String(v);}
  get textContent(){return this._text+this.children.map(c=>c.textContent).join('');}
  matches(selector){
    if(selector.startsWith('#'))return this.id===selector.slice(1);
    if(selector.startsWith('.'))return (this.className||'').split(' ').includes(selector.slice(1));
    if(selector.startsWith('[')){const a=selector.match(/^\[([^=\]]+)(?:="([^"]*)")?\]$/);return a&&(a[2]===undefined?this.attrs[a[1]]!==undefined:this.attrs[a[1]]===a[2]);}
    return this.tagName.toLowerCase()===selector.replace('[id]','')&&(!selector.includes('[id]')||this.id);
  }
  querySelectorAll(selector){const found=[];const visit=n=>{for(const c of n.children){if(selector.split(',').some(s=>c.matches(s)))found.push(c);visit(c);}};visit(this);return found;}
  querySelector(s){return this.querySelectorAll(s)[0]||null;}
  closest(s){return this.matches(s)?this:this.parentNode?.closest(s);}
  addEventListener(type,fn){if(!this.events.has(type))this.events.set(type,new Set());this.events.get(type).add(fn);}
  dispatch(type,extra={}){const event={target:this,preventDefault(){this.prevented=true;},...extra};let n=this;while(n){for(const fn of n.events.get(type)||[])fn(event);n=n.parentNode;}return event;}
  focus(){Element.focused=this;}
  setSelectionRange(start,end){this.selectionStart=start;this.selectionEnd=end;}
}
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
function setup(search='?tab=opensource'){
  const doc=new Element('document'),body=new Element('body');doc.append(body);doc.body=body;body.dataset={};
  body.innerHTML='<nav id="sidebar"></nav><main id="main"></main><button id="mNavBtn"></button><div id="mNavBackdrop"></div>';
  Object.defineProperty(doc,'activeElement',{get:()=>Element.focused});
  doc.getElementById=id=>doc.querySelector('#'+id);doc.createElement=t=>new Element(t);
  const timers=new Map(),requests=[],now=Date.parse('2026-11-14T00:00:00Z');let serial=0;
  class Clock extends Date {static now(){return h.now;}}
  const ctx={document:doc,URLSearchParams,AbortController,Date:Clock,console,
    location:{search,origin:'http://local.test',assign:()=>assert.fail('unexpected redirect')},
    history:{replaceState:(_,__,url)=>ctx.location.search=url},localStorage:{getItem:()=>null,setItem:()=>{}},
    setTimeout:(fn,ms)=>{timers.set(++serial,{fn,ms});return serial;},clearTimeout:id=>timers.delete(id),
    addEventListener:()=>{},scrollY:0,scrollTo:(_,y)=>ctx.scrollY=y,
    snsCaptureView:()=>null,snsRestoreView:()=>{},SNS_OPS:{},
    screenSnsOperations:()=>'<p>SNS</p>',screenSnsAccounts:()=>'',screenVaultAllLive:()=>'',
    fetch:(url,options={})=>{
      if(url==='/api/session')return Promise.resolve({ok:true,json:async()=>({authenticated:true})});
      assert.match(url,/^\/api\/opensource\/(catalog|repos\/[a-f0-9]{32})$/);
      assert.equal(options.method,undefined,'only read requests');
      return new Promise((resolve,reject)=>requests.push({url,options,resolve,reject}));
    }};
  ctx.window=ctx;vm.createContext(ctx);const run=s=>vm.runInContext(s,ctx),load=f=>run(fs.readFileSync(path.join(web,f),'utf8'));
  const h={now,ctx,doc,host:doc.getElementById('main'),requests,timers,run,load,
    get:id=>doc.getElementById(id),root:()=>doc.querySelector('.ilson-opensource'),
    fire(ms){for(const [id,t] of [...timers])if(t.ms===ms){timers.delete(id);t.fn();}},
    click(selector){const b=doc.querySelector(selector);assert.ok(b,selector);b.dispatch('click');},
    input(id,value){const n=doc.getElementById(id);n.value=value;n.dispatch('input');}};
  load('opensource.js');return h;
}
const row=(id='a'.repeat(32),number=1)=>({id,full_name:'synthetic/fake-'+number,category:'make',curated_order:number,one_liner:'가짜 문서 도구',use_cases:['가상 문서'],difficulty:2,box_burden:'browse',preparation:'가상 준비물',cost:'필수 유료 API 없음',license:{spdx:'MIT',url:'https://github.com/synthetic/fake/LICENSE',conditions:'가상 조건'},gitbap_url:'https://www.gitbap.com/r/synthetic/fake-'+number,reviewed_at:'2026-11-14T00:00:00Z',runnable:false});
const listing=(repos=[row()])=>({state:repos.length?'ready':'empty',repos,generated_at:'2026-11-14T00:00:00Z',valid_until:'2026-11-17T00:00:00Z',visible_until:'2026-11-17T00:00:00Z'});
function detailed(r=row()) {return {...listing(),repo:{...r,mild_md:'가상 순한맛 설명',prerequisites:['가상 준비'],limitations:['가상 한계'],data_processing:'자료 업로드 없음',official_url:'https://github.com/synthetic/fake',source:{summary_created_at:'2026-11-12T00:00:00Z',synced_at:'2026-11-13T00:00:00Z',status_checked_at:'2026-11-14T00:00:00Z'},review:{reviewed_at:'2026-11-14T00:00:00Z',valid_until:'2026-11-17T00:00:00Z',metadata_checked_at:'2026-11-14T00:00:00Z',past_safety_pass:true,past_alive_pass:true,past_evaluated_at:'2026-10-01T00:00:00Z'},preview:{input:'가상 입력',result:'검토된 결과',placement:'가상 업무',source:'합성 기록'},video:{gitbap_url:r.gitbap_url,made_at:'2026-11-13T00:00:00Z',duration_s:35,valid_until:'2026-11-15T00:00:00Z'}}};}
async function respond(req,data,status=200){req.resolve({ok:status===200,status,json:async()=>data});await flush();}
async function component(){
  const h=setup();assert.equal(h.requests.length,0,'loading asset starts nothing');
  h.ctx.IlsonOpensource.mount(h.host);h.ctx.IlsonOpensource.mount(h.host);
  assert.equal(h.requests.length,1);assert.match(h.root().textContent,/불러오고/);
  await respond(h.requests[0],listing([row(),{...row('e'.repeat(32),2),box_burden:'expert'}]));
  assert.equal(h.doc.querySelectorAll('[role="tab"]').length,6);
  assert.match(h.root().textContent,/2개 도구/);
  h.input('os-search','fake-1');assert.match(h.get('os-results').textContent,/1개 도구/);
  h.click('[data-category="make"]');
  h.input('os-filter','browse');assert.match(h.get('os-results').textContent,/1개 도구/);
  h.host.scrollTop=412;h.ctx.scrollY=34;h.click('[data-repo="'+'a'.repeat(32)+'"]');
  assert.equal(h.requests.length,2);assert.equal(h.host.scrollTop,0);
  const d=detailed();d.repo.mild_md='<img src=x onerror=alert(1)>한국어';
  await respond(h.requests[1],d);
  const content=h.root().textContent;
  assert.match(content,/설명용 예시이며 이 Box에서 실행한 결과가 아닙니다/);
  let last=-1;for(const heading of ['1. 해결하려는 일','2. 깃밥 순한맛 설명','3. 맞는 상황','4. 기존 영상','5. 라이선스','6. 가능한 다음 단계']){const index=content.indexOf(heading);assert.ok(index>last);last=index;}
  assert.equal(h.doc.querySelectorAll('img').length,0,'source text escaped');
  assert.equal(h.doc.querySelectorAll('iframe').length,0);assert.equal(h.doc.querySelectorAll('video').length,0);
  assert.match(content,/2026\D+11\D+12/);assert.match(content,/2026\D+11\D+13/);assert.match(content,/2026\D+11\D+14/);assert.match(content,/KST/);
  h.click('[data-action="back"]');await respond(h.requests[2],listing());
  assert.equal(h.get('os-search').value,'fake-1');assert.equal(h.get('os-filter').querySelector('[value="browse"]').attrs.value,'browse');
  assert.equal(h.get('os-tab-make').attrs['aria-selected'],'true');
  assert.equal(h.host.scrollTop,412);assert.equal(h.ctx.scrollY,34);assert.equal(Element.focused.dataset.repo,'a'.repeat(32));
  const event=h.get('os-tab-make').dispatch('keydown',{key:'ArrowRight'});assert.equal(event.prevented,true);
  assert.equal(h.get('os-tab-run').attrs['aria-selected'],'true');
  h.get('os-tab-run').dispatch('keydown',{key:'Home'});assert.equal(h.get('os-tab-all').attrs['aria-selected'],'true');
  h.get('os-tab-all').dispatch('keydown',{key:'End'});assert.equal(h.get('os-tab-run').attrs['aria-selected'],'true');
  h.get('os-tab-run').dispatch('keydown',{key:'Home'});
  h.get('os-search').focus();h.get('os-search').setSelectionRange(2,4);h.host.scrollTop=224;
  h.fire(30000);await respond(h.requests[3],listing());
  assert.equal(Element.focused,h.get('os-search'),'background refresh retains typing focus');
  assert.equal(h.get('os-search').selectionStart,2);assert.equal(h.get('os-search').selectionEnd,4);assert.equal(h.host.scrollTop,224);
  h.ctx.IlsonOpensource.leave();assert.equal(h.timers.size,0);
  // Aborted responses deliberately ignore their signal and must not replace newer views.
  h.ctx.IlsonOpensource.mount(h.host);const stale=h.requests[4];h.ctx.IlsonOpensource.leave();
  assert.equal(stale.options.signal.aborted,true);assert.equal(h.timers.size,0,'leave also clears request deadline');h.ctx.IlsonOpensource.mount(h.host);
  await respond(stale,listing([{...row(),full_name:'STALE_RESPONSE'}]));assert.doesNotMatch(h.root().textContent,/STALE_RESPONSE/);
  await respond(h.requests[5],listing());
  h.ctx.IlsonOpensource.leave();assert.equal(h.timers.size,0);
}
async function failures(){
  for(const [state,label] of [['empty','소개할 도구를 검토하고 있어요'],['under_review','공개 검토 중'],['expired','자료가 만료'],['verification_failed','자료 검증에 실패'],['load_failed','불러오지 못했어요']]){
    const h=setup();h.ctx.IlsonOpensource.mount(h.host);await respond(h.requests[0],{state,repos:[]});assert.match(h.root().textContent,new RegExp(label));h.ctx.IlsonOpensource.leave();
  }
  for(const [code,label] of [[401,'접속이 만료'],[403,'권한'],[404,'공개 가능한 자료']]){
    const h=setup();h.ctx.IlsonOpensource.mount(h.host);await respond(h.requests[0],{error:'FAKE_SECRET_ERROR'},code);
    assert.match(h.root().textContent,new RegExp(label));assert.doesNotMatch(h.root().textContent,/FAKE_SECRET_ERROR/);h.ctx.IlsonOpensource.leave();
  }
  const h=setup();h.ctx.IlsonOpensource.mount(h.host);await respond(h.requests[0],listing());
  h.fire(30000);h.requests[1].reject(Error('FAKE_SECRET_NETWORK'));await flush();
  assert.match(h.root().textContent,/불러오지 못했어요/);assert.equal(h.doc.querySelectorAll('a').length,0,'failure removes stale links');assert.doesNotMatch(h.root().textContent,/FAKE_SECRET/);
  h.click('[data-action="retry"]');await respond(h.requests[2],listing());
  h.click('[data-repo="'+'a'.repeat(32)+'"]');const d=detailed();d.repo.preview=null;d.repo.video=null;await respond(h.requests[3],d);
  assert.match(h.root().textContent,/승인된 샘플 결과가 없어/);assert.match(h.root().textContent,/영상이 확인되지 않았습니다/);
  h.ctx.IlsonOpensource.leave();
}
async function expiry(){
  const h=setup();h.ctx.IlsonOpensource.mount(h.host);const data=listing();data.visible_until='2026-11-14T00:01:00Z';await respond(h.requests[0],data);
  h.fire(30000);assert.equal(h.requests.length,2);
  assert.ok([...h.timers.values()].some(t=>t.ms===60000),'deadline remains armed during stalled refresh');
  h.now+=60000;h.fire(60000);assert.match(h.root().textContent,/資料|자료가 만료/);assert.equal(h.doc.querySelectorAll('a').length,0);
  assert.equal(h.requests[1].options.signal.aborted,true,'expiry aborts pending refresh');
  await respond(h.requests[1],listing());assert.equal(h.doc.querySelectorAll('a').length,0,'late stale body cannot reopen expired links');
  assert.equal(h.timers.size,0);
  h.ctx.IlsonOpensource.leave();
}
async function shell(){
  const h=setup();h.ctx.IlsonDashboard={leave(){}};h.load('pack-library/pack-navigation.js');h.load('shell.js');await flush();
  assert.equal(h.requests.length,1);assert.equal(h.ctx.location.search,'?tab=opensource');
  assert.match(h.get('sidebar').innerHTML,/플랫폼/);assert.match(h.get('sidebar').innerHTML,/A.go\('opensource'\)/);
  h.run('render();render()');assert.equal(h.requests.length,1,'unrelated shell renders retain component');
  await respond(h.requests[0],listing());h.run("A.go('sns')");assert.equal(h.timers.size,0);
  h.run("A.go('opensource')");assert.equal(h.requests.length,2);h.ctx.IlsonOpensource.leave();
}
async function referenceCatalog(){
  const data=JSON.parse(fs.readFileSync(path.join(web,'opensource-catalog.json'),'utf8'));
  const rows=data.repos.map(r=>({...r,reviewed_at:r.review.reviewed_at,metadata_verdict:r.review.metadata_verdict,metadata_warning:r.review.metadata_warning}));
  const h=setup();h.now=Date.parse(data.generated_at);h.ctx.IlsonOpensource.mount(h.host);
  const response={...data,state:'ready',repos:rows,visible_until:data.valid_until};
  await respond(h.requests[0],response);
  assert.match(h.root().textContent,/22개 도구/);
  assert.match(h.root().textContent,/깃밥 점검 전 · 소개만/);
  assert.match(h.root().textContent,/주의:.*라이선스/);
  assert.ok(h.doc.querySelectorAll('a').every(a=>a.attrs.href!=='null'&&a.attrs.href!=='undefined'));
  for(const [category,count] of [['build',7],['design',6],['grow',3],['make',3],['run',3]]){
    h.click(`[data-category="${category}"]`);assert.match(h.get('os-results').textContent,new RegExp(count+'개 도구'));
  }
  h.click('[data-category="all"]');
  const unc=rows.find(r=>r.metadata_verdict==='not_curated');
  h.click(`[data-repo="${unc.id}"]`);
  await respond(h.requests[1],{...response,repo:unc});
  assert.match(h.root().textContent,/공식 문서로 정리한 소개/);
  assert.match(h.root().textContent,/not_curated/);
  assert.doesNotMatch(h.root().textContent,/깃밥 원문 설명/);
  assert.ok(h.doc.querySelectorAll('a').every(a=>!a.attrs.href.includes('gitbap.com')));
  // 30 days exceeds the browser's signed 32-bit timeout range. Re-arm at
  // that limit, rather than expiring immediately through timer overflow.
  assert.ok([...h.timers.values()].some(t=>t.ms===2147483647));
  h.now+=2147483647;h.fire(2147483647);
  assert.doesNotMatch(h.root().textContent,/자료가 만료/);
  const remaining=Date.parse(data.valid_until)-h.now;
  assert.ok(remaining>0&&remaining<2147483647);
  assert.ok([...h.timers.values()].some(t=>t.ms===remaining));
  h.now+=remaining;h.fire(remaining);
  assert.match(h.root().textContent,/자료가 만료/);assert.equal(h.doc.querySelectorAll('a').length,0);
  h.ctx.IlsonOpensource.leave();
  const empty=setup();empty.ctx.IlsonOpensource.mount(empty.host);await respond(empty.requests[0],listing());
  empty.click('[data-category="grow"]');
  assert.match(empty.get('os-results').textContent,/0개 도구/);
  assert.match(empty.get('os-results').textContent,/소개할 도구를 검토하고 있어요/);
  empty.ctx.IlsonOpensource.leave();
}
(async()=>{await component();await failures();await expiry();await shell();await referenceCatalog();console.log('opensource component + shell lifecycle PASS');})().catch(e=>{console.error(e);process.exitCode=1;});
