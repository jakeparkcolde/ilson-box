#!/bin/bash
# run-job.sh <command-name> — run one headless Claude job and deliver its output.
#   command-name ∈ briefing | weekly | tidy  (a file in ~/.claude/commands/ or $ILSON_HOME/claude/commands/)
# Guards: max turns, wall-clock timeout, output cap, failure notification. Never prompts.

source "$(dirname "$0")/common.sh"

name="${1:?command name}"
today=$(date '+%Y-%m-%d')
out="$LOGS/$name.$today.out"
MAX_TURNS="${ILSON_MAX_TURNS:-12}"
TIMEOUT_S="${ILSON_JOB_TIMEOUT:-600}"

cd "$ILSON_HOME" || exit 1
log "$name" "start (max_turns=$MAX_TURNS timeout=${TIMEOUT_S}s)"

# claude -p runs the slash command non-interactively; cwd is the box so CLAUDE.md
# and vault/ are in scope. acceptEdits auto-approves file edits inside the box
# (path-pattern allow rules in settings.json were NOT honored in -p mode — measured
# 2026-09-05); everything else still follows settings.json deny rules.
if command -v timeout >/dev/null 2>&1; then T="timeout $TIMEOUT_S"; else T=""; fi
if $T claude -p "/$name $today" --max-turns "$MAX_TURNS" --output-format text --permission-mode acceptEdits > "$out" 2>"$LOGS/$name.$today.err"; then
    mark_run "$name"
    log "$name" "ok ($(wc -c < "$out" | tr -d ' ') bytes)"
    "$LIB_DIR/notify.sh" "$name" < "$out"
else
    rc=$?
    log "$name" "FAILED rc=$rc: $(tail -c 300 "$LOGS/$name.$today.err" | tr '\n' ' ')"
    tail -c 600 "$LOGS/$name.$today.err" | "$LIB_DIR/notify.sh" "$name" --fail
    exit $rc
fi
