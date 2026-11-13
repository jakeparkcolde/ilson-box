# Ilson diagnostic recorder v1. POSIX + OS tools only; generated into installers.
# Raw arguments, stdout/stderr, paths, environment values and notes are never logged.
diag_unavailable() { DIAG_AVAILABLE=0; printf '%s\n' 'LOG_UNAVAILABLE: 설치 이력을 저장할 수 없습니다. 성공 이력 생성 미확인.' >&2; }
diag_safe() {
    diag_p=$1
    [ "$(printf '%s' "$diag_p" | LC_ALL=C tr -d '\000-\037\177')" = "$diag_p" ] || return 1
    case "$diag_p" in /*) ;; *) return 1 ;; esac
    while [ "$diag_p" != / ]; do
        [ ! -L "$diag_p" ] || return 1
        if [ -e "$diag_p" ]; then
            diag_owner=$(stat -f %u "$diag_p" 2>/dev/null) || diag_owner=$(stat -c %u "$diag_p" 2>/dev/null) || return 1
            [ "$diag_owner" = "$(id -u)" ] || [ "$diag_owner" = 0 ] || return 1
        fi
        diag_p=$(dirname "$diag_p")
        # macOS fixed OS aliases only, never user symlinks.
        case "$diag_p" in /var) diag_p=/private/var ;; /tmp) diag_p=/private/tmp ;; /etc) diag_p=/private/etc ;; esac
    done
}
diag_private() {
    diag_safe "$1" || return 1
    [ -d "$1" ] || return 1
    diag_mode=$(stat -f %Lp "$1" 2>/dev/null) || diag_mode=$(stat -c %a "$1" 2>/dev/null) || return 1
    [ "$diag_mode" = 700 ] || return 1
    diag_owner=$(stat -f %u "$1" 2>/dev/null) || diag_owner=$(stat -c %u "$1" 2>/dev/null) || return 1
    [ "$diag_owner" = "$(id -u)" ]
}
diag_valid_id() { [ "${#1}" = 32 ] && case "$1" in *[!a-f0-9]*) return 1 ;; *) return 0 ;; esac; }
diag_event() {
    [ "${DIAG_AVAILABLE:-0}" = 1 ] || return 0
    case "$1" in run-start|step-start|step-end|run-end) ;; *) return 0 ;; esac
    case "$2" in bootstrap.start|download.installer|preflight.platform|preflight.arch|runtime.python|runtime.node|tools.brew|tools.git|tools.jq|tools.gh|tools.coreutils|tools.python|tools.node|tools.claude|tools.codex|tools.aside|tools.herdr|tools.hc|tools.tvly|tools.claude.download|tools.claude.execute|tools.codex.download|tools.codex.execute|tools.vendor.download|tools.vendor.execute|apps.orca|apps.obsidian|apps.tailscale|apps.aside|apps.herdr|kit.prepare|vault.prepare|helper.install|cli.link|path.persist|verify.absolute|verify.current|verify.new-window|verify.simulated|setup.stage|setup.machine|setup.jobs|setup.web|setup.telegram|setup.auth-pending|finish) ;; *) return 0 ;; esac
    case "$3" in ok|failed|skipped-with-reason|running) ;; *) return 0 ;; esac
    case "$4" in STARTED|OK|REUSED_VERIFIED|DEPENDENCY_FAILED|PYTHON_TOO_OLD|RUNTIME_MISSING|WRONG_INSTALLER|UNSUPPORTED_OS|SMART_DASH|UNKNOWN_OPTION|COMMAND_CONFLICT|OUTSIDE_VAULT|DNS_FAILED|HTTP_FAILED|TIMEOUT|TLS_FAILED|DOWNLOAD_FAILED|EXECUTE_FAILED|VERIFY_FAILED|HASH_MISMATCH|USER_MODIFIED|PATH_MANUAL|AUTH_PENDING|USER_CONFIRMATION_REQUIRED|USER_DECLARED|DRY_RUN|NOT_APPLICABLE|NOT_SELECTED|INTERRUPTED|LOG_UNAVAILABLE|DETAIL_SUPPRESSED|CLOCK_UNVERIFIED) ;; *) return 0 ;; esac
    case "$5" in true|false) ;; *) return 0 ;; esac
    diag_exit=${6:--}; case "$diag_exit" in ''|*[!0-9]*) diag_exit=- ;; esac
    diag_host=${7:-none}; case "$diag_host" in none|custom_host|raw.githubusercontent.com|codeload.github.com|github.com|claude.ai|chatgpt.com|www.python.org|releases.herdr.dev|releases.aside.com) ;; *) diag_host=custom_host ;; esac
    diag_http=${8:--}; case "$diag_http" in ''|*[!0-9]*) diag_http=- ;; esac
    diag_transfer=${9:--}; case "$diag_transfer" in ''|*[!0-9]*) diag_transfer=- ;; esac
    diag_now=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
    diag_end=-; [ "$1" = step-end ] || [ "$1" = run-end ] || diag_end=-
    case "$1" in *-end) diag_end=$diag_now ;; esac
    diag_seq=$(( $(wc -l < "$DIAG_FILE") + 1 ))
    # Attempt increases per repeated fixed step, e.g. vendor downloads and kit members.
    diag_attempt=$(awk -F '\t' -v step="$2" '$8=="step-start" && $9==step {n++} END {print n+0}' "$DIAG_FILE")
    [ "$1" != step-start ] || diag_attempt=$((diag_attempt+1))
    [ "$diag_attempt" -gt 0 ] || diag_attempt=1
    [ "$(wc -c < "$DIAG_FILE")" -lt 1048576 ] || { diag_unavailable; return 0; }
    if ! printf '1\t%s\t-\t%s\tILSON-DIAG-1\tILSON-DIAG-1\t%s\t%s\t%s\t%s\t%s\t%s\t-\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\tunverified\t%s\n' \
        "$ILSON_DIAG_RUN_ID" "$diag_seq" "$DIAG_EDITION" "$1" "$2" "$diag_attempt" "$diag_now" "$diag_end" "$3" "$4" "$5" "$diag_exit" "${DIAG_EXIT_SOURCE:-none}" "$diag_host" "$diag_http" "$diag_transfer" "$DIAG_PROXY" "$DIAG_ENVIRONMENT" >> "$DIAG_FILE"; then diag_unavailable; fi
}
diag_begin() {
    DIAG_EDITION=$1; DIAG_AVAILABLE=0; DIAG_ACTIVE=; DIAG_CHILD=0; DIAG_DRY=0
    shift
    for diag_arg do case "$diag_arg" in --dry-run|-DryRun) DIAG_DRY=1 ;; esac; done
    [ "${ILSON_COURSE_DRY_RUN:-0}" != 1 ] && [ "${ILSON_DRY_RUN:-0}" != 1 ] || DIAG_DRY=1
    [ "$DIAG_DRY" = 0 ] || { printf '%s\n' 'DIAGNOSTICS DRY_RUN: 영속 로그 없음'; return 0; }
    DIAG_ROOT=${ILSON_DIAGNOSTICS_DIR:-$HOME/.ilson-diagnostics}
    diag_safe "$DIAG_ROOT" || { diag_unavailable; return 0; }
    if [ -e "$DIAG_ROOT" ]; then diag_private "$DIAG_ROOT" || { diag_unavailable; return 0; }; fi
    (umask 077; mkdir -p "$DIAG_ROOT/runs") || { diag_unavailable; return 0; }
    diag_private "$DIAG_ROOT/runs" || { diag_unavailable; return 0; }
    diag_retain 19
    if diag_valid_id "${ILSON_DIAG_RUN_ID:-}" && diag_private "$DIAG_ROOT/runs/$ILSON_DIAG_RUN_ID" && [ -f "$DIAG_ROOT/runs/$ILSON_DIAG_RUN_ID/events.tsv" ] && [ ! -L "$DIAG_ROOT/runs/$ILSON_DIAG_RUN_ID/events.tsv" ]; then
        DIAG_CHILD=1
    else
        ILSON_DIAG_RUN_ID=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')
        diag_valid_id "$ILSON_DIAG_RUN_ID" || { diag_unavailable; return 0; }
        (umask 077; mkdir "$DIAG_ROOT/runs/$ILSON_DIAG_RUN_ID" && : > "$DIAG_ROOT/runs/$ILSON_DIAG_RUN_ID/events.tsv") || { diag_unavailable; return 0; }
    fi
    DIAG_FILE="$DIAG_ROOT/runs/$ILSON_DIAG_RUN_ID/events.tsv"
    DIAG_PROXY=false
    [ -z "${HTTPS_PROXY:-}${HTTP_PROXY:-}${ALL_PROXY:-}${https_proxy:-}${http_proxy:-}${all_proxy:-}" ] || DIAG_PROXY=true
    DIAG_OS=$(uname -s); case "$DIAG_OS" in Darwin|Linux) ;; *) DIAG_OS=unknown ;; esac
    DIAG_ARCH=$(uname -m); case "$DIAG_ARCH" in arm64|x86_64) ;; *) DIAG_ARCH=unknown ;; esac
    DIAG_OS_VERSION=unknown
    if [ "$DIAG_OS" = Darwin ]; then DIAG_OS_VERSION=$(sw_vers -productVersion 2>/dev/null || printf unknown); fi
    printf '%s' "$DIAG_OS_VERSION" | LC_ALL=C grep -Eq '^[0-9]{1,3}(\.[0-9]{1,3}){1,3}$' || DIAG_OS_VERSION=unknown
    DIAG_ROSETTA=false
    if [ "$DIAG_OS" = Darwin ] && [ "$(sysctl -in sysctl.proc_translated 2>/dev/null || :)" = 1 ]; then DIAG_ROSETTA=true; fi
    DIAG_ENVIRONMENT="{\"os\":\"$DIAG_OS\",\"os_version\":\"$DIAG_OS_VERSION\",\"arch\":\"$DIAG_ARCH\",\"rosetta\":$DIAG_ROSETTA}"
    DIAG_AVAILABLE=1
    export ILSON_DIAG_RUN_ID ILSON_DIAGNOSTICS_DIR
    [ "$DIAG_CHILD" = 1 ] || diag_event run-start bootstrap.start running STARTED true
}
diag_step_start() { DIAG_ACTIVE=$1; DIAG_REQUIRED=${2:-true}; diag_event step-start "$DIAG_ACTIVE" running STARTED "$DIAG_REQUIRED"; }
diag_step_end() { diag_event step-end "$1" "$2" "$3" "${4:-true}" "${5:--}" "${6:-none}" "${7:--}" "${8:--}"; DIAG_ACTIVE=; }
diag_skip() { diag_step_start "$1" "${3:-true}"; diag_step_end "$1" skipped-with-reason "$2" "${3:-true}"; }
diag_finish() {
    diag_rc=${1:-0}
    [ "${DIAG_DRY:-0}" = 0 ] || return "$diag_rc"
    [ "${DIAG_AVAILABLE:-0}" = 1 ] || return 3
    if [ -n "${DIAG_ACTIVE:-}" ]; then diag_step_end "$DIAG_ACTIVE" failed INTERRUPTED "${DIAG_REQUIRED:-true}" "$diag_rc"; diag_rc=3; fi
    if awk -F '\t' '$8=="step-end" && $16=="true" && $14!="ok" && $15!="DRY_RUN" && $15!="NOT_APPLICABLE" && $15!="NOT_SELECTED" {bad=1} END {exit !bad}' "$DIAG_FILE"; then [ "$diag_rc" != 0 ] || diag_rc=1; fi
    diag_result=ok; diag_reason=OK
    [ "$diag_rc" = 0 ] || { diag_result=failed; diag_reason=EXECUTE_FAILED; }
    [ "${DIAG_CHILD:-0}" = 1 ] || diag_event run-end finish "$diag_result" "$diag_reason" true "$diag_rc"
    return "$diag_rc"
}
diag_download() {
    # URL is used for transfer only. Persist host enum/status; never curl stderr or URL text.
    diag_url=$1; diag_out=$2; diag_step=${3:-download.installer}; diag_req=${4:-true}
    diag_host=custom_host
    case "$diag_url" in
        https://raw.githubusercontent.com/*) diag_host=raw.githubusercontent.com ;;
        https://codeload.github.com/*) diag_host=codeload.github.com ;;
        https://github.com/*) diag_host=github.com ;;
        https://claude.ai/install.sh) diag_host=claude.ai ;;
        https://chatgpt.com/codex/install.sh) diag_host=chatgpt.com ;;
        https://releases.herdr.dev/*) diag_host=releases.herdr.dev ;;
        https://releases.aside.com/*) diag_host=releases.aside.com ;;
    esac
    diag_step_start "$diag_step" "$diag_req"
    diag_rc=0
    diag_http=$(curl -fsSL --connect-timeout 10 --max-time 120 -w '%{http_code}' "$diag_url" -o "$diag_out" 2>/dev/null) || diag_rc=$?
    # Suppress arbitrary stdout from a fake/unexpected curl too.
    case "$diag_http" in [0-9][0-9][0-9]) ;; *) diag_http=- ;; esac
    diag_reason=OK; diag_result=ok
    case "$diag_rc" in 0) ;; 5|6) diag_reason=DNS_FAILED ;; 22) diag_reason=HTTP_FAILED ;; 28) diag_reason=TIMEOUT ;; 35|51|58|60) diag_reason=TLS_FAILED ;; *) diag_reason=DOWNLOAD_FAILED ;; esac
    [ "$diag_rc" = 0 ] || diag_result=failed
    DIAG_EXIT_SOURCE=curl diag_step_end "$diag_step" "$diag_result" "$diag_reason" "$diag_req" "$diag_rc" "$diag_host" "$diag_http" "$diag_rc"
    return "$diag_rc"
}
diag_next() {
    diag_valid_id "${ILSON_DIAG_RUN_ID:-}" || return 0
    printf '\n현재 창에서 직접 실행:\nexport PATH="$HOME/.local/bin:$PATH"; ilson doctor --install --confirm-shell current --run %s\n' "$ILSON_DIAG_RUN_ID"
    printf '새 창을 연 뒤 직접 실행 (사용자 선언):\nilson doctor --install --confirm-shell new --run %s\n' "$ILSON_DIAG_RUN_ID"
    case "$DIAG_EDITION" in full-mac) printf '명령 복구: "$HOME/.ilson-cli/ilson" doctor --install --run %s\n' "$ILSON_DIAG_RUN_ID" ;; *) printf '명령 복구: "$HOME/.local/bin/ilson" doctor --install --run %s\n' "$ILSON_DIAG_RUN_ID" ;; esac
}
diag_verify() (
    "$@" >/dev/null 2>&1 & diag_pid=$!
    (sleep 5; kill -TERM "$diag_pid" 2>/dev/null) >/dev/null 2>&1 & diag_timer=$!
    diag_verify_rc=0; wait "$diag_pid" || diag_verify_rc=$?
    kill -TERM "$diag_timer" 2>/dev/null || :
    wait "$diag_timer" 2>/dev/null || :
    exit "$diag_verify_rc"
)
diag_retain() (
    # Root already validated. Only exact owned run files; unknown contents/links survive.
    diag_limit=${1:-20}; diag_total=0; diag_count=0; diag_now_epoch=$(date +%s)
    diag_inventory=$(
        for diag_dir in "$DIAG_ROOT"/runs/*; do
            diag_id=${diag_dir##*/}; diag_valid_id "$diag_id" || continue
            [ -d "$diag_dir" ] && [ ! -L "$diag_dir" ] || continue
            [ -f "$diag_dir/events.tsv" ] && [ ! -L "$diag_dir/events.tsv" ] || continue
            diag_known=1
            for diag_entry in "$diag_dir"/* "$diag_dir"/.[!.]*; do
                [ -e "$diag_entry" ] || [ -L "$diag_entry" ] || continue
                if [ "${diag_entry##*/}" = events.tsv ] || [ "${diag_entry##*/}" = events.jsonl ]; then
                    [ ! -L "$diag_entry" ] || diag_known=0
                else diag_known=0; fi
            done
            [ "$diag_known" = 1 ] || continue
            diag_stamp=$(stat -f %m "$diag_dir/events.tsv" 2>/dev/null) || diag_stamp=$(stat -c %Y "$diag_dir/events.tsv" 2>/dev/null) || continue
            # Recent active runs are not removed by another installer.
            if ! awk -F '\t' '$8=="run-end" {found=1} END {exit !found}' "$diag_dir/events.tsv"; then
                [ "$((diag_now_epoch-diag_stamp))" -ge 86400 ] || continue
            fi
            diag_bytes=$(wc -c < "$diag_dir/events.tsv")
            if [ -f "$diag_dir/events.jsonl" ]; then diag_bytes=$((diag_bytes+$(wc -c < "$diag_dir/events.jsonl"))); fi
            printf '%s %s %s\n' "$diag_stamp" "$diag_bytes" "$diag_id"
        done | sort -rn
    )
    printf '%s\n' "$diag_inventory" | while read -r diag_stamp diag_bytes diag_id; do
        diag_valid_id "${diag_id:-}" || continue
        diag_count=$((diag_count+1)); diag_total=$((diag_total+diag_bytes))
        if [ "$diag_count" -gt "$diag_limit" ] || [ "$diag_total" -gt 9437184 ] || [ "$((diag_now_epoch-diag_stamp))" -gt 2592000 ]; then
            diag_dir="$DIAG_ROOT/runs/$diag_id"
            # Exact files only, never recursive deletion or a wildcard deletion target.
            find "$diag_dir/events.tsv" -type f -delete
            [ ! -f "$diag_dir/events.jsonl" ] || find "$diag_dir/events.jsonl" -type f -delete
            rmdir "$diag_dir" 2>/dev/null || :
        fi
    done
)
