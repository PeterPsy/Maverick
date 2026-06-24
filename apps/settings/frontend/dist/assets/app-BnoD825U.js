import{s as ue,D as Ie,a as Ce}from"./pages-BZUBskpf.js";async function m(e,t={}){const s=await fetch(e,{credentials:"same-origin",headers:{"Content-Type":"application/json",...t.headers||{}},...t}),n=await s.json();if(!s.ok)throw new Error(n.detail||n.error||`Request failed ${s.status}`);return n}async function He(){return(await m("/api/admin/users")).items}async function Me(){return(await m("/api/admin/workspaces")).items}async function Re(){return(await m("/api/admin/workspace-apps")).items}function ie(e,t=""){return typeof e=="string"?e:t}function De(e){return Array.isArray(e)?e.filter(t=>typeof t=="string"):[]}function Le(e){if(!e||typeof e!="object"||Array.isArray(e))return null;const t=e,s=t.kind==="image"||t.kind==="glyph"?t.kind:null;return s&&typeof t.value=="string"?{kind:s,value:t.value}:null}function Ue(e){const t=e&&typeof e=="object"&&!Array.isArray(e)?e:{},s=ie(t.app_id);return{app_id:s,name:ie(t.name,s||"Unnamed app"),views:De(t.views),logo:Le(t.logo)}}async function Te(){return((await m("/api/apps")).items||[]).map(Ue).filter(t=>t.app_id)}function Ne(e){const t=new URLSearchParams({consumer_app_id:e});return m(`/api/apps/dependencies?${t.toString()}`)}function Oe(e,t,s){return m("/api/apps/dependencies",{method:"POST",body:JSON.stringify({consumer_app_id:e,alias:t,provider_app_ids:s})})}function Q(){return m("/api/settings/platform")}function Be(e){return m("/api/providers/active",{method:"POST",body:JSON.stringify(e)})}function je(e){return m("/api/providers/hosted/selection",{method:"POST",body:JSON.stringify(e)})}function Fe(e,t="settings_runtime_sessions_cleared"){return m("/api/settings/runtime-sessions/clear",{method:"POST",body:JSON.stringify({session_ids:e,reason:t})})}function qe(){return m("/api/auth/logout",{method:"POST"})}function We(e){return m("/api/admin/persistence/migrations/dry-run",{method:"POST",body:JSON.stringify(e)})}function Je(e){return m("/api/admin/persistence/migrations/apply",{method:"POST",body:JSON.stringify(e)})}function Ke(e){return m("/api/admin/users",{method:"POST",body:JSON.stringify(e)})}function ze(e,t){return m(`/api/admin/users/${encodeURIComponent(e)}`,{method:"PATCH",body:JSON.stringify(t)})}function Ve(e,t){return m(`/api/admin/users/${encodeURIComponent(e)}/password`,{method:"POST",body:JSON.stringify({password:t})})}function Ge(e){return m(`/api/admin/users/${encodeURIComponent(e)}`,{method:"DELETE"})}function Qe(e,t){return m(`/api/admin/users/${encodeURIComponent(e)}/workspaces`,{method:"PUT",body:JSON.stringify({memberships:t})})}function Xe(e){return m(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"POST",body:JSON.stringify({source_id:e.source_id,enabled:!0})})}function Ye(e,t){return m(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"PATCH",body:JSON.stringify({status:t?"enabled":"disabled"})})}function Ze(e){return m(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"DELETE",body:JSON.stringify({})})}function x(e){const t=e?.provider.active_provider,s=e?.provider.model_settings;return fe(t,s,se(e))}function se(e){const t=e?.provider.active_provider,s=e?.provider.model_settings;return ve(t,s)}function ge(e){const t=e?.provider.hosted_text?.active_provider||null,s=e?.provider.hosted_text?.model_settings||null;return fe(t,s,me(e))}function me(e){const t=e?.provider.hosted_text?.active_provider||null,s=e?.provider.hosted_text?.model_settings||null;return ve(t,s)}function fe(e,t,s){const n=t?.selected_model_id||e?.default_model_family||"",a=s.find(o=>o.model_id===n)||null;return{modelId:n,reasoningEffort:t?.selected_reasoning_effort||_e(a)}}function ve(e,t){const s=t?.selected_model_id||e?.default_model_family||"",n=Z(t?.available_models).length?Z(t?.available_models):Z(e?.model_options);return(n.length?n:s?[et(s,t?.selected_reasoning_effort||"")]:[]).map(xe)}function _e(e){return e?.default_reasoning_effort||e?.supported_reasoning_efforts[0]?.effort||""}function Z(e){return(e||[]).filter(t=>t.model_id)}function xe(e){return e.supported_reasoning_efforts.length||!e.default_reasoning_effort?e:{...e,supported_reasoning_efforts:[{effort:e.default_reasoning_effort,label:e.default_reasoning_effort,description:null}]}}function et(e,t){return{model_id:e,label:e,description:null,default_reasoning_effort:t||null,supported_reasoning_efforts:t?[{effort:t,label:t,description:null}]:[]}}const tt=new Set(["created","running","stopping"]);function st(){return{cleanupError:"",clearingAllRuntime:!1,cleaningSessionIds:new Set,draftModelId:"",draftReasoningEffort:"",hostedDraftModelId:"",hostedProviderError:"",isSavingHostedProvider:!1,isSavingProvider:!1,providerError:""}}function X(e,t){const{modelId:s,reasoningEffort:n}=x(t),{modelId:a}=ge(t);e.draftModelId=s,e.draftReasoningEffort=n,e.hostedDraftModelId=a}function nt(e,t,s){const n=se(t).find(a=>a.model_id===s)||null;e.draftModelId=s,e.draftReasoningEffort=_e(n),e.providerError=""}function at(e,t){e.hostedDraftModelId=t,e.hostedProviderError=""}function it(e,t){if(!e)return`<section class="settings-card settings-platform">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Settings</p>
          <h2>Platform settings</h2>
        </div>
      </div>
      <p class="settings-card-copy">Platform settings are not available from the active backend.</p>
    </section>`;const s=e.provider.active_provider,n=e.provider.hosted_text?.active_provider||null,a=pt(e),o=a.filter(g=>tt.has(g.status)),i=e.runtime.cleanup_allowed??!1,l=e.runtime.cleanup_scope||"none",u=se(e),y=me(e),S=x(e).modelId,C=x(e).reasoningEffort,E=ge(e).modelId,U=y.find(g=>g.model_id===E)||null,j=n?`${U?.label||E||"Hosted model"} - ${n.label||n.provider_id}`:"No hosted text provider",d=(u.find(g=>g.model_id===t.draftModelId)||u[0]||null)?.supported_reasoning_efforts||[],_=!!(s&&t.draftModelId&&!t.isSavingProvider&&(t.draftModelId!==S||t.draftReasoningEffort!==C)),w=!!(n&&t.hostedDraftModelId&&!t.isSavingHostedProvider&&t.hostedDraftModelId!==E);return`<section class="settings-card settings-platform">
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
          <h3>${f(e.user.display_name||e.user.username||"Unavailable")}</h3>
          <p>${f(e.user.platform_role||"member")} · ${f(e.workspace.name||e.workspace.workspace_id)}</p>
          <button type="button" class="settings-secondary settings-platform-logout" id="settings-logout">
            <span class="material-symbols-rounded" aria-hidden="true">logout</span>
            Logout
          </button>
        </div>
      </article>
      <article class="settings-platform-tile settings-platform-provider">
        <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">memory</span>
        <div>
          <p class="settings-kicker">Agentic provider</p>
          <h3>${f(s?.label||"Provider not loaded")}</h3>
          <p>${f(S||"model")} · ${f(C||"reasoning")} · Codex tools/filesystem/MCP · ${o.length} active / ${a.length} in scope</p>
        </div>
      </article>
      <article class="settings-platform-tile settings-platform-provider">
        <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">bolt</span>
        <div>
          <p class="settings-kicker">Hosted chat / fast model</p>
          <h3>${f(j)}</h3>
          <p>${f(E||"model not selected")} · plain hosted chat only · runtime engine remains Codex</p>
        </div>
      </article>
    </div>
    <div class="settings-platform-provider-forms">
      ${ot(u,d,_,t)}
      ${lt(y,w,t,!!n)}
    </div>
    ${dt(a,i,l,t)}
  </section>`}function rt(e){document.getElementById("settings-provider-model")?.addEventListener("change",t=>{e.onProviderModelChanged(t.currentTarget.value)}),document.getElementById("settings-provider-reasoning")?.addEventListener("change",t=>{e.onProviderReasoningChanged(t.currentTarget.value)}),document.getElementById("settings-hosted-provider-model")?.addEventListener("change",t=>{e.onHostedProviderModelChanged(t.currentTarget.value)}),document.getElementById("settings-save-provider")?.addEventListener("click",e.onSaveProviderSettings),document.getElementById("settings-save-hosted-provider")?.addEventListener("click",e.onSaveHostedProviderSettings),document.getElementById("settings-logout")?.addEventListener("click",e.onLogout),document.getElementById("settings-clear-all-runtime")?.addEventListener("click",e.onClearAllRuntimeSessions),document.querySelectorAll("[data-runtime-clear]").forEach(t=>{t.addEventListener("click",()=>e.onClearRuntimeSession(t.dataset.runtimeClear||""))})}function ot(e,t,s,n){return`<div class="settings-platform-provider-form">
    <div class="settings-platform-form-heading">
      <span class="material-symbols-rounded" aria-hidden="true">terminal</span>
      <span>
        <strong>Codex agent model</strong>
        <small>Agentic sessions, tools, filesystem, MCP and skills</small>
      </span>
    </div>
    <label class="settings-platform-field">
      <span>Model</span>
      <select id="settings-provider-model" ${!e.length||n.isSavingProvider?"disabled":""}>
        ${e.map(a=>`<option value="${F(a.model_id)}" ${a.model_id===n.draftModelId?"selected":""}>${f(a.label||a.model_id)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Reasoning</span>
      <select id="settings-provider-reasoning" ${!t.length||n.isSavingProvider?"disabled":""}>
        ${t.map(a=>`<option value="${F(a.effort)}" ${a.effort===n.draftReasoningEffort?"selected":""}>${f(a.label||a.effort)}</option>`).join("")}
      </select>
    </label>
    <button type="button" id="settings-save-provider" ${s?"":"disabled"}>
      <span class="material-symbols-rounded" aria-hidden="true">${n.isSavingProvider?"sync":"save"}</span>
      ${n.isSavingProvider?"Saving":"Save model"}
    </button>
    ${n.providerError?`<p class="settings-platform-error">${f(n.providerError)}</p>`:""}
  </div>`}function lt(e,t,s,n){return`<div class="settings-platform-provider-form">
    <div class="settings-platform-form-heading">
      <span class="material-symbols-rounded" aria-hidden="true">route</span>
      <span>
        <strong>Hosted chat fast model</strong>
        <small>Hosted text providers govern plain_hosted_chat and fast_model only</small>
      </span>
    </div>
    <label class="settings-platform-field settings-platform-field-wide">
      <span>Model</span>
      <select id="settings-hosted-provider-model" ${!n||!e.length||s.isSavingHostedProvider?"disabled":""}>
        ${e.map(a=>`<option value="${F(a.model_id)}" ${a.model_id===s.hostedDraftModelId?"selected":""}>${f(a.label||a.model_id)}</option>`).join("")}
      </select>
    </label>
    <button type="button" id="settings-save-hosted-provider" ${t?"":"disabled"}>
      <span class="material-symbols-rounded" aria-hidden="true">${s.isSavingHostedProvider?"sync":"save"}</span>
      ${s.isSavingHostedProvider?"Saving":"Save hosted model"}
    </button>
    ${n?"":'<p class="settings-card-copy settings-platform-note">Activate a hosted text provider before selecting a fast model.</p>'}
    ${s.hostedProviderError?`<p class="settings-platform-error">${f(s.hostedProviderError)}</p>`:""}
  </div>`}function dt(e,t,s,n){return`<details class="settings-platform-runtime" open>
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
      ${e.length?e.map(o=>ct(o,t,n)).join(""):'<p class="settings-card-copy">No runtime sessions.</p>'}
    </div>
    ${n.cleanupError?`<p class="settings-platform-error">${f(n.cleanupError)}</p>`:""}
  </details>`}function ct(e,t,s){const n=s.cleaningSessionIds.has(e.session_id);return`<div class="settings-platform-runtime-row">
    <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">terminal</span>
    <span class="settings-platform-runtime-copy">
      <span class="settings-platform-runtime-title">
        <strong>${f(e.agent_id||e.session_id)}</strong>
        <button type="button" class="settings-secondary settings-platform-runtime-clear" data-runtime-clear="${F(e.session_id)}" aria-label="Clean runtime session ${F(e.agent_id||e.session_id)}" ${!t||s.clearingAllRuntime||n?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">${n?"sync":"delete_sweep"}</span>
          <span class="settings-platform-runtime-clear-label">${n?"Cleaning":"Clean"}</span>
        </button>
      </span>
      <small>${f(e.workspace_name||e.workspace_id)} · ${f(e.effective_mode)} · ${f(e.status)}</small>
      <code>${f(e.session_id)}</code>
    </span>
  </div>`}function pt(e){return e.runtime.all_sessions||e.runtime.sessions||[]}function f(e){return e.replace(/[&<>"']/g,t=>t==="&"?"&amp;":t==="<"?"&lt;":t===">"?"&gt;":t==='"'?"&quot;":"&#39;")}function F(e){return f(e)}const ut=5,gt=4,mt=4,ft=3,vt=2,_t=4;function ht(e){return`<section class="settings-loading-skeleton" role="status" aria-label="Settings content is loading">
    <header class="detail-header settings-loading-skeleton__header" aria-hidden="true">
      <div class="detail-title-block">
        ${p("title")}
        <span class="detail-title-separator" aria-hidden="true"></span>
        ${p("subtitle")}
      </div>
    </header>
    ${yt(e)}
  </section>`}function yt(e){return e.id==="workspace-access"?$t():e.id==="workspace-apps"?wt():e.id==="platform-settings"?kt():e.id==="persistence"?St():bt()}function bt(){return`${W()}
    <section class="settings-card settings-loading-skeleton__create" aria-hidden="true">
      ${Pt("short-title")}
      ${A(ut,()=>b("field"))}
      ${b("button")}
    </section>
    ${he()}
    <div class="settings-loading-skeleton__profile-row" aria-hidden="true">
      <section class="settings-card settings-loading-skeleton__detail-card">
        ${O(!0)}
        <div class="settings-loading-skeleton__field-grid">
          ${A(gt,()=>z())}
        </div>
        ${b("toggle")}
        ${b("button")}
      </section>
      <section class="settings-card settings-loading-skeleton__password-card">
        ${O(!1)}
        ${p("copy")}
        <div class="settings-loading-skeleton__field-grid">
          ${A(2,()=>z())}
        </div>
        ${b("button")}
        ${b("danger-button")}
      </section>
    </div>`}function $t(){return`${W()}
    ${he()}
    <section class="settings-card" aria-hidden="true">
      ${O(!0)}
      <div class="settings-loading-skeleton__rows">
        ${A(mt,()=>Et())}
      </div>
    </section>`}function wt(){return`${W()}
    <section class="settings-card" aria-hidden="true">
      ${O(!1)}
      ${p("copy-wide")}
      <div class="settings-loading-skeleton__rows">
        ${A(ft,()=>At())}
      </div>
    </section>`}function kt(){return`${W()}
    <section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
      ${O(!1)}
      <div class="settings-loading-skeleton__settings-grid">
        ${A(vt,()=>It())}
      </div>
      <div class="settings-loading-skeleton__provider-form">
        ${A(2,()=>z())}
        ${b("button")}
      </div>
      <div class="settings-loading-skeleton__runtime-list">
        ${A(_t,()=>Ct())}
      </div>
    </section>`}function St(){return`${W()}
    <section class="settings-card settings-loading-skeleton__persistence" aria-hidden="true">
      ${O(!0)}
      <div class="settings-loading-skeleton__adapter-cards">
        ${A(2,()=>Ht())}
      </div>
      ${Mt()}
    </section>`}function W(){return`<section class="settings-card settings-page-settings" aria-hidden="true">
    ${L("page")}
    <span class="settings-loading-skeleton__copy-stack">
      ${p("kicker")}
      ${p("card-title")}
      ${p("copy")}
    </span>
  </section>`}function he(){return`<section class="settings-card settings-user-picker" aria-hidden="true">
    <div class="settings-loading-skeleton__copy-stack">
      ${p("kicker")}
      ${p("card-title")}
      ${p("copy-short")}
    </div>
    ${z()}
  </section>`}function O(e){return`<div class="settings-loading-skeleton__heading">
    <span class="settings-loading-skeleton__copy-stack">
      ${p("kicker")}
      ${p("card-title")}
    </span>
    ${e?b("pill"):""}
  </div>`}function Pt(e){return`<div class="settings-loading-skeleton__copy-stack">
    ${p("kicker")}
    ${p(e)}
  </div>`}function z(){return`<span class="settings-loading-skeleton__field-wrap">
    ${p("label")}
    ${b("field")}
  </span>`}function Et(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--membership">
    ${b("checkbox")}
    ${L("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${p("row-title")}
      ${p("row-copy")}
    </span>
    ${b("select")}
  </span>`}function At(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--app">
    ${L("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${p("row-title")}
      ${p("row-copy")}
    </span>
    ${b("toggle-pill")}
    ${b("button")}
  </span>`}function It(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--tile">
    ${L("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${p("row-title")}
      ${p("row-copy")}
    </span>
  </span>`}function Ct(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--runtime">
    ${L("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${p("row-title")}
      ${p("row-copy")}
    </span>
    ${b("button")}
  </span>`}function Ht(){return`<span class="settings-loading-skeleton__adapter-card">
    ${L("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${p("row-title")}
      ${p("row-copy-wide")}
    </span>
    ${b("pill")}
  </span>`}function Mt(){return`<span class="settings-loading-skeleton__result">
    ${L("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${p("row-title")}
      ${p("row-copy-wide")}
    </span>
  </span>`}function p(e){return`<span class="settings-loading-skeleton__line settings-loading-skeleton__line--${e}"></span>`}function b(e){return`<span class="settings-loading-skeleton__block settings-loading-skeleton__block--${e}"></span>`}function L(e){return`<span class="settings-loading-skeleton__icon settings-loading-skeleton__icon--${e}"></span>`}function A(e,t){return Array.from({length:e},t).join("")}function Rt({publishChanged:e,render:t,setNotice:s}){let n=[],a=[],o="",i=[],l="",u=!1,y=new Set;function S(){return{appRegistry:n,dependencies:a,error:o,isLoading:u,loadErrors:i,savingKeys:y}}function C(){n=[],a=[],o="",i=[],l=""}function E(){l=""}async function U(d,_,w=!1){if(!(!d||u)&&!(!w&&l===d)){u=!0,o="",i=[],t();try{const[g,c]=await Promise.all([Te(),J(d,_)]);n=g,a=c,l=d}catch(g){a=[],l="",o=g instanceof Error?g.message:"Unable to load app links."}finally{u=!1,t()}}}async function j(d,_,w){const g=Dt(d,_);y=new Set([...y,g]),t();try{const c=await Oe(d,_,w);a=a.map(D=>D.consumer_app_id===d?c:D),e(d,c),s({tone:"success",message:"App link updated."})}finally{const c=new Set(y);c.delete(g),y=c,t()}}async function J(d,_){const w=_.filter(c=>c.workspace_id===d&&c.status==="enabled"),g=await Promise.all(w.map(async c=>{try{return{app:c,payload:await Ne(c.app_id)}}catch(D){return{app:c,error:D instanceof Error?D.message:"Unable to load app links."}}}));return i=g.filter(c=>"error"in c).map(c=>({app_id:c.app.app_id,message:c.error,name:c.app.name||c.app.app_id})),g.filter(c=>"payload"in c&&c.payload.dependencies.length>0).map(c=>c.payload).sort((c,D)=>c.consumer_app_id.localeCompare(D.consumer_app_id))}return{ensureLoaded:U,invalidate:E,reset:C,saveDependencySelection:j,viewState:S}}function Dt(e,t){return`${e}:${t}`}function r(e){return e.replace(/[&<>"']/g,t=>t==="&"?"&amp;":t==="<"?"&lt;":t===">"?"&gt;":t==='"'?"&quot;":"&#39;")}function v(e){return r(e)}function B(e){return`<section class="settings-card settings-page-settings">
    <span class="settings-page-settings-icon material-symbols-rounded" aria-hidden="true">${r(e.icon)}</span>
    <span>
      <p class="settings-kicker">Settings page</p>
      <h2>${r(e.title)}</h2>
      <p class="settings-card-copy">${r(e.summary)}</p>
    </span>
  </section>`}function Lt({appRegistry:e,dependencies:t,error:s,isLoading:n,loadErrors:a,page:o,savingKeys:i,workspaceApps:l}){return`${B(o)}
    <section class="settings-card settings-app-links">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">App links</p>
          <h2>Provider app links</h2>
        </div>
      </div>
      <p class="settings-card-copy">Provider links are workspace-scoped. A selected provider is reused until it becomes unavailable; otherwise one-provider interface links use the first available candidate as their automatic default.</p>
      ${s?`<p class="settings-platform-error">${r(s)}</p>`:""}
      ${a.length?`<div class="settings-app-link-errors">${a.map(qt).join("")}</div>`:""}
      ${t.length>1?Ut(t,e,l):""}
      <div class="settings-app-link-list">
        ${t.length?t.map(u=>Tt(u,e,l,i)).join(""):Ot(s,n)}
      </div>
    </section>`}function Ut(e,t,s){return`<nav class="settings-app-link-consumer-nav" aria-label="Provider link apps">
    ${e.map(n=>{const a=s.find(l=>l.workspace_id===n.workspace_id&&l.app_id===n.consumer_app_id),o=ne(t,n.consumer_app_id),i=a?.name||o?.name||n.consumer_app_id;return`<a class="settings-app-link-consumer-nav__item" href="#${v(ye(n.consumer_app_id))}">
        <strong>${r(i)}</strong>
        <small>${r(String(n.dependencies.length))}</small>
      </a>`}).join("")}
  </nav>`}function Tt(e,t,s,n){const a=s.find(i=>i.workspace_id===e.workspace_id&&i.app_id===e.consumer_app_id),o=ne(t,e.consumer_app_id);return`<article class="settings-app-link-consumer" id="${v(ye(e.consumer_app_id))}">
    <header class="settings-app-link-consumer__header">
      ${$e(o,e.consumer_app_id)}
      <span class="settings-app-copy">
        <strong>${r(a?.name||e.consumer_app_id)}</strong>
        <small>${r(e.consumer_app_id)} - ${r(e.status)}</small>
      </span>
    </header>
    <div class="settings-app-link-dependencies">
      ${e.dependencies.map(i=>Nt(e.consumer_app_id,i,t,n)).join("")}
    </div>
  </article>`}function Nt(e,t,s,n){const a=n.has(Bt(e,t.alias)),o=jt(t),i=be(t);return`<section class="settings-app-link-row">
    <header class="settings-app-link-row__header">
      <span class="settings-app-link-row__copy">
        <strong>${r(t.alias)}</strong>
        <small>${r(t.interface)} ${r(t.version)}</small>
      </span>
      <span class="settings-pill ${t.status==="resolved"||i?"":"settings-pill-muted"}">${r(Ft(t,i))}</span>
    </header>
    <p class="settings-card-copy">${r(t.description||"No description.")}</p>
    ${t.blocked_reason?`<p class="settings-platform-error">${r(t.blocked_reason)}</p>`:""}
    ${t.stale_provider_app_ids.length?`<p class="settings-platform-error">Unavailable selection: ${r(t.stale_provider_app_ids.join(", "))}</p>`:""}
    ${t.candidates.length?`<div class="settings-app-link-candidates">
            ${t.candidates.map(l=>{const u=o.includes(l.app_id),y=t.cardinality==="many"?"checkbox":"radio",S=`dependency:${e}:${t.alias}`,C=ne(s,l.app_id);return`<label class="settings-app-link-candidate ${u?"is-selected":""}">
                <input
                  ${u?"checked":""}
                  ${a?"disabled":""}
                  data-dependency-choice="${v(re(e,t.alias,l.app_id))}"
                  name="${v(S)}"
                  type="${y}"
                />
                ${$e(C,l.app_id)}
                <span>
                  <strong>${r(l.name||l.app_id)}</strong>
                  <small>${r(l.app_id)} - ${r(l.interface_version)}${l.app_id===i?" - automatic default":""}</small>
                </span>
              </label>`}).join("")}
          </div>`:'<p class="settings-card-copy">No enabled provider app is available for this interface.</p>'}
    ${i?`<button type="button" class="settings-secondary" data-dependency-save-default="${v(re(e,t.alias,i))}" ${a?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">${a?"sync":"save"}</span>
          ${a?"Saving":"Save default"}
        </button>`:""}
  </section>`}function Ot(e,t){return e?"":t?'<p class="settings-card-copy">Loading app links...</p>':'<p class="settings-card-copy">No enabled app in the active workspace declares provider links.</p>'}function Bt(e,t){return`${e}:${t}`}function re(e,t,s){return`${e}:${t}:${s}`}function ye(e){return`settings-app-link-consumer-${e}`}function jt(e){if(e.selected_provider_app_ids.length)return e.selected_provider_app_ids;const t=be(e);return t?[t]:[]}function be(e){return e.selected_provider_app_ids.length||e.status!=="optional_unset"||e.cardinality!=="one"||e.stale_provider_app_ids.length||e.blocked_reason?"":e.candidates[0]?.app_id||""}function Ft(e,t){return t?"auto default":e.status==="optional_unset"?"unset":e.status}function ne(e,t){return e.find(s=>s.app_id===t)||null}function qt(e){return`<p class="settings-platform-error">${r(e.name||e.app_id)}: ${r(e.message)}</p>`}function $e(e,t){if(e?.logo?.kind==="image"&&e.logo.value)return`<span class="settings-app-link-logo is-image"><img alt="" loading="lazy" src="${v(e.logo.value)}" /></span>`;const s=e?.logo?.value||Wt(e,t);return`<span class="settings-app-link-logo is-glyph"><span class="material-symbols-rounded" aria-hidden="true">${r(s)}</span></span>`}function Wt(e,t){const s={agents:"smart_toy","app-store":"storefront","base-shell":"dashboard",chat:"forum",checklist:"checklist",crm:"contacts","developer-kit":"developer_board","docs-studio":"description","document-generator":"description","dynamic-views":"dashboard_customize","gmail-app":"mail",memory:"database","maverick-monitor":"monitor_heart",settings:"admin_panel_settings",skills:"school",speech:"record_voice_over",storage:"cloud","website-studio":"web_asset"};return s[t]?s[t]:e?.views.includes("chat")?"forum":e?.views.includes("agents")?"smart_toy":e?.views.includes("shell")?"dashboard":"apps"}function Jt(e){document.getElementById("dismiss-notice")?.addEventListener("click",e.dismissNotice),document.getElementById("create-user")?.addEventListener("submit",s=>{s.preventDefault(),e.createUser(s.currentTarget).catch(e.showError)});const t=e.selectedUser();document.getElementById("selected-user")?.addEventListener("change",s=>{e.selectUser(s.currentTarget.value)}),document.getElementById("edit-user")?.addEventListener("submit",s=>{s.preventDefault(),t&&e.updateSelectedUser(s.currentTarget,t).catch(e.showError)}),document.getElementById("reset-password")?.addEventListener("submit",s=>{s.preventDefault(),t&&e.resetSelectedUserPassword(s.currentTarget,t).catch(e.showError)}),document.getElementById("delete-user")?.addEventListener("click",()=>{t&&e.deleteSelectedUser(t).catch(e.showError)}),document.getElementById("save-memberships")?.addEventListener("click",()=>{t&&e.updateMemberships(t).catch(e.showError)}),zt(e),Kt(e),Vt(e),rt({onClearAllRuntimeSessions:()=>{e.clearRuntimeSessionsFromPanel().catch(e.showError)},onClearRuntimeSession:s=>{s&&e.clearRuntimeSessionsFromPanel([s]).catch(e.showError)},onLogout:()=>{e.logoutFromSettings().catch(e.showError)},onHostedProviderModelChanged:e.onHostedProviderModelChanged,onProviderModelChanged:e.onProviderModelChanged,onProviderReasoningChanged:e.onProviderReasoningChanged,onSaveHostedProviderSettings:()=>{e.saveHostedProviderSettingsFromPanel().catch(e.showError)},onSaveProviderSettings:()=>{e.saveProviderSettingsFromPanel().catch(e.showError)}})}function Kt(e){document.querySelectorAll("[data-dependency-choice]").forEach(t=>{t.addEventListener("change",()=>{const s=oe(t.dataset.dependencyChoice||"");if(!s)return;const n=e.appDependencies().find(o=>o.consumer_app_id===s.consumerAppId)?.dependencies.find(o=>o.alias===s.alias);if(!n)return;if(n.cardinality==="one"){e.saveDependencySelection(s.consumerAppId,s.alias,[s.providerAppId]).catch(e.showError);return}const a=new Set(n.selected_provider_app_ids);t.checked?a.add(s.providerAppId):a.delete(s.providerAppId),e.saveDependencySelection(s.consumerAppId,s.alias,Array.from(a)).catch(e.showError)})}),document.querySelectorAll("[data-dependency-save-default]").forEach(t=>{t.addEventListener("click",()=>{const s=oe(t.dataset.dependencySaveDefault||"");s&&e.saveDependencySelection(s.consumerAppId,s.alias,[s.providerAppId]).catch(e.showError)})})}function oe(e){const[t,s,...n]=e.split(":"),a=n.join(":");return!t||!s||!a?null:{alias:s,consumerAppId:t,providerAppId:a}}function zt(e){document.querySelectorAll("[data-app-toggle]").forEach(t=>{t.addEventListener("change",()=>{const s=e.workspaceApps().find(n=>`${n.workspace_id}:${n.app_id}`===t.dataset.appToggle);s&&e.setWorkspaceAppStatus(s,t.checked).catch(e.showError)})}),document.querySelectorAll("[data-app-install]").forEach(t=>{t.addEventListener("click",()=>{const s=e.workspaceApps().find(n=>`${n.workspace_id}:${n.app_id}`===t.dataset.appInstall);s&&e.installWorkspaceApp(s).catch(e.showError)})}),document.querySelectorAll("[data-app-uninstall]").forEach(t=>{t.addEventListener("click",()=>{const s=e.workspaceApps().find(n=>`${n.workspace_id}:${n.app_id}`===t.dataset.appUninstall);s&&e.uninstallWorkspaceApp(s).catch(e.showError)})})}function Vt(e){document.querySelectorAll("[data-adapter-target]").forEach(t=>{t.addEventListener("click",()=>{const s=t.dataset.adapterTarget;(s==="json"||s==="mongo")&&e.persistenceController.prepare(s).catch(e.showError)})}),document.getElementById("close-migration-modal")?.addEventListener("click",()=>{e.persistenceController.cancel()}),document.getElementById("cancel-migration")?.addEventListener("click",()=>{e.persistenceController.cancel()}),document.getElementById("validate-migration")?.addEventListener("click",()=>{e.persistenceController.validateDraft().catch(e.showError)}),document.querySelectorAll("[data-migration-field]").forEach(t=>{const s=n=>{const a=t.dataset.migrationField;if(a&&a in(e.persistenceController.viewState().targetDraft||{})){const o=!!e.persistenceController.viewState().migrationPlan;e.persistenceController.updateDraft(a,t.value,{render:n}),!n&&o&&Gt()}};t.addEventListener("input",()=>s(!1)),t.addEventListener("change",()=>s(!0))}),document.getElementById("settings-delete-source")?.addEventListener("change",t=>{e.persistenceController.setDeleteSource(t.currentTarget.checked)}),document.getElementById("confirm-migration")?.addEventListener("click",()=>{e.persistenceController.apply().catch(e.showError)})}function Gt(){const e=document.getElementById("confirm-migration");e&&(e.disabled=!0);const t=document.querySelector(".settings-migration-plan");if(!t)return;const s=t.querySelector(".material-symbols-rounded"),n=t.querySelector("strong"),a=t.querySelector("small");s&&(s.textContent="rule"),n&&(n.textContent="Dry run changed"),a&&(a.textContent="Validate the dry run again before applying migration."),t.querySelector(".settings-migration-collections")?.remove()}function Qt(e){let t=null,s=null,n="",a=null,o=null,i=null,l=!1;function u(){return{deleteSourceAfterMigration:l,migrationPlan:a,migrationProgress:i,migrationResult:o,migrationTarget:t,persistence:e.getPersistence(),targetDraft:s}}async function y(d){const _=e.getPersistence();if(!_||_.active_adapter.kind===d){E();return}t=d,s=Xt(d,_),n="",a=null,l=!1,i=null,e.setNotice(null),e.render()}function S(d,_,w={}){s&&(s={...s,[d]:_},a=null,n="",i=null,w.render!==!1&&e.render())}function C(d){l=d,e.render()}function E(){t=null,s=null,a=null,n="",i=null,e.render()}async function U(){if(!(!s||!t)){i={target:t,phase:"validating",percent:10,title:`Dry run to ${t.toUpperCase()}`,detail:"Validating target adapter and collection copy plan before applying changes."},e.setNotice(null),e.render();try{const d=ee(s);a=await We(d),n=le(d)}catch(d){throw i=null,a=null,n="",d}i=null,a.same_adapter&&e.setNotice({tone:"info",message:"The selected persistence adapter is already active."}),e.render()}}async function j(){if(!s||!t)return;const d=ee(s),_=le(d);if(!a||n!==_){await U();return}if(a.same_adapter)return;i={target:t,phase:"applying",percent:38,title:`Migration to ${t.toUpperCase()}`,detail:"Copying the validated control-plane plan to the target adapter."},e.setNotice(null),e.render();try{o=await Je({...d,delete_source:l,restart_backend:!0})}catch(g){throw i={target:t,phase:"failed",percent:100,title:"Migration failed",detail:g instanceof Error?g.message:"Unable to apply migration."},g}const w=t;t=null,s=null,a=null,n="",i={target:w,phase:"restarting",percent:68,title:"Restart backend",detail:o.backend_restart?.detail||"Backend restart scheduled."},e.render(),await J(w)}async function J(d){const _=Date.now(),w=9e4;for(;Date.now()-_<w;){i={target:d,phase:"polling",percent:84,title:"Verifying cutover",detail:"Waiting for the backend to become healthy with the new adapter."},e.render();const g=await e.requestPersistenceStatusQuiet();if(g?.active_adapter.kind===d){e.setPersistence(g);const c=o?.source_cleanup?.scheduled===!0;i={target:d,phase:"complete",percent:100,title:"Migration complete",detail:c?`Active adapter: ${d.toUpperCase()}. Source cleanup is scheduled after health check.`:`Active adapter: ${d.toUpperCase()}. Source storage was preserved.`},e.setNotice({tone:"success",message:`Migration to ${d.toUpperCase()} complete.`}),e.render();return}await new Promise(c=>window.setTimeout(c,1500))}i={target:d,phase:"failed",percent:100,title:"Verification not completed",detail:"The backend did not confirm the new adapter before the timeout. Check service health and logs."},e.setNotice({tone:"error",message:"Migration not confirmed before the timeout."}),e.render()}return{apply:j,cancel:E,prepare:y,setDeleteSource:C,updateDraft:S,validateDraft:U,viewState:u}}function Xt(e,t){const s=t.active_adapter;return{kind:e,json_root:s.json_root||"data/control-plane/json",mongodb_uri:s.mongo_uri||"mongodb://127.0.0.1:27017/maverick",mongodb_database:s.mongo_database||"maverick",mongodb_username:s.mongo_username||"",mongodb_password_ref:s.mongo_password_ref||""}}function ee(e){return{kind:e.kind,json_root:e.json_root.trim()||"data/control-plane/json",mongodb_uri:e.mongodb_uri.trim(),mongodb_database:e.mongodb_database.trim()||"maverick",mongodb_username:e.mongodb_username?.trim()||void 0,mongodb_password_ref:e.mongodb_password_ref?.trim()||void 0}}function le(e){return JSON.stringify(ee(e))}function Yt(e,t){return`${B(e)}
    ${es(t)}`}function Zt(e){const{deleteSourceAfterMigration:t,migrationPlan:s,migrationProgress:n,migrationTarget:a,persistence:o}=e;if(!a||!o)return"";const i=o.active_adapter.kind.toUpperCase(),l=a.toUpperCase(),u=!!(n&&!["complete","failed"].includes(n.phase)),y=!!(s&&!s.same_adapter&&!u);return`<div class="settings-modal-backdrop" role="presentation">
    <section class="settings-modal" role="dialog" aria-modal="true" aria-labelledby="adapter-migration-title">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Confirm migration</p>
          <h2 id="adapter-migration-title">${i} → ${l}</h2>
        </div>
        <button type="button" class="settings-icon-button" id="close-migration-modal" aria-label="Close" ${u?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">close</span>
        </button>
      </div>
      ${s?as(s):ns(n)}
      ${xt(e)}
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
        <button type="button" class="${t?"settings-danger":"settings-secondary"}" id="confirm-migration" ${y?"":"disabled"}>
          <span class="material-symbols-rounded" aria-hidden="true">sync_alt</span>
          ${t?"Apply and schedule cleanup":"Apply migration"}
        </button>
      </div>
    </section>
  </div>`}function xt(e){const t=e.targetDraft;if(!t)return"";const s=!!(e.migrationProgress&&!["complete","failed"].includes(e.migrationProgress.phase));return`<div class="settings-migration-target">
    <label class="settings-platform-field">
      <span>JSON root</span>
      <input data-migration-field="json_root" value="${v(t.json_root)}" ${s?"disabled":""} />
    </label>
    ${t.kind==="mongo"?`<label class="settings-platform-field">
          <span>Mongo URI</span>
          <input data-migration-field="mongodb_uri" value="${v(t.mongodb_uri)}" ${s?"disabled":""} />
        </label>
        <label class="settings-platform-field">
          <span>Mongo database</span>
          <input data-migration-field="mongodb_database" value="${v(t.mongodb_database)}" ${s?"disabled":""} />
        </label>
        <label class="settings-platform-field">
          <span>Mongo username</span>
          <input data-migration-field="mongodb_username" value="${v(t.mongodb_username||"")}" ${s?"disabled":""} />
        </label>
        <label class="settings-platform-field">
          <span>Password secret ref</span>
          <input data-migration-field="mongodb_password_ref" value="${v(t.mongodb_password_ref||"")}" ${s?"disabled":""} />
        </label>`:""}
  </div>`}function es(e){const{migrationProgress:t,migrationResult:s,persistence:n}=e;if(!n)return`<section class="settings-card settings-persistence">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Persistence</p>
          <h2>Control plane adapter</h2>
        </div>
        <span class="settings-pill settings-pill-muted">offline</span>
      </div>
      <p class="settings-card-copy">The core persistence surfaces are not available in the active backend.</p>
    </section>`;const a=n.active_adapter,o=n.collections.reduce((y,S)=>y+S.count,0),i=a.kind==="json",l=a.kind==="mongo",u=t&&!["complete","failed"].includes(t.phase);return`<section class="settings-card settings-persistence">
    <div class="settings-heading">
      <div>
        <p class="settings-kicker">Persistence</p>
        <h2>Control plane adapter</h2>
      </div>
      <span class="settings-pill">${o} documents</span>
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
      <button type="button" class="settings-adapter-card ${l?"is-active":""}" ${l||u?"disabled":'data-adapter-target="mongo"'}>
        <span class="settings-adapter-card-icon material-symbols-rounded" aria-hidden="true">${l?"check_circle":"database"}</span>
        <span>
          <strong>Mongo</strong>
          <small>${r(l?a.mongo_database:"mongodb://127.0.0.1:27017/maverick")}</small>
        </span>
        <em>${l?"Current":"Review migration"}</em>
      </button>
    </div>
    ${ts(t)}
    ${ss(s)}
  </section>`}function ts(e){return e?`<div class="settings-migration-progress ${e.phase==="failed"?"is-failed":""} ${e.phase==="complete"?"is-complete":""}">
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
  </div>`:""}function ss(e){return e?`<div class="settings-migration-result">
    <span class="material-symbols-rounded" aria-hidden="true">task_alt</span>
    <span>
      <strong>Last migration</strong>
      <small>${e.collections.reduce((s,n)=>s+n.count,0)} documents · target ${r(e.target_adapter.kind)} · cleanup ${e.source_cleanup?.scheduled?"scheduled":"not requested"}</small>
    </span>
  </div>`:""}function ns(e){return`<div class="settings-migration-plan">
    <span class="material-symbols-rounded" aria-hidden="true">rule</span>
    <span>
      <strong>${r(e?.title||"Dry run not validated")}</strong>
      <small>${r(e?.detail||"Adjust the target fields, then validate the dry run before applying migration.")}</small>
    </span>
  </div>`}function as(e){const t=e.collections.reduce((n,a)=>n+a.count,0),s=e.target_collections.reduce((n,a)=>n+a.count,0);return`<div class="settings-migration-plan">
    <span class="material-symbols-rounded" aria-hidden="true">${e.same_adapter?"block":"rule"}</span>
    <span>
      <strong>${e.same_adapter?"Target already active":"Dry run complete"}</strong>
      <small>${t} source documents · ${s} target documents before copy · env ${r(e.env_file)}</small>
    </span>
    <div class="settings-migration-collections">
      ${e.collections.map(n=>`<span><strong>${r(n.name)}</strong><small>${n.count}</small></span>`).join("")}
    </div>
  </div>`}async function is(e){const t=e.settings?.provider.active_provider?.provider_id;if(!t||!e.state.draftModelId){e.state.providerError="Provider not loaded.",e.render();return}e.state.isSavingProvider=!0,e.state.providerError="",e.render();try{await Be({provider_id:t,model_id:e.state.draftModelId,model_reasoning_effort:e.state.draftReasoningEffort||null});const s=await Q();e.setSettings(s),X(e.state,s),e.setNotice({tone:"success",message:"Provider settings updated."})}catch(s){e.state.providerError=s instanceof Error?s.message:"Unable to update provider settings."}finally{e.state.isSavingProvider=!1,e.render()}}async function rs(e){const t=e.settings?.provider.hosted_text?.active_provider?.provider_id;if(!t||!e.state.hostedDraftModelId){e.state.hostedProviderError="Hosted provider not loaded.",e.render();return}e.state.isSavingHostedProvider=!0,e.state.hostedProviderError="",e.render();try{await je({provider_id:t,model_id:e.state.hostedDraftModelId});const s=await Q();e.setSettings(s),X(e.state,s),e.setNotice({tone:"success",message:"Hosted model settings updated."})}catch(s){e.state.hostedProviderError=s instanceof Error?s.message:"Unable to update hosted model settings."}finally{e.state.isSavingHostedProvider=!1,e.render()}}function os({page:e,pendingDeleteUserId:t,selectedUser:s,users:n}){return`${B(e)}
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
    ${we(n,s)}
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
              <label>Name<input name="display_name" value="${v(s.display_name||"")}" /></label>
              <label>Email<input name="email" type="email" value="${v(s.email||"")}" /></label>
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
        </div>`:'<section class="settings-card"><h2>No users</h2></section>'}`}function ls({page:e,selectedUser:t,users:s,workspaces:n}){return`${B(e)}
    ${we(s,t)}
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
          <div class="settings-memberships">${ds(t,n)}</div>
        </section>`:'<section class="settings-card"><h2>No users</h2></section>'}`}function we(e,t){return e.length?`<section class="settings-card settings-user-picker">
    <div>
      <p class="settings-kicker">User directory</p>
      <h2>${r(t?t.display_name||t.username:"Select user")}</h2>
      <p class="settings-card-copy">${e.length} user${e.length===1?"":"s"} available.</p>
    </div>
    <label class="settings-platform-field">
      <span>Selected user</span>
      <select id="selected-user">
        ${e.map(s=>`<option value="${v(s.user_id)}" ${s.user_id===t?.user_id?"selected":""}>${r(s.display_name||s.username)} (${r(s.username)})</option>`).join("")}
      </select>
    </label>
  </section>`:`<section class="settings-card settings-user-picker">
      <div>
        <p class="settings-kicker">User directory</p>
        <h2>No users</h2>
      </div>
      <p class="settings-card-copy">Create a user before editing profile or workspace access settings.</p>
    </section>`}function ds(e,t){return t.map(s=>{const n=e.memberships.find(a=>a.workspace_id===s.workspace_id);return`<label class="settings-membership">
        <input type="checkbox" data-workspace-enabled="${v(s.workspace_id)}" ${n?"checked":""} />
        <span class="settings-membership-icon material-symbols-rounded" aria-hidden="true">workspaces</span>
        <span>
          <strong>${r(s.name)}</strong>
          <small>${r(s.workspace_id)}</small>
        </span>
        <select data-workspace-role="${v(s.workspace_id)}">
          <option value="member" ${n?.role!=="admin"?"selected":""}>Member</option>
          <option value="admin" ${n?.role==="admin"?"selected":""}>Workspace admin</option>
        </select>
      </label>`}).join("")}function cs({page:e,workspaceApps:t,workspaces:s}){return`${B(e)}
    <section class="settings-card">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Workspace apps</p>
          <h2>Installation and visibility</h2>
        </div>
      </div>
      <p class="settings-card-copy">Installed means the app has a workspace binding. Only enabled apps are visible to users and served by the core.</p>
      <div class="settings-app-workspaces">${ps(s,t)}</div>
    </section>`}function ps(e,t){return e.map(s=>{const n=t.filter(i=>i.workspace_id===s.workspace_id),a=n.filter(i=>i.status==="enabled").length,o=n.filter(i=>i.installed).length;return`<details class="settings-app-workspace">
        <summary class="settings-app-workspace-heading">
          <span class="settings-summary-caret material-symbols-rounded" aria-hidden="true">chevron_right</span>
          <span class="settings-app-workspace-icon material-symbols-rounded" aria-hidden="true">deployed_code</span>
          <span>
            <strong>${r(s.name)}</strong>
            <small>${r(s.workspace_id)} · ${a}/${o} enabled</small>
          </span>
        </summary>
        <div class="settings-apps">
          ${n.map(us).join("")}
        </div>
      </details>`}).join("")}function us(e){const t=e.status==="enabled",s=e.installed,n=s?e.status:"not installed",a=`${e.workspace_id}:${e.app_id}`;return`<div class="settings-app-row">
    <span class="settings-app-icon material-symbols-rounded" aria-hidden="true">${r(gs(e))}</span>
    <span class="settings-app-copy">
      <strong>${r(e.name)}</strong>
      <small>${r(e.app_id)} · v${r(e.version)} · ${r(n)}</small>
    </span>
    ${s?`<label class="settings-switch">
          <input type="checkbox" data-app-toggle="${v(a)}" ${t?"checked":""} />
          <span>Enabled</span>
        </label>
        <button type="button" class="settings-secondary" data-app-uninstall="${v(a)}">
          <span class="material-symbols-rounded" aria-hidden="true">link_off</span>
          Uninstall
        </button>`:`<button type="button" class="settings-secondary" data-app-install="${v(a)}">
          <span class="material-symbols-rounded" aria-hidden="true">add_link</span>
          Install
        </button>`}
  </div>`}function gs(e){return e.status!=="enabled"?"hide_source":{agents:"smart_toy","app-store":"storefront","base-shell":"dashboard",browser:"language",calendar:"calendar_month",chat:"forum",checklist:"checklist",crm:"contacts","developer-kit":"developer_board","docs-studio":"description","document-generator":"description","dynamic-views":"dashboard_customize","gmail-app":"mail",mail:"mail",memory:"database","maverick-monitor":"monitor_heart",settings:"admin_panel_settings",skills:"school",speech:"record_voice_over",storage:"cloud",vault:"key","website-studio":"web_asset"}[e.app_id]||"apps"}let H=[],V=[],q=[],te=null,P=null,k=st();const ke=Object.fromEntries(new URLSearchParams(window.location.search).entries());let G=ue(ke)||Ie,I=Pe(ke),T=!0,N="",$=null,de="",ce="";const ae=Qt({getPersistence:()=>te,render:()=>h(),requestPersistenceStatusQuiet:hs,setNotice:e=>{$=e},setPersistence:e=>{te=e}}),M=Rt({publishChanged:Ms,render:()=>h(),setNotice:e=>{$=e}});function Se(){return H.find(e=>e.user_id===I)||H[0]}function Pe(e){const t=K(e.user_id)||K(e.selected_user_id)||K(e.id);if(t)return t;const s=K(e.app_page),n=/^users\/([^/?#]+)$/.exec(s);if(!n?.[1])return"";try{return decodeURIComponent(n[1])}catch{return n[1]}}function K(e){return typeof e=="string"?e.trim():""}function ms(e){const t=ue(e),s=Pe(e);let n=!1;t&&t!==G&&(G=t,n=!0),s&&s!==I&&(I=s,N="",n=!0),n&&((H.length||T)&&h(),t==="app-links"&&Ee())}function fs(e){e.id===de||window.parent===window||(de=e.id,window.parent.postMessage({type:"maverick.app.selection-changed",owner_app_id:"settings",selection:{page_id:e.id}},window.location.origin))}function vs(e){!e||e.user_id===ce||window.parent===window||(ce=e.user_id,window.parent.postMessage({type:"maverick.app.selection-changed",owner_app_id:"settings",selection:{user_id:e.user_id}},window.location.origin))}function Y(){window.parent!==window&&window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"settings",resource:"users"},window.location.origin)}async function _s(){try{return await m("/api/admin/persistence")}catch(e){return $={tone:"error",message:e instanceof Error?e.message:"Persistence API unavailable"},null}}async function hs(){try{return await m("/api/admin/persistence")}catch{return null}}async function ys(){try{return await Q()}catch{return null}}async function R(){T=!0,h();try{const[e,t,s,n,a]=await Promise.all([He(),Me(),Re(),_s(),ys()]),o=P?.workspace.workspace_id||"",i=a?.workspace.workspace_id||"";H=e,V=t,q=s,te=n,P=a,o!==i&&M.reset(),X(k,P),(!I||!H.some(l=>l.user_id===I))&&(I=H[0]?.user_id||"")}finally{T=!1}h(),G==="app-links"&&Ee()}async function Ee(e=!1){const t=P?.workspace.workspace_id||"";await M.ensureLoaded(t,q,e)}async function bs(e){const t=new FormData(e);I=(await Ke({username:String(t.get("username")||""),password:String(t.get("password")||""),display_name:String(t.get("display_name")||""),email:String(t.get("email")||""),platform_role:String(t.get("platform_role")||"member")})).user_id,e.reset(),await R(),Y()}async function $s(e,t){const s=new FormData(e);await ze(t.user_id,{display_name:String(s.get("display_name")||""),email:String(s.get("email")||""),platform_role:String(s.get("platform_role")||"member"),account_type:String(s.get("account_type")||"standard"),is_active:s.get("is_active")==="on"}),await R(),Y()}async function ws(e,t){const s=new FormData(e),n=String(s.get("password")||""),a=String(s.get("password_confirmation")||"");if(n!==a)throw new Error("Passwords do not match");await Ve(t.user_id,n),e.reset(),$={tone:"success",message:"Password updated."},h()}async function ks(e){const t=e.display_name||e.username;if(N!==e.user_id){N=e.user_id,$={tone:"info",message:`Press Delete user again to confirm permanent removal of ${t}.`},h();return}await Ge(e.user_id),I="",N="",$={tone:"success",message:`${t} deleted.`},await R(),Y()}async function Ss(e){const t=V.map(s=>{const n=document.querySelector(`[data-workspace-enabled="${s.workspace_id}"]`),a=document.querySelector(`[data-workspace-role="${s.workspace_id}"]`);return n?.checked?{workspace_id:s.workspace_id,role:a?.value||"member"}:null}).filter(s=>!!s);await Qe(e.user_id,t),await R(),Y()}async function Ps(e){await Xe(e),M.invalidate(),await R()}async function Es(e,t){await Ye(e,t),M.invalidate(),await R()}async function As(e){await Ze(e),M.invalidate(),await R()}async function Is(e,t,s){await M.saveDependencySelection(e,t,s)}async function Cs(e){const t=(e||[]).filter(Boolean);k.cleanupError="",t.length?t.forEach(s=>k.cleaningSessionIds.add(s)):k.clearingAllRuntime=!0,h();try{const s=await Fe(t.length?t:void 0);Hs(s),P=await Q(),X(k,P),$={tone:"success",message:t.length?"Runtime session cleaned.":"Runtime sessions cleaned."}}catch(s){k.cleanupError=s instanceof Error?s.message:"Unable to clean runtime sessions."}finally{t.forEach(s=>k.cleaningSessionIds.delete(s)),k.clearingAllRuntime=!1,h()}}function Hs(e){e.deleted_threads<=0||window.parent===window||(window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"chat",resource:"threads"},window.location.origin),e.deleted_thread_ids.forEach(t=>{window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"chat",resource:"threads",deleted_thread_id:t},window.location.origin)}))}function Ms(e,t){window.parent!==window&&window.parent.postMessage({type:"maverick.app.dependencies-changed",app_id:e,status:t.status},window.location.origin)}async function Rs(){if(window.parent&&window.parent!==window){window.parent.postMessage({type:"maverick.shell.logout"},window.location.origin);return}await qe(),window.location.href="/"}function Ds(e,t){if(e.id==="users")return os({page:e,pendingDeleteUserId:N,selectedUser:t,users:H});if(e.id==="workspace-access")return ls({page:e,selectedUser:t,users:H,workspaces:V});if(e.id==="workspace-apps")return cs({page:e,workspaceApps:q,workspaces:V});if(e.id==="app-links"){const s=M.viewState();return Lt({appRegistry:s.appRegistry,dependencies:s.dependencies,error:s.error,isLoading:s.isLoading,loadErrors:s.loadErrors,page:e,savingKeys:s.savingKeys,workspaceApps:q})}return e.id==="platform-settings"?Ls(e):Yt(e,ae.viewState())}function Ls(e){return`${B(e)}
    ${it(P,k)}`}function h(){const e=document.getElementById("app"),t=T?void 0:Se(),s=Ce(G);e&&(e.innerHTML=`<main class="settings-shell">
    <section class="settings-main">
      <div class="settings-content">
        ${T?ht(s):`<header class="detail-header">
          <div class="detail-title-block">
            <h2>${r(s.title)}</h2>
            <span class="detail-title-separator" aria-hidden="true"></span>
            <p>${r(s.summary)}</p>
          </div>
        </header>
        ${Ts()}
        ${Ds(s,t)}`}
      </div>
    </section>
    ${Zt(ae.viewState())}
  </main>`,Us(),fs(s),T||vs(t))}function Us(){Jt({clearRuntimeSessionsFromPanel:Cs,createUser:bs,deleteSelectedUser:ks,dismissNotice:()=>{$=null,h()},installWorkspaceApp:Ps,logoutFromSettings:Rs,onHostedProviderModelChanged:e=>{at(k,e),h()},onProviderModelChanged:e=>{nt(k,P,e),h()},onProviderReasoningChanged:e=>{k.draftReasoningEffort=e,k.providerError="",h()},persistenceController:ae,render:h,resetSelectedUserPassword:ws,saveDependencySelection:Is,saveHostedProviderSettingsFromPanel:()=>rs(pe()),saveProviderSettingsFromPanel:()=>is(pe()),selectedUser:Se,selectUser:e=>{I=e,N="",h()},setWorkspaceAppStatus:Es,showError:Ae,uninstallWorkspaceApp:As,updateMemberships:Ss,updateSelectedUser:$s,workspaceApps:()=>q,appDependencies:()=>M.viewState().dependencies})}function pe(){return{render:h,setNotice:e=>{$=e},setSettings:e=>{P=e},settings:P,state:k}}function Ae(e){$={tone:"error",message:e instanceof Error?e.message:"Unexpected error"},h()}function Ts(){return $?`<div class="settings-notice settings-notice-${$.tone}">
    <span class="material-symbols-rounded" aria-hidden="true">${$.tone==="error"?"error":$.tone==="success"?"task_alt":"info"}</span>
    <span>${r($.message)}</span>
    <button type="button" class="settings-icon-button" id="dismiss-notice" aria-label="Close">
      <span class="material-symbols-rounded" aria-hidden="true">close</span>
    </button>
  </div>`:""}window.addEventListener("message",e=>{if(e.origin!==window.location.origin||!e.data||typeof e.data!="object")return;const t=e.data;t.type==="maverick.app.navigate"&&(!t.app_id||t.app_id==="settings")&&ms(t.params||{})});window.parent?.postMessage({type:"maverick.app.ready",app_id:"settings"},window.location.origin);R().catch(Ae);
