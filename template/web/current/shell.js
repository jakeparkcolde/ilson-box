/* 운영 화면 렌더러의 호스트. 데모 회사/가상 계정/발행 기록은 넣지 않는다. */
const S={tab:new URLSearchParams(location.search).get('tab')||'sns',vaultSel:'',vaultGroup:'',vaultDoc:null};
const LIVE={on:true,d:{vault:[],vault_ok:true}};
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const typing=()=>{const n=document.activeElement;return ['TEXTAREA','SELECT'].includes(n?.tagName)||(n?.tagName==='INPUT'&&!['checkbox','radio','button','submit','reset'].includes(n.type));};
const renderIdle=()=>{if(!typing())render();};
async function api(path,body){const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await response.json();if(!response.ok){if(response.status===401)location.assign('/');throw Error(data.error||'요청을 완료하지 못했습니다.');}return data;}
const A={
  go(tab){if(tab==='inbox'){SNS_OPS.view='pending';tab='sns';}if(!['sns','sns-accounts','research','knowledge','vault','packs','learn','dashboard'].includes(tab))return;const learn=window.IlsonLearn;if(tab==='learn'&&S.tab==='learn'&&learn){document.body.classList.remove('m-nav-open');learn.menu();return;}if(S.tab==='learn'&&tab!=='learn')learn?.leave();const changed=S.tab!==tab;S.tab=tab;document.body.classList.remove('m-nav-open');render();if(changed){document.getElementById('main').scrollTop=0;window.scrollTo(0,0);if(tab==='learn')learn?.restore();}if(tab==='vault')loadVault();},
  pickVaultGroup(group){group=decodeURIComponent(group);S.vaultGroup=group;render();},
  pickVault(rel){rel=decodeURIComponent(rel);S.vaultSel=rel;S.vaultDoc=null;render();},
  async vaultOpenDoc(rel,name,base,id){rel=decodeURIComponent(rel);name=decodeURIComponent(name);base=decodeURIComponent(base);const folder=LIVE.d.vault.find(r=>r.rel===rel),file=folder?.files.find(f=>id?f.id===decodeURIComponent(id):f.name===name);if(!file)return;S.vaultDoc={id:file.id,rel,name,base,content:null};render();try{const data=await api('/api/current/document',{id:file.id});if(S.vaultDoc?.id===file.id){S.vaultDoc.content=data.content;S.vaultDoc.category=data.path.split("/").at(-2);render();}}catch(error){if(S.vaultDoc?.id===file.id){S.vaultDoc.content=error.message;render();}}},
  vaultEditStart(){if(S.vaultDoc?.content!=null){S.vaultDoc.draft=S.vaultDoc.content;S.vaultDoc.edit=true;render();}},
  vaultEditCancel(){if(S.vaultDoc){S.vaultDoc.edit=false;render();}},
  async vaultSave(){const doc=S.vaultDoc;if(!doc)return;doc.draft=document.getElementById('vaultEditor').value;try{const result=await api('/api/workspace/documents',{title:doc.name,content:doc.draft.startsWith('# '+doc.name+'\n')?doc.draft.slice(doc.name.length+3).trimStart():doc.draft,category:['company','research','knowledge','sns'].includes(doc.category)?doc.category:'company',previous_id:doc.id});await loadVault();const folder=LIVE.d.vault.find(f=>f.files.some(d=>d.id===result.id));S.vaultSel=folder.rel;S.vaultGroup=folder.group;await A.vaultOpenDoc(vaultArg(folder.rel),vaultArg(result.title),'box',vaultArg(result.id));S.vaultDoc.msg='원본과 연결된 새 기록으로 저장했습니다.';render();}catch(error){doc.msg=error.message;render();}},
  noop(event){event?.preventDefault();}
};
function renderNav(){const items=[{group:'일'},{id:'sns',icon:'send',label:'SNS 운영'},{id:'sns-accounts',icon:'link',label:'SNS 계정 관리'},{id:'vault',icon:'archive',label:'서류함'},{id:'dashboard',icon:'activity',label:'자동화·컴퓨터 현황'},{group:'플랫폼'},{id:'research',icon:'search',label:'리서치'},{id:'knowledge',icon:'book-open',label:'지식 훔치기'},{id:'packs',icon:'package',label:'팩 보관함'},{group:'배우기'},{id:'learn',icon:'graduation-cap',label:'Claude 배우기'}];document.getElementById('sidebar').innerHTML=`<div class="brand"><span style="font-family:Georgia,'Times New Roman',serif;font-size:15px;letter-spacing:.28em;font-weight:500;color:var(--ink)" aria-label="ILSON">ILSON<span style="color:#828fff;font-size:12px;margin-left:1px;vertical-align:1px">✦</span></span><span style="margin-left:auto;font-family:var(--font-mono);font-size:10px;color:var(--ink4)">local</span></div>${items.map(n=>n.group?`<div class="nav-group">${n.group}</div>`:`<button class="nav-item${S.tab===n.id?' on':''}"${S.tab===n.id?' aria-current="page"':''} onclick="A.go('${n.id}')"><i data-lucide="${n.icon}"></i><span style="flex:1">${n.label}</span></button>`).join('')}<div style="flex:1"></div><a class="nav-item" href="/people">직원 · 조직도 · 스킬</a><a class="nav-item" href="/#device">기기 관리</a><div class="side-user"><span>이 미니의 일손</span><button id="themeToggle" aria-label="테마 전환">◐</button></div>`;document.getElementById('themeToggle').onclick=()=>{const theme=document.body.dataset.theme==='light'?'dark':'light';document.body.dataset.theme=theme;try{localStorage.setItem('ilson-theme',theme);}catch{}};}
function render(){
  const main=document.getElementById('main');
  const inputState=[...main.querySelectorAll('input[id],textarea[id]')].filter(n=>n.type!=='password').map(n=>({id:n.id,value:n.value,focus:n===document.activeElement,start:n.selectionStart,end:n.selectionEnd}));
  const keep=snsCaptureView();
  history.replaceState(null,'','?tab='+encodeURIComponent(S.tab)+(S.tab==='learn'&&window.IlsonLearn?IlsonLearn.query():''));
  renderNav();
  if(S.tab==='dashboard'){
    // Keep the mounted view through unrelated async shell renders.
    IlsonDashboard.mount(main);
  }else{
    window.IlsonDashboard?.leave();
    if(!IlsonPacks.current(S.tab)){
      main.innerHTML=({sns:screenSnsOperations,'sns-accounts':screenSnsAccounts,vault:screenVaultAllLive,research:()=>IlsonPacks.render('research','pack-library'),knowledge:()=>IlsonPacks.render('knowledge','pack-library'),packs:()=>IlsonPacks.render('packs','pack-library'),learn:()=>window.IlsonLearn?IlsonLearn.render():''}[S.tab]||screenSnsOperations)();
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
try{document.body.dataset.theme=localStorage.getItem('ilson-theme')||'dark';}catch{document.body.dataset.theme='dark';}
(async()=>{try{await api('/api/session');render();if(S.tab==='vault')await loadVault();}catch(error){document.getElementById('main').textContent=error.message;}})();
