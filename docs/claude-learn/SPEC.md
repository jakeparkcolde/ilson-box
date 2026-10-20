# Claude 배우기 — in-product manual spec (2026-10-20)

A beginner manual inside the ilson-box web UI that teaches Claude from zero, then how to use it inside 일손 Box, then (later) vibe coding.
This file is the single source of truth for implementers, writers and reviewers.

## 1. Audience and promise

- Primary reader: a small-business owner in their 50s–60s who has never used an AI tool or a terminal. Mac user (Mac mini or MacBook), Korean only.
- Second reader: a student in a classroom install on a laptop (educator-led session).
- Promise: every lesson ends with one concrete thing the reader made, in about 5 minutes of reading plus hands-on time, without needing anyone's help.

## 2. Originality rule (from Jake, 2026-10-20) — HARD

We studied an existing Korean vibe-coding course as a benchmark. **Do not copy it.** No sentences, headings, section labels, analogies, example prompts, example projects or illustrations taken from it, even reworded closely.
Writers do not open the benchmark. The benchmark name and the detailed do-not-reuse list are kept outside this public repo; independent reviewers get them from the maintainer and check every lesson against them.

Generic facts (what a token is, that Git saves versions) are fine. Our own framing, examples and wording must be new.

## 3. How we are better (the "일손 스타일" upgrade)

1. **The manual knows your box.** Lessons can show live checks from `/api/overview` (Claude 로그인, 회사 폴더 신뢰, 회사 정보, 텔레그램) right inside the step that needs them.
2. **Your shop, not a sample.** A "내 가게 정보" panel (가게 이름, 업종, 지역, 대표 상품) fills placeholders in every prompt. 가게 이름 is prefilled from the box company name when present. Defaults are a clearly fictional example.
3. **One running story.** Examples follow one fictional business through the course (default: 햇살꽃집, a neighbourhood flower shop) so each lesson builds on the last: shop intro → price list → supplier quote → customer reply → weekly report.
4. **Business work first.** Writing, documents, research, customer replies, reports. Coding comes last, as an optional advanced track.
5. **No install cliff.** 일손 Box already installed Claude Code. The terminal part starts from one copy button (`ilson chat`).
6. **Easy to read for older eyes.** 16px+ body text, a "글자 크게" toggle, one idea per paragraph, Korean everywhere, English UI words shown with their Korean meaning.
7. **Copy buttons and progress.** Every prompt and command has a copy button. Checklists and "마쳤어요" are saved on this Mac.
8. **Safety built in.** Every lesson that touches data says what not to share. Every terminal lesson says how to undo.
9. **Facts dated and sourced.** Each lesson shows "내용 확인일" and links official Anthropic pages used.

## 4. Curriculum

### Track A: 기본 과정 (22 lessons). ★ = first release (11 lessons)

| id | 부 | 강 | title (working) | surface |
|---|---|---|---|---|
| b01 ★ | 1 시작하기 | 1 | Claude는 어떤 일을 도와주나요 | both |
| b02 ★ | 1 | 2 | 계정 만들기와 요금제 고르기 | web |
| b03 ★ | 1 | 3 | 안심하고 쓰기 위한 약속 (개인정보·학습 설정·넣으면 안 되는 정보) | web |
| b04 ★ | 2 대화하기 | 4 | 첫 부탁: 한 줄과 자세한 부탁의 차이 | web |
| b05 ★ | 2 | 5 | 잘 통하는 부탁 만들기 | web |
| b06 ★ | 2 | 6 | 파일과 사진 맡기기 | web |
| b07 ★ | 2 | 7 | 믿기 전에 확인하기 | web |
| b08 | 2 | 8 | 프로젝트와 메모리로 우리 가게 기억시키기 | web |
| b09 | 2 | 9 | 아티팩트로 문서·표 만들기 | web |
| b10 | 2 | 10 | 웹 검색·리서치와 앱 연결 | web |
| b11 ★ | 3 일손박스에서 쓰기 | 11 | 터미널, 버튼 하나로 시작하기 | ilson |
| b12 ★ | 3 | 12 | 로그인과 "이 폴더를 믿을까요?" | ilson |
| b13 ★ | 3 | 13 | 첫 작업: 만들고, 고치고, 다시 열기 | ilson |
| b14 ★ | 3 | 14 | 허락하기와 되돌리기 | ilson |
| b15 | 3 | 15 | 회사 설명서 만들기 (/onboard) | ilson |
| b16 | 3 | 16 | 일손박스 메뉴와 같이 쓰기 | ilson |
| b17 | 4 맡기기 | 17 | 정해진 시간에 알아서 (ilson start, 텔레그램) | ilson |
| b18 | 4 | 18 | 팩·스킬로 능력 더하기 | ilson |
| b19 | 4 | 19 | 더 해보기: 우리 가게 소개 페이지 | ilson |
| b20 | 5 막혔을 때 | 20 | 사용량 한도에 걸렸을 때 | both |
| b21 | 5 | 21 | 오류가 났을 때 | both |
| b22 | 5 | 22 | 용어 사전·자주 묻는 질문 | both |

Surfaces: `web` = claude.ai in a browser or the Claude desktop/mobile app; `ilson` = Claude Code through 일손 Box (`ilson chat`); `both`.

### Track B: 바이브 코딩 심화 (planned, not in first release)

A business-tool project instead of a toy: build a 예약·문의 접수 page for the running shop, step by step, ending with a public link.
Working outline (to be refined later): v01 만들 것 한 장으로 정하기 · v02 첫 화면 · v03 저장점과 되돌리기 · v04 문의 내용 저장 · v05 외부 서비스와 비밀 열쇠 · v06 관리자 로그인 · v07 인터넷에 공개 (상업적 사용 조건 확인) · v08 손님 의견으로 고치기 · v09 디자인 다듬기 · v10 휴대폰 홈 화면에 올리기.
The catalog shows this track as "준비 중" with a one-paragraph description only.

## 5. Architecture

- Native screen inside the `/current/` SPA (not an iframe), so it inherits the Linear skin tokens in `template/web/current/base.css` and the dark/light theme.
- Files (new):
  - `template/web/current/learn/learn.js` — renderer, exposes `window.IlsonLearn` with `render()` used by `shell.js`.
  - `template/web/current/learn/learn.css`
  - `template/web/current/learn/catalog.json` — tracks, parts, lesson order and status.
  - `template/web/current/learn/lessons/<id>.json` — one file per published lesson.
  - `template/web/current/learn/img/*.svg` — optional illustrations (self-made, no external assets).
- Do not put files under `template/web/current/pack-library/` (overwritten by the research pack build).
- Registration:
  - `shell.js`: nav group `배우기` with item `{id:'learn', icon:<a bundled Lucide icon such as graduation-cap>, label:'Claude 배우기'}`; add `learn` to the `A.go` whitelist and the `render()` map.
  - `index.html`: add the CSS and script (script before `shell.js`).
  - `template/lib/web-admin-server.py`: add every new file explicitly to `STATIC` with the right content type. Query strings only on whitelisted `/current/` paths are already supported.
- Updates: `ilson update` ships `web/` files with `.html .css .js .svg .json` only. No other formats.
- CSP is `default-src 'self'`; images allow `'self' data:` (and `https:` under `/current/`). External iframes (YouTube) are blocked, so videos are links that open a new tab.
- Content rendering: never inject raw lesson text as HTML. Escape everything, then apply a tiny safe inline markup: `**bold**` and `` `code` ``. Links only from structured `links`/`sources` arrays, `https:` only, `target="_blank" rel="noopener noreferrer"`.
- Live status: fetch `/api/overview` (session required; 401 → shell already redirects). Map check ids `claude`, `company`, `trust`, `telegram`, `search` to state `ok | attention | unknown` and show `label` + `detail`. In sandbox mode the server returns `unknown`; show that honestly.
- Personal info: localStorage key `ilson-learn-shop` `{name, kind, area, product}`. Progress: `ilson-learn-progress` `{<lessonId>: {done: bool, checks: [bool...], at: ISO}}`. Last lesson: `ilson-learn-last`. Large text: `ilson-learn-large`. Wrap every storage access in try/catch; the page must work without storage.
- URL: `/current/index.html?tab=learn` (catalog) and `?tab=learn&lesson=b04`. Keep `render()`'s `history.replaceState` behaviour working for other tabs.
- Copy: `navigator.clipboard.writeText` (127.0.0.1 is a secure context) with a select-text fallback; show "복사했어요" for 2 s.

## 6. Lesson JSON schema

```json
{
  "id": "b04",
  "track": "basic",
  "part": 2,
  "number": 4,
  "title": "첫 부탁: 한 줄과 자세한 부탁의 차이",
  "subtitle": "one playful line",
  "minutes": 6,
  "surface": "web",
  "checked": "2026-10-20",
  "outcome": ["what the reader will have at the end (1-3 items)"],
  "prepare": ["what to have ready (optional)"],
  "steps": [
    {
      "title": "step title",
      "why": "one line: why this step matters",
      "body": ["paragraph", "paragraph"],
      "prompt": {"text": "text to send to Claude; may use {{가게이름}} {{업종}} {{지역}} {{대표상품}}", "note": "optional hint under the box"},
      "command": {"text": "ilson chat", "note": "optional"},
      "self": "something only the reader can do (login, payment, verification code)",
      "success": "what the screen shows when it worked",
      "status": ["claude", "trust"],
      "figure": {"src": "img/b04-compare.svg", "alt": "...", "caption": "..."},
      "tip": "optional",
      "caution": "optional"
    }
  ],
  "explain": [
    {"heading": "concept heading", "body": ["paragraph"], "table": {"head": ["", ""], "rows": [["", ""]]}}
  ],
  "trouble": [{"symptom": "what went wrong", "fix": "what to do", "prompt": "optional text to paste to Claude"}],
  "checklist": ["self-check items (2-4)"],
  "keep": ["up to 3 takeaways"],
  "links": [{"label": "official page", "url": "https://..."}],
  "sources": [{"label": "fact source", "url": "https://..."}],
  "history": [{"date": "2026-10-20", "note": "처음 작성"}]
}
```

All step fields except `title` are optional. Keep `body` paragraphs to 1-2 sentences.

`catalog.json`:

```json
{
  "version": "2026-10-20",
  "intro": "one-paragraph intro",
  "example_shop": {"name": "햇살꽃집", "kind": "꽃집", "area": "우리 동네", "product": "계절 꽃다발"},
  "tracks": [
    {"id": "basic", "title": "기본 과정", "summary": "...", "status": "open",
     "parts": [{"number": 1, "title": "시작하기", "lessons": [
        {"id": "b01", "number": 1, "title": "...", "subtitle": "...", "minutes": 5, "surface": "both", "status": "published"}
     ]}]},
    {"id": "vibe", "title": "바이브 코딩 심화", "summary": "...", "status": "soon", "parts": []}
  ]
}
```

`status`: `published` (file exists, clickable) or `soon` (shown dimmed with "준비 중").

## 7. UI labels (ours — keep this wording)

- Catalog: title "Claude 배우기", progress "11강 중 3강 마침", button "이어서 배우기", panel "내 가게 정보로 바꾸기", track badge "준비 중".
- Lesson header: "1부 · 시작하기", "4강", title, subtitle, chips "약 6분", "어디서: 브라우저·앱" / "어디서: 일손박스 터미널" / "어디서: 둘 다", "내용 확인일 2026-10-20".
- Sections: "이번 시간에 만들 것" (outcome), "준비할 것" (prepare), "따라 하기" (steps), "왜 그런가요?" (explain), "잘 안 될 때" (trouble), "스스로 확인" (checklist), "한 줄 정리" (keep), "더 알아보기" (links), "근거" (sources), "고친 기록" (history, collapsed).
- Step parts: prompt box header "Claude에게 보낼 말" + [복사]; command box header "터미널에 붙여 넣기" + [복사]; `self` callout "이건 직접 해 주세요"; `success` callout "이렇게 보이면 성공"; `tip` "알아두면 좋아요"; `caution` "조심하세요"; status card "내 일손박스 지금 상태".
- Footer: "이 강 마쳤어요" toggle, previous/next lesson buttons ("앞 강", "다음 강으로").
- Toolbar: "글자 크게", "목차".

## 8. Writing style

- Korean 해요체, warm and plain. One sentence per line where it helps. No jargon without an immediate plain explanation in parentheses.
- Do not address the reader as "사장님" or "여러분" repeatedly; write directly ("이렇게 해 보세요").
- Each lesson: outcome first, then do, then explain. 3–5 steps.
- Every prompt is something a beginner can paste as is, filled from the shop panel. Teach the habit of telling Claude what not to do, asking it to ask questions first, and asking it to mark guesses.
- Facts that change (prices, plan features, limits, menu names) appear only with the checked date and an official source. Use only facts in `docs/claude-learn/FACTS.md`; if something is not there, leave it out or mark it for verification instead of guessing.
- Screens change: describe buttons by their visible label and position, and say "화면 모양은 바뀔 수 있어요" once where it matters.
- No real customer names, no private hosts, no prices we cannot source. The repo is public.

## 8a. Figures (Jake, 2026-10-20: every lesson gets fitting images, charts or diagrams)

- Every published lesson has **2–4 figures**: one `cover` figure under the lesson header that shows the outcome or the big picture, plus figures inside steps or explain items where a picture beats words.
- Kinds: concept diagram (how things connect), flow diagram (step order), comparison (before/after, good/bad request), simplified screen sketch (where a button is — schematic, labelled "실제 화면은 조금 다를 수 있어요"), terminal sketch (what the terminal shows), decision chart (which plan, what to do when stuck), checklist card.
- Format: **SVG only** (`ilson update` ships no PNG/JPG). Hand-authored vector, no scripts, no `foreignObject`, no external references, no embedded raster images, no web fonts. ≤ 60 KB per file.
- Look: drawn on a light plate so it reads in dark and light themes. Palette: background `#ffffff`/`#f5f6f6`, ink `#1d1d21`, secondary ink `#6b7078`, hairline `#e4e4e8`, accent `#5e6ad2` (soft `#e8eafb`), success `#1d8a38`, caution `#a3720a`, danger `#c4423b`. Rounded corners 12–16. Generous whitespace.
- Text: Korean, `font-family="Apple SD Gothic Neo, Pretendard, 'Noto Sans KR', sans-serif"`, at least 18px at the 720px design width (main labels 20–26px, titles up to 30px), no more than ~12 words per label. Never put facts in a figure that are not in the lesson text or FACTS.md.
- Size: `viewBox` width 720 (height as needed, ideally ≤ 480). The box web UI opens on the Mac itself, so the legibility target is the desktop reading column (~700px); narrow windows can tap to enlarge. Split complex ideas into two figures instead of shrinking text.
- Shared look: follow `docs/claude-learn/FIGURE-STYLE.md` and its reference drawing so every figure looks like one set.
- Accessibility: every figure has `alt` (what it shows, one sentence) and a `caption`.
- Screen sketches must not imitate Anthropic branding pixel for pixel: no logos, generic shapes, real button labels only when FACTS.md confirms them.
- File names: `img/<lessonId>-<slug>.svg`.
- Schema: lesson-level `"cover": {figure}`; `figure` allowed in steps and in explain items. Figure object: `{"src": "img/b04-compare.svg", "alt": "...", "caption": "..."}`. The renderer shows figures on a plate and opens a larger view on click.

## 8b. Adding or publishing a lesson

1. Write `lessons/<id>.json` (schema §6) with facts only from FACTS.md, plus figure briefs in `docs/claude-learn/figures/<id>.md`.
2. Draw the figures into `img/` per §8a and FIGURE-STYLE.md.
3. Run an independent content review (facts, beginner readability, originality §2) and fix.
4. Run `python3 tools/sync_learn.py`. It copies title/subtitle/minutes/surface into `catalog.json`, publishes the lesson only when every figure exists, and rewrites the learn block of `STATIC`. `tests/test_learn.py` fails if this step was skipped.
5. Earlier lessons mark references to unpublished lessons as "N강(준비 중)" or "(N강, 준비 중)". Search for the new lesson's number and remove those markers.
6. Run the full suite, then ship through a box release (`ilson update`).

The lesson titles in §4 are working titles; `catalog.json` is the source of truth.

## 9. Acceptance (first release)

- Menu "Claude 배우기" appears in `/current/`; catalog shows both tracks; 11 published lessons open; unpublished ones show "준비 중".
- Shop panel fills prompts; copy works; progress and large text persist; page works with storage blocked.
- Live status card shows real states from `/api/overview`.
- Works at 375px width (no horizontal scroll) and in dark and light themes.
- All new files are in `STATIC`; tests cover static serving, catalog/lesson JSON validity (every published lesson file exists and matches the schema), nav registration, and the escape rule.
- Full test suite passes with `/usr/bin/python3 -B -m unittest discover -s tests`.
- Content passes the independent review: facts match FACTS.md sources, beginner readability, originality against section 2.
