"""Local, durable approval decisions. Contents stay outside vault snapshots."""
from __future__ import annotations
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat
import time

_ACTIONS = {}


class FrozenDict(dict):
    def _immutable(self, *_args, **_kwargs):
        raise TypeError('approval request is read-only')
    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _immutable
    __ior__ = _immutable


def freeze(value):
    if isinstance(value, dict):
        return FrozenDict({key: freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class ApprovalRequest:
    id: str
    action_type: str
    target: dict
    title: str
    body: str
    body_sha256: str
    meta: dict
    version: int
    state: str
    created_at: str
    expires_at: str


@dataclass(frozen=True)
class ActionResult:
    status: str = 'success'
    external_ref: str | None = None
    detail: str = ''


class ApprovalStale(Exception):
    pass


class ActionFailed(Exception):
    pass


class ActionUnknown(Exception):
    pass


def approval_request(row):
    data = as_dict(row) if isinstance(row, sqlite3.Row) else row
    iso = lambda n: datetime.fromtimestamp(n, timezone.utc).isoformat()
    return ApprovalRequest(id=data['id'], action_type=data['action_type'], target=freeze(data['target']),
                           title=data['title'], body=data['body'], body_sha256=data['body_hash'],
                           meta=freeze(data['meta']), version=data['version'], state=data['state'],
                           created_at=iso(data['created']), expires_at=iso(data['expires']))


def register_action(action_type, verify, execute, local_context=None):
    if not isinstance(action_type, str) or not action_type or not callable(verify) or not callable(execute) or (local_context is not None and not callable(local_context)):
        raise ValueError('invalid action')
    if action_type in _ACTIONS and _ACTIONS[action_type] != (verify, execute, local_context):
        raise ValueError('action already registered')
    _ACTIONS[action_type] = (verify, execute, local_context)


def home_path(home=None):
    return Path(home or os.environ.get('ILSON_HOME', Path.home() / 'ilson'))


def connect(home=None):
    root = home_path(home) / '.approval'
    if root.is_symlink():
        raise ValueError('invalid approval directory')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = root.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('approval directory permissions')
    path = root / 'approvals.sqlite3'
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('approval database permissions')
    finally:
        os.close(fd)
    db = sqlite3.connect(path, timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA busy_timeout=30000')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS requests (
      id TEXT PRIMARY KEY, action_type TEXT NOT NULL, target TEXT NOT NULL,
      title TEXT NOT NULL, body TEXT NOT NULL, body_hash TEXT NOT NULL,
      meta TEXT NOT NULL, version INTEGER NOT NULL, created REAL NOT NULL,
      expires REAL NOT NULL, state TEXT NOT NULL, execution TEXT NOT NULL,
      actor TEXT, error TEXT
    );
    CREATE TABLE IF NOT EXISTS callbacks (
      token_hash TEXT PRIMARY KEY, request_id TEXT NOT NULL, decision TEXT NOT NULL,
      chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
      generation TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS events (
      id INTEGER PRIMARY KEY, request_id TEXT NOT NULL, time REAL NOT NULL,
      actor TEXT, action_type TEXT NOT NULL, target TEXT NOT NULL,
      body_hash TEXT NOT NULL, event TEXT NOT NULL, error TEXT
    );
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    ''')
    return db


def digest(body):
    return hashlib.sha256(body.encode('utf-8')).hexdigest()


def event(db, req, actor, name, error=None):
    db.execute('INSERT INTO events(request_id,time,actor,action_type,target,body_hash,event,error) VALUES(?,?,?,?,?,?,?,?)',
               (req['id'], time.time(), actor, req['action_type'], req['target'], req['body_hash'], name, error))


def request_approval(action_type, target, title, body, meta=None, ttl_hours=24, *, home=None):
    if action_type not in _ACTIONS:
        raise ValueError('unregistered action')
    if not isinstance(target, dict) or set(target) != {'channel', 'account', 'object_id'} or not all(isinstance(x, str) and x for x in target.values()):
        raise ValueError('invalid approval target')
    if not all(isinstance(x, str) and x for x in (title, body)) or not isinstance(meta if meta is not None else {}, dict):
        raise ValueError('invalid approval request')
    if not 0 < ttl_hours <= 168 or len(body.encode('utf-8')) > 256000 or len(json.dumps(target)) > 1024 or len(title) > 1000:
        raise ValueError('invalid approval request')
    encoded = json.dumps(meta or {}, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    target = json.dumps(target, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    request_id = secrets.token_hex(16)
    now = time.time()
    with connect(home) as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (request_id, action_type, target, title, body, digest(body), encoded,
                    1, now, now + ttl_hours * 3600, 'pending', 'received', None, None))
        req = db.execute('SELECT * FROM requests WHERE id=?', (request_id,)).fetchone()
        event(db, req, None, 'requested')
        db.commit()
    return request_id


def as_dict(row):
    if row is None:
        return None
    req = dict(row)
    req['meta'] = json.loads(req['meta'])
    req['target'] = json.loads(req['target'])
    return req


def expire_pending(home=None):
    with connect(home) as db:
        db.execute('BEGIN IMMEDIATE')
        for req in db.execute("SELECT * FROM requests WHERE state='pending' AND expires<=?", (time.time(),)).fetchall():
            db.execute("UPDATE requests SET state='expired' WHERE id=?", (req['id'],))
            event(db, req, None, 'expired')
        db.commit()


def get(request_id, home=None):
    expire_pending(home)
    with connect(home) as db:
        return as_dict(db.execute('SELECT * FROM requests WHERE id=?', (request_id,)).fetchone())


def list_requests(home=None):
    expire_pending(home)
    with connect(home) as db:
        return [as_dict(row) for row in db.execute('SELECT * FROM requests ORDER BY created DESC LIMIT 200')]


def decide(request_id, decision, actor, *, home=None):
    if decision not in ('approved', 'changed', 'rejected'):
        raise ValueError('invalid decision')
    with connect(home) as db:
        db.execute('BEGIN IMMEDIATE')
        req = db.execute('SELECT * FROM requests WHERE id=?', (request_id,)).fetchone()
        if req is None or not (req['state'] == 'pending' or (decision == 'rejected' and req['state'] == 'approved' and req['execution'] == 'received')):
            db.rollback()
            return False
        if req['state'] == 'pending' and req['expires'] <= time.time():
            db.execute("UPDATE requests SET state='expired' WHERE id=? AND state='pending'", (request_id,))
            event(db, req, actor, 'expired')
            db.commit()
            return False
        db.execute('UPDATE requests SET state=?, actor=? WHERE id=?', (decision, actor, request_id))
        event(db, req, actor, decision)
        db.commit()
        return True


def bind_callbacks(request_id, token_map, chat_id, user_id, message_id, generation, *, home=None):
    with connect(home) as db:
        db.execute('BEGIN IMMEDIATE')
        req = db.execute('SELECT * FROM requests WHERE id=?', (request_id,)).fetchone()
        if not req or req['state'] != 'pending' or req['expires'] <= time.time():
            raise ValueError('request no longer pending')
        for decision, token in token_map.items():
            if decision not in ('approved', 'changed', 'rejected'):
                raise ValueError('invalid decision')
            db.execute('INSERT INTO callbacks VALUES(?,?,?,?,?,?,?,0)',
                       (digest(token), request_id, decision, chat_id, user_id, message_id, generation))
        db.commit()


def callback(token, chat_id, user_id, message_id, generation, *, home=None):
    if not isinstance(token, str) or len(token) > 64:
        return None
    with connect(home) as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM callbacks WHERE token_hash=?', (digest(token),)).fetchone()
        if not row or row['used'] or (row['chat_id'], row['user_id'], row['message_id'], row['generation']) != (chat_id, user_id, message_id, generation):
            db.rollback()
            return None
        req = db.execute('SELECT * FROM requests WHERE id=?', (row['request_id'],)).fetchone()
        if not req or req['state'] != 'pending':
            db.rollback()
            return None
        if req['expires'] <= time.time():
            db.execute("UPDATE requests SET state='expired' WHERE id=?", (req['id'],))
            event(db, req, str(user_id), 'expired')
            db.commit()
            return None
        db.execute('UPDATE callbacks SET used=1 WHERE request_id=?', (req['id'],))
        db.execute('UPDATE requests SET state=?,actor=? WHERE id=?', (row['decision'], str(user_id), req['id']))
        event(db, req, str(user_id), row['decision'])
        db.commit()
        return req['id'], row['decision']


def setting(key, value=None, *, home=None):
    with connect(home) as db:
        if value is None:
            row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
            return row[0] if row else None
        db.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, str(value)))
        return value


_REPORT_STATES = ('pending', 'approved', 'changed', 'rejected', 'expired', 'executing', 'success', 'failed', 'result_unknown')


def report_connection(home=None):
    path = home_path(home) / '.approval/approvals.sqlite3'
    if not path.exists():
        return None
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('invalid approval database')
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    return db


def weekly_counts(since, until, *, home=None):
    db = report_connection(home)
    if db is None:
        return {}
    try:
        begin, end = since.timestamp(), until.timestamp()
        if end <= begin:
            raise ValueError('invalid period')
        result = {state: 0 for state in _REPORT_STATES}
        rows = db.execute('SELECT event,COUNT(DISTINCT request_id) AS n FROM events WHERE time>=? AND time<? GROUP BY event', (begin, end))
        for row in rows:
            if row['event'] in result and row['event'] != 'pending':
                result[row['event']] = row['n']
        result['pending'] = db.execute('''SELECT COUNT(*) FROM requests r WHERE r.created<? AND r.expires>?
            AND NOT EXISTS (SELECT 1 FROM events e WHERE e.request_id=r.id AND e.time<? AND e.event IN
            ('approved','changed','rejected','expired','executing','success','failed','result_unknown'))''', (end, end, end)).fetchone()[0]
        return result
    finally:
        db.close()


def list_titles(states, since, until, limit=20, *, home=None):
    db = report_connection(home)
    if db is None:
        return []
    try:
        states = set(states)
        if not states <= set(_REPORT_STATES) or not isinstance(limit, int) or not 0 <= limit <= 200:
            raise ValueError('invalid report filter')
        begin, end = since.timestamp(), until.timestamp()
        if end <= begin:
            raise ValueError('invalid period')
        rows = db.execute('''SELECT r.id,r.action_type,r.title,e.event,e.time,r.expires FROM requests r
            JOIN events e ON e.id=(SELECT id FROM events e2 WHERE e2.request_id=r.id AND e2.time<? ORDER BY e2.time DESC,e2.id DESC LIMIT 1)
            WHERE e.time>=? ORDER BY e.time DESC,e.id DESC''', (end, begin))
        output = []
        for row in rows:
            state = 'pending' if row['event'] == 'requested' else row['event']
            if state == 'pending' and row['expires'] <= end:
                continue
            if state in states and len(output) < limit:
                output.append({'id': row['id'], 'action_type': row['action_type'], 'title': row['title'],
                               'state': state, 'updated_at': datetime.fromtimestamp(row['time'], timezone.utc).isoformat()})
        return output
    finally:
        db.close()
