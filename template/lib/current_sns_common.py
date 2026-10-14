"""SNS 운영 조회 모델. 발행 원장은 읽기만 하고 서버 결과를 화면에서 대조한다.

예약·승인·재시도 함수는 호출하지 않는다. 조회 실패는 빈 정상 결과와 구별하고,
서버 식별자 또는 계정·시각·전체 본문이 유일하게 일치할 때만 두 기록을 합친다.
"""
from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import logging
import re
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit, quote, parse_qsl
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
UTC = timezone.utc
OVERDUE_GRACE = timedelta(minutes=45)
PLATFORMS = {"threads": "Threads", "instagram": "Instagram", "facebook": "Facebook",
             "naverblog": "네이버 블로그", "x": "X", "linkedin": "LinkedIn",
             "qiita": "Qiita", "zenn": "Zenn", "youtube": "YouTube"}
META = {"threads", "instagram", "facebook"}
LABELS = {"pending": "승인 대기", "approved": "승인됨", "scheduled": "예약됨",
          "published": "발행 기록 있음", "failed": "발행 실패", "held": "보류",
          "unknown": "결과 확인 필요", "cancelled": "취소·반려"}
log = logging.getLogger(__name__)
_lock = threading.Lock()
_cache = {}


def stamp(value, *, server=False):
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d.replace(tzinfo=UTC if server else KST) if d.tzinfo is None else d
    except (ValueError, TypeError):
        return None


def iso(value, *, server=False):
    d = stamp(value, server=server)
    return d.astimezone(KST).isoformat() if d else ""


def account_name(value):
    return str(value or "").strip().lstrip("@").casefold()

