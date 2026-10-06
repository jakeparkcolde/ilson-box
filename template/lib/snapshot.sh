#!/bin/bash
# snapshot.sh — commit vault/ and state/ into the box-local git repo every 10 minutes.
# This is the recovery line for torn writes and bad edits (restore = git checkout).
# Local only; never pushes.

source "$(dirname "$0")/common.sh"

cd "$ILSON_HOME" || exit 1
[ -d .git ] || { git init -q && printf 'logs/\nstate/pairing.json\n' > .gitignore; } || exit 1
# 2026-10-06: 로컬 웹 관리자의 접속 비밀은 복구용 Git에도 담지 않는다.
# 기존 박스도 갱신하며 고객의 기존 제외 규칙은 보존한다.
[ ! -L .gitignore ] || { log snapshot "FAILED: .gitignore must be a regular file"; exit 1; }
if ! grep -Fxq '/state/web-admin/' .gitignore 2>/dev/null; then
    printf '\n/state/web-admin/\n' >> .gitignore || exit 1
fi
tracked_admin=$(git ls-files -- state/web-admin) || exit 1
if [ -n "$tracked_admin" ]; then
    log snapshot "FAILED: web manager credentials are tracked; review local backup before continuing"
    exit 1
fi
# 무시된 디렉터리를 명시 pathspec에 넣으면 Git이 종료 1을 돌려준다.
# 제외 규칙의 실제 적용을 확인한 뒤 상위 폴더를 수집한다.
git check-ignore --quiet state/web-admin/token || { log snapshot "FAILED: web manager credentials are not excluded"; exit 1; }
git add -A -- vault state .gitignore || exit 1
if ! git diff --cached --quiet; then
    # Box-local backup must work before a person configures their Git identity.
    git -c user.name='Ilson Box' -c user.email='ilson@localhost' -c commit.gpgsign=false \
        commit -q -m "snapshot $(date '+%Y-%m-%d %H:%M')" || { log snapshot "commit failed"; exit 1; }
    log snapshot "committed"
fi
mark_run snapshot
