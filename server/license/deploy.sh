#!/bin/sh
# Operator-run only after independent review and authorized resource creation.
# Stages a production build without assigning its domain; promotion is separate.
set -eu
[ "${ILSON_LICENSE_REVIEW_PASSED:-}" = yes ] || { printf '%s\n' '검수 통과를 확인한 총괄만 실행하세요.' >&2; exit 1; }
cd "$(dirname "$0")"
python3 preflight.py --server
command -v vercel >/dev/null 2>&1 || { printf '%s\n' 'Vercel CLI가 필요합니다.' >&2; exit 1; }
vercel build --prod
vercel deploy --prebuilt --prod --skip-domain
printf '%s\n' '스테이징 URL을 검증한 뒤 승인된 절차로 vercel promote를 실행하세요.'
