"""외부 라이브러리 없이 사용하는 고정 Meta API HTTP 전송기."""
import json as json_module
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class Response:
    def __init__(self, status, raw):
        self.status_code, self.raw = status, raw

    def json(self):
        return json_module.loads(self.raw)


class Client:
    def __init__(self, transport=None, timeout=60):
        self.transport, self.timeout = transport, timeout

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def request(self, method, url, *, params=None, json=None, headers=None):
        if self.transport:
            return self.transport(method, url, params=params, json=json, headers=headers)
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname not in {'graph.instagram.com', 'graph.threads.net', 'graph.facebook.com'} or parsed.username or parsed.password:
            raise ValueError('허용하지 않는 API 주소')
        if params:
            url += '?' + urlencode(params)
        data = json_module.dumps(json).encode() if json is not None else None
        request = Request(url, data=data, method=method, headers=headers or {})
        try:
            response = build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=self.timeout)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise ValueError('API 응답 크기 초과')
            return Response(response.code, raw)

    def get(self, url, **kwargs):
        return self.request('GET', url, **kwargs)

    def post(self, url, **kwargs):
        return self.request('POST', url, **kwargs)
