#!/bin/bash
set -euo pipefail
case "${1:-}" in ''|--check) ;; *) echo '사용법: bash install.sh [--check]' >&2; exit 1 ;; esac
[ "$(uname -s)" = Darwin ] || { echo 'macOS용 설치 프로그램입니다.' >&2; exit 1; }
case "$(uname -m)" in x86_64|arm64) ;; *) echo '지원하지 않는 CPU입니다.' >&2; exit 1 ;; esac
if [ "${1:-}" != --check ]; then
  if ! ( : </dev/tty ) 2>/dev/null; then
    echo '맥의 터미널 앱에서 실행해 주세요. 설치 중 관리자 암호와 로그인이 필요할 수 있습니다.' >&2
    exit 1
  fi
fi
KIT_URL='https://macmini.tailb24b18.ts.net:10000/assets/ilson-install/2026.10.16.3/ilson-intel-mac-20261016.zip'
KIT_SHA='bd4c7820160537701e9229079b7e15d73e32a0c3896c135205bfc9d2b1e8e6d5'
ILSON_TMP="$(mktemp -d "${TMPDIR:-/tmp}/ilson-install.XXXXXXXX")"
trap 'rm -rf "$ILSON_TMP"' EXIT
printf '일손 Box 2026.10.16.3 설치 묶음을 다운로드합니다…\n'
curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --connect-timeout 20 --max-time 300 --retry 2 "$KIT_URL" -o "$ILSON_TMP/kit.zip"
printf '%s  %s\n' "$KIT_SHA" "$ILSON_TMP/kit.zip" | shasum -a 256 -c - >/dev/null
unzip -q "$ILSON_TMP/kit.zip" -d "$ILSON_TMP"
if [ "${1:-}" = --check ]; then
  bash "$ILSON_TMP/ilson-intel-mac-20261016/install-intel.command" --check
else
  bash "$ILSON_TMP/ilson-intel-mac-20261016/install-intel.command" </dev/tty
fi
