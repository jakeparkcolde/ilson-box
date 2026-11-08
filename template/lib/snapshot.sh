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
for learning_temporary in '/vault/.ilson-learning/lock' '/vault/.ilson-learning/.ilson-*' '/vault/.ilson-learning/rollback/.ilson-*' '/vault/lessons/.ilson-*'; do
    if ! grep -Fxq "$learning_temporary" .gitignore 2>/dev/null; then
        printf '%s\n' "$learning_temporary" >> .gitignore || exit 1
    fi
done
tracked_admin=$(git ls-files -- state/web-admin) || exit 1
if [ -n "$tracked_admin" ]; then
    log snapshot "FAILED: web manager credentials are tracked; review local backup before continuing"
    exit 1
fi
# License serial and device identity must never enter the local recovery repository.
if ! grep -Fxq '/state/license/' .gitignore 2>/dev/null; then
    printf '\n/state/license/\n' >> .gitignore || exit 1
fi
tracked_license=$(git ls-files -- state/license) || exit 1
[ -z "$tracked_license" ] || { log snapshot "FAILED: license credentials are tracked; review local backup"; exit 1; }
git check-ignore --quiet state/license/serial || { log snapshot "FAILED: license credentials are not excluded"; exit 1; }
# SNS 비밀과 실행 장부는 볼트/보고서 백업과 분리한다.
for private in .credentials .workspace .approval; do
    if ! grep -Fxq "/$private/" .gitignore 2>/dev/null; then
        printf '\n/%s/\n' "$private" >> .gitignore || exit 1
    fi
    tracked=$(git ls-files -- "$private") || exit 1
    [ -z "$tracked" ] || { log snapshot "FAILED: private workspace files are tracked"; exit 1; }
done
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
