"""일손 관리자 시험 서버. AI 호출은 프로세스 내부 가짜로 대체한다."""
import runpy
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'template/lib'))
import inbox_extract
original=inbox_extract.extract
inbox_extract.extract=lambda home,name,digest,consent: original(home,name,digest,consent,lambda *_:{'draft':'가상 금액 1234원','evidence':'첫 페이지 가상 금액'})
runpy.run_path(str(ROOT/'tests/fixtures/admin_navigation_server.py'),run_name='__main__')
