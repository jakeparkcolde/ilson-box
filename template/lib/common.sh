#!/bin/bash
# common.sh — shared paths, logging, and pairing lookup for box jobs.
# Sourced by every script in lib/. Never prints secrets.

set -u

# Absolute lib dir — callers cd elsewhere, so never build sibling paths from $0.
LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ILSON_HOME="${ILSON_HOME:-$HOME/ilson}"
VAULT="$ILSON_HOME/vault"
STATE="$ILSON_HOME/state"
LOGS="$ILSON_HOME/logs"
PAIRING="$STATE/pairing.json"
mkdir -p "$LOGS" "$STATE"

# log <job> <message> — one line per event, rotated by size in watchdog.sh
log() { printf '%s [%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" "$2" >> "$LOGS/$1.log"; }

# pairing_get <key> — read one field from pairing.json (empty when unpaired)
pairing_get() { [ -f "$PAIRING" ] && jq -r --arg k "$1" '.[$k] // empty' "$PAIRING" 2>/dev/null; }

# company_name — from CONTEXT.md, falls back to "우리 회사"
company_name() {
    local n; n=$(grep -m1 '^- 회사명:' "$VAULT/CONTEXT.md" 2>/dev/null | sed 's/^- 회사명: *//')
    case "$n" in ""|"("*) echo "우리 회사" ;; *) echo "$n" ;; esac
}

# mark_run <job> — stamp last successful run (watchdog reads these)
mark_run() { date +%s > "$STATE/last-run.$1"; }
