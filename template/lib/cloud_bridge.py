#!/usr/bin/env python3
"""ilson-box Student Cloud Runner Bridge.

Connects a student's local ilson-box to the ilson.work Supabase cloud backend
using Python standard library only (macOS Python 3.9+ compatible).

Security & Idempotency Contracts:
- Plaintext office codes are NEVER persisted to disk; only derived runner
  credentials live in ``$ILSON_HOME/state/cloud-runner.json`` (mode 0600).
- OAuth access tokens live strictly in local ``$ILSON_HOME/state/sns-tokens.json``
  (mode 0600) and are NEVER uploaded to Supabase.
- Heartbeat payloads send ONLY DB-allowlisted columns (``last_beat_at``,
  ``agent_version``, ``linked_accounts``) and ONLY the 4 allowlisted account
  keys (``platform``, ``username``, ``state``, ``expires_at``).
- Publishing acquires a non-blocking OS file lock (``fcntl.flock`` on POSIX,
  ``msvcrt.locking`` on Windows) and persists each ``approval_id`` to durable
  ``$ILSON_HOME/state/cloud-published.json`` BEFORE attempting cloud status
  writeback so retries/crashes never double-post.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
from typing import Any, Callable, Optional
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_SUPABASE_URL = "https://vouivhdenbqpcwdptpnj.supabase.co"
DEFAULT_SUPABASE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZvdWl2aGRlbmJxcGN3ZHB0cG5qIiwicm9sZSI6ImFub24iLC"
    "JpYXQiOjE3ODYyOTE4MzksImV4cCI6MjEwMTg2NzgzOX0."
    "tO0X6r0Qxdi1MsRlKr1pljwtT-PtsJxkLMjRyEp6Q7U"
)
AGENT_VERSION = "ilson-box-cloud-bridge/1.0"

# Exact protocol match with agents/_shared/tools/office_code.py
ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
LENGTH = 16
GROUP = 4
PREFIX = "ILSON"
PW_DOMAIN = "ilson-runner-pw-v1:"
_STRIP = re.compile(r"[^0-9A-Za-z]")

SAFE_LINKED_ACCOUNT_KEYS = frozenset({"platform", "username", "state", "expires_at"})
SAFE_BEAT_COLUMNS = frozenset({"last_beat_at", "agent_version", "linked_accounts"})
SUPPORTED_PLATFORMS = frozenset({"threads", "instagram"})
RUNNER_STATE_PUBLISH_KEY = "student_publish_log_v1"

HTTP_TIMEOUT_SEC = 30.0
MAX_RESPONSE_BYTES = 4 * 1024 * 1024

HttpSend = Callable[[str, str, dict[str, str], Optional[bytes], float], tuple[int, bytes]]
PublisherFn = Callable[..., str]


class CloudBridgeError(RuntimeError):
    """Operational error in the student cloud runner bridge."""


class OfficeCodeError(CloudBridgeError, ValueError):
    """Invalid office code format."""


# ── Office Code Helpers ───────────────────────────────────────────────────────


def normalize_office_code(raw: str) -> str:
    """Normalize a human-entered office code identically to office_code.normalize()."""
    if not isinstance(raw, str):
        raise OfficeCodeError("사무소 코드가 비어 있어요")
    s = _STRIP.sub("", raw).upper()
    if s.startswith(PREFIX):
        s = s[len(PREFIX):]
    if len(s) != LENGTH:
        raise OfficeCodeError(
            f"사무소 코드는 {LENGTH}글자예요 (지금 {len(s)}글자) — 다시 확인해 주세요"
        )
    bad = sorted(set(s) - set(ALPHABET))
    if bad:
        raise OfficeCodeError(
            f"사무소 코드에 없는 글자가 있어요: {' '.join(bad)} — 0·O, 1·I·L, U 는 쓰지 않아요"
        )
    return s


def derive_runner_password(raw: str) -> str:
    """Derive the runner account password identically to office_code.derive_password()."""
    normalized = normalize_office_code(raw)
    return hashlib.sha256((PW_DOMAIN + normalized).encode("utf-8")).hexdigest()


# ── Time Helpers ──────────────────────────────────────────────────────────────


def _coerce_utc(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _iso_utc(dt: datetime) -> str:
    return _coerce_utc(dt).isoformat().replace("+00:00", "Z")


def _parse_iso_datetime(value: Any) -> datetime | None:
    """Parse ISO-8601 / Postgres timestamptz strings reliably on Python 3.9+."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if len(raw) > 10 and raw[10] == " ":
        raw = raw[:10] + "T" + raw[11:]
    if raw[-1] in ("Z", "z"):
        raw = raw[:-1] + "+00:00"
    raw = re.sub(
        r"(\d{2}:\d{2}:\d{2})\.(\d+)",
        lambda m: f"{m.group(1)}.{m.group(2).ljust(6, '0')[:6]}",
        raw,
    )
    raw = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", raw)
    raw = re.sub(r"([+-]\d{2})$", r"\1:00", raw)
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ── Private Atomic File Store (0600 / Windows ACL, no symlinks or reparse points) ──

_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_BINARY = getattr(os, "O_BINARY", 0)
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def _state_dir(home: Path) -> Path:
    return Path(home) / "state"


def _runner_config_path(home: Path) -> Path:
    return _state_dir(home) / "cloud-runner.json"


def _token_vault_path(home: Path) -> Path:
    return _state_dir(home) / "sns-tokens.json"


def _published_log_path(home: Path) -> Path:
    return _state_dir(home) / "cloud-published.json"


def _publish_lock_path(home: Path) -> Path:
    return _state_dir(home) / "cloud-publish.lock"


def _is_sandbox(home: Path) -> bool:
    return (_state_dir(home) / "sandbox").exists()


def _is_link_or_reparse(path: Path) -> bool:
    """Return True if path is a symlink or (on Windows) a reparse point."""
    if path.is_symlink():
        return True
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    if os.name == "nt" and (getattr(info, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT):
        return True
    return False


def _assert_not_symlink(path: Path) -> None:
    """Reject symlinks and Windows reparse points on target and parent directories."""
    parent = path.parent
    if os.name == "nt":
        home_parent = parent.parent
        if home_parent != parent and str(home_parent) not in ("/var", "/tmp", "/etc"):
            if _is_link_or_reparse(home_parent):
                raise CloudBridgeError(
                    f"보안 오류: 홈 디렉터리가 심볼릭 링크 또는 리파스 포인트입니다 ({home_parent})"
                )
    if _is_link_or_reparse(parent):
        raise CloudBridgeError(f"보안 오류: 상태 디렉터리가 심볼릭 링크 또는 리파스 포인트입니다 ({parent})")
    if _is_link_or_reparse(path):
        raise CloudBridgeError(f"보안 오류: 민감 파일이 심볼릭 링크 또는 리파스 포인트입니다 ({path})")


def _load_windows_acl() -> Callable[..., Any] | None:
    """Import sibling license.windows_acl when available."""
    lib_dir = str(Path(__file__).resolve().parent)
    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)
    try:
        import license as _license_mod  # type: ignore[import-not-found]
    except ImportError:
        return None
    return getattr(_license_mod, "windows_acl", None)


def _windows_acl_claim_or_verify(path: Path, *, create: bool = False) -> None:
    """On Windows, claim or verify user-only owner/DACL via license.windows_acl (fail closed)."""
    if os.name != "nt":
        return
    acl_fn = _load_windows_acl()
    if acl_fn is None:
        raise CloudBridgeError(
            f"보안 오류: Windows 권한 검증 모듈(license.windows_acl)을 불러올 수 없습니다 ({path.name})"
        )
    try:
        acl_fn(path, create=create)
    except Exception as exc:
        raise CloudBridgeError(
            f"보안 오류: 개인 파일 권한 확인에 실패했습니다 ({path.name}): {exc}"
        ) from exc


def _ensure_private_state_dir(state_dir: Path) -> None:
    """Create shared state dir safely, rejecting links/reparse points.

    On Windows, per-file user-only DACLs are enforced on each private cloud state file
    rather than rewriting the shared `$ILSON_HOME/state` folder used by sibling helpers.
    """
    if os.name == "nt":
        home_parent = state_dir.parent
        if home_parent != state_dir and str(home_parent) not in ("/var", "/tmp", "/etc"):
            if _is_link_or_reparse(home_parent):
                raise CloudBridgeError(
                    f"보안 오류: 홈 디렉터리가 심볼릭 링크 또는 리파스 포인트입니다 ({home_parent})"
                )
    if _is_link_or_reparse(state_dir):
        raise CloudBridgeError(f"보안 오류: 상태 디렉터리가 심볼릭 링크 또는 리파스 포인트입니다 ({state_dir})")
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if _is_link_or_reparse(state_dir) or not state_dir.is_dir():
        raise CloudBridgeError(f"보안 오류: 상태 디렉터리가 올바르지 않습니다 ({state_dir})")


def _lock_held(exc: OSError) -> bool:
    """Return True if exc indicates another process holds the non-blocking file lock."""
    if os.name == "nt":
        held = {errno.EACCES, errno.EDEADLK, getattr(errno, "EDEADLOCK", errno.EDEADLK)}
    else:
        held = {errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES}
    return isinstance(exc, BlockingIOError) or getattr(exc, "errno", None) in held


def _open_lock_file(lock_path: Path) -> int:
    """Open or create the publish lock file safely across POSIX and Windows."""
    _ensure_private_state_dir(lock_path.parent)
    _assert_not_symlink(lock_path)
    if os.name == "nt":
        created = False
        try:
            fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT | os.O_EXCL | _O_BINARY, 0o600)
            created = True
        except FileExistsError:
            _assert_not_symlink(lock_path)
            _windows_acl_claim_or_verify(lock_path, create=False)
            fd = os.open(str(lock_path), os.O_RDWR | _O_BINARY)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise CloudBridgeError(f"보안 오류: 잠금 파일 형식이 올바르지 않습니다 ({lock_path})")
            if created:
                _windows_acl_claim_or_verify(lock_path, create=True)
        except Exception:
            os.close(fd)
            raise
        return fd

    try:
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT | _O_NOFOLLOW, 0o600)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise CloudBridgeError(f"보안 오류: 잠금 파일이 심볼릭 링크입니다 ({lock_path})") from exc
        raise
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise CloudBridgeError(f"보안 오류: 잠금 파일 형식이 올바르지 않습니다 ({lock_path})")
    except Exception:
        os.close(fd)
        raise
    return fd


def _acquire_nonblocking_lock(fd: int) -> None:
    """Acquire an exclusive non-blocking OS lock on fd."""
    if os.name == "nt":
        import msvcrt
        if os.fstat(fd).st_size < 1:
            os.write(fd, b"0")
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _release_lock(fd: int) -> None:
    """Release an OS lock acquired by _acquire_nonblocking_lock."""
    if os.name == "nt":
        import msvcrt
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        import fcntl
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass


def _write_private_json(path: Path, data: Any) -> None:
    """Atomically write JSON with 0o600 / Windows ACL permissions, rejecting links."""
    path = Path(path)
    _assert_not_symlink(path)
    _ensure_private_state_dir(path.parent)
    _assert_not_symlink(path)

    payload = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    tmp_name = f".{path.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp"
    tmp_path = path.parent / tmp_name

    fd = os.open(str(tmp_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW | _O_BINARY, 0o600)
    try:
        if os.name == "nt":
            _windows_acl_claim_or_verify(tmp_path, create=True)
        elif hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        view = memoryview(payload)
        written = 0
        while written < len(payload):
            n = os.write(fd, view[written:])
            if n <= 0:
                raise OSError("short write")
            written += n
        os.fsync(fd)
    except Exception:
        try:
            os.close(fd)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise
    os.close(fd)

    try:
        _assert_not_symlink(path)
        os.replace(str(tmp_path), str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _read_private_json(path: Path, default: Any = None) -> Any:
    """Read JSON from a private state file with O_NOFOLLOW / Windows ACL checks."""
    path = Path(path)
    _assert_not_symlink(path)
    if os.name == "nt":
        try:
            path.lstat()
        except FileNotFoundError:
            return default
        _assert_not_symlink(path)
        _windows_acl_claim_or_verify(path, create=False)
    try:
        fd = os.open(str(path), os.O_RDONLY | _O_NOFOLLOW | _O_BINARY)
    except FileNotFoundError:
        return default
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise CloudBridgeError(f"보안 오류: 민감 파일이 심볼릭 링크입니다 ({path})") from exc
        raise CloudBridgeError(f"상태 파일을 읽을 수 없습니다 ({path.name}): {exc}") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise CloudBridgeError(f"보안 오류: 민감 파일 형식이 올바르지 않습니다 ({path})")
        if os.name != "nt" and (info.st_uid != os.getuid() or (info.st_mode & 0o077)):
            raise CloudBridgeError(f"보안 오류: 민감 파일 소유자·권한이 올바르지 않습니다 ({path.name})")
        with os.fdopen(fd, "r", encoding="utf-8") as fh:
            fd = -1
            return json.load(fh)
    except CloudBridgeError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise CloudBridgeError(f"상태 파일을 읽을 수 없습니다 ({path.name}): {exc}") from exc
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass


def _load_runner_config(home: Path) -> dict[str, Any]:
    cfg = _read_private_json(_runner_config_path(home), default=None)
    if not isinstance(cfg, dict):
        raise CloudBridgeError(
            "클라우드 페어링 정보가 없습니다. 먼저 `ilson cloud pair --code <사무소코드>`를 실행해 주세요."
        )
    for key in ("company_id", "runner_id", "email", "derived_password", "supabase_url", "anon_key"):
        if not str(cfg.get(key) or "").strip():
            raise CloudBridgeError(
                f"클라우드 페어링 설정이 불완전합니다 ({key} 누락). 다시 페어링해 주세요."
            )
    return cfg


# ── HTTP Layer (stdlib only, injectable for tests) ────────────────────────────


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _is_allowed_http_url(parsed: urllib.parse.SplitResult) -> bool:
    if not parsed.netloc or not parsed.hostname or parsed.username or parsed.password:
        return False
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and parsed.hostname.lower() in _LOOPBACK_HOSTS


def _resolve_endpoints(
    supabase_url: str | None = None,
    anon_key: str | None = None,
) -> tuple[str, str]:
    url = (
        supabase_url
        or os.environ.get("ILSON_CLOUD_URL")
        or DEFAULT_SUPABASE_URL
    ).strip().rstrip("/")
    key = (
        anon_key
        or os.environ.get("ILSON_CLOUD_ANON_KEY")
        or DEFAULT_SUPABASE_ANON_KEY
    ).strip()
    if not url or not key:
        raise CloudBridgeError("클라우드 주소 또는 anon 키가 비어 있습니다.")
    parsed = urllib.parse.urlsplit(url)
    if parsed.username or parsed.password:
        raise CloudBridgeError("클라우드 주소에 인증 정보를 포함할 수 없습니다.")
    if not _is_allowed_http_url(parsed):
        raise CloudBridgeError(f"허용되지 않는 클라우드 주소입니다: {url}")
    return url, key


def _default_http_send(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout: float = HTTP_TIMEOUT_SEC,
) -> tuple[int, bytes]:
    parsed = urllib.parse.urlsplit(url)
    if not _is_allowed_http_url(parsed):
        raise CloudBridgeError("허용되지 않는 요청 주소입니다.")
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        resp = opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as err:
        try:
            raw = err.read(MAX_RESPONSE_BYTES + 1)
        finally:
            err.close()
        if len(raw) > MAX_RESPONSE_BYTES:
            raise CloudBridgeError("클라우드 오류 응답이 너무 큽니다.") from err
        return int(err.code), raw
    except urllib.error.URLError as err:
        raise CloudBridgeError(f"클라우드 연결에 실패했습니다: {err.reason}") from err

    with resp:
        raw = resp.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise CloudBridgeError("클라우드 응답 크기가 제한을 초과했습니다.")
        return int(resp.status), raw


def _http_json(
    http_send: HttpSend | None,
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    payload: Any = None,
    timeout: float = HTTP_TIMEOUT_SEC,
) -> tuple[int, Any]:
    sender = http_send or _default_http_send
    req_headers = dict(headers)
    body: bytes | None = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    req_headers.setdefault("Accept", "application/json")
    status, raw = sender(method, url, req_headers, body, timeout)
    if not raw:
        return status, None
    try:
        return status, json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return status, raw.decode("utf-8", errors="replace")[:300]


def _auth_headers(anon_key: str, jwt: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "apikey": anon_key,
        "Authorization": f"Bearer {jwt}",
        "Accept": "application/json",
    }
    if extra:
        headers.update(extra)
    return headers


# ── Core Operations ───────────────────────────────────────────────────────────


def authenticate(cfg: dict[str, Any], *, http_send: HttpSend | None = None) -> str:
    """Sign in via Supabase password grant and return an in-memory JWT."""
    base_url = str(cfg["supabase_url"]).rstrip("/")
    anon_key = str(cfg["anon_key"])
    url = f"{base_url}/auth/v1/token?grant_type=password"
    status, data = _http_json(
        http_send,
        "POST",
        url,
        headers={"apikey": anon_key, "Content-Type": "application/json"},
        payload={"email": cfg["email"], "password": cfg["derived_password"]},
    )
    if status >= 400 or not isinstance(data, dict) or not data.get("access_token"):
        raise CloudBridgeError(
            f"클라우드 러너 인증에 실패했습니다 (HTTP {status}). 사무소 코드를 다시 페어링해 주세요."
        )
    return str(data["access_token"])


def build_safe_linked_accounts(
    vault_data: Any,
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Project local token vault into the 4 DB-allowlisted non-secret keys only."""
    current = _coerce_utc(now)
    if not isinstance(vault_data, dict):
        return []
    accounts = vault_data.get("accounts")
    if not isinstance(accounts, dict):
        return []

    safe_list: list[dict[str, Any]] = []
    for key in sorted(accounts.keys()):
        rec = accounts.get(key)
        if not isinstance(rec, dict):
            continue
        platform = str(rec.get("platform") or "").strip().lower()
        username = str(rec.get("username") or "").strip()
        if not platform or not username:
            continue
        expires_raw = rec.get("expires_at")
        expires_str = str(expires_raw).strip() if expires_raw is not None else ""
        expires_dt = _parse_iso_datetime(expires_str) if expires_str else None
        has_token = bool(str(rec.get("access_token") or "").strip())
        if not has_token or (expires_str and (expires_dt is None or expires_dt <= current)):
            state = "expired"
        else:
            state = "ok"
        entry: dict[str, Any] = {
            "platform": platform,
            "username": username,
            "state": state,
            "expires_at": str(expires_raw) if expires_raw else None,
        }
        # Belt-and-suspenders guard against schema drift
        assert set(entry.keys()) == SAFE_LINKED_ACCOUNT_KEYS
        safe_list.append(entry)
    return safe_list


def send_heartbeat(
    home: Path | str,
    cfg: dict[str, Any],
    jwt: str,
    *,
    agent_version: str = AGENT_VERSION,
    http_send: HttpSend | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Send runner heartbeat using ONLY the 3 DB-allowlisted beat columns."""
    home_path = Path(home)
    current = _coerce_utc(now)
    vault_path = _token_vault_path(home_path)
    vault_data = _read_private_json(vault_path, default={"accounts": {}})
    safe_accounts = build_safe_linked_accounts(vault_data, now=current)

    payload: dict[str, Any] = {
        "last_beat_at": _iso_utc(current),
        "agent_version": str(agent_version),
        "linked_accounts": safe_accounts,
    }
    assert set(payload.keys()) == SAFE_BEAT_COLUMNS

    base_url = str(cfg["supabase_url"]).rstrip("/")
    runner_id = urllib.parse.quote(str(cfg["runner_id"]), safe="")
    url = f"{base_url}/rest/v1/runner?id=eq.{runner_id}"
    status, _ = _http_json(
        http_send,
        "PATCH",
        url,
        headers=_auth_headers(cfg["anon_key"], jwt, {"Prefer": "return=minimal"}),
        payload=payload,
    )
    if status >= 400:
        raise CloudBridgeError(f"러너 하트비트 전송에 실패했습니다 (HTTP {status}).")
    return {
        "ok": True,
        "last_beat_at": payload["last_beat_at"],
        "agent_version": payload["agent_version"],
        "linked_accounts": safe_accounts,
    }


def pair_with_cloud(
    home: Path | str,
    code: str,
    *,
    supabase_url: str | None = None,
    anon_key: str | None = None,
    http_send: HttpSend | None = None,
    now: datetime | None = None,
    agent_version: str = AGENT_VERSION,
) -> dict[str, Any]:
    """Claim an office code, verify login, store 0600 credentials, and send first heartbeat."""
    home_path = Path(home)
    if _is_sandbox(home_path):
        raise CloudBridgeError("샌드박스 환경에서는 클라우드 페어링을 실행할 수 없습니다.")

    normalized = normalize_office_code(code)
    base_url, resolved_anon_key = _resolve_endpoints(supabase_url, anon_key)
    current = _coerce_utc(now)

    rpc_url = f"{base_url}/rest/v1/rpc/claim_office"
    status, data = _http_json(
        http_send,
        "POST",
        rpc_url,
        headers={
            "apikey": resolved_anon_key,
            "Authorization": f"Bearer {resolved_anon_key}",
            "Content-Type": "application/json",
        },
        payload={"code": normalized},
    )
    if status >= 400 or not isinstance(data, dict):
        raise CloudBridgeError(f"사무소 코드 확인 요청이 실패했습니다 (HTTP {status}).")

    if data.get("ok") is not True:
        reason = str(data.get("reason") or "unknown")
        if reason == "locked":
            raise CloudBridgeError(
                "사무소 코드 입력 실패가 많아 잠시 잠겼습니다. 15분 뒤에 다시 시도해 주세요."
            )
        if reason == "mismatch":
            raise CloudBridgeError(
                "사무소 코드가 일치하지 않습니다. 대시보드에 표시된 코드를 다시 확인해 주세요."
            )
        raise CloudBridgeError(f"사무소 코드 교환에 실패했습니다 ({reason}).")

    company_id = str(data.get("company_id") or "").strip()
    runner_id = str(data.get("runner_id") or "").strip()
    email = str(data.get("email") or "").strip()
    if not (company_id and runner_id and email):
        raise CloudBridgeError("서버가 불완전한 사무소 정보를 반환했습니다.")

    derived_password = derive_runner_password(normalized)
    paired_at = _iso_utc(current)
    cfg: dict[str, Any] = {
        "company_id": company_id,
        "runner_id": runner_id,
        "email": email,
        "derived_password": derived_password,
        "supabase_url": base_url,
        "anon_key": resolved_anon_key,
        "paired_at": paired_at,
    }

    # Verify derived credentials work before persisting
    jwt = authenticate(cfg, http_send=http_send)

    # Persist WITHOUT plaintext office code
    _write_private_json(_runner_config_path(home_path), cfg)

    # Immediately send initial heartbeat so ilson.work shows green online
    send_heartbeat(
        home_path,
        cfg,
        jwt,
        agent_version=agent_version,
        http_send=http_send,
        now=current,
    )

    return {
        "company_id": company_id,
        "runner_id": runner_id,
        "paired_at": paired_at,
    }


def claim_link_handoffs(
    home: Path | str,
    cfg: dict[str, Any],
    jwt: str,
    *,
    http_send: HttpSend | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Pull ready OAuth handoffs into local 0600 vault, then burn them in cloud."""
    home_path = Path(home)
    current = _coerce_utc(now)
    base_url = str(cfg["supabase_url"]).rstrip("/")
    cid = urllib.parse.quote(str(cfg["company_id"]), safe="")
    url = (
        f"{base_url}/rest/v1/link_handoff_live"
        f"?company_id=eq.{cid}"
        "&select=id,platform,state,access_token,user_id,username,token_expires,status"
    )
    status, rows = _http_json(
        http_send,
        "GET",
        url,
        headers=_auth_headers(cfg["anon_key"], jwt),
    )
    if status >= 400 or not isinstance(rows, list):
        raise CloudBridgeError(f"SNS 계정 연결 인계 조회에 실패했습니다 (HTTP {status}).")

    vault_path = _token_vault_path(home_path)
    vault = _read_private_json(vault_path, default={"accounts": {}})
    if not isinstance(vault, dict) or not isinstance(vault.get("accounts"), dict):
        vault = {"accounts": {}}

    claimed_accounts: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_status = str(row.get("status") or "ready").strip().lower()
        if row_status != "ready":
            continue
        token = str(row.get("access_token") or "").strip()
        handoff_id = str(row.get("id") or "").strip()
        platform = str(row.get("platform") or "").strip().lower()
        username = str(row.get("username") or "").strip()
        user_id = str(row.get("user_id") or "").strip()
        if not token or not handoff_id or not platform:
            continue

        account_key = f"{platform}:{username or user_id}"
        vault["accounts"][account_key] = {
            "platform": platform,
            "user_id": user_id,
            "username": username or user_id,
            "access_token": token,
            "expires_at": str(row.get("token_expires") or "") or None,
            "claimed_at": _iso_utc(current),
        }
        # Step 1: persist locally with 0600 atomic write BEFORE burning in cloud
        _write_private_json(vault_path, vault)

        # Step 2: immediately burn token in cloud via DB trigger link_handoff_burn_trg
        patch_url = (
            f"{base_url}/rest/v1/link_handoff?id=eq.{urllib.parse.quote(handoff_id, safe='')}"
        )
        p_status, _ = _http_json(
            http_send,
            "PATCH",
            patch_url,
            headers=_auth_headers(cfg["anon_key"], jwt, {"Prefer": "return=minimal"}),
            payload={"status": "claimed"},
        )
        if p_status >= 400:
            raise CloudBridgeError(
                f"인계 토큰을 로컬에 저장했지만 클라우드 소각에 실패했습니다 (HTTP {p_status})."
            )

        claimed_accounts.append({"platform": platform, "username": username or user_id})

    return {"claimed": len(claimed_accounts), "accounts": claimed_accounts}


def _sanitize_media_urls(media_urls: list[str] | None) -> list[str]:
    if not media_urls:
        return []
    cleaned: list[str] = []
    for item in media_urls:
        raw = str(item or "").strip()
        if not raw:
            continue
        parsed = urllib.parse.urlsplit(raw)
        if parsed.scheme != "https" or not parsed.netloc:
            raise CloudBridgeError(
                f"미디어 URL은 공개 https:// 주소만 허용됩니다 (http:// 및 로컬 경로 불가): {raw}"
            )
        if parsed.username or parsed.password:
            raise CloudBridgeError("미디어 URL에 인증 정보를 포함할 수 없습니다.")
        cleaned.append(raw)
    return cleaned


def submit_draft(
    home: Path | str,
    *,
    source_key: str,
    platform: str,
    account: str,
    body: str,
    title: str = "",
    media_urls: list[str] | None = None,
    scheduled_at: str | None = None,
    kind: str = "sns_post",
    http_send: HttpSend | None = None,
) -> dict[str, Any]:
    """Submit a pending approval draft to ilson.work (P-STAMP compliant: status='pending' ONLY)."""
    home_path = Path(home)
    if _is_sandbox(home_path):
        raise CloudBridgeError("샌드박스 환경에서는 클라우드 결재 초안을 올릴 수 없습니다.")

    clean_source_key = str(source_key or "").strip()
    if not clean_source_key:
        raise CloudBridgeError("source_key가 비어 있습니다.")

    cfg = _load_runner_config(home_path)
    jwt = authenticate(cfg, http_send=http_send)
    safe_media = _sanitize_media_urls(media_urls)

    payload: dict[str, Any] = {
        "title": str(title or ""),
        "body": str(body or ""),
        "media_urls": safe_media,
    }
    row: dict[str, Any] = {
        "company_id": cfg["company_id"],
        "source_key": clean_source_key,
        "kind": str(kind or "sns_post"),
        "status": "pending",  # P-STAMP invariant: runner can ONLY submit pending drafts
        "platform": str(platform or "").strip().lower() or None,
        "account": str(account or "").strip() or None,
        "payload": payload,
    }
    if scheduled_at:
        row["scheduled_at"] = str(scheduled_at).strip()

    base_url = str(cfg["supabase_url"]).rstrip("/")
    url = f"{base_url}/rest/v1/approval?on_conflict=company_id,source_key"
    status, data = _http_json(
        http_send,
        "POST",
        url,
        headers=_auth_headers(
            cfg["anon_key"],
            jwt,
            {"Prefer": "resolution=merge-duplicates,return=representation"},
        ),
        payload=row,
    )
    if status >= 400:
        raise CloudBridgeError(f"결재 초안 등록에 실패했습니다 (HTTP {status}).")

    approval_id = None
    if isinstance(data, list) and data and isinstance(data[0], dict):
        approval_id = data[0].get("id")
    elif isinstance(data, dict):
        approval_id = data.get("id")

    return {
        "ok": True,
        "approval_id": approval_id,
        "source_key": clean_source_key,
        "status": "pending",
    }


def _find_token_entry(
    vault: dict[str, Any],
    platform: str,
    account: str,
) -> dict[str, Any] | None:
    accounts = vault.get("accounts") if isinstance(vault, dict) else None
    if not isinstance(accounts, dict):
        return None
    plat = platform.strip().lower()
    acct = account.strip()
    acct_norm = acct.lstrip("@").lower()

    direct = accounts.get(f"{plat}:{acct}")
    if isinstance(direct, dict):
        return direct
    if acct_norm:
        direct_norm = accounts.get(f"{plat}:{acct_norm}")
        if isinstance(direct_norm, dict):
            return direct_norm
        for rec in accounts.values():
            if not isinstance(rec, dict):
                continue
            if str(rec.get("platform") or "").strip().lower() != plat:
                continue
            rec_user = str(rec.get("username") or "").strip().lstrip("@").lower()
            rec_uid = str(rec.get("user_id") or "").strip().lower()
            if acct_norm in (rec_user, rec_uid):
                return rec
        return None

    # Empty account: match only if exactly one account exists for that platform
    matches = [
        rec for rec in accounts.values()
        if isinstance(rec, dict) and str(rec.get("platform") or "").strip().lower() == plat
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def _extract_publish_content(payload: Any) -> tuple[str, list[Any]]:
    if not isinstance(payload, dict):
        return "", []
    text = str(
        payload.get("body")
        or payload.get("text")
        or payload.get("caption")
        or ""
    ).strip()
    media: list[Any] = []
    if isinstance(payload.get("slides"), list) and payload["slides"]:
        media = list(payload["slides"])
    elif isinstance(payload.get("media_urls"), list) and payload["media_urls"]:
        media = list(payload["media_urls"])
    else:
        for k in ("image_url", "video_url"):
            val = payload.get(k)
            if isinstance(val, str) and val.strip():
                media.append({"url": val.strip(), "kind": "video" if k == "video_url" else "image"})
    return text, media


def _infer_media_kind(item: Any) -> tuple[str, str]:
    if isinstance(item, dict):
        url = str(item.get("url") or "").strip()
        kind = str(item.get("kind") or "image").strip().lower()
        return url, ("video" if kind == "video" else "image")
    url = str(item or "").strip()
    lower = urllib.parse.urlsplit(url).path.lower()
    if lower.endswith((".mp4", ".mov", ".m4v", ".webm")):
        return url, "video"
    return url, "image"


def _default_publish(
    *,
    platform: str,
    account: str,
    user_id: str,
    token: str,
    text: str,
    media_urls: list[Any],
    approval: dict[str, Any],
) -> str:
    """Publish via existing template/lib/social/meta_publish.py."""
    lib_dir = str(Path(__file__).resolve().parent)
    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)
    from social import meta_publish  # type: ignore[import-not-found]

    if platform == "threads":
        if not media_urls:
            return meta_publish.publish_threads(token=token, user_id=user_id, text=text)
        if len(media_urls) == 1:
            url, kind = _infer_media_kind(media_urls[0])
            if kind == "image":
                return meta_publish.publish_threads(
                    token=token, user_id=user_id, text=text, image_url=url
                )
        slides = [
            {"url": u, "kind": k}
            for u, k in (_infer_media_kind(m) for m in media_urls)
        ]
        return meta_publish.publish_threads_media(
            token=token, user_id=user_id, text=text, slides=slides
        )

    if platform == "instagram":
        if not media_urls:
            raise CloudBridgeError("인스타그램 게시에는 최소 1개의 미디어 URL이 필요합니다.")
        if len(media_urls) == 1:
            url, kind = _infer_media_kind(media_urls[0])
            return meta_publish.publish_instagram(
                kind=kind, token=token, user_id=user_id, url=url, caption=text
            )
        slides = [
            {"url": u, "kind": k}
            for u, k in (_infer_media_kind(m) for m in media_urls)
        ]
        return meta_publish.publish_instagram_carousel(
            token=token, user_id=user_id, slides=slides, caption=text
        )

    raise CloudBridgeError(f"지원하지 않는 발행 플랫폼입니다: {platform}")


def _write_runner_state_publish_log(
    cfg: dict[str, Any],
    jwt: str,
    published_map: dict[str, Any],
    *,
    now: datetime,
    http_send: HttpSend | None = None,
) -> bool:
    base_url = str(cfg["supabase_url"]).rstrip("/")
    url = f"{base_url}/rest/v1/runner_state?on_conflict=company_id,key"
    row = {
        "company_id": cfg["company_id"],
        "key": RUNNER_STATE_PUBLISH_KEY,
        "data": {
            "updated_at": _iso_utc(now),
            "published": published_map,
        },
        "updated_at": _iso_utc(now),
    }
    try:
        status, _ = _http_json(
            http_send,
            "POST",
            url,
            headers=_auth_headers(
                cfg["anon_key"],
                jwt,
                {"Prefer": "resolution=merge-duplicates,return=minimal"},
            ),
            payload=row,
        )
        return status < 400
    except CloudBridgeError:
        return False


def dispatch_approved_publishes(
    home: Path | str,
    cfg: dict[str, Any],
    jwt: str,
    *,
    http_send: HttpSend | None = None,
    publisher: PublisherFn | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Fetch approved/queued SNS approvals and publish due items with strict idempotency."""
    home_path = Path(home)
    if _is_sandbox(home_path) and not dry_run:
        raise CloudBridgeError("샌드박스 환경에서는 실제 SNS 발행을 실행할 수 없습니다.")

    current = _coerce_utc(now)
    lock_fd: int | None = None
    lock_acquired = False
    if not dry_run:
        lock_fd = _open_lock_file(_publish_lock_path(home_path))
    try:
        if lock_fd is not None:
            try:
                _acquire_nonblocking_lock(lock_fd)
                lock_acquired = True
            except OSError as exc:
                if _lock_held(exc):
                    return {
                        "locked": True,
                        "dry_run": dry_run,
                        "published": [],
                        "would_publish": [],
                        "skipped": [],
                        "errors": [],
                    }
                raise

        base_url = str(cfg["supabase_url"]).rstrip("/")
        cid = urllib.parse.quote(str(cfg["company_id"]), safe="")
        url = (
            f"{base_url}/rest/v1/approval"
            f"?company_id=eq.{cid}"
            "&status=in.(approved,queued)"
            "&order=scheduled_at.asc.nullsfirst"
            "&limit=20"
        )
        status, rows = _http_json(
            http_send,
            "GET",
            url,
            headers=_auth_headers(cfg["anon_key"], jwt),
        )
        if status >= 400 or not isinstance(rows, list):
            raise CloudBridgeError(f"승인 결재 목록 조회에 실패했습니다 (HTTP {status}).")

        pub_log_path = _published_log_path(home_path)
        pub_log = _read_private_json(pub_log_path, default={"published": {}})
        if not isinstance(pub_log, dict) or not isinstance(pub_log.get("published"), dict):
            pub_log = {"published": {}}

        vault = _read_private_json(_token_vault_path(home_path), default={"accounts": {}})
        if not isinstance(vault, dict):
            vault = {"accounts": {}}

        publish_fn = publisher or _default_publish
        published_items: list[dict[str, Any]] = []
        would_publish_items: list[dict[str, Any]] = []
        skipped_items: list[dict[str, Any]] = []
        error_items: list[dict[str, Any]] = []

        for row in rows:
            if not isinstance(row, dict):
                continue
            approval_id = str(row.get("id") or "").strip()
            if not approval_id:
                continue

            if approval_id in pub_log["published"]:
                skipped_items.append({"approval_id": approval_id, "reason": "already_published"})
                continue

            sched_raw = row.get("scheduled_at")
            sched_str = str(sched_raw).strip() if sched_raw is not None else ""
            if sched_str:
                sched_dt = _parse_iso_datetime(sched_str)
                if sched_dt is None:
                    skipped_items.append(
                        {
                            "approval_id": approval_id,
                            "reason": "invalid_scheduled_at",
                            "scheduled_at": sched_str,
                        }
                    )
                    continue
                if sched_dt > current:
                    skipped_items.append(
                        {
                            "approval_id": approval_id,
                            "reason": "not_due_yet",
                            "scheduled_at": sched_str,
                        }
                    )
                    continue

            platform = str(row.get("platform") or "").strip().lower()
            account = str(row.get("account") or "").strip()
            if platform not in SUPPORTED_PLATFORMS:
                skipped_items.append(
                    {"approval_id": approval_id, "reason": "unsupported_platform", "platform": platform}
                )
                continue

            token_entry = _find_token_entry(vault, platform, account)
            if not token_entry or not str(token_entry.get("access_token") or "").strip():
                error_items.append(
                    {
                        "approval_id": approval_id,
                        "platform": platform,
                        "account": account,
                        "error": "연결된 계정 토큰이 로컬 금고에 없습니다.",
                    }
                )
                continue

            exp_raw = token_entry.get("expires_at")
            exp_str = str(exp_raw).strip() if exp_raw is not None else ""
            if exp_str:
                exp_dt = _parse_iso_datetime(exp_str)
                if exp_dt is None or exp_dt <= current:
                    error_items.append(
                        {
                            "approval_id": approval_id,
                            "platform": platform,
                            "account": account or str(token_entry.get("username") or ""),
                            "error": "계정 토큰이 만료되었거나 만료 시각을 확인할 수 없습니다. ilson.work에서 계정을 다시 연결해 주세요.",
                        }
                    )
                    continue

            text, media_urls = _extract_publish_content(row.get("payload"))
            resolved_account = account or str(token_entry.get("username") or "")

            if dry_run:
                would_publish_items.append(
                    {
                        "approval_id": approval_id,
                        "platform": platform,
                        "account": resolved_account,
                        "media_count": len(media_urls),
                    }
                )
                continue

            try:
                remote_id = str(
                    publish_fn(
                        platform=platform,
                        account=resolved_account,
                        user_id=str(token_entry.get("user_id") or ""),
                        token=str(token_entry["access_token"]),
                        text=text,
                        media_urls=media_urls,
                        approval=row,
                    )
                    or ""
                ).strip()
                if not remote_id:
                    raise CloudBridgeError("발행 응답에 게시물 ID가 없습니다.")
            except Exception as exc:  # noqa: BLE001 — isolate per-item publish errors
                # Sanitize error so token can never leak into logs/reports
                msg = str(exc)
                raw_token = str(token_entry.get("access_token") or "")
                if raw_token and raw_token in msg:
                    msg = msg.replace(raw_token, "[REDACTED]")
                error_items.append(
                    {
                        "approval_id": approval_id,
                        "platform": platform,
                        "account": resolved_account,
                        "error": msg[:240],
                    }
                )
                continue

            # CRITICAL: Persist durable idempotency log BEFORE attempting cloud writeback!
            record = {
                "published_at": _iso_utc(current),
                "platform": platform,
                "account": resolved_account,
                "remote_id": remote_id,
                "status": "published",
            }
            pub_log["published"][approval_id] = record
            _write_private_json(pub_log_path, pub_log)

            # Best-effort PATCH approval status (legacy P-STAMP trigger may return 403/400)
            cloud_status_updated = False
            try:
                patch_url = (
                    f"{base_url}/rest/v1/approval?id=eq.{urllib.parse.quote(approval_id, safe='')}"
                )
                p_status, _ = _http_json(
                    http_send,
                    "PATCH",
                    patch_url,
                    headers=_auth_headers(cfg["anon_key"], jwt, {"Prefer": "return=minimal"}),
                    payload={"status": "published"},
                )
                cloud_status_updated = p_status < 400
            except CloudBridgeError:
                cloud_status_updated = False

            # Always record execution summary to runner_state (student_publish_log_v1)
            runner_state_updated = _write_runner_state_publish_log(
                cfg,
                jwt,
                pub_log["published"],
                now=current,
                http_send=http_send,
            )

            published_items.append(
                {
                    "approval_id": approval_id,
                    "platform": platform,
                    "account": resolved_account,
                    "remote_id": remote_id,
                    "status": "published",
                    "cloud_status_updated": cloud_status_updated,
                    "runner_state_updated": runner_state_updated,
                }
            )

        return {
            "locked": False,
            "dry_run": dry_run,
            "published": published_items,
            "would_publish": would_publish_items,
            "skipped": skipped_items,
            "errors": error_items,
        }
    finally:
        if lock_fd is not None:
            if lock_acquired:
                _release_lock(lock_fd)
            os.close(lock_fd)


def sync_once(
    home: Path | str,
    *,
    dry_run: bool = False,
    http_send: HttpSend | None = None,
    publisher: PublisherFn | None = None,
    now: datetime | None = None,
    agent_version: str = AGENT_VERSION,
) -> dict[str, Any]:
    """Run one full sync cycle: authenticate -> claim handoffs -> heartbeat -> publish."""
    home_path = Path(home)
    if _is_sandbox(home_path) and not dry_run:
        raise CloudBridgeError("샌드박스 환경에서는 클라우드 동기화를 실행할 수 없습니다.")

    cfg = _load_runner_config(home_path)
    jwt = authenticate(cfg, http_send=http_send)
    if dry_run:
        handoffs: dict[str, Any] = {"claimed": 0, "accounts": [], "skipped_dry_run": True}
        heartbeat: dict[str, Any] = {"ok": True, "skipped_dry_run": True}
    else:
        handoffs = claim_link_handoffs(home_path, cfg, jwt, http_send=http_send, now=now)
        heartbeat = send_heartbeat(
            home_path,
            cfg,
            jwt,
            agent_version=agent_version,
            http_send=http_send,
            now=now,
        )
    publishes = dispatch_approved_publishes(
        home_path,
        cfg,
        jwt,
        http_send=http_send,
        publisher=publisher,
        now=now,
        dry_run=dry_run,
    )
    return {
        "ok": True,
        "handoffs": handoffs,
        "heartbeat": heartbeat,
        "publishes": publishes,
    }


def get_status(home: Path | str, *, now: datetime | None = None) -> dict[str, Any]:
    """Read-only local status of cloud pairing, linked accounts, and publish count."""
    home_path = Path(home)
    cfg = _read_private_json(_runner_config_path(home_path), default=None)
    vault = _read_private_json(_token_vault_path(home_path), default={"accounts": {}})
    pub_log = _read_private_json(_published_log_path(home_path), default={"published": {}})

    paired = isinstance(cfg, dict) and bool(cfg.get("company_id")) and bool(cfg.get("runner_id"))
    published_map = pub_log.get("published") if isinstance(pub_log, dict) else {}
    return {
        "paired": paired,
        "sandbox": _is_sandbox(home_path),
        "company_id": cfg.get("company_id") if paired else None,
        "runner_id": cfg.get("runner_id") if paired else None,
        "paired_at": cfg.get("paired_at") if paired else None,
        "supabase_url": cfg.get("supabase_url") if paired else None,
        "linked_accounts": build_safe_linked_accounts(vault, now=now),
        "published_count": len(published_map) if isinstance(published_map, dict) else 0,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────


def _default_home() -> str:
    return os.environ.get("ILSON_HOME") or str(Path.home() / "ilson")


def _build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--home", default=argparse.SUPPRESS, help="ILSON_HOME 경로")
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="JSON 출력")

    parser = argparse.ArgumentParser(
        prog="cloud_bridge.py",
        description="ilson-box 학생용 클라우드 러너 브리지",
        parents=[common],
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_pair = sub.add_parser("pair", parents=[common], help="사무소 코드로 클라우드 페어링")
    p_pair.add_argument("--code", required=True, help="사무소 코드 (ILSON-XXXX-XXXX-XXXX-XXXX)")
    p_pair.add_argument("--url", default=None, help="Supabase URL 재정의")
    p_pair.add_argument("--anon-key", default=None, help="Supabase anon 키 재정의")

    p_sync = sub.add_parser("sync", parents=[common], help="인계 수신 + 하트비트 + 승인 발행 1회 실행")
    p_sync.add_argument("--dry-run", action="store_true", help="실제 발행 없이 예정 목록만 확인")

    p_draft = sub.add_parser("submit-draft", parents=[common], help="결재함 초안(pending) 등록")
    p_draft.add_argument("--source-key", required=True, help="중복 방지용 고유 키")
    p_draft.add_argument("--platform", required=True, help="플랫폼 (threads|instagram)")
    p_draft.add_argument("--account", required=True, help="계정명")
    p_draft.add_argument("--body", required=True, help="게시 본문")
    p_draft.add_argument("--title", default="", help="초안 제목")
    p_draft.add_argument("--media-url", action="append", default=[], dest="media_urls", help="공개 미디어 URL")
    p_draft.add_argument("--scheduled-at", default=None, help="예약 발행 시각 (ISO 8601)")
    p_draft.add_argument("--kind", default="sns_post", help="결재 종류 (기본: sns_post)")

    sub.add_parser("status", parents=[common], help="로컬 클라우드 연결 상태 확인")

    sub.add_parser("heartbeat", parents=[common], help="클라우드 러너 하트비트 1회 전송")

    p_publish = sub.add_parser("publish", parents=[common], help="승인된 SNS 게시물 발행 1회 실행")
    p_publish.add_argument("--dry-run", action="store_true", help="실제 발행 없이 예정 목록만 확인")

    return parser


def _print_human(command: str, result: dict[str, Any]) -> None:
    if command == "pair":
        print(f"클라우드 페어링 완료: company={result['company_id']} runner={result['runner_id']}")
    elif command == "status":
        if not result["paired"]:
            print("클라우드 연결: 미연결 (ilson cloud pair --code <코드>로 연결하세요)")
            return
        print(f"클라우드 연결: 연결됨 (runner={result['runner_id']}, paired_at={result['paired_at']})")
        accounts = result.get("linked_accounts") or []
        print(f"연결된 SNS 계정: {len(accounts)}개")
        for acc in accounts:
            print(f"  - {acc['platform']}: @{acc['username']} ({acc['state']})")
        print(f"로컬 발행 이력: {result.get('published_count', 0)}건")
    elif command == "sync":
        h = result.get("handoffs", {})
        p = result.get("publishes", {})
        if p.get("dry_run"):
            print(
                f"동기화(dry-run) 완료: 인계 {h.get('claimed', 0)}건, "
                f"발행 예정 {len(p.get('would_publish', []))}건, 오류 {len(p.get('errors', []))}건"
            )
        else:
            print(
                f"동기화 완료: 인계 {h.get('claimed', 0)}건, "
                f"발행 {len(p.get('published', []))}건, 오류 {len(p.get('errors', []))}건"
            )
    elif command == "submit-draft":
        print(f"결재 초안 등록 완료: source_key={result['source_key']} status={result['status']}")
    elif command == "heartbeat":
        print(
            f"하트비트 전송 완료: last_beat_at={result['last_beat_at']} "
            f"(연결 계정 {len(result.get('linked_accounts') or [])}개)"
        )
    elif command == "publish":
        if result.get("locked"):
            print("다른 발행 작업이 실행 중입니다 (잠금 활성).")
        elif result.get("dry_run"):
            print(
                f"발행(dry-run) 확인 완료: 발행 예정 {len(result.get('would_publish', []))}건, "
                f"건너뜀 {len(result.get('skipped', []))}건, 오류 {len(result.get('errors', []))}건"
            )
        else:
            print(
                f"발행 완료: 발행 {len(result.get('published', []))}건, "
                f"건너뜀 {len(result.get('skipped', []))}건, 오류 {len(result.get('errors', []))}건"
            )


def main(
    argv: list[str] | None = None,
    *,
    http_send: HttpSend | None = None,
    publisher: PublisherFn | None = None,
) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    as_json = bool(getattr(args, "json", False))
    home = Path(getattr(args, "home", None) or _default_home())

    try:
        if args.command == "pair":
            result = pair_with_cloud(
                home,
                args.code,
                supabase_url=args.url,
                anon_key=args.anon_key,
                http_send=http_send,
            )
        elif args.command == "sync":
            result = sync_once(
                home,
                dry_run=bool(args.dry_run),
                http_send=http_send,
                publisher=publisher,
            )
        elif args.command == "submit-draft":
            result = submit_draft(
                home,
                source_key=args.source_key,
                platform=args.platform,
                account=args.account,
                body=args.body,
                title=args.title,
                media_urls=args.media_urls,
                scheduled_at=args.scheduled_at,
                kind=args.kind,
                http_send=http_send,
            )
        elif args.command == "status":
            result = get_status(home)
        elif args.command == "heartbeat":
            if _is_sandbox(home):
                raise CloudBridgeError("샌드박스 환경에서는 클라우드 하트비트를 전송할 수 없습니다.")
            cfg = _load_runner_config(home)
            jwt = authenticate(cfg, http_send=http_send)
            result = send_heartbeat(home, cfg, jwt, http_send=http_send)
        elif args.command == "publish":
            if _is_sandbox(home) and not args.dry_run:
                raise CloudBridgeError("샌드박스 환경에서는 실제 SNS 발행을 실행할 수 없습니다.")
            cfg = _load_runner_config(home)
            jwt = authenticate(cfg, http_send=http_send)
            result = dispatch_approved_publishes(
                home,
                cfg,
                jwt,
                http_send=http_send,
                publisher=publisher,
                dry_run=bool(args.dry_run),
            )
        else:
            raise CloudBridgeError(f"알 수 없는 명령입니다: {args.command}")
    except CloudBridgeError as exc:
        if as_json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"오류: {exc}", file=sys.stderr)
        return 1

    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_human(args.command, result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
