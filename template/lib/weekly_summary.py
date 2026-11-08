"""Deterministic weekly report; reads only explicitly published summary records."""
import argparse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import hashlib
import re
import os
from pathlib import Path
import tempfile

KST = timezone(timedelta(hours=9))
CATEGORIES = (('completed', '완료한 일'), ('pending', '승인 대기'),
              ('needs_review', '확인 필요'), ('skills', '새로 승인된 스킬'),
              ('lessons', '승인된 배운 점'))


def clean(value):
    return ' '.join(value.split())[:160] if isinstance(value, str) else ''


def day(value):
    if not isinstance(value, str):
        return None
    try:
        if len(value) == 10:
            return date.fromisoformat(value)
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return dt.astimezone(KST).date() if dt.tzinfo else None
    except ValueError:
        return None


def read_json(path):
    if path.is_symlink():
        return None
    try:
        if path.stat().st_size > 1024 * 1024:
            return None
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, ValueError):
        return None


def safe_inside(root, path):
    root = Path(root)
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    current = root
    if current.is_symlink():
        return False
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return False
    return True


def dated_files(directory, start, end):
    if directory.is_symlink() or not directory.is_dir():
        return []
    found = []
    for path in sorted(directory.glob('*.md')):
        if path.is_symlink() or not path.is_file():
            continue
        match = re.match(r'(\d{4}-\d{2}-\d{2})', path.name)
        when = day(match.group(1)) if match else None
        if when and start <= when <= end:
            found.append((path, when))
    return found


def input_records(vault, start, end):
    """Read only obvious completion markers and document metadata, never drafts' bodies."""
    data = {'completed': [], 'pending': [], 'needs_review': [], 'lessons': [], 'skills': []}
    seen = set()
    journal = vault / 'journal'
    for path, when in dated_files(journal, start, end) if safe_inside(vault, journal) else []:
        try:
            if path.stat().st_size > 1024 * 1024:
                continue
            text = path.read_text(encoding='utf-8')
        except (OSError, UnicodeError):
            continue
        for number, line in enumerate(text.splitlines()):
            if '확인 필요' in line:
                data['needs_review'].append({'id': 'journal:' + path.name + ':' + str(number),
                    'title': '일지 확인 필요 항목', 'date': str(when), 'source': '일지 ' + str(when)})
            match = re.match(r'^\s*(?:[-*]\s*\[x\]|[-*]?\s*완료\s*:)\s*(.+?)\s*$', line, re.I)
            if not match:
                continue
            body = match.group(1)
            ident = hashlib.sha256(body.encode('utf-8')).hexdigest()
            if ident in seen:
                continue
            seen.add(ident)
            kind_match = re.search(r'\[유형:\s*([^\]\n]{1,40})\]', body)
            kind = clean(kind_match.group(1)) if kind_match else ''
            actor = 'ilson' if '[수행:일손]' in body else 'person' if '[수행:사람]' in body else None
            data['completed'].append({'id': ident, 'title': '완료 표시된 업무', 'date': str(when),
                                      'source': '일지 ' + str(when), 'work_type': kind, 'actor': actor})
    briefing = vault / 'reports' / 'briefing'
    for path, when in dated_files(briefing, start, end) if safe_inside(vault, briefing) else []:
        try:
            text = path.read_text(encoding='utf-8') if path.stat().st_size <= 1024 * 1024 else ''
        except (OSError, UnicodeError):
            continue
        for number, line in enumerate(text.splitlines()):
            if '확인 필요' in line:
                data['needs_review'].append({'id': 'briefing:' + path.name + ':' + str(number),
                    'title': '브리핑 확인 필요 항목', 'date': str(when), 'source': '브리핑 ' + str(when)})
    pending = vault / 'reports' / 'pending'
    if safe_inside(vault, pending) and pending.is_dir():
        for path in sorted(pending.glob('*.md')):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                modified = datetime.fromtimestamp(path.stat().st_mtime, KST).date()
            except OSError:
                continue
            data['pending'].append({'id': 'pending:' + path.name, 'title': '승인 대기 문서 (마지막 수정일)',
                                    'date': str(modified), 'source': '승인 대기함'})
    # These are approved documents. A filename date is evidence; mtime is not approval date.
    lessons = vault / 'lessons'
    for path, when in dated_files(lessons, start, end) if safe_inside(vault, lessons) else []:
        data['lessons'].append({'id': 'lesson:' + path.name, 'title': '승인된 배운 점 기록',
                                'date': str(when), 'source': '배운 점 ' + str(when)})
    approved = vault / 'lessons' / 'approved-learning.md'
    if safe_inside(vault, approved) and approved.is_file():
        try:
            modified = datetime.fromtimestamp(approved.stat().st_mtime, KST).date()
            if start <= modified <= end:
                data['lessons'].append({'id': 'approved-learning', 'title': '승인된 배운 점 문서 (마지막 수정일)',
                                        'date': str(modified), 'source': '승인된 배운 점'})
        except OSError:
            pass
    return data


def approval_entries(start, end):
    try:
        import approval_store
    except ImportError:
        return [], {}, False
    since = datetime.combine(start, datetime.min.time(), KST)
    until = datetime.combine(end + timedelta(days=1), datetime.min.time(), KST)
    try:
        counts = approval_store.weekly_counts(since, until)
        rows = approval_store.list_titles(['pending', 'failed', 'result_unknown'], since, until, limit=20)
        if not isinstance(counts, dict) or not isinstance(rows, list):
            raise ValueError('invalid approval result')
        result = []
        for row in rows:
            if not isinstance(row, dict) or row.get('state') not in ('pending', 'failed', 'result_unknown'):
                continue
            when = day(row.get('updated_at'))
            if not when or not clean(row.get('id')):
                continue
            label = '승인 요청' if row['state'] == 'pending' else '승인 처리 결과 확인 필요'
            result.append((row['state'], when, label))
        valid_counts = {key: val for key, val in counts.items() if key in ('pending', 'approved', 'changed', 'rejected', 'expired', 'executing', 'success', 'failed', 'result_unknown') and type(val) is int and val >= 0}
        return result, valid_counts, False
    except Exception:
        return [], {}, True


def build(vault, end, flat_vault=False):
    vault = Path(vault)
    start = end - timedelta(days=6)
    settings_path = vault / 'reports' / 'weekly-input.json'
    settings = read_json(settings_path) if safe_inside(vault, settings_path) else None
    settings = settings if isinstance(settings, dict) else {}
    data = input_records(vault, start, end)
    public_path = vault / 'reports' / 'weekly' / '.learning-summary.json'
    public = read_json(public_path) if safe_inside(vault, public_path) else None
    groups = {key: [] for key, _ in CATEGORIES}
    approval_rows, approval_counts, approval_error = approval_entries(start, end)
    for state, when, label in approval_rows:
        key = 'pending' if state == 'pending' else 'needs_review'
        groups[key].append(({}, when, label, '승인 요청 저장소'))
    seen = set()
    for key in ('completed', 'pending', 'needs_review'):
        rows = data.get(key, [])
        if not isinstance(rows, list):
            continue
        for item in rows:
            if not isinstance(item, dict):
                continue
            ident, title, source = (clean(item.get(k)) for k in ('id', 'title', 'source'))
            when = day(item.get('date'))
            if not ident or not title or not source or not when or (key != 'pending' and not start <= when <= end):
                continue
            if (key, ident) in seen:
                continue
            seen.add((key, ident))
            groups[key].append((item, when, title, source))
    available = isinstance(public, dict) and public.get('version') == 1 and isinstance(public.get('items'), list)
    shared_skills = []
    skill_root = vault if flat_vault else vault.parent
    for skills in (skill_root / '.claude' / 'skills',):
        if not skills.is_dir() or any(p.is_symlink() for p in (skills, skills.parent)):
            continue
        for folder in sorted(skills.iterdir()):
            path = folder / 'SKILL.md'
            if folder.is_symlink() or not folder.is_dir() or path.is_symlink() or not path.is_file():
                continue
            try:
                body = path.read_text(encoding='utf-8') if path.stat().st_size <= 1024 * 1024 else ''
                modified = datetime.fromtimestamp(path.stat().st_mtime, KST).date()
            except (OSError, UnicodeError):
                continue
            if start <= modified <= end and re.search(r'(?m)^출처: 스킬 나눔 · [0-9]+기 · 나눔-[a-f0-9]{10} · [0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', body):
                shared_skills.append((modified, folder.name))
    for item in data['lessons']:
        groups['lessons'].append((item, day(item['date']), item['title'], item['source']))
    if available:
        for item in public['items']:
            if not isinstance(item, dict) or item.get('status') != 'approved':
                continue
            kind = item.get('type')
            key = {'skill': 'skills', 'lesson': 'lessons'}.get(kind)
            ident, title, source = (clean(item.get(k)) for k in ('id', 'title', 'source'))
            when = day(item.get('date'))
            if not key or not ident or not title or not source or not when or not start <= when <= end or (key, ident) in seen:
                continue
            seen.add((key, ident))
            groups[key].append((item, when, title, source))
    lines = [f'# 이번 주 일손 리포트 {start}~{end}', '',
             '수집 범위: 일지·브리핑·배운 점의 날짜 기록과 승인 대기함, 승인된 공개 학습 요약 · 한국 시간 · 최근 7일',
             '일손과 사람이 한 일을 기록에서 구분할 수 없으면 확인 필요입니다.', '']
    for key, label in CATEGORIES:
        lines.append('## ' + label)
        rows = groups[key]
        if not rows:
            lines.append('확인 필요 (승인 요청 저장소 조회 실패)' if key == 'needs_review' and approval_error else '확인 필요 (승인된 공개 요약 없음)' if key == 'skills' and not available else '기록 없음')
        if key in ('pending', 'needs_review') and rows:
            lines.append(f'확인된 항목: {len(rows)}건 (자료별 집계, 서로 중복될 수 있음)')
        for item, when, title, source in rows:
            extra = ''
            if key == 'completed':
                actor = {'ilson': '일손', 'person': '사람'}.get(item.get('actor'), '수행자 확인 필요')
                extra = ' · ' + actor
            if key == 'skills' and item.get('origin') == 'skill_share_installed':
                extra = ' · 스킬 나눔으로 설치됨'
            lines.append(f'- {title} · {when} · 출처: {source}{extra}')
        lines.append('')
    lines.append('## 승인 요청 저장소 현황')
    if approval_counts:
        for state, label in (('pending', '승인 대기'), ('approved', '승인됨'), ('changed', '변경됨'), ('rejected', '거절됨'), ('expired', '만료됨'), ('executing', '처리 중'), ('success', '처리 완료'), ('failed', '실패'), ('result_unknown', '결과 확인 필요')):
            if approval_counts.get(state, 0):
                lines.append(f'- {label}: {approval_counts[state]}건 · 출처: 승인 요청 저장소')
        if not any(approval_counts.values()):
            lines.append('기록 없음')
    else:
        lines.append('확인 필요 (조회 실패)' if approval_error else '기록 없음')
    lines.append('')
    lines.append('## 스킬 나눔으로 설치된 스킬')
    if not shared_skills:
        lines.append('기록 없음')
    for modified, _ in shared_skills:
        lines.append(f'- 설치된 스킬 · 파일 마지막 수정일 {modified} · 출처: 스킬 나눔')
    lines.append('')
    lines.append('## 추정 절약 시간')
    rates = settings.get('baseline_minutes', {})
    rates = rates if isinstance(rates, dict) else {}
    counts = {}
    for item, _, _, _ in groups['completed']:
        kind = clean(item.get('work_type'))
        if kind and item.get('actor') == 'ilson':
            counts[kind] = counts.get(kind, 0) + 1
    calculated = []
    missing = []
    for kind, count in sorted(counts.items()):
        try:
            raw = rates[kind]
            if isinstance(raw, bool):
                raise ValueError()
            minutes = Decimal(str(raw))
            if not minutes.is_finite() or minutes < 0:
                raise ValueError()
        except (KeyError, ValueError, InvalidOperation):
            missing.append(kind)
            continue
        calculated.append(minutes * count)
        lines.append(f'- {kind}: {count}건 × 사장님 기준 {minutes}분 = {minutes * count}분')
    if not calculated:
        lines.append('확인 필요: 완료 근거와 업무 유형별 기준 시간이 있어야 계산할 수 있습니다.')
    elif not missing and sum(counts.values()) == len(groups['completed']):
        lines.append(f'- 합계: {sum(calculated)}분 (추정)')
    else:
        lines.append('- 일부만 계산했습니다. 전체 절약 시간은 확인 필요입니다.')
    if missing or sum(counts.values()) != len(groups['completed']):
        lines.append('- 기준 시간 또는 업무 유형이 없는 완료 기록은 계산에서 제외했습니다.')
    lines += ['- 같은 완료 문구는 중복으로 보고 한 번만 계산하며, 일손이 수행했다고 표시된 건만 계산합니다.', '']
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--vault', required=True)
    parser.add_argument('--flat-vault', action='store_true')
    parser.add_argument('--end', help='마지막 날짜 YYYY-MM-DD (한국 시간)')
    args = parser.parse_args(argv)
    end = date.fromisoformat(args.end) if args.end else datetime.now(KST).date()
    vault = Path(args.vault)
    target_dir = vault / 'reports' / 'weekly'
    if not safe_inside(vault, target_dir):
        raise ValueError('보고서 폴더 경로가 링크입니다')
    target_dir.mkdir(parents=True, exist_ok=True)
    if not safe_inside(vault, target_dir):
        raise ValueError('보고서 폴더 경로가 링크입니다')
    target = target_dir / (str(end) + '-ilson.md')
    if target.is_symlink():
        raise ValueError('보고서 경로가 링크입니다')
    content = build(vault, end, flat_vault=args.flat_vault)
    fd, temp = tempfile.mkstemp(prefix='.weekly-', dir=target_dir)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(content)
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    print(target)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
