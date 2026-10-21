-- =====================================================================
-- cleanup.sql : 오래된 예약 요청 정리하기 (사장님이 SQL Editor 에서 직접)
-- 보관 기간: 아래 예시는 6개월이에요. 개인정보 처리방침(privacy.html)에 적은
--   기간과 똑같이 맞추세요. 바꿀 곳은 【2】【3】의 '6 months' 두 곳.
--   예: '3 months' (3개월), '1 year' (1년), '90 days' (90일)
-- 쓰는 법: 【1】【2】【3】을 한 칸씩 복사해 따로 Run 하세요.
--   【1】【2】는 읽기만 해서 언제 돌려도 안전해요.
--   【3】은 되돌릴 수 없어요. 먼저 사장님 화면에서 CSV로 백업하세요.
-- =====================================================================


-- 【1】 상태별 개수 보기 (읽기만)
select status as "상태",
       count(*) as "개수",
       (min(created_at) at time zone 'Asia/Seoul')::date as "가장 오래된 날"
from public.reservation_requests
group by status
order by array_position(array['새 요청', '확인함', '완료'], status);


-- 【2】 지울 대상 미리 세기 (읽기만)
select count(*) as "지울 요청 수"
from public.reservation_requests
where created_at < now() - interval '6 months';          -- ★ 보관 기간


-- 【3】 실제로 지우기 (되돌릴 수 없어요)
with deleted as (
  delete from public.reservation_requests
  where created_at < now() - interval '6 months'         -- ★ 보관 기간 (【2】와 똑같이)
  returning id
)
select count(*) as "지운 요청 수" from deleted;
