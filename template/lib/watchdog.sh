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
    last=$( [ -f "$f" ] && cat "$f" || echo 0 )
    if [ $((now - last)) -gt "$max" ] && [ ! -f "$STATE/alerted.$job.$today" ]; then
        touch "$STATE/alerted.$job.$today"
        printf '%s 업무가 %s 이상 안 돌았어요. 박스 상태를 봐주세요 (ilson doctor).' "$job" "$((max/3600))시간" \
            | "$(dirname "$0")/notify.sh" watchdog --fail
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
