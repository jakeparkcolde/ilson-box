"""
meta_publish.py (공용)
----------------------
인스타그램·쓰레드 발행 (SPEC-PUBLISH-001 요구 8).

발행 집행 주체는 러너다(요구 7, 대표 확정 2026-08-09). 우리 인프라는 남의 SNS
토큰을 보관하지도 대행 발행하지도 않는다. 그러려면 지금 tide.pub(TypeScript)에
있는 발행 능력이 러너로 와야 하고, 이 파일이 그 이식이다.

**두 층으로 갈라 둔다.**
  ① 순수 층 (위쪽) — 무엇을 보낼지, 어떤 오류를 다시 시도할지. 네트워크 없음.
  ② HTTP 층 (아래쪽) — 실제로 보내고 기다리는 부분. `transport`·`sleep` 주입.

가른 이유 둘:
  · 재작성 버그가 제일 숨기 쉬운 자리가 ①이다. 순수해야 원본과 대조할 수 있다.
  · 플랫폼 API를 안 부르고 테스트할 수 있어야 CI가 남의 계정을 건드리지 않는다.

**토큰은 인자로만 받는다.** 이 모듈은 토큰이 어디서 오는지 모른다 — 러너 로컬
금고든 무엇이든 그건 호출부의 일이다 (P-CRED).

원본: sns-marketer `apps/web/src/lib/social/meta-publisher.ts`.
**옮기면서 규칙을 고치지 않았다.** 같은 입력에 같은 결과가 나오는지를
`test_meta_publish.py`가 원본 주석에 적힌 분기표 그대로 고정한다. 발행은 되돌릴
수 없는 동작이라, 옮기는 김에 개선하고 싶은 마음을 여기서는 누른다.

미디어 제약 (원본 주석 보존 — Meta가 컨테이너 단계에서 검증하므로 여기서 막지 않는다):
  · 단일 피드 비디오는 REELS로 게시해야 피드·그리드에 노출된다 (VIDEO는 사실상 폐기 경로)
  · 캐러셀 자식에서는 VIDEO가 유효하다
  · video_url은 공개 접근 가능한 http(s) URL이어야 한다 (base64 업로드 불가)
  · 비디오 컨테이너 처리 시간은 이미지보다 훨씬 길다 (보통 30초~수 분)
출처: developers.facebook.com/docs/instagram-platform/content-publishing
"""

from __future__ import annotations

from typing import Any, Union
import logging
import re

# 폴링 예산 — 이미지와 비디오가 다르다 (원본과 같은 값, 초 단위로 환산).
IG_IMAGE_READY_WAIT_SEC = 30.0
IG_VIDEO_READY_WAIT_SEC = 210.0

# 재시도 — 원본과 같은 규칙 (2초, 4초).
MAX_RETRIES = 2
RETRY_BASE_SEC = 2.0

# 호스트가 셋 다 다르다. 인스타 발행은 graph.facebook.com이 **아니라**
# graph.instagram.com이다 (Instagram Login 경로). 섞으면 권한이 안 맞아 막힌다.
GRAPH_FACEBOOK = "https://graph.facebook.com/v21.0"    # FB 페이지 게시 전용
GRAPH_INSTAGRAM = "https://graph.instagram.com/v21.0"  # 인스타 발행
GRAPH_THREADS = "https://graph.threads.net/v1.0"

# 슬라이드: 문자열이면 이미지 URL(레거시 호환), dict면 kind 명시.
CarouselSlide = Union[str, dict]


class PublishError(RuntimeError):
    """발행 실패. 조용히 삼키지 않는다 — 안 나간 글을 나간 것으로 세지 않는다."""

    def __init__(self, message, *, reason='api_error', code=None, http_status=None):
        super().__init__(message)
        self.reason = reason
        self.code = code
        self.http_status = http_status


class ContainerNotReady(PublishError):
    """시간 예산 안에 준비를 확인하지 못함. 확정 ERROR와 구분한다."""

    def __init__(self, message, **kwargs):
        super().__init__(message, reason='container_timeout', **kwargs)


_SAFE_REASONS = {
    'api_error': 'Meta API 요청 실패',
    'container_timeout': '컨테이너 준비 시간 초과',
    'container_error': '컨테이너 처리 실패',
    'container_expired': '컨테이너 만료',
}


def safe_publish_detail(exc: PublishError) -> str:
    """응답·URL·예외 원문은 절대 복사하지 않는다. 분류와 정수만 허용한다."""
    detail = _SAFE_REASONS.get(exc.reason, _SAFE_REASONS['api_error'])
    for label, value in (('HTTP', exc.http_status), ('code', exc.code)):
        if type(value) is int and 0 <= value <= 999999999:
            detail += f' {label}={value}'
    return detail


def safe_failure_record(value) -> str:
    """이 실행기가 만든 허용 형식만 장부로 전달한다. 과거 자유 형식 오류는 버린다."""
    reasons = '|'.join(re.escape(v) for v in _SAFE_REASONS.values())
    pattern = rf'내부 SNS 발행 실패: (?:{reasons})(?: HTTP=[0-9]{{1,9}})?(?: code=[0-9]{{1,9}})? — 실제 게시 확인 후 처리'
    if isinstance(value, str) and re.fullmatch(pattern, value):
        return value
    return '내부 SNS 발행 실패 — 실행 결과 확인 필요'


def normalize_slide(slide: CarouselSlide) -> dict:
    """슬라이드를 {url, kind}로 정규화한다. 문자열은 이미지로 본다(레거시 호환)."""
    if isinstance(slide, str):
        return {"url": slide, "kind": "image"}
    if not isinstance(slide, dict) or not slide.get("url"):
        raise PublishError(f"슬라이드 모양이 아니다: {slide!r}")
    kind = slide.get("kind", "image")
    if kind not in ("image", "video"):
        raise PublishError(f"kind는 image·video 중 하나: {kind!r}")
    return {"url": slide["url"], "kind": kind}


def container_params(*, kind: str, url: str, caption: str | None = None,
                     is_carousel_item: bool = False,
                     share_to_feed: bool = True,
                     cover_url: str = "") -> dict:
    """인스타 미디어 컨테이너 생성 파라미터 (access_token 제외).

    분기 지식을 한 곳에 모아 호출부 중복을 없앤다 — 원본이 라우트 중복을 없애려고
    만든 함수이고, 같은 이유로 여기서도 하나다.

        image  + carousel child : {image_url, is_carousel_item}
        image  + single         : {image_url, caption}
        video  + carousel child : {media_type: VIDEO, video_url, is_carousel_item}
        video  + single         : {media_type: REELS, video_url, caption,
                                   share_to_feed, cover_url?}
    """
    if kind not in ("image", "video"):
        raise PublishError(f"kind는 image·video 중 하나: {kind!r}")

    if kind == "video":
        if is_carousel_item:
            # 캐러셀 자식 비디오는 VIDEO가 유효하다.
            return {"media_type": "VIDEO", "video_url": url,
                    "is_carousel_item": True}
        # 단일 비디오는 REELS여야 피드·그리드에 보인다.
        params: dict[str, Any] = {"media_type": "REELS", "video_url": url,
                                  "share_to_feed": share_to_feed}
        if caption is not None:
            params["caption"] = caption
        if cover_url:
            params["cover_url"] = cover_url
        return params

    if is_carousel_item:
        return {"image_url": url, "is_carousel_item": True}
    params = {"image_url": url}
    if caption is not None:
        params["caption"] = caption
    return params


def threads_container_params(text: str, image_url: str = "") -> dict:
    """쓰레드 컨테이너 파라미터 (access_token 제외)."""
    if image_url:
        return {"text": text, "media_type": "IMAGE", "image_url": image_url}
    return {"text": text, "media_type": "TEXT"}


def is_transient(body: Any) -> bool:
    """다시 시도해도 되는 오류인가 — Meta가 `is_transient`로 알려준다.

    엄격히 `True`만 본다. 값이 없거나 모양이 다르면 **재시도하지 않는다** —
    영구 오류를 계속 두드리면 쿼터만 태우고, 그 사이 진짜 원인은 안 보인다.
    """
    if not isinstance(body, dict):
        return False
    err = body.get("error")
    return isinstance(err, dict) and err.get("is_transient") is True


def retry_delay_sec(attempt: int) -> float:
    """재시도 대기 (원본과 같은 값: 1회차 2초, 2회차 4초)."""
    return RETRY_BASE_SEC * (attempt + 1)


# 컨테이너 폴링 — 원본과 같은 값 (0.5초에서 시작해 1.5배씩, 최대 4초).
POLL_START_SEC = 0.5
POLL_MAX_SEC = 4.0
POLL_GROWTH = 1.5

# 게시 재시도 — 원본과 같은 값 (최대 4회, 3초 간격).
PUBLISH_ATTEMPTS = 4
PUBLISH_WAIT_SEC = 3.0

# "컨테이너가 아직 안 됐다" 계열만 다시 시도한다. 권한·유효성 오류는 즉시 실패다 —
# 안 될 것을 네 번 두드려봐야 쿼터만 태우고 원인은 그대로다.
#
# **플랫폼마다 낱말이 다르다** (원본의 정규식을 그대로 옮겼다). 쓰레드의 것을
# 인스타에 쓰면 9007을 못 알아보고 즉시 포기한다.
_NOT_READY = {
    "threads": r"not ready|not available|processing|2207027",
    "instagram": r"not ready|not available|processing|media.*not|9007",
}


def is_not_ready(body: Any, *, platform: str = "threads") -> bool:
    """컨테이너 미준비 계열 오류인가 (원본 정규식과 같은 낱말·같은 플랫폼별 구분)."""
    import json as _json
    import re

    pattern = _NOT_READY.get(platform)
    if pattern is None:
        raise PublishError(f"모르는 플랫폼: {platform!r}")
    try:
        msg = _json.dumps(body, ensure_ascii=False)
    except (TypeError, ValueError):
        msg = str(body)
    # IGNORECASE만 — 원본이 `/.../i`이고 `s` 플래그가 없다. JSON 직렬화 결과에는
    # 진짜 줄바꿈이 안 들어가므로 실무 차이는 없지만, 이식은 충실한 쪽이 맞다.
    return re.search(pattern, msg, re.IGNORECASE) is not None


def error_message(body: Any) -> str:
    """플랫폼 오류에서 사람이 읽을 한 줄을 뽑는다. 못 뽑으면 원문 일부.

    토큰이 섞여 나올 수 있는 자리라 길이를 자른다 — 오류 메시지가 로그를 통해
    비밀을 흘리는 경로가 되지 않게.
    """
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])[:300]
    return str(body)[:300]


# ── HTTP 층 ───────────────────────────────────────────────────
# 위쪽 순수 함수들이 "무엇을 보낼지"를 정했다면, 여기는 "실제로 보내고 기다리는"
# 부분이다. `transport`와 `sleep`을 주입할 수 있어 네트워크·대기 없이 테스트된다
# (ilson_supabase와 같은 규약).
#
# 토큰은 **인자로만** 받는다. 이 모듈은 어디서 토큰이 오는지 모른다 — 러너 로컬
# 금고든 무엇이든, 그건 호출부의 일이다 (P-CRED: 우리는 남의 토큰을 보관하지 않는다).

HTTP_TIMEOUT_SEC = 60.0


def _client(transport=None, timeout: float = HTTP_TIMEOUT_SEC):
    # 고객 설치본은 표준 라이브러리만 사용한다. 원본 MockTransport 시험은 유지한다.
    if transport is not None:
        import httpx
        return httpx.Client(transport=transport, timeout=timeout)
    from .http import Client
    return Client(timeout=timeout)


def _json_of(response) -> Any:
    try:
        return response.json()
    except Exception:  # noqa: BLE001 — 본문이 JSON이 아닐 수 있다
        return {}


def post_with_retry(url: str, payload: dict, *, transport=None,
                    sleep=None, max_retries: int = MAX_RETRIES) -> Any:
    """POST 하고, **일시적 오류만** 다시 시도한다 (원본 fetchWithRetry와 같은 규칙).

    반환은 응답 본문(dict). 실패는 `PublishError` — 조용히 빈 값을 돌려주지
    않는다. 안 나간 글을 나간 것으로 세면 사장님이 두 번 올리게 된다.
    """
    import time

    _sleep = sleep or time.sleep
    last: Any = {}
    for attempt in range(max_retries + 1):
        with _client(transport) as c:
            r = c.post(url, json=payload,
                       headers={"Content-Type": "application/json"})
        if r.status_code < 400:
            return _json_of(r)
        last = _json_of(r)
        if is_transient(last) and attempt < max_retries:
            _sleep(retry_delay_sec(attempt))
            continue
        break
    error = last.get('error') if isinstance(last, dict) else None
    raise PublishError(error_message(last), http_status=r.status_code,
                       code=error.get('code') if isinstance(error, dict) else None)


def wait_for_container(container_url: str, token: str, *,
                       max_wait_sec: float = IG_IMAGE_READY_WAIT_SEC,
                       transport=None, sleep=None, now=None, platform='instagram') -> None:
    """컨테이너가 준비될 때까지 기다린다 (원본 waitForContainerReady와 같은 규칙).

    `FINISHED`면 돌아오고, `ERROR`면 예외, 시간이 다 되면 예외다.
    **조회 실패 자체는 예외로 보지 않는다** — 응답에 status가 없거나 권한 때문에
    FINISHED를 영영 못 볼 수 있어서, 폴링 실패가 곧 발행 불가는 아니다.
    원본은 호출부에서 폴링 예외를 삼키기도 한다. Threads는 시간 초과만 넘기며
    확정 ERROR/EXPIRED는 전파한다. Instagram 호출부의 기존 정책은 유지한다.
    """
    import time

    _sleep = sleep or time.sleep
    _now = now or time.monotonic
    start = _now()
    delay = POLL_START_SEC
    # Threads에는 status_code가 없다. Instagram의 기존 조회 계약은 유지한다.
    fields = 'status,error_message' if platform == 'threads' else 'status,status_code'
    last_http, last_code = None, None
    while _now() - start < max_wait_sec:
        with _client(transport) as c:
            r = c.get(container_url,
                      params={"fields": fields,
                              "access_token": token})
        last_http = r.status_code
        data = _json_of(r)
        error = data.get('error') if isinstance(data, dict) else None
        last_code = error.get('code') if isinstance(error, dict) else None
        if r.status_code < 400:
            if isinstance(data, dict):
                if data.get("status") == "FINISHED":
                    return
                if data.get("status") == "ERROR":
                    raise PublishError(
                        f"컨테이너 처리 실패 ({data.get('status_code', 'unknown')})",
                        reason='container_error')
                if platform == 'threads' and data.get('status') == 'EXPIRED':
                    raise PublishError('컨테이너 만료', reason='container_expired')
        _sleep(delay)
        delay = min(delay * POLL_GROWTH, POLL_MAX_SEC)
    raise ContainerNotReady(f"컨테이너 준비 시간 초과 ({max_wait_sec:.0f}초)",
                            http_status=last_http, code=last_code)


def publish_threads(*, token: str, user_id: str, text: str, image_url: str = "",
                    transport=None, sleep=None, now=None, container_params=None) -> str:
    """쓰레드 1건 발행. 반환은 게시물 id.

    2단계다: 컨테이너 생성 → 게시. 이미지가 있으면 사이에서 준비를 기다린다.

    게시 재시도가 위쪽 `post_with_retry`와 **다른 규칙**인 것에 주의 — 여기는
    "컨테이너 미준비"만 다시 시도한다(권장 패턴). 일시 오류 재시도와 섞으면
    권한 오류를 네 번 두드리게 된다.
    """
    import time

    _sleep = sleep or time.sleep

    body = _json_of_or_raise(
        post_with_retry(f"{GRAPH_THREADS}/{user_id}/threads",
                        {**(container_params or threads_container_params(text, image_url)),
                         "access_token": token},
                        transport=transport, sleep=sleep))
    container_id = str(body.get("id") or "")
    if not container_id:
        raise PublishError(f"컨테이너 id가 없다: {str(body)[:200]}")

    if image_url or container_params:
        try:
            wait_for_container(f"{GRAPH_THREADS}/{container_id}", token,
                               transport=transport, sleep=sleep, now=now, platform='threads')
        except ContainerNotReady as exc:
            # 준비 미확인만 게시 단계에 넘긴다. ERROR/EXPIRED는 게시하지 않는다.
            logging.getLogger(__name__).warning('Threads 부모: %s', safe_publish_detail(exc))

    last: Any = {}
    for attempt in range(PUBLISH_ATTEMPTS):
        if attempt > 0:
            _sleep(PUBLISH_WAIT_SEC)
        with _client(transport) as c:
            r = c.post(f"{GRAPH_THREADS}/{user_id}/threads_publish",
                       json={"creation_id": container_id, "access_token": token},
                       headers={"Content-Type": "application/json"})
        if r.status_code < 400:
            got = _json_of(r)
            post_id = str(got.get("id") or "")
            if not post_id:
                raise PublishError(f"게시 id가 없다: {str(got)[:200]}")
            return post_id
        last = _json_of(r)
        if not is_not_ready(last):
            break     # 권한·유효성 오류는 즉시 실패
    error = last.get('error') if isinstance(last, dict) else None
    raise PublishError(f"쓰레드 발행 실패: {error_message(last)}", http_status=r.status_code,
                       code=error.get('code') if isinstance(error, dict) else None)


def publish_threads_media(*, token, user_id, text, slides, transport=None, sleep=None):
    """Threads 이미지·영상·캐러셀. Meta 공식 Threads API 컬렉션 규약.

    https://www.postman.com/meta/threads/documentation/dht3nzz/threads-api
    장수를 줄이거나 영상 URL을 이미지로 보내는 조용한 폴백은 금지한다.
    """
    media = [normalize_slide(slide) for slide in slides]
    if not 1 <= len(media) <= 20:
        raise PublishError('Threads 미디어는 1~20개가 필요합니다')
    params = []
    for slide in media:
        video = slide['kind'] == 'video'
        params.append({'media_type': 'VIDEO' if video else 'IMAGE',
                       'video_url' if video else 'image_url': slide['url']})
    if len(params) == 1:
        parent = {**params[0], 'text': text}
    else:
        children = []
        for item in params:
            body = _json_of_or_raise(post_with_retry(
                f'{GRAPH_THREADS}/{user_id}/threads',
                {**item, 'is_carousel_item': True, 'access_token': token},
                transport=transport, sleep=sleep))
            child = str(body.get('id') or '')
            if not child:
                raise PublishError('Threads 미디어 컨테이너 ID 없음')
            try:
                wait_for_container(f'{GRAPH_THREADS}/{child}', token,
                                   transport=transport, sleep=sleep, platform='threads')
            except ContainerNotReady as exc:
                # 2026-09-30: 조회 시간 초과는 처리 실패가 아니다. 장수는 보존하고
                # 부모 생성/게시 응답으로 판단한다. 확정 ERROR/EXPIRED는 전파한다.
                logging.getLogger(__name__).warning('Threads 자식 %d: %s', len(children)+1,
                                                    safe_publish_detail(exc))
            children.append(child)
        parent = {'media_type': 'CAROUSEL', 'children': ','.join(children), 'text': text}
    return publish_threads(token=token, user_id=user_id, text=text,
                           container_params=parent, transport=transport, sleep=sleep)


def _json_of_or_raise(body: Any) -> dict:
    if not isinstance(body, dict):
        raise PublishError(f"응답 모양이 아니다: {str(body)[:200]}")
    return body


def _media_publish(*, api_base: str, user_id: str, creation_id: str, token: str,
                   platform: str, transport=None, sleep=None,
                   attempts: int = PUBLISH_ATTEMPTS,
                   backoff_sec: float = PUBLISH_WAIT_SEC) -> str:
    """컨테이너를 게시한다. 미준비 계열만 재시도 (원본 publishInstagramMedia_publish).

    쓰레드의 게시 루프와 같은 모양이지만 **낱말 목록이 다르다** — `platform`으로 가른다.
    """
    import time

    _sleep = sleep or time.sleep
    last: Any = {}
    for attempt in range(attempts):
        if attempt > 0:
            _sleep(backoff_sec)
        with _client(transport) as c:
            r = c.post(f"{api_base}/{user_id}/media_publish",
                       json={"creation_id": creation_id, "access_token": token},
                       headers={"Content-Type": "application/json"})
        if r.status_code < 400:
            got = _json_of(r)
            post_id = str(got.get("id") or "")
            if not post_id:
                raise PublishError(f"게시 id가 없다: {str(got)[:200]}")
            return post_id
        last = _json_of(r)
        if not is_not_ready(last, platform=platform):
            break     # 권한·유효성 오류는 즉시 실패
    raise PublishError(f"게시 실패: {error_message(last)}")


def _create_container(*, api_base: str, user_id: str, params: dict, token: str,
                      transport=None) -> str:
    """미디어 컨테이너를 만들고 id를 돌려준다. 재시도하지 않는다 (원본과 같다)."""
    with _client(transport) as c:
        r = c.post(f"{api_base}/{user_id}/media",
                   json={**params, "access_token": token},
                   headers={"Content-Type": "application/json"})
    if r.status_code >= 400:
        raise PublishError(f"컨테이너 생성 실패: {error_message(_json_of(r))}")
    got = _json_of(r)
    container_id = str(got.get("id") or "") if isinstance(got, dict) else ""
    if not container_id:
        raise PublishError(f"컨테이너 id가 없다: {str(got)[:200]}")
    return container_id


def publish_instagram_image(*, token: str, user_id: str, image_url: str,
                            caption: str, transport=None, sleep=None,
                            now=None) -> str:
    """인스타 이미지 1장 발행. 반환은 게시물 id.

    ⚠️ **원본의 비대칭을 그대로 옮겼다.** 이미지 경로는 릴스 경로와 다르다:
      · 준비 대기 실패를 **삼키지 않는다** (릴스는 삼키고 발행을 시도한다)
      · 게시를 **재시도하지 않는다** (릴스는 미준비 계열을 4회까지 다시 한다)

    릴스 경로가 나중에 추가되며 안전망을 얻었고 이미지 경로는 옛 모양으로 남은
    것으로 보인다. 옮기며 고치지 않은 이유는 이 함수가 지금 우리 계정의 실제
    발행 경로이고, 발행은 되돌릴 수 없기 때문이다. 통일은 **대조로 동등함을
    확인한 뒤** 별도로 결정할 일이다 — 이식과 개선을 같은 커밋에 섞지 않는다.
    """
    if not image_url:
        raise PublishError("인스타 게시에는 이미지가 필수입니다")

    container_id = _create_container(
        api_base=GRAPH_INSTAGRAM, user_id=user_id,
        params={"image_url": image_url, "caption": caption},
        token=token, transport=transport)

    # 원본에 .catch()가 없다 — 폴링 실패가 곧 발행 실패다.
    wait_for_container(f"{GRAPH_INSTAGRAM}/{container_id}", token,
                       transport=transport, sleep=sleep, now=now)

    with _client(transport) as c:
        r = c.post(f"{GRAPH_INSTAGRAM}/{user_id}/media_publish",
                   json={"creation_id": container_id, "access_token": token},
                   headers={"Content-Type": "application/json"})
    if r.status_code >= 400:
        raise PublishError(f"인스타 발행 실패: {error_message(_json_of(r))}")
    got = _json_of(r)
    post_id = str(got.get("id") or "") if isinstance(got, dict) else ""
    if not post_id:
        raise PublishError(f"게시 id가 없다: {str(got)[:200]}")
    return post_id


def publish_instagram_reel(*, token: str, user_id: str, video_url: str,
                           caption: str, share_to_feed: bool = True,
                           cover_url: str = "",
                           ready_wait_sec: float = IG_VIDEO_READY_WAIT_SEC,
                           transport=None, sleep=None, now=None) -> str:
    """인스타 릴스(단일 비디오) 발행. 반환은 게시물 id.

    3단계다: REELS 컨테이너 → (연장된) 준비 대기 → 게시(미준비 재시도 네트).
    비디오 컨테이너는 처리에 오래 걸려 대기 예산이 이미지보다 7배다.
    """
    if not video_url:
        raise PublishError("릴스 게시에는 video_url(공개 http URL)이 필수입니다")

    container_id = _create_container(
        api_base=GRAPH_INSTAGRAM, user_id=user_id,
        params=container_params(kind="video", url=video_url, caption=caption,
                                share_to_feed=share_to_feed, cover_url=cover_url),
        token=token, transport=transport)

    try:
        wait_for_container(f"{GRAPH_INSTAGRAM}/{container_id}", token,
                           max_wait_sec=ready_wait_sec, transport=transport,
                           sleep=sleep, now=now)
    except PublishError:
        # 폴링 실패가 곧 발행 불가는 아니다 — 아래 재시도 네트가 처리한다.
        pass

    return _media_publish(api_base=GRAPH_INSTAGRAM, user_id=user_id,
                          creation_id=container_id, token=token,
                          platform="instagram", transport=transport, sleep=sleep)


def publish_instagram(*, kind: str, token: str, user_id: str, url: str,
                      caption: str, **kw) -> str:
    """미디어 종류 라우팅 — 이미지는 이미지 경로, 비디오는 릴스로.

    원본의 후방호환 진입점(`publishInstagramMedia`)과 같은 역할이다.
    """
    if kind == "video":
        return publish_instagram_reel(token=token, user_id=user_id,
                                      video_url=url, caption=caption, **kw)
    if kind == "image":
        kw.pop("share_to_feed", None)
        kw.pop("cover_url", None)
        kw.pop("ready_wait_sec", None)
        return publish_instagram_image(token=token, user_id=user_id,
                                       image_url=url, caption=caption, **kw)
    raise PublishError(f"kind는 image·video 중 하나: {kind!r}")


CAROUSEL_MIN = 2
CAROUSEL_MAX = 10


def publish_instagram_carousel(*, token: str, user_id: str,
                               slides: list, caption: str,
                               transport=None, sleep=None, now=None) -> str:
    """인스타 캐러셀 발행 (2~10장, 이미지·비디오 혼합). 반환은 게시물 id.

    5단계다:
      ① 슬라이드마다 자식 컨테이너 생성 (일시 오류 재시도)
      ② 자식들 준비 대기 — **best-effort**, 실패해도 계속 간다
      ③ 부모 컨테이너 생성 (media_type=CAROUSEL, children=id,id,...)
      ④ 부모 준비 대기 — best-effort
      ⑤ 게시 (미준비 재시도 네트)

    ── 원본과 의도적으로 다른 두 가지 (숨기지 않고 적는다) ──
    1) **순차로 돈다.** 원본은 자식을 3개씩 병렬로 만든다. 러너에 동시성 장치를
       들이지 않으려고 순차로 갔다 — 결과는 같고 느릴 뿐이며, 러너는 사람을
       기다리게 하지 않는 배경 프로세스다. 대신 실패 시점이 다르다: 원본은 그
       묶음 3개를 다 시도한 뒤 던지고, 여기는 첫 실패에서 멈춘다(만들다 만
       고아 컨테이너가 덜 생기므로 이쪽이 낫다).
    2) **대기 예산을 자식마다 그 종류로 준다.** 원본은 3개 묶음에 비디오가 하나라도
       있으면 그 묶음 전체에 긴 예산을 준다 — 묶음으로 나눈 결과지 의도가 아니다.
       ②가 best-effort라 예산이 짧아 일찍 포기해도 ⑤의 재시도 네트가 받는다.

    두 차이 모두 ②가 실패를 무시하는 단계라서 관측 결과가 같다. 그래도 적어두는
    이유는, 나중에 "왜 원본과 다르지"를 다시 조사하지 않게 하기 위해서다.
    """
    if not isinstance(slides, (list, tuple)) or len(slides) < CAROUSEL_MIN:
        raise PublishError(f"캐러셀에는 최소 {CAROUSEL_MIN}장의 미디어가 필요합니다")
    if len(slides) > CAROUSEL_MAX:
        raise PublishError(f"캐러셀은 최대 {CAROUSEL_MAX}장까지 가능합니다")

    normalized = [normalize_slide(s) for s in slides]
    has_video = any(s["kind"] == "video" for s in normalized)

    # ① 자식 컨테이너 — 자식에는 caption을 싣지 않는다 (부모만 갖는다).
    children: list[dict] = []
    for slide in normalized:
        body = post_with_retry(
            f"{GRAPH_INSTAGRAM}/{user_id}/media",
            {**container_params(kind=slide["kind"], url=slide["url"],
                                is_carousel_item=True),
             "access_token": token},
            transport=transport, sleep=sleep)
        child_id = str(body.get("id") or "") if isinstance(body, dict) else ""
        if not child_id:
            raise PublishError(f"자식 컨테이너 id가 없다: {str(body)[:200]}")
        children.append({"id": child_id, "kind": slide["kind"]})

    # ② 자식 준비 대기 — best-effort. 여기서 멈추면 ⑤의 재시도 네트를 못 쓴다.
    for child in children:
        budget = (IG_VIDEO_READY_WAIT_SEC if child["kind"] == "video"
                  else IG_IMAGE_READY_WAIT_SEC)
        try:
            wait_for_container(f"{GRAPH_INSTAGRAM}/{child['id']}", token,
                               max_wait_sec=budget, transport=transport,
                               sleep=sleep, now=now)
        except PublishError:
            pass

    # ③ 부모 컨테이너
    carousel_id = _create_container(
        api_base=GRAPH_INSTAGRAM, user_id=user_id,
        params={"media_type": "CAROUSEL",
                "children": ",".join(c["id"] for c in children),
                "caption": caption},
        token=token, transport=transport)

    # ④ 부모 준비 대기 — best-effort (비디오가 하나라도 있으면 연장 예산)
    try:
        wait_for_container(
            f"{GRAPH_INSTAGRAM}/{carousel_id}", token,
            max_wait_sec=(IG_VIDEO_READY_WAIT_SEC if has_video
                          else IG_IMAGE_READY_WAIT_SEC),
            transport=transport, sleep=sleep, now=now)
    except PublishError:
        pass

    # ⑤ 게시
    return _media_publish(api_base=GRAPH_INSTAGRAM, user_id=user_id,
                          creation_id=carousel_id, token=token,
                          platform="instagram", transport=transport, sleep=sleep)
