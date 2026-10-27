"use strict";
// 브라우저 기록은 새 이벤트를 추가한다. 이전 조사 결과는 수정하지 않는다.
window.ResearchThreads={
 key:"ilson-research-threads-v1",
 jobPrefix:"ilson-research-result-v1:",
 pendingKey:"ilson-research-pending-v1",
 read(){
  const rows=JSON.parse(localStorage.getItem(this.key)||"[]");
  if(!Array.isArray(rows))throw Error("조사 내역 형식을 확인하세요");
  // 완료 작업마다 별도 키를 써서 다른 탭의 read/modify/write가 결과를 덮어쓰지 않는다.
  for(let i=0;i<localStorage.length;i++){
   const key=localStorage.key(i);
   if(key?.startsWith(this.jobPrefix)){const row=JSON.parse(localStorage.getItem(key));if(row)rows.push(row);}
  }
  return rows.sort((a,b)=>String(a.saved_at).localeCompare(String(b.saved_at)));
 },
 append(thread,result,job){
  if(job&&!/^[a-f0-9]{32}$/.test(job))throw Error("실행 번호를 확인하세요");
  const key=job?this.jobPrefix+job:null;
  if(key){const saved=localStorage.getItem(key);if(saved)return JSON.parse(saved);}
  const event={id:job||crypto.randomUUID(),thread:thread||crypto.randomUUID(),saved_at:new Date().toISOString(),result};
  // 같은 작업의 중복 완료는 같은 키에 같은 조사방으로 수렴한다.
  if(key)localStorage.setItem(key,JSON.stringify(event));
  else localStorage.setItem(this.key,JSON.stringify([...this.readLegacy(),event]));
  return event;
 },
 readLegacy(){const rows=JSON.parse(localStorage.getItem(this.key)||"[]");if(!Array.isArray(rows))throw Error("조사 내역 형식을 확인하세요");return rows;},
 pending(){
  const row=JSON.parse(localStorage.getItem(this.pendingKey)||"null");
  if(!row)return null;
  if(row.version!==1||typeof row.ref!=="string"||!row.ref||typeof row.thread!=="string"||!row.thread||typeof row.question!=="string"||!row.question.trim()||row.question.length>400||!Number.isFinite(row.started)||!['day','week','month','year','all'].includes(row.period)||!['quick','deep'].includes(row.mode)||(row.id!==undefined&&!/^[a-f0-9]{32}$/.test(row.id)))throw Error("진행 중 조사 기록을 읽지 못했습니다. 새 조사를 열기 전에 기기의 실행 상태를 확인하세요.");
  return row;
 },
 remember(row){
  // 요청 본문·첨부 이미지·인증 토큰은 복구 기록에 넣지 않는다.
  const safe={version:1,ref:row.ref,thread:row.thread,question:row.question,period:row.period,mode:row.mode,videos:row.videos===true,started:row.started};
  if(row.id)safe.id=row.id;
  if(row.terminal)safe.terminal=row.terminal;
  localStorage.setItem(this.pendingKey,JSON.stringify(safe));return safe;
 },
 forget(ref){if(this.pending()?.ref===ref)localStorage.removeItem(this.pendingKey);},
 rooms(){const rooms=new Map();for(const row of this.read()){if(!row||typeof row.thread!=="string"||!row.result)continue;if(!rooms.has(row.thread))rooms.set(row.thread,{id:row.thread,title:row.result.question,events:[]});rooms.get(row.thread).events.push(row);}return [...rooms.values()].reverse();}
};
