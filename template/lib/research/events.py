"""로그인/기기 권한을 통과한 조사 상태만 SSE로 전달한다. 재접속은 최신 상태부터다."""
import json
import re
import time

try:
    from .run import ResearchError
except ImportError:
    from run import ResearchError


def serve_events(handler,jobs,owner,key):
    reply=getattr(handler,'_json_response',None)
    def error(message,code):
        if reply:reply({'error':message},code)
        else:handler.reply(code,{'error':message})
    if not re.fullmatch(r'[a-f0-9]{32}',key):
        error('조사 기록을 찾지 못했습니다',404);return
    try:
        attached=jobs.subscribe(owner,key)
    except ResearchError as exc:
        error(str(exc),429);return
    if not attached:
        error('조사 기록을 찾지 못했습니다',404);return
    try:
        handler.send_response(200)
        handler.send_header('Content-Type','text/event-stream; charset=utf-8')
        handler.send_header('Cache-Control','no-store')
        handler.send_header('X-Accel-Buffering','no')
        handler.send_header('X-Content-Type-Options','nosniff')
        handler.send_header('Connection','close')
        handler.end_headers()
        handler.close_connection=True
        handler.connection.settimeout(10)
        revision=-1;start=time.monotonic()
        while time.monotonic()-start<600:
            row=jobs.wait(owner,key,revision)
            if not row:break
            if row['revision']!=revision:
                encoded=json.dumps(row,ensure_ascii=False,separators=(',',':')).encode()
                handler.wfile.write(b'event: state\ndata: '+encoded+b'\n\n')
                revision=row['revision']
            else:handler.wfile.write(b': keepalive\n\n')
            handler.wfile.flush()
            if row['stage'] in ('done','error'):break
    except (BrokenPipeError,ConnectionError,TimeoutError):
        # 접속 종료는 조사를 취소하지 않는다. 재접속/폴링으로 최신 검증 문단을 복원한다.
        pass
    finally:jobs.unsubscribe(key)
