#!/bin/sh
# ilson installer — the one line a customer pastes into Terminal.
#
#   curl -fsSL https://<host>/install.sh | sh
#   curl -fsSL https://<host>/install.sh | sh -s -- --code ABCD-1234
#
# What it does (no sudo, no password):
#   1. preflight   macOS · Apple Silicon · curl · tar
#   2. fetch       ilson CLI + template/ (they must stay together — ilson reads $SELF_DIR/template)
#   3. install     -> $CLI_DIR (default ~/.ilson-cli), kept apart from the box itself (~/ilson)
#   4. link        -> $BIN_DIR/ilson (default ~/.local/bin), PATH appended to ~/.zprofile if missing
#   5. next        prints `ilson init --code XXXX-XXXX`, or runs it when --code was given
#
# Sources, in order of precedence:
#   ILSON_SRC        local directory or tarball  (testing today, before a host exists)
#   ILSON_DIST_BASE  https base serving ilson-<version>.tar.gz  (production, host TBD)
#
# Design: coldbyte-vault wiki/plans/2026-09-05-ilson-init-원커맨드-온보딩-설계.md
# User-facing strings are Korean on purpose; code comments stay English.

set -eu

# --- knobs ------------------------------------------------------------------
ILSON_DIST_BASE="${ILSON_DIST_BASE:-}"          # TODO: fill in when the download host is decided
ILSON_SRC="${ILSON_SRC:-}"                      # local dir or .tar.gz — wins over ILSON_DIST_BASE
ILSON_VERSION="${ILSON_VERSION:-latest}"
CLI_DIR="${ILSON_CLI_DIR:-$HOME/.ilson-cli}"
BIN_DIR="${ILSON_BIN_DIR:-$HOME/.local/bin}"
BOX_HOME="${ILSON_HOME:-$HOME/ilson}"           # the box itself — must never be the CLI dir
CODE=""
PASS_SANDBOX=""                                 # forwarded to `ilson init` — safe rehearsal
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
    die "받아올 주소가 없습니다. 배포 주소가 정해지기 전에는 ILSON_SRC 로 시험하세요:
     ILSON_SRC=/경로/ilson-box sh install.sh"
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

if [ -n "$CODE" ]; then
    printf '\n이어서 박스를 짓습니다 (코드 %s%s)\n\n' "$CODE" \
        "$( [ -n "$PASS_SANDBOX" ] && echo ' · 샌드박스' )"
    if [ -n "$PASS_SANDBOX" ]; then
        exec "$CLI_DIR/ilson" init --code "$CODE" --sandbox
    fi
    exec "$CLI_DIR/ilson" init --code "$CODE"
fi

cat <<EOF

다음 한 줄을 실행하세요 (설치 안내문에 적힌 코드로):

    ilson init --code XXXX-XXXX

먼저 상태만 보고 싶으면:

    ilson doctor

EOF
