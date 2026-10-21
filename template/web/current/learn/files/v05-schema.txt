-- =====================================================================
-- schema.sql : 예약·문의 상자 만들기
-- 어디서: Supabase 대시보드 > SQL Editor 에 이 파일 전체를 붙여 넣고 Run
-- 언제: 프로젝트를 만든 직후 한 번만
-- 결과: 손님(로그인 안 한 방문자)은 예약 요청을 "보내기"만 할 수 있어요.
--       누구도 아직 읽을 수 없어요. 사장님이 읽는 규칙은 owner-policy.sql 에 있어요.
-- 시험 기록: test-log.md (2026-10-21)
-- 두 번 실행하면 "already exists" 오류가 나고 아무것도 바뀌지 않아요. 이미 된 거예요.
-- =====================================================================


-- 1) 예약 요청을 담을 표 (칸마다 글자 수 제한이 있어요)
create table public.reservation_requests (
  id            uuid primary key default gen_random_uuid(),   -- 요청 번호 (자동)
  created_at    timestamptz not null default now(),           -- 받은 시각 (자동)
  customer_name text not null
                check (char_length(customer_name) <= 30 and btrim(customer_name) <> ''),
                                                              -- 이름: 꼭 쓰기, 30자까지
  contact       text not null
                check (char_length(contact) <= 50 and btrim(contact) <> ''),
                                                              -- 연락처: 꼭 쓰기, 50자까지
  wanted_date   date,                                         -- 원하는 날짜 (비워도 돼요)
  wanted_time   text check (char_length(wanted_time) <= 20),  -- 원하는 시간 (예: 오후 2시), 20자까지
  item          text check (char_length(item) <= 50),         -- 원하는 상품, 50자까지
  message       text check (char_length(message) <= 500),     -- 남길 말, 500자까지
  consent       boolean not null check (consent),             -- 개인정보 동의: 반드시 true
  status        text not null default '새 요청'
                check (status in ('새 요청', '확인함', '완료')), -- 처리 상태: 이 셋 중 하나
  handled_at    timestamptz                                   -- 사장님이 확인·완료한 시각
);


-- 2) 규칙 켜기(RLS): 켜 두면 아래 규칙(policy)에 맞는 요청만 통과해요.
alter table public.reservation_requests enable row level security;


-- 3) 권한(GRANT): 2026년부터 새 표는 저절로 열리지 않아요.
--    먼저 모두 닫고, 필요한 칸만 엽니다. (예전 프로젝트에서도 똑같이 동작하게)
revoke all on table public.reservation_requests from anon, authenticated;

-- 손님(anon): 아래 7칸에 "쓰기"만. 읽기·고치기·지우기 권한은 없어요.
--   상태·받은 시각·처리 시각은 손님이 정할 수 없어요.
grant insert (customer_name, contact, wanted_date, wanted_time, item, message, consent)
  on table public.reservation_requests to anon;

-- 로그인한 사람(authenticated): 읽기 + 상태 두 칸만 고치기.
--   누가 실제로 읽을 수 있는지는 owner-policy.sql 이 정해요. 그 전에는 아무도 못 읽어요.
grant select on table public.reservation_requests to authenticated;
grant update (status, handled_at) on table public.reservation_requests to authenticated;


-- 4) 규칙(policy): 손님 요청은 "동의함 + 새 요청 + 처리 시각 없음"일 때만 들어와요.
create policy "손님은 예약 요청 보내기만"
  on public.reservation_requests
  for insert
  to anon
  with check (
    consent = true
    and status = '새 요청'
    and handled_at is null
  );


-- 5) 최신순 목록과 오래된 요청 정리를 빠르게
create index reservation_requests_created_at_idx
  on public.reservation_requests (created_at desc);
