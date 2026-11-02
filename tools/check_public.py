"""공개 게시 전에 배포 ZIP과 manifest를 검사한다. 찾은 값은 출력하지 않고 파일·패턴 이름·횟수만 알린다.

Each ZIP member is compared by bytes with the git tree at a commit. A member already in the public repository is
checked for what must never ship; anything new also gets the softer checks. Terms that must never ship stay outside git, in a
denylist file, because this repository is public. Do not add a client or private term to this file.
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
spec = importlib.util.spec_from_file_location('public_refresher', ROOT / 'tools/refresh_pack.py')
refresher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresher)

DEFAULT_DENYLIST = Path.home() / '.config/ilson/public-denylist.txt'
# The pack's own files, kept from the previous pack rather than the repository (tools/refresh_pack.py).
PACK_ONLY = ('README.txt', 'manifest.json', 'serve.py', 'start.sh')
PACK_PINS = 'tools/pack-only-pins.json'
SENSITIVE_PATH = re.compile(r'(?i)(^|/)(\.env[^/]*|state|vault|logs|credentials[^/]*|tokens?\.json|\.ssh|\.git|id_rsa[^/]*'
                            r'|auth\.json|cookies\.txt|\.netrc|\.npmrc|pairing\.json|jobs\.conf|job-settings\.json|settings\.local\.json'
                            r'|[^/]*\.sqlite3?|[^/]*\.db|[^/]*\.pem|[^/]*\.key|[^/]*\.p12)(/|$)')
GZIP_MAGIC = b'\x1f\x8b'
ZIP_MAGICS = (b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08')
UTF16_BOMS = (b'\xff\xfe', b'\xfe\xff')
# Blocks on every member and the manifest.
HARD = [(name, re.compile(pattern)) for name, pattern in (
    ('ts-net-host', rb'(?i)\.ts\.net\b'),
    ('tailnet-label', rb'(?i)\btail(?=[0-9a-f]*[0-9])[0-9a-f]{4,}\b'),
    ('machine-host', rb'(?i)mac-?(?:mini|studio)'),
    ('tailnet-ip', rb'(?<![0-9.])100\.(?:6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.[0-9]{1,3}\.[0-9]{1,3}(?!\.?[0-9])'),
    ('tailnet-ipv6', rb'(?i)(?<![0-9a-f:])fd7a:115c:a1e0:'),
    ('supabase-host', rb'[a-z0-9]{20}\.supabase\.co'),
    ('github-token', rb'\bgh[pousr]_[A-Za-z0-9]{20,}\b|github_pat_[A-Za-z0-9_]{20,}'),
    ('anthropic-openai-key', rb'\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}\b'),
    ('google-key', rb'\bAIza[0-9A-Za-z_-]{30,}\b'),
    ('aws-key', rb'\bAKIA[0-9A-Z]{16}\b'),
    ('slack-token', rb'\bxox[baprs]-[A-Za-z0-9-]{10,}'),
    ('telegram-bot', rb'\b[0-9]{8,10}:AA[A-Za-z0-9_-]{30,}\b'),
    ('jwt', rb'\beyJ[A-Za-z0-9_-]{15,}\.eyJ[A-Za-z0-9_-]{15,}\.'),
    ('private-key', rb'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
    ('stripe-live-key', rb'\b[sr]k_live_[A-Za-z0-9]{16,}'),
    ('webhook-secret', rb'\bwhsec_[A-Za-z0-9+/=_-]{16,}'),
    ('google-oauth-secret', rb'\bGOCSPX-[A-Za-z0-9_-]{16,}'),
    ('google-oauth-token', rb'\bya29\.[A-Za-z0-9_.-]{20,}'),
    ('huggingface-token', rb'\bhf_[A-Za-z0-9]{20,}'),
    ('npm-token', rb'\bnpm_[A-Za-z0-9]{20,}'),
    ('supabase-token', rb'\bsbp_[A-Za-z0-9]{20,}|\bsb_secret_[A-Za-z0-9_-]{16,}'),
    ('notion-token', rb'\bntn_[A-Za-z0-9]{20,}'),
    ('vercel-token', rb'\bvercel_[A-Za-z0-9]{20,}'),
    ('paddle-live-key', rb'\bpdl_live_[A-Za-z0-9_]{16,}'),
    ('sendgrid-key', rb'\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}'),
    ('aws-secret-key', rb'(?i)aws_secret_access_key["\']?\s*[:=]\s*["\']?[A-Za-z0-9/+=]{20,}'),
    ('bearer-token', rb'(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}'),
    ('assigned-secret', rb'(?i)(?:api[_-]?key|secret|token|password|passwd)["\']?\s*[:=]\s*["\'][A-Za-z0-9_\-/+=]{16,}["\']'),
    ('assigned-password', rb'(?i)(?:password|passwd)["\']?\s*[:=]\s*["\'][A-Za-z0-9_\-/+=.]{12,}["\']'),
    ('unquoted-secret', rb'\b[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD)\s*=\s*[A-Za-z0-9_\-/+=.]{16,}'),
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


class DenylistError(ValueError):
    pass


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
            rows.append('[주의] 차단 이름은 확인하지 않았습니다 (--no-denylist).')
        rows.append('결과: ' + ('차단 ' + str(len(self.blocks)) + '건' if self.blocked else '통과'))
        return rows


def load_denylist(path):
    # Returns [(name, pattern)]. The name is the line number: the term itself must not reach any output.
    try:
        # utf-8-sig: a BOM must not hide the term on the first line.
        text = Path(path).read_text(encoding='utf-8-sig')
    except FileNotFoundError:
        raise DenylistError('차단 이름 목록이 없어 확인하지 않았습니다: ' + str(path)) from None
    terms = []
    for number, line in enumerate(text.splitlines(), 1):
        term = line.strip()
        if term and not term.startswith('#'):
            forms = {unicodedata.normalize(form, term).encode() for form in ('NFC', 'NFD')}
            terms.append(('denylist-line-' + str(number), re.compile(b'|'.join(map(re.escape, sorted(forms))), re.I)))
    if not terms:
        raise DenylistError('차단 이름 목록이 비어 있어 확인하지 않았습니다: ' + str(path))
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


def readable(data):
    # The bytes to scan. A UTF-16 file hides every pattern unless a decoded copy is scanned too.
    return data + b'\n' + data.decode('utf-16', 'ignore').encode() if data[:2] in UTF16_BOMS else data


def path_allowed(name):
    area, _, path = name.partition('/')
    return updater.allowed(area, path)


def member_label(index, name, kind='member'):
    # What the report prints when the finding is in the name: the name itself could be the value.
    return kind + '#' + str(index) + ' sha:' + hashlib.sha256(name.encode('utf-8', 'surrogateescape')).hexdigest()[:8]


def name_findings(name, patterns):
    found = hits(patterns, name.encode('utf-8', 'surrogateescape'))
    return found + [('sensitive-path', 1)] if SENSITIVE_PATH.search(name) else found


def same_form(name):
    # git keeps a precomposed path while macOS can hand the build a decomposed one.
    return unicodedata.normalize('NFC', name)


def valid_pack_version(value):
    # The rule build_release applies to a pack version.
    return isinstance(value, str) and re.fullmatch('[0-9.]+', value) is not None


def read_pins(root, sha):
    # From the commit, not the working tree: a pin nobody committed proves nothing.
    shown = subprocess.run(['git', 'show', sha + ':' + PACK_PINS], cwd=root, capture_output=True)
    try:
        pins = json.loads(shown.stdout) if shown.returncode == 0 else None
    except ValueError:
        return None
    return pins if isinstance(pins, dict) and set(pins) == set(PACK_ONLY) - {'manifest.json'} else None


def pack_manifest_ok(data, version):
    # Not pinned, because its version changes with every release.
    try:
        manifest = json.loads(data)
    except ValueError:
        return False
    return isinstance(manifest, dict) and set(manifest) == refresher.MANIFEST_KEYS and manifest['id'] == 'research' and manifest['version'] == version


def pack_problems(prefix, version, files, pins):
    # The pack's own files are the only release bytes outside the commit, so tie them to it another way.
    found = []
    for name in PACK_ONLY:
        data = files.get(prefix + name)
        if data is None:
            found.append((prefix + name, 'pack-file-missing'))
        elif name == 'manifest.json':
            if not pack_manifest_ok(data, version):
                found.append((prefix + name, 'pack-manifest'))
        elif pins is None or pins[name] != updater.digest(data):
            found.append((prefix + name, 'pack-file-not-pinned'))
    return found


def check(archive, manifest, commit='HEAD', denylist=DEFAULT_DENYLIST, use_denylist=True, root=ROOT, exact_commit=False):
    # A missing denylist raises ValueError before anything is scanned. exact_commit ties the stage to the commit:
    # no other bytes may ship, which a scan alone cannot show for an older, dirty or ignored-file build.
    terms = load_denylist(denylist) if use_denylist else []
    sha, tree = public_tree(root, commit)
    blobs = set(tree.values())
    report = Report(sha, use_denylist)
    bundle, raw = Path(archive).read_bytes(), Path(manifest).read_bytes()
    listing = Path(manifest).name

    def block(where, found):
        report.blocks += [(where, name, count) for name, count in found]

    try:
        release = json.loads(raw)
    except ValueError:
        release = None
    version = release.get('research_version') if isinstance(release, dict) else None
    if version is not None and not valid_pack_version(version):
        block(listing, [('research-version', 1)])
    prefix = 'box/packs/research/' + version + '/' if valid_pack_version(version) else None
    pack_only = {prefix + name for name in PACK_ONLY} if prefix else set()
    names, shipped, pack_files, labels = [], {}, {}, {}
    with zipfile.ZipFile(io.BytesIO(bundle)) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            name = info.filename
            names.append(name)
            report.members += 1
            try:
                data = z.read(info)
            except Exception as exc:
                # zipfile puts the member name in its messages.
                raise ValueError('묶음 파일을 읽지 못했습니다: ' + member_label(report.members, name) + ' (' + type(exc).__name__ + ')') from None
            view = readable(data)
            found = name_findings(name, HARD + SOFT + terms)
            if not path_allowed(name):
                found.append(('path-not-allowed', 1))
            label = member_label(report.members, name) if found else name
            labels[name] = label
            if name in pack_only:
                pack_files[name] = data
            block(label, found)
            if data[:2] == GZIP_MAGIC or data[:4] in ZIP_MAGICS:
                block(label, [('nested-archive', 1)])
            # The stamped updater is public once its FEED line is cleared; the stamped address is checked on its own.
            body = updater.unstamp(data) if name == updater.UPDATER_KEY else data
            shipped[same_form(name)] = blob_id(body)
            public = shipped[same_form(name)] in blobs
            block(label, hits(HARD + terms, view))
            if public:
                report.notes += [(label, pattern, count) for pattern, count in hits(SOFT, view)]
            else:
                report.new.append(label)
                block(label, hits(SOFT, view))
                if exact_commit and name not in pack_only:
                    block(label, [('not-in-commit', 1)])
            if name == updater.UPDATER_KEY:
                try:
                    feed = updater.feed_of(data).encode()
                except ValueError:
                    block(label, [('updater-feed-line', 1)])
                else:
                    if feed not in body:
                        block(label + ' FEED', hits(SOFT, feed))
    block(listing, hits(HARD + SOFT + terms, readable(raw)))
    if exact_commit and prefix:
        pins = read_pins(root, sha)
        if pins is None:
            block(PACK_PINS, [('pack-pins-unreadable', 1)])
        for name, pattern in pack_problems(prefix, version, pack_files, pins):
            block(labels.get(name, name), [(pattern, 1)])
    if exact_commit:
        # A cli member is its tracked file, so a file added after the build shows up here.
        for index, (path, blob) in enumerate(sorted(tree.items()), 1):
            if updater.allowed('cli', path) and shipped.get(same_form('cli/' + path)) != blob:
                # Tracked paths are public unless one of them holds a value.
                block(member_label(index, path, 'commit-file') if name_findings(path, HARD + SOFT + terms) else path, [('commit-file-not-in-stage', 1)])
    try:
        listed = [item['area'] + '/' + item['path'] for item in release['files']]
    except (KeyError, TypeError):
        block(listing, [('manifest-format', 1)])
        return report
    if updater.digest(bundle) != release.get('archive_sha256'):
        block(listing, [('archive-hash-mismatch', 1)])
    if sorted(listed) != sorted(names):
        block(listing, [('file-list-mismatch', len(set(listed) ^ set(names)) or 1)])
    for path in listed:
        if SENSITIVE_PATH.search(path):
            block(listing, [('sensitive-path', 1)])
        if not path_allowed(path):
            block(listing, [('path-not-allowed', 1)])
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description='Scan a release ZIP and its manifest before publishing them.')
    p.add_argument('archive', type=Path, help='release ZIP')
    p.add_argument('manifest', type=Path, help='release-<version>.json')
    p.add_argument('--commit', default='HEAD', help='commit whose tree counts as already public (default: HEAD)')
    p.add_argument('--exact-commit', action='store_true', help='block every member that is not at that commit (always on for publish_release)')
    lists = p.add_mutually_exclusive_group()
    lists.add_argument('--denylist', type=Path, default=DEFAULT_DENYLIST, help='terms that must never ship, UTF-8, one per line, # comments')
    lists.add_argument('--no-denylist', action='store_true', help='scan without that list (rehearsals only)')
    a = p.parse_args(argv)
    try:
        report = check(a.archive, a.manifest, a.commit, a.denylist, not a.no_denylist, exact_commit=a.exact_commit)
    except DenylistError as exc:
        raise SystemExit('공개 검사를 하지 못했습니다: ' + str(exc) + ' (목록 없이 검사하려면 --no-denylist)')
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        raise SystemExit('공개 검사를 하지 못했습니다: ' + str(exc))
    print('\n'.join(report.lines()))
    return 1 if report.blocked else 0


if __name__ == '__main__':
    sys.exit(main())
