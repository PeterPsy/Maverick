import{l as y}from"../../adminApi-BbgnavI7.js";const m="(max-width: 979px)";let o=[],l="",r="",c="",f=!0;function h(e){return e.display_name||e.username}function g(e){return e.platform_role==="admin"?"Admin":"Member"}function _(){const e=l.trim().toLowerCase();return e?o.filter(t=>`${h(t)} ${t.username} ${t.email||""} ${t.user_id} ${t.platform_role}`.toLowerCase().includes(e)):o}function u(){if(typeof window>"u")return!1;try{const e=window.parent&&window.parent!==window?window.parent:window;return typeof e.matchMedia=="function"&&e.matchMedia(m).matches}catch{return typeof window.matchMedia=="function"&&window.matchMedia(m).matches}}function v(e){r=e,s(),window.parent?.postMessage({type:"maverick.widget.open-app",app_id:"user-admin",params:{app_page:`users/${encodeURIComponent(e)}`,user_id:e}},window.location.origin),u()&&window.parent?.postMessage({type:"maverick.shell.sidebar.close"},window.location.origin)}async function w(){try{o=await y(),(!r||!o.some(e=>e.user_id===r))&&(r=o[0]?.user_id||""),c=""}catch(e){c=e instanceof Error?e.message:"Unable to load users."}finally{f=!1,s()}}function $(e){if(e.origin!==window.location.origin||!e.data||typeof e.data!="object")return;const t=e.data;if(t.type==="maverick.widget.context-changed"){const n=L(t.context?.content?.payload),a=k(n);a&&(r=a,s());return}if(t.type==="maverick.app.selection-changed"&&t.owner_app_id==="user-admin"){const n=i(t.selection?.user_id);n&&(r=n,s());return}t.type==="maverick.widget.data-changed"&&t.owner_app_id==="user-admin"&&t.resource==="users"&&w()}function L(e){if(!e||typeof e!="object"||Array.isArray(e))return{};const t=e.active_app_params;return t&&typeof t=="object"&&!Array.isArray(t)?t:{}}function k(e){const t=i(e.user_id)||i(e.selected_user_id)||i(e.id);if(t)return t;const n=i(e.app_page),a=/^users\/([^/?#]+)$/.exec(n);if(!a?.[1])return"";try{return decodeURIComponent(a[1])}catch{return a[1]}}function i(e){return typeof e=="string"?e.trim():""}function d(e){return e.replace(/[&<>"']/g,t=>{switch(t){case"&":return"&amp;";case"<":return"&lt;";case">":return"&gt;";case'"':return"&quot;";default:return"&#39;"}})}function s(){const e=document.getElementById("user-admin-sidebar-root");if(!e)return;const t=_();e.innerHTML=`<main class="user-admin-sidebar-widget ${u()?"is-shell-mobile":""}">
    <div class="user-admin-sidebar-search-frame">
      <span class="material-symbols-rounded" aria-hidden="true">search</span>
      <input
        aria-label="Search users"
        class="user-admin-sidebar-search"
        placeholder="Search users"
        value="${d(l)}"
      />
    </div>
    ${c?`<p class="user-admin-sidebar-empty">${d(c)}</p>`:""}
    <div class="user-admin-sidebar-list">
      ${f?M():t.length?t.map(E).join(""):'<p class="user-admin-sidebar-empty">No users found.</p>'}
    </div>
  </main>`,I()}function E(e){const t=e.user_id===r?"is-active":"",n=e.is_active?"active":"disabled";return`<button class="user-admin-sidebar-row ${t}" data-user-id="${d(e.user_id)}" type="button">
    <span class="material-symbols-rounded user-admin-sidebar-row__icon" aria-hidden="true">${e.platform_role==="admin"?"admin_panel_settings":"account_circle"}</span>
    <span class="user-admin-sidebar-row__copy">
      <strong>${d(h(e))}</strong>
      <span>${d(g(e))} · ${e.memberships.length} workspace · ${n}</span>
    </span>
  </button>`}function M(){return`<div aria-hidden="true" class="user-admin-sidebar-skeleton">
    ${Array.from({length:7}).map(()=>`<div class="user-admin-sidebar-skeleton__row">
      <span class="user-admin-sidebar-skeleton__icon"></span>
      <span class="user-admin-sidebar-skeleton__copy"><span></span><span></span></span>
    </div>`).join("")}
  </div>`}function I(){const e=document.querySelector(".user-admin-sidebar-search");e?.addEventListener("input",()=>{l=e.value,s()}),document.querySelectorAll("[data-user-id]").forEach(t=>{t.addEventListener("click",()=>{const n=t.dataset.userId||"";n&&v(n)})})}function A(){let e=null;document.addEventListener("touchstart",t=>{if(!u()||t.touches.length!==1||S(t.target)){e=null;return}const n=t.touches[0];e={id:n.identifier,x:n.clientX,y:n.clientY}},{passive:!0}),document.addEventListener("touchmove",t=>{if(!e)return;const n=Array.from(t.changedTouches).find(b=>b.identifier===e?.id);if(!n)return;const a=n.clientX-e.x,p=Math.abs(n.clientY-e.y);Math.abs(a)>12&&Math.abs(a)>p&&(t.preventDefault(),t.stopPropagation()),a<=-72&&p<=48&&(t.preventDefault(),t.stopPropagation(),window.parent?.postMessage({type:"maverick.shell.sidebar.close"},window.location.origin),e=null)},{passive:!1}),document.addEventListener("touchcancel",()=>{e=null},{passive:!0}),document.addEventListener("touchend",()=>{e=null},{passive:!0})}function S(e){return e instanceof Element&&!!e.closest('input, textarea, select, [contenteditable="true"], [data-no-sidebar-swipe]')}window.addEventListener("message",$);A();s();w();
