#!/bin/bash
# 배포된 코드만 갱신한다. vault/state/설정과 고객 예약 업무는 변경하지 않는다.
set -eu
cli_root="${ILSON_CLI_DIR:-$HOME/.ilson-cli}"
[ -f "$cli_root/tools/update.py" ] || { echo '새 업데이트 도구를 최초 한 번 설치해야 합니다.' >&2; exit 1; }
# Scheduled run only: a box without an update address skips instead of failing every day.
# Older update.py versions ignore this variable.
export ILSON_UPDATE_SKIP_IF_NO_FEED=1
exec python3 "$cli_root/tools/update.py" --home "${ILSON_HOME:-$HOME/ilson}" --cli "$cli_root" "$@"
