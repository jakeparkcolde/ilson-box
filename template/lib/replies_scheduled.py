"""Opt-in scheduled collection: drafts only, never request approval or publish."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
from replies_draft import draft
from replies_ingest import collect, fingerprint, private_dir, save
from replies_service import client_for


def config(home):
    path = private_dir(home) / 'schedule.json'
    if not path.exists(): return None
    from replies_naver_qna import secure_json_file
    data = secure_json_file(path)
    if not isinstance(data, dict): raise ValueError('예약 설정을 확인하세요.')
    if data == {'enabled':False}: return None
    if set(data) != {'enabled','account','model_consent','start','id'}: raise ValueError('예약 설정을 확인하세요.')
    if data['enabled'] is not True: return None
    if data['model_consent'] is not True or not isinstance(data['account'], str) or not data['account']:
        raise ValueError('예약 동의를 확인하세요.')
    return data


def run(home, now=None):
    import fcntl
    from replies_naver_qna import secure_json_file
    from replies_service import write_private_json
    lock_path = private_dir(home) / 'schedule.lock'
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return 2
        settings = config(home)
        if not settings: return 2
        now = now or datetime.now(timezone.utc)
        cursor_path = private_dir(home) / 'cursor.json'
        cursor = secure_json_file(cursor_path) if cursor_path.exists() else {}
        initial = datetime.fromisoformat(settings['start'].replace('Z','+00:00'))
        since = cursor.get('through') if cursor.get('id') == settings['id'] else settings['start']
        start = datetime.fromisoformat(since.replace('Z','+00:00'))
        if initial.tzinfo is None or start.tzinfo is None or start > now: raise ValueError('예약 시작 시각 확인 필요')
        # Revisit the previous day to catch ordinary indexing delays; the
        # unique question key and fingerprint prevent duplicate drafts.
        if cursor.get('id') == settings['id']:
            start = max(initial, start - timedelta(days=1))
        client = client_for(home, settings['account'])
        while start < now:
            end = min(start + timedelta(days=7), now)
            start_text, end_text = start.isoformat(timespec='seconds'), end.isoformat(timespec='seconds')
            rows = collect(client, start_text, end_text)
            if config(home) != settings: return 2
            save(home, 'naver_commerce', settings['account'], rows, start_text, end_text)
            db = private_dir(home) / 'questions.sqlite3'
            with sqlite3.connect(db) as conn:
                conn.execute('CREATE TABLE IF NOT EXISTS drafts (account TEXT NOT NULL, question_id INTEGER NOT NULL, fingerprint TEXT NOT NULL, status TEXT NOT NULL, body TEXT, PRIMARY KEY(account, question_id))')
                for qid, row in rows.items():
                    if config(home) != settings: return 2
                    if row['answered'] or row.get('answer') or row.get('answers'): continue
                    digest = fingerprint(row)
                    existing = conn.execute('SELECT fingerprint FROM drafts WHERE account=? AND question_id=?', (settings['account'], qid)).fetchone()
                    if existing and existing[0] == digest: continue
                    result = draft(row['question'], consent=True, home=home)
                    if config(home) != settings: return 2
                    conn.execute('INSERT INTO drafts VALUES (?, ?, ?, ?, ?) ON CONFLICT(account, question_id) DO UPDATE SET fingerprint=excluded.fingerprint, status=excluded.status, body=excluded.body',
                                 (settings['account'], qid, digest, result['status'], result.get('text')))
                    conn.commit()
            if config(home) != settings: return 2
            write_private_json(home, 'cursor.json', {'id':settings['id'], 'through':end_text})
            start = end
        return 0
    finally:
        os.close(fd)

if __name__ == '__main__':
    try:
        if len(sys.argv) != 2: raise ValueError()
        from runtime_gate import running
        with running(Path(sys.argv[1])):
            code = run(Path(sys.argv[1]))
        sys.exit(code)
    except Exception:
        # Never send customer text, credentials, or upstream diagnostics to logs.
        print('예약 문의 수집 또는 초안 준비 실패. 관리자에서 확인하세요.', file=sys.stderr)
        sys.exit(1)
