#!/bin/bash
# snapshot.sh — commit vault/ and state/ into the box-local git repo every 10 minutes.
# This is the recovery line for torn writes and bad edits (restore = git checkout).
# Local only; never pushes.

source "$(dirname "$0")/common.sh"

cd "$ILSON_HOME" || exit 1
[ -d .git ] || { git init -q && printf 'logs/\nstate/pairing.json\n' > .gitignore; } || exit 1
git add -A vault state .gitignore || exit 1
if ! git diff --cached --quiet; then
    # Box-local backup must work before a person configures their Git identity.
    git -c user.name='Ilson Box' -c user.email='ilson@localhost' -c commit.gpgsign=false \
        commit -q -m "snapshot $(date '+%Y-%m-%d %H:%M')" || { log snapshot "commit failed"; exit 1; }
    log snapshot "committed"
fi
mark_run snapshot
