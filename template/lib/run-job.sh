#!/bin/bash
# run-job.sh <command-name> — run one headless Claude job and deliver its output.
#   command-name identifies a file in $ILSON_HOME/.claude/commands/.
# Guards: max turns, wall-clock timeout, output cap, failure notification. Never prompts.

source "$(dirname "$0")/common.sh"

name="${1:?command name}"
[[ "$name" =~ ^[a-z][a-z0-9_-]*$ ]] || { printf '잘못된 업무명\n' >&2; exit 2; }
today=$(date '+%Y-%m-%d')
out="$LOGS/$name.$today.out"
MAX_TURNS="${ILSON_MAX_TURNS:-12}"
TIMEOUT_S="${ILSON_JOB_TIMEOUT:-600}"

cd "$ILSON_HOME" || exit 1
log "$name" "start (max_turns=$MAX_TURNS timeout=${TIMEOUT_S}s)"

# 2026-09-05: vault path allows failed in -p; acceptEdits was the workaround.
# 2026-10-01: manager edits are broader now, so that workaround would also
# auto-approve code changes. Use a separate dontAsk profile and surface denied
# tools as failed jobs. Actual vault writes still need a new-Mac smoke test.
policy="$LIB_DIR/job-settings.json"
rules="$LIB_DIR/job-rules.md"
task_file="$ILSON_HOME/.claude/commands/$name.md"
if [ ! -f "$policy" ] || [ ! -f "$rules" ] || [ ! -f "$task_file" ] ||
    ! jq -e '.permissions.defaultMode == "dontAsk" and .disableAllHooks == true' "$policy" >/dev/null 2>&1; then
    log "$name" 'FAILED: missing/invalid scheduled-job configuration — run ilson setup'
    printf '예약 업무 설정이 없거나 잘못되었습니다. ilson setup 을 실행하세요.\n' >&2
    exit 1
fi
# 2026-10-07: YAML 머리말(---)을 -p 다음에 넘기면 CLI가 옵션으로 읽어
# unknown option으로 종료한다. 배포 원본에서 머리말을 제외하고 stdin으로
# 전달한다. 본문 자체가 '-'로 시작하는 사용자 명령도 같은 오류를 내지 않는다.
if ! task=$(python3 "$LIB_DIR/job-prompt.py" "$task_file" "$today"); then
    log "$name" 'FAILED: invalid scheduled-job prompt'
    printf '예약 업무 프롬프트 준비 실패: 명령 파일과 설치 상태를 확인하세요.\n' > "$out"
    "$LIB_DIR/notify.sh" "$name" --fail < "$out"
    exit 1
fi
if command -v gtimeout >/dev/null 2>&1; then T=(gtimeout -k 5 "$TIMEOUT_S");
elif command -v timeout >/dev/null 2>&1; then T=(timeout -k 5 "$TIMEOUT_S");
else log "$name" "FAILED: timeout tool missing — run ilson setup"; exit 1; fi
raw=$(mktemp) || exit 1
trap 'rm -f "$raw"' EXIT
# Do not use --bare: it disables subscription OAuth/keychain authentication.
# Disable user/project/local settings, skills, hooks, and MCP inheritance.
# Explicit tools exclude subagents and interactive questions. Managed policies
# still apply; this is permission separation, not an OS security sandbox.
if "${T[@]}" claude --safe-mode -p --max-turns "$MAX_TURNS" --output-format json \
    --permission-mode dontAsk --setting-sources '' --settings "$policy" \
    --disable-slash-commands --strict-mcp-config --mcp-config '{"mcpServers":{}}' \
    --disallowedTools 'mcp__*' \
    --tools 'Read,Glob,Grep,Edit,Write,Bash,WebSearch,WebFetch' \
    --append-system-prompt-file "$rules" <<< "$task" > "$raw" 2>"$LOGS/$name.$today.err"; then
    if ! jq -e '.is_error == false and ((.permission_denials // []) | length == 0) and
        (.result | type == "string" and length > 0)' "$raw" >/dev/null 2>&1; then
        log "$name" 'FAILED: permission denied, incomplete job, or invalid result'
        printf '예약 업무 미완료: 권한 거절 또는 응답 오류. 관리 대화에서 확인하세요.\n' > "$out"
        "$LIB_DIR/notify.sh" "$name" --fail < "$out"
        exit 1
    fi
    jq -r '.result' "$raw" > "$out" || exit 1
    mark_run "$name"
    log "$name" "ok ($(wc -c < "$out" | tr -d ' ') bytes)"
    "$LIB_DIR/notify.sh" "$name" < "$out"
else
    rc=$?
    log "$name" "FAILED rc=$rc: $(tail -c 300 "$LOGS/$name.$today.err" | tr '\n' ' ')"
    tail -c 600 "$LOGS/$name.$today.err" | "$LIB_DIR/notify.sh" "$name" --fail
    exit $rc
fi
