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

if [ "$before" != "$after" ]; then
    cp -R "$src/template/lib/." "$ILSON_HOME/lib/"
    # Permissions/skills are part of our layer too. Custom commands and the
    # customer's settings.local.json remain; no source file overwrites them.
    cp -R "$src/template/claude/." "$ILSON_HOME/.claude/"
    cp "$src/template/CLAUDE.md" "$ILSON_HOME/CLAUDE.md"
    log update "applied $before → $after"
    printf '일손 업데이트 적용: %s → %s' "$before" "$after" | "$LIB_DIR/notify.sh" update
else
    log update "up to date ($after)"
fi
mark_run update
