"""Execute registered approvals once, with a durable unknown-result state."""
from __future__ import annotations
from contextvars import ContextVar
from datetime import datetime
import fcntl
import os
from pathlib import Path
import approval_store as store

_ACTIVE_HOME = ContextVar('approval_home')


def note_path(req):
    home = _ACTIVE_HOME.get()
    if req.target['channel'] != 'local_note' or req.target['account'] != 'local':
        raise store.ApprovalStale('invalid target')
    name = req.target['object_id']
    if name in ('.', '..') or Path(name).name != name or not name.endswith('.md'):
        raise store.ApprovalStale('invalid target')
    pending = home / 'vault/reports/pending'
    for path in (home / 'vault', home / 'vault/reports', pending):
        if path.is_symlink():
            raise store.ApprovalStale('linked path')
    path = pending / name
    if path.is_symlink() or not path.is_file():
        raise store.ApprovalStale('draft unavailable')
    return path


def verify_note(req):
    path = note_path(req)
    content = path.read_text(encoding='utf-8')
    if store.digest(content) != req.body_sha256 or content != req.body:
        raise store.ApprovalStale('draft changed')
    dest = _ACTIVE_HOME.get() / 'vault/reports/approved'
    if dest.is_symlink() or (dest / path.name).exists() or (dest / path.name).is_symlink():
        raise store.ApprovalStale('destination unavailable')


def execute_note(req):
    path = note_path(req)
    home = _ACTIVE_HOME.get()
    dest = home / 'vault/reports/approved'
    dest.mkdir(parents=True, exist_ok=True)
    destination = dest / path.name
    os.link(path, destination, follow_symlinks=False)
    try:
        # Check the linked file again at the move boundary. Never remove a
        # draft when the bytes or file identity changed since verification.
        before = os.stat(path, follow_symlinks=False)
        linked = os.stat(destination, follow_symlinks=False)
        if path.is_symlink() or destination.is_symlink() or (before.st_dev, before.st_ino) != (linked.st_dev, linked.st_ino):
            raise store.ApprovalStale('draft changed')
        content = destination.read_text(encoding='utf-8')
        after = os.stat(path, follow_symlinks=False)
        if store.digest(content) != req.body_sha256 or (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise store.ApprovalStale('draft changed')
    except store.ApprovalStale:
        os.unlink(destination)
        raise
    os.unlink(path)
    journal = home / 'vault/journal'
    if journal.is_symlink():
        raise OSError('journal unavailable')
    journal.mkdir(parents=True, exist_ok=True)
    log = journal / (datetime.now().strftime('%Y-%m-%d') + '.md')
    fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'a', encoding='utf-8') as output:
        output.write('\n- 승인한 초안을 보관했습니다. 승인 번호: ' + req.id + '\n')
    return store.ActionResult()


def register():
    store.register_action('local_note', verify_note, execute_note)


def execution_lock(home):
    with store.connect(home):
        pass
    fd = os.open(store.home_path(home) / '.approval/execute.lock', os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def dispatch(request_id, home=None, *, license_check=None):
    home = store.home_path(home)
    fd = execution_lock(home)
    try:
        return _dispatch(request_id, home, license_check=license_check)
    finally:
        os.close(fd)


def _dispatch(request_id, home, *, license_check=None):
    from approval_actions import load_all
    load_all()
    if license_check is None:
        from license import evaluate
        license_check = lambda: evaluate(home)[0]
    try:
        if not license_check():
            return 'license_required'
    except Exception:
        return 'license_required'
    with store.connect(home) as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM requests WHERE id=?', (request_id,)).fetchone()
        if not row or row['state'] != 'approved' or row['execution'] != 'received':
            db.rollback()
            return 'not_ready'
        db.execute("UPDATE requests SET state='executing',execution='running' WHERE id=? AND state='approved'", (request_id,))
        store.event(db, row, row['actor'], 'executing')
        db.commit()
    req_data = store.as_dict(row)
    req_data['state'] = 'executing'
    req = store.approval_request(req_data)
    token = _ACTIVE_HOME.set(home)
    try:
        action = store._ACTIONS.get(req.action_type)
        if not action or store.digest(req.body) != req.body_sha256:
            raise store.ApprovalStale('content or action changed')
        action[0](req)
        try:
            allowed = license_check()
        except Exception:
            allowed = False
        if not allowed:
            raise store.ActionFailed('license required')
        result = action[1](req)
        if not isinstance(result, store.ActionResult) or result.status != 'success':
            raise store.ActionUnknown('invalid action result')
        final, error = 'success', None
    except store.ApprovalStale:
        final, error = 'changed', 'stale'
    except store.ActionFailed:
        final, error = 'failed', 'failed'
    except Exception:
        final, error = 'result_unknown', 'unknown'
    finally:
        _ACTIVE_HOME.reset(token)
    finish(request_id, final, error, home)
    return final


def finish(request_id, state, error, home):
    with store.connect(home) as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM requests WHERE id=?', (request_id,)).fetchone()
        if row and row['state'] == 'executing':
            db.execute('UPDATE requests SET state=?,execution=?,error=? WHERE id=?', (state, state, error, request_id))
            store.event(db, row, row['actor'], state, error)
        db.commit()


def recover(home=None):
    fd = execution_lock(home)
    try:
        with store.connect(home) as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute("SELECT * FROM requests WHERE state='executing'").fetchall()
            for row in rows:
                db.execute("UPDATE requests SET state='result_unknown',execution='result_unknown',error='interrupted' WHERE id=?", (row['id'],))
                store.event(db, row, row['actor'], 'result_unknown', 'interrupted')
            db.commit()
    finally:
        os.close(fd)
