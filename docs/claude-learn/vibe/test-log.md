# Test log: vibe track SQL and client snippets

Date: 2026-10-21. Files under test: `schema.sql`, `owner-policy.sql`, `cleanup.sql`, `client-snippets.md` (this folder).
Re-run this whenever Supabase changes grants, RLS defaults or supabase-js again.

## Summary

| Suite | Result |
|---|---|
| schema.sql + owner-policy.sql + cleanup.sql, 2026 default (new tables not exposed) | 46/46 PASS |
| same, legacy default (new tables auto-exposed, pre-2026 projects) | 46/46 PASS, evidence identical to the 2026 run |
| schema.sql without the GRANT section (2026 default) | 42501 confirmed (2/2) |
| schema.sql without the GRANT section, legacy default ("old tutorial") | 5/5 behaved as predicted, including 2 security gaps |
| client-snippets.md code in jsdom with real supabase-js 2.118.0 | 15/15 PASS |
| Round 2: client code J1–J14 again (email confirmation on, users made like the dashboard) | 15/15 PASS |
| Round 2: owner account paths (client-snippets.md §8) | 4/4 PASS |
| Round 2: CSV backup (client-snippets.md §9, v10-backup-code.txt) | 8/8 PASS |

## Environment

- `public.ecr.aws/supabase/postgres:17.6.1.155` (Postgres 17.6), `public.ecr.aws/supabase/postgrest:v14.7` (PostgREST 14.7), `public.ecr.aws/supabase/gotrue:v2.188.1` (Supabase Auth). All local images, nothing pulled.
- One private Docker network `claude-learn-sqltest-net`; containers `claude-learn-sqltest-{db,rest,auth}`; ports bound to 127.0.0.1 only (56432 db, 56301 rest, 56399 auth, 56321 gateway).
- Throwaway JWT secret and DB password generated per run with `secrets.token_hex`, never written to the repo.
- supabase-js: the file `https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2` served on 2026-10-21 (header: `@supabase/supabase-js@2.118.0/dist/umd/supabase.js`); jsdom 30.1.3; Node 25.

## Real vs emulated

Real (no emulation): Postgres with Supabase roles (`anon`, `authenticated`, `authenticator`, `postgres` = non-superuser with BYPASSRLS, as on hosted Supabase), PostgREST, GoTrue password sign-in / sign-out / admin user creation, `auth.uid()` (installed by GoTrue's own migrations: `coalesce(request.jwt.claim.sub, request.jwt.claims->>'sub')::uuid`), the `safeupdate` and `supautils` libraries preloaded for `authenticator`.

Emulated:
1. **2026 "tables not exposed" default**: ran exactly the revoke the dashboard runs at project creation (changelog 45329): `alter default privileges for role postgres in schema public revoke select, insert, update, delete on tables from anon, authenticated, service_role;` plus the same for `usage, select on sequences`.
2. **Legacy default**: the image's own default privileges (`arwdDxtm` on new public tables for anon/authenticated/service_role).
3. **API gateway**: a small Python proxy on 127.0.0.1:56321 routes `/rest/v1` to PostgREST and `/auth/v1` to GoTrue, rejects unknown `apikey` values with 401, and when `Authorization` is missing or equals the publishable key (what supabase-js sends before sign-in) replaces it with an anon JWT. A user access token passes through unchanged. Fake keys: `sb_publishable_localtest_...`, `sb_secret_localtest_...`.
4. **SQL Editor**: each file sent with `psql -U postgres -c "<whole file>"`, i.e. one simple query = one implicit transaction, as role `postgres`. Whether the dashboard's SQL Editor sends a paste exactly this way is not verified.
5. **Users**: owner `11111111-1111-4111-8111-111111111111`, stranger `22222222-2222-4222-8222-222222222222`, created through GoTrue's admin API with `email_confirm: true`. API tests use self-minted HS256 JWTs (`role: authenticated`, `sub` = those ids); client tests use tokens issued by GoTrue's password grant.
6. **Allow new users to sign up = off**: `GOTRUE_DISABLE_SIGNUP=true`.

Not covered: the hosted dashboard UI, invite / magic-link email, asymmetric JWT signing keys, CORS, Vercel hosting.

## Commands

```bash
# secrets (throwaway): JWT_SECRET and DB_PW from python3 -c "import secrets; print(secrets.token_hex(24))"
docker network create claude-learn-sqltest-net
docker run -d --name claude-learn-sqltest-db --network claude-learn-sqltest-net \
  -e POSTGRES_PASSWORD="$DB_PW" -e JWT_SECRET="$JWT_SECRET" -e JWT_EXP=3600 \
  -p 127.0.0.1:56432:5432 public.ecr.aws/supabase/postgres:17.6.1.155
# role passwords for network logins (the CLI does the same)
docker exec -i claude-learn-sqltest-db psql -U supabase_admin -d postgres -v pw="$DB_PW" <<'SQL'
alter role authenticator with password :'pw';
alter role supabase_auth_admin with password :'pw';
alter role postgres with password :'pw';
SQL
docker run -d --name claude-learn-sqltest-auth --network claude-learn-sqltest-net \
  -e GOTRUE_API_HOST=0.0.0.0 -e GOTRUE_API_PORT=9999 -e API_EXTERNAL_URL=http://127.0.0.1:56321 \
  -e GOTRUE_DB_DRIVER=postgres \
  -e GOTRUE_DB_DATABASE_URL="postgres://supabase_auth_admin:$DB_PW@claude-learn-sqltest-db:5432/postgres" \
  -e GOTRUE_SITE_URL=http://127.0.0.1:56321 -e GOTRUE_DISABLE_SIGNUP=true \
  -e GOTRUE_JWT_SECRET="$JWT_SECRET" -e GOTRUE_JWT_EXP=3600 -e GOTRUE_JWT_AUD=authenticated \
  -e GOTRUE_JWT_DEFAULT_GROUP_NAME=authenticated -e GOTRUE_JWT_ADMIN_ROLES=service_role \
  -e GOTRUE_EXTERNAL_EMAIL_ENABLED=true -e GOTRUE_MAILER_AUTOCONFIRM=true \
  -p 127.0.0.1:56399:9999 public.ecr.aws/supabase/gotrue:v2.188.1
docker run -d --name claude-learn-sqltest-rest --network claude-learn-sqltest-net \
  -e PGRST_DB_URI="postgres://authenticator:$DB_PW@claude-learn-sqltest-db:5432/postgres" \
  -e PGRST_DB_SCHEMAS=public,graphql_public -e PGRST_DB_EXTRA_SEARCH_PATH=public,extensions \
  -e PGRST_DB_ANON_ROLE=anon -e PGRST_JWT_SECRET="$JWT_SECRET" -e PGRST_DB_MAX_ROWS=1000 \
  -p 127.0.0.1:56301:3000 public.ecr.aws/supabase/postgrest:v14.7

# apply SQL like the SQL Editor (one query, role postgres), owner UID substituted
docker exec -i claude-learn-sqltest-db psql -U postgres -d postgres -v ON_ERROR_STOP=1 -c "$(cat schema.sql)"
docker exec -i claude-learn-sqltest-db psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -c "$(sed 's/여기에-사장님-아이디/11111111-1111-4111-8111-111111111111/' owner-policy.sql)"
docker exec claude-learn-sqltest-db psql -U postgres -d postgres -c "notify pgrst, 'reload schema';"

# requests exactly as supabase-js sends them (through the gateway)
GW=http://127.0.0.1:56321/rest/v1/reservation_requests; PUB=sb_publishable_localtest_0000000000
curl -X POST "$GW" -H "apikey: $PUB" -H "Authorization: Bearer $PUB" -H 'Content-Type: application/json' \
  -H 'Prefer: return=minimal' \
  -d '{"customer_name":"김하늘","contact":"010-1234-5678","wanted_date":"2026-11-02","wanted_time":"오후 2시","item":"꽃다발","message":"포장 부탁드려요","consent":true}'
# -> 201, empty body
curl "$GW?select=*" -H "apikey: $PUB" -H "Authorization: Bearer $PUB"
# -> 401 {"code":"42501","message":"permission denied for table reservation_requests"}
curl "$GW?select=id,created_at,customer_name,status&order=created_at.desc" -H "apikey: $PUB" -H "Authorization: Bearer $OWNER_JWT"
# -> 200, all rows; same call with $STRANGER_JWT -> 200 []
curl -X PATCH "$GW?id=eq.$ID&select=id" -H "apikey: $PUB" -H "Authorization: Bearer $OWNER_JWT" \
  -H 'Content-Type: application/json' -H 'Prefer: return=representation' -d '{"status":"확인함","handled_at":"2026-10-21T01:00:00Z"}'
# -> 200 [{"id":...}]; with {"customer_name":"x"} -> 403 42501
```

The full suites were run with a Python runner (every case below, one HTTP request or one SQL query each) and a Node runner that pulls the five code blocks out of `client-snippets.md`, loads them into jsdom pages as classic `<script>`s after the real supabase-js bundle, fills and submits the forms, and checks both the page and the database. The runners were deleted after the run. To repeat, use the commands above and the cases below.

## Results: schema.sql, owner-policy.sql, cleanup.sql

Grants after `schema.sql` (both modes): `anon: INSERT(consent, contact, customer_name, item, message, wanted_date, wanted_time)`; `authenticated: SELECT, UPDATE(handled_at, status)`.

| ID | Case | Expected | 2026 default | Legacy default | Evidence (2026 default run) |
|---|---|---|---|---|---|
| P0 | owner select BEFORE owner-policy.sql (schema only) | no rows | PASS | PASS | HTTP 200 rows=0 |
| P1 | owner-policy.sql run with placeholder unchanged | error, nothing changed | PASS | PASS | psql rc=1: ERROR:  invalid input syntax for type uuid: "여기에-사장님-아이디"; policies still 1 (the drop statements were rolled back too) |
| P2 | owner-policy.sql with owner UID | 3 policies listed | PASS | PASS | 사장님만 상태 바꾸기\|UPDATE\|{authenticated} / 사장님만 예약 보기\|SELECT\|{authenticated} / 손님은 예약 요청 보내기만\|INSERT\|{anon} |
| P3 | owner-policy.sql run a second time | ok (re-runnable) | PASS | PASS | psql rc=0 |
| P4 | schema.sql run a second time | error 'already exists', nothing changed | PASS | PASS | ERROR:  relation "reservation_requests" already exists |
| A1 | anon insert valid row (Prefer: return=minimal) | 201 | PASS | PASS | HTTP 201 (no body) |
| A2 | anon insert, no Prefer header (supabase-js default), optional fields null | 201 | PASS | PASS | HTTP 201 (no body) |
| A3 | anon insert consent=false | rejected | PASS | PASS | HTTP 401 42501 new row violates row-level security policy for table "reservation_requests" |
| A4 | anon insert status='완료' | rejected (42501) | PASS | PASS | HTTP 401 42501 permission denied for table reservation_requests |
| A5 | anon insert that names status='새 요청' itself | rejected (column not granted) | PASS | PASS | HTTP 401 42501 permission denied for table reservation_requests |
| A6 | anon insert that sets handled_at | rejected (42501) | PASS | PASS | HTTP 401 42501 permission denied for table reservation_requests |
| A7 | anon insert that sets created_at | rejected (42501) | PASS | PASS | HTTP 401 42501 permission denied for table reservation_requests |
| A8 | anon insert that sets id | rejected (42501) | PASS | PASS | HTTP 401 42501 permission denied for table reservation_requests |
| A9 | anon insert + .select() (return=representation) | rejected (42501), row not saved | PASS | PASS | HTTP 401 42501 permission denied for table reservation_requests |
| A10 | anon select * | denied (42501) | PASS | PASS | HTTP 401 42501 permission denied for table reservation_requests |
| A11 | anon select id | denied (42501) | PASS | PASS | HTTP 401 42501 permission denied for table reservation_requests |
| A12 | anon update status | denied (42501) | PASS | PASS | HTTP 401 42501 permission denied for table reservation_requests |
| A13 | anon delete | denied (42501) | PASS | PASS | HTTP 401 42501 permission denied for table reservation_requests |
| A14 | anon insert impossible date 2026-13-45 | rejected (22008) | PASS | PASS | HTTP 400 22008 date/time field value out of range: "2026-13-45" |
| L1 | customer_name 30 Korean chars (limit) | 201 | PASS | PASS | HTTP 201 (no body) |
| L2 | customer_name 31 chars | rejected (23514/23502) | PASS | PASS | HTTP 400 23514 new row for relation "reservation_requests" violates check constraint "reservation_requests_customer_nam… |
| L3 | customer_name only spaces | rejected (23514/23502) | PASS | PASS | HTTP 400 23514 new row for relation "reservation_requests" violates check constraint "reservation_requests_customer_nam… |
| L4 | contact 51 chars | rejected (23514/23502) | PASS | PASS | HTTP 400 23514 new row for relation "reservation_requests" violates check constraint "reservation_requests_contact_chec… |
| L5 | contact empty string | rejected (23514/23502) | PASS | PASS | HTTP 400 23514 new row for relation "reservation_requests" violates check constraint "reservation_requests_contact_chec… |
| L6 | wanted_time 21 chars | rejected (23514/23502) | PASS | PASS | HTTP 400 23514 new row for relation "reservation_requests" violates check constraint "reservation_requests_wanted_time_… |
| L7 | item 51 chars | rejected (23514/23502) | PASS | PASS | HTTP 400 23514 new row for relation "reservation_requests" violates check constraint "reservation_requests_item_check" |
| L8 | message 500 Korean chars (limit) | 201 | PASS | PASS | HTTP 201 (no body) |
| L9 | message 501 chars | rejected (23514/23502) | PASS | PASS | HTTP 400 23514 new row for relation "reservation_requests" violates check constraint "reservation_requests_message_chec… |
| L10 | customer_name missing | rejected (23514/23502) | PASS | PASS | HTTP 400 23502 null value in column "customer_name" of relation "reservation_requests" violates not-null constraint |
| S1 | stranger (signed in, not owner) select * | 200, 0 rows | PASS | PASS | HTTP 200 rows=0 |
| S2a | stranger update with NO filter | refused by safeupdate (21000) | PASS | PASS | HTTP 400 21000 UPDATE requires a WHERE clause |
| S2 | stranger update status (filter matching every row) | 0 rows changed (no error) | PASS | PASS | HTTP 200 rows=0; DB '새 요청' rows 4->4 |
| S3 | stranger insert | denied (42501) | PASS | PASS | HTTP 403 42501 permission denied for table reservation_requests |
| S4 | stranger delete | denied (42501) | PASS | PASS | HTTP 403 42501 permission denied for table reservation_requests |
| O1 | owner select, newest first (admin.js query) | 200, all 4 rows | PASS | PASS | HTTP 200 rows=4 |
| O2 | owner update status='확인함' + handled_at (+ .select('id')) | 200, 1 row, saved | PASS | PASS | HTTP 200 rows=1; DB: 확인함 true |
| O3 | owner update customer_name | denied (42501) | PASS | PASS | HTTP 403 42501 permission denied for table reservation_requests |
| O4 | owner update status='취소' (not allowed value) | rejected (23514) | PASS | PASS | HTTP 400 23514 new row for relation "reservation_requests" violates check constraint "reservation_requests_status_check" |
| O5 | owner update status + message together | denied (42501), nothing saved | PASS | PASS | HTTP 403 42501 permission denied for table reservation_requests |
| O6 | owner delete via API | denied (42501) | PASS | PASS | HTTP 403 42501 permission denied for table reservation_requests |
| O7 | owner insert via API (signed-in session) | denied (42501) | PASS | PASS | HTTP 403 42501 permission denied for table reservation_requests |
| C1 | cleanup 【1】 count by status (SQL Editor role postgres) | rows per status | PASS | PASS | 새 요청\|4\|2026-04-04 / 확인함\|2\|2026-05-21 / 완료\|1\|2026-03-21 |
| C2 | cleanup 【2】 preview count (6 months) | 2 | PASS | PASS | out=2  |
| C3 | cleanup 【3】 delete older than 6 months | 2 deleted, others kept | PASS | PASS | out=2; rows 7->5 |
| C4 | cleanup 【2】 again after delete | 0 | PASS | PASS | out=0 |
| C5 | whole cleanup.sql pasted at once | all 3 blocks run, last result = deleted count | PASS | PASS | psql output: 새 요청\|3\|2026-10-21 / 확인함\|2\|2026-05-21 / 0 / 0 |

C1–C5 used three back-dated rows inserted as `postgres` (7 months, 200 days and 5 months old).

## Results: what happens without the GRANT lines

Grants left on a new table under the 2026 default when section 3 is missing: `anon` and `authenticated` still hold `REFERENCES, TRIGGER, TRUNCATE` (only select/insert/update/delete are revoked by default), which is why `schema.sql` starts section 3 with `revoke all`.

| ID | Case | Expected | Result | Evidence |
|---|---|---|---|---|
| G1 | [no GRANT, 2026 default] anon insert | 42501 permission denied | PASS | HTTP 401 42501 permission denied for table reservation_requests; hint=Grant the required privileges to the current role with: GRANT INSERT ON public.reservation_requests… |
| G2 | [no GRANT, 2026 default] owner select | 42501 permission denied | PASS | HTTP 403 42501 permission denied for table reservation_requests |
| G3 | [old tutorial, legacy default] anon insert | 201 (works on old projects) | PASS | HTTP 201 (no body) |
| G4 | [old tutorial, legacy default] anon select | 200 + empty list (not an error) | PASS | HTTP 200 rows=0 |
| G5 | [old tutorial, legacy default] anon insert status='완료' | blocked only by RLS check | PASS | HTTP 401 42501 new row violates row-level security policy for table "reservation_requests" |
| G6 | [old tutorial, legacy default] anon insert with fake created_at | ACCEPTED (gap) | PASS | HTTP 201 (no body) |
| G7 | [old tutorial, legacy default] owner update customer_name | ACCEPTED (gap) | PASS | HTTP 200 rows=2 |

Full G1 hint text: `Grant the required privileges to the current role with: GRANT INSERT ON public.reservation_requests TO anon;`

## Results: client-snippets.md (jsdom + supabase-js 2.118.0 + GoTrue + PostgREST)

| ID | Case | Expected | Result | Evidence |
|---|---|---|---|---|
| J1 | reserve.js: customer sends a valid request | success text, 1 row saved as 새 요청 | PASS | msg="예약 요청을 받았어요. 가게에서 확인한 뒤 연락드릴게요."; row=이수민\|새 요청\|true\|true; form reset=true |
| J2 | reserve.js: consent box not ticked | message, nothing sent | PASS | msg="개인정보 수집·이용에 동의해 주셔야 보낼 수 있어요."; rows 1->1 |
| J3 | reserve.js: 501-char message (server limit) | friendly message, no row | PASS | msg="빈칸이나 너무 긴 글이 있어요. 확인하고 다시 보내 주세요."; console=예약 요청 저장 실패 23514 |
| J4 | reserve.js: server unreachable | fallback message, button usable again | PASS | msg="지금은 보내지 못했어요. 잠시 뒤 다시 보내시거나 가게로 전화 주세요." |
| J6 | admin.js: wrong password | friendly message, stays on login | PASS | msg="이메일이나 비밀번호가 맞지 않아요."; console=로그인 실패 invalid_credentials |
| J7 | admin.js: owner signs in, list newest first | inbox shown, 2 rows | PASS | msg="예약 요청 2건 (최신순)"; items=2; first="<b>굵게</b> · 010-2222-3333원하는 날: 2026-11-…" |
| J8 | admin.js: hostile text shown as plain text | no <img>/<b> element, script not run | PASS | img/b elements=0; __xss=undefined |
| J9 | admin.js: change status to 완료 | saved with handled_at | PASS | msg="'완료'(으)로 바꿨어요."; DB=완료\|true (<b>굵게</b>) |
| J10 | admin.js: change status back to 새 요청 | handled_at cleared | PASS | DB=새 요청\|true |
| J11 | admin.js: reopen page while signed in | inbox shown without login | PASS | msg="예약 요청 2건 (최신순)"; storage keys=sb-127-auth-token |
| J5 | reserve.js while owner is signed in on the same browser | still sent as customer | PASS | msg="예약 요청을 받았어요. 가게에서 확인한 뒤 연락드릴게요." |
| J5b | control: reserve.js WITHOUT persistSession:false, owner signed in | rejected (42501), shows why the option matters | PASS | msg="지금은 보내지 못했어요. 잠시 뒤 다시 보내시거나 가게로 전화 주세요."; console=예약 요청 저장 실패 42501 |
| J12 | admin.js: sign out | login box shown, session removed from browser | PASS | auth-token keys left=0 |
| J13 | admin.js: another signed-in user (not owner) | empty list + hint, no rows | PASS | msg="아직 예약 요청이 없어요. 있어야 하는데 안 보이면 owner-policy.sql 의 아이디를 확인하세요." |
| J14 | supabase.auth.signUp with sign-ups turned off | refused | PASS | error=signup_disabled Signups not allowed for this instance |

## Findings for the lessons

1. A table made with SQL on a project created after 2026-05-30 answers every API call with `42501 permission denied for table ...` until it has GRANTs (G1, G2). Supabase adds a hint that names the GRANT to run.
2. Old-tutorial SQL (no GRANT) on a legacy project looks fine but leaks: anon select returns an empty list instead of an error, a customer can set `created_at`, and the owner can rewrite customer fields (G4, G6, G7). `revoke all` plus column grants make old and new projects behave the same (46/46 identical).
3. PostgREST returns 42501 as HTTP 401 for anon and 403 for a signed-in user.
4. `consent=false` is stopped by the RLS policy (42501 `new row violates row-level security policy`) before the CHECK constraint runs (A3).
5. A blocked update by a signed-in non-owner is not an error: HTTP 200 with 0 rows (S2). admin.js therefore chains `.select('id')` and treats 0 rows as a failure.
6. Supabase's `safeupdate` refuses UPDATE/DELETE without a filter (`21000 UPDATE requires a WHERE clause`, S2a).
7. `.insert()` followed by `.select()` from the customer page fails with 42501 and saves nothing (A9).
8. Forgetting the placeholder in owner-policy.sql gives `ERROR: invalid input syntax for type uuid: "여기에-사장님-아이디"` and changes nothing (P1). Re-running with the right UID is safe (P3).
9. Before owner-policy.sql runs, nobody can read requests, not even the owner (P0).
10. psql prints the result of every statement when the whole cleanup.sql runs (C5). How the dashboard's SQL Editor displays several results is not verified, so the lesson runs one block at a time.
11. The customer page must create its client with `persistSession: false`: without it, a browser where the owner is signed in sends customer requests as the owner and they fail with 42501 (J5 vs J5b).
12. Owner policies use `(select auth.uid())`; the plan shows one `InitPlan` per query, as the Supabase performance guidance describes.

## Round 2: owner account and CSV backup (2026-10-21)

Same images and the same private network, ports and prefix as above, rebuilt from scratch with new throwaway secrets. Changes from round 1:
- Auth runs with email confirmation on (`GOTRUE_MAILER_AUTOCONFIRM=false`, the hosted default per FACTS-VIBE V8.11) and Site URL `http://localhost:3000` (the value the docs tell you to change, V8.17). Email links use `/auth/v1/verify` like hosted links (`GOTRUE_MAILER_URLPATHS_*=/auth/v1/verify`, as the Supabase CLI sets them).
- A fourth container, `claude-learn-sqltest-mail` (`public.ecr.aws/supabase/mailpit:v1.22.3`, local image, API on 127.0.0.1:56325), catches the invite email.
- Users are made the way the dashboard's **Create new user** form does it: the form sends `email`, `password`, `email_confirm` (dashboard source, V8.17). Here that is GoTrue's admin create-user call through the gateway with the secret key, random UUIDs, sign-ups off. **Send invitation** = GoTrue's `/invite`.
- The CSV runs add an HTML button and the §9 JS to the §4/§5 owner page (`admin.html` + `admin.js`), exactly as §9 says. jsdom has no `URL.createObjectURL` and saves no files, so the test captures the Blob and the anchor's `download` name, reads the bytes with `FileReader`, and parses them with Python's `csv` module (`strict=True`). The expected values come from the database: the same columns, Korea time, newest first, with the same `'` guard applied.
- Data for X1–X5: 2,340 rows inserted as `postgres` with past times, plus 4 hostile or tricky requests sent by a customer through the Data API (HTTP 201), plus the J-test rows: 2,347 in total.
- X5 restarts PostgREST with `PGRST_DB_MAX_ROWS=300` to stand in for a project whose "Max rows" is lower than the default 1,000.
- One fix during the run: the first U4 attempt got a link without `/auth/v1` (local Auth config only), so the gateway returned 404. After setting the URL paths, the whole round-2 suite was re-run from an empty user list and table. All 27 results below are from that clean run.

| ID | Case | Expected | Result | Evidence |
|---|---|---|---|---|
| U1 | Create new user (email + password + Auto confirm) while sign-ups are off | user created and confirmed | PASS | disable_signup=true; HTTP 200; email_confirmed_at set=true; policies: 3 |
| U2 | Create new user with Auto confirm OFF, then sign in (confirm email on, as hosted) | sign-in refused | PASS | create HTTP 200, confirmed=false; page="이메일이나 비밀번호가 맞지 않아요."; server code=로그인 실패 email_not_confirmed |
| U4 | Send invitation while sign-ups are off | invite sent; user has no password; link returns to Site URL | PASS | invite HTTP 200; mail="You have been invited"; link=http://127.0.0.1:56321/auth/v1/verify?token=…&type=invite&redirect_to=http://localhost:3000; verify -> 303 http://localhost:3000#access_token=…&exp… |
| U5 | forgot password: Delete user, Create new user (same email), re-run owner-policy.sql | new UID; empty until policy re-run, then all rows | PASS | delete HTTP 200; new UID differs=true; before re-run: "아직 예약 요청이 없어요. 있어야 하…"; after: "예약 요청 200건 (최신순)"; rows kept=2347 |
| X1 | owner CSV of 2347 rows (Data API max rows 1000) | one file, every row once, newest first | PASS | file=예약요청-2026-10-21.csv; rows=2347; requests=4; msg="예약 요청 2347건을 CSV로 내려받았어요."; mismatches=0  |
| X1b | file encoding | UTF-8 with BOM, CRLF, header in Korean | PASS | first bytes=efbbbf; type=text/csv;charset=utf-8; header=받은 시각\|이름\|연락처\|원하는 날짜\|원하는 시간\|상품\|남긴 말\|상태\|처리 시각 |
| X2 | commas, quotes, LF/CRLF inside cells, emoji | parsed back exactly (Python csv, strict) | PASS | customer inserts=201,201,201,201; tricky rows=2; sample=["2026-10-21 10:44:26","쉼표, 그리고 \"따옴표\"",",,,","","오후 2시","\"","첫 줄\n둘째 줄\r\n셋째 줄 😀 끝,","새 요청",""] |
| X3 | cells starting with = + - @ tab CR | neutralised with a leading ' | PASS | cells starting with formula char=0; guarded cells=7 (DB values needing guard=7); example="'=HYPERLINK(\"http://x.y\",\"클릭\")" "'+82 10-1234-5678" "" "'\t=1+1" "'-2+3" "'@SUM(1+1)" |
| X4 | stranger (signed in, not owner) clicks CSV | no file, "no requests" message | PASS | msg="내려받을 예약 요청이 없어요."; downloads=0 |
| X5 | owner CSV with Data API max rows = 300 (2347 rows) | still every row once, newest first | PASS | rows=2347; requests=9; mismatches=0  |
| X6 | template/.../files/v10-backup-code.txt | same as section 9, <= 64 KB, UTF-8 without BOM | PASS | 4209 bytes; identical to md section 9=true; BOM=false |
| X7 | signed out (anon) triggers CSV | no file, failure message | PASS | msg="CSV를 만들지 못했어요. 로그아웃한 뒤 다시 로그인해 보세요."; console=CSV 불러오기 실패 42501 |

| ID | Case | Result |
|---|---|---|
| J1 | reserve.js: customer sends a valid request | PASS |
| J2 | reserve.js: consent box not ticked | PASS |
| J3 | reserve.js: 501-char message (server limit) | PASS |
| J4 | reserve.js: server unreachable | PASS |
| J6 | admin.js: wrong password | PASS |
| J7 | admin.js: owner signs in, list newest first | PASS |
| J8 | admin.js: hostile text shown as plain text | PASS |
| J9 | admin.js: change status to 완료 | PASS |
| J10 | admin.js: change status back to 새 요청 | PASS |
| J11 | admin.js: reopen page while signed in | PASS |
| J5 | reserve.js while owner is signed in on the same browser | PASS |
| J5b | control: reserve.js WITHOUT persistSession:false, owner signed in | PASS |
| J12 | admin.js: sign out | PASS |
| J13 | admin.js: another signed-in user (not owner) | PASS |
| J14 | supabase.auth.signUp with sign-ups turned off | PASS |

Findings (round 2):
13. The dashboard's **Create new user** path (email + password, **Auto confirm user?** on) works with sign-ups off, and the owner can sign in at once (U1). The sign-ups setting blocks only self sign-up from a page (J14).
14. With **Auto confirm user?** off and email confirmation on, sign-in is refused with `email_not_confirmed`; admin.js shows its generic "이메일이나 비밀번호가 맞지 않아요." (U2).
15. **Send invitation** works with sign-ups off, but the invited user never gets a password they know (empty before the link; a random hash after it). The link `…/auth/v1/verify?…&type=invite&redirect_to=http://localhost:3000` sends them to the Site URL with tokens in the `#` part (U4).
16. Forgotten password without email: Delete user → Create new user gives a new UID; the owner sees an empty list until owner-policy.sql is re-run with it; no request is lost (U5).
17. CSV paging must stop on an empty page, not on a short one: with "Max rows" at 300 a "short page = done" rule would have stopped after the first 300 rows; the §9 code fetched all 2,347 (9 requests, X5).
18. The formula guard changed exactly the 7 cells that start with `=`, `+`, `-`, `@`, tab or CR, including a harmless `- 포장은 간단히` and a phone number `+82 …`, which now begin with `'` (X3).

## Cleanup

Round 1 (2026-10-21): stopped the gateway process (checked first by PID, start time, working folder and port 56321); `docker rm -f claude-learn-sqltest-rest claude-learn-sqltest-auth claude-learn-sqltest-db`; `docker network rm claude-learn-sqltest-net`.

Round 2 (2026-10-21): the same steps plus `claude-learn-sqltest-mail`.

After each round, `docker ps -a` and `docker network ls` showed no `claude-learn-sqltest-*` entries, and ports 56432, 56301, 56399, 56321 and 56325 were free. The four images stay in place; none declares a volume, so no anonymous volumes were left. The test runners, throwaway secrets, jsdom install and downloaded supabase-js file were deleted. Other projects' containers were not touched.
