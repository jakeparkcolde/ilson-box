# coding: utf-8
"""Opt-in, bounded local Claude metadata ledger. No provider text is persisted.

Codex adapter intentionally unsupported until cumulative counters are validated.
Network code lives in usage_sync; status/export are always offline.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import hashlib
import hmac
import itertools
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import tempfile
import time
import uuid
from zoneinfo import ZoneInfo

VERSION = 'usage-v1'
COUNTERS = ('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_creation_tokens')
MODELS = ('claude-sonnet-4-5', 'claude-sonnet-4-6', 'claude-opus-4-1',
          'claude-opus-4-5', 'claude-opus-4-6', 'claude-haiku-4-5')
MAX_INT = 2**53 - 1
PRICE_SOURCE = 'https://platform.claude.com/docs/en/about-claude/pricing'
PRICE_DATE = '2026-11-15'
# USD / million: ordinary input, output, cache read. Cache writes are 1.25x–2x input.
PRICES = {'claude-sonnet-4-5': (3, 15, .3), 'claude-sonnet-4-6': (3, 15, .3),
          'claude-opus-4-1': (15, 75, 1.5), 'claude-opus-4-5': (5, 25, .5),
          'claude-opus-4-6': (5, 25, .5), 'claude-haiku-4-5': (1, 5, .1)}
PRIVACY = ('사용 기록과 강사 공유는 각각 기본 꺼짐입니다. 선택한 실습 폴더의 날짜·도구·모델·세션·본인 대화 횟수·토큰 숫자만 집계합니다. '
           '대화 본문·제목·파일명·경로·프로젝트명·컴퓨터명·사용자명은 전송하지 않습니다. 수신자는 강사 Jake이며 참여는 선택이고 성적·출석 평가와 연결하지 않습니다. '
           '로컬 최근 366일, 서버 첫 수신 후 최대 60일(강의 종료+60일이 먼저면 그날) 보관합니다. 끄기는 새 수집·전송 중단, 연결 해제는 서버 삭제도 요청합니다. '
           '공급자 로그·별도 사본·OS 백업은 삭제하지 않습니다. 후기 공개·설문 연결은 별도 동의입니다.')


class UsageError(ValueError):
    pass


def stamp(value):
    if not isinstance(value, str) or len(value) > 40:
        raise UsageError('시각 형식 확인이 필요합니다.')
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise UsageError('시간대가 없는 기록입니다.')
    return dt.timestamp()


def local_zone(name):
    # Windows CPython commonly has no IANA database. Modern Korea has no DST;
    # these explicit fallbacks cover all retained dates without an install.
    if name in ('UTC', 'Etc/UTC'):
        return timezone.utc
    try:
        return ZoneInfo(name)
    except (ValueError, KeyError):
        if name == 'Asia/Seoul':
            return timezone(timedelta(hours=9), name='Asia/Seoul')
        raise UsageError('이 기기의 IANA 시간대 자료가 없습니다. UTC 또는 Asia/Seoul을 사용하세요.') from None


def count(value):
    return value if type(value) is int and 0 <= value <= MAX_INT else None


def model_id(value):
    if isinstance(value, str):
        for name in MODELS:
            if value == name or re.fullmatch(re.escape(name) + r'-\d{8}', value):
                return name
    return None


def safe(path, private=False):
    """Reject links/reparse points and foreign-owned files, including ancestors."""
    path = Path(os.path.abspath(path))
    for p in (path, *path.parents):
        if sys.platform == 'darwin' and str(p) in ('/tmp', '/var', '/etc'):
            continue  # fixed OS aliases; resolved below before I/O
        try:
            info = p.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise UsageError('링크 경로는 사용할 수 없습니다.')
        if hasattr(os, 'getuid') and info.st_uid not in (0, os.getuid()):
            raise UsageError('본인 소유 경로만 사용할 수 있습니다.')
        if p == path:
            if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                raise UsageError('공유된 파일은 사용할 수 없습니다.')
            if private and os.name != 'nt' and (info.st_uid != os.getuid() or info.st_mode & 0o077):
                raise UsageError('기록 폴더·파일의 개인 권한을 확인하세요.')
    return path.resolve()


def write_json(path, value):
    safe(path, private=True)
    fd, temporary = tempfile.mkstemp(prefix='.usage-', dir=path.parent)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class Ledger:
    def __init__(self, home, *, user_home=None, clock=time.time):
        self.home = Path(home).absolute()
        self.user_home = Path(user_home or Path.home()).absolute()
        self.root = self.home / 'state/usage-timeline'
        self.clock = clock

    def config(self):
        if not self.root.exists():
            return {'enabled': False, 'sync_enabled': False}
        safe(self.root, private=True)
        target = self.root / 'settings.json'
        safe(target, private=True)
        if not target.exists():
            return {'enabled': False, 'sync_enabled': False}
        if target.stat().st_size > 65536:
            raise UsageError('사용 기록 설정을 확인하세요.')
        with target.open(encoding='utf-8') as stream:
            return json.load(stream)

    def prepare(self):
        safe(self.root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        safe(self.root, private=True)
        # Prevent even a snapshot racing first collection from adding private files.
        ignore = self.home / '.gitignore'
        safe(ignore)
        existing = ignore.read_text(encoding='utf-8') if ignore.exists() else ''
        if '/state/usage-timeline/' not in existing.splitlines():
            with ignore.open('a', encoding='utf-8') as stream:
                stream.write('\n/state/usage-timeline/\n')

    @contextmanager
    def locked(self, *, wait=False):
        self.prepare()
        path = self.root / 'lock'
        safe(path, private=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            deadline = time.monotonic() + (3 if wait else 0)
            while True:
                try:
                    if os.name == 'nt':
                        import msvcrt
                        if not os.fstat(fd).st_size:
                            os.write(fd, b'0')
                        os.lseek(fd, 0, 0)
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise UsageError('사용 기록 처리 중입니다. 잠시 후 다시 시도하세요.') from None
                    time.sleep(0.02)
            yield
        finally:
            os.close(fd)

    def save(self, cfg):
        write_json(self.root / 'settings.json', cfg)

    def connect(self):
        path = self.root / 'ledger.sqlite3'
        safe(path, private=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        os.close(fd)
        db = sqlite3.connect(path, timeout=0.1)
        db.row_factory = sqlite3.Row
        db.executescript('''
          CREATE TABLE IF NOT EXISTS events (
            key TEXT PRIMARY KEY, session TEXT, at REAL, kind TEXT, model TEXT,
            input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER,
            cache_creation_tokens INTEGER, quality TEXT, seen_at REAL);
          CREATE TABLE IF NOT EXISTS cursors (key TEXT PRIMARY KEY, inode TEXT, offset INTEGER);
        ''')
        if 'seen_at' not in {r['name'] for r in db.execute('PRAGMA table_info(events)')}:
            db.execute('ALTER TABLE events ADD COLUMN seen_at REAL DEFAULT 0')
        return db

    def on(self, workspace, zone, *, backfill=None):
        if (self.home / 'state/company.json').exists():
            raise UsageError('회사 모드 사용 기록은 준비 중입니다. 개인 실습 기기에서 사용하세요.')
        try:
            local_zone(zone)
        except (ValueError, KeyError):
            raise UsageError('IANA 시간대를 확인하세요.') from None
        workspace = safe(Path(workspace).expanduser())
        if not workspace.is_dir() or not workspace.is_relative_to(self.user_home.resolve()):
            raise UsageError('본인 홈 안의 실습 폴더를 선택하세요.')
        now = self.clock()
        with self.locked():
            cfg = self.config()
            if cfg.get('timezone', zone) != zone:
                raise UsageError('시간대 변경은 기존 기록 삭제 후 가능합니다.')
            if cfg.get('enabled'):
                if cfg.get('workspace') != str(workspace):
                    raise UsageError('먼저 기록을 끈 뒤 새 실습 폴더를 선택하세요.')
                return
            start = now
            if backfill:
                try:
                    day = date.fromisoformat(backfill)
                    start = datetime.combine(day, datetime.min.time(), local_zone(zone)).timestamp()
                except ValueError:
                    raise UsageError('불러올 시작 날짜를 확인하세요.') from None
                if not now - 366 * 86400 <= start <= now:
                    raise UsageError('불러오기는 최근 366일 이내 날짜만 가능합니다.')
            cfg.setdefault('device_id', str(uuid.uuid4()))
            cfg.setdefault('salt', os.urandom(32).hex())
            cfg.setdefault('revision', 1)
            if cfg.get('workspace') != str(workspace):
                cfg['windows'] = []  # Old folder consent never authorizes a new folder's past logs.
            cfg.setdefault('windows', [])
            cfg['windows'].append([start, None])
            cfg.update(enabled=True, workspace=str(workspace), timezone=zone,
                       partial=False, format_partial=False, consent_version=VERSION, codex_enabled=False)
            self.save(cfg)

    def off(self):
        if not self.root.exists():
            return
        with self.locked(wait=True):
            cfg = self.config()
            if cfg.get('enabled') and cfg.get('windows'):
                cfg['windows'][-1][1] = self.clock()
            cfg.update(enabled=False, sync_enabled=False)
            self.save(cfg)

    def key(self, cfg, value):
        return hmac.new(bytes.fromhex(cfg['salt']), value.encode('utf-8'), hashlib.sha256).hexdigest()

    def source(self, cfg):
        encoded = re.sub(r'[^a-zA-Z0-9]', '-', cfg['workspace'])
        return self.user_home / '.claude/projects' / encoded

    def parse(self, obj, cfg, now):
        """Return whitelisted event only. Unknown shapes produce no fabricated counts."""
        if not isinstance(obj, dict):
            raise UsageError('partial')
        kind = obj.get('type')
        if kind in ('file-history-snapshot', 'progress', 'system', 'queue-operation', 'summary', 'last-prompt'):
            return None
        if kind not in ('user', 'assistant'):
            raise UsageError('partial')
        if obj.get('isSidechain') is True or obj.get('isMeta') is True:
            return None
        if obj.get('cwd') != cfg['workspace']:
            if 'cwd' not in obj:
                raise UsageError('partial')
            return None
        at = stamp(obj.get('timestamp'))
        if at > now + 300:
            raise UsageError('partial')
        if not any(start <= at and (end is None or at <= end) for start, end in cfg['windows']):
            return None
        message = obj.get('message')
        if not isinstance(message, dict) or message.get('role') != kind:
            raise UsageError('partial')
        session = obj.get('sessionId')
        ident = message.get('id') if kind == 'assistant' else obj.get('uuid')
        if not all(isinstance(v, str) and 0 < len(v) < 256 for v in (session, ident)):
            raise UsageError('partial')
        if kind == 'user':
            content = message.get('content')
            if isinstance(content, list):
                if any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in content):
                    return None
                if not content or any(not isinstance(b, dict) or b.get('type') != 'text' or not isinstance(b.get('text'), str) for b in content):
                    raise UsageError('partial')
            elif not isinstance(content, str):
                raise UsageError('partial')
            counters = [None] * 4
            model = None
            quality = 'observed'
        else:
            usage = message.get('usage')
            if not isinstance(usage, dict):
                raise UsageError('partial')
            counters = [count(usage.get(k)) for k in ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')]
            model = model_id(message.get('model'))
            quality = 'partial' if None in counters or model is None else 'observed'
        return (self.key(cfg, kind + ':' + session + ':' + ident), self.key(cfg, session), at, kind, model, *counters, quality, at)

    def collect(self):
        cfg = self.config()
        if not cfg.get('enabled') or (self.home / 'state/company.json').exists():
            return self.summary()
        with self.locked():
            cfg = self.config()
            if not cfg.get('enabled'):
                return self.summary()
            now, started = self.clock(), time.monotonic()
            partial = cfg.get('format_partial', False)
            format_partial = partial
            source = self.source(cfg)
            try:
                safe(source)
                files = list(itertools.islice(source.glob('*.jsonl'), 4097)) if source.is_dir() else []
                if len(files) > 4096:
                    files = files[:4096]
                    partial = True
            except (OSError, UsageError):
                files, partial = [], True
            db = self.connect()
            try:
                cursors = {r['key']: r for r in db.execute('SELECT * FROM cursors')}
                def priority(path):
                    try:
                        info = path.lstat()
                        old = cursors.get(self.key(cfg, str(path)))
                        inode = str(info.st_dev) + ':' + str(info.st_ino)
                        return (bool(old and old['inode'] == inode and old['offset'] == info.st_size), path.name)
                    except OSError:
                        return (False, path.name)
                files.sort(key=priority)
                if len(files) > 256 and any(not priority(p)[0] for p in files[256:]):
                    partial = True
                for path in files[:256]:
                    if time.monotonic() - started > 2:
                        partial = True
                        break
                    try:
                        safe(path)
                        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
                        with os.fdopen(fd, 'rb') as stream:
                            info = os.fstat(stream.fileno())
                            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or (hasattr(os, 'getuid') and info.st_uid != os.getuid()):
                                raise UsageError('partial')
                            key = self.key(cfg, str(path))
                            inode = str(info.st_dev) + ':' + str(info.st_ino)
                            old = db.execute('SELECT inode,offset FROM cursors WHERE key=?', (key,)).fetchone()
                            offset = old['offset'] if old and old['inode'] == inode and info.st_size >= old['offset'] else 0
                            stream.seek(offset)
                            budget = 2 * 1024 * 1024
                            while budget > 0:
                                line = stream.readline(min(1024 * 1024, budget) + 1)
                                if not line:
                                    break
                                if not line.endswith(b'\n'):
                                    partial = True
                                    break
                                budget -= len(line)
                                offset += len(line)
                                try:
                                    event = self.parse(json.loads(line), cfg, now)
                                    if event:
                                        existing = db.execute('SELECT * FROM events WHERE key=?', (event[0],)).fetchone()
                                        if existing:
                                            # Replayed/rotated old chunks cannot rewind a final message's usage.
                                            first_at = min(existing['at'], event[2])
                                            if event[-1] < (existing['seen_at'] or existing['at']):
                                                event = tuple(existing)
                                            elif event[-1] == existing['seen_at']:
                                                # Equal timestamps with conflicting usage cannot establish a final value.
                                                if tuple(existing)[5:9] != event[5:9]:
                                                    event = (*event[:5], None, None, None, None, 'partial', event[-1])
                                            event = (event[0], event[1], first_at, *event[3:])
                                            if tuple(existing) == event:
                                                continue
                                        db.execute('INSERT OR REPLACE INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?)', event)
                                except (ValueError, TypeError, KeyError, OverflowError):
                                    partial = format_partial = True
                            if offset < info.st_size:
                                partial = True
                            db.execute('INSERT OR REPLACE INTO cursors VALUES (?,?,?)', (key, inode, offset))
                    except (OSError, ValueError):
                        partial = True
                db.execute('DELETE FROM events WHERE at < ?', (now - 366 * 86400,))
                db.commit()
                rows = self.rows(db, cfg)
                old_rows = self._ledger_rows()
                if rows != old_rows or cfg.get('partial') != partial:
                    cfg['revision'] = cfg.get('revision', 0) + 1
                cfg.update(partial=partial, format_partial=format_partial, last_collected_at=now)
                # Both atomic files are under the lock; a crash rebuilds daily projection from SQLite.
                write_json(self.root / 'daily.json', rows)
                self.save(cfg)
            finally:
                db.close()
        return self.summary()

    def rows(self, db, cfg):
        events = list(db.execute('SELECT * FROM events ORDER BY at,key'))
        rows, sessions = {}, set()
        zone = local_zone(cfg['timezone'])
        for event in events:
            day = datetime.fromtimestamp(event['at'], zone).date().isoformat()
            def row(model):
                key = (day, model)
                if key not in rows:
                    rows[key] = dict(date=day, tool='claude_code', model=model, sessions=0, turns=0,
                                     **dict.fromkeys(COUNTERS), quality='observed')
                return rows[key]
            base = row(None)
            if event['session'] not in sessions:
                base['sessions'] += 1
                sessions.add(event['session'])
            if event['kind'] == 'user':
                base['turns'] += 1
            else:
                target = row(event['model'])
                for counter in COUNTERS:
                    value = event[counter]
                    if value is not None:
                        target[counter] = (target[counter] or 0) + value
                if event['quality'] == 'partial':
                    target['quality'] = 'partial'
        return [rows[k] for k in sorted(rows, key=lambda x: (x[0], x[1] or ''))]

    def _ledger_rows(self):
        path = self.root / 'daily.json'
        if not path.exists():
            return []
        safe(path, private=True)
        with path.open(encoding='utf-8') as stream:
            return json.load(stream)

    def payload(self):
        cfg = self.config()
        if not cfg.get('device_id'):
            return None
        return dict(schema_version=1, aggregation_version=VERSION, device_id=cfg['device_id'],
                    enrollment_id=cfg.get('enrollment_id'), consent_id=cfg.get('consent_id'),
                    timezone=cfg['timezone'], revision=cfg['revision'], daily=self._ledger_rows())

    def summary(self):
        cfg = self.config()
        rows = self._ledger_rows() if cfg.get('device_id') else []
        today = datetime.fromtimestamp(self.clock(), local_zone(cfg.get('timezone', 'UTC'))).date()
        state = 'off' if not cfg.get('enabled') else 'partial' if cfg.get('partial') or any(r['quality'] == 'partial' for r in rows) else 'on' if rows else 'on_no_data'
        return dict(state=state, enabled=cfg.get('enabled', False), timezone=cfg.get('timezone', 'UTC'),
                    linked=bool(cfg.get('consent_id')), sync_enabled=cfg.get('sync_enabled', False),
                    revoke_pending=cfg.get('revoke_pending', False), sync_state=cfg.get('sync_state', 'disabled'),
                    last_sync_at=cfg.get('last_sync_at'), source_available=bool(cfg.get('workspace') and self.source(cfg).is_dir()),
                    codex='준비 중', privacy=PRIVACY, daily=rows, today=today.isoformat(),
                    totals=metrics(rows, today), tools={tool: metrics([r for r in rows if r['tool'] == tool], today) for tool in ('claude_code', 'codex')},
                    preview=self.payload(), price_table=dict(source=PRICE_SOURCE, checked_at=PRICE_DATE, version='anthropic-20261115', label='추정', cache_write_assumption='TTL 미기록: 5분~1시간 가격 범위'))

    def delete_local(self):
        if not self.root.exists():
            return
        self.off()
        with self.locked(wait=True):
            cfg = self.config()
            db = self.connect()
            try:
                db.executescript('DELETE FROM events; DELETE FROM cursors; VACUUM;')
                db.commit()
            finally:
                db.close()
            cfg.update(windows=[], partial=False, revision=cfg.get('revision', 0) + 1)
            cfg.pop('workspace', None)
            write_json(self.root / 'daily.json', [])
            self.save(cfg)


def metrics(rows, today):
    days, months, models = {}, {}, {}
    counters = {key: None for key in COUNTERS}
    sessions = turns = 0
    for row in rows:
        value = row['sessions'] + row['turns']
        sessions += row['sessions']; turns += row['turns']
        tokens = sum(row[k] or 0 for k in COUNTERS)
        for key in COUNTERS:
            if row[key] is not None:
                counters[key] = (counters[key] or 0) + row[key]
        if value or tokens:
            days[row['date']] = days.get(row['date'], 0) + row['turns']
            months[row['date'][:7]] = months.get(row['date'][:7], 0) + row['turns']
        if row['model']:
            models[row['model']] = models.get(row['model'], 0) + tokens
    longest = run = 0; previous = None
    for value in sorted(days):
        day = date.fromisoformat(value)
        run = run + 1 if previous and day == previous + timedelta(days=1) else 1
        longest = max(longest, run); previous = day
    current = 0; cursor = today if today.isoformat() in days else today - timedelta(days=1)
    while cursor.isoformat() in days:
        current += 1; cursor -= timedelta(days=1)
    recent = [r for r in rows if (today - timedelta(days=29)).isoformat() <= r['date'] <= today.isoformat()]
    peak = lambda values: max(values, key=lambda k: (values[k], k)) if values else None
    return dict(sessions=sessions, turns=turns, active_days=len(days), current_streak=current, longest_streak=longest,
                peak_day=peak(days), peak_month=peak(months), most_used_model=peak(models), **counters,
                estimated_cost=estimated_cost(rows), recent_30_days=dict(turns=sum(r['turns'] for r in recent), sessions=sum(r['sessions'] for r in recent),
                                    active_days=len({r['date'] for r in recent if r['sessions'] or r['turns'] or any(r[k] for k in COUNTERS)})))


def estimated_cost(rows):
    low = high = 0.0
    known = False
    partial = False
    for row in rows:
        if not any(row[k] is not None for k in COUNTERS):
            continue
        price = PRICES.get(row['model'])
        if price is None or any(row[k] is None for k in COUNTERS):
            partial = True
            continue
        known = True
        base = row['input_tokens'] * price[0] + row['output_tokens'] * price[1] + row['cache_read_tokens'] * price[2]
        low += (base + row['cache_creation_tokens'] * price[0] * 1.25) / 1e6
        high += (base + row['cache_creation_tokens'] * price[0] * 2) / 1e6
    return dict(usd_min=round(low, 6) if known else None, usd_max=round(high, 6) if known else None, partial=partial)


def main(argv=None, *, home=None, user_home=None):
    parser = argparse.ArgumentParser(description='내 AI 사용 기록 · 기본 OFF · F8 계정 한도와 별개')
    parser.add_argument('--home', default=home or os.environ.get('ILSON_HOME', str(Path.home() / 'ilson')))
    parser.add_argument('action', choices=('on', 'off', 'status', 'export', 'link', 'unlink', 'sync', 'tick', 'delete-local'))
    parser.add_argument('--workspace')
    parser.add_argument('--timezone', default='Asia/Seoul')
    parser.add_argument('--backfill-from')
    parser.add_argument('--base-url')
    parser.add_argument('--consent', action='store_true')
    parser.add_argument('--codex', action='store_true')
    args = parser.parse_args(argv)
    ledger = Ledger(args.home, user_home=user_home)
    try:
        if args.codex:
            raise UsageError('Codex 사용 기록은 누적 카운터 검증 전으로 준비 중입니다.')
        if args.action == 'on':
            if not args.consent or not args.workspace:
                raise UsageError('개인정보 안내를 읽고 --consent --workspace 실습폴더로 직접 켜세요. ' + PRIVACY)
            ledger.on(args.workspace, args.timezone, backfill=args.backfill_from)
            result = ledger.collect()
        elif args.action == 'off':
            ledger.off(); result = ledger.summary()
        elif args.action in ('status', 'export'):
            result = ledger.summary() if args.action == 'status' else ledger.payload()
            if args.action == 'export' and result is not None:
                from usage_sync import validate_payload
                validate_payload(result, date.fromisoformat(ledger.summary()['today']), linked=False)
        elif args.action == 'delete-local':
            ledger.delete_local(); result = ledger.summary()
        elif args.action in ('link', 'unlink', 'sync'):
            from usage_sync import Client
            client = Client(ledger)
            if args.action == 'link':
                print(json.dumps(ledger.payload(), ensure_ascii=False, indent=2))
                if not args.consent:
                    raise UsageError('전송 JSON과 안내를 확인하고 --consent로 별도 공유에 동의하세요. ' + PRIVACY)
                if not sys.stdin.isatty():
                    raise UsageError('일회 연결 코드는 대화형 터미널에서 입력하세요.')
                import getpass
                result = client.link(args.base_url or '', getpass.getpass('강의 사이트의 일회 연결 코드: '))
            elif args.action == 'unlink':
                result = client.unlink()
            else:
                ledger.collect(); result = client.sync()
        else:
            if not ledger.config().get('enabled') and not ledger.config().get('revoke_pending'):
                return 0
            ledger.collect()
            from usage_sync import Client
            result = Client(ledger).sync()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except UsageError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, sqlite3.Error):
        print('사용 기록 요청을 완료하지 못했습니다. 입력·개인 권한·연결 상태를 확인하세요.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
