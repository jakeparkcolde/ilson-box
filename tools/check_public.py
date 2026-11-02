"""공개 게시 전에 배포 ZIP과 manifest를 검사한다. 찾은 값은 출력하지 않고 파일·패턴 이름·횟수만 알린다.

Each ZIP member is compared by bytes with the git tree at a commit. A member already in the public repository is
checked for what must never ship, client names included; anything new also gets the softer checks. Client names stay outside git, in
a denylist file, because this repository is public. Do not add a client or private term to this file.
"""
import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import unicodedata
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('public_updater', ROOT / 'tools/update.py')
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)

DEFAULT_DENYLIST = Path.home() / '.config/ilson/public-denylist.txt'
# The pack's own files, kept from the previous pack rather than the repository (tools/refresh_pack.py).
PACK_ONLY = ('README.txt', 'manifest.json', 'serve.py', 'start.sh')
SENSITIVE_PATH = re.compile(r'(?i)(^|/)(\.env[^/]*|state|vault|logs|credentials[^/]*|tokens?\.json'
                            r'|[^/]*\.sqlite3?|[^/]*\.db|[^/]*\.pem|[^/]*\.key)(/|$)')
# Blocks on every member and the manifest.
HARD = [(name, re.compile(pattern)) for name, pattern in (
    ('ts-net-host', rb'(?i)\.ts\.net\b'),
    ('tailnet-label', rb'\btail(?=[0-9a-f]*[0-9])[0-9a-f]{4,}\b'),
    ('machine-host', rb'(?i)mac-?(?:mini|studio)'),
    ('tailnet-ip', rb'(?<![0-9.])100\.(?:6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.[0-9]{1,3}\.[0-9]{1,3}(?!\.?[0-9])'),
    ('supabase-host', rb'[a-z0-9]{20}\.supabase\.co'),
    ('github-token', rb'\bgh[pousr]_[A-Za-z0-9]{20,}\b|github_pat_[A-Za-z0-9_]{20,}'),
    ('anthropic-openai-key', rb'\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}\b'),
    ('google-key', rb'\bAIza[0-9A-Za-z_-]{30,}\b'),
    ('aws-key', rb'\bAKIA[0-9A-Z]{16}\b'),
    ('slack-token', rb'\bxox[baprs]-[A-Za-z0-9-]{10,}'),
    ('telegram-bot', rb'\b[0-9]{8,10}:AA[A-Za-z0-9_-]{30,}\b'),
    ('jwt', rb'\beyJ[A-Za-z0-9_-]{15,}\.eyJ[A-Za-z0-9_-]{15,}\.'),
    ('private-key', rb'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
    ('assigned-secret', rb'(?i)(?:api[_-]?key|secret|token|password|passwd)["\']?\s*[:=]\s*["\'][A-Za-z0-9_\-/+=]{16,}["\']'),
)]
# Blocks on anything not already public; reported only on members that are.
SOFT = [(name, re.compile(pattern)) for name, pattern in (
    ('email', rb'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}'),
    ('phone-kr', rb'\b01[016789]-?[0-9]{3,4}-?[0-9]{4}\b'),
    ('person-or-business-number', rb'\b[0-9]{6}-[1-4][0-9]{6}\b|\b[0-9]{3}-[0-9]{2}-[0-9]{5}\b'),
    ('personal-home', rb'/Users/[a-zA-Z0-9._-]+|/home/[a-z][a-z0-9_-]+'),
    ('external-drive', rb'/Volumes/[^ "\'<]+'),
    ('lan-ip', rb'(?<![0-9.])(?:192\.168|10\.[0-9]{1,3}|172\.(?:1[6-9]|2[0-9]|3[01]))\.[0-9]{1,3}\.[0-9]{1,3}(?!\.?[0-9])'),
)]


class Report:
    def __init__(self, commit, denylist_checked):
        self.commit, self.denylist_checked = commit, denylist_checked
        self.blocks, self.notes, self.new = [], [], []
        self.members = 0

    @property
    def blocked(self):
        return bool(self.blocks)

    def lines(self):
        rows = ['공개 검사 · 기준 커밋 ' + self.commit[:7] + ' · 파일 ' + str(self.members) + '개 · 저장소에 없는 파일 ' + str(len(self.new)) + '개']
        rows += ['[새 파일] ' + name for name in self.new]
        for label, found in (('차단', self.blocks), ('참고', self.notes)):
            rows += ['[' + label + '] ' + where + ' · ' + pattern + ' · ' + str(count) + '회' for where, pattern, count in found]
        if not self.denylist_checked:
            rows.append('[주의] 거래처 이름은 확인하지 않았습니다 (--no-denylist).')
        rows.append('결과: ' + ('차단 ' + str(len(self.blocks)) + '건' if self.blocked else '통과'))
        return rows


def load_denylist(path):
    # Returns [(name, pattern)]. The name is the line number: the term itself must not reach any output.
    try:
        text = Path(path).read_text(encoding='utf-8')
    except FileNotFoundError:
        raise ValueError('거래처 이름 목록이 없어 확인하지 않았습니다: ' + str(path) + ' (목록 없이 검사하려면 --no-denylist)') from None
    terms = []
    for number, line in enumerate(text.splitlines(), 1):
        term = line.strip()
        if term and not term.startswith('#'):
            forms = {unicodedata.normalize(form, term).encode() for form in ('NFC', 'NFD')}
            terms.append(('denylist-line-' + str(number), re.compile(b'|'.join(map(re.escape, sorted(forms))), re.I)))
    if not terms:
        raise ValueError('거래처 이름 목록이 비어 있어 확인하지 않았습니다: ' + str(path) + ' (목록 없이 검사하려면 --no-denylist)')
    return terms


def public_tree(root, commit):
    # The commit's regular files as git blob ids, so members are compared without reading every file.
    resolved = subprocess.run(['git', 'rev-parse', '--verify', commit + '^{commit}'], cwd=root, capture_output=True, text=True)
    if resolved.returncode:
        raise ValueError('기준 커밋을 찾지 못했습니다: ' + commit)
    sha = resolved.stdout.strip()
    listed = subprocess.run(['git', 'ls-tree', '-r', '-z', sha], cwd=root, capture_output=True)
    if listed.returncode:
        raise ValueError('기준 커밋의 파일 목록을 읽지 못했습니다: ' + sha)
    tree = {}
    for row in filter(None, listed.stdout.split(b'\0')):
        meta, path = row.split(b'\t', 1)
        mode, kind, blob = meta.split()
        if kind == b'blob' and mode != b'120000':
            tree[path.decode('utf-8', 'surrogateescape')] = blob.decode()
    return sha, tree


def blob_id(data):
    return hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()


def hits(patterns, data):
    return [(name, count) for name, count in ((name, len(rx.findall(data))) for name, rx in patterns) if count]


def pack_only_members(release):
    version = release.get('research_version') if isinstance(release, dict) else None
    return {'box/packs/research/' + version + '/' + name for name in PACK_ONLY} if isinstance(version, str) and version else set()


def check(archive, manifest, commit='HEAD', denylist=DEFAULT_DENYLIST, use_denylist=True, root=ROOT, exact_commit=False):
    # A missing denylist raises ValueError before anything is scanned. exact_commit ties the stage to the commit:
    # no other bytes may ship, which a scan alone cannot show for an older, dirty or ignored-file build.
    terms = load_denylist(denylist) if use_denylist else []
    sha, tree = public_tree(root, commit)
    blobs = set(tree.values())
    report = Report(sha, use_denylist)
    bundle, raw = Path(archive).read_bytes(), Path(manifest).read_bytes()
    label = Path(manifest).name

    def block(where, found):
        report.blocks += [(where, name, count) for name, count in found]

    try:
        release = json.loads(raw)
    except ValueError:
        release = None
    pack_only = pack_only_members(release)
    names, shipped = [], {}
    with zipfile.ZipFile(io.BytesIO(bundle)) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            name, data = info.filename, z.read(info)
            names.append(name)
            report.members += 1
            # The stamped updater is public once its FEED line is cleared; the stamped address is checked on its own.
            body = updater.unstamp(data) if name == updater.UPDATER_KEY else data
            shipped[name] = blob_id(body)
            public = shipped[name] in blobs
            if SENSITIVE_PATH.search(name):
                block(name, [('sensitive-path', 1)])
            block(name, hits(HARD + terms, name.encode() + b'\n' + data))
            # A blob match says the bytes are public, not the name this member carries.
            block(name, hits(SOFT, name.encode()))
            if public:
                report.notes += [(name, pattern, count) for pattern, count in hits(SOFT, data)]
            else:
                report.new.append(name)
                block(name, hits(SOFT, data))
                if exact_commit and name not in pack_only:
                    block(name, [('not-in-commit', 1)])
            if name == updater.UPDATER_KEY:
                try:
                    feed = updater.feed_of(data).encode()
                except ValueError:
                    block(name, [('updater-feed-line', 1)])
                else:
                    if feed not in body:
                        block(name + ' FEED', hits(SOFT, feed))
    block(label, hits(HARD + SOFT + terms, raw))
    if exact_commit:
        # A cli member is its tracked file, so a file added after the build shows up here.
        missing = [path for path, blob in tree.items() if updater.allowed('cli', path) and shipped.get('cli/' + path) != blob]
        if missing:
            block('commit ' + sha[:7], [('commit-file-not-in-stage', len(missing))])
    try:
        listed = [item['area'] + '/' + item['path'] for item in release['files']]
    except (KeyError, TypeError):
        block(label, [('manifest-format', 1)])
        return report
    if updater.digest(bundle) != release.get('archive_sha256'):
        block(label, [('archive-hash-mismatch', 1)])
    if sorted(listed) != sorted(names):
        block(label, [('file-list-mismatch', len(set(listed) ^ set(names)) or 1)])
    for path in listed:
        if SENSITIVE_PATH.search(path):
            block(label, [('sensitive-path', 1)])
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description='Scan a release ZIP and its manifest before publishing them.')
    p.add_argument('archive', type=Path, help='release ZIP')
    p.add_argument('manifest', type=Path, help='release-<version>.json')
    p.add_argument('--commit', default='HEAD', help='commit whose tree counts as already public (default: HEAD)')
    p.add_argument('--exact-commit', action='store_true', help='block every member that is not at that commit (always on for publish_release)')
    lists = p.add_mutually_exclusive_group()
    lists.add_argument('--denylist', type=Path, default=DEFAULT_DENYLIST, help='client names, UTF-8, one per line, # comments')
    lists.add_argument('--no-denylist', action='store_true', help='scan without client names')
    a = p.parse_args(argv)
    try:
        report = check(a.archive, a.manifest, a.commit, a.denylist, not a.no_denylist, exact_commit=a.exact_commit)
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        raise SystemExit('공개 검사를 하지 못했습니다: ' + str(exc))
    print('\n'.join(report.lines()))
    return 1 if report.blocked else 0


if __name__ == '__main__':
    sys.exit(main())
