-- Additive Full Install Tracking migration; compatible with 001_license.sql, 002_skill_share.sql, and 003_short_serial.sql.
begin;

alter table license_private.devices
  add column if not exists os text check (os in ('Windows','macOS','Linux','unknown')),
  add column if not exists arch text check (arch in ('AMD64','arm64','x86_64','unknown')),
  add column if not exists edition text check (edition in ('windows-course','intel-course','mac-box','unknown')),
  add column if not exists client_version text check (client_version ~ '^[A-Za-z0-9._-]{1,32}$');

create table if not exists license_private.install_runs (
  run_id text primary key check (run_id ~ '^[a-f0-9]{32}$'),
  edition text not null check (edition in ('windows-course','intel-course','mac-box')),
  os text not null check (os in ('Windows','macOS','Linux','unknown')),
  arch text not null check (arch in ('AMD64','arm64','x86_64','unknown')),
  os_version text not null default 'unknown' check (os_version ~ '^(unknown|[0-9]{1,6}(\.[0-9]{1,6}){0,3})$'),
  shell text not null default 'unknown' check (shell in ('powershell','bash','zsh','unknown')),
  shell_version text not null default 'unknown' check (shell_version ~ '^(unknown|[0-9]{1,6}(\.[0-9]{1,6}){0,3})$'),
  installer_version text not null check (installer_version ~ '^[A-Za-z0-9._-]{1,32}$'),
  result text not null check (result in ('ok','failed')),
  exit_code integer,
  failed_steps jsonb not null default '[]'::jsonb check (jsonb_typeof(failed_steps) = 'array' and jsonb_array_length(failed_steps) <= 20),
  helper_status text check (helper_status in ('INSTALLED','UPDATED','UP_TO_DATE')),
  license_id text references license_private.licenses(id) on delete set null,
  ip_hash text not null check (ip_hash ~ '^[a-f0-9]{64}$'),
  created_at bigint not null,
  updated_at bigint not null
);

alter table license_private.install_runs enable row level security;
revoke all on license_private.install_runs from public, anon, authenticated;

create index if not exists install_runs_created_at_idx on license_private.install_runs(created_at desc);
create index if not exists install_runs_license_id_idx on license_private.install_runs(license_id);

create or replace function public.ilson_license_request(p jsonb) returns jsonb
language plpgsql security definer set search_path = pg_catalog, license_private as $$
declare
 item license_private.licenses%rowtype; dev license_private.devices%rowtype;
 act text := p->>'action'; lic jsonb := p->'license'; ident text := lic->>'id';
 sch text := p->>'short_code_hash'; sealed text := p->>'sealed_serial'; v_id text;
 now_s bigint := floor(extract(epoch from clock_timestamp())); window_s bigint; hits integer;
 request_hash text; event_row license_private.events%rowtype; result text; count_devices integer;
 meta jsonb := p->'client_meta';
 v_os text := null; v_arch text := null; v_edition text := null; v_client_version text := null; v_run_id text := null;
begin
 if act not in ('activate','check','deactivate','register','revoke','renew-payment','release-device','devices') then return jsonb_build_object('status','invalid_serial'); end if;
 if coalesce(p->>'ip_hash','') !~ '^[a-f0-9]{64}$' then return jsonb_build_object('status','invalid_serial'); end if;
 window_s := now_s / 60;
 if now_s % 300 = 0 then
   delete from license_private.rate_limits where window_start < window_s - 1440;
 end if;

 -- Strictly parse optional client_meta; invalid fields are silently ignored so activation never breaks.
 if act in ('activate','check') and jsonb_typeof(meta) = 'object' then
   if jsonb_typeof(meta->'os') = 'string' and (meta->>'os') in ('Windows','macOS','Linux','unknown') then
     v_os := meta->>'os';
   end if;
   if jsonb_typeof(meta->'arch') = 'string' and (meta->>'arch') in ('AMD64','arm64','x86_64','unknown') then
     v_arch := meta->>'arch';
   end if;
   if jsonb_typeof(meta->'edition') = 'string' and (meta->>'edition') in ('windows-course','intel-course','mac-box','unknown') then
     v_edition := meta->>'edition';
   end if;
   if jsonb_typeof(meta->'client_version') = 'string' and (meta->>'client_version') ~ '^[A-Za-z0-9._-]{1,32}$' then
     v_client_version := meta->>'client_version';
   end if;
   if jsonb_typeof(meta->'run_id') = 'string' and (meta->>'run_id') ~ '^[a-f0-9]{32}$' then
     v_run_id := meta->>'run_id';
   end if;
 end if;

 -- V2 short serial activation: unlocked short_code_hash lookup first, then rate_limits in V1 lock order before FOR UPDATE (prevents AB-BA deadlocks).
 if act = 'activate' and (p ? 'short_code_hash') and (lic is null or jsonb_typeof(lic) = 'null') then
   if coalesce(sch,'') !~ '^[a-f0-9]{64}$' or coalesce(p->>'device_hash','') !~ '^[a-f0-9]{64}$' then
     return jsonb_build_object('status','invalid_serial');
   end if;
   for result in select unnest(array['ip:'||(p->>'ip_hash'),'short:'||sch]) loop
     insert into license_private.rate_limits(bucket,window_start,hits) values(result,window_s,1)
     on conflict(bucket,window_start) do update set hits=license_private.rate_limits.hits+1 returning license_private.rate_limits.hits into hits;
     if hits > 60 then return jsonb_build_object('status','rate_limited'); end if;
   end loop;
   select id into v_id from license_private.licenses where short_code_hash = sch;
   if not found then
     return jsonb_build_object('status','invalid_serial');
   end if;
   insert into license_private.rate_limits(bucket,window_start,hits) values('license:'||v_id,window_s,1)
   on conflict(bucket,window_start) do update set hits=license_private.rate_limits.hits+1 returning license_private.rate_limits.hits into hits;
   if hits > 60 then return jsonb_build_object('status','rate_limited'); end if;
   select * into item from license_private.licenses where id = v_id and short_code_hash = sch for update;
   if not found or item.sealed_serial is null then
     return jsonb_build_object('status','invalid_serial');
   end if;
   if item.status='revoked' then return jsonb_build_object('status','revoked'); end if;
   if item.expires is not null and now_s >= item.expires then return jsonb_build_object('status','expired'); end if;
   if item.plan=2 and now_s >= item.paid_until then return jsonb_build_object('status','payment_due'); end if;
   select * into dev from license_private.devices where license_id=item.id and device_hash=p->>'device_hash';
   if not found or dev.released_at is not null then
     select count(*) into count_devices from license_private.devices where license_id=item.id and released_at is null;
     if count_devices >= item.device_limit then return jsonb_build_object('status','device_limit'); end if;
     insert into license_private.devices(license_id,device_hash,activated_at,last_seen_at,released_at,os,arch,edition,client_version)
     values(item.id,p->>'device_hash',now_s,now_s,null,v_os,v_arch,v_edition,v_client_version)
     on conflict(license_id,device_hash) do update set
       activated_at=now_s,
       last_seen_at=now_s,
       released_at=null,
       os=coalesce(v_os,license_private.devices.os),
       arch=coalesce(v_arch,license_private.devices.arch),
       edition=coalesce(v_edition,license_private.devices.edition),
       client_version=coalesce(v_client_version,license_private.devices.client_version);
   else
     update license_private.devices set
       last_seen_at=now_s,
       os=coalesce(v_os,os),
       arch=coalesce(v_arch,arch),
       edition=coalesce(v_edition,edition),
       client_version=coalesce(v_client_version,client_version)
     where license_id=item.id and device_hash=p->>'device_hash';
   end if;
   if v_run_id is not null then
     update license_private.install_runs
     set license_id = item.id, updated_at = now_s
     where run_id = v_run_id and license_id is null;
   end if;
   return jsonb_build_object('status','active','expires_at',item.expires,'paid_until',item.paid_until,'sealed_serial',item.sealed_serial);
 end if;

 if coalesce(ident,'') !~ '^[a-f0-9]{32}$' then return jsonb_build_object('status','invalid_serial'); end if;
 for result in select unnest(array['ip:'||(p->>'ip_hash'),'license:'||ident]) loop
   insert into license_private.rate_limits(bucket,window_start,hits) values(result,window_s,1)
   on conflict(bucket,window_start) do update set hits=license_private.rate_limits.hits+1 returning license_private.rate_limits.hits into hits;
   if hits > 60 then return jsonb_build_object('status','rate_limited'); end if;
 end loop;
 if act in ('register','revoke','renew-payment','release-device','devices') then
   if coalesce(p->>'request_id','') !~ '^[a-f0-9]{32}$' then return jsonb_build_object('status','invalid_serial'); end if;
   request_hash := md5((p - 'ip_hash')::text);
   select * into event_row from license_private.events where request_id=p->>'request_id';
   if found then
     if event_row.payload_hash <> request_hash then return jsonb_build_object('status','conflict'); end if;
     return jsonb_build_object('status','ok');
   end if;
 end if;
 if (act='renew-payment' or (act='register' and lic->>'plan'='2')) and
    (jsonb_typeof(p->'paid_until') is distinct from 'number' or
     coalesce(p->>'paid_until','') !~ '^[0-9]{1,10}$') then
   return jsonb_build_object('status','conflict');
 end if;
 if act='renew-payment' or (act='register' and lic->>'plan'='2') then
   if (p->>'paid_until')::bigint <= 0 or (p->>'paid_until')::bigint >= 4294967295 then
     return jsonb_build_object('status','conflict');
   end if;
 end if;
 if act='register' then
   if coalesce(p->>'display_name','')='' then return jsonb_build_object('status','invalid_serial'); end if;
   if (p ? 'short_code_hash' and jsonb_typeof(p->'short_code_hash') not in ('null','string')) or
      (p ? 'sealed_serial' and jsonb_typeof(p->'sealed_serial') not in ('null','string')) then
     return jsonb_build_object('status','invalid_serial');
   end if;
   if (sch is null) <> (sealed is null) then return jsonb_build_object('status','invalid_serial'); end if;
   if sch is not null and (sch !~ '^[a-f0-9]{64}$' or sealed !~ '^[A-Za-z0-9_-]{188}$') then
     return jsonb_build_object('status','invalid_serial');
   end if;
   if sch is not null and exists(select 1 from license_private.licenses where short_code_hash = sch and id <> ident) then
     return jsonb_build_object('status','conflict');
   end if;
   begin
     insert into license_private.licenses(id,payload_hash,display_name,cohort,plan,issued,expires,paid_until,short_code_hash,sealed_serial)
     values(ident,lic->>'payload_hash',p->>'display_name',(lic->>'cohort')::integer,(lic->>'plan')::integer,(lic->>'issued')::bigint,
       case when (lic->>'expires')::bigint=4294967295 then null else (lic->>'expires')::bigint end,
       case when (lic->>'plan')::integer=2 then (p->>'paid_until')::bigint else null end,
       sch, sealed)
     on conflict(id) do nothing;
   exception when unique_violation then
     return jsonb_build_object('status','conflict');
   end;
 end if;
 select * into item from license_private.licenses where id=ident for update;
 if not found or item.payload_hash <> lic->>'payload_hash' then return jsonb_build_object('status','invalid_serial'); end if;
 if act='register' then
   if item.display_name <> p->>'display_name'
      or item.short_code_hash is distinct from sch
      or item.sealed_serial is distinct from sealed then
     return jsonb_build_object('status','conflict');
   end if;
 elsif act='revoke' then
   update license_private.licenses set status='revoked',revoked_at=coalesce(revoked_at,now_s) where id=ident;
 elsif act='renew-payment' then
   if item.plan <> 2 or (p->>'paid_until')::bigint <= item.paid_until or (p->>'paid_until')::bigint >= 4294967295 then return jsonb_build_object('status','conflict'); end if;
   update license_private.licenses set paid_until=(p->>'paid_until')::bigint where id=ident;
 elsif act='release-device' then
   update license_private.devices set released_at=now_s where license_id=ident and device_hash=p->>'target_device' and released_at is null;
 elsif act='devices' then
   return jsonb_build_object('status','ok','devices',coalesce((select jsonb_agg(jsonb_build_object('device_hash',device_hash,'activated_at',activated_at,'released_at',released_at)) from license_private.devices where license_id=ident),'[]'::jsonb));
 elsif act='deactivate' then
   update license_private.devices set released_at=now_s where license_id=ident and device_hash=p->>'device_hash' and released_at is null;
   return jsonb_build_object('status','active');
 else
   if item.status='revoked' then return jsonb_build_object('status','revoked'); end if;
   if item.expires is not null and now_s >= item.expires then return jsonb_build_object('status','expired'); end if;
   if item.plan=2 and now_s >= item.paid_until then return jsonb_build_object('status','payment_due'); end if;
   select * into dev from license_private.devices where license_id=ident and device_hash=p->>'device_hash';
   if act='check' and (not found or dev.released_at is not null) then return jsonb_build_object('status','device_not_registered'); end if;
   if act='activate' and (not found or dev.released_at is not null) then
     select count(*) into count_devices from license_private.devices where license_id=ident and released_at is null;
     if count_devices >= item.device_limit then return jsonb_build_object('status','device_limit'); end if;
     insert into license_private.devices(license_id,device_hash,activated_at,last_seen_at,released_at,os,arch,edition,client_version)
     values(ident,p->>'device_hash',now_s,now_s,null,v_os,v_arch,v_edition,v_client_version)
     on conflict(license_id,device_hash) do update set
       activated_at=now_s,
       last_seen_at=now_s,
       released_at=null,
       os=coalesce(v_os,license_private.devices.os),
       arch=coalesce(v_arch,license_private.devices.arch),
       edition=coalesce(v_edition,license_private.devices.edition),
       client_version=coalesce(v_client_version,license_private.devices.client_version);
   else
     update license_private.devices set
       last_seen_at=now_s,
       os=coalesce(v_os,os),
       arch=coalesce(v_arch,arch),
       edition=coalesce(v_edition,edition),
       client_version=coalesce(v_client_version,client_version)
     where license_id=ident and device_hash=p->>'device_hash';
   end if;
   if v_run_id is not null then
     update license_private.install_runs
     set license_id = item.id, updated_at = now_s
     where run_id = v_run_id and license_id is null;
   end if;
   return jsonb_build_object('status','active','expires_at',item.expires,'paid_until',item.paid_until);
 end if;
 insert into license_private.events(request_id,license_id,action,payload_hash,occurred_at) values(p->>'request_id',ident,act,request_hash,now_s);
 return jsonb_build_object('status','ok');
end $$;
revoke all on function public.ilson_license_request(jsonb) from public, anon, authenticated;
grant execute on function public.ilson_license_request(jsonb) to service_role;

create or replace function public.ilson_install_telemetry(p jsonb) returns jsonb
language plpgsql security definer set search_path = pg_catalog, license_private as $$
declare
 now_s bigint := floor(extract(epoch from clock_timestamp()));
 window_s bigint := now_s / 60;
 hits integer;
 v_ip_hash text;
 v_run_id text;
 v_edition text;
 v_os text;
 v_arch text;
 v_os_version text := 'unknown';
 v_shell text := 'unknown';
 v_shell_version text := 'unknown';
 v_installer_version text;
 v_result text;
 v_exit_code integer := null;
 v_helper_status text := null;
 v_failed_steps jsonb := '[]'::jsonb;
 elem jsonb;
 clean_elem jsonb;
 v_step text;
 v_reason text;
 v_http integer;
 k text;
begin
 if jsonb_typeof(p) is distinct from 'object' then
   return jsonb_build_object('status','invalid_request');
 end if;
 if jsonb_typeof(p->'ip_hash') is distinct from 'string' or coalesce(p->>'ip_hash','') !~ '^[a-f0-9]{64}$' then
   return jsonb_build_object('status','invalid_request');
 end if;
 v_ip_hash := p->>'ip_hash';

 insert into license_private.rate_limits(bucket,window_start,hits)
 values('telemetry:'||v_ip_hash, window_s, 1)
 on conflict(bucket,window_start) do update set hits=license_private.rate_limits.hits+1
 returning license_private.rate_limits.hits into hits;
 if hits > 60 then
   return jsonb_build_object('status','rate_limited');
 end if;

 if jsonb_typeof(p->'run_id') is distinct from 'string' or (p->>'run_id') !~ '^[a-f0-9]{32}$' then
   return jsonb_build_object('status','invalid_request');
 end if;
 v_run_id := p->>'run_id';

 if jsonb_typeof(p->'edition') is distinct from 'string' or (p->>'edition') not in ('windows-course','intel-course','mac-box') then
   return jsonb_build_object('status','invalid_request');
 end if;
 v_edition := p->>'edition';

 if jsonb_typeof(p->'os') is distinct from 'string' or (p->>'os') not in ('Windows','macOS','Linux','unknown') then
   return jsonb_build_object('status','invalid_request');
 end if;
 v_os := p->>'os';

 if jsonb_typeof(p->'arch') is distinct from 'string' or (p->>'arch') not in ('AMD64','arm64','x86_64','unknown') then
   return jsonb_build_object('status','invalid_request');
 end if;
 v_arch := p->>'arch';

 if p ? 'os_version' and jsonb_typeof(p->'os_version') <> 'null' then
   if jsonb_typeof(p->'os_version') is distinct from 'string' or (p->>'os_version') !~ '^(unknown|[0-9]{1,6}(\.[0-9]{1,6}){0,3})$' then
     return jsonb_build_object('status','invalid_request');
   end if;
   v_os_version := p->>'os_version';
 end if;

 if p ? 'shell' and jsonb_typeof(p->'shell') <> 'null' then
   if jsonb_typeof(p->'shell') is distinct from 'string' or (p->>'shell') not in ('powershell','bash','zsh','unknown') then
     return jsonb_build_object('status','invalid_request');
   end if;
   v_shell := p->>'shell';
 end if;

 if p ? 'shell_version' and jsonb_typeof(p->'shell_version') <> 'null' then
   if jsonb_typeof(p->'shell_version') is distinct from 'string' or (p->>'shell_version') !~ '^(unknown|[0-9]{1,6}(\.[0-9]{1,6}){0,3})$' then
     return jsonb_build_object('status','invalid_request');
   end if;
   v_shell_version := p->>'shell_version';
 end if;

 if jsonb_typeof(p->'installer_version') is distinct from 'string' or (p->>'installer_version') !~ '^[A-Za-z0-9._-]{1,32}$' then
   return jsonb_build_object('status','invalid_request');
 end if;
 v_installer_version := p->>'installer_version';

 if jsonb_typeof(p->'result') is distinct from 'string' or (p->>'result') not in ('ok','failed') then
   return jsonb_build_object('status','invalid_request');
 end if;
 v_result := p->>'result';

 if p ? 'exit_code' and jsonb_typeof(p->'exit_code') <> 'null' then
   if jsonb_typeof(p->'exit_code') is distinct from 'number' or (p->>'exit_code') !~ '^-?[0-9]{1,6}$' then
     return jsonb_build_object('status','invalid_request');
   end if;
   v_exit_code := (p->>'exit_code')::integer;
 end if;

 if p ? 'helper_status' and jsonb_typeof(p->'helper_status') <> 'null' then
   if jsonb_typeof(p->'helper_status') is distinct from 'string' or (p->>'helper_status') not in ('INSTALLED','UPDATED','UP_TO_DATE') then
     return jsonb_build_object('status','invalid_request');
   end if;
   v_helper_status := p->>'helper_status';
 end if;

 if p ? 'failed_steps' and jsonb_typeof(p->'failed_steps') <> 'null' then
   if jsonb_typeof(p->'failed_steps') is distinct from 'array' or jsonb_array_length(p->'failed_steps') > 20 then
     return jsonb_build_object('status','invalid_request');
   end if;
   for elem in select value from jsonb_array_elements(p->'failed_steps') loop
     if jsonb_typeof(elem) is distinct from 'object' then
       return jsonb_build_object('status','invalid_request');
     end if;
     for k in select key from jsonb_object_keys(elem) as t(key) loop
       if k not in ('step_id','reason_code','http_code') then
         return jsonb_build_object('status','invalid_request');
       end if;
     end loop;
     if jsonb_typeof(elem->'step_id') is distinct from 'string' or
        (elem->>'step_id') !~ '^(bootstrap\.start|download\.installer|preflight\.(platform|arch)|runtime\.(python|node)|tools\.(brew|git|jq|gh|coreutils|python|node|claude|codex|aside|herdr|hc|tvly|vendor)(\.(download|execute))?|apps\.(orca|obsidian|tailscale|aside|herdr)|kit\.prepare|vault\.prepare|helper\.install|cli\.link|path\.persist|verify\.(absolute|current|new-window|simulated)|setup\.(stage|machine|jobs|web|telegram|auth-pending)|finish)$' then
       return jsonb_build_object('status','invalid_request');
     end if;
     if jsonb_typeof(elem->'reason_code') is distinct from 'string' or
        (elem->>'reason_code') not in ('STARTED','OK','REUSED_VERIFIED','DEPENDENCY_FAILED','PYTHON_TOO_OLD','RUNTIME_MISSING','WRONG_INSTALLER','UNSUPPORTED_OS','SMART_DASH','UNKNOWN_OPTION','COMMAND_CONFLICT','OUTSIDE_VAULT','DNS_FAILED','HTTP_FAILED','TIMEOUT','TLS_FAILED','DOWNLOAD_FAILED','EXECUTE_FAILED','VERIFY_FAILED','HASH_MISMATCH','USER_MODIFIED','PATH_MANUAL','AUTH_PENDING','USER_CONFIRMATION_REQUIRED','USER_DECLARED','DRY_RUN','NOT_APPLICABLE','NOT_SELECTED','INTERRUPTED','LOG_UNAVAILABLE','DETAIL_SUPPRESSED','CLOCK_UNVERIFIED') then
       return jsonb_build_object('status','invalid_request');
     end if;
     v_step := elem->>'step_id';
     v_reason := elem->>'reason_code';
     v_http := null;
     if elem ? 'http_code' and jsonb_typeof(elem->'http_code') <> 'null' then
       if jsonb_typeof(elem->'http_code') is distinct from 'number' or (elem->>'http_code') !~ '^[1-5][0-9]{2}$' then
         return jsonb_build_object('status','invalid_request');
       end if;
       v_http := (elem->>'http_code')::integer;
     end if;
     if v_http is null then
       clean_elem := jsonb_build_object('step_id', v_step, 'reason_code', v_reason);
     else
       clean_elem := jsonb_build_object('step_id', v_step, 'reason_code', v_reason, 'http_code', v_http);
     end if;
     v_failed_steps := v_failed_steps || jsonb_build_array(clean_elem);
   end loop;
 end if;

 insert into license_private.install_runs(
   run_id, edition, os, arch, os_version, shell, shell_version,
   installer_version, result, exit_code, failed_steps, helper_status,
   ip_hash, created_at, updated_at
 ) values (
   v_run_id, v_edition, v_os, v_arch, v_os_version, v_shell, v_shell_version,
   v_installer_version, v_result, v_exit_code, v_failed_steps, v_helper_status,
   v_ip_hash, now_s, now_s
 )
 on conflict(run_id) do update set
   edition = excluded.edition,
   os = excluded.os,
   arch = excluded.arch,
   os_version = excluded.os_version,
   shell = excluded.shell,
   shell_version = excluded.shell_version,
   installer_version = excluded.installer_version,
   result = excluded.result,
   exit_code = excluded.exit_code,
   failed_steps = excluded.failed_steps,
   helper_status = coalesce(excluded.helper_status, license_private.install_runs.helper_status),
   updated_at = now_s;

 if now_s % 300 = 0 then
   delete from license_private.install_runs where created_at < now_s - 15552000;
 end if;

 return jsonb_build_object('status','ok');
end $$;
revoke all on function public.ilson_install_telemetry(jsonb) from public, anon, authenticated;
grant execute on function public.ilson_install_telemetry(jsonb) to service_role;

create or replace function public.ilson_admin_overview(p jsonb) returns jsonb
language plpgsql security definer set search_path = pg_catalog, license_private as $$
declare
 now_s bigint := floor(extract(epoch from clock_timestamp()));
 v_cohort integer := null;
 v_summary jsonb;
 v_cohorts jsonb;
 v_licenses jsonb;
 v_runs jsonb;
 v_failures jsonb;
begin
 if p is not null and jsonb_typeof(p) = 'object' and (p ? 'cohort') and jsonb_typeof(p->'cohort') <> 'null' then
   if jsonb_typeof(p->'cohort') is distinct from 'number' or (p->>'cohort') !~ '^[0-9]{1,5}$' then
     return jsonb_build_object('status','invalid_request');
   end if;
   v_cohort := (p->>'cohort')::integer;
   if v_cohort < 1 or v_cohort > 65535 then
     return jsonb_build_object('status','invalid_request');
   end if;
 end if;

 with lic_stats as (
   select
     l.id,
     l.display_name,
     l.cohort,
     l.plan,
     l.status,
     l.issued,
     l.expires,
     l.paid_until,
     (l.short_code_hash is not null) as has_short_serial,
     l.device_limit,
     coalesce(count(d.device_hash) filter (where d.released_at is null), 0)::integer as active_devices,
     coalesce(count(d.device_hash), 0)::integer as total_devices,
     min(d.activated_at) as first_activated_at,
     max(d.last_seen_at) as last_seen_at,
     coalesce(
       jsonb_agg(
         jsonb_build_object(
           'device_hash_prefix', left(d.device_hash, 12),
           'activated_at', d.activated_at,
           'last_seen_at', d.last_seen_at,
           'released_at', d.released_at,
           'os', d.os,
           'arch', d.arch,
           'edition', d.edition,
           'client_version', d.client_version
         )
         order by (d.released_at is not null) asc, d.last_seen_at desc
       ) filter (where d.device_hash is not null),
       '[]'::jsonb
     ) as devices
   from license_private.licenses l
   left join license_private.devices d on d.license_id = l.id
   where v_cohort is null or l.cohort = v_cohort
   group by l.id
 ),
 run_stats as (
   select
     count(*) filter (where r.created_at >= now_s - 604800)::integer as recent_runs_7d,
     count(*) filter (where r.created_at >= now_s - 604800 and r.result = 'ok')::integer as ok_runs_7d,
     count(*) filter (where r.created_at >= now_s - 604800 and r.result = 'failed')::integer as failed_runs_7d
   from license_private.install_runs r
   left join license_private.licenses l on l.id = r.license_id
   where v_cohort is null or l.cohort = v_cohort
 )
 select
   jsonb_build_object(
     'total_licenses', coalesce((select count(*)::integer from lic_stats), 0),
     'active_licenses', coalesce((select count(*) filter (where status = 'active' and active_devices > 0)::integer from lic_stats), 0),
     'inactive_licenses', coalesce((select count(*) filter (where status = 'active' and active_devices = 0)::integer from lic_stats), 0),
     'revoked_licenses', coalesce((select count(*) filter (where status = 'revoked')::integer from lic_stats), 0),
     'total_active_devices', coalesce((select sum(active_devices)::integer from lic_stats), 0),
     'recent_runs_7d', rs.recent_runs_7d,
     'ok_runs_7d', rs.ok_runs_7d,
     'failed_runs_7d', rs.failed_runs_7d
   ),
   coalesce(
     (select jsonb_agg(
        jsonb_build_object(
          'cohort', c.cohort,
          'total', c.total,
          'activated', c.activated,
          'inactive', c.inactive,
          'active_devices', c.active_devices
        ) order by c.cohort asc
      )
      from (
        select
          cohort,
          count(*)::integer as total,
          count(*) filter (where status = 'active' and active_devices > 0)::integer as activated,
          count(*) filter (where status = 'active' and active_devices = 0)::integer as inactive,
          coalesce(sum(active_devices), 0)::integer as active_devices
        from lic_stats
        group by cohort
      ) c),
     '[]'::jsonb
   ),
   coalesce(
     (select jsonb_agg(
        jsonb_build_object(
          'id', ls.id,
          'display_name', ls.display_name,
          'cohort', ls.cohort,
          'plan', ls.plan,
          'status', ls.status,
          'issued', ls.issued,
          'expires', ls.expires,
          'paid_until', ls.paid_until,
          'has_short_serial', ls.has_short_serial,
          'device_limit', ls.device_limit,
          'active_devices', ls.active_devices,
          'total_devices', ls.total_devices,
          'first_activated_at', ls.first_activated_at,
          'last_seen_at', ls.last_seen_at,
          'devices', ls.devices
        ) order by ls.cohort asc, ls.display_name asc
      )
      from lic_stats ls),
     '[]'::jsonb
   )
 into v_summary, v_cohorts, v_licenses
 from run_stats rs;

 select coalesce(
   (select jsonb_agg(
      jsonb_build_object(
        'run_id', sub.run_id,
        'edition', sub.edition,
        'os', sub.os,
        'arch', sub.arch,
        'os_version', sub.os_version,
        'shell', sub.shell,
        'shell_version', sub.shell_version,
        'installer_version', sub.installer_version,
        'result', sub.result,
        'exit_code', sub.exit_code,
        'failed_steps', sub.failed_steps,
        'helper_status', sub.helper_status,
        'license_id', sub.license_id,
        'display_name', sub.display_name,
        'cohort', sub.cohort,
        'created_at', sub.created_at
      ) order by sub.created_at desc, sub.run_id asc
    )
    from (
      select
        r.run_id, r.edition, r.os, r.arch, r.os_version, r.shell, r.shell_version,
        r.installer_version, r.result, r.exit_code, r.failed_steps, r.helper_status,
        r.license_id, l.display_name, l.cohort, r.created_at
      from license_private.install_runs r
      left join license_private.licenses l on l.id = r.license_id
      where v_cohort is null or l.cohort = v_cohort
      order by r.created_at desc, r.run_id asc
      limit 100
    ) sub),
   '[]'::jsonb
 ) into v_runs;

 select coalesce(
   (select jsonb_agg(
      jsonb_build_object(
        'step_id', f.step_id,
        'reason_code', f.reason_code,
        'count', f.cnt
      ) order by f.cnt desc, f.step_id asc, f.reason_code asc
    )
    from (
      select
        step->>'step_id' as step_id,
        step->>'reason_code' as reason_code,
        count(*)::integer as cnt
      from license_private.install_runs r
      left join license_private.licenses l on l.id = r.license_id
      cross join lateral jsonb_array_elements(r.failed_steps) as step
      where r.created_at >= now_s - 2592000
        and (v_cohort is null or l.cohort = v_cohort)
      group by step->>'step_id', step->>'reason_code'
      order by cnt desc, step_id asc, reason_code asc
      limit 20
    ) f),
   '[]'::jsonb
 ) into v_failures;

 return jsonb_build_object(
   'status', 'ok',
   'summary', v_summary,
   'cohorts', v_cohorts,
   'licenses', v_licenses,
   'install_runs', v_runs,
   'failure_breakdown', v_failures
 );
end $$;
revoke all on function public.ilson_admin_overview(jsonb) from public, anon, authenticated;
grant execute on function public.ilson_admin_overview(jsonb) to service_role;

commit;
