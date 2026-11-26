"""로컬 콘솔(ilson open) 사이드바의 ilson.work 역할 안내 및 핸드오프 링크 검증."""

from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHELL_JS = ROOT / "template/web/current/shell.js"
SHELL_CSS = ROOT / "template/web/current/shell.css"


class LocalCloudRoleTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "node is required for shell.js syntax and runtime checks")
    def test_shell_js_syntax_valid(self):
        res = subprocess.run(
            ["node", "--check", str(SHELL_JS)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(res.returncode, 0, res.stderr)

    @unittest.skipUnless(shutil.which("node"), "node is required for shell.js runtime checks")
    def test_sidebar_renders_cloud_handoff_link_and_local_role_copy(self):
        harness = r"""
const fs = require('fs');
const vm = require('vm');
const shellPath = process.argv[1];
const source = fs.readFileSync(shellPath, 'utf8');

function mkEl(id) {
  return {
    id,
    innerHTML: '',
    textContent: '',
    hidden: false,
    value: '',
    dataset: {},
    style: {},
    classList: { toggle() {}, add() {}, remove() {}, contains: () => false },
    setAttribute() {},
    removeAttribute() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
  };
}

const byId = {
  sidebar: mkEl('sidebar'),
  main: mkEl('main'),
  mNavBtn: mkEl('mNavBtn'),
  mNavBackdrop: mkEl('mNavBackdrop'),
  railCollapseBtn: mkEl('railCollapseBtn'),
  folioRail: mkEl('folioRail'),
  sideSearch: mkEl('sideSearch'),
  logout: mkEl('logout'),
  themeToggle: mkEl('themeToggle'),
};

const context = {
  console,
  URLSearchParams,
  encodeURIComponent,
  decodeURIComponent,
  location: { pathname: '/current/', search: '?tab=home', hash: '', origin: 'http://127.0.0.1:18794', assign() {} },
  history: { replaceState() {} },
  localStorage: { getItem: () => 'dark', setItem() {} },
  document: {
    body: { dataset: {}, classList: { toggle() {}, add() {}, remove() {}, contains: () => false } },
    activeElement: null,
    getElementById: (id) => byId[id] || null,
  },
  scrollTo() {},
  addEventListener() {},
  setInterval() {},
  snsCaptureView: () => null,
  snsRestoreView() {},
  screenSnsOperations: () => '<div>sns</div>',
  IlsonPacks: { current: () => false, render: () => '' },
  fetch: async (path) => ({
    ok: true,
    status: 200,
    json: async () => (path === '/api/session'
      ? { ok: true, peers: { current: { name: '맥 스튜디오', subtitle: '주력 머신' }, peers: [] } }
      : { box: { setup_state: 'ready' } }),
  }),
};
context.window = context;
vm.createContext(context);
vm.runInContext(source, context, { filename: 'shell.js' });

setImmediate(() => {
  setImmediate(() => {
    const html = byId.sidebar.innerHTML;
    if (!html.includes('href="https://ilson.work/"')) {
      console.error('missing ilson.work href:', html);
      process.exit(1);
    }
    if (!html.includes('target="_blank"') || !html.includes('rel="noopener noreferrer"')) {
      console.error('missing target/rel security attrs:', html);
      process.exit(1);
    }
    if (!html.includes('ilson.work 열기 ↗')) {
      console.error('missing CTA label:', html);
      process.exit(1);
    }
    if (!html.includes('일상 결재·보고서·협업은 ilson.work · 이 화면은 로컬 설정·진단 콘솔')) {
      console.error('missing local console role copy:', html);
      process.exit(1);
    }
    if (!html.includes('로컬 연결됨') || !html.includes('side-user')) {
      console.error('existing side-user footer missing:', html);
      process.exit(1);
    }
    console.log('LOCAL_CLOUD_ROLE_OK');
  });
});
"""
        res = subprocess.run(
            ["node", "-e", harness, str(SHELL_JS)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(res.returncode, 0, res.stderr + res.stdout)
        self.assertIn("LOCAL_CLOUD_ROLE_OK", res.stdout)

    def test_shell_css_includes_dark_and_light_cloud_card_styles(self):
        css = SHELL_CSS.read_text(encoding="utf-8")
        for token in (
            ".folio-shell .side-cloud-card{",
            ".side-cloud-note{",
            ".side-cloud-link{",
            'body[data-theme="light"].folio-shell .side-cloud-link{',
        ):
            self.assertIn(token, css)


if __name__ == "__main__":
    unittest.main()
