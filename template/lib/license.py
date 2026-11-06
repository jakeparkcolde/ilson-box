"""Ilson serial verification and offline lease state, stdlib only.

Pure-Python Ed25519 is not constant-time and has not received a security audit.
Only use signing on Jake's trusted Studio, never in a network service.
"""
import argparse
import base64
import getpass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import struct
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

# Production public keys are added only after Jake's key ceremony and review.
PUBLIC_KEYS = {}
API_URL = ''  # Set the approved HTTPS Vercel URL before a production release.
DOMAIN = b'ILSON-LICENSE-V1\0'
GRACE = 14 * 86400
CHECK_INTERVAL = 86400
Q = 2**255 - 19
L = 2**252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, Q - 2, Q) % Q
I = pow(2, (Q - 1) // 4, Q)
IDENTITY = (0, 1, 1, 0)


def recover_x(y, sign):
    if y >= Q:
        raise ValueError('invalid point')
    x2 = (y*y - 1) * pow(D*y*y + 1, Q - 2, Q) % Q
    x = pow(x2, (Q + 3) // 8, Q)
    if (x*x - x2) % Q:
        x = x * I % Q
    if (x*x - x2) % Q or (x == 0 and sign):
        raise ValueError('invalid point')
    return Q - x if (x & 1) != sign else x


def decode_point(data):
    if len(data) != 32:
        raise ValueError('invalid point')
    value = int.from_bytes(data, 'little')
    y, sign = value & ((1 << 255)-1), value >> 255
    x = recover_x(y, sign)
    return (x, y, 1, x*y % Q)


def add(p, q):
    x1,y1,z1,t1 = p
    x2,y2,z2,t2 = q
    a = (y1-x1)*(y2-x2) % Q
    b = (y1+x1)*(y2+x2) % Q
    c = 2*D*t1*t2 % Q
    d = 2*z1*z2 % Q
    e,f,g,h = b-a,d-c,d+c,b+a
    return (e*f % Q, g*h % Q, f*g % Q, e*h % Q)


def mul(p, n):
    r = IDENTITY
    while n:
        if n & 1:
            r = add(r,p)
        p = add(p,p)
        n >>= 1
    return r


def encode_point(p):
    x,y,z,_ = p
    zinv = pow(z,Q-2,Q)
    x,y = x*zinv % Q,y*zinv % Q
    return (y | ((x & 1) << 255)).to_bytes(32,'little')


B = decode_point(bytes.fromhex('5866666666666666666666666666666666666666666666666666666666666666'))


def public_key(seed):
    if len(seed) != 32:
        raise ValueError('invalid seed')
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], 'little')
    a = (a & ((1 << 254)-8)) | (1 << 254)
    return encode_point(mul(B,a))


def sign(seed, message):
    h = hashlib.sha512(seed).digest()
    a = (int.from_bytes(h[:32], 'little') & ((1 << 254)-8)) | (1 << 254)
    pub = public_key(seed)
    r = int.from_bytes(hashlib.sha512(h[32:] + message).digest(), 'little') % L
    encoded_r = encode_point(mul(B,r))
    k = int.from_bytes(hashlib.sha512(encoded_r + pub + message).digest(),'little') % L
    return encoded_r + ((r + k*a) % L).to_bytes(32,'little')


def verify(pub, message, signature):
    try:
        if len(pub) != 32 or len(signature) != 64:
            return False
        a, r = decode_point(pub), decode_point(signature[:32])
        s = int.from_bytes(signature[32:],'little')
        if s >= L or encode_point(a) == encode_point(IDENTITY):
            return False
        if encode_point(mul(a,L)) != encode_point(IDENTITY) or encode_point(mul(r,L)) != encode_point(IDENTITY):
            return False
        k = int.from_bytes(hashlib.sha512(signature[:32]+pub+message).digest(),'little') % L
        return secrets.compare_digest(encode_point(mul(B,s)), encode_point(add(r,mul(a,k))))
    except (ValueError, TypeError):
        return False


def encode_serial(payload, seed):
    if len(payload) != 29:
        raise ValueError('invalid payload')
    data = payload + sign(seed, DOMAIN + payload)
    raw = base64.b32encode(data).decode('ascii').rstrip('=')
    return 'ILSON-' + '-'.join(raw[i:i+5] for i in range(0,len(raw),5))


def parse_serial(value, now=None):
    if len(value) > 512:
        raise ValueError('INVALID_SERIAL')
    clean = re.sub(r'[\s-]', '', value).upper()
    if not clean.startswith('ILSON') or not re.fullmatch(r'ILSON[A-Z2-7]{149}', clean):
        raise ValueError('INVALID_SERIAL')
    text = clean[5:]
    try:
        raw = base64.b32decode(text + '='*((-len(text)) % 8))
        if len(raw) != 93 or base64.b32encode(raw).decode().rstrip('=') != text:
            raise ValueError()
        payload, signature = raw[:29], raw[29:]
        version,kid,ident,cohort,plan,issued,expires = struct.unpack('>BB16sHBII',payload)
        pub = PUBLIC_KEYS.get(kid)
        if version != 1 or not cohort or plan not in (1,2) or not pub or not verify(pub,DOMAIN+payload,signature):
            raise ValueError()
        if expires == 0xffffffff and plan != 1 or expires != 0xffffffff and expires <= issued:
            raise ValueError()
        now = int(time.time() if now is None else now)
        if issued > now + 300:
            raise ValueError('CLOCK_ERROR')
        if expires != 0xffffffff and now >= expires:
            raise ValueError('EXPIRED')
        return {'id':ident.hex(),'cohort':cohort,'plan':plan,'issued':issued,'expires':expires,'kid':kid,'payload_hash':hashlib.sha256(payload).hexdigest()}
    except (ValueError, KeyError, struct.error) as exc:
        if str(exc) in ('CLOCK_ERROR','EXPIRED'):
            raise
        raise ValueError('INVALID_SERIAL') from None


def private_dir(home):
    path = Path(home) / 'state' / 'license'
    for part in (path.parent, path):
        if part.is_symlink():
            raise ValueError('STORAGE_ERROR')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('STORAGE_ERROR')
    return path


def safe_read(path):
    fd = os.open(str(path), os.O_RDONLY | getattr(os,'O_NOFOLLOW',0))
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077 or st.st_size > 8192:
            raise ValueError('STORAGE_ERROR')
        with os.fdopen(fd,'r',encoding='utf-8') as f:
            fd = -1
            return f.read()
    finally:
        if fd >= 0:
            os.close(fd)


def safe_write(path, value):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError('STORAGE_ERROR')
    fd, name = tempfile.mkstemp(prefix='.license-',dir=str(path.parent))
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            f.write(value)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def request(action, serial, device, url=None):
    url = API_URL if url is None else url
    if not url or urllib.parse.urlparse(url).scheme != 'https':
        raise OSError('server unavailable')
    nonce = secrets.token_hex(16)
    body = json.dumps({'serial':serial,'device_id':device,'nonce':nonce}).encode()
    req = urllib.request.Request(url.rstrip('/')+'/api/v1/'+action,body,{'Content-Type':'application/json','Cache-Control':'no-store'},method='POST')
    try:
        with urllib.request.build_opener(NoRedirect).open(req,timeout=5) as response:
            result = json.loads(response.read(8193))
    except urllib.error.HTTPError as e:
        if e.code not in (400,403,409):
            raise OSError('server unavailable') from None
        try:
            result = json.loads(e.read(8193))
        except (ValueError, OSError):
            raise OSError('invalid response') from None
    except (OSError,ValueError):
        raise OSError('server unavailable') from None
    if not isinstance(result,dict) or result.get('nonce') != nonce or not isinstance(result.get('server_time'),int):
        raise OSError('invalid response')
    if result.get('status') not in ('active','revoked','expired','payment_due','device_limit','device_not_registered','invalid_serial'):
        raise OSError('invalid response')
    return result


def _evaluate(home, serial=None, force=False, now=None, transport=request):
    now = int(time.time() if now is None else now)
    path = private_dir(home)
    state_path = path / 'state.json'
    try:
        state = json.loads(safe_read(state_path))
        if not isinstance(state,dict):
            raise ValueError('STORAGE_ERROR')
    except FileNotFoundError:
        state = {}
    if serial is None:
        try:
            serial = safe_read(path/'serial').strip()
        except FileNotFoundError:
            return False, 'NO_LICENSE'
    info = parse_serial(serial,now)
    same = state.get('id') == info['id']
    if not same:
        state = {'id':info['id'], 'first':now, 'last_success':None, 'registered':False, 'last_observed':now}
    try:
        device = safe_read(path/'device-id').strip()
        if not re.fullmatch('[0-9a-f]{64}',device):
            raise ValueError('STORAGE_ERROR')
    except FileNotFoundError:
        device = secrets.token_hex(32)
        safe_write(path/'device-id',device)
    previous = state.get('last_observed',now)
    clock_error = now < previous - 300
    due = force or clock_error or bool(state.get('denied')) or not state.get('last_success') or now >= state['last_success']+CHECK_INTERVAL
    result = None
    if due:
        try:
            result = transport('check' if state.get('registered') else 'activate',serial,device)
        except OSError:
            pass
    if result is not None and result.get('status') == 'device_not_registered' and state.get('registered'):
        # A released device must be registered again through the same limit check.
        # A transport failure here cannot turn an explicit denial into a lease.
        try:
            result = transport('activate',serial,device)
        except OSError:
            pass
    if result is not None:
        server_time = result['server_time']
        if abs(now-server_time) > 300:
            return False,'CLOCK_ERROR'
        clock_error = False
        status = result['status']
        if status != 'active':
            state.update({'denied':status,'last_observed':now})
            # A rejected replacement serial must not overwrite the prior license state.
            if same:
                safe_write(state_path,json.dumps(state))
            return False,status.upper()
        state.update({'registered':True,'last_success':now,'denied':None,'paid_until':result.get('paid_until')})
    if clock_error:
        return False,'CLOCK_ERROR'
    if state.get('denied'):
        return False,state['denied'].upper()
    deadline = (state.get('last_success') or state['first']) + GRACE
    if info['expires'] != 0xffffffff:
        deadline = min(deadline,info['expires'])
    if now >= deadline:
        return False,'GRACE_EXPIRED'
    state['last_observed'] = now
    safe_write(path/'serial',serial)
    safe_write(state_path,json.dumps(state))
    return True, 'ACTIVE' if state.get('last_success') else 'OFFLINE_GRACE'


def evaluate(home, serial=None, force=False, now=None, transport=request):
    path = private_dir(home)
    lock = os.open(str(path / 'lock'), os.O_RDWR | os.O_CREAT | getattr(os,'O_NOFOLLOW',0), 0o600)
    try:
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('STORAGE_ERROR')
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _evaluate(home, serial, force, now, transport)
    finally:
        os.close(lock)


def deactivate(home):
    path = private_dir(home)
    serial = safe_read(path/'serial').strip()
    device = safe_read(path/'device-id').strip()
    result = request('deactivate', serial, device)
    if result.get('status') != 'active' or abs(int(time.time())-result['server_time']) > 300:
        raise ValueError('STORAGE_ERROR')
    for name in ('serial','state.json'):
        (path/name).unlink(missing_ok=True)
    return True

def main():
    parser = argparse.ArgumentParser(description='일손 라이선스')
    parser.add_argument('--home',default=os.environ.get('ILSON_HOME',str(Path.home()/'ilson')))
    parser.add_argument('action',choices=('activate','status','check','deactivate'))
    parser.add_argument('serial',nargs='?')
    parser.add_argument('--stdin',action='store_true')
    args = parser.parse_args()
    try:
        if args.action == 'deactivate':
            deactivate(args.home)
            print('이 기기의 라이선스를 해제했습니다.')
            return 0
        serial = args.serial
        if args.action == 'activate' and serial is None:
            serial = sys.stdin.read(513) if args.stdin else getpass.getpass('시리얼을 붙여넣으세요: ')
        ok, code = evaluate(args.home,serial,force=args.action in ('activate','status'))
        if args.action != 'check' or not ok:
            print(('라이선스 확인: ' if ok else '라이선스 확인 필요: ') + code + ('' if ok else ' — ilson license activate'))
        if ok and args.action == 'status':
            directory = private_dir(args.home)
            info = parse_serial(safe_read(directory/'serial').strip())
            state = json.loads(safe_read(directory/'state.json'))
            deadline = (state.get('last_success') or state['first']) + GRACE
            if info['expires'] != 0xffffffff:
                deadline = min(deadline, info['expires'])
            print('일련번호 끝:', info['id'][-8:], '플랜:', '일시불' if info['plan'] == 1 else '월 납부')
            print('서명 만료:', '무기한' if info['expires'] == 0xffffffff else time.strftime('%Y-%m-%d %H:%M UTC',time.gmtime(info['expires'])))
            print('마지막 서버 확인:', time.strftime('%Y-%m-%d %H:%M UTC',time.gmtime(state['last_success'])) if state.get('last_success') else '없음')
            print('오프라인 사용 기한:',time.strftime('%Y-%m-%d %H:%M UTC',time.gmtime(deadline)))
            if state.get('paid_until'):
                print('마지막 확인 납부 기한:',time.strftime('%Y-%m-%d %H:%M UTC',time.gmtime(state['paid_until'])))
        return 0 if ok else 1
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError) as e:
        code = str(e) if str(e) in ('INVALID_SERIAL','EXPIRED','CLOCK_ERROR','STORAGE_ERROR') else 'STORAGE_ERROR'
        print('라이선스 확인 필요: ' + code + ' — ilson license activate',file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
