"""공개 원문을 제한해서 읽는다. DNS 결과를 검사한 IP에 연결하고 인증을 전달하지 않는다."""
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import http.client
import ipaddress
import socket
import threading
import time
from collections import OrderedDict
from urllib.parse import urlsplit, urljoin

class VisibleText(HTMLParser):
    def __init__(self):super().__init__();self.skip=0;self.parts=[];self.ignored=[]
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','noscript','svg','nav','footer'):self.skip+=1;self.ignored.append(tag)
    def handle_endtag(self,tag):
        if tag in self.ignored:
            self.ignored.remove(tag);self.skip=max(0,self.skip-1)
    def handle_data(self,data):
        if not self.skip and data.strip():self.parts.append(data.strip())


def destination(url):
    p=urlsplit(url)
    if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or p.port not in (None,80 if p.scheme=='http' else 443):
        raise ValueError('공개 HTTP 주소 필요')
    addresses=socket.getaddrinfo(p.hostname,p.port or (443 if p.scheme=='https' else 80),type=socket.SOCK_STREAM)
    ips={r[4][0] for r in addresses}
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):raise ValueError('공개 IP 주소 필요')
    return p,sorted(ips)[0]


def read(url):
    for _ in range(3):
        p,ip=destination(url)
        cls=http.client.HTTPSConnection if p.scheme=='https' else http.client.HTTPConnection
        conn=cls(p.hostname,port=p.port,timeout=6)
        # TLS 검증과 Host는 원래 도메인을 유지하고 연결 대상만 검사한 IP로 고정한다.
        conn._create_connection=lambda addr,timeout,*args:socket.create_connection((ip,addr[1]),timeout)
        try:
            conn.request('GET',(p.path or '/')+('?' +p.query if p.query else ''),headers={'User-Agent':'IlsonResearch/0.3 (+source reading)','Accept':'text/html,text/plain'})
            response=conn.getresponse()
            if response.status in (301,302,303,307,308):
                location=response.getheader('Location')
                if not location:raise ValueError('리디렉션 주소 없음')
                url=urljoin(url,location);continue
            kind=response.getheader('Content-Type','').split(';')[0]
            if response.status!=200 or kind not in ('text/html','text/plain'):raise ValueError('읽을 수 없는 응답')
            raw=response.read(300001)
            if len(raw)>300000:raw=raw[:300000]
            charset=response.headers.get_content_charset() or 'utf-8'
            text=raw.decode(charset,errors='replace')
            if kind=='text/html':
                parser=VisibleText();parser.feed(text);text='\n'.join(parser.parts)
            if len(text.strip())<100:raise ValueError('본문이 충분하지 않음')
            return text[:60000]
        finally:conn.close()
    raise ValueError('리디렉션 횟수 초과')


_cache=OrderedDict()
_cache_lock=threading.Lock()


def cached_read(url,ttl):
    # 공개 원문만 짧게 최대128건 메모리에 보관한다. 인증이나 LLM 답변은 저장하지 않는다.
    now=time.monotonic()
    if ttl>0:
        with _cache_lock:
            item=_cache.get(url)
            if item and now-item[0]<ttl:
                _cache.move_to_end(url);return item[1],True
    text=read(url)  # 공개 IP 검사·접속 IP 고정·리디렉션 재검사는 기존 경로를 통과한다.
    if ttl>0:
        with _cache_lock:
            _cache[url]=(time.monotonic(),text);_cache.move_to_end(url)
            while len(_cache)>128:_cache.popitem(last=False)
    return text,False


def enrich(sources,*,cache_ttl=0,max_reads=None):
    pending=[s['id'] for s in sources if s.get('read_status')!='read']
    selected=set(pending if max_reads is None else pending[:max_reads])
    def one(source):
        row=dict(source)
        if row.get('read_status')=='read':return row
        if row['id'] not in selected:
            row['read_status']='snippet';row['read_note']='빠른 조사에서는 검색 발췌문을 사용했습니다';return row
        try:
            text,hit=cached_read(row['url'],cache_ttl);row['content']='검색 발췌문:\n'+row['content']+'\n읽은 원문 일부:\n'+text;row['method']='original-text-partial';row['read_status']='read';row['cache_hit']=hit
        except Exception:
            row['read_status']='unavailable';row['read_error']='원문 접근 실패 또는 지원하지 않는 형식 — 검색 발췌문만 사용'
        return row
    # 외부 원문만 병렬로 읽는다. Google 검색 호출은 병렬 실행하지 않는다.
    with ThreadPoolExecutor(max_workers=3) as pool:return list(pool.map(one,sources))
