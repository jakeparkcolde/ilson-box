"use strict";
const packs = [
{id:"motion",name:"모션그래픽 제작",category:"marketing",symbol:"▶",color:"#b3a5da",wash:"#ede8f7",motion:true,desc:"제품 소개와 설명을 움직이는 영상으로. 팩을 꽂고 이 화면에서 무음 소개 영상을 만들어보세요.",need:"일손 Box 최신 업데이트 · 사용자 Claude 계정",cost:"사용자 LLM 구독 사용 · 추가 생성 서비스 비용 별도",features:["주제와 자료로 영상 구성·장면 제작","HyperFrames 미리보기 후 검토·렌더","10·15·30초 무음 텍스트 영상 · MP4 저장"]},
{id:"sns",name:"SNS 운영",category:"marketing",symbol:"↗",color:"#b1a1d0",wash:"#ece6f3",desc:"글 준비부터 승인된 게시물의 예약 발행까지.",need:"Instagram · Threads 계정 연결",cost:"LLM 구독과 채널별 이용 조건 확인",features:["채널에 맞는 게시물 초안 준비","사장님 승인 후 예약 발행","발행 결과와 연결 상태 확인"]},
{id:"research",name:"시장조사",category:"insight",symbol:"⌕",color:"#9cbacc",wash:"#e4edf1",desc:"궁금한 시장과 경쟁사 소식을 출처와 함께.",need:"검색 계정 · LLM 연결",cost:"검색 크레딧과 사용자 LLM 구독 사용",features:["질문에 맞는 공개 웹 검색","출처를 붙인 조사 보고","확인된 사실과 추론 구분"]},
{id:"meeting",name:"회의 · 통화",category:"office",symbol:"≋",color:"#dac38b",wash:"#f3eddd",desc:"길었던 대화에서 결정과 다음 할 일을 정리해요.",need:"회의·통화 전사 파일",cost:"사용자 LLM 구독 사용",features:["전사 파일에서 회의 내용 정리","담당자와 후속 업무 후보 추출","확인 후 업무 등록"]},
{id:"content",name:"콘텐츠 제작",category:"marketing",symbol:"✺",color:"#dca799",wash:"#f4e6df",desc:"브랜드의 이야기를 글과 카드 콘텐츠로.",need:"브랜드 자료 · 생성 도구 연결",cost:"이미지·영상 생성 서비스별 비용 확인",features:["브랜드에 맞는 글 초안","카드뉴스와 숏폼 제작 흐름","검토할 결과물 미리보기"]},
{id:"price",name:"가격 감시",category:"insight",symbol:"↘",color:"#a8bc90",wash:"#e8eddf",desc:"관심 상품의 가격을 살피고 변화 후보를 알려줘요.",need:"상품 URL · 가격 기준 설정",cost:"검색·수집 방식에 따라 비용 확인",features:["지정 상품의 공개 판매가 조사","기준과 비교한 확인 대상 정리","안내 문안 준비 후 승인 요청"]},
{id:"inventory",name:"재고 점검",category:"office",symbol:"▦",color:"#b5b4ab",wash:"#e9e9e3",desc:"내가 쓰는 재고 자료로 부족 품목을 한눈에.",need:"엑셀·시트 연결부 추가 개발 필요",cost:"연결 방식 확정 후 안내",features:["현재는 범용 팩 설계 단계","기존 FLOWWORK 연동은 사내용","엑셀·시트용 입력 검증과 연결부 필요"]}
];
const grid=document.getElementById("packGrid"), dialog=document.getElementById("packDialog");
let chosen=packs[0],busy=false;
fetch("downloads/research-pack-0.15.3.zip",{method:"HEAD"}).then(r=>{if(r.ok&&r.headers.get("content-type")?.includes("zip")){packs.find(p=>p.id==="research").download=true;render(document.querySelector("[data-filter].selected").dataset.filter)}}).catch(()=>{});
function render(filter="all"){const shown=packs.filter(p=>filter==="all"||p.category===filter);document.getElementById("packCount").textContent=`${shown.length}개의 팩 · ${shown.filter(p=>p.motion).length}개 웹 연결 · ${shown.filter(p=>p.download).length}개 설치 파일 제공`;grid.replaceChildren();for(const [i,p] of shown.entries()){const button=document.createElement("button");button.className="pack-card";button.style.setProperty("--color",p.color);button.style.setProperty("--wash",p.wash);button.innerHTML=`<div class="pack-art" aria-hidden="true"><div class="mini-cart"><div class="mini-label"><small>ILSON / WORK PACK</small><b>${p.name}</b><span>${p.symbol}</span></div></div><span class="art-number">PACK / ${String(packs.indexOf(p)+1).padStart(2,"0")}</span></div><div class="pack-meta"><span>${{marketing:"마케팅",office:"업무 정리",insight:"조사 · 분석"}[p.category]}</span><span>${p.motion?"꽂아서 사용 · 베타":p.download?"Box 설치 파일 제공":"준비 중"}</span></div><h3>${p.name} 팩</h3><p>${p.desc}</p><div class="card-bottom"><span>설명과 연결 조건</span><span>↗</span></div>`;button.addEventListener("click",()=>details(p));grid.append(button)}}
function details(p){chosen=p;document.getElementById("demoHelp").hidden=!!p.motion;document.getElementById("tryPack").hidden=!!p.motion;document.getElementById("downloadPack").hidden=!p.download;document.getElementById("downloadHelp").hidden=!p.download;const detail=document.getElementById("detail");detail.style.setProperty("--wash",p.wash);detail.innerHTML=`<div class="detail-symbol" aria-hidden="true">${p.symbol}</div><p class="eyebrow">ILSON WORK PACK · ${p.motion?"꽂아서 사용 · 베타":p.download?"Box 설치 파일 제공":"준비 중"}</p><h2>${p.name} 팩</h2><p class="detail-desc">${p.desc}</p><ul class="detail-list">${p.features.map(x=>`<li>${x}</li>`).join("")}</ul><div class="detail-info"><b>시작에 필요한 것</b><br>${p.need}<br><br><b>이용 비용</b><br>${p.cost}</div>${p.motion?`<div id="motionPanel"><p>팩 상태를 확인하는 중…</p></div>`:""}`;dialog.showModal();if(p.motion)motionPanel()}
document.querySelectorAll("[data-filter]").forEach(button=>button.addEventListener("click",()=>{document.querySelectorAll("[data-filter]").forEach(x=>{const on=x===button;x.classList.toggle("selected",on);x.setAttribute("aria-pressed",String(on))});render(button.dataset.filter)}));
document.getElementById("tryPack").addEventListener("click",()=>{if(busy)return;busy=true;dialog.close();const playground=document.querySelector(".playground");playground.classList.remove("inserting");const cart=document.getElementById("demoPack");cart.style.background=chosen.color;document.getElementById("demoName").textContent=chosen.name;document.getElementById("demoSymbol").textContent=chosen.symbol;document.getElementById("screenTitle").textContent="팩을 꽂는 중…";document.getElementById("screenText").textContent="모션 체험 · 설치하지 않습니다";playground.scrollIntoView({block:"center"});requestAnimationFrame(()=>{playground.classList.add("inserting");setTimeout(()=>{document.getElementById("screenIcon").textContent=chosen.symbol;document.getElementById("screenTitle").textContent=`${chosen.name} 팩`;document.getElementById("screenText").textContent="체험 완료 · 실제 설치는 준비 중";document.getElementById("sceneCaption").textContent=`${chosen.name}: ${chosen.need}`;busy=false},matchMedia("(prefers-reduced-motion: reduce)").matches?0:1550)})});
render();document.body.classList.add("loaded");

let motionTimer;
async function motionApi(path,data){
 const response=await fetch('/api/motion/'+path,{method:data?'POST':'GET',headers:data?{'Content-Type':'application/json'}:undefined,body:data?JSON.stringify(data):undefined});
 let value;try{value=await response.json()}catch{throw Error('일손 관리자를 업데이트한 뒤 다시 열어주세요.')}
 if(!response.ok)throw Error(value.error||value.message||'요청하지 못했습니다. 관리자 연결 상태를 확인해주세요.');return value;
}
function motionMessage(message){const el=document.getElementById('motionStatus');if(el)el.textContent=message}
async function motionPanel(){
 clearTimeout(motionTimer);const panel=document.getElementById('motionPanel');
 panel.innerHTML='<p id="motionStatus" role="status">팩 상태를 확인하는 중…</p><button class="primary" id="motionInstall" hidden>팩 꽂기</button><form id="motionForm" hidden><label>어떤 영상을 만들까요?<textarea id="motionBrief" required maxlength="2000" rows="4" style="width:100%;box-sizing:border-box" placeholder="우리 가게 신메뉴를 소개하는 영상을 만들어줘. 메뉴는 딸기 라테, 가격은 6천 원이야."></textarea></label><label>영상 길이 <select id="motionDuration"><option value="10">10초</option><option value="15" selected>15초</option><option value="30">30초</option></select></label><p class="fine">무음 · 가로형 텍스트 모션그래픽. 문구는 사용자 Claude 계정으로 구성합니다.</p><button class="primary" type="submit" id="motionCreate">미리보기 만들기</button></form><div id="motionResult"></div>';
 const install=document.getElementById('motionInstall'),form=document.getElementById('motionForm');
 install.onclick=()=>submitMotion('install',{});
 form.onsubmit=e=>{e.preventDefault();submitMotion('create',{brief:document.getElementById('motionBrief').value,duration:Number(document.getElementById('motionDuration').value)})};
 try{const state=await motionApi('status');install.hidden=state.installed;form.hidden=!state.installed;
 motionMessage(state.installed?'팩이 연결되었습니다. 제작 요청을 입력하세요.':'팩을 꽂으면 영상 도구를 자동으로 준비합니다. 처음에는 몇 분 걸릴 수 있습니다.');
 const active=state.jobs.find(j=>['queued','running'].includes(j.status));if(active){watchMotion(active.id);return}
 const recent=state.jobs.find(j=>j.status==='done'&&j.result?.project_id);if(recent)await showMotion(recent.result);
 if(state.jobs[0]?.status==='failed')motionMessage(state.jobs[0].error);
 }catch(error){motionMessage(error.message)}
}
function motionBusy(on){for(const id of ['motionInstall','motionCreate','motionRender']){const el=document.getElementById(id);if(el)el.disabled=on}}
async function submitMotion(kind,data){motionBusy(true);try{const job=await motionApi(kind,data);watchMotion(job.id)}catch(error){motionMessage(error.message);motionBusy(false)}}
async function watchMotion(id){
 clearTimeout(motionTimer);motionBusy(true);
 try{const job=await motionApi('jobs/'+id);const labels={queued:'순서를 기다리고 있어요.',installing:'영상 도구와 제작 스킬을 준비하고 있어요.',writing:'영상 문구와 장면을 구성하고 있어요.',checking:'영상 구성을 확인하고 있어요.',rendering:'MP4 영상을 저장하고 있어요.',running:'작업을 시작하고 있어요.'};
 if(job.status==='failed'){motionMessage(job.error);motionBusy(false);return}
 if(job.status==='done'){if(job.kind==='motion_install'){await motionPanel();return}motionBusy(false);await showMotion(job.result);motionMessage(job.kind==='motion_render'?'영상 저장이 완료되었습니다.':'미리보기를 확인한 뒤 MP4 저장을 눌러주세요.');return}
 motionMessage(labels[job.stage]||'작업 중입니다.');if(dialog.open)motionTimer=setTimeout(()=>watchMotion(id),2000);
 }catch(error){motionMessage(error.message);motionBusy(false)}
}
async function showMotion(result){
 const area=document.getElementById('motionResult');if(!area)return;area.replaceChildren();
 if(result.download){const a=document.createElement('a');a.className='primary';a.textContent='MP4 다운로드';a.href='/api/motion/projects/'+result.project_id+'/download';a.download='일손-모션그래픽.mp4';area.append(a);return}
 const preview=await motionApi('projects/'+result.project_id+'/preview');const frame=document.createElement('iframe');frame.title='영상 미리보기';frame.setAttribute('sandbox','allow-scripts');frame.style='width:100%;aspect-ratio:16/9;border:0';frame.srcdoc=preview.html;area.append(frame);
 const button=document.createElement('button');button.id='motionRender';button.className='primary';button.textContent='이 구성으로 MP4 저장';button.onclick=()=>submitMotion('render',{project_id:result.project_id,approved:true});area.append(button);
}
dialog.addEventListener('close',()=>clearTimeout(motionTimer));
