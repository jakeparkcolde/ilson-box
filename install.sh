#!/bin/sh
# ilson installer — the one line a customer pastes into Terminal.
#
#   curl -fsSL https://raw.githubusercontent.com/jakeparkcolde/ilson-box/main/install.sh | sh
#   sh install.sh --cli-only  # only install the CLI, without setup
#
# What it does (setup may prompt for Homebrew admin privileges):
#   1. preflight   macOS · Apple Silicon · curl · tar
#   2. fetch       ilson CLI + template/ (they must stay together — ilson reads $SELF_DIR/template)
#   3. install     -> $CLI_DIR (default ~/.ilson-cli), kept apart from the box itself (~/ilson)
#   4. link        -> $BIN_DIR/ilson (default ~/.local/bin), PATH appended to ~/.zprofile if missing
#   5. setup       install tools and stage the box; authentication stays interactive
#
# Sources, in order of precedence:
#   ILSON_SRC        local directory or tarball  (testing today, before a host exists)
#   ILSON_DIST_BASE  optional custom https base serving ilson-<version>.tar.gz
#   otherwise       public GitHub source archive (ILSON_SOURCE_REF, default main)
#
# Design: coldbyte-vault wiki/plans/2026-09-05-ilson-init-원커맨드-온보딩-설계.md
# User-facing strings are Korean on purpose; code comments stay English.

set -eu

# --- knobs ------------------------------------------------------------------
ILSON_DIST_BASE="${ILSON_DIST_BASE:-}"          # optional custom distribution host
ILSON_SRC="${ILSON_SRC:-}"                      # local dir or .tar.gz — wins over ILSON_DIST_BASE
ILSON_VERSION="${ILSON_VERSION:-latest}"
CLI_DIR="${ILSON_CLI_DIR:-$HOME/.ilson-cli}"
BIN_DIR="${ILSON_BIN_DIR:-$HOME/.local/bin}"
BOX_HOME="${ILSON_HOME:-$HOME/ilson}"           # the box itself — must never be the CLI dir
CODE=""
PASS_SANDBOX=""                                 # forwarded to `ilson setup` — safe rehearsal
CLI_ONLY=0
TMP=""

# --- output helpers ---------------------------------------------------------
say()  { printf '  %s\n' "$1"; }
ok()   { printf '  ✅ %s\n' "$1"; }
die()  { printf '\n❌ %s\n' "$1" >&2; exit 1; }
has()  { command -v "$1" >/dev/null 2>&1; }

cleanup() { [ -n "$TMP" ] && [ -d "$TMP" ] && rm -rf "$TMP"; }
trap cleanup EXIT INT TERM

while [ $# -gt 0 ]; do
    case "$1" in
        --code)    CODE="${2:-}"; shift ;;
        --dir)     CLI_DIR="${2:-}"; shift ;;
        --sandbox) PASS_SANDBOX="--sandbox" ;;
        --cli-only) CLI_ONLY=1 ;;
        *) die "모르는 옵션: $1" ;;
    esac
    shift
done

printf '\n일손 설치 — %s\n\n' "$(date '+%Y-%m-%d %H:%M')"

# --- 1. preflight -----------------------------------------------------------
printf '[1] 사전 점검\n'
[ "$(uname -s)" = "Darwin" ] || die "이 설치기는 맥에서만 돕니다 (지금: $(uname -s))"
ok "맥 $(sw_vers -productVersion 2>/dev/null || echo '')"

case "$(uname -m)" in
    arm64) ok "애플 실리콘" ;;
    *)     say "⚠️  인텔 맥입니다 — 돌지만 느릴 수 있어요" ;;
esac

has curl || die "curl 이 없습니다"
has tar  || die "tar 가 없습니다"
ok "curl · tar"

# Guard: the CLI must never land on top of the box, or init would overwrite it.
[ "$CLI_DIR" != "$BOX_HOME" ] || die "설치 위치가 박스 자리와 같습니다 ($CLI_DIR) — --dir 로 다른 곳을 지정하세요"
[ "$CLI_DIR" != "$HOME" ]     || die "설치 위치가 홈 폴더입니다 — --dir 로 다른 곳을 지정하세요"

# Guard: refuse to replace a directory that is not a previous ilson install.
if [ -e "$CLI_DIR" ] && [ ! -f "$CLI_DIR/ilson" ]; then
    die "$CLI_DIR 가 이미 있는데 일손 설치본이 아닙니다 — 확인 후 직접 지우거나 --dir 를 쓰세요"
fi

# --- 2. fetch ---------------------------------------------------------------
printf '\n[2] 내려받기\n'
TMP="$(mktemp -d)"
STAGE="$TMP/stage"
mkdir -p "$STAGE"

if [ -n "$ILSON_SRC" ]; then
    if [ -d "$ILSON_SRC" ]; then
        # Copy the shipped unit only — never the dev leftovers (.sandbox/, .moai/, .git/).
        # The tarball path is clean by construction (built with `git archive`, see README).
        # `if` (not `&&`): a trailing false test would end the loop non-zero and
        # `set -e` would abort the installer silently.
        for item in ilson template README.md docs; do
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
    curl -fsSL "$URL" -o "$TMP/ilson.tar.gz" || die "내려받기 실패: $URL"
    tar -xzf "$TMP/ilson.tar.gz" -C "$STAGE" --strip-components 1 2>/dev/null \
        || tar -xzf "$TMP/ilson.tar.gz" -C "$STAGE"
    ok "$URL"
else
    # Public source archive: no GitHub login, Git or pairing code is needed.
    REF="${ILSON_SOURCE_REF:-main}"
    curl -fsSL --connect-timeout 10 --max-time 120 \
        "https://codeload.github.com/jakeparkcolde/ilson-box/tar.gz/$REF" \
        -o "$TMP/ilson.tar.gz" || die "GitHub 다운로드 실패 — 연결 확인 후 다시 실행하세요"
    tar -xzf "$TMP/ilson.tar.gz" -C "$STAGE" --strip-components 1 \
        || die "GitHub 설치 묶음을 풀 수 없습니다"
    ok "GitHub 일손 Box 소스 다운로드"
fi

# The CLI and its template are one unit — a half-copy would fail later, inside init.
[ -f "$STAGE/ilson" ]                || die "받은 것에 ilson 이 없습니다"
[ -f "$STAGE/template/CLAUDE.md" ]   || die "받은 것에 template/ 이 없습니다 (ilson 은 template 없이 못 돕니다)"
ok "구성 확인 (ilson + template)"

# --- 3. install -------------------------------------------------------------
printf '\n[3] 설치\n'
rm -rf "$CLI_DIR"
mkdir -p "$(dirname "$CLI_DIR")"
mv "$STAGE" "$CLI_DIR"
chmod +x "$CLI_DIR/ilson"
ok "$CLI_DIR"

# --- 4. link + PATH ---------------------------------------------------------
printf '\n[4] 명령 등록\n'
mkdir -p "$BIN_DIR"
ln -sf "$CLI_DIR/ilson" "$BIN_DIR/ilson"
ok "$BIN_DIR/ilson"

case ":$PATH:" in
    *":$BIN_DIR:"*)
        ok "PATH 에 이미 있음"
        ;;
    *)
        PROFILE="$HOME/.zprofile"
        LINE="export PATH=\"$BIN_DIR:\$PATH\""
        if [ -f "$PROFILE" ] && grep -Fqs "$LINE" "$PROFILE"; then
            ok "PATH 줄이 이미 있음 ($PROFILE)"
        else
            printf '\n# ilson\n%s\n' "$LINE" >> "$PROFILE"
            ok "PATH 추가 ($PROFILE)"
        fi
        say "이 터미널에서 바로 쓰려면: export PATH=\"$BIN_DIR:\$PATH\""
        PATH="$BIN_DIR:$PATH"
        export PATH
        ;;
esac

# --- 5. next ----------------------------------------------------------------
printf '\n설치 끝 — %s\n' "$("$CLI_DIR/ilson" 2>/dev/null | head -1 || echo 'ilson')"

if [ "$CLI_ONLY" = "1" ]; then
    say "CLI만 설치했습니다. 기본 구성 시작: $CLI_DIR/ilson setup"
    exit 0
fi

printf '\n이어서 도구와 박스 기본 구성을 준비합니다.\n'
set -- "$CLI_DIR/ilson" setup
[ -z "$CODE" ] || set -- "$@" --code "$CODE"
[ -z "$PASS_SANDBOX" ] || set -- "$@" --sandbox
# Do not exec here: the installer EXIT trap must clean its download directory.
# curl | sh has a pipe on stdin. Use a controlling terminal when available,
# otherwise setup reports steps that require a person and exits without waiting.
if [ -z "$PASS_SANDBOX" ] && ( : </dev/tty ) 2>/dev/null; then
    "$@" </dev/tty
else
    "$@"
fi
