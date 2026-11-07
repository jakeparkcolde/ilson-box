-- Apply only after separate approval; compatible with 001_license.sql.
begin;
create table license_private.shared_skills (
 id uuid primary key, owner_id text not null references license_private.licenses(id),
 cohort integer not null, alias text not null, name text not null,
 files jsonb not null, status text not null default 'pending'
   check (status in ('pending','approved','rejected','withdrawn')),
 created_at bigint not null default floor(extract(epoch from clock_timestamp())),
 changed_at bigint not null default floor(extract(epoch from clock_timestamp()))
);
alter table license_private.shared_skills enable row level security;
revoke all on license_private.shared_skills from public, anon, authenticated;

-- Authentication, status checks and content access share the transaction and
-- the same license row lock used by revocation and device release.
create or replace function public.ilson_skill_request(p jsonb) returns jsonb
language plpgsql security definer set search_path = pg_catalog, license_private as $$
declare
 act text := p->>'action'; lic jsonb := p->'license'; item license_private.licenses%rowtype;
 skill license_private.shared_skills%rowtype; now_s bigint := floor(extract(epoch from clock_timestamp()));
 ident text := lic->>'id'; sid uuid; k text; v jsonb; count_files integer := 0; total_bytes integer := 0;
 limit_hits integer; window_s bigint := now_s / 60; audience boolean := coalesce((p->>'cohort_only')::boolean,false);
begin
 if act in ('admin-list','admin-approve','admin-reject','admin-withdraw') then
   if p->>'admin' is distinct from 'true' then return jsonb_build_object('status','forbidden'); end if;
 elsif act in ('share','list','get','withdraw') then
   if ident !~ '^[a-f0-9]{32}$' or coalesce(p->>'device_hash','') !~ '^[a-f0-9]{64}$' then
     return jsonb_build_object('status','invalid_serial');
   end if;
   select * into item from license_private.licenses where id=ident for update;
   if not found or item.payload_hash <> lic->>'payload_hash' then return jsonb_build_object('status','invalid_serial'); end if;
   if item.status <> 'active' then return jsonb_build_object('status','revoked'); end if;
   if item.expires is not null and now_s >= item.expires then return jsonb_build_object('status','expired'); end if;
   if item.plan=2 and now_s >= item.paid_until then return jsonb_build_object('status','payment_due'); end if;
   if not exists(select 1 from license_private.devices where license_id=ident and device_hash=p->>'device_hash' and released_at is null) then
     return jsonb_build_object('status','device_not_registered');
   end if;
   insert into license_private.rate_limits(bucket,window_start,hits) values('skill:'||ident,window_s,1)
     on conflict(bucket,window_start) do update set hits=license_private.rate_limits.hits+1 returning license_private.rate_limits.hits into limit_hits;
   if limit_hits > 30 then return jsonb_build_object('status','rate_limited'); end if;
 else return jsonb_build_object('status','invalid_request'); end if;

 if act='share' then
   if coalesce(p->>'name','') !~ '^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$' or jsonb_typeof(p->'files') <> 'object' then
     return jsonb_build_object('status','invalid_request');
   end if;
   for k,v in select * from jsonb_each(p->'files') loop
     count_files := count_files + 1;
     if k !~ '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}\.md$' or jsonb_typeof(v) <> 'string' then
       return jsonb_build_object('status','invalid_request');
     end if;
     total_bytes := total_bytes + octet_length(v #>> '{}');
   end loop;
   if count_files < 1 or count_files > 10 or total_bytes > 48000 or not (p->'files' ? 'SKILL.md') then
     return jsonb_build_object('status','invalid_request');
   end if;
   sid := gen_random_uuid();
   insert into license_private.shared_skills(id,owner_id,cohort,alias,name,files)
   values(sid,ident,item.cohort,'나눔-'||substr(replace(gen_random_uuid()::text,'-',''),1,10),p->>'name',p->'files');
   return jsonb_build_object('status','ok','id',sid);
 elsif act='list' then
   return jsonb_build_object('status','ok','items',coalesce((select jsonb_agg(jsonb_build_object('id',id,'name',name,'cohort',cohort,'alias',alias) order by created_at desc)
      from license_private.shared_skills where status='approved' and (not audience or cohort=item.cohort)), '[]'::jsonb));
 elsif act='admin-list' then
   if coalesce(p->>'offset','0') !~ '^[0-9]{1,7}$' or coalesce((p->>'offset')::integer,0)>1000000 then
     return jsonb_build_object('status','invalid_request');
   end if;
   return jsonb_build_object('status','ok','items',coalesce((select jsonb_agg(jsonb_build_object('id',id,'name',name,'cohort',cohort,'alias',alias,'status',status,'files',files) order by created_at desc)
      from (select * from license_private.shared_skills order by created_at desc,id desc limit 25 offset coalesce((p->>'offset')::integer,0)) recent), '[]'::jsonb));
 end if;
 begin sid := (p->>'id')::uuid; exception when others then return jsonb_build_object('status','invalid_request'); end;
 select * into skill from license_private.shared_skills where id=sid for update;
 if not found then return jsonb_build_object('status','not_found'); end if;
 if act='get' then
   if skill.status <> 'approved' or (audience and skill.cohort <> item.cohort) then return jsonb_build_object('status','not_found'); end if;
   return jsonb_build_object('status','ok','item',jsonb_build_object('id',skill.id,'name',skill.name,'cohort',skill.cohort,'alias',skill.alias,'files',skill.files));
 elsif act='withdraw' then
   if skill.owner_id <> ident then return jsonb_build_object('status','forbidden'); end if;
   update license_private.shared_skills set status='withdrawn',changed_at=now_s where id=sid;
 elsif act='admin-approve' then
   if skill.status <> 'pending' then return jsonb_build_object('status','conflict'); end if;
   update license_private.shared_skills set status='approved',changed_at=now_s where id=sid;
 elsif act='admin-reject' then
   if skill.status <> 'pending' then return jsonb_build_object('status','conflict'); end if;
   update license_private.shared_skills set status='rejected',changed_at=now_s where id=sid;
 elsif act='admin-withdraw' then
   update license_private.shared_skills set status='withdrawn',changed_at=now_s where id=sid;
 else return jsonb_build_object('status','invalid_request'); end if;
 return jsonb_build_object('status','ok');
end $$;
revoke all on function public.ilson_skill_request(jsonb) from public, anon, authenticated;
grant execute on function public.ilson_skill_request(jsonb) to service_role;
commit;
