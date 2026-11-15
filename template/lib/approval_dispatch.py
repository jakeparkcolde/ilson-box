"""Execute registered approvals once, with a durable unknown-result state."""
from __future__ import annotations
from contextvars import ContextVar
from datetime import datetime
import ilson_platform as platform
from ilson_platform import vault_root
import os
import errno
from pathlib import Path
import approval_store as store

_ACTIVE_HOME = ContextVar('approval_home')
_ACTIVE_VAULT = ContextVar('approval_vault', default=None)


def active_vault(home):
    return vault_root(home, _ACTIVE_VAULT.get())


def note_path(req):
    home = _ACTIVE_HOME.get()
    if req.target['channel'] != 'local_note' or req.target['account'] != 'local':
        raise store.ApprovalStale('invalid target')
    name = req.target['object_id']
    if name in ('.', '..') or Path(name).name != name or not name.endswith('.md'):
        raise store.ApprovalStale('invalid target')
    from access_policy import require_owner
    policy = require_owner(home)
    if policy:
        policy.read('management/reports/pending/' + name, 256000)
        return policy.vault / 'management/reports/pending' / name
    vault = active_vault(home)
    pending = vault / 'reports/pending'
    for path in (vault, vault / 'reports', pending):
        if path.is_symlink():
            raise store.ApprovalStale('linked path')
    path = pending / name
    if platform.IS_WINDOWS:
        platform.safe_path(path)
        if path.lstat().st_nlink != 1: raise store.ApprovalStale('shared draft')
    if path.is_symlink() or not path.is_file():
        raise store.ApprovalStale('draft unavailable')
    return path


def verify_note(req):
    path = note_path(req)
    from access_policy import require_owner
    policy = require_owner(_ACTIVE_HOME.get())
    content = policy.read('management/reports/pending/' + path.name, 256000)[0].decode('utf-8') if policy else (platform.WindowsFiles(path.parent).text(path.name, 256000)[0] if platform.IS_WINDOWS else path.read_text(encoding='utf-8'))
    if store.digest(content) != req.body_sha256 or content != req.body:
        raise store.ApprovalStale('draft changed')
    dest = (policy.vault / 'management/reports/approved') if policy else active_vault(_ACTIVE_HOME.get()) / 'reports/approved'
    if dest.is_symlink() or (dest / path.name).exists() or (dest / path.name).is_symlink():
        raise store.ApprovalStale('destination unavailable')


def execute_note(req):
    path = note_path(req)
    home = _ACTIVE_HOME.get()
    from access_policy import require_owner
    policy = require_owner(home)
    if policy:
        raw, _ = policy.read('management/reports/pending/' + path.name, 256000)
        if store.digest(raw.decode('utf-8')) != req.body_sha256:
            raise store.ApprovalStale('draft changed')
        policy.create('management/reports/approved/' + path.name, raw)
        policy.create('management/journal/approval-' + req.id + '.md', ('승인 번호: ' + req.id + '\n').encode())
        return store.ActionResult()
    dest = active_vault(home) / 'reports/approved'
    dest.mkdir(parents=True, exist_ok=True)
    destination = dest / path.name
    copied = False
    if platform.IS_WINDOWS:
        platform.safe_path(destination)
        try:
            os.link(path, destination)
        except OSError as error:
            if error.errno not in (errno.EPERM, errno.EACCES, errno.EXDEV, errno.ENOTSUP, errno.EINVAL): raise
            try: platform.copy_verified(path, destination, req.body_sha256)
            except ValueError: raise store.ApprovalStale('draft changed') from None
            copied = True
    else:
        os.link(path, destination, follow_symlinks=False)
    if not copied:
        _finish_link(path, destination, req)
    journal = active_vault(home) / 'journal'
    if journal.is_symlink():
        raise OSError('journal unavailable')
    if platform.IS_WINDOWS: platform.safe_path(journal)
    journal.mkdir(parents=True, exist_ok=True)
    log = journal / (datetime.now().strftime('%Y-%m-%d') + '.md')
    if platform.IS_WINDOWS: platform.safe_path(log)
    fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'a', encoding='utf-8') as output:
        output.write('\n- 승인한 초안을 보관했습니다. 승인 번호: ' + req.id + '\n')
    return store.ActionResult()


def _finish_link(path, destination, req):
    try:
        # Check the linked file again at the move boundary. Never remove a
        # draft when the bytes or file identity changed since verification.
        before = os.stat(path, follow_symlinks=False)
        linked = os.stat(destination, follow_symlinks=False)
        if path.is_symlink() or destination.is_symlink() or (before.st_dev, before.st_ino) != (linked.st_dev, linked.st_ino):
            raise store.ApprovalStale('draft changed')
        if platform.IS_WINDOWS:
            with destination.open('rb') as stream: content = stream.read(256001).decode('utf-8')
        else:
            content = destination.read_text(encoding='utf-8')
        after = os.stat(path, follow_symlinks=False)
        if store.digest(content) != req.body_sha256 or (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise store.ApprovalStale('draft changed')
    except store.ApprovalStale:
        os.unlink(destination)
        raise
    os.unlink(path)


def register():
    store.register_action('local_note', verify_note, execute_note)


def execution_lock(home):
    with store.connect(home):
        pass
    path = store.home_path(home) / '.approval/execute.lock'
    if platform.IS_WINDOWS: platform.safe_path(path)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        platform.lock(fd)
        return fd
    except Exception:
        os.close(fd)
        raise


def dispatch(request_id, home=None, *, license_check=None, vault=None, profile="box"):
    home = store.home_path(home)
    fd = execution_lock(home)
    vault_token = _ACTIVE_VAULT.set(vault)
    try:
        return _dispatch(request_id, home, license_check=license_check, profile=profile)
    finally:
        _ACTIVE_VAULT.reset(vault_token)
        os.close(fd)


def _dispatch(request_id, home, *, license_check=None, profile="box"):
    from approval_actions import load_all
    load_all(profile=profile)
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
        if not row or (profile == 'course' and row['action_type'] != 'local_note') or row['state'] != 'approved' or row['execution'] != 'received':
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
