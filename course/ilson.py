"""Course-only command: license protects learning, not the student's documents."""
import os
from pathlib import Path
import subprocess
import sys


def _main(argv):
    os.environ['ILSON_HOME'] = os.environ.get('ILSON_COURSE_STATE', str(Path.home() / '.ilson-course'))
    os.environ['ILSON_PROFILE'] = 'course'
    if any('—' in arg or '–' in arg for arg in argv):
        print('SMART_DASH: --help / --version처럼 ASCII 하이픈 두 개를 사용하세요.')
        return 2
    if argv == ['--version']:
        print('ilson ' + ('windows-course' if os.name == 'nt' else 'intel-course') + ' ILSON-DIAG-1')
        return 0
    if argv and argv[0] in ('open', 'admin'):
        lib = Path(__file__).resolve().parent
        if (lib / 'lib/web-admin.py').is_file(): lib /= 'lib'
        home = os.environ['ILSON_HOME']
        vault = os.environ.get('ILSON_COURSE_VAULT', str(Path.home() / 'Documents/일손강의-1기'))
        command = 'open' if argv[0] == 'open' else (argv[1] if len(argv) > 1 else 'status')
        extra = argv[1:] if argv[0] == 'open' else argv[2:]
        if command not in ('open', 'status', 'stop') or (extra and not (command == 'stop' and extra == ['--force'])):
            print('사용법: ilson open | ilson admin status|stop [--force]')
            return 2
        return subprocess.call([sys.executable, '-X', 'utf8', str(lib / 'web-admin.py'), command,
                                '--home', home, '--vault', vault, '--profile', 'course'] + extra)
    if argv and argv[0] == 'doctor':
        if (Path(__file__).resolve().parent / 'lib/install_diagnostics.py').is_file():
            sys.path.insert(0, str(Path(__file__).resolve().parent / 'lib'))
        import install_diagnostics
        edition = 'windows-course' if os.name == 'nt' else 'intel-course'
        cli = str(Path(os.environ.get('LOCALAPPDATA', '')) / 'ilson-course/bin/ilson.cmd') if os.name == 'nt' else str(Path.home() / '.local/bin/ilson')
        vault = os.environ.get('ILSON_COURSE_VAULT', str(Path.home() / 'Documents/일손강의-1기'))
        # No new daemon in course editions. Doctor opportunistically runs a bounded tick.
        if not any(arg in ('--share', '--install') for arg in argv[1:]):
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
        print('사용법: ilson open | ilson admin status|stop | ilson doctor --install [--share] | ilson --version | ilson usage | ilson curator|diary [--on|--off|--status|--addendum] | ilson update [--rollback] | ilson report weekly | ilson learn ... | ilson skill share|list|get|withdraw | ilson license activate|status')
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
