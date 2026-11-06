-- Apply only after Jake approval, on the new Supabase project. No real credentials.
begin;
create schema if not exists license_private;
revoke all on schema license_private from public, anon, authenticated;
create table license_private.licenses (
 id text primary key check (id ~ '^[a-f0-9]{32}$'), payload_hash text not null,
 display_name text not null check (length(display_name) between 1 and 64),
 cohort integer not null check (cohort between 1 and 65535), plan integer not null check (plan in (1,2)),
 issued bigint not null, expires bigint, paid_until bigint, status text not null default 'active' check(status in ('active','revoked')),
 revoked_at bigint, device_limit integer not null default 2 check(device_limit > 0),
 check ((plan=1 and paid_until is null) or (plan=2 and paid_until is not null)),
 check ((status='active' and revoked_at is null) or (status='revoked' and revoked_at is not null))
);
create table license_private.devices (
 license_id text not null references license_private.licenses(id), device_hash text not null,
 activated_at bigint not null, last_seen_at bigint not null, released_at bigint,
 primary key(license_id,device_hash)
);
create table license_private.rate_limits (bucket text not null, window_start bigint not null, hits integer not null, primary key(bucket,window_start));
create index rate_limits_window on license_private.rate_limits(window_start);
create table license_private.events (request_id text primary key, license_id text not null, action text not null, payload_hash text not null, occurred_at bigint not null);
alter table license_private.licenses enable row level security;
alter table license_private.devices enable row level security;
alter table license_private.rate_limits enable row level security;
alter table license_private.events enable row level security;
revoke all on all tables in schema license_private from public, anon, authenticated;

-- All requests, including invalid admin credentials and malformed serials, consume an IP bucket.
create or replace function public.ilson_rate_limit(p_bucket text) returns boolean
language plpgsql security definer set search_path = pg_catalog, license_private as $$
declare n integer; w bigint := floor(extract(epoch from clock_timestamp()))::bigint / 60;
begin
 if p_bucket !~ '^[a-f0-9]{64}$' then return false; end if;
 insert into license_private.rate_limits(bucket,window_start,hits) values('edge:'||p_bucket,w,1)
 on conflict(bucket,window_start) do update set hits=license_private.rate_limits.hits+1 returning license_private.rate_limits.hits into n;
 return n <= 120;
end $$;
revoke all on function public.ilson_rate_limit(text) from public, anon, authenticated;
grant execute on function public.ilson_rate_limit(text) to service_role;

create or replace function public.ilson_license_request(p jsonb) returns jsonb
language plpgsql security definer set search_path = pg_catalog, license_private as $$
declare
 item license_private.licenses%rowtype; dev license_private.devices%rowtype;
 act text := p->>'action'; lic jsonb := p->'license'; ident text := lic->>'id';
 now_s bigint := floor(extract(epoch from clock_timestamp())); window_s bigint; hits integer;
 request_hash text; event_row license_private.events%rowtype; result text; count_devices integer;
begin
 if act not in ('activate','check','deactivate','register','revoke','renew-payment','release-device','devices') then return jsonb_build_object('status','invalid_serial'); end if;
 if ident !~ '^[a-f0-9]{32}$' or coalesce(p->>'ip_hash','') !~ '^[a-f0-9]{64}$' then return jsonb_build_object('status','invalid_serial'); end if;
 window_s := now_s / 60;
 if now_s % 300 = 0 then
   delete from license_private.rate_limits where window_start < window_s - 1440;
 end if;
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
 if act='register' then
   if coalesce(p->>'display_name','')='' then return jsonb_build_object('status','invalid_serial'); end if;
   insert into license_private.licenses(id,payload_hash,display_name,cohort,plan,issued,expires,paid_until)
   values(ident,lic->>'payload_hash',p->>'display_name',(lic->>'cohort')::integer,(lic->>'plan')::integer,(lic->>'issued')::bigint,
     case when (lic->>'expires')::bigint=4294967295 then null else (lic->>'expires')::bigint end,
     case when (lic->>'plan')::integer=2 then (p->>'paid_until')::bigint else null end)
   on conflict(id) do nothing;
 end if;
 select * into item from license_private.licenses where id=ident for update;
 if not found or item.payload_hash <> lic->>'payload_hash' then return jsonb_build_object('status','invalid_serial'); end if;
 if act='register' then
   if item.display_name <> p->>'display_name' then return jsonb_build_object('status','conflict'); end if;
 elsif act='revoke' then
   update license_private.licenses set status='revoked',revoked_at=coalesce(revoked_at,now_s) where id=ident;
 elsif act='renew-payment' then
   if item.plan <> 2 or (p->>'paid_until')::bigint <= item.paid_until then return jsonb_build_object('status','conflict'); end if;
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
