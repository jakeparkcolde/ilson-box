#!/bin/bash
# notify.sh <job> [--fail] — send stdin text to the paired Telegram chat.
# Usage: some_command | notify.sh briefing
# Falls back to a log line when unpaired, so jobs never fail on delivery.

source "$(dirname "$0")/common.sh"

job="${1:-notify}"; kind="${2:-}"
text=$(cat)
[ -z "$text" ] && exit 0

# Telegram hard limit is 4096 chars; keep one screen.
text=$(printf '%s' "$text" | head -c 3500)
[ "$kind" = "--fail" ] && text="⚠️ 예약 업무 실패: $job
$text"

token=$(pairing_get telegram_bot_token)
chat=$(pairing_get telegram_chat_id)
if [ -z "$token" ] || [ -z "$chat" ]; then
    log "$job" "notify skipped (unpaired): $(printf '%s' "$text" | head -c 120)"
    exit 0
fi

# Plain text on purpose — no parse_mode, so job output cannot break markup.
if curl -fsS --max-time 15 -X POST "https://api.telegram.org/bot${token}/sendMessage" \
        --data-urlencode "chat_id=${chat}" --data-urlencode "text=${text}" >/dev/null; then
    log "$job" "notify sent (${#text} chars)"
else
    log "$job" "notify FAILED (telegram api)"
    exit 1
fi
