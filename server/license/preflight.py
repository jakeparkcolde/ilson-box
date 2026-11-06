"""Read-only deployment preflight. This script does not create or deploy resources."""
import argparse
from pathlib import Path
import sys

parser=argparse.ArgumentParser()
parser.add_argument('--server',action='store_true',help='서버 스테이징 전 검사; URL 확정 전 허용')
args=parser.parse_args()
root=Path(__file__).resolve().parents[2]
text=(root/'template/lib/license.py').read_text()
errors=[]
if 'PUBLIC_KEYS = {}' in text: errors.append('Box 공개키가 아직 지정되지 않았습니다.')
if not args.server and "API_URL = ''" in text: errors.append('Box의 실제 Vercel HTTPS 주소가 아직 지정되지 않았습니다.')
for path in ('server/license/migrations/001_license.sql','server/license/api/v1/[action].js','server/license/issuer.py'):
    if not (root/path).is_file(): errors.append('필수 파일 누락: '+path)
for error in errors: print('미준비:',error)
if errors:
    print('외부 서비스는 생성하거나 변경하지 않았습니다.')
    sys.exit(1)
print('로컬 필수 파일 확인 완료. 배포 승인을 대신하지 않습니다.')
