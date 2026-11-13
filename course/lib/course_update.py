"""Upgrade course helper code from an explicitly pinned official installer, never main.

The installer is read as a data container; app installers, shell profiles, vaults and
launch agents are not run or changed. A release operator supplies the revision/hash.
"""
import argparse
import base64
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.request

MAX_INSTALLER = 4 * 1024 * 1024
MAX_BUNDLE = 8 * 1024 * 1024
BASE = 'https://raw.githubusercontent.com/jakeparkcolde/ilson-box/'


class UpdateError(Exception):
    pass


def payload_module(path=None):
    path = path or Path(__file__).absolute().parent / 'install_payload.py'
    if not path.is_file() and path.parent.name == 'lib':
        path = path.parent.parent / 'install_payload.py'
    spec = importlib.util.spec_from_file_location('_course_payload', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_pin(pin, edition):
    if (not isinstance(pin, dict) or set(pin) != {'schema', 'edition', 'source_ref', 'sha256'}
            or pin['schema'] != 1 or pin['edition'] != edition
            or not re.fullmatch('[a-f0-9]{40}', pin.get('source_ref', ''))
            or not re.fullmatch('[a-f0-9]{64}', pin.get('sha256', ''))):
        raise UpdateError('INVALID_PIN')
    return pin


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def fetch(pin):
    name = 'install-windows.ps1' if pin['edition'] == 'windows-course' else 'install-intel-mac.sh'
    url = BASE + pin['source_ref'] + '/course/' + name
    with urllib.request.build_opener(NoRedirect).open(url, timeout=30) as response:
        data = response.read(MAX_INSTALLER + 1)
    if len(data) > MAX_INSTALLER or hashlib.sha256(data).hexdigest() != pin['sha256']:
        raise UpdateError('INSTALLER_HASH_MISMATCH')
    return data


def extract(data):
    text = data.decode('utf-8')
    def value(key):
        pattern = r"(?m)^(?:COURSE_" + key.upper() + r"|\$Course" + key.title() + r")='([A-Za-z0-9+/=]+)'$"
        values = re.findall(pattern, text)
        if len(values) != 1:
            raise UpdateError('INVALID_INSTALLER')
        return base64.b64decode(values[0], validate=True)
    compressed = value('payload')
    import io
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        raw = stream.read(MAX_BUNDLE + 1)
    if len(raw) > MAX_BUNDLE:
        raise UpdateError('BUNDLE_TOO_LARGE')
    files = json.loads(raw)
    bootstrap = value('bootstrap')
    if not isinstance(files, dict) or files.get('install_payload.py', '').encode('utf-8') != bootstrap:
        raise UpdateError('BOOTSTRAP_MISMATCH')
    compile(bootstrap, 'install_payload.py', 'exec')
    return files, bootstrap


def self_check(root):
    for args in (['--version'], ['doctor', '--install', '--self-check', '--json']):
        result = subprocess.run([sys.executable, '-X', 'utf8', str(root / 'ilson.py'), *args],
                                stdin=subprocess.DEVNULL, capture_output=True, timeout=15)
        if result.returncode or args == ['--version'] and b'ILSON-DIAG-1' not in result.stdout:
            raise UpdateError('SELF_CHECK_FAILED')


def upgrade(root, pin, installer=None):
    current = payload_module()
    current.safe(root)
    data = fetch(pin) if installer is None else installer
    # A test fixture must pass the same hash gate as a downloaded installer.
    if len(data) > MAX_INSTALLER or hashlib.sha256(data).hexdigest() != pin['sha256']:
        raise UpdateError('INSTALLER_HASH_MISMATCH')
    files, bootstrap = extract(data)
    stage = root / '.update-staging'
    current.safe(stage)
    stage.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='pinned-', dir=stage) as temporary:
        bootstrap_path = Path(temporary) / 'install_payload.py'
        bootstrap_path.write_bytes(bootstrap)
        reviewed = payload_module(bootstrap_path)
        backup = reviewed.install(root, files, verify=lambda: self_check(root))
    # Remember only this immutable revision/hash, never a moving branch or arbitrary URL.
    current.safe(root / '.course-update-pin.json')
    current.atomic_write(root / '.course-update-pin.json', json.dumps(pin, sort_keys=True).encode())
    return backup


def last_backup(root):
    module = payload_module()
    base = root / '.install-backups'
    module.safe(base)
    valid = []
    if base.is_dir():
        for backup in base.glob('upgrade-*'):
            module.safe(backup)
            path = backup / 'manifest.json'
            module.safe(path)
            if path.is_file() and json.loads(path.read_text()).get('status', 'applied') == 'applied':
                valid.append(backup)
    if not valid:
        raise UpdateError('NO_BACKUP')
    return max(valid, key=lambda p: (p.stat().st_mtime_ns, p.name))


def main(argv=None):
    parser = argparse.ArgumentParser(description='강의판 도우미 갱신: 고정 설치기 SHA-256 확인·백업·자체 점검')
    parser.add_argument('--source-ref', help='강사가 제공한 검수된 40자리 커밋')
    parser.add_argument('--sha256', help='해당 판본 설치기의 64자리 SHA-256')
    parser.add_argument('--manifest', type=Path, help='강사가 제공한 로컬 고정 manifest JSON')
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args(argv)
    root = Path(__file__).absolute().parent
    edition = 'windows-course' if os.name == 'nt' else 'intel-course'
    try:
        module = payload_module()
        if args.rollback:
            if args.source_ref or args.sha256 or args.manifest:
                raise UpdateError('INVALID_OPTIONS')
            module.rollback(root, last_backup(root))
            print('ROLLBACK_OK: 직전 도우미 코드를 복구했습니다. 노트·설정은 보존합니다.')
            return 0
        if args.manifest:
            if args.source_ref or args.sha256:
                raise UpdateError('INVALID_OPTIONS')
            module.safe(args.manifest.absolute())
            pin = json.loads(args.manifest.read_text(encoding='utf-8'))
        elif args.source_ref or args.sha256:
            pin = {'schema': 1, 'edition': edition, 'source_ref': args.source_ref or '', 'sha256': args.sha256 or ''}
        else:
            saved = root / '.course-update-pin.json'
            module.safe(saved)
            if not saved.is_file():
                print('PIN_REQUIRED: 강사가 제공한 고정 manifest 또는 --source-ref <커밋> --sha256 <설치기 해시>를 사용하세요. main은 실행하지 않습니다.')
                return 2
            pin = json.loads(saved.read_text(encoding='utf-8'))
        validate_pin(pin, edition)
        # Same cross-process lock as the installer, including manual installer reruns.
        backup = upgrade(root, pin)
        print('UPDATE_OK: 도우미 자체 점검 완료. 기존 실행기·Python 선택·PATH·볼트 보존.' + (' 백업 있음.' if backup else ' 이미 같은 버전.'))
        return 0
    except (UpdateError, OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        print('UPDATE_FAILED: 코드·고정 버전·백업 상태를 확인하세요. 사용자 수정본은 덮어쓰지 않습니다.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
