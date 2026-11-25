#!/usr/bin/env python3
"""Studio-only issuer. Never uploads the Ed25519 signing seed."""
import argparse
import datetime as dt
import hashlib
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
    short_target=None
    if args.short or args.short_output:
        short_target=Path(args.short_output).expanduser() if args.short_output else Path(str(target)+'.short')
        if short_target.parent.resolve() != CONFIG.resolve():
            raise ValueError('short serial file must be in ~/.config/ilson-license/')
        if short_target.name.casefold() == target.name.casefold() or short_target.exists() or short_target.is_symlink():
            raise ValueError('short output already exists')
    fd=os.open(str(target),os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'w') as f:
        f.write(serial+'\n')
        f.flush()
        os.fsync(f.fileno())
    if short_target is not None:
        short_created=False
        try:
            short_code=license.generate_short_serial()
            sfd=os.open(str(short_target),os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
            short_created=True
            with os.fdopen(sfd,'w') as f:
                f.write(short_code+'\n')
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            if short_created:
                short_target.unlink(missing_ok=True)
            target.unlink(missing_ok=True)
            raise
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
    if args.action=='register' and getattr(args,'short_file',None):
        short_code=license.safe_read(Path(args.short_file).expanduser()).strip()
        canonical=license.normalize_short_serial(short_code)
        salt=hashlib.sha256(b'ilson-short-salt-v2\0'+canonical.encode('ascii')+b'\0'+license.serial_raw_bytes(serial)).digest()[:16]
        body['short_code_hash']=license.short_code_hash(canonical)
        body['sealed_serial']=license.seal_serial(canonical,serial,salt=salt)
    req=urllib.request.Request(args.server.rstrip('/')+'/api/v1/'+args.action,json.dumps(body).encode(),{'Content-Type':'application/json','X-Ilson-Admin':secret},method='POST')
    with urllib.request.build_opener(license.NoRedirect).open(req,timeout=10) as response:
        result=json.loads(response.read(8193))
    if result.get('nonce')!=body['nonce'] or result.get('status')!='ok':
        raise ValueError('management request not confirmed')
    print('관리 요청 완료. 요청 ID:',body['request_id'])
    if args.action=='devices':
        for dev in result.get('devices',[]):
            print('기기 해시:',dev['device_hash'],'해제:',bool(dev['released_at']))


def _fmt_ts(ts):
    if not ts:
        return '-'
    kst = dt.timezone(dt.timedelta(hours=9))
    return dt.datetime.fromtimestamp(int(ts), kst).strftime('%Y-%m-%d %H:%M')


def _admin_secret():
    env_secret = os.environ.get('ILSON_LICENSE_ADMIN_SECRET', '').strip()
    if env_secret:
        return env_secret
    return license.safe_read(CONFIG / 'admin-secret').strip()


def format_overview(data):
    lines = []
    s = data.get('summary') or {}
    lines.append('=== 일손 설치·활성화 현황 ===')
    lines.append(
        f"전체 라이선스: {s.get('total_licenses', 0)}명 "
        f"(활성 {s.get('active_licenses', 0)} / 미활성 {s.get('inactive_licenses', 0)} / 폐기 {s.get('revoked_licenses', 0)}) | "
        f"활성 기기: {s.get('total_active_devices', 0)}대"
    )
    lines.append(
        f"최근 7일 설치 실행: {s.get('recent_runs_7d', 0)}건 "
        f"(성공 {s.get('ok_runs_7d', 0)} / 실패 {s.get('failed_runs_7d', 0)})"
    )

    cohorts = data.get('cohorts') or []
    lines.append('')
    lines.append('[기수별 요약]')
    if not cohorts:
        lines.append('  (데이터 없음)')
    else:
        lines.append('  기수 | 발급 | 활성화 | 미활성 | 활성 기기')
        lines.append('  -----+------+--------+--------+----------')
        for c in cohorts:
            lines.append(
                f"  {str(c.get('cohort', '-')):>3}기 | {c.get('total', 0):>4} | "
                f"{c.get('activated', 0):>6} | {c.get('inactive', 0):>6} | {c.get('active_devices', 0):>9}"
            )

    licenses_list = data.get('licenses') or []
    lines.append('')
    lines.append(f'[수강생별 상태 ({len(licenses_list)}명)]')
    if not licenses_list:
        lines.append('  (등록된 라이선스 없음)')
    else:
        lines.append('  기수 | 이름 | 시리얼 | 상태 | OS/아키텍처 | 활성기기 | 최초 활성화(KST) | 최근 접속(KST)')
        lines.append('  -----+------+--------+------+-------------+----------+------------------+----------------')
        for lic in licenses_list:
            serial_kind = 'V2' if lic.get('has_short_serial') else 'V1'
            if lic.get('status') == 'revoked':
                st_label = '폐기'
            elif (lic.get('active_devices') or 0) > 0:
                st_label = '활성'
            else:
                st_label = '미활성'
            devs = lic.get('devices') or []
            active_devs = [d for d in devs if d.get('released_at') is None]
            primary = active_devs[0] if active_devs else (devs[0] if devs else None)
            if primary and (primary.get('os') or primary.get('arch')):
                os_arch = f"{primary.get('os') or '?'}/{primary.get('arch') or '?'}"
            else:
                os_arch = '-'
            dev_cnt = f"{lic.get('active_devices', 0)}/{lic.get('device_limit', 2)}"
            lines.append(
                f"  {lic.get('cohort', '-')}기 | {lic.get('display_name', '-')} | {serial_kind} | "
                f"{st_label} | {os_arch} | {dev_cnt} | "
                f"{_fmt_ts(lic.get('first_activated_at'))} | {_fmt_ts(lic.get('last_seen_at'))}"
            )

    runs = data.get('install_runs') or []
    lines.append('')
    lines.append(f'[최근 설치 실행 로그 ({len(runs)}건, 미활성화 포함)]')
    if not runs:
        lines.append('  (설치 실행 기록 없음)')
    else:
        for r in runs:
            res_label = '성공' if r.get('result') == 'ok' else f"실패(rc={r.get('exit_code')})"
            owner = f"{r['display_name']}({r['cohort']}기)" if r.get('display_name') else '(미활성화)'
            helper = r.get('helper_status') or '-'
            steps = r.get('failed_steps') or []
            fail_txt = ', '.join(
                f"{fs.get('step_id')}:{fs.get('reason_code')}" + (f"({fs['http_code']})" if fs.get('http_code') else '')
                for fs in steps
            )
            tail = f" | 실패: {fail_txt}" if fail_txt else ''
            lines.append(
                f"  {_fmt_ts(r.get('created_at'))} | {res_label} | {r.get('edition', '-')} | "
                f"{r.get('os', '?')} {r.get('os_version', '?')}/{r.get('arch', '?')} | "
                f"helper={helper} | {owner}{tail}"
            )

    failures = data.get('failure_breakdown') or []
    lines.append('')
    lines.append('[실패 단계 TOP (최근 30일)]')
    if not failures:
        lines.append('  (실패 기록 없음)')
    else:
        for f in failures:
            lines.append(f"  - {f.get('step_id')} / {f.get('reason_code')}: {f.get('count', 0)}건")

    return '\n'.join(lines)


def overview(args):
    endpoint = urllib.parse.urlparse(args.server)
    if endpoint.scheme != 'https' or not endpoint.netloc or endpoint.query or endpoint.fragment:
        raise ValueError('HTTPS server URL required')
    secret = _admin_secret()
    body = {'nonce': secrets.token_hex(16)}
    if args.cohort is not None:
        if not 1 <= args.cohort <= 65535:
            raise ValueError('cohort out of range')
        body['cohort'] = args.cohort
    req = urllib.request.Request(
        args.server.rstrip('/') + '/api/v1/admin-overview',
        json.dumps(body).encode(),
        {'Content-Type': 'application/json', 'X-Ilson-Admin': secret},
        method='POST',
    )
    with urllib.request.build_opener(license.NoRedirect).open(req, timeout=15) as response:
        result = json.loads(response.read(2 * 1024 * 1024))
    if result.get('nonce') != body['nonce'] or result.get('status') != 'ok':
        raise ValueError('overview request not confirmed')
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_overview(result))


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
    issue_parser.add_argument('--short',action='store_true'); issue_parser.add_argument('--short-output')
    for action in ('register','revoke','renew-payment','release-device','devices'):
        q=sub.add_parser(action)
        q.add_argument('--server',required=True); q.add_argument('--serial-file',required=True)
        q.add_argument('--request-id'); q.add_argument('--display-name'); q.add_argument('--paid-until'); q.add_argument('--target-device')
        if action=='register': q.add_argument('--short-file')
    ov=sub.add_parser('overview')
    ov.add_argument('--server',required=True)
    ov.add_argument('--cohort',type=int)
    ov.add_argument('--json',action='store_true')
    args=p.parse_args()
    try:
        require_studio()
        if args.action in ('init-key','init-admin'): initialize(args)
        elif args.action=='issue': issue(args)
        elif args.action=='overview': overview(args)
        else: operate(args)
    except (OSError,ValueError,TypeError,subprocess.SubprocessError,urllib.error.URLError):
        print('발급/관리 요청 실패: 설정과 서버 상태를 확인하세요.',file=sys.stderr)
        return 1
    return 0

if __name__=='__main__':
    sys.exit(main())
