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
  result=research(Q,'all',home,options={'mode':'deep'})
  (ROOT/(provider+'-result.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2))
  print(provider,'OK',result['metrics'],flush=True)
 except Exception as e:
  (ROOT/(provider+'-error.txt')).write_text(traceback.format_exc());print(provider,'FAILED',str(e),flush=True)
with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run,['claude','codex']))
