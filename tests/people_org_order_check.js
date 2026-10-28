/* Execute the real org actions against mixed hierarchy storage order. No network/browser needed. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const file=process.argv[2]||'template/web/current/people.js';
const source=fs.readFileSync(file,'utf8').replace('return {mount,leave,canLeave};','return {mount,leave,canLeave,test:{P,action,org}};');
const view={innerHTML:'',children:[],querySelectorAll:()=>[]};
const context={window:{addEventListener(){}},document:{activeElement:null},console};
vm.createContext(context);vm.runInContext(source,context);
const {P,action,org}=context.window.IlsonPeople.test;
const rows=[{id:'a',name:'기획',parent_id:''},{id:'a1',name:'하위1',parent_id:'a'},{id:'b',name:'운영',parent_id:''},{id:'b1',name:'운영하위',parent_id:'b'},{id:'a2',name:'하위2',parent_id:'a'},{id:'c',name:'지원',parent_id:''}];
P.tab='org';P.data={departments:rows,employees:[]};P.root={querySelector:id=>id==='#p-view'?view:null};
P.org={departments:structuredClone(rows),placements:{employee:'a1'}};
const order=parent=>Array.from(P.org.departments.filter(d=>d.parent_id===parent),d=>d.id);
const relationships=()=>JSON.stringify([...P.org.departments].sort((a,b)=>a.id.localeCompare(b.id)).map(d=>[d.id,d.name,d.parent_id]));
const originalRelations=relationships(),originalPlacement=JSON.stringify(P.org.placements);
function disabled(id,action){const html=org();const tag=html.match(new RegExp('<button[^>]*data-p="'+action+'"[^>]*data-id="'+id+'"[^>]*>'));assert.ok(tag,'button exists');return /\sdisabled(?:\s|>)/.test(tag[0]);}
(async()=>{
 await action('org-up','b');assert.deepEqual(order(''),['b','a','c'],'운영↑ must cross an interleaved child and move before 기획');
 assert.deepEqual(order('a'),['a1','a2']);assert.deepEqual(order('b'),['b1']);
 await action('org-down','b');assert.deepEqual(order(''),['a','b','c']);
 await action('org-up','a2');assert.deepEqual(order('a'),['a2','a1'],'child siblings move across another branch');assert.deepEqual(order(''),['a','b','c']);
 assert.equal(disabled('a','org-up'),true);assert.equal(disabled('c','org-down'),true);
 assert.equal(disabled('a2','org-up'),true);assert.equal(disabled('a1','org-down'),true);
 assert.equal(disabled('b','org-up'),false);assert.equal(disabled('b','org-down'),false);
 assert.equal(disabled('b1','org-up'),true);assert.equal(disabled('b1','org-down'),true);
 const before=JSON.stringify(P.org);for(const [a,id] of [['org-up','a'],['org-down','c'],['org-up','a2'],['org-down','a1'],['org-up','missing']])await action(a,id);
 assert.equal(JSON.stringify(P.org),before,'boundaries and unknown IDs are safe no-ops');
 assert.equal(relationships(),originalRelations,'parent, name and membership must stay unchanged');
 assert.equal(JSON.stringify(P.org.placements),originalPlacement);
 console.log('PASS mixed root/child sibling up/down, boundary disabled/no-op, unrelated order, parent and employee preservation');
})().catch(error=>{console.error(error);process.exitCode=1;});
