'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const nodes={},events={},requests=[];let nextTimer=0;
const node=id=>nodes[id]||(nodes[id]={innerHTML:'',textContent:'',clears:0,replaceChildren(){this.clears++;this.innerHTML='';},contains(){return false;},querySelectorAll(){return [];}});
const document={hidden:false,activeElement:null,getElementById:node,querySelectorAll:()=>[],addEventListener:(key,fn)=>events[key]=fn};
const context={document,AbortController,setTimeout:()=>++nextTimer,clearTimeout(){},console,
 fetch:(path,options)=>new Promise((resolve,reject)=>requests.push({path,options,resolve,reject}))};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),context);
const run=code=>vm.runInContext(code,context),flush=()=>new Promise(r=>setImmediate(r));
const state=name=>({employees:[{id:'a'.repeat(32),name,role:'역할',active:1,department_id:''}],departments:[],skills:[],assignments:[],catalog:[]});
const reply=(request,data,status=200)=>request.resolve({ok:status===200,status,json:async()=>data});
(async()=>{
 assert.equal(requests.length,1);reply(requests[0],state('처음'));await flush();
 node('editor').innerHTML='작성 중 입력';const clears=node('editor').clears;
 run('poll();poll()');assert.equal(requests.length,2,'one request in flight');
 reply(requests[1],state('새 직원'));await flush();
 assert(node('view').innerHTML.includes('새 직원'));assert.equal(node('editor').innerHTML,'작성 중 입력');assert.equal(node('editor').clears,clears);
 run('poll()');const stale=requests[2];document.hidden=true;events.visibilitychange();assert(stale.options.signal.aborted);
 reply(stale,state('늦은 응답'));await flush();assert(!node('view').innerHTML.includes('늦은 응답'));
 const count=requests.length;await run('poll()');assert.equal(requests.length,count,'hidden tab does not request');
 document.hidden=false;events.visibilitychange();reply(requests.at(-1),state('다시 보임'));await flush();assert(node('view').innerHTML.includes('다시 보임'));
 run('busy=true');await run('poll()');assert.equal(requests.length,count+1);run('busy=false');
 run('poll()');requests.at(-1).reject(Error('offline'));await flush();assert(node('sync-status').textContent.includes('다시 연결'));assert.equal(node('editor').innerHTML,'작성 중 입력');
 run('poll()');reply(requests.at(-1),{},401);await flush();assert.equal(run('authExpired'),true);assert(node('sync-status').textContent.includes('만료'));assert.equal(node('editor').innerHTML,'작성 중 입력');
 console.log('PASS polling: single flight, input preservation, hidden/visible, abort/late response, busy, offline, 401');
})().catch(e=>{console.error(e);process.exitCode=1;});
