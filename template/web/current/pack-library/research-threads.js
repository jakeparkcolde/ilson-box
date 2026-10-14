"use strict";
// 브라우저 기록은 새 이벤트를 추가한다. 이전 조사 결과는 수정하지 않는다.
window.ResearchThreads={
 key:"ilson-research-threads-v1",
 read(){const rows=JSON.parse(localStorage.getItem(this.key)||"[]");if(!Array.isArray(rows))throw Error("조사 내역 형식을 확인하세요");return rows;},
 append(thread,result){const event={id:crypto.randomUUID(),thread:thread||crypto.randomUUID(),saved_at:new Date().toISOString(),result};localStorage.setItem(this.key,JSON.stringify([...this.read(),event]));return event;},
 rooms(){const rooms=new Map();for(const row of this.read()){if(!row||typeof row.thread!=="string"||!row.result)continue;if(!rooms.has(row.thread))rooms.set(row.thread,{id:row.thread,title:row.result.question,events:[]});rooms.get(row.thread).events.push(row);}return [...rooms.values()].reverse();}
};
