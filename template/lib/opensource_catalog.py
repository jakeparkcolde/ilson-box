"""Read-only L0 catalog. No fetching, execution, user documents or persistent writes.

The installed bundle is the only trust source in stage B. Stage C must implement
signature verification and durable anti-rollback before enabling remote updates.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
import re
import threading
import time

CATALOG_PATH = 'web/current/opensource-catalog.json'
MAX_BYTES = 1024 * 1024
MAX_REPOS = 500
POLICY_VERSION = 'box-l0-bundle-30d-v2'
SCHEMA_VERSION = 2
BUNDLE_TTL = 30 * 86400
SOURCE_CHECK_WINDOW = 72 * 3600
MANUAL_PATH = 'reference-manual-20261115'
# This editorial exception is restricted to the reviewed reference repos and
# Round 2 repo-level introductions (including two explicit skill collections).
# GitHub numeric IDs also bind identity if a name is transferred or reused.
REFERENCE_REPOS = {
    'cli/cli': (212613049, 'MIT', 'LICENSE'),
    'microsoft/playwright': (221981891, 'Apache-2.0', 'LICENSE'),
    'openai/codex': (965415649, 'Apache-2.0', 'LICENSE'),
    'nextlevelbuilder/ui-ux-pro-max-skill': (1106996539, 'MIT', 'LICENSE'),
    'heygen-com/hyperframes': (1177402105, 'Apache-2.0', 'LICENSE'),
    'FFmpeg/FFmpeg': (1614410, 'LGPL-2.1-or-later', 'LICENSE.md'),
    'firecrawl/firecrawl': (787076358, 'AGPL-3.0-only', 'LICENSE'),
    'puppeteer/puppeteer': (90796663, 'Apache-2.0', 'LICENSE'),
    'openai/whisper': (537603333, 'MIT', 'LICENSE'),
    'python/cpython': (81598961, 'PSF-2.0', 'LICENSE'),
    'nodejs/node': (27193779, 'MIT', 'LICENSE'),
    'ollama/ollama': (658928958, 'MIT', 'LICENSE'),
    'obra/superpowers': (1073224795, 'MIT', 'LICENSE'),
    'garrytan/gstack': (1179264259, 'MIT', 'LICENSE'),
    'Graphify-Labs/graphify': (1200597263, 'Apache-2.0', 'LICENSE'),
    'jarrodwatts/claude-hud': (1126473386, 'MIT', 'LICENSE'),
    'pbakaus/impeccable': (1097346685, 'Apache-2.0', 'LICENSE'),
    'Leonxlnx/taste-skill': (1162099055, 'MIT', 'LICENSE'),
    'mvanhorn/last30days-skill': (1140843380, 'MIT', 'LICENSE'),
    'blader/humanizer': (1136666433, 'MIT', 'LICENSE'),
    'vercel-labs/skills': (1134543109, 'MIT', 'LICENSE'),
    'emilkowalski/skills': (1183325896, 'MIT', 'LICENSE'),
}
CATEGORIES = (
    ('build', '만들고 점검하기'), ('design', '디자인'),
    ('grow', '찾고 알리기'), ('make', '콘텐츠 만들기'),
    ('run', '운영·연결'),
)
ID = re.compile(r'[a-f0-9]{32}\Z')
COMMIT = re.compile(r'[a-f0-9]{40}\Z')
HASH = re.compile(r'[a-f0-9]{64}\Z')
NAME = re.compile(r'[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}\Z')
# A conservative reviewed SPDX subset; adding a licence needs a policy revision.
LICENSES = {'MIT', 'Apache-2.0', 'BSD-2-Clause', 'BSD-3-Clause', 'ISC',
            'MPL-2.0', 'GPL-2.0-only', 'GPL-3.0-only', 'AGPL-3.0-only', 'Unlicense', 'CC0-1.0'}
UNSAFE = re.compile(
    r'<|>|`|\$\(|(?:^|\s)(?:curl|wget|sudo|npx|bash|sh|chmod|chown)\s|'
    r'\b(?:pip3?|npm|brew)\s+install\b|\bgit\s+clone\b|\bdocker\s+run\b|'
    r'(?:^|\n)\s*(?:[$#]\s*)?(?:python3?|node|deno|bun|npm|pnpm|yarn|pip3?|uv|brew|git|docker|podman|echo|printf|cat|cp|mv|rm|mkdir|rmdir)\b|'
    r'/(?:Users|Volumes)/|\.env\b|-----BEGIN|\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]+|'
    r'\b\d{5,15}:[A-Za-z0-9_-]{20,200}\b|\b(?:api[_ -]?key|token|secret)\s*[:=]', re.I)


class InvalidCatalog(ValueError):
    """Only fixed status codes escape this module; never source text or paths."""


class SignatureRejected(InvalidCatalog):
    pass


def keys(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise InvalidCatalog()
    return value


def integer(value, low=0, high=2**53 - 1):
    if type(value) is not int or not low <= value <= high:
        raise InvalidCatalog()
    return value


def text(value, limit=4000, *, ko=False):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or UNSAFE.search(value):
        raise InvalidCatalog()
    if any(ord(c) < 32 and c not in '\n\t' for c in value) or (ko and not re.search('[가-힣]', value)):
        raise InvalidCatalog()
    return value


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', value):
        raise InvalidCatalog()
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        raise InvalidCatalog() from None


def strings(value, *, ko=False):
    if not isinstance(value, list) or len(value) > 30:
        raise InvalidCatalog()
    return [text(v, 1000, ko=ko) for v in value]


def exact(value, expected):
    if type(value) is not type(expected) or value != expected:
        raise InvalidCatalog()


def verify_trusted_bundle(document):
    """STAGE C HOOK: remote signatures are unsupported and fail closed.

    'bundled' means trusted installed distribution, NOT a verified signature.
    No URL, key download, network fallback or remote update entry point exists.
    """
    if document.get('signature') != {'kind': 'bundled', 'key_id': None, 'value': None}:
        raise SignatureRejected()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidCatalog()
        result[key] = value
    return result


def validate(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        raise InvalidCatalog()
    try:
        doc = json.loads(raw, object_pairs_hook=unique_object,
                         parse_constant=lambda _: (_ for _ in ()).throw(InvalidCatalog()))
        keys(doc, ('schema_version', 'catalog_version', 'generated_at', 'valid_until',
                   'policy_version', 'revocation_version', 'revoked_repo_ids',
                   'signature', 'source_commit', 'repos'))
        exact(doc['schema_version'], SCHEMA_VERSION)
        exact(doc['policy_version'], POLICY_VERSION)
        integer(doc['catalog_version'], 1)
        integer(doc['revocation_version'])
        generated, until = timestamp(doc['generated_at']), timestamp(doc['valid_until'])
        if not generated < until <= generated + BUNDLE_TTL or not isinstance(doc['source_commit'], str) or not COMMIT.fullmatch(doc['source_commit']):
            raise InvalidCatalog()
        revoked = doc['revoked_repo_ids']
        if not isinstance(revoked, list) or len(revoked) > 10000 or any(not isinstance(v, str) or not ID.fullmatch(v) for v in revoked) or len(set(revoked)) != len(revoked):
            raise InvalidCatalog()
        if not isinstance(doc['repos'], list) or len(doc['repos']) > MAX_REPOS or any(not isinstance(v, dict) for v in doc['repos']):
            raise InvalidCatalog()
        # Duplicate identities invalidate the envelope, rather than selecting a winner.
        for field in ('id', 'github_id', 'full_name'):
            values = [r.get(field) for r in doc['repos']]
            if any(not isinstance(v, (str, int)) or isinstance(v, bool) for v in values) or len(set(values)) != len(values):
                raise InvalidCatalog()
        verify_trusted_bundle(doc)
        return doc
    except (UnicodeError, ValueError, TypeError, RecursionError) as error:
        if isinstance(error, SignatureRejected):
            raise
        raise InvalidCatalog() from None


def visible_repo(row, doc, now):
    """Unknown, unreviewed or malformed rows never supply even a name or link."""
    keys(row, ('id', 'github_id', 'full_name', 'category', 'curated_order',
               'one_liner', 'mild_md', 'use_cases', 'prerequisites', 'limitations',
               'difficulty', 'box_burden', 'preparation', 'cost', 'data_processing',
               'license', 'gitbap_url', 'official_url', 'source', 'review',
               'catalog_approved', 'runnable', 'preview', 'video', 'approval_path'))
    manual = row['approval_path'] == MANUAL_PATH
    if not manual:
        exact(row['approval_path'], 'gitbap-reviewed')
    if not isinstance(row['id'], str) or not ID.fullmatch(row['id']):
        raise InvalidCatalog()
    integer(row['github_id'], 1)
    name = row['full_name']
    if not isinstance(name, str) or not NAME.fullmatch(name) or any(p.startswith('.') or p.endswith('.git') for p in name.split('/')):
        raise InvalidCatalog()
    if row['category'] not in dict(CATEGORIES):
        raise InvalidCatalog()
    if not isinstance(row['license'], dict) or not isinstance(row['review'], dict):
        raise InvalidCatalog()
    license_file = 'LICENSE'
    if manual:
        if name not in REFERENCE_REPOS:
            raise InvalidCatalog()
        github_id, spdx, license_file = REFERENCE_REPOS[name]
        exact(row['github_id'], github_id)
        exact(row['license'].get('spdx'), spdx)
        exact(row['preview'], None)
        exact(row['video'], None)
    integer(row['curated_order'], 0, 10000)
    exact(row['catalog_approved'], True)
    exact(row['runnable'], False)
    for field in ('one_liner', 'mild_md'):
        text(row[field], 12000, ko=True)
    for field in ('preparation', 'cost', 'data_processing'):
        text(row[field], ko=True)
    for field in ('use_cases', 'prerequisites', 'limitations'):
        strings(row[field], ko=True)
    if not row['limitations']:
        raise InvalidCatalog()
    if row['difficulty'] is not None:
        integer(row['difficulty'], 1, 5)
    if row['box_burden'] not in ('browse', 'guided', 'expert', 'unknown'):
        raise InvalidCatalog()
    gitbap = 'https://www.gitbap.com/r/' + name
    if manual and row['review'].get('metadata_verdict') == 'not_curated':
        exact(row['gitbap_url'], None)
    else:
        exact(row['gitbap_url'], gitbap)
    exact(row['official_url'], 'https://github.com/' + name)
    source = keys(row['source'], ('summary_id', 'summary_revision', 'lang', 'readme_hash',
                                  'summary_readme_hash', 'model', 'summary_created_at',
                                  'synced_at', 'status_checked_at', 'commit', 'copy_origin'))
    if manual:
        exact(source['summary_id'], None)
        exact(source['summary_revision'], None)
        exact(source['model'], None)
        exact(source['summary_readme_hash'], None)
        if source['copy_origin'] not in ('official-readme', 'gitbap-adapted'):
            raise InvalidCatalog()
    else:
        text(source['summary_id'], 100)
        text(source['model'], 100)
        exact(source['copy_origin'], 'gitbap')
    if source['summary_revision'] is not None:
        integer(source['summary_revision'], 1)
    exact(source['lang'], 'ko')
    if not isinstance(source['readme_hash'], str) or not HASH.fullmatch(source['readme_hash']):
        raise InvalidCatalog()
    if not manual:
        exact(source['summary_readme_hash'], source['readme_hash'])
    if not isinstance(source['commit'], str) or not COMMIT.fullmatch(source['commit']):
        raise InvalidCatalog()
    for field in ('summary_created_at', 'synced_at', 'status_checked_at'):
        if timestamp(source[field]) > timestamp(doc['generated_at']):
            raise InvalidCatalog()
    generated = timestamp(doc['generated_at'])
    # At release, sources must be recent. After release, this is a pinned
    # introduction, not a claim that upstream is still less than 72h old.
    if timestamp(source['status_checked_at']) + SOURCE_CHECK_WINDOW <= generated:
        raise InvalidCatalog()
    lic = keys(row['license'], ('spdx', 'conditions', 'url', 'reviewed'))
    if lic['spdx'] not in LICENSES and not manual:
        raise InvalidCatalog()
    text(lic['conditions'], ko=True)
    exact(lic['reviewed'], True)
    exact(lic['url'], 'https://github.com/' + name + '/blob/' + source['commit'] + '/' + license_file)
    review = keys(row['review'], ('hidden', 'review_status', 'metadata_verdict',
        'content_scan', 'policy', 'rights', 'maintenance', 'archived', 'prohibited',
        'requirements_confirmed', 'key_required', 'paid_api_required',
        'reviewed_at', 'valid_until', 'target_commit', 'policy_version',
        'past_safety_pass', 'past_alive_pass', 'past_evaluated_at', 'metadata_checked_at',
        'metadata_warning', 'disabled'))
    if manual:
        if review['metadata_verdict'] not in ('ok', 'review', 'caution', 'not_curated'):
            raise InvalidCatalog()
        if review['metadata_verdict'] == 'caution':
            text(review['metadata_warning'], 1000, ko=True)
        else:
            exact(review['metadata_warning'], None)
        if source['copy_origin'] == 'gitbap-adapted' and review['metadata_verdict'] == 'not_curated':
            raise InvalidCatalog()
    else:
        exact(review['metadata_verdict'], 'ok')
        exact(review['metadata_warning'], None)
    for field, expected in dict(hidden=False, review_status='approved',
        content_scan='ok', policy='approved', rights='approved', maintenance='active',
        archived=False, disabled=False, prohibited=False, requirements_confirmed=True,
        key_required=False, paid_api_required=False, policy_version=POLICY_VERSION).items():
        exact(review[field], expected)
    exact(review['target_commit'], source['commit'])
    reviewed, until = timestamp(review['reviewed_at']), timestamp(review['valid_until'])
    if not reviewed <= generated < until <= reviewed + BUNDLE_TTL or now >= until:
        raise InvalidCatalog()
    if not timestamp(review['metadata_checked_at']) <= generated < timestamp(review['metadata_checked_at']) + SOURCE_CHECK_WINDOW:
        raise InvalidCatalog()
    for field in ('past_safety_pass', 'past_alive_pass'):
        if review[field] is not None and type(review[field]) is not bool:
            raise InvalidCatalog()
    if review['past_evaluated_at'] is not None:
        if timestamp(review['past_evaluated_at']) > timestamp(doc['generated_at']):
            raise InvalidCatalog()
    result = copy.deepcopy(row)
    if row['preview'] is not None:
        sample = keys(row['preview'], ('approved', 'input', 'result', 'placement', 'source'))
        exact(sample['approved'], True)
        for field in ('input', 'result', 'placement', 'source'):
            text(sample[field], ko=True)
    if row['video'] is not None:
        video = keys(row['video'], ('public_approved', 'lang', 'made_at', 'duration_s',
                                    'gitbap_url', 'approval_basis', 'valid_until'))
        # A ready/unpublished, non-Korean or expired video is never advertised.
        if video['public_approved'] is not True or video['lang'] != 'ko' or timestamp(video['valid_until']) <= now:
            result['video'] = None
        else:
            integer(video['duration_s'], 1, 7200)
            if timestamp(video['made_at']) > timestamp(doc['generated_at']):
                raise InvalidCatalog()
            text(video['approval_basis'], ko=True)
            exact(video['gitbap_url'], gitbap)
    return result


class Catalog:
    def __init__(self, read, *, clock=time.time, redact=lambda value: value):
        self.read, self.clock, self.redact = read, clock, redact
        self.lock = threading.Lock()
        self.good = None
        self.digest = None
        self.revocation_version = -1
        self.revoked = set()
        self.verification_blocked = False

    def snapshot(self, repo_id=None):
        with self.lock:
            now = self.clock()
            failure = None
            try:
                raw = self.read(CATALOG_PATH, MAX_BYTES)[0]
                doc = validate(raw)
                if timestamp(doc['generated_at']) > now:
                    raise InvalidCatalog()
                digest = hashlib.sha256(raw).digest()
                # Emergency tombstones survive body rollback and empty newer lists.
                if doc['revocation_version'] >= self.revocation_version:
                    self.revoked.update(doc['revoked_repo_ids'])
                    self.revocation_version = doc['revocation_version']
                if self.good and (doc['catalog_version'] < self.good['catalog_version'] or
                    doc['revocation_version'] < self.revocation_version or
                    (doc['catalog_version'] == self.good['catalog_version'] and digest != self.digest)):
                    failure = 'older_version'
                else:
                    self.good, self.digest = doc, digest
                    self.verification_blocked = False
            except SignatureRejected:
                self.verification_blocked = True
                return self.status('verification_failed')
            except (OSError, ValueError, TypeError, RecursionError):
                failure = 'load_failed'
            if self.verification_blocked:
                return self.status('verification_failed')
            if self.good is None:
                return self.status('load_failed')
            doc = self.good
            metadata = {k: doc[k] for k in ('catalog_version', 'generated_at', 'valid_until', 'policy_version')}
            if now < timestamp(doc['generated_at']):
                return {**self.status('verification_failed'), **metadata}
            if now >= timestamp(doc['valid_until']):
                return {**self.status('expired'), **metadata}
            rows = []
            for row in doc['repos']:
                if row.get('id') in self.revoked:
                    continue
                try:
                    public = visible_repo(row, doc, now)
                    if self.redact(public) == public:
                        rows.append(public)
                except (InvalidCatalog, TypeError, KeyError):
                    continue
            rows.sort(key=lambda r: (r['curated_order'], r['id']))
            visible_until = min([timestamp(doc['valid_until'])] + [
                timestamp(r['review']['valid_until']) for r in rows])
            result = {**self.status('ready' if rows else ('under_review' if doc['repos'] else 'empty')),
                      **metadata, 'warning': failure, 'revocation_version': self.revocation_version,
                      'visible_until': datetime.fromtimestamp(visible_until, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
            if repo_id is not None:
                match = next((r for r in rows if r['id'] == repo_id), None)
                # No hints (including IDs/names/links) about blocked or absent items.
                return {**result, 'state': 'ready' if match else 'unavailable', 'repo': match}
            # Explicit list projection: no unapproved or incidental source fields.
            fields = ('id', 'full_name', 'category', 'curated_order', 'one_liner', 'use_cases',
                      'difficulty', 'box_burden', 'preparation', 'cost', 'license', 'gitbap_url')
            result['repos'] = [{**{k: r[k] for k in fields}, 'reviewed_at': r['review']['reviewed_at'],
                                'approval_path': r['approval_path'],
                                'official_url': r['official_url'],
                                'metadata_verdict': r['review']['metadata_verdict'],
                                'metadata_warning': r['review']['metadata_warning'],
                                'runnable': False} for r in rows]
            return result

    @staticmethod
    def status(state):
        return {'state': state, 'repos': [], 'runnable': False,
                'categories': [{'id': key, 'label': label} for key, label in CATEGORIES]}
