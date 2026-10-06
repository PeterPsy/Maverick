import{D as g,s as i,i as h,S as u,c as w}from"../../pages-DUQjEraw.js";const p="(max-width: 979px)";let c="",r=b();function b(){return i(Object.fromEntries(new URLSearchParams(window.location.search).entries()))||g}function y(){const e=c.trim().toLowerCase();return e?u.filter(t=>`${t.title} ${t.summary} ${t.id}`.toLowerCase().includes(e)):u}function d(){if(typeof window>"u")return!1;try{const e=window.parent&&window.parent!==window?window.parent:window;return typeof e.matchMedia=="function"&&e.matchMedia(p).matches}catch{return typeof window.matchMedia=="function"&&window.matchMedia(p).matches}}function v(e){r=e,n(),window.parent?.postMessage({type:"maverick.widget.open-app",app_id:"settings",params:{app_page:w(e),page_id:e}},"*"),d()&&window.parent?.postMessage({type:"maverick.shell.sidebar.close"},"*")}function E(e){if(!h(e)||!e.data||typeof e.data!="object")return;const t=e.data;if(t.type==="maverick.widget.context-changed"){const a=i(_(t.context?.content?.payload));a&&(r=a,n());return}if(t.type==="maverick.app.selection-changed"&&t.owner_app_id==="settings"){const a=i(t.selection||{});a&&(r=a,n())}}function _(e){if(!e||typeof e!="object"||Array.isArray(e))return{};const t=e.active_app_params;return t&&typeof t=="object"&&!Array.isArray(t)?t:{}}function s(e){return e.replace(/[&<>"']/g,t=>{switch(t){case"&":return"&amp;";case"<":return"&lt;";case">":return"&gt;";case'"':return"&quot;";default:return"&#39;"}})}function f(e){return s(e)}function n(){const e=document.getElementById("settings-sidebar-root");if(!e)return;const t=y();e.innerHTML=`<main class="settings-sidebar-widget ${d()?"is-shell-mobile":""}">
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
      ${t.length?t.map(M).join(""):'<p class="settings-sidebar-empty">No pages found.</p>'}
    </div>
  </main>`,S()}function M(e){return`<button class="settings-sidebar-row ${e.id===r?"is-active":""}" data-page-id="${f(e.id)}" type="button">
    <span class="material-symbols-rounded settings-sidebar-row__icon" aria-hidden="true">${s(e.icon)}</span>
    <span class="settings-sidebar-row__copy">
      <strong>${s(e.title)}</strong>
      <span>${s(e.summary)}</span>
    </span>
  </button>`}function S(){const e=document.querySelector(".settings-sidebar-search");e?.addEventListener("input",()=>{c=e.value,n()}),document.querySelectorAll("[data-page-id]").forEach(t=>{t.addEventListener("click",()=>{const a=i({page_id:t.dataset.pageId||""});a&&v(a)})})}function L(){let e=null;document.addEventListener("touchstart",t=>{if(!d()||t.touches.length!==1||P(t.target)){e=null;return}const a=t.touches[0];e={id:a.identifier,x:a.clientX,y:a.clientY}},{passive:!0}),document.addEventListener("touchmove",t=>{if(!e)return;const a=Array.from(t.changedTouches).find(m=>m.identifier===e?.id);if(!a)return;const o=a.clientX-e.x,l=Math.abs(a.clientY-e.y);Math.abs(o)>12&&Math.abs(o)>l&&(t.preventDefault(),t.stopPropagation()),o<=-72&&l<=48&&(t.preventDefault(),t.stopPropagation(),window.parent?.postMessage({type:"maverick.shell.sidebar.close"},"*"),e=null)},{passive:!1}),document.addEventListener("touchcancel",()=>{e=null},{passive:!0}),document.addEventListener("touchend",()=>{e=null},{passive:!0})}function P(e){return e instanceof Element&&!!e.closest('input, textarea, select, [contenteditable="true"], [data-no-sidebar-swipe]')}window.addEventListener("message",E);L();n();
