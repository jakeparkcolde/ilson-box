#!/usr/bin/env python3
"""Studio-only issuer. Never uploads the Ed25519 signing seed."""
import argparse
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import secrets
import struct
import subprocess
import sys
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('ilson_license',ROOT/'template/lib/license.py')
license = importlib.util.module_from_spec(spec)
spec.loader.exec_module(license)
CONFIG = Path.home()/'.config/ilson-license'


def timestamp(value):
    date = dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    if date.tzinfo is None:
        raise ValueError('UTC offset is required')
    result=int(date.timestamp())
    if not 0 <= result < 0xffffffff:
        raise ValueError('date out of range')
    return result


def require_studio():
    result=subprocess.run(['/usr/sbin/sysctl','-n','hw.model'],capture_output=True,text=True,check=True,timeout=3)
    if result.stdout.strip() != 'Mac17,14':
        raise ValueError('Studio required')


def initialize(args):
    # This command is supplied for the later authorized ceremony; development
    # and tests must not create or use a real signing key.
    if CONFIG.is_symlink():
        raise ValueError('unsafe config directory')
    CONFIG.mkdir(mode=0o700,parents=True,exist_ok=True)
    st=CONFIG.stat()
    if st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise ValueError('unsafe config directory')
    name='signing-key' if args.action=='init-key' else 'admin-secret'
    path=CONFIG/name
    fd=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    if args.action == 'init-key':
        seed=secrets.token_bytes(32)
        value=seed.hex()
    else:
        value=secrets.token_urlsafe(48)
    with os.fdopen(fd,'w') as f:
        f.write(value+'\n')
        f.flush()
        os.fsync(f.fileno())
    print('Studio의 안전한 파일에 저장했습니다:',path)
    if args.action == 'init-key':
        print('공개키:',license.public_key(seed).hex())


def issue(args):
    key_path=Path(args.key).expanduser()
    if key_path.parent.resolve()!=CONFIG.resolve():
        raise ValueError('signing key must be in ~/.config/ilson-license/')
    seed=bytes.fromhex(license.safe_read(key_path).strip())
    issued=timestamp(args.issued)
    expiry=0xffffffff if args.expires=='never' else timestamp(args.expires)
    plan={'one-time':1,'monthly':2}[args.plan]
    if expiry==0xffffffff and plan!=1 or expiry!=0xffffffff and expiry<=issued:
        raise ValueError('invalid expiry')
    if plan == 2:
        initial=dt.datetime.fromtimestamp(issued,dt.timezone.utc)
        try:
            one_year=initial.replace(year=initial.year+1)
        except ValueError:
            one_year=initial.replace(year=initial.year+1,day=28)
        if expiry != int(one_year.timestamp()):
            raise ValueError('monthly signature must expire in 12 months')
    if not 1<=args.cohort<=65535 or not 0<=args.kid<=255 or len(seed)!=32:
        raise ValueError('invalid fields')
    payload=struct.pack('>BB16sHBII',1,args.kid,secrets.token_bytes(16),args.cohort,plan,issued,expiry)
    serial=license.encode_serial(payload,seed)
    target=Path(args.output).expanduser()
    if target.parent.resolve() != CONFIG.resolve():
        raise ValueError('serial file must be in ~/.config/ilson-license/')
    if target.exists() or target.is_symlink():
        raise ValueError('output already exists')
    fd=os.open(str(target),os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'w') as f:
        f.write(serial+'\n')
    print('시리얼 파일을 준비했습니다. 안전한 전달 전 경로와 권한을 확인하세요.')


def operate(args):
    endpoint=urllib.parse.urlparse(args.server)
    if endpoint.scheme!='https' or not endpoint.netloc or endpoint.query or endpoint.fragment:
        raise ValueError('HTTPS server URL required')
    serial=license.safe_read(Path(args.serial_file).expanduser()).strip()
    secret=license.safe_read(CONFIG/'admin-secret').strip()
    body={'serial':serial,'nonce':secrets.token_hex(16),'request_id':args.request_id or secrets.token_hex(16)}
    if args.display_name: body['display_name']=args.display_name
    if args.paid_until: body['paid_until']=timestamp(args.paid_until)
    if args.target_device: body['target_device']=args.target_device
    req=urllib.request.Request(args.server.rstrip('/')+'/api/v1/'+args.action,json.dumps(body).encode(),{'Content-Type':'application/json','X-Ilson-Admin':secret},method='POST')
    with urllib.request.build_opener(license.NoRedirect).open(req,timeout=10) as response:
        result=json.loads(response.read(8193))
    if result.get('nonce')!=body['nonce'] or result.get('status')!='ok':
        raise ValueError('management request not confirmed')
    print('관리 요청 완료. 요청 ID:',body['request_id'])
    if args.action=='devices':
        for dev in result.get('devices',[]):
            print('기기 해시:',dev['device_hash'],'해제:',bool(dev['released_at']))


def main():
    p=argparse.ArgumentParser(description='Studio 전용 일손 라이선스 발급/관리')
    sub=p.add_subparsers(dest='action',required=True)
    sub.add_parser('init-key')
    sub.add_parser('init-admin')
    issue_parser=sub.add_parser('issue')
    issue_parser.add_argument('--key',required=True); issue_parser.add_argument('--output',required=True)
    issue_parser.add_argument('--kid',type=int,required=True); issue_parser.add_argument('--cohort',type=int,required=True)
    issue_parser.add_argument('--plan',choices=('one-time','monthly'),required=True)
    issue_parser.add_argument('--issued',required=True); issue_parser.add_argument('--expires',required=True)
    for action in ('register','revoke','renew-payment','release-device','devices'):
        q=sub.add_parser(action)
        q.add_argument('--server',required=True); q.add_argument('--serial-file',required=True)
        q.add_argument('--request-id'); q.add_argument('--display-name'); q.add_argument('--paid-until'); q.add_argument('--target-device')
    args=p.parse_args()
    try:
        require_studio()
        if args.action in ('init-key','init-admin'): initialize(args)
        elif args.action=='issue': issue(args)
        else: operate(args)
    except (OSError,ValueError,TypeError,subprocess.SubprocessError,urllib.error.URLError):
        print('발급/관리 요청 실패: 설정과 서버 상태를 확인하세요.',file=sys.stderr)
        return 1
    return 0

if __name__=='__main__':
    sys.exit(main())
