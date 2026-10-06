#!/usr/bin/env python3
"""일손 Box의 로컬 읽기 전용 관리자. 실행·설정 변경·외부 접속 API는 없다."""
from __future__ import annotations

import argparse
from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import hmac
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
from socketserver import TCPServer
import stat
import subprocess
import sys
import threading
import time
from urllib.parse import unquote, urlsplit

SERVICE = "ilson-box-admin"
SESSION_SECONDS = 8 * 3600
REPORT_LIMIT = 100
REPORT_BYTES = 256 * 1024
REPORT_DEPTH = 3
SCAN_LIMIT = 1000
JOB_LIMIT = 100
BODY_LIMIT = 4096
LABELS = {
    "briefing": "아침 브리핑", "weekly": "주간 보고", "tidy": "자료 정리",
    "watchdog": "업무 점검", "snapshot": "복구용 기록", "update": "일손 업데이트",
    "admin": "웹 관리자",
}
STATIC = {"/": ("web/index.html", "text/html; charset=utf-8"),
          "/index.html": ("web/index.html", "text/html; charset=utf-8"),
          "/styles.css": ("web/styles.css", "text/css; charset=utf-8"),
          "/app.js": ("web/app.js", "application/javascript; charset=utf-8"),
          "/favicon.svg": ("web/favicon.svg", "image/svg+xml")}


class AdminError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class Unreadable(ValueError):
    pass


def stamp(value=None):
    return datetime.fromtimestamp(time.time() if value is None else value, timezone.utc).isoformat(timespec="seconds")


class Files:
    """허용한 루트 아래 일반 파일만 연다. 모든 경로 요소에서 링크를 거부한다."""
    def __init__(self, home):
        self.home = Path(home).resolve()

    def open_dir(self, parts=()):
        descriptor = os.open(self.home, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts:
                if part in {"", ".", ".."} or "/" in part:
                    raise Unreadable("경로를 확인할 수 없습니다.")
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            return descriptor
        except Exception:
            os.close(descriptor)
            raise

    def read(self, relative, limit, private=False):
        parts = Path(relative).parts
        if not parts or Path(relative).is_absolute() or any(p in {"", ".", ".."} for p in parts):
            raise Unreadable("경로를 확인할 수 없습니다.")
        directory = None
        descriptor = None
        try:
            directory = self.open_dir(parts[:-1])
            descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
                raise Unreadable("파일 형식 또는 크기를 확인해주세요.")
            if private and (stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid()):
                raise Unreadable("관리자 연결 파일의 소유자·권한을 확인해주세요.")
            pieces = []
            remaining = limit + 1
            while remaining:
                chunk = os.read(descriptor, min(remaining, 65536))
                if not chunk:
                    break
                pieces.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(pieces)
            if len(raw) > limit:
                raise Unreadable("파일이 너무 큽니다.")
            return raw, info
        except FileNotFoundError:
            raise
        except (OSError, ValueError):
            raise Unreadable("파일을 안전하게 읽지 못했습니다.") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if directory is not None:
                os.close(directory)

    def text(self, relative, limit, private=False):
        raw, info = self.read(relative, limit, private)
        try:
            return raw.decode("utf-8"), info
        except UnicodeError:
            raise Unreadable("문서 인코딩을 확인해주세요.") from None

    def marker(self, relative):
        try:
            self.read(relative, 100)
            return True
        except FileNotFoundError:
            return False
        except Unreadable:
            return None


class Probe:
    """사용자 입력을 명령에 넣지 않는 제한된 상태 조회. 결과는 30초 캐시한다."""
    def __init__(self, home, run=None, which=shutil.which, clock=time.monotonic):
        self.home, self.which, self.clock = home, which, clock
        self.run = run or self.command
        self.cache = {}
        self.lock = threading.Lock()

    def command(self, args):
        process = None
        try:
            process = subprocess.Popen(args, cwd=self.home, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       start_new_session=True)
            try:
                raw, _ = process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                return None
            if len(raw) > 1024 * 1024:
                return None
            return process.returncode, raw.decode("utf-8")
        except (OSError, UnicodeError):
            return None
        finally:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()

    def cached(self, key, factory):
        with self.lock:
            now = self.clock()
            found = self.cache.get(key)
            if found and now - found[0] < 30:
                return found[1]
            value = factory()
            self.cache[key] = (self.clock(), value)
            return value

    def claude(self):
        def query():
            executable = self.which("claude")
            if not executable:
                return "attention", "Claude Code가 없습니다. 터미널에서 ilson setup을 실행하세요."
            result = self.run([executable, "auth", "status"])
            if result is not None:
                code, output = result
                try:
                    data = json.loads(output)
                    if isinstance(data, dict) and data.get("loggedIn") is False:
                        return "attention", "Claude에 로그인하지 않았습니다. 터미널에서 claude로 로그인하세요."
                    if code == 0 and isinstance(data, dict) and data.get("loggedIn") is True:
                        return "ok", "Claude 로그인 상태를 확인했습니다. 업무 실행·잔여 한도는 별도 확인이 필요합니다."
                except (ValueError, TypeError):
                    pass
            return "unknown", "로그인 상태를 확인하지 못했습니다. 터미널에서 ilson doctor로 점검하세요."
        return self.cached("claude", query)

    def jobs(self):
        def query():
            executable = self.which("launchctl")
            if not executable:
                return None
            result = self.run([executable, "list"])
            if result is None or result[0] != 0:
                return None
            lines = result[1].splitlines()
            if not lines or lines[0].split() != ["PID", "Status", "Label"]:
                return None
            labels = set()
            for line in lines[1:]:
                if not line.strip():
                    continue
                parts = line.split()
                if len(parts) != 3 or not re.fullmatch(r"-|[0-9]+", parts[0]) or not re.fullmatch(r"-?[0-9]+", parts[1]):
                    return None
                labels.add(parts[2])
            return labels
        return self.cached("launchctl", query)


def schedule_label(value):
    daily = re.fullmatch(r"daily ([0-2][0-9]):([0-5][0-9])", value)
    weekly = re.fullmatch(r"weekly ([0-6]) ([0-2][0-9]):([0-5][0-9])", value)
    every = re.fullmatch(r"every ([0-9]{1,8})", value)
    if daily and int(daily[1]) < 24:
        return f"매일 {daily[1]}:{daily[2]}"
    if weekly and int(weekly[2]) < 24:
        return f"매주 {'일월화수목금토'[int(weekly[1])]}요일 {weekly[2]}:{weekly[3]}"
    if every and 1 <= int(every[1]) <= 31536000:
        seconds = int(every[1])
        if seconds % 3600 == 0:
            return f"{seconds // 3600}시간마다"
        if seconds % 60 == 0:
            return f"{seconds // 60}분마다"
        return f"{seconds}초마다"
    return None


class Box:
    def __init__(self, home, *, probe=None, user_home=None, clock=time.time):
        # Claude와 ilson doctor는 사용자가 진입한 경로를 신뢰 키로 기록한다.
        # macOS /var와 /private/var처럼 같은 폴더의 원래 경로도 확인한다.
        self.project_paths = {str(Path(home).absolute()), str(Path(home).resolve())}
        self.home = Path(home).resolve()
        self.files = Files(self.home)
        self.user_files = Files(user_home or Path.home())
        self.clock = clock
        self.probe = probe or Probe(self.home)
        try:
            token, _ = self.files.text("state/web-admin/token", 200, private=True)
            instance, _ = self.files.text("state/web-admin/instance", 200, private=True)
        except (FileNotFoundError, Unreadable):
            raise AdminError("관리자 연결 설정이 없습니다. ilson admin start로 준비해주세요.") from None
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,160}", token) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", instance):
            raise AdminError("관리자 연결 설정 형식을 확인해주세요.")
        self.token, self.instance = token, instance
        self.cookie_name = "ilson_box_admin_" + hashlib.sha256(str(self.home).encode()).hexdigest()[:12]
        self.sessions = {}
        self.session_lock = threading.Lock()
        self.attempts = OrderedDict()
        self.secret_values = {token}
        self.secret_lock = threading.Lock()

    def redact(self, value):
        with self.secret_lock:
            known = tuple(self.secret_values)
        if isinstance(value, str):
            for secret in known:
                value = value.replace(secret, "[비밀값 숨김]")
            return re.sub(r"\b[0-9]{5,15}:[A-Za-z0-9_-]{20,200}\b", "[비밀값 숨김]", value)
        if isinstance(value, dict):
            return {key: self.redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        return value

    def telegram(self):
        blank = {"state": "missing", "bot_username": None, "verified_at": None}
        try:
            raw, _ = self.files.text("state/pairing.json", 65536)
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError()
        except FileNotFoundError:
            return blank
        except (Unreadable, ValueError):
            return {**blank, "state": "unknown"}
        token, chat = data.get("telegram_bot_token"), data.get("telegram_chat_id")
        if isinstance(token, str) and len(token) >= 8:
            with self.secret_lock:
                self.secret_values.add(token)
        configured = (isinstance(token, str) and re.fullmatch(r"[0-9]{5,15}:[A-Za-z0-9_-]{20,200}", token)
                      and ((type(chat) is int and chat != 0) or (isinstance(chat, str) and re.fullmatch(r"-?[1-9][0-9]*", chat))))
        name, checked = data.get("telegram_bot_username"), data.get("telegram_verified_at")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_]{5,64}", name):
            name = None
        try:
            parsed = datetime.fromisoformat(checked.replace("Z", "+00:00")) if isinstance(checked, str) else None
            checked = parsed.isoformat(timespec="seconds") if parsed and parsed.tzinfo else None
        except ValueError:
            checked = None
        return {"state": "configured" if configured else "missing", "bot_username": name, "verified_at": checked}

    def company(self):
        try:
            text, _ = self.files.text("vault/CONTEXT.md", 65536)
            match = re.search(r"^- 회사명:[ \t]*([^\r\n]*)", text, re.MULTILINE)
            name = match[1].strip() if match else ""
            if not name or name.startswith("("):
                return "우리 회사", "attention", "회사 정보가 비어 있습니다. ilson chat에서 /onboard로 인터뷰를 시작하세요."
            return name[:120], "ok", "회사 이름이 기록되어 있습니다."
        except FileNotFoundError:
            return "우리 회사", "attention", "회사 소개가 없습니다. ilson setup 후 회사 인터뷰를 진행하세요."
        except Unreadable:
            return "우리 회사", "unknown", "회사 정보 파일을 확인하지 못했습니다."

    def trust(self):
        try:
            raw, _ = self.user_files.text(".claude.json", 4 * 1024 * 1024)
            data = json.loads(raw)
            projects = data.get("projects") if isinstance(data, dict) else None
            if not isinstance(projects, dict):
                return "unknown", "Claude 폴더 신뢰 설정을 확인하지 못했습니다."
            if any(isinstance(projects.get(path), dict)
                   and projects[path].get("hasTrustDialogAccepted") is True
                   for path in self.project_paths):
                return "ok", "이 Box 폴더의 Claude 신뢰 설정을 확인했습니다."
            return "attention", "터미널에서 ilson chat을 열고 폴더 신뢰를 확인하세요."
        except FileNotFoundError:
            return "attention", "터미널에서 ilson chat을 처음 열어 폴더 신뢰를 확인하세요."
        except (Unreadable, ValueError):
            return "unknown", "Claude 폴더 신뢰 설정을 읽지 못했습니다."

    def jobs(self, sandbox):
        try:
            text, _ = self.files.text("launchd/jobs.conf", 65536)
        except (FileNotFoundError, Unreadable):
            return [], ["예약 업무 설정을 읽지 못했습니다."]
        parsed, seen, invalid = [], set(), 0
        lines = text.splitlines()
        for line in lines[:512]:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [part.strip() for part in line.split("|")]
            if len(parts) != 4:
                invalid += 1
                continue
            name, script, arguments, schedule = parts
            label = schedule_label(schedule)
            if (not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name) or name in seen
                    or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}\.sh", script)
                    or len(arguments) > 256 or any(ord(c) < 32 for c in arguments) or label is None):
                invalid += 1
                continue
            seen.add(name)
            if len(parsed) >= JOB_LIMIT:
                invalid += 1
                continue
            parsed.append((name, label))
        notices = []
        if invalid or len(lines) > 512:
            notices.append("일부 예약 설정을 확인하지 못했습니다. 터미널에서 ilson doctor로 점검하세요.")
        registered = None if sandbox else self.probe.jobs()
        rows = []
        for name, schedule in parsed:
            label = LABELS.get(name, "추가 업무")
            if name not in LABELS:
                try:
                    command, _ = self.files.text(f".claude/commands/{name}.md", 65536)
                    description = re.search(r"^description:[ \t]*([^\r\n]+)", "\n".join(command.splitlines()[:20]), re.MULTILINE)
                    if description:
                        label = description[1].strip(" \"'")[:80]
                except (FileNotFoundError, Unreadable):
                    pass
            registration = "sandbox" if sandbox else ("unknown" if registered is None else ("loaded" if "com.ilson." + name in registered else "not_loaded"))
            labels = {"loaded": "예약 등록 확인", "not_loaded": "등록되지 않음", "unknown": "등록 상태 확인 불가", "sandbox": "샌드박스 · 실행하지 않음"}
            last, state = None, "missing"
            try:
                raw, _ = self.files.text(f"state/last-run.{name}", 32)
                raw = raw.strip()
                if not re.fullmatch(r"[0-9]{1,12}", raw) or not 0 < int(raw) <= self.clock() + 300:
                    raise Unreadable("시각 확인 불가")
                last, state = stamp(int(raw)), "recorded"
            except FileNotFoundError:
                pass
            except (Unreadable, ValueError, OverflowError):
                state = "unknown"
            rows.append({"id": name, "label": label, "schedule": schedule, "registration": registration,
                         "registration_label": labels[registration], "last_success_at": last,
                         "last_success_state": state, "execution_state": "unknown",
                         "execution_label": "현재 실행 중인지와 최근 실패 여부는 이 기록으로 알 수 없습니다."})
        return rows, notices

    def overview(self):
        marker = self.files.marker("state/sandbox")
        sandbox = marker is not False
        company, company_state, company_detail = self.company()
        telegram = self.telegram()
        claude = ("unknown", "샌드박스에서는 계정 상태를 조회하지 않습니다.") if sandbox else self.probe.claude()
        trust = self.trust()
        checks = [{"id": "claude", "label": "Claude 로그인", "state": claude[0], "detail": claude[1]},
                  {"id": "company", "label": "회사 정보", "state": company_state, "detail": company_detail},
                  {"id": "trust", "label": "회사 폴더 신뢰", "state": trust[0], "detail": trust[1]},
                  {"id": "telegram", "label": "텔레그램 알림", "state": {"configured": "ok", "missing": "attention", "unknown": "unknown"}[telegram["state"]],
                   "detail": {"configured": "알림 설정이 저장되어 있습니다. 현재 연결·실제 수신은 별도 확인이 필요합니다.", "missing": "터미널에서 ilson telegram connect로 알림을 연결하세요.", "unknown": "알림 설정을 확인하지 못했습니다."}[telegram["state"]]}]
        installed = self.probe.which("tvly") is not None
        try:
            self.files.read("lib/search.sh", 128 * 1024)
            self.files.read(".claude/skills/ilson-search/SKILL.md", 128 * 1024)
        except (FileNotFoundError, Unreadable):
            installed = False
        checks.append({"id": "search", "label": "웹 검색 준비", "state": "ok" if installed else "attention",
                       "detail": "검색 도구·스킬이 있습니다. 인증·잔여 한도·실제 검색은 확인하지 않았습니다." if installed else "검색 구성 확인이 필요합니다. 터미널에서 ilson setup을 실행하세요."})
        jobs, notices = self.jobs(sandbox)
        pending, complete = self.files.marker("state/setup-pending"), self.files.marker("state/setup-complete")
        setup_state = "pending" if sandbox or pending is True else ("ready" if complete is True else "unknown")
        return self.redact({"generated_at": stamp(self.clock()), "box": {"company_name": company, "sandbox": sandbox,
                            "setup_state": setup_state, "timezone": datetime.now().astimezone().tzname()},
                           "checks": checks, "telegram": telegram, "jobs": jobs,
                           "limitations": notices + ["마지막 성공 기록만으로 현재 실행 중·최근 실패·알림 도착 여부를 확정하지 않습니다.",
                                                       "이 화면은 조회 전용입니다. 업무 실행·설정 변경은 터미널의 ilson chat에서 진행하세요."]})

    def report_candidates(self):
        rows, limited, visited = [], False, 0

        def scan(parts, depth):
            nonlocal limited, visited
            if depth > REPORT_DEPTH or visited >= SCAN_LIMIT:
                limited = True
                return
            descriptor = None
            try:
                descriptor = self.files.open_dir(parts)
                with os.scandir(descriptor) as entries:
                    names = []
                    for entry in entries:
                        visited += 1
                        if visited > SCAN_LIMIT:
                            limited = True
                            break
                        if not entry.name.startswith(".") and not entry.is_symlink():
                            names.append((entry.name, entry.is_dir(follow_symlinks=False), entry.is_file(follow_symlinks=False)))
                for name, directory, file in sorted(names):
                    relative = parts + (name,)
                    if directory:
                        scan(relative, depth + 1)
                    elif file and name.lower().endswith(".md"):
                        rows.append("/".join(relative))
            except FileNotFoundError:
                return
            except (OSError, Unreadable):
                limited = True
            finally:
                if descriptor is not None:
                    os.close(descriptor)
        scan(("vault", "reports"), 0)
        return rows, limited

    def report_index(self):
        self.telegram()  # 보고서에 실수로 포함된 저장 토큰도 응답 전에 숨긴다.
        candidates, limited = self.report_candidates()
        rows = []
        for relative in candidates:
            try:
                text, info = self.files.text(relative, REPORT_BYTES)
            except (FileNotFoundError, Unreadable):
                limited = True
                continue
            path = Path(relative)
            title = path.stem[:120]
            for line in text.splitlines()[:40]:
                if line.startswith("# ") and line[2:].strip():
                    title = line[2:].strip()[:120]
                    break
            category = {"briefing": "아침 브리핑", "weekly": "주간 보고", "pending": "승인 대기 초안"}.get(path.parts[2] if len(path.parts) > 3 else "", "업무 보고")
            identity = hmac.new(self.token.encode(), relative.encode(), hashlib.sha256).hexdigest()[:32]
            rows.append(({"id": identity, "title": title, "category": category, "updated_at": stamp(info.st_mtime), "size_bytes": info.st_size}, relative))
        rows.sort(key=lambda row: row[0]["updated_at"], reverse=True)
        if len(rows) > REPORT_LIMIT:
            limited = True
        return rows[:REPORT_LIMIT], limited

    def reports(self):
        rows, limited = self.report_index()
        return self.redact({"reports": [row for row, _ in rows], "limited": limited, "limit": REPORT_LIMIT,
                            "notice": "일부 문서가 개수·깊이·파일 크기 제한 또는 읽기 문제로 표시되지 않을 수 있습니다." if limited else "보고서는 이 Box에 저장된 문서만 보여줍니다."})

    def report(self, identity):
        if not re.fullmatch(r"[a-f0-9]{32}", identity):
            raise AdminError("보고서를 찾을 수 없습니다.", 404)
        rows, _ = self.report_index()
        for metadata, relative in rows:
            if hmac.compare_digest(metadata["id"], identity):
                try:
                    text, _ = self.files.text(relative, REPORT_BYTES)
                except (FileNotFoundError, Unreadable):
                    raise AdminError("보고서를 읽지 못했습니다. 목록을 새로 확인해주세요.", 404) from None
                return self.redact({**metadata, "text": text, "truncated": False})
        raise AdminError("보고서를 찾을 수 없습니다.", 404)

    def login(self, token):
        now = self.clock()
        with self.session_lock:
            minute, count = self.attempts.get("login", (now, 0))
            if now - minute >= 60:
                minute, count = now, 0
            if count >= 10:
                raise AdminError("연결 시도가 많습니다. 잠시 후 ilson open으로 다시 열어주세요.", 429)
            self.attempts["login"] = (minute, count + 1)
            if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,160}", token) or not hmac.compare_digest(token, self.token):
                raise AdminError("연결을 확인하지 못했습니다. ilson open으로 다시 열어주세요.", 401)
            self.sessions = {key: expiry for key, expiry in self.sessions.items() if expiry > now}
            if len(self.sessions) >= 64:
                raise AdminError("열린 관리자 창이 많습니다. 잠시 후 다시 연결해주세요.", 429)
            session = secrets.token_urlsafe(32)
            self.sessions[hashlib.sha256(session.encode()).hexdigest()] = now + SESSION_SECONDS
            return session

    def authenticated(self, session):
        if not isinstance(session, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,100}", session):
            return False
        key = hashlib.sha256(session.encode()).hexdigest()
        with self.session_lock:
            expiry = self.sessions.get(key, 0)
            if expiry <= self.clock():
                self.sessions.pop(key, None)
                return False
            return True

    def logout(self, session):
        if isinstance(session, str):
            with self.session_lock:
                self.sessions.pop(hashlib.sha256(session.encode()).hexdigest(), None)


def parse_json(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError()
            result[key] = value
        return result
    def constant(_):
        raise ValueError()
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except (ValueError, UnicodeError, RecursionError):
        raise AdminError("요청 형식을 확인해주세요.") from None


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def server_bind(self):
        # 2026-10-06 실측: HTTPServer의 역방향 DNS가 macOS에서 약 35초 대기했다.
        # 고정 loopback 주소는 이름 조회가 필요 없다. 실제 바인딩 포트만 보존한다.
        TCPServer.server_bind(self)
        self.server_name = "localhost"
        self.server_port = self.server_address[1]

    def __init__(self, box, port):
        self.box = box
        super().__init__(("127.0.0.1", port), Handler)
        self.hosts = {"127.0.0.1:" + str(self.server_port), "localhost:" + str(self.server_port)}
        self.origins = {"http://" + host for host in self.hosts}

    def handle_error(self, request, client_address):
        print("일손 관리자: 요청 처리를 완료하지 못했습니다.", file=sys.stderr)


class Handler(BaseHTTPRequestHandler):
    server_version = "IlsonBoxAdmin"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *_):
        pass

    def reply(self, status, value, content_type="application/json; charset=utf-8", cookie=None):
        raw = json.dumps(self.server.box.redact(value), ensure_ascii=False).encode() if isinstance(value, dict) else value
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        if status == 429:
            self.send_header("Retry-After", "60")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    def session(self):
        try:
            jar = SimpleCookie()
            jar.load(self.headers.get("Cookie", ""))
            morsel = jar.get(self.server.box.cookie_name)
            return morsel.value if morsel else ""
        except Exception:
            return ""

    def cookie(self, value, age):
        return f"{self.server.box.cookie_name}={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={age}"

    def boundary(self):
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0].lower() not in self.server.hosts:
            raise AdminError("이 기기의 일손 관리자 주소에서 접속해주세요.", 403)
        origins = self.headers.get_all("Origin", [])
        if len(origins) > 1 or (origins and origins[0] not in self.server.origins):
            raise AdminError("요청 출처를 확인할 수 없습니다.", 403)
        if self.command == "POST" and (not origins or self.headers.get("Sec-Fetch-Site") == "cross-site"):
            raise AdminError("일손 관리자 화면에서 다시 연결해주세요.", 403)

    def route(self):
        try:
            parsed = urlsplit(self.path)
        except ValueError:
            raise AdminError("요청 주소를 확인해주세요.") from None
        if parsed.query or parsed.fragment:
            raise AdminError("요청 주소를 확인해주세요.", 404)
        return unquote(parsed.path)

    def require_session(self):
        if not self.server.box.authenticated(self.session()):
            raise AdminError("연결이 필요합니다. 터미널에서 ilson open으로 열어주세요.", 401)

    def body(self):
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise AdminError("JSON 요청이 필요합니다.", 415)
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,6}", lengths[0]):
            raise AdminError("요청 길이를 확인해주세요.")
        size = int(lengths[0])
        if not 0 < size <= BODY_LIMIT:
            raise AdminError("요청 크기를 확인해주세요.", 413)
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise AdminError("요청이 완료되지 않았습니다.")
        return parse_json(raw)

    def guarded(self, callback):
        try:
            self.boundary()
            callback()
        except AdminError as exc:
            self.reply(exc.status, {"error": str(exc)})
        except (OSError, Unreadable, ValueError):
            print("일손 관리자: 파일·상태 조회를 완료하지 못했습니다.", file=sys.stderr)
            self.reply(503, {"error": "상태를 확인하지 못했습니다. 잠시 후 다시 조회해주세요."})

    def do_GET(self):
        self.guarded(self.get)

    def do_HEAD(self):
        self.do_GET()

    def get(self):
        path = self.route()
        if path in {"/api/health", "/health"}:
            return self.reply(200, {"service": SERVICE, "instance": self.server.box.instance})
        if path in STATIC:
            relative, kind = STATIC[path]
            try:
                raw, _ = self.server.box.files.read(relative, 1024 * 1024)
            except (FileNotFoundError, Unreadable):
                raise AdminError("관리자 화면 파일이 없습니다. ilson setup으로 갱신해주세요.", 404) from None
            return self.reply(200, raw, kind)
        self.require_session()
        if path == "/api/session":
            return self.reply(200, {"authenticated": True})
        if path == "/api/overview":
            return self.reply(200, self.server.box.overview())
        if path == "/api/reports":
            return self.reply(200, self.server.box.reports())
        if path.startswith("/api/reports/"):
            return self.reply(200, self.server.box.report(path.removeprefix("/api/reports/")))
        raise AdminError("페이지를 찾을 수 없습니다.", 404)

    def do_POST(self):
        self.guarded(self.post)

    def post(self):
        path = self.route()
        if path == "/api/session":
            data = self.body()
            if set(data) != {"token"}:
                raise AdminError("연결 요청 형식을 확인해주세요.")
            session = self.server.box.login(data["token"])
            return self.reply(200, {"ok": True}, cookie=self.cookie(session, SESSION_SECONDS))
        if path == "/api/logout":
            self.require_session()
            if self.body():
                raise AdminError("로그아웃 요청 형식을 확인해주세요.")
            self.server.box.logout(self.session())
            return self.reply(200, {"ok": True}, cookie=self.cookie("", 0))
        raise AdminError("지원하지 않는 요청입니다.", 404)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    try:
        if not args.home.is_absolute() or not 1 <= args.port <= 65535:
            raise AdminError("Box 절대 경로와 포트를 확인해주세요.")
        server = Server(Box(args.home), args.port)
    except (AdminError, OSError, ValueError):
        parser.exit(1, "일손 관리자 시작 실패: 연결 설정·파일 권한·사용 중인 포트를 확인해주세요.\n")
    print(f"일손 관리자: http://127.0.0.1:{server.server_port}/ · 이 기기에서만 접속", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
