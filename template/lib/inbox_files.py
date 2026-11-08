"""사람이 넣은 파일만 읽는다. 경로와 실제 이미지 형식을 확인한다."""
import hashlib
import io
import os
import secrets
import stat
import warnings
from contextlib import contextmanager
from pathlib import Path

MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 40_000_000
EXTENSIONS = {'.jpg': 'JPEG', '.jpeg': 'JPEG', '.png': 'PNG', '.heic': 'HEIF'}

class InboxError(ValueError):
    pass

@contextmanager
def safe_dir(home, *parts, create=False):
    """모든 경로 구성요소를 링크를 따르지 않는 디렉터리 FD로 연다."""
    fd = os.open(str(home), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if os.fstat(fd).st_uid != os.geteuid():
            raise InboxError('폴더 소유자를 확인하세요.')
        for part in parts:
            if not _safe_name(part):
                raise InboxError('폴더 경로를 확인하세요.')
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd); fd = next_fd
            if os.fstat(fd).st_uid != os.geteuid():
                raise InboxError('폴더 소유자를 확인하세요.')
        yield fd
    except OSError:
        raise InboxError('폴더를 안전하게 열지 못했습니다.') from None
    finally:
        os.close(fd)

def inbox_dir(home, create=False):
    with safe_dir(home, 'vault', 'inbox', create=create):
        pass
    return Path(home) / 'vault' / 'inbox'

def _safe_name(name):
    return isinstance(name, str) and name not in ('', '.', '..') and '/' not in name and '\\' not in name and '\x00' not in name

def read_file(home, name):
    if not _safe_name(name):
        raise InboxError('파일 이름을 확인하세요.')
    with safe_dir(home, 'vault', 'inbox') as dfd:
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
            try:
                info = os.fstat(fd)
                if info.st_uid != os.geteuid() or not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_BYTES:
                    raise InboxError('빈 파일이거나 10MB를 넘는 파일입니다.')
                chunks = bytearray()
                while len(chunks) <= MAX_BYTES:
                    part = os.read(fd, min(131072, MAX_BYTES + 1 - len(chunks)))
                    if not part:
                        break
                    chunks.extend(part)
                if len(chunks) != info.st_size or len(chunks) > MAX_BYTES:
                    raise InboxError('파일이 바뀌었습니다. 다시 확인하세요.')
                return bytes(chunks)
            finally:
                os.close(fd)
        except OSError:
            raise InboxError('파일을 안전하게 읽지 못했습니다.') from None

def normalize(name, raw):
    expected = EXTENSIONS.get(Path(name).suffix.lower())
    if not expected:
        raise InboxError('지원하지 않는 파일입니다.')
    try:
        from PIL import Image, ImageOps
        if expected == 'HEIF':
            from pillow_heif import register_heif_opener
            register_heif_opener(thumbnails=False, depth_images=False, aux_images=False)
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as img:
                if img.format != expected or img.width * img.height > MAX_PIXELS or getattr(img, 'n_frames', 1) != 1:
                    raise ValueError()
                img.load()
                img = ImageOps.exif_transpose(img).convert('RGB')
                # 메타데이터를 빼고 모델 전달용 사진을 만든다.
                pixels = Image.new('RGB', img.size)
                pixels.paste(img)
        for edge in (1600, 1280, 1024, 800):
            scaled = pixels.copy(); scaled.thumbnail((edge, edge))
            for quality in (88, 72, 55):
                out = io.BytesIO(); scaled.save(out, format='JPEG', quality=quality)
                if out.tell() <= 240_000:
                    return out.getvalue()
    except (ImportError, ValueError, OSError, SyntaxError, Warning):
        from inbox_sips import normalize_sips
        return normalize_sips(name, raw)
    except Image.DecompressionBombError:
        from inbox_sips import normalize_sips
        return normalize_sips(name, raw)
    raise InboxError('사진이 너무 복잡해 준비하지 못했습니다.')

def inspect(home, name):
    raw = read_file(home, name)
    if Path(name).suffix.lower() == '.pdf':
        from inbox_pdf import validate_pdf
        pages = validate_pdf(raw)
        return {'name':name, 'sha256':hashlib.sha256(raw).hexdigest(), 'bytes':len(raw), 'format':'PDF', 'pages':pages}, raw
    image = normalize(name, raw)
    return {'name': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'format': EXTENSIONS[Path(name).suffix.lower()]}, image

def list_files(home):
    rows, seen = [], {}
    with safe_dir(home, 'vault', 'inbox', create=True) as dfd:
        names = sorted(e.name for e in os.scandir(dfd))[:500]
    for name in names:
        if name.startswith('.'):
            continue
        try:
            meta, _ = inspect(home, name)
            meta['duplicate_of'] = seen.get(meta['sha256'])
            seen.setdefault(meta['sha256'], name)
            meta['supported'] = True
        except (InboxError, OSError):
            meta = {'name': name, 'supported': False}
        rows.append(meta)
    return rows

def atomic_create(dfd, name, raw):
    """같은 디렉터리에 임시 파일을 쓰고 링크하여 충돌 시 덮어쓰지 않는다."""
    temp = '.inbox-' + secrets.token_hex(16)
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dfd)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(raw); out.flush(); os.fsync(out.fileno())
        try:
            os.link(temp, name, src_dir_fd=dfd, dst_dir_fd=dfd, follow_symlinks=False)
        except FileExistsError:
            raise InboxError('이미 같은 이름이 있어 저장하지 않았습니다.') from None
    finally:
        os.unlink(temp, dir_fd=dfd)
