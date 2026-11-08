"""Fail-closed, bounded product-question pagination and private deduplication."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat


def fingerprint(item):
    keys = ('questionId', 'createDate', 'question', 'productId', 'productName', 'answered', 'answer', 'answers')
    data = {key: item.get(key) for key in keys}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def validate_interval(start, end):
    def parse(s):
        if not isinstance(s, str):
            raise ValueError('조회 기간을 확인하세요.')
        result = datetime.fromisoformat(s.replace('Z', '+00:00'))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError('조회 기간에는 시간대가 필요합니다.')
        return result
    if parse(start) >= parse(end):
        raise ValueError('조회 시작과 종료를 확인하세요.')


def collect_once(client, start, end):
    validate_interval(start, end)
    rows = {}
    total = pages = None
    page = 1
    while True:
        result = client.page(start, end, page)
        if not isinstance(result, dict) or not isinstance(result.get('contents'), list):
            raise ValueError('문의 목록 형식 확인 필요')
        p, n = result.get('totalPages'), result.get('totalElements')
        if type(p) is not int or type(n) is not int or p < 0 or n < 0 or p > 10000 or (p == 0) != (n == 0) or n > p * 100:
            raise ValueError('문의 페이지 수 확인 필요')
        if pages is None:
            pages, total = p, n
        if (pages, total) != (p, n) or len(result['contents']) > 100:
            raise ValueError('목록이 바뀌었습니다. 다시 확인하세요.')
        for row in result['contents']:
            if not isinstance(row, dict) or type(row.get('questionId')) is not int or row['questionId'] <= 0 or type(row.get('answered')) is not bool or not isinstance(row.get('question'), str) or not isinstance(row.get('createDate'), str):
                raise ValueError('문의 내용 확인 필요')
            qid = row['questionId']
            if qid in rows:
                # Overlapping pages can conceal other entries. Never save a partial scan.
                raise ValueError('중복 페이지가 발견되어 수집을 중단했습니다.')
            rows[qid] = row
        if page >= max(1, pages):
            break
        page += 1
    if len(rows) != total:
        raise ValueError('문의 개수가 일치하지 않아 수집을 중단했습니다.')
    return rows


def collect(client, start, end):
    # Two full scans detect many, though not all, paging races. No answered filter:
    # the same snapshot is needed to verify an answer before dispatch.
    first = collect_once(client, start, end)
    second = collect_once(client, start, end)
    if {k: fingerprint(v) for k, v in first.items()} != {k: fingerprint(v) for k, v in second.items()}:
        raise ValueError('조회 중 문의가 바뀌어 수집을 중단했습니다.')
    return second


def private_dir(home):
    root = Path(home) / '.credentials'
    root.mkdir(mode=0o700, exist_ok=True)
    st = root.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
        raise ValueError('비공개 저장 폴더 권한을 확인하세요.')
    folder = root / 'replies'
    folder.mkdir(mode=0o700, exist_ok=True)
    st = folder.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
        raise ValueError('비공개 저장 폴더 권한을 확인하세요.')
    return folder


def save(home, channel, account, rows, start, end):
    validate_interval(start, end)
    if channel != 'naver_commerce' or not isinstance(account, str) or not account or len(account) > 128:
        raise ValueError('연결 계정을 확인하세요.')
    db = private_dir(home) / 'questions.sqlite3'
    flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(db, flags, 0o600)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o600 or st.st_nlink != 1:
            raise ValueError('문의 저장 파일 권한을 확인하세요.')
    finally:
        os.close(fd)
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS questions (channel TEXT NOT NULL, account TEXT NOT NULL, question_id INTEGER NOT NULL, data TEXT NOT NULL, fingerprint TEXT NOT NULL, PRIMARY KEY(channel, account, question_id))')
        for qid, row in rows.items():
            conn.execute('INSERT INTO questions VALUES (?, ?, ?, ?, ?) ON CONFLICT(channel, account, question_id) DO UPDATE SET data=excluded.data, fingerprint=excluded.fingerprint WHERE questions.fingerprint != excluded.fingerprint',
                         (channel, account, qid, json.dumps({'question': row, 'start': start, 'end': end}, ensure_ascii=False), fingerprint(row)))
    return len(rows)


def get(home, account, question_id):
    db = private_dir(home) / 'questions.sqlite3'
    if not db.is_file() or db.is_symlink():
        raise ValueError('저장된 문의를 확인하세요.')
    st = db.stat()
    if st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o600 or st.st_nlink != 1:
        raise ValueError('문의 저장 파일 권한을 확인하세요.')
    with sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True) as conn:
        row = conn.execute('SELECT data, fingerprint FROM questions WHERE channel=? AND account=? AND question_id=?', ('naver_commerce', account, question_id)).fetchone()
    if not row:
        raise ValueError('저장된 문의를 찾을 수 없습니다.')
    record = json.loads(row[0])
    if fingerprint(record['question']) != row[1]:
        raise ValueError('저장된 문의가 바뀌었습니다.')
    return record, row[1]
