#!/bin/bash
# run-job.sh <command-name> — run one headless Claude job and deliver its output.
#   command-name identifies a file in $ILSON_HOME/.claude/commands/.
# Guards: max turns, wall-clock timeout, output cap, failure notification. Never prompts.

source "$(dirname "$0")/common.sh"

name="${1:?command name}"
[[ "$name" =~ ^[a-z][a-z0-9_-]*$ ]] || { printf '잘못된 업무명\n' >&2; exit 2; }
if ! python3 "$LIB_DIR/license.py" --home "$ILSON_HOME" check >/dev/null 2>&1; then
    log "$name" 'skipped: license required'
    exit 0
fi
if [ "$COMPANY_MODE" = company ]; then
    python3 "$LIB_DIR/company_runtime.py" --home "$ILSON_HOME" job "$name" &
    company_child=$!
    trap 'kill -TERM "$company_child" 2>/dev/null; wait "$company_child"; exit 143' TERM INT HUP
    wait "$company_child"; company_rc=$?
    trap - TERM INT HUP
    [ "$company_rc" -eq 0 ] || exit "$company_rc"
    mark_run "$name"
    exit 0
fi
today=$(date '+%Y-%m-%d')
out="$LOGS/$name.$today.out"
MAX_TURNS="${ILSON_MAX_TURNS:-12}"
TIMEOUT_S="${ILSON_JOB_TIMEOUT:-600}"

cd "$ILSON_HOME" || exit 1
log "$name" "start (max_turns=$MAX_TURNS timeout=${TIMEOUT_S}s)"

# Opt-in product Q&A collector uses a no-tools Claude invocation and never
# sends or requests approval. Only this fixed job name reaches the adapter.
if [ "$name" = reply-drafts ]; then
    if command -v gtimeout >/dev/null 2>&1; then REPLY_TIMEOUT=(gtimeout -k 5 "$TIMEOUT_S");
    elif command -v timeout >/dev/null 2>&1; then REPLY_TIMEOUT=(timeout -k 5 "$TIMEOUT_S");
    else log "$name" 'FAILED: timeout tool missing'; exit 1; fi
    "${REPLY_TIMEOUT[@]}" python3 "$LIB_DIR/replies_scheduled.py" "$ILSON_HOME" >/dev/null 2>&1 &
    reply_child=$!
    trap 'kill -TERM "$reply_child" 2>/dev/null; wait "$reply_child"; log "$name" "stopped by signal"; exit 143' TERM INT HUP
    wait "$reply_child"; reply_rc=$?
    trap - TERM INT HUP
    if [ "$reply_rc" -eq 2 ]; then
        log "$name" 'skipped: disabled or already running'
        exit 0
    fi
    if [ "$reply_rc" -eq 0 ]; then
        mark_run "$name"
        log "$name" 'draft collection complete or disabled'
        exit 0
    fi
    log "$name" 'FAILED: draft collection; diagnostics suppressed'
    exit 1
fi

# report_heading <file> <title> — 제목 줄이 없는 저장 보고서에만 제목을 붙인다.
# 웹 보고서 목록과 같은 규칙: 앞 40줄에 '# 제목' 줄이 있으면 그대로 둔다. 머리말(---)로
# 시작하는 문서는 머리말이 깨지므로 건드리지 않는다. BOM은 빼고 판단하며 권한은 그대로 둔다.
report_heading() {
    local file="$1" title="$2" tmp mode top bom=$'\xef\xbb\xbf'
    [ -f "$file" ] && [ ! -L "$file" ] || return 0
    top=$(head -n 40 "$file" | LC_ALL=C sed "1s/^$bom//")
    case "$(printf '%s\n' "$top" | head -n 1)" in ---|---$'\r') return 0 ;; esac
    printf '%s\n' "$top" | LC_ALL=C grep -q '^# .*[^[:space:]]' && return 0
    mode=$(stat -f %Lp "$file") || return 0
    tmp=$(mktemp "$file.XXXXXX") || return 0
    if { printf '%s\n\n' "$title"; LC_ALL=C sed "1s/^$bom//" "$file"; } > "$tmp" &&
        chmod "$mode" "$tmp" && mv -f "$tmp" "$file"; then
        log "$name" "report heading added"
    else
        rm -f "$tmp"
    fi
}

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
_classify_cli_failure() {
    local code="$1" json_file="$2" err_file="$3"
    local probe_text=""
    if [ -s "$json_file" ]; then
        if jq -e '((.permission_denials // []) | length) > 0' "$json_file" >/dev/null 2>&1; then
            printf 'permission_denied\n'
            return 0
        fi
        probe_text=$(jq -r '
            [
                (if .is_error == true then .result else empty end),
                .error,
                .message,
                .subtype
            ] | map(select(type == "string")) | join("\n")
        ' "$json_file" 2>/dev/null || true)
    fi
    if { [ -n "$probe_text" ] && printf '%s\n' "$probe_text" | grep -Eiq 'permission[_ ]denied' 2>/dev/null; } ||
       { [ -s "$err_file" ] && grep -Eiq 'permission[_ ]denied' "$err_file" 2>/dev/null; }; then
        printf 'permission_denied\n'
        return 0
    fi
    if [ -s "$json_file" ] && jq -e '.subtype == "error_max_turns"' "$json_file" >/dev/null 2>&1; then
        printf 'cli_error\n'
        return 0
    fi
    case "$code" in
        124|137) printf 'timeout\n'; return 0 ;;
    esac
    if { [ -n "$probe_text" ] && printf '%s\n' "$probe_text" | grep -Eiq 'rate.?limit|usage.?limit|hit your limit|quota|too many requests|(^|[^0-9])429([^0-9]|$)|overloaded|limit reached|try again later|(사용량|요청|구독).*한도' 2>/dev/null; } ||
       { [ -s "$err_file" ] && grep -Eiq 'rate.?limit|usage.?limit|hit your limit|quota|too many requests|(^|[^0-9])429([^0-9]|$)|overloaded|limit reached|try again later|(사용량|요청|구독).*한도' "$err_file" 2>/dev/null; }; then
        printf 'rate_limit\n'
        return 0
    fi
    if { [ -n "$probe_text" ] && printf '%s\n' "$probe_text" | grep -Eiq 'not logged in|please log in|login required|authentication|unauthorized|(^|[^0-9])401([^0-9]|$)|session.*expired|token.*expired|expired.*token|sign in|(로그인.*(만료|필요)|다시.*로그인|세션.*만료)' 2>/dev/null; } ||
       { [ -s "$err_file" ] && grep -Eiq 'not logged in|please log in|login required|authentication|unauthorized|(^|[^0-9])401([^0-9]|$)|session.*expired|token.*expired|expired.*token|sign in|(로그인.*(만료|필요)|다시.*로그인|세션.*만료)' "$err_file" 2>/dev/null; }; then
        printf 'auth_expired\n'
        return 0
    fi
    if { [ -n "$probe_text" ] && printf '%s\n' "$probe_text" | grep -Eiq 'timed out|timeout|시간이?[[:space:]]*초과' 2>/dev/null; } ||
       { [ -s "$err_file" ] && grep -Eiq 'timed out|timeout|시간이?[[:space:]]*초과' "$err_file" 2>/dev/null; }; then
        printf 'timeout\n'
        return 0
    fi
    printf 'cli_error\n'
}

_learning_boundary_fingerprint() {
    python3 - "$VAULT" <<'PY'
import hashlib, os, sys
from pathlib import Path

vault = Path(sys.argv[1])
h = hashlib.sha256()

def record(label: str, path: Path) -> None:
    if not os.path.lexists(path):
        h.update(f"{label}:ABSENT\n".encode("utf-8"))
        return
    st = os.lstat(path)
    if path.is_symlink():
        h.update(f"{label}:LINK:{os.readlink(path)}:{st.st_mtime_ns}\n".encode("utf-8"))
        return
    if path.is_dir():
        h.update(f"{label}:DIR:{st.st_mtime_ns}\n".encode("utf-8"))
        for root, dirs, files in os.walk(path, followlinks=False):
            dirs.sort()
            files.sort()
            rel_root = os.path.relpath(root, path)
            for d in dirs:
                dp = Path(root) / d
                dst = os.lstat(dp)
                kind = "LINK:" + os.readlink(dp) if dp.is_symlink() else "DIR"
                h.update(f"{label}/{rel_root}/{d}:{kind}:{dst.st_mtime_ns}\n".encode("utf-8"))
            for f in files:
                fp = Path(root) / f
                fst = os.lstat(fp)
                if fp.is_symlink():
                    h.update(f"{label}/{rel_root}/{f}:LINK:{os.readlink(fp)}:{fst.st_mtime_ns}\n".encode("utf-8"))
                elif fp.is_file():
                    fh = hashlib.sha256()
                    with fp.open("rb") as fh_in:
                        for chunk in iter(lambda: fh_in.read(65536), b""):
                            fh.update(chunk)
                    h.update(f"{label}/{rel_root}/{f}:FILE:{fst.st_size}:{fst.st_mtime_ns}:{fh.hexdigest()}\n".encode("utf-8"))
                else:
                    h.update(f"{label}/{rel_root}/{f}:OTHER:{fst.st_mode}:{fst.st_mtime_ns}\n".encode("utf-8"))
        return
    if path.is_file():
        fh = hashlib.sha256()
        with path.open("rb") as fh_in:
            for chunk in iter(lambda: fh_in.read(65536), b""):
                fh.update(chunk)
        h.update(f"{label}:FILE:{st.st_size}:{st.st_mtime_ns}:{fh.hexdigest()}\n".encode("utf-8"))
        return
    h.update(f"{label}:OTHER:{st.st_mode}:{st.st_mtime_ns}\n".encode("utf-8"))

record(".ilson-learning", vault / ".ilson-learning")
record("lessons/approved-learning.md", vault / "lessons" / "approved-learning.md")
print(h.hexdigest())
PY
}

_output_leaks_secret() {
    local out_file="$1" token=""
    token=$(pairing_get telegram_bot_token)
    printf '%s' "$token" | python3 -c '
import re, sys
tok = sys.stdin.read()
with open(sys.argv[1], "r", encoding="utf-8", errors="ignore") as f:
    text = f.read()
if tok and tok in text:
    sys.exit(0)
patterns = (
    r"sk-ant-[A-Za-z0-9_-]{8,}",
    r"AKIA[0-9A-Z]{16}",
    r"ghp_[A-Za-z0-9]{20,}",
    r"github_pat_[A-Za-z0-9_]{10,}",
    r"AIza[A-Za-z0-9_-]{20,}",
    r"xox[baprs]-[A-Za-z0-9-]{10,}",
    r"BEGIN [A-Z ]*PRIVATE KEY",
    r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}",
    r"(?:^|[^A-Za-z0-9])(?:bot)?[0-9]{7,12}:[A-Za-z0-9_-]{25,}",
)
for pat in patterns:
    if re.search(pat, text):
        sys.exit(0)
sys.exit(1)
' "$out_file"
}

_finish_job_success() {
    local mode_tag="$1"
    # 정형 리포트는 별도로 생성하며 학습 비공개 저장소를 읽지 않는다.
    if [ "$name" = weekly ]; then
        if ! python3 "$LIB_DIR/weekly_summary.py" --vault "$VAULT" >/dev/null; then
            log "$name" 'FAILED: weekly summary generation'
            exit 1
        fi
    fi
    mark_run "$name"
    if [ -n "$mode_tag" ]; then
        log "$name" "ok ($mode_tag; $(wc -c < "$out" | tr -d ' ') bytes)"
    else
        log "$name" "ok ($(wc -c < "$out" | tr -d ' ') bytes)"
    fi
    # 2026-10-21: 보고서 목록은 첫 '# ' 줄을 제목으로 쓴다. 평문으로 저장된
    # 브리핑·주간 보고에 제목을 붙인다. 텔레그램 본문($out)은 바꾸지 않는다.
    case "$name" in
        briefing) report_heading "vault/reports/briefing/$today.md" "# $today 아침 브리핑" ;;
        weekly) report_heading "vault/reports/weekly/$today.md" "# $today 주간 보고" ;;
    esac
    # 야간 정리는 tidy.md 가 정한 '이상 없음' 한 줄일 때만 조용히 끝낸다. 이상 보고는 보낸다.
    if [ "$name" = tidy ] &&
        [ "$(sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' "$out" | sed '/^$/d')" = '정리 완료, 특이사항 없음' ]; then
        log "$name" "notify skipped (nothing unusual)"
    else
        "$LIB_DIR/notify.sh" "$name" < "$out"
    fi
}

raw=$(mktemp) || exit 1
raw_err=$(mktemp) || { rm -f "$raw"; exit 1; }
effective_policy=$(mktemp) || { rm -f "$raw" "$raw_err"; printf '예약 권한 설정을 준비하지 못했습니다.\n' >&2; exit 1; }
search_cnt=$(mktemp) || { rm -f "$raw" "$raw_err" "$effective_policy"; exit 1; }
printf '0\n' > "$search_cnt" || { rm -f "$raw" "$raw_err" "$effective_policy" "$search_cnt"; exit 1; }
claude_out=""
codex_in=""
codex_out=""
codex_err=""
child=""
_cleanup_temps() {
    local f
    for f in "$raw" "$raw_err" "$effective_policy" "$search_cnt" "$claude_out" "$codex_in" "$codex_out" "$codex_err"; do
        [ -n "$f" ] && rm -f "$f"
    done
}
_on_signal() {
    if [ -n "$child" ]; then
        kill -TERM "$child" 2>/dev/null
        wait "$child" 2>/dev/null
    fi
    _cleanup_temps
    log "$name" "stopped by signal (pause, logout or shutdown)"
    exit 143
}
trap '_cleanup_temps' EXIT
# Existing installs keep their job-settings.json. Add the learning and sensitive-path
# protections to the per-run profile without overwriting the user's saved settings.
if ! jq '.permissions.deny = ((.permissions.deny // []) + [
  "Read(./state/**)",
  "Read(**/.ssh/**)", "Read(**/.aws/**)", "Read(**/.gnupg/**)",
  "Read(**/.claude.json)", "Read(**/.claude/**)", "Read(**/.codex/**)",
  "Read(**/id_rsa*)", "Read(**/id_ed25519*)",
  "Read(**/*.pem)", "Read(**/*.key)", "Read(**/*credentials*)",
  "Read(./vault/.ilson-learning/**)",
  "Edit(./vault/.ilson-learning/**)", "Write(./vault/.ilson-learning/**)",
  "Edit(./vault/lessons/approved-learning.md)", "Write(./vault/lessons/approved-learning.md)"
] | unique)' "$policy" > "$effective_policy"; then
    log "$name" 'FAILED: invalid scheduled-job policy'
    exit 1
fi
policy="$effective_policy"
# Do not use --bare: it disables subscription OAuth/keychain authentication.
# Disable user/project/local settings, skills, hooks, and MCP inheritance.
# Explicit tools exclude subagents and interactive questions. Managed policies
# still apply; this is permission separation, not an OS security sandbox.
# 2026-10-21: launchd가 업무를 내리면(ilson pause·로그아웃) 본체에 TERM만 보낸다. gtimeout은
# 자기 프로세스 묶음에서 claude를 돌려 그대로 두면 제한 시간까지 고아로 남는다. 함께 끝내고
# 실패 알림은 보내지 않는다(사람이 멈춘 것이다). 띄우기 전에 걸어 그 사이의 신호도 받고,
# 임시 파일이 남아 있는 전 구간 동안 해제하지 않는다.
trap '_on_signal' TERM INT HUP
# CLI stderr can contain credentials and private upstream responses. Keep only
# an exit-code and safe-category summary in the usual .err file, never the raw diagnostic stream.
: > "$LOGS/$name.$today.err"
ILSON_SEARCH_COUNTER_FILE="$search_cnt" "${T[@]}" claude --safe-mode -p --max-turns "$MAX_TURNS" --output-format json \
    --permission-mode dontAsk --setting-sources '' --settings "$policy" \
    --disable-slash-commands --strict-mcp-config --mcp-config '{"mcpServers":{}}' \
    --disallowedTools 'mcp__*' \
    --tools 'Read,Glob,Grep,Edit,Write,Bash,WebSearch,WebFetch' \
    --append-system-prompt-file "$rules" <<< "$task" > "$raw" 2> "$raw_err" &
child=$!
wait "$child"; rc=$?
child=""

if [ "$rc" -eq 0 ] &&
    jq -e '.is_error == false and ((.permission_denials // []) | length == 0) and
        (.result | type == "string" and length > 0)' "$raw" >/dev/null 2>&1; then
    rm -f "$raw_err"
    raw_err=""
    printf 'CLI rc=%s reason=ok (stderr suppressed)\n' "$rc" > "$LOGS/$name.$today.err"
    claude_out=$(mktemp) || exit 1
    jq -r '.result' "$raw" > "$claude_out" || exit 1
    if _output_leaks_secret "$claude_out"; then
        rm -f "$claude_out"
        claude_out=""
        log "$name" 'FAILED: claude output rejected (secret detected)'
        printf '원인: 민감 정보 노출 감지로 보고 전송을 차단했습니다.\n복구: 터미널에서 ilson doctor 로 설정과 업무 지침을 점검하세요.\n' > "$out"
        "$LIB_DIR/notify.sh" "$name" --fail < "$out"
        exit 1
    fi
    cat "$claude_out" > "$out" || exit 1
    rm -f "$claude_out"
    claude_out=""
    _finish_job_success ""
    exit 0
fi

reason=$(_classify_cli_failure "$rc" "$raw" "$raw_err")
rm -f "$raw_err"
raw_err=""
printf 'CLI rc=%s reason=%s (stderr suppressed)\n' "$rc" "$reason" > "$LOGS/$name.$today.err"

codex_fallback_tried=0
if { [ "$reason" = rate_limit ] || [ "$reason" = auth_expired ]; } &&
    [ "${ILSON_CODEX_FALLBACK:-1}" != "0" ] &&
    command -v codex >/dev/null 2>&1; then
    codex_fallback_tried=1
    log "$name" "fallback: claude ($reason) -> codex"
    codex_in=$(mktemp) || codex_in=""
    codex_out=$(mktemp) || codex_out=""
    codex_err=$(mktemp) || codex_err=""
    if [ -n "$codex_in" ] && [ -n "$codex_out" ] && [ -n "$codex_err" ]; then
        before_fp=$(_learning_boundary_fingerprint || true)
        {
            printf '작업 디렉터리 안내: 현재 작업 디렉터리는 %s (vault/)입니다.\n' "$VAULT"
            printf '보안 경계: .ilson-learning/ 하위 파일과 lessons/approved-learning.md 는 절대 읽거나 수정·생성하지 마세요.\n\n'
            cat "$rules"
            printf '\n\n'
            printf '%s\n' "$task"
        } > "$codex_in"
        child=""
        ILSON_SEARCH_COUNTER_FILE="$search_cnt" "${T[@]}" codex exec --ignore-user-config --ignore-rules --ephemeral \
            --sandbox workspace-write --skip-git-repo-check --color never \
            -C "$VAULT" -o "$codex_out" - < "$codex_in" >/dev/null 2> "$codex_err" &
        child=$!
        wait "$child"; codex_rc=$?
        child=""
        after_fp=$(_learning_boundary_fingerprint || true)
        if [ -z "$before_fp" ] || [ -z "$after_fp" ] || [ "$before_fp" != "$after_fp" ]; then
            rm -f "$codex_in" "$codex_out" "$codex_err"
            codex_in=""; codex_out=""; codex_err=""
            log "$name" 'FAILED: codex fallback violated learning boundary'
            printf '원인: 보조 CLI(Codex) 실행이 학습 보호 경계를 위반하여 결과를 차단했습니다.\n복구: 터미널에서 ilson doctor 로 상태와 보호 파일을 점검하세요.\n' > "$out"
            "$LIB_DIR/notify.sh" "$name" --fail < "$out"
            exit 1
        fi
        if [ "$codex_rc" -eq 0 ] && [ -s "$codex_out" ] && grep -q '[^[:space:]]' "$codex_out"; then
            if _output_leaks_secret "$codex_out"; then
                rm -f "$codex_in" "$codex_out" "$codex_err"
                codex_in=""; codex_out=""; codex_err=""
                log "$name" 'FAILED: codex fallback output rejected (paired secret detected)'
                printf '원인: 보조 CLI(Codex) 출력에서 민감 정보 노출 감지로 보고 전송을 차단했습니다.\n복구: 터미널에서 ilson doctor 로 설정을 점검하세요.\n' > "$out"
                "$LIB_DIR/notify.sh" "$name" --fail < "$out"
                exit 1
            fi
            rm -f "$codex_in" "$codex_err"
            codex_in=""; codex_err=""
            cat "$codex_out" > "$out" || exit 1
            rm -f "$codex_out"
            codex_out=""
            _finish_job_success "codex fallback"
            exit 0
        fi
        codex_reason=$(_classify_cli_failure "$codex_rc" "" "$codex_err")
        log "$name" "fallback codex failed (rc=$codex_rc reason=$codex_reason; stderr suppressed)"
        rm -f "$codex_in" "$codex_out" "$codex_err"
        codex_in=""; codex_out=""; codex_err=""
    fi
fi

case "$reason" in
    rate_limit)
        log_reason='rate_limit'
        cause_ko='원인: Claude 구독 사용량 한도 도달'
        recovery_ko='복구: 잠시 후 자동 재개됩니다. 보조 CLI(codex login)를 연결해 두면 한도 시 자동 전환됩니다.'
        ;;
    auth_expired)
        log_reason='auth_expired'
        cause_ko='원인: Claude 구독 로그인 세션 만료'
        recovery_ko='복구: 터미널에서 claude login 을 실행한 뒤 다시 확인하세요.'
        ;;
    timeout)
        log_reason='time limit reached'
        cause_ko="원인: 예약 업무 실행 시간 초과(${TIMEOUT_S}초, rc=${rc})"
        recovery_ko='복구: 터미널에서 ilson doctor 로 상태를 점검하세요.'
        ;;
    permission_denied)
        log_reason='permission_denied'
        cause_ko='원인: 예약 업무 권한 규칙에서 도구 호출이 거절됨'
        recovery_ko='복구: ilson chat 에서 업무 지침과 허용 권한을 확인하세요.'
        ;;
    *)
        log_reason='command failed'
        cause_ko="원인: 예약 업무 CLI 실행 오류(rc=${rc})"
        recovery_ko='복구: 터미널에서 ilson doctor 로 상태를 점검하세요.'
        ;;
esac

if [ "$rc" -ne 0 ]; then
    log "$name" "FAILED rc=$rc ($log_reason; stderr suppressed)"
else
    log "$name" "FAILED: $reason (permission denied, incomplete job, or invalid result; stderr suppressed)"
fi

{
    printf '%s\n' "$cause_ko"
    printf '%s\n' "$recovery_ko"
    if [ "$codex_fallback_tried" -eq 1 ]; then
        printf '참고: 보조 CLI(Codex) 자동 전환도 실패했습니다.\n'
    fi
} > "$out"

"$LIB_DIR/notify.sh" "$name" --fail < "$out"
if [ "$rc" -ne 0 ]; then
    exit "$rc"
fi
exit 1
