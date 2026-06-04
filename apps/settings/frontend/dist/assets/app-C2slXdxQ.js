import{s as pe,D as $e,a as Se}from"./pages-BZUBskpf.js";async function g(e,t={}){const s=await fetch(e,{credentials:"same-origin",headers:{"Content-Type":"application/json",...t.headers||{}},...t}),n=await s.json();if(!s.ok)throw new Error(n.detail||n.error||`Request failed ${s.status}`);return n}async function Pe(){return(await g("/api/admin/users")).items}async function Ee(){return(await g("/api/admin/workspaces")).items}async function Ae(){return(await g("/api/admin/workspace-apps")).items}function ie(e,t=""){return typeof e=="string"?e:t}function Ce(e){return Array.isArray(e)?e.filter(t=>typeof t=="string"):[]}function Ie(e){if(!e||typeof e!="object"||Array.isArray(e))return null;const t=e,s=t.kind==="image"||t.kind==="glyph"?t.kind:null;return s&&typeof t.value=="string"?{kind:s,value:t.value}:null}function Re(e){const t=e&&typeof e=="object"&&!Array.isArray(e)?e:{},s=ie(t.app_id);return{app_id:s,name:ie(t.name,s||"Unnamed app"),views:Ce(t.views),logo:Ie(t.logo)}}async function Le(){return((await g("/api/apps")).items||[]).map(Re).filter(t=>t.app_id)}function Me(e){const t=new URLSearchParams({consumer_app_id:e});return g(`/api/apps/dependencies?${t.toString()}`)}function Ue(e,t,s){return g("/api/apps/dependencies",{method:"POST",body:JSON.stringify({consumer_app_id:e,alias:t,provider_app_ids:s})})}function ee(){return g("/api/settings/platform")}function He(e){return g("/api/providers/active",{method:"POST",body:JSON.stringify(e)})}function De(e,t="settings_runtime_sessions_cleared"){return g("/api/settings/runtime-sessions/clear",{method:"POST",body:JSON.stringify({session_ids:e,reason:t})})}function Te(){return g("/api/auth/logout",{method:"POST"})}function Ne(e){return g("/api/admin/persistence/migrations/dry-run",{method:"POST",body:JSON.stringify(e)})}function Oe(e){return g("/api/admin/persistence/migrations/apply",{method:"POST",body:JSON.stringify(e)})}function je(e){return g("/api/admin/users",{method:"POST",body:JSON.stringify(e)})}function Be(e,t){return g(`/api/admin/users/${encodeURIComponent(e)}`,{method:"PATCH",body:JSON.stringify(t)})}function Fe(e,t){return g(`/api/admin/users/${encodeURIComponent(e)}/password`,{method:"POST",body:JSON.stringify({password:t})})}function qe(e){return g(`/api/admin/users/${encodeURIComponent(e)}`,{method:"DELETE"})}function We(e,t){return g(`/api/admin/users/${encodeURIComponent(e)}/workspaces`,{method:"PUT",body:JSON.stringify({memberships:t})})}function Je(e){return g(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"POST",body:JSON.stringify({source_id:e.source_id,enabled:!0})})}function Ke(e,t){return g(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"PATCH",body:JSON.stringify({status:t?"enabled":"disabled"})})}function ze(e){return g(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"DELETE",body:JSON.stringify({})})}function Y(e){const t=e?.provider.active_provider,s=e?.provider.model_settings,n=s?.selected_model_id||t?.default_model_family||"",a=te(e).find(l=>l.model_id===n)||null;return{modelId:n,reasoningEffort:s?.selected_reasoning_effort||ue(a)}}function te(e){const t=e?.provider.active_provider,s=e?.provider.model_settings,n=s?.selected_model_id||t?.default_model_family||"",a=X(s?.available_models).length?X(s?.available_models):X(t?.model_options);return(a.length?a:n?[Ge(n,s?.selected_reasoning_effort||"")]:[]).map(Ve)}function ue(e){return e?.default_reasoning_effort||e?.supported_reasoning_efforts[0]?.effort||""}function X(e){return(e||[]).filter(t=>t.model_id)}function Ve(e){return e.supported_reasoning_efforts.length||!e.default_reasoning_effort?e:{...e,supported_reasoning_efforts:[{effort:e.default_reasoning_effort,label:e.default_reasoning_effort,description:null}]}}function Ge(e,t){return{model_id:e,label:e,description:null,default_reasoning_effort:t||null,supported_reasoning_efforts:t?[{effort:t,label:t,description:null}]:[]}}const Qe=new Set(["created","running","stopping"]);function Xe(){return{cleanupError:"",clearingAllRuntime:!1,cleaningSessionIds:new Set,draftModelId:"",draftReasoningEffort:"",isSavingProvider:!1,providerError:""}}function se(e,t){const{modelId:s,reasoningEffort:n}=Y(t);e.draftModelId=s,e.draftReasoningEffort=n}function Ye(e,t,s){const n=te(t).find(a=>a.model_id===s)||null;e.draftModelId=s,e.draftReasoningEffort=ue(n),e.providerError=""}function Ze(e,t){if(!e)return`<section class="settings-card settings-platform">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Settings</p>
          <h2>Platform settings</h2>
        </div>
      </div>
      <p class="settings-card-copy">Platform settings are not available from the active backend.</p>
    </section>`;const s=e.provider.active_provider,n=nt(e),a=n.filter(C=>Qe.has(C.status)),l=e.runtime.cleanup_allowed??!1,i=e.runtime.cleanup_scope||"none",o=te(e),u=Y(e).modelId,h=Y(e).reasoningEffort,M=(o.find(C=>C.model_id===t.draftModelId)||o[0]||null)?.supported_reasoning_efforts||[],D=!!(s&&t.draftModelId&&!t.isSavingProvider&&(t.draftModelId!==u||t.draftReasoningEffort!==h));return`<section class="settings-card settings-platform">
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
          <h3>${b(e.user.display_name||e.user.username||"Unavailable")}</h3>
          <p>${b(e.user.platform_role||"member")} · ${b(e.workspace.name||e.workspace.workspace_id)}</p>
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
          <h3>${b(s?.label||"Provider not loaded")}</h3>
          <p>${b(u||"model")} · ${b(h||"reasoning")} · ${a.length} active / ${n.length} in scope</p>
        </div>
      </article>
    </div>
    ${et(o,M,D,t)}
    ${tt(n,l,i,t)}
  </section>`}function xe(e){document.getElementById("settings-provider-model")?.addEventListener("change",t=>{e.onProviderModelChanged(t.currentTarget.value)}),document.getElementById("settings-provider-reasoning")?.addEventListener("change",t=>{e.onProviderReasoningChanged(t.currentTarget.value)}),document.getElementById("settings-save-provider")?.addEventListener("click",e.onSaveProviderSettings),document.getElementById("settings-logout")?.addEventListener("click",e.onLogout),document.getElementById("settings-clear-all-runtime")?.addEventListener("click",e.onClearAllRuntimeSessions),document.querySelectorAll("[data-runtime-clear]").forEach(t=>{t.addEventListener("click",()=>e.onClearRuntimeSession(t.dataset.runtimeClear||""))})}function et(e,t,s,n){return`<div class="settings-platform-provider-form">
    <label class="settings-platform-field">
      <span>Model</span>
      <select id="settings-provider-model" ${!e.length||n.isSavingProvider?"disabled":""}>
        ${e.map(a=>`<option value="${W(a.model_id)}" ${a.model_id===n.draftModelId?"selected":""}>${b(a.label||a.model_id)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Reasoning</span>
      <select id="settings-provider-reasoning" ${!t.length||n.isSavingProvider?"disabled":""}>
        ${t.map(a=>`<option value="${W(a.effort)}" ${a.effort===n.draftReasoningEffort?"selected":""}>${b(a.label||a.effort)}</option>`).join("")}
      </select>
    </label>
    <button type="button" id="settings-save-provider" ${s?"":"disabled"}>
      <span class="material-symbols-rounded" aria-hidden="true">${n.isSavingProvider?"sync":"save"}</span>
      ${n.isSavingProvider?"Saving":"Save model"}
    </button>
    ${n.providerError?`<p class="settings-platform-error">${b(n.providerError)}</p>`:""}
  </div>`}function tt(e,t,s,n){return`<details class="settings-platform-runtime" open>
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
      ${e.length?e.map(l=>st(l,t,n)).join(""):'<p class="settings-card-copy">No runtime sessions.</p>'}
    </div>
    ${n.cleanupError?`<p class="settings-platform-error">${b(n.cleanupError)}</p>`:""}
  </details>`}function st(e,t,s){const n=s.cleaningSessionIds.has(e.session_id);return`<div class="settings-platform-runtime-row">
    <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">terminal</span>
    <span class="settings-platform-runtime-copy">
      <span class="settings-platform-runtime-title">
        <strong>${b(e.agent_id||e.session_id)}</strong>
        <button type="button" class="settings-secondary settings-platform-runtime-clear" data-runtime-clear="${W(e.session_id)}" aria-label="Clean runtime session ${W(e.agent_id||e.session_id)}" ${!t||s.clearingAllRuntime||n?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">${n?"sync":"delete_sweep"}</span>
          <span class="settings-platform-runtime-clear-label">${n?"Cleaning":"Clean"}</span>
        </button>
      </span>
      <small>${b(e.workspace_name||e.workspace_id)} · ${b(e.effective_mode)} · ${b(e.status)}</small>
      <code>${b(e.session_id)}</code>
    </span>
  </div>`}function nt(e){return e.runtime.all_sessions||e.runtime.sessions||[]}function b(e){return e.replace(/[&<>"']/g,t=>t==="&"?"&amp;":t==="<"?"&lt;":t===">"?"&gt;":t==='"'?"&quot;":"&#39;")}function W(e){return b(e)}const at=5,it=4,rt=4,ot=3,lt=2,dt=4;function ct(e){return`<section class="settings-loading-skeleton" role="status" aria-label="Settings content is loading">
    <header class="detail-header settings-loading-skeleton__header" aria-hidden="true">
      <div class="detail-title-block">
        ${p("title")}
        <span class="detail-title-separator" aria-hidden="true"></span>
        ${p("subtitle")}
      </div>
    </header>
    ${pt(e)}
  </section>`}function pt(e){return e.id==="workspace-access"?gt():e.id==="workspace-apps"?mt():e.id==="platform-settings"?ft():e.id==="persistence"?_t():ut()}function ut(){return`${F()}
    <section class="settings-card settings-loading-skeleton__create" aria-hidden="true">
      ${vt("short-title")}
      ${P(at,()=>w("field"))}
      ${w("button")}
    </section>
    ${ge()}
    <div class="settings-loading-skeleton__profile-row" aria-hidden="true">
      <section class="settings-card settings-loading-skeleton__detail-card">
        ${O(!0)}
        <div class="settings-loading-skeleton__field-grid">
          ${P(it,()=>J())}
        </div>
        ${w("toggle")}
        ${w("button")}
      </section>
      <section class="settings-card settings-loading-skeleton__password-card">
        ${O(!1)}
        ${p("copy")}
        <div class="settings-loading-skeleton__field-grid">
          ${P(2,()=>J())}
        </div>
        ${w("button")}
        ${w("danger-button")}
      </section>
    </div>`}function gt(){return`${F()}
    ${ge()}
    <section class="settings-card" aria-hidden="true">
      ${O(!0)}
      <div class="settings-loading-skeleton__rows">
        ${P(rt,()=>ht())}
      </div>
    </section>`}function mt(){return`${F()}
    <section class="settings-card" aria-hidden="true">
      ${O(!1)}
      ${p("copy-wide")}
      <div class="settings-loading-skeleton__rows">
        ${P(ot,()=>yt())}
      </div>
    </section>`}function ft(){return`${F()}
    <section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
      ${O(!1)}
      <div class="settings-loading-skeleton__settings-grid">
        ${P(lt,()=>bt())}
      </div>
      <div class="settings-loading-skeleton__provider-form">
        ${P(2,()=>J())}
        ${w("button")}
      </div>
      <div class="settings-loading-skeleton__runtime-list">
        ${P(dt,()=>wt())}
      </div>
    </section>`}function _t(){return`${F()}
    <section class="settings-card settings-loading-skeleton__persistence" aria-hidden="true">
      ${O(!0)}
      <div class="settings-loading-skeleton__adapter-cards">
        ${P(2,()=>kt())}
      </div>
      ${$t()}
    </section>`}function F(){return`<section class="settings-card settings-page-settings" aria-hidden="true">
    ${H("page")}
    <span class="settings-loading-skeleton__copy-stack">
      ${p("kicker")}
      ${p("card-title")}
      ${p("copy")}
    </span>
  </section>`}function ge(){return`<section class="settings-card settings-user-picker" aria-hidden="true">
    <div class="settings-loading-skeleton__copy-stack">
      ${p("kicker")}
      ${p("card-title")}
      ${p("copy-short")}
    </div>
    ${J()}
  </section>`}function O(e){return`<div class="settings-loading-skeleton__heading">
    <span class="settings-loading-skeleton__copy-stack">
      ${p("kicker")}
      ${p("card-title")}
    </span>
    ${e?w("pill"):""}
  </div>`}function vt(e){return`<div class="settings-loading-skeleton__copy-stack">
    ${p("kicker")}
    ${p(e)}
  </div>`}function J(){return`<span class="settings-loading-skeleton__field-wrap">
    ${p("label")}
    ${w("field")}
  </span>`}function ht(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--membership">
    ${w("checkbox")}
    ${H("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${p("row-title")}
      ${p("row-copy")}
    </span>
    ${w("select")}
  </span>`}function yt(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--app">
    ${H("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${p("row-title")}
      ${p("row-copy")}
    </span>
    ${w("toggle-pill")}
    ${w("button")}
  </span>`}function bt(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--tile">
    ${H("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${p("row-title")}
      ${p("row-copy")}
    </span>
  </span>`}function wt(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--runtime">
    ${H("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${p("row-title")}
      ${p("row-copy")}
    </span>
    ${w("button")}
  </span>`}function kt(){return`<span class="settings-loading-skeleton__adapter-card">
    ${H("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${p("row-title")}
      ${p("row-copy-wide")}
    </span>
    ${w("pill")}
  </span>`}function $t(){return`<span class="settings-loading-skeleton__result">
    ${H("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${p("row-title")}
      ${p("row-copy-wide")}
    </span>
  </span>`}function p(e){return`<span class="settings-loading-skeleton__line settings-loading-skeleton__line--${e}"></span>`}function w(e){return`<span class="settings-loading-skeleton__block settings-loading-skeleton__block--${e}"></span>`}function H(e){return`<span class="settings-loading-skeleton__icon settings-loading-skeleton__icon--${e}"></span>`}function P(e,t){return Array.from({length:e},t).join("")}function St({publishChanged:e,render:t,setNotice:s}){let n=[],a=[],l="",i=[],o="",u=!1,h=new Set;function A(){return{appRegistry:n,dependencies:a,error:l,isLoading:u,loadErrors:i,savingKeys:h}}function M(){n=[],a=[],l="",i=[],o=""}function D(){o=""}async function C(d,y,$=!1){if(!(!d||u)&&!(!$&&o===d)){u=!0,l="",i=[],t();try{const[v,c]=await Promise.all([Le(),Q(d,y)]);n=v,a=c,o=d}catch(v){a=[],o="",l=v instanceof Error?v.message:"Unable to load app links."}finally{u=!1,t()}}}async function G(d,y,$){const v=Pt(d,y);h=new Set([...h,v]),t();try{const c=await Ue(d,y,$);a=a.map(U=>U.consumer_app_id===d?c:U),e(d,c),s({tone:"success",message:"App link updated."})}finally{const c=new Set(h);c.delete(v),h=c,t()}}async function Q(d,y){const $=y.filter(c=>c.workspace_id===d&&c.status==="enabled"),v=await Promise.all($.map(async c=>{try{return{app:c,payload:await Me(c.app_id)}}catch(U){return{app:c,error:U instanceof Error?U.message:"Unable to load app links."}}}));return i=v.filter(c=>"error"in c).map(c=>({app_id:c.app.app_id,message:c.error,name:c.app.name||c.app.app_id})),v.filter(c=>"payload"in c&&c.payload.dependencies.length>0).map(c=>c.payload).sort((c,U)=>c.consumer_app_id.localeCompare(U.consumer_app_id))}return{ensureLoaded:C,invalidate:D,reset:M,saveDependencySelection:G,viewState:A}}function Pt(e,t){return`${e}:${t}`}function r(e){return e.replace(/[&<>"']/g,t=>t==="&"?"&amp;":t==="<"?"&lt;":t===">"?"&gt;":t==='"'?"&quot;":"&#39;")}function f(e){return r(e)}function j(e){return`<section class="settings-card settings-page-settings">
    <span class="settings-page-settings-icon material-symbols-rounded" aria-hidden="true">${r(e.icon)}</span>
    <span>
      <p class="settings-kicker">Settings page</p>
      <h2>${r(e.title)}</h2>
      <p class="settings-card-copy">${r(e.summary)}</p>
    </span>
  </section>`}function Et({appRegistry:e,dependencies:t,error:s,isLoading:n,loadErrors:a,page:l,savingKeys:i,workspaceApps:o}){return`${j(l)}
    <section class="settings-card settings-app-links">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">App links</p>
          <h2>Provider app links</h2>
        </div>
      </div>
      <p class="settings-card-copy">Provider links are workspace-scoped. A selected provider is reused until it becomes unavailable; otherwise one-provider interface links use the first available candidate as their automatic default.</p>
      ${s?`<p class="settings-platform-error">${r(s)}</p>`:""}
      ${a.length?`<div class="settings-app-link-errors">${a.map(Ht).join("")}</div>`:""}
      ${t.length>1?At(t,e,o):""}
      <div class="settings-app-link-list">
        ${t.length?t.map(u=>Ct(u,e,o,i)).join(""):Rt(s,n)}
      </div>
    </section>`}function At(e,t,s){return`<nav class="settings-app-link-consumer-nav" aria-label="Provider link apps">
    ${e.map(n=>{const a=s.find(o=>o.workspace_id===n.workspace_id&&o.app_id===n.consumer_app_id),l=ne(t,n.consumer_app_id),i=a?.name||l?.name||n.consumer_app_id;return`<a class="settings-app-link-consumer-nav__item" href="#${f(me(n.consumer_app_id))}">
        <strong>${r(i)}</strong>
        <small>${r(String(n.dependencies.length))}</small>
      </a>`}).join("")}
  </nav>`}function Ct(e,t,s,n){const a=s.find(i=>i.workspace_id===e.workspace_id&&i.app_id===e.consumer_app_id),l=ne(t,e.consumer_app_id);return`<article class="settings-app-link-consumer" id="${f(me(e.consumer_app_id))}">
    <header class="settings-app-link-consumer__header">
      ${_e(l,e.consumer_app_id)}
      <span class="settings-app-copy">
        <strong>${r(a?.name||e.consumer_app_id)}</strong>
        <small>${r(e.consumer_app_id)} - ${r(e.status)}</small>
      </span>
    </header>
    <div class="settings-app-link-dependencies">
      ${e.dependencies.map(i=>It(e.consumer_app_id,i,t,n)).join("")}
    </div>
  </article>`}function It(e,t,s,n){const a=n.has(Lt(e,t.alias)),l=Mt(t),i=fe(t);return`<section class="settings-app-link-row">
    <header class="settings-app-link-row__header">
      <span class="settings-app-link-row__copy">
        <strong>${r(t.alias)}</strong>
        <small>${r(t.interface)} ${r(t.version)}</small>
      </span>
      <span class="settings-pill ${t.status==="resolved"||i?"":"settings-pill-muted"}">${r(Ut(t,i))}</span>
    </header>
    <p class="settings-card-copy">${r(t.description||"No description.")}</p>
    ${t.blocked_reason?`<p class="settings-platform-error">${r(t.blocked_reason)}</p>`:""}
    ${t.stale_provider_app_ids.length?`<p class="settings-platform-error">Unavailable selection: ${r(t.stale_provider_app_ids.join(", "))}</p>`:""}
    ${t.candidates.length?`<div class="settings-app-link-candidates">
            ${t.candidates.map(o=>{const u=l.includes(o.app_id),h=t.cardinality==="many"?"checkbox":"radio",A=`dependency:${e}:${t.alias}`,M=ne(s,o.app_id);return`<label class="settings-app-link-candidate ${u?"is-selected":""}">
                <input
                  ${u?"checked":""}
                  ${a?"disabled":""}
                  data-dependency-choice="${f(re(e,t.alias,o.app_id))}"
                  name="${f(A)}"
                  type="${h}"
                />
                ${_e(M,o.app_id)}
                <span>
                  <strong>${r(o.name||o.app_id)}</strong>
                  <small>${r(o.app_id)} - ${r(o.interface_version)}${o.app_id===i?" - automatic default":""}</small>
                </span>
              </label>`}).join("")}
          </div>`:'<p class="settings-card-copy">No enabled provider app is available for this interface.</p>'}
    ${i?`<button type="button" class="settings-secondary" data-dependency-save-default="${f(re(e,t.alias,i))}" ${a?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">${a?"sync":"save"}</span>
          ${a?"Saving":"Save default"}
        </button>`:""}
  </section>`}function Rt(e,t){return e?"":t?'<p class="settings-card-copy">Loading app links...</p>':'<p class="settings-card-copy">No enabled app in the active workspace declares provider links.</p>'}function Lt(e,t){return`${e}:${t}`}function re(e,t,s){return`${e}:${t}:${s}`}function me(e){return`settings-app-link-consumer-${e}`}function Mt(e){if(e.selected_provider_app_ids.length)return e.selected_provider_app_ids;const t=fe(e);return t?[t]:[]}function fe(e){return e.selected_provider_app_ids.length||e.status!=="optional_unset"||e.cardinality!=="one"||e.stale_provider_app_ids.length||e.blocked_reason?"":e.candidates[0]?.app_id||""}function Ut(e,t){return t?"auto default":e.status==="optional_unset"?"unset":e.status}function ne(e,t){return e.find(s=>s.app_id===t)||null}function Ht(e){return`<p class="settings-platform-error">${r(e.name||e.app_id)}: ${r(e.message)}</p>`}function _e(e,t){if(e?.logo?.kind==="image"&&e.logo.value)return`<span class="settings-app-link-logo is-image"><img alt="" loading="lazy" src="${f(e.logo.value)}" /></span>`;const s=e?.logo?.value||Dt(e,t);return`<span class="settings-app-link-logo is-glyph"><span class="material-symbols-rounded" aria-hidden="true">${r(s)}</span></span>`}function Dt(e,t){const s={agents:"smart_toy","app-store":"storefront","base-shell":"dashboard",chat:"forum",checklist:"checklist",crm:"contacts","developer-kit":"developer_board","docs-studio":"description","document-generator":"description","dynamic-views":"dashboard_customize","gmail-app":"mail",memory:"database","maverick-monitor":"monitor_heart",settings:"admin_panel_settings",skills:"school",speech:"record_voice_over",storage:"cloud","website-studio":"web_asset"};return s[t]?s[t]:e?.views.includes("chat")?"forum":e?.views.includes("agents")?"smart_toy":e?.views.includes("shell")?"dashboard":"apps"}function Tt(e){document.getElementById("dismiss-notice")?.addEventListener("click",e.dismissNotice),document.getElementById("create-user")?.addEventListener("submit",s=>{s.preventDefault(),e.createUser(s.currentTarget).catch(e.showError)});const t=e.selectedUser();document.getElementById("selected-user")?.addEventListener("change",s=>{e.selectUser(s.currentTarget.value)}),document.getElementById("edit-user")?.addEventListener("submit",s=>{s.preventDefault(),t&&e.updateSelectedUser(s.currentTarget,t).catch(e.showError)}),document.getElementById("reset-password")?.addEventListener("submit",s=>{s.preventDefault(),t&&e.resetSelectedUserPassword(s.currentTarget,t).catch(e.showError)}),document.getElementById("delete-user")?.addEventListener("click",()=>{t&&e.deleteSelectedUser(t).catch(e.showError)}),document.getElementById("save-memberships")?.addEventListener("click",()=>{t&&e.updateMemberships(t).catch(e.showError)}),Ot(e),Nt(e),jt(e),xe({onClearAllRuntimeSessions:()=>{e.clearRuntimeSessionsFromPanel().catch(e.showError)},onClearRuntimeSession:s=>{s&&e.clearRuntimeSessionsFromPanel([s]).catch(e.showError)},onLogout:()=>{e.logoutFromSettings().catch(e.showError)},onProviderModelChanged:e.onProviderModelChanged,onProviderReasoningChanged:e.onProviderReasoningChanged,onSaveProviderSettings:()=>{e.saveProviderSettingsFromPanel().catch(e.showError)}})}function Nt(e){document.querySelectorAll("[data-dependency-choice]").forEach(t=>{t.addEventListener("change",()=>{const s=oe(t.dataset.dependencyChoice||"");if(!s)return;const n=e.appDependencies().find(l=>l.consumer_app_id===s.consumerAppId)?.dependencies.find(l=>l.alias===s.alias);if(!n)return;if(n.cardinality==="one"){e.saveDependencySelection(s.consumerAppId,s.alias,[s.providerAppId]).catch(e.showError);return}const a=new Set(n.selected_provider_app_ids);t.checked?a.add(s.providerAppId):a.delete(s.providerAppId),e.saveDependencySelection(s.consumerAppId,s.alias,Array.from(a)).catch(e.showError)})}),document.querySelectorAll("[data-dependency-save-default]").forEach(t=>{t.addEventListener("click",()=>{const s=oe(t.dataset.dependencySaveDefault||"");s&&e.saveDependencySelection(s.consumerAppId,s.alias,[s.providerAppId]).catch(e.showError)})})}function oe(e){const[t,s,...n]=e.split(":"),a=n.join(":");return!t||!s||!a?null:{alias:s,consumerAppId:t,providerAppId:a}}function Ot(e){document.querySelectorAll("[data-app-toggle]").forEach(t=>{t.addEventListener("change",()=>{const s=e.workspaceApps().find(n=>`${n.workspace_id}:${n.app_id}`===t.dataset.appToggle);s&&e.setWorkspaceAppStatus(s,t.checked).catch(e.showError)})}),document.querySelectorAll("[data-app-install]").forEach(t=>{t.addEventListener("click",()=>{const s=e.workspaceApps().find(n=>`${n.workspace_id}:${n.app_id}`===t.dataset.appInstall);s&&e.installWorkspaceApp(s).catch(e.showError)})}),document.querySelectorAll("[data-app-uninstall]").forEach(t=>{t.addEventListener("click",()=>{const s=e.workspaceApps().find(n=>`${n.workspace_id}:${n.app_id}`===t.dataset.appUninstall);s&&e.uninstallWorkspaceApp(s).catch(e.showError)})})}function jt(e){document.querySelectorAll("[data-adapter-target]").forEach(t=>{t.addEventListener("click",()=>{const s=t.dataset.adapterTarget;(s==="json"||s==="mongo")&&e.persistenceController.prepare(s).catch(e.showError)})}),document.getElementById("close-migration-modal")?.addEventListener("click",()=>{e.persistenceController.cancel()}),document.getElementById("cancel-migration")?.addEventListener("click",()=>{e.persistenceController.cancel()}),document.getElementById("validate-migration")?.addEventListener("click",()=>{e.persistenceController.validateDraft().catch(e.showError)}),document.querySelectorAll("[data-migration-field]").forEach(t=>{const s=n=>{const a=t.dataset.migrationField;if(a&&a in(e.persistenceController.viewState().targetDraft||{})){const l=!!e.persistenceController.viewState().migrationPlan;e.persistenceController.updateDraft(a,t.value,{render:n}),!n&&l&&Bt()}};t.addEventListener("input",()=>s(!1)),t.addEventListener("change",()=>s(!0))}),document.getElementById("settings-delete-source")?.addEventListener("change",t=>{e.persistenceController.setDeleteSource(t.currentTarget.checked)}),document.getElementById("confirm-migration")?.addEventListener("click",()=>{e.persistenceController.apply().catch(e.showError)})}function Bt(){const e=document.getElementById("confirm-migration");e&&(e.disabled=!0);const t=document.querySelector(".settings-migration-plan");if(!t)return;const s=t.querySelector(".material-symbols-rounded"),n=t.querySelector("strong"),a=t.querySelector("small");s&&(s.textContent="rule"),n&&(n.textContent="Dry run changed"),a&&(a.textContent="Validate the dry run again before applying migration."),t.querySelector(".settings-migration-collections")?.remove()}function Ft(e){let t=null,s=null,n="",a=null,l=null,i=null,o=!1;function u(){return{deleteSourceAfterMigration:o,migrationPlan:a,migrationProgress:i,migrationResult:l,migrationTarget:t,persistence:e.getPersistence(),targetDraft:s}}async function h(d){const y=e.getPersistence();if(!y||y.active_adapter.kind===d){D();return}t=d,s=qt(d,y),n="",a=null,o=!1,i=null,e.setNotice(null),e.render()}function A(d,y,$={}){s&&(s={...s,[d]:y},a=null,n="",i=null,$.render!==!1&&e.render())}function M(d){o=d,e.render()}function D(){t=null,s=null,a=null,n="",i=null,e.render()}async function C(){if(!(!s||!t)){i={target:t,phase:"validating",percent:10,title:`Dry run to ${t.toUpperCase()}`,detail:"Validating target adapter and collection copy plan before applying changes."},e.setNotice(null),e.render();try{const d=Z(s);a=await Ne(d),n=le(d)}catch(d){throw i=null,a=null,n="",d}i=null,a.same_adapter&&e.setNotice({tone:"info",message:"The selected persistence adapter is already active."}),e.render()}}async function G(){if(!s||!t)return;const d=Z(s),y=le(d);if(!a||n!==y){await C();return}if(a.same_adapter)return;i={target:t,phase:"applying",percent:38,title:`Migration to ${t.toUpperCase()}`,detail:"Copying the validated control-plane plan to the target adapter."},e.setNotice(null),e.render();try{l=await Oe({...d,delete_source:o,restart_backend:!0})}catch(v){throw i={target:t,phase:"failed",percent:100,title:"Migration failed",detail:v instanceof Error?v.message:"Unable to apply migration."},v}const $=t;t=null,s=null,a=null,n="",i={target:$,phase:"restarting",percent:68,title:"Restart backend",detail:l.backend_restart?.detail||"Backend restart scheduled."},e.render(),await Q($)}async function Q(d){const y=Date.now(),$=9e4;for(;Date.now()-y<$;){i={target:d,phase:"polling",percent:84,title:"Verifying cutover",detail:"Waiting for the backend to become healthy with the new adapter."},e.render();const v=await e.requestPersistenceStatusQuiet();if(v?.active_adapter.kind===d){e.setPersistence(v);const c=l?.source_cleanup?.scheduled===!0;i={target:d,phase:"complete",percent:100,title:"Migration complete",detail:c?`Active adapter: ${d.toUpperCase()}. Source cleanup is scheduled after health check.`:`Active adapter: ${d.toUpperCase()}. Source storage was preserved.`},e.setNotice({tone:"success",message:`Migration to ${d.toUpperCase()} complete.`}),e.render();return}await new Promise(c=>window.setTimeout(c,1500))}i={target:d,phase:"failed",percent:100,title:"Verification not completed",detail:"The backend did not confirm the new adapter before the timeout. Check service health and logs."},e.setNotice({tone:"error",message:"Migration not confirmed before the timeout."}),e.render()}return{apply:G,cancel:D,prepare:h,setDeleteSource:M,updateDraft:A,validateDraft:C,viewState:u}}function qt(e,t){const s=t.active_adapter;return{kind:e,json_root:s.json_root||"data/control-plane/json",mongodb_uri:s.mongo_uri||"mongodb://127.0.0.1:27017/maverick",mongodb_database:s.mongo_database||"maverick",mongodb_username:s.mongo_username||"",mongodb_password_ref:s.mongo_password_ref||""}}function Z(e){return{kind:e.kind,json_root:e.json_root.trim()||"data/control-plane/json",mongodb_uri:e.mongodb_uri.trim(),mongodb_database:e.mongodb_database.trim()||"maverick",mongodb_username:e.mongodb_username?.trim()||void 0,mongodb_password_ref:e.mongodb_password_ref?.trim()||void 0}}function le(e){return JSON.stringify(Z(e))}function Wt(e,t){return`${j(e)}
    ${zt(t)}`}function Jt(e){const{deleteSourceAfterMigration:t,migrationPlan:s,migrationProgress:n,migrationTarget:a,persistence:l}=e;if(!a||!l)return"";const i=l.active_adapter.kind.toUpperCase(),o=a.toUpperCase(),u=!!(n&&!["complete","failed"].includes(n.phase)),h=!!(s&&!s.same_adapter&&!u);return`<div class="settings-modal-backdrop" role="presentation">
    <section class="settings-modal" role="dialog" aria-modal="true" aria-labelledby="adapter-migration-title">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Confirm migration</p>
          <h2 id="adapter-migration-title">${i} → ${o}</h2>
        </div>
        <button type="button" class="settings-icon-button" id="close-migration-modal" aria-label="Close" ${u?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">close</span>
        </button>
      </div>
      ${s?Xt(s):Qt(n)}
      ${Kt(e)}
      <label class="settings-toggle settings-migration-delete-source">
        <input id="settings-delete-source" type="checkbox" ${t?"checked":""} ${u?"disabled":""} />
        Schedule source cleanup after restart health check
      </label>
      <p class="settings-card-copy">Leave cleanup off to preserve the current source adapter data as a rollback point. Cleanup is a separate explicit choice and requires backend restart.</p>
      <div class="settings-modal-actions">
        <button type="button" class="settings-secondary" id="cancel-migration" ${u?"disabled":""}>Cancel</button>
        <button type="button" class="settings-secondary" id="validate-migration" ${u?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">rule</span>
          Validate dry run
        </button>
        <button type="button" class="${t?"settings-danger":"settings-secondary"}" id="confirm-migration" ${h?"":"disabled"}>
          <span class="material-symbols-rounded" aria-hidden="true">sync_alt</span>
          ${t?"Apply and schedule cleanup":"Apply migration"}
        </button>
      </div>
    </section>
  </div>`}function Kt(e){const t=e.targetDraft;if(!t)return"";const s=!!(e.migrationProgress&&!["complete","failed"].includes(e.migrationProgress.phase));return`<div class="settings-migration-target">
    <label class="settings-platform-field">
      <span>JSON root</span>
      <input data-migration-field="json_root" value="${f(t.json_root)}" ${s?"disabled":""} />
    </label>
    ${t.kind==="mongo"?`<label class="settings-platform-field">
          <span>Mongo URI</span>
          <input data-migration-field="mongodb_uri" value="${f(t.mongodb_uri)}" ${s?"disabled":""} />
        </label>
        <label class="settings-platform-field">
          <span>Mongo database</span>
          <input data-migration-field="mongodb_database" value="${f(t.mongodb_database)}" ${s?"disabled":""} />
        </label>
        <label class="settings-platform-field">
          <span>Mongo username</span>
          <input data-migration-field="mongodb_username" value="${f(t.mongodb_username||"")}" ${s?"disabled":""} />
        </label>
        <label class="settings-platform-field">
          <span>Password secret ref</span>
          <input data-migration-field="mongodb_password_ref" value="${f(t.mongodb_password_ref||"")}" ${s?"disabled":""} />
        </label>`:""}
  </div>`}function zt(e){const{migrationProgress:t,migrationResult:s,persistence:n}=e;if(!n)return`<section class="settings-card settings-persistence">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Persistence</p>
          <h2>Control plane adapter</h2>
        </div>
        <span class="settings-pill settings-pill-muted">offline</span>
      </div>
      <p class="settings-card-copy">The core persistence surfaces are not available in the active backend.</p>
    </section>`;const a=n.active_adapter,l=n.collections.reduce((h,A)=>h+A.count,0),i=a.kind==="json",o=a.kind==="mongo",u=t&&!["complete","failed"].includes(t.phase);return`<section class="settings-card settings-persistence">
    <div class="settings-heading">
      <div>
        <p class="settings-kicker">Persistence</p>
        <h2>Control plane adapter</h2>
      </div>
      <span class="settings-pill">${l} documents</span>
    </div>
    <div class="settings-adapter-cards">
      <button type="button" class="settings-adapter-card ${i?"is-active":""}" ${i||u?"disabled":'data-adapter-target="json"'}>
        <span class="settings-adapter-card-icon material-symbols-rounded" aria-hidden="true">${i?"check_circle":"database"}</span>
        <span>
          <strong>JSON</strong>
          <small>${r(i?a.json_root:"data/control-plane/json")}</small>
        </span>
        <em>${i?"Current":"Review migration"}</em>
      </button>
      <button type="button" class="settings-adapter-card ${o?"is-active":""}" ${o||u?"disabled":'data-adapter-target="mongo"'}>
        <span class="settings-adapter-card-icon material-symbols-rounded" aria-hidden="true">${o?"check_circle":"database"}</span>
        <span>
          <strong>Mongo</strong>
          <small>${r(o?a.mongo_database:"mongodb://127.0.0.1:27017/maverick")}</small>
        </span>
        <em>${o?"Current":"Review migration"}</em>
      </button>
    </div>
    ${Vt(t)}
    ${Gt(s)}
  </section>`}function Vt(e){return e?`<div class="settings-migration-progress ${e.phase==="failed"?"is-failed":""} ${e.phase==="complete"?"is-complete":""}">
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
  </div>`:""}function Gt(e){return e?`<div class="settings-migration-result">
    <span class="material-symbols-rounded" aria-hidden="true">task_alt</span>
    <span>
      <strong>Last migration</strong>
      <small>${e.collections.reduce((s,n)=>s+n.count,0)} documents · target ${r(e.target_adapter.kind)} · cleanup ${e.source_cleanup?.scheduled?"scheduled":"not requested"}</small>
    </span>
  </div>`:""}function Qt(e){return`<div class="settings-migration-plan">
    <span class="material-symbols-rounded" aria-hidden="true">rule</span>
    <span>
      <strong>${r(e?.title||"Dry run not validated")}</strong>
      <small>${r(e?.detail||"Adjust the target fields, then validate the dry run before applying migration.")}</small>
    </span>
  </div>`}function Xt(e){const t=e.collections.reduce((n,a)=>n+a.count,0),s=e.target_collections.reduce((n,a)=>n+a.count,0);return`<div class="settings-migration-plan">
    <span class="material-symbols-rounded" aria-hidden="true">${e.same_adapter?"block":"rule"}</span>
    <span>
      <strong>${e.same_adapter?"Target already active":"Dry run complete"}</strong>
      <small>${t} source documents · ${s} target documents before copy · env ${r(e.env_file)}</small>
    </span>
    <div class="settings-migration-collections">
      ${e.collections.map(n=>`<span><strong>${r(n.name)}</strong><small>${n.count}</small></span>`).join("")}
    </div>
  </div>`}function Yt({page:e,pendingDeleteUserId:t,selectedUser:s,users:n}){return`${j(e)}
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
    ${ve(n,s)}
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
              <label>Name<input name="display_name" value="${f(s.display_name||"")}" /></label>
              <label>Email<input name="email" type="email" value="${f(s.email||"")}" /></label>
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
        </div>`:'<section class="settings-card"><h2>No users</h2></section>'}`}function Zt({page:e,selectedUser:t,users:s,workspaces:n}){return`${j(e)}
    ${ve(s,t)}
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
          <div class="settings-memberships">${xt(t,n)}</div>
        </section>`:'<section class="settings-card"><h2>No users</h2></section>'}`}function ve(e,t){return e.length?`<section class="settings-card settings-user-picker">
    <div>
      <p class="settings-kicker">User directory</p>
      <h2>${r(t?t.display_name||t.username:"Select user")}</h2>
      <p class="settings-card-copy">${e.length} user${e.length===1?"":"s"} available.</p>
    </div>
    <label class="settings-platform-field">
      <span>Selected user</span>
      <select id="selected-user">
        ${e.map(s=>`<option value="${f(s.user_id)}" ${s.user_id===t?.user_id?"selected":""}>${r(s.display_name||s.username)} (${r(s.username)})</option>`).join("")}
      </select>
    </label>
  </section>`:`<section class="settings-card settings-user-picker">
      <div>
        <p class="settings-kicker">User directory</p>
        <h2>No users</h2>
      </div>
      <p class="settings-card-copy">Create a user before editing profile or workspace access settings.</p>
    </section>`}function xt(e,t){return t.map(s=>{const n=e.memberships.find(a=>a.workspace_id===s.workspace_id);return`<label class="settings-membership">
        <input type="checkbox" data-workspace-enabled="${f(s.workspace_id)}" ${n?"checked":""} />
        <span class="settings-membership-icon material-symbols-rounded" aria-hidden="true">workspaces</span>
        <span>
          <strong>${r(s.name)}</strong>
          <small>${r(s.workspace_id)}</small>
        </span>
        <select data-workspace-role="${f(s.workspace_id)}">
          <option value="member" ${n?.role!=="admin"?"selected":""}>Member</option>
          <option value="admin" ${n?.role==="admin"?"selected":""}>Workspace admin</option>
        </select>
      </label>`}).join("")}function es({page:e,workspaceApps:t,workspaces:s}){return`${j(e)}
    <section class="settings-card">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Workspace apps</p>
          <h2>Installation and visibility</h2>
        </div>
      </div>
      <p class="settings-card-copy">Installed means the app has a workspace binding. Only enabled apps are visible to users and served by the core.</p>
      <div class="settings-app-workspaces">${ts(s,t)}</div>
    </section>`}function ts(e,t){return e.map(s=>{const n=t.filter(i=>i.workspace_id===s.workspace_id),a=n.filter(i=>i.status==="enabled").length,l=n.filter(i=>i.installed).length;return`<details class="settings-app-workspace">
        <summary class="settings-app-workspace-heading">
          <span class="settings-summary-caret material-symbols-rounded" aria-hidden="true">chevron_right</span>
          <span class="settings-app-workspace-icon material-symbols-rounded" aria-hidden="true">deployed_code</span>
          <span>
            <strong>${r(s.name)}</strong>
            <small>${r(s.workspace_id)} · ${a}/${l} enabled</small>
          </span>
        </summary>
        <div class="settings-apps">
          ${n.map(ss).join("")}
        </div>
      </details>`}).join("")}function ss(e){const t=e.status==="enabled",s=e.installed,n=s?e.status:"not installed",a=`${e.workspace_id}:${e.app_id}`;return`<div class="settings-app-row">
    <span class="settings-app-icon material-symbols-rounded" aria-hidden="true">${r(ns(e))}</span>
    <span class="settings-app-copy">
      <strong>${r(e.name)}</strong>
      <small>${r(e.app_id)} · v${r(e.version)} · ${r(n)}</small>
    </span>
    ${s?`<label class="settings-switch">
          <input type="checkbox" data-app-toggle="${f(a)}" ${t?"checked":""} />
          <span>Enabled</span>
        </label>
        <button type="button" class="settings-secondary" data-app-uninstall="${f(a)}">
          <span class="material-symbols-rounded" aria-hidden="true">link_off</span>
          Uninstall
        </button>`:`<button type="button" class="settings-secondary" data-app-install="${f(a)}">
          <span class="material-symbols-rounded" aria-hidden="true">add_link</span>
          Install
        </button>`}
  </div>`}function ns(e){return e.status!=="enabled"?"hide_source":{agents:"smart_toy","app-store":"storefront","base-shell":"dashboard",browser:"language",calendar:"calendar_month",chat:"forum",checklist:"checklist",crm:"contacts","developer-kit":"developer_board","docs-studio":"description","document-generator":"description","dynamic-views":"dashboard_customize","gmail-app":"mail",mail:"mail",memory:"database","maverick-monitor":"monitor_heart",settings:"admin_panel_settings",skills:"school",speech:"record_voice_over",storage:"cloud",vault:"key","website-studio":"web_asset"}[e.app_id]||"apps"}let I=[],K=[],B=[],x=null,S=null,m=Xe();const he=Object.fromEntries(new URLSearchParams(window.location.search).entries());let z=pe(he)||$e,E=be(he),T=!0,N="",k=null,de="",ce="";const ae=Ft({getPersistence:()=>x,render:()=>_(),requestPersistenceStatusQuiet:ls,setNotice:e=>{k=e},setPersistence:e=>{x=e}}),R=St({publishChanged:ks,render:()=>_(),setNotice:e=>{k=e}});function ye(){return I.find(e=>e.user_id===E)||I[0]}function be(e){const t=q(e.user_id)||q(e.selected_user_id)||q(e.id);if(t)return t;const s=q(e.app_page),n=/^users\/([^/?#]+)$/.exec(s);if(!n?.[1])return"";try{return decodeURIComponent(n[1])}catch{return n[1]}}function q(e){return typeof e=="string"?e.trim():""}function as(e){const t=pe(e),s=be(e);let n=!1;t&&t!==z&&(z=t,n=!0),s&&s!==E&&(E=s,N="",n=!0),n&&((I.length||T)&&_(),t==="app-links"&&we())}function is(e){e.id===de||window.parent===window||(de=e.id,window.parent.postMessage({type:"maverick.app.selection-changed",owner_app_id:"settings",selection:{page_id:e.id}},window.location.origin))}function rs(e){!e||e.user_id===ce||window.parent===window||(ce=e.user_id,window.parent.postMessage({type:"maverick.app.selection-changed",owner_app_id:"settings",selection:{user_id:e.user_id}},window.location.origin))}function V(){window.parent!==window&&window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"settings",resource:"users"},window.location.origin)}async function os(){try{return await g("/api/admin/persistence")}catch(e){return k={tone:"error",message:e instanceof Error?e.message:"Persistence API unavailable"},null}}async function ls(){try{return await g("/api/admin/persistence")}catch{return null}}async function ds(){try{return await ee()}catch{return null}}async function L(){T=!0,_();try{const[e,t,s,n,a]=await Promise.all([Pe(),Ee(),Ae(),os(),ds()]),l=S?.workspace.workspace_id||"",i=a?.workspace.workspace_id||"";I=e,K=t,B=s,x=n,S=a,l!==i&&R.reset(),se(m,S),(!E||!I.some(o=>o.user_id===E))&&(E=I[0]?.user_id||"")}finally{T=!1}_(),z==="app-links"&&we()}async function we(e=!1){const t=S?.workspace.workspace_id||"";await R.ensureLoaded(t,B,e)}async function cs(e){const t=new FormData(e);E=(await je({username:String(t.get("username")||""),password:String(t.get("password")||""),display_name:String(t.get("display_name")||""),email:String(t.get("email")||""),platform_role:String(t.get("platform_role")||"member")})).user_id,e.reset(),await L(),V()}async function ps(e,t){const s=new FormData(e);await Be(t.user_id,{display_name:String(s.get("display_name")||""),email:String(s.get("email")||""),platform_role:String(s.get("platform_role")||"member"),account_type:String(s.get("account_type")||"standard"),is_active:s.get("is_active")==="on"}),await L(),V()}async function us(e,t){const s=new FormData(e),n=String(s.get("password")||""),a=String(s.get("password_confirmation")||"");if(n!==a)throw new Error("Passwords do not match");await Fe(t.user_id,n),e.reset(),k={tone:"success",message:"Password updated."},_()}async function gs(e){const t=e.display_name||e.username;if(N!==e.user_id){N=e.user_id,k={tone:"info",message:`Press Delete user again to confirm permanent removal of ${t}.`},_();return}await qe(e.user_id),E="",N="",k={tone:"success",message:`${t} deleted.`},await L(),V()}async function ms(e){const t=K.map(s=>{const n=document.querySelector(`[data-workspace-enabled="${s.workspace_id}"]`),a=document.querySelector(`[data-workspace-role="${s.workspace_id}"]`);return n?.checked?{workspace_id:s.workspace_id,role:a?.value||"member"}:null}).filter(s=>!!s);await We(e.user_id,t),await L(),V()}async function fs(e){await Je(e),R.invalidate(),await L()}async function _s(e,t){await Ke(e,t),R.invalidate(),await L()}async function vs(e){await ze(e),R.invalidate(),await L()}async function hs(e,t,s){await R.saveDependencySelection(e,t,s)}async function ys(){const e=S?.provider.active_provider?.provider_id;if(!e||!m.draftModelId){m.providerError="Provider not loaded.",_();return}m.isSavingProvider=!0,m.providerError="",_();try{await He({provider_id:e,model_id:m.draftModelId,model_reasoning_effort:m.draftReasoningEffort||null}),S=await ee(),se(m,S),k={tone:"success",message:"Provider settings updated."}}catch(t){m.providerError=t instanceof Error?t.message:"Unable to update provider settings."}finally{m.isSavingProvider=!1,_()}}async function bs(e){const t=(e||[]).filter(Boolean);m.cleanupError="",t.length?t.forEach(s=>m.cleaningSessionIds.add(s)):m.clearingAllRuntime=!0,_();try{const s=await De(t.length?t:void 0);ws(s),S=await ee(),se(m,S),k={tone:"success",message:t.length?"Runtime session cleaned.":"Runtime sessions cleaned."}}catch(s){m.cleanupError=s instanceof Error?s.message:"Unable to clean runtime sessions."}finally{t.forEach(s=>m.cleaningSessionIds.delete(s)),m.clearingAllRuntime=!1,_()}}function ws(e){e.deleted_threads<=0||window.parent===window||(window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"chat",resource:"threads"},window.location.origin),e.deleted_thread_ids.forEach(t=>{window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"chat",resource:"threads",deleted_thread_id:t},window.location.origin)}))}function ks(e,t){window.parent!==window&&window.parent.postMessage({type:"maverick.app.dependencies-changed",app_id:e,status:t.status},window.location.origin)}async function $s(){if(window.parent&&window.parent!==window){window.parent.postMessage({type:"maverick.shell.logout"},window.location.origin);return}await Te(),window.location.href="/"}function Ss(e,t){if(e.id==="users")return Yt({page:e,pendingDeleteUserId:N,selectedUser:t,users:I});if(e.id==="workspace-access")return Zt({page:e,selectedUser:t,users:I,workspaces:K});if(e.id==="workspace-apps")return es({page:e,workspaceApps:B,workspaces:K});if(e.id==="app-links"){const s=R.viewState();return Et({appRegistry:s.appRegistry,dependencies:s.dependencies,error:s.error,isLoading:s.isLoading,loadErrors:s.loadErrors,page:e,savingKeys:s.savingKeys,workspaceApps:B})}return e.id==="platform-settings"?Ps(e):Wt(e,ae.viewState())}function Ps(e){return`${j(e)}
    ${Ze(S,m)}`}function _(){const e=document.getElementById("app"),t=T?void 0:ye(),s=Se(z);e&&(e.innerHTML=`<main class="settings-shell">
    <section class="settings-main">
      <div class="settings-content">
        ${T?ct(s):`<header class="detail-header">
          <div class="detail-title-block">
            <h2>${r(s.title)}</h2>
            <span class="detail-title-separator" aria-hidden="true"></span>
            <p>${r(s.summary)}</p>
          </div>
        </header>
        ${As()}
        ${Ss(s,t)}`}
      </div>
    </section>
    ${Jt(ae.viewState())}
  </main>`,Es(),is(s),T||rs(t))}function Es(){Tt({clearRuntimeSessionsFromPanel:bs,createUser:cs,deleteSelectedUser:gs,dismissNotice:()=>{k=null,_()},installWorkspaceApp:fs,logoutFromSettings:$s,onProviderModelChanged:e=>{Ye(m,S,e),_()},onProviderReasoningChanged:e=>{m.draftReasoningEffort=e,m.providerError="",_()},persistenceController:ae,render:_,resetSelectedUserPassword:us,saveDependencySelection:hs,saveProviderSettingsFromPanel:ys,selectedUser:ye,selectUser:e=>{E=e,N="",_()},setWorkspaceAppStatus:_s,showError:ke,uninstallWorkspaceApp:vs,updateMemberships:ms,updateSelectedUser:ps,workspaceApps:()=>B,appDependencies:()=>R.viewState().dependencies})}function ke(e){k={tone:"error",message:e instanceof Error?e.message:"Unexpected error"},_()}function As(){return k?`<div class="settings-notice settings-notice-${k.tone}">
    <span class="material-symbols-rounded" aria-hidden="true">${k.tone==="error"?"error":k.tone==="success"?"task_alt":"info"}</span>
    <span>${r(k.message)}</span>
    <button type="button" class="settings-icon-button" id="dismiss-notice" aria-label="Close">
      <span class="material-symbols-rounded" aria-hidden="true">close</span>
    </button>
  </div>`:""}window.addEventListener("message",e=>{if(e.origin!==window.location.origin||!e.data||typeof e.data!="object")return;const t=e.data;t.type==="maverick.app.navigate"&&(!t.app_id||t.app_id==="settings")&&as(t.params||{})});window.parent?.postMessage({type:"maverick.app.ready",app_id:"settings"},window.location.origin);L().catch(ke);
