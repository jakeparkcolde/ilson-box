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

test('V2 short serial: register, activate, device limit, revoke, V1/skill-share interop and rate limit', async()=>{
 const db=new PGlite();
 await db.exec('create role anon; create role authenticated; create role service_role;');
 for (const name of ['001_license.sql','002_skill_share.sql','003_short_serial.sql']) {
  await db.exec(fs.readFileSync(require('node:path').join(__dirname,'../migrations',name),'utf8'));
 }
 global.fetch=async (url,opts)=>{
  const body=JSON.parse(opts.body);
  const fn=url.pathname.split('/').pop();
  const arg=fn==='ilson_rate_limit'?body.p_bucket:JSON.stringify(body.p);
  const type=fn==='ilson_rate_limit'?'text':'jsonb';
  const result=await db.query(`select public.${fn}($1::${type}) as result`,[arg]);
  return {ok:true,json:async()=>result.rows[0].result};
 };
 const v1=token(1,55,1), v1Other=token(1,56,1);
 const shortCode='IL2-ABCD-EFGH-JKLM';
 const sch=handler.shortCodeHash(shortCode);
 const sealed='Z'.repeat(188);
 // Half-pair or malformed short fields must be rejected with 400 invalid_serial
 assert.equal((await run('register',{serial:v1,display_name:'V2',request_id:'1'.repeat(32),short_code_hash:sch},true)).code,400);
 assert.equal((await run('register',{serial:v1,display_name:'V2',request_id:'1'.repeat(32),short_code_hash:'bad',sealed_serial:sealed},true)).code,400);
 // Valid V2 register + idempotent retry + mismatched short fields conflict
 assert.equal((await run('register',{serial:v1,display_name:'V2',request_id:'2'.repeat(32),short_code_hash:sch,sealed_serial:sealed},true)).value.status,'ok');
 assert.equal((await run('register',{serial:v1,display_name:'V2',request_id:'2'.repeat(32),short_code_hash:sch,sealed_serial:sealed},true)).value.status,'ok');
 assert.equal((await run('register',{serial:v1,display_name:'V2',request_id:'8'.repeat(32),short_code_hash:sch,sealed_serial:'X'.repeat(188)},true)).code,409);
 // Duplicate short_code_hash on another license -> 409 conflict
 assert.equal((await run('register',{serial:v1Other,display_name:'V2B',request_id:'3'.repeat(32),short_code_hash:sch,sealed_serial:'Y'.repeat(188)},true)).code,409);
 // RLS: anon and authenticated cannot read license_private.licenses or call ilson_license_request
 await assert.rejects(()=>db.exec('begin; set local role anon; select short_code_hash, sealed_serial from license_private.licenses; commit;'));
 await db.exec('rollback;');
 await assert.rejects(()=>db.exec('begin; set local role authenticated; select public.ilson_license_request(\'{}\'::jsonb); commit;'));
 await db.exec('rollback;');
 // Activate devices 1 & 2 via short serial (lowercase/spaces normalized) -> returns sealed_serial
 const act1=await run('activate',{serial:shortCode.toLowerCase().replace(/-/g,' '),device_id:'1'.repeat(64)});
 assert.equal(act1.code,200); assert.equal(act1.value.status,'active'); assert.equal(act1.value.sealed_serial,sealed);
 const act2=await run('activate',{serial:shortCode,device_id:'2'.repeat(64)});
 assert.equal(act2.code,200); assert.equal(act2.value.status,'active'); assert.equal(act2.value.sealed_serial,sealed);
 // Device 3 hits device_limit and MUST NOT return sealed_serial
 const act3=await run('activate',{serial:shortCode,device_id:'3'.repeat(64)});
 assert.equal(act3.code,409); assert.equal(act3.value.status,'device_limit'); assert.equal(act3.value.sealed_serial,undefined);
 // V1 check & skill-share work with the V1 serial on the device activated via V2 short code
 const chk=await run('check',{serial:v1,device_id:'1'.repeat(64)});
 assert.equal(chk.code,200); assert.equal(chk.value.status,'active'); assert.equal(chk.value.sealed_serial,undefined);
 const shared=await run('skill-share',{serial:v1,device_id:'1'.repeat(64),name:'v2skill',files:{'SKILL.md':'# 테스트'}});
 assert.equal(shared.code,200); assert.equal(shared.value.status,'ok');
 // Revoke -> V2 activate returns 403 revoked and MUST NOT return sealed_serial
 assert.equal((await run('revoke',{serial:v1,request_id:'4'.repeat(32)},true)).value.status,'ok');
 const revAct=await run('activate',{serial:shortCode,device_id:'1'.repeat(64)});
 assert.equal(revAct.code,403); assert.equal(revAct.value.status,'revoked'); assert.equal(revAct.value.sealed_serial,undefined);
 // Nonexistent short code rate-limiting (short:<hash> bucket at 60/min, even across distinct IPs)
 const badShort='IL2-2345-6789-ABCD';
 let shortThrottled=false;
 for (let i=0;i<65;i++) {
  const r=await new Promise((resolve,reject)=>{
   const res={setHeader(){},status(code){this.code=code;return this},json(value){resolve({code:this.code,value});return this}};
   handler({method:'POST',query:{action:'activate'},body:{serial:badShort,device_id:'9'.repeat(64),nonce:'b'.repeat(32)},headers:{'x-forwarded-for':`198.51.100.${i+1}`}},res).catch(reject);
  });
  if (r.code===429 && r.value.status==='rate_limited') { shortThrottled=true; break; }
  assert.equal(r.code,400); assert.equal(r.value.status,'invalid_serial'); assert.equal(r.value.sealed_serial,undefined);
 }
 assert.equal(shortThrottled,true,'unknown short code probes must be rate limited');
 await db.close();
});

test('Full Install Tracking: telemetry, client_meta linking, admin-overview, RLS and rate limit', async()=>{
 const db=new PGlite();
 await db.exec('create role anon; create role authenticated; create role service_role;');
 for (const name of ['001_license.sql','002_skill_share.sql','003_short_serial.sql','004_install_tracking.sql','004_install_tracking.sql']) {
  await db.exec(fs.readFileSync(require('node:path').join(__dirname,'../migrations',name),'utf8'));
 }
 global.fetch=async (url,opts)=>{
  const body=JSON.parse(opts.body);
  const fn=url.pathname.split('/').pop();
  const arg=fn==='ilson_rate_limit'?body.p_bucket:JSON.stringify(body.p);
  const type=fn==='ilson_rate_limit'?'text':'jsonb';
  const result=await db.query(`select public.${fn}($1::${type}) as result`,[arg]);
  return {ok:true,json:async()=>result.rows[0].result};
 };

 // RLS checks for new table and RPCs
 for (const role of ['anon','authenticated']) {
  await assert.rejects(()=>db.exec(`begin; set local role ${role}; select * from license_private.install_runs; commit;`));
  await db.exec('rollback;');
  await assert.rejects(()=>db.exec(`begin; set local role ${role}; select public.ilson_install_telemetry('{}'::jsonb); commit;`));
  await db.exec('rollback;');
  await assert.rejects(()=>db.exec(`begin; set local role ${role}; select public.ilson_admin_overview('{}'::jsonb); commit;`));
  await db.exec('rollback;');
 }

 // Register licenses in cohort 1 (V2 + V1) and cohort 2 (V1 inactive)
 const v2Serial=token(1,61,1), v1Serial=token(1,62,1), c2Serial=token(1,63,2);
 const shortCode='IL2-WXYZ-2345-6789';
 const sch=handler.shortCodeHash(shortCode);
 const sealed='S'.repeat(188);
 assert.equal((await run('register',{serial:v2Serial,display_name:'홍길동',request_id:'1'.repeat(32),short_code_hash:sch,sealed_serial:sealed},true)).value.status,'ok');
 assert.equal((await run('register',{serial:v1Serial,display_name:'김철수',request_id:'2'.repeat(32)},true)).value.status,'ok');
 assert.equal((await run('register',{serial:c2Serial,display_name:'이영희',request_id:'3'.repeat(32)},true)).value.status,'ok');

 // Telemetry validation: reject invalid enums, PII, unknown keys, bad failed_steps
 const winRun='a'.repeat(32), macRun='b'.repeat(32), failedRun='c'.repeat(32);
 const baseTel={run_id:winRun,edition:'windows-course',os:'Windows',arch:'AMD64',os_version:'10.0.26100',shell:'powershell',shell_version:'5.1.26100.1',installer_version:'ILSON-DIAG-1',result:'ok',exit_code:0,failed_steps:[],helper_status:'INSTALLED'};
 assert.equal((await run('install-telemetry',{...baseTel,email:'user@example.com'})).code,400);
 assert.equal((await run('install-telemetry',{...baseTel,os:'FreeBSD'})).code,400);
 assert.equal((await run('install-telemetry',{...baseTel,os_version:'Windows 11 /Users/secret'})).code,400);
 assert.equal((await run('install-telemetry',{...baseTel,failed_steps:[{step_id:'evil.step',reason_code:'TIMEOUT'}]})).code,400);
 assert.equal((await run('install-telemetry',{...baseTel,failed_steps:[{step_id:'apps.herdr',reason_code:'DOWNLOAD_FAILED',note:'secret'}]})).code,400);
 assert.equal((await run('install-telemetry',{...baseTel,failed_steps:Array.from({length:21},()=>({step_id:'apps.herdr',reason_code:'TIMEOUT'}))})).code,400);

 // Valid telemetry submissions
 assert.equal((await run('install-telemetry',baseTel)).code,200);
 assert.equal((await run('install-telemetry',{run_id:macRun,edition:'intel-course',os:'macOS',arch:'x86_64',os_version:'13.6',shell:'bash',shell_version:'3.2.57',installer_version:'ILSON-DIAG-1',result:'ok',exit_code:0,failed_steps:[],helper_status:'UPDATED'})).code,200);
 assert.equal((await run('install-telemetry',{run_id:failedRun,edition:'windows-course',os:'Windows',arch:'AMD64',os_version:'10.0.22631',shell:'powershell',shell_version:'5.1.22621',installer_version:'ILSON-DIAG-1',result:'failed',exit_code:1,failed_steps:[{step_id:'apps.herdr',reason_code:'HTTP_FAILED',http_code:503},{step_id:'runtime.python',reason_code:'RUNTIME_MISSING'}]})).code,200);

 // V2 activate with valid client_meta links winRun
 const dev1='1'.repeat(64), dev2='2'.repeat(64);
 const actV2=await run('activate',{serial:shortCode,device_id:dev1,client_meta:{os:'Windows',arch:'AMD64',edition:'windows-course',client_version:'ILSON-DIAG-1',run_id:winRun}});
 assert.equal(actV2.code,200); assert.equal(actV2.value.status,'active'); assert.equal(actV2.value.sealed_serial,sealed);

 // Upsert same winRun must preserve license_id
 assert.equal((await run('install-telemetry',{...baseTel,helper_status:'UP_TO_DATE'})).code,200);

 // V1 activate with malformed client_meta still succeeds; valid fields kept, invalid ignored
 const actV1=await run('activate',{serial:v1Serial,device_id:dev2,client_meta:{os:'INVALID_OS',arch:'x86_64',edition:'evil',client_version:'bad version with spaces',run_id:'not-hex'}});
 assert.equal(actV1.code,200); assert.equal(actV1.value.status,'active');
 // V1 check updates missing os/edition and links macRun while keeping existing arch
 const chkV1=await run('check',{serial:v1Serial,device_id:dev2,client_meta:{os:'macOS',edition:'intel-course',client_version:'ILSON-DIAG-1',run_id:macRun}});
 assert.equal(chkV1.code,200); assert.equal(chkV1.value.status,'active');

 // admin-overview auth & validation
 assert.equal((await run('admin-overview',{},false)).code,403);
 assert.equal((await run('admin-overview',{cohort:0},true)).code,400);
 assert.equal((await run('admin-overview',{cohort:'1'},true)).code,400);

 // admin-overview full report
 const ov=await run('admin-overview',{},true);
 assert.equal(ov.code,200); assert.equal(ov.value.status,'ok');
 assert.equal(ov.value.summary.total_licenses,3);
 assert.equal(ov.value.summary.active_licenses,2);
 assert.equal(ov.value.summary.inactive_licenses,1);
 assert.equal(ov.value.summary.revoked_licenses,0);
 assert.equal(ov.value.summary.total_active_devices,2);
 assert.equal(ov.value.summary.recent_runs_7d,3);
 assert.equal(ov.value.summary.ok_runs_7d,2);
 assert.equal(ov.value.summary.failed_runs_7d,1);
 assert.equal(ov.value.cohorts.length,2);
 assert.deepEqual(ov.value.cohorts.map(c=>c.cohort),[1,2]);
 // Secret/hash leak check
 const rawOv=JSON.stringify(ov.value);
 assert(!rawOv.includes(sealed),'must never expose sealed_serial');
 assert(!rawOv.includes(sch),'must never expose short_code_hash');
 const dev1Hash=crypto.createHash('sha256').update('ilson-device-v1\0'+dev1).digest('hex');
 assert(!rawOv.includes(dev1Hash),'must never expose full device_hash');
 assert(rawOv.includes(dev1Hash.slice(0,12)),'should expose 12-char device_hash_prefix');
 // Check linked license_id & devices metadata
 const v2Lic=ov.value.licenses.find(l=>l.display_name==='홍길동');
 assert.equal(v2Lic.has_short_serial,true);
 assert.equal(v2Lic.devices[0].os,'Windows');
 assert.equal(v2Lic.devices[0].arch,'AMD64');
 const v1Lic=ov.value.licenses.find(l=>l.display_name==='김철수');
 assert.equal(v1Lic.has_short_serial,false);
 assert.equal(v1Lic.devices[0].os,'macOS');
 assert.equal(v1Lic.devices[0].arch,'x86_64');
 assert.equal(v1Lic.devices[0].edition,'intel-course');
 const linkedWin=ov.value.install_runs.find(r=>r.run_id===winRun);
 assert.equal(linkedWin.display_name,'홍길동');
 const unlinkedFail=ov.value.install_runs.find(r=>r.run_id===failedRun);
 assert.equal(unlinkedFail.display_name,null);
 assert.equal(ov.value.failure_breakdown.length,2);

 // Cohort filter
 const ovC2=await run('admin-overview',{cohort:2},true);
 assert.equal(ovC2.code,200);
 assert.equal(ovC2.value.licenses.length,1);
 assert.equal(ovC2.value.licenses[0].display_name,'이영희');

 // Telemetry rate limiting (>60/min from same IP -> 429)
 let telLimited=false;
 for (let i=0;i<65;i++) {
  const r=await new Promise((resolve,reject)=>{
   const res={setHeader(){},status(code){this.code=code;return this},json(value){resolve({code:this.code,value});return this}};
   handler({method:'POST',query:{action:'install-telemetry'},body:{...baseTel,run_id:String(i).padStart(32,'0'),nonce:'d'.repeat(32)},headers:{'x-forwarded-for':'203.0.113.77'}},res).catch(reject);
  });
  if (r.code===429 && r.value.status==='rate_limited') { telLimited=true; break; }
  assert.equal(r.code,200);
 }
 assert.equal(telLimited,true,'telemetry endpoint must enforce 60/min rate limit');
 await db.close();
});
