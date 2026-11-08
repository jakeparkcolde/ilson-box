"""Private Telegram approval cards; a single locked long-poll consumer per Box."""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
import approval_store as store
import approval_dispatch as dispatch


class TelegramError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_):
        raise TelegramError('redirect')


def api(token, method, data, *, endpoint='https://api.telegram.org'):
    req = Request(endpoint + '/bot' + token + '/' + method,
                  data=json.dumps(data).encode(), headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with build_opener(NoRedirect()).open(req, timeout=40) as response:
            result = json.loads(response.read(2_000_001))
        if not isinstance(result, dict) or result.get('ok') is not True:
            raise TelegramError('request failed')
        return result['result']
    except HTTPError as error:
        error.close()
        raise TelegramError('connection failed') from None
    except (URLError, OSError, ValueError, KeyError, TimeoutError):
        raise TelegramError('connection failed') from None


def root(home):
    # connect creates the private directory using a restricted umask.
    with store.connect(home):
        pass
    return store.home_path(home) / '.approval'


def receiver_lock(home):
    path = root(home) / 'receiver.lock'
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, BlockingIOError):
        os.close(fd)
        raise TelegramError('이미 텔레그램 수신기가 실행 중입니다. 먼저 중지해 주세요.') from None
    return fd


def read_config(home):
    path = root(home) / 'telegram.json'
    if path.is_symlink():
        raise TelegramError('invalid configuration')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or not isinstance(data.get('token'), str) or type(data.get('chat_id')) is not int or type(data.get('user_id')) is not int or not isinstance(data.get('generation'), str):
            raise ValueError()
        return data
    except (OSError, ValueError):
        raise TelegramError('휴대폰 승인 연결이 필요합니다.') from None


def save_config(home, token, chat_id, user_id):
    base = root(home)
    fd, temp = tempfile.mkstemp(dir=base, prefix='pair-')
    with os.fdopen(fd, 'w', encoding='utf-8') as out:
        json.dump({'token': token, 'chat_id': chat_id, 'user_id': user_id,
                   'generation': secrets.token_hex(16)}, out)
        out.flush()
        os.fsync(out.fileno())
    os.replace(temp, base / 'telegram.json')
    # The generation has its own offset; old buttons fail generation validation.


def send_card(home, request_id, *, consent=False, transport=api, license_check=None):
    if (store.home_path(home) / 'state/sandbox').exists():
        raise TelegramError('샌드박스에서는 텔레그램에 보내지 않습니다.')
    if not consent:
        raise TelegramError('텔레그램에 전문을 보내는 데 동의해야 합니다.')
    if license_check is None:
        from license import evaluate
        license_check = lambda: evaluate(home)[0]
    if not license_check():
        raise TelegramError('라이선스 확인이 필요합니다.')
    req = store.get(request_id, home)
    if not req or req['state'] != 'pending' or req['expires'] <= time.time():
        raise TelegramError('대기 중인 요청이 아닙니다.')
    cfg = read_config(home)
    action = store._ACTIONS.get(req['action_type'])
    if not action:
        raise TelegramError('등록되지 않은 승인 요청입니다.')
    text = '승인 요청\n행동: ' + req['action_type'] + '\n대상: ' + json.dumps(req['target'], ensure_ascii=False)
    if action[2] is not None:
        text += '\n문의 원문은 일손 화면에서 확인해 주세요.'
    else:
        text += '\n제목: ' + req['title']
    text += '\n\n' + req['body']
    if cfg['token'] in text or re.search(r'\b[0-9]{5,15}:[A-Za-z0-9_-]{20,200}\b', text):
        raise TelegramError('비밀값이 포함되어 있어 보낼 수 없습니다.')
    if len(text) > 3500:
        raise TelegramError('내용이 깁니다. 로컬 승인 대기함에서 확인해 주세요.')
    tokens = {decision: secrets.token_urlsafe(24) for decision in ('approved', 'changed', 'rejected')}
    keyboard = [[{'text': label, 'callback_data': tokens[key]} for label, key in
                 (('승인', 'approved'), ('고치기', 'changed'), ('버리기', 'rejected'))]]
    message = transport(cfg['token'], 'sendMessage', {'chat_id': cfg['chat_id'], 'text': text, 'reply_markup': {'inline_keyboard': keyboard}})
    message_id = message.get('message_id') if isinstance(message, dict) else None
    if type(message_id) is not int or message_id <= 0:
        raise TelegramError('메시지 확인 실패')
    store.bind_callbacks(request_id, tokens, cfg['chat_id'], cfg['user_id'], message_id, cfg['generation'], home=home)
    return message_id


def process_update(home, update, *, transport=api, license_check=None):
    cb = update.get('callback_query') if isinstance(update, dict) else None
    if not isinstance(cb, dict) or not isinstance(cb.get('id'), str):
        return
    cfg = read_config(home)
    sender, msg = cb.get('from'), cb.get('message')
    result = None
    if isinstance(sender, dict) and isinstance(msg, dict) and isinstance(msg.get('chat'), dict):
        chat = msg['chat']
        if (chat.get('type') == 'private' and type(chat.get('id')) is int and chat['id'] == cfg['chat_id']
                and type(sender.get('id')) is int and sender['id'] == cfg['user_id']
                and sender.get('is_bot') is False and type(msg.get('message_id')) is int
                and not any(msg.get(key) for key in ('forward_origin', 'forward_from', 'forward_from_chat', 'forward_sender_name', 'forward_date'))):
            result = store.callback(cb.get('data'), chat['id'], sender['id'], msg['message_id'], cfg['generation'], home=home)
    label = '이미 처리되었거나 확인할 수 없는 요청입니다.'
    if result:
        label = {'approved': '승인을 접수했습니다.', 'changed': '고친 뒤 새 승인을 요청해 주세요.', 'rejected': '요청을 취소했습니다. 원본은 남아 있습니다.'}[result[1]]
    try:
        transport(cfg['token'], 'answerCallbackQuery', {'callback_query_id': cb['id'], 'text': label})
    except TelegramError:
        pass
    if result and result[1] == 'approved':
        dispatch.dispatch(result[0], home, license_check=license_check)


def poll_once(home, *, transport=api, license_check=None):
    cfg = read_config(home)
    offset = int(store.setting('offset:' + cfg['generation'], home=home) or '0')
    updates = transport(cfg['token'], 'getUpdates', {'offset': offset, 'timeout': 25, 'allowed_updates': ['message', 'callback_query']})
    if not isinstance(updates, list):
        raise TelegramError('invalid updates')
    for update in updates:
        if not isinstance(update, dict) or type(update.get('update_id')) is not int:
            raise TelegramError('invalid update')
        process_update(home, update, transport=transport, license_check=license_check)
        offset = max(offset, update['update_id'] + 1)
        store.setting('offset:' + cfg['generation'], offset, home=home)


def code_fingerprint():
    base = Path(__file__).resolve().parent
    paths = [base / name for name in ('approval_telegram.py', 'approval_store.py', 'approval_dispatch.py', 'approval_actions.py')]
    paths.extend(sorted(base.glob('replies_*.py')))
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode())
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b'missing')
    return digest.digest()


def serve(home):
    if (store.home_path(home) / 'state/sandbox').exists():
        raise TelegramError('샌드박스에서는 수신하지 않습니다.')
    os.environ['ILSON_HOME'] = str(store.home_path(home).resolve())
    from approval_actions import load_all
    load_all()
    fd = receiver_lock(home)
    try:
        fingerprint = code_fingerprint()
        dispatch.recover(home)
        # A crash after accepting a click but before dispatch leaves an untouched
        # approval. Only those never claimed can be resumed; executing is unknown.
        for req in store.list_requests(home):
            if req['state'] == 'approved' and req['execution'] == 'received':
                dispatch.dispatch(req['id'], home)
        while True:
            # launchd KeepAlive reloads new code after a regular Box update.
            if code_fingerprint() != fingerprint:
                return
            try:
                poll_once(home)
            except TelegramError:
                # No token or remote response is printed.
                print('텔레그램 수신을 확인하지 못했습니다. 연결 상태를 확인합니다.', file=sys.stderr)
                time.sleep(10)
    finally:
        os.close(fd)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', type=Path, required=True)
    args = parser.parse_args()
    serve(args.home)
