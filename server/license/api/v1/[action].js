'use strict';
const crypto = require('node:crypto');
const DOMAIN = Buffer.from('ILSON-LICENSE-V1\0');
const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
const SHORT_RE = /^IL2[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{12}$/;
const HEX32_RE = /^[a-f0-9]{32}$/;
const CLIENT_VER_RE = /^[A-Za-z0-9._-]{1,32}$/;
const NUM_VER_RE = /^(unknown|[0-9]{1,6}(\.[0-9]{1,6}){0,3})$/;
const STEP_ID_RE = /^(bootstrap\.start|download\.installer|preflight\.(platform|arch)|runtime\.(python|node)|tools\.(brew|git|jq|gh|coreutils|python|node|claude|codex|aside|herdr|hc|tvly|vendor)(\.(download|execute))?|apps\.(orca|obsidian|tailscale|aside|herdr)|kit\.prepare|vault\.prepare|helper\.install|cli\.link|path\.persist|verify\.(absolute|current|new-window|simulated)|setup\.(stage|machine|jobs|web|telegram|auth-pending)|finish)$/;
const REASON_CODES = new Set(['STARTED','OK','REUSED_VERIFIED','DEPENDENCY_FAILED','PYTHON_TOO_OLD','RUNTIME_MISSING','WRONG_INSTALLER','UNSUPPORTED_OS','SMART_DASH','UNKNOWN_OPTION','COMMAND_CONFLICT','OUTSIDE_VAULT','DNS_FAILED','HTTP_FAILED','TIMEOUT','TLS_FAILED','DOWNLOAD_FAILED','EXECUTE_FAILED','VERIFY_FAILED','HASH_MISMATCH','USER_MODIFIED','PATH_MANUAL','AUTH_PENDING','USER_CONFIRMATION_REQUIRED','USER_DECLARED','DRY_RUN','NOT_APPLICABLE','NOT_SELECTED','INTERRUPTED','LOG_UNAVAILABLE','DETAIL_SUPPRESSED','CLOCK_UNVERIFIED']);
const TELEMETRY_EDITIONS = new Set(['windows-course','intel-course','mac-box']);
const CLIENT_EDITIONS = new Set(['windows-course','intel-course','mac-box','unknown']);
const OS_VALUES = new Set(['Windows','macOS','Linux','unknown']);
const ARCH_VALUES = new Set(['AMD64','arm64','x86_64','unknown']);
const SHELL_VALUES = new Set(['powershell','bash','zsh','unknown']);
const HELPER_STATUSES = new Set(['INSTALLED','UPDATED','UP_TO_DATE']);
const TELEMETRY_KEYS = new Set(['nonce','run_id','edition','os','arch','os_version','shell','shell_version','installer_version','result','exit_code','failed_steps','helper_status']);

function sanitizeClientMeta(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const meta = {};
  if (typeof raw.os === 'string' && OS_VALUES.has(raw.os)) meta.os = raw.os;
  if (typeof raw.arch === 'string' && ARCH_VALUES.has(raw.arch)) meta.arch = raw.arch;
  if (typeof raw.edition === 'string' && CLIENT_EDITIONS.has(raw.edition)) meta.edition = raw.edition;
  if (typeof raw.client_version === 'string' && CLIENT_VER_RE.test(raw.client_version)) meta.client_version = raw.client_version;
  if (typeof raw.run_id === 'string' && HEX32_RE.test(raw.run_id)) meta.run_id = raw.run_id;
  return Object.keys(meta).length ? meta : null;
}

function validateTelemetry(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) return null;
  for (const key of Object.keys(body)) {
    if (!TELEMETRY_KEYS.has(key)) return null;
  }
  if (typeof body.run_id !== 'string' || !HEX32_RE.test(body.run_id)) return null;
  if (typeof body.edition !== 'string' || !TELEMETRY_EDITIONS.has(body.edition)) return null;
  if (typeof body.os !== 'string' || !OS_VALUES.has(body.os)) return null;
  if (typeof body.arch !== 'string' || !ARCH_VALUES.has(body.arch)) return null;
  let osVersion = 'unknown';
  if (body.os_version !== undefined && body.os_version !== null) {
    if (typeof body.os_version !== 'string' || !NUM_VER_RE.test(body.os_version)) return null;
    osVersion = body.os_version;
  }
  let shell = 'unknown';
  if (body.shell !== undefined && body.shell !== null) {
    if (typeof body.shell !== 'string' || !SHELL_VALUES.has(body.shell)) return null;
    shell = body.shell;
  }
  let shellVersion = 'unknown';
  if (body.shell_version !== undefined && body.shell_version !== null) {
    if (typeof body.shell_version !== 'string' || !NUM_VER_RE.test(body.shell_version)) return null;
    shellVersion = body.shell_version;
  }
  if (typeof body.installer_version !== 'string' || !CLIENT_VER_RE.test(body.installer_version)) return null;
  if (body.result !== 'ok' && body.result !== 'failed') return null;
  let exitCode = null;
  if (body.exit_code !== undefined && body.exit_code !== null) {
    if (!Number.isSafeInteger(body.exit_code) || body.exit_code < -999999 || body.exit_code > 999999) return null;
    exitCode = body.exit_code;
  }
  let helperStatus = null;
  if (body.helper_status !== undefined && body.helper_status !== null) {
    if (typeof body.helper_status !== 'string' || !HELPER_STATUSES.has(body.helper_status)) return null;
    helperStatus = body.helper_status;
  }
  const failedSteps = [];
  if (body.failed_steps !== undefined && body.failed_steps !== null) {
    if (!Array.isArray(body.failed_steps) || body.failed_steps.length > 20) return null;
    for (const item of body.failed_steps) {
      if (!item || typeof item !== 'object' || Array.isArray(item)) return null;
      for (const k of Object.keys(item)) {
        if (k !== 'step_id' && k !== 'reason_code' && k !== 'http_code') return null;
      }
      if (typeof item.step_id !== 'string' || !STEP_ID_RE.test(item.step_id)) return null;
      if (typeof item.reason_code !== 'string' || !REASON_CODES.has(item.reason_code)) return null;
      const clean = { step_id: item.step_id, reason_code: item.reason_code };
      if (item.http_code !== undefined && item.http_code !== null) {
        if (!Number.isSafeInteger(item.http_code) || item.http_code < 100 || item.http_code > 599) return null;
        clean.http_code = item.http_code;
      }
      failedSteps.push(clean);
    }
  }
  return {
    run_id: body.run_id,
    edition: body.edition,
    os: body.os,
    arch: body.arch,
    os_version: osVersion,
    shell,
    shell_version: shellVersion,
    installer_version: body.installer_version,
    result: body.result,
    exit_code: exitCode,
    failed_steps: failedSteps,
    helper_status: helperStatus
  };
}

function cleanShortSerial(value) {
  if (typeof value !== 'string' || value.length > 512) return null;
  const clean = value.replace(/[ \t\r\n\f\v-]/g, '').toUpperCase();
  return SHORT_RE.test(clean) ? clean : null;
}

function isShortSerial(value) {
  return cleanShortSerial(value) !== null;
}

function shortCodeHash(value) {
  const clean = cleanShortSerial(value);
  if (!clean) throw new Error('INVALID_SERIAL');
  const body = clean.slice(3);
  const canonical = `IL2-${body.slice(0, 4)}-${body.slice(4, 8)}-${body.slice(8, 12)}`;
  return crypto.createHash('sha256').update(Buffer.concat([Buffer.from('ilson-short-v2\0'), Buffer.from(canonical, 'ascii')])).digest('hex');
}

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
  if (action === 'install-telemetry') {
    const telemetry = validateTelemetry(body);
    if (!telemetry) return send(400, 'invalid_request');
    try {
      const endpoint = new URL('/rest/v1/rpc/ilson_install_telemetry', process.env.SUPABASE_URL);
      if (endpoint.protocol !== 'https:' || !process.env.SUPABASE_SECRET_KEY) throw new Error('configuration');
      const input = { ...telemetry, ip_hash: hash('ilson-ip-v1\0' + ip) };
      const response = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json', apikey: process.env.SUPABASE_SECRET_KEY }, body: JSON.stringify({ p: input }), signal: AbortSignal.timeout(5000) });
      if (!response.ok) throw new Error('database');
      const result = await response.json();
      if (!result || typeof result.status !== 'string') throw new Error('database');
      const code = { ok: 200, invalid_request: 400, rate_limited: 429 }[result.status] || 503;
      return send(code, result.status);
    } catch { return send(503, 'unavailable'); }
  }
  if (action === 'admin-overview') {
    if (!eqSecret(req.headers['x-ilson-admin'], process.env.ILSON_ADMIN_SECRET)) return res.status(403).json({ error: 'UNAUTHORIZED' });
    const input = {};
    if (body.cohort !== undefined && body.cohort !== null) {
      if (!Number.isSafeInteger(body.cohort) || body.cohort < 1 || body.cohort > 65535) return send(400, 'invalid_request');
      input.cohort = body.cohort;
    }
    try {
      const endpoint = new URL('/rest/v1/rpc/ilson_admin_overview', process.env.SUPABASE_URL);
      if (endpoint.protocol !== 'https:' || !process.env.SUPABASE_SECRET_KEY) throw new Error('configuration');
      const response = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json', apikey: process.env.SUPABASE_SECRET_KEY }, body: JSON.stringify({ p: input }), signal: AbortSignal.timeout(8000) });
      if (!response.ok) throw new Error('database');
      const result = await response.json();
      if (!result || typeof result.status !== 'string') throw new Error('database');
      const code = { ok: 200, invalid_request: 400 }[result.status] || 503;
      return send(code, result.status, Object.fromEntries(Object.entries(result).filter(([key]) => key !== 'status')));
    } catch { return send(503, 'unavailable'); }
  }
  if (!admin && !['activate','check','deactivate'].includes(action)) return send(400,'invalid_serial');
  if (admin && !eqSecret(req.headers['x-ilson-admin'],process.env.ILSON_ADMIN_SECRET)) return res.status(403).json({error:'UNAUTHORIZED'});
  const shortActivate = action === 'activate' && isShortSerial(body.serial);
  const clientMeta = (action === 'activate' || action === 'check') ? sanitizeClientMeta(body.client_meta) : null;
  let input;
  if (shortActivate) {
    const device = body.device_id;
    if (!/^[a-f0-9]{64}$/.test(device || '')) return send(400,'invalid_serial');
    let shortHash;
    try { shortHash = shortCodeHash(body.serial); } catch { return send(400,'invalid_serial'); }
    input = {
      action: 'activate',
      short_code_hash: shortHash,
      device_hash: hash('ilson-device-v1\0'+device),
      ip_hash: hash('ilson-ip-v1\0'+ip),
      ...(clientMeta ? {client_meta: clientMeta} : {})
    };
  } else {
    let parsed;
    try { parsed = serialData(body.serial); } catch { return send(400,'invalid_serial'); }
    if ((action === 'renew-payment' || (action === 'register' && parsed.plan === 2)) &&
        (!Number.isSafeInteger(body.paid_until) || body.paid_until <= 0 || body.paid_until >= 0xffffffff)) {
      return send(400,'invalid_serial');
    }
    const hasShort = body.short_code_hash !== undefined && body.short_code_hash !== null;
    const hasSealed = body.sealed_serial !== undefined && body.sealed_serial !== null;
    if (action === 'register') {
      if (hasShort !== hasSealed) return send(400,'invalid_serial');
      if (hasShort && (typeof body.short_code_hash !== 'string' || !/^[a-f0-9]{64}$/.test(body.short_code_hash) ||
          typeof body.sealed_serial !== 'string' || !/^[A-Za-z0-9_-]{188}$/.test(body.sealed_serial))) {
        return send(400,'invalid_serial');
      }
    }
    const device=body.device_id;
    if (!admin && !/^[a-f0-9]{64}$/.test(device || '')) return send(400,'invalid_serial');
    input={action,license:parsed,device_hash:device ? hash('ilson-device-v1\0'+device) : null,
      ip_hash:hash('ilson-ip-v1\0'+ip), display_name:admin ? body.display_name : null,
      paid_until:admin ? body.paid_until : null, request_id:admin ? body.request_id : null,
      target_device:admin ? body.target_device : null,
      ...(clientMeta ? {client_meta: clientMeta} : {}),
      ...(action === 'register' && hasShort ? {short_code_hash: body.short_code_hash, sealed_serial: body.sealed_serial} : {})};
  }
  try {
    const endpoint = new URL('/rest/v1/rpc/ilson_license_request', process.env.SUPABASE_URL);
    if (endpoint.protocol !== 'https:' || !process.env.SUPABASE_SECRET_KEY) throw new Error('configuration');
    const response=await fetch(endpoint, {method:'POST',headers:{'Content-Type':'application/json',apikey:process.env.SUPABASE_SECRET_KEY},body:JSON.stringify({p:input}),signal:AbortSignal.timeout(5000)});
    if (!response.ok) throw new Error('database');
    const result=await response.json();
    if (!result || typeof result.status !== 'string') throw new Error('database');
    const code={active:200,ok:200,revoked:403,expired:403,payment_due:403,device_limit:409,device_not_registered:409,invalid_serial:400,rate_limited:429,conflict:409}[result.status] || 503;
    return send(code,result.status,{expires_at:result.expires_at ?? null,paid_until:result.paid_until ?? null,next_check_seconds:86400,
      ...(shortActivate && result.status === 'active' && typeof result.sealed_serial === 'string' ? {sealed_serial: result.sealed_serial} : {}),
      ...(admin && result.devices ? {devices:result.devices}: {})});
  } catch {
    return send(503,'unavailable');
  }
}
module.exports=handler;
module.exports.serialData=serialData;
module.exports.shortCodeHash=shortCodeHash;
