const vaultArg=value=>encodeURIComponent(String(value)).replace(/\'/g,"%27");
const VAULT_TYPE_STYLE = {
  '커밋 연대기': { bg: 'rgba(78,132,255,.15)', co: '#5c8dff' },
  '공지': { bg: 'var(--success-bg)', co: 'var(--flow-deep)' },
  '지표': { bg: 'var(--warning-bg)', co: 'var(--warning)' },
  '기타': { bg: 'var(--bg-subtle)', co: 'var(--text-muted)' },
};
/* ════════ 회사 서류함 (라이브 — wiki/systems 실문서, 좌우 분할 편집) ════════ */
/* 회사 서류함 — 묶음 → 서랍 → 문서 (3층).
   폴더 안에 또 폴더가 있어서(agents 9개, 커뮤니티 10개…) 2층으로는 안 담긴다.
   예전엔 wiki/systems 한 폴더(7개)만 보여 줬다 — 이름은 「회사 서류함」인데
   볼트 477개 중 1.5%였다 (2026-08-12 실측). */
function screenVaultAllLive(){
  const tree = LIVE.d.vault || [];
  // 못 읽는 것과 비어 있는 것은 다르다 — 빈 화면은 "기록이 없다"로 읽힌다.
  if (LIVE.d.vault_ok === false) return `<div class="screen">
    <div class="eyebrow">회사 서류함</div>
    <div class="h1row"><h1 class="title">볼트에 연결되지 않았어요</h1></div>
    <div class="card" style="padding:20px;font-size:13px;line-height:1.7;color:var(--text-body)">
      서류가 없는 게 아니라 <b>볼트를 못 읽고 있어요.</b> 이 미니의 서류 저장 공간과 접근 권한을 확인해 주세요.
    </div></div>`;

  const sel = tree.find(v => v.rel === S.vaultSel) || tree[0];
  const openG = S.vaultGroup || (sel && sel.group) || '';
  const doc = S.vaultDoc;   // {rel, base, name, content|null, edit, draft, msg}
  const groups = [];
  tree.forEach(d => { if (!groups.includes(d.group)) groups.push(d.group); });
  const nDocs = tree.reduce((a, d) => a + d.n, 0);

  return `<div class="screen">
    <div class="eyebrow">회사 서류함</div>
    <div class="h1row" style="margin-bottom:8px"><h1 class="title">회사의 기억 — 문서 ${nDocs}개</h1></div>
    <div style="font-size:13px;color:var(--text-muted);margin-bottom:20px">직원들이 일하며 쌓은 기록이에요. 볼트(옵시디언)의 실제 문서를 보여 줍니다. 수정하면 원본과 연결된 새 기록이 생깁니다.</div>
    <div style="display:grid;grid-template-columns:250px 1fr;gap:16px;align-items:start">
      <div>
        ${groups.map(g => {
          const mine = tree.filter(d => d.group === g);
          const on = g === openG;
          return `
        <div class="card" style="overflow:hidden;margin-bottom:8px">
          <button onclick="A.pickVaultGroup('${vaultArg(g)}')" style="display:flex;align-items:center;gap:8px;width:100%;text-align:left;padding:11px 14px;border:none;cursor:pointer;background:${on ? 'var(--s2)' : 'transparent'}">
            <i data-lucide="${on ? 'chevron-down' : 'chevron-right'}" style="width:14px;height:14px;color:var(--text-muted)"></i>
            <span style="flex:1;font-weight:700;font-size:13.5px">${esc(g)}</span>
            <span class="mono" style="font-size:11.5px;color:var(--text-faint)">${mine.reduce((a, d) => a + d.n, 0)}</span>
          </button>
          ${on ? mine.map(v => { const cur = sel && v.rel === sel.rel; return `
            <button onclick="A.pickVault('${vaultArg(v.rel)}')" style="display:flex;align-items:center;gap:8px;width:100%;text-align:left;padding:9px 14px 9px 20px;border:none;border-top:1px solid var(--border);cursor:pointer;background:${cur ? 'var(--success-bg)' : 'transparent'};position:relative">
              ${cur ? '<span style="position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--flow-green)"></span>' : ''}
              <i data-lucide="folder" style="width:13px;height:13px;color:var(--flow-deep);flex-shrink:0"></i>
              <span style="flex:1;font-size:12.5px;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(v.name)}</span>
              <span class="mono" style="font-size:11px;color:var(--text-faint)">${v.n}</span>
            </button>`; }).join('') : ''}
        </div>`; }).join('') || '<div class="card" style="padding:24px;text-align:center;font-size:13px;color:var(--text-faint)">아직 기록이 없어요.</div>'}
      </div>
      <div style="display:grid;grid-template-columns:minmax(280px,340px) 1fr;gap:14px;align-items:start">
        <div>
          ${sel ? `
          <div class="card" style="padding:14px 16px;margin-bottom:12px">
            <div style="display:flex;align-items:center;gap:6px;margin-bottom:6px">
              <span class="chip" style="background:var(--bg-subtle);color:var(--text-muted);font-size:11px">${esc(sel.label)}</span>
              ${sel.writable
                ? '<span class="chip" style="background:var(--success-bg);color:var(--flow-deep);font-size:11px">수정 가능</span>'
                : '<span class="chip" style="background:var(--bg-subtle);color:var(--text-muted);font-size:11px"><i data-lucide="lock" style="width:10px;height:10px"></i>읽기 전용</span>'}
            </div>
            <div style="font-size:12.5px;line-height:1.7;color:var(--text-body)">${esc(sel.rule)}</div>
            ${(sel.readers || []).length ? `<div style="font-size:12px;color:var(--text-muted);margin-top:6px">읽는 직원: ${esc(sel.readers.join(' · '))}</div>` : ''}
          </div>
          <div class="card" style="overflow:hidden;max-height:60vh;overflow-y:auto">
            ${sel.files.map((f,i) => { const st = VAULT_TYPE_STYLE[f.type] || VAULT_TYPE_STYLE['기타']; const on = doc && doc.rel === sel.rel && doc.id === f.id; return `
              <button onclick="A.vaultOpenDoc('${vaultArg(sel.rel)}','${vaultArg(f.name)}','${vaultArg(sel.base)}','${vaultArg(f.id)}')" style="display:flex;align-items:center;gap:10px;width:100%;text-align:left;border:none;background:${on ? 'var(--s2)' : 'transparent'};padding:11px 14px;cursor:pointer;position:relative;${i < sel.files.length-1 ? 'border-bottom:1px solid var(--border)' : ''}">
                ${on ? '<span style="position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--flow-green)"></span>' : ''}
                <i data-lucide="file-text" style="width:14px;height:14px;color:var(--text-faint);flex-shrink:0"></i>
                <span style="flex:1;font-size:13px;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(f.name)}</span>
                ${f.type !== '기타' ? `<span class="chip" style="background:${st.bg};color:${st.co};font-size:10px;flex-shrink:0">${f.type}</span>` : ''}
              </button>`; }).join('')}
          </div>` : ''}
        </div>
        <div class="card" style="padding:0;overflow:hidden;min-height:420px;display:flex;flex-direction:column">
          ${doc ? `
            <div style="display:flex;align-items:center;gap:10px;padding:12px 16px;border-bottom:1px solid var(--border);background:var(--bg-subtle)">
              <i data-lucide="file-text" style="width:15px;height:15px;color:var(--flow-deep)"></i>
              <span style="flex:1;font-weight:700;font-size:13.5px;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(doc.name)}</span>
              ${!(sel && sel.writable) ? ''
              : doc.edit ? `
                <button class="btn" style="height:30px;background:var(--card);border:1px solid var(--border);font-size:12px" onclick="A.vaultEditCancel()">취소</button>
                <button class="btn btn-primary" style="height:30px;font-size:12px" onclick="A.vaultSave()">저장</button>`
              : `<button class="btn btn-ghost" style="height:30px;font-size:12px" onclick="A.vaultEditStart()"><i data-lucide="pencil" style="width:12px;height:12px"></i>수정</button>`}
            </div>
            ${doc.edit
              ? `<textarea id="vaultEditor" style="flex:1;border:none;outline:none;resize:none;padding:16px 18px;font-size:13px;line-height:1.75;font-family:var(--font-mono);background:var(--card);min-height:380px">${esc(doc.draft ?? doc.content ?? '')}</textarea>`
              : `<div style="flex:1;overflow-y:auto;padding:16px 18px;font-size:13px;line-height:1.75;white-space:pre-wrap;font-family:var(--font-mono);max-height:62vh">${doc.content === null ? '불러오는 중…' : esc(doc.content)}</div>`}
            <div style="padding:8px 16px;border-top:1px solid var(--border);font-size:11px;color:var(--text-faint)">
              ${esc(doc.msg || (doc.edit ? '저장하면 원본을 보존하고 연결된 새 기록을 만듭니다.'
                                         : (sel && sel.rel && sel.rel !== '.' ? sel.rel + ' / ' : '') + doc.name))}
            </div>`
          : `<div style="flex:1;display:flex;align-items:center;justify-content:center;font-size:13px;color:var(--text-faint)">왼쪽에서 문서를 고르면 여기서 볼 수 있어요</div>`}
        </div>
      </div>
    </div>
  </div>`;
}
