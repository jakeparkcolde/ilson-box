"""Opt-in status-line observer. Only allowlisted numbers are persisted."""
import json
import hashlib
import math
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time
import fcntl
from contextlib import contextmanager

MAX_INPUT = 1024 * 1024
FRESH_SECONDS = 900


def number(value, low, high):
    return value if type(value) in (int, float) and math.isfinite(value) and low <= value <= high else None


def extract(data, now=None):
    data = data if isinstance(data, dict) else {}
    limits = data.get('rate_limits') if isinstance(data.get('rate_limits'), dict) else {}
    cost = data.get('cost') if isinstance(data.get('cost'), dict) else {}
    result = {'observed_at': int(time.time() if now is None else now), 'cost_usd': number(cost.get('total_cost_usd'), 0, 1e9)}
    for key in ('five_hour', 'seven_day'):
        window = limits.get(key) if isinstance(limits.get(key), dict) else {}
        reset = number(window.get('resets_at'), 0, 1e11)
        result[key] = {'used_percentage': number(window.get('used_percentage'), 0, 100),
                       'resets_at': int(reset) if reset is not None and reset == int(reset) else None}
    return result


def read_json(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix='.usage-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def state_dir(home):
    return Path(home) / 'state' / 'usage'


def settings_path():
    return Path.home() / '.claude' / 'settings.json'


def backup_path(home, settings=None):
    settings = settings or settings_path()
    tag = hashlib.sha256(str(Path(home).resolve()).encode()).hexdigest()[:20]
    return settings.parent / ('ilson-usage-backup-' + tag + '.json')


def wrapper(home):
    return {'type': 'command', 'command': ' '.join(shlex.quote(str(x)) for x in (sys.executable, Path(__file__).resolve(), '--observe', Path(home).resolve()))}


def installed_value(home, backup):
    result = wrapper(home)
    old = backup.get('value') if isinstance(backup, dict) else None
    if isinstance(old, dict):
        for key in ('padding', 'refreshInterval'):
            if key in old:
                result[key] = old[key]
    return result


def is_wrapper(value, home, backup):
    return isinstance(backup, dict) and value == installed_value(home, backup)


def preview(home, settings=None):
    settings = settings or settings_path()
    if settings.is_symlink() or backup_path(home, settings).is_symlink():
        raise ValueError('설정 또는 복구 기록이 링크여서 자동 변경할 수 없습니다.')
    config = read_json(settings, {})
    if not isinstance(config, dict):
        raise ValueError('Claude 설정 형식을 확인하세요.')
    old = config.get('statusLine')
    backup = read_json(backup_path(home, settings), None)
    installed = is_wrapper(old, home, backup)
    supported = old is None or (isinstance(old, dict) and old.get('type') == 'command' and isinstance(old.get('command'), str) and set(old) <= {'type', 'command', 'padding', 'refreshInterval'})
    if isinstance(old, dict) and 'usage_observer.py' in str(old.get('command', '')) and not installed:
        supported = False
    # Project and local settings take precedence over user settings. Do not claim
    # a working connection when a Box-specific override exists.
    for name in ('settings.json', 'settings.local.json'):
        project = read_json(Path(home) / '.claude' / name, {})
        if not isinstance(project, dict) or 'statusLine' in project:
            supported = False
    return {'enabled': installed, 'existing': old is not None and not installed, 'supported': supported,
            'conflict': bool(backup is not None and not installed)}


@contextmanager
def settings_lock(settings):
    settings.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(settings.parent / '.ilson-usage.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def enable(home, settings=None):
    settings = settings or settings_path()
    with settings_lock(settings):
        _enable(home, settings)


def _enable(home, settings):
    state = preview(home, settings)
    if state['enabled']:
        return
    if state['conflict'] or not state['supported']:
        raise ValueError('기존 상태줄 설정을 안전하게 연결할 수 없습니다. 설정을 확인하세요.')
    config = read_json(settings, {})
    old = config.get('statusLine')
    # Persist before changing the setting; an interrupted setup can be recovered.
    write_json(backup_path(home, settings), {'present': 'statusLine' in config, 'value': old})
    if read_json(settings, {}) != config:
        raise ValueError('Claude 설정이 동시에 변경되어 연결을 멈췄습니다. 복구 기록을 확인하세요.')
    config['statusLine'] = installed_value(home, {'value': old})
    write_json(settings, config)


def disable(home, settings=None):
    settings = settings or settings_path()
    with settings_lock(settings):
        _disable(home, settings)


def _disable(home, settings):
    saved_path = backup_path(home, settings)
    if settings.is_symlink() or saved_path.is_symlink():
        raise ValueError('설정 또는 복구 기록이 링크여서 자동 복구할 수 없습니다.')
    backup = read_json(saved_path, None)
    if not isinstance(backup, dict):
        raise ValueError('복구할 설정 기록이 없습니다.')
    config = read_json(settings, {})
    if not isinstance(config, dict) or not is_wrapper(config.get('statusLine'), home, backup):
        raise ValueError('상태줄이 변경되어 자동 복구를 멈췄습니다. 기존 설정을 직접 확인하세요.')
    original = dict(config)
    if backup.get('present'):
        config['statusLine'] = backup.get('value')
    else:
        config.pop('statusLine', None)
    if read_json(settings, {}) != original:
        raise ValueError('Claude 설정이 동시에 변경되어 복구를 멈췄습니다.')
    write_json(settings, config)
    saved_path.unlink()


def observe(home, raw, now=None, notify=None, authorized=None):
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return
    sample = extract(value, now)
    folder = state_dir(home)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(folder / 'lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        write_json(folder / 'latest.json', sample)
        options = read_json(folder / 'alerts.json', {})
        sent = read_json(folder / 'sent.json', {})
        if not isinstance(options, dict) or not isinstance(sent, dict):
            return
        threshold = number(options.get('threshold'), 1, 100)
        if options.get('enabled') is not True or threshold is None:
            return
        for key in ('five_hour', 'seven_day'):
            window = sample[key]
            used, reset = window['used_percentage'], window['resets_at']
            if used is None or reset is None or reset <= sample['observed_at'] or used < threshold:
                continue
            marker = str(reset)
            seen = sent.get(key, [])
            if not isinstance(seen, list):
                seen = [seen] if isinstance(seen, str) else []
            if marker in seen:
                continue
            if authorized is None:
                from license import evaluate
                try:
                    allowed = evaluate(home)[0]
                except (OSError, ValueError, TypeError):
                    allowed = False
            else:
                allowed = authorized()
            if not allowed:
                continue
            # Mark before sending: crashes or failed deliveries never cause duplicate sends.
            sent[key] = (seen + [marker])[-32:]
            write_json(folder / 'sent.json', sent)
            message = f"Claude {'5시간' if key == 'five_hour' else '7일'} 한도 관측값이 {used}%입니다. /usage에서 확인하세요."
            if notify:
                notify(message)
            else:
                subprocess.run(['bash', str(Path(__file__).with_name('notify.sh')), 'usage'], input=message, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20, check=False)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--disable':
        try:
            disable(Path(sys.argv[2]))
            print('관측을 끄고 기존 상태줄을 복구했습니다.')
            return 0
        except (OSError, ValueError):
            print('자동 복구를 완료하지 못했습니다. Claude 상태줄 설정과 일손 복구 기록을 확인하세요.', file=sys.stderr)
            return 1
    if len(sys.argv) != 3 or sys.argv[1] != '--observe':
        return 2
    home = Path(sys.argv[2])
    raw = sys.stdin.buffer.read()
    backup = read_json(backup_path(home), {})
    old = backup.get('value') if isinstance(backup, dict) else None
    if len(raw) <= MAX_INPUT:
        try:
            if preview(home)['enabled']:
                observe(home, raw)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    if isinstance(old, dict) and isinstance(old.get('command'), str):
        try:
            p = subprocess.run(old['command'], shell=True, input=raw)
            return p.returncode
        except (OSError, subprocess.SubprocessError):
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
