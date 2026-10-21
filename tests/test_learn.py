"""Claude 배우기 화면: 정적 등록, 강의 JSON 형식, 그림 안전성, 메뉴 연결, 이스케이프 규칙, 실제 서빙."""
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET

import test_mini_workspace as fixtures

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'template/web/current'
LEARN = WEB / 'learn'
STATIC = fixtures.admin.STATIC
TYPES = {'.js': 'application/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
         '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml', '.txt': 'text/plain; charset=utf-8'}
ID_RE = re.compile(r'^[a-z][0-9]{2}$')
FIG_RE = re.compile(r'^img/[a-z][0-9]{2}-[a-z0-9]+(?:-[a-z0-9]+)*\.svg$')
FILE_RE = re.compile(r'^files/v[0-9]{2}-[a-z0-9]+(-[a-z0-9]+)*\.txt$')
FILE_TEXT = ('<script>fileMarker(1)</script>\n-- {{가게이름}} 그대로 둡니다\n' + ''.join('select %d;\n' % n for n in range(1, 10))
             + '  끝 공백  \n')  # 12줄: 처음 8줄만 보이다가 펼치면 전체
DATE_RE = re.compile(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
PLACEHOLDERS = {'가게이름', '업종', '지역', '대표상품'}
CHECK_IDS = {'claude', 'company', 'trust', 'telegram', 'search'}
SURFACES = {'web', 'ilson', 'both'}
LESSON_KEYS = {'id', 'track', 'part', 'number', 'title', 'subtitle', 'minutes', 'surface', 'checked', 'cover', 'outcome',
               'prepare', 'steps', 'explain', 'trouble', 'checklist', 'keep', 'links', 'sources', 'history'}
STEP_KEYS = {'title', 'why', 'body', 'prompt', 'command', 'memo', 'file', 'self', 'success', 'status', 'figure', 'tip', 'caution'}
EXPLAIN_KEYS = {'heading', 'body', 'table', 'figure'}
TROUBLE_KEYS = {'symptom', 'fix', 'prompt'}
ALLOWED_SVG = {'svg', 'g', 'defs', 'title', 'desc', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon', 'path', 'text',
               'tspan', 'linearGradient', 'radialGradient', 'stop', 'clipPath', 'marker', 'symbol', 'use', 'style'}
SVG_POLICY = "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; sandbox"
NODE = shutil.which('node')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def catalog():
    return read_json(LEARN / 'catalog.json')


def catalog_rows():
    rows = []
    for track in catalog()['tracks']:
        for part in track['parts']:
            for lesson in part['lessons']:
                rows.append((track, part, lesson))
    return rows


def published():
    return [(t, p, l) for t, p, l in catalog_rows() if l['status'] == 'published' and t['status'] != 'soon']


def lesson_files():
    return sorted((LEARN / 'lessons').glob('*.json')) if (LEARN / 'lessons').is_dir() else []


def file_refs(lesson):
    return [step['file'].get('src') for step in lesson.get('steps', []) if isinstance(step, dict) and isinstance(step.get('file'), dict)]


def figures(lesson):
    found = []
    if isinstance(lesson.get('cover'), dict):
        found.append(('cover', lesson['cover']))
    for i, step in enumerate(lesson.get('steps', [])):
        if isinstance(step, dict) and 'figure' in step:
            found.append(('steps[%d]' % i, step['figure']))
    for i, item in enumerate(lesson.get('explain', [])):
        if isinstance(item, dict) and 'figure' in item:
            found.append(('explain[%d]' % i, item['figure']))
    return found


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


TRACK_BY_LETTER = {'b': 'basic', 'v': 'vibe'}


def track_problems(data):
    """과정마다 id(b01.., v01..)·강 번호·부 번호가 1부터 순서대로인지 본다. 문제 목록을 돌려준다."""
    problems = []
    letter = {track: key for key, track in TRACK_BY_LETTER.items()}
    for track in data['tracks']:
        if track['id'] not in letter:
            problems.append('모르는 과정 ' + track['id'])
            continue
        lessons = [l for part in track['parts'] for l in part['lessons']]
        want = [letter[track['id']] + '%02d' % n for n in range(1, len(lessons) + 1)]
        if [l['id'] for l in lessons] != want:
            problems.append('%s: id 순서 %s' % (track['id'], [l['id'] for l in lessons]))
        if [l['number'] for l in lessons] != list(range(1, len(lessons) + 1)):
            problems.append('%s: 강 번호 순서' % track['id'])
        if [part['number'] for part in track['parts']] != list(range(1, len(track['parts']) + 1)):
            problems.append('%s: 부 번호 순서' % track['id'])
    return problems


def vibe_fixture(vibe_status='open'):
    """심화 과정이 열린 상황을 흉내 내는 시험용 목록과 강의. learn/ 폴더에는 만들지 않는다."""
    def row(lesson_id, number, title, status='published', surface='both'):
        return {'id': lesson_id, 'number': number, 'title': title, 'subtitle': title + ' 부제', 'minutes': 6,
                'surface': surface, 'status': status}
    data = {'version': '2026-10-21', 'intro': '시험용 목록', 'example_shop': {'name': '시험가게', 'kind': '빵집', 'area': '시험동', 'product': '식빵'},
            'tracks': [
                {'id': 'basic', 'title': '기본 과정', 'summary': '기본 요약', 'status': 'open', 'parts': [
                    {'number': 1, 'title': '시작', 'lessons': [row('b01', 1, '기본 첫 강', surface='web'), row('b02', 2, '기본 끝 강', surface='web')]}]},
                {'id': 'vibe', 'title': '바이브 코딩 심화', 'summary': '심화 요약', 'status': vibe_status, 'parts': [
                    {'number': 1, 'title': '만들 것 정하기', 'lessons': [row('v01', 1, '한 장으로 정하기'), row('v02', 2, '첫 화면')]},
                    {'number': 2, 'title': '저장하기', 'lessons': [row('v03', 3, '저장점', 'soon')]}]}]}
    lessons = {}
    for track in data['tracks']:
        for part in track['parts']:
            for entry in part['lessons']:
                if entry['status'] == 'published':
                    lessons[entry['id']] = {
                        'id': entry['id'], 'track': track['id'], 'part': part['number'], 'number': entry['number'],
                        'title': entry['title'], 'subtitle': entry['subtitle'], 'minutes': entry['minutes'], 'surface': entry['surface'],
                        'checked': '2026-10-21', 'outcome': ['시험 결과물'],
                        'steps': [{'title': '시험 단계', 'body': ['시험 본문'], 'prompt': {'text': '{{가게이름}} 시험 부탁'},
                                   'file': {'src': 'files/v01-sample.txt', 'label': '시험 자료 파일', 'note': '시험 설명'}}],
                        'checklist': ['시험 확인'], 'keep': ['시험 정리'], 'history': [{'date': '2026-10-21', 'note': '시험'}]}
    return data, lessons


class 정적등록시험(unittest.TestCase):
    def test_learn폴더의_모든파일이_STATIC에_있고_그반대도_맞다(self):
        files = {'/current/' + p.relative_to(WEB).as_posix() for p in LEARN.rglob('*') if p.is_file()}
        registered = {k for k in STATIC if k.startswith('/current/learn/')}
        self.assertEqual(files - set(STATIC), set(), 'STATIC에 등록하지 않은 배우기 파일')
        self.assertEqual({k for k in registered if not (ROOT / 'template' / STATIC[k][0]).is_file()}, set(), '없는 파일을 가리키는 STATIC')
        for key in registered:
            relative, kind = STATIC[key]
            self.assertEqual(relative, 'web' + key, key)
            self.assertEqual(kind, TYPES[Path(key).suffix], key)

    def test_목차와_STATIC이_강의파일과_맞는다(self):
        # 강의를 고치거나 더하면 python3 tools/sync_learn.py 로 맞춘다.
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'tools/sync_learn.py'), '--check'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_업데이트가_싣는_형식과_서버크기상한을_지킨다(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('learn_updater', ROOT / 'tools/update.py')
        updater = importlib.util.module_from_spec(spec); spec.loader.exec_module(updater)
        for path in LEARN.rglob('*'):
            if path.is_file():
                self.assertIn(path.suffix, TYPES, path)
                self.assertTrue(updater.allowed('box', 'web/' + path.relative_to(WEB.parent).as_posix()), path)
                self.assertTrue(updater.allowed('cli', path.relative_to(ROOT).as_posix()), path)
                # 서버의 일반 정적 파일 상한(1 MiB)
                self.assertLessEqual(path.stat().st_size, 1024 * 1024, path)
        self.assertLessEqual((LEARN / 'learn.js').stat().st_size, 64 * 1024)
        for path in lesson_files():
            self.assertLessEqual(path.stat().st_size, 100 * 1024, path)


class 목록시험(unittest.TestCase):
    def test_목록은_형식이맞고_id가_겹치지않는다(self):
        data = catalog()
        self.assertTrue(DATE_RE.match(data['version']))
        self.assertIsInstance(data['intro'], str)
        self.assertEqual(set(data['example_shop']), {'name', 'kind', 'area', 'product'})
        self.assertTrue(all(isinstance(v, str) and v for v in data['example_shop'].values()))
        tracks = data['tracks']
        self.assertEqual([t['id'] for t in tracks], ['basic', 'vibe'])
        for track in tracks:
            self.assertIn(track['status'], {'open', 'soon'})
            self.assertIsInstance(track['title'], str)
            self.assertIsInstance(track['summary'], str)
            self.assertIsInstance(track['parts'], list)
        ids = [l['id'] for _, _, l in catalog_rows()]
        self.assertEqual(len(ids), len(set(ids)), '강 id 중복')
        self.assertEqual([l['id'] for t, _, l in catalog_rows() if t['id'] == 'basic'], ['b%02d' % n for n in range(1, 23)])
        self.assertEqual(track_problems(data), [])
        for track, part, lesson in catalog_rows():
            with self.subTest(lesson=lesson.get('id')):
                self.assertTrue(ID_RE.match(lesson['id']))
                self.assertIsInstance(part['number'], int)
                self.assertIsInstance(part['title'], str)
                self.assertIsInstance(lesson['number'], int)
                self.assertTrue(lesson['title'] and isinstance(lesson['title'], str))
                self.assertIsInstance(lesson['subtitle'], str)
                self.assertIsInstance(lesson['minutes'], int)
                self.assertTrue(1 <= lesson['minutes'] <= 30)
                self.assertIn(lesson['surface'], SURFACES)
                self.assertIn(lesson['status'], {'published', 'soon'})
                self.assertEqual(TRACK_BY_LETTER.get(lesson['id'][0]), track['id'], 'id 첫 글자와 과정이 맞아야 합니다')

    def test_과정순서점검이_잘못된목록을_찾아낸다(self):
        good, _ = vibe_fixture()
        self.assertEqual(track_problems(good), [])
        self.assertEqual(track_problems(vibe_fixture('soon')[0]), [])
        swapped = json.loads(json.dumps(good))
        lessons = swapped['tracks'][1]['parts'][0]['lessons']
        lessons[0], lessons[1] = lessons[1], lessons[0]
        self.assertTrue(track_problems(swapped))
        wrong_track = json.loads(json.dumps(good))
        wrong_track['tracks'][1]['parts'][1]['lessons'][0]['id'] = 'b03'
        self.assertTrue(track_problems(wrong_track))
        restarted = json.loads(json.dumps(good))
        restarted['tracks'][1]['parts'][1]['lessons'][0]['number'] = 1
        self.assertTrue(track_problems(restarted), '심화 강 번호는 부가 바뀌어도 이어서 매긴다')
        parts = json.loads(json.dumps(good))
        parts['tracks'][1]['parts'][1]['number'] = 3
        self.assertTrue(track_problems(parts))

    def test_발행된강은_파일이있고_목록과_일치한다(self):
        self.assertTrue(published(), '발행된 강이 하나는 있어야 합니다')
        for track, part, entry in published():
            with self.subTest(lesson=entry['id']):
                path = LEARN / 'lessons' / (entry['id'] + '.json')
                self.assertTrue(path.is_file(), path)
                lesson = read_json(path)
                self.assertEqual(lesson['id'], entry['id'])
                self.assertEqual(lesson['track'], track['id'])
                self.assertEqual(lesson['part'], part['number'])
                self.assertEqual(lesson['number'], entry['number'])
                self.assertEqual(lesson['surface'], entry['surface'])
                self.assertEqual(lesson['title'], entry['title'])
                self.assertEqual(lesson['subtitle'], entry['subtitle'])
                self.assertEqual(lesson['minutes'], entry['minutes'])


class 강의형식시험(unittest.TestCase):
    def check_text(self, value, where, limit=600, required=False):
        self.assertIsInstance(value, str, where)
        if required:
            self.assertTrue(value.strip(), where)
        self.assertLessEqual(len(value), limit, where)

    def check_list(self, value, where, limit=600):
        self.assertIsInstance(value, list, where)
        for i, item in enumerate(value):
            self.check_text(item, '%s[%d]' % (where, i), limit)

    def check_links(self, value, where):
        self.assertIsInstance(value, list, where)
        for i, link in enumerate(value):
            self.assertIsInstance(link, dict, where)
            self.check_text(link.get('label'), '%s[%d].label' % (where, i), 120, True)
            self.assertRegex(link.get('url', ''), r'^https://[^\s<>"\'`]+$', '%s[%d].url는 https만' % (where, i))

    def check_figure(self, value, where):
        self.assertIsInstance(value, dict, where)
        self.assertRegex(value.get('src', ''), FIG_RE, where)
        self.check_text(value.get('alt'), where + '.alt', 200, True)
        self.check_text(value.get('caption'), where + '.caption', 200, True)

    def check_lesson(self, lesson, name):
        self.assertLessEqual(set(lesson) - LESSON_KEYS, set(), name + ': 모르는 항목')
        self.assertTrue(ID_RE.match(lesson['id']), name)
        self.assertIn(lesson['id'][0], TRACK_BY_LETTER, name)
        self.assertEqual(lesson['track'], TRACK_BY_LETTER[lesson['id'][0]], name)
        self.assertIsInstance(lesson['part'], int)
        self.assertIsInstance(lesson['number'], int)
        self.check_text(lesson['title'], name + '.title', 80, True)
        self.assertNotRegex(lesson['title'], r'[`*]', name + '.title: 제목은 글자 그대로 보여서 꾸밈 기호를 쓰지 않는다')
        self.check_text(lesson['subtitle'], name + '.subtitle', 80)
        self.assertIsInstance(lesson['minutes'], int)
        self.assertTrue(1 <= lesson['minutes'] <= 30)
        self.assertIn(lesson['surface'], SURFACES)
        self.assertRegex(lesson['checked'], DATE_RE)
        self.check_list(lesson['outcome'], name + '.outcome', 200)
        self.assertTrue(1 <= len(lesson['outcome']) <= 3, name + '.outcome는 1~3개')
        if 'cover' in lesson:
            self.check_figure(lesson['cover'], name + '.cover')
        if 'prepare' in lesson:
            self.check_list(lesson['prepare'], name + '.prepare', 200)
        self.assertIsInstance(lesson['steps'], list)
        self.assertTrue(1 <= len(lesson['steps']) <= 6, name + '.steps는 1~6개')
        for i, step in enumerate(lesson['steps']):
            where = '%s.steps[%d]' % (name, i)
            self.assertIsInstance(step, dict, where)
            self.assertLessEqual(set(step) - STEP_KEYS, set(), where + ': 모르는 항목')
            self.check_text(step.get('title'), where + '.title', 80, True)
            self.assertNotRegex(step['title'], r'[`*]', where + '.title: 제목은 글자 그대로 보여서 꾸밈 기호를 쓰지 않는다')
            for key in ('why', 'self', 'success', 'tip', 'caution'):
                if key in step:
                    self.check_text(step[key], where + '.' + key, 400)
            if 'body' in step:
                self.check_list(step['body'], where + '.body', 300)
            for key in ('prompt', 'command', 'memo'):
                if key in step:
                    self.assertIsInstance(step[key], dict, where + '.' + key)
                    self.check_text(step[key].get('text'), where + '.' + key + '.text', 1500, True)
                    self.assertLessEqual(set(step[key]) - {'text', 'note'}, set(), where + '.' + key)
                    if 'note' in step[key]:
                        self.check_text(step[key]['note'], where + '.' + key + '.note', 300)
            if 'file' in step:
                self.assertIsInstance(step['file'], dict, where + '.file')
                self.assertLessEqual(set(step['file']) - {'src', 'label', 'note'}, set(), where + '.file')
                self.assertRegex(step['file'].get('src', ''), FILE_RE, where + '.file.src')
                self.check_text(step['file'].get('label'), where + '.file.label', 80, True)
                if 'note' in step['file']:
                    self.check_text(step['file']['note'], where + '.file.note', 400)
            if 'status' in step:
                self.assertIsInstance(step['status'], list, where)
                self.assertLessEqual(set(step['status']) - CHECK_IDS, set(), where + '.status')
            if 'figure' in step:
                self.check_figure(step['figure'], where + '.figure')
        for i, item in enumerate(lesson.get('explain', [])):
            where = '%s.explain[%d]' % (name, i)
            self.assertIsInstance(item, dict, where)
            self.assertLessEqual(set(item) - EXPLAIN_KEYS, set(), where)
            if 'heading' in item:
                self.check_text(item['heading'], where + '.heading', 80)
                self.assertNotRegex(item['heading'], r'[`*]', where + '.heading: 제목은 글자 그대로 보여서 꾸밈 기호를 쓰지 않는다')
            if 'body' in item:
                self.check_list(item['body'], where + '.body', 400)
            if 'table' in item:
                table = item['table']
                self.check_list(table.get('head', []), where + '.table.head', 80)
                self.assertIsInstance(table.get('rows'), list, where)
                for row in table['rows']:
                    self.check_list(row, where + '.table.rows', 200)
            if 'figure' in item:
                self.check_figure(item['figure'], where + '.figure')
        for i, item in enumerate(lesson.get('trouble', [])):
            where = '%s.trouble[%d]' % (name, i)
            self.assertIsInstance(item, dict, where)
            self.assertLessEqual(set(item) - TROUBLE_KEYS, set(), where)
            self.check_text(item.get('symptom'), where + '.symptom', 200, True)
            self.check_text(item.get('fix'), where + '.fix', 400, True)
            if 'prompt' in item:
                self.check_text(item['prompt'], where + '.prompt', 1500, True)
        if 'checklist' in lesson:
            self.check_list(lesson['checklist'], name + '.checklist', 200)
            self.assertLessEqual(len(lesson['checklist']), 4)
        if 'keep' in lesson:
            self.check_list(lesson['keep'], name + '.keep', 200)
            self.assertLessEqual(len(lesson['keep']), 3)
        for key in ('links', 'sources'):
            if key in lesson:
                self.check_links(lesson[key], name + '.' + key)
        for i, item in enumerate(lesson.get('history', [])):
            self.assertRegex(item.get('date', ''), DATE_RE)
            self.check_text(item.get('note'), '%s.history[%d].note' % (name, i), 200, True)
        for text in strings(lesson):
            for found in re.findall(r'\{\{([^{}]*)\}\}', text):
                self.assertIn(found, PLACEHOLDERS, name + ': 모르는 자리표시 {{' + found + '}}')

    def test_심화과정_시험강의도_같은형식을_지킨다(self):
        for lesson_id, lesson in vibe_fixture()[1].items():
            with self.subTest(lesson=lesson_id):
                self.check_lesson(lesson, lesson_id)

    def test_모든강의파일이_형식을_지킨다(self):
        files = lesson_files()
        self.assertTrue(files)
        known = {l['id'] for _, _, l in catalog_rows()}
        for path in files:
            with self.subTest(file=path.name):
                lesson = read_json(path)
                self.assertEqual(path.stem, lesson['id'])
                self.assertIn(lesson['id'], known)
                self.check_lesson(lesson, path.name)


class 그림시험(unittest.TestCase):
    def check_svg(self, path):
        self.assertLessEqual(path.stat().st_size, 60 * 1024, path.name)
        raw = path.read_text(encoding='utf-8')
        lowered = raw.lower()
        self.assertNotIn('<script', lowered)
        self.assertNotIn('foreignobject', lowered)
        self.assertNotRegex(lowered, r'url\(\s*(?!#)', '외부 url() 참조')
        self.assertNotIn('@import', lowered)
        root = ET.fromstring(raw)
        self.assertEqual(root.tag.rsplit('}', 1)[-1], 'svg')
        for node in root.iter():
            tag = node.tag.rsplit('}', 1)[-1]
            self.assertIn(tag, ALLOWED_SVG, '%s: 허용하지 않는 요소 <%s>' % (path.name, tag))
            for name, value in node.attrib.items():
                local = name.rsplit('}', 1)[-1].lower()
                self.assertFalse(local.startswith('on'), '%s: 이벤트 속성 %s' % (path.name, name))
                if local == 'href':
                    self.assertTrue(value.startswith('#'), '%s: 외부 링크 %s' % (path.name, value))

    def test_그림폴더의_모든SVG가_작고_안전하다(self):
        folder = LEARN / 'img'
        if not folder.is_dir():
            self.skipTest('그림 폴더가 아직 없습니다.')
        for path in sorted(folder.iterdir()):
            if path.is_file():
                with self.subTest(file=path.name):
                    self.assertEqual(path.suffix, '.svg')
                    self.assertRegex('img/' + path.name, FIG_RE)
                    self.check_svg(path)

    def test_발행된강의_그림은_있고_등록된다(self):
        for _, _, entry in published():
            lesson = read_json(LEARN / 'lessons' / (entry['id'] + '.json'))
            for where, figure in figures(lesson):
                with self.subTest(lesson=entry['id'], where=where):
                    src = figure.get('src', '')
                    self.assertRegex(src, FIG_RE)
                    self.assertTrue((LEARN / src).is_file(), src)
                    self.assertEqual(STATIC.get('/current/learn/' + src), ('web/current/learn/' + src, 'image/svg+xml'))

    def test_그림폴더에_쓰이지않는_파일이_없다(self):
        folder = LEARN / 'img'
        if not folder.is_dir():
            self.skipTest('그림 폴더가 아직 없습니다.')
        used = set()
        for path in lesson_files():
            used.update(f.get('src') for _, f in figures(read_json(path)) if isinstance(f, dict))
        used.update(s for s in strings(catalog()) if FIG_RE.match(s))
        for path in folder.iterdir():
            if path.is_file():
                self.assertIn('img/' + path.name, used, '어느 강에도 쓰이지 않는 그림: ' + path.name)


class 자료파일시험(unittest.TestCase):
    def test_자료파일은_이름_등록_크기_UTF8_규칙을_지킨다(self):
        folder = LEARN / 'files'
        if not folder.is_dir():
            self.skipTest('자료 파일 폴더가 아직 없습니다.')
        for path in sorted(folder.iterdir()):
            with self.subTest(file=path.name):
                self.assertTrue(path.is_file())
                self.assertRegex('files/' + path.name, FILE_RE)
                self.assertEqual(STATIC.get('/current/learn/files/' + path.name),
                                 ('web/current/learn/files/' + path.name, 'text/plain; charset=utf-8'))
                self.assertLessEqual(path.stat().st_size, 64 * 1024)
                raw = path.read_bytes()
                raw.decode('utf-8')  # 깨진 UTF-8이면 여기서 실패한다.
                self.assertFalse(raw.startswith(b'\xef\xbb\xbf'), 'BOM이 있으면 복사한 글이 파일과 달라집니다')

    def test_발행된강의_자료파일은_있고_등록된다(self):
        for _, _, entry in published():
            lesson = read_json(LEARN / 'lessons' / (entry['id'] + '.json'))
            for src in file_refs(lesson):
                with self.subTest(lesson=entry['id'], src=src):
                    self.assertRegex(src, FILE_RE)
                    self.assertTrue((LEARN / src).is_file(), src)
                    self.assertEqual(STATIC.get('/current/learn/' + src), ('web/current/learn/' + src, 'text/plain; charset=utf-8'))

    def test_자료파일폴더에_쓰이지않는_파일이_없다(self):
        folder = LEARN / 'files'
        if not folder.is_dir():
            self.skipTest('자료 파일 폴더가 아직 없습니다.')
        used = {src for path in lesson_files() for src in file_refs(read_json(path))}
        for path in folder.iterdir():
            self.assertIn('files/' + path.name, used, '어느 강에도 쓰이지 않는 자료 파일: ' + path.name)

    def test_txt는_업데이트와_정리도구가_함께_싣는다(self):
        import importlib.util
        loaded = {}
        for name, path in (('learn_updater_txt', 'tools/update.py'), ('learn_sync_txt', 'tools/sync_learn.py')):
            spec = importlib.util.spec_from_file_location(name, ROOT / path)
            loaded[path] = importlib.util.module_from_spec(spec); spec.loader.exec_module(loaded[path])
        updater, sync = loaded['tools/update.py'], loaded['tools/sync_learn.py']
        self.assertTrue(updater.allowed('box', 'web/current/learn/files/v01-schema.txt'))
        self.assertTrue(updater.allowed('cli', 'template/web/current/learn/files/v01-schema.txt'))
        self.assertEqual(sync.KINDS, TYPES)
        lesson = {'steps': [{'title': 't', 'file': {'src': 'files/v09-missing.txt', 'label': 'x'}}]}
        self.assertEqual(sync.files(lesson), ['files/v09-missing.txt'], '빠진 자료 파일이 있으면 강을 공개하지 않는다')


class 메뉴연결시험(unittest.TestCase):
    def test_메뉴_주소_화면맵에_배우기가_등록된다(self):
        shell = (WEB / 'shell.js').read_text(encoding='utf-8')
        self.assertIn("{group:'배우기'}", shell)
        self.assertIn("{id:'learn',icon:'graduation-cap',label:'Claude 배우기'}", shell)
        allowed = re.search(r"if\(!\[([^\]]*)\]\.includes\(tab\)\)return;", shell)
        self.assertIsNotNone(allowed)
        self.assertIn("'learn'", allowed.group(1))
        self.assertIn("learn:()=>", shell)
        self.assertIn("IlsonLearn.query()", shell)
        # 배우기 안에서 메뉴를 누르면 목차(home), 나갈 때 자리 기억, 돌아오면 같은 강·같은 자리
        self.assertIn("learn.menu();return;", shell)
        self.assertIn("learn?.leave()", shell)
        self.assertIn("if(tab==='learn')learn?.restore();", shell)
        icons = (WEB / 'icons.js').read_text(encoding='utf-8')
        for name in ('GraduationCap', 'NotebookPen'):
            self.assertIn(name, icons)

    def test_체크박스에_초점이있어도_상태갱신을_막지않는다(self):
        shell = (WEB / 'shell.js').read_text(encoding='utf-8')
        line = next(l for l in shell.splitlines() if l.startswith('const typing='))
        self.assertIn("'checkbox'", line)
        self.assertIn('TEXTAREA', line)

    def test_화면파일은_shell보다_먼저_불러온다(self):
        page = (WEB / 'index.html').read_text(encoding='utf-8')
        self.assertIn('<link rel="stylesheet" href="learn/learn.css">', page)
        self.assertIn('<script src="learn/learn.js" defer></script>', page)
        self.assertLess(page.index('learn/learn.js'), page.index('shell.js'))


POISON = '<x-p onclick="alert(1)">\'&amp;{{가게이름}}'
STRUCTURAL = {'id', 'status', 'surface', 'track', 'src', 'url', 'state', 'version'}


def poison(value, key=None):
    """구조용 값(id·상태·주소)만 남기고 모든 글자에 HTML 조각을 붙인다."""
    if isinstance(value, dict):
        return {k: poison(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [poison(v, key) for v in value]
    if isinstance(value, str) and key not in STRUCTURAL:
        return value + POISON
    return value


HARNESS = r"""
const vm = require('vm'), fs = require('fs');
const P = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const src = fs.readFileSync(P.js, 'utf8');
function make(search, storage, files) {
  const fetched = [], copied = [], main = { scrollTop: 0 };
  const store = storage === null ? null : new Map(Object.entries(storage));
  const guard = () => { if (!store) throw new Error('blocked'); };
  const ctx = {
    console, URL, URLSearchParams, setTimeout, clearTimeout,
    location: { search, assign() {} }, history: { pushState() {}, replaceState() {} },
    document: { getElementById: id => id === 'main' ? main : null, querySelector: () => null, querySelectorAll: () => [], addEventListener() {}, removeEventListener() {} },
    navigator: { clipboard: { writeText: async t => { copied.push(t); } } },
    localStorage: { getItem(k) { guard(); return store.has(k) ? store.get(k) : null; }, setItem(k, v) { guard(); store.set(k, String(v)); }, removeItem(k) { guard(); store.delete(k); } },
    fetch: async path => { fetched.push(path); return path in files ? { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(files[path])), text: async () => String(files[path]) } : { ok: false, status: 404, json: async () => ({}), text: async () => '' }; },
    addEventListener() {}, scrollTo() {}
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(src, ctx);
  return { L: ctx.IlsonLearn, fetched, copied, store, main };
}
const tick = () => new Promise(r => setTimeout(r, 0));
async function settle(env) { let html = ''; for (let i = 0; i < 6; i++) { html = env.L.render(); await tick(); } return html; }
(async () => {
  const out = {};
  const base = { 'learn/catalog.json': P.catalog, '/api/overview': P.overview };
  const a = make('?tab=learn&lesson=b01', null, { ...base, 'learn/lessons/b01.json': P.evil, 'learn/files/v01-sample.txt': P.file_text });
  out.a_html = await settle(a);
  out.a_fetched_first = a.fetched.slice();
  a.L.copy('p0'); a.L.copy('m0'); await tick();
  a.L.fileCopy(0); out.a_file_ready = await settle(a);
  a.L.fileToggle(0); out.a_file_open = await settle(a);
  a.L.fileCopy(0); await settle(a);
  a.L.fileToggle(1); a.L.fileToggle(2); out.a_file_error = await settle(a);
  out.a_copied = a.copied; out.a_fetched = a.fetched;
  a.L.toggleLarge(); out.a_large = a.L.render().includes('lr-large');
  const a2 = make('?tab=learn', {}, { 'learn/catalog.json': P.catalog, '/api/overview': P.overview_placeholder });
  out.a2_html = await settle(a2);
  const b = make('?tab=learn&lesson=b01', { 'ilson-learn-shop': JSON.stringify({ name: '<i>가게</i>' }) }, { ...base, 'learn/lessons/b01.json': P.real });
  out.b_html = await settle(b);
  b.L.toggleDone(); out.b_progress = JSON.parse(b.store.get('ilson-learn-progress'));
  const c1 = make('?tab=learn&lesson=../x', {}, base); await settle(c1); out.c1_fetched = c1.fetched;
  const c2 = make('?tab=learn&lesson=' + P.soon_id, {}, base); out.c2_html = await settle(c2); out.c2_fetched = c2.fetched; out.c2_query = c2.L.query();
  const d = make('?tab=learn', {}, base); out.d_html = await settle(d); out.d_query = d.L.query();
  // 다른 메뉴에 다녀와도 같은 강·같은 자리, 강 안에서 메뉴를 누르면 목차
  const e = make('?tab=learn', {}, { ...base, 'learn/lessons/b01.json': P.real }); await settle(e);
  e.main.scrollTop = 300; e.L.open('b01'); await settle(e); out.e_open_query = e.L.query();
  e.main.scrollTop = 480; e.L.leave(); e.main.scrollTop = 0; e.L.restore(); out.e_restored = e.main.scrollTop;
  e.L.menu(); out.e_menu_query = e.L.query(); out.e_catalog_top = e.main.scrollTop;
  // 모든 글자를 오염시킨 실제 목록·강의·상태
  const p1 = make('?tab=learn&lesson=b02', { 'ilson-learn-shop': JSON.stringify(P.poison_shop) }, { 'learn/catalog.json': P.p_catalog, '/api/overview': P.p_overview, 'learn/lessons/b02.json': P.p_lesson });
  out.p1_html = await settle(p1);
  p1.L.home(); out.p1_catalog = p1.L.render();
  const p2 = make('?tab=learn', {}, { 'learn/catalog.json': P.p_catalog, '/api/overview': P.p_overview });
  out.p2_html = await settle(p2);
  // 심화 과정이 열린 시험용 목록
  const vfiles = (cat, lessons) => Object.assign({ 'learn/catalog.json': cat, '/api/overview': P.overview },
    Object.fromEntries(Object.entries(lessons).map(([id, l]) => ['learn/lessons/' + id + '.json', l])));
  const prog = ids => JSON.stringify(Object.fromEntries(ids.map(id => [id, { done: true }])));
  const V = vfiles(P.vibe_catalog, P.vibe_lessons);
  out.v_catalog = await settle(make('?tab=learn', { 'ilson-learn-progress': prog(['b01']) }, V));
  out.v_resume_vibe = await settle(make('?tab=learn', { 'ilson-learn-progress': prog(['b01', 'b02']), 'ilson-learn-last': '"v02"' }, V));
  out.v_resume_basic = await settle(make('?tab=learn', { 'ilson-learn-progress': prog(['v01']), 'ilson-learn-last': '"v01"' }, V));
  out.v_resume_basic2 = await settle(make('?tab=learn', { 'ilson-learn-progress': prog(['b01']), 'ilson-learn-last': '"v02"' }, V));
  out.v_all_done = await settle(make('?tab=learn', { 'ilson-learn-progress': prog(['b01', 'b02', 'v01', 'v02']) }, V));
  out.v_lesson1 = await settle(make('?tab=learn&lesson=v01', {}, V));
  out.v_lesson2 = await settle(make('?tab=learn&lesson=v02', {}, V));
  out.v_basic_end = await settle(make('?tab=learn&lesson=b02', {}, V));
  const VS = vfiles(P.vibe_soon_catalog, P.vibe_lessons);
  out.v_soon_end = await settle(make('?tab=learn&lesson=b02', {}, VS));
  out.v_soon_catalog = await settle(make('?tab=learn', {}, VS));
  const vs = make('?tab=learn&lesson=v01', {}, VS); out.v_soon_lesson = await settle(vs); out.v_soon_fetched = vs.fetched;
  const PV = vfiles(P.p_vibe_catalog, P.p_vibe_lessons);
  out.pv_catalog = await settle(make('?tab=learn', { 'ilson-learn-progress': prog(['b01', 'b02']) }, PV));
  out.pv_lesson = await settle(make('?tab=learn&lesson=v01', {}, PV));
  out.pv_end = await settle(make('?tab=learn&lesson=b02', {}, PV));
  console.log(JSON.stringify(out));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


class 이스케이프시험(unittest.TestCase):
    harness_output = None

    def setUp(self):
        self.source = (LEARN / 'learn.js').read_text(encoding='utf-8')

    def test_esc가_다섯글자를_바꾸고_HTML주입API를_쓰지않는다(self):
        self.assertIn("const esc = value =>", self.source)
        self.assertIn("/[&<>\"']/g", self.source)
        for entity in ('&amp;', '&lt;', '&gt;', '&quot;', '&#39;'):
            self.assertIn(entity, self.source)
        for banned in ('innerHTML', 'outerHTML', 'insertAdjacentHTML', 'document.write', 'eval(', 'new Function', 'srcdoc'):
            self.assertNotIn(banned, self.source, banned)

    def test_강의값을_그대로_끼워넣지_않는다(self):
        # ${step.title} 처럼 객체 속성을 esc()/inl() 없이 HTML 문자열에 넣으면 실패한다.
        raw = re.compile(r"\$\{\s*[A-Za-z_$][\w$]*(?:\??\.[\w$]+|\[[^\]]*\])+\s*(?:(?:\|\||\?\?)\s*(?:''|\"\"))?\s*\}")
        self.assertEqual(raw.findall(self.source), [])
        self.assertGreater(self.source.count('${esc('), 20)
        self.assertGreater(self.source.count('${inl('), 10)
        for match in re.finditer(r'target="_blank"', self.source):
            self.assertIn('rel="noopener noreferrer"', self.source[match.start():match.start() + 60])

    def test_인라인처리기에는_검증한_값만_들어간다(self):
        handlers = re.findall(r'\son[a-z]+="([^"]*)"', self.source)
        self.assertGreater(len(handlers), 10)
        for handler in handlers:
            for expression in re.findall(r'\$\{([^}]*)\}', handler):
                self.assertRegex(expression.strip(), r'^esc\((id|src|key|i)\)$', handler)

    def node_or_skip(self):
        if NODE:
            return
        if os.environ.get('CI') == '1':
            self.fail('CI=1에서는 node가 있어야 렌더링 이스케이프를 확인할 수 있습니다.')
        self.skipTest('JS 실행기는 로컬 브라우저 검증 환경에서 사용합니다.')

    def run_harness(self):
        # 한 번만 실행하고 시험끼리 결과를 나눠 쓴다.
        if 이스케이프시험.harness_output is None:
            이스케이프시험.harness_output = self.render_with_node()
        return 이스케이프시험.harness_output

    def render_with_node(self):
        real_catalog = catalog()
        real_lesson = read_json(LEARN / 'lessons/b01.json')
        evil = {
            'id': 'b01', 'track': 'basic', 'part': 1, 'number': 1,
            'title': '<img src=x onerror=alert(1)>', 'subtitle': '**<script>alert(1)</script>**',
            'minutes': 5, 'surface': 'both', 'checked': '2026-10-20', 'outcome': ['<b>결과</b>'],
            'cover': {'src': '../../shell.js', 'alt': 'x', 'caption': 'x'},
            'steps': [{'title': '<b>t</b>', 'body': ['`<svg onload=x>` 와 **굵게**'],
                       'prompt': {'text': '{{가게이름}} <i>x</i> {{없는것}}'},
                       'memo': {'text': '{{업종}} <i>m</i>', 'note': '<u>n</u>'}, 'status': ['claude', 'evil'],
                       'file': {'src': 'files/v01-sample.txt', 'label': '<b>파일</b>', 'note': '<i>n</i>'}},
                      {'title': 'bad', 'file': {'src': 'files/../v01-x.txt', 'label': 'bad'}},
                      {'title': 'missing', 'file': {'src': 'files/v01-missing.txt', 'label': 'missing'}}],
            'explain': [{'heading': 'h', 'figure': {'src': 'img/b01-sample.svg" onerror="x', 'alt': 'a', 'caption': 'c'}}],
            'links': [{'label': 'bad', 'url': 'javascript:alert(1)'}, {'label': 'quote', 'url': 'https://example.com/a"b'},
                      {'label': '<u>ok</u>', 'url': 'https://example.com/x'}],
            'checklist': ['<x>'], 'history': [{'date': '<d>', 'note': 'n'}],
        }
        overview = {'box': {'company_name': '<회사>', 'sandbox': False},
                    'checks': [{'id': 'claude', 'state': 'ok', 'label': '<L>', 'detail': '<D>'},
                               {'id': 'company', 'state': 'ok', 'label': '회사 정보', 'detail': ''}]}
        placeholder = {'box': {'company_name': '우리 회사', 'sandbox': False},
                       'checks': [{'id': 'company', 'state': 'attention', 'label': '회사 정보', 'detail': '비어 있음'}]}
        source = read_json(LEARN / 'lessons/b02.json')
        source['steps'][0]['memo'] = {'text': '{{업종}} 메모 틀', 'note': '메모 설명'}
        p_catalog = poison(real_catalog)
        for track in p_catalog['tracks']:
            for part in track['parts']:
                for lesson in part['lessons']:
                    if lesson['id'] == 'b02':
                        lesson['status'] = 'published'
        p_overview = poison({'box': {'company_name': '시험 회사', 'sandbox': True, 'setup_state': 'pending'},
                             'checks': [{'id': c, 'state': 'ok', 'label': c, 'detail': c + ' 상세'}
                                        for c in ('claude', 'company', 'trust', 'telegram', 'search')]})
        soon = next((l['id'] for _, _, l in catalog_rows() if l['status'] == 'soon'), None)
        if soon is None:
            # 모든 강이 공개된 뒤에도 '준비 중' 강을 받지 않는지 보려고 시험용 강을 하나 끼워 넣는다.
            soon = 'b99'
            real_catalog['tracks'][0]['parts'][-1]['lessons'].append(
                {'id': soon, 'number': 99, 'title': '시험용 준비 중 강', 'subtitle': '', 'minutes': 5, 'surface': 'both', 'status': 'soon'})
        fixture = {'js': str(LEARN / 'learn.js'), 'soon_id': soon, 'file_text': FILE_TEXT, 'catalog': real_catalog, 'overview': overview, 'overview_placeholder': placeholder,
                   'evil': evil, 'real': real_lesson, 'p_catalog': p_catalog, 'p_overview': p_overview, 'p_lesson': poison(source),
                   'poison_shop': {k: v + POISON for k, v in real_catalog['example_shop'].items()}}
        vibe_catalog, vibe_lessons = vibe_fixture()
        fixture.update({'vibe_catalog': vibe_catalog, 'vibe_lessons': vibe_lessons, 'vibe_soon_catalog': vibe_fixture('soon')[0],
                        'p_vibe_catalog': poison(vibe_catalog), 'p_vibe_lessons': {k: poison(v) for k, v in vibe_lessons.items()}})
        import tempfile
        with tempfile.NamedTemporaryFile('w', suffix='.json', encoding='utf-8', delete=False) as handle:
            json.dump(fixture, handle, ensure_ascii=False)
        try:
            result = subprocess.run([NODE, '-', handle.name], input=HARNESS, text=True, capture_output=True, timeout=30)
        finally:
            os.unlink(handle.name)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_악성강의도_글자로만_보이고_복사는_원문이다(self):
        self.node_or_skip()
        out = self.run_harness()
        html = out['a_html']
        for bad in ('<img src=x', '<script', '<svg onload', '<b>t</b>', '<b>결과</b>', '<i>x</i>', '<i>m</i>', '<u>', '<x>',
                    'javascript:', '../', 'onerror="x', 'a"b', 'evil'):
            self.assertNotIn(bad, html, bad)
        self.assertIn('&lt;img src=x onerror=alert(1)&gt;', html)
        self.assertIn('<strong>&lt;script&gt;alert(1)&lt;/script&gt;</strong>', html)
        self.assertRegex(html, r'<code(?: class="lr-nw")?>&lt;svg onload=x&gt;</code>')
        self.assertIn('<strong>굵게</strong>', html)
        self.assertIn('<mark class="lr-fill">&lt;회사&gt;</mark>', html)
        self.assertIn('{{없는것}}', html)
        self.assertIn('메모장에 저장해 둘 틀', html)
        self.assertIn('lr-box-memo', html)
        self.assertIn('<mark class="lr-fill">꽃집</mark> &lt;i&gt;m&lt;/i&gt;', html)
        self.assertIn('href="https://example.com/x" target="_blank" rel="noopener noreferrer"', html)
        self.assertIn('&lt;L&gt;', html)
        self.assertIn('&lt;D&gt;', html)
        self.assertIn('learn/lessons/b01.json', out['a_fetched'])
        self.assertEqual(out['a_copied'], ['<회사> <i>x</i> {{없는것}}', '꽃집 <i>m</i>', FILE_TEXT, FILE_TEXT],
                         '파일은 받기 전이든 후든 자리표시도 바꾸지 않고 그대로 복사')
        self.assertTrue(out['a_large'], '저장소가 막혀도 글자 크게가 이 화면 동안 유지되어야 합니다')

    def test_자료파일상자는_늦게받고_글자로만_보인다(self):
        self.node_or_skip()
        out = self.run_harness()
        html = out['a_html']
        self.assertEqual(html.count('class="lr-box lr-box-file"'), 2, '경로가 틀린 파일 단계는 그리지 않는다')
        self.assertIn('<i data-lucide="file-code"></i>&lt;b&gt;파일&lt;/b&gt;', html)
        self.assertIn('<p class="lr-box-note">&lt;i&gt;n&lt;/i&gt;</p>', html)
        self.assertIn('펼치기', html)
        self.assertFalse(any(p.startswith('learn/files/') for p in out['a_fetched_first']), '펼치거나 복사하기 전에는 받지 않는다')
        self.assertFalse(any('..' in p for p in out['a_fetched']), out['a_fetched'])
        self.assertEqual(out['a_fetched'].count('learn/files/v01-sample.txt'), 1, '같은 파일은 한 번만 받는다')
        ready = out['a_file_ready']
        self.assertIn('12줄 · ', ready)
        self.assertIn('처음 8줄만 보여요', ready)
        self.assertIn('class="lr-file-text lr-file-cut"', ready)
        self.assertIn('data-file-open="false"', ready)
        self.assertIn('펼치기 (모두 12줄)', ready)
        opened = out['a_file_open']
        self.assertIn('data-file-open="true"', opened)
        self.assertIn('aria-expanded="true" aria-controls="lr-text-f0"', opened)
        self.assertIn('접기', opened)
        self.assertNotIn('lr-file-cut', opened)
        for name in ('a_html', 'a_file_ready', 'a_file_open', 'a_file_error'):
            self.assertNotIn('fileMarker', out[name], '파일 글자는 HTML에 넣지 않는다(textContent만)')
            self.assertNotIn('<script', out[name])
        self.assertIn('파일을 불러오지 못했어요', out['a_file_error'])
        self.assertIn('onclick="IlsonLearn.fileRetry(2)"', out['a_file_error'])

    def test_회사정보가_확인되기전에는_예시가게를_쓴다(self):
        self.node_or_skip()
        out = self.run_harness()
        self.assertIn('<b>햇살꽃집</b>', out['a2_html'])
        self.assertNotIn('<b>우리 회사</b>', out['a2_html'])
        self.assertIn('<mark class="lr-fill">&lt;i&gt;가게&lt;/i&gt;</mark>', out['b_html'])
        self.assertIn('<mark class="lr-fill">꽃집</mark>', out['b_html'])
        self.assertIs(out['b_progress']['b01']['done'], True)

    def test_잘못된강주소는_받지않고_목록으로(self):
        self.node_or_skip()
        out = self.run_harness()
        self.assertFalse(any('..' in p or 'lessons' in p for p in out['c1_fetched']), out['c1_fetched'])
        self.assertFalse(any(p.startswith('learn/lessons/') for p in out['c2_fetched']), out['c2_fetched'])
        self.assertIn('준비 중이거나', out['c2_html'])
        self.assertEqual(out['c2_query'], '')
        self.assertEqual(out['d_query'], '')
        self.assertIn('%d강 중 0강 마침' % len([1 for t, _, _ in published() if t['id'] == 'basic']), out['d_html'])
        self.assertIn('바이브 코딩 심화', out['d_html'])
        self.assertIn('준비 중', out['d_html'])

    def test_다른메뉴에_다녀오면_같은강_같은자리로(self):
        self.node_or_skip()
        out = self.run_harness()
        self.assertEqual(out['e_open_query'], '&lesson=b01')
        self.assertEqual(out['e_restored'], 480)
        self.assertEqual(out['e_menu_query'], '')
        self.assertEqual(out['e_catalog_top'], 300)

    @staticmethod
    def resume_id(html):
        found = re.search(r'class="lr-btn lr-btn-primary lr-btn-big" href="\?tab=learn&amp;lesson=([a-z][0-9]{2})"', html)
        return found.group(1) if found else None

    def test_심화과정이_열리면_목록에_과정별진도와_줄이_나온다(self):
        self.node_or_skip()
        out = self.run_harness()
        html = out['v_catalog']
        self.assertIn('<div class="lr-progress-track">기본 과정</div><strong class="lr-progress-num">2강 중 1강 마침</strong>', html)
        self.assertIn('다음 차례: 2강 기본 끝 강', html)
        self.assertEqual(self.resume_id(html), 'b02')
        vibe = html[html.index('<h2 class="lr-h2">바이브 코딩 심화</h2>'):]
        self.assertIn('<div class="lr-track-progress"><span>2강 중 0강 마침</span>', vibe)
        self.assertIn('1부 · 만들 것 정하기', vibe)
        self.assertIn('2부 · 저장하기', vibe)
        for label in ('심화 1강', '심화 2강', '심화 3강'):
            self.assertIn('<span class="lr-row-num">%s</span>' % label, vibe)
        self.assertIn('data-lr-row="v01"', vibe)
        self.assertNotIn('data-lr-row="v03"', vibe, '준비 중인 강은 열리지 않는다')
        self.assertIn('<span class="lr-row-num">1강</span>', html[:html.index('바이브 코딩 심화</h2>')])
        soon = out['v_soon_catalog']
        self.assertNotIn('심화 1강', soon)
        self.assertIn('<h2 class="lr-h2">바이브 코딩 심화</h2><span class="lr-badge">준비 중</span>', soon)

    def test_이어서배우기는_기본과정_먼저_다음은_심화(self):
        self.node_or_skip()
        out = self.run_harness()
        self.assertEqual(self.resume_id(out['v_resume_basic']), 'b01')
        self.assertEqual(self.resume_id(out['v_resume_basic2']), 'b02', '심화 강을 보다 왔어도 기본 과정에 남은 강이 먼저')
        self.assertIn('<div class="lr-progress-track">기본 과정</div>', out['v_resume_basic'])
        self.assertEqual(self.resume_id(out['v_resume_vibe']), 'v02')
        self.assertIn('<div class="lr-progress-track">바이브 코딩 심화</div><strong class="lr-progress-num">2강 중 0강 마침</strong>', out['v_resume_vibe'])
        self.assertIn('다음 차례: 심화 2강 첫 화면', out['v_resume_vibe'])
        done = out['v_all_done']
        self.assertIsNone(self.resume_id(done))
        self.assertIn('<div class="lr-progress-track">모든 과정</div><strong class="lr-progress-num">4강 중 4강 마침</strong>', done)
        self.assertIn('준비된 강을 모두 마쳤어요', done)

    def test_심화강의_머리말과_이동은_과정안에서만(self):
        self.node_or_skip()
        out = self.run_harness()
        first = out['v_lesson1']
        self.assertIn('<div class="lr-eyebrow">바이브 코딩 심화 · 1부 · 만들 것 정하기<span class="lr-dot" aria-hidden="true"></span>심화 1강</div>', first)
        self.assertIn('<span class="lr-pager-label">다음 강으로</span><span class="lr-pager-title">심화 2강 · 첫 화면</span>', first)
        self.assertNotIn('lr-prev', first, '심화 첫 강의 앞 강은 기본 과정으로 넘어가지 않는다')
        self.assertNotIn('lr-next-track', first)
        second = out['v_lesson2']
        self.assertIn('<span class="lr-pager-label">앞 강</span><span class="lr-pager-title">심화 1강 · 한 장으로 정하기</span>', second)
        self.assertIn('<span class="lr-pager-title">준비 중이에요</span>', second)
        self.assertNotIn('lr-next-track', second)
        end = out['v_basic_end']
        self.assertIn('<div class="lr-eyebrow">1부 · 시작<span class="lr-dot" aria-hidden="true"></span>2강</div>', end)
        self.assertNotIn('다음 강으로', end)
        self.assertIn('class="lr-next-track" href="?tab=learn&amp;lesson=v01"', end)
        self.assertIn('기본 과정의 마지막 강이에요', end)
        self.assertIn('심화 1강 · 한 장으로 정하기', end)
        self.assertNotIn('lr-next-track', out['v_soon_end'], '심화 과정이 준비 중이면 이어 주는 카드를 보이지 않는다')
        self.assertFalse(any('lessons/v01' in p for p in out['v_soon_fetched']), '준비 중인 과정의 강은 받지 않는다')
        self.assertIn('준비 중이거나', out['v_soon_lesson'])

    def test_심화과정_글자를_오염시켜도_새지않는다(self):
        self.node_or_skip()
        out = self.run_harness()
        for name in ('pv_catalog', 'pv_lesson', 'pv_end'):
            self.assertNotIn('<x-', out[name], name)
            self.assertGreater(out[name].count('&lt;x-p onclick=&quot;alert(1)&quot;&gt;'), 3, name)
        escaped = '&lt;x-p onclick=&quot;alert(1)&quot;&gt;&#39;&amp;amp;'
        self.assertIn('바이브 코딩 심화' + escaped, out['pv_lesson'])
        self.assertIn('class="lr-next-track"', out['pv_end'])
        self.assertIn('심화 1강', out['pv_catalog'])

    def test_실제목록과_강의의_모든글자를_오염시켜도_새지않는다(self):
        self.node_or_skip()
        out = self.run_harness()
        for name in ('p1_html', 'p1_catalog', 'p2_html'):
            self.assertNotIn('<x-', out[name], name)
        self.assertGreater(out['p1_html'].count('&lt;x-p onclick=&quot;alert(1)&quot;&gt;'), 30)
        self.assertGreater(out['p2_html'].count('&lt;x-p'), 30)
        self.assertIn('메모장에 저장해 둘 틀', out['p1_html'])


class 서빙시험(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.WorkspaceHTTPTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.server, self.cookie, self.home = fixture.server, fixture.cookie, fixture.home
        shutil.copytree(ROOT / 'template/web', fixture.home / 'web', dirs_exist_ok=True)

    def get(self, path, cookie=False):
        connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        connection.request('GET', path, headers={'Cookie': self.cookie} if cookie else {})
        response = connection.getresponse()
        result = (response.status, dict(response.getheaders()), response.read())
        connection.close()
        return result

    def test_배우기파일을_정확한형식으로_서빙한다(self):
        status, headers, body = self.get('/current/learn/catalog.json')
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'application/json; charset=utf-8')
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(json.loads(body), catalog())
        for key, (relative, kind) in STATIC.items():
            if key.startswith('/current/learn/'):
                status, headers, body = self.get(key)
                self.assertEqual(status, 200, key)
                self.assertEqual(headers['Content-Type'], kind, key)
                self.assertEqual(body, (ROOT / 'template' / relative).read_bytes(), key)

    def test_자료파일은_text_plain으로_그대로_서빙한다(self):
        name = 'v99-test-fixture.txt'
        target = self.home / 'web/current/learn/files' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(FILE_TEXT, encoding='utf-8')
        key = '/current/learn/files/' + name
        STATIC[key] = ('web/current/learn/files/' + name, 'text/plain; charset=utf-8')
        self.addCleanup(STATIC.pop, key, None)
        status, headers, body = self.get(key)
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'text/plain; charset=utf-8')
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(body.decode('utf-8'), FILE_TEXT)
        self.assertEqual(self.get('/current/learn/files/v99-other.txt', cookie=True)[0], 404)

    def test_SVG는_스크립트없는_전용CSP로_서빙한다(self):
        for path in [k for k, v in STATIC.items() if v[1] == 'image/svg+xml' and k.startswith('/current/')]:
            status, headers, _ = self.get(path)
            self.assertEqual(status, 200, path)
            self.assertEqual(headers['Content-Security-Policy'], SVG_POLICY, path)
        status, headers, _ = self.get('/current/index.html?tab=learn')
        self.assertIn("script-src 'self'", headers['Content-Security-Policy'])
        self.assertIn("img-src 'self' data: https:", headers['Content-Security-Policy'])

    def test_강의주소쿼리는_통과하고_등록하지않은경로는_막는다(self):
        for path in ('/current/index.html?tab=learn', '/current/index.html?tab=learn&lesson=b04', '/current/?tab=learn&lesson=b01'):
            status, headers, body = self.get(path)
            self.assertEqual(status, 200, path)
            self.assertIn(b'learn/learn.js', body)
        for path in ('/current/learn/lessons/b99.json', '/current/learn/lessons/../catalog.json', '/current/learn/',
                     '/current/learn/lessons/%2e%2e/catalog.json', '/current/learn/img/missing.svg'):
            self.assertIn(self.get(path)[0], (401, 404), path)
            self.assertEqual(self.get(path, cookie=True)[0], 404, path)


if __name__ == '__main__':
    unittest.main()
