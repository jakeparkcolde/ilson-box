"use strict";
// 같은 일손 화면 안에서는 중복 헤더를 숨기고 메뉴 전환을 부모에게 전달한다.
if (new URLSearchParams(location.search).get("embedded") === "1" && window.parent !== window) {
  document.documentElement.classList.add("embedded");
  // Embedded research uses the shell navigation and theme; standalone keeps its own.
  if (document.getElementById("researchTheme")) {
    document.getElementById("toggleThreads").textContent = "조사 내역";
    const syncTheme = () => applyResearchTheme(window.parent.document.body.dataset.theme);
    syncTheme();
    const observer = new MutationObserver(syncTheme);
    observer.observe(window.parent.document.body, {attributes: true, attributeFilter: ["data-theme"]});
    window.addEventListener("pagehide", () => observer.disconnect());
    window.addEventListener("pageshow", () => {
      syncTheme();
      observer.observe(window.parent.document.body, {attributes: true, attributeFilter: ["data-theme"]});
    });
  }
  document.addEventListener("click", event => {
    const anchor = event.target.closest("a[href]");
    if (!anchor || anchor.hasAttribute("download")) return;
    const url = new URL(anchor.href, location.href);
    const page = url.pathname.split("/").pop();
    if (url.origin !== location.origin || !["packs.html", "research.html", "knowledge.html"].includes(page)) return;
    if (url.searchParams.has("ability")) return;
    event.preventDefault();
    window.parent.postMessage({type: "ilson-pack-tab", tab: ({"packs.html":"packs","research.html":"research","knowledge.html":"knowledge"})[page]}, location.origin);
  });
}
