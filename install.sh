#!/bin/sh
# ilson installer — the one line a customer pastes into Terminal.
#
#   curl -fsSL https://raw.githubusercontent.com/jakeparkcolde/ilson-box/main/install.sh | sh
#   sh install.sh --cli-only  # only install the CLI, without setup
#   sh install.sh --feed <url>  # save the update feed address (…/latest-v2.json) on the box
#
# What it does (setup may prompt for Homebrew admin privileges):
#   1. preflight   macOS · Apple Silicon/Intel · curl · tar
#   2. fetch       ilson CLI + template/ (they must stay together — ilson reads $SELF_DIR/template)
#   3. install     -> $CLI_DIR (default ~/.ilson-cli), kept apart from the box itself (~/ilson)
#   4. link        -> $BIN_DIR/ilson (default ~/.local/bin), PATH appended to ~/.zprofile and ~/.zshrc
#                     (bash: login profile and ~/.bashrc) if missing
#   5. setup       install tools and stage the box; authentication stays interactive
#
# Sources, in order of precedence:
#   ILSON_SRC        local directory or tarball  (testing today, before a host exists)
#   ILSON_DIST_BASE  optional custom https base serving ilson-<version>.tar.gz
#   otherwise       public GitHub source archive (ILSON_SOURCE_REF, default main)
#
# Update feed (optional): --feed <url> or ILSON_UPDATE_FEED, saved to $BOX_HOME/.updates/feed for
# `ilson update`. --feed replaces a saved address. Otherwise the address stamped into the CLI being
# replaced (release builds stamp it) wins over a saved one, as in update.py. ILSON_UPDATE_FEED only fills
# a missing, empty or invalid saved address.
#
# Design: coldbyte-vault wiki/plans/2026-09-05-ilson-init-원커맨드-온보딩-설계.md
# User-facing strings are Korean on purpose; code comments stay English.

# DIAGNOSTICS_BEGIN
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
    diag_bin=${ILSON_BIN_DIR:-$HOME/.local/bin}
    diag_in_path=false; case ":$PATH:" in *":$diag_bin:"*) diag_in_path=true ;; esac
    diag_exists=false; [ ! -f "$diag_bin/ilson" ] || diag_exists=true
    diag_vault=${ILSON_COURSE_VAULT:-$HOME/Documents/일손강의-1기}
    [ "$DIAG_EDITION" != full-mac ] || diag_vault=${ILSON_HOME:-$HOME/ilson}/vault
    diag_vault_exists=false; [ ! -d "$diag_vault" ] || diag_vault_exists=true
    diag_cwd=outside_vault
    case "$(pwd -P)/" in "$diag_vault/"*) diag_cwd=inside_vault ;; esac
    diag_facts="{\"bin_in_path\":$diag_in_path,\"cli_exists\":$diag_exists,\"vault_exists\":$diag_vault_exists}"
    if ! printf '1\t%s\t-\t%s\tILSON-DIAG-1\tILSON-DIAG-1\t%s\t%s\t%s\t%s\t%s\t%s\t-\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\tunverified\t%s\t%s\t%s\n' \
        "$ILSON_DIAG_RUN_ID" "$diag_seq" "$DIAG_EDITION" "$1" "$2" "$diag_attempt" "$diag_now" "$diag_end" "$3" "$4" "$5" "$diag_exit" "${DIAG_EXIT_SOURCE:-none}" "$diag_host" "$diag_http" "$diag_transfer" "$DIAG_PROXY" "$DIAG_ENVIRONMENT" "$diag_facts" "$diag_cwd" >> "$DIAG_FILE"; then diag_unavailable; fi
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
    if [ "${ILSON_BIN_DIR:-$HOME/.local/bin}" != "$HOME/.local/bin" ]; then
        diag_bin_quoted=$(diag_quote "$ILSON_BIN_DIR") || { printf '강사와 경로 확인\n'; return 0; }
        printf '\n현재 창에서 직접 실행:\nexport PATH=%s:"$PATH"; ilson doctor --install --confirm-shell current --run %s\n' "$diag_bin_quoted" "$ILSON_DIAG_RUN_ID"
    else
    printf '\n현재 창에서 직접 실행:\nexport PATH="$HOME/.local/bin:$PATH"; ilson doctor --install --confirm-shell current --run %s\n' "$ILSON_DIAG_RUN_ID"
    fi
    printf '새 창을 연 뒤 직접 실행 (사용자 선언):\nilson doctor --install --confirm-shell new --run %s\n' "$ILSON_DIAG_RUN_ID"
    if [ "$DIAG_EDITION" = full-mac ] && [ "${ILSON_CLI_DIR:-$HOME/.ilson-cli}" != "$HOME/.ilson-cli" ]; then
        diag_cli_quoted=$(diag_quote "$ILSON_CLI_DIR/ilson") || { printf '강사와 경로 확인\n'; return 0; }
        printf '명령 복구: %s doctor --install --run %s\n' "$diag_cli_quoted" "$ILSON_DIAG_RUN_ID"
        return 0
    fi
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
    if [ -d "$DIAG_ROOT/share" ] && [ ! -L "$DIAG_ROOT/share" ]; then
        for diag_share in "$DIAG_ROOT"/share/IL-*; do
            [ -f "$diag_share" ] && [ ! -L "$diag_share" ] || continue
            printf '%s' "${diag_share##*/}" | LC_ALL=C grep -Eq '^IL-[A-F0-9]{12}\.(txt|json)$' || continue
            find "$diag_share" -type f -mtime +30 -delete
        done
    fi
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
diag_quote() {
    [ "$(printf '%s' "$1" | LC_ALL=C tr -d '\000-\037\177')" = "$1" ] || return 1
    printf "'"; printf '%s' "$1" | sed "s/'/'\\\\''/g"; printf "'"
}
# DIAGNOSTICS_END
diag_begin full-mac "$@"
set -eu

# --- knobs ------------------------------------------------------------------
ILSON_DIST_BASE="${ILSON_DIST_BASE:-}"          # optional custom distribution host
ILSON_SRC="${ILSON_SRC:-}"                      # local dir or .tar.gz — wins over ILSON_DIST_BASE
ILSON_VERSION="${ILSON_VERSION:-latest}"
CLI_DIR="${ILSON_CLI_DIR:-$HOME/.ilson-cli}"
BIN_DIR="${ILSON_BIN_DIR:-$HOME/.local/bin}"
BOX_HOME="${ILSON_HOME:-$HOME/ilson}"           # the box itself — must never be the CLI dir
CODE=""
UPDATE_FEED="${ILSON_UPDATE_FEED:-}"            # optional update feed address (https)
FEED_EXPLICIT=0                                 # 1 with --feed: may replace a saved address
PASS_SANDBOX=""                                 # forwarded to `ilson setup` — safe rehearsal
CLI_ONLY=0
TMP=""

# --- output helpers ---------------------------------------------------------
say()  { printf '  %s\n' "$1"; }
ok()   { printf '  ✅ %s\n' "$1"; }
die()  { printf '\n❌ %s\n' "$1" >&2; exit 1; }
has()  { command -v "$1" >/dev/null 2>&1; }

# valid_feed <url> — the same rule as valid_feed in tools/update.py (tests/test_update_feed.py runs one
# case list through both): lowercase https, a host, optional port 1-65535, no userinfo, and only plain
# URL characters (no quotes, spaces, newlines, '@', '#' or '$').
valid_feed() {
    [ -n "$1" ] || return 1
    # Anything left after deleting allowed characters (the x keeps a trailing newline visible) is refused.
    [ "$(printf '%s' "$1" | LC_ALL=C tr -d 'A-Za-z0-9._~%/:?=&,;!*()+-'; echo x)" = x ] || return 1
    printf '%s\n' "$1" | grep -Eq '^https://[A-Za-z0-9][A-Za-z0-9.-]*(:[0-9]{1,5})?(/.*)?$' || return 1
    feed_authority="${1#https://}"; feed_authority="${feed_authority%%/*}"
    case "$feed_authority" in
        *:*) feed_port="${feed_authority##*:}"; [ "$feed_port" -ge 1 ] && [ "$feed_port" -le 65535 ] ;;
    esac
}

cleanup() { [ -n "$TMP" ] && [ -d "$TMP" ] && rm -rf "$TMP"; }
install_interrupted=0
installer_exit() {
    install_rc=$?
    trap - EXIT INT TERM
    if [ "${DIAG_ACTIVE:-}" = helper.install ] && [ "$install_rc" -ne 0 ] && [ "$install_interrupted" = 0 ]; then
        DIAG_EXIT_SOURCE=native diag_step_end helper.install failed EXECUTE_FAILED true "$install_rc"
    fi
    diag_finish "$install_rc" || install_rc=$?
    diag_next
    cleanup
    exit "$install_rc"
}
trap installer_exit EXIT
trap 'install_interrupted=1; exit 3' INT TERM

while [ $# -gt 0 ]; do
    case "$1" in
        --code)    CODE="${2:-}"; shift ;;
        --dir)     CLI_DIR="${2:-}"; shift ;;
        --sandbox) PASS_SANDBOX="--sandbox" ;;
        --cli-only) CLI_ONLY=1 ;;
        --dry-run) : ;;
        --feed)    [ $# -ge 2 ] || die "--feed 뒤에 업데이트 주소가 필요합니다"
                   UPDATE_FEED="$2"; FEED_EXPLICIT=1; shift ;;
        *—*|*–*) diag_skip preflight.platform SMART_DASH true; printf 'SMART_DASH: --help처럼 ASCII 하이픈 두 개를 사용하세요.\n'; exit 2 ;;
        *) diag_skip preflight.platform UNKNOWN_OPTION true; die "UNKNOWN_OPTION" ;;
    esac
    shift
done

[ "${DIAG_DRY:-0}" = 0 ] || { printf '모의 실행: 파일·PATH 변경 없음\n'; exit 0; }
printf '\n일손 설치 — %s\n\n' "$(date '+%Y-%m-%d %H:%M')"

# --- 1. preflight -----------------------------------------------------------
printf '[1] 사전 점검\n'
diag_step_start preflight.platform
[ "$(uname -s)" = "Darwin" ] || { diag_step_end preflight.platform failed WRONG_INSTALLER true 2; printf "이 설치기는 맥에서만 돕니다\n"; exit 2; }
ok "맥 $(sw_vers -productVersion 2>/dev/null || echo '')"

diag_step_end preflight.platform ok OK true 0
diag_step_start preflight.arch
case "$(uname -m)" in
    arm64) ok "애플 실리콘" ;;
    x86_64)
        if [ "$(sysctl -in sysctl.proc_translated 2>/dev/null || :)" = 1 ]; then
            diag_step_end preflight.arch failed WRONG_INSTALLER true 2
            printf 'Rosetta 터미널 대신 기본 터미널로 실행하세요.\n'; exit 2
        fi
        ok "Intel 64비트 Mac (의존 도구는 설치 후 확인)" ;;
    *) die "지원하지 않는 CPU: $(uname -m)" ;;
esac

diag_step_end preflight.arch ok OK true 0
has curl || die "curl 이 없습니다"
has tar  || die "tar 가 없습니다"
ok "curl · tar"

# Guard: the CLI must never land on top of the box, or init would overwrite it.
[ "$CLI_DIR" != "$BOX_HOME" ] || die "설치 위치가 박스 자리와 같습니다 ($CLI_DIR) — --dir 로 다른 곳을 지정하세요"
[ "$CLI_DIR" != "$HOME" ]     || die "설치 위치가 홈 폴더입니다 — --dir 로 다른 곳을 지정하세요"

# Guard: an update address must be a plain https URL — checked before anything is downloaded.
if [ -n "$UPDATE_FEED" ] || [ "$FEED_EXPLICIT" = 1 ]; then
    valid_feed "$UPDATE_FEED" || die "업데이트 주소는 https:// 로 시작하는 주소여야 합니다: $UPDATE_FEED"
fi

# Guard: refuse to replace a directory that is not a previous ilson install.
if [ -e "$CLI_DIR" ] && [ ! -f "$CLI_DIR/ilson" ]; then
    die "$CLI_DIR 가 이미 있는데 일손 설치본이 아닙니다 — 확인 후 직접 지우거나 --dir 를 쓰세요"
fi

# Decide the update address before anything is replaced, in update.py's order: --feed, then the
# address stamped into the CLI being replaced, then the saved one. ILSON_UPDATE_FEED only fills a
# missing, empty or invalid saved address. If an address must be written but cannot be, stop now,
# while the old CLI (possibly the only copy of the address) is still in place.
FEED_FILE="$BOX_HOME/.updates/feed"
OLD_FEED=""
if [ -f "$CLI_DIR/tools/update.py" ]; then
    OLD_FEED="$(sed -n "s/^FEED='\([^']*\)'[[:space:]]*\$/\1/p" "$CLI_DIR/tools/update.py" 2>/dev/null | head -n 1)"
    valid_feed "$OLD_FEED" || OLD_FEED=""
fi
# A saved address counts only if update.py would accept it (trimmed, at most 4 KB, valid).
SAVED_FEED=""
if [ -f "$FEED_FILE" ] && [ ! -L "$FEED_FILE" ] && [ "$(( $(wc -c < "$FEED_FILE") ))" -le 4096 ]; then
    SAVED_FEED="$(sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e '/^$/d' "$FEED_FILE" 2>/dev/null)" || SAVED_FEED=""
    valid_feed "$SAVED_FEED" || SAVED_FEED=""
fi
if [ "$FEED_EXPLICIT" = 1 ]; then
    FEED_VALUE="$UPDATE_FEED"
elif [ -n "$OLD_FEED" ]; then
    FEED_VALUE="$OLD_FEED"
elif [ -z "$SAVED_FEED" ]; then
    FEED_VALUE="$UPDATE_FEED"
else
    FEED_VALUE=""
fi
[ "$FEED_EXPLICIT" = 1 ] || [ "$FEED_VALUE" != "$SAVED_FEED" ] || FEED_VALUE=""
WRITE_FEED=0
if [ -n "$FEED_VALUE" ]; then
    # The nearest existing folder on the way to .updates must be a real, writable directory.
    FEED_DIR="$BOX_HOME/.updates"
    while [ ! -e "$FEED_DIR" ] && [ ! -L "$FEED_DIR" ]; do FEED_DIR="$(dirname "$FEED_DIR")"; done
    if [ -L "$BOX_HOME" ] && [ ! -e "$BOX_HOME" ]; then
        die "업데이트 주소를 저장할 수 없습니다 — 박스 폴더 링크가 깨져 있습니다: $BOX_HOME"
    elif [ -L "$BOX_HOME/.updates" ] || [ ! -d "$FEED_DIR" ] \
        || [ -L "$FEED_FILE" ] || { [ -e "$FEED_FILE" ] && [ ! -f "$FEED_FILE" ]; }; then
        die "업데이트 주소를 저장할 수 없습니다 — 링크·파일·폴더 위치를 확인하세요: $FEED_FILE"
    elif [ ! -w "$FEED_DIR" ]; then
        die "업데이트 주소를 저장할 수 없습니다 — 폴더에 쓸 권한이 없습니다: $FEED_DIR"
    fi
    WRITE_FEED=1
elif [ -n "$SAVED_FEED" ]; then
    KEEP_FEED=1
fi

# --- 2. fetch ---------------------------------------------------------------
printf '\n[2] 내려받기\n'
TMP="$(mktemp -d)"
STAGE="$TMP/stage"
mkdir -p "$STAGE"

if [ -n "$ILSON_SRC" ]; then
    diag_step_start download.installer
    if [ -d "$ILSON_SRC" ]; then
        # Copy the shipped unit only — never the dev leftovers (.sandbox/, .moai/, .git/).
        # The tarball path is clean by construction (built with `git archive`, see README).
        # `if` (not `&&`): a trailing false test would end the loop non-zero and
        # `set -e` would abort the installer silently.
        for item in ilson template tools README.md docs; do
            if [ -e "$ILSON_SRC/$item" ]; then cp -R "$ILSON_SRC/$item" "$STAGE/"; fi
        done
        ok "로컬 폴더에서 복사"
        say "$ILSON_SRC"
    elif [ -f "$ILSON_SRC" ]; then
        tar -xzf "$ILSON_SRC" -C "$STAGE" --strip-components 1 2>/dev/null \
            || tar -xzf "$ILSON_SRC" -C "$STAGE"
        ok "로컬 묶음 풀기"
    else
        die "ILSON_SRC 를 찾을 수 없습니다: $ILSON_SRC"
    fi
elif [ -n "$ILSON_DIST_BASE" ]; then
    URL="$ILSON_DIST_BASE/ilson-$ILSON_VERSION.tar.gz"
    diag_download "$URL" "$TMP/ilson.tar.gz" download.installer || die "내려받기 실패: $URL"
    tar -xzf "$TMP/ilson.tar.gz" -C "$STAGE" --strip-components 1 2>/dev/null \
        || tar -xzf "$TMP/ilson.tar.gz" -C "$STAGE"
    ok "$URL"
else
    # Public source archive: no GitHub login, Git or pairing code is needed.
    REF="${ILSON_SOURCE_REF:-main}"
    diag_download "https://codeload.github.com/jakeparkcolde/ilson-box/tar.gz/$REF" "$TMP/ilson.tar.gz" download.installer || die "GitHub 다운로드 실패 — 연결 확인 후 다시 실행하세요"
    tar -xzf "$TMP/ilson.tar.gz" -C "$STAGE" --strip-components 1 \
        || die "GitHub 설치 묶음을 풀 수 없습니다"
    ok "GitHub 일손 Box 소스 다운로드"
fi

[ -z "$ILSON_SRC" ] || diag_step_end download.installer ok OK true 0
# The CLI and its template are one unit — a half-copy would fail later, inside init.
[ -f "$STAGE/ilson" ]                || die "받은 것에 ilson 이 없습니다"
[ -f "$STAGE/template/CLAUDE.md" ]   || die "받은 것에 template/ 이 없습니다 (ilson 은 template 없이 못 돕니다)"
ok "구성 확인 (ilson + template)"

# --- 3. install -------------------------------------------------------------
diag_step_start helper.install
printf '\n[3] 설치\n'
rm -rf "$CLI_DIR"
mkdir -p "$(dirname "$CLI_DIR")"
mv "$STAGE" "$CLI_DIR"
chmod +x "$CLI_DIR/ilson"
ok "$CLI_DIR"
diag_step_end helper.install ok OK true 0

# Keep the update address on the box so it survives CLI reinstalls (decided in the preflight above).
# Write through an unpredictable temporary file in the same folder, then rename it into place.
if [ "$WRITE_FEED" = 1 ]; then
    mkdir -p "$BOX_HOME/.updates"
    FEED_TMP="$(mktemp "$BOX_HOME/.updates/.feed.XXXXXX")" || die "업데이트 주소를 저장하지 못했습니다: $FEED_FILE"
    if printf '%s\n' "$FEED_VALUE" > "$FEED_TMP" && chmod 644 "$FEED_TMP" \
        && [ ! -L "$FEED_FILE" ] && [ ! -d "$FEED_FILE" ] && mv -f "$FEED_TMP" "$FEED_FILE"; then
        ok "업데이트 주소 저장"
    else
        rm -f "$FEED_TMP"
        die "업데이트 주소를 저장하지 못했습니다: $FEED_FILE"
    fi
elif [ "${KEEP_FEED:-0}" = 1 ]; then
    ok "업데이트 주소 유지"
fi

# --- 4. link + PATH ---------------------------------------------------------
printf '\n[4] 명령 등록\n'
diag_step_start cli.link
mkdir -p "$BIN_DIR"
ln -sf "$CLI_DIR/ilson" "$BIN_DIR/ilson"
ok "$BIN_DIR/ilson"
diag_step_end cli.link ok OK true 0
diag_step_start path.persist

# ~/.zprofile only reaches login shells. Orca, Claude Code and other non-login zsh shells read ~/.zshrc,
# and a bash user reads the bash startup files, so the same line goes into each of them once.
# The rule matches course/install-intel-mac.sh: a file already counts when it holds the line in either
# form (this installer writes the expanded path, the Intel installer and the lecture workaround use $HOME);
# a symlink, a directory or a file that cannot be written is never followed or replaced — the line to add
# by hand is printed and listed again in the summary, and the install goes on.
LINE="export PATH=\"$BIN_DIR:\$PATH\""
case "$BIN_DIR" in
    "$HOME"/*) HOME_LINE="export PATH=\"\$HOME/${BIN_DIR#"$HOME"/}:\$PATH\"" ;;
    *) HOME_LINE="$LINE" ;;
esac
PATH_MANUAL=""
has_path_line() {
    # Whole-line match after trimming surrounding blanks; an unreadable file counts as not having it.
    ILSON_LINE_A="$LINE" ILSON_LINE_B="$HOME_LINE" awk '
        { sub(/^[[:space:]]+/, ""); sub(/[[:space:]]+$/, "") }
        $0 == ENVIRON["ILSON_LINE_A"] || $0 == ENVIRON["ILSON_LINE_B"] { found = 1; exit }
        END { exit !found }' "$1" 2>/dev/null
}
path_manual() {
    say "PATH 줄을 쓰지 못함 ($1) — 직접 추가하세요: $LINE"
    PATH_MANUAL="$PATH_MANUAL    · $1
"
}
add_path_line() {
    if [ -f "$1" ] && has_path_line "$1"; then
        ok "PATH 줄이 이미 있음 ($1)"
    elif [ -L "$1" ] || { [ -e "$1" ] && [ ! -f "$1" ]; }; then
        # A link (dotfile manager) or a directory: never write through it.
        path_manual "$1"
    elif printf '\n# ilson\n%s\n' "$LINE" 2>/dev/null >> "$1"; then
        ok "PATH 추가 ($1)"
    else
        # e.g. a read-only or root-owned ~/.zshrc: report it instead of stopping the install
        path_manual "$1"
    fi
}
add_path_lines() {
    add_path_line "$HOME/.zprofile"
    add_path_line "$HOME/.zshrc"
    case "${SHELL:-}" in
        */bash)
            # A bash login shell reads only the first of these that exists; do not create one that hides another.
            BASH_LOGIN="$HOME/.bash_profile"
            for candidate in "$HOME/.bash_profile" "$HOME/.bash_login" "$HOME/.profile"; do
                if [ -f "$candidate" ]; then BASH_LOGIN="$candidate"; break; fi
            done
            add_path_line "$BASH_LOGIN"
            add_path_line "$HOME/.bashrc"
            ;;
    esac
}
print_path_manual() {
    [ -n "$PATH_MANUAL" ] || return 0
    printf '  PATH 직접 추가 필요: 아래 파일에 이 줄을 넣으세요 — %s\n' "$LINE"
    printf '%s' "$PATH_MANUAL"
}

case ":$PATH:" in
    *":$BIN_DIR:"*)
        ok "PATH 에 이미 있음"
        # Same rule as a first install (and as the Intel installer): fill in any shell file still missing the line,
        # e.g. an earlier install that wrote ~/.zprofile only, or a PATH set by hand in this window.
        add_path_lines
        ;;
    *)
        add_path_lines
        say "이 터미널에서 바로 쓰려면: export PATH=\"$BIN_DIR:\$PATH\""
        say "또는 새 터미널을 열거나 source ~/.zshrc 를 실행하세요 (bash는 source ~/.bash_profile)."
        PATH="$BIN_DIR:$PATH"
        export PATH
        ;;
esac

if [ -n "$PATH_MANUAL" ]; then diag_step_end path.persist skipped-with-reason PATH_MANUAL false
else diag_step_end path.persist ok OK true 0; fi
diag_skip verify.current USER_CONFIRMATION_REQUIRED false
diag_skip verify.new-window USER_CONFIRMATION_REQUIRED false
verify_installed_cli() {
diag_step_start verify.absolute
if "$CLI_DIR/ilson" --version 2>/dev/null | grep -q 'full-mac ILSON-DIAG-1' &&
   "$CLI_DIR/ilson" doctor --install --self-check --json >/dev/null 2>&1; then diag_step_end verify.absolute ok OK true 0
else diag_step_end verify.absolute failed VERIFY_FAILED true 1; fi
}
# --- 5. next ----------------------------------------------------------------
printf '\n설치 끝 — %s\n' "$("$CLI_DIR/ilson" 2>/dev/null | head -1 || echo 'ilson')"

if [ "$CLI_ONLY" = "1" ]; then
    verify_installed_cli
    say "CLI만 설치했습니다. 기본 구성 시작: $CLI_DIR/ilson setup"
    printf '\n설치 요약\n  설치됨: 일손 CLI\n  실패: 없음\n'
    print_path_manual
    printf '  다음 할 일: ilson setup · ilson license activate\n'
    exit 0
fi

ILSON_INSTALL_SUMMARY="$TMP/install-summary.tsv"
export ILSON_INSTALL_SUMMARY
: > "$ILSON_INSTALL_SUMMARY"
printf '\n이어서 도구와 박스 기본 구성을 준비합니다.\n'
set -- "$CLI_DIR/ilson" setup
[ -z "$CODE" ] || set -- "$@" --code "$CODE"
[ -z "$PASS_SANDBOX" ] || set -- "$@" --sandbox
# Do not exec here: the installer EXIT trap must clean its download directory.
# curl | sh has a pipe on stdin. Use a controlling terminal when available,
# otherwise setup reports steps that require a person and exits without waiting.
SETUP_RC=0
if [ -z "$PASS_SANDBOX" ] && ( : </dev/tty ) 2>/dev/null; then
    "$@" </dev/tty || SETUP_RC=$?
else
    "$@" || SETUP_RC=$?
fi
say "Herdr와 Aside에서 필요한 계정 로그인과 연결은 직접 해주세요."
printf '\n강의 키트를 준비합니다. 기존 파일은 보존합니다.\n'
diag_step_start kit.prepare
if python3 "$CLI_DIR/template/lib/course-kit.py" "$CLI_DIR/template/claude/skills/course-kit-20261109" "$BOX_HOME"; then
    diag_step_end kit.prepare ok OK true 0
    ok "강의 키트 준비 완료"
    printf '설치됨\t강의 키트\n' >> "$ILSON_INSTALL_SUMMARY"
else
    diag_step_end kit.prepare failed EXECUTE_FAILED true 1
    printf '실패\t강의 키트\n' >> "$ILSON_INSTALL_SUMMARY"
    say "강의 키트 준비 실패 — Python을 확인한 뒤 ilson course-kit 을 다시 실행하세요"
    SETUP_RC=1
fi
verify_installed_cli
printf '\n설치 요약\n'
printf '  설치됨: 일손 CLI\n'
awk -F '\t' '$1 == "설치됨" {print "    · " $2}' "$ILSON_INSTALL_SUMMARY"
if [ "$SETUP_RC" = 0 ]; then
    printf '  실패: 없음\n'
else
    printf '  실패: 아래 항목 또는 미완료 구성 (위 상세 안내 확인)\n'
    awk -F '\t' '$1 == "실패" {print "    · " $2}' "$ILSON_INSTALL_SUMMARY"
    say "일부 설치가 끝나지 않았습니다. 위 안내를 확인한 뒤 ilson setup 을 다시 실행하세요."
fi
print_path_manual
printf '  다음 할 일: ilson license activate · 계정 로그인 및 필요한 권한 확인\n'
awk -F '\t' '$1 == "다음할일" {print "    · " $2}' "$ILSON_INSTALL_SUMMARY"
exit "$SETUP_RC"
