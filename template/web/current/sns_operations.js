/* SNS 운영과 내부 계정 연결. 결재는 기존 사람 승인 경로를 공유한다. */
const SNS_OPS = { data: null, box: null, busy: false, error: '', brand: '', channel: '', view: 'scheduled', query: '', page: 0, groupBy: 'brand', health: '', account: '', recordsOpen: false, record: '', weeklyIds:null };

// 2026-09-24: 60초 갱신·승인 응답 때 DOM이 교체돼 읽던 본문 맨 위로 돌아갔다.
// 같은 글을 다시 그릴 때만 상세 스크롤을 복원한다. 다른 글에 이전 위치를 옮기지 않는다.
function snsCaptureView(){
  if(S.tab!=='sns')return null;
  const main=document.querySelector('#main'),detail=document.querySelector('.sns-post-detail');
  return {top:main?.scrollTop||0,left:main?.scrollLeft||0,record:detail?.dataset.record,
    detailTop:detail?.scrollTop||0,detailLeft:detail?.scrollLeft||0};
}
function snsRestoreView(keep){
  if(!keep||S.tab!=='sns')return;
  const main=document.querySelector('#main'),detail=document.querySelector('.sns-post-detail');
  if(main){main.scrollTop=keep.top;main.scrollLeft=keep.left;}
  if(detail&&keep.record&&detail.dataset.record===keep.record){detail.scrollTop=keep.detailTop;detail.scrollLeft=keep.detailLeft;}
}

async function loadSnsOperations(){
  if (SNS_OPS.busy) return;
  SNS_OPS.busy = true; SNS_OPS.error = '';
  if (['sns','sns-accounts'].includes(S.tab)) renderIdle();
  try {
    const [r, box, naver, browser, readiness] = await Promise.all([
      fetch('/api/sns-operations'+(SNS_WEEK.week?'?week='+encodeURIComponent(SNS_WEEK.week):''), { cache: 'no-store' }),
      fetch('/api/sns-internal', { cache: 'no-store' }).then(async res => {
        if (!res.ok) return null;
        const value = await res.json();
        return Array.isArray(value.accounts) ? value : null;
      }).catch(() => null),
      fetch('/api/sns-naver', {cache:'no-store'}).then(res=>res.ok?res.json():null).catch(()=>null),
      fetch('/api/sns-browser', {cache:'no-store'}).then(res=>res.ok?res.json():null).catch(()=>null),
      fetch('/api/sns-readiness', {cache:'no-store'}).then(res=>res.ok?res.json():null).catch(()=>null),
    ]);
    SNS_OPS.naver = naver;
    SNS_OPS.box = box;
    SNS_OPS.browser = browser;
    SNS_OPS.readiness = readiness;
    if (r.status === 401) { location.href = '/'; return; }
    if (!r.ok) throw new Error(r.status === 403 ? '이 사무소의 SNS 자료를 볼 권한이 없습니다.' : 'SNS 운영 자료를 불러오지 못했습니다.');
    const data = await r.json();
    if (!Array.isArray(data.records) || !Array.isArray(data.accounts) || !Array.isArray(data.sources)) throw new Error('조회 결과 형식을 확인하지 못했습니다.');
    if(naver?.provider==='playwright'){
      for(const a of data.accounts){
        if(a.platform==='naverblog'&&a.account===naver.account)Object.assign(a,{
          state:naver.state,label:naver.label,action:naver.state==='ok'?'':'전용 로그인 창에서 로그인 후 연결 확인',
          route:'browser',route_label:'일손 전용 브라우저',
          evidence:(naver.state==='ok'?'블로그 글쓰기 권한 확인':'전용 브라우저 상태')+(naver.checked_at?' · '+snsTime(naver.checked_at):' 미확인')});
      }
    }
    snsMergeBrowserHealth(data,browser);
    SNS_OPS.rawAccounts = data.accounts.map(a=>({...a}));
    snsMergeInternalAccounts(data, box);
    SNS_OPS.data = data;
  } catch (e) {
    SNS_OPS.data = null; SNS_OPS.rawAccounts = null;
    SNS_OPS.error = e.message || '연결 상태를 확인해 주세요.';
  } finally {
    SNS_OPS.busy = false;
    if (['sns','sns-accounts'].includes(S.tab)) renderIdle();
  }
}

function snsMergeBrowserHealth(data,browser){
  for(const health of browser?.accounts||[]){
    const a=data.accounts.find(a=>a.platform===health.platform&&a.account===health.account);
    if(a)Object.assign(a,{browser_health:health,state:health.state,label:health.label,
      action:health.login_state==='login_required'?'발행에 사용하는 브라우저에서 다시 로그인':'로그인과 계정 상태 확인',
      evidence:'브라우저 로그인 점검'+(health.checked_at?' · '+snsTime(health.checked_at):' 미실행')});
  }
}
function snsSetFilter(key, value){
  SNS_OPS.weeklyIds=null;
  SNS_OPS[key] = value; SNS_OPS.page = 0; SNS_OPS.record = '';
  if (['brand','channel','query','health'].includes(key)) SNS_OPS.account = '';
  render();
}
function snsPage(delta){ SNS_OPS.page = Math.max(0, SNS_OPS.page + delta); SNS_OPS.record = ''; render(); }
function snsCanonicalAccount(platform,account){
  const name=String(account||'').trim().replace(/^@/,'').toLowerCase(),key=platform+':'+name;
  const target=SNS_OPS.box?.binding==='matched'?SNS_OPS.box.account_aliases?.[key]:null;
  return target?.startsWith(platform+':')?target.slice(platform.length+1):name;
}
function snsAccountKey(a){ return JSON.stringify([a.platform, snsCanonicalAccount(a.platform,a.account)]); }
function snsBrands(a){ return a.brands && a.brands.length ? a.brands : [a.brand || '미분류']; }
function snsAccountIssue(a){ return ['error','warning'].includes(a.state); }
function snsPickAccount(key){
  SNS_OPS.weeklyIds=null;
  SNS_OPS.account = key; SNS_OPS.view = 'all'; SNS_OPS.page = 0; render();
  document.getElementById('snsRecordsPanel')?.scrollIntoView({behavior:'smooth',block:'start'});
}
function snsClearFilters(){
  // render의 입력 보존보다 먼저 비워야 이전 검색어가 되살아나지 않는다.
  const input=document.getElementById('snsQuery');if(input)input.value='';
  Object.assign(SNS_OPS,{brand:'',channel:'',health:'',account:'',query:'',page:0,record:'',weeklyIds:null}); render(); }

function snsAccounts(data, withQuery=true){
  const q = withQuery ? SNS_OPS.query.toLowerCase() : '';
  return data.accounts.filter(a => (!SNS_OPS.brand || snsBrands(a).includes(SNS_OPS.brand))
    && (!SNS_OPS.channel || a.channel === SNS_OPS.channel)
    && (!SNS_OPS.health || (SNS_OPS.health === 'issue' ? snsAccountIssue(a) : a.state === SNS_OPS.health))
    && (!q || [a.account,a.channel,...snsBrands(a)].join(' ').toLowerCase().includes(q)));
}

function snsGroups(data, axis){
  const groups = new Map();
  for (const a of data.accounts) for (const name of new Set(axis === 'channel' ? [a.channel] : snsBrands(a))) {
    if (!groups.has(name)) groups.set(name,{name,accounts:new Map()});
    groups.get(name).accounts.set(snsAccountKey(a),a);
  }
  return [...groups.values()].map(g => {
    const rows=[...g.accounts.values()];
    return {name:g.name,total:rows.length,issue:rows.filter(snsAccountIssue).length,
      unknown:rows.filter(a=>a.state==='unknown').length,active:rows.filter(a=>a.state==='ok').length};
  }).sort((a,b)=>(a.name==='미분류')-(b.name==='미분류') || b.issue-a.issue || a.name.localeCompare(b.name,'ko'));
}

function snsAccountActivity(a, data){
  const rows=data.records.filter(r=>snsAccountKey(r)===snsAccountKey(a) && (!SNS_OPS.brand || r.brand===SNS_OPS.brand));
  const now=Date.parse(data.generated_at);
  const latest=rows.filter(r=>r.status==='published' && r.published_at).map(r=>r.published_at).sort().at(-1) || '';
  const next=rows.filter(r=>['scheduled','approved'].includes(r.status) && Date.parse(r.scheduled_at)>now).map(r=>r.scheduled_at).sort()[0] || '';
  return {latest,next,pending:rows.filter(r=>r.status==='pending').length,attention:rows.filter(r=>r.attention).length,total:rows.length};
}

function snsTime(value){
  if (!value || !Number.isFinite(Date.parse(value))) return '미기록';
  return new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value));
}

function snsRecords(data){
  if(SNS_OPS.weeklyIds)return data.records.filter(r=>SNS_OPS.weeklyIds.includes(r.id));
  const visibleAccounts = new Set(snsAccounts(data,false).map(snsAccountKey));
  const matchingAccounts = new Set(snsAccounts(data).map(snsAccountKey)),q=SNS_OPS.query.toLowerCase();
  return data.records.filter(r => visibleAccounts.has(snsAccountKey(r)) && (!SNS_OPS.brand || r.brand === SNS_OPS.brand)
    && (!SNS_OPS.channel || r.channel === SNS_OPS.channel)
    && (!SNS_OPS.account || snsAccountKey(r) === SNS_OPS.account)
    && (!q || matchingAccounts.has(snsAccountKey(r)) || [r.title,r.excerpt].join(' ').toLowerCase().includes(q)));
}

// 지난 예약·시각 미정·실패는 예정 건수와 분리해도 장부 상태는 바꾸지 않는다.
function snsRecordIssue(r){
  return !!(r.attention || r.attempt_error || (['approved','scheduled'].includes(r.status) && !Number.isFinite(Date.parse(r.scheduled_at))));
}
function snsRecordLabel(r){
  // 장부의 예약 상태만으로 실제 일정이 확인된 것처럼 표시하지 않는다.
  if(r.status==='scheduled' && !Number.isFinite(Date.parse(r.scheduled_at)))return '예약 확인 필요';
  return r.overdue?'예약 지연':r.status_label;
}
function snsRecordMatches(r, view){
  return view === 'all' || (view === 'attention' ? snsRecordIssue(r) : view === 'scheduled' ? ['approved','scheduled'].includes(r.status) && !snsRecordIssue(r) : r.status === view);
}
function snsScheduledRecords(rows){
  return rows.filter(r=>snsRecordMatches(r,'scheduled')).sort((a,b)=>Date.parse(a.scheduled_at)-Date.parse(b.scheduled_at));
}

function snsBadge(label, state){
  const cls = ['ok', 'warning', 'error', 'unknown'].includes(state) ? state : 'unknown';
  return `<span class="sns-badge ${cls}">${esc(label)}</span>`;
}

function snsLink(url){
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== 'https:' || parsed.username || parsed.password) return '';
    return `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">게시물 열기 ↗</a>`;
  } catch(e) { return ''; }
}

let snsConnectBusy = false;
let snsConnectMessage = '';
let snsConnectUrl = '';
let snsConnectionTimer = null;

function snsHealth(a){
  if (a.health === 'error' || a.state === 'expired') return ['error','재연결 필요'];
  if (a.health === 'mismatch') return ['error','연결 계정 불일치'];
  if (a.health === 'ok') return a.state === 'stale' ? ['warning','인증 확인 · 갱신 필요'] : ['ok','인증 확인됨'];
  return ['unknown','인증 확인 필요'];
}

function snsMergeInternalAccounts(data, box){
  if (box?.binding !== 'matched') return;
  for (const a of box.accounts.filter(a=>a.publishing)) {
    let row = data.accounts.find(r=>r.platform===a.platform && String(r.account).replace(/^@/,'').toLowerCase()===a.username.toLowerCase());
    if (!row) { row={platform:a.platform,account:a.username,channel:a.platform==='threads'?'Threads':'인스타그램',brand:'미분류',brands:['미분류']}; data.accounts.push(row); }
    const [state,label]=snsHealth(a);
    Object.assign(row,{state,label,expires_at:a.expires_at,evidence:'내부 일손 · SNS 인증 조회',action:state==='ok'?'':'내부 연결에서 재연결',internal:true});
  }
}

async function snsConnect(platform, account='', preparedPopup=undefined, pageId=''){
  if (snsConnectBusy) return;
  // 클릭 이벤트 안에서 창을 열어 모바일 팝업 차단을 줄인다. 차단되면 링크로 계속.
  const popup=preparedPopup===undefined?window.open('about:blank','_blank'):preparedPopup;
  if (popup) { popup.opener=null; popup.document.title='SNS 연결'; popup.document.body.textContent='SNS 인증 화면을 준비하고 있습니다…'; }
  snsConnectBusy=true; snsConnectMessage='인증 화면을 준비하고 있습니다…'; snsConnectUrl=''; render();
  try {
    const r=await fetch('/api/sns-internal/connect',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({platform,account,page_id:pageId})});
    const data=await r.json();
    if (!r.ok || !data.ok) throw new Error(data.error || '연결 요청을 만들지 못했습니다.');
    const url=new URL(data.authorize_url);
    if (url.protocol!=='https:' || !['threads.net','www.instagram.com','www.facebook.com'].includes(url.hostname)) throw new Error('인증 주소를 확인하지 못했습니다.');
    snsConnectUrl=url.href;
    if (popup) popup.location.replace(url.href);
    snsConnectMessage='SNS에서 로그인·동의를 마친 뒤 이 화면으로 돌아오세요. 연결 결과는 자동으로 갱신됩니다.';
    clearTimeout(snsConnectionTimer);
    const until=Date.now()+11*60*1000;
    const poll=async()=>{
      if (Date.now()>until || !['sns','sns-accounts'].includes(S.tab)) return;
      await loadSnsOperations();
      snsConnectionTimer=setTimeout(poll,5000);
    };
    snsConnectionTimer=setTimeout(poll,3000);
  } catch(e) { popup?.close(); snsConnectMessage=e.message || 'SNS 연결 요청에 실패했습니다.'; }
  finally { snsConnectBusy=false; if(['sns','sns-accounts'].includes(S.tab)) render(); }
}

function snsBoxPanel(){
  const box=SNS_OPS.box;
  const count=box?.binding==='matched'?box.accounts.length:null;
  return `<section class="sns-panel sns-account-shortcut"><div><h2>SNS 계정 연결</h2><p class="sns-meta">${count===null?'연결 상태 확인 필요':`내부에 저장된 연결 ${count}개`} · 연결 이력과 사업부 분류는 계정 관리에서 확인하세요.</p></div><button class="btn btn-primary" onclick="A.go('sns-accounts')">계정 관리 열기 →</button></section>`;
}

function snsDay(value){
  if(!Number.isFinite(Date.parse(value)))return '';
  const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date(value));
  const part=t=>parts.find(p=>p.type===t).value;
  return `${part('year')}-${part('month')}-${part('day')}`;
}
function snsClock(value){
  return Number.isFinite(Date.parse(value))?new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(value)):'미정';
}
function snsRecordTime(r){
  return SNS_OPS.view==='published'?r.published_at:SNS_OPS.view==='pending'?r.prepared_at:r.scheduled_at||r.published_at||r.prepared_at;
}
function snsDayLabel(value, now){
  const day=snsDay(value);
  if(!day)return '시각 미정';
  const prefix=day===snsDay(now)?'오늘 · ':day===snsDay(new Date(Date.parse(now)+86400000).toISOString())?'내일 · ':'';
  return prefix+new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',month:'long',day:'numeric',weekday:'short'}).format(new Date(value));
}
function snsSelectRecord(id){
  SNS_OPS.record=id;render();
  document.getElementById('snsPostDetailTitle')?.focus({preventScroll:true});
}
function snsCloseRecord(){
  const id=SNS_OPS.record;SNS_OPS.record='';render();
  document.getElementById('sns-post-'+encodeURIComponent(id))?.focus({preventScroll:true});
}
function snsPostImages(r){
  const images=Array.isArray(r.images)?r.images:[];
  if(!images.length)return '';
  return `<section class="sns-post-images" aria-label="첨부 이미지"><h3>첨부 이미지 ${images.length}장</h3><div class="sns-image-gallery">${images.map((raw,i)=>{
    const url=typeof raw==='string'&&(/^https:\/\//i.test(raw)||raw.startsWith('/previews/'))?raw:'';
    const label=`이미지 ${i+1} / ${images.length}`;
    return `<figure>${url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer" aria-label="${label} 크게 보기"><img src="${esc(url)}" alt="${label}" loading="lazy" decoding="async" referrerpolicy="no-referrer" onerror="this.hidden=true;this.nextElementSibling.hidden=false"><span class="sns-image-missing" hidden>이미지를 불러오지 못했습니다.</span></a>`:'<div class="sns-image-missing">이미지 파일을 확인할 수 없습니다.</div>'}<figcaption>${label}${url?' · 클릭하여 크게 보기':''}</figcaption></figure>`;
  }).join('')}</div></section>`;
}
function snsPostVideo(r){
  if(!r.video)return '';
  const raw=r.video.url,url=typeof raw==='string'&&(/^https:\/\//i.test(raw)||raw.startsWith('/previews/'))?raw:'';
  return `<section class="sns-post-video" aria-label="첨부 영상"><h3>${esc(r.video.label||'영상')}</h3>${url?`<video controls preload="metadata" src="${esc(url)}" style="width:100%;max-height:420px">영상 재생을 지원하지 않는 브라우저입니다.</video><p><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">영상 원본 열기</a></p>`:'<p>영상 파일을 확인할 수 없습니다.</p>'}</section>`;
}
// 발행 결재 — 결재함과 같은 실행부(/api/approve·/api/reject, 장부 message_id)를 부른다 (2026-09-24 Jake).
// 여기서 결재 로직을 새로 두면 경로가 갈라진다. mid는 문자열로 다룬다(2^53 초과 id).
const SNS_DECISION={busy:'',kind:'',mid:'',record:'',message:'',note:'',rejectOpen:false};
function snsDecisionReject(mid,open){SNS_DECISION.mid=mid;SNS_DECISION.rejectOpen=open;SNS_DECISION.message='';render();if(open)document.getElementById('sns-decision-note')?.focus();}
async function snsDecide(mid,kind){
  if(SNS_DECISION.busy||!mid)return;
  const note=SNS_DECISION.note.trim();
  const record=SNS_OPS.data?.records.find(r=>r.mid===mid)?.id||SNS_OPS.record;
  Object.assign(SNS_DECISION,{busy:mid,kind,mid,record,message:kind==='reject'?'반려 처리 중…':kind==='now'?'지금 발행으로 등록하는 중…':'예약 큐에 등록하는 중…'});render();
  try{
    const res=await fetch(kind==='reject'?'/api/reject':'/api/approve',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(kind==='reject'?{mid,note}:{mid,immediate:kind==='now'})});
    const data=await res.json().catch(()=>({}));
    if(data.ok){
      const t=data.when?snsTime(data.when):'';
      SNS_DECISION.message=kind==='reject'?(data.redraft?.ok?'반려했어요 — 사유를 반영한 재작성본을 결재함에 올렸어요.':'반려했어요 — '+(data.redraft?.reason||'사유가 기록됐습니다.'))
        :kind==='now'?`지금 발행 등록 완료 — 이 미니의 실행기가 처리합니다.${t?' (예약 '+t+')':''}`:`승인 완료 — ${t||'다음 슬롯'}에 발행 예약됐어요.`;
      SNS_DECISION.rejectOpen=false;SNS_DECISION.note='';
    }else SNS_DECISION.message=`${kind==='reject'?'반려':'승인'} 실패 — ${data.error||'알 수 없는 오류'}`;
  }catch(e){SNS_DECISION.message='처리 실패 — 서버 연결을 확인해 주세요.';}
  finally{SNS_DECISION.busy='';SNS_DECISION.kind='';render();}
  await loadSnsOperations();
}
function snsPostDecision(r){
  const d=SNS_DECISION,mine=(!!d.record&&d.record===r.id)||(!!d.mid&&d.mid===r.mid);
  const notice=mine&&d.message?`<p class="sns-notice" role="status">${esc(d.message)}</p>`:'';
  if(r.status!=='pending'||!r.mid)return notice;
  const busy=d.busy===r.mid,mid=esc(r.mid);
  return `<section class="sns-post-decision" aria-label="발행 결재">
    <p class="sns-meta">결재함과 같은 승인 경로입니다. 승인은 예약 큐 등록이며 바로 게시되지 않습니다.</p>
    <div class="sns-post-links"><button class="btn btn-primary" onclick="snsDecide('${mid}','approve')" ${busy?'disabled':''}>${busy&&d.kind==='approve'?'처리 중…':'승인 (예약 발행)'}</button><button class="btn btn-ghost" onclick="snsDecide('${mid}','now')" ${busy?'disabled':''}>${busy&&d.kind==='now'?'처리 중…':'지금 발행'}</button><button class="btn btn-ghost" onclick="snsDecisionReject('${mid}',${!(mine&&d.rejectOpen)})" ${busy?'disabled':''}>${mine&&d.rejectOpen?'반려 취소':'반려…'}</button></div>
    ${mine&&d.rejectOpen?`<label class="sns-decision-note"><span>반려 사유 (재작성의 재료가 됩니다)</span><textarea id="sns-decision-note" rows="3" oninput="SNS_DECISION.note=this.value">${esc(d.note)}</textarea></label><button class="btn btn-ghost" onclick="snsDecide('${mid}','reject')" ${busy?'disabled':''}>반려 확정</button>`:''}
    ${notice}
  </section>`;
}
function snsPostDetail(r){
  if(!r)return '<aside class="sns-post-detail"><div class="sns-detail-placeholder">목록에서 글을 선택하면<br>내용과 발행 상태를 확인할 수 있습니다.</div></aside>';
  const issue=snsRecordIssue(r),reason=r.attempt_error||r.reason||(issue?'예약 시각을 확인해 주세요.':'');
  return `<aside class="sns-post-detail" data-record="${esc(r.id)}" aria-label="선택한 글 상세">
    <div class="sns-detail-top"><span>글 상세</span>${['pending','scheduled','cancelled'].includes(r.status)?`<button class="btn btn-ghost" data-id="${esc(r.id)}" onclick="snsCompose(this.dataset.id)">초안 수정</button>`:''}<button class="btn btn-ghost sns-agenda-back" onclick="snsCloseRecord()">목록으로</button></div>
    <div class="sns-post-context">${esc(r.brand)} · ${esc(r.channel)}</div>
    <h2 id="snsPostDetailTitle" tabindex="-1">${esc(r.title)}</h2>
    <p class="sns-post-account">${esc(r.account)}</p>
    ${snsBadge(snsRecordLabel(r),issue?'warning':r.status==='published'?'ok':'unknown')}
    <dl class="sns-post-facts"><div><dt>게시 예정</dt><dd>${r.scheduled_at?snsTime(r.scheduled_at):'시각 미정'}</dd></div><div><dt>준비</dt><dd>${snsTime(r.prepared_at)}</dd></div>${r.published_at?`<div><dt>발행 완료</dt><dd>${snsTime(r.published_at)}</dd></div>`:''}</dl>
    ${reason?`<div class="sns-action"><b>${esc(reason)}</b><br>${esc(r.attempt_action||r.action||'발행 경로에서 예약 시각 확인')}</div>`:''}
    <h3>${r.body?'본문':'본문 미리보기'}</h3><p class="sns-post-body">${esc(r.body||r.excerpt||'저장된 미리보기가 없습니다.')}</p>
    <p class="sns-meta">${r.body?'장부에 저장된 전문입니다.':'장부에 저장된 앞부분입니다.'}</p>
    ${snsPostImages(r)}
    ${snsPostVideo(r)}
    ${r.link_comment_status?`<p class="sns-meta">링크 댓글 · ${esc(({waiting:'본문 발행 후 자동 등록',sent:'게시 완료',blocked:'승인·계정·댓글 조회 권한 확인 필요',claimed:'전송 결과 확인 중 · 자동 재전송 중지',uncertain:'전송 결과 확인 필요 · 자동 재전송 중지'})[r.link_comment_status]||'확인 필요')}</p>`:''}
    ${snsPostDecision(r)}
    <div class="sns-post-links">${snsLink(r.url)}${r.status==='pending'?`<button class="btn ${r.mid?'btn-ghost':'btn-primary'}" onclick="A.go('inbox')">결재함에서 검토</button>`:''}</div>
    <p class="sns-post-evidence">${esc(r.evidence)}${r.local_status&&r.local_status!==r.status?' · 장부와 확인 상태 다름':''}</p>
  </aside>`;
}
function snsAgenda(rows, now, selected){
  const groups=new Map();
  for(const r of rows){const when=snsRecordTime(r),day=snsDay(when);if(!groups.has(day))groups.set(day,{when,rows:[]});groups.get(day).rows.push(r);}
  return [...groups.values()].map(g=>`<section class="sns-day-group"><h3 class="sns-day-heading">${snsDayLabel(g.when,now)}<span>${g.rows.length}건</span></h3>
    ${g.rows.map(r=>`<article class="sns-record sns-agenda-item"><button class="sns-agenda-row ${r.id===selected?.id?'selected':''}" id="sns-post-${esc(encodeURIComponent(r.id))}" data-record="${esc(r.id)}" onclick="snsSelectRecord(this.dataset.record)" aria-pressed="${r.id===selected?.id}">
      <span class="sns-agenda-time">${snsClock(snsRecordTime(r))}</span>
      <span class="sns-agenda-copy"><strong>${esc(r.title)}</strong><span>${esc(r.brand)} · ${esc(r.channel)} · ${esc(r.account)}</span></span>
      <span class="sns-agenda-state">${snsBadge(snsRecordLabel(r),snsRecordIssue(r)?'warning':r.status==='published'?'ok':'unknown')}</span>
    </button></article>`).join('')}</section>`).join('');
}
function screenSnsOperations(){
  const d = SNS_OPS.data;
  if (!d && !SNS_OPS.busy && !SNS_OPS.error) setTimeout(loadSnsOperations, 0);
  const head = `<div class="sns-head"><div><div class="sns-eyebrow">ILSON · SNS</div><h1>SNS 운영</h1><p>게시 일정과 처리할 일을 한눈에 확인하세요.</p></div>
    <div class="sns-head-actions"><button class="btn btn-ghost" onclick="snsCompose()">새 초안</button><button class="btn btn-ghost" onclick="A.go('sns-accounts')">계정 관리 →</button><button class="btn btn-primary" onclick="loadSnsOperations()" ${SNS_OPS.busy?'disabled':''}>${SNS_OPS.busy?'확인 중…':'새로 확인'}</button></div></div>`;
  if(!d)return `<div class="sns-ops sns-workspace">${head}<div class="sns-panel" role="status">${esc(SNS_OPS.error||'발행 장부를 확인하고 있습니다…')}</div></div>`;
  const all=snsRecords(d),accounts=snsAccounts(d,false),selectedAccount=d.accounts.find(a=>snsAccountKey(a)===SNS_OPS.account);
  const variants=[['scheduled','게시 예정'],['pending','승인 대기'],['attention','처리 필요'],['published','발행 기록'],['all','전체']];
  const counts=Object.fromEntries(variants.map(([v])=>[v,all.filter(r=>snsRecordMatches(r,v)).length]));
  const rows=SNS_OPS.view==='scheduled'?snsScheduledRecords(all):all.filter(r=>snsRecordMatches(r,SNS_OPS.view));
  const size=20,page=Math.min(SNS_OPS.page,Math.max(0,Math.ceil(rows.length/size)-1)),shown=rows.slice(page*size,(page+1)*size);
  // 승인·반려 후 목록 상태가 바뀌어도 검토한 글과 결과 안내를 유지한다.
  // 필터/페이지/목록 이동은 기존 함수들이 record를 명시적으로 비운다.
  const selected=all.find(r=>r.id===SNS_OPS.record)||shown[0];
  const errors=d.sources.filter(s=>s.status!=='ok');
  const brandOptions=[...new Set([...d.accounts.flatMap(snsBrands),...d.records.map(r=>r.brand)])].sort();
  const options=(values,current)=>[...new Set(values)].sort().map(v=>`<option value="${esc(v)}" ${v===current?'selected':''}>${esc(v)}</option>`).join('');
  return `<div class="sns-ops sns-workspace">${head}
    ${snsWeekly(d)}
    ${errors.length?`<div class="sns-notice" role="alert"><b>일부 자료를 확인하지 못했습니다.</b> 조회된 기록만 표시합니다.<br>${errors.map(s=>esc(s.name)+' — '+esc(s.message||'조회 미완료')).join('<br>')}</div>`:''}
    <div class="sns-summary" aria-label="SNS 운영 요약">
      ${[['scheduled','게시 예정','다가오는 발행 일정'],['pending','승인 대기','검토 후 발행할 글'],['attention','처리 필요','지연·실패·시각 확인']].map(([v,label,help])=>`<button class="sns-summary-item ${SNS_OPS.view===v?'active':''}" aria-pressed="${SNS_OPS.view===v}" onclick="snsSetFilter('view','${v}')"><span>${label}</span><strong>${counts[v]}<small>건</small></strong><span class="sns-summary-help">${help}</span></button>`).join('')}
      <button class="sns-summary-item" onclick="A.go('sns-accounts')"><span>관리 계정</span><strong>${accounts.length}<small>개</small></strong><span class="sns-summary-help">연결·사업부 관리 →</span></button>
    </div>
    <section class="sns-agenda-panel" id="snsRecordsPanel" aria-label="게시 예정 및 발행 기록">
      ${SNS_OPS.weeklyIds?`<div class="sns-active-account" role="status">선택한 인디케이터의 회차 ${all.length}건 · 사업부·SNS·검색에 반영됨<button class="btn btn-ghost" onclick="snsClearFilters()">전체 콘텐츠 보기</button></div>`:''}
      <div class="sns-agenda-toolbar"><div class="sns-views" role="group" aria-label="발행 상태 필터">${variants.map(([v,label])=>`<button class="sns-view-tab ${SNS_OPS.view===v?'active':''}" aria-pressed="${SNS_OPS.view===v}" onclick="snsSetFilter('view','${v}')">${label}<span>${counts[v]}</span></button>`).join('')}</div></div>
      <div class="sns-filters"><label>사업부<select id="snsBrand" onchange="snsSetFilter('brand',this.value)"><option value="">전체 사업부</option>${options(brandOptions,SNS_OPS.brand)}</select></label>
        <label>SNS<select id="snsChannel" onchange="snsSetFilter('channel',this.value)"><option value="">전체 SNS</option>${options([...d.records,...d.accounts].map(r=>r.channel),SNS_OPS.channel)}</select></label>
        ${SNS_OPS.weeklyIds&&SNS_WEEK.selected?`<label style="max-width:220px">선택 회차<select style="width:100%;min-width:0" aria-label="인디케이터 콘텐츠 회차" onchange="snsWeekConnect(this.value)">${(d.weekly?.rows[SNS_WEEK.selected[0]]?.cells[SNS_WEEK.selected[1]]?.items||[]).filter(i=>i.id&&d.records.some(r=>r.id===i.id)).map(i=>`<option value="${esc(i.id)}" ${i.id===SNS_OPS.record?'selected':''}>${esc(i.label+' · '+i.title)}</option>`).join('')}</select></label>`:''}
        <label class="sns-search">검색<input id="snsQuery" type="search" value="${esc(SNS_OPS.query)}" placeholder="제목, 계정, 사업부 검색" onchange="snsSetFilter('query',this.value)"></label>
        <button class="btn btn-ghost sns-filter-reset" onclick="snsClearFilters()">초기화</button>
      </div>
      ${selectedAccount?`<div class="sns-active-account">${esc(selectedAccount.channel)} · ${esc(selectedAccount.account)}<button class="btn btn-ghost" onclick="snsClearFilters()">전체 계정 보기</button></div>`:''}
      <div class="sns-list-caption"><span>${variants.find(([v])=>v===SNS_OPS.view)?.[1]||'기록'} ${rows.length}건${SNS_OPS.view==='scheduled'?' · 가까운 일정순':''} · 한국 시간</span><span>${SNS_OPS.busy?'새 자료 확인 중':snsTime(d.generated_at)+' 확인'}</span></div>
      <div class="sns-agenda-workspace ${SNS_OPS.record&&selected?.id===SNS_OPS.record?'has-selection':''}">
        <div class="sns-agenda-main"><div class="sns-records">${snsAgenda(shown,d.generated_at,selected)||`<div class="sns-empty">${errors.length?'조회된 자료에는 해당 글이 없습니다. 미확인 자료를 점검해 주세요.':'이 조건에 맞는 글이 없습니다.'}</div>`}</div>
          <div class="sns-pagination"><button class="btn btn-ghost" onclick="snsPage(-1)" ${page===0?'disabled':''}>이전</button><span>${page+1} / ${Math.max(1,Math.ceil(rows.length/size))}</span><button class="btn btn-ghost" onclick="snsPage(1)" ${(page+1)*size>=rows.length?'disabled':''}>다음</button></div>
        </div>${snsPostDetail(selected)}
      </div>
    </section>
    <details class="sns-data-notes"><summary>자료 출처와 조회 안내</summary><p>아래 기록 목록 수치는 현재 필터 기준입니다. 예약 지연·시각 미정·발행 오류는 처리 필요에서 확인하세요. 동일 글로 확인되지 않은 기록은 각각 표시합니다. 서버 조회 범위는 ${esc(d.query_range?.start||'미확인')} ~ ${esc(d.query_range?.end||'미확인')}이며 60초마다 갱신합니다.</p>${d.sources.map(s=>`<p>${esc(s.name)} — ${s.status==='ok'?'조회됨':'확인 필요'} · ${snsTime(s.checked_at)}</p>`).join('')}</details>
  </div>`;
}

function snsReadinessPanel(channel=''){
  const d=SNS_OPS.readiness,rows=Array.isArray(d?.accounts)?d.accounts.filter(r=>!channel||r.channel===channel):[];
  const labels={ok:'점검 통과',warning:'확인 필요',error:'게시 차단',unknown:'확인 불가'};
  const symbols={ok:'●',warning:'▲',error:'■',unknown:'?'};
  const counts=Object.fromEntries(Object.keys(labels).map(s=>[s,rows.filter(r=>r.state===s).length]));
  return `<section id="sns-readiness-detail" class="sns-panel sns-readiness" tabindex="-1" aria-label="${esc(channel||'전 채널')} 게시 준비 상태">
    <div class="sns-readiness-head"><div><h2>${esc(channel)} 게시 준비 상태</h2><p class="sns-meta">현재 전체 계정 기준 · 저장된 인증·관측 결과 · 실제 게시 성공은 별도 확인</p></div>
      <span class="sns-meta">${d?.checked_at?'마지막 점검 '+snsTime(d.checked_at):'점검 기록 없음'}${d?.next_check_at&&!d.stale?'<br>다음 점검 예정 '+snsTime(d.next_check_at):''}</span></div>
    <p class="sns-readiness-counts">${Object.entries(labels).map(([s,label])=>`<span class="sns-readiness-badge ${s}">${symbols[s]} ${label} ${counts[s]}개</span>`).join('')}</p>
    <p class="sns-meta">회색은 점검 근거가 부족한 상태입니다. 각 계정을 펼치면 확인된 항목과 미확인 항목을 볼 수 있습니다.</p>
    ${!d||d.stale?`<p role="status">${esc(d?.message||'점검 결과를 조회하지 못했습니다.')}</p>`:''}
    <div class="sns-readiness-grid">${rows.map((r,index)=>{
      const state=labels[r.state]?r.state:'unknown';
      const problem=(r.checks||[]).find(c=>c.state==='error')||(r.checks||[]).find(c=>c.state==='warning')||(r.checks||[]).find(c=>c.state==='unknown');
      return `<details id="sns-readiness-account-${index}" class="sns-readiness-card ${state}"><summary><span class="sns-readiness-badge ${state}">${symbols[state]} ${labels[state]}</span><strong>${esc(r.channel)} · ${esc(r.display_name||r.account)}</strong><span class="sns-meta">${esc((r.brands||[]).join(' · '))}</span></summary>
        ${problem?'<p>'+esc(problem.detail)+'</p>':''}
        <p class="sns-meta">최근 실제 발행 성공: ${r.last_published_at?snsTime(r.last_published_at):'성공 근거 미확인'}</p>
        ${(r.checks||[]).map(c=>`<p><b>${esc(c.name)}</b> · ${esc(labels[c.state]||labels.unknown)}<br>${esc(c.detail)}${c.action?'<br><span class="sns-meta">조치: '+esc(c.action)+'</span>':''}</p>`).join('')}</details>`;
    }).join('')||'<p class="sns-meta">채널 목록과 점검 결과가 준비되면 표시됩니다.</p>'}</div>
  </section>`;
}

const SNS_WEEK = {week:'', selected:null, closed:new Set(), brand:'', market:'', grouping:'platform'};

function snsSourceReadiness(row){
  const data=SNS_OPS.readiness,all=data?.accounts||[];
  const platform=row.platform||all.find(a=>a.channel===row.channel)?.platform||'';
  const account=snsCanonicalAccount(platform,row.account);
  const accounts=all.filter(a=>a.platform===platform&&(row.readinessUnassigned?!a.account&&a.display_name===row.display_name:row.identity_pending?a.identity_pending&&a.platform==='youtube':account&&snsCanonicalAccount(platform,a.account)===account));
  const order=['error','unknown','warning','ok'];
  const state=!data||data.stale||!accounts.length?'unknown':order.find(s=>accounts.some(a=>a.state===s))||'unknown';
  const labels={error:'게시 차단',unknown:'확인 불가',warning:'확인 필요',ok:'점검 통과'};
  return {state,label:data?.stale?'점검 지연':labels[state],accounts,
    key:JSON.stringify([row.brand,row.channel,account||row.display_name]),checked_at:data?.checked_at||''};
}
function snsSourceOrphans(channel){
  return (SNS_OPS.readiness?.accounts||[]).filter(a=>a.channel===channel&&a.identity_pending&&!a.account)
    .map(a=>({platform:a.platform,channel:a.channel,account:'',display_name:a.display_name,brand:'미분류',readinessUnassigned:true}));
}
function snsSourceSignal(row){
  const health=snsSourceReadiness(row);
  return `<button type="button" class="sns-source-signal sns-readiness-badge ${health.state}" data-source="${esc(health.key)}" onclick="snsSourceReadinessOpen(this.dataset.source)" aria-expanded="${SNS_OPS.readinessSource===health.key}" aria-label="${esc(row.brand+' '+row.channel+' '+(row.display_name||row.account)+' 현재 게시 준비: '+health.label)}" title="${esc(health.label)} · 현재 계정의 게시 준비 상태${health.checked_at?' · '+esc(snsTime(health.checked_at))+' 점검':''}"><span class="sns-source-dot" aria-hidden="true"></span></button>`;
}
function snsSourceReadinessOpen(key){
  SNS_OPS.readinessSource=SNS_OPS.readinessSource===key?'':key;
  render();
  if(SNS_OPS.readinessSource){const panel=document.getElementById('sns-source-readiness-detail');panel?.scrollIntoView({block:'nearest'});panel?.focus({preventScroll:true});}
}
function snsSourceDetails(row){
  const health=snsSourceReadiness(row),labels={ok:'점검 통과',warning:'확인 필요',error:'게시 차단',unknown:'확인 불가'};
  return `<section id="sns-source-readiness-detail" class="sns-source-detail" tabindex="-1" aria-label="${esc(row.brand+' '+row.channel+' '+(row.display_name||row.account))} 점검 상세"><h4>${esc(health.label)} · 현재 게시 준비 상태</h4><p>인증·관측 기록 · ${health.checked_at?snsTime(health.checked_at)+' 확인':'점검 기록 없음'} · 실제 발행 성공은 별도 확인</p>
    ${SNS_OPS.readiness?.stale?'<p>이전 관측 · 현재 상태 확인 필요</p>':''}
    ${health.accounts.map(a=>`<p>최근 실제 발행 성공: ${a.last_published_at?snsTime(a.last_published_at):'성공 근거 미확인'}</p>${(a.checks||[]).map(c=>`<p><b>${esc(c.name)} · ${esc(SNS_OPS.readiness?.stale?'확인 불가':labels[c.state]||labels.unknown)}</b><br>${esc(c.detail)}${c.action?'<br>조치: '+esc(c.action):''}</p>`).join('')}`).join('')||'<p>이 계정과 일치하는 점검 자료가 없습니다. 계정 연결·점검 대상을 확인해 주세요.</p>'}</section>`;
}
async function snsWeekMove(delta){
  if(SNS_OPS.busy)return;
  if(delta===0)SNS_WEEK.week='';
  else {
    const date=new Date((SNS_OPS.data?.weekly?.start||snsDay(new Date().toISOString()))+'T00:00:00+09:00');
    date.setUTCDate(date.getUTCDate()+delta*7);
    SNS_WEEK.week=snsDay(date.toISOString());
  }
  SNS_WEEK.selected=null;SNS_OPS.weeklyIds=null;SNS_OPS.record='';
  await loadSnsOperations();
  document.getElementById('sns-week-move-'+delta)?.focus();
}
function snsWeekClose(){const selected=SNS_WEEK.selected;SNS_WEEK.selected=null;render();if(selected)document.getElementById('sns-cell-'+selected.join('-'))?.focus();}
function snsWeekConnect(id,overview=false){
  const selected=SNS_WEEK.selected,cell=selected?SNS_OPS.data?.weekly?.rows[selected[0]]?.cells[selected[1]]:null;
  const ids=(cell?.items||[]).map(i=>i.id).filter(key=>key&&(SNS_OPS.data?.records||[]).some(r=>r.id===key));
  if(!ids.includes(id))return;
  const record=SNS_OPS.data.records.find(r=>r.id===id);
  const filters={snsQuery:overview?'':record.title||'',snsBrand:record.brand||'',snsChannel:record.channel||''};
  // 상위 render의 입력 복원이 이전 필터 값을 되살리지 않도록 DOM도 먼저 동기화한다.
  for(const [key,value] of Object.entries(filters)){const input=document.getElementById(key);if(input)input.value=value;}
  Object.assign(SNS_OPS,{weeklyIds:overview?ids:[id],record:id,view:'all',page:0,brand:record.brand||'',channel:record.channel||'',health:'',account:snsAccountKey(record),query:filters.snsQuery});
  SNS_OPS.page=Math.max(0,Math.floor(snsRecords(SNS_OPS.data).findIndex(r=>r.id===id)/20));
  render();
  const target=document.getElementById(overview?'sns-week-detail':'snsRecordsPanel');
  target?.scrollIntoView({block:'start'});
  document.getElementById(overview?'sns-week-detail':'snsPostDetailTitle')?.focus({preventScroll:true});
}
function snsWeekSelect(row,day){
  SNS_WEEK.selected=[row,day];
  const items=SNS_OPS.data?.weekly?.rows[row]?.cells[day]?.items||[];
  const connected=items.filter(i=>i.id&&(SNS_OPS.data?.records||[]).some(r=>r.id===i.id));
  const first=connected.find(i=>['failed','attention','unknown'].includes(i.state))||connected[0];
  if(first){snsWeekConnect(first.id,true);return;}
  SNS_OPS.weeklyIds=null;SNS_OPS.record='';
  render();document.getElementById('sns-week-detail')?.focus();
}
function snsWeekToggle(index,focusId){
  SNS_WEEK.closed.has(index)?SNS_WEEK.closed.delete(index):SNS_WEEK.closed.add(index);render();if(focusId)document.getElementById(focusId)?.focus();
}
function snsWeekFilter(key,value){SNS_WEEK[key]=value;SNS_WEEK.selected=null;render();document.getElementById('sns-week-'+key)?.focus();}
function snsWeekGroups(rows,visible){
  const platforms=['Instagram','Threads','Facebook','YouTube','X','네이버 블로그','LinkedIn','Qiita','Zenn'];
  const kinds=['일반 글','카드뉴스','영상','웹툰','정기 콘텐츠 미확인'];
  const rank=(values,value)=>values.includes(value)?values.indexOf(value):values.length;
  const entries=rows.map((r,ri)=>({r,ri})).filter(({r})=>visible(r));
  entries.sort((a,b)=>rank(platforms,a.r.channel)-rank(platforms,b.r.channel)||a.r.brand.localeCompare(b.r.brand,'ko')||a.r.account.localeCompare(b.r.account)||rank(kinds,a.r.kind)-rank(kinds,b.r.kind)||a.r.kind.localeCompare(b.r.kind,'ko'));
  const cards=new Map();
  for(const entry of entries){const title=SNS_WEEK.grouping==='brand'?entry.r.brand:entry.r.channel;if(!cards.has(title))cards.set(title,[]);cards.get(title).push(entry);}
  return [...cards.entries()];
}
function snsWeekDetails(row,cell,d){
  const states={failed:['×','실패'],attention:['!','지연·확인 필요'],unknown:['?','조회 불가'],scheduled:['◷','예약'],rejected:['−','직접 반려'],done:['✓','완료'],none:['—','예정 없음']};
  const order=Object.keys(states),items=[...cell.items].sort((a,b)=>order.indexOf(a.state)-order.indexOf(b.state));
  const counts=order.map(state=>({state,n:items.filter(i=>i.state===state).length})).filter(x=>x.n);
  return `<section id="sns-week-detail" class="sns-week-detail" tabindex="-1" aria-label="선택한 일정 상세">
    <button class="btn btn-ghost sns-week-close" onclick="snsWeekClose()">상세 닫기</button>
    <h3>${esc(row.brand)} · ${esc(row.channel)} · ${esc(row.kind)} · ${esc(cell.day)}</h3>
    <div class="sns-cell-summary"><strong>${cell.done}/${cell.total} 발행 완료</strong>${counts.map(({state,n})=>`<span class="sns-item-status ${state}">${states[state][0]} ${states[state][1]} ${n}건</span>`).join('')}</div>
    ${cell.schedule_known?'':'<p class="sns-meta">조회된 콘텐츠와 확인된 슬롯 기준 · 전체 정기 일정 미확인</p>'}
    <div class="sns-cell-items">${items.map(i=>{
      const state=states[i.state]||states.unknown,connected=i.id&&(d.records||[]).some(r=>r.id===i.id);
      return `<article class="sns-cell-item"><span class="sns-item-status ${esc(i.state)}">${state[0]} ${esc((i.label||state[1]).replace(/^[✓×!◷?—−]\s*/,''))}</span><div><b>${esc(i.title)}</b>
        <p>${i.state==='done'?'발행 '+snsTime(i.published_at):'예정 '+snsTime(i.scheduled_at)}</p>
        ${i.reason?`<p class="sns-cell-reason">${esc(i.reason)}</p>`:''}
        ${snsLink(i.url)}${connected?`<button class="btn btn-ghost" data-record="${esc(i.id)}" onclick="snsWeekConnect(this.dataset.record)">이 콘텐츠 보기 ↓</button>`:'<p>예정 슬롯만 확인됨 · 연결된 콘텐츠 없음</p>'}
        ${i.evidence?`<details><summary>판정 근거</summary><p>${esc(i.evidence)}</p></details>`:''}</div></article>`;
    }).join('')||'<p>조회된 콘텐츠 기록 없음</p>'}</div></section>`;
}
function snsWeekly(d){
  const w=d.weekly;
  if(!w)return '';
  const brands=[...new Set(w.rows.map(r=>r.brand))];
  const visible=r=>(!SNS_WEEK.brand||r.brand===SNS_WEEK.brand)&&(!SNS_WEEK.market||r.market===SNS_WEEK.market);
  const markets=[...new Set(w.rows.map(r=>r.market||'언어·시장 확인 필요'))];
  const today=snsDay(d.generated_at),current=w.start<=today&&today<=w.end;
  const issues=w.issues.filter(i=>i.day<=today&&w.rows.some(r=>visible(r)&&r.brand===i.brand&&r.channel===i.channel&&r.account===i.account));
  const unavailable=w.rows.filter(r=>visible(r)&&r.cells.some(c=>c.state==='unknown')).length;
  const items=w.rows.filter(visible).flatMap(r=>r.cells.flatMap(c=>c.items));
  const totals={done:items.filter(i=>i.state==='done').length,failed:items.filter(i=>i.state==='failed').length,delayed:items.filter(i=>i.state==='attention'&&i.attention_kind==='delayed').length,approval:items.filter(i=>i.state==='attention'&&i.attention_kind==='approval').length};
  const notices=(w.operation_notices||[]).filter(n=>!SNS_WEEK.brand||!n.brand||n.brand===SNS_WEEK.brand);
  const selected=SNS_WEEK.selected, row=selected?w.rows[selected[0]]:null,cell=row?.cells[selected[1]];
  const details=cell?snsWeekDetails(row,cell,d):'<div id="sns-week-detail" hidden></div>';
  const symbols={done:'✓',failed:'×',attention:'!',scheduled:'◷',none:'—',unknown:'?'};
  const names={done:'완료',failed:'실패',attention:'지연·확인 필요',scheduled:'예약',none:'예정 없음',unknown:'조회 불가'};
  return `<section class="sns-weekly sns-panel" aria-label="SNS 주간 발행 현황">
    <div class="sns-week-heading"><div><h2>SNS 주간 발행 현황</h2><p>${esc(w.start)} ~ ${esc(w.end)} · KST</p></div><nav aria-label="주 이동"><button class="btn btn-ghost" id="sns-week-move--1" onclick="snsWeekMove(-1)" ${SNS_OPS.busy?'disabled':''}>이전 주</button><button class="btn btn-ghost" id="sns-week-move-0" onclick="snsWeekMove(0)" ${SNS_OPS.busy?'disabled':''}>이번 주</button><button class="btn btn-ghost" id="sns-week-move-1" onclick="snsWeekMove(1)" ${SNS_OPS.busy?'disabled':''}>다음 주</button></nav></div>
    <div class="sns-filters"><label>보기<select id="sns-week-grouping" onchange="snsWeekFilter('grouping',this.value)"><option value="platform" ${SNS_WEEK.grouping==='platform'?'selected':''}>플랫폼별</option><option value="brand" ${SNS_WEEK.grouping==='brand'?'selected':''}>사업부별</option></select></label><label>사업부<select id="sns-week-brand" onchange="snsWeekFilter('brand',this.value)"><option value="">전체 사업부</option>${brands.map(b=>`<option ${b===SNS_WEEK.brand?'selected':''}>${esc(b)}</option>`).join('')}</select></label><label>언어·시장<select id="sns-week-market" onchange="snsWeekFilter('market',this.value)"><option value="">전체 언어·시장</option>${markets.map(m=>`<option ${m===SNS_WEEK.market?'selected':''}>${esc(m)}</option>`).join('')}</select></label></div>
    <div class="sns-week-pulse" aria-label="선택 주 발행 결과">${[['done','성공 발행','확인된 게시 결과'],['failed','발행 실패','개별 상세 확인'],['delayed','승인 후 지연','발행 확인이 없는 건'],['approval','승인 대기','검토가 필요한 건']].map(([key,label,help])=>`<div class="${key}"><span>${label}</span><strong>${totals[key]}<small>건</small></strong><p>${help}</p></div>`).join('')}</div>
    ${notices.length?`<details class="sns-week-notices"><summary>현재 운영 안내 <span>${notices.length}</span> · 중지·실행 이력</summary><p>현재 상태 기준 · 위 수치는 선택한 주 기준입니다. 언어·시장 필터와 별개로 사업부 운영 안내를 표시합니다.</p>${notices.map(n=>`<p><b>${n.kind==='paused'?'Ⅱ 운영 중지':'? 확인 필요'} · ${esc(n.title)}</b><br>${esc(n.detail)}</p>`).join('')}</details>`:''}
    <div class="sns-week-alert" role="status"><strong>${current?'오늘 확인할 것':'선택 주의 확인할 것'} ${issues.length}건</strong> · 일정·자료 확인 불가 ${unavailable}행${w.complete?'':' · 조회 미완료'}</div>
    <div class="sns-week-legend" aria-label="상태 범례">${Object.keys(symbols).map(state=>`<span><i class="${state}" aria-hidden="true">${symbols[state]}</i>${names[state]}</span>`).join('')}</div>
    <div class="sns-week-cards">${snsWeekGroups(w.rows,visible).map(([brand,entries],bi)=>{
      const groups=new Map();for(const entry of entries){const r=entry.r,key=JSON.stringify([r.brand,r.channel,r.account,r.display_name]);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(entry);}
      const orphans=SNS_WEEK.grouping==='platform'?snsSourceOrphans(brand):[];
      return `<section class="sns-week-card" aria-labelledby="sns-week-card-${bi}"><header><div class="sns-week-title"><h3 id="sns-week-card-${bi}">${esc(brand)}</h3></div><span>${groups.size}개 계정${orphans.length?' · 계정 미지정 '+orphans.length:''}</span></header><div class="sns-week-scroll" role="region" aria-label="${esc(brand)} 주간 현황" tabindex="0"><table class="sns-week-table"><thead><tr><th scope="col">${SNS_WEEK.grouping==='platform'?'사업부 · 콘텐츠':'채널 · 콘텐츠'}</th>${w.days.map((day,i)=>`<th scope="col" ${day===today?'aria-current="date"':''}>${['월','화','수','목','금','토','일'][i]}<small>${Number(day.slice(-2))}</small></th>`).join('')}</tr></thead>${[...groups.values()].map(entries=>{
        const r=entries[0].r,health=snsSourceReadiness(r),key=JSON.stringify([r.brand,r.channel,r.account]),closed=SNS_WEEK.closed.has(key),id='sns-account-'+entries[0].ri;
        return `<tbody class="sns-source-box"><tr class="sns-week-account source-${health.state}"><th colspan="8"><div class="sns-source-heading">${snsSourceSignal(r)}<button class="sns-source-toggle" id="${id}" data-key="${esc(key)}" onclick="snsWeekToggle(this.dataset.key,this.id)" aria-expanded="${!closed}">${closed?'▸':'▾'} ${esc(SNS_WEEK.grouping==='platform'?r.brand:r.channel)} · ${esc(r.display_name||r.account)}<small>${esc(r.market||'언어·시장 확인 필요')}${r.identity_pending?' · 계정 확인 필요':r.account&&r.account!==r.display_name?' · '+esc(r.account):''}</small></button></div></th></tr>${SNS_OPS.readinessSource===health.key?'<tr><td colspan="8">'+snsSourceDetails(r)+'</td></tr>':''}${closed?'':entries.map(({r,ri})=>`<tr><th scope="row">${esc(r.kind)}${r.schedule_known||r.kind==='정기 콘텐츠 미확인'?'':'<small class="sns-week-schedule-note">일정 미확인</small>'}</th>${r.cells.map((c,ci)=>`<td class="${c.day===today?'sns-week-today':''}"><button id="sns-cell-${ri}-${ci}" class="sns-week-cell ${c.state}" onclick="snsWeekSelect(${ri},${ci})" aria-pressed="${selected?.[0]===ri&&selected?.[1]===ci}" aria-controls="sns-week-detail" aria-label="${esc(r.brand+' '+r.channel+' '+r.account+' '+r.kind+' '+c.day+' '+names[c.state]+(c.total?' · '+c.total+'건 중 '+c.done+'건 완료':'')+(c.rejected?' · 직접 반려 '+c.rejected+'건':''))}"><span aria-hidden="true">${symbols[c.state]}</span>${c.total>0?`<small aria-hidden="true">${c.done}/${c.total}</small>`:''}</button></td>`).join('')}</tr>`).join('')}</tbody><tbody class="sns-source-gap" aria-hidden="true"><tr><td colspan="8"></td></tr></tbody>`;
      }).join('')}${orphans.map(r=>{const health=snsSourceReadiness(r);return `<tbody class="sns-source-box"><tr class="sns-week-account source-${health.state}"><th colspan="8"><div class="sns-source-heading">${snsSourceSignal(r)}<span class="sns-source-toggle">${esc(r.display_name)}</span></div></th></tr>${SNS_OPS.readinessSource===health.key?'<tr><td colspan="8">'+snsSourceDetails(r)+'</td></tr>':''}</tbody><tbody class="sns-source-gap" aria-hidden="true"><tr><td colspan="8"></td></tr></tbody>`;}).join('')}</table></div></section>`;
    }).join('')}</div>${!w.rows.some(visible)?'<p class="sns-empty">이 조건에 맞는 계정이 없습니다.</p>':''}${details}
    <p class="sns-meta">예정 시각 ${w.grace_minutes}분 초과 후 누락 확인 · 완료/전체는 조회된 콘텐츠와 확인된 예정 슬롯 기준입니다. 일정 미확인 행은 전체 예정이 확정되지 않았습니다. 완료는 성공 발행 기록 기준이며 온라인 재조회와 다릅니다.</p>
    <p class="sns-meta">마지막 확인 ${snsTime(w.checked_at)} · 조회 범위 ${esc(d.query_range?.start||w.start)} ~ ${esc(d.query_range?.end||w.end)}</p>
    <details><summary>일정 판정 범위</summary>${w.notes.map(n=>`<p>${esc(n)}</p>`).join('')}</details>
  </section>`;
}

setInterval(() => { if (['sns','sns-accounts'].includes(S.tab) && !document.hidden && !typing()) loadSnsOperations(); }, 60000);
