#!/bin/bash
# Finder에서 두 번 눌러도 실제 Box 경로를 사용한다. 인증 값은 넣지 않는다.
set -eu
SELF="${BASH_SOURCE[0]}"
while [ -L "$SELF" ]; do
    PARENT="$(cd "$(dirname "$SELF")" && pwd)"
    SELF="$(readlink "$SELF")"
    case "$SELF" in /*) ;; *) SELF="$PARENT/$SELF" ;; esac
done
BOX_DIR="$(cd "$(dirname "$SELF")" && pwd)"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
exec python3 "$BOX_DIR/lib/web-admin.py" open --home "$BOX_DIR"
