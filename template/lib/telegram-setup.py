# coding: utf-8
"""토큰을 대화에 남기지 않고 개인 텔레그램 알림을 연결한다.

설정 마법사는 알림을 보내거나 기존 webhook·업데이트 구독을 바꾸지 않는다.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import getpass
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
import warnings


TOKEN = re.compile(r"[0-9]{5,16}:[A-Za-z0-9_-]{20,200}\Z")
USERNAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")
METHODS = {"getMe", "getWebhookInfo", "getUpdates", "getChat"}
WAIT_SECONDS = 300


class SetupError(ValueError):
    pass


def positive_id(value):
    if isinstance(value, str) and value.isascii() and value.isdigit():
        value = int(value)
    return value if type(value) is int and value > 0 else None


def saved_chat_id(value):
    # 기존 notify.sh는 그룹·채널의 음수 chat_id도 사용한다. 재설치가 이를 지우면 안 된다.
    if isinstance(value, str) and re.fullmatch(r"-?[0-9]+", value):
        value = int(value)
    return value if type(value) is int and value != 0 else None


def check_sandbox(home):
    if (home / "state/sandbox").exists():
        raise SetupError("샌드박스에서는 텔레그램에 연결하지 않습니다.")


def read_pairing(home):
    path = home / "state/pairing.json"
    if path.is_symlink() or path.parent.is_symlink():
        raise SetupError("연결 설정 경로가 바로가기입니다. 기존 설정을 보존했습니다.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise SetupError("연결 설정 파일을 읽지 못했습니다. 기존 설정을 보존했습니다.") from None
    if not isinstance(data, dict):
        raise SetupError("연결 설정 파일 형식이 올바르지 않습니다. 기존 설정을 보존했습니다.")
    return data


def telegram_fields(data):
    return {key: value for key, value in data.items() if key.startswith("telegram_")}


def configured(data):
    token = data.get("telegram_bot_token")
    return isinstance(token, str) and bool(TOKEN.fullmatch(token)) and saved_chat_id(data.get("telegram_chat_id")) is not None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_):
        raise SetupError("텔레그램 응답 주소가 변경되어 연결을 중단했습니다.")


def request(home, token, method, payload=None, *, request_timeout=15):
    """API 주소에는 토큰이 있으므로 예외 원문과 서버 description을 출력하지 않는다."""
    check_sandbox(home)
    if method not in METHODS or not TOKEN.fullmatch(token):
        raise SetupError("텔레그램 연결 정보가 올바르지 않습니다.")
    req = Request(
        "https://api.telegram.org/bot" + token + "/" + method,
        data=json.dumps(payload or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with build_opener(NoRedirect()).open(req, timeout=request_timeout) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise SetupError("텔레그램 응답이 너무 커서 연결을 중단했습니다.")
        body = json.loads(raw)
    except HTTPError as error:
        if error.code in (401, 404):
            message = "봇 토큰을 확인하지 못했습니다. BotFather에서 복사한 토큰을 확인하세요."
        elif error.code == 409:
            message = "다른 곳에서 이 봇의 메시지를 받고 있습니다. 기존 수신 연결을 확인하세요."
        elif error.code == 429:
            message = "텔레그램 요청이 잠시 제한되었습니다. 잠시 뒤 다시 연결하세요."
        else:
            message = "텔레그램 요청에 실패했습니다. 기존 설정은 유지됩니다."
        raise SetupError(message) from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise SetupError("텔레그램 응답을 확인하지 못했습니다. 네트워크를 확인하고 다시 연결하세요.") from None
    if not isinstance(body, dict) or body.get("ok") is not True or "result" not in body:
        raise SetupError("텔레그램에서 연결을 확인하지 못했습니다. 기존 설정은 유지됩니다.")
    result = body["result"]
    if method == "getUpdates":
        if not isinstance(result, list) or any(not isinstance(update, dict) for update in result):
            raise SetupError("텔레그램 메시지 응답 형식을 확인하지 못했습니다.")
    elif not isinstance(result, dict):
        raise SetupError("텔레그램 연결 응답 형식을 확인하지 못했습니다.")
    return result


def bot_identity(home, token):
    bot = request(home, token, "getMe")
    username = bot.get("username")
    if positive_id(bot.get("id")) is None or bot.get("is_bot") is not True or not isinstance(username, str) or not USERNAME.fullmatch(username):
        raise SetupError("봇의 정보를 확인하지 못했습니다. 기존 설정은 유지됩니다.")
    return {"id": positive_id(bot["id"]), "username": username}


def verify_chat(home, token, chat_id, *, private_only=True):
    chat = request(home, token, "getChat", {"chat_id": chat_id})
    types = {"private"} if private_only else {"private", "group", "supergroup", "channel"}
    if chat.get("type") not in types or saved_chat_id(chat.get("id")) != chat_id:
        description = "개인 대화방" if private_only else "기존 대화방"
        raise SetupError(description + "을 확인하지 못했습니다. 기존 설정은 유지됩니다.")


def wait_for_start(home, token, nonce, *, wait_seconds=WAIT_SECONDS):
    deadline = time.monotonic() + wait_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SetupError("연결 시간이 지났습니다. 다시 실행한 뒤 봇에서 시작 버튼을 눌러 주세요.")
        # offset은 앞선 메시지를 확인 처리한다. 음수 offset도 이전 큐를 버린다.
        # allowed_updates는 지속 설정이다. 둘 다 생략하여 기존 수신을 보존한다.
        updates = request(home, token, "getUpdates", {"timeout": min(10, max(0, int(remaining) - 1)), "limit": 100},
                          request_timeout=min(15, remaining))
        if time.monotonic() >= deadline:
            raise SetupError("연결 시간이 지났습니다. 다시 실행한 뒤 봇에서 시작 버튼을 눌러 주세요.")
        if len(updates) >= 100:
            raise SetupError("받지 않은 메시지가 많이 남아 있습니다. 기존 봇 수신 프로그램에서 먼저 확인해 주세요.")
        matches = set()
        for update in updates:
            message = update.get("message")
            if not isinstance(message, dict) or message.get("text") != "/start " + nonce:
                continue
            chat = message.get("chat")
            sender = message.get("from")
            if not isinstance(chat, dict) or not isinstance(sender, dict):
                continue
            chat_id = positive_id(chat.get("id"))
            if chat.get("type") == "private" and chat_id is not None and positive_id(sender.get("id")) == chat_id and sender.get("is_bot") is False and not message.get("forward_origin"):
                matches.add(chat_id)
        if len(matches) > 1:
            raise SetupError("서로 다른 개인 대화에서 연결 요청을 받았습니다. 링크를 공유하지 말고 다시 연결하세요.")
        if matches:
            return matches.pop()
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(1, remaining))


def save_pairing(home, original, changes):
    """snapshot은 vault/state를 수집한다. 토큰 임시 파일은 그 밖에만 둔다."""
    check_sandbox(home)
    private = home / ".telegram-setup"
    if private.is_symlink():
        raise SetupError("텔레그램 설정 경로가 바로가기입니다. 기존 설정을 보존했습니다.")
    private.mkdir(mode=0o700, parents=True, exist_ok=True)
    private.chmod(0o700)
    lock_path = private / "lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_path, flags, 0o600)
    with os.fdopen(descriptor, "a") as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        current = read_pairing(home)
        if telegram_fields(current) != telegram_fields(original):
            raise SetupError("연결 중 다른 곳에서 텔레그램 설정이 바뀌었습니다. 최신 설정을 보존했습니다.")
        current.update(changes)
        target = home / "state/pairing.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix="pairing-", suffix=".tmp", dir=private)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(current, output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def open_bot(url):
    if sys.platform == "darwin":
        try:
            subprocess.run(["open", url], check=False, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            print("자동으로 열지 못했습니다. 위 링크를 직접 열어 주세요.")


def interactive():
    return bool(sys.stdin.isatty())


def connect(home, original=None):
    check_sandbox(home)
    if not interactive():
        raise SetupError("터미널에서 ilson telegram connect 를 직접 실행해 주세요. 토큰을 채팅에 붙여넣지 않아도 됩니다.")
    original = read_pairing(home) if original is None else original
    if telegram_fields(original):
        answer = input("기존 텔레그램 연결을 바꾸시겠어요? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("기존 텔레그램 연결을 유지했습니다.")
            return
    print("텔레그램에서 @BotFather 를 열고 /newbot 으로 봇을 만들어 주세요.")
    print("이미 만든 봇은 BotFather에서 토큰을 복사하면 됩니다. 입력한 토큰은 화면에 표시되지 않습니다.")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            token = getpass.getpass("봇 토큰 붙여넣기: ").strip()
        except getpass.GetPassWarning:
            raise SetupError("토큰을 숨겨서 입력할 수 없습니다. 일반 터미널에서 다시 실행해 주세요.") from None
    if not TOKEN.fullmatch(token):
        raise SetupError("봇 토큰 형식을 확인해 주세요. 입력한 내용은 저장하지 않았습니다.")
    bot = bot_identity(home, token)
    webhook = request(home, token, "getWebhookInfo")
    if not isinstance(webhook.get("url"), str):
        raise SetupError("봇의 기존 연결 상태를 확인하지 못했습니다.")
    if webhook["url"]:
        raise SetupError("이 봇은 다른 서비스에 연결되어 있습니다. 기존 연결을 유지하려면 새 봇을 만들어 연결해 주세요.")
    nonce = secrets.token_urlsafe(24)
    url = "https://t.me/" + bot["username"] + "?start=" + nonce
    print("확인된 봇: @" + bot["username"])
    print("아래 링크를 열고 텔레그램의 시작 버튼을 눌러 주세요. 링크는 5분 동안만 사용합니다.")
    print(url)
    open_bot(url)
    chat_id = wait_for_start(home, token, nonce)
    verify_chat(home, token, chat_id)
    save_pairing(home, original, {
        "telegram_bot_token": token,
        "telegram_chat_id": chat_id,
        "telegram_bot_id": bot["id"],
        "telegram_bot_username": bot["username"],
        "telegram_verified_at": datetime.now(timezone.utc).isoformat(),
    })
    print("텔레그램 개인 알림 연결을 저장했습니다. 시험 메시지는 보내지 않았습니다.")


def status(home, verify=False):
    data = read_pairing(home)
    if not configured(data):
        print("텔레그램 알림이 연결되지 않았습니다. ilson telegram connect 로 연결하세요.")
        return 1 if verify else 0
    if not verify:
        print("텔레그램 연결 설정이 저장되어 있습니다. 실제 연결 확인: ilson telegram status --verify")
        return 0
    check_sandbox(home)
    bot = bot_identity(home, data["telegram_bot_token"])
    saved_bot = data.get("telegram_bot_id")
    if saved_bot is not None and positive_id(saved_bot) != bot["id"]:
        raise SetupError("저장된 봇과 토큰의 봇이 다릅니다. 다시 연결해 주세요.")
    verify_chat(home, data["telegram_bot_token"], saved_chat_id(data["telegram_chat_id"]), private_only=False)
    print("텔레그램 봇과 저장된 대화 연결을 확인했습니다. 메시지는 보내지 않았습니다.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="개인 텔레그램 알림 연결")
    parser.add_argument("command", choices=("setup", "connect", "status"))
    parser.add_argument("--home", type=Path, default=Path(os.environ.get("ILSON_HOME", Path.home() / "ilson")))
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    if args.verify and args.command != "status":
        parser.error("--verify 는 status 에서만 사용할 수 있습니다")
    try:
        if args.command == "status":
            return status(args.home, args.verify)
        if args.command == "setup":
            original = read_pairing(args.home)
            if configured(original):
                print("기존 텔레그램 알림 연결을 유지했습니다.")
                return 0
            if (args.home / "state/sandbox").exists():
                print("샌드박스에서는 텔레그램 연결을 건너뜁니다.")
                return 0
            if not interactive():
                print("텔레그램 알림 연결은 터미널에서 ilson telegram connect 를 실행하면 됩니다.")
                return 0
            if input("개인 텔레그램으로 일손 알림을 받으시겠어요? [Y/n] ").strip().lower() in ("n", "no"):
                print("나중에 ilson telegram connect 로 연결할 수 있습니다.")
                return 0
            connect(args.home, original)
        else:
            connect(args.home)
        return 0
    except (EOFError, KeyboardInterrupt):
        print("\n연결을 취소했습니다. 기존 설정은 유지됩니다.")
    except SetupError as error:
        print(str(error))
    except OSError:
        print("설정 파일을 저장하지 못했습니다. 기존 설정을 확인한 뒤 다시 연결해 주세요.")
    return 0 if args.command == "setup" else 1


if __name__ == "__main__":
    raise SystemExit(main())
