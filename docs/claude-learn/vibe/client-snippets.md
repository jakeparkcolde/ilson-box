# 클라이언트 코드: 손님 예약 화면 + 사장님 예약함

Plain HTML/CSS/JS, 빌드 없음, Node 없음. supabase-js 는 CDN 한 줄로 불러와요 (FACTS-VIBE V8.10).
아래 코드 블록은 그대로 시험했어요: 실제 supabase-js 2.118.0 (CDN `@2` 가 2026-10-21에 주는 파일) + jsdom 화면 + Supabase Postgres 17 / PostgREST v14.7 / Auth(GoTrue) v2.188.1. 결과는 `test-log.md` 의 J 표 (8절 사장님 계정은 U 표, 9절 CSV 는 X 표).

전제:
- `schema.sql` 과 `owner-policy.sql` 을 실행했어요.
- **Allow new users to sign up**(새 사용자 가입 허용)을 껐고, 사장님 계정이 있어요.
- 표 이름 `reservation_requests`, 칸 이름, 상태 값 `새 요청` / `확인함` / `완료` 는 SQL 과 글자 하나까지 같아야 해요.

## 1. config.js: 공개해도 되는 두 값만

```js
// config.js : 공개해도 되는 두 값만 넣어요.
// Supabase > Connect (또는 Settings > API Keys) 에서 복사해요.
// secret key(sb_secret_...)와 데이터베이스 비밀번호는 절대 여기에 넣지 않아요.
const SUPABASE_URL = 'https://여기에-프로젝트-주소.supabase.co';
const SUPABASE_PUBLISHABLE_KEY = 'sb_publishable_여기에-키';
```

## 2. reserve.html: 폼 부분

`name` 은 아래 reserve.js 가 찾는 이름이라 바꾸면 안 돼요. `maxlength` 는 schema.sql 의 글자 수 제한과 같아요.

```html
<!-- reserve.html : <body> 안에 넣는 부분 -->
<form id="reserve-form">
  <label>이름 <input name="customer_name" maxlength="30" required autocomplete="name"></label>
  <label>연락처 <input name="contact" maxlength="50" required autocomplete="tel"></label>
  <label>원하는 날짜 <input name="wanted_date" type="date"></label>
  <label>원하는 시간 <input name="wanted_time" maxlength="20" placeholder="예: 오후 2시"></label>
  <label>원하는 상품 <input name="item" maxlength="50"></label>
  <label>남길 말 <textarea name="message" maxlength="500" rows="4"></textarea></label>
  <label>
    <input name="consent" type="checkbox" required>
    개인정보 수집·이용에 동의합니다 (<a href="privacy.html">자세히</a>)
  </label>
  <button type="submit">예약 요청 보내기</button>
  <p id="reserve-result" role="status" aria-live="polite"></p>
</form>
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.118.0"></script>
<script src="config.js"></script>
<script src="reserve.js"></script>
```

동의 문구 옆에는 심화 8강의 네 가지 항목(무엇을, 왜, 얼마나 보관, 거부할 권리)을 함께 보여 주세요.

## 3. reserve.js: 보내기만 하는 코드

```js
// reserve.js : 손님 예약 화면. 예약 요청을 "보내기"만 해요.
// 손님 화면은 로그인 정보를 쓰지 않아요.
// (같은 브라우저에서 사장님이 로그인해 있어도 손님으로 보내야 하니까요)
const db = supabase.createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, {
  auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
});

const form = document.getElementById('reserve-form');
const result = document.getElementById('reserve-result');

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = form.querySelector('button[type="submit"]');
  const value = (name) => form.elements[name].value.trim();
  const optional = (name) => value(name) || null; // 빈칸은 null 로 보내요

  if (!form.elements.consent.checked) {
    result.textContent = '개인정보 수집·이용에 동의해 주셔야 보낼 수 있어요.';
    return;
  }

  button.disabled = true; // 두 번 눌러도 한 번만 보내요
  result.textContent = '보내는 중이에요…';

  // .select() 를 붙이지 않아요. 손님은 읽기 권한이 없어서 붙이면 실패해요.
  const { error } = await db.from('reservation_requests').insert({
    customer_name: value('customer_name'),
    contact: value('contact'),
    wanted_date: optional('wanted_date'),
    wanted_time: optional('wanted_time'),
    item: optional('item'),
    message: optional('message'),
    consent: true,
  });

  button.disabled = false;
  if (error) {
    console.error('예약 요청 저장 실패', error); // 원인은 개발자 도구에서만 보여요
    result.textContent = friendlyMessage(error);
    return;
  }
  form.reset();
  result.textContent = '예약 요청을 받았어요. 가게에서 확인한 뒤 연락드릴게요.';
});

// 오류 번호를 손님이 알아듣는 말로 바꿔요.
function friendlyMessage(error) {
  if (error.code === '23514' || error.code === '23502') {
    return '빈칸이나 너무 긴 글이 있어요. 확인하고 다시 보내 주세요.';
  }
  if (error.code === '22007' || error.code === '22008') {
    return '날짜를 다시 골라 주세요.';
  }
  return '지금은 보내지 못했어요. 잠시 뒤 다시 보내시거나 가게로 전화 주세요.';
}
```

## 4. admin.html: 사장님 화면 뼈대

```html
<!-- admin.html : <head> 에 noindex 한 줄, <body> 안에 아래 두 칸 -->
<meta name="robots" content="noindex">

<section id="login-box">
  <h1>사장님 로그인</h1>
  <form id="login-form">
    <label>이메일 <input name="email" type="email" required autocomplete="username"></label>
    <label>비밀번호 <input name="password" type="password" required autocomplete="current-password"></label>
    <button type="submit">로그인</button>
  </form>
  <p id="login-message" role="status" aria-live="polite"></p>
</section>

<section id="inbox" hidden>
  <h1>예약함</h1>
  <button id="reload-button" type="button">새로고침</button>
  <button id="logout-button" type="button">로그아웃</button>
  <p id="inbox-message" role="status" aria-live="polite"></p>
  <ul id="request-list"></ul>
</section>
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.118.0"></script>
<script src="config.js"></script>
<script src="admin.js"></script>
```

## 5. admin.js: 로그인, 최신순 목록, 상태 바꾸기, 로그아웃

```js
// admin.js : 사장님 예약함. 로그인 → 최신순 목록 → 상태 바꾸기 → 로그아웃
const db = supabase.createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY);
const STATUSES = ['새 요청', '확인함', '완료']; // schema.sql 과 똑같이

const loginBox = document.getElementById('login-box');
const loginForm = document.getElementById('login-form');
const loginMessage = document.getElementById('login-message');
const inbox = document.getElementById('inbox');
const inboxMessage = document.getElementById('inbox-message');
const list = document.getElementById('request-list');

loginForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  loginMessage.textContent = '로그인 중…';
  const { error } = await db.auth.signInWithPassword({
    email: loginForm.elements.email.value.trim(),
    password: loginForm.elements.password.value,
  });
  if (error) {
    console.error('로그인 실패', error);
    loginMessage.textContent = '이메일이나 비밀번호가 맞지 않아요.';
    return;
  }
  loginForm.reset();
  loginMessage.textContent = '';
  showInbox();
});

document.getElementById('reload-button').addEventListener('click', () => loadRequests());
document.getElementById('logout-button').addEventListener('click', async () => {
  await db.auth.signOut();
  showLogin();
});

// 로그인이 풀리면(오래 두었을 때 등) 로그인 화면으로 돌아가요.
db.auth.onAuthStateChange((event) => {
  if (event === 'SIGNED_OUT') showLogin();
});

function showLogin() {
  inbox.hidden = true;
  loginBox.hidden = false;
  list.replaceChildren();
}

function showInbox() {
  loginBox.hidden = true;
  inbox.hidden = false;
  loadRequests();
}

async function loadRequests() {
  inboxMessage.textContent = '불러오는 중…';
  const { data, error } = await db
    .from('reservation_requests')
    .select('id, created_at, customer_name, contact, wanted_date, wanted_time, item, message, status')
    .order('created_at', { ascending: false })
    .limit(200);
  if (error) {
    console.error('목록 불러오기 실패', error);
    inboxMessage.textContent = '목록을 불러오지 못했어요. 로그아웃한 뒤 다시 로그인해 보세요.';
    return;
  }
  inboxMessage.textContent = data.length
    ? `예약 요청 ${data.length}건 (최신순)`
    : '아직 예약 요청이 없어요. 있어야 하는데 안 보이면 owner-policy.sql 의 아이디를 확인하세요.';
  list.replaceChildren(...data.map(renderRequest));
}

// 손님이 쓴 글은 textContent 로만 넣어요.
// innerHTML 은 쓰지 않아요: 손님이 넣은 코드가 사장님 화면에서 실행될 수 있어요.
function renderRequest(row) {
  const li = document.createElement('li');
  const lines = [
    `${row.customer_name} · ${row.contact}`,
    `원하는 날: ${row.wanted_date ?? '-'} ${row.wanted_time ?? ''}`,
    `상품: ${row.item ?? '-'}`,
    `남긴 말: ${row.message ?? '-'}`,
    `받은 시각: ${new Date(row.created_at).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' })}`,
  ];
  for (const text of lines) {
    const p = document.createElement('p');
    p.textContent = text;
    li.append(p);
  }
  const select = document.createElement('select');
  select.setAttribute('aria-label', '처리 상태');
  for (const status of STATUSES) {
    select.add(new Option(status, status, false, status === row.status));
  }
  select.addEventListener('change', () => changeStatus(row.id, select));
  li.append(select);
  return li;
}

async function changeStatus(id, select) {
  const status = select.value;
  select.disabled = true;
  // .select('id') 로 실제로 바뀐 줄이 있는지 확인해요.
  // (권한이 없으면 오류 없이 0줄이 바뀌어요)
  const { data, error } = await db
    .from('reservation_requests')
    .update({ status, handled_at: status === '새 요청' ? null : new Date().toISOString() })
    .eq('id', id)
    .select('id');
  select.disabled = false;
  if (error || data.length === 0) {
    console.error('상태 바꾸기 실패', error);
    inboxMessage.textContent = '상태를 바꾸지 못했어요. 다시 로그인한 뒤 해 보세요.';
    loadRequests();
    return;
  }
  inboxMessage.textContent = `'${status}'(으)로 바꿨어요.`;
}

// 처음 열 때: 이미 로그인돼 있으면 바로 예약함을 보여 줘요.
db.auth.getSession().then(({ data }) => (data.session ? showInbox() : showLogin()));
```

## 6. 오류가 나면: 번호와 뜻

| 보이는 것 | 뜻 | 할 일 |
|---|---|---|
| `42501` permission denied for table reservation_requests | 그 역할에 GRANT 가 없어요. 손님이 읽기를 시도했거나, 받지 않는 칸(status 등)을 보냈거나, schema.sql 의 3번(GRANT)이 빠졌어요. | 손님은 `.select()` 없이 7칸만 보내기. 표를 새로 만들었다면 schema.sql 전체를 다시 확인 |
| `42501` new row violates row-level security policy | 규칙(policy)에 안 맞아요. 예: 동의(consent)가 false | 동의 체크 확인 |
| `23514` violates check constraint | 글자 수 초과, 빈칸만 입력, 허용되지 않은 상태 값 | 입력 확인 (maxlength 와 SQL 제한이 같아야 해요) |
| `23502` violates not-null constraint | 이름·연락처 같은 필수 칸이 비었어요 | 입력 확인 |
| `22007` / `22008` | 날짜 형식이 틀렸어요 | 날짜 다시 고르기 |
| `21000` UPDATE requires a WHERE clause | 조건 없이 "전부 바꾸기"를 막아 주는 Supabase 안전장치 | `.eq('id', id)` 처럼 한 줄을 지정 |
| 로그인 후 목록이 비어 있음 (오류 없음) | 사장님 아이디가 owner-policy.sql 과 달라요, 또는 owner-policy.sql 을 아직 안 돌렸어요 | Users 의 User UID 를 다시 복사해 owner-policy.sql 다시 실행 |
| 상태를 바꿨는데 "바꾸지 못했어요" | 0줄이 바뀌었어요 (사장님이 아닌 계정, 또는 로그인 만료) | 로그아웃 후 사장님 계정으로 다시 로그인 |

## 7. 꼭 지킬 것

- 손님 화면(reserve.js)은 `.insert()` 뒤에 `.select()` 를 붙이지 않아요.
- 손님 화면은 `persistSession: false` 로 만들어요. 빼면 같은 브라우저에서 사장님이 로그인해 있을 때 손님 요청이 사장님 이름으로 가서 `42501` 로 거절돼요 (시험 J5b).
- 사장님 화면은 손님 글을 `textContent` 로만 보여 줘요. `innerHTML` 금지.
- 상태를 바꿀 때는 `.eq('id', id)` 로 한 줄만, `.select('id')` 로 바뀐 줄 수를 확인해요.
- 페이지와 저장소에는 프로젝트 주소와 publishable key 만. secret key 는 어디에도 넣지 않아요.
- `@2` 는 늘 최신 2.x 를 불러와요. 다 만든 뒤에는 `@2.118.0` 처럼 정확한 버전으로 고정하면 나중에 저절로 바뀌지 않아요 (2.118.0 = 2026-10-21 npm 최신).

## 8. 사장님 계정 만들기 (심화 7강)

대시보드에서 이메일과 비밀번호로 바로 만들어요. 메일도, 비밀번호를 정하는 페이지도 필요 없어요.
화면 이름은 Supabase 대시보드 소스(supabase/supabase, master, 2026-10-21 확인)와 같아요.

1. **Authentication** → **Users** → **Add user**(사용자 추가) → **Create new user**(새 사용자 만들기)
2. 창 **Create a new user** 에서 **Email address**(이메일 주소)에 사장님 이메일, **User Password**(비밀번호)에 새 비밀번호를 넣어요.
3. **Auto confirm user?**(사용자 자동 확인)는 켜진 그대로 둬요. 기본으로 켜져 있어요. 창에 "A confirmation email will not be sent when creating a user via this form." 이라고 나와요.
4. **Create user**(사용자 만들기)를 눌러요.
5. 목록에서 사장님 줄을 열어 **User UID** 를 복사해 owner-policy.sql 의 ★ 두 곳에 넣고 Run 해요.
   SQL Editor 에서 `select id, email from auth.users;` 를 Run 해도 UID 가 보여요.

**Allow new users to sign up**(새 사용자 가입 허용)을 꺼도 이 방법으로 만들 수 있어요 (시험 U1). 끄면 막히는 것은 웹페이지에서 스스로 가입하는 것(`signUp`)뿐이에요 (시험 J14).

알아 둘 것:
- **Auto confirm user?** 를 끄고 만들면 로그인이 안 돼요. 서버는 `email_not_confirmed` 를 돌려주고, admin.js 는 "이메일이나 비밀번호가 맞지 않아요." 를 보여 줘요 (시험 U2). 그 계정을 지우고 체크한 채 다시 만들면 돼요. UID 가 바뀌니 owner-policy.sql 도 다시 Run 해요.
- **Send invitation**(초대 보내기)으로 만들면 사장님이 정한 비밀번호가 없는 계정이 생겨서 이 화면으로는 로그인할 수 없어요 (시험 U4). 초대 메일의 링크는 **Site URL** 로 돌아가는데, 바꾸기 전 값은 `http://localhost:3000` 이에요. 이 과정에서는 초대를 쓰지 않아요.
- 비밀번호를 잊었을 때: 대시보드에는 비밀번호를 직접 바꾸는 버튼이 없어요. **Send password recovery** 는 메일 링크라 초대와 같은 Site URL 문제가 있어요. 가장 쉬운 길은 Users 에서 사장님 계정을 **Delete user** 로 지우고, 같은 이메일로 **Create new user** 를 다시 한 뒤, 새 User UID 로 owner-policy.sql 을 다시 Run 하는 거예요. 예약 요청은 그대로 남아요 (시험 U5).

## 9. CSV로 내려받기 (심화 10강)

사장님 예약함에 버튼 하나와 함수 몇 개를 더해요. 사장님으로 로그인했을 때만 줄이 담기고, 다른 계정은 0건이에요 (RLS).

```html
<!-- admin.html 에 추가 : <section id="inbox"> 안, 로그아웃 버튼 다음 줄 -->
<button id="csv-button" type="button">CSV로 내려받기</button>
```

```js
// admin.js 맨 아래에 추가 : CSV로 내려받기 (사장님만)
const CSV_COLUMNS = [
  ['created_at', '받은 시각'],
  ['customer_name', '이름'],
  ['contact', '연락처'],
  ['wanted_date', '원하는 날짜'],
  ['wanted_time', '원하는 시간'],
  ['item', '상품'],
  ['message', '남긴 말'],
  ['status', '상태'],
  ['handled_at', '처리 시각'],
];

document.getElementById('csv-button').addEventListener('click', () => downloadCsv());

async function downloadCsv() {
  inboxMessage.textContent = 'CSV 파일을 만드는 중…';
  const rows = await fetchAllRequests();
  if (!rows) {
    inboxMessage.textContent = 'CSV를 만들지 못했어요. 로그아웃한 뒤 다시 로그인해 보세요.';
    return;
  }
  if (rows.length === 0) {
    inboxMessage.textContent = '내려받을 예약 요청이 없어요.';
    return;
  }
  const lines = [CSV_COLUMNS.map(([, title]) => csvCell(title))];
  for (const row of rows) {
    lines.push(CSV_COLUMNS.map(([key]) => csvCell(csvText(key, row[key]))));
  }
  // 맨 앞의 ﻿(BOM) 덕분에 엑셀·Numbers 가 한글을 깨뜨리지 않고 열어요.
  const csv = '﻿' + lines.map((cells) => cells.join(',')).join('\r\n') + '\r\n';
  const today = new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' }); // 예: 2026-10-21
  const link = document.createElement('a');
  link.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  link.download = `예약요청-${today}.csv`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 10000);
  inboxMessage.textContent = `예약 요청 ${rows.length}건을 CSV로 내려받았어요.`;
}

// 한 번에 최대 1,000줄씩 오니까, 빈 묶음이 올 때까지 이어서 가져와요.
async function fetchAllRequests() {
  const rows = [];
  const seen = new Set(); // 받는 도중 새 요청이 들어와 겹친 줄은 한 번만 담아요
  let from = 0;
  for (;;) {
    const { data, error } = await db
      .from('reservation_requests')
      .select('id, ' + CSV_COLUMNS.map(([key]) => key).join(', '))
      .order('created_at', { ascending: false })
      .order('id', { ascending: false })
      .range(from, from + 999);
    if (error) {
      console.error('CSV 불러오기 실패', error);
      return null;
    }
    if (data.length === 0) return rows;
    from += data.length;
    for (const row of data) {
      if (!seen.has(row.id)) {
        seen.add(row.id);
        rows.push(row);
      }
    }
  }
}

// 시각은 한국 시간 "2026-10-21 14:05:09" 꼴로 바꾸고, 빈칸은 비워 둬요.
function csvText(key, value) {
  if (value === null || value === undefined) return '';
  if (key === 'created_at' || key === 'handled_at') {
    return new Date(value).toLocaleString('sv-SE', { timeZone: 'Asia/Seoul' });
  }
  return String(value);
}

// 한 칸을 CSV 규칙대로 만들어요: 큰따옴표로 감싸고, 안의 " 는 "" 로 바꿔요.
// = + - @ 나 탭으로 시작하면 앞에 ' 를 붙여 엑셀이 수식으로 실행하지 않게 해요.
function csvCell(text) {
  const safe = /^[=+\-@\t\r]/.test(text) ? `'${text}` : text;
  return `"${safe.replace(/"/g, '""')}"`;
}
```

알아 둘 것:
- 쉼표, 큰따옴표, 줄바꿈이 든 글도 칸이 밀리지 않아요 (시험 X2).
- `=`, `+`, `-`, `@`, 탭으로 시작하는 칸은 앞에 `'` 가 붙어요. 그래서 `+82` 로 시작하는 연락처는 `'+82…` 로 보여요 (시험 X3).
- 1,000건이 넘어도 끝까지 담아요 (시험 X1, X5).
- 파일 이름은 `예약요청-2026-10-21.csv` 처럼 한국 날짜예요.
- 내려받은 파일에도 손님 개인정보가 있어요. 안전한 곳에 두고, 보관 기간이 지나면 cleanup.sql 로 지울 때 이 파일도 함께 지워요.
