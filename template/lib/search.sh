#!/bin/bash
# Box search boundary: one bounded request, no interactive login or raw errors.
set -u
fail() { printf '%s\n' "$1" >&2; exit "${2:-1}"; }
box_home="${ILSON_HOME:-$HOME/ilson}"
[ ! -f "$box_home/state/sandbox" ] || fail '샌드박스에서는 외부 검색을 실행하지 않습니다.'
[ "$#" -ge 1 ] && [ "$#" -le 3 ] || fail '사용법: bash lib/search.sh "검색어" [general|news] [day|week|month|year]' 2
query="$1"; topic="${2:-general}"; period="${3:-week}"
[ -n "$query" ] && [ "${#query}" -le 400 ] || fail '검색어는 1~400자입니다.' 2
# A leading dash must not turn user text into a CLI flag.
case "$query" in -*) fail '검색어는 옵션(-)으로 시작할 수 없습니다.' 2 ;; esac
case "$topic" in general|news) ;; *) fail '검색 종류는 general 또는 news입니다.' 2 ;; esac
case "$period" in day|week|month|year) ;; *) fail '검색 기간은 day/week/month/year입니다.' 2 ;; esac
for tool in tvly jq gtimeout; do
    command -v "$tool" >/dev/null 2>&1 || fail "검색 도구 없음: $tool — ilson setup 을 실행하세요."
done
limit="${ILSON_SEARCH_TIMEOUT:-45}"
case "$limit" in ''|*[!0-9]*) fail '검색 시간 제한이 잘못되었습니다.' 2 ;; esac
[ "$limit" -gt 0 ] && [ "$limit" -le 45 ] || fail '검색 시간 제한은 1~45초입니다.' 2
# Keep stderr private: provider errors can contain credential-bearing URLs.
if ! result=$(gtimeout -k 2 "$limit" tvly search "$query" --depth basic --max-results 5 \
    --topic "$topic" --time-range "$period" --json </dev/null 2>/dev/null); then
    fail '검색 미완료: 도구 오류·시간 초과·인증/한도를 확인하세요. 자동 로그인이나 재시도는 하지 않았습니다.'
fi
if ! printf '%s' "$result" | jq -e '
    type == "object" and (.results | type == "array") and
    all(.results[]; (.title | type == "string") and (.url | type == "string") and
        (.url | test("^https?://")) and (.content | type == "string"))
    ' >/dev/null 2>&1; then
    fail '검색 응답 형식 오류: 검색 결과를 확인할 수 없습니다.'
fi
# Empty results are valid; do not turn malformed/error responses into emptiness.
printf '%s' "$result" | jq '{results: [.results[:5][] |
    {title, url, content: .content[:6000]} +
    (if (.published_date | type) == "string" then {published_date} else {} end)]}'
