import{D as m,s,S as u,b as w}from"../../pages-CLJdDbBh.js";const p="(max-width: 979px)";let c="",r=h();function h(){return s(Object.fromEntries(new URLSearchParams(window.location.search).entries()))||m}function b(){const e=c.trim().toLowerCase();return e?u.filter(t=>`${t.title} ${t.summary} ${t.id}`.toLowerCase().includes(e)):u}function d(){if(typeof window>"u")return!1;try{const e=window.parent&&window.parent!==window?window.parent:window;return typeof e.matchMedia=="function"&&e.matchMedia(p).matches}catch{return typeof window.matchMedia=="function"&&window.matchMedia(p).matches}}function y(e){r=e,a(),window.parent?.postMessage({type:"maverick.widget.open-app",app_id:"settings",params:{app_page:w(e),page_id:e}},window.location.origin),d()&&window.parent?.postMessage({type:"maverick.shell.sidebar.close"},window.location.origin)}function v(e){if(e.origin!==window.location.origin||!e.data||typeof e.data!="object")return;const t=e.data;if(t.type==="maverick.widget.context-changed"){const n=s(E(t.context?.content?.payload));n&&(r=n,a());return}if(t.type==="maverick.app.selection-changed"&&t.owner_app_id==="settings"){const n=s(t.selection||{});n&&(r=n,a())}}function E(e){if(!e||typeof e!="object"||Array.isArray(e))return{};const t=e.active_app_params;return t&&typeof t=="object"&&!Array.isArray(t)?t:{}}function i(e){return e.replace(/[&<>"']/g,t=>{switch(t){case"&":return"&amp;";case"<":return"&lt;";case">":return"&gt;";case'"':return"&quot;";default:return"&#39;"}})}function f(e){return i(e)}function a(){const e=document.getElementById("settings-sidebar-root");if(!e)return;const t=b();e.innerHTML=`<main class="settings-sidebar-widget ${d()?"is-shell-mobile":""}">
    <div class="settings-sidebar-search-frame">
      <span class="material-symbols-rounded" aria-hidden="true">search</span>
      <input
        aria-label="Search settings pages"
        class="settings-sidebar-search"
        placeholder="Search pages"
        value="${f(c)}"
      />
    </div>
    <div class="settings-sidebar-list">
      ${t.length?t.map(_).join(""):'<p class="settings-sidebar-empty">No pages found.</p>'}
    </div>
  </main>`,S()}function _(e){return`<button class="settings-sidebar-row ${e.id===r?"is-active":""}" data-page-id="${f(e.id)}" type="button">
    <span class="material-symbols-rounded settings-sidebar-row__icon" aria-hidden="true">${i(e.icon)}</span>
    <span class="settings-sidebar-row__copy">
      <strong>${i(e.title)}</strong>
      <span>${i(e.summary)}</span>
    </span>
  </button>`}function S(){const e=document.querySelector(".settings-sidebar-search");e?.addEventListener("input",()=>{c=e.value,a()}),document.querySelectorAll("[data-page-id]").forEach(t=>{t.addEventListener("click",()=>{const n=s({page_id:t.dataset.pageId||""});n&&y(n)})})}function L(){let e=null;document.addEventListener("touchstart",t=>{if(!d()||t.touches.length!==1||A(t.target)){e=null;return}const n=t.touches[0];e={id:n.identifier,x:n.clientX,y:n.clientY}},{passive:!0}),document.addEventListener("touchmove",t=>{if(!e)return;const n=Array.from(t.changedTouches).find(g=>g.identifier===e?.id);if(!n)return;const o=n.clientX-e.x,l=Math.abs(n.clientY-e.y);Math.abs(o)>12&&Math.abs(o)>l&&(t.preventDefault(),t.stopPropagation()),o<=-72&&l<=48&&(t.preventDefault(),t.stopPropagation(),window.parent?.postMessage({type:"maverick.shell.sidebar.close"},window.location.origin),e=null)},{passive:!1}),document.addEventListener("touchcancel",()=>{e=null},{passive:!0}),document.addEventListener("touchend",()=>{e=null},{passive:!0})}function A(e){return e instanceof Element&&!!e.closest('input, textarea, select, [contenteditable="true"], [data-no-sidebar-swipe]')}window.addEventListener("message",v);L();a();
