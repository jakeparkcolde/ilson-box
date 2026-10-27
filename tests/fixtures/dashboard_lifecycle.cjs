// Small DOM/timer fixture for component ownership and shell transitions; no browser is started.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const web = path.resolve(__dirname, '../../template/web');
class Element {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase(); this.children = []; this.parentNode = null;
    this.attrs = {}; this.dataset = {}; this.events = new Map(); this.value = '';
    this.hidden = false; this.disabled = false; this._text = ''; this._html = '';
    this.classList = {
      contains: name => (this.className || '').split(/\s+/).includes(name),
      remove: name => { this.className = (this.className || '').split(/\s+/).filter(n => n !== name).join(' '); },
      toggle: name => { const has = this.classList.contains(name); this.classList.remove(name); if (!has) this.className = (this.className || '') + ' ' + name; }
    };
  }
  setAttribute(key, value) {
    this.attrs[key] = value;
    if (key === 'id') this.id = value;
    if (key === 'class') this.className = value;
    if (key === 'type') this.type = value;
    if (key === 'value') this.value = value;
    if (key.startsWith('data-')) this.dataset[key.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = value;
  }
  append(...children) {
    for (const child of children) {
      if (child.tagName === '#FRAGMENT') { this.append(...child.children.slice()); continue; }
      if (child.parentNode) child.parentNode.children = child.parentNode.children.filter(n => n !== child);
      child.parentNode = this; this.children.push(child);
    }
  }
  replaceChildren(...children) { for (const child of this.children) child.parentNode = null; this.children = []; this._text = ''; this.append(...children); }
  set textContent(value) { this.replaceChildren(); this._text = String(value); }
  get textContent() { return this._text + this.children.map(n => n.textContent).join(''); }
  set innerHTML(html) {
    this.replaceChildren(); this._html = html;
    const stack = [this];
    for (const token of html.match(/<[^>]*>|[^<]+/g) || []) {
      if (token.startsWith('</')) { if (stack.length > 1) stack.pop(); continue; }
      if (!token.startsWith('<')) { const n = new Element('#text'); n.textContent = token; stack.at(-1).append(n); continue; }
      if (token.startsWith('<!')) continue;
      const tag = token.match(/^<([\w-]+)/)?.[1]; if (!tag) continue;
      const n = new Element(tag);
      for (const attr of token.matchAll(/([\w-]+)="([^"]*)"/g)) n.setAttribute(attr[1], attr[2]);
      stack.at(-1).append(n);
      if (!['input', 'br', 'img', 'link', 'meta', 'hr'].includes(tag)) stack.push(n);
    }
    for (const n of this.querySelectorAll('select')) n.value = n.querySelector('option')?.value || '';
  }
  get innerHTML() { return this._html; }
  querySelectorAll(selector) {
    const matches = n => selector.split(',').some(part => {
      if (part.startsWith('#')) return n.id === part.slice(1);
      if (part.startsWith('.')) return (n.className || '').split(/\s+/).includes(part.slice(1));
      return n.tagName.toLowerCase() === part.replace('[id]', '') && (!part.includes('[id]') || n.id);
    });
    const result = [];
    const visit = n => { for (const child of n.children) { if (matches(child)) result.push(child); visit(child); } };
    visit(this); return result;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  addEventListener(type, fn) { if (!this.events.has(type)) this.events.set(type, new Set()); this.events.get(type).add(fn); }
  removeEventListener(type, fn) { this.events.get(type)?.delete(fn); }
  dispatch(type) { for (const fn of this.events.get(type) || []) fn({target: this}); }
  focus() {}
}
function setup(search = '?tab=dashboard') {
  const body = new Element('body');
  body.innerHTML = '<nav id="sidebar"></nav><main id="main"></main><button id="mNavBtn"></button><div id="mNavBackdrop"></div>';
  const document = new Element('document'); document.append(body); document.body = body; document.hidden = false;
  document.getElementById = id => document.querySelector('#' + id);
  document.createElement = tag => new Element(tag);
  document.createDocumentFragment = () => new Element('#fragment');
  const timers = new Map(), requests = [], events = new Element(), storage = new Map(); let serial = 0;
  const location = {search, origin: 'http://local.test', assign: () => assert.fail('unexpected navigation')};
  const ctx = {
    document, location, URLSearchParams, AbortController, console,
    setTimeout: (fn, ms) => { timers.set(++serial, {fn, ms}); return serial; },
    clearTimeout: id => timers.delete(id),
    localStorage: {getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value)},
    history: {replaceState: (_, __, url) => { location.search = url; }},
    fetch: (url, options) => {
      if (url === '/api/session') return Promise.resolve({ok: true, json: async () => ({authenticated: true})});
      assert.equal(url, '/api/dashboard');
      return new Promise((resolve, reject) => requests.push({resolve, reject, options}));
    },
    addEventListener: (...args) => events.addEventListener(...args), scrollTo: () => {},
    snsCaptureView: () => null, snsRestoreView: () => {}, SNS_OPS: {},
    screenSnsOperations: () => '<div id="sns-view">SNS</div>',
    screenSnsAccounts: () => '<div id="accounts-view">accounts</div>',
    screenVaultAllLive: () => '<div>vault</div>'
  };
  ctx.window = ctx; vm.createContext(ctx);
  const run = src => vm.runInContext(src, ctx);
  const load = file => run(fs.readFileSync(path.join(web, file), 'utf8'));
  const host = document.getElementById('main');
  const dashboard = () => document.querySelector('.ilson-dashboard');
  const get = id => document.getElementById('db-' + id);
  const polls = () => [...timers.values()].filter(t => t.ms === 30000).length;
  const fire = ms => { for (const [id, timer] of [...timers]) if (timer.ms === ms) { timers.delete(id); timer.fn(); } };
  load('dashboard.js');
  return {ctx, run, load, document, host, dashboard, get, requests, timers, polls, fire};
}
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
function sample(percent = 12) {
  const metric = {state: 'ok', observed_at: '2026-01-01T00:00:00Z', value: {percent, used_bytes: 100, total_bytes: 200, free_bytes: 100}};
  return {observed_at: '2026-01-01T00:00:00Z', platform: 'fixture', sandbox: false,
    cpu: metric, memory: metric, disk: metric,
    automations: {state: 'ok', notices: [], observed_at: metric.observed_at, items: [
      {id: 'example.one', name: '<img src=x onerror=alert(1)>', state: 'running', source: 'box'},
      {id: 'example.two', name: 'second', state: 'unavailable', source: 'launchd'}
    ]}};
}
async function respond(request, data = sample(), status = 200) {
  request.resolve({ok: status === 200, status, json: async () => data}); await flush();
}
async function component() {
  const h = setup(), {ctx, requests, get} = h;
  assert.equal(requests.length, 0, 'loading the asset alone does not poll');
  ctx.IlsonDashboard.mount(h.host); const root = h.dashboard();
  ctx.IlsonDashboard.mount(h.host);
  assert.equal(requests.length, 1); assert.equal(h.polls(), 0);
  assert.equal(h.document.events.get('visibilitychange').size, 1);
  await respond(requests[0]);
  assert.equal(h.polls(), 1); assert.equal(get('refresh').disabled, false);
  assert.match(get('resources').textContent, /12%/);
  assert.match(get('jobs').textContent, /<img src=x onerror=alert\(1\)>/);
  assert.equal(get('jobs').querySelectorAll('img').length, 0, 'API text never becomes markup');
  const detail = get('jobs').querySelector('details'); detail.open = true; detail.dispatch('toggle');
  get('search').value = 'example.one'; get('search').dispatch('input');
  assert.equal(get('count').textContent, '1 / 2개');
  get('refresh').dispatch('click'); get('refresh').dispatch('click');
  assert.equal(requests.length, 2); assert.equal(h.polls(), 0);
  const before = get('status').textContent;
  await respond(requests[1]); // Cached response keeps exactly the same sample timestamp.
  assert.equal(get('status').textContent, before); assert.equal(h.polls(), 1);
  assert.equal(requests[1].options.cache, 'no-store');
  ctx.IlsonDashboard.mount(h.host);
  assert.equal(requests.length, 2); assert.equal(h.dashboard(), root);
  ctx.IlsonDashboard.leave(); h.host.innerHTML = '<div>SNS</div>';
  assert.equal(h.timers.size, 0); assert.equal(h.document.events.get('visibilitychange').size, 0);
  h.document.dispatch('visibilitychange'); assert.equal(requests.length, 2);
  ctx.IlsonDashboard.mount(h.host);
  assert.equal(h.dashboard(), root); assert.equal(get('search').value, 'example.one');
  assert.equal(get('jobs').querySelector('details').open, true);
  assert.equal(get('refresh').events.get('click').size, 1);
  assert.equal(get('search').events.get('input').size, 1);
  assert.equal(requests.length, 3);
  ctx.IlsonDashboard.leave(); assert.equal(requests[2].options.signal.aborted, true);
  ctx.IlsonDashboard.mount(h.host); assert.equal(requests.length, 4);
  await respond(requests[2], sample(99)); // Old request deliberately ignores its aborted signal.
  assert.doesNotMatch(get('resources').textContent, /99%/);
  assert.equal(get('refresh').disabled, true); assert.equal(h.polls(), 0);
  await respond(requests[3], sample(18)); assert.match(get('resources').textContent, /18%/);
  assert.equal(h.polls(), 1);
  h.fire(30000); assert.equal(requests.length, 5);
  await respond(requests[4], null, 401);
  assert.match(get('error').textContent, /인증이 필요/); assert.equal(get('error').hidden, false);
  assert.match(get('resources').textContent, /지난 관측/);
  get('refresh').dispatch('click'); requests[5].reject(Error('offline')); await flush();
  assert.match(get('error').textContent, /지난 관측/);
  get('refresh').dispatch('click'); await respond(requests[6]); assert.equal(get('error').hidden, true);
  get('search').value = ''; get('source').value = 'launchd'; get('state').value = 'unknown';
  get('state').dispatch('change'); assert.equal(get('count').textContent, '1 / 2개');
  h.document.hidden = true; h.document.dispatch('visibilitychange'); assert.equal(h.polls(), 0);
  get('refresh').dispatch('click'); assert.equal(requests.length, 7);
  h.document.hidden = false; h.document.dispatch('visibilitychange'); assert.equal(requests.length, 8);
  let jsonResolve;
  requests[7].resolve({ok: true, status: 200, json: () => new Promise(resolve => {jsonResolve = resolve;})});
  await flush(); ctx.IlsonDashboard.leave();
  jsonResolve(sample(88)); await flush();
  assert.doesNotMatch(get('resources').textContent, /88%/); assert.equal(h.timers.size, 0);
  ctx.IlsonDashboard.leave(); // Idempotent cleanup.
  const hidden = setup(); hidden.document.hidden = true; hidden.ctx.IlsonDashboard.mount(hidden.host);
  assert.equal(hidden.requests.length, 0); assert.equal(hidden.timers.size, 0);
  hidden.document.hidden = false; hidden.document.dispatch('visibilitychange');
  hidden.requests[0].reject(Error('initial offline')); await flush();
  assert.doesNotMatch(hidden.get('error').textContent, /지난 관측/);
  hidden.get('refresh').dispatch('click'); const empty = sample(); empty.automations = {...empty.automations, state: 'empty', items: []};
  await respond(hidden.requests[1], empty); assert.match(hidden.get('jobs').textContent, /등록된 업무가 없습니다/);
  hidden.ctx.IlsonDashboard.leave();
}
async function shell() {
  const h = setup(); let leaves = 0, restores = 0, menus = 0;
  h.ctx.IlsonLearn = {render: () => '<div id="learn-view">learn</div>', query: () => '&lesson=c01', leave: () => leaves++, restore: () => restores++, menu: () => menus++};
  h.load('current/pack-library/pack-navigation.js'); h.load('current/shell.js'); await flush();
  assert.equal(h.requests.length, 1, 'direct dashboard link mounts after session check');
  const root = h.dashboard(); assert.ok(root); assert.equal(h.ctx.location.search, '?tab=dashboard');
  assert.match(h.document.getElementById('sidebar').innerHTML, /nav-item on[^>]*aria-current="page"[^>]*A.go\('dashboard'\)/);
  assert.equal(h.document.querySelectorAll('#themeToggle').length, 1);
  assert.equal(root.querySelector('header'), null); assert.equal(root.querySelector('iframe'), null);
  h.run("A.go('dashboard');render();render();"); assert.equal(h.requests.length, 1); assert.equal(h.dashboard(), root);
  h.document.getElementById('themeToggle').onclick(); assert.equal(h.document.body.dataset.theme, 'light');
  h.document.getElementById('mNavBtn').onclick(); assert.equal(h.document.body.classList.contains('m-nav-open'), true);
  h.run("A.go('packs')"); assert.equal(h.requests[0].options.signal.aborted, true);
  assert.equal(h.document.body.classList.contains('m-nav-open'), false); assert.equal(h.timers.size, 0);
  const frame = h.document.getElementById('ilsonPackFrame'); assert.ok(frame);
  h.run('render()'); assert.equal(h.document.getElementById('ilsonPackFrame'), frame, 'pack frame is retained');
  h.run("A.go('learn')"); assert.ok(h.document.getElementById('learn-view')); assert.equal(restores, 1);
  h.run("A.go('learn')"); assert.equal(menus, 1);
  h.run("A.go('sns')"); assert.ok(h.document.getElementById('sns-view')); assert.equal(leaves, 1);
  h.run("A.go('sns-accounts')"); assert.ok(h.document.getElementById('accounts-view'));
  h.run("A.go('dashboard')"); assert.equal(h.dashboard(), root); assert.equal(h.requests.length, 2);
  await respond(h.requests[0], sample(99)); assert.doesNotMatch(h.get('resources').textContent, /99%/);
  await respond(h.requests[1]); assert.equal(h.polls(), 1);
  h.run("A.go('research')"); assert.equal(h.document.getElementById('ilsonPackFrame').dataset.packView, 'research');
  h.run("A.go('knowledge')"); assert.equal(h.document.getElementById('ilsonPackFrame').dataset.packView, 'knowledge');
  assert.equal(h.timers.size, 0);
}
(async () => {await component(); await shell(); console.log('dashboard component + shell lifecycle PASS');})().catch(error => {console.error(error); process.exitCode = 1;});
