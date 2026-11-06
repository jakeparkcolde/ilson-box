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
function token(plan=2) {
 const p=Buffer.alloc(29); p[0]=1;p[1]=1;p.fill(42,2,18);p.writeUInt16BE(1,18);p[20]=plan;
 const now=Math.floor(Date.now()/1000);p.writeUInt32BE(now-60,21);p.writeUInt32BE(now+3600*24*365,25);
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
test('API and PostgreSQL transactions: register, limit, revoke and renew', async()=>{
 const db=new PGlite();
 await db.exec('create role anon; create role authenticated; create role service_role;');
 await db.exec(fs.readFileSync(require('node:path').join(__dirname,'../migrations/001_license.sql'),'utf8'));
 global.fetch=async (_url,opts)=>{
  try {
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
