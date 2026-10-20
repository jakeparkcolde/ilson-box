#!/bin/bash
set -euo pipefail
KIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI_DIR="$HOME/.ilson-cli"
BOX_DIR="$HOME/ilson"
export ILSON_HOME="$BOX_DIR"
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
fail() { printf '\n설치 중단: %s\n' "$1" >&2; exit 1; }
case "${1:-}" in ""|--check) ;; *) fail "사용법: bash install-intel.command [--check]" ;; esac
[ "$(uname -s)" = Darwin ] || fail 'macOS용 설치 묶음입니다.'
case "$(uname -m)" in arm64|x86_64) ;; *) fail '지원하지 않는 CPU입니다.' ;; esac
cd "$KIT_DIR"
shasum -a 256 -c SHA256SUMS >/dev/null || fail '묶음 파일이 변경되었거나 손상되었습니다. 다시 복사하세요.'
if [ "${1:-}" = --check ]; then
    printf '묶음 체크섬 확인 완료 · CPU %s · macOS %s · 실제 설치는 실행하지 않았습니다.\n' "$(uname -m)" "$(sw_vers -productVersion)"
    exit 0
fi
if [ -f "$CLI_DIR/.intel-kit-complete" ]; then
    printf '이미 이 묶음으로 설치를 완료했습니다. ilson open으로 여세요.\n'
    exit 0
fi
if [ -e "$CLI_DIR" ]; then
    [ ! -L "$CLI_DIR" ] && [ -f "$CLI_DIR/.intel-kit-pending" ] && [ "$(cat "$CLI_DIR/.intel-kit-pending")" = '2026.10.16.3' ] || fail '기존 설치는 보존했습니다. 기존 일손에서는 ilson update를 사용하세요.'
else
    [ ! -e "$BOX_DIR" ] && [ ! -L "$BOX_DIR" ] || fail '~/ilson이 이미 있어 보존했습니다. 기존 설치 여부를 먼저 확인하세요.'
    [ ! -e "$HOME/.local/bin/ilson" ] && [ ! -L "$HOME/.local/bin/ilson" ] || fail "기존 ilson 명령이 있어 보존했습니다."
    ILSON_SRC="$KIT_DIR/cli" ILSON_CLI_DIR="$CLI_DIR" ILSON_BIN_DIR="$HOME/.local/bin" sh "$KIT_DIR/install.sh" --cli-only
    printf '2026.10.16.3' > "$CLI_DIR/.intel-kit-pending"
fi
"$CLI_DIR/ilson" setup
# Apply the included verified release locally; initial installation needs no Tailscale connection.
python3 "$CLI_DIR/tools/update.py" --home "$BOX_DIR" --cli "$CLI_DIR" \
    --manifest "$KIT_DIR/release/release-2026.10.16.3.json" \
    --archive "$KIT_DIR/release/ilson-box-2026.10.16.3.zip"
claude --version
codex --version
"$CLI_DIR/ilson" llm
mv "$CLI_DIR/.intel-kit-pending" "$CLI_DIR/.intel-kit-complete"
printf '\n일손 기본 설치 완료. Claude/Codex 로그인은 이 컴퓨터에서 직접 진행하세요.\n'
printf '화면 열기: ~/.local/bin/ilson open\n기본 AI 변경: ~/.local/bin/ilson llm codex\n'
printf '예약 업무와 노트북 절전 설정은 자동으로 켜거나 바꾸지 않았습니다.\n'
