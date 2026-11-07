const test=require('node:test');
const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const fs=require('node:fs');
const {PGlite}=require(process.env.PGLITE_PATH || '@electric-sql/pglite');
const handler=require('../api/v1/[action].js');
const seed=Buffer.from('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60','hex');
const key=crypto.createPrivateKey({key:Buffer.concat([Buffer.from('302e020100300506032b657004220420','hex'),seed]),format:'der',type:'pkcs8'});
process.env.ILSON_PUBLIC_KEY_1='d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a';
process.env.ILSON_ADMIN_SECRET='test-secret'; process.env.SUPABASE_URL='https://example.invalid'; process.env.SUPABASE_SECRET_KEY='test-key';
function token(plan=2, fill=42, cohort=1, expired=false) {
 const p=Buffer.alloc(29); p[0]=1;p[1]=1;p.fill(fill,2,18);p.writeUInt16BE(cohort,18);p[20]=plan;
 const now=Math.floor(Date.now()/1000);p.writeUInt32BE(now-120,21);p.writeUInt32BE(expired?now-60:now+3600*24*365,25);
 const sig=crypto.sign(null,Buffer.concat([Buffer.from('ILSON-LICENSE-V1\0'),p]),key);
 let bits=0,acc=0,out=''; for (const byte of Buffer.concat([p,sig])) {acc=(acc<<8)|byte;bits+=8;while(bits>=5){bits-=5;out+='ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'[(acc>>bits)&31];acc&=(1<<bits)-1;}}
 if(bits)out+='ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'[(acc<<(5-bits))&31];
 return 'ILSON-'+(out.match(/.{1,5}/g).join('-'));
}
function run(action,body,admin=false) {
 return new Promise((resolve,reject)=>{
  const res={setHeader(){},status(code){this.code=code;return this},json(value){resolve({code:this.code,value});return this}};
  handler({method:'POST',query:{action},body:{...body,nonce:'a'.repeat(32)},headers:{'x-forwarded-for':'192.0.2.1',...(admin?{'x-ilson-admin':'test-secret'}:{})}},res).catch(reject);
 });
}
test('health responds without secrets and only accepts GET',()=>{
 const health=require('../api/health.js');
 const res={setHeader(){},status(code){this.code=code;return this},json(value){this.value=value;return this}};
 health({method:'GET'},res);assert.equal(res.code,200);assert.deepEqual(res.value,{service:'ilson-license',status:'ok'});
 health({method:'POST'},res);assert.equal(res.code,405);
});
test('skill sharing requires a live registered license and moderation', async()=>{
 const db=new PGlite();
 await db.exec('create role anon; create role authenticated; create role service_role;');
 for (const name of ['001_license.sql','002_skill_share.sql']) await db.exec(fs.readFileSync(require('node:path').join(__dirname,'../migrations',name),'utf8'));
 global.fetch=async (url,opts)=>{
  const body=JSON.parse(opts.body);
  const fn=url.pathname.split('/').pop();
  const arg=fn==='ilson_rate_limit'?body.p_bucket:JSON.stringify(body.p);
  const type=fn==='ilson_rate_limit'?'text':'jsonb';
  const result=await db.query(`select public.${fn}($1::${type}) as result`,[arg]);
  return {ok:true,json:async()=>result.rows[0].result};
 };
 const one=token(1,41,1), two=token(1,42,2), dead=token(1,43,1,true), device='a'.repeat(64);
 for (const [i,serial] of [one,two,dead].entries()) {
  assert.equal((await run('register',{serial,display_name:'실명은 비공개',request_id:String(i+1).repeat(32)},true)).value.status,'ok');
  if (serial!==dead) assert.equal((await run('activate',{serial,device_id:device})).value.status,'active');
 }
 const data={serial:one,device_id:device,name:'sample',files:{'SKILL.md':'# 학습\n검토합니다.'}};
 assert.equal((await run('skill-list',{serial:'bad',device_id:device})).value.status,'invalid_serial');
 assert.equal((await run('skill-list',{serial:dead,device_id:device})).value.status,'expired');
 assert.equal((await run('skill-list',{serial:one,device_id:'b'.repeat(64)})).value.status,'device_not_registered');
 assert.equal((await run('skill-share',{...data,files:{'../SKILL.md':'bad'}})).value.status,'invalid_request');
 const shared=await run('skill-share',data);assert.equal(shared.value.status,'ok');const id=shared.value.id;
 assert.deepEqual((await run('skill-list',{serial:two,device_id:device})).value.items,[]);
 assert.equal((await run('skill-get',{serial:two,device_id:device,id})).value.status,'not_found');
 assert.equal((await run('skill-withdraw',{serial:two,device_id:device,id})).value.status,'forbidden');
 assert.equal((await run('skill-admin-approve',{id})).code,403);
 const pending=await run('skill-admin-list',{},true);assert.equal(pending.value.items[0].status,'pending');
 assert.equal((await run('skill-admin-approve',{id},true)).value.status,'ok');
 const list=await run('skill-list',{serial:two,device_id:device});assert.equal(list.value.items.length,1);
 assert(!JSON.stringify(list).includes('실명은 비공개'));
 assert.equal((await run('skill-get',{serial:two,device_id:device,id})).value.item.files['SKILL.md'],'# 학습\n검토합니다.');
 process.env.ILSON_SKILL_COHORT_ONLY='true';
 assert.deepEqual((await run('skill-list',{serial:two,device_id:device})).value.items,[]);
 assert.equal((await run('skill-get',{serial:two,device_id:device,id})).value.status,'not_found');
 delete process.env.ILSON_SKILL_COHORT_ONLY;
 const rejected=(await run('skill-share',data)).value.id;
 assert.equal((await run('skill-admin-reject',{id:rejected},true)).value.status,'ok');
 assert.equal((await run('skill-get',{serial:one,device_id:device,id:rejected})).value.status,'not_found');
 assert.equal((await run('skill-admin-approve',{id:rejected},true)).value.status,'conflict');
 const moderated=(await run('skill-share',data)).value.id;
 assert.equal((await run('skill-admin-approve',{id:moderated},true)).value.status,'ok');
 assert.equal((await run('skill-admin-withdraw',{id:moderated},true)).value.status,'ok');
 assert.equal((await run('skill-get',{serial:two,device_id:device,id:moderated})).value.status,'not_found');
 assert.equal((await run('skill-withdraw',{serial:one,device_id:device,id})).value.status,'ok');
 assert.equal((await run('skill-get',{serial:one,device_id:device,id})).value.status,'not_found');
 assert.equal((await run('revoke',{serial:two,request_id:'7'.repeat(32)},true)).value.status,'ok');
 assert.equal((await run('skill-list',{serial:two,device_id:device})).value.status,'revoked');
 await db.close();
});
test('API and PostgreSQL transactions: register, limit, revoke and renew', async()=>{
 const db=new PGlite();
 await db.exec('create role anon; create role authenticated; create role service_role;');
 await db.exec(fs.readFileSync(require('node:path').join(__dirname,'../migrations/001_license.sql'),'utf8'));
 global.fetch=async (_url,opts)=>{
  try {
   assert.equal(opts.headers.apikey,process.env.SUPABASE_SECRET_KEY);
   assert.equal(opts.headers.Authorization,undefined,'opaque Supabase API keys are not bearer JWTs');
   const body=JSON.parse(opts.body);
   const r=_url.pathname.endsWith('/ilson_rate_limit')
    ? await db.query('select public.ilson_rate_limit($1::text) as result',[body.p_bucket])
    : await db.query('select public.ilson_license_request($1::jsonb) as result',[JSON.stringify(body.p)]);
   return {ok:true,json:async()=>r.rows[0].result};
  }
  catch(e){throw e;}
 };
 const serial=token();const now=Math.floor(Date.now()/1000);
 assert.equal((await run('register',{serial,display_name:'가명',paid_until:null,request_id:'0'.repeat(32)},true)).code,400);
 const reg=await run('register',{serial,display_name:'가명',paid_until:now+86400,request_id:'1'.repeat(32)},true);
 assert.equal(reg.value.status,'ok');
 for(let n=1;n<=2;n++) assert.equal((await run('activate',{serial,device_id:String(n).repeat(64)})).value.status,'active');
 assert.equal((await run('activate',{serial,device_id:'3'.repeat(64)})).value.status,'device_limit');
 assert.equal((await run('renew-payment',{serial,paid_until:null,request_id:'9'.repeat(32)},true)).code,400);
 assert.equal((await run('renew-payment',{serial,paid_until:now+172800,request_id:'2'.repeat(32)},true)).value.status,'ok');
 assert.equal((await run('check',{serial,device_id:'1'.repeat(64)})).value.paid_until,now+172800);
 assert.equal((await run('revoke',{serial,request_id:'3'.repeat(32)},true)).value.status,'ok');
 assert.equal((await run('check',{serial,device_id:'1'.repeat(64)})).value.status,'revoked');
 assert.equal((await run('register',{serial,display_name:'X',paid_until:now+86400,request_id:'4'.repeat(32)},false)).code,403);
 let throttled=false;
 for(let i=0;i<121;i++) {
  const r=await run('register',{serial,display_name:'X',paid_until:now+86400,request_id:'4'.repeat(32)},false);
  if(r.code===429) {throttled=true;break;}
 }
 assert.equal(throttled,true,'invalid admin attempts must be rate limited');
 await db.close();
});
