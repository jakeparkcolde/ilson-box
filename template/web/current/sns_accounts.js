/* 계정 연결 전용 화면. 연결·분류만 바꾸며 발행 대상 설정은 바꾸지 않는다. */
const SNS_ACCOUNTS = {brand:'',platform:'',route:'',status:'all',query:'',selected:'',mobileStep:'brands',historyOpen:false,form:null,saving:false,message:''};
let snsEditorSequence=0;
const SNS_PLATFORMS = {instagram:'Instagram',threads:'Threads',facebook:'Facebook',x:'X',naverblog:'네이버 블로그',linkedin:'LinkedIn',qiita:'Qiita',zenn:'Zenn',youtube:'YouTube'};
const snsDirectoryKey = (pf,account)=>pf+':'+snsCanonicalAccount(pf,account);

function snsDirectory(){
  const rows=new Map();
  for(const a of SNS_OPS.rawAccounts||[]){
    if(a.identity_pending)continue; // 식별자 없는 관리 대상은 주간 목록에서 확인하며 가짜 계정을 등록하지 않는다.
    const key=snsDirectoryKey(a.platform,a.account);
    const account=snsCanonicalAccount(a.platform,a.account);
    if(rows.has(key)&&account!==a.account)continue; // 실제 등록 계정의 인증 근거를 별칭 행으로 덮지 않는다.
    rows.set(key,{key,platform:a.platform,account,brands:snsBrands(a),legacy:{...a},native:null});
  }
  const box=SNS_OPS.box;
  if(box?.binding==='matched'){
    for(const a of box.accounts){
      const key=snsDirectoryKey(a.platform,a.username);
      if(!rows.has(key))rows.set(key,{key,platform:a.platform,account:a.username,brands:['미분류'],legacy:null});
      rows.get(key).native=a;
    }
    for(const [key,m] of Object.entries(box.registry||{})){
      if(!rows.has(key))rows.set(key,{key,platform:m.platform,account:m.account,brands:['미분류'],native:null,legacy:null});
      const row=rows.get(key); row.meta=m;
      if(Array.isArray(m.brands))row.brands=m.brands.length?m.brands:['미분류'];
    }
  }
  return [...rows.values()].map(r=>{
    r.meta=r.meta||{};
    r.archived=r.meta.management_status==='archived';
    r.internalUnknown=box?.binding!=='matched';
    // 2026-09-23: 기존 도구 오류로 정상 인증 계정까지 재연결 대상으로 세지 않는다.
    // 내부 지원 SNS의 미연결·조회 미완료는 확인 필요, 기존 전용 SNS는 기존 상태로 판정.
    r.legacyIssue=['error','warning'].includes(r.legacy?.state);
    r.needsAttention=r.native?snsHealth(r.native)[0]!=='ok':(['instagram','threads'].includes(r.platform)||r.legacyIssue);
    r.transitionPending=!!r.native&&snsHealth(r.native)[0]==='ok'&&!r.native.publishing;
    r.expiry=snsExpiry(r.native);
    r.expiring=!!r.expiry?.attention;
    return r;
  }).sort((a,b)=>a.brands[0].localeCompare(b.brands[0],'ko')||a.account.localeCompare(b.account)||a.platform.localeCompare(b.platform));
}

// 만료 D-day — 판정(7일=곧 만료)은 맥미니 금고가 내리고(state), 여기서는 남은 날만 센다.
// 2026-09-24 Jake: 만료가 접힌 이력 안에만 있어 gitbap_com 10/10 만료를 보고서에서야 알았다.
function snsExpiry(n,now=Date.now()){
  const t=Date.parse(n?.expires_at);if(!n||!Number.isFinite(t))return null;
  const days=Math.ceil((t-now)/86400000),urgent=n.state==='expired'||days<=0,soon=n.state==='stale';
  return {days,state:urgent?'error':soon?'warning':'ok',label:urgent?'인증 만료':soon?`만료 D-${days} · 갱신 필요`:`만료 D-${days}`,attention:urgent||soon};
}
function snsAccountFilter(key,value){
  SNS_ACCOUNTS[key]=value;
  SNS_ACCOUNTS.selected='';SNS_ACCOUNTS.historyOpen=false;
  SNS_ACCOUNTS.mobileStep='list';
  render();
  if(key==='brand'||key==='status')snsAccountScrollStep();
}
function snsSelectAccount(key){
  SNS_ACCOUNTS.selected=key;SNS_ACCOUNTS.mobileStep='detail';SNS_ACCOUNTS.historyOpen=false;render();snsAccountScrollStep();
  document.getElementById('sns-detail-title')?.focus({preventScroll:true});
}
function snsAccountScrollStep(){
  if(typeof window!=='undefined'&&window.matchMedia('(max-width:1200px)').matches)
    document.getElementById('sns-account-workspace')?.scrollIntoView({block:'start'});
}
function snsAccountStep(step){SNS_ACCOUNTS.mobileStep=step;render();snsAccountScrollStep();}
function snsAccountHistory(open){SNS_ACCOUNTS.historyOpen=open;}
const snsEncodedKey=value=>encodeURIComponent(value).replace(/'/g,'%27');
function snsAccountReset(){for(const id of ['sns-directory-search','sns-directory-platform']){const input=document.getElementById(id);if(input)input.value='';}Object.assign(SNS_ACCOUNTS,{brand:'',platform:'',route:'',status:'all',query:'',selected:'',mobileStep:'list',historyOpen:false});render();}
function snsDirectoryFiltered(rows){
  const f=SNS_ACCOUNTS,q=f.query.trim().toLowerCase();
  return rows.filter(r=>(f.status==='archived'?r.archived:!r.archived)&&(!f.route||snsAccountRoute(r).key===f.route)&&(!f.brand||r.brands.includes(f.brand))&&(!f.platform||r.platform===f.platform)
    &&(f.status==='all'||f.status==='archived'||f.status==='internal'&&r.native||f.status==='attention'&&r.needsAttention||f.status==='unknown'&&snsAccountConnection(r)[0]==='unknown'||f.status==='transition'&&r.transitionPending||f.status==='expiring'&&r.expiring||f.status==='unclassified'&&r.brands.includes('미분류'))
    &&(!q||[r.account,r.meta.display_name,r.meta.owner,...r.brands].join(' ').toLowerCase().includes(q)));
}
function snsOpenAccount(key=''){
  const row=snsDirectory().find(r=>r.key===key);
  SNS_ACCOUNTS.form=row?{key,platform:row.platform,account:row.account,page_id:row.meta.page_id||row.legacy?.page_id||'',display_name:row.meta.display_name||'',brands:row.brands.filter(b=>b!=='미분류').join(', '),owner:row.meta.owner||'',management_status:row.meta.management_status||'active'}
    :{key:'',platform:'instagram',account:'',display_name:'',brands:'',owner:'',management_status:'active'};
  if(row)SNS_ACCOUNTS.selected=row.key;
  SNS_ACCOUNTS.form.formId='sns-editor-'+(++snsEditorSequence);
  snsConnectMessage='';snsConnectUrl='';SNS_ACCOUNTS.message='';render();
  document.getElementById('sns-account-form')?.scrollIntoView({behavior:'smooth',block:'start'});
  document.getElementById(SNS_ACCOUNTS.form.formId+(row?'-display':'-name'))?.focus();
}
function snsCloseAccount(){SNS_ACCOUNTS.form=null;SNS_ACCOUNTS.message='';render();document.getElementById('sns-detail-title')?.focus({preventScroll:true});}
function snsAccountInput(key,value){if(SNS_ACCOUNTS.form)SNS_ACCOUNTS.form[key]=value;}
async function snsSaveAccount(connect=false){
  if(SNS_ACCOUNTS.saving||!SNS_ACCOUNTS.form)return;
  const form=SNS_ACCOUNTS.form;
  const account=form.account.trim().replace(/^@/,'');
  if(!account){SNS_ACCOUNTS.message='연결할 계정의 사용자 이름을 입력해 주세요.';render();return;}
  if(connect&&!['instagram','threads','facebook'].includes(form.platform))return;
  if(connect&&form.platform==='facebook'&&!/^[0-9]{5,30}$/.test(form.page_id||'')){SNS_ACCOUNTS.message='연결할 Facebook 페이지 ID를 입력해 주세요.';render();return;}
  const popup=connect?window.open('about:blank','_blank'):null;
  if(popup){popup.opener=null;popup.document.body.textContent='SNS 인증 화면을 준비하고 있습니다…';}
  SNS_ACCOUNTS.saving=true;SNS_ACCOUNTS.message='';
  try{
    const payload={platform:form.platform,account,display_name:form.display_name,brands:form.brands.split(',').map(b=>b.trim()).filter(Boolean),owner:form.owner,management_status:form.management_status};
    const r=await fetch('/api/sns-internal/account',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const data=await r.json();if(!r.ok||!data.ok)throw new Error(data.error||'계정 정보를 저장하지 못했습니다.');
    form.account=account;form.key=snsDirectoryKey(form.platform,account);SNS_ACCOUNTS.selected=form.key;
    SNS_ACCOUNTS.message=connect?'분류를 저장했습니다. SNS 인증을 진행해 주세요.':'계정 분류를 저장했습니다. 연결·발행 설정은 바뀌지 않았습니다.';
    await loadSnsOperations();
    if(connect)await snsConnect(form.platform,account,popup,form.page_id||'');
  }catch(e){popup?.close();SNS_ACCOUNTS.message=e.message||'저장에 실패했습니다.';}
  finally{SNS_ACCOUNTS.saving=false;if(S.tab==='sns-accounts')render();}
}
function snsReconnectAccount(key){
  const row=snsDirectory().find(r=>r.key===key);if(!row)return;
  snsOpenAccount(key);
}

function snsAccountForm(){
  const f=SNS_ACCOUNTS.form;if(!f)return '';
  const supported=['instagram','threads','facebook'].includes(f.platform);
  const disabled=SNS_ACCOUNTS.saving||snsConnectBusy;
  return `<section id="sns-account-form" class="sns-panel sns-connection-form" aria-labelledby="sns-form-title">
    <div class="sns-section-head"><div><h2 id="sns-form-title">${f.key?'계정 정보 · 연결 관리':'계정 추가'}</h2><p class="sns-meta">1. 사업부와 계정을 확인하고 2. 해당 계정으로 SNS에 로그인하세요.</p></div><button class="btn btn-ghost" onclick="snsCloseAccount()">닫기</button></div>
    <div class="sns-account-fields">
      <label>SNS<select id="${f.formId}-platform" onchange="snsAccountInput('platform',this.value);render()" ${f.key?'disabled':''}>${Object.entries(SNS_PLATFORMS).map(([k,v])=>`<option value="${k}" ${f.platform===k?'selected':''}>${v}</option>`).join('')}</select></label>
      <label>계정 사용자 이름<input id="${f.formId}-name" maxlength="160" value="${esc(f.account)}" placeholder="예: my_company" ${f.key?'readonly':''} oninput="snsAccountInput('account',this.value)"></label>
      ${f.platform==='facebook'?`<label>Facebook 페이지 ID<input id="${f.formId}-page" inputmode="numeric" value="${esc(f.page_id||'')}" placeholder="Meta에서 확인한 페이지 ID" oninput="snsAccountInput('page_id',this.value)"></label>`:''}
      <label>표시 이름<input id="${f.formId}-display" maxlength="80" value="${esc(f.display_name)}" placeholder="예: 대표 개인 계정" oninput="snsAccountInput('display_name',this.value)"></label>
      <label>사업부 · 브랜드<input id="${f.formId}-brands" list="sns-brand-options" maxlength="328" value="${esc(f.brands)}" placeholder="공동 사용은 쉼표로 구분: 일손, 플로우워크" oninput="snsAccountInput('brands',this.value)"></label>
      <label>담당자<input id="${f.formId}-owner" maxlength="80" value="${esc(f.owner)}" placeholder="예: Jake" oninput="snsAccountInput('owner',this.value)"></label>
      <label>관리 상태<select id="${f.formId}-management" onchange="snsAccountInput('management_status',this.value)"><option value="active" ${f.management_status==='active'?'selected':''}>관리 중</option><option value="archived" ${f.management_status==='archived'?'selected':''}>보관</option></select></label>
    </div>
    <p class="sns-meta">보관한 계정은 기본 목록에서 제외됩니다. 기존 예약·자동 업무는 계속 실행되므로 실제 발행 중지는 해당 운영 경로에서 별도로 처리해야 합니다.</p>
    <datalist id="sns-brand-options">${[...new Set(snsDirectory().flatMap(r=>r.brands))].filter(b=>b!=='미분류').map(b=>`<option value="${esc(b)}"></option>`).join('')}</datalist>
    <p class="sns-notice">${f.platform==='facebook'?'Facebook에서 위 페이지의 조회·게시 권한을 허용해 주세요. 선택한 페이지 한 개만 내부 맥미니에 연결하며, 기존 발행 경로는 유지됩니다.':supported?'입력한 계정과 실제 인증한 계정이 다르면 연결을 저장하지 않습니다. 연결 완료만으로 글이 발행되지는 않습니다.':'이 SNS는 여기서 계정 분류를 관리할 수 있습니다. 로그인·인증은 기존 운영 경로에서 관리합니다.'}</p>
    <div class="sns-connect-actions"><button class="btn btn-ghost" onclick="snsSaveAccount(false)" ${disabled?'disabled':''}>관리 정보 저장</button>${supported?`<button class="btn btn-primary" onclick="snsSaveAccount(true)" ${disabled||!(SNS_OPS.box?.connectable||[]).includes(f.platform)?'disabled':''}>${SNS_ACCOUNTS.saving?'처리 중…':SNS_PLATFORMS[f.platform]+' 인증 시작'}</button>`:''}</div>
    ${SNS_ACCOUNTS.message?`<p class="sns-notice" role="status">${esc(SNS_ACCOUNTS.message)}</p>`:''}
  </section>`;
}

function snsConnectionOrigin(row){
  const m=row.meta;
  if(!row.native)return row.internalUnknown?'내부 연결 조회 미완료':'내부 연결 기록 없음';
  if(m.origin==='migrated')return `기존 연결 이관 · ${snsTime(m.imported_at)}`;
  if(m.origin==='internal')return `내부에서 연결 · ${snsTime(m.linked_at)}`;
  return '기존 저장 연결 · 연결 시점 미기록';
}
// 인증 상태와 발행 전환을 분리한다. 외부 도구 오류는 상세에서도 숨기지 않는다.
function snsAccountConnection(r){
  if(r.native){
    const [state,label]=snsHealth(r.native);
    return [state,state==='ok'?'정상':label];
  }
  if(r.internalUnknown&&['instagram','threads'].includes(r.platform))return ['unknown','확인 불가'];
  const old=r.legacy;
  if(old?.browser_health)return [old.browser_health.state,old.browser_health.label];
  if(old?.state==='ok')return ['ok',r.platform==='naverblog'?'연결 확인됨':'등록 활성'];
  if(old?.state==='error')return ['error',old.label==='연결 유효기간 경과'?'재인증 필요':'연결 점검 필요'];
  if(old?.state==='warning')return ['warning','갱신 필요'];
  return ['unknown','확인 불가'];
}
function snsAccountRoute(r){
  if(r.native?.publishing)return {key:'internal',label:'일손',evidence:'새로 승인한 글을 내부 실행기가 발행'};
  if(r.internalUnknown&&['instagram','threads'].includes(r.platform))return {key:'unknown',label:'경로 확인 필요',evidence:'내부 발행 설정 조회 미완료'};
  const key=r.legacy?.route;
  return {key:key||'unknown',label:r.legacy?.route_label||'경로 확인 필요',evidence:r.legacy?.evidence||'발행 경로 자료 없음'};
}
function snsAccountPublishing(r){
  return r.native?.publishing?'새 승인 글 발행':r.native?'발행 전환 대기':snsAccountRoute(r).label;
}
function snsDirectoryActivity(r){
  const d=SNS_OPS.data,rows=(d?.records||[]).filter(a=>snsDirectoryKey(a.platform,a.account)===r.key);
  const now=Date.parse(d?.generated_at),time=a=>Date.parse(a.published_at||a.scheduled_at||a.prepared_at)||0;
  const latest=rows.filter(a=>a.status==='published'&&Number.isFinite(Date.parse(a.published_at))).sort((a,b)=>time(b)-time(a))[0]?.published_at||'';
  const next=rows.filter(a=>['scheduled','approved'].includes(a.status)&&Date.parse(a.scheduled_at)>now).sort((a,b)=>Date.parse(a.scheduled_at)-Date.parse(b.scheduled_at))[0]?.scheduled_at||'';
  const failed=rows.filter(a=>a.status==='failed'||(!['published','cancelled'].includes(a.status)&&a.attempt_error)).sort((a,b)=>time(b)-time(a))[0];
  const failure=failed?{...failed,reason:failed.attempt_error||failed.reason,action:failed.attempt_action||failed.action}:null;
  return {latest,next,failure,attention:rows.filter(a=>a.attention).length,complete:!!d&&!(d.sources||[]).some(a=>a.status!=='ok')};
}
function snsAccountRecords(key,view='all'){
  const r=snsDirectory().find(a=>a.key===key);if(!r)return;
  Object.assign(SNS_OPS,{brand:'',channel:'',health:'',query:'',account:snsAccountKey(r),view,page:0,record:'',recordsOpen:true});
  A.go('sns');
}
function snsAccountUpcoming(r){
  const rows=snsScheduledRecords((SNS_OPS.data?.records||[]).filter(a=>snsDirectoryKey(a.platform,a.account)===r.key));
  if(!rows.length)return '';
  const key=snsEncodedKey(r.key);
  return `<section class="sns-detail-upcoming" aria-label="계정 게시 예정"><h3>게시 예정 ${rows.length}건</h3>
    <ol>${rows.slice(0,3).map(a=>`<li><span class="sns-meta">${a.scheduled_at?snsTime(a.scheduled_at):'시각 미정'}${a.overdue?' · 예약 지연':''}</span><p>${esc(a.title||'제목 없음')}</p></li>`).join('')}</ol>
    <button class="btn btn-primary" onclick="snsAccountRecords(decodeURIComponent('${key}'),'scheduled')">게시 예정 ${rows.length}건 보기 →</button></section>`;
}
function snsPlatformIcon(platform){
  const file={instagram:'instagram',threads:'threads',facebook:'facebook',x:'x',naverblog:'naver',linkedin:'linkedin',qiita:'qiita',zenn:'zenn'}[platform];
  return file?`<span class="sns-service-icon ${file}"><img src="assets/sns/${file}.svg" alt="" width="24" height="24"></span>`:'<i data-lucide="globe" aria-hidden="true"></i>';
}
function snsAccountRow(r){
  const [state,label]=snsAccountConnection(r),selected=SNS_ACCOUNTS.selected===r.key;
  const warning=r.legacyIssue&&state==='ok'&&r.native&&!r.native.publishing;
  const route=snsAccountRoute(r),activity=snsDirectoryActivity(r);
  return `<button class="sns-directory-row ${selected?'selected':''}" aria-pressed="${selected}" onclick="snsSelectAccount(decodeURIComponent('${snsEncodedKey(r.key)}'))">
    ${snsPlatformIcon(r.platform)}<span class="sns-row-identity"><span class="sns-row-platform">${esc(SNS_PLATFORMS[r.platform]||r.platform)}</span><strong>${esc(r.meta.display_name||r.account)}</strong><span>${esc(r.brands.join(' · '))} · 담당 ${esc(r.meta.owner||'미지정')}</span><span class="sns-row-activity">최근 ${activity.latest?snsTime(activity.latest):'조회 기록 없음'} · 다음 ${activity.next?snsTime(activity.next):'조회 예약 없음'}</span></span>
    <span class="sns-row-state">${snsBadge(label,state)}${r.expiry?`<span class="${r.expiry.attention?'sns-warn':'sns-meta'}">${esc(r.expiry.label)}</span>`:''}<span class="sns-route">${esc(route.label)}</span>${r.archived?'<span>보관</span>':''}${r.native?`<span class="${!r.native.publishing?'sns-warn':''}">${esc(snsAccountPublishing(r))}</span>`:''}${warning?'<span class="sns-warn">기존 연결 확인 필요</span>':''}</span><i data-lucide="chevron-right" aria-hidden="true"></i>
  </button>`;
}
let snsNaverBusy=false, snsNaverMessage='';
async function snsNaverAction(action){
  if(snsNaverBusy)return;
  snsNaverBusy=true;snsNaverMessage=action==='check'?'블로그 글쓰기 권한을 확인하고 있습니다…':'';render();
  try{
    const res=await fetch('/api/sns-naver/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    const d=await res.json();
    snsNaverMessage=d.message||d.connection?.label||d.error||'연결 상태를 확인하지 못했습니다.';
    await loadSnsOperations();
  }catch(e){snsNaverMessage='요청을 완료하지 못했습니다. 연결 상태를 다시 확인해 주세요.';}
  finally{snsNaverBusy=false;render();}
}
function snsNaverPanel(r){
  if(r.platform!=='naverblog'||r.account!==SNS_OPS.naver?.account)return '';
  return `<section class="sns-panel"><h3>네이버 전용 로그인</h3><p>맥북에서는 로그인 팝업이 뜨지 않습니다. 맥미니 화면에서 로그인해 주세요. 등록한 네이버 아이디로 로그인하고 창을 닫은 뒤 연결을 확인하세요. 게시 대상은 선택한 계정의 블로그입니다. 연결 확인은 글을 게시하지 않습니다.</p><div class="sns-connect-actions"><button class="btn btn-ghost" onclick="snsNaverAction('login')" ${snsNaverBusy?'disabled':''}>맥미니에서 로그인 창 열기</button><button class="btn btn-primary" onclick="snsNaverAction('check')" ${snsNaverBusy?'disabled':''}>연결 확인</button></div>${snsNaverMessage?`<p role="status">${esc(snsNaverMessage)}</p>`:''}</section>`;
}
let snsBrowserBusy='',snsBrowserMessage='',snsBrowserMessageKey='';
async function snsBrowserCheck(key){
  const r=snsDirectory().find(a=>a.key===key);if(!r||snsBrowserBusy)return;
  snsBrowserBusy=key;snsBrowserMessageKey=key;snsBrowserMessage='로그인 상태 점검을 요청하고 있습니다…';render();
  try{
    const res=await fetch('/api/sns-browser/check',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({platform:r.platform,account:r.account})});
    const data=await res.json();snsBrowserMessage=data.message||data.error||'점검 요청을 확인하지 못했습니다.';
    if(res.ok){setTimeout(()=>loadSnsOperations(),5000);setTimeout(()=>loadSnsOperations(),20000);}
  }catch(e){snsBrowserMessage='점검을 요청하지 못했습니다. 다시 시도해 주세요.';}
  finally{snsBrowserBusy='';render();}
}
function snsBrowserPanel(r){
  const h=r.legacy?.browser_health;if(!h)return '';
  return `<section class="sns-panel" aria-label="브라우저 로그인 상태"><h3>브라우저 로그인</h3><p>${snsBadge(h.label,h.state)}${h.checking?' · 확인 중':''}</p><p class="sns-meta">30분마다 자동 확인 · 마지막 확인 ${h.checked_at?snsTime(h.checked_at):'아직 없음'}${h.stale?' · 최신 확인 필요':''}</p><p>글쓰기 화면: ${h.publish_access==='confirmed'?'접근 확인됨':'권한 확인 전'}</p><p class="sns-meta">${h.provider==='playwright'?'일손 전용 브라우저':'현재 발행에 사용하는 Aside 브라우저'} 기준입니다. 로그인 상태와 실제 게시 성공은 별개입니다.</p><button class="btn btn-ghost" onclick="snsBrowserCheck(decodeURIComponent('${snsEncodedKey(r.key)}'))" ${snsBrowserBusy===r.key||h.checking?'disabled':''}>지금 확인</button>${snsBrowserMessage&&snsBrowserMessageKey===r.key?`<p role="status">${esc(snsBrowserMessage)}</p>`:''}</section>`;
}
function snsAccountDetail(r){
  if(!r)return '<div class="sns-detail-empty"><i data-lucide="mouse-pointer-2" aria-hidden="true"></i><h2>계정을 선택하세요</h2><p>연결 상태와 발행 설정을 확인할 수 있습니다.</p></div>';
  const n=r.native,m=r.meta,[state,label]=snsAccountConnection(r),supported=['instagram','threads','facebook'].includes(r.platform);
  const route=snsAccountRoute(r),activity=snsDirectoryActivity(r);
  const key=snsEncodedKey(r.key),canManage=SNS_OPS.box?.binding==='matched';
  const note=n?.publishing?'이 계정은 새로 승인한 글을 내부 일손에서 발행합니다.':n?'계정 연결은 저장되었습니다. 이 계정의 초안을 만들고 승인하면 발행합니다.':supported?'아래에서 계정을 확인하고 SNS에 로그인하면 내부 연결을 시작할 수 있습니다.':r.platform==='naverblog'&&r.account===SNS_OPS.naver?.account?'전용 브라우저에 로그인한 뒤 계정과 글쓰기 권한을 확인하세요.':'이 SNS는 사업부와 담당자를 관리할 수 있습니다. 로그인·인증은 기존 운영 경로에서 진행합니다.';
  return `<button class="btn btn-ghost sns-mobile-back" onclick="snsAccountStep('list')"><i data-lucide="arrow-left" aria-hidden="true"></i>계정 목록</button>
    <p class="sns-detail-eyebrow">계정 상세</p><div class="sns-detail-identity">${snsPlatformIcon(r.platform)}<div><span>${esc(SNS_PLATFORMS[r.platform]||r.platform)}</span><h2 id="sns-detail-title" tabindex="-1">${esc(m.display_name||r.account)}</h2>${m.display_name?`<p>@${esc(r.account)}</p>`:''}</div></div>
    <dl class="sns-detail-facts"><div><dt>발행 경로</dt><dd><b>${esc(route.label)}</b><small>${esc(route.evidence)}</small></dd></div><div><dt>연결 상태</dt><dd>${snsBadge(label,state)}<small>${esc(n?'SNS 프로필 조회':r.legacy?.evidence||'연결 조회 자료 없음')}${!n&&r.legacy?.label?' · '+esc(r.legacy.label):''}</small></dd></div>${r.expiry?`<div><dt>인증 만료</dt><dd class="${r.expiry.attention?'sns-warn':''}">${esc(r.expiry.label)}<small>${snsTime(n.expires_at)}${r.expiry.attention?' · 「다시 연결」로 재인증':''}</small></dd></div>`:''}<div><dt>사업부</dt><dd>${esc(r.brands.join(' · '))}${r.brands.length>1?'<small>공동 사용 계정</small>':''}</dd></div><div><dt>담당자</dt><dd>${esc(m.owner||'미지정')}</dd></div><div><dt>발행 상태</dt><dd class="${n&&!n.publishing?'sns-warn':''}">${esc(snsAccountPublishing(r))}</dd></div></dl>
    <section class="sns-detail-activity" aria-label="계정 운영 현황"><h3>발행 · 예약 현황</h3><dl class="sns-detail-facts"><div><dt>최근 발행</dt><dd>${activity.latest?snsTime(activity.latest):'조회 기록 없음'}</dd></div><div><dt>다음 예약</dt><dd>${activity.next?snsTime(activity.next):'조회 예약 없음'}</dd></div><div><dt>최근 실패·시도 오류</dt><dd>${activity.failure?esc(activity.failure.reason||'실패 사유 미기록'):'조회된 실패·시도 오류 없음'}${activity.failure?'<small>준비 기록 '+snsTime(activity.failure.prepared_at)+' · '+esc(activity.failure.action||'발행 기록 확인')+'</small>':''}</dd></div></dl><p class="sns-meta">${activity.complete?'조회된 장부 기준입니다.':'일부 자료가 미확인이라 기록이 누락될 수 있습니다.'} 이 미니에 저장된 게시물 기준입니다. 연결 상태와 게시 성공은 별개입니다.</p><button class="btn btn-ghost" onclick="snsAccountRecords(decodeURIComponent('${key}'))">발행 기록 보기 →</button></section>
    ${snsAccountUpcoming(r)}
    ${snsNaverPanel(r)}
    ${snsBrowserPanel(r)}
    ${r.archived?'<p class="sns-notice">보관 중인 계정입니다. 보관은 목록 분류이며 예약·자동 발행을 중지하지 않습니다.</p>':''}
    ${state==='error'||state==='warning'?`<p class="sns-notice">${esc(r.native?'계정 정보를 확인하고 다시 인증해 주세요.':r.legacy?.action||'해당 운영 경로에서 연결 상태를 확인해 주세요.')}</p>`:''}
    ${r.legacy&&!(r.platform==='naverblog'&&r.account===SNS_OPS.naver?.account)&&['error','warning'].includes(r.legacy.state)?`<p class="sns-detail-warning">기존 도구: ${esc(r.legacy.label)}. ${n?.publishing?'이전 예약에 영향이 있는지 확인하세요.':'기존 경로로 발행한다면 연결 상태를 확인하세요.'}</p>`:''}
    <p class="sns-detail-note">${r.internalUnknown?'내부 연결을 조회하지 못했습니다. 새로 확인한 뒤 관리해 주세요.':note}</p>
    <div class="sns-detail-actions"><button class="btn btn-primary" onclick="snsOpenAccount(decodeURIComponent('${key}'))" ${canManage?'':'disabled'}>${supported&&!n?'계정 확인 · 연결':'계정 정보 수정'}</button>${supported&&n?`<button class="btn btn-ghost" onclick="snsReconnectAccount(decodeURIComponent('${key}'))" ${canManage?'':'disabled'}>다시 연결</button>`:''}</div>
    <details class="sns-detail-history" ontoggle="snsAccountHistory(this.open)" ${SNS_ACCOUNTS.historyOpen?'open':''}><summary>연결 이력 및 기존 도구 정보</summary><p>${esc(snsConnectionOrigin(r))}</p>${n?`<p>인증 확인 ${snsTime(n.checked_at)}<br>만료 ${snsTime(n.expires_at)}</p>`:''}<p>기존 도구: ${r.legacy?esc(r.legacy.label):'기록 없음'}</p><p>인증 확인은 SNS 프로필 조회 결과이며 실제 게시 성공과는 다릅니다.</p></details>`;
}
function screenSnsAccounts(){
  if(!SNS_OPS.data&&!SNS_OPS.busy&&!SNS_OPS.error)setTimeout(loadSnsOperations,0);
  const all=snsDirectory(),active=all.filter(r=>!r.archived),rows=snsDirectoryFiltered(all),f=SNS_ACCOUNTS,box=SNS_OPS.box;
  // 선택한 계정이 필터 밖으로 사라지면 옛 상세를 남기지 않는다.
  if(!rows.some(r=>r.key===f.selected))f.selected=rows[0]?.key||'';
  const selected=rows.find(r=>r.key===f.selected);
  const groupRows=f.status==='archived'?all.filter(r=>r.archived):active;
  const brands=[...new Set(groupRows.flatMap(r=>r.brands))].sort((a,b)=>a==='미분류'?1:b==='미분류'?-1:a.localeCompare(b,'ko'));
  const states=[['all','관리 중',active.length],['internal','내부 연결',active.filter(r=>r.native).length],['attention','연결 확인 필요',active.filter(r=>r.needsAttention).length],['transition','발행 전환 대기',active.filter(r=>r.transitionPending).length],['expiring','만료 임박',active.filter(r=>r.expiring).length],['unknown','확인 불가',active.filter(r=>snsAccountConnection(r)[0]==='unknown').length],['unclassified','미분류',active.filter(r=>r.brands.includes('미분류')).length],['archived','보관',all.filter(r=>r.archived).length]];
  const brandButton=(brand,label,n)=>`<button class="sns-brand-choice ${f.brand===brand?'selected':''}" aria-pressed="${f.brand===brand}" onclick="snsAccountFilter('brand',decodeURIComponent('${snsEncodedKey(brand)}'))"><span>${esc(label)}</span><strong>${n}</strong></button>`;
  const worker={recent:'승인 발행 실행 중',error:'발행 처리 확인 필요',stale:'실행 신호 오래됨',unknown:'실행 상태 미확인'}[box?.worker]||'실행 상태 미확인';
  return `<div class="sns-ops sns-accounts-page"><div class="sns-head"><div><div class="sns-eyebrow">ILSON · ACCOUNTS</div><h1>SNS 계정 관리</h1><p>발행 경로, 연결 상태와 계정별 운영 현황을 확인하세요.</p></div><div class="sns-connect-actions"><button class="btn btn-ghost" onclick="loadSnsOperations()" ${SNS_OPS.busy?'disabled':''}>${SNS_OPS.busy?'확인 중…':'새로 확인'}</button><button class="btn btn-primary" onclick="snsOpenAccount()" ${box?.binding!=='matched'?'disabled':''}>+ 계정 추가</button></div></div>
    ${SNS_OPS.error?`<p class="sns-notice" role="alert">기존 운영 자료 조회 실패: ${esc(SNS_OPS.error)} 확인된 내부 연결만 표시할 수 있습니다.</p>`:''}
    ${box?.binding!=='matched'?'<p class="sns-notice" role="alert">내부 연결 상태를 확인하지 못했습니다. 계정이 연결되지 않았다는 뜻은 아닙니다.</p>':''}
    ${(SNS_OPS.data?.sources||[]).some(s=>s.status!=='ok')?'<p class="sns-notice">일부 기존 운영 자료를 확인하지 못했습니다. 목록이 전체 계정을 뜻하지 않을 수 있습니다.</p>':''}
    <div class="sns-account-summary" aria-label="연결 상태 필터">${states.map(([key,label,n])=>`<button class="sns-account-metric ${f.status===key?'selected':''}" aria-pressed="${f.status===key}" onclick="snsAccountFilter('status','${key}')"><span>${label}</span><strong>${n}</strong></button>`).join('')}</div>
    ${snsAccountForm()}
    ${snsConnectMessage?`<p class="sns-notice" role="status">${esc(snsConnectMessage)} ${snsConnectUrl?`<a href="${esc(snsConnectUrl)}" target="_blank" rel="noopener noreferrer">인증 창 열기</a>`:''}</p>`:''}
    ${(box?.connections||[]).length?`<section class="sns-connection-progress"><h2>최근 연결 요청</h2>${box.connections.map(c=>`<p><b>${esc(SNS_PLATFORMS[c.platform]||c.platform)}${c.username||c.expected_account?' · @'+esc(c.username||c.expected_account):''}</b> · ${esc(c.message)}</p>`).join('')}</section>`:''}
    <div id="sns-account-workspace" class="sns-account-workspace" data-step="${f.mobileStep}">
      <nav class="sns-brand-nav" aria-label="사업부 선택"><h2>사업부</h2>${brandButton('','전체',groupRows.length)}${brands.map(b=>brandButton(b,b,groupRows.filter(r=>r.brands.includes(b)).length)).join('')}<p class="sns-brand-hint">공동 계정은 각 사업부에<br>함께 표시됩니다.</p></nav>
      <section class="sns-directory" aria-label="계정 목록"><button class="btn btn-ghost sns-mobile-back" onclick="snsAccountStep('brands')"><i data-lucide="arrow-left" aria-hidden="true"></i>사업부 선택</button><div class="sns-directory-heading"><h2>${esc(f.brand||'전체 사업부')}</h2><p><span aria-live="polite">${rows.length}개 계정</span>${f.status!=='all'?' · '+states.find(s=>s[0]===f.status)[1]:''}</p></div>
        <div class="sns-directory-controls"><label class="sns-directory-search"><span class="sns-visually-hidden">계정·담당자 검색</span><input id="sns-directory-search" value="${esc(f.query)}" placeholder="계정명 또는 담당자 검색" oninput="snsAccountFilter('query',this.value)"></label><label><span class="sns-visually-hidden">SNS</span><select id="sns-directory-platform" onchange="snsAccountFilter('platform',this.value)"><option value="">전체 SNS</option>${Object.entries(SNS_PLATFORMS).map(([k,v])=>`<option value="${k}" ${f.platform===k?'selected':''}>${v}</option>`).join('')}</select></label></div>
        <div class="sns-route-filters" role="group" aria-label="발행 경로 필터">${[['','전체 경로'],['internal','일손'],['marketer','SNS MARKETER'],['browser','브라우저 자동화'],['unknown','경로 확인 필요']].map(([k,label])=>`<button class="btn ${f.route===k?'btn-primary':'btn-ghost'}" aria-pressed="${f.route===k}" onclick="snsAccountFilter('route','${k}')">${label}</button>`).join('')}</div>
        ${(f.platform||f.route||f.query||f.status!=='all')?'<button class="btn btn-ghost sns-filter-reset" onclick="snsAccountReset()">필터 초기화</button>':''}
        <div class="sns-directory-list">${rows.map(snsAccountRow).join('')||`<div class="sns-empty">${SNS_OPS.busy?'계정을 확인하고 있습니다…':'해당 조건의 계정이 없습니다. 필터를 바꾸거나 계정을 추가해 주세요.'}</div>`}</div>
      </section>
      <aside class="sns-account-detail" aria-label="계정 상세">${snsAccountDetail(selected)}</aside>
    </div>
    <div class="sns-account-footer"><span>계정 연결과 발행 대상 지정·게시 승인은 별도입니다.</span><button class="btn btn-ghost" onclick="A.go('sns')">발행 현황 <i data-lucide="arrow-up-right" aria-hidden="true"></i></button></div>
    <details class="sns-account-storage"><summary>연결 정보 보관과 발행 상태</summary><p>${esc(worker)} · 마지막 처리 ${snsTime(box?.last_cycle_at)}.</p><p>인증 정보는 회사 맥미니에 보관합니다. 인증 중계에 잠시 전달된 정보는 수령 후 지웁니다. Instagram·Threads는 이 화면에서 연결하고, 다른 SNS 로그인은 기존 운영 경로에서 관리합니다.</p></details>
  </div>`;
}
