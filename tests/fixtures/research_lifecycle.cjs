// Run the real research scripts across independent iframe-like VM instances.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const {webcrypto} = require('node:crypto');
const web = path.resolve(__dirname, '../../template/web/current/pack-library');
const job = 'a'.repeat(32), secondJob = 'b'.repeat(32);
const result = question => ({version:1, question, checked_at:'2026-10-27T00:00:00Z', sources:[{id:1,title:'Source',url:'https://example.org/fact',read_status:'read'}], claims:[{kind:'fact',text:'Verified content',source_ids:[1]}], limitations:'Test fixture'});
class Element {
 constructor(tag='div'){this.tagName=tag;this.children=[];this.parentNode=null;this.attrs={};this.dataset={};this.events=new Map();this.value='';this._text='';this.hidden=false;this.disabled=false;this.classes=new Set();this.classList={add:(...xs)=>xs.forEach(x=>this.classes.add(x)),remove:(...xs)=>xs.forEach(x=>this.classes.delete(x)),contains:x=>this.classes.has(x),toggle:x=>{if(this.classes.has(x))this.classes.delete(x);else this.classes.add(x);}};}
 append(...nodes){for(let node of nodes){if(typeof node==='string'){const t=new Element('#text');t.textContent=node;node=t;}node.remove();node.parentNode=this;this.children.push(node);}}
 remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(n=>n!==this);this.parentNode=null;}
 after(node){if(!this.parentNode)return;node.remove();const parent=this.parentNode;node.parentNode=parent;parent.children.splice(parent.children.indexOf(this)+1,0,node);}
 replaceChildren(...nodes){for(const n of this.children)n.parentNode=null;this.children=[];this._text='';this.append(...nodes);}
 set textContent(value){this.replaceChildren();this._text=String(value);}
 get textContent(){return this._text+this.children.map(n=>n.textContent).join('');}
 setAttribute(k,v){this.attrs[k]=String(v);}
 addEventListener(type,fn){if(!this.events.has(type))this.events.set(type,[]);this.events.get(type).push(fn);}
 dispatch(type,extra={}){for(const fn of this.events.get(type)||[])fn({target:this,preventDefault(){},...extra});}
 click(){this.dispatch('click');}
 requestSubmit(){this.dispatch('submit');}
 querySelector(selector){if(selector==='button[type=submit]')return this.button;if(selector==='option[value=all]')return this.option;return null;}
 querySelectorAll(){return [];}
 scrollIntoView(){} focus(){} getClientRects(){return [1];}
}
function storageFor(map){return {get length(){return map.size;},key:i=>[...map.keys()][i]??null,getItem:k=>map.get(k)??null,setItem:(k,v)=>map.set(k,String(v)),removeItem:k=>map.delete(k)};}
function locks(){let tail=Promise.resolve();return {request:(_name,fn)=>{const next=tail.then(fn);tail=next.catch(()=>{});return next;}};}
function setup(store=new Map(),config={}){
 const nodes=new Map(),body=new Element('body'),events=new Element(),timers=new Map();let serial=0;
 const html=fs.readFileSync(path.join(web,'research.html'),'utf8');
 for(const [,id] of html.matchAll(/id="([^"]+)"/g)){const node=new Element();node.id=id;nodes.set(id,node);body.append(node);}
 const get=id=>nodes.get(id),form=get('researchForm');form.button=new Element('button');form.append(form.button);
 get('period').value='all';get('period').selectedOptions=[new Element('option')];get('period').option=new Element('option');get('researchMode').value='quick';
 const heading=new Element();body.append(heading);
 const document={body,documentElement:new Element('html'),getElementById:get,querySelector:s=>s==='.research-heading'?heading:null,querySelectorAll:()=>[],createElement:t=>new Element(t),createTextNode:t=>{const n=new Element('#text');n.textContent=t;return n;}};
 const calls=[],state={stage:'reading',...config},storage=storageFor(store);
 const image={busy:false,attachment:null,isLoading:()=>false,isBlocked:()=>false,get(){return this.attachment;},setBusy(v){this.busy=v;},setReady(){},clear(){this.attachment=null;}};
 const response=(data,status=200)=>({ok:status>=200&&status<300,status,json:async()=>data,headers:{get:()=>''}});
 const ctx={document,localStorage:storage,crypto:webcrypto,navigator:{locks:config.locks||locks(),clipboard:{writeText:async()=>{}}},console,URL,URLSearchParams,AbortController,AbortSignal,TextDecoder,Uint8Array,Date,ResearchImage:image,
  requestAnimationFrame:fn=>fn(),setTimeout:(fn,ms)=>{timers.set(++serial,{fn,ms});return serial;},clearTimeout:id=>timers.delete(id),
  addEventListener:(...args)=>events.addEventListener(...args),
  fetch:async(url,options={})=>{
   calls.push({url,options});
   if(url==='/api/research-capabilities'){
    if(state.capError)throw Error('offline');
    return response(state.capabilities||{mode:'internal',async:true,stream:false,provider:'auto'},state.capStatus||200);
   }
   if(url==='/api/research/jobs'&&options.method==='POST'){
    if(state.submitDeferred)return state.submitDeferred;
    if(state.submitLost)throw Error('lost response');
    return response({id:state.job||job});
   }
   if(url==='/api/research')return response(result('Synchronous'));
   if(url.endsWith('/events')){
    if(state.sseResponse)return state.sseResponse();
    throw Error('stream dropped');
   }
   if(url.startsWith('/api/research/jobs/')){
    assert.ok(storage.getItem('ilson-research-pending-v1')||state.allowRemoved,'persist before tracking');
    if(state.getDeferred)return state.getDeferred;
    if(state.offline)throw Error('offline');
    return response({id:job,stage:state.stage,error:state.error,result:state.stage==='done'?result(state.question||'Original follow-up'):null},state.status||200);
   }
   throw Error('unexpected fetch '+url);
  }};
 ctx.window=ctx;vm.createContext(ctx);const run=src=>vm.runInContext(src,ctx);
 for(const name of ['research-threads.js','research.js'])run(fs.readFileSync(path.join(web,name),'utf8'));
 return {ctx,run,get,events,timers,calls,state,store,storage,image,postCount:()=>calls.filter(c=>c.options.method==='POST').length,
  async flush(){for(let i=0;i<25;i++)await Promise.resolve();},
  async tick(){const entry=[...timers].find(([,t])=>t.ms===500);assert.ok(entry,'poll timer expected');timers.delete(entry[0]);entry[1].fn();await this.flush();},
  leave(){events.dispatch('pagehide');},
  submit(question='Original follow-up'){get('question').value=question;form.requestSubmit();}};
}
function pending(store,overrides={}){store.set('ilson-research-pending-v1',JSON.stringify({version:1,ref:'ref-1',id:job,thread:'original-room',question:'Original follow-up',period:'month',mode:'deep',videos:true,started:Date.now()-150000,...overrides}));}
function saved(store){return [...store].filter(([key])=>key.startsWith('ilson-research-result-v1:')).map(([,value])=>JSON.parse(value));}
async function test(name,fn){await fn();console.log('PASS '+name);}
(async()=>{
 await test('navigate while running, revisit while running, reload after server completes',async()=>{
  const store=new Map(),first=setup(store);await first.flush();
  first.run('currentThread="original-room"');first.ctx.ResearchThreads.append('original-room',result('Earlier question'));
  first.get('period').value='month';first.get('researchMode').value='deep';first.get('includeVideos').checked=true;
  first.image.attachment={data:'PRIVATE-IMAGE-BYTES',token:'PRIVATE-ATTACHMENT-TOKEN'};
  first.submit();await first.flush();assert.equal(first.postCount(),1);
  const ref=JSON.parse(store.get('ilson-research-pending-v1'));
  assert.equal(ref.id,job);assert.equal(ref.thread,'original-room');assert.equal(ref.mode,'deep');assert.equal(ref.period,'month');
  assert.equal(JSON.parse(first.calls.find(c=>c.options.method==='POST').options.body).options.context[0],'Earlier question');
  assert.ok(!JSON.stringify([...store]).includes('PRIVATE-'));first.leave();await first.flush();assert.equal(first.timers.size,0);
  const revisit=setup(store);await revisit.flush();assert.equal(revisit.postCount(),0);assert.equal(revisit.get('answerQuestion').textContent,'Original follow-up');assert.equal(revisit.get('earlierAnswers').children.length,1);assert.equal(revisit.get('researchMode').value,'deep');assert.match(revisit.get('researchStatus').textContent,/메뉴를 이동해도/);
  revisit.leave();await revisit.flush();
  const after=setup(store,{stage:'done'});await after.flush();assert.equal(after.postCount(),0);assert.equal(saved(store).length,1);assert.equal(saved(store)[0].thread,'original-room');assert.equal(after.ctx.ResearchThreads.read().length,2);assert.equal(store.has('ilson-research-pending-v1'),false);assert.match(after.get('claims').textContent,/Verified content/);
  after.leave();const again=setup(store,{stage:'done'});await again.flush();assert.equal(again.postCount(),0);assert.equal(saved(store).length,1);assert.match(again.get('claims').textContent,/Verified content/);
 });
 await test('native stages and elapsed time truthfully describe continued work',async()=>{
  const labels={running:'조사 준비 · 진행 중',searching:'웹 자료 검색',reading:'원문 읽기',retrying:'보조 자료 확인 · 재시도 중'};
  for(const [stage,label] of Object.entries(labels)){
   const store=new Map();pending(store);const view=setup(store,{stage});await view.flush();assert.equal(view.get('researchProgressText').textContent,label);assert.match(view.get('researchStatus').textContent,/메뉴를 이동해도/);const elapsed=Number(view.get('researchStatus').textContent.match(/(\d+)초/)[1]);assert.ok(elapsed>=150);assert.equal(view.postCount(),0);view.leave();await view.flush();
  }
 });
 await test('completion then menu reload restores saved result without network job creation',async()=>{
  const store=new Map(),view=setup(store,{stage:'done'});await view.flush();view.submit();await view.flush();assert.equal(saved(store).length,1);assert.equal(view.postCount(),1);view.leave();const reload=setup(store);await reload.flush();assert.equal(reload.postCount(),0);assert.equal(saved(store).length,1);assert.equal(reload.get('answerQuestion').textContent,'Original follow-up');
 });
 await test('two tabs consume the same completion once and preserve independent job saves',async()=>{
  const store=new Map();pending(store);
  let resolveGet;const getDeferred=new Promise(resolve=>resolveGet=resolve);
  const a=setup(store,{getDeferred}),b=setup(store,{getDeferred});await a.flush();await b.flush();
  resolveGet({ok:true,status:200,json:async()=>({stage:'done',result:result('Original follow-up')})});await a.flush();await b.flush();
  assert.equal(saved(store).length,1);assert.equal(a.postCount()+b.postCount(),0);assert.equal(saved(store)[0].thread,'original-room');
  a.ctx.ResearchThreads.append('another-room',result('Second'),secondJob);b.ctx.ResearchThreads.append('original-room',result('Original follow-up'),job);
  assert.equal(saved(store).length,2);assert.equal(a.ctx.ResearchThreads.read().length,2);
 });
 await test('simultaneous tab submissions share one accepted job',async()=>{
  const store=new Map(),lock=locks();let resolvePost;
  const submitDeferred=new Promise(resolve=>resolvePost=resolve);
  const a=setup(store,{locks:lock,submitDeferred}),b=setup(store,{locks:lock});await a.flush();await b.flush();a.submit();b.submit();await a.flush();await b.flush();assert.equal(a.postCount()+b.postCount(),1);
  resolvePost({ok:true,status:200,json:async()=>({id:job})});await a.flush();await b.flush();assert.equal(a.postCount()+b.postCount(),1);a.leave();b.leave();await a.flush();
 });
 await test('offline status failure keeps job for online recovery',async()=>{
  const store=new Map();pending(store);const view=setup(store,{offline:true});await view.flush();assert.match(view.get('researchStatus').textContent,/계속될 수/);assert.ok(store.has('ilson-research-pending-v1'));assert.equal(view.get('answerPanel').attrs['aria-busy'],'false');
  view.state.offline=false;view.state.stage='done';view.events.dispatch('online');await view.flush();assert.equal(saved(store).length,1);assert.equal(view.postCount(),0);
 });
 await test('capabilities failure waits for authenticated capability recovery',async()=>{
  const store=new Map();pending(store);const view=setup(store,{capStatus:401,stage:'done'});await view.flush();assert.equal(view.calls.filter(c=>c.url.includes('/jobs/')).length,0);assert.equal(view.get('answerPanel').attrs['aria-busy'],'false');view.state.capStatus=200;view.events.dispatch('online');await view.flush();assert.equal(saved(store).length,1);assert.equal(view.postCount(),0);
 });
 for(const status of [401,403])await test('auth '+status+' retains reference and retry refreshes token',async()=>{
  const store=new Map();pending(store);const view=setup(store,{status,capabilities:{mode:'box',async:true,stream:false,provider:'multi',token:'OLD-SECRET'}});await view.flush();assert.match(view.get('researchStatus').textContent,/로그인/);assert.ok(store.has('ilson-research-pending-v1'));assert.ok(!JSON.stringify([...store]).includes('SECRET'));
  view.state.status=200;view.state.stage='done';view.state.capabilities.token='NEW-SECRET';view.submit('Different input');await view.flush();assert.equal(view.postCount(),0);assert.equal(saved(store).length,1);assert.equal(view.calls.at(-1).options.headers['X-Ilson-Research'],'NEW-SECRET');
 });
 await test('notfound terminal failure survives reload without pretending to cancel',async()=>{
  const store=new Map();pending(store);const view=setup(store,{status:404});await view.flush();assert.match(view.get('researchStatus').textContent,/보관 기간/);view.leave();const reload=setup(store);await reload.flush();assert.equal(reload.calls.filter(c=>c.url.includes('/jobs/')).length,0);assert.match(reload.get('researchStatus').textContent,/보관 기간/);assert.equal(reload.postCount(),0);
 });
 await test('server error survives navigation and a deliberate new question can run',async()=>{
  const store=new Map();pending(store);const view=setup(store,{stage:'error',error:'Synthetic provider failure'});await view.flush();assert.match(view.get('researchStatus').textContent,/Synthetic provider failure/);view.leave();const reload=setup(store,{stage:'done',job:secondJob,question:'Next question'});await reload.flush();assert.match(reload.get('researchStatus').textContent,/Synthetic provider failure/);reload.submit('Next question');await reload.flush();assert.equal(reload.postCount(),1);assert.equal(saved(store)[0].id,secondJob);
 });
 await test('lost submit response persists uncertainty and never automatically posts again',async()=>{
  const store=new Map(),view=setup(store,{submitLost:true});await view.flush();view.submit();await view.flush();assert.equal(view.postCount(),1);assert.match(view.get('researchStatus').textContent,/실행 번호를 알 수 없습니다/);view.leave();const reload=setup(store);await reload.flush();reload.submit();await reload.flush();assert.equal(reload.postCount(),0);assert.match(reload.get('researchStatus').textContent,/중복 실행 가능/);
 });
 await test('SSE disconnection falls back to same-job polling',async()=>{
  const store=new Map();pending(store);const view=setup(store,{stage:'done',capabilities:{mode:'box',async:true,stream:true,token:'MEMORY-ONLY',provider:'multi'}});await view.flush();assert.ok(view.calls.some(c=>c.url.endsWith('/events')));assert.equal(saved(store).length,1);assert.equal(view.postCount(),0);
 });
 await test('standalone SSE terminal answer saves once without polling',async()=>{
  const store=new Map();pending(store);const text='data: '+JSON.stringify({revision:1,stage:'reading'})+'\n\ndata: '+JSON.stringify({revision:2,stage:'done',result:result('Original follow-up')})+'\n\n';
  const view=setup(store,{capabilities:{mode:'box',async:true,stream:true,token:'MEMORY-ONLY',provider:'multi'},sseResponse:()=>({ok:true,headers:{get:()=> 'text/event-stream'},body:new ReadableStream({start(controller){controller.enqueue(new TextEncoder().encode(text));controller.close();}})})});await view.flush();assert.equal(saved(store).length,1);assert.equal(view.postCount(),0);assert.equal(view.calls.filter(c=>c.url.includes('/jobs/')&&!c.url.endsWith('/events')).length,0);
 });
 await test('old tab completion cannot clear a newer pending reference',async()=>{
  const store=new Map();pending(store);let resolveGet;const view=setup(store,{getDeferred:new Promise(resolve=>resolveGet=resolve)});await view.flush();pending(store,{ref:'new-ref',id:secondJob,thread:'new-room'});resolveGet({ok:true,status:200,json:async()=>({stage:'done',result:result('Original follow-up')})});await view.flush();assert.equal(JSON.parse(store.get('ilson-research-pending-v1')).id,secondJob);assert.equal(saved(store).length,1);
 });
 await test('storage denied before submit cannot start an untrackable task',async()=>{
  const view=setup();await view.flush();view.storage.setItem=()=>{throw Error('storage denied');};view.submit();await view.flush();assert.equal(view.postCount(),0);assert.match(view.get('researchStatus').textContent,/storage denied/);
 });
 await test('result save failure keeps a downloadable result and retryable job reference',async()=>{
  const store=new Map();pending(store);const view=setup(store,{stage:'done'}),write=view.storage.setItem;view.storage.setItem=(key,value)=>{if(key.startsWith('ilson-research-result-v1:'))throw Error('quota');write(key,value);};await view.flush();assert.match(view.get('claims').textContent,/Verified content/);assert.match(view.get('researchStatus').textContent,/자동 저장 실패/);assert.ok(store.has('ilson-research-pending-v1'));view.storage.setItem=write;view.submit();await view.flush();assert.equal(saved(store).length,1);assert.equal(view.postCount(),0);
 });
 await test('leaving before POST response preserves uncertainty without cancelling server job',async()=>{
  const store=new Map();let rejectPost;const view=setup(store,{submitDeferred:new Promise((_,reject)=>rejectPost=reject)});await view.flush();view.submit();await view.flush();assert.equal(view.postCount(),1);view.leave();rejectPost(Error('document left'));await view.flush();const reload=setup(store);await reload.flush();assert.equal(reload.postCount(),0);assert.match(reload.get('researchStatus').textContent,/실행 번호를 알 수 없습니다/);
 });
 await test('back-forward cache restoration reconnects the same running task',async()=>{
  const store=new Map();pending(store);const view=setup(store);await view.flush();view.leave();await view.flush();view.state.stage='done';view.events.dispatch('pageshow',{persisted:true});await view.flush();assert.equal(saved(store).length,1);assert.equal(view.postCount(),0);
 });
 await test('static request preparation and standalone synchronous execution stay available',async()=>{
  const staticView=setup(new Map(),{capStatus:404});await staticView.flush();staticView.submit('Static question');await staticView.flush();assert.equal(staticView.get('requestPanel').hidden,false);assert.match(staticView.get('requestText').textContent,/Static question/);assert.equal(staticView.postCount(),0);
  const sync=setup(new Map(),{capabilities:{mode:'box',async:false,stream:false,provider:'aside',token:'MEMORY-ONLY'}});await sync.flush();sync.submit('Synchronous');await sync.flush();assert.equal(sync.calls.filter(c=>c.url==='/api/research'&&c.options.method==='POST').length,1);assert.match(sync.get('claims').textContent,/Verified content/);
 });
 console.log('research lifecycle PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});
