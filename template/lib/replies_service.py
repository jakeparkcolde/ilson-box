"""Local admin entry points. No scheduler or outbound answer route lives here."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat
from replies_draft import draft
from replies_ingest import collect, private_dir, save
from replies_naver_qna import NaverQna


def path_for(home, account):
    if not isinstance(account, str) or not account.strip() or len(account) > 128:
        raise ValueError('계정 별칭을 확인하세요.')
    return private_dir(home) / ('naver-' + hashlib.sha256(account.encode()).hexdigest() + '.json')


def save_connection(home, data):
    if not isinstance(data, dict) or set(data) != {'account', 'client_id', 'client_secret', 'type', 'account_id'}:
        raise ValueError('연결 입력을 확인하세요.')
    if any(not isinstance(data[k], str) or len(data[k]) > 512 for k in data):
        raise ValueError('연결 입력을 확인하세요.')
    if not data['client_id'].strip() or not data['client_secret'].strip() or data['type'] not in ('SELF','SELLER') or (data['type'] == 'SELLER' and not data['account_id'].strip()):
        raise ValueError('연결 입력을 확인하세요.')
    path = path_for(home, data['account'])
    # Create the temporary file with restrictive permissions from its first byte.
    temporary = path.with_name('.new-' + secrets.token_hex(16))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump({k:data[k] for k in ('client_id','client_secret','type','account_id')}, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        # Do not expose input or raw exceptions in a response or log.
        try: temporary.unlink()
        except OSError: pass
        raise
    return {'ok':True, 'message':'연결 정보를 이 기기의 비공개 파일에 저장했습니다. 실제 연결 여부는 아직 확인하지 않았습니다.'}


def client_for(home, account):
    return NaverQna(path_for(home, account), home=home)


def fetch_questions(home, data):
    if not isinstance(data, dict) or set(data) != {'account','start','end','consent'} or data['consent'] is not True:
        raise ValueError('수집 동의와 조회 기간을 확인하세요.')
    client = client_for(home, data['account'])
    rows = collect(client, data['start'], data['end'])
    count = save(home, 'naver_commerce', data['account'], rows, data['start'], data['end'])
    return {'count':count, 'questions':[{'id':str(q['questionId']), 'question':q['question'], 'answered':q['answered']} for q in rows.values()]}


def manual_draft(home, data):
    if not isinstance(data, dict) or set(data) != {'text','consent'}:
        raise ValueError('입력을 확인하세요.')
    return draft(data['text'], consent=data['consent'], home=home)


def install_connection_runtime(home, data):
    if not isinstance(data, dict) or set(data) != {'consent'}:
        raise ValueError('설치 동의를 확인하세요.')
    from replies_runtime import install
    return install(home, consent=data['consent'])


def request_answer(home, data):
    if not isinstance(data, dict) or set(data) != {'account','question_id','body'}:
        raise ValueError('답변 대상을 확인하세요.')
    qid = data['question_id']
    if not isinstance(qid, str) or not qid.isascii() or not qid.isdigit() or qid.startswith('0') or len(qid) > 18:
        raise ValueError('문의 번호를 확인하세요.')
    import approval_store
    from replies_dispatch import Adapter
    adapter = Adapter(home, approval_store, lambda account:client_for(home, account), approval_store)
    request_id = adapter.request(data['account'], int(qid), data['body'])
    return {'ok':True, 'message':'승인 요청을 만들었습니다. 승인함에서 내용과 대상을 확인하세요.', 'request_id':request_id}


def write_private_json(home, name, data):
    if name not in ('schedule.json', 'cursor.json'):
        raise ValueError('설정 파일을 확인하세요.')
    path = private_dir(home) / name
    temporary = path.with_name('.new-' + secrets.token_hex(16))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try: temporary.unlink()
        except OSError: pass
        raise


def schedule(home, data):
    if not isinstance(data, dict) or set(data) != {'enabled','account','start','collection_consent','model_consent'} or type(data['enabled']) is not bool:
        raise ValueError('예약 설정을 확인하세요.')
    if not data['enabled']:
        write_private_json(home, 'schedule.json', {'enabled':False})
        return {'ok':True, 'message':'예약 수집을 껐습니다. 이미 등록한 예약을 내리려면 터미널에서 ilson pause reply-drafts를 실행하세요.'}
    if data['collection_consent'] is not True or data['model_consent'] is not True:
        raise ValueError('수집과 Claude 전송에 동의해야 합니다.')
    from replies_ingest import validate_interval
    from datetime import datetime, timezone
    validate_interval(data['start'], datetime.now(timezone.utc).isoformat())
    # Validate the selected private connection now; do not test or use it here.
    from replies_naver_qna import load_credentials
    load_credentials(path_for(home, data['account']))
    jobs = Path(home) / 'launchd/jobs.conf'
    flags = os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(jobs, flags)
    import fcntl
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_nlink != 1 or st.st_size > 100000:
            raise ValueError('예약 목록을 확인하세요.')
        content = os.read(fd, 100001).decode('utf-8')
        matches = [line for line in content.splitlines() if line.split('|', 1)[0].strip() == 'reply-drafts']
        entry = 'reply-drafts | run-job.sh | reply-drafts | daily 09:00'
        if matches and (len(matches) != 1 or matches[0] != entry):
            raise ValueError('기존 예약 업무 이름이 겹칩니다.')
        if not matches:
            os.lseek(fd, 0, os.SEEK_END)
            os.write(fd, (('' if not content or content.endswith('\n') else '\n') + entry + '\n').encode())
            os.fsync(fd)
        settings = {'enabled':True,'account':data['account'],'model_consent':True,
                    'start':data['start'],'id':secrets.token_hex(16)}
        write_private_json(home, 'schedule.json', settings)
    finally:
        os.close(fd)
    command = 'ilson resume reply-drafts' if (Path(home) / 'state/paused.reply-drafts').exists() else 'ilson start'
    return {'ok':True, 'message':'예약을 준비했습니다. 터미널에서 ' + command + '를 실행해 등록하세요. 수집 후 초안까지만 만듭니다.'}


def list_drafts(home, data):
    if not isinstance(data, dict) or set(data) != {'account'} or not isinstance(data['account'], str) or not data['account']:
        raise ValueError('계정 별칭을 확인하세요.')
    db = private_dir(home) / 'questions.sqlite3'
    if not db.exists(): return {'drafts':[]}
    if db.is_symlink(): raise ValueError('저장 파일을 확인하세요.')
    st = db.stat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o600 or st.st_nlink != 1:
        raise ValueError('저장 파일을 확인하세요.')
    with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True) as conn:
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='drafts'").fetchone()
        if not exists: return {'drafts':[]}
        rows = conn.execute('SELECT d.question_id, d.status, d.body, q.data FROM drafts d JOIN questions q ON q.channel=? AND q.account=d.account AND q.question_id=d.question_id WHERE d.account=? ORDER BY d.question_id DESC LIMIT 100', ('naver_commerce',data['account'])).fetchall()
    drafts=[]
    for qid, status, body, raw in rows:
        record=json.loads(raw)
        question=record['question']
        if question.get('answered') is True: continue
        drafts.append({'id':str(qid), 'question':question['question'], 'status':status, 'body':body})
    return {'drafts':drafts}


def disconnect(home, data):
    if not isinstance(data, dict) or set(data) != {'account'}:
        raise ValueError('계정을 확인하세요.')
    path = path_for(home, data['account'])
    write_private_json(home, 'schedule.json', {'enabled':False})
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file(): raise ValueError('인증 파일을 확인하세요.')
        path.unlink()
    return {'ok':True, 'message':'연결 정보와 예약 수집을 껐습니다. 저장된 문의·초안은 이 기기에 남아 있습니다.'}
