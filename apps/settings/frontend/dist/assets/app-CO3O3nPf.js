import{s as ne,D as ge,a as me}from"./pages-CLJdDbBh.js";async function p(e,t={}){const s=await fetch(e,{credentials:"same-origin",headers:{"Content-Type":"application/json",...t.headers||{}},...t}),n=await s.json();if(!s.ok)throw new Error(n.detail||n.error||`Request failed ${s.status}`);return n}async function fe(){return(await p("/api/admin/users")).items}async function ve(){return(await p("/api/admin/workspaces")).items}async function _e(){return(await p("/api/admin/workspace-apps")).items}function K(){return p("/api/settings/platform")}function he(e){return p("/api/providers/active",{method:"POST",body:JSON.stringify(e)})}function be(e,t="settings_runtime_sessions_cleared"){return p("/api/settings/runtime-sessions/clear",{method:"POST",body:JSON.stringify({session_ids:e,reason:t})})}function ye(){return p("/api/auth/logout",{method:"POST"})}function we(e){return p("/api/admin/persistence/migrations/dry-run",{method:"POST",body:JSON.stringify(e)})}function $e(e){return p("/api/admin/persistence/migrations/apply",{method:"POST",body:JSON.stringify(e)})}function ke(e){return p("/api/admin/users",{method:"POST",body:JSON.stringify(e)})}function Se(e,t){return p(`/api/admin/users/${encodeURIComponent(e)}`,{method:"PATCH",body:JSON.stringify(t)})}function Pe(e,t){return p(`/api/admin/users/${encodeURIComponent(e)}/password`,{method:"POST",body:JSON.stringify({password:t})})}function Ee(e){return p(`/api/admin/users/${encodeURIComponent(e)}`,{method:"DELETE"})}function Ce(e,t){return p(`/api/admin/users/${encodeURIComponent(e)}/workspaces`,{method:"PUT",body:JSON.stringify({memberships:t})})}function Re(e){return p(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"POST",body:JSON.stringify({source_id:e.source_id,enabled:!0})})}function Ae(e,t){return p(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"PATCH",body:JSON.stringify({status:t?"enabled":"disabled"})})}function Ie(e){return p(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"DELETE",body:JSON.stringify({})})}function J(e){const t=e?.provider.active_provider,s=e?.provider.model_settings,n=s?.selected_model_id||t?.default_model_family||"",a=X(e).find(d=>d.model_id===n)||null;return{modelId:n,reasoningEffort:s?.selected_reasoning_effort||ae(a)}}function X(e){const t=e?.provider.active_provider,s=e?.provider.model_settings,n=s?.selected_model_id||t?.default_model_family||"",a=W(s?.available_models).length?W(s?.available_models):W(t?.model_options);return(a.length?a:n?[Ue(n,s?.selected_reasoning_effort||"")]:[]).map(Me)}function ae(e){return e?.default_reasoning_effort||e?.supported_reasoning_efforts[0]?.effort||""}function W(e){return(e||[]).filter(t=>t.model_id)}function Me(e){return e.supported_reasoning_efforts.length||!e.default_reasoning_effort?e:{...e,supported_reasoning_efforts:[{effort:e.default_reasoning_effort,label:e.default_reasoning_effort,description:null}]}}function Ue(e,t){return{model_id:e,label:e,description:null,default_reasoning_effort:t||null,supported_reasoning_efforts:t?[{effort:t,label:t,description:null}]:[]}}const Te=new Set(["created","running","stopping"]);function He(){return{cleanupError:"",clearingAllRuntime:!1,cleaningSessionIds:new Set,draftModelId:"",draftReasoningEffort:"",isSavingProvider:!1,providerError:""}}function Y(e,t){const{modelId:s,reasoningEffort:n}=J(t);e.draftModelId=s,e.draftReasoningEffort=n}function Oe(e,t,s){const n=X(t).find(a=>a.model_id===s)||null;e.draftModelId=s,e.draftReasoningEffort=ae(n),e.providerError=""}function Le(e,t){if(!e)return`<section class="settings-card settings-platform">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Settings</p>
          <h2>Platform settings</h2>
        </div>
      </div>
      <p class="settings-card-copy">Platform settings are not available from the active backend.</p>
    </section>`;const s=e.provider.active_provider,n=qe(e),a=n.filter(C=>Te.has(C.status)),d=e.runtime.cleanup_allowed??!1,i=e.runtime.cleanup_scope||"none",g=X(e),_=J(e).modelId,k=J(e).reasoningEffort,q=(g.find(C=>C.model_id===t.draftModelId)||g[0]||null)?.supported_reasoning_efforts||[],L=!!(s&&t.draftModelId&&!t.isSavingProvider&&(t.draftModelId!==_||t.draftReasoningEffort!==k));return`<section class="settings-card settings-platform">
    <div class="settings-heading settings-platform-heading">
      <div>
        <p class="settings-kicker">Settings</p>
        <h2>Platform settings</h2>
      </div>
    </div>
    <div class="settings-platform-grid">
      <article class="settings-platform-tile settings-platform-user">
        <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">manage_accounts</span>
        <div>
          <p class="settings-kicker">Current user</p>
          <h3>${m(e.user.display_name||e.user.username||"Unavailable")}</h3>
          <p>${m(e.user.platform_role||"member")} · ${m(e.workspace.name||e.workspace.workspace_id)}</p>
          <button type="button" class="settings-secondary settings-platform-logout" id="settings-logout">
            <span class="material-symbols-rounded" aria-hidden="true">logout</span>
            Logout
          </button>
        </div>
      </article>
      <article class="settings-platform-tile settings-platform-provider">
        <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">memory</span>
        <div>
          <p class="settings-kicker">Provider</p>
          <h3>${m(s?.label||"Provider not loaded")}</h3>
          <p>${m(_||"model")} · ${m(k||"reasoning")} · ${a.length} active / ${n.length} in scope</p>
        </div>
      </article>
    </div>
    ${De(g,q,L,t)}
    ${Be(n,d,i,t)}
  </section>`}function Ne(e){document.getElementById("settings-provider-model")?.addEventListener("change",t=>{e.onProviderModelChanged(t.currentTarget.value)}),document.getElementById("settings-provider-reasoning")?.addEventListener("change",t=>{e.onProviderReasoningChanged(t.currentTarget.value)}),document.getElementById("settings-save-provider")?.addEventListener("click",e.onSaveProviderSettings),document.getElementById("settings-logout")?.addEventListener("click",e.onLogout),document.getElementById("settings-clear-all-runtime")?.addEventListener("click",e.onClearAllRuntimeSessions),document.querySelectorAll("[data-runtime-clear]").forEach(t=>{t.addEventListener("click",()=>e.onClearRuntimeSession(t.dataset.runtimeClear||""))})}function De(e,t,s,n){return`<div class="settings-platform-provider-form">
    <label class="settings-platform-field">
      <span>Model</span>
      <select id="settings-provider-model" ${!e.length||n.isSavingProvider?"disabled":""}>
        ${e.map(a=>`<option value="${V(a.model_id)}" ${a.model_id===n.draftModelId?"selected":""}>${m(a.label||a.model_id)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Reasoning</span>
      <select id="settings-provider-reasoning" ${!t.length||n.isSavingProvider?"disabled":""}>
        ${t.map(a=>`<option value="${V(a.effort)}" ${a.effort===n.draftReasoningEffort?"selected":""}>${m(a.label||a.effort)}</option>`).join("")}
      </select>
    </label>
    <button type="button" id="settings-save-provider" ${s?"":"disabled"}>
      <span class="material-symbols-rounded" aria-hidden="true">${n.isSavingProvider?"sync":"save"}</span>
      ${n.isSavingProvider?"Saving":"Save model"}
    </button>
    ${n.providerError?`<p class="settings-platform-error">${m(n.providerError)}</p>`:""}
  </div>`}function Be(e,t,s,n){return`<details class="settings-platform-runtime" open>
    <summary class="settings-heading settings-collapsible-heading">
      <div>
        <p class="settings-kicker">Runtime</p>
        <h2>Agent sessions</h2>
      </div>
    </summary>
    <div class="settings-platform-runtime-toolbar">
      <span class="settings-card-copy">${s==="server"?"Scope: full server":s==="workspace"?"Scope: active workspace":"Runtime cleanup is not allowed in this workspace"}</span>
      <span class="settings-platform-runtime-actions">
        <span class="settings-pill">${e.length}</span>
        <button type="button" class="settings-secondary" id="settings-clear-all-runtime" ${!t||!e.length||n.clearingAllRuntime?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">${n.clearingAllRuntime?"sync":"cleaning_services"}</span>
          ${n.clearingAllRuntime?"Cleaning":"Clean all"}
        </button>
      </span>
    </div>
    ${t?"":'<p class="settings-platform-error">Only authorized admins can clean runtime sessions in this scope.</p>'}
    <div class="settings-platform-runtime-list">
      ${e.length?e.map(d=>je(d,t,n)).join(""):'<p class="settings-card-copy">No runtime sessions.</p>'}
    </div>
    ${n.cleanupError?`<p class="settings-platform-error">${m(n.cleanupError)}</p>`:""}
  </details>`}function je(e,t,s){const n=s.cleaningSessionIds.has(e.session_id);return`<div class="settings-platform-runtime-row">
    <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">terminal</span>
    <span class="settings-platform-runtime-copy">
      <strong>${m(e.agent_id||e.session_id)}</strong>
      <small>${m(e.workspace_name||e.workspace_id)} · ${m(e.effective_mode)} · ${m(e.status)}</small>
      <code>${m(e.session_id)}</code>
    </span>
    <button type="button" class="settings-secondary" data-runtime-clear="${V(e.session_id)}" ${!t||s.clearingAllRuntime||n?"disabled":""}>
      <span class="material-symbols-rounded" aria-hidden="true">${n?"sync":"delete_sweep"}</span>
      ${n?"Cleaning":"Clean"}
    </button>
  </div>`}function qe(e){return e.runtime.all_sessions||e.runtime.sessions||[]}function m(e){return e.replace(/[&<>"']/g,t=>t==="&"?"&amp;":t==="<"?"&lt;":t===">"?"&gt;":t==='"'?"&quot;":"&#39;")}function V(e){return m(e)}const Fe=5,We=4,Je=4,Ve=3,Ge=2,Qe=4;function ze(e){return`<section class="settings-loading-skeleton" role="status" aria-label="Settings content is loading">
    <header class="detail-header settings-loading-skeleton__header" aria-hidden="true">
      <div class="detail-title-block">
        ${o("title")}
        <span class="detail-title-separator" aria-hidden="true"></span>
        ${o("subtitle")}
      </div>
    </header>
    ${Ke(e)}
  </section>`}function Ke(e){return e.id==="workspace-access"?Ye():e.id==="workspace-apps"?Ze():e.id==="platform-settings"?xe():e.id==="persistence"?et():Xe()}function Xe(){return`${T()}
    <section class="settings-card settings-loading-skeleton__create" aria-hidden="true">
      ${tt("short-title")}
      ${y(Fe,()=>f("field"))}
      ${f("button")}
    </section>
    ${ie()}
    <div class="settings-loading-skeleton__profile-row" aria-hidden="true">
      <section class="settings-card settings-loading-skeleton__detail-card">
        ${U(!0)}
        <div class="settings-loading-skeleton__field-grid">
          ${y(We,()=>D())}
        </div>
        ${f("toggle")}
        ${f("button")}
      </section>
      <section class="settings-card settings-loading-skeleton__password-card">
        ${U(!1)}
        ${o("copy")}
        <div class="settings-loading-skeleton__field-grid">
          ${y(2,()=>D())}
        </div>
        ${f("button")}
        ${f("danger-button")}
      </section>
    </div>`}function Ye(){return`${T()}
    ${ie()}
    <section class="settings-card" aria-hidden="true">
      ${U(!0)}
      <div class="settings-loading-skeleton__rows">
        ${y(Je,()=>st())}
      </div>
    </section>`}function Ze(){return`${T()}
    <section class="settings-card" aria-hidden="true">
      ${U(!1)}
      ${o("copy-wide")}
      <div class="settings-loading-skeleton__rows">
        ${y(Ve,()=>nt())}
      </div>
    </section>`}function xe(){return`${T()}
    <section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
      ${U(!1)}
      <div class="settings-loading-skeleton__settings-grid">
        ${y(Ge,()=>at())}
      </div>
      <div class="settings-loading-skeleton__provider-form">
        ${y(2,()=>D())}
        ${f("button")}
      </div>
      <div class="settings-loading-skeleton__runtime-list">
        ${y(Qe,()=>it())}
      </div>
    </section>`}function et(){return`${T()}
    <section class="settings-card settings-loading-skeleton__persistence" aria-hidden="true">
      ${U(!0)}
      <div class="settings-loading-skeleton__adapter-cards">
        ${y(2,()=>rt())}
      </div>
      ${ot()}
    </section>`}function T(){return`<section class="settings-card settings-page-settings" aria-hidden="true">
    ${E("page")}
    <span class="settings-loading-skeleton__copy-stack">
      ${o("kicker")}
      ${o("card-title")}
      ${o("copy")}
    </span>
  </section>`}function ie(){return`<section class="settings-card settings-user-picker" aria-hidden="true">
    <div class="settings-loading-skeleton__copy-stack">
      ${o("kicker")}
      ${o("card-title")}
      ${o("copy-short")}
    </div>
    ${D()}
  </section>`}function U(e){return`<div class="settings-loading-skeleton__heading">
    <span class="settings-loading-skeleton__copy-stack">
      ${o("kicker")}
      ${o("card-title")}
    </span>
    ${e?f("pill"):""}
  </div>`}function tt(e){return`<div class="settings-loading-skeleton__copy-stack">
    ${o("kicker")}
    ${o(e)}
  </div>`}function D(){return`<span class="settings-loading-skeleton__field-wrap">
    ${o("label")}
    ${f("field")}
  </span>`}function st(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--membership">
    ${f("checkbox")}
    ${E("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${o("row-title")}
      ${o("row-copy")}
    </span>
    ${f("select")}
  </span>`}function nt(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--app">
    ${E("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${o("row-title")}
      ${o("row-copy")}
    </span>
    ${f("toggle-pill")}
    ${f("button")}
  </span>`}function at(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--tile">
    ${E("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${o("row-title")}
      ${o("row-copy")}
    </span>
  </span>`}function it(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--runtime">
    ${E("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${o("row-title")}
      ${o("row-copy")}
    </span>
    ${f("button")}
  </span>`}function rt(){return`<span class="settings-loading-skeleton__adapter-card">
    ${E("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${o("row-title")}
      ${o("row-copy-wide")}
    </span>
    ${f("pill")}
  </span>`}function ot(){return`<span class="settings-loading-skeleton__result">
    ${E("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${o("row-title")}
      ${o("row-copy-wide")}
    </span>
  </span>`}function o(e){return`<span class="settings-loading-skeleton__line settings-loading-skeleton__line--${e}"></span>`}function f(e){return`<span class="settings-loading-skeleton__block settings-loading-skeleton__block--${e}"></span>`}function E(e){return`<span class="settings-loading-skeleton__icon settings-loading-skeleton__icon--${e}"></span>`}function y(e,t){return Array.from({length:e},t).join("")}function lt(e){document.getElementById("dismiss-notice")?.addEventListener("click",e.dismissNotice),document.getElementById("create-user")?.addEventListener("submit",s=>{s.preventDefault(),e.createUser(s.currentTarget).catch(e.showError)});const t=e.selectedUser();document.getElementById("selected-user")?.addEventListener("change",s=>{e.selectUser(s.currentTarget.value)}),document.getElementById("edit-user")?.addEventListener("submit",s=>{s.preventDefault(),t&&e.updateSelectedUser(s.currentTarget,t).catch(e.showError)}),document.getElementById("reset-password")?.addEventListener("submit",s=>{s.preventDefault(),t&&e.resetSelectedUserPassword(s.currentTarget,t).catch(e.showError)}),document.getElementById("delete-user")?.addEventListener("click",()=>{t&&e.deleteSelectedUser(t).catch(e.showError)}),document.getElementById("save-memberships")?.addEventListener("click",()=>{t&&e.updateMemberships(t).catch(e.showError)}),dt(e),ct(e),Ne({onClearAllRuntimeSessions:()=>{e.clearRuntimeSessionsFromPanel().catch(e.showError)},onClearRuntimeSession:s=>{s&&e.clearRuntimeSessionsFromPanel([s]).catch(e.showError)},onLogout:()=>{e.logoutFromSettings().catch(e.showError)},onProviderModelChanged:e.onProviderModelChanged,onProviderReasoningChanged:e.onProviderReasoningChanged,onSaveProviderSettings:()=>{e.saveProviderSettingsFromPanel().catch(e.showError)}})}function dt(e){document.querySelectorAll("[data-app-toggle]").forEach(t=>{t.addEventListener("change",()=>{const s=e.workspaceApps().find(n=>`${n.workspace_id}:${n.app_id}`===t.dataset.appToggle);s&&e.setWorkspaceAppStatus(s,t.checked).catch(e.showError)})}),document.querySelectorAll("[data-app-install]").forEach(t=>{t.addEventListener("click",()=>{const s=e.workspaceApps().find(n=>`${n.workspace_id}:${n.app_id}`===t.dataset.appInstall);s&&e.installWorkspaceApp(s).catch(e.showError)})}),document.querySelectorAll("[data-app-uninstall]").forEach(t=>{t.addEventListener("click",()=>{const s=e.workspaceApps().find(n=>`${n.workspace_id}:${n.app_id}`===t.dataset.appUninstall);s&&e.uninstallWorkspaceApp(s).catch(e.showError)})})}function ct(e){document.querySelectorAll("[data-adapter-target]").forEach(t=>{t.addEventListener("click",()=>{const s=t.dataset.adapterTarget;(s==="json"||s==="mongo")&&e.persistenceController.prepare(s).catch(e.showError)})}),document.getElementById("close-migration-modal")?.addEventListener("click",()=>{e.persistenceController.cancel()}),document.getElementById("cancel-migration")?.addEventListener("click",()=>{e.persistenceController.cancel()}),document.getElementById("validate-migration")?.addEventListener("click",()=>{e.persistenceController.validateDraft().catch(e.showError)}),document.querySelectorAll("[data-migration-field]").forEach(t=>{const s=n=>{const a=t.dataset.migrationField;if(a&&a in(e.persistenceController.viewState().targetDraft||{})){const d=!!e.persistenceController.viewState().migrationPlan;e.persistenceController.updateDraft(a,t.value,{render:n}),!n&&d&&pt()}};t.addEventListener("input",()=>s(!1)),t.addEventListener("change",()=>s(!0))}),document.getElementById("settings-delete-source")?.addEventListener("change",t=>{e.persistenceController.setDeleteSource(t.currentTarget.checked)}),document.getElementById("confirm-migration")?.addEventListener("click",()=>{e.persistenceController.apply().catch(e.showError)})}function pt(){const e=document.getElementById("confirm-migration");e&&(e.disabled=!0);const t=document.querySelector(".settings-migration-plan");if(!t)return;const s=t.querySelector(".material-symbols-rounded"),n=t.querySelector("strong"),a=t.querySelector("small");s&&(s.textContent="rule"),n&&(n.textContent="Dry run changed"),a&&(a.textContent="Validate the dry run again before applying migration."),t.querySelector(".settings-migration-collections")?.remove()}function r(e){return e.replace(/[&<>"']/g,t=>t==="&"?"&amp;":t==="<"?"&lt;":t===">"?"&gt;":t==='"'?"&quot;":"&#39;")}function h(e){return r(e)}function H(e){return`<section class="settings-card settings-page-settings">
    <span class="settings-page-settings-icon material-symbols-rounded" aria-hidden="true">${r(e.icon)}</span>
    <span>
      <p class="settings-kicker">Settings page</p>
      <h2>${r(e.title)}</h2>
      <p class="settings-card-copy">${r(e.summary)}</p>
    </span>
  </section>`}function ut(e){let t=null,s=null,n="",a=null,d=null,i=null,g=!1;function _(){return{deleteSourceAfterMigration:g,migrationPlan:a,migrationProgress:i,migrationResult:d,migrationTarget:t,persistence:e.getPersistence(),targetDraft:s}}async function k(l){const b=e.getPersistence();if(!b||b.active_adapter.kind===l){L();return}t=l,s=gt(l,b),n="",a=null,g=!1,i=null,e.setNotice(null),e.render()}function O(l,b,R={}){s&&(s={...s,[l]:b},a=null,n="",i=null,R.render!==!1&&e.render())}function q(l){g=l,e.render()}function L(){t=null,s=null,a=null,n="",i=null,e.render()}async function C(){if(!(!s||!t)){i={target:t,phase:"validating",percent:10,title:`Dry run to ${t.toUpperCase()}`,detail:"Validating target adapter and collection copy plan before applying changes."},e.setNotice(null),e.render();try{const l=G(s);a=await we(l),n=ee(l)}catch(l){throw i=null,a=null,n="",l}i=null,a.same_adapter&&e.setNotice({tone:"info",message:"The selected persistence adapter is already active."}),e.render()}}async function pe(){if(!s||!t)return;const l=G(s),b=ee(l);if(!a||n!==b){await C();return}if(a.same_adapter)return;i={target:t,phase:"applying",percent:38,title:`Migration to ${t.toUpperCase()}`,detail:"Copying the validated control-plane plan to the target adapter."},e.setNotice(null),e.render();try{d=await $e({...l,delete_source:g,restart_backend:!0})}catch(A){throw i={target:t,phase:"failed",percent:100,title:"Migration failed",detail:A instanceof Error?A.message:"Unable to apply migration."},A}const R=t;t=null,s=null,a=null,n="",i={target:R,phase:"restarting",percent:68,title:"Restart backend",detail:d.backend_restart?.detail||"Backend restart scheduled."},e.render(),await ue(R)}async function ue(l){const b=Date.now(),R=9e4;for(;Date.now()-b<R;){i={target:l,phase:"polling",percent:84,title:"Verifying cutover",detail:"Waiting for the backend to become healthy with the new adapter."},e.render();const A=await e.requestPersistenceStatusQuiet();if(A?.active_adapter.kind===l){e.setPersistence(A);const F=d?.source_cleanup?.scheduled===!0;i={target:l,phase:"complete",percent:100,title:"Migration complete",detail:F?`Active adapter: ${l.toUpperCase()}. Source cleanup is scheduled after health check.`:`Active adapter: ${l.toUpperCase()}. Source storage was preserved.`},e.setNotice({tone:"success",message:`Migration to ${l.toUpperCase()} complete.`}),e.render();return}await new Promise(F=>window.setTimeout(F,1500))}i={target:l,phase:"failed",percent:100,title:"Verification not completed",detail:"The backend did not confirm the new adapter before the timeout. Check service health and logs."},e.setNotice({tone:"error",message:"Migration not confirmed before the timeout."}),e.render()}return{apply:pe,cancel:L,prepare:k,setDeleteSource:q,updateDraft:O,validateDraft:C,viewState:_}}function gt(e,t){const s=t.active_adapter;return{kind:e,json_root:s.json_root||"data/control-plane/json",mongodb_uri:s.mongo_uri||"mongodb://127.0.0.1:27017/maverick",mongodb_database:s.mongo_database||"maverick",mongodb_username:s.mongo_username||"",mongodb_password_ref:s.mongo_password_ref||""}}function G(e){return{kind:e.kind,json_root:e.json_root.trim()||"data/control-plane/json",mongodb_uri:e.mongodb_uri.trim(),mongodb_database:e.mongodb_database.trim()||"maverick",mongodb_username:e.mongodb_username?.trim()||void 0,mongodb_password_ref:e.mongodb_password_ref?.trim()||void 0}}function ee(e){return JSON.stringify(G(e))}function mt(e,t){return`${H(e)}
    ${_t(t)}`}function ft(e){const{deleteSourceAfterMigration:t,migrationPlan:s,migrationProgress:n,migrationTarget:a,persistence:d}=e;if(!a||!d)return"";const i=d.active_adapter.kind.toUpperCase(),g=a.toUpperCase(),_=!!(n&&!["complete","failed"].includes(n.phase)),k=!!(s&&!s.same_adapter&&!_);return`<div class="settings-modal-backdrop" role="presentation">
    <section class="settings-modal" role="dialog" aria-modal="true" aria-labelledby="adapter-migration-title">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Confirm migration</p>
          <h2 id="adapter-migration-title">${i} → ${g}</h2>
        </div>
        <button type="button" class="settings-icon-button" id="close-migration-modal" aria-label="Close" ${_?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">close</span>
        </button>
      </div>
      ${s?wt(s):yt(n)}
      ${vt(e)}
      <label class="settings-toggle settings-migration-delete-source">
        <input id="settings-delete-source" type="checkbox" ${t?"checked":""} ${_?"disabled":""} />
        Schedule source cleanup after restart health check
      </label>
      <p class="settings-card-copy">Leave cleanup off to preserve the current source adapter data as a rollback point. Cleanup is a separate explicit choice and requires backend restart.</p>
      <div class="settings-modal-actions">
        <button type="button" class="settings-secondary" id="cancel-migration" ${_?"disabled":""}>Cancel</button>
        <button type="button" class="settings-secondary" id="validate-migration" ${_?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">rule</span>
          Validate dry run
        </button>
        <button type="button" class="${t?"settings-danger":"settings-secondary"}" id="confirm-migration" ${k?"":"disabled"}>
          <span class="material-symbols-rounded" aria-hidden="true">sync_alt</span>
          ${t?"Apply and schedule cleanup":"Apply migration"}
        </button>
      </div>
    </section>
  </div>`}function vt(e){const t=e.targetDraft;if(!t)return"";const s=!!(e.migrationProgress&&!["complete","failed"].includes(e.migrationProgress.phase));return`<div class="settings-migration-target">
    <label class="settings-platform-field">
      <span>JSON root</span>
      <input data-migration-field="json_root" value="${h(t.json_root)}" ${s?"disabled":""} />
    </label>
    ${t.kind==="mongo"?`<label class="settings-platform-field">
          <span>Mongo URI</span>
          <input data-migration-field="mongodb_uri" value="${h(t.mongodb_uri)}" ${s?"disabled":""} />
        </label>
        <label class="settings-platform-field">
          <span>Mongo database</span>
          <input data-migration-field="mongodb_database" value="${h(t.mongodb_database)}" ${s?"disabled":""} />
        </label>
        <label class="settings-platform-field">
          <span>Mongo username</span>
          <input data-migration-field="mongodb_username" value="${h(t.mongodb_username||"")}" ${s?"disabled":""} />
        </label>
        <label class="settings-platform-field">
          <span>Password secret ref</span>
          <input data-migration-field="mongodb_password_ref" value="${h(t.mongodb_password_ref||"")}" ${s?"disabled":""} />
        </label>`:""}
  </div>`}function _t(e){const{migrationProgress:t,migrationResult:s,persistence:n}=e;if(!n)return`<section class="settings-card settings-persistence">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Persistence</p>
          <h2>Control plane adapter</h2>
        </div>
        <span class="settings-pill settings-pill-muted">offline</span>
      </div>
      <p class="settings-card-copy">The core persistence surfaces are not available in the active backend.</p>
    </section>`;const a=n.active_adapter,d=n.collections.reduce((k,O)=>k+O.count,0),i=a.kind==="json",g=a.kind==="mongo",_=t&&!["complete","failed"].includes(t.phase);return`<section class="settings-card settings-persistence">
    <div class="settings-heading">
      <div>
        <p class="settings-kicker">Persistence</p>
        <h2>Control plane adapter</h2>
      </div>
      <span class="settings-pill">${d} documents</span>
    </div>
    <div class="settings-adapter-cards">
      <button type="button" class="settings-adapter-card ${i?"is-active":""}" ${i||_?"disabled":'data-adapter-target="json"'}>
        <span class="settings-adapter-card-icon material-symbols-rounded" aria-hidden="true">${i?"check_circle":"database"}</span>
        <span>
          <strong>JSON</strong>
          <small>${r(i?a.json_root:"data/control-plane/json")}</small>
        </span>
        <em>${i?"Current":"Review migration"}</em>
      </button>
      <button type="button" class="settings-adapter-card ${g?"is-active":""}" ${g||_?"disabled":'data-adapter-target="mongo"'}>
        <span class="settings-adapter-card-icon material-symbols-rounded" aria-hidden="true">${g?"check_circle":"database"}</span>
        <span>
          <strong>Mongo</strong>
          <small>${r(g?a.mongo_database:"mongodb://127.0.0.1:27017/maverick")}</small>
        </span>
        <em>${g?"Current":"Review migration"}</em>
      </button>
    </div>
    ${ht(t)}
    ${bt(s)}
  </section>`}function ht(e){return e?`<div class="settings-migration-progress ${e.phase==="failed"?"is-failed":""} ${e.phase==="complete"?"is-complete":""}">
    <div class="settings-migration-progress-heading">
      <span class="material-symbols-rounded" aria-hidden="true">${e.phase==="complete"?"check_circle":e.phase==="failed"?"error":"sync"}</span>
      <span>
        <strong>${r(e.title)}</strong>
        <small>${r(e.detail)}</small>
      </span>
      <em>${e.percent}%</em>
    </div>
    <div class="settings-progress-track" aria-label="Migration progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${e.percent}">
      <span style="width: ${e.percent}%"></span>
    </div>
  </div>`:""}function bt(e){return e?`<div class="settings-migration-result">
    <span class="material-symbols-rounded" aria-hidden="true">task_alt</span>
    <span>
      <strong>Last migration</strong>
      <small>${e.collections.reduce((s,n)=>s+n.count,0)} documents · target ${r(e.target_adapter.kind)} · cleanup ${e.source_cleanup?.scheduled?"scheduled":"not requested"}</small>
    </span>
  </div>`:""}function yt(e){return`<div class="settings-migration-plan">
    <span class="material-symbols-rounded" aria-hidden="true">rule</span>
    <span>
      <strong>${r(e?.title||"Dry run not validated")}</strong>
      <small>${r(e?.detail||"Adjust the target fields, then validate the dry run before applying migration.")}</small>
    </span>
  </div>`}function wt(e){const t=e.collections.reduce((n,a)=>n+a.count,0),s=e.target_collections.reduce((n,a)=>n+a.count,0);return`<div class="settings-migration-plan">
    <span class="material-symbols-rounded" aria-hidden="true">${e.same_adapter?"block":"rule"}</span>
    <span>
      <strong>${e.same_adapter?"Target already active":"Dry run complete"}</strong>
      <small>${t} source documents · ${s} target documents before copy · env ${r(e.env_file)}</small>
    </span>
    <div class="settings-migration-collections">
      ${e.collections.map(n=>`<span><strong>${r(n.name)}</strong><small>${n.count}</small></span>`).join("")}
    </div>
  </div>`}function $t({page:e,pendingDeleteUserId:t,selectedUser:s,users:n}){return`${H(e)}
    <form class="settings-card settings-create" id="create-user">
      <div>
        <p class="settings-kicker">New user</p>
        <h2>Create access</h2>
      </div>
      <input name="username" placeholder="username" required />
      <input name="password" type="password" placeholder="temporary password" required />
      <input name="display_name" placeholder="display name" />
      <input name="email" type="email" placeholder="email" />
      <select name="platform_role">
        <option value="member">Member</option>
        <option value="admin">Admin</option>
      </select>
      <button type="submit">
        <span class="material-symbols-rounded" aria-hidden="true">person_add</span>
        Create user
      </button>
    </form>
    ${re(n,s)}
    ${s?`<div class="settings-profile-row">
          <form class="settings-card settings-detail" id="edit-user">
            <div class="settings-heading">
              <div>
                <p class="settings-kicker">Selected user</p>
                <h2>${r(s.display_name||s.username)}</h2>
              </div>
              <span class="settings-pill">${s.is_active?"active":"disabled"}</span>
            </div>
            <div class="settings-grid">
              <label>Name<input name="display_name" value="${h(s.display_name||"")}" /></label>
              <label>Email<input name="email" type="email" value="${h(s.email||"")}" /></label>
              <label>Platform role<select name="platform_role">
                <option value="member" ${s.platform_role==="member"?"selected":""}>Member</option>
                <option value="admin" ${s.platform_role==="admin"?"selected":""}>Admin</option>
              </select></label>
              <label>Account type<select name="account_type">
                <option value="standard" ${s.account_type==="standard"?"selected":""}>Standard</option>
                <option value="facilitated" ${s.account_type==="facilitated"?"selected":""}>Facilitated</option>
              </select></label>
            </div>
            <label class="settings-toggle"><input name="is_active" type="checkbox" ${s.is_active?"checked":""} /> Account active</label>
            <button type="submit">
              <span class="material-symbols-rounded" aria-hidden="true">save</span>
              Save user
            </button>
          </form>
          <form class="settings-card settings-password" id="reset-password">
            <div class="settings-heading">
              <div>
                <p class="settings-kicker">Password</p>
                <h2>Reset access</h2>
              </div>
              <span class="settings-password-icon material-symbols-rounded" aria-hidden="true">key</span>
            </div>
            <p class="settings-card-copy">Set a new temporary password for the selected user.</p>
            <div class="settings-password-grid">
              <label>New password<input name="password" type="password" minlength="8" autocomplete="new-password" required /></label>
              <label>Confirm password<input name="password_confirmation" type="password" minlength="8" autocomplete="new-password" required /></label>
            </div>
            <button type="submit" class="settings-secondary">
              <span class="material-symbols-rounded" aria-hidden="true">password</span>
              Update password
            </button>
            <button type="button" class="settings-danger" id="delete-user">
              <span class="material-symbols-rounded" aria-hidden="true">person_remove</span>
              ${t===s.user_id?"Confirm delete":"Delete user"}
            </button>
          </form>
        </div>`:'<section class="settings-card"><h2>No users</h2></section>'}`}function kt({page:e,selectedUser:t,users:s,workspaces:n}){return`${H(e)}
    ${re(s,t)}
    ${t?`<section class="settings-card">
          <div class="settings-heading">
            <div>
              <p class="settings-kicker">Workspace</p>
              <h2>Assignments</h2>
            </div>
            <button type="button" id="save-memberships">
              <span class="material-symbols-rounded" aria-hidden="true">admin_panel_settings</span>
              Save access
            </button>
          </div>
          <div class="settings-memberships">${St(t,n)}</div>
        </section>`:'<section class="settings-card"><h2>No users</h2></section>'}`}function re(e,t){return e.length?`<section class="settings-card settings-user-picker">
    <div>
      <p class="settings-kicker">User directory</p>
      <h2>${r(t?t.display_name||t.username:"Select user")}</h2>
      <p class="settings-card-copy">${e.length} user${e.length===1?"":"s"} available.</p>
    </div>
    <label class="settings-platform-field">
      <span>Selected user</span>
      <select id="selected-user">
        ${e.map(s=>`<option value="${h(s.user_id)}" ${s.user_id===t?.user_id?"selected":""}>${r(s.display_name||s.username)} (${r(s.username)})</option>`).join("")}
      </select>
    </label>
  </section>`:`<section class="settings-card settings-user-picker">
      <div>
        <p class="settings-kicker">User directory</p>
        <h2>No users</h2>
      </div>
      <p class="settings-card-copy">Create a user before editing profile or workspace access settings.</p>
    </section>`}function St(e,t){return t.map(s=>{const n=e.memberships.find(a=>a.workspace_id===s.workspace_id);return`<label class="settings-membership">
        <input type="checkbox" data-workspace-enabled="${h(s.workspace_id)}" ${n?"checked":""} />
        <span class="settings-membership-icon material-symbols-rounded" aria-hidden="true">workspaces</span>
        <span>
          <strong>${r(s.name)}</strong>
          <small>${r(s.workspace_id)}</small>
        </span>
        <select data-workspace-role="${h(s.workspace_id)}">
          <option value="member" ${n?.role!=="admin"?"selected":""}>Member</option>
          <option value="admin" ${n?.role==="admin"?"selected":""}>Workspace admin</option>
        </select>
      </label>`}).join("")}function Pt({page:e,workspaceApps:t,workspaces:s}){return`${H(e)}
    <section class="settings-card">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Workspace apps</p>
          <h2>Installation and visibility</h2>
        </div>
      </div>
      <p class="settings-card-copy">Installed means the app has a workspace binding. Only enabled apps are visible to users and served by the core.</p>
      <div class="settings-app-workspaces">${Et(s,t)}</div>
    </section>`}function Et(e,t){return e.map(s=>{const n=t.filter(i=>i.workspace_id===s.workspace_id),a=n.filter(i=>i.status==="enabled").length,d=n.filter(i=>i.installed).length;return`<details class="settings-app-workspace">
        <summary class="settings-app-workspace-heading">
          <span class="settings-summary-caret material-symbols-rounded" aria-hidden="true">chevron_right</span>
          <span class="settings-app-workspace-icon material-symbols-rounded" aria-hidden="true">deployed_code</span>
          <span>
            <strong>${r(s.name)}</strong>
            <small>${r(s.workspace_id)} · ${a}/${d} enabled</small>
          </span>
        </summary>
        <div class="settings-apps">
          ${n.map(Ct).join("")}
        </div>
      </details>`}).join("")}function Ct(e){const t=e.status==="enabled",s=e.installed,n=s?e.status:"not installed",a=`${e.workspace_id}:${e.app_id}`;return`<div class="settings-app-row">
    <span class="settings-app-icon material-symbols-rounded" aria-hidden="true">${t?"apps":"hide_source"}</span>
    <span class="settings-app-copy">
      <strong>${r(e.name)}</strong>
      <small>${r(e.app_id)} · v${r(e.version)} · ${r(n)}</small>
    </span>
    ${s?`<label class="settings-switch">
          <input type="checkbox" data-app-toggle="${h(a)}" ${t?"checked":""} />
          <span>Enabled</span>
        </label>
        <button type="button" class="settings-secondary" data-app-uninstall="${h(a)}">
          <span class="material-symbols-rounded" aria-hidden="true">link_off</span>
          Uninstall
        </button>`:`<button type="button" class="settings-secondary" data-app-install="${h(a)}">
          <span class="material-symbols-rounded" aria-hidden="true">add_link</span>
          Install
        </button>`}
  </div>`}let S=[],B=[],Z=[],Q=null,w=null,c=He();const oe=Object.fromEntries(new URLSearchParams(window.location.search).entries());let z=ne(oe)||ge,$=de(oe),I=!0,M="",v=null,te="",se="";const x=ut({getPersistence:()=>Q,render:()=>u(),requestPersistenceStatusQuiet:Ut,setNotice:e=>{v=e},setPersistence:e=>{Q=e}});function le(){return S.find(e=>e.user_id===$)||S[0]}function de(e){const t=N(e.user_id)||N(e.selected_user_id)||N(e.id);if(t)return t;const s=N(e.app_page),n=/^users\/([^/?#]+)$/.exec(s);if(!n?.[1])return"";try{return decodeURIComponent(n[1])}catch{return n[1]}}function N(e){return typeof e=="string"?e.trim():""}function Rt(e){const t=ne(e),s=de(e);let n=!1;t&&t!==z&&(z=t,n=!0),s&&s!==$&&($=s,M="",n=!0),n&&(S.length||I)&&u()}function At(e){e.id===te||window.parent===window||(te=e.id,window.parent.postMessage({type:"maverick.app.selection-changed",owner_app_id:"settings",selection:{page_id:e.id}},window.location.origin))}function It(e){!e||e.user_id===se||window.parent===window||(se=e.user_id,window.parent.postMessage({type:"maverick.app.selection-changed",owner_app_id:"settings",selection:{user_id:e.user_id}},window.location.origin))}function j(){window.parent!==window&&window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"settings",resource:"users"},window.location.origin)}async function Mt(){try{return await p("/api/admin/persistence")}catch(e){return v={tone:"error",message:e instanceof Error?e.message:"Persistence API unavailable"},null}}async function Ut(){try{return await p("/api/admin/persistence")}catch{return null}}async function Tt(){try{return await K()}catch{return null}}async function P(){I=!0,u();try{const[e,t,s,n,a]=await Promise.all([fe(),ve(),_e(),Mt(),Tt()]);S=e,B=t,Z=s,Q=n,w=a,Y(c,w),(!$||!S.some(d=>d.user_id===$))&&($=S[0]?.user_id||"")}finally{I=!1}u()}async function Ht(e){const t=new FormData(e);$=(await ke({username:String(t.get("username")||""),password:String(t.get("password")||""),display_name:String(t.get("display_name")||""),email:String(t.get("email")||""),platform_role:String(t.get("platform_role")||"member")})).user_id,e.reset(),await P(),j()}async function Ot(e,t){const s=new FormData(e);await Se(t.user_id,{display_name:String(s.get("display_name")||""),email:String(s.get("email")||""),platform_role:String(s.get("platform_role")||"member"),account_type:String(s.get("account_type")||"standard"),is_active:s.get("is_active")==="on"}),await P(),j()}async function Lt(e,t){const s=new FormData(e),n=String(s.get("password")||""),a=String(s.get("password_confirmation")||"");if(n!==a)throw new Error("Passwords do not match");await Pe(t.user_id,n),e.reset(),v={tone:"success",message:"Password updated."},u()}async function Nt(e){const t=e.display_name||e.username;if(M!==e.user_id){M=e.user_id,v={tone:"info",message:`Press Delete user again to confirm permanent removal of ${t}.`},u();return}await Ee(e.user_id),$="",M="",v={tone:"success",message:`${t} deleted.`},await P(),j()}async function Dt(e){const t=B.map(s=>{const n=document.querySelector(`[data-workspace-enabled="${s.workspace_id}"]`),a=document.querySelector(`[data-workspace-role="${s.workspace_id}"]`);return n?.checked?{workspace_id:s.workspace_id,role:a?.value||"member"}:null}).filter(s=>!!s);await Ce(e.user_id,t),await P(),j()}async function Bt(e){await Re(e),await P()}async function jt(e,t){await Ae(e,t),await P()}async function qt(e){await Ie(e),await P()}async function Ft(){const e=w?.provider.active_provider?.provider_id;if(!e||!c.draftModelId){c.providerError="Provider not loaded.",u();return}c.isSavingProvider=!0,c.providerError="",u();try{await he({provider_id:e,model_id:c.draftModelId,model_reasoning_effort:c.draftReasoningEffort||null}),w=await K(),Y(c,w),v={tone:"success",message:"Provider settings updated."}}catch(t){c.providerError=t instanceof Error?t.message:"Unable to update provider settings."}finally{c.isSavingProvider=!1,u()}}async function Wt(e){const t=(e||[]).filter(Boolean);c.cleanupError="",t.length?t.forEach(s=>c.cleaningSessionIds.add(s)):c.clearingAllRuntime=!0,u();try{const s=await be(t.length?t:void 0);Jt(s),w=await K(),Y(c,w),v={tone:"success",message:t.length?"Runtime session cleaned.":"Runtime sessions cleaned."}}catch(s){c.cleanupError=s instanceof Error?s.message:"Unable to clean runtime sessions."}finally{t.forEach(s=>c.cleaningSessionIds.delete(s)),c.clearingAllRuntime=!1,u()}}function Jt(e){e.deleted_threads<=0||window.parent===window||(window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"chat",resource:"threads"},window.location.origin),e.deleted_thread_ids.forEach(t=>{window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"chat",resource:"threads",deleted_thread_id:t},window.location.origin)}))}async function Vt(){if(window.parent&&window.parent!==window){window.parent.postMessage({type:"maverick.shell.logout"},window.location.origin);return}await ye(),window.location.href="/"}function Gt(e,t){return e.id==="users"?$t({page:e,pendingDeleteUserId:M,selectedUser:t,users:S}):e.id==="workspace-access"?kt({page:e,selectedUser:t,users:S,workspaces:B}):e.id==="workspace-apps"?Pt({page:e,workspaceApps:Z,workspaces:B}):e.id==="platform-settings"?Qt(e):mt(e,x.viewState())}function Qt(e){return`${H(e)}
    ${Le(w,c)}`}function u(){const e=document.getElementById("app"),t=I?void 0:le(),s=me(z);e&&(e.innerHTML=`<main class="settings-shell">
    <section class="settings-main">
      <div class="settings-content">
        ${I?ze(s):`<header class="detail-header">
          <div class="detail-title-block">
            <h2>${r(s.title)}</h2>
            <span class="detail-title-separator" aria-hidden="true"></span>
            <p>${r(s.summary)}</p>
          </div>
        </header>
        ${Kt()}
        ${Gt(s,t)}`}
      </div>
    </section>
    ${ft(x.viewState())}
  </main>`,zt(),At(s),I||It(t))}function zt(){lt({clearRuntimeSessionsFromPanel:Wt,createUser:Ht,deleteSelectedUser:Nt,dismissNotice:()=>{v=null,u()},installWorkspaceApp:Bt,logoutFromSettings:Vt,onProviderModelChanged:e=>{Oe(c,w,e),u()},onProviderReasoningChanged:e=>{c.draftReasoningEffort=e,c.providerError="",u()},persistenceController:x,render:u,resetSelectedUserPassword:Lt,saveProviderSettingsFromPanel:Ft,selectedUser:le,selectUser:e=>{$=e,M="",u()},setWorkspaceAppStatus:jt,showError:ce,uninstallWorkspaceApp:qt,updateMemberships:Dt,updateSelectedUser:Ot,workspaceApps:()=>Z})}function ce(e){v={tone:"error",message:e instanceof Error?e.message:"Unexpected error"},u()}function Kt(){return v?`<div class="settings-notice settings-notice-${v.tone}">
    <span class="material-symbols-rounded" aria-hidden="true">${v.tone==="error"?"error":v.tone==="success"?"task_alt":"info"}</span>
    <span>${r(v.message)}</span>
    <button type="button" class="settings-icon-button" id="dismiss-notice" aria-label="Close">
      <span class="material-symbols-rounded" aria-hidden="true">close</span>
    </button>
  </div>`:""}window.addEventListener("message",e=>{if(e.origin!==window.location.origin||!e.data||typeof e.data!="object")return;const t=e.data;t.type==="maverick.app.navigate"&&(!t.app_id||t.app_id==="settings")&&Rt(t.params||{})});window.parent?.postMessage({type:"maverick.app.ready",app_id:"settings"},window.location.origin);P().catch(ce);
