#!/bin/bash
# update.sh — pull our layer (lib/, claude/commands, launchd/, CLAUDE.md) from the
# update repo named in pairing.json. v0: plain git pull into $ILSON_HOME/template,
# then re-copy. Customer approval before apply is a v1 item (Telegram button).
# Never touches vault/ or state/.

source "$(dirname "$0")/common.sh"

repo=$(pairing_get update_repo)
[ -z "$repo" ] && { log update "skipped: no update_repo in pairing"; exit 0; }

src="$ILSON_HOME/template"
if [ -d "$src/.git" ]; then
    before=$(git -C "$src" rev-parse --short HEAD)
    git -C "$src" pull -q --ff-only || { log update "pull failed"; exit 1; }
    after=$(git -C "$src" rev-parse --short HEAD)
else
    git clone -q "$repo" "$src" || { log update "clone failed"; exit 1; }
    before=none; after=$(git -C "$src" rev-parse --short HEAD)
fi

if [ "$before" != "$after" ] || [ -f "$STATE/update-pending" ]; then
    # pull 뒤 복사/관리자 재시작이 실패해도 다음 점검에서 같은 리비전을 다시 적용한다.
    touch "$STATE/update-pending" || exit 1
    cp -R "$src/template/lib/." "$ILSON_HOME/lib/" || { log update "library copy failed"; exit 1; }
    # Permissions/skills are part of our layer too. Custom commands and the
    # customer's settings.local.json remain; no source file overwrites them.
    cp -R "$src/template/claude/." "$ILSON_HOME/.claude/" || { log update "commands copy failed"; exit 1; }
    cp "$src/template/CLAUDE.md" "$ILSON_HOME/CLAUDE.md" || { log update "rules copy failed"; exit 1; }
    if [ -d "$src/template/web" ]; then
        [ ! -L "$ILSON_HOME/web" ] || { log update "web folder is a symlink"; exit 1; }
        mkdir -p "$ILSON_HOME/web" && cp -R "$src/template/web/." "$ILSON_HOME/web/" || { log update "web copy failed"; exit 1; }
        cp "$src/template/open.command" "$ILSON_HOME/일손 열기.command" && chmod 700 "$ILSON_HOME/일손 열기.command" || exit 1
        # 이미 설치한 관리 화면만 갱신한다. 브라우저·예약 업무를 새로 열지 않는다.
        if [ -f "$STATE/web-admin/config.json" ] && [ -f "$STATE/web-admin/enabled" ] && [ ! -f "$STATE/sandbox" ]; then
            python3 "$ILSON_HOME/lib/web-admin.py" install --home "$ILSON_HOME" || { log update "web manager refresh failed"; exit 1; }
        fi
    fi
    rm -f "$STATE/update-pending" || exit 1
    log update "applied $before → $after"
    printf '일손 업데이트 적용: %s → %s' "$before" "$after" | "$LIB_DIR/notify.sh" update
else
    log update "up to date ($after)"
fi
mark_run update
