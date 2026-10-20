"""Claude 배우기 목차와 서버 허용 목록을 강의 파일에 맞춘다.

- catalog.json: 강의 파일의 title/subtitle/minutes/surface를 목차에 옮기고,
  강의가 가리키는 그림이 모두 있을 때만 status를 published로 둔다.
- web-admin-server.py: "Claude 배우기 화면" 주석 아래 줄을 learn/ 폴더의 실제 파일로 다시 쓴다.

사용: python3 tools/sync_learn.py [--check]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEARN = ROOT / 'template/web/current/learn'
SERVER = ROOT / 'template/lib/web-admin-server.py'
MARKER = '# Claude 배우기 화면 — 강의 파일을 추가하면 여기에도 한 줄씩 등록한다.\n'
KINDS = {'.js': 'application/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
         '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml'}
FIRST = ['learn.js', 'learn.css', 'catalog.json']


def figures(lesson):
    found = [lesson['cover']['src']] if lesson.get('cover') else []
    found += [s['figure']['src'] for s in lesson.get('steps', []) if s.get('figure')]
    found += [e['figure']['src'] for e in lesson.get('explain', []) if e.get('figure')]
    return found


def synced_catalog():
    catalog = json.loads((LEARN / 'catalog.json').read_text(encoding='utf-8'))
    report = []
    for track in catalog['tracks']:
        for part in track['parts']:
            for entry in part['lessons']:
                path = LEARN / 'lessons' / f"{entry['id']}.json"
                if not path.exists():
                    continue
                lesson = json.loads(path.read_text(encoding='utf-8'))
                for key in ('title', 'subtitle', 'minutes', 'surface'):
                    entry[key] = lesson[key]
                missing = [src for src in figures(lesson) if not (LEARN / src).exists()]
                entry['status'] = 'soon' if missing else 'published'
                report.append((entry['id'], entry['status'], missing))
    return json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', report


def synced_server():
    files = FIRST + sorted(p.relative_to(LEARN).as_posix() for p in LEARN.rglob('*')
                           if p.is_file() and p.relative_to(LEARN).as_posix() not in FIRST)
    lines = [f"STATIC['/current/learn/{f}'] = ('web/current/learn/{f}', '{KINDS[Path(f).suffix]}')" for f in files]
    text = SERVER.read_text(encoding='utf-8')
    start = text.index(MARKER) + len(MARKER)
    end = text.index('\n\nclass AdminError', start)
    return text[:start] + '\n'.join(lines) + text[end:], len(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='바꾸지 않고 어긋난 곳만 알린다')
    args = parser.parse_args()
    catalog, report = synced_catalog()
    server, count = synced_server()
    stale = [p for p, new in ((LEARN / 'catalog.json', catalog), (SERVER, server))
             if p.read_text(encoding='utf-8') != new]
    for lesson_id, status, missing in report:
        print(lesson_id, status, ' '.join(missing))
    print(count, 'STATIC learn entries')
    if args.check:
        for path in stale:
            print('맞지 않음:', path.relative_to(ROOT))
        return 1 if stale else 0
    (LEARN / 'catalog.json').write_text(catalog, encoding='utf-8')
    SERVER.write_text(server, encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
