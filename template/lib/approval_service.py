"""Manage the one per-user macOS approval receiver."""
import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile

LABEL = 'com.ilson.approval'


def manage(command, home, *, agents=None, launchctl='launchctl'):
    if sys.platform != 'darwin':
        raise ValueError('맥 Box 전용 기능입니다.')
    home = Path(home).resolve()
    if (home / 'state/sandbox').exists():
        raise ValueError('샌드박스에서는 수신기를 설치하지 않습니다.')
    agents = Path(agents or Path.home() / 'Library/LaunchAgents')
    if agents.is_symlink():
        raise ValueError('LaunchAgents 경로를 확인해 주세요.')
    agents.mkdir(parents=True, exist_ok=True)
    path = agents / (LABEL + '.plist')
    if path.is_symlink():
        raise ValueError('수신기 설정 경로를 확인해 주세요.')
    domain = 'gui/' + str(os.getuid())
    if command in ('install', 'stop'):
        check = subprocess.run([launchctl, 'print', domain + '/' + LABEL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if path.exists():
            try:
                with path.open('rb') as source:
                    current = plistlib.load(source)
                args = current.get('ProgramArguments', [])
                owned = (current.get('Label') == LABEL and len(args) == 4 and args[1:] == [str(home / 'lib/approval_telegram.py'), '--home', str(home)])
            except (OSError, ValueError, TypeError, AttributeError, plistlib.InvalidFileException):
                owned = False
            if not owned:
                raise ValueError('다른 Box의 수신기 설정이 있어 보존했습니다.')
        elif check.returncode == 0:
            raise ValueError('실행 중인 수신기의 소유자를 확인하지 못했습니다.')
        if check.returncode == 0:
            subprocess.run([launchctl, 'bootout', domain + '/' + LABEL], check=True)
    if command == 'install':
        config = {'Label': LABEL, 'ProgramArguments': ['/usr/bin/python3', str(home / 'lib/approval_telegram.py'), '--home', str(home)], 'RunAtLoad': True, 'KeepAlive': True, 'EnvironmentVariables': {'ILSON_HOME': str(home)}, 'Umask': 0o077}
        fd, temp = tempfile.mkstemp(dir=agents, prefix='.ilson-approval-')
        with os.fdopen(fd, 'wb') as out:
            plistlib.dump(config, out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
        subprocess.run([launchctl, 'enable', domain + '/' + LABEL], check=True)
        subprocess.run([launchctl, 'bootstrap', domain, str(path)], check=True)
        print('휴대폰 승인 수신기를 시작했습니다.')
    elif command == 'stop':
        # Disable only this label so launchd does not respawn it; retain the plist.
        subprocess.run([launchctl, 'disable', domain + '/' + LABEL], check=True)
        print('휴대폰 승인 수신기를 중지했습니다.')
    else:
        return subprocess.run([launchctl, 'print', domain + '/' + LABEL], check=False).returncode
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['install', 'stop', 'status'])
    parser.add_argument('--home', required=True)
    args = parser.parse_args()
    try:
        raise SystemExit(manage(args.command, args.home))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print('수신기 상태를 바꾸지 못했습니다. 설정을 확인해 주세요.', file=sys.stderr)
        raise SystemExit(1)
