"use strict";
// 두 일손 화면에서 같은 팩 화면을 재사용한다. 계정·결재 API는 이 화면에 전달하지 않는다.
window.IlsonPacks = {
  render(tab, base) {
    const research = tab === "research";
    const title = tab === "knowledge" ? "지식 훔치기" : research ? "리서치" : "팩 보관함";
    const file = tab === "knowledge" ? "knowledge.html" : research ? "research.html" : "packs.html";
    return `<section class="ilson-pack-pane${research ? " ilson-research-pane" : ""}">${research ? `<style>
/* 모바일 리서치는 프레임 높이를 화면에 맞추고 부모 메뉴를 입력창에서 분리한다. */
@media(max-width:720px){
 body:has(.ilson-research-pane) .app{height:100vh;height:100dvh}
 .ilson-research-pane{height:100vh;height:100dvh;min-height:0}
 .ilson-research-pane #ilsonPackFrame{height:100%!important;min-height:0!important;border-radius:0!important}
 .main:has(>.ilson-research-pane){min-width:0;overflow:hidden}
 body:has(.ilson-research-pane) .m-nav-btn{top:calc(6px + env(safe-area-inset-top,0px));right:12px;bottom:auto;left:auto;width:44px;height:44px;border-radius:9px;box-shadow:none}
}
</style>` : ""}<iframe id="ilsonPackFrame" data-pack-view="${tab}" data-pack-revision="20261003-mobile1"
      title="일손 ${title}" src="${base}/${file}?embedded=1&v=20261003-mobile1"
      style="display:block;width:100%;height:calc(100vh - 100px);min-height:650px;border:0;border-radius:14px;background:#f6f5f0"></iframe></section>`;
  },
  current(tab) {
    const frame = document.getElementById("ilsonPackFrame");
    return ["packs", "research", "knowledge"].includes(tab) && frame?.dataset.packView === tab && frame?.dataset.packRevision === "20261003-mobile1";
  }
};
window.addEventListener("message", event => {
  const frame = document.getElementById("ilsonPackFrame");
  if (event.origin !== location.origin || !frame || event.source !== frame.contentWindow ||
      event.data?.type !== "ilson-pack-tab" || !["packs", "research", "knowledge"].includes(event.data.tab)) return;
  if (typeof A !== "undefined") A.go(event.data.tab);
});
