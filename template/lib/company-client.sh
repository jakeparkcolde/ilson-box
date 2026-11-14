#!/bin/sh
# Bootstrap for a standard employee account; no installer, brew or launchctl.
case "${1:-}" in
    company) shift; exec python3 "$(dirname "$0")/company.py" "$@" ;;
    *) printf '%s\n' '사용법: ilson company join --id <회사ID>'; exit 2 ;;
esac
