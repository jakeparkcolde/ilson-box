"""Explicit opt-in bcrypt dependency in the Box's existing private venv."""
import json
from pathlib import Path
import subprocess
import sys

VERSION = '4.3.0'
# PyPI bcrypt 4.3.0 macOS universal2 wheels, checked 2026-11-08.
REQUIREMENT = '''bcrypt==4.3.0 \\
    --hash=sha256:f81b0ed2639568bf14749112298f9e4e2b28853dab50a8b357e31798686a036d \\
    --hash=sha256:0d3efb1157edebfd9128e4e46e2ac1a64e0c1fe46fb023158e31798686a036d \\
    --hash=sha256:f01e060f14b6b57bbb72fc5b4a83ac21c443c9a2ee708e04a10e9192f90a6281
'''
CHECK = 'import bcrypt,sys; sys.exit(0 if bcrypt.__version__ == "4.3.0" else 1)'
SIGN = '''import base64,bcrypt,json,sys
v=json.load(sys.stdin)
if bcrypt.__version__ != "4.3.0": sys.exit(2)
s=bcrypt.hashpw((v["id"]+"_"+v["timestamp"]).encode(),v["secret"].encode())
sys.stdout.write(base64.b64encode(s).decode())
'''


def python_path(home):
    runtime = Path(home) / '.runtime'
    venv = runtime / 'venv'
    if runtime.is_symlink() or venv.is_symlink():
        raise ValueError('전용 실행 환경 경로를 확인하세요.')
    return venv / 'bin/python'


def ready(home, runner=subprocess.run):
    py = python_path(home)
    if not py.is_file(): return False
    try:
        return runner([str(py), '-c', CHECK], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired): return False


def install(home, *, consent, runner=subprocess.run, platform=sys.platform):
    if consent is not True:
        raise ValueError('네이버 연결 설치 동의가 필요합니다.')
    if platform != 'darwin':
        raise ValueError('이 연결은 맥에서만 준비할 수 있습니다.')
    import fcntl, os
    from replies_ingest import private_dir
    lock = os.open(private_dir(home) / 'runtime.lock', os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise ValueError('연결 준비가 이미 진행 중입니다.') from None
        return _install(home, runner)
    finally:
        os.close(lock)


def _install(home, runner):
    py = python_path(home)
    if ready(home, runner): return {'ok':True, 'message':'네이버 연결 준비가 되어 있습니다.'}
    py.parent.parent.parent.mkdir(mode=0o700, exist_ok=True)
    if not py.exists():
        try:
            result = runner([sys.executable, '-m', 'venv', str(py.parent.parent)], capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            raise ValueError('전용 실행 환경을 만들지 못했습니다.') from None
        if result.returncode:
            raise ValueError('전용 실행 환경을 만들지 못했습니다.')
    from replies_ingest import private_dir
    import os, secrets
    req = private_dir(home) / ('.bcrypt-' + secrets.token_hex(12))
    fd = os.open(req, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='ascii') as f:
            f.write(REQUIREMENT)
        try:
            result = runner([str(py), '-m', 'pip', '--isolated', 'install', '--disable-pip-version-check', '--require-hashes', '--only-binary=:all:', '-r', str(req)], capture_output=True, timeout=240)
        except (OSError, subprocess.TimeoutExpired):
            raise ValueError('네이버 연결 준비를 마치지 못했습니다.') from None
        if result.returncode or not ready(home, runner):
            raise ValueError('네이버 연결 준비를 마치지 못했습니다.')
    finally:
        try: req.unlink()
        except OSError: pass
    return {'ok':True, 'message':'네이버 연결 준비가 되었습니다. 연결 정보와 권한을 확인하세요.'}


def sign(home, client_id, client_secret, timestamp, runner=subprocess.run):
    if not ready(home, runner):
        raise ValueError('네이버 연결 준비가 필요합니다. 연결 화면에서 설치하세요.')
    payload = json.dumps({'id':client_id,'secret':client_secret,'timestamp':timestamp})
    try:
        result = runner([str(python_path(home)), '-c', SIGN], input=payload, text=True, capture_output=True, timeout=20)
        if result.returncode or not result.stdout or len(result.stdout) > 200:
            raise ValueError()
        return result.stdout
    except (OSError, subprocess.TimeoutExpired, ValueError):
        raise ValueError('네이버 인증 준비를 확인하세요.') from None
