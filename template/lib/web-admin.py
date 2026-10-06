# coding: utf-8
"""일손 Box의 로컬 관리 화면만 설치·열기·점검·중지한다."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import secrets
import socket
import stat
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener


LABEL = "com.ilson.admin"
SERVICE = "ilson-box-admin"
DEFAULT_PORT = 18794
SECRET_FORMAT = re.compile(r"[A-Za-z0-9_-]{32,128}\Z")


class AdminError(ValueError):
    pass


class HealthPending(AdminError):
    """프로세스 시작 중의 일시적인 연결 시간 초과. 다른 서비스 응답과 구별한다."""
    pass


def run(args, *, timeout=15, input=None):
    # 호출 인자에는 token을 넣지 않는다. 오류 원문도 사용자 화면에 출력하지 않는다.
    try:
        return subprocess.run(args, input=input, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise AdminError("관리 웹 실행 도구가 응답하지 않았습니다. 다시 시도해 주세요.") from None


def regular(path):
    """민감 파일은 심볼릭 링크·하드 링크를 통해 다른 파일과 공유하지 않는다."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise AdminError("관리 웹 설정 파일 경로를 확인해 주세요. 기존 설정은 변경하지 않았습니다.")
    return True


def directory(path):
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise AdminError("관리 웹 설정 폴더 경로를 확인해 주세요.")


def paths(home):
    if not home.is_absolute() or any(ord(c) < 32 for c in str(home)):
        raise AdminError("Box 폴더는 올바른 절대 경로여야 합니다.")
    directory(home)
    directory(home / "state")
    private = home / "state/web-admin"
    directory(private)
    return private


def check_mutation(home):
    paths(home)
    if (home / "state/sandbox").exists():
        raise AdminError("샌드박스에서는 관리 웹 설치·열기·중지를 실행하지 않습니다.")
    if sys.platform != "darwin":
        raise AdminError("관리 웹 자동 실행은 macOS에서 지원합니다.")


def read_text(path):
    if not regular(path):
        return None
    if path.stat().st_size > 65536:
        raise AdminError("관리 웹 설정 파일 크기를 확인해 주세요.")
    return path.read_text(encoding="utf-8")


def read_config(home):
    raw = read_text(paths(home) / "config.json")
    if raw is None:
        return {}
    try:
        config = json.loads(raw)
    except ValueError:
        raise AdminError("관리 웹 설정을 읽지 못했습니다. 기존 설정을 보존했습니다.") from None
    if not isinstance(config, dict) or config.get("version") != 1 or not valid_port(config.get("port")):
        raise AdminError("관리 웹 설정 형식이 올바르지 않습니다. 기존 설정을 보존했습니다.")
    return config


def valid_port(value):
    return type(value) is int and 1024 <= value <= 65535


def selected_port(config, override):
    port = override if override is not None else config.get("port", DEFAULT_PORT)
    if not valid_port(port):
        raise AdminError("관리 웹 포트는 1024~65535 사이의 숫자여야 합니다.")
    return port


def atomic_write(path, content):
    regular(path)
    descriptor, temporary = tempfile.mkstemp(prefix=".admin-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def snapshot_protected(home):
    # 정기 snapshot이 state/를 수집한다. 비밀을 만들기 전에 제외와 미추적을 확인한다.
    if not (home / ".git").exists():
        raise AdminError("먼저 ilson setup 으로 Box의 기록 보호 구성을 준비해 주세요.")
    tracked = run(["git", "-C", str(home), "ls-files", "--", "state/web-admin"])
    if tracked.returncode != 0 or tracked.stdout.strip():
        raise AdminError("관리 웹 설정의 기록 보호 상태를 확인하지 못했습니다. 설정은 보존했습니다.")
    ignored = run(["git", "-C", str(home), "check-ignore", "--quiet", "state/web-admin/token"])
    if ignored.returncode != 0:
        raise AdminError("관리 웹 비밀 설정의 기록 제외가 필요합니다. ilson setup 을 다시 실행해 주세요.")


def prepare_secrets(home):
    snapshot_protected(home)
    private = paths(home)
    private.mkdir(mode=0o700, parents=True, exist_ok=True)
    private.chmod(0o700)
    changed = False
    for name, length in (("token", 32), ("instance", 24)):
        path = private / name
        value = read_text(path)
        if value is None:
            atomic_write(path, secrets.token_urlsafe(length).encode())
            changed = True
        elif not SECRET_FORMAT.fullmatch(value):
            raise AdminError("관리 웹 연결 정보가 손상되었습니다. 기존 설정을 보존했습니다.")
        else:
            path.chmod(0o600)
    return changed


def identity(home):
    value = read_text(paths(home) / "instance")
    if value is None or not SECRET_FORMAT.fullmatch(value):
        return None
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_):
        raise AdminError("관리 웹 응답 주소가 다릅니다. 다른 서비스를 변경하지 않았습니다.")


def health(port):
    """없음과 다른 프로그램의 포트 점유를 구분한다. 프록시는 사용하지 않는다."""
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(
                f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
            raw = response.read(4097)
        if len(raw) > 4096:
            raise ValueError()
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except AdminError:
        raise
    except HTTPError:
        raise AdminError("관리 웹 포트를 다른 프로그램이 사용 중입니다. 기존 프로그램은 변경하지 않았습니다.") from None
    except (URLError, OSError):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                pass
        except ConnectionRefusedError:
            return None
        except TimeoutError:
            raise HealthPending("관리 웹 포트의 응답을 기다리고 있습니다.") from None
        except OSError:
            raise AdminError("관리 웹 포트 상태를 확인하지 못했습니다.") from None
        raise AdminError("관리 웹 포트를 다른 프로그램이 사용 중입니다. 기존 프로그램은 변경하지 않았습니다.") from None
    except ValueError:
        raise AdminError("관리 웹 응답이 올바르지 않습니다. 다른 프로그램은 변경하지 않았습니다.") from None


def ours(response, instance):
    if response is None:
        return False
    if instance is None or response.get("service") != SERVICE or response.get("instance") != instance:
        raise AdminError("이 포트는 다른 Box 또는 프로그램이 사용 중입니다. 해당 서비스는 변경하지 않았습니다.")
    return True


def domain():
    return f"gui/{os.getuid()}"


def plist_path():
    return Path.home() / "Library/LaunchAgents" / (LABEL + ".plist")


def owns_arguments(arguments, home):
    if not isinstance(arguments, list) or len(arguments) != 6:
        return False
    return (arguments[1] == str(home / "lib/web-admin-server.py") and arguments[2] == "--home"
            and arguments[3] == str(home) and arguments[4] == "--port")


def existing_plist(home):
    path = plist_path()
    if not regular(path):
        return None
    try:
        if path.stat().st_size > 65536:
            raise ValueError()
        with path.open("rb") as file:
            value = plistlib.load(file)
    except (ValueError, plistlib.InvalidFileException):
        raise AdminError("기존 관리 웹 실행 설정을 읽지 못했습니다. 덮어쓰지 않았습니다.") from None
    if not isinstance(value, dict) or value.get("Label") != LABEL or not owns_arguments(value.get("ProgramArguments"), home):
        raise AdminError("다른 Box가 관리 웹 자동 실행을 사용 중입니다. 기존 설정을 변경하지 않았습니다.")
    return value


def loaded(home):
    result = run(["/bin/launchctl", "print", domain() + "/" + LABEL])
    if result.returncode != 0:
        if "could not find service" in (result.stdout + result.stderr).lower():
            return False
        raise AdminError("관리 웹 자동 실행 상태를 확인하지 못했습니다.")
    match = re.search(r"\barguments\s*=\s*\{\s*\n(.*?)\n\s*\}", result.stdout, re.S)
    arguments = [line.strip().strip('"') for line in match.group(1).splitlines()] if match else []
    if not owns_arguments(arguments, home):
        raise AdminError("다른 Box가 관리 웹 자동 실행을 사용 중입니다. 해당 서비스는 변경하지 않았습니다.")
    return True


def source_digest(home):
    server = home / "lib/web-admin-server.py"
    if not regular(server):
        raise AdminError("관리 웹 실행 파일이 없습니다. ilson setup 을 다시 실행해 주세요.")
    digest = hashlib.sha256()
    sources = [server]
    web = home / "web"
    directory(web)
    if web.exists():
        sources += sorted(path for path in web.rglob("*") if path.is_file())
    for path in sources:
        regular(path)
        digest.update(str(path.relative_to(home)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def build_plist(home, port):
    private = paths(home)
    return {
        "Label": LABEL,
        "ProgramArguments": [str(Path(sys.executable).resolve()), str(home / "lib/web-admin-server.py"),
                             "--home", str(home), "--port", str(port)],
        "WorkingDirectory": str(home), "RunAtLoad": True, "KeepAlive": True,
        "EnvironmentVariables": {"PATH": str(Path.home() / ".local/bin") + ":/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
        "StandardOutPath": str(private / "stdout.log"), "StandardErrorPath": str(private / "stderr.log"),
        "Umask": 0o077,
    }


def protected_log(path):
    regular(path)
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)


def launch(args):
    if run(["/bin/launchctl", *args]).returncode != 0:
        raise AdminError("관리 웹 자동 실행을 변경하지 못했습니다. 상태를 확인한 뒤 다시 실행해 주세요.")


def await_health(port, instance, *, wait=12):
    deadline = time.monotonic() + wait
    while True:
        try:
            if ours(health(port), instance):
                return
        except HealthPending:
            # 새 프로세스가 준비되는 잠깐의 timeout만 재시도한다.
            # 다른 앱/instance/잘못된 HTTP 응답은 여전히 즉시 중단한다.
            pass
        if time.monotonic() >= deadline:
            raise AdminError("관리 웹이 아직 응답하지 않습니다. ilson admin status 로 확인해 주세요.")
        time.sleep(0.3)


def install(home, port_override=None):
    check_mutation(home)
    snapshot_protected(home)
    private = paths(home)
    private.mkdir(mode=0o700, parents=True, exist_ok=True)
    private.chmod(0o700)
    lock_path = private / "launcher.lock"
    regular(lock_path)
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "a") as lock:
        os.fchmod(lock.fileno(), 0o600)
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise AdminError("다른 창에서 관리 웹을 준비하고 있습니다. 잠시 뒤 다시 시도해 주세요.") from None
        config = read_config(home)
        port = selected_port(config, port_override)
        old_plist = existing_plist(home)
        is_loaded = loaded(home)
        ready = ours(health(port), identity(home))
        if ready and not is_loaded:
            raise AdminError("자동 실행 밖에서 관리 웹이 실행 중입니다. 기존 실행을 먼저 확인해 주세요.")
        digest = source_digest(home)
        secrets_changed = prepare_secrets(home)
        desired = build_plist(home, port)
        changed = old_plist != desired or config.get("source_digest") != digest or secrets_changed
        regular(private / "enabled")
        for name in ("stdout.log", "stderr.log"):
            protected_log(private / name)
        path = plist_path()
        directory(path.parent)
        path.parent.mkdir(parents=True, exist_ok=True)
        if is_loaded and changed:
            launch(["bootout", domain() + "/" + LABEL])
            is_loaded = False
        if old_plist != desired:
            atomic_write(path, plistlib.dumps(desired))
        if not is_loaded:
            launch(["bootstrap", domain(), str(path)])
        elif not ready:
            launch(["kickstart", "-k", domain() + "/" + LABEL])
        await_health(port, identity(home))
        updated = dict(config, version=1, port=port, source_digest=digest)
        if updated != config:
            atomic_write(private / "config.json", json.dumps(updated, ensure_ascii=False, indent=2).encode())
        # 자동 업데이트는 이 명시적 활성 표시가 있을 때만 관리 웹을 재시작한다.
        # health를 확인하기 전에는 새 설치를 활성화 완료로 기록하지 않는다.
        atomic_write(private / "enabled", b"1\n")
    return port


def open_browser(home, port):
    if not ours(health(port), identity(home)):
        raise AdminError("관리 웹의 연결을 확인하지 못해 화면을 열지 않았습니다.")
    token = read_text(paths(home) / "token")
    if token is None or not SECRET_FORMAT.fullmatch(token):
        raise AdminError("관리 웹 연결 정보를 확인하지 못했습니다.")
    # macOS open/webbrowser는 URL을 프로세스 인자로 노출한다. AppleScript stdin만 사용한다.
    url = f"http://127.0.0.1:{port}/#token={token}"
    result = run(["/usr/bin/osascript", "-"], input='open location "' + url + '"\n')
    if result.returncode != 0:
        raise AdminError("관리 웹은 준비됐지만 브라우저를 열지 못했습니다. 같은 명령을 다시 실행해 주세요.")


def status(home, port_override=None):
    paths(home)
    if (home / "state/sandbox").exists():
        print("샌드박스입니다. 실제 관리 웹 상태는 확인하지 않습니다.")
        return 1
    config = read_config(home)
    port = selected_port(config, port_override)
    if identity(home) is None:
        print("관리 웹이 아직 설정되지 않았습니다. ilson open 으로 시작하세요.")
        return 1
    if ours(health(port), identity(home)):
        print(f"관리 웹이 실행 중입니다. 주소: http://127.0.0.1:{port}/")
        return 0
    print("관리 웹이 응답하지 않습니다. ilson open 으로 다시 시작하세요.")
    return 1


def stop(home):
    check_mutation(home)
    marker = paths(home) / "enabled"
    regular(marker)
    old_plist = existing_plist(home)
    is_loaded = loaded(home)
    config = read_config(home)
    fallback_port = int(old_plist["ProgramArguments"][-1]) if old_plist else DEFAULT_PORT
    port = selected_port(config, None) if config else fallback_port
    instance = identity(home)
    if not is_loaded and instance is not None and ours(health(port), instance):
        raise AdminError("자동 실행 밖에서 관리 웹이 실행 중입니다. 실행한 터미널에서 중지해 주세요.")
    if is_loaded:
        launch(["bootout", domain() + "/" + LABEL])
        # macOS bootout은 요청을 받은 뒤 실제 등록 해제가 잠시 늦을 수 있다.
        # 같은 Box의 서비스인지 계속 확인하면서 짧게 기다린다.
        deadline = time.monotonic() + 5
        while loaded(home):
            if time.monotonic() >= deadline:
                raise AdminError("관리 웹 중지를 확인하지 못했습니다.")
            time.sleep(0.1)
        if instance is not None:
            deadline = time.monotonic() + 3
            while ours(health(port), instance):
                if time.monotonic() >= deadline:
                    raise AdminError("관리 웹 프로세스의 중지를 확인하지 못했습니다.")
                time.sleep(0.1)
    if old_plist is not None:
        plist_path().unlink()
    if marker.exists():
        marker.unlink()
    print("관리 웹 자동 실행을 중지했습니다. 예약 업무는 계속 실행됩니다.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="일손 Box 로컬 관리 화면")
    parser.add_argument("command", choices=("install", "open", "status", "stop"))
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--port", type=int)
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            return status(args.home, args.port)
        if args.command == "stop":
            stop(args.home)
        else:
            port = install(args.home, args.port)
            if args.command == "open":
                open_browser(args.home, port)
                print("일손 관리 화면을 브라우저에서 열었습니다.")
            else:
                print("일손 관리 웹 자동 실행을 준비하고 응답을 확인했습니다.")
        return 0
    except (AdminError, OSError, UnicodeError) as error:
        print(str(error) if isinstance(error, AdminError) else "관리 웹 설정을 처리하지 못했습니다. 기존 설정을 확인해 주세요.")
        return 1
    except KeyboardInterrupt:
        print("관리 웹 설정을 중단했습니다. ilson admin status 로 현재 상태를 확인하세요.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
