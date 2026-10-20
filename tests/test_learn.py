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
         '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml'}
ID_RE = re.compile(r'^[a-z][0-9]{2}$')
FIG_RE = re.compile(r'^img/[a-z][0-9]{2}-[a-z0-9]+(?:-[a-z0-9]+)*\.svg$')
DATE_RE = re.compile(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$')
PLACEHOLDERS = {'가게이름', '업종', '지역', '대표상품'}
CHECK_IDS = {'claude', 'company', 'trust', 'telegram', 'search'}
SURFACES = {'web', 'ilson', 'both'}
LESSON_KEYS = {'id', 'track', 'part', 'number', 'title', 'subtitle', 'minutes', 'surface', 'checked', 'cover', 'outcome',
               'prepare', 'steps', 'explain', 'trouble', 'checklist', 'keep', 'links', 'sources', 'history'}
STEP_KEYS = {'title', 'why', 'body', 'prompt', 'command', 'memo', 'self', 'success', 'status', 'figure', 'tip', 'caution'}
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
        self.assertEqual(tracks[1]['status'], 'soon')
        ids = [l['id'] for _, _, l in catalog_rows()]
        self.assertEqual(len(ids), len(set(ids)), '강 id 중복')
        self.assertEqual(ids, ['b%02d' % n for n in range(1, 23)])
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
        self.assertEqual([l['number'] for _, _, l in catalog_rows()], list(range(1, 23)))

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
        self.assertEqual(lesson['track'], 'basic' if lesson['id'].startswith('b') else 'vibe')
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
    fetch: async path => { fetched.push(path); return path in files ? { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(files[path])) } : { ok: false, status: 404, json: async () => ({}) }; },
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
  const a = make('?tab=learn&lesson=b01', null, { ...base, 'learn/lessons/b01.json': P.evil });
  out.a_html = await settle(a);
  a.L.copy('p0'); a.L.copy('m0'); await tick();
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
                       'memo': {'text': '{{업종}} <i>m</i>', 'note': '<u>n</u>'}, 'status': ['claude', 'evil']}],
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
        soon = next(l['id'] for _, _, l in catalog_rows() if l['status'] == 'soon')
        fixture = {'js': str(LEARN / 'learn.js'), 'soon_id': soon, 'catalog': real_catalog, 'overview': overview, 'overview_placeholder': placeholder,
                   'evil': evil, 'real': real_lesson, 'p_catalog': p_catalog, 'p_overview': p_overview, 'p_lesson': poison(source),
                   'poison_shop': {k: v + POISON for k, v in real_catalog['example_shop'].items()}}
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
        self.assertIn('<code>&lt;svg onload=x&gt;</code>', html)
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
        self.assertEqual(out['a_copied'], ['<회사> <i>x</i> {{없는것}}', '꽃집 <i>m</i>'])
        self.assertTrue(out['a_large'], '저장소가 막혀도 글자 크게가 이 화면 동안 유지되어야 합니다')

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
        self.assertIn('%d강 중 0강 마침' % len(published()), out['d_html'])
        self.assertIn('바이브 코딩 심화', out['d_html'])
        self.assertIn('준비 중', out['d_html'])

    def test_다른메뉴에_다녀오면_같은강_같은자리로(self):
        self.node_or_skip()
        out = self.run_harness()
        self.assertEqual(out['e_open_query'], '&lesson=b01')
        self.assertEqual(out['e_restored'], 480)
        self.assertEqual(out['e_menu_query'], '')
        self.assertEqual(out['e_catalog_top'], 300)

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
        self.server, self.cookie = fixture.server, fixture.cookie
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
