-- =====================================================================
-- owner-policy.sql : 사장님만 예약을 읽고, 상태만 바꾸게 하는 규칙
-- 언제: schema.sql 을 실행하고, 사장님 계정을 만든 다음
--       (Authentication > Users 에 사장님 이메일이 보이면 준비 끝)
-- 할 일:
--   1. Users 목록에서 사장님 줄을 열어 User UID 를 복사해요.
--      (예: 3f2b9c1e-7a4d-4e1b-9c3a-1d2e3f4a5b6c 처럼 생긴 36글자)
--   2. 아래 ★ 두 곳의 여기에-사장님-아이디 를 그 UID 로 바꿔요. (따옴표는 그대로)
--   3. SQL Editor 에 전체를 붙여 넣고 Run.
-- 바꾸지 않고 Run 하면 "invalid input syntax for type uuid" 오류가 나고
-- 아무것도 바뀌지 않아요. UID 를 넣고 다시 Run 하면 돼요.
-- UID 를 잘못 넣었을 때도 고쳐서 다시 Run 하면 돼요. (전 규칙을 지우고 새로 만들어요)
-- =====================================================================


-- 1) 같은 이름의 규칙이 있으면 먼저 지워요 (다시 실행할 수 있게)
drop policy if exists "사장님만 예약 보기" on public.reservation_requests;
drop policy if exists "사장님만 상태 바꾸기" on public.reservation_requests;


-- 2) 읽기: 로그인한 사람 중 사장님 아이디인 사람만 모든 예약을 봐요.
create policy "사장님만 예약 보기"
  on public.reservation_requests
  for select
  to authenticated
  using ( (select auth.uid()) = '여기에-사장님-아이디'::uuid );   -- ★ 바꿀 곳 1


-- 3) 고치기: 사장님만. 고칠 수 있는 칸은 schema.sql 에서 정한 두 칸
--    (status, handled_at) 뿐이에요. 같은 조건이 고친 뒤의 줄에도 적용돼요.
create policy "사장님만 상태 바꾸기"
  on public.reservation_requests
  for update
  to authenticated
  using ( (select auth.uid()) = '여기에-사장님-아이디'::uuid );   -- ★ 바꿀 곳 2


-- 4) 확인: 결과 칸에 규칙 3개가 보이면 성공이에요.
select policyname as "규칙 이름", cmd as "종류", roles as "누구에게"
from pg_policies
where schemaname = 'public' and tablename = 'reservation_requests'
order by policyname;
