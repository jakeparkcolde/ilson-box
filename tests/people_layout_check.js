'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('template/web/current/people.js','utf8').replace('return {mount,leave,canLeave};','return {mount,leave,canLeave,test:{P,action,org,portrait}};');
const storage={};const context={structuredClone,window:{addEventListener(){}},document:{activeElement:null},localStorage:{getItem:k=>storage[k],setItem:(k,v)=>storage[k]=v},confirm:()=>true,crypto:require('node:crypto').webcrypto,console};
function create(){vm.createContext(context);vm.runInContext(source,context);return context.window.IlsonPeople.test;}
(async()=>{let {P,action,org,portrait}=create();P.tab='org';P.data={departments:[{id:'a',name:'기존 팀',parent_id:''}],employees:[{id:'b',name:'기존 직원',department_id:'a',role:'검토'}]};const view={innerHTML:'',querySelectorAll:()=>[]};P.root={querySelector:id=>id==='#p-view'?view:null};
const populated=P.data;P.data={departments:[],employees:[]};assert.match(org(),/조직도 보기/);assert.match(org(),/범용 조직 템플릿/);P.data=populated;
assert.match(org(),/조직도 보기/);assert.match(org(),/범용 조직 템플릿/);assert.match(portrait(P.data.employees[0]),/<svg/);
await action('org-layout','list');assert.equal(storage['ilson-org-layout'],'list');assert.match(org(),/p-layout-list/);
const before=JSON.stringify(P.data);await action('org-template','official');assert.equal(JSON.stringify(P.data),before);assert.equal(P.org.placements.b,'a');assert.equal(P.org.departments[0].name,'기존 팀');assert.ok(P.org.departments.some(d=>d.parent_id));
const n=P.org.departments.length;await action('org-template','official');assert.equal(P.org.departments.length,n);
for(const id of ['functional','service','flat'])await action('org-template',id);
assert.equal(JSON.stringify(P.data),before);assert.equal(P.org.placements.b,'a');
assert.equal(create().P.layout,'list');console.log('PASS first-visit controls, default face, layout persistence, additive template draft and placement preservation');
})().catch(e=>{console.error(e);process.exitCode=1;});
