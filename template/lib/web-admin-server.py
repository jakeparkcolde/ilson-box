#!/usr/bin/env python3
"""일손 Box의 로컬 업무 관리자. 세션·동일 출처 인증 뒤 업무 API를 제공한다."""
from __future__ import annotations

import argparse
import errno
from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import hmac
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import plistlib
import re
import secrets
import shutil
import signal
import socket
from socketserver import TCPServer
import stat
import subprocess
import sys
import threading
import time
from urllib.parse import unquote, urlsplit

LIBRARY = str(Path(__file__).resolve().parent)
if LIBRARY not in sys.path:
    sys.path.insert(0, LIBRARY)

import ilson_platform as platform

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
# ilson pause 가 거절하는 기본 관리 업무.
BASE_JOBS = {"watchdog", "snapshot", "update"}
STATIC = {"/dashboard": ("web/dashboard.html", "text/html; charset=utf-8"),
          "/dashboard.js": ("web/dashboard.js", "application/javascript; charset=utf-8"),
          "/dashboard.css": ("web/dashboard.css", "text/css; charset=utf-8"),
          "/": ("web/index.html", "text/html; charset=utf-8"),
          "/index.html": ("web/index.html", "text/html; charset=utf-8"),
          "/styles.css": ("web/styles.css", "text/css; charset=utf-8"),
          "/fonts.css": ("web/fonts.css", "text/css; charset=utf-8"),
          "/fonts/InterVariable-4.1.woff2": ("web/fonts/InterVariable-4.1.woff2", "font/woff2"),
          "/fonts/PretendardVariable-1.3.9.woff2": ("web/fonts/PretendardVariable-1.3.9.woff2", "font/woff2"),
          "/fonts/JetBrainsMono-Regular-2.304.woff2": ("web/fonts/JetBrainsMono-Regular-2.304.woff2", "font/woff2"),
          "/workspace.js": ("web/workspace.js", "application/javascript; charset=utf-8"),
          "/workspace.css": ("web/workspace.css", "text/css; charset=utf-8"),
          "/app.js": ("web/app.js", "application/javascript; charset=utf-8"),
          "/favicon.svg": ("web/favicon.svg", "image/svg+xml")}


STATIC['/usage-history'] = ('web/usage-history.html', 'text/html; charset=utf-8')
STATIC['/usage-history.js'] = ('web/usage-history.js', 'application/javascript; charset=utf-8')
STATIC['/usage-history.css'] = ('web/usage-history.css', 'text/css; charset=utf-8')
STATIC['/approval'] = ('web/approval.html', 'text/html; charset=utf-8')
STATIC['/approval.js'] = ('web/approval.js', 'application/javascript; charset=utf-8')
STATIC['/current/opensource.js'] = ('web/current/opensource.js', 'application/javascript; charset=utf-8')
STATIC['/current/opensource.css'] = ('web/current/opensource.css', 'text/css; charset=utf-8')
STATIC['/current/replies.js'] = ('web/current/replies.js', 'application/javascript; charset=utf-8')

STATIC['/people'] = ('web/people.html', 'text/html; charset=utf-8')
STATIC['/people.js'] = ('web/people.js', 'application/javascript; charset=utf-8')
STATIC['/people.css'] = ('web/people.css', 'text/css; charset=utf-8')

# 기존 일손 화면 자산도 명시한 경로만 제공한다.
STATIC['/current/assets/sns/facebook.svg'] = ('web/current/assets/sns/facebook.svg', 'image/svg+xml')
STATIC['/current/assets/sns/instagram.svg'] = ('web/current/assets/sns/instagram.svg', 'image/svg+xml')
STATIC['/current/assets/sns/linkedin.svg'] = ('web/current/assets/sns/linkedin.svg', 'image/svg+xml')
STATIC['/current/assets/sns/naver.svg'] = ('web/current/assets/sns/naver.svg', 'image/svg+xml')
STATIC['/current/assets/sns/qiita.svg'] = ('web/current/assets/sns/qiita.svg', 'image/svg+xml')
STATIC['/current/assets/sns/threads.svg'] = ('web/current/assets/sns/threads.svg', 'image/svg+xml')
STATIC['/current/assets/sns/x.svg'] = ('web/current/assets/sns/x.svg', 'image/svg+xml')
STATIC['/current/assets/sns/zenn.svg'] = ('web/current/assets/sns/zenn.svg', 'image/svg+xml')
STATIC['/current/composer.js'] = ('web/current/composer.js', 'application/javascript; charset=utf-8')
STATIC["/current/"] = ("web/current/index.html", "text/html; charset=utf-8")
STATIC['/current/people.js'] = ('web/current/people.js', 'application/javascript; charset=utf-8')
STATIC['/current/people.css'] = ('web/current/people.css', 'text/css; charset=utf-8')
STATIC['/current/base.css'] = ('web/current/base.css', 'text/css; charset=utf-8')
STATIC['/current/icons.js'] = ('web/current/icons.js', 'application/javascript; charset=utf-8')
STATIC['/current/index.html'] = ('web/current/index.html', 'text/html; charset=utf-8')
STATIC['/current/pack-library/ability-format.js'] = ('web/current/pack-library/ability-format.js', 'application/javascript; charset=utf-8')
STATIC['/current/pack-library/ability-library.js'] = ('web/current/pack-library/ability-library.js', 'application/javascript; charset=utf-8')
STATIC['/current/pack-library/knowledge.css'] = ('web/current/pack-library/knowledge.css', 'text/css; charset=utf-8')
STATIC['/current/pack-library/knowledge.html'] = ('web/current/pack-library/knowledge.html', 'text/html; charset=utf-8')
STATIC['/current/pack-library/knowledge.js'] = ('web/current/pack-library/knowledge.js', 'application/javascript; charset=utf-8')
STATIC['/current/pack-library/pack-embedded.js'] = ('web/current/pack-library/pack-embedded.js', 'application/javascript; charset=utf-8')
STATIC['/current/pack-library/pack-navigation.js'] = ('web/current/pack-library/pack-navigation.js', 'application/javascript; charset=utf-8')
STATIC['/current/pack-library/packs.css'] = ('web/current/pack-library/packs.css', 'text/css; charset=utf-8')
STATIC['/current/pack-library/packs.html'] = ('web/current/pack-library/packs.html', 'text/html; charset=utf-8')
STATIC['/current/pack-library/packs.js'] = ('web/current/pack-library/packs.js', 'application/javascript; charset=utf-8')
STATIC['/current/pack-library/research-threads.js'] = ('web/current/pack-library/research-threads.js', 'application/javascript; charset=utf-8')
STATIC['/current/pack-library/research.css'] = ('web/current/pack-library/research.css', 'text/css; charset=utf-8')
STATIC['/current/pack-library/research.html'] = ('web/current/pack-library/research.html', 'text/html; charset=utf-8')
STATIC['/current/pack-library/research-image.js'] = ('web/current/pack-library/research-image.js', 'application/javascript; charset=utf-8')
STATIC['/current/pack-library/research.js'] = ('web/current/pack-library/research.js', 'application/javascript; charset=utf-8')
STATIC['/current/shell.css'] = ('web/current/shell.css', 'text/css; charset=utf-8')
STATIC['/current/shell.js'] = ('web/current/shell.js', 'application/javascript; charset=utf-8')
STATIC['/current/sns_accounts.js'] = ('web/current/sns_accounts.js', 'application/javascript; charset=utf-8')
STATIC['/current/sns_operations.css'] = ('web/current/sns_operations.css', 'text/css; charset=utf-8')
STATIC['/current/sns_operations.js'] = ('web/current/sns_operations.js', 'application/javascript; charset=utf-8')
STATIC['/current/vault.js'] = ('web/current/vault.js', 'application/javascript; charset=utf-8')
STATIC['/current/inbox-files.js'] = ('web/current/inbox-files.js', 'application/javascript; charset=utf-8')
STATIC['/current/inbox-files.css'] = ('web/current/inbox-files.css', 'text/css; charset=utf-8')
# Claude 배우기 화면 — 강의 파일을 추가하면 여기에도 한 줄씩 등록한다.
STATIC['/current/learn/learn.js'] = ('web/current/learn/learn.js', 'application/javascript; charset=utf-8')
STATIC['/current/learn/learn.css'] = ('web/current/learn/learn.css', 'text/css; charset=utf-8')
STATIC['/current/learn/catalog.json'] = ('web/current/learn/catalog.json', 'application/json; charset=utf-8')
STATIC['/current/learn/files/v05-schema.txt'] = ('web/current/learn/files/v05-schema.txt', 'text/plain; charset=utf-8')
STATIC['/current/learn/files/v06-reserve-code.txt'] = ('web/current/learn/files/v06-reserve-code.txt', 'text/plain; charset=utf-8')
STATIC['/current/learn/files/v07-admin-code.txt'] = ('web/current/learn/files/v07-admin-code.txt', 'text/plain; charset=utf-8')
STATIC['/current/learn/files/v07-owner-policy.txt'] = ('web/current/learn/files/v07-owner-policy.txt', 'text/plain; charset=utf-8')
STATIC['/current/learn/files/v10-backup-code.txt'] = ('web/current/learn/files/v10-backup-code.txt', 'text/plain; charset=utf-8')
STATIC['/current/learn/files/v10-cleanup.txt'] = ('web/current/learn/files/v10-cleanup.txt', 'text/plain; charset=utf-8')
STATIC['/current/learn/files/v10-policy-check.txt'] = ('web/current/learn/files/v10-policy-check.txt', 'text/plain; charset=utf-8')
STATIC['/current/learn/img/b01-course-map.svg'] = ('web/current/learn/img/b01-course-map.svg', 'image/svg+xml')
STATIC['/current/learn/img/b01-cover.svg'] = ('web/current/learn/img/b01-cover.svg', 'image/svg+xml')
STATIC['/current/learn/img/b01-strengths.svg'] = ('web/current/learn/img/b01-strengths.svg', 'image/svg+xml')
STATIC['/current/learn/img/b01-three-ways.svg'] = ('web/current/learn/img/b01-three-ways.svg', 'image/svg+xml')
STATIC['/current/learn/img/b02-cover.svg'] = ('web/current/learn/img/b02-cover.svg', 'image/svg+xml')
STATIC['/current/learn/img/b02-plan-chooser.svg'] = ('web/current/learn/img/b02-plan-chooser.svg', 'image/svg+xml')
STATIC['/current/learn/img/b02-signup-screen.svg'] = ('web/current/learn/img/b02-signup-screen.svg', 'image/svg+xml')
STATIC['/current/learn/img/b02-usage-window.svg'] = ('web/current/learn/img/b02-usage-window.svg', 'image/svg+xml')
STATIC['/current/learn/img/b03-anonymize.svg'] = ('web/current/learn/img/b03-anonymize.svg', 'image/svg+xml')
STATIC['/current/learn/img/b03-cover.svg'] = ('web/current/learn/img/b03-cover.svg', 'image/svg+xml')
STATIC['/current/learn/img/b03-privacy-setting.svg'] = ('web/current/learn/img/b03-privacy-setting.svg', 'image/svg+xml')
STATIC['/current/learn/img/b03-retention.svg'] = ('web/current/learn/img/b03-retention.svg', 'image/svg+xml')
STATIC['/current/learn/img/b04-ask-first.svg'] = ('web/current/learn/img/b04-ask-first.svg', 'image/svg+xml')
STATIC['/current/learn/img/b04-cover.svg'] = ('web/current/learn/img/b04-cover.svg', 'image/svg+xml')
STATIC['/current/learn/img/b04-fix-ways.svg'] = ('web/current/learn/img/b04-fix-ways.svg', 'image/svg+xml')
STATIC['/current/learn/img/b05-before-after.svg'] = ('web/current/learn/img/b05-before-after.svg', 'image/svg+xml')
STATIC['/current/learn/img/b05-cover.svg'] = ('web/current/learn/img/b05-cover.svg', 'image/svg+xml')
STATIC['/current/learn/img/b05-memo-card.svg'] = ('web/current/learn/img/b05-memo-card.svg', 'image/svg+xml')
STATIC['/current/learn/img/b06-attach.svg'] = ('web/current/learn/img/b06-attach.svg', 'image/svg+xml')
STATIC['/current/learn/img/b06-before-upload.svg'] = ('web/current/learn/img/b06-before-upload.svg', 'image/svg+xml')
STATIC['/current/learn/img/b06-cover.svg'] = ('web/current/learn/img/b06-cover.svg', 'image/svg+xml')
STATIC['/current/learn/img/b06-quote-compare.svg'] = ('web/current/learn/img/b06-quote-compare.svg', 'image/svg+xml')
STATIC['/current/learn/img/b07-cover.svg'] = ('web/current/learn/img/b07-cover.svg', 'image/svg+xml')
STATIC['/current/learn/img/b07-sorted-answer.svg'] = ('web/current/learn/img/b07-sorted-answer.svg', 'image/svg+xml')
STATIC['/current/learn/img/b07-when-official.svg'] = ('web/current/learn/img/b07-when-official.svg', 'image/svg+xml')
STATIC['/current/learn/img/b08-cover.svg'] = ('web/current/learn/img/b08-cover.svg', 'image/svg+xml')
STATIC['/current/learn/img/b08-in-out.svg'] = ('web/current/learn/img/b08-in-out.svg', 'image/svg+xml')
STATIC['/current/learn/img/b08-memory-map.svg'] = ('web/current/learn/img/b08-memory-map.svg', 'image/svg+xml')
STATIC['/current/learn/img/b08-project-screen.svg'] = ('web/current/learn/img/b08-project-screen.svg', 'image/svg+xml')
STATIC['/current/learn/img/b09-cover.svg'] = ('web/current/learn/img/b09-cover.svg', 'image/svg+xml')
STATIC['/current/learn/img/b09-share-menu.svg'] = ('web/current/learn/img/b09-share-menu.svg', 'image/svg+xml')
STATIC['/current/learn/img/b09-who-sees.svg'] = ('web/current/learn/img/b09-who-sees.svg', 'image/svg+xml')
STATIC['/current/learn/img/b10-cover.svg'] = ('web/current/learn/img/b10-cover.svg', 'image/svg+xml')
STATIC['/current/learn/img/b10-hidden-order.svg'] = ('web/current/learn/img/b10-hidden-order.svg', 'image/svg+xml')
STATIC['/current/learn/img/b10-permissions.svg'] = ('web/current/learn/img/b10-permissions.svg', 'image/svg+xml')
STATIC['/current/learn/img/b10-report-check.svg'] = ('web/current/learn/img/b10-report-check.svg', 'image/svg+xml')
STATIC['/current/learn/img/b11-chat-screen.svg'] = ('web/current/learn/img/b11-chat-screen.svg', 'image/svg+xml')
STATIC['/current/learn/img/b11-cover.svg'] = ('web/current/learn/img/b11-cover.svg', 'image/svg+xml')
STATIC['/current/learn/img/b11-exit-keys.svg'] = ('web/current/learn/img/b11-exit-keys.svg', 'image/svg+xml')
STATIC['/current/learn/img/b11-spotlight.svg'] = ('web/current/learn/img/b11-spotlight.svg', 'image/svg+xml')
STATIC['/current/learn/img/b12-login-flow.svg'] = ('web/current/learn/img/b12-login-flow.svg', 'image/svg+xml')
STATIC['/current/learn/img/b12-three-checks.svg'] = ('web/current/learn/img/b12-three-checks.svg', 'image/svg+xml')
STATIC['/current/learn/img/b12-trust-decision.svg'] = ('web/current/learn/img/b12-trust-decision.svg', 'image/svg+xml')
STATIC['/current/learn/img/b13-cycle.svg'] = ('web/current/learn/img/b13-cycle.svg', 'image/svg+xml')
STATIC['/current/learn/img/b13-folders.svg'] = ('web/current/learn/img/b13-folders.svg', 'image/svg+xml')
STATIC['/current/learn/img/b13-vault-screen.svg'] = ('web/current/learn/img/b13-vault-screen.svg', 'image/svg+xml')
STATIC['/current/learn/img/b14-auto-check.svg'] = ('web/current/learn/img/b14-auto-check.svg', 'image/svg+xml')
STATIC['/current/learn/img/b14-permission-prompt.svg'] = ('web/current/learn/img/b14-permission-prompt.svg', 'image/svg+xml')
STATIC['/current/learn/img/b14-rewind-menu.svg'] = ('web/current/learn/img/b14-rewind-menu.svg', 'image/svg+xml')
STATIC['/current/learn/img/b14-safety-flow.svg'] = ('web/current/learn/img/b14-safety-flow.svg', 'image/svg+xml')
STATIC['/current/learn/img/b15-answer-guide.svg'] = ('web/current/learn/img/b15-answer-guide.svg', 'image/svg+xml')
STATIC['/current/learn/img/b15-interview-map.svg'] = ('web/current/learn/img/b15-interview-map.svg', 'image/svg+xml')
STATIC['/current/learn/img/b15-status-after.svg'] = ('web/current/learn/img/b15-status-after.svg', 'image/svg+xml')
STATIC['/current/learn/img/b16-menu-map.svg'] = ('web/current/learn/img/b16-menu-map.svg', 'image/svg+xml')
STATIC['/current/learn/img/b16-research-screen.svg'] = ('web/current/learn/img/b16-research-screen.svg', 'image/svg+xml')
STATIC['/current/learn/img/b16-shared-vault.svg'] = ('web/current/learn/img/b16-shared-vault.svg', 'image/svg+xml')
STATIC['/current/learn/img/b17-start-check.svg'] = ('web/current/learn/img/b17-start-check.svg', 'image/svg+xml')
STATIC['/current/learn/img/b17-telegram-connect.svg'] = ('web/current/learn/img/b17-telegram-connect.svg', 'image/svg+xml')
STATIC['/current/learn/img/b17-week-schedule.svg'] = ('web/current/learn/img/b17-week-schedule.svg', 'image/svg+xml')
STATIC['/current/learn/img/b18-review-card.svg'] = ('web/current/learn/img/b18-review-card.svg', 'image/svg+xml')
STATIC['/current/learn/img/b18-skill-contents.svg'] = ('web/current/learn/img/b18-skill-contents.svg', 'image/svg+xml')
STATIC['/current/learn/img/b19-local-vs-public.svg'] = ('web/current/learn/img/b19-local-vs-public.svg', 'image/svg+xml')
STATIC['/current/learn/img/b19-notes-to-page.svg'] = ('web/current/learn/img/b19-notes-to-page.svg', 'image/svg+xml')
STATIC['/current/learn/img/b19-page-sketch.svg'] = ('web/current/learn/img/b19-page-sketch.svg', 'image/svg+xml')
STATIC['/current/learn/img/b20-choices.svg'] = ('web/current/learn/img/b20-choices.svg', 'image/svg+xml')
STATIC['/current/learn/img/b20-shared-allowance.svg'] = ('web/current/learn/img/b20-shared-allowance.svg', 'image/svg+xml')
STATIC['/current/learn/img/b20-usage-page.svg'] = ('web/current/learn/img/b20-usage-page.svg', 'image/svg+xml')
STATIC['/current/learn/img/b21-calm-steps.svg'] = ('web/current/learn/img/b21-calm-steps.svg', 'image/svg+xml')
STATIC['/current/learn/img/b21-safe-fixes.svg'] = ('web/current/learn/img/b21-safe-fixes.svg', 'image/svg+xml')
STATIC['/current/learn/img/b21-where-to-ask.svg'] = ('web/current/learn/img/b21-where-to-ask.svg', 'image/svg+xml')
STATIC['/current/learn/img/b22-learn-next.svg'] = ('web/current/learn/img/b22-learn-next.svg', 'image/svg+xml')
STATIC['/current/learn/img/b22-word-map.svg'] = ('web/current/learn/img/b22-word-map.svg', 'image/svg+xml')
STATIC['/current/learn/img/v01-customer-path.svg'] = ('web/current/learn/img/v01-customer-path.svg', 'image/svg+xml')
STATIC['/current/learn/img/v01-fields.svg'] = ('web/current/learn/img/v01-fields.svg', 'image/svg+xml')
STATIC['/current/learn/img/v01-three-accounts.svg'] = ('web/current/learn/img/v01-three-accounts.svg', 'image/svg+xml')
STATIC['/current/learn/img/v02-promise-card.svg'] = ('web/current/learn/img/v02-promise-card.svg', 'image/svg+xml')
STATIC['/current/learn/img/v02-trust-yes-no.svg'] = ('web/current/learn/img/v02-trust-yes-no.svg', 'image/svg+xml')
STATIC['/current/learn/img/v02-two-folders.svg'] = ('web/current/learn/img/v02-two-folders.svg', 'image/svg+xml')
STATIC['/current/learn/img/v03-four-files.svg'] = ('web/current/learn/img/v03-four-files.svg', 'image/svg+xml')
STATIC['/current/learn/img/v03-narrow-window.svg'] = ('web/current/learn/img/v03-narrow-window.svg', 'image/svg+xml')
STATIC['/current/learn/img/v03-page-to-form.svg'] = ('web/current/learn/img/v03-page-to-form.svg', 'image/svg+xml')
STATIC['/current/learn/img/v04-closing-album.svg'] = ('web/current/learn/img/v04-closing-album.svg', 'image/svg+xml')
STATIC['/current/learn/img/v04-daily-close.svg'] = ('web/current/learn/img/v04-daily-close.svg', 'image/svg+xml')
STATIC['/current/learn/img/v04-rewind-vs-album.svg'] = ('web/current/learn/img/v04-rewind-vs-album.svg', 'image/svg+xml')
STATIC['/current/learn/img/v05-columns.svg'] = ('web/current/learn/img/v05-columns.svg', 'image/svg+xml')
STATIC['/current/learn/img/v05-reservation-box.svg'] = ('web/current/learn/img/v05-reservation-box.svg', 'image/svg+xml')
STATIC['/current/learn/img/v05-sql-editor.svg'] = ('web/current/learn/img/v05-sql-editor.svg', 'image/svg+xml')
STATIC['/current/learn/img/v05-two-checks.svg'] = ('web/current/learn/img/v05-two-checks.svg', 'image/svg+xml')
STATIC['/current/learn/img/v06-private-window.svg'] = ('web/current/learn/img/v06-private-window.svg', 'image/svg+xml')
STATIC['/current/learn/img/v06-send-only.svg'] = ('web/current/learn/img/v06-send-only.svg', 'image/svg+xml')
STATIC['/current/learn/img/v06-two-promises.svg'] = ('web/current/learn/img/v06-two-promises.svg', 'image/svg+xml')
STATIC['/current/learn/img/v07-owner-inbox.svg'] = ('web/current/learn/img/v07-owner-inbox.svg', 'image/svg+xml')
STATIC['/current/learn/img/v07-replace-star.svg'] = ('web/current/learn/img/v07-replace-star.svg', 'image/svg+xml')
STATIC['/current/learn/img/v07-who-can.svg'] = ('web/current/learn/img/v07-who-can.svg', 'image/svg+xml')
STATIC['/current/learn/img/v08-four-items.svg'] = ('web/current/learn/img/v08-four-items.svg', 'image/svg+xml')
STATIC['/current/learn/img/v08-privacy-outline.svg'] = ('web/current/learn/img/v08-privacy-outline.svg', 'image/svg+xml')
STATIC['/current/learn/img/v08-retention-loop.svg'] = ('web/current/learn/img/v08-retention-loop.svg', 'image/svg+xml')
STATIC['/current/learn/img/v09-import-screen.svg'] = ('web/current/learn/img/v09-import-screen.svg', 'image/svg+xml')
STATIC['/current/learn/img/v09-plan-choice.svg'] = ('web/current/learn/img/v09-plan-choice.svg', 'image/svg+xml')
STATIC['/current/learn/img/v09-push-to-web.svg'] = ('web/current/learn/img/v09-push-to-web.svg', 'image/svg+xml')
STATIC['/current/learn/img/v09-rollback.svg'] = ('web/current/learn/img/v09-rollback.svg', 'image/svg+xml')
STATIC['/current/learn/img/v10-ask-help.svg'] = ('web/current/learn/img/v10-ask-help.svg', 'image/svg+xml')
STATIC['/current/learn/img/v10-care-rhythm.svg'] = ('web/current/learn/img/v10-care-rhythm.svg', 'image/svg+xml')
STATIC['/current/learn/img/v10-three-blocks.svg'] = ('web/current/learn/img/v10-three-blocks.svg', 'image/svg+xml')
STATIC['/current/learn/lessons/b01.json'] = ('web/current/learn/lessons/b01.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/b02.json'] = ('web/current/learn/lessons/b02.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/b03.json'] = ('web/current/learn/lessons/b03.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/b04.json'] = ('web/current/learn/lessons/b04.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/b05.json'] = ('web/current/learn/lessons/b05.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/b06.json'] = ('web/current/learn/lessons/b06.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/b07.json'] = ('web/current/learn/lessons/b07.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/b08.json'] = ('web/current/learn/lessons/b08.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/b09.json'] = ('web/current/learn/lessons/b09.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/b10.json'] = ('web/current/learn/lessons/b10.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/b11.json'] = ('web/current/learn/lessons/b11.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/b12.json'] = ('web/current/learn/lessons/b12.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/b13.json'] = ('web/current/learn/lessons/b13.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/b14.json'] = ('web/current/learn/lessons/b14.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/b15.json'] = ('web/current/learn/lessons/b15.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/b16.json'] = ('web/current/learn/lessons/b16.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/b17.json'] = ('web/current/learn/lessons/b17.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/b18.json'] = ('web/current/learn/lessons/b18.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/b19.json'] = ('web/current/learn/lessons/b19.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/b20.json'] = ('web/current/learn/lessons/b20.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/b21.json'] = ('web/current/learn/lessons/b21.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/b22.json'] = ('web/current/learn/lessons/b22.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/v01.json'] = ('web/current/learn/lessons/v01.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/v02.json'] = ('web/current/learn/lessons/v02.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/v03.json'] = ('web/current/learn/lessons/v03.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/v04.json'] = ('web/current/learn/lessons/v04.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/v05.json'] = ('web/current/learn/lessons/v05.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/v06.json'] = ('web/current/learn/lessons/v06.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/v07.json'] = ('web/current/learn/lessons/v07.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/v08.json'] = ('web/current/learn/lessons/v08.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/v09.json'] = ('web/current/learn/lessons/v09.json', 'application/json; charset=utf-8')
STATIC['/current/learn/lessons/v10.json'] = ('web/current/learn/lessons/v10.json', 'application/json; charset=utf-8')

class AdminError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class SettingsProblem(AdminError):
    """Connection settings (token/instance) are missing or malformed."""


class PermissionProblem(AdminError):
    """A private admin file failed its owner/permission check."""
    def __init__(self, message, elevated=False, redirected=False):
        super().__init__(message)
        self.elevated = elevated
        self.redirected = redirected


class PortProblem(AdminError):
    """The loopback listener could not be opened."""


# Windows reports socket errors with WSA codes, not the C errno values.
PORT_BUSY = {errno.EADDRINUSE, errno.EACCES, 10048, 10013}


def port_busy(error):
    return error.errno in PORT_BUSY or getattr(error, 'winerror', None) in (10048, 10013)


Unreadable = platform.Unreadable


def stamp(value=None):
    return datetime.fromtimestamp(time.time() if value is None else value, timezone.utc).isoformat(timespec="seconds")


Files = platform.files


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
                                       **({"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if platform.IS_WINDOWS else {"start_new_session": True}))
            try:
                raw, _ = process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                if platform.IS_WINDOWS: process.kill()
                else: os.killpg(process.pid, signal.SIGKILL)
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


def plist_schedule(data):
    """ilson start가 쓰는 plist 일정을 jobs.conf 표기로 바꾼다. 다른 형식은 None."""
    interval, calendar = data.get("StartInterval"), data.get("StartCalendarInterval")
    if type(interval) is int and calendar is None:
        return f"every {interval}"
    if interval is not None or not isinstance(calendar, dict) or not set(calendar) <= {"Weekday", "Hour", "Minute"}:
        return None
    hour, minute, weekday = calendar.get("Hour"), calendar.get("Minute"), calendar.get("Weekday")
    if type(hour) is not int or type(minute) is not int or not 0 <= hour < 24 or not 0 <= minute < 60:
        return None
    if weekday is None:
        return f"daily {hour:02d}:{minute:02d}"
    # launchd는 7도 일요일로 읽는다.
    return f"weekly {weekday % 7} {hour:02d}:{minute:02d}" if type(weekday) is int and 0 <= weekday <= 7 else None


class Box:
    profile = "box"
    def __init__(self, home, *, probe=None, user_home=None, clock=time.time, profile="box", vault=None):
        # Claude와 ilson doctor는 사용자가 진입한 경로를 신뢰 키로 기록한다.
        # macOS /var와 /private/var처럼 같은 폴더의 원래 경로도 확인한다.
        self.project_paths = {str(Path(home).absolute()), str(Path(home).resolve())}
        self.home = Path(home).resolve()
        self.profile = profile
        self.features = sorted(platform.features(profile))
        self.static = platform.COURSE_STATIC if profile == "course" else STATIC
        self.static_files = Files(Path(LIBRARY).parent) if profile == "course" else None
        self.license_lock = threading.Lock()
        self.license_cache = None
        self.license_clock = time.monotonic
        self.last_activity = time.monotonic()
        self.vault = platform.vault_root(self.home, vault) if profile == "course" else self.home / "vault"
        if profile == "course": self.project_paths = {str(self.vault.absolute()), str(self.vault.resolve())}
        release=self.home/'.updates/installed.json'
        self.release_info={k:v for k,v in json.loads(release.read_text()).items() if k in ('version','research_version')} if release.is_file() else {}
        from access_policy import require_owner
        self.company_policy = require_owner(self.home)
        self.files = Files(self.home)
        self.vault_files = Files(self.vault) if profile == "course" else self.files
        self.user_files = Files(user_home or Path.home())
        self.clock = clock
        self.probe = probe or Probe(self.home)
        self.resource_collector = None
        if "dashboard" in self.features:
            from resource_dashboard import Collector
            self.resource_collector = Collector(self.home)
        try:
            token, _ = self.files.text("state/web-admin/token", 200, private=True)
            instance, _ = self.files.text("state/web-admin/instance", 200, private=True)
        except FileNotFoundError:
            raise SettingsProblem("관리자 연결 설정이 없습니다. ilson admin start로 준비해주세요.") from None
        except platform.AccessProblem as error:
            raise PermissionProblem("관리자 연결 파일의 소유자·권한을 확인해주세요.", elevated=error.elevated,
                                    redirected=getattr(error, 'redirected', False)) from None
        except Unreadable:
            raise PermissionProblem("관리자 연결 파일을 안전하게 읽지 못했습니다.") from None
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,160}", token) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", instance):
            raise SettingsProblem("관리자 연결 설정 형식을 확인해주세요.")
        self.token, self.instance = token, instance
        self.cookie_name = "ilson_box_admin_" + hashlib.sha256(str(self.home).encode()).hexdigest()[:12]
        self.sessions = {}
        self.session_lock = threading.Lock()
        self.attempts = OrderedDict()
        self.secret_values = {token}
        self.secret_lock = threading.Lock()
        self._workspace = None
        self.workspace_lock = threading.Lock()
        self.opensource_catalog = None
        if "opensource" in self.features:
            from opensource_catalog import Catalog
            self.opensource_catalog = Catalog(self.files.read, clock=self.clock, redact=self.redact)

    def licensed(self):
        from license import evaluate
        def check():
            try: return bool(evaluate(self.home)[0])
            except (OSError, ValueError, TypeError): return False
        if self.profile != 'course': return check()
        with self.license_lock:
            now = self.license_clock()
            if self.license_cache is None or now - self.license_cache[0] >= 60:
                self.license_cache = (now, check())
            return self.license_cache[1]

    def course_overview(self):
        company, state, detail = self.company()
        if state != 'ok': detail = 'Claude 대화에서 실습 볼트의 CONTEXT.md에 회사 정보를 정리하세요.'
        claude, trust = self.probe.claude(), self.trust()
        licensed = self.licensed()
        return self.redact({'features': self.features, 'generated_at': stamp(self.clock()),
            'box': {'company_name': company, 'sandbox': False, 'setup_state': 'ready'},
            'checks': [{'id': 'claude', 'label': 'Claude 로그인', 'state': claude[0], 'detail': claude[1]},
                {'id': 'company', 'label': '회사 정보', 'state': state, 'detail': detail},
                {'id': 'trust', 'label': '실습 폴더 신뢰', 'state': trust[0], 'detail': trust[1]},
                {'id': 'license', 'label': '라이선스', 'state': 'ok' if licensed else 'attention',
                 'detail': '이용 권한을 확인했습니다.' if licensed else 'ilson license activate로 이용 권한을 확인하세요.'}],
            'jobs': [], 'limitations': ['강의판은 예약 없이 직접 실행합니다. 초안은 Claude 대화에서 저장하세요.']})

    def pending_drafts(self):
        rows = []
        try:
            for name, _, regular in sorted(self.vault_files.listdir(('reports', 'pending')))[:100]:
                if regular and name.endswith('.md') and not name.startswith('.'):
                    try:
                        text, _ = self.vault_files.text('reports/pending/' + name, REPORT_BYTES)
                        title = next((line[2:122] for line in text.splitlines()[:40] if line.startswith('# ')), name)
                        rows.append({'name': name, 'title': title})
                    except (OSError, Unreadable): pass
        except (OSError, Unreadable): pass
        return rows

    def workspace(self):
        with self.workspace_lock:
            if self._workspace is None:
                library = str(Path(__file__).resolve().parent)
                if library not in sys.path:
                    sys.path.insert(0, library)
                from mini_workspace import Workspace
                self._workspace = Workspace(self.home, self.files)
            return self._workspace

    def redact(self, value):
        with self.secret_lock:
            known = tuple(self.secret_values)
        if isinstance(value, str):
            for secret in known:
                value = value.replace(secret, "[비밀값 숨김]")
            value = re.sub(r"(?i)\bILSON(?:[-\s]*[A-Z2-7]){149}\b", "[비밀값 숨김]", value)
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
            if self.company_policy:
                text = self.company_policy.read('company/CONTEXT.md', 65536, company_only=True)[0].decode('utf-8')
            else:
                text, _ = self.vault_files.text("CONTEXT.md" if self.profile == "course" else "vault/CONTEXT.md", 65536)
            match = re.search(r"^- 회사명:[ \t]*([^\r\n]*)", text, re.MULTILINE)
            name = match[1].strip() if match else ""
            if not name or name.startswith("("):
                return "우리 회사", "attention", "회사 정보가 비어 있습니다. ilson chat에서 /onboard로 인터뷰를 시작하세요."
            return name[:120], "ok", "회사 이름이 기록되어 있습니다."
        except FileNotFoundError:
            return "우리 회사", "attention", "회사 소개가 없습니다. ilson setup 후 회사 인터뷰를 진행하세요."
        except (OSError, ValueError, UnicodeError, Unreadable):
            return "우리 회사", "unknown", "회사 정보 파일을 확인하지 못했습니다."

    def trust(self):
        try:
            raw, _ = self.user_files.text(".claude.json", 4 * 1024 * 1024)
            data = json.loads(raw)
            projects = data.get("projects") if isinstance(data, dict) else None
            if not isinstance(projects, dict):
                return "unknown", "Claude 폴더 신뢰 설정을 확인하지 못했습니다."
            if self.profile == 'course':
                import ntpath
                matches = self.project_paths
                if platform.IS_WINDOWS:
                    matches = {ntpath.normcase(ntpath.normpath(p)) for p in matches}
                for key, value in projects.items():
                    if not isinstance(key, str): continue
                    normal = ntpath.normcase(ntpath.normpath(key)) if platform.IS_WINDOWS else key
                    if normal in matches and isinstance(value, dict) and value.get('hasTrustDialogAccepted') is True:
                        return 'ok', '실습 폴더의 Claude 신뢰 설정을 확인했습니다.'
                return 'unknown', '실습 폴더에서 Claude Code를 열어 폴더 신뢰를 직접 확인하세요.'
            if any(isinstance(projects.get(path), dict)
                   and projects[path].get("hasTrustDialogAccepted") is True
                   for path in self.project_paths):
                return "ok", "이 Box 폴더의 Claude 신뢰 설정을 확인했습니다."
            return "attention", "터미널에서 ilson chat을 열고 폴더 신뢰를 확인하세요."
        except FileNotFoundError:
            if self.profile == "course": return "unknown", "실습 폴더에서 Claude Code를 열어 폴더 신뢰를 직접 확인하세요."
            return "attention", "터미널에서 ilson chat을 처음 열어 폴더 신뢰를 확인하세요."
        except (Unreadable, ValueError):
            return "unknown", "Claude 폴더 신뢰 설정을 읽지 못했습니다."

    def registered_schedule(self, name):
        """launchd에 실제 등록된 이 Box의 일정. ilson start가 복사한 LaunchAgents 사본을 읽는다."""
        try:
            raw, _ = self.user_files.read(f"Library/LaunchAgents/com.ilson.{name}.plist", 65536)
            data = plistlib.loads(raw)
            environment = data.get("EnvironmentVariables") if isinstance(data, dict) else None
            box = environment.get("ILSON_HOME") if isinstance(environment, dict) else None
            # 같은 이름의 다른 Box 등록은 이 Box의 일정으로 보이지 않는다.
            if not isinstance(box, str) or box not in self.project_paths or data.get("Label") != f"com.ilson.{name}":
                return None
            return schedule_label(plist_schedule(data) or "")
        # 참고용 표시다. 손상된 plist(잘못된 날짜·깊은 중첩 등)의 어떤 예외도 화면을 깨뜨리지 않고 설정 일정으로 돌아간다.
        except Exception:
            return None

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
            paused = not sandbox and self.files.marker(f"state/paused.{name}") is True
            loaded = None if registered is None else "com.ilson." + name in registered
            registration = "sandbox" if sandbox else "paused" if paused else ("unknown" if loaded is None else ("loaded" if loaded else "not_loaded"))
            labels = {"loaded": "예약 등록 확인", "not_loaded": "등록되지 않음", "unknown": "등록 상태 확인 불가",
                      "sandbox": "샌드박스 · 실행하지 않음", "paused": "멈춤"}
            # 일정은 jobs.conf가 아니라 실제 등록된 plist 기준이다. 읽지 못하면 설정값을 쓴다.
            actual = None if sandbox else self.registered_schedule(name)
            note = None
            if paused and loaded:
                note = f"멈춤으로 기록됐지만 아직 예약에 남아 있어요 · 터미널에서 다시 멈추기: 「ilson pause {name}」"
            elif not paused and actual and actual != schedule:
                # 기본 관리 업무의 다시 등록 절차는 template/CLAUDE.md 에 있다.
                again = ("기본 관리 업무라 ilson chat에서 다시 등록을 요청하세요" if name in BASE_JOBS
                         else f"다시 등록해야 적용돼요: 「ilson pause {name}」 후 「ilson resume {name}」")
                note = f"설정이 바뀌었어요 · 지금은 등록된 일정({actual})으로 돌아요. {again}"
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
            rows.append({"id": name, "label": label, "schedule": actual or schedule, "configured_schedule": schedule,
                         "registered_schedule": actual, "schedule_note": note, "registration": registration,
                         "registration_label": labels[registration], "last_success_at": last,
                         "last_success_state": state, "execution_state": "unknown",
                         "execution_label": "현재 실행 중인지와 최근 실패 여부는 이 기록으로 알 수 없습니다."})
        return rows, notices

    def overview(self):
        if self.profile == "course": return self.course_overview()
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
        return self.redact({"features": self.features, "generated_at": stamp(self.clock()), "box": {"company_name": company, "sandbox": sandbox,
                            "setup_state": setup_state, "timezone": datetime.now().astimezone().tzname()},
                           "checks": checks, "telegram": telegram, "jobs": jobs,
                           "limitations": notices + ["마지막 성공 기록만으로 현재 실행 중·최근 실패·알림 도착 여부를 확정하지 않습니다.",
                                                       "리서치·지식·SNS·서류함은 각 메뉴에서 처리합니다. 기존 예약 업무 설정은 ilson chat에서 변경하세요."]})

    def report_candidates(self):
        if self.company_policy:
            return (self.company_policy.files('company/reports', suffix='.md', limit=REPORT_LIMIT + 1) +
                    self.company_policy.files('management/reports', suffix='.md', limit=REPORT_LIMIT + 1)), False
        rows, limited, visited = [], False, 0

        def scan(parts, depth):
            nonlocal limited, visited
            if depth > REPORT_DEPTH or visited >= SCAN_LIMIT:
                limited = True
                return
            try:
                names = []
                for name, directory, file in self.vault_files.listdir(parts):
                    visited += 1
                    if visited > SCAN_LIMIT:
                        limited = True
                        break
                    if not name.startswith('.'):
                        names.append((name, directory, file))
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
        scan(("reports",) if self.profile == "course" else ("vault", "reports"), 0)
        return rows, limited

    def report_index(self):
        self.telegram()  # 보고서에 실수로 포함된 저장 토큰도 응답 전에 숨긴다.
        candidates, limited = self.report_candidates()
        rows = []
        for relative in candidates:
            try:
                if self.company_policy:
                    raw, info = self.company_policy.read(relative, REPORT_BYTES)
                    text = raw.decode('utf-8')
                else:
                    text, info = self.vault_files.text(relative, REPORT_BYTES)
            except (OSError, ValueError, UnicodeError, Unreadable):
                limited = True
                continue
            path = Path(relative)
            title = path.stem[:120]
            # run-job 의 report_heading 과 같은 규칙: 앞 BOM을 빼고 40줄 안의 '# 제목'을 찾는다.
            for line in text.removeprefix("\ufeff").splitlines()[:40]:
                if line.startswith("# ") and line[2:].strip():
                    title = line[2:].strip()[:120]
                    break
            category = {"briefing": "아침 브리핑", "weekly": "주간 보고", "pending": "승인 대기 초안"}.get(path.parts[-2] if len(path.parts) > (2 if self.profile == "course" else 3) else "", "업무 보고")
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
                    if self.company_policy:
                        raw, _ = self.company_policy.read(relative, REPORT_BYTES)
                        text = raw.decode('utf-8')
                    else:
                        text, _ = self.vault_files.text(relative, REPORT_BYTES)
                except (OSError, ValueError, UnicodeError, Unreadable):
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

    def peers_info(self):
        try:
            text, _ = self.files.text("state/web-admin/peers.json", 16384)
            data = json.loads(text)
        except (FileNotFoundError, Unreadable, ValueError, OSError):
            return None
        if not isinstance(data, dict):
            return None

        def clean_text(value, limit):
            if not isinstance(value, str):
                return ""
            value = re.sub(r"[\x00-\x1f\x7f]+", " ", value).strip()
            return self.redact(value)[:limit]

        def valid_peer_url(raw):
            if not isinstance(raw, str) or len(raw) > 256 or any(ord(c) < 33 or ord(c) == 127 for c in raw):
                return None
            try:
                parsed = urlsplit(raw)
            except ValueError:
                return None
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                return None
            host = (parsed.hostname or "").lower()
            if not host:
                return None
            if parsed.scheme == "https":
                pass
            elif parsed.scheme == "http" and host in ("127.0.0.1", "localhost"):
                pass
            else:
                return None
            try:
                port = parsed.port
            except ValueError:
                return None
            if port is not None and not (1 <= port <= 65535):
                return None
            origin = f"{parsed.scheme}://{host}" + (f":{port}" if port else "")
            return origin

        peers = []
        raw_peers = data.get("peers")
        if isinstance(raw_peers, list):
            seen = set()
            for item in raw_peers[:8]:
                if not isinstance(item, dict):
                    continue
                pid = clean_text(item.get("id"), 32)
                name = clean_text(item.get("name"), 40)
                sub = clean_text(item.get("subtitle"), 60)
                url = valid_peer_url(item.get("url"))
                if not name or not url or url in seen:
                    continue
                seen.add(url)
                peers.append({"id": pid or f"peer-{len(peers)+1}", "name": name, "subtitle": sub, "url": url, "current": bool(item.get("current"))})
        if not peers:
            return None
        cur = data.get("current") if isinstance(data.get("current"), dict) else None
        current = None
        if cur:
            cname = clean_text(cur.get("name"), 40)
            if cname:
                current = {"id": clean_text(cur.get("id"), 32), "name": cname, "subtitle": clean_text(cur.get("subtitle"), 60)}
        if current is None:
            matched = next((p for p in peers if p.get("current")), None)
            if matched:
                current = {"id": matched["id"], "name": matched["name"], "subtitle": matched["subtitle"]}
        return {"current": current, "peers": peers}

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
        if platform.IS_WINDOWS:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        TCPServer.server_bind(self)
        self.server_name = "localhost"
        self.server_port = self.server_address[1]

    def __init__(self, box, port):
        self.box = box
        if platform.IS_WINDOWS: self.allow_reuse_address = False
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
        request_path = urlsplit(self.path).path
        frameable = request_path == "/" or request_path.startswith("/current/pack-library/")
        self.send_header("X-Frame-Options", "SAMEORIGIN" if frameable else "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        policy = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        if urlsplit(self.path).path.startswith('/current/'):
            policy = policy.replace("img-src 'self' data:", "img-src 'self' data: https:; media-src 'self' https:")
        if frameable:
            policy = policy.replace("frame-ancestors 'none'", "frame-ancestors 'self'")
        if content_type == "image/svg+xml":
            # 그림을 주소창에서 직접 열어도 스크립트·외부 자원이 동작하지 않게 한다.
            policy = "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; sandbox"
        self.send_header("Content-Security-Policy", policy)
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
        callback_path = urlsplit(self.path).path
        callback = self.server.box.profile == 'box' and self.command == 'GET' and re.fullmatch(r'/api/oauth/callback/(threads|instagram|facebook)', callback_path)
        callback_host = bool(callback and len(hosts) == 1 and self.current_ui().oauth.callback_host(hosts[0], callback_path))
        if len(hosts) != 1 or (hosts[0].lower() not in self.server.hosts and not callback_host):
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
        if parsed.fragment or (parsed.query and not (unquote(parsed.path) in STATIC and parsed.path.startswith("/current/") or parsed.path == "/api/sns-operations" or re.fullmatch(r"/api/oauth/callback/(threads|instagram|facebook)", parsed.path))):
            raise AdminError("요청 주소를 확인해주세요.", 404)
        return unquote(parsed.path)

    def require_session(self, message=None):
        if not self.server.box.authenticated(self.session()):
            raise AdminError(message or "연결이 필요합니다. 터미널에서 ilson open으로 열어주세요.", 401)
        self.server.box.last_activity = time.monotonic()

    def body(self, limit=BODY_LIMIT):
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise AdminError("JSON 요청이 필요합니다.", 415)
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,8}", lengths[0]):
            raise AdminError("요청 길이를 확인해주세요.")
        size = int(lengths[0])
        if not 0 < size <= limit:
            raise AdminError("요청 크기를 확인해주세요.", 413)
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise AdminError("요청이 완료되지 않았습니다.")
        return parse_json(raw)

    def guarded(self, callback):
        try:
            if self.server.box.profile == "course" and not platform.course_route(self.command, unquote(urlsplit(self.path).path)):
                raise AdminError("페이지를 찾을 수 없습니다.", 404)
            self.boundary()
            approval_path = urlsplit(self.path).path
            usage_safe = ((self.command in ('GET', 'HEAD') and approval_path in ('/usage-history', '/usage-history.js', '/usage-history.css', '/api/usage-history/summary')) or
                          (self.command == 'POST' and approval_path in ('/api/usage-history/off', '/api/usage-history/export', '/api/usage-history/delete-local', '/api/usage-history/unlink')))
            session_safe = approval_path == '/api/session' or (self.server.box.profile == 'course' and approval_path in ('/api/admin/shutdown', '/api/logout'))
            # The offline privacy page uses the same shell assets. Static UI
            # code/styles/fonts carry no account data; APIs keep their license gates.
            shell_asset = (self.command in ('GET', 'HEAD') and approval_path in self.server.box.static
                           and self.server.box.static[approval_path][1].split(';', 1)[0] in
                           ('text/css', 'application/javascript', 'font/woff2'))
            if usage_safe or session_safe or shell_asset:
                licensed = True  # Local privacy controls never renew/check a network license.
            else:
                licensed = self.server.box.licensed()
            approval_safe = ((self.command in ('GET', 'HEAD') and approval_path in ('/approval', '/approval.js', '/api/approvals', '/api/session')) or (self.command == 'POST' and approval_path in ('/api/session', '/api/approvals/reject')))
            if not licensed and approval_path not in ('/health', '/api/health') and not approval_safe:
                if self.command in ('GET', 'HEAD') and not urlsplit(self.path).path.startswith('/api/'):
                    return self.reply(200, '<!doctype html><meta charset="utf-8"><title>일손 라이선스</title><h1>일손 라이선스가 필요합니다</h1><p>터미널에서 ilson license activate 를 실행하세요.</p><p><a id="approval" href="/approval">승인 대기함 보기·취소</a></p><p><a id="usage-history" href="/usage-history">내 AI 사용 기록 보기·끄기·내보내기·삭제</a></p><script>for(const id of ["approval","usage-history"])document.getElementById(id).href+=location.hash</script>'.encode(), 'text/html; charset=utf-8')
                if approval_path.startswith('/api/opensource/'):
                    return self.reply(403, {'error':'일손 라이선스가 필요합니다. 이용 권한을 확인해 주세요.'})
                return self.reply(403, {'error':'라이선스가 필요합니다. ilson license activate를 실행하세요.'})
            if urlsplit(self.path).path in ('/health','/api/health'):callback()
            else:
                from runtime_gate import running
                with running(self.server.box.home):callback()
        except BlockingIOError:
            self.reply(503, {'error':'업데이트 적용 중입니다. 잠시 후 새로고침하세요.'})
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
        if re.fullmatch(r'/api/oauth/callback/(threads|instagram|facebook)', path):
            if self.command != 'GET':
                raise AdminError('인증 콜백은 GET 요청만 허용합니다.', 405)
            from urllib.parse import parse_qs
            from mini_workspace import WorkspaceError
            params = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
            if any(len(values) != 1 for values in params.values()):
                raise AdminError('인증 응답 형식을 확인하세요.', 400)
            try:
                self.current_ui().oauth.finish(path.rsplit('/', 1)[-1], {k:v[0] for k,v in params.items()})
                return self.reply(200, '<!doctype html><meta charset="utf-8"><title>일손 SNS 연결</title><h1>계정 연결을 확인했습니다.</h1><p>원래 일손 화면으로 돌아가세요.</p>'.encode(), 'text/html; charset=utf-8')
            except WorkspaceError as error:
                raise AdminError(str(error), error.status) from None
        if path in {"/api/health", "/health"}:
            return self.reply(200, {"service": SERVICE, "instance": self.server.box.instance, "release":self.server.box.release_info, **({"pid": os.getpid(), "source_digest": getattr(self.server, "source_digest", "")} if self.server.box.profile == "course" else {})})
        if path in self.server.box.static:
            relative, kind = self.server.box.static[path]
            try:
                # 한글 전체 글리프가 있는 고정 Pretendard 파일(2,057,688 B)만큼 허용한다.
                # 폰트도 위 정확한 경로만 서빙하며 일반 정적 파일·보고서 상한은 유지한다.
                limit = 2 * 1024 * 1024 if kind == "font/woff2" else 1024 * 1024
                raw, _ = (self.server.box.static_files or self.server.box.files).read(relative, limit)
            except (FileNotFoundError, Unreadable):
                raise AdminError("관리자 화면 파일이 없습니다. ilson setup으로 갱신해주세요.", 404) from None
            return self.reply(200, raw, kind)
        self.require_session('접속이 만료되었습니다. 다시 연결해 주세요.' if path.startswith('/api/opensource/') else None)
        if path == '/api/opensource/catalog' or path.startswith('/api/opensource/repos/'):
            from access_policy import require_owner, AccessDenied
            try:
                require_owner(self.server.box.home)
            except AccessDenied:
                raise AdminError('오픈소스 메뉴는 회사 대표만 사용할 수 있습니다.', 403) from None
            repo_id = None
            if path != '/api/opensource/catalog':
                repo_id = path.removeprefix('/api/opensource/repos/')
                if not re.fullmatch(r'[a-f0-9]{32}', repo_id):
                    raise AdminError('자료를 찾을 수 없습니다.', 404)
            result = self.server.box.opensource_catalog.snapshot(repo_id)
            return self.reply(404 if result['state'] == 'unavailable' else 200, result)
        if path == '/api/inbox-files':
            from inbox_files import list_files
            return self.reply(200, {'files':list_files(self.server.box.home)})
        if self.server.box.profile == "box":
            from current_ui import handles
        else:
            handles = lambda path: False
        if re.fullmatch(r'/api/motion/projects/[a-f0-9]{32}/download',path):
            from motion_pack import asset
            from mini_workspace import WorkspaceError
            try: return self.reply(200,asset(self.server.box.home,path.split('/')[-2],'output.mp4'),'video/mp4')
            except WorkspaceError as error: raise AdminError(str(error),error.status) from None
        if handles(path):
            return self.current_request("GET", path)
        if path == "/api/approvals":
            import approval_store as store
            from approval_actions import load_all
            load_all(profile=self.server.box.profile)
            rows = store.list_requests(self.server.box.home)
            for row in rows:
                visible = [row['body'], row['title'], *row['target'].values()]
                row['local_context'] = None
                row['context_error'] = False
                action = store._ACTIONS.get(row['action_type'])
                if action and action[2] is not None:
                    try:
                        context = action[2](store.approval_request(row))
                        if context is not None and (not isinstance(context, str) or len(context) > 256000):
                            raise ValueError('invalid local context')
                        row['local_context'] = context
                        if context is not None:
                            visible.append(context)
                    except Exception:
                        row['context_error'] = True
                row['review_blocked'] = row['context_error'] or any(self.server.box.redact(value) != value for value in visible)
            return self.reply(200, {"requests": rows, "drafts": self.server.box.pending_drafts() if self.server.box.profile == "course" else []})
        if path == "/api/session":
            peers = self.server.box.peers_info()
            payload = {"authenticated": True, "features": self.server.box.features, "profile": self.server.box.profile}
            if peers:
                payload["peers"] = peers
            return self.reply(200, payload)
        if path == "/api/peers":
            return self.reply(200, self.server.box.peers_info() or {"current": None, "peers": []})
        if path.startswith("/api/workspace/"):
            return self.workspace_request("GET", path)
        if path == "/api/usage-history/summary":
            return self.usage_request(path)
        if path == "/api/usage":
            from usage_dashboard import dashboard as usage_dashboard
            return self.reply(200, usage_dashboard(self.server.box.home))
        if path == "/api/dashboard":
            from resource_dashboard import dashboard
            return self.reply(200, dashboard(self.server.box, self.server.box.resource_collector))
        if path == "/api/overview":
            return self.reply(200, self.server.box.overview())
        if path == "/api/reports":
            return self.reply(200, self.server.box.reports())
        if path.startswith("/api/reports/"):
            return self.reply(200, self.server.box.report(path.removeprefix("/api/reports/")))
        raise AdminError("페이지를 찾을 수 없습니다.", 404)

    def do_POST(self):
        self.guarded(self.post)

    def usage_request(self, path):
        self.require_session()
        from access_policy import require_owner, AccessDenied
        from usage_timeline import Ledger, UsageError
        import sqlite3
        try:
            require_owner(self.server.box.home)
            ledger = Ledger(self.server.box.home, user_home=self.server.box.user_files.home, clock=self.server.box.clock)
            if self.command in ('GET', 'HEAD') and path == '/api/usage-history/summary':
                return self.reply(200, ledger.summary())
            data = self.body()
            action = path.removeprefix('/api/usage-history/')
            if not isinstance(data, dict):
                raise UsageError('설정을 확인하세요.')
            if action == 'on' and set(data) == {'workspace', 'timezone', 'backfill_from', 'consent'} and data['consent'] is True:
                if not isinstance(data['workspace'], str) or not isinstance(data['timezone'], str) or (data['backfill_from'] is not None and not isinstance(data['backfill_from'], str)):
                    raise UsageError('실습 폴더와 시간대를 확인하세요.')
                ledger.on(data['workspace'], data['timezone'], backfill=data['backfill_from'])
                result = ledger.collect()
            elif action in ('off', 'collect', 'delete-local', 'export', 'unlink', 'sync') and not data:
                if action == 'off': ledger.off()
                elif action == 'collect': ledger.collect()
                elif action == 'delete-local': ledger.delete_local()
                elif action == 'export':
                    from usage_sync import validate_payload
                    payload = ledger.payload()
                    if payload is not None:
                        from datetime import date
                        validate_payload(payload, date.fromisoformat(ledger.summary()['today']), linked=False)
                    return self.reply(200, payload if payload is not None else b'null')
                else:
                    from usage_sync import Client
                    if action == 'unlink': Client(ledger).unlink()
                    else:
                        ledger.collect()
                        Client(ledger).sync()
                result = ledger.summary()
            elif action == 'link' and set(data) == {'base_url', 'code', 'consent', 'preview_revision'} and data['consent'] is True:
                if not isinstance(data['code'], str) or not isinstance(data['base_url'], str) or type(data['preview_revision']) is not int or ledger.config().get('revision') != data['preview_revision']:
                    raise UsageError('기록이 바뀌었습니다. 전송 JSON을 다시 확인하세요.')
                from usage_sync import Client
                result = Client(ledger).link(data['base_url'], data['code'])
            else:
                raise UsageError('지원하는 사용 기록 요청을 확인하세요.')
            return self.reply(200, result)
        except AccessDenied:
            raise AdminError('사용 기록은 본인 개인 관리자에서만 확인할 수 있습니다.', 403) from None
        except UsageError as error:
            raise AdminError(str(error), 400) from None
        except (OSError, ValueError, sqlite3.Error):
            raise AdminError('사용 기록을 처리하지 못했습니다. 개인 권한과 연결 상태를 확인하세요.', 503) from None

    def workspace_request(self, method, path):
        work = self.server.box.workspace()
        from mini_workspace import WorkspaceError
        try:
            data = self.body(limit=2900000 if path == '/api/workspace/people/avatar' else 400000) if method == "POST" else None
            if method == 'GET' and path.startswith('/api/workspace/people/avatar/'):
                return self.reply(200,work.people.avatar_image(path.removeprefix('/api/workspace/people/avatar/')),'image/jpeg')
            if path == '/api/workspace/people/registry' and method == 'GET':
                rows, notices = self.server.box.jobs(self.server.box.files.marker('state/sandbox') is not False)
                reports, limited = self.server.box.report_index()
                for row in rows:
                    # run-job.sh의 고정 출력 계약만 연결한다. 이름 유사도로 다른 업무 서류를 연결하지 않는다.
                    row['reports'] = [meta for meta,relative in reports if row['id'] in ('briefing','weekly') and relative.startswith('vault/reports/'+row['id']+'/')]
                if limited: notices.append('일부 정기 업무 결과 서류를 읽지 못했거나 조회 한도를 넘었습니다.')
                return self.reply(200, self.server.box.redact({'jobs':rows,'notices':notices}))
            if path == '/api/workspace/people/schedules' and method == 'POST':
                rows, _ = self.server.box.jobs(self.server.box.files.marker('state/sandbox') is not False)
                ids = data.get('schedule_ids') if isinstance(data,dict) else None
                if not isinstance(ids,list) or any(not isinstance(v,str) or v not in {r['id'] for r in rows} for v in ids):
                    raise WorkspaceError('현재 설치에 등록된 정기업무만 연결하세요.')
            result = work.handle(method, path.removeprefix("/api/workspace"), data)
            return self.reply(200, result)
        except AdminError:
            raise
        except WorkspaceError as error:
            raise AdminError(str(error), error.status) from None
        except Exception:
            print("일손 업무 요청 실패: 연결·업무 저장 상태를 확인하세요.", file=sys.stderr)
            raise AdminError("업무 요청을 완료하지 못했습니다. 연결·입력·저장 상태를 확인하세요.", 503) from None

    def current_ui(self):
        from current_ui import CurrentUI
        work = self.server.box.workspace()
        with work.lock:
            if not hasattr(work, 'current_ui'):
                work.current_ui = CurrentUI(work)
        return work.current_ui

    def current_request(self, method, path):
        from mini_workspace import WorkspaceError
        current = self.current_ui()
        try:
            from research.image_normalize import MAX_UPLOAD_JSON
            data = self.body(limit=MAX_UPLOAD_JSON if path=='/api/research/image' else 400000) if method == "POST" else None
            return self.reply(200, current.dispatch(method, path, urlsplit(self.path).query, data))
        except WorkspaceError as error:
            raise AdminError(str(error), error.status) from None
        except Exception:
            print("기존 일손 화면 요청 실패: 실행 환경을 확인하세요.", file=sys.stderr)
            raise AdminError("업무를 완료하지 못했습니다. 실행 도구·인증·저장 상태를 확인하세요.", 503) from None

    def inbox_request(self, path):
        from inbox_files import InboxError, inspect
        from inbox_extract import extract
        from inbox_review import read_draft, approve
        import base64
        try:
            data = self.body(limit=50000)
            if not isinstance(data, dict):
                raise InboxError('입력을 확인하세요.')
            if path == '/api/inbox-files/preview' and set(data) == {'name','sha256','page'}:
                meta, image = inspect(self.server.box.home, data['name'])
                if meta['sha256'] != data['sha256']:
                    raise InboxError('파일이 바뀌었습니다. 다시 확인하세요.')
                if meta['format']=='PDF':
                    from inbox_pdf import render_pdf
                    image = render_pdf(image, data['page'])
                elif data['page'] != 1 or isinstance(data['page'],bool):
                    raise InboxError('쪽수를 확인하세요.')
                result = {'kind':'pdf' if meta['format']=='PDF' else 'image','image':base64.b64encode(image).decode('ascii')}
            elif path == '/api/inbox-files/extract' and set(data) == {'name','sha256','consent'}:
                result = extract(self.server.box.home, data['name'], data['sha256'], data['consent'])
            elif path == '/api/inbox-files/draft' and set(data) == {'sha256'}:
                result = read_draft(self.server.box.home, data['sha256'])
            elif path == '/api/inbox-files/approve' and set(data) == {'sha256','text','category','confirmed'}:
                result = approve(self.server.box.home, data['sha256'], data['text'], data['category'], data['confirmed'])
            else:
                raise InboxError('요청을 확인하세요.')
            return self.reply(200,result)
        except InboxError as error:
            raise AdminError(str(error), 400) from None
        except Exception:
            raise AdminError('요청을 완료하지 못했습니다. 원본은 보존됩니다.', 503) from None

    def approval_request(self, path):
        import approval_store as store
        import approval_dispatch as dispatch
        from approval_actions import load_all
        load_all(profile=self.server.box.profile)
        data = self.body()
        if not isinstance(data, dict):
            raise AdminError('요청 형식을 확인해 주세요.')
        home = self.server.box.home
        if path == '/api/approvals/create':
            name = data.get('name')
            if not isinstance(name, str) or not name.endswith('.md') or Path(name).name != name:
                raise AdminError('대기 중인 초안 파일 이름을 확인해 주세요.')
            if self.server.box.company_policy:
                try:
                    body = self.server.box.company_policy.read('management/reports/pending/' + name, 256000)[0].decode('utf-8')
                    request_id = store.request_approval('local_note', {'channel': 'local_note', 'account': 'local', 'object_id': name}, name, body, home=home)
                except (OSError, ValueError):
                    raise AdminError('초안을 읽지 못했습니다.') from None
                return self.reply(200, {'id': request_id})
            vault = self.server.box.vault
            pending = vault / 'reports/pending'
            if any(p.is_symlink() for p in (vault, vault / 'reports', pending, pending / name)):
                raise AdminError('초안 경로를 확인해 주세요.')
            try:
                if not (pending / name).is_file() or (pending / name).stat().st_size > 256000:
                    raise ValueError('invalid draft')
                body = self.server.box.vault_files.text('reports/pending/' + name, 256000)[0] if self.server.box.profile == 'course' else (pending / name).read_text(encoding='utf-8')
                request_id = store.request_approval('local_note', {'channel': 'local_note', 'account': 'local', 'object_id': name}, name, body, home=home)
            except (OSError, UnicodeError, ValueError):
                raise AdminError('초안을 읽지 못했습니다. 파일과 크기를 확인해 주세요.') from None
            return self.reply(200, {'id': request_id})
        request_id = data.get('id')
        if not isinstance(request_id, str) or not re.fullmatch('[a-f0-9]{32}', request_id):
            raise AdminError('승인 요청을 확인해 주세요.')
        if path == '/api/approvals/run':
            return self.reply(200, {'status': dispatch.dispatch(request_id, home, vault=self.server.box.vault, profile=self.server.box.profile, license_check=self.server.box.licensed if self.server.box.profile == "course" else None)})
        if path == '/api/approvals/send':
            from approval_telegram import TelegramError, send_card
            try:
                req = store.get(request_id, home)
                if not req or any(self.server.box.redact(value) != value for value in [req['body'], req['title'], *req['target'].values()]):
                    raise TelegramError('sensitive content')
                send_card(home, request_id, consent=data.get('consent') is True)
                return self.reply(200, {'ok': True})
            except (TelegramError, OSError, ValueError):
                raise AdminError('휴대폰 승인 요청을 보내지 못했습니다. 연결과 내용을 확인해 주세요.') from None
        decisions = {'/api/approvals/approve': 'approved', '/api/approvals/change': 'changed', '/api/approvals/reject': 'rejected'}
        if path not in decisions:
            raise AdminError('지원하지 않는 요청입니다.', 404)
        if decisions[path] == 'approved':
            req = store.get(request_id, home)
            if not req or any(self.server.box.redact(value) != value for value in [req['body'], req['title'], *req['target'].values()]):
                raise AdminError('숨겨진 내용이 있어 승인할 수 없습니다. 초안을 수정한 뒤 다시 요청하세요.')
        if not store.decide(request_id, decisions[path], 'local', home=home):
            raise AdminError('이미 처리되었거나 만료된 요청입니다.', 409)
        status = dispatch.dispatch(request_id, home, vault=self.server.box.vault, profile=self.server.box.profile, license_check=self.server.box.licensed if self.server.box.profile == "course" else None) if decisions[path] == 'approved' else decisions[path]
        return self.reply(200, {'status': status})

    def post(self):
        path = self.route()
        if path == '/api/admin/shutdown' and self.server.box.profile == 'course':
            self.require_session()
            if self.body(): raise AdminError('중지 요청을 확인하세요.')
            self.reply(200, {'ok': True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if path == '/api/replies/draft' and self.server.box.profile == 'course':
            self.require_session()
            data = self.body(limit=12000)
            if set(data) != {'text', 'consent'}: raise AdminError('입력을 확인하세요.')
            from replies_draft import draft
            try: return self.reply(200, draft(data['text'], consent=data['consent'], home=self.server.box.vault))
            except ValueError as error: raise AdminError(str(error)) from None
        if path.startswith("/api/usage-history/"):
            return self.usage_request(path)
        if path.startswith('/api/approvals/'):
            self.require_session()
            return self.approval_request(path)
        if path in ('/api/replies/connection', '/api/replies/collect', '/api/replies/draft', '/api/replies/install', '/api/replies/request', '/api/replies/schedule', '/api/replies/drafts', '/api/replies/disconnect'):
            self.require_session()
            import replies_service as service
            try:
                data = self.body(limit=12000)
                action = {'/api/replies/connection': service.save_connection,
                          '/api/replies/collect': service.fetch_questions,
                          '/api/replies/draft': service.manual_draft,
                          '/api/replies/install': service.install_connection_runtime,
                          '/api/replies/request': service.request_answer,
                          '/api/replies/schedule': service.schedule,
                          '/api/replies/drafts': service.list_drafts,
                          '/api/replies/disconnect': service.disconnect}[path]
                return self.reply(200, action(self.server.box.home, data))
            except Exception:
                raise AdminError('요청을 완료하지 못했습니다. 입력과 연결 상태를 확인해 주세요.', 400) from None
        if path.startswith('/api/inbox-files/'):
            self.require_session()
            return self.inbox_request(path)
        if self.server.box.profile == "box":
            from current_ui import handles
        else:
            handles = lambda path: False
        if handles(path):
            self.require_session()
            return self.current_request("POST", path)
        if path.startswith("/api/workspace/"):
            self.require_session()
            # 요청이 실행 모듈을 불러오기 전에 세션과 출처부터 검증한다.
            self.server.box.workspace()
            return self.workspace_request("POST", path)
        if path == "/api/usage":
            self.require_session()
            from usage_observer import enable, disable, state_dir, write_json, number
            data = self.body()
            if not isinstance(data, dict):
                raise AdminError("설정을 확인해주세요.")
            try:
                action = data.get('action')
                if action == 'enable' and set(data) == {'action'}:
                    enable(self.server.box.home)
                elif action == 'disable' and set(data) == {'action'}:
                    disable(self.server.box.home)
                elif action == 'alerts' and set(data) == {'action', 'enabled', 'threshold'} and type(data['enabled']) is bool and number(data['threshold'], 1, 100) is not None:
                    write_json(state_dir(self.server.box.home) / 'alerts.json', {'enabled': data['enabled'], 'threshold': data['threshold']})
                else:
                    raise AdminError("설정을 확인해주세요.")
            except ValueError as error:
                raise AdminError(str(error)) from None
            from usage_dashboard import dashboard as usage_dashboard
            return self.reply(200, usage_dashboard(self.server.box.home))
        if path == "/api/session":
            data = self.body()
            if set(data) != {"token"}:
                raise AdminError("연결 요청 형식을 확인해주세요.")
            session = self.server.box.login(data["token"])
            self.server.box.last_activity = time.monotonic()
            peers = self.server.box.peers_info()
            payload = {"ok": True, "features": self.server.box.features, "profile": self.server.box.profile}
            if peers:
                payload["peers"] = peers
            return self.reply(200, payload, cookie=self.cookie(session, SESSION_SECONDS))
        if path == "/api/logout":
            self.require_session()
            if self.body():
                raise AdminError("로그아웃 요청 형식을 확인해주세요.")
            self.server.box.logout(self.session())
            return self.reply(200, {"ok": True}, cookie=self.cookie("", 0))
        raise AdminError("지원하지 않는 요청입니다.", 404)


def course_server(args):
    from course_admin import private_home
    home, private = private_home(args.home)
    if args.vault is None or not args.vault.is_absolute() or not args.vault.is_dir(): raise AdminError('실습 볼트를 확인하세요.')
    platform.safe_path(args.vault)
    os.environ.update(ILSON_HOME=str(home), ILSON_PROFILE='course', ILSON_COURSE_VAULT=str(args.vault))
    fd = platform.acquire_lock(private / 'server.lock')
    code_lock = None
    server = None
    stopped = threading.Event()
    try:
        code_lock = platform.acquire_lock(Path(LIBRARY) / '.admin.lock')
        from approval_actions import load_all
        load_all(profile='course')
        box = Box(home, profile='course', vault=args.vault)
        try:
            try: server = Server(box, args.port)
            except OSError as error:
                if not port_busy(error): raise
                server = Server(box, 0)
        except OSError:
            raise PortProblem('관리 화면 포트를 열지 못했습니다.') from None
        server.source_digest = platform.code_digest(Path(LIBRARY))
        executable, started = platform.process_identity(os.getpid())
        info = {'service': SERVICE, 'pid': os.getpid(), 'port': server.server_port, 'started_at': started,
                'source_digest': server.source_digest, 'instance': box.instance, 'executable': executable}
        platform.atomic_write(private / 'server.json', json.dumps(info).encode())
        def idle():
            while not stopped.wait(min(30, args.idle_seconds / 2)):
                if time.monotonic() - box.last_activity >= args.idle_seconds:
                    server.shutdown()
                    return
        thread = threading.Thread(target=idle, daemon=True)
        thread.start()
        print(f'일손 강의 관리자: http://127.0.0.1:{server.server_port}/ · 유휴 2시간 뒤 종료', flush=True)
        server.serve_forever(poll_interval=.1)
    finally:
        stopped.set()
        if server is not None: server.server_close()
        try:
            value = json.loads((private / 'server.json').read_text())
            if value.get('pid') == os.getpid() and value.get('instance') == box.instance:
                platform.safe_path(private / 'server.json').unlink()
        except (OSError, ValueError, UnboundLocalError): pass
        if code_lock is not None: os.close(code_lock)
        os.close(fd)


def course_failure(error):
    """(exit code, fixed message) by cause; course_admin maps the same codes. No paths or secrets."""
    import course_admin
    if isinstance(error, PortProblem):
        return course_admin.EXIT_PORT, course_admin.PORT_MESSAGE
    if isinstance(error, SettingsProblem):
        return course_admin.EXIT_SETTINGS, course_admin.SETTINGS_MESSAGE
    if isinstance(error, (PermissionProblem, platform.AccessProblem, PermissionError)):
        elevated, redirected = bool(getattr(error, 'elevated', False)), bool(getattr(error, 'redirected', False))
        if redirected:
            return course_admin.EXIT_REDIRECTED, course_admin.permission_message(False, True)
        return (course_admin.EXIT_ELEVATED if elevated else course_admin.EXIT_PERMISSION), course_admin.permission_message(elevated)
    if isinstance(error, course_admin.CourseAdminError):
        return 1, str(error)
    return 1, '관리 화면을 준비하지 못했습니다. ilson doctor로 확인해주세요.'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--profile", choices=("box", "course"), default="box")
    parser.add_argument("--vault", type=Path)
    parser.add_argument("--idle-seconds", type=float, default=7200)
    args = parser.parse_args()
    try:
        if args.profile == "course":
            if not args.home.is_absolute() or not 0 <= args.port <= 65535 or args.idle_seconds <= 0:
                raise AdminError("관리자 실행 설정을 확인하세요.")
            return course_server(args)
        if not args.home.is_absolute() or not 1 <= args.port <= 65535:
            raise AdminError("Box 절대 경로와 포트를 확인해주세요.")
        os.environ['ILSON_HOME'] = str(args.home.resolve())
        from approval_actions import load_all
        load_all()
        server = Server(Box(args.home), args.port)
        server.box.workspace().start()
    except (AdminError, OSError, ValueError) as error:
        if args.profile == "course":
            code, message = course_failure(error)
            parser.exit(code, "일손 관리자 시작 실패: " + message + "\n")
        parser.exit(1, "일손 관리자 시작 실패: 연결 설정·파일 권한·사용 중인 포트를 확인해주세요.\n")
    print(f"일손 관리자: http://127.0.0.1:{server.server_port}/ · 이 기기에서만 접속", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if server.box._workspace is not None:
            server.box._workspace.close()


if __name__ == "__main__":
    main()
