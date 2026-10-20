from pathlib import Path
import sys,json,time,traceback
from concurrent.futures import ThreadPoolExecutor
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'lib'))
from research.engine import research
from research.settings import save
Q='Apple 공식 자료로 기본 M3(2023)와 기본 M4(2024) 14형 MacBook Pro의 기본 메모리, USB-C 포트 수와 규격, 카메라, 외장 화면 2대 연결 조건을 비교해줘. Pro/Max 칩 제외. 현재 가격 제외.'
def run(provider):
 home=ROOT/provider;home.mkdir(exist_ok=True);save(home,provider)
 try:
  result=research(('서울에서 초등 1학년이 참여할 수 있는 독서와 미술·만들기를 연계한 오프라인 수업 사례 3개를 비교해줘. 기관명, 지역, 연령, 회당 시간, 수강료, 책과 활동 연결 방식과 공식 출처를 제시해줘. 2026년 10월 16일 기준 현재 모집과 과거 사례를 구분하고 확인 못한 값은 미확인으로 남겨줘.' if provider=='claude' else Q),'all',home,options={'mode':'deep'})
  (ROOT/(provider+'-result.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2))
  print(provider,'OK',result['metrics'],flush=True)
 except Exception as e:
  (ROOT/(provider+'-error.txt')).write_text(traceback.format_exc());print(provider,'FAILED',str(e),flush=True)
with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run,['claude','codex']))
