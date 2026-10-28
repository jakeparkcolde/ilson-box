'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[2],'utf8');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const people={employees:[],departments:[],skills:[],assignments:[],catalog:[]};
function harness(){
 const nodes={},events={},requests=[];
 const node=id=>nodes[id]||(nodes[id]={innerHTML:'',textContent:'',replaceChildren(){this.innerHTML='';},contains(){return false;},querySelectorAll(){return [];}});
 const document={hidden:false,activeElement:null,getElementById:node,querySelectorAll:()=>[],addEventListener:(key,fn)=>events[key]=fn};
 const context={document,AbortController,setTimeout:()=>1,clearTimeout(){},console,
  fetch:(path,options={})=>new Promise((resolve,reject)=>{
   const request={path,options,resolve,reject};requests.push(request);
   options.signal?.addEventListener('abort',()=>reject(Object.assign(Error('Aborted'),{name:'AbortError'})),{once:true});
  })};
 vm.createContext(context);vm.runInContext(source,context);
 return {document,node,events,requests,run:code=>vm.runInContext(code,context),
  reply:(request,body)=>request.resolve({ok:true,status:200,json:async()=>body}),
  click:()=>events.click({target:{closest:()=>({dataset:{tab:'jobs'}})}})};
}
async function initialClick(){
 const h=harness();const click=h.click();await flush();
 // Clicking before initial state must replace the cancelled request.
 assert.equal(h.requests.length,2,'initial Jobs click must reload initial people state');
 assert(h.requests[0].options.signal.aborted);
 h.reply(h.requests[1],people);await flush();assert(h.requests.at(-1).path.endsWith('/jobs'));
 h.reply(h.requests.at(-1),{jobs:[]});await click;await flush();
 assert(h.node('view').innerHTML.includes('아직 요청한 직원 업무가 없습니다.'));
 const count=h.requests.length;await h.run('poll()');assert.equal(h.requests.length,count,'completed Jobs remains manual');
}
async function hiddenJobs(showEarly=false){
 const h=harness();h.reply(h.requests[0],people);await flush();
 const click=h.click();await flush();const old=h.requests.at(-1);assert(old.path.endsWith('/jobs'));
 h.node('editor').innerHTML='보존할 입력';
 h.document.hidden=true;h.events.visibilitychange();
 // Reappear before the old request settles: busy guard may defer recovery to the next tick.
 if(showEarly){h.document.hidden=false;h.events.visibilitychange();}await flush();
 h.reply(old,{jobs:[{id:'old',kind:'employee',title:'폐기할 늦은 응답',status:'done'}]});await click;await flush();
 if(!showEarly){h.document.hidden=false;h.events.visibilitychange();await flush();}
 h.run('poll();poll()');await flush();
 assert(old.options.signal.aborted,'hidden Jobs request must be cancelled');
 const current=h.requests.at(-1);assert.notEqual(current,old,'visible Jobs must recover a discarded load');
 if(current.path.endsWith('/people')){h.reply(current,people);await flush();}
 const replacement=h.requests.at(-1);assert(replacement.path.endsWith('/jobs'));assert.notEqual(replacement,old);
 h.reply(replacement,{jobs:[{id:'new',kind:'employee',title:'복구된 업무',status:'done'}]});await flush();
 assert.equal(h.requests.filter(r=>r.path.endsWith('/jobs')).length,2,'one replacement Jobs request');
 assert(h.node('view').innerHTML.includes('복구된 업무'));assert(!h.node('view').innerHTML.includes('폐기할 늦은 응답'));
 assert.equal(h.node('editor').innerHTML,'보존할 입력');
 const count=h.requests.length;await h.run('poll()');assert.equal(h.requests.length,count,'no periodic Jobs refresh after recovery');
}
async function visibleBeforeOldSettles(){await hiddenJobs(true);}
(async()=>{let failures=0;for(const test of [initialClick,hiddenJobs,visibleBeforeOldSettles]){try{await test();console.log('PASS',test.name);}catch(error){failures++;console.error('FAIL',test.name,error.message);}}process.exitCode=failures?1:0;})();
