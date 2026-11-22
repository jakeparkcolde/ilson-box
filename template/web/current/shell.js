/* 운영 화면 렌더러의 호스트. 데모 회사/가상 계정/발행 기록은 넣지 않는다. */
const initialTab=location.pathname==='/usage-history'?'usage-history':new URLSearchParams(location.search).get('tab');
const S={tab:initialTab||'sns',vaultSel:'',vaultGroup:'',vaultDoc:null};
const deviceTabs={home:'overview',jobs:'jobs',reports:'reports',settings:'settings'};
const LIVE={on:true,d:{vault:[],vault_ok:true}};
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const typing=()=>{const n=document.activeElement;return ['TEXTAREA','SELECT'].includes(n?.tagName)||(n?.tagName==='INPUT'&&!['checkbox','radio','button','submit','reset'].includes(n.type));};
const renderIdle=()=>{if(!typing())render();};
async function api(path,body){const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await response.json();if(!response.ok){if(response.status===401)location.assign('/');throw Error(data.error||'요청을 완료하지 못했습니다.');}return data;}
const A={
  go(tab){if(tab==='inbox'){SNS_OPS.view='pending';tab='sns';}if(!['home','jobs','reports','settings','sns','sns-accounts','research','knowledge','vault','received-files','packs','opensource','learn','dashboard','usage-history','staff','org','skills','replies'].includes(tab))return;const learn=window.IlsonLearn;if(tab==='learn'&&S.tab==='learn'&&learn){document.body.classList.remove('m-nav-open');learn.menu();return;}if(S.tab==='learn'&&tab!=='learn')learn?.leave();const changed=S.tab!==tab;if(changed&&window.IlsonPeople&&!IlsonPeople.canLeave())return;S.tab=tab;document.body.classList.remove('m-nav-open');render();if(changed){document.getElementById('main').scrollTop=0;window.scrollTo(0,0);if(tab==='learn')learn?.restore();}if(tab==='vault')loadVault();},
  pickVaultGroup(group){group=decodeURIComponent(group);S.vaultGroup=group;render();},
  pickVault(rel){rel=decodeURIComponent(rel);S.vaultSel=rel;S.vaultDoc=null;render();},
  async vaultOpenDoc(rel,name,base,id){rel=decodeURIComponent(rel);name=decodeURIComponent(name);base=decodeURIComponent(base);const folder=LIVE.d.vault.find(r=>r.rel===rel),file=folder?.files.find(f=>id?f.id===decodeURIComponent(id):f.name===name);if(!file)return;S.vaultDoc={id:file.id,rel,name,base,content:null};render();try{const data=await api('/api/current/document',{id:file.id});if(S.vaultDoc?.id===file.id){S.vaultDoc.content=data.content;S.vaultDoc.category=data.path.split("/").at(-2);render();}}catch(error){if(S.vaultDoc?.id===file.id){S.vaultDoc.content=error.message;render();}}},
  vaultEditStart(){if(S.vaultDoc?.content!=null){S.vaultDoc.draft=S.vaultDoc.content;S.vaultDoc.edit=true;render();}},
  vaultEditCancel(){if(S.vaultDoc){S.vaultDoc.edit=false;render();}},
  async vaultSave(){const doc=S.vaultDoc;if(!doc)return;doc.draft=document.getElementById('vaultEditor').value;try{const result=await api('/api/workspace/documents',{title:doc.name,content:doc.draft.startsWith('# '+doc.name+'\n')?doc.draft.slice(doc.name.length+3).trimStart():doc.draft,category:['company','research','knowledge','sns'].includes(doc.category)?doc.category:'company',previous_id:doc.id});await loadVault();const folder=LIVE.d.vault.find(f=>f.files.some(d=>d.id===result.id));S.vaultSel=folder.rel;S.vaultGroup=folder.group;await A.vaultOpenDoc(vaultArg(folder.rel),vaultArg(result.title),'box',vaultArg(result.id));S.vaultDoc.msg='원본과 연결된 새 기록으로 저장했습니다.';render();}catch(error){doc.msg=error.message;render();}},
  noop(event){event?.preventDefault();}
};
const railTabMap={home:'home',jobs:'jobs',reports:'jobs',sns:'sns','sns-accounts':'sns',replies:'sns',dashboard:'dashboard','usage-history':'dashboard',vault:'vault','received-files':'vault',research:'vault',knowledge:'vault',packs:'vault',opensource:'vault',staff:'staff',org:'staff',skills:'staff',settings:'settings',learn:'learn'};
const FOLDERS={work:true,company:false,platform:false};
const META={pending:null,jobs:null,reports:null,registered:null,attention:null};
const PEERS={current:null,list:[],open:false};
function peerUrl(base){
  const clean=String(base||'').replace(/\/+$/,'');
  return S.tab==='usage-history'?clean+'/usage-history':clean+'/current/index.html?tab='+encodeURIComponent(S.tab||'home');
}
function togglePeerMenu(event){
  event?.stopPropagation?.();
  if(!PEERS.list.length){A.go('home');return;}
  PEERS.open=!PEERS.open;
  renderNav();
}
function switchPeer(index){
  const target=PEERS.list[index];
  PEERS.open=false;
  if(!target)return;
  if(target.current){renderNav();A.go('home');return;}
  if(window.IlsonPeople&&!IlsonPeople.canLeave())return;
  location.assign(peerUrl(target.url));
}
function updateRailClock(){
  const nowEl=document.getElementById('railNow'),timeEl=document.getElementById('railNowTime');
  if(!nowEl||!timeEl)return;
  const d=new Date(),mins=d.getHours()*60+d.getMinutes();
  const hh=String(d.getHours()).padStart(2,'0'),mm=String(d.getMinutes()).padStart(2,'0');
  timeEl.textContent=hh+':'+mm;
  const pct=Math.max(8,Math.min(90,mins/1440*100));
  if(nowEl.style)nowEl.style.top=pct.toFixed(2)+'%';
}
function applyNavMeta(){
  const setText=(id,val)=>{const el=document.getElementById(id);if(!el)return;if(val==null||val===''){el.hidden=true;return;}el.textContent=String(val);el.hidden=false;};
  setText('navCountJobs',META.jobs);
  setText('navCountReports',META.reports);
  setText('navCountRegistered',META.registered);
  setText('navCountAttention',META.attention);
  const badge=document.getElementById('navBadgePending');
  if(badge){const n=Number(META.pending);if(n>0){badge.textContent=String(n);badge.hidden=false;}else badge.hidden=true;}
  const dot=document.getElementById('railPendingDot');
  if(dot)dot.hidden=!(Number(META.pending)>0);
}
function syncRail(){
  const rail=document.getElementById('folioRail');
  if(!rail)return;
  const active=railTabMap[S.tab]||'home';
  for(const btn of rail.querySelectorAll('.rail-btn')){
    const on=btn.dataset?.rail===active;
    btn.classList?.toggle('on',on);
    if(on)btn.setAttribute?.('aria-current','page');
    else btn.removeAttribute?.('aria-current');
  }
  updateRailClock();
}
function toggleFolder(key){
  FOLDERS[key]=!FOLDERS[key];
  renderNav();
}
function toggleAllFolders(){
  const allOpen=Object.values(FOLDERS).every(Boolean);
  for(const k of Object.keys(FOLDERS))FOLDERS[k]=!allOpen;
  renderNav();
}
function filterNav(query){
  const sb=document.getElementById('sidebar');
  if(!sb)return;
  const q=String(query||'').trim().toLowerCase();
  for(const folder of sb.querySelectorAll('.nav-folder')){
    const key=folder.dataset?.folder;
    const body=folder.querySelector('.folder-children');
    let visible=0;
    for(const row of folder.querySelectorAll('.nav-row')){
      const btn=row.querySelector('.nav-item');
      const match=!q||(btn?.textContent||'').toLowerCase().includes(q);
      row.hidden=!match;
      if(match)visible++;
    }
    folder.hidden=!!q&&visible===0;
    if(body)body.hidden=q?visible===0:!FOLDERS[key];
  }
  for(const sec of sb.querySelectorAll('.nav-section[data-flat]')){
    let visible=0;
    for(const row of sec.querySelectorAll('.nav-row')){
      const btn=row.querySelector('.nav-item');
      const match=!q||(btn?.textContent||'').toLowerCase().includes(q);
      row.hidden=!match;
      if(match)visible++;
    }
    sec.hidden=visible===0;
  }
}
function renderNav(){
  const wsItems=[
    {id:'home',icon:'layout-grid',label:'홈'},
    {id:'jobs',icon:'workflow',label:'업무',countId:'navCountJobs'},
    {id:'reports',icon:'file-text',label:'보고서',countId:'navCountReports'},
    {id:'settings',icon:'sliders-horizontal',label:'설정'}
  ];
  const liveItems=[
    {id:'sns',dot:'lime',label:'SNS 운영',badgeId:'navBadgePending'},
    {id:'dashboard',dot:'muted',label:'자동화·컴퓨터 현황',countId:'navCountRegistered'},
    {id:'usage-history',dot:'alert',label:'내 AI 사용 기록',countId:'navCountAttention'}
  ];
  const learnEntry=[{group:'배우기'},{id:'learn',icon:'graduation-cap',label:'Claude 배우기'}];
  const folders=[
    {key:'work',label:'업무 · 파일',items:[{id:'vault',label:'서류함'},{id:'received-files',label:'받은 파일'},{id:'sns-accounts',label:'SNS 계정 관리'},{id:'replies',label:'답글 초안'}]},
    {key:'company',label:'우리 회사',items:[{id:'staff',label:'직원'},{id:'org',label:'조직도'},{id:'skills',label:'업무 스킬'}]},
    {key:'platform',label:'플랫폼',items:[{id:'research',label:'리서치'},{id:'knowledge',label:'지식 훔치기'},{id:'packs',label:'팩 보관함'},{id:'opensource',label:'오픈소스'},learnEntry[1]]}
  ];
  for(const f of folders){if(f.items.some(i=>i.id===S.tab))FOLDERS[f.key]=true;}
  const prevSearch=document.getElementById('sideSearch')?.value||'';
  const rowBtn=(n,extra)=>`<div class="nav-row${S.tab===n.id?' is-on':''}"><button class="nav-item${S.tab===n.id?' on':''}"${S.tab===n.id?' aria-current="page"':''} onclick="A.go('${n.id}')">${extra}<span class="nav-label">${n.label}</span></button>${n.badgeId?`<span class="nav-pill-lime" id="${n.badgeId}" hidden></span>`:''}${n.countId?`<span class="nav-count" id="${n.countId}" hidden></span>`:''}</div>`;
  const wsHtml=`<div class="nav-section" data-flat="1"><div class="nav-group">워크스페이스</div>${wsItems.map(n=>rowBtn(n,`<i data-lucide="${n.icon}"></i>`)).join('')}</div>`;
  const liveHtml=`<div class="nav-section" data-flat="1"><div class="nav-group">실시간</div>${liveItems.map(n=>rowBtn(n,`<span class="nav-dot is-${n.dot}" aria-hidden="true"></span>`)).join('')}</div>`;
  const folderHtml=`<div class="nav-section"><div class="nav-group-row"><span class="nav-group">폴더</span><button class="nav-group-plus" type="button" title="폴더 전체 펼치기/접기" aria-label="폴더 전체 펼치기/접기" onclick="toggleAllFolders()"><svg viewBox="0 0 12 12" width="11" height="11" aria-hidden="true"><path d="M6 1.5v9M1.5 6h9" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg></button></div>${folders.map(f=>{
    const open=!!FOLDERS[f.key];
    return `<div class="nav-folder${open?' is-open':''}" data-folder="${f.key}"><button class="folder-head" type="button" aria-expanded="${open}" onclick="toggleFolder('${f.key}')"><svg class="folder-chev" viewBox="0 0 10 10" width="9" height="9" aria-hidden="true"><path d="${open?'M2 3.5l3 3 3-3':'M3.5 2l3 3-3 3'}" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg><i data-lucide="folder"></i><span class="folder-label">${f.label}</span><span class="folder-count">${f.items.length}</span></button><div class="folder-children"${open?'':' hidden'}>${f.items.map(n=>`<div class="nav-row is-child${S.tab===n.id?' is-on':''}"><button class="nav-item${S.tab===n.id?' on':''}"${S.tab===n.id?' aria-current="page"':''} onclick="A.go('${n.id}')"><span class="nav-label">${n.label}</span></button></div>`).join('')}</div></div>`;
  }).join('')}</div>`;
  const wsName=PEERS.current?.name||'일손 Box';
  const wsSub=PEERS.current?.subtitle||'운영 워크스페이스';
  const hasPeers=PEERS.list.length>0;
  const peerMenuHtml=hasPeers&&PEERS.open?`<div class="side-ws-menu" id="peerMenu" role="menu" aria-label="기기 전환"><div class="side-ws-menu-hd">연결된 기기</div>${PEERS.list.map((p,i)=>`<button class="side-ws-opt${p.current?' is-on':''}" type="button" role="menuitem" onclick="switchPeer(${i})"><span class="side-ws-opt-dot" aria-hidden="true"></span><span class="side-ws-opt-txt"><strong>${esc(p.name)}</strong>${p.subtitle?`<small>${esc(p.subtitle)}</small>`:''}</span>${p.current?'<span class="side-ws-opt-tag">현재</span>':''}</button>`).join('')}</div>`:'';
  document.getElementById('sidebar').innerHTML=`<div class="side-ws-wrap"><button class="side-ws${PEERS.open?' is-open':''}" type="button" onclick="${hasPeers?'togglePeerMenu(event)':'A.go(\'home\')'}" aria-label="${esc(wsName)} ${esc(wsSub)}"${hasPeers?` aria-haspopup="menu" aria-expanded="${PEERS.open}"`:''}><span class="side-ws-mark" aria-hidden="true">일</span><span class="side-ws-text"><strong class="side-ws-name">${esc(wsName)}</strong><small class="side-ws-sub">${esc(wsSub)}</small></span><svg class="side-ws-chev" viewBox="0 0 12 16" width="12" height="16" aria-hidden="true"><path d="M2 6l4-4 4 4M2 10l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/></svg></button>${peerMenuHtml}</div><label class="side-search"><svg class="side-search-ic" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" stroke-width="1.3"/><path d="M10.5 10.5L14 14" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg><input id="sideSearch" type="search" placeholder="검색" aria-label="메뉴 검색" value="${esc(prevSearch)}"><kbd>⌘K</kbd></label><div class="side-scroll">${wsHtml}${liveHtml}${folderHtml}</div><div class="side-user"><span class="side-avatar" aria-hidden="true">일손<i class="side-avatar-dot"></i></span><span class="side-user-meta"><strong class="side-user-name">${esc(PEERS.current?.name||'이 미니의 일손')}</strong><small class="side-user-role">로컬 연결됨</small></span><span class="side-user-actions"><button id="themeToggle" type="button" title="테마 전환" aria-label="테마 전환">◐</button><button id="logout" type="button" title="접속 종료" aria-label="접속 종료"><i data-lucide="log-out"></i></button></span></div>`;
  const searchEl=document.getElementById('sideSearch');
  if(searchEl){
    searchEl.oninput=()=>filterNav(searchEl.value);
    searchEl.onkeydown=e=>{
      if(e.key==='Escape'){searchEl.value='';filterNav('');searchEl.blur?.();}
      else if(e.key==='Enter'){
        const first=document.getElementById('sidebar')?.querySelector('.nav-row:not([hidden]) .nav-item');
        if(first&&typeof first.click==='function'){e.preventDefault?.();first.click();}
      }
    };
    if(prevSearch)filterNav(prevSearch);
  }
  document.getElementById('logout').onclick=async()=>{if(window.IlsonPeople&&!IlsonPeople.canLeave())return;try{await api('/api/logout',{});location.assign('/');}catch{window.alert('접속 종료를 확인하지 못했습니다. 다시 시도해 주세요.');}};
  document.getElementById('themeToggle').onclick=()=>{const theme=document.body.dataset.theme==='light'?'dark':'light';document.body.dataset.theme=theme;try{localStorage.setItem('ilson-theme',theme);}catch{}};
  applyNavMeta();
  syncRail();
  if(window.lucide)lucide.createIcons();
}
function render(){
  const main=document.getElementById('main');
  if(S.tab!=='opensource')window.IlsonOpensource?.leave();
  const inputState=[...main.querySelectorAll('input[id],textarea[id]')].filter(n=>n.type!=='password').map(n=>({id:n.id,value:n.value,focus:n===document.activeElement,start:n.selectionStart,end:n.selectionEnd}));
  const keep=snsCaptureView();
  history.replaceState(null,'',S.tab==='usage-history'?'/usage-history':(location.pathname==='/usage-history'?'/current/':'')+'?tab='+encodeURIComponent(S.tab)+(S.tab==='learn'&&window.IlsonLearn?IlsonLearn.query():''));
  document.body.classList.toggle('folio-home',S.tab==='home');
  renderNav();
  if(deviceTabs[S.tab]){
    window.IlsonPeople?.leave();
    window.IlsonDashboard?.leave();
    const view=deviceTabs[S.tab], existing=main.querySelector('#deviceFrame');
    if(!existing){
      main.innerHTML='<iframe id="deviceFrame" class="device-frame" title="일손 시작과 기기 상태"></iframe>';
      const frame=main.querySelector('#deviceFrame');frame.dataset.view=view;frame.src='/#device&embedded&view='+encodeURIComponent(view);
    }else if(existing.dataset.view!==view){
      existing.dataset.view=view;existing.src='/#device&embedded&view='+encodeURIComponent(view);
    }
  }else if(['staff','org','skills'].includes(S.tab)){
    window.IlsonDashboard?.leave();
    IlsonPeople.mount(main,S.tab);
  }else if(S.tab==='opensource'){
    window.IlsonPeople?.leave();
    window.IlsonDashboard?.leave();
    IlsonOpensource.mount(main);
  }else if(S.tab==='usage-history'){
    window.IlsonPeople?.leave();
    window.IlsonDashboard?.leave();
    if(!main.querySelector('.usage-history'))IlsonUsage.mount(main);
  }else if(S.tab==='dashboard'){
    window.IlsonPeople?.leave();
    // Keep the mounted view through unrelated async shell renders.
    IlsonDashboard.mount(main);
  }else{
    window.IlsonPeople?.leave();
    window.IlsonDashboard?.leave();
    if(!IlsonPacks.current(S.tab)){
      main.innerHTML=({sns:screenSnsOperations,'sns-accounts':screenSnsAccounts,vault:screenVaultAllLive,'received-files':()=>window.screenInboxFiles?.()||'',research:()=>IlsonPacks.render('research','pack-library'),knowledge:()=>IlsonPacks.render('knowledge','pack-library'),packs:()=>IlsonPacks.render('packs','pack-library'),replies:()=>window.IlsonReplies.screen(),learn:()=>window.IlsonLearn?IlsonLearn.render():''}[S.tab]||screenSnsOperations)();
      for(const state of inputState){
        const n=document.getElementById(state.id);
        if(n){n.value=state.value;if(state.focus){n.focus();try{n.setSelectionRange(state.start,state.end);}catch{}}}
      }
    }
  }
  if(window.lucide)lucide.createIcons();
  snsRestoreView(keep);
}
async function loadVault(){try{const d=await api('/api/current/vault');Object.assign(LIVE.d,d);}catch{LIVE.d.vault_ok=false;}if(S.tab==='vault')render();}
document.getElementById('mNavBtn').onclick=()=>document.body.classList.toggle('m-nav-open');
document.getElementById('mNavBackdrop').onclick=()=>document.body.classList.remove('m-nav-open');
const collapseBtn=document.getElementById('railCollapseBtn');
if(collapseBtn)collapseBtn.onclick=()=>{const collapsed=document.body.classList.toggle('folio-side-collapsed');collapseBtn.setAttribute('aria-pressed',String(collapsed));};
window.addEventListener('keydown',event=>{
  if(event.key==='Escape'&&PEERS.open){PEERS.open=false;renderNav();return;}
  if((event.metaKey||event.ctrlKey)&&String(event.key||'').toLowerCase()==='k'){
    const searchEl=document.getElementById('sideSearch');
    if(!searchEl)return;
    event.preventDefault?.();
    if(document.body.classList.contains('folio-side-collapsed')){
      document.body.classList.remove('folio-side-collapsed');
      collapseBtn?.setAttribute('aria-pressed','false');
    }
    searchEl.focus?.();searchEl.select?.();
  }
});
try{document.body.dataset.theme=localStorage.getItem('ilson-theme')||'dark';}catch{document.body.dataset.theme='dark';}
window.addEventListener('message',event=>{
  const frame=document.getElementById('deviceFrame');
  if(event.origin!==location.origin||!frame||event.source!==frame.contentWindow)return;
  if(event.data?.type==='ilson-home-meta'){
    if(event.data.pendingCount!=null)META.pending=event.data.pendingCount;
    if(event.data.jobsCount!=null)META.jobs=event.data.jobsCount;
    if(event.data.reportsCount!=null)META.reports=event.data.reportsCount;
    if(event.data.registeredCount!=null)META.registered=event.data.registeredCount;
    if(event.data.attentionCount!=null)META.attention=event.data.attentionCount;
    applyNavMeta();
    return;
  }
  if(event.data?.type!=='ilson-device-page')return;
  const next=Object.keys(deviceTabs).find(tab=>deviceTabs[tab]===event.data.page);
  if(!next||!deviceTabs[S.tab])return;
  S.tab=next;document.body.classList.toggle('folio-home',next==='home');frame.dataset.view=deviceTabs[next];history.replaceState(null,'','?tab='+encodeURIComponent(next));renderNav();
});
window.addEventListener('storage',event=>{if(event.key==='ilson-theme')document.body.dataset.theme=event.newValue||'dark';});
if(typeof setInterval==='function')setInterval(updateRailClock,60000);
window.addEventListener('click',event=>{if(PEERS.open&&!event.target?.closest?.('.side-ws-wrap')){PEERS.open=false;renderNav();}});
(async()=>{try{
  const params=new URLSearchParams((location.hash||'').slice(1)),token=params.get('token');
  let session=null;
  if(token){history.replaceState(null,'',location.pathname+location.search);session=await api('/api/session',{token});}
  else session=await api('/api/session');
  if(session?.peers?.peers?.length){PEERS.current=session.peers.current||null;PEERS.list=session.peers.peers;}
  if(!initialTab){try{const overview=await api('/api/overview');S.tab=overview.box?.setup_state==='ready'?'sns':'home';}catch{S.tab='home';}}
  render();if(S.tab==='vault')await loadVault();
}catch(error){document.getElementById('main').textContent=error.message;}})();
