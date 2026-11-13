"""Offline install diagnostics v1. Never persist command output, credentials or notes."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import time

VERSION = 'ILSON-DIAG-1'
EDITIONS = {'full-mac', 'intel-course', 'windows-course', 'unknown'}
STEPS = set('bootstrap.start download.installer preflight.platform preflight.arch runtime.python runtime.node tools.brew tools.git tools.jq tools.gh tools.coreutils tools.python tools.node tools.claude tools.codex tools.aside tools.herdr tools.hc tools.tvly tools.claude.download tools.claude.execute tools.codex.download tools.codex.execute tools.vendor.download tools.vendor.execute apps.orca apps.obsidian apps.tailscale apps.aside apps.herdr kit.prepare vault.prepare helper.install cli.link path.persist verify.absolute verify.current verify.new-window verify.simulated setup.stage setup.machine setup.jobs setup.web setup.telegram setup.auth-pending finish'.split())
REASONS = set('STARTED OK REUSED_VERIFIED DEPENDENCY_FAILED PYTHON_TOO_OLD RUNTIME_MISSING WRONG_INSTALLER UNSUPPORTED_OS SMART_DASH UNKNOWN_OPTION COMMAND_CONFLICT OUTSIDE_VAULT DNS_FAILED HTTP_FAILED TIMEOUT TLS_FAILED DOWNLOAD_FAILED EXECUTE_FAILED VERIFY_FAILED HASH_MISMATCH USER_MODIFIED PATH_MANUAL AUTH_PENDING USER_CONFIRMATION_REQUIRED USER_DECLARED DRY_RUN NOT_APPLICABLE NOT_SELECTED INTERRUPTED LOG_UNAVAILABLE DETAIL_SUPPRESSED CLOCK_UNVERIFIED'.split())
HOSTS = {'none', 'custom_host', 'raw.githubusercontent.com', 'codeload.github.com', 'github.com', 'claude.ai', 'chatgpt.com', 'www.python.org', 'releases.herdr.dev', 'releases.aside.com'}
EVENTS = {'run-start', 'step-start', 'step-end', 'run-end'}
RESULTS = {'ok', 'failed', 'skipped-with-reason', 'running'}
TSV_FIELDS = 'schema run_id parent_run_id seq installer_version source_ref edition event step_id attempt started_at ended_at elapsed_ms result reason_code required exit_code exit_source host http_code transport_code proxy clock environment'.split()
EXTRA_FIELDS = {'environment', 'path_facts', 'cwd_kind', 'cwd_display', 'error_tail'}
ID = re.compile(r'^[a-f0-9]{32}$')
STAMP = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
EXIT_SOURCES = {'none', 'native', 'curl', 'exception', 'installer', 'doctor'}


def utc():
    return dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def redact_event(event):
    """Rebuild from enums, bounded numbers and boolean facts; raw tails are suppressed."""
    clean = {}
    enums = {'edition': EDITIONS, 'event': EVENTS, 'step_id': STEPS, 'reason_code': REASONS,
             'result': RESULTS, 'host': HOSTS, 'exit_source': EXIT_SOURCES,
             'proxy': {'true', 'false', 'unknown'}, 'clock': {'unverified', 'monotonic'},
             'cwd_kind': {'inside_vault', 'outside_vault', 'unknown'}}
    for key, allowed in enums.items():
        if isinstance(event.get(key), str) and event[key] in allowed:
            clean[key] = event[key]
    for key in ('schema', 'seq', 'attempt', 'elapsed_ms', 'exit_code', 'http_code', 'transport_code'):
        value = event.get(key)
        if type(value) is int and 0 <= value <= 2147483647:
            clean[key] = value
        elif value is None and key in ('elapsed_ms', 'exit_code', 'http_code', 'transport_code'):
            clean[key] = None
    for key in ('run_id', 'parent_run_id'):
        if ID.fullmatch(str(event.get(key, ''))):
            clean[key] = event[key]
        elif key == 'parent_run_id':
            clean[key] = None
    for key in ('started_at', 'ended_at'):
        if STAMP.fullmatch(str(event.get(key, ''))):
            clean[key] = event[key]
        elif key == 'ended_at':
            clean[key] = None
    if event.get('installer_version') == VERSION:
        clean['installer_version'] = VERSION
    ref = event.get('source_ref', '')
    if isinstance(ref, str) and (ref == VERSION or re.fullmatch(r'[a-f0-9]{7,40}', ref)):
        clean['source_ref'] = ref
    if type(event.get('required')) is bool:
        clean['required'] = event['required']
    if 'error_tail' in event:
        clean['error_tail'] = ['DETAIL_SUPPRESSED']
    if 'cwd_display' in event:
        clean['cwd_display'] = '[작업폴더]'
    facts = event.get('path_facts', {})
    if isinstance(facts, dict):
        clean['path_facts'] = {k: facts[k] for k in ('bin_in_path', 'cli_exists', 'vault_exists', 'command_matches') if type(facts.get(k)) is bool}
    env = event.get('environment', {})
    if isinstance(env, dict):
        safe = {}
        for key, allowed in {'os': {'Darwin', 'Windows', 'Linux', 'unknown'}, 'arch': {'arm64', 'x86_64', 'AMD64', 'unknown'}, 'shell': {'sh', 'bash', 'zsh', 'powershell', 'unknown'}}.items():
            if env.get(key) in allowed:
                safe[key] = env[key]
        for key in ('os_version', 'shell_version', 'python', 'node', 'claude'):
            value = env.get(key)
            if isinstance(value, str) and (value in ('missing', 'unknown') or re.fullmatch(r'\d{1,3}(\.\d{1,3}){1,3}', value)):
                safe[key] = value
        if type(env.get('rosetta')) is bool:
            safe['rosetta'] = env['rosetta']
        clean['environment'] = safe
    return clean


def validate_event(event):
    if not isinstance(event, dict) or set(event) - set(TSV_FIELDS) - EXTRA_FIELDS:
        raise ValueError('INVALID_EVENT')
    clean = redact_event(event)
    needed = {'schema', 'run_id', 'seq', 'installer_version', 'source_ref', 'edition', 'event', 'step_id', 'attempt', 'started_at', 'result', 'reason_code', 'required'}
    if not needed <= clean.keys() or clean['schema'] != 1 or clean['seq'] < 1 or clean['attempt'] < 1:
        raise ValueError('INVALID_EVENT')
    if any(clean.get(k) != v for k, v in event.items() if k not in ('error_tail', 'cwd_display')):
        raise ValueError('INVALID_EVENT')
    return clean


def safe_path(path, private=False):
    path = Path(os.path.abspath(path))
    # macOS system aliases are fixed root-owned links, not user-controlled storage.
    if sys.platform == 'darwin' and path.parts[1:2] in [('var',), ('tmp',), ('etc',)]:
        path = Path('/private') / path.relative_to('/')
    for part in [*reversed(path.parents), path]:
        if part.is_symlink():
            raise ValueError('UNSAFE_PATH')
        if part.exists():
            info = part.stat()
            if getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('UNSAFE_PATH')
            if os.name != 'nt':
                # System-owned ancestors are normal; task-owned storage must be private.
                if info.st_uid not in (0, os.getuid()):
                    raise ValueError('UNSAFE_OWNER')
                if part == path and private and (info.st_uid != os.getuid() or info.st_mode & 0o077):
                    raise ValueError('UNSAFE_PERMISSIONS')
    return path


def diagnostics_root():
    default = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'ilson-diagnostics' if os.name == 'nt' else Path.home() / '.ilson-diagnostics'
    return safe_path(os.environ.get('ILSON_DIAGNOSTICS_DIR', default), private=True)


def private_dir(path):
    safe_path(path, private=True)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return safe_path(path, private=True)


def read_run(directory):
    events, damaged = [], False
    safe_path(directory, private=True)
    files = [p for p in (directory / 'events.tsv', directory / 'events.jsonl') if p.exists()]
    for file in files:
        safe_path(file, private=True)
        if file.stat().st_size > 1024 * 1024:
            return [], True
        data = file.read_bytes()
        if data and not data.endswith(b'\n'):
            damaged = True
        for raw in data.splitlines():
            try:
                if file.suffix == '.tsv':
                    values = raw.decode('ascii').split('\t')
                    if len(values) != len(TSV_FIELDS):
                        raise ValueError('INVALID_EVENT')
                    event = dict(zip(TSV_FIELDS, values))
                    for key in ('schema', 'seq', 'attempt', 'elapsed_ms', 'exit_code', 'http_code', 'transport_code'):
                        event[key] = None if event[key] == '-' else int(event[key])
                    event['environment'] = json.loads(event['environment'])
                    event['required'] = {'true': True, 'false': False}[event['required']]
                    for key in ('parent_run_id', 'ended_at'):
                        if event[key] == '-': event[key] = None
                else:
                    event = json.loads(raw.decode('utf-8'))
                events.append(validate_event(event))
            except (ValueError, UnicodeError, KeyError, TypeError):
                damaged = True
    seen = set()
    for e in events:
        if e['run_id'] != directory.name or e['seq'] in seen: damaged = True
        seen.add(e['seq'])
    return sorted(events, key=lambda e: e['seq']), damaged


def summarize_run(events, damaged=False):
    """Failures remain visible even if a later run-end incorrectly claims success."""
    last, active = {}, set()
    for e in events:
        key = (e['step_id'], e['attempt'])
        if e['event'] == 'step-start': active.add(key)
        if e['event'] == 'step-end':
            active.discard(key)
            last[e['step_id']] = e
    failures = [e for e in last.values() if e['required'] and e['result'] != 'ok' and e['reason_code'] not in ('DRY_RUN', 'NOT_APPLICABLE', 'NOT_SELECTED')]
    pending = [e for e in last.values() if not e['required'] and e['result'] != 'ok' and e['reason_code'] not in ('NOT_APPLICABLE', 'NOT_SELECTED', 'DRY_RUN')]
    end = next((e for e in reversed(events) if e['event'] == 'run-end'), None)
    interrupted = damaged or bool(active) or not end
    code = 3 if interrupted else 1 if failures or end['result'] == 'failed' else 4 if pending else 0
    return {'run_id': events[0]['run_id'] if events else None, 'edition': events[0]['edition'] if events else 'unknown',
            'status': 'interrupted' if interrupted else 'failed' if code == 1 else 'pending' if code == 4 else 'ok',
            'exit_code': code, 'first_failure': failures[0]['reason_code'] if failures else None,
            'current': last.get('verify.current', {}).get('result', 'unconfirmed'),
            'new_window': last.get('verify.new-window', {}).get('result', 'unconfirmed'),
            'steps': {key: {'result': e['result'], 'reason_code': e['reason_code']} for key, e in last.items()}}


def retain(root, now=None):
    """Only exact owned run/share files; unknown contents, links and active runs survive."""
    now = time.time() if now is None else now
    runs = root / 'runs'
    if not runs.exists(): return
    safe_path(runs, private=True)
    known = []
    for directory in runs.iterdir():
        if not ID.fullmatch(directory.name): continue
        try:
            safe_path(directory, private=True)
            files = list(directory.iterdir())
            if not files or any(p.name not in ('events.tsv', 'events.jsonl') or not p.is_file() or p.is_symlink() for p in files): continue
            events, damaged = read_run(directory)
            if not any(e['event'] == 'run-end' for e in events) and now - directory.stat().st_mtime < 86400: continue
            known.append((directory, files, max(p.stat().st_mtime for p in files), sum(p.stat().st_size for p in files)))
        except (OSError, ValueError): continue
    known.sort(key=lambda item: item[2], reverse=True)
    total = 0
    for index, (directory, files, stamp, size) in enumerate(known):
        total += size
        if index >= 20 or total > 10 * 1024 * 1024 or now - stamp > 30 * 86400:
            for file in files: safe_path(file, private=True).unlink()
            directory.rmdir()
    share = root / 'share'
    if share.exists():
        safe_path(share, private=True)
        for file in share.iterdir():
            if re.fullmatch(r'IL-[A-F0-9]{12}\.(json|txt)', file.name) and not file.is_symlink() and file.is_file() and now - file.stat().st_mtime > 30 * 86400:
                safe_path(file, private=True).unlink()


def export_share(events, root, damaged=False):
    clean = [validate_event(redact_event(e)) for e in events]
    for e in clean: e.pop('cwd_display', None)
    summary = summarize_run(clean, damaged)
    folder = private_dir(root / 'share')
    reference = 'IL-' + secrets.token_hex(6).upper()
    payload = {'schema': 1, 'reference': reference, 'summary': summary, 'events': clean}
    for suffix, data in [('json', json.dumps(payload, ensure_ascii=False, indent=2)), ('txt', json.dumps(summary, ensure_ascii=False, indent=2) + '\n파일을 직접 검토해 전달하세요. 자동 전송하지 않았습니다.\n')]:
        path = folder / (reference + '.' + suffix)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream: stream.write(data + '\n')
    return reference


def append_confirmation(directory, events, kind, matched):
    if not events: raise ValueError('NO_RUN')
    base = {k: events[0][k] for k in ('run_id', 'installer_version', 'source_ref', 'edition')}
    seq = max(e['seq'] for e in events)
    step = 'verify.' + {'current': 'current', 'new': 'new-window', 'simulated': 'simulated'}[kind]
    attempt = 1 + max((e['attempt'] for e in events if e['step_id'] == step), default=0)
    for event_type in ('step-start', 'step-end'):
        seq += 1
        e = dict(base, schema=1, seq=seq, event=event_type, step_id=step, attempt=attempt, started_at=utc(), required=False,
                 result='running' if event_type == 'step-start' else 'ok' if matched else 'failed',
                 reason_code='STARTED' if event_type == 'step-start' else 'USER_DECLARED' if matched else 'COMMAND_CONFLICT')
        validate_event(e)
        file = directory / 'events.jsonl'
        safe_path(file, private=True)
        fd = os.open(file, os.O_CREAT | os.O_APPEND | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(fd, 'a', encoding='utf-8') as stream: stream.write(json.dumps(e) + '\n')


def next_lines(edition, run_id, cli=None, vault=None):
    if not run_id or not ID.fullmatch(run_id): return []
    if edition == 'windows-course':
        return ["$env:Path=[Environment]::GetEnvironmentVariable('Path','Machine')+';'+[Environment]::GetEnvironmentVariable('Path','User'); ilson doctor --install --confirm-shell current --run " + run_id,
                'ilson doctor --install --confirm-shell new --run ' + run_id,
                '& "$env:LOCALAPPDATA\\ilson-course\\bin\\ilson.cmd" doctor --install --run ' + run_id]
    target = cli or str(Path.home() / ('.ilson-cli/ilson' if edition == 'full-mac' else '.local/bin/ilson'))
    if any(ord(c) < 32 or ord(c) == 127 for c in target): return ['강사와 경로 확인']
    return ['export PATH="$HOME/.local/bin:$PATH"; ilson doctor --install --confirm-shell current --run ' + run_id,
            'ilson doctor --install --confirm-shell new --run ' + run_id,
            shlex.quote(target) + ' doctor --install --run ' + run_id]


def main(argv=None, edition='unknown', cli=None, vault=None):
    parser = argparse.ArgumentParser(description='일손 로컬 설치 점검 · 네트워크 연결 없음')
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--share', action='store_true')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--self-check', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--simulate-shell', choices=('zsh', 'bash'), help='명시적으로 셸 초기화 파일 실행을 허용하고 모의 점검')
    parser.add_argument('--run')
    parser.add_argument('--confirm-shell', choices=('current', 'new'))
    args = parser.parse_args(argv)
    try:
        if args.self_check:
            print(json.dumps({'version': VERSION, 'edition_expected': edition}))
            return 0
        root = diagnostics_root()
        if args.run and not ID.fullmatch(args.run): raise ValueError('INVALID_RUN')
        retain(root)
        folders = sorted((root / 'runs').glob('*'), key=lambda p: p.stat().st_mtime, reverse=True) if (root / 'runs').exists() else []
        directory = root / 'runs' / args.run if args.run else next((p for p in folders if ID.fullmatch(p.name)), None)
        events, damaged = read_run(directory) if directory and directory.exists() else ([], False)
        if args.simulate_shell:
            if not args.run or not events: raise ValueError('RUN_REQUIRED')
            shell = '/bin/' + args.simulate_shell
            expected = Path(cli or str(Path.home() / '.local/bin/ilson')).resolve()
            matched = True
            for flags in ('-lic', '-ic'):
                try:
                    probe = subprocess.run([shell, flags, 'command -v ilson'], capture_output=True, timeout=5)
                    value = probe.stdout[-4096:].decode('utf-8', errors='replace').strip().splitlines()
                    matched = matched and probe.returncode == 0 and bool(value) and Path(value[-1]).resolve() == expected
                except (OSError, subprocess.TimeoutExpired): matched = False
            append_confirmation(directory, events, 'simulated', matched)
            events, damaged = read_run(directory)
        if args.confirm_shell:
            if not args.run: raise ValueError('RUN_REQUIRED')
            expected = cli or str(Path.home() / '.local/bin/ilson')
            found = shutil.which('ilson')
            matched = bool(found and Path(found).resolve() == Path(expected).resolve())
            if matched:
                try:
                    output = subprocess.run([found, '--version'], capture_output=True, timeout=5)
                    matched = output.returncode == 0 and VERSION.encode() in output.stdout and edition.encode() in output.stdout
                except (OSError, subprocess.TimeoutExpired): matched = False
            append_confirmation(directory, events, args.confirm_shell, matched)
            events, damaged = read_run(directory)
        summary = summarize_run(events, damaged)
        if edition != 'unknown' and events and summary['edition'] not in (edition, 'unknown'):
            summary.update(status='wrong_installer', exit_code=2, first_failure='WRONG_INSTALLER')
        selected_vault = Path(vault) if vault else Path.home() / 'Documents/일손강의-1기'
        try: inside = Path.cwd().is_relative_to(selected_vault.resolve())
        except (OSError, ValueError): inside = False
        summary['cwd_kind'] = 'inside_vault' if inside else 'outside_vault'
        summary['vault_exists'] = selected_vault.is_dir()
        summary['version'] = VERSION
        summary['edition_expected'] = edition
        if args.share:
            if not events: raise ValueError('NO_RUN')
            summary['reference'] = export_share(events, root, damaged)
        if args.json: print(json.dumps(summary, ensure_ascii=False))
        else:
            print('일손 설치 점검 · ' + edition + ' · ' + VERSION)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            print('현재 창/새 창은 별도 확인하며 새 창 여부는 사용자의 선언입니다.')
            for line in next_lines(summary['edition'], summary['run_id'], cli, vault): print(line)
            if not inside:
                value = str(selected_vault)
                if all(ord(c) >= 32 and ord(c) != 127 for c in value):
                    print(('Set-Location -LiteralPath ' + "'" + value.replace("'", "''") + "'") if edition == 'windows-course' else 'cd ' + shlex.quote(value))
            if summary.get('first_failure') == 'PYTHON_TOO_OLD':
                print('Python 3.10 이상을 공식 macOS 설치기로 설치한 뒤 검수된 Intel 강의판 설치 명령을 다시 실행하세요: https://www.python.org/downloads/macos/')
            if args.share: print('공유 참조: ' + summary['reference'] + ' (share 폴더의 TXT/JSON 파일도 함께 전달하세요. 자동 전송하지 않았습니다.)')
        return summary['exit_code']
    except (OSError, ValueError):
        print('LOG_UNAVAILABLE: 로컬 진단 불가. 성공 기록이나 공유 파일 생성이 확인되지 않았습니다.', file=sys.stderr)
        return 3


if __name__ == '__main__':
    sys.exit(main())
