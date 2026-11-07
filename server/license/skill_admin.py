"""Instructor-only localhost review screen for skill sharing.

Run locally: python3 server/license/skill_admin.py
The administrator secret is entered interactively and is not written to disk.
"""
import getpass
import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import secrets
import sys
import urllib.error
import urllib.request

API = 'https://ilson-license.vercel.app/api/v1/skill-'
PAGE = r'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>스킬 나눔 검토</title><style nonce="NONCE">body{font:16px system-ui;max-width:900px;margin:2rem auto;padding:0 1rem}article{border:1px solid #aaa;border-radius:8px;padding:1rem;margin:1rem 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f4f1;padding:1rem}button{padding:.5rem;margin:.25rem}#error{color:#a00}</style></head><body><h1>스킬 나눔</h1><p>내용을 검토한 뒤 승인·반려하거나 공유를 내립니다. 25건씩 표시됩니다.</p><button id="refresh">새로고침</button><button id="prev">이전</button><button id="next">다음</button><span id="page"></span><p id="error" role="alert"></p><div id="items"></div><script nonce="NONCE">
const token='TOKEN';let offset=0;
async function call(action,id){const r=await fetch('/api/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-Ilson-Session':token},body:JSON.stringify({id,offset})});const j=await r.json();if(!r.ok||j.status!=='ok')throw Error('요청 실패: '+(j.status||'연결 오류'));return j;}
function el(tag,text){const e=document.createElement(tag);e.textContent=text;return e;}
async function refresh(){try{document.querySelector('#error').textContent='';const data=await call('list');document.querySelector('#page').textContent=' '+(Math.floor(offset/25)+1)+'쪽';const area=document.querySelector('#items');area.replaceChildren();for(const item of data.items){const box=el('article','');box.append(el('h2',item.name),el('p',`${item.cohort}기 · ${item.alias} · ${item.status} · ${item.id}`));for(const [name,content] of Object.entries(item.files)){box.append(el('h3',name),el('pre',content));}for(const action of (item.status==='pending'?['approve','reject','withdraw']:item.status==='approved'?['withdraw']:[])){const button=el('button',({approve:'승인',reject:'반려',withdraw:'내리기'})[action]);button.onclick=async()=>{if(!confirm('이 스킬을 '+button.textContent+'할까요?'))return;try{await call(action,item.id);await refresh();}catch(e){document.querySelector('#error').textContent=e.message;}};box.append(button);}area.append(box);}}catch(e){document.querySelector('#error').textContent=e.message;}}
document.querySelector('#refresh').onclick=refresh;document.querySelector('#prev').onclick=()=>{offset=Math.max(0,offset-25);refresh();};document.querySelector('#next').onclick=()=>{offset+=25;refresh();};refresh();
</script></body></html>'''

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def remote(action, secret, ident, offset=0):
    nonce = secrets.token_hex(16)
    body = json.dumps({'nonce':nonce, 'id':ident, 'offset':offset}).encode()
    req = urllib.request.Request(API + 'admin-' + action, body,
        {'Content-Type':'application/json', 'Cache-Control':'no-store', 'X-Ilson-Admin':secret}, method='POST')
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=5) as response:
            result = json.loads(response.read(8 * 1024 * 1024))
        if result.get('nonce') != nonce or result.get('status') != 'ok':
            raise ValueError('bad response')
        return result
    except (ValueError, OSError, TypeError):
        return {'status':'unavailable'}


class ReviewServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, secret):
        super().__init__(('127.0.0.1', 0), Handler)
        self.secret = secret
        self.token = secrets.token_urlsafe(32)
        self.origin = 'http://127.0.0.1:' + str(self.server_port)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, data, content_type='application/json; charset=utf-8'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'nonce-"+self.server.token+"'; style-src 'nonce-"+self.server.token+"'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def host_ok(self):
        return self.headers.get('Host') == '127.0.0.1:' + str(self.server.server_port)

    def do_GET(self):
        if not self.host_ok() or self.path != '/':
            return self.reply(404, b'{}')
        page = PAGE.replace('NONCE', self.server.token).replace('TOKEN', self.server.token)
        self.reply(200, page.encode(), 'text/html; charset=utf-8')

    def do_POST(self):
        if not self.host_ok() or self.headers.get('Origin') != self.server.origin or not hmac.compare_digest(self.headers.get('X-Ilson-Session',''), self.server.token):
            return self.reply(403, b'{}')
        action = self.path.removeprefix('/api/')
        if action not in ('list','approve','reject','withdraw') or self.path != '/api/' + action:
            return self.reply(404, b'{}')
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 1024: raise ValueError()
            body = json.loads(self.rfile.read(length))
            ident = body.get('id')
            offset = body.get('offset', 0)
            if type(offset) is not int or not 0 <= offset <= 1000000: raise ValueError()
            if action != 'list' and (not isinstance(ident,str) or len(ident) != 36): raise ValueError()
        except (ValueError, TypeError, AttributeError):
            return self.reply(400, b'{}')
        result = remote(action, self.server.secret, ident, offset)
        self.reply(200 if result['status']=='ok' else 503, json.dumps(result, ensure_ascii=False).encode())


def main():
    if not sys.stdin.isatty():
        print('강사 터미널에서 직접 관리자 비밀을 입력해야 합니다.',file=sys.stderr)
        return 1
    secret = getpass.getpass('관리자 비밀: ')
    if not secret: return 1
    server = ReviewServer(secret)
    print('스킬 나눔 검토:', server.origin, '\n종료: Ctrl-C', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0

if __name__ == '__main__':
    sys.exit(main())
