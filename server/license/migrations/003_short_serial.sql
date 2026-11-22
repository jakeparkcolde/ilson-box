-- Additive V2 short serial (IL2-XXXX-XXXX-XXXX) migration; compatible with 001_license.sql and 002_skill_share.sql.
begin;
alter table license_private.licenses
  add column if not exists short_code_hash text unique check (short_code_hash ~ '^[a-f0-9]{64}$'),
  add column if not exists sealed_serial text check (sealed_serial ~ '^[A-Za-z0-9_-]{188}$');
alter table license_private.licenses
  add constraint licenses_short_serial_pair check ((short_code_hash is null) = (sealed_serial is null));

create or replace function public.ilson_license_request(p jsonb) returns jsonb
language plpgsql security definer set search_path = pg_catalog, license_private as $$
declare
 item license_private.licenses%rowtype; dev license_private.devices%rowtype;
 act text := p->>'action'; lic jsonb := p->'license'; ident text := lic->>'id';
 sch text := p->>'short_code_hash'; sealed text := p->>'sealed_serial'; v_id text;
 now_s bigint := floor(extract(epoch from clock_timestamp())); window_s bigint; hits integer;
 request_hash text; event_row license_private.events%rowtype; result text; count_devices integer;
begin
 if act not in ('activate','check','deactivate','register','revoke','renew-payment','release-device','devices') then return jsonb_build_object('status','invalid_serial'); end if;
 if coalesce(p->>'ip_hash','') !~ '^[a-f0-9]{64}$' then return jsonb_build_object('status','invalid_serial'); end if;
 window_s := now_s / 60;
 if now_s % 300 = 0 then
   delete from license_private.rate_limits where window_start < window_s - 1440;
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
     insert into license_private.devices values(item.id,p->>'device_hash',now_s,now_s,null)
     on conflict(license_id,device_hash) do update set activated_at=now_s,last_seen_at=now_s,released_at=null;
   else
     update license_private.devices set last_seen_at=now_s where license_id=item.id and device_hash=p->>'device_hash';
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
     insert into license_private.devices values(ident,p->>'device_hash',now_s,now_s,null)
     on conflict(license_id,device_hash) do update set activated_at=now_s,last_seen_at=now_s,released_at=null;
   else
     update license_private.devices set last_seen_at=now_s where license_id=ident and device_hash=p->>'device_hash';
   end if;
   return jsonb_build_object('status','active','expires_at',item.expires,'paid_until',item.paid_until);
 end if;
 insert into license_private.events(request_id,license_id,action,payload_hash,occurred_at) values(p->>'request_id',ident,act,request_hash,now_s);
 return jsonb_build_object('status','ok');
end $$;
revoke all on function public.ilson_license_request(jsonb) from public, anon, authenticated;
grant execute on function public.ilson_license_request(jsonb) to service_role;
commit;
