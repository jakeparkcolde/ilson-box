"""Loopback-only synthetic Naver/Telegram server for the future 1+6 integration test."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading
from urllib.parse import urlsplit

class State:
    def __init__(self):
        self.question = {'questionId': 7, 'question': '합성 문의 원문', 'createDate': '2026-11-02T12:00:00+09:00', 'productId': 1, 'productName': '합성 제품', 'answered': False, 'answer': None, 'answers': []}
        self.calls = []
        self.put_mode = 'success'  # success, disconnect (ambiguous result), server_error

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def respond(self, code, body=None):
        data = b'' if body is None else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        if data:
            self.wfile.write(data)
    def do_GET(self):
        path = urlsplit(self.path).path
        self.server.state.calls.append(('GET', path, None))
        if path == '/external/v1/contents/qnas':
            self.respond(200, {'contents': [self.server.state.question], 'totalElements': 1, 'totalPages': 1})
        else:
            self.respond(404)
    def do_POST(self):
        path = urlsplit(self.path).path
        raw = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        if path == '/external/v1/oauth2/token':
            self.server.state.calls.append(('POST', path, None))
            self.respond(200, {'access_token': 'synthetic-only'})
        elif path.startswith('/botsynthetic-token/'):
            body = json.loads(raw)
            self.server.state.calls.append(('POST', path.rsplit('/', 1)[-1], body))
            result = {'message_id': 123} if path.endswith('/sendMessage') else True
            self.respond(200, {'ok': True, 'result': result})
        else:
            self.respond(404)
    def do_PUT(self):
        path = urlsplit(self.path).path
        raw = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        self.server.state.calls.append(('PUT', path, json.loads(raw)))
        if path != '/external/v1/contents/qnas/7':
            self.respond(404)
        elif self.server.state.put_mode == 'disconnect':
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
        elif self.server.state.put_mode == 'server_error':
            self.respond(503)
        else:
            self.respond(204)

@contextmanager
def fake_services():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.state = State()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.state, 'http://127.0.0.1:' + str(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
