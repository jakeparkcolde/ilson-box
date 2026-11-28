"""Course-only command: license protects learning, not the student's documents."""
import os
from pathlib import Path
import subprocess
import sys
import urllib.parse
import webbrowser

DEFAULT_WORKSPACE_URL = 'https://ilson.work/'
CLOUD_ACTIONS = ('pair', 'sync', 'sync-wiki', 'worker', 'status', 'submit-draft', 'heartbeat', 'publish')
_UNSAFE_URL_CHARS = set('"\'`\\<>|{}^')


def _validate_cloud_url(raw):
    if not isinstance(raw, str) or not raw:
        raise ValueError('워크스페이스 주소(ILSON_WORKSPACE_URL)가 비어 있습니다. https:// 주소를 사용하세요.')
    if any(ch.isspace() or ord(ch) < 32 or 127 <= ord(ch) <= 159 or ch in _UNSAFE_URL_CHARS for ch in raw):
        raise ValueError('워크스페이스 주소(ILSON_WORKSPACE_URL)에 허용되지 않는 문자(공백·제어문자·따옴표)가 포함되어 있습니다.')
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme != 'https' or not parsed.netloc or not parsed.hostname:
        raise ValueError('워크스페이스 주소(ILSON_WORKSPACE_URL)는 올바른 https:// 주소여야 합니다.')
    try:
        _ = parsed.port
    except ValueError:
        raise ValueError('워크스페이스 주소(ILSON_WORKSPACE_URL)의 포트 형식이 올바르지 않습니다.') from None
    if parsed.username is not None or parsed.password is not None:
        raise ValueError('워크스페이스 주소(ILSON_WORKSPACE_URL)에 계정 정보(username/password)를 포함할 수 없습니다.')
    return raw


def _open_browser_url(url):
    if os.name == 'nt':
        os.startfile(url)
        return
    if sys.platform == 'darwin':
        result = subprocess.run(['/usr/bin/open', url], check=False)
        if result.returncode != 0:
            raise RuntimeError('브라우저를 열지 못했습니다.')
        return
    if not webbrowser.open(url):
        raise RuntimeError('브라우저를 열지 못했습니다.')


def _resolve_helper(name):
    base = Path(__file__).resolve().parent
    for candidate in (base / name, base / 'lib' / name, base.parent / 'template/lib' / name):
        if candidate.is_file():
            return candidate
    return base / name


def _open_cloud_workspace(home):
    raw_url = os.environ['ILSON_WORKSPACE_URL'] if 'ILSON_WORKSPACE_URL' in os.environ else DEFAULT_WORKSPACE_URL
    try:
        url = _validate_cloud_url(raw_url)
    except ValueError as exc:
        print(f'오류: {exc}', file=sys.stderr)
        return 2
    try:
        _open_browser_url(url)
    except (OSError, RuntimeError) as exc:
        print(f'오류: 브라우저에서 {url} 을(를) 열지 못했습니다 ({exc}).', file=sys.stderr)
        return 1
    print(f'일손 워크스페이스({url})를 브라우저에서 열었습니다.')
    if not (Path(home) / 'state/cloud-runner.json').exists():
        print('이 PC를 ilson.work에 연결하려면: ilson cloud pair --code <사무소코드>')
    print('로컬 간이 화면이 필요하면: ilson open --local')
    return 0


def _main(argv):
    os.environ['ILSON_HOME'] = os.environ.get('ILSON_COURSE_STATE', str(Path.home() / '.ilson-course'))
    os.environ['ILSON_PROFILE'] = 'course'
    if any('—' in arg or '–' in arg for arg in argv):
        print('SMART_DASH: --help / --version처럼 ASCII 하이픈 두 개를 사용하세요.')
        return 2
    if argv == ['--version']:
        print('ilson ' + ('windows-course' if os.name == 'nt' else 'intel-course') + ' ILSON-DIAG-1')
        return 0
    if argv and argv[0] == 'open':
        home = os.environ['ILSON_HOME']
        if argv == ['open']:
            return _open_cloud_workspace(home)
        if argv == ['open', '--local']:
            lib = Path(__file__).resolve().parent
            if (lib / 'lib/web-admin.py').is_file(): lib /= 'lib'
            vault = os.environ.get('ILSON_COURSE_VAULT', str(Path.home() / 'Documents/일손강의-1기'))
            return subprocess.call([sys.executable, '-X', 'utf8', str(lib / 'web-admin.py'), 'open',
                                    '--home', home, '--vault', vault, '--profile', 'course'])
        print('사용법: ilson open [--local] | ilson admin status|stop [--force]')
        return 2
    if argv and argv[0] == 'admin':
        lib = Path(__file__).resolve().parent
        if (lib / 'lib/web-admin.py').is_file(): lib /= 'lib'
        home = os.environ['ILSON_HOME']
        vault = os.environ.get('ILSON_COURSE_VAULT', str(Path.home() / 'Documents/일손강의-1기'))
        command = argv[1] if len(argv) > 1 else 'status'
        extra = argv[2:]
        if command not in ('open', 'status', 'stop') or (extra and not (command == 'stop' and extra == ['--force'])):
            print('사용법: ilson open [--local] | ilson admin status|stop [--force]')
            return 2
        return subprocess.call([sys.executable, '-X', 'utf8', str(lib / 'web-admin.py'), command,
                                '--home', home, '--vault', vault, '--profile', 'course'] + extra)
    if argv and argv[0] == 'cloud':
        home = os.environ['ILSON_HOME']
        sub = argv[1] if len(argv) > 1 else ''
        cloud_script = _resolve_helper('cloud_bridge.py')
        if not sub:
            print('사용법: ilson cloud pair|sync|sync-wiki|worker|status|submit-draft|heartbeat|publish')
            return 2
        is_help = sub in ('--help', '-h') or (sub in CLOUD_ACTIONS and any(arg in ('--help', '-h') for arg in argv[2:]))
        if not is_help and sub not in CLOUD_ACTIONS:
            print('사용법: ilson cloud pair|sync|sync-wiki|worker|status|submit-draft|heartbeat|publish')
            return 2
        if not is_help and sub != 'status':
            license_cmd = [sys.executable, '-X', 'utf8', str(_resolve_helper('license.py')), '--home', str(home)]
            if subprocess.call(license_cmd + ['check']):
                return 1
        return subprocess.call([sys.executable, '-X', 'utf8', str(cloud_script), '--home', str(home)] + argv[1:])
    if argv and argv[0] == 'pair':
        home = os.environ['ILSON_HOME']
        cloud_script = _resolve_helper('cloud_bridge.py')
        rest = argv[1:]
        if any(arg in ('--help', '-h') for arg in rest):
            return subprocess.call([sys.executable, '-X', 'utf8', str(cloud_script), '--home', str(home), 'pair', '--help'])
        has_cloud_or_code = any(arg in ('--cloud', '--code') or arg.startswith('--code=') for arg in rest)
        if not has_cloud_or_code:
            print('사용법: ilson cloud pair --code <사무소코드> (또는 ilson pair --code <사무소코드>)')
            return 2
        pair_args = [arg for arg in rest if arg != '--cloud']
        license_cmd = [sys.executable, '-X', 'utf8', str(_resolve_helper('license.py')), '--home', str(home)]
        if subprocess.call(license_cmd + ['check']):
            return 1
        return subprocess.call([sys.executable, '-X', 'utf8', str(cloud_script), '--home', str(home), 'pair'] + pair_args)
    if argv and argv[0] == 'doctor':
        if (Path(__file__).resolve().parent / 'lib/install_diagnostics.py').is_file():
            sys.path.insert(0, str(Path(__file__).resolve().parent / 'lib'))
        import install_diagnostics
        edition = 'windows-course' if os.name == 'nt' else 'intel-course'
        cli = str(Path(os.environ.get('LOCALAPPDATA', '')) / 'ilson-course/bin/ilson.cmd') if os.name == 'nt' else str(Path.home() / '.local/bin/ilson')
        vault = os.environ.get('ILSON_COURSE_VAULT', str(Path.home() / 'Documents/일손강의-1기'))
        # No new daemon in course editions. Doctor opportunistically runs a bounded tick.
        if not any(arg in ('--share', '--install', '--fix-permissions') for arg in argv[1:]):
            lib = Path(__file__).resolve().parent
            if (lib / 'lib/usage_timeline.py').is_file(): lib /= 'lib'
            if (lib / 'usage_timeline.py').is_file():
                subprocess.Popen([sys.executable, '-X', 'utf8', str(lib / 'usage_timeline.py'), '--home',
                                  os.environ.get('ILSON_COURSE_STATE', str(Path.home() / '.ilson-course')), 'tick'],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return install_diagnostics.main(argv[1:], edition=edition, cli=cli, vault=vault)
    if argv and argv[0] == 'usage' and len(argv) > 1:
        lib = Path(__file__).resolve().parent
        if (lib / 'lib/usage_timeline.py').is_file():
            lib /= 'lib'
        home = os.environ.get('ILSON_COURSE_STATE', str(Path.home() / '.ilson-course'))
        return subprocess.call([sys.executable, '-X', 'utf8', str(lib / 'usage_timeline.py'), '--home', home] + argv[1:])
    if argv and argv[0] == 'usage':
        print('Claude Code에서 /usage를 입력하거나 Claude 설정의 Usage에서 계정 한도를 확인하세요. 강의판은 자동 경고를 제공하지 않습니다.')
        return 0
    if argv and argv[0] in ('curator', 'diary', 'update'):
        lib = Path(__file__).resolve().parent
        if (lib / 'lib/curator.py').is_file():
            lib = lib / 'lib'
        home = Path(os.environ.get('ILSON_COURSE_STATE', Path.home() / '.ilson-course'))
        if argv[0] == 'update':
            return subprocess.call([sys.executable, '-X', 'utf8', str(lib / 'course_update.py')] + argv[1:])
        edition = 'windows-course' if os.name == 'nt' else 'intel-course'
        vault = os.environ.get('ILSON_COURSE_VAULT', str(Path.home() / 'Documents/일손강의-1기'))
        return subprocess.call([sys.executable, '-X', 'utf8', str(lib / 'curator.py'),
                                '--home', str(home), '--edition', edition, '--vault', vault] + argv[1:])
    if not argv or argv[0] not in ('learn', 'license', 'skill', 'report'):
        print('사용법: ilson open [--local] | ilson cloud pair|sync|status | ilson admin status|stop | ilson doctor --install [--share] | ilson doctor --fix-permissions | ilson --version | ilson usage | ilson curator|diary [--on|--off|--status|--addendum] | ilson update [--rollback] | ilson report weekly | ilson learn ... | ilson skill share|list|get|withdraw | ilson license activate|status')
        return 0 if not argv or argv[0] in ('-h', '--help') else 2
    lib = Path(__file__).resolve().parent
    home = Path(os.environ.get('ILSON_COURSE_STATE', Path.home() / '.ilson-course'))
    vault = Path(os.environ.get('ILSON_COURSE_VAULT', Path.home() / 'Documents' / '일손강의-1기'))
    license_cmd = [sys.executable, '-X', 'utf8', str(lib / 'license.py'), '--home', str(home)]
    if argv[0] == 'license':
        return subprocess.call(license_cmd + (argv[1:] or ['status']))
    if subprocess.call(license_cmd + ['check']):
        return 1
    if argv[0] == 'report':
        if argv[1:] != ['weekly']:
            print('사용법: ilson report weekly')
            return 2
        return subprocess.call([sys.executable, '-X', 'utf8', str(lib / 'weekly_summary.py'), '--vault', str(vault), '--flat-vault'])
    if argv[0] == 'skill':
        return subprocess.call([sys.executable, '-X', 'utf8', str(lib / 'skill_share.py'),
                                '--home', str(vault), '--license-home', str(home), '--flat-vault'] + argv[1:])
    return subprocess.call([sys.executable, '-X', 'utf8', str(lib / 'selflearn.py'),
                            '--home', str(vault), '--flat-vault'] + argv[1:])


def main(argv):
    previous = {name: os.environ.get(name) for name in ('ILSON_HOME', 'ILSON_PROFILE')}
    try:
        return _main(argv)
    finally:
        for name, value in previous.items():
            if value is None: os.environ.pop(name, None)
            else: os.environ[name] = value


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
