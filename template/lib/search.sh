#!/bin/bash
# Box search boundary: one bounded request, no interactive login or raw errors.
set -u
fail() { printf '%s\n' "$1" >&2; exit "${2:-1}"; }
box_home="${ILSON_HOME:-$HOME/ilson}"
[ ! -f "$box_home/state/sandbox" ] || fail '샌드박스에서는 외부 검색을 실행하지 않습니다.'
[ "$#" -ge 1 ] && [ "$#" -le 3 ] || fail '사용법: bash lib/search.sh "검색어" [general|news] [day|week|month|year|all]' 2
query="$1"; topic="${2:-general}"; period="${3:-week}"
[ -n "$query" ] && [ "${#query}" -le 400 ] || fail '검색어는 1~400자입니다.' 2
# A leading dash must not turn user text into a CLI flag.
case "$query" in -*) fail '검색어는 옵션(-)으로 시작할 수 없습니다.' 2 ;; esac
case "$topic" in general|news) ;; *) fail '검색 종류는 general 또는 news입니다.' 2 ;; esac
case "$period" in day|week|month|year|all) ;; *) fail '검색 기간은 day/week/month/year/all입니다.' 2 ;; esac
# Outbound egress DLP: block control chars/newlines and high-confidence secret patterns before external search.
if ! printf '%s' "$query" | python3 -c '
import re, sys
q = sys.stdin.read()
patterns = (
    r"[\x00-\x1f\x7f]",
    r"sk-ant-",
    r"sk-[A-Za-z0-9_-]{16,}",
    r"ghp_[A-Za-z0-9]{20,}",
    r"github_pat_",
    r"AIza[A-Za-z0-9_-]{20,}",
    r"xox[baprs]-",
    r"AKIA[0-9A-Z]{16}",
    r"eyJ[A-Za-z0-9_-]{10,}\.eyJ",
    r"(?:^|[^A-Za-z0-9])(?:bot)?[0-9]{7,12}:[A-Za-z0-9_-]{25,}",
    r"BEGIN [A-Z ]*PRIVATE KEY",
    r"Bearer [A-Za-z0-9._-]{16,}",
)
for pat in patterns:
    if re.search(pat, q):
        sys.exit(1)
sys.exit(0)
'; then
    fail '검색어에 민감한 인증 정보 형식이 포함되어 외부 검색을 차단했습니다.' 2
fi
cfile="${ILSON_SEARCH_COUNTER_FILE:-}"
_search_counter_op() {
    local mode="$1" path="$2"
    [ -f "$path" ] && [ ! -L "$path" ] || return 4
    python3 -c '
import fcntl, os, stat, sys
mode, path = sys.argv[1], sys.argv[2]
flags = os.O_RDONLY if mode == "check" else os.O_RDWR
if hasattr(os, "O_NOFOLLOW"):
    flags |= os.O_NOFOLLOW
try:
    fd = os.open(path, flags)
except OSError:
    sys.exit(4)
try:
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):
        sys.exit(4)
    fcntl.flock(fd, fcntl.LOCK_SH if mode == "check" else fcntl.LOCK_EX)
    raw = os.read(fd, 64).decode("ascii", errors="strict").strip()
    if not raw or not raw.isdigit():
        sys.exit(4)
    count = int(raw, 10)
    if count >= 3:
        sys.exit(3)
    if mode == "inc":
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        os.write(fd, f"{count + 1}\n".encode("ascii"))
    sys.exit(0)
except Exception:
    sys.exit(4)
finally:
    os.close(fd)
' "$mode" "$path"
}
if [ -n "$cfile" ]; then
    _search_counter_op check "$cfile"
    c_rc=$?
    if [ "$c_rc" -eq 3 ]; then
        fail '예약 업무당 외부 검색은 최대 3회까지 허용됩니다.' 2
    elif [ "$c_rc" -ne 0 ]; then
        fail '검색 횟수 추적 파일이 유효하지 않아 외부 검색을 차단했습니다.' 2
    fi
fi
for tool in tvly jq gtimeout; do
    command -v "$tool" >/dev/null 2>&1 || fail "검색 도구 없음: $tool — ilson setup 을 실행하세요."
done
limit="${ILSON_SEARCH_TIMEOUT:-45}"
case "$limit" in ''|*[!0-9]*) fail '검색 시간 제한이 잘못되었습니다.' 2 ;; esac
[ "$limit" -gt 0 ] && [ "$limit" -le 45 ] || fail '검색 시간 제한은 1~45초입니다.' 2
if [ -n "$cfile" ]; then
    _search_counter_op inc "$cfile"
    c_rc=$?
    if [ "$c_rc" -eq 3 ]; then
        fail '예약 업무당 외부 검색은 최대 3회까지 허용됩니다.' 2
    elif [ "$c_rc" -ne 0 ]; then
        fail '검색 횟수 추적 파일이 유효하지 않아 외부 검색을 차단했습니다.' 2
    fi
fi
# Keep stderr private: provider errors can contain credential-bearing URLs.
# macOS Bash 3.2의 set -u에서는 빈 배열 확장도 오류다. 위치 인자로 조립한다.
set -- tvly search "$query" --depth basic --max-results 5 --topic "$topic" --json
[ "$period" = all ] || set -- "$@" --time-range "$period"
if ! result=$(gtimeout -k 2 "$limit" "$@" </dev/null 2>/dev/null); then
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
