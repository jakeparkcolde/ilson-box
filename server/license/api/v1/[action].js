'use strict';
const crypto = require('node:crypto');
const DOMAIN = Buffer.from('ILSON-LICENSE-V1\0');
const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';

function serialData(value) {
  if (typeof value !== 'string' || value.length > 512) throw new Error('INVALID_SERIAL');
  const clean = value.replace(/[\s-]/g, '').toUpperCase();
  if (!/^ILSON[A-Z2-7]{149}$/.test(clean)) throw new Error('INVALID_SERIAL');
  let bits = 0, acc = 0, out = [];
  for (const c of clean.slice(5)) {
    acc = (acc << 5) | ALPHABET.indexOf(c); bits += 5;
    if (bits >= 8) { bits -= 8; out.push((acc >> bits) & 255); acc &= (1 << bits)-1; }
  }
  if (out.length !== 93 || acc !== 0) throw new Error('INVALID_SERIAL');
  const raw=Buffer.from(out), p=raw.subarray(0,29), sig=raw.subarray(29);
  const kid=p[1], keyHex=process.env[`ILSON_PUBLIC_KEY_${kid}`] || '';
  if (p[0] !== 1 || !/^[0-9a-f]{64}$/i.test(keyHex) || p.readUInt16BE(18)===0 || ![1,2].includes(p[20])) throw new Error('INVALID_SERIAL');
  const key=crypto.createPublicKey({key:Buffer.concat([Buffer.from('302a300506032b6570032100','hex'),Buffer.from(keyHex,'hex')]),format:'der',type:'spki'});
  if (!crypto.verify(null,Buffer.concat([DOMAIN,p]),key,sig)) throw new Error('INVALID_SERIAL');
  const issued=p.readUInt32BE(21), expires=p.readUInt32BE(25), plan=p[20];
  if ((expires===0xffffffff && plan!==1) || (expires!==0xffffffff && expires<=issued) || issued > Math.floor(Date.now()/1000)+300) throw new Error('INVALID_SERIAL');
  return {id:p.subarray(2,18).toString('hex'),cohort:p.readUInt16BE(18),plan,issued,expires,payload_hash:crypto.createHash('sha256').update(p).digest('hex')};
}
function eqSecret(a,b) {
  if (typeof a !== 'string' || typeof b !== 'string' || !b) return false;
  const x=crypto.createHash('sha256').update(a).digest(), y=crypto.createHash('sha256').update(b).digest();
  return crypto.timingSafeEqual(x,y);
}
async function handler(req,res) {
  res.setHeader('Cache-Control','no-store');
  res.setHeader('Content-Type','application/json');
  if (req.method !== 'POST') return res.status(405).json({error:'METHOD'});
  const action=req.query.action;
  let body=req.body;
  try { if (typeof body==='string') body=JSON.parse(body); } catch { return res.status(400).json({error:'INVALID_REQUEST'}); }
  const skillActions=['skill-share','skill-list','skill-get','skill-withdraw','skill-admin-list','skill-admin-approve','skill-admin-reject','skill-admin-withdraw'];
  if (!body || typeof body!=='object' || Buffer.byteLength(JSON.stringify(body))>(skillActions.includes(action)?131072:8192)) return res.status(400).json({error:'INVALID_REQUEST'});
  const now=Math.floor(Date.now()/1000), nonce=body.nonce;
  if (!/^[a-f0-9]{32}$/.test(nonce || '')) return res.status(400).json({error:'INVALID_REQUEST'});
  const send=(code,status,extra={})=>res.status(code).json({nonce,server_time:now,status,...extra});
  const admin=['register','revoke','renew-payment','release-device','devices'].includes(action);
  const ip=String(req.headers['x-forwarded-for'] || req.socket?.remoteAddress || '').split(',')[0].trim();
  const hash=x=>crypto.createHash('sha256').update(x).digest('hex');
  // Limit invalid credentials too; fail closed when shared rate-limit storage is unavailable.
  try {
    const endpoint=new URL('/rest/v1/rpc/ilson_rate_limit',process.env.SUPABASE_URL);
    if (endpoint.protocol !== 'https:' || !process.env.SUPABASE_SECRET_KEY) throw new Error('configuration');
    const response=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json',apikey:process.env.SUPABASE_SECRET_KEY},body:JSON.stringify({p_bucket:hash('ilson-ip-v1\0'+ip)}),signal:AbortSignal.timeout(5000)});
    if (!response.ok) throw new Error('database');
    if (await response.json() !== true) return send(429,'rate_limited');
  } catch { return send(503,'unavailable'); }
  if (skillActions.includes(action)) {
    const skillAction=action.slice(6), skillAdmin=skillAction.startsWith('admin-');
    if (skillAdmin && !eqSecret(req.headers['x-ilson-admin'],process.env.ILSON_ADMIN_SECRET)) return res.status(403).json({error:'UNAUTHORIZED'});
    if (skillAction==='admin-list' && body.offset!==undefined && (!Number.isSafeInteger(body.offset) || body.offset<0 || body.offset>1000000)) return send(400,'invalid_request');
    let license=null, deviceHash=null;
    if (!skillAdmin) {
      try { license=serialData(body.serial); } catch { return send(400,'invalid_serial'); }
      if (!/^[a-f0-9]{64}$/.test(body.device_id || '')) return send(400,'invalid_serial');
      deviceHash=hash('ilson-device-v1\0'+body.device_id);
    }
    if (skillAction==='share') {
      if (typeof body.name!=='string' || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(body.name) ||
          !body.files || Array.isArray(body.files) || typeof body.files!=='object') return send(400,'invalid_request');
      const entries=Object.entries(body.files);
      if (!Object.hasOwn(body.files,'SKILL.md') || entries.length<1 || entries.length>10 ||
          entries.some(([name,value])=>!/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}\.md$/.test(name) || typeof value!=='string' || /[\x00-\x08\x0b-\x1f\x7f]/.test(value)) ||
          entries.reduce((n,[,value])=>n+Buffer.byteLength(value),0)>48000) return send(400,'invalid_request');
    }
    try {
      const endpoint=new URL('/rest/v1/rpc/ilson_skill_request',process.env.SUPABASE_URL);
      if (endpoint.protocol!=='https:' || !process.env.SUPABASE_SECRET_KEY) throw new Error('configuration');
      const input={action:skillAction,license,device_hash:deviceHash,admin:skillAdmin,
        cohort_only:process.env.ILSON_SKILL_COHORT_ONLY==='true',name:body.name,files:body.files,id:body.id,offset:body.offset};
      const response=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json',apikey:process.env.SUPABASE_SECRET_KEY},body:JSON.stringify({p:input}),signal:AbortSignal.timeout(5000)});
      if (!response.ok) throw new Error('database');
      const result=await response.json();
      if (!result || typeof result.status!=='string') throw new Error('database');
      const code={ok:200,invalid_request:400,invalid_serial:400,revoked:403,expired:403,payment_due:403,forbidden:403,device_not_registered:403,not_found:404,conflict:409,rate_limited:429}[result.status] || 503;
      return send(code,result.status,Object.fromEntries(Object.entries(result).filter(([key])=>key!=='status')));
    } catch { return send(503,'unavailable'); }
  }
  if (!admin && !['activate','check','deactivate'].includes(action)) return send(400,'invalid_serial');
  if (admin && !eqSecret(req.headers['x-ilson-admin'],process.env.ILSON_ADMIN_SECRET)) return res.status(403).json({error:'UNAUTHORIZED'});
  let parsed;
  try { parsed = serialData(body.serial); } catch { return send(400,'invalid_serial'); }
  if ((action === 'renew-payment' || (action === 'register' && parsed.plan === 2)) &&
      (!Number.isSafeInteger(body.paid_until) || body.paid_until <= 0 || body.paid_until >= 0xffffffff)) {
    return send(400,'invalid_serial');
  }
  const device=body.device_id;
  if (!admin && !/^[a-f0-9]{64}$/.test(device || '')) return send(400,'invalid_serial');
  const input={action,license:parsed,device_hash:device ? hash('ilson-device-v1\0'+device) : null,
    ip_hash:hash('ilson-ip-v1\0'+ip), display_name:admin ? body.display_name : null,
    paid_until:admin ? body.paid_until : null, request_id:admin ? body.request_id : null,
    target_device:admin ? body.target_device : null};
  try {
    const endpoint = new URL('/rest/v1/rpc/ilson_license_request', process.env.SUPABASE_URL);
    if (endpoint.protocol !== 'https:' || !process.env.SUPABASE_SECRET_KEY) throw new Error('configuration');
    const response=await fetch(endpoint, {method:'POST',headers:{'Content-Type':'application/json',apikey:process.env.SUPABASE_SECRET_KEY},body:JSON.stringify({p:input}),signal:AbortSignal.timeout(5000)});
    if (!response.ok) throw new Error('database');
    const result=await response.json();
    if (!result || typeof result.status !== 'string') throw new Error('database');
    const code={active:200,ok:200,revoked:403,expired:403,payment_due:403,device_limit:409,device_not_registered:409,invalid_serial:400,rate_limited:429,conflict:409}[result.status] || 503;
    return send(code,result.status,{expires_at:result.expires_at ?? null,paid_until:result.paid_until ?? null,next_check_seconds:86400,...(admin && result.devices ? {devices:result.devices}: {})});
  } catch {
    return send(503,'unavailable');
  }
}
module.exports=handler;
module.exports.serialData=serialData;
