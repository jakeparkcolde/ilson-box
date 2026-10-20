"use strict";
/* Claude 배우기 — 강의 목록·본문 렌더러.
   강의 글은 전부 이스케이프한 뒤 **굵게**·`코드`만 살린다. 링크는 links/sources의 https 주소만 연다.
   데이터는 한 번만 받아 두고, 화면은 캐시로 바로 그린 뒤 도착하면 다시 그린다. */
(function () {
  const ID_RE = /^[a-z][0-9]{2}$/;
  const FIG_RE = /^img\/[a-z][0-9]{2}-[a-z0-9]+(?:-[a-z0-9]+)*\.svg$/;
  const COPY_RE = /^[pctm][0-9]{1,3}$/;
  const PH = /\{\{(가게이름|업종|지역|대표상품)\}\}/g;
  const PH_ONE = /\{\{(가게이름|업종|지역|대표상품)\}\}/;
  const PH_KEY = { 가게이름: "name", 업종: "kind", 지역: "area", 대표상품: "product" };
  const FIELDS = [["name", "가게 이름"], ["kind", "업종"], ["area", "지역"], ["product", "대표 상품"]];
  const KEYS = { shop: "ilson-learn-shop", progress: "ilson-learn-progress", last: "ilson-learn-last", large: "ilson-learn-large" };
  const SURFACE = { web: "브라우저·앱", ilson: "일손박스 터미널", both: "둘 다" };
  const CHECKS = { claude: "Claude 로그인", company: "회사 정보", trust: "회사 폴더 신뢰", telegram: "텔레그램 알림", search: "웹 검색 준비" };
  const STATE = { ok: "됐어요", attention: "확인 필요", unknown: "알 수 없음" };
  const STATE_ICON = { ok: "circle-check", attention: "circle-alert", unknown: "circle-help" };
  const MEM = {}; // 저장소가 막힌 브라우저에서도 이 화면을 연 동안은 기억한다.
  const L = {
    catalog: null, catalogState: "idle", lessons: {}, lessonState: {}, overview: null, overviewState: "idle",
    lesson: null, notice: "", shopOpen: false, shopMsg: "", copied: "", copyTimer: 0, view: "", catalogTop: 0,
    sh: null, zoomFrom: null, zoomN: "", figN: 0, leftLesson: null, leftTop: 0, focusTitle: false
  };

  try {
    const q = new URLSearchParams(location.search);
    if (q.get("tab") === "learn" && ID_RE.test(q.get("lesson") || "")) L.lesson = q.get("lesson");
  } catch { /* 주소를 못 읽으면 목록부터 보여 준다. */ }

  /* ── 기본 도구 ── */
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const arr = value => Array.isArray(value) ? value : [];
  const txt = value => typeof value === "string" ? value : typeof value === "number" ? String(value) : "";
  const obj = value => value && typeof value === "object" && !Array.isArray(value) ? value : null;
  const clean = value => typeof value === "string" ? value.replace(/[\u0000-\u001f\u007f]/g, " ").trim().slice(0, 30) : "";

  function load(key, fallback) {
    let raw = null;
    try { raw = localStorage.getItem(key); } catch { raw = null; }
    if (raw == null && Object.prototype.hasOwnProperty.call(MEM, key)) raw = MEM[key];
    if (raw == null) return fallback;
    try { return JSON.parse(raw); } catch { return fallback; }
  }
  function save(key, value) {
    const raw = JSON.stringify(value);
    MEM[key] = raw;
    try { localStorage.setItem(key, raw); } catch { /* 이 화면 동안만 기억 */ }
  }
  function drop(key) {
    delete MEM[key];
    try { localStorage.removeItem(key); } catch { /* 무시 */ }
  }
  const large = () => load(KEYS.large, false) === true;
  const progress = () => obj(load(KEYS.progress, {})) || {};
  const lessonProgress = id => obj(progress()[id]) || {};
  function mark(id, patch) {
    const all = progress();
    all[id] = Object.assign({}, obj(all[id]) || {}, patch, { at: new Date().toISOString() });
    save(KEYS.progress, all);
  }

  /* ── 내 가게 정보: 직접 적은 값 → 회사 이름(가게 이름만, 회사 정보가 확인된 경우) → 예시 ── */
  function shop() {
    const example = obj(L.catalog && L.catalog.example_shop) || {};
    const mine = obj(load(KEYS.shop, {})) || {};
    const box = obj(L.overview && L.overview.box);
    const companyOk = arr(L.overview && L.overview.checks).some(c => obj(c) && c.id === "company" && c.state === "ok");
    const company = companyOk && box ? clean(box.company_name) : "";
    const v = {}, from = {}, fallback = {};
    for (const [k] of FIELDS) {
      fallback[k] = k === "name" && company ? company : clean(example[k]);
      if (clean(mine[k])) { v[k] = clean(mine[k]); from[k] = "mine"; }
      else { v[k] = fallback[k]; from[k] = k === "name" && company ? "box" : "example"; }
    }
    return { v, from, fallback, mine };
  }
  const value = name => (L.sh ? L.sh.v[PH_KEY[name]] : "") || "";
  const fillPlain = text => txt(text).replace(PH, (_, name) => value(name));
  function fillMark(text) {
    const t = txt(text);
    let out = "", last = 0;
    for (const m of t.matchAll(PH)) {
      out += esc(t.slice(last, m.index)) + '<mark class="lr-fill">' + esc(value(m[1])) + "</mark>";
      last = m.index + m[0].length;
    }
    return out + esc(t.slice(last));
  }
  /* 이스케이프 다음에만 **굵게**·`코드`·자리표시를 바꾼다. 원문 HTML은 글자로 보인다. */
  function inl(text) {
    return esc(txt(text)).split(/(`[^`\n]+`)/).map((part, i) => i % 2
      ? (part.length <= 20 ? '<code class="lr-nw">' : "<code>") + part.slice(1, -1).replace(PH, (_, name) => esc(value(name))) + "</code>"
      : part.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>").replace(PH, (_, name) => '<span class="lr-fillin">' + esc(value(name)) + "</span>")
    ).join("");
  }
  function safeUrl(url) {
    if (typeof url !== "string" || !/^https:\/\/[^\s<>"'`]+$/.test(url)) return "";
    try { return new URL(url).protocol === "https:" ? url : ""; } catch { return ""; }
  }
  function host(url) {
    try { return new URL(url).host; } catch { return ""; }
  }

  /* ── 데이터 받기 (한 번만) ── */
  async function getJSON(path) {
    const response = await fetch(path, { cache: "no-store", credentials: "same-origin" });
    if (response.status === 401) { location.assign("/"); throw new Error("login"); }
    if (!response.ok) throw new Error(String(response.status));
    return response.json();
  }
  function refresh() {
    if (typeof S !== "undefined" && S.tab === "learn" && typeof renderIdle === "function") renderIdle();
    focusTitle();
  }
  /* 강을 연 뒤 제목에 초점을 둔다. 강 파일이 아직 오는 중이면 도착해 다시 그린 뒤에. */
  function focusTitle() {
    if (!L.focusTitle) return;
    const title = document.getElementById("lrTitle");
    if (title) { L.focusTitle = false; title.focus({ preventScroll: true }); }
  }
  function ensureCatalog() {
    if (L.catalogState !== "idle") return;
    L.catalogState = "loading";
    getJSON("learn/catalog.json").then(data => {
      if (!obj(data) || !Array.isArray(data.tracks)) throw new Error("shape");
      L.catalog = data; L.catalogState = "ready";
    }).catch(() => { L.catalogState = "error"; }).then(refresh);
  }
  function ensureLesson(id) {
    if (L.lessonState[id]) return;
    L.lessonState[id] = "loading";
    getJSON("learn/lessons/" + id + ".json").then(data => {
      if (!obj(data) || data.id !== id || !Array.isArray(data.steps)) throw new Error("shape");
      L.lessons[id] = data; L.lessonState[id] = "ready";
    }).catch(() => { L.lessonState[id] = "error"; }).then(refresh);
  }
  function ensureOverview() {
    if (L.overviewState !== "idle") return;
    L.overviewState = "loading";
    getJSON("/api/overview").then(data => {
      L.overview = obj(data); L.overviewState = "ready";
    }).catch(() => { L.overviewState = "error"; }).then(refresh);
  }

  /* ── 목록 색인 ── */
  function index() {
    const rows = [];
    for (const t of arr(L.catalog && L.catalog.tracks)) {
      if (!obj(t)) continue;
      for (const p of arr(t.parts)) {
        if (!obj(p)) continue;
        for (const l of arr(p.lessons)) if (obj(l) && ID_RE.test(txt(l.id))) rows.push({ l, p, t });
      }
    }
    return rows;
  }
  const isOpen = r => r.l.status === "published" && r.t.status !== "soon";
  const published = () => index().filter(isOpen);
  const find = id => index().find(r => r.l.id === id);
  function resolve() {
    if (!L.lesson || !L.catalog) return;
    const r = find(L.lesson);
    if (!r || !isOpen(r)) {
      L.notice = "찾는 강은 아직 준비 중이거나 주소가 바뀌었어요. 아래 목록에서 골라 주세요.";
      L.lesson = null;
    }
  }
  function resumeTarget(pub, prog) {
    const done = r => obj(prog[r.l.id]) && prog[r.l.id].done === true;
    const last = load(KEYS.last, "");
    const at = pub.findIndex(r => r.l.id === last);
    if (at >= 0 && !done(pub[at])) return pub[at];
    return pub.slice(at + 1).find(r => !done(r)) || pub.find(r => !done(r)) || null;
  }
  function neighbours(id) {
    const here = find(id);
    const all = here ? index().filter(r => r.t === here.t) : [];
    const i = all.findIndex(r => r.l.id === id);
    const next = all.slice(i + 1).find(isOpen);
    return { prev: all.slice(0, i).reverse().find(isOpen), next, soon: !next && all.slice(i + 1).length > 0 };
  }

  /* ── 공통 조각 ── */
  const sec = (title, body, cls) => body ? `<section class="lr-sec ${esc(cls)}"><h2 class="lr-h2">${esc(title)}</h2>${body}</section>` : "";
  const paras = list => (typeof list === "string" ? [list] : arr(list)).map(p => `<p>${inl(p)}</p>`).join("");
  const list = (items, cls) => {
    const rows = arr(items).filter(x => txt(x)).map(x => `<li>${inl(x)}</li>`).join("");
    return rows ? `<ul class="${esc(cls)}">${rows}</ul>` : "";
  };
  const loadingBox = message => `<div class="lr-wait" role="status"><span class="lr-spin" aria-hidden="true"></span>${esc(message)}</div>`;
  const errorBox = message => `<div class="lr-wait lr-error" role="alert"><p>${inl(message)}</p><button type="button" class="lr-btn lr-btn-primary" onclick="IlsonLearn.retry()">다시 시도</button></div>`;
  const lessonLink = (id, inner, cls, row) => `<a class="${esc(cls)}" href="?tab=learn&amp;lesson=${esc(id)}"${row ? ` data-lr-row="${esc(id)}"` : ""} onclick="return IlsonLearn.open('${esc(id)}',event)">${inner}</a>`;
  function largeButton() {
    const on = large();
    return `<button type="button" class="lr-btn lr-btn-ghost${on ? " on" : ""}" aria-pressed="${on}" data-lr-focus="large" onclick="IlsonLearn.toggleLarge()"><i data-lucide="a-large-small"></i>글자 크게</button>`;
  }
  function callout(kind, label, icon, text) {
    return text ? `<div class="lr-callout lr-${esc(kind)}"><div class="lr-callout-label"><i data-lucide="${esc(icon)}"></i>${esc(label)}</div><div>${inl(text)}</div></div>` : "";
  }
  function fig(f, cls) {
    const item = obj(f);
    const src = item ? txt(item.src) : "";
    if (!FIG_RE.test(src)) return "";
    const alt = txt(item.alt), cap = txt(item.caption), n = ++L.figN;
    return `<figure class="lr-fig${cls ? " " + esc(cls) : ""}">
      <button type="button" class="lr-fig-btn" data-fig-n="${esc(n)}" onclick="IlsonLearn.zoom('${esc(src)}',this)" aria-label="${esc("크게 보기: " + (alt || cap || "그림"))}">
        <img src="learn/${esc(src)}" alt="${esc(alt)}" decoding="async"><span class="lr-fig-zoom" aria-hidden="true"><i data-lucide="maximize-2"></i></span>
      </button>${cap ? `<figcaption>${inl(cap)}</figcaption>` : ""}
    </figure>`;
  }
  function box(kind, i, item) {
    const text = obj(item) ? txt(item.text) : txt(item);
    if (!text) return "";
    const key = kind + i, cmd = kind === "c", memo = kind === "m";
    const label = cmd ? "터미널에 붙여 넣기" : memo ? "메모장에 저장해 둘 틀" : "Claude에게 보낼 말";
    const note = obj(item) ? txt(item.note) : "";
    return `<div class="lr-box${cmd ? " lr-box-cmd" : ""}${memo ? " lr-box-memo" : ""}">
      <div class="lr-box-head"><span>${memo ? '<i data-lucide="notebook-pen"></i>' : ""}${esc(label)}</span><button type="button" class="lr-copy" data-copy="${esc(key)}" onclick="IlsonLearn.copy('${esc(key)}')" aria-label="${esc(label + " 복사")}"><i data-lucide="copy"></i><span class="lr-copy-label" aria-live="polite">${L.copied === key ? "복사했어요" : "복사"}</span></button></div>
      <pre class="lr-box-text" id="lr-text-${esc(key)}">${cmd ? esc(text) : fillMark(text)}</pre>${note ? `<p class="lr-box-note">${inl(note)}</p>` : ""}
    </div>`;
  }
  function statusCard(ids, i) {
    const wanted = arr(ids).filter(id => Object.prototype.hasOwnProperty.call(CHECKS, id));
    if (!wanted.length) return "";
    let body;
    if (L.overviewState === "ready" && L.overview) {
      const checks = arr(L.overview.checks);
      body = `<ul class="lr-stats">${wanted.map(id => {
        const c = checks.find(x => obj(x) && x.id === id) || {};
        const st = Object.prototype.hasOwnProperty.call(STATE, c.state) ? c.state : "unknown";
        return `<li><span class="lr-state lr-state-${esc(st)}"><i data-lucide="${esc(STATE_ICON[st])}"></i>${esc(STATE[st])}</span><span class="lr-stat-text"><strong>${esc(txt(c.label) || CHECKS[id])}</strong>${txt(c.detail) ? `<span>${esc(c.detail)}</span>` : ""}</span></li>`;
      }).join("")}</ul>${obj(L.overview.box) && L.overview.box.sandbox === true ? '<p class="lr-muted">체험용(샌드박스) 설치라서 일부 상태는 「알 수 없음」으로 보여요.</p>' : ""}`;
    } else if (L.overviewState === "error") {
      body = '<p class="lr-muted">지금 상태를 불러오지 못했어요. 잠시 뒤 「다시 확인」을 눌러 주세요.</p>';
    } else {
      body = loadingBox("상태를 확인하는 중이에요…");
    }
    return `<div class="lr-status"><div class="lr-status-head"><span><i data-lucide="activity"></i>내 일손박스 지금 상태</span><button type="button" class="lr-btn lr-btn-small" data-lr-focus="recheck-${esc(i)}" onclick="IlsonLearn.recheck('${esc(i)}')">다시 확인</button></div>${body}</div>`;
  }

  /* ── 내 가게 정보 패널 ── */
  function shopPanel(compact) {
    const sh = L.sh, open = L.shopOpen;
    const own = FIELDS.some(([k]) => sh.from[k] === "mine");
    const where = own ? "" : sh.from.name === "box" ? "가게 이름은 회사 정보에서 가져왔어요. 업종·지역·대표 상품은 아직 예시라서 바꿔 주세요" : "지금은 예시예요";
    const form = `<form class="lr-shop-form" id="lrShopForm" onsubmit="return IlsonLearn.saveShop(event)">
        ${FIELDS.map(([k, label]) => `<label class="lr-field"><span>${esc(label)}</span><input id="lrShop-${esc(k)}" type="text" maxlength="30" autocomplete="off" value="${esc(clean(sh.mine[k]))}" placeholder="${esc(sh.fallback[k])}"></label>`).join("")}
        <p class="lr-muted">이 Mac의 브라우저에만 저장돼요. 비워 둔 칸에는 예시가 들어가요.</p>
        <div class="lr-actions"><button type="submit" class="lr-btn lr-btn-primary">저장</button><button type="button" class="lr-btn lr-btn-ghost" onclick="IlsonLearn.resetShop()">예시로 되돌리기</button></div>
      </form>`;
    return `<section class="lr-shop${compact ? " lr-shop-compact" : ""}" aria-label="내 가게 정보">
      <div class="lr-shop-row">
        <div class="lr-shop-now"><span class="lr-shop-label">부탁 문장에 들어가는 가게</span>
          <span class="lr-shop-value">${FIELDS.map(([k]) => `<b>${esc(sh.v[k])}</b>`).join('<span aria-hidden="true"> · </span>')}</span>
          ${where ? `<span class="lr-muted">${esc(where)}</span>` : ""}</div>
        <button type="button" class="lr-btn lr-btn-ghost" aria-expanded="${open}" aria-controls="lrShopForm" data-lr-focus="shop" onclick="IlsonLearn.toggleShop()"><i data-lucide="store"></i>내 가게 정보로 바꾸기</button>
      </div>${open ? form : ""}${L.shopMsg ? `<p class="lr-ok" role="status">${esc(L.shopMsg)}</p>` : ""}
    </section>`;
  }

  /* ── 목록 화면 ── */
  function catalogView() {
    const C = L.catalog, pub = published(), prog = progress();
    const doneCount = pub.filter(r => obj(prog[r.l.id]) && prog[r.l.id].done === true).length;
    const next = resumeTarget(pub, prog);
    const started = doneCount > 0 || Object.keys(prog).length > 0 || !!load(KEYS.last, "");
    const pct = pub.length ? Math.round(doneCount / pub.length * 100) : 0;
    const go = next ? lessonLink(next.l.id, `${started ? "이어서 배우기" : "첫 강 시작하기"}<i data-lucide="arrow-right"></i>`, "lr-btn lr-btn-primary lr-btn-big") : "";
    return `<header class="lr-head">
        <div class="lr-eyebrow">배우기</div>
        <div class="lr-titlebar"><h1 class="lr-h1">Claude 배우기</h1>${largeButton()}</div>
        ${txt(C.intro) ? `<p class="lr-lead">${inl(C.intro)}</p>` : ""}
      </header>
      ${L.notice ? `<div class="lr-notice" role="status"><span>${esc(L.notice)}</span><button type="button" class="lr-btn lr-btn-small" onclick="IlsonLearn.dismiss()">닫기</button></div>` : ""}
      <section class="lr-progress" aria-label="진도">
        <div class="lr-progress-row"><div><strong class="lr-progress-num">${esc(pub.length)}강 중 ${esc(doneCount)}강 마침</strong>
          ${next ? `<div class="lr-muted">다음 차례: ${esc(next.l.number)}강 ${esc(next.l.title)}</div>` : pub.length ? '<div class="lr-muted">준비된 강을 모두 마쳤어요. 새 강이 열리면 여기에 보여요.</div>' : ""}</div>${go}</div>
        <div class="lr-bar" role="progressbar" aria-label="마친 강" aria-valuemin="0" aria-valuemax="${esc(pub.length)}" aria-valuenow="${esc(doneCount)}"><span style="width:${esc(pct)}%"></span></div>
      </section>
      ${shopPanel(false)}
      ${arr(C.tracks).filter(obj).map(t => trackView(t, prog)).join("")}`;
  }
  function trackView(t, prog) {
    const soon = t.status === "soon";
    return `<section class="lr-track${soon ? " lr-track-soon" : ""}">
      <div class="lr-track-head"><h2 class="lr-h2">${esc(t.title)}</h2>${soon ? '<span class="lr-badge">준비 중</span>' : ""}</div>
      ${txt(t.summary) ? `<p class="lr-track-sum">${inl(t.summary)}</p>` : ""}
      ${soon ? "" : arr(t.parts).filter(obj).map(p => `<div class="lr-part"><h3 class="lr-part-title">${esc(p.number)}부 · ${esc(p.title)}</h3>
        <ol class="lr-rows">${arr(p.lessons).filter(l => obj(l) && ID_RE.test(txt(l.id))).map(l => lessonRow(l, prog)).join("")}</ol></div>`).join("")}
    </section>`;
  }
  function lessonRow(l, prog) {
    const open = l.status === "published", done = open && obj(prog[l.id]) && prog[l.id].done === true;
    const meta = [l.minutes ? "약 " + txt(l.minutes) + "분" : "", SURFACE[l.surface] ? "어디서: " + SURFACE[l.surface] : ""].filter(Boolean).join(" · ");
    const tail = !open ? '<span class="lr-badge">준비 중</span>' : done ? '<span class="lr-row-done"><i data-lucide="circle-check"></i>마침</span>' : '<i data-lucide="chevron-right" class="lr-row-go"></i>';
    const inner = `<span class="lr-row-num">${esc(l.number)}강</span><span class="lr-row-text"><span class="lr-row-title">${esc(l.title)}</span>${txt(l.subtitle) ? `<span class="lr-row-sub">${esc(l.subtitle)}</span>` : ""}${meta ? `<span class="lr-row-meta">${esc(meta)}</span>` : ""}</span>${tail}`;
    return `<li>${open ? lessonLink(l.id, inner, "lr-row" + (done ? " lr-row-finished" : ""), true) : `<div class="lr-row lr-row-soon">${inner}</div>`}</li>`;
  }

  /* ── 강의 화면 ── */
  function toolbar() {
    return `<div class="lr-toolbar"><button type="button" class="lr-btn lr-btn-ghost" data-lr-focus="toc" onclick="IlsonLearn.home()"><i data-lucide="list"></i>목차</button>${largeButton()}</div>`;
  }
  function usesShop(D) {
    return arr(D.steps).some(s => obj(s) && (PH_ONE.test(obj(s.prompt) ? txt(s.prompt.text) : "") || PH_ONE.test(obj(s.memo) ? txt(s.memo.text) : "")))
      || arr(D.trouble).some(t => obj(t) && PH_ONE.test(txt(t.prompt)));
  }
  function stepView(s, i) {
    if (!obj(s)) return "";
    return `<li class="lr-step" id="lr-step-${esc(i + 1)}">
      <div class="lr-step-head"><span class="lr-step-num" aria-hidden="true">${esc(i + 1)}</span><h3 class="lr-h3"><span class="lr-sr">${esc(i + 1)}단계: </span>${esc(s.title)}</h3></div>
      ${txt(s.why) ? `<p class="lr-why">${inl(s.why)}</p>` : ""}
      ${paras(s.body)}${fig(s.figure)}
      ${callout("self", "이건 직접 해 주세요", "hand", s.self)}
      ${box("c", i, s.command)}${box("p", i, s.prompt)}${box("m", i, s.memo)}${statusCard(s.status, i)}
      ${callout("success", "이렇게 보이면 성공", "circle-check", s.success)}
      ${callout("tip", "알아두면 좋아요", "lightbulb", s.tip)}
      ${callout("caution", "조심하세요", "triangle-alert", s.caution)}
    </li>`;
  }
  function explainView(x) {
    if (!obj(x)) return "";
    const t = obj(x.table), head = t ? arr(t.head) : [], rows = t ? arr(t.rows).filter(Array.isArray) : [];
    const table = head.length || rows.length ? `<div class="lr-table-wrap"><table class="lr-table">${head.length ? `<thead><tr>${head.map(h => `<th scope="col">${inl(h)}</th>`).join("")}</tr></thead>` : ""}<tbody>${rows.map(r => `<tr>${r.map(c => `<td>${inl(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>` : "";
    return `<div class="lr-explain">${txt(x.heading) ? `<h3 class="lr-h3">${esc(x.heading)}</h3>` : ""}${paras(x.body)}${table}${fig(x.figure)}</div>`;
  }
  function troubleView(t, i) {
    if (!obj(t)) return "";
    return `<li class="lr-trouble"><p class="lr-trouble-sym"><i data-lucide="circle-alert"></i><strong>${inl(t.symptom)}</strong></p>${txt(t.fix) ? `<p>${inl(t.fix)}</p>` : ""}${box("t", i, t.prompt)}</li>`;
  }
  function linkList(items) {
    const rows = arr(items).map(x => {
      const url = safeUrl(obj(x) ? x.url : "");
      return url ? `<li><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(txt(x.label) || url)}<i data-lucide="external-link"></i></a><span class="lr-host">${esc(host(url))}</span></li>` : "";
    }).join("");
    return rows ? `<ul class="lr-links">${rows}</ul>` : "";
  }
  function lessonView(D) {
    const here = find(D.id), id = D.id, prog = lessonProgress(id), done = prog.done === true;
    const part = here ? here.p : null, nb = neighbours(id), checks = arr(prog.checks);
    if (load(KEYS.last, "") !== id) save(KEYS.last, id);
    const chips = [txt(D.minutes) ? "약 " + txt(D.minutes) + "분" : "", SURFACE[D.surface] ? "어디서: " + SURFACE[D.surface] : "", txt(D.checked) ? "내용 확인일 " + txt(D.checked) : ""].filter(Boolean);
    const checklist = arr(D.checklist).filter(x => txt(x)).map((c, i) => `<li><label class="lr-check"><input type="checkbox" id="lr-check-${esc(i)}"${checks[i] === true ? " checked" : ""} onchange="IlsonLearn.check(${esc(i)},this.checked)"><span>${inl(c)}</span></label></li>`).join("");
    const history = arr(D.history).filter(obj).map(h => `<li><span class="lr-mono">${esc(h.date)}</span> ${inl(h.note)}</li>`).join("");
    const pagerItem = (r, label, cls) => r ? lessonLink(r.l.id, `<span class="lr-pager-label">${esc(label)}</span><span class="lr-pager-title">${esc(r.l.number)}강 · ${esc(r.l.title)}</span>`, "lr-pager-item " + cls) : "";
    return `${toolbar()}
      <header class="lr-head">
        <div class="lr-eyebrow">${esc(D.part)}부 · ${esc(part ? part.title : "")}<span class="lr-dot" aria-hidden="true"></span>${esc(D.number)}강</div>
        <h1 class="lr-h1" id="lrTitle" tabindex="-1">${esc(D.title)}</h1>
        ${txt(D.subtitle) ? `<p class="lr-sub">${inl(D.subtitle)}</p>` : ""}
        <div class="lr-chips">${chips.map(c => `<span class="lr-chip">${esc(c)}</span>`).join("")}</div>
      </header>
      ${fig(D.cover, "lr-cover")}
      ${sec("이번 시간에 만들 것", list(D.outcome, "lr-outcome"), "lr-sec-outcome")}
      ${sec("준비할 것", list(D.prepare, "lr-plain"), "")}
      ${usesShop(D) ? shopPanel(true) : ""}
      ${sec("따라 하기", arr(D.steps).length ? `<ol class="lr-steps">${arr(D.steps).map(stepView).join("")}</ol>` : "", "")}
      ${sec("왜 그런가요?", arr(D.explain).map(explainView).join(""), "")}
      ${sec("잘 안 될 때", arr(D.trouble).length ? `<ul class="lr-troubles">${arr(D.trouble).map(troubleView).join("")}</ul>` : "", "")}
      ${sec("스스로 확인", checklist ? `<ul class="lr-checks">${checklist}</ul>` : "", "")}
      ${sec("한 줄 정리", list(D.keep, "lr-keep"), "")}
      ${sec("더 알아보기", linkList(D.links), "")}
      ${sec("근거", linkList(D.sources), "lr-sec-small")}
      ${history ? `<details class="lr-history"><summary>고친 기록</summary><ul>${history}</ul></details>` : ""}
      <footer class="lr-foot">
        <button type="button" class="lr-done${done ? " on" : ""}" aria-pressed="${done}" data-lr-focus="done" onclick="IlsonLearn.toggleDone()"><i data-lucide="${done ? "circle-check" : "circle"}"></i>이 강 마쳤어요</button>
        ${done ? '<p class="lr-muted">잘하셨어요. 기록해 두었어요.</p>' : ""}
        <nav class="lr-pager" aria-label="강 이동">${pagerItem(nb.prev, "앞 강", "lr-prev") || "<span></span>"}${pagerItem(nb.next, "다음 강으로", "lr-next") || (nb.soon ? '<span class="lr-pager-item lr-pager-off"><span class="lr-pager-label">다음 강</span><span class="lr-pager-title">준비 중이에요</span></span>' : "")}</nav>
      </footer>`;
  }

  /* ── 그림 크게 보기: #modals 안에 그려서 화면을 다시 그려도 남는다 ── */
  function figures(D) {
    const out = [];
    if (!obj(D)) return out;
    if (obj(D.cover)) out.push(D.cover);
    for (const s of arr(D.steps)) if (obj(s) && obj(s.figure)) out.push(s.figure);
    for (const x of arr(D.explain)) if (obj(x) && obj(x.figure)) out.push(x.figure);
    return out;
  }
  function zoomKeys(event) {
    if (event.key === "Escape") { event.preventDefault(); closeZoom(); }
    else if (event.key === "Tab") { event.preventDefault(); const close = document.querySelector(".lr-zoom-close"); if (close) close.focus(); }
  }
  function setInert(on) {
    for (const n of [document.querySelector(".app"), document.getElementById("mNavBtn")]) if (n) n.inert = on;
  }
  function closeZoom() {
    document.removeEventListener("keydown", zoomKeys, true);
    const shades = document.querySelectorAll(".lr-zoom");
    if (!shades.length) return;
    shades.forEach(n => n.remove());
    setInert(false);
    const n = /^[0-9]{1,3}$/.test(L.zoomN) ? L.zoomN : "";
    const back = L.zoomFrom && L.zoomFrom.isConnected ? L.zoomFrom : n ? document.querySelector('.lr-fig-btn[data-fig-n="' + n + '"]') : null;
    L.zoomFrom = null; L.zoomN = "";
    if (back) back.focus({ preventScroll: true });
  }
  const el = (tag, cls) => { const n = document.createElement(tag); if (cls) n.className = cls; return n; };

  /* ── 화면 갱신 ── */
  function shellRender(focus) {
    if (typeof S !== "undefined" && S.tab === "learn" && typeof window.render === "function") window.render();
    if (focus) {
      const n = document.querySelector('[data-lr-focus="' + focus + '"]');
      if (n) n.focus({ preventScroll: true });
    }
  }
  function toTop() {
    const main = document.getElementById("main");
    if (main) main.scrollTop = 0;
    window.scrollTo(0, 0);
  }
  function wrap(view, body) {
    const enter = view !== L.view;
    L.view = view;
    return `<div class="lr${large() ? " lr-large" : ""}${enter ? " lr-enter" : ""}" id="lrRoot">${body}</div>`;
  }
  function copyText(key) {
    const D = L.lessons[L.lesson];
    if (!D || !COPY_RE.test(key)) return "";
    const i = Number(key.slice(1));
    L.sh = shop();
    if (key[0] === "t") { const t = obj(arr(D.trouble)[i]); return t ? fillPlain(t.prompt) : ""; }
    const s = obj(arr(D.steps)[i]), item = s ? obj({ p: s.prompt, m: s.memo, c: s.command }[key[0]]) : null;
    if (!item) return "";
    return key[0] === "c" ? txt(item.text) : fillPlain(item.text);
  }
  function copyLabel(key, label) {
    document.querySelectorAll('[data-copy="' + key + '"] .lr-copy-label').forEach(n => { n.textContent = label; });
  }
  function legacyCopy(text) {
    const area = document.createElement("textarea");
    area.value = text; area.setAttribute("readonly", "");
    area.style.position = "fixed"; area.style.top = "-1000px"; area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch { ok = false; }
    area.remove();
    return ok;
  }

  window.IlsonLearn = {
    render() {
      L.figN = 0;
      ensureCatalog();
      ensureOverview();
      L.sh = shop();
      if (!L.catalog) {
        return wrap("wait", `<header class="lr-head"><div class="lr-eyebrow">배우기</div><h1 class="lr-h1">Claude 배우기</h1></header>${L.catalogState === "error"
          ? errorBox("배우기 자료를 불러오지 못했어요. 잠시 뒤 다시 시도해 주세요. 계속 안 되면 터미널에서 `ilson update`를 실행해 보세요.")
          : loadingBox("배우기 자료를 불러오는 중이에요…")}`);
      }
      resolve();
      if (!L.lesson) return wrap("catalog", catalogView());
      const id = L.lesson;
      ensureLesson(id);
      if (L.lessons[id]) return wrap("lesson:" + id, lessonView(L.lessons[id]));
      return wrap("wait:" + id, toolbar() + (L.lessonState[id] === "error"
        ? errorBox("이 강을 불러오지 못했어요. 잠시 뒤 다시 시도하거나 목차에서 다른 강을 골라 주세요.")
        : loadingBox("강의를 불러오는 중이에요…")));
    },
    /* shell.js가 주소를 고칠 때 붙인다: 열린 강이 있으면 &lesson=b04 */
    query() {
      resolve();
      return L.lesson ? "&lesson=" + encodeURIComponent(L.lesson) : "";
    },
    /* 다른 메뉴로 나갈 때 읽던 자리를 기억한다. */
    leave() {
      closeZoom();
      const main = document.getElementById("main"), top = main ? main.scrollTop : 0;
      if (L.lesson) { L.leftLesson = L.lesson; L.leftTop = top; } else L.catalogTop = top;
    },
    /* 메뉴로 돌아오면 같은 강, 같은 자리로 (shell.js가 화면을 그린 뒤 부른다) */
    restore() {
      const main = document.getElementById("main");
      if (main) main.scrollTop = L.lesson ? (L.lesson === L.leftLesson ? L.leftTop : 0) : L.catalogTop;
    },
    /* 이미 배우기 화면에서 메뉴를 다시 누르면: 강 안이면 목차로, 목차면 맨 위로 */
    menu() {
      if (L.lesson) return this.home();
      L.notice = "";
      shellRender();
      toTop();
    },
    open(id, event) {
      if (event && (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button === 1)) return true;
      if (!ID_RE.test(txt(id))) return false;
      const r = find(id);
      if (!r || !isOpen(r)) return false;
      const main = document.getElementById("main");
      if (!L.lesson && main) L.catalogTop = main.scrollTop;
      closeZoom();
      L.lesson = id; L.notice = ""; L.shopMsg = "";
      try { history.pushState(null, "", "?tab=learn&lesson=" + id); } catch { /* 주소 기록이 막혀도 화면은 연다 */ }
      shellRender();
      toTop();
      L.focusTitle = true;
      focusTitle();
      return false;
    },
    home() {
      closeZoom();
      const from = L.lesson;
      L.focusTitle = false;
      L.lesson = null; L.shopMsg = "";
      try { history.pushState(null, "", "?tab=learn"); } catch { /* 무시 */ }
      shellRender();
      const main = document.getElementById("main");
      if (main) main.scrollTop = L.catalogTop;
      const row = from && ID_RE.test(from) ? document.querySelector('[data-lr-row="' + from + '"]') : null;
      if (row) row.focus({ preventScroll: true });
    },
    popstate() {
      if (typeof S === "undefined" || typeof A === "undefined") return;
      let q;
      try { q = new URLSearchParams(location.search); } catch { return; }
      const tab = q.get("tab") || "sns";
      closeZoom();
      if (tab === "learn") {
        const id = q.get("lesson") || "";
        L.lesson = ID_RE.test(id) ? id : null;
        if (S.tab !== "learn") return A.go("learn");
        shellRender();
        const main = document.getElementById("main");
        if (main) main.scrollTop = L.lesson ? 0 : L.catalogTop;
      } else if (S.tab === "learn") {
        A.go(tab);
      }
    },
    retry() {
      if (L.catalogState === "error") L.catalogState = "idle";
      if (L.overviewState === "error") L.overviewState = "idle";
      if (L.lesson && L.lessonState[L.lesson] === "error") delete L.lessonState[L.lesson];
      shellRender();
    },
    recheck(i) {
      if (L.overviewState === "loading") return;
      L.overviewState = "idle";
      shellRender(/^[0-9]{1,3}$/.test(txt(i)) ? "recheck-" + i : "");
    },
    dismiss() { L.notice = ""; shellRender(); },
    toggleLarge() { save(KEYS.large, !large()); shellRender("large"); },
    toggleShop() { L.shopOpen = !L.shopOpen; L.shopMsg = ""; shellRender("shop"); if (L.shopOpen) { const n = document.getElementById("lrShop-name"); if (n) n.focus(); } },
    saveShop(event) {
      if (event) event.preventDefault();
      const next = {};
      for (const [k] of FIELDS) {
        const input = document.getElementById("lrShop-" + k);
        next[k] = clean(input ? input.value : "");
      }
      save(KEYS.shop, next);
      L.shopOpen = false;
      L.shopMsg = "저장했어요. 이제 부탁 문장에 이 정보가 들어가요.";
      shellRender("shop");
      return false;
    },
    resetShop() {
      drop(KEYS.shop);
      L.shopOpen = false;
      L.shopMsg = "예시 정보로 되돌렸어요.";
      shellRender("shop");
    },
    toggleDone() {
      const id = L.lesson;
      if (!id || !L.lessons[id]) return;
      mark(id, { done: lessonProgress(id).done !== true });
      shellRender("done");
    },
    check(i, on) {
      const id = L.lesson, D = L.lessons[id];
      if (!D || !Number.isInteger(i) || i < 0 || i >= arr(D.checklist).length) return;
      const checks = arr(D.checklist).map((_, n) => arr(lessonProgress(id).checks)[n] === true);
      checks[i] = on === true;
      mark(id, { checks });
    },
    copy(key) {
      const text = copyText(txt(key));
      if (!text) return;
      const ok = () => {
        L.copied = key;
        copyLabel(key, "복사했어요");
        clearTimeout(L.copyTimer);
        L.copyTimer = setTimeout(() => { if (L.copied === key) L.copied = ""; copyLabel(key, "복사"); }, 2000);
      };
      const fail = () => {
        const n = document.getElementById("lr-text-" + key);
        if (n && window.getSelection) { const r = document.createRange(); r.selectNodeContents(n); const s = window.getSelection(); s.removeAllRanges(); s.addRange(r); }
        copyLabel(key, "글자를 골라 두었어요. ⌘+C로 복사하세요");
      };
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(ok, () => (legacyCopy(text) ? ok() : fail()));
      else if (legacyCopy(text)) ok(); else fail();
    },
    zoom(src, button) {
      if (!FIG_RE.test(txt(src))) return;
      const f = figures(L.lessons[L.lesson]).find(x => x.src === src) || {};
      closeZoom();
      L.zoomFrom = button || null;
      L.zoomN = button && button.dataset ? txt(button.dataset.figN) : "";
      const shade = el("div", "lr-zoom"), panel = el("div", "lr-zoom-panel"), close = el("button", "lr-zoom-close"), plate = el("div", "lr-zoom-plate"), img = el("img");
      shade.setAttribute("role", "dialog"); shade.setAttribute("aria-modal", "true"); shade.setAttribute("aria-label", txt(f.alt) || "그림 크게 보기");
      close.type = "button"; close.setAttribute("aria-label", "닫기"); close.textContent = "×";
      img.src = "learn/" + src; img.alt = txt(f.alt);
      plate.appendChild(img);
      panel.append(close, plate);
      if (txt(f.caption)) {
        const cap = el("p", "lr-zoom-cap");
        cap.id = "lrZoomCap"; cap.textContent = txt(f.caption).replace(/\*\*|`/g, "");
        shade.setAttribute("aria-describedby", "lrZoomCap");
        panel.appendChild(cap);
      }
      shade.appendChild(panel);
      shade.addEventListener("click", event => {
        // 휴대폰처럼 그림을 옆으로 끌어 보는 중에는 그림을 눌러도 닫지 않는다.
        if (plate.contains(event.target) && plate.scrollWidth > plate.clientWidth + 1) return;
        closeZoom();
      });
      (document.getElementById("modals") || document.body).appendChild(shade);
      setInert(true);
      document.addEventListener("keydown", zoomKeys, true);
      close.focus();
    }
  };
  window.addEventListener("popstate", () => window.IlsonLearn.popstate());
})();
