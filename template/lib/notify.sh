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
    log "$job" "notify skipped (unpaired)"
    exit 0
fi

# curl config quoting, using only Bash builtins: values never become process
# arguments or exported environment variables. Escape backslashes first so
# quotes/control characters in a report cannot add config options.
config_value() {
    local value="$2"
    value=${value//\\/\\\\}
    value=${value//\"/\\\"}
    value=${value//$'\n'/\\n}
    value=${value//$'\r'/\\r}
    value=${value//$'\t'/\\t}
    value=${value//$'\v'/\\v}
    printf '%s = "%s"\n' "$1" "$value"
}

# Stream config through a pipe: no secret-bearing temporary files to clean up.
# -q must be first: a user's .curlrc could enable tracing or save the response.
# Plain text on purpose — no parse_mode. Neither response nor stderr is safe
# to log (both may contain the token, request text or upstream diagnostics).
if {
    config_value url "https://api.telegram.org/bot${token}/sendMessage"
    config_value data-urlencode "chat_id=${chat}"
    config_value data-urlencode "text=${text}"
} | curl -q -fsS --max-time 15 -X POST --config - >/dev/null 2>/dev/null; then
    log "$job" "notify sent (${#text} chars)"
else
    rc=$?
    case "$rc" in
        28) reason=timeout ;;
        22) reason='http error' ;;
        *) reason='transport error' ;;
    esac
    log "$job" "notify FAILED (telegram api; $reason; curl rc=$rc)"
    exit 1
fi
