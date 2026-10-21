#!/bin/bash
# watchdog.sh — every 10 minutes: is each scheduled job running on time? rotate logs.
# Alerts once per stale job per day (state/alerted.<job>.<date>), never re-kicks a
# Claude job by itself (a stuck job burning tokens twice is worse than a late one).

source "$(dirname "$0")/common.sh"

today=$(date '+%Y-%m-%d'); now=$(date +%s)
# job:max-age-seconds — briefing daily, weekly 8 days, tidy daily, snapshot 30 min
for spec in briefing:93600 weekly:691200 tidy:93600 snapshot:1800; do
    job=${spec%%:*}; max=${spec##*:}
    f="$STATE/last-run.$job"
    [ -f "$STATE/enabled.$job" ] || continue           # only jobs init enabled
    [ -e "$STATE/paused.$job" ] && continue             # ilson pause 로 멈춘 업무
    last=$( [ -f "$f" ] && cat "$f" || echo 0 )
    # 깨진 기록은 0으로 본다. 앞자리 0은 8진수로 읽혀 반복문 전체가 멈추므로 10진수로 읽는다.
    case "$last" in ''|*[!0-9]*) last=0 ;; esac
    last=$((10#$last))
    # 미래 기록(시계 오류·손상)은 믿지 않는다. 지금으로 맞추면 매번 다시 맞춰져 알림이 영영 막힌다.
    [ "$last" -gt $((now + 300)) ] && last=0
    # 2026-10-21: 켠 뒤 아직 첫 예정 시각이 오지 않은 업무를 실패로 알렸다.
    # 켠 시각(enabled 표시)부터 재고, 다시 켠 업무는 오래된 성공 기록보다 켠 시각을 쓴다.
    since=$(stat -f%m "$STATE/enabled.$job" 2>/dev/null || echo 0)
    case "$since" in ''|*[!0-9]*) since=0 ;; esac
    # 켠 표시가 미래(시계를 뒤로 돌린 직후 등)면 기준을 믿을 수 없어 이번 회차는 건너뛴다.
    [ "$since" -gt $((now + 300)) ] && continue
    [ "$since" -gt "$last" ] && last=$since
    if [ "$max" -ge 3600 ]; then limit="$((max/3600))시간"; else limit="$((max/60))분"; fi
    if [ $((now - last)) -gt "$max" ] && [ ! -f "$STATE/alerted.$job.$today" ]; then
        touch "$STATE/alerted.$job.$today"
        printf '%s 업무가 %s 이상 안 돌았어요. 박스 상태를 봐주세요 (ilson doctor).' "$job" "$limit" \
            | "$LIB_DIR/notify.sh" watchdog --fail
        log watchdog "stale: $job"
    fi
done

# Rotate any log over 5MB (single level).
for l in "$LOGS"/*.log; do
    [ -f "$l" ] || continue
    if [ "$(stat -f%z "$l")" -gt 5242880 ]; then mv -f "$l" "$l.1"; fi
done
find "$LOGS" -name '*.out' -mtime +30 -delete 2>/dev/null
find "$STATE" -name 'alerted.*' -mtime +7 -delete 2>/dev/null
mark_run watchdog
