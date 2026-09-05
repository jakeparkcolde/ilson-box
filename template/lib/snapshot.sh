#!/bin/bash
# snapshot.sh — commit vault/ and state/ into the box-local git repo every 10 minutes.
# This is the recovery line for torn writes and bad edits (restore = git checkout).
# Local only; never pushes.

source "$(dirname "$0")/common.sh"

cd "$ILSON_HOME" || exit 1
[ -d .git ] || { git init -q && printf 'logs/\nstate/pairing.json\n' > .gitignore; }
git add -A vault state .gitignore 2>/dev/null
if ! git diff --cached --quiet; then
    git commit -q -m "snapshot $(date '+%Y-%m-%d %H:%M')" && log snapshot "committed"
fi
mark_run snapshot
