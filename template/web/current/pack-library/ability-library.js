"use strict";
(()=>{
  const root=document.getElementById("savedAbilities"),key="ilson-ability-library-v1";
  if(!root)return;
  let rows;
  try{rows=JSON.parse(localStorage.getItem(key)||"[]");if(!Array.isArray(rows))throw Error()}catch{root.textContent="저장된 능력을 읽지 못했습니다. 결과 JSON을 보관해 주세요.";return}
  if(!rows.length){root.textContent="아직 만든 능력이 없어요. ‘지식 훔치기’에서 링크를 새 능력으로 만들어보세요.";return}
  for(const result of rows){try{IlsonAbility.validate(result);const card=document.createElement("article");card.className="saved-ability";const title=document.createElement("h3");title.textContent=result.skill.title;const description=document.createElement("p");description.textContent=result.skill.description;const badge=document.createElement("p");badge.textContent=`초안 · 시험 미실행 · ${result.sources.length}개 출처`;badge.className="fine";const link=document.createElement("a");link.textContent="초안 검토 ↗";const embedded=new URLSearchParams(location.search).get("embedded")==="1";link.href="knowledge.html?ability="+encodeURIComponent(result.library_id)+(embedded?"&embedded=1":"");const button=document.createElement("button");button.textContent="스킬 ZIP 받기 ↓";button.addEventListener("click",()=>IlsonAbility.download(IlsonAbility.zip(result),result.skill.name+"-draft.zip"));card.append(title,description,badge,link,button);root.append(card)}catch{const message=document.createElement("p");message.textContent="형식을 확인하지 못한 저장 항목이 있습니다. 원본 파일은 보존됩니다.";root.append(message)}}
})();
