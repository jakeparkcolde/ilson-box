"""텔레그램 온보딩 회귀 시험. 실제 API·토큰·메시지는 사용하지 않는다."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
import warnings


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("telegram_setup", ROOT / "template/lib/telegram-setup.py")
telegram = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(telegram)
TEST_TOKEN = "123456:" + "TEST_ONLY_NOT_A_REAL_TOKEN"
NONCE = "only_this_setup_attempt"


def update(chat_id=72, *, nonce=NONCE, kind="private", sender=None, bot=False):
    return {"update_id": 15, "message": {"text": "/start " + nonce,
            "chat": {"id": chat_id, "type": kind},
            "from": {"id": chat_id if sender is None else sender, "is_bot": bot}}}


class TelegramSetupTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="ilson-telegram-test-")
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name) / "box"
        (self.home / "state").mkdir(parents=True)
        self.pairing = self.home / "state/pairing.json"
        self.calls = []

    def save(self, data):
        self.pairing.write_text(json.dumps(data), encoding="utf-8")

    def api(self, home, token, method, payload=None, **kwargs):
        self.calls.append((method, payload, kwargs))
        if method == "getMe":
            return {"id": 123456, "is_bot": True, "username": "test_only_bot"}
        if method == "getWebhookInfo":
            return {"url": ""}
        if method == "getUpdates":
            return [update()]
        if method == "getChat":
            return {"id": 72, "type": "private"}
        self.fail("허용하지 않은 API 호출: " + method)

    @contextlib.contextmanager
    def wizard(self, *, api=None, input_value="y"):
        with patch.object(telegram, "interactive", return_value=True), \
             patch.object(telegram.getpass, "getpass", return_value=TEST_TOKEN), \
             patch.object(telegram.secrets, "token_urlsafe", return_value=NONCE), \
             patch.object(telegram, "open_bot"), \
             patch.object(telegram, "request", side_effect=api or self.api), \
             patch("builtins.input", return_value=input_value):
            yield

    def run_main(self, command, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = telegram.main([command, "--home", str(self.home), *args])
        self.assertNotIn(TEST_TOKEN, output.getvalue())
        return result, output.getvalue()

    def test_처음연결은_이번nonce의_개인방만_검증하고_안전저장한다(self):
        self.save({"source": "local", "device_id": "keep-me"})
        with self.wizard():
            result, output = self.run_main("connect")
        self.assertEqual(result, 0, output)
        data = json.loads(self.pairing.read_text())
        self.assertEqual(data["device_id"], "keep-me")
        self.assertEqual(data["telegram_chat_id"], 72)
        self.assertEqual(data["telegram_bot_id"], 123456)
        self.assertEqual(data["telegram_bot_token"], TEST_TOKEN)
        self.assertEqual(data["telegram_bot_username"], "test_only_bot")
        self.assertIn("telegram_verified_at", data)
        self.assertEqual(stat.S_IMODE(self.pairing.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.home / ".telegram-setup").stat().st_mode), 0o700)
        self.assertEqual([row[0] for row in self.calls], ["getMe", "getWebhookInfo", "getUpdates", "getChat"])
        self.assertIn("https://t.me/test_only_bot?start=" + NONCE, output)
        self.assertEqual(list((self.home / ".telegram-setup").glob("*.tmp")), [])

    def test_setup은_기존완전설정을_API없이_그대로보존한다(self):
        self.save({"telegram_bot_token": TEST_TOKEN, "telegram_chat_id": "72", "other": 5})
        before = self.pairing.read_bytes()
        with patch.object(telegram, "request") as request, patch("builtins.input") as prompt:
            result, output = self.run_main("setup")
        self.assertEqual(result, 0, output)
        request.assert_not_called()
        prompt.assert_not_called()
        self.assertEqual(self.pairing.read_bytes(), before)

    def test_setup은_기존그룹알림도_입력이나API없이보존한다(self):
        self.save({"telegram_bot_token": TEST_TOKEN, "telegram_chat_id": "-1001234567"})
        before = self.pairing.read_bytes()
        with patch.object(telegram, "request") as request, patch("builtins.input") as prompt, \
             patch.object(telegram, "interactive", return_value=True):
            result, output = self.run_main("setup")
        self.assertEqual(result, 0, output)
        prompt.assert_not_called()
        request.assert_not_called()
        self.assertEqual(self.pairing.read_bytes(), before)

    def test_status는_기존그룹알림을_개인방으로변경하지않고검증한다(self):
        self.save({"telegram_bot_token": TEST_TOKEN, "telegram_chat_id": "-1001234567"})
        before = self.pairing.read_bytes()
        def api(*args, **kwargs):
            if args[2] == "getChat":
                self.assertEqual(args[3]["chat_id"], -1001234567)
                return {"id": -1001234567, "type": "supergroup"}
            return self.api(*args, **kwargs)
        with patch.object(telegram, "request", side_effect=api):
            result, output = self.run_main("status", "--verify")
        self.assertEqual(result, 0, output)
        self.assertNotIn("개인 대화", output)
        self.assertEqual(self.pairing.read_bytes(), before)

    def test_조회도중만료된nonce를_연결하지않는다(self):
        with patch.object(telegram.time, "monotonic", side_effect=[0, 299, 301]), \
             patch.object(telegram, "request", return_value=[update()]):
            with self.assertRaisesRegex(telegram.SetupError, "시간"):
                telegram.wait_for_start(self.home, TEST_TOKEN, NONCE)

    def test_비TTY_setup은_나중에실행할명령만안내하고_성공한다(self):
        with patch.object(telegram, "interactive", return_value=False), patch.object(telegram, "request") as request:
            result, output = self.run_main("setup")
        self.assertEqual(result, 0)
        self.assertIn("ilson telegram connect", output)
        request.assert_not_called()
        self.assertFalse(self.pairing.exists())

    def test_비TTY_connect는_토큰입력도네트워크도하지않는다(self):
        with patch.object(telegram, "interactive", return_value=False), \
             patch.object(telegram.getpass, "getpass") as password, patch.object(telegram, "request") as request:
            result, output = self.run_main("connect")
        self.assertEqual(result, 1)
        self.assertIn("터미널", output)
        password.assert_not_called()
        request.assert_not_called()

    def test_setup선택거절은_알림없이끝난다(self):
        with self.wizard(input_value="n"):
            result, _ = self.run_main("setup")
        self.assertEqual(result, 0)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.pairing.exists())

    def test_기존설정교체는_명시적으로동의해야한다(self):
        self.save({"telegram_bot_token": TEST_TOKEN, "telegram_chat_id": 73})
        before = self.pairing.read_bytes()
        with self.wizard(input_value=""):
            result, _ = self.run_main("connect")
        self.assertEqual(result, 0)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.pairing.read_bytes(), before)

    def test_getpass가_숨김입력불가이면_평문fallback전에_중단한다(self):
        def fallback(*args):
            warnings.warn("echo input", telegram.getpass.GetPassWarning)
            self.fail("숨김 입력 경고 뒤 평문 fallback에 도달했다")
        with self.wizard(), patch.object(telegram.getpass, "getpass", side_effect=fallback):
            result, output = self.run_main("connect")
        self.assertEqual(result, 1)
        self.assertIn("숨겨서", output)
        self.assertEqual(self.calls, [])

    def test_webhook이있으면_삭제하거나_polling하지않는다(self):
        def api(*args, **kwargs):
            if args[2] == "getWebhookInfo":
                return {"url": "https://existing.example/private-path"}
            return self.api(*args, **kwargs)
        self.save({"source": "keep"})
        before = self.pairing.read_bytes()
        with self.wizard(api=api):
            result, output = self.run_main("connect")
        self.assertEqual(result, 1)
        self.assertNotIn("private-path", output)
        self.assertEqual([row[0] for row in self.calls], ["getMe"])
        self.assertEqual(self.pairing.read_bytes(), before)

    def test_조회는_offset과_allowed_updates를_절대전달하지않는다(self):
        with patch.object(telegram, "request", side_effect=self.api):
            self.assertEqual(telegram.wait_for_start(self.home, TEST_TOKEN, NONCE), 72)
        payload = self.calls[0][1]
        self.assertEqual(set(payload), {"limit", "timeout"})
        self.assertLessEqual(payload["timeout"], 10)

    def test_과거nonce_그룹_다른발신자_봇_전달메시지를_선택하지않는다(self):
        forwarded = update(81)
        forwarded["message"]["forward_origin"] = {"type": "user"}
        replies = [[update(73, nonce="old"), update(74, kind="group"),
                    update(75, sender=76), update(77, bot=True), forwarded], [update()]]
        with patch.object(telegram, "request", side_effect=replies), patch.object(telegram.time, "sleep"):
            self.assertEqual(telegram.wait_for_start(self.home, TEST_TOKEN, NONCE), 72)

    def test_동일nonce가_두개개인방에서오면_임의선택하지않는다(self):
        with patch.object(telegram, "request", return_value=[update(72), update(73)]):
            with self.assertRaisesRegex(telegram.SetupError, "서로 다른"):
                telegram.wait_for_start(self.home, TEST_TOKEN, NONCE)

    def test_100개backlog는_offset으로건너뛰지않는다(self):
        with patch.object(telegram, "request", return_value=[update()] * 100) as request:
            with self.assertRaisesRegex(telegram.SetupError, "많이"):
                telegram.wait_for_start(self.home, TEST_TOKEN, NONCE)
        self.assertEqual(request.call_count, 1)

    def test_시간초과는_빈성공으로삼키지않는다(self):
        with patch.object(telegram.time, "monotonic", side_effect=[0, 301]), \
             patch.object(telegram, "request") as request:
            with self.assertRaisesRegex(telegram.SetupError, "시간"):
                telegram.wait_for_start(self.home, TEST_TOKEN, NONCE)
        request.assert_not_called()

    def test_대화방재확인에실패하면_설정파일을만들지않는다(self):
        def api(*args, **kwargs):
            if args[2] == "getChat":
                return {"id": 73, "type": "private"}
            return self.api(*args, **kwargs)
        with self.wizard(api=api):
            result, output = self.run_main("connect")
        self.assertEqual(result, 1)
        self.assertIn("개인 대화", output)
        self.assertFalse(self.pairing.exists())

    def test_설정중_추가된다른필드는_최신파일과병합한다(self):
        original = {"source": "old"}
        self.save({"source": "new", "web_device": "later"})
        telegram.save_pairing(self.home, original, {"telegram_chat_id": 72})
        self.assertEqual(json.loads(self.pairing.read_text()), {"source": "new", "web_device": "later", "telegram_chat_id": 72})

    def test_동시텔레그램변경은_덮어쓰지않는다(self):
        self.save({"telegram_chat_id": 73, "other": "keep"})
        before = self.pairing.read_bytes()
        with self.assertRaisesRegex(telegram.SetupError, "다른 곳"):
            telegram.save_pairing(self.home, {}, {"telegram_chat_id": 72})
        self.assertEqual(self.pairing.read_bytes(), before)

    def test_깨진JSON은_새파일로덮어쓰지않는다(self):
        self.pairing.write_text("{broken")
        with self.wizard():
            result, _ = self.run_main("connect")
        self.assertEqual(result, 1)
        self.assertEqual(self.pairing.read_text(), "{broken")
        self.assertEqual(self.calls, [])

    def test_저장임시파일은_state밖이며_실패시제거한다(self):
        original = {"source": "keep"}
        self.save(original)
        before = self.pairing.read_bytes()
        def refuse(source, target):
            self.assertEqual(Path(source).parent, self.home / ".telegram-setup")
            self.assertEqual(stat.S_IMODE(Path(source).stat().st_mode), 0o600)
            self.assertEqual(target, self.pairing)
            raise PermissionError("mock filesystem failure")
        with patch.object(telegram.os, "replace", side_effect=refuse):
            with self.assertRaises(PermissionError):
                telegram.save_pairing(self.home, original, {"telegram_bot_token": TEST_TOKEN})
        self.assertEqual(self.pairing.read_bytes(), before)
        self.assertEqual(list((self.home / ".telegram-setup").glob("*.tmp")), [])
        self.assertEqual(sorted(path.name for path in (self.home / "state").iterdir()), ["pairing.json"])

    def test_심볼릭링크설정은_따라가지않는다(self):
        elsewhere = self.home / "elsewhere.json"
        elsewhere.write_text('{"source":"keep"}')
        self.pairing.symlink_to(elsewhere)
        with self.assertRaisesRegex(telegram.SetupError, "바로가기"):
            telegram.read_pairing(self.home)
        self.assertEqual(elsewhere.read_text(), '{"source":"keep"}')

    def test_status는_저장확인과_API검증을_구분한다(self):
        self.save({"telegram_bot_token": TEST_TOKEN, "telegram_chat_id": 72})
        with patch.object(telegram, "request") as request:
            result, output = self.run_main("status")
        self.assertEqual(result, 0)
        self.assertIn("저장", output)
        request.assert_not_called()
        with patch.object(telegram, "request", side_effect=self.api):
            result, output = self.run_main("status", "--verify")
        self.assertEqual(result, 0, output)
        self.assertEqual([row[0] for row in self.calls], ["getMe", "getChat"])

    def test_status검증은_저장된봇불일치를실패로반환한다(self):
        self.save({"telegram_bot_token": TEST_TOKEN, "telegram_chat_id": 72, "telegram_bot_id": 99999})
        with patch.object(telegram, "request", side_effect=self.api):
            result, _ = self.run_main("status", "--verify")
        self.assertEqual(result, 1)
        self.assertEqual([row[0] for row in self.calls], ["getMe"])

    def test_샌드박스에서는_connect_status검증_API직접호출도금지한다(self):
        (self.home / "state/sandbox").touch()
        self.save({"telegram_bot_token": TEST_TOKEN, "telegram_chat_id": 72})
        with patch.object(telegram, "build_opener") as opener:
            self.assertEqual(self.run_main("setup")[0], 0)
            self.assertEqual(self.run_main("connect")[0], 1)
            self.assertEqual(self.run_main("status", "--verify")[0], 1)
            with self.assertRaisesRegex(telegram.SetupError, "샌드박스"):
                telegram.request(self.home, TEST_TOKEN, "getMe")
        opener.assert_not_called()

    def test_EOF와취소는_기존설정을보존하며_setup만성공종료한다(self):
        self.save({"source": "keep"})
        before = self.pairing.read_bytes()
        for exception in (EOFError, KeyboardInterrupt):
            for command, code in (("setup", 0), ("connect", 1)):
                with self.subTest(exception=exception, command=command), self.wizard(), \
                     patch.object(telegram.getpass, "getpass", side_effect=exception):
                    result, _ = self.run_main(command)
                self.assertEqual(result, code)
                self.assertEqual(self.pairing.read_bytes(), before)

    def test_HTTP오류와네트워크예외에_토큰_URL_서버본문이노출되지않는다(self):
        errors = [HTTPError("https://example/" + TEST_TOKEN, 409, TEST_TOKEN, {}, None), URLError(TEST_TOKEN)]
        for error in errors:
            with self.subTest(error=type(error).__name__), patch.object(telegram, "build_opener") as opener:
                opener.return_value.open.side_effect = error
                with self.assertRaises(telegram.SetupError) as raised:
                    telegram.request(self.home, TEST_TOKEN, "getMe")
            self.assertNotIn(TEST_TOKEN, str(raised.exception))
            self.assertNotIn("https://", str(raised.exception))

    def test_불완전하거나실패한_API_JSON은_성공으로보지않는다(self):
        cases = [b"not-json", b"[]", b'{"ok":true}',
                 json.dumps({"ok": False, "description": TEST_TOKEN}).encode(),
                 b'{"ok":true,"result":42}']
        for raw in cases:
            with self.subTest(raw=raw[:20]), patch.object(telegram, "build_opener") as opener:
                opener.return_value.open.return_value.__enter__.return_value.read.return_value = raw
                with self.assertRaises(telegram.SetupError) as raised:
                    telegram.request(self.home, TEST_TOKEN, "getMe")
                self.assertNotIn(TEST_TOKEN, str(raised.exception))

    def test_메시지발송이나웹훅삭제_API는_호출할수없다(self):
        with patch.object(telegram, "build_opener") as opener:
            for method in ("sendMessage", "deleteWebhook", "setWebhook"):
                with self.assertRaises(telegram.SetupError):
                    telegram.request(self.home, TEST_TOKEN, method)
        opener.assert_not_called()

    def test_리디렉션은_토큰을다른호스트로보내지않는다(self):
        with self.assertRaises(telegram.SetupError):
            telegram.NoRedirect().redirect_request(None, None, 302, None, {}, "https://elsewhere.example")

    def test_맥링크열기는_shell문자열을사용하지않는다(self):
        with patch.object(telegram.sys, "platform", "darwin"), patch.object(telegram.subprocess, "run") as run:
            telegram.open_bot("https://t.me/test_only_bot?start=" + NONCE)
        self.assertEqual(run.call_args.args[0], ["open", "https://t.me/test_only_bot?start=" + NONCE])
        self.assertFalse(run.call_args.kwargs.get("shell", False))


if __name__ == "__main__":
    unittest.main()
