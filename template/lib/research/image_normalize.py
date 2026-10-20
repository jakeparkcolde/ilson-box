"""인증된 첨부 요청을 메모리에서 JPEG로 변환한다. 파일·EXIF를 보관하지 않는다."""
import base64
import binascii
import io
import threading
import warnings
try:
    from .run import ResearchError
except ImportError:
    from run import ResearchError

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_JSON = 14 * 1024 * 1024
_lock = threading.Lock()


def heif_available():
    try:
        import pillow_heif
        return True
    except ImportError:
        return False


def normalize(value):
    if not isinstance(value, dict) or set(value) != {'data', 'media_type'}:
        raise ResearchError('이미지 첨부 형식을 확인하세요')
    encoded, mime = value['data'], value['media_type']
    if mime not in ('image/heic', 'image/heif') or not isinstance(encoded, str) or not 1 <= len(encoded) <= 4 * ((MAX_UPLOAD_BYTES + 2) // 3):
        raise ResearchError('HEIC·HEIF 사진은 10MB 이하여야 합니다')
    if not _lock.acquire(blocking=False):
        raise ResearchError('다른 이미지를 준비 중입니다. 잠시 후 다시 첨부하세요')
    try:
        from PIL import Image, ImageOps
        from pillow_heif import register_heif_opener
        register_heif_opener(thumbnails=False, depth_images=False, aux_images=False)
        raw = base64.b64decode(encoded, validate=True)
        if not raw or len(raw) > MAX_UPLOAD_BYTES:
            raise ValueError()
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format != 'HEIF' or source.width * source.height > 40_000_000:
                    raise ValueError()
                source.load()
                oriented = ImageOps.exif_transpose(source)
                rgb = oriented.convert('RGB')
                # 새로운 픽셀 버퍼로 EXIF·GPS·XMP·ICC 등 메타데이터를 모두 제거한다.
                pixels = Image.new('RGB', rgb.size)
                pixels.paste(rgb)
        for edge in (1600, 1280, 1024, 800):
            scaled = pixels.copy()
            scaled.thumbnail((edge, edge))
            for quality in (88, 72, 55):
                output = io.BytesIO()
                scaled.save(output, format='JPEG', quality=quality)
                if output.tell() <= 240_000:
                    return {'media_type': 'image/jpeg', 'data': base64.b64encode(output.getvalue()).decode('ascii')}
        raise ValueError()
    except ImportError:
        raise ResearchError('HEIC 변환 준비가 필요합니다. JPEG로 변환해 첨부하거나 실행기를 업데이트하세요') from None
    except (ValueError, OSError, SyntaxError, binascii.Error, Warning, Image.DecompressionBombError):
        raise ResearchError('HEIC 사진을 읽지 못했습니다. 손상되지 않은 사진을 다시 첨부하세요') from None
    finally:
        _lock.release()
