"""초안 확인 후 별도 승인으로 새 노트만 저장한다."""
import json
import os
import re
from inbox_files import InboxError, inspect, safe_dir, atomic_create

def read_draft(home, digest):
    if not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest):
        raise InboxError('초안을 확인하세요.')
    with safe_dir(home, 'state', 'inbox-drafts') as dfd:
        fd = os.open(digest+'.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
        try:
            with os.fdopen(fd, 'rb') as stream:
                raw = stream.read(100001)
            if len(raw)>100000:
                raise ValueError()
            value = json.loads(raw)
            if not isinstance(value,dict) or value.get('sha256') != digest:
                raise ValueError()
            return value
        except (ValueError,UnicodeDecodeError):
            raise InboxError('초안을 읽지 못했습니다.') from None

def approve(home, digest, text, category, confirmed):
    if confirmed is not True or category not in ('company','journal') or not isinstance(text,str) or not text.strip() or len(text)>16000:
        raise InboxError('수정 내용을 확인하고 반영을 승인하세요.')
    draft = read_draft(home,digest)
    if inspect(home,draft['name'])[0]['sha256'] != digest:
        raise InboxError('원본이 바뀌었습니다. 다시 확인하세요.')
    filename = '받은파일-' + digest[:24] + '.md'
    body = '# 받은 파일 정리\n\n' + text.strip() + '\n\n## 확인 근거\n\n' + draft['evidence'].strip() + '\n'
    with safe_dir(home, 'vault', category) as dfd:
        atomic_create(dfd, filename, body.encode('utf-8'))
    return {'saved':category + '/' + filename}
