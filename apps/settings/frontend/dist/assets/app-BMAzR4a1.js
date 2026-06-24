import{s as ge,D as Ce,a as He}from"./pages-BZUBskpf.js";async function m(e,t={}){const s=await fetch(e,{credentials:"same-origin",headers:{"Content-Type":"application/json",...t.headers||{}},...t}),n=await s.json();if(!s.ok)throw new Error(n.detail||n.error||`Request failed ${s.status}`);return n}async function Me(){return(await m("/api/admin/users")).items}async function De(){return(await m("/api/admin/workspaces")).items}async function Le(){return(await m("/api/admin/workspace-apps")).items}function re(e,t=""){return typeof e=="string"?e:t}function Ue(e){return Array.isArray(e)?e.filter(t=>typeof t=="string"):[]}function Te(e){if(!e||typeof e!="object"||Array.isArray(e))return null;const t=e,s=t.kind==="image"||t.kind==="glyph"?t.kind:null;return s&&typeof t.value=="string"?{kind:s,value:t.value}:null}function Oe(e){const t=e&&typeof e=="object"&&!Array.isArray(e)?e:{},s=re(t.app_id);return{app_id:s,name:re(t.name,s||"Unnamed app"),views:Ue(t.views),logo:Te(t.logo)}}async function qe(){return((await m("/api/apps")).items||[]).map(Oe).filter(t=>t.app_id)}function Ne(e){const t=new URLSearchParams({consumer_app_id:e});return m(`/api/apps/dependencies?${t.toString()}`)}function je(e,t,s){return m("/api/apps/dependencies",{method:"POST",body:JSON.stringify({consumer_app_id:e,alias:t,provider_app_ids:s})})}function G(){return m("/api/settings/platform")}function Be(e){return m("/api/providers/active",{method:"POST",body:JSON.stringify(e)})}function Fe(e){return m("/api/providers/hosted/selection",{method:"POST",body:JSON.stringify(e)})}function ze(e,t="settings_runtime_sessions_cleared"){return m("/api/settings/runtime-sessions/clear",{method:"POST",body:JSON.stringify({session_ids:e,reason:t})})}function We(){return m("/api/auth/logout",{method:"POST"})}function Je(e){return m("/api/admin/persistence/migrations/dry-run",{method:"POST",body:JSON.stringify(e)})}function Qe(e){return m("/api/admin/persistence/migrations/apply",{method:"POST",body:JSON.stringify(e)})}function Ke(e){return m("/api/admin/users",{method:"POST",body:JSON.stringify(e)})}function Ve(e,t){return m(`/api/admin/users/${encodeURIComponent(e)}`,{method:"PATCH",body:JSON.stringify(t)})}function Ge(e,t){return m(`/api/admin/users/${encodeURIComponent(e)}/password`,{method:"POST",body:JSON.stringify({password:t})})}function Xe(e){return m(`/api/admin/users/${encodeURIComponent(e)}`,{method:"DELETE"})}function Ye(e,t){return m(`/api/admin/users/${encodeURIComponent(e)}/workspaces`,{method:"PUT",body:JSON.stringify({memberships:t})})}function Ze(e){return m(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"POST",body:JSON.stringify({source_id:e.source_id,enabled:!0})})}function xe(e,t){return m(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"PATCH",body:JSON.stringify({status:t?"enabled":"disabled"})})}function et(e){return m(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"DELETE",body:JSON.stringify({})})}function x(e){const t=e?.provider.active_provider,s=e?.provider.model_settings;return ve(t,s,se(e))}function se(e){const t=e?.provider.active_provider,s=e?.provider.model_settings;return he(t,s)}function me(e){const t=e?.provider.hosted_text?.active_provider||null,s=e?.provider.hosted_text?.model_settings||null;return ve(t,s,fe(e))}function fe(e){const t=e?.provider.hosted_text?.active_provider||null,s=e?.provider.hosted_text?.model_settings||null;return he(t,s)}function ve(e,t,s){const n=t?.selected_model_id||e?.default_model_family||"",a=s.find(o=>o.model_id===n)||null;return{modelId:n,reasoningEffort:t?.selected_reasoning_effort||_e(a)}}function he(e,t){const s=t?.selected_model_id||e?.default_model_family||"",n=Z(t?.available_models).length?Z(t?.available_models):Z(e?.model_options);return(n.length?n:s?[st(s,t?.selected_reasoning_effort||"")]:[]).map(tt)}function _e(e){return e?.default_reasoning_effort||e?.supported_reasoning_efforts[0]?.effort||""}function Z(e){return(e||[]).filter(t=>t.model_id)}function tt(e){return e.supported_reasoning_efforts.length||!e.default_reasoning_effort?e:{...e,supported_reasoning_efforts:[{effort:e.default_reasoning_effort,label:e.default_reasoning_effort,description:null}]}}function st(e,t){return{model_id:e,label:e,description:null,default_reasoning_effort:t||null,supported_reasoning_efforts:t?[{effort:t,label:t,description:null}]:[]}}const nt=new Set(["created","running","stopping"]);function at(){return{cleanupError:"",clearingAllRuntime:!1,cleaningSessionIds:new Set,draftModelId:"",draftReasoningEffort:"",hostedDraftModelId:"",hostedRoutingAllowFallbacks:!0,hostedRoutingDataCollection:"",hostedRoutingMode:"auto",hostedRoutingProviderId:"",hostedRoutingQuantization:"",hostedRoutingRequireParameters:!1,hostedRoutingSort:"",hostedProviderError:"",isSavingHostedProvider:!1,isSavingProvider:!1,providerError:""}}function X(e,t){const{modelId:s,reasoningEffort:n}=x(t),{modelId:a}=me(t),o=ne(t,a);e.draftModelId=s,e.draftReasoningEffort=n,e.hostedDraftModelId=a,e.hostedRoutingMode=o.mode||"auto",e.hostedRoutingProviderId=o.provider_id||"",e.hostedRoutingAllowFallbacks=o.allow_fallbacks!==!1,e.hostedRoutingRequireParameters=o.require_parameters===!0,e.hostedRoutingSort=o.sort||"",e.hostedRoutingDataCollection=o.data_collection||"",e.hostedRoutingQuantization=o.quantizations?.[0]||""}function it(e,t,s){const n=se(t).find(a=>a.model_id===s)||null;e.draftModelId=s,e.draftReasoningEffort=_e(n),e.providerError=""}function rt(e,t,s){e.hostedDraftModelId=s;const n=ne(t,s);e.hostedRoutingMode=n.mode||"auto",e.hostedRoutingProviderId=n.provider_id||"",e.hostedRoutingAllowFallbacks=n.allow_fallbacks!==!1,e.hostedRoutingRequireParameters=n.require_parameters===!0,e.hostedRoutingSort=n.sort||"",e.hostedRoutingDataCollection=n.data_collection||"",e.hostedRoutingQuantization=n.quantizations?.[0]||"",e.hostedProviderError=""}function ot(e,t,s){t==="mode"&&typeof s=="string"&&["auto","prefer","only","ignore"].includes(s)?e.hostedRoutingMode=s:t==="provider_id"&&typeof s=="string"?e.hostedRoutingProviderId=s:t==="allow_fallbacks"&&typeof s=="boolean"?e.hostedRoutingAllowFallbacks=s:t==="require_parameters"&&typeof s=="boolean"?e.hostedRoutingRequireParameters=s:t==="sort"&&typeof s=="string"&&["","price","throughput","latency"].includes(s)?e.hostedRoutingSort=s:t==="data_collection"&&typeof s=="string"&&["","allow","deny"].includes(s)?e.hostedRoutingDataCollection=s:t==="quantization"&&typeof s=="string"&&(e.hostedRoutingQuantization=s),e.hostedProviderError=""}function be(e){return{mode:e.hostedRoutingMode,provider_id:e.hostedRoutingProviderId||void 0,allow_fallbacks:e.hostedRoutingAllowFallbacks,require_parameters:e.hostedRoutingRequireParameters,sort:e.hostedRoutingSort,data_collection:e.hostedRoutingDataCollection,quantizations:e.hostedRoutingQuantization?[e.hostedRoutingQuantization]:[]}}function lt(e,t){if(!e)return`<section class="settings-card settings-platform">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Settings</p>
          <h2>Platform settings</h2>
        </div>
      </div>
      <p class="settings-card-copy">Platform settings are not available from the active backend.</p>
    </section>`;const s=e.provider.active_provider,n=e.provider.hosted_text?.active_provider||null,a=mt(e),o=a.filter(d=>nt.has(d.status)),r=e.runtime.cleanup_allowed??!1,i=e.runtime.cleanup_scope||"none",p=se(e),b=fe(e),P=x(e).modelId,C=x(e).reasoningEffort,R=me(e).modelId,L=b.find(d=>d.model_id===R)||null,B=b.find(d=>d.model_id===t.hostedDraftModelId)||L||null,F=n?`${L?.label||R||"Hosted model"} - ${n.label||n.provider_id}`:"No hosted text provider",h=(p.find(d=>d.model_id===t.draftModelId)||p[0]||null)?.supported_reasoning_efforts||[],k=!!(s&&t.draftModelId&&!t.isSavingProvider&&(t.draftModelId!==P||t.draftReasoningEffort!==C)),f=!!(n&&t.hostedDraftModelId&&!t.isSavingHostedProvider&&(t.hostedDraftModelId!==R||ft(t,e)));return`<section class="settings-card settings-platform">
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
          <h3>${g(e.user.display_name||e.user.username||"Unavailable")}</h3>
          <p>${g(e.user.platform_role||"member")} · ${g(e.workspace.name||e.workspace.workspace_id)}</p>
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
          <h3>${g(s?.label||"Provider not loaded")}</h3>
          <p>${g(P||"model")} · ${g(C||"reasoning")} · Codex tools/filesystem/MCP · ${o.length} active / ${a.length} in scope</p>
        </div>
      </article>
      <article class="settings-platform-tile settings-platform-provider">
        <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">bolt</span>
        <div>
          <p class="settings-kicker">Hosted chat / fast model</p>
          <h3>${g(F)}</h3>
          <p>${g(R||"model not selected")} · plain hosted chat only · runtime engine remains Codex</p>
        </div>
      </article>
    </div>
    <div class="settings-platform-provider-forms">
      ${ct(p,h,k,t)}
      ${pt(b,B,f,t,!!n)}
    </div>
    ${ut(a,r,i,t)}
  </section>`}function dt(e){document.getElementById("settings-provider-model")?.addEventListener("change",t=>{e.onProviderModelChanged(t.currentTarget.value)}),document.getElementById("settings-provider-reasoning")?.addEventListener("change",t=>{e.onProviderReasoningChanged(t.currentTarget.value)}),document.getElementById("settings-hosted-provider-model")?.addEventListener("change",t=>{e.onHostedProviderModelChanged(t.currentTarget.value)}),document.querySelectorAll("[data-openrouter-routing]").forEach(t=>{t.addEventListener("change",s=>{const n=s.currentTarget;e.onHostedProviderRoutingChanged(n.dataset.openrouterRouting||"",n instanceof HTMLInputElement&&n.type==="checkbox"?n.checked:n.value)})}),document.getElementById("settings-save-provider")?.addEventListener("click",e.onSaveProviderSettings),document.getElementById("settings-save-hosted-provider")?.addEventListener("click",e.onSaveHostedProviderSettings),document.getElementById("settings-logout")?.addEventListener("click",e.onLogout),document.getElementById("settings-clear-all-runtime")?.addEventListener("click",e.onClearAllRuntimeSessions),document.querySelectorAll("[data-runtime-clear]").forEach(t=>{t.addEventListener("click",()=>e.onClearRuntimeSession(t.dataset.runtimeClear||""))})}function ct(e,t,s,n){return`<div class="settings-platform-provider-form">
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
        ${e.map(a=>`<option value="${E(a.model_id)}" ${a.model_id===n.draftModelId?"selected":""}>${g(a.label||a.model_id)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Reasoning</span>
      <select id="settings-provider-reasoning" ${!t.length||n.isSavingProvider?"disabled":""}>
        ${t.map(a=>`<option value="${E(a.effort)}" ${a.effort===n.draftReasoningEffort?"selected":""}>${g(a.label||a.effort)}</option>`).join("")}
      </select>
    </label>
    <button type="button" id="settings-save-provider" ${s?"":"disabled"}>
      <span class="material-symbols-rounded" aria-hidden="true">${n.isSavingProvider?"sync":"save"}</span>
      ${n.isSavingProvider?"Saving":"Save model"}
    </button>
    ${n.providerError?`<p class="settings-platform-error">${g(n.providerError)}</p>`:""}
  </div>`}function pt(e,t,s,n,a){const o=t?.upstream_provider_options||[],r=Array.from(new Set(o.map(i=>i.quantization||"").filter(Boolean)));return`<div class="settings-platform-provider-form">
    <div class="settings-platform-form-heading">
      <span class="material-symbols-rounded" aria-hidden="true">route</span>
      <span>
        <strong>Hosted chat fast model</strong>
        <small>Hosted text providers govern plain_hosted_chat and fast_model only</small>
      </span>
    </div>
    <label class="settings-platform-field settings-platform-field-wide">
      <span>Model</span>
      <select id="settings-hosted-provider-model" ${!a||!e.length||n.isSavingHostedProvider?"disabled":""}>
        ${e.map(i=>`<option value="${E(i.model_id)}" ${i.model_id===n.hostedDraftModelId?"selected":""}>${g(i.label||i.model_id)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>OpenRouter upstream</span>
      <select data-openrouter-routing="mode" ${!a||!o.length||n.isSavingHostedProvider?"disabled":""}>
        ${[["auto","Auto"],["prefer","Prefer selected"],["only","Only selected"],["ignore","Ignore selected"]].map(([i,p])=>`<option value="${E(i)}" ${i===n.hostedRoutingMode?"selected":""}>${g(p)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Upstream provider</span>
      <select data-openrouter-routing="provider_id" ${!a||!o.length||n.hostedRoutingMode==="auto"||n.isSavingHostedProvider?"disabled":""}>
        <option value="">Select provider</option>
        ${o.map(i=>`<option value="${E(String(i.provider_id||i.tag||""))}" ${(i.provider_id||i.tag)===n.hostedRoutingProviderId?"selected":""}>${g(i.label||i.provider_id||i.tag||"Provider")}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Sort</span>
      <select data-openrouter-routing="sort" ${!a||n.isSavingHostedProvider?"disabled":""}>
        ${[["","OpenRouter default"],["price","Price"],["throughput","Throughput"],["latency","Latency"]].map(([i,p])=>`<option value="${E(i)}" ${i===n.hostedRoutingSort?"selected":""}>${g(p)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Data collection</span>
      <select data-openrouter-routing="data_collection" ${!a||n.isSavingHostedProvider?"disabled":""}>
        ${[["","OpenRouter default"],["allow","Allow"],["deny","Deny"]].map(([i,p])=>`<option value="${E(i)}" ${i===n.hostedRoutingDataCollection?"selected":""}>${g(p)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Quantization</span>
      <select data-openrouter-routing="quantization" ${!a||!r.length||n.isSavingHostedProvider?"disabled":""}>
        <option value="">Any</option>
        ${r.map(i=>`<option value="${E(i)}" ${i===n.hostedRoutingQuantization?"selected":""}>${g(i)}</option>`).join("")}
      </select>
    </label>
    <div class="settings-platform-checks">
      <label><input type="checkbox" data-openrouter-routing="allow_fallbacks" ${n.hostedRoutingAllowFallbacks?"checked":""} ${!a||n.isSavingHostedProvider?"disabled":""}> Allow OpenRouter fallback</label>
      <label><input type="checkbox" data-openrouter-routing="require_parameters" ${n.hostedRoutingRequireParameters?"checked":""} ${!a||n.isSavingHostedProvider?"disabled":""}> Require supported parameters</label>
    </div>
    <button type="button" id="settings-save-hosted-provider" ${s?"":"disabled"}>
      <span class="material-symbols-rounded" aria-hidden="true">${n.isSavingHostedProvider?"sync":"save"}</span>
      ${n.isSavingHostedProvider?"Saving":"Save hosted model"}
    </button>
    ${a?"":'<p class="settings-card-copy settings-platform-note">Activate a hosted text provider before selecting a fast model.</p>'}
    ${n.hostedProviderError?`<p class="settings-platform-error">${g(n.hostedProviderError)}</p>`:""}
  </div>`}function ut(e,t,s,n){return`<details class="settings-platform-runtime" open>
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
      ${e.length?e.map(o=>gt(o,t,n)).join(""):'<p class="settings-card-copy">No runtime sessions.</p>'}
    </div>
    ${n.cleanupError?`<p class="settings-platform-error">${g(n.cleanupError)}</p>`:""}
  </details>`}function gt(e,t,s){const n=s.cleaningSessionIds.has(e.session_id);return`<div class="settings-platform-runtime-row">
    <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">terminal</span>
    <span class="settings-platform-runtime-copy">
      <span class="settings-platform-runtime-title">
        <strong>${g(e.agent_id||e.session_id)}</strong>
        <button type="button" class="settings-secondary settings-platform-runtime-clear" data-runtime-clear="${E(e.session_id)}" aria-label="Clean runtime session ${E(e.agent_id||e.session_id)}" ${!t||s.clearingAllRuntime||n?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">${n?"sync":"delete_sweep"}</span>
          <span class="settings-platform-runtime-clear-label">${n?"Cleaning":"Clean"}</span>
        </button>
      </span>
      <small>${g(e.workspace_name||e.workspace_id)} · ${g(e.effective_mode)} · ${g(e.status)}</small>
      <code>${g(e.session_id)}</code>
    </span>
  </div>`}function mt(e){return e.runtime.all_sessions||e.runtime.sessions||[]}function ne(e,t){const s=e?.provider.hosted_text?.selection?.openrouter_provider_routing_by_model?.[t];return{mode:s?.mode||"auto",provider_id:s?.provider_id||"",allow_fallbacks:s?.allow_fallbacks!==!1,require_parameters:s?.require_parameters===!0,sort:s?.sort||"",data_collection:s?.data_collection||"",quantizations:s?.quantizations||[]}}function ft(e,t){const s=ne(t,e.hostedDraftModelId),n=be(e);return s.mode!==n.mode||(s.provider_id||"")!==(n.provider_id||"")||s.allow_fallbacks!==!1!=(n.allow_fallbacks!==!1)||s.require_parameters===!0!=(n.require_parameters===!0)||(s.sort||"")!==(n.sort||"")||(s.data_collection||"")!==(n.data_collection||"")||(s.quantizations?.[0]||"")!==(n.quantizations?.[0]||"")}function g(e){return e.replace(/[&<>"']/g,t=>t==="&"?"&amp;":t==="<"?"&lt;":t===">"?"&gt;":t==='"'?"&quot;":"&#39;")}function E(e){return g(e)}const vt=5,ht=4,_t=4,bt=3,yt=2,$t=4;function wt(e){return`<section class="settings-loading-skeleton" role="status" aria-label="Settings content is loading">
    <header class="detail-header settings-loading-skeleton__header" aria-hidden="true">
      <div class="detail-title-block">
        ${u("title")}
        <span class="detail-title-separator" aria-hidden="true"></span>
        ${u("subtitle")}
      </div>
    </header>
    ${kt(e)}
  </section>`}function kt(e){return e.id==="workspace-access"?Pt():e.id==="workspace-apps"?Et():e.id==="platform-settings"?Rt():e.id==="persistence"?At():St()}function St(){return`${W()}
    <section class="settings-card settings-loading-skeleton__create" aria-hidden="true">
      ${It("short-title")}
      ${A(vt,()=>$("field"))}
      ${$("button")}
    </section>
    ${ye()}
    <div class="settings-loading-skeleton__profile-row" aria-hidden="true">
      <section class="settings-card settings-loading-skeleton__detail-card">
        ${N(!0)}
        <div class="settings-loading-skeleton__field-grid">
          ${A(ht,()=>Q())}
        </div>
        ${$("toggle")}
        ${$("button")}
      </section>
      <section class="settings-card settings-loading-skeleton__password-card">
        ${N(!1)}
        ${u("copy")}
        <div class="settings-loading-skeleton__field-grid">
          ${A(2,()=>Q())}
        </div>
        ${$("button")}
        ${$("danger-button")}
      </section>
    </div>`}function Pt(){return`${W()}
    ${ye()}
    <section class="settings-card" aria-hidden="true">
      ${N(!0)}
      <div class="settings-loading-skeleton__rows">
        ${A(_t,()=>Ct())}
      </div>
    </section>`}function Et(){return`${W()}
    <section class="settings-card" aria-hidden="true">
      ${N(!1)}
      ${u("copy-wide")}
      <div class="settings-loading-skeleton__rows">
        ${A(bt,()=>Ht())}
      </div>
    </section>`}function Rt(){return`${W()}
    <section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
      ${N(!1)}
      <div class="settings-loading-skeleton__settings-grid">
        ${A(yt,()=>Mt())}
      </div>
      <div class="settings-loading-skeleton__provider-form">
        ${A(2,()=>Q())}
        ${$("button")}
      </div>
      <div class="settings-loading-skeleton__runtime-list">
        ${A($t,()=>Dt())}
      </div>
    </section>`}function At(){return`${W()}
    <section class="settings-card settings-loading-skeleton__persistence" aria-hidden="true">
      ${N(!0)}
      <div class="settings-loading-skeleton__adapter-cards">
        ${A(2,()=>Lt())}
      </div>
      ${Ut()}
    </section>`}function W(){return`<section class="settings-card settings-page-settings" aria-hidden="true">
    ${T("page")}
    <span class="settings-loading-skeleton__copy-stack">
      ${u("kicker")}
      ${u("card-title")}
      ${u("copy")}
    </span>
  </section>`}function ye(){return`<section class="settings-card settings-user-picker" aria-hidden="true">
    <div class="settings-loading-skeleton__copy-stack">
      ${u("kicker")}
      ${u("card-title")}
      ${u("copy-short")}
    </div>
    ${Q()}
  </section>`}function N(e){return`<div class="settings-loading-skeleton__heading">
    <span class="settings-loading-skeleton__copy-stack">
      ${u("kicker")}
      ${u("card-title")}
    </span>
    ${e?$("pill"):""}
  </div>`}function It(e){return`<div class="settings-loading-skeleton__copy-stack">
    ${u("kicker")}
    ${u(e)}
  </div>`}function Q(){return`<span class="settings-loading-skeleton__field-wrap">
    ${u("label")}
    ${$("field")}
  </span>`}function Ct(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--membership">
    ${$("checkbox")}
    ${T("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${u("row-title")}
      ${u("row-copy")}
    </span>
    ${$("select")}
  </span>`}function Ht(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--app">
    ${T("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${u("row-title")}
      ${u("row-copy")}
    </span>
    ${$("toggle-pill")}
    ${$("button")}
  </span>`}function Mt(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--tile">
    ${T("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${u("row-title")}
      ${u("row-copy")}
    </span>
  </span>`}function Dt(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--runtime">
    ${T("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${u("row-title")}
      ${u("row-copy")}
    </span>
    ${$("button")}
  </span>`}function Lt(){return`<span class="settings-loading-skeleton__adapter-card">
    ${T("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${u("row-title")}
      ${u("row-copy-wide")}
    </span>
    ${$("pill")}
  </span>`}function Ut(){return`<span class="settings-loading-skeleton__result">
    ${T("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${u("row-title")}
      ${u("row-copy-wide")}
    </span>
  </span>`}function u(e){return`<span class="settings-loading-skeleton__line settings-loading-skeleton__line--${e}"></span>`}function $(e){return`<span class="settings-loading-skeleton__block settings-loading-skeleton__block--${e}"></span>`}function T(e){return`<span class="settings-loading-skeleton__icon settings-loading-skeleton__icon--${e}"></span>`}function A(e,t){return Array.from({length:e},t).join("")}function Tt({publishChanged:e,render:t,setNotice:s}){let n=[],a=[],o="",r=[],i="",p=!1,b=new Set;function P(){return{appRegistry:n,dependencies:a,error:o,isLoading:p,loadErrors:r,savingKeys:b}}function C(){n=[],a=[],o="",r=[],i=""}function R(){i=""}async function L(c,h,k=!1){if(!(!c||p)&&!(!k&&i===c)){p=!0,o="",r=[],t();try{const[f,d]=await Promise.all([qe(),F(c,h)]);n=f,a=d,i=c}catch(f){a=[],i="",o=f instanceof Error?f.message:"Unable to load app links."}finally{p=!1,t()}}}async function B(c,h,k){const f=Ot(c,h);b=new Set([...b,f]),t();try{const d=await je(c,h,k);a=a.map(U=>U.consumer_app_id===c?d:U),e(c,d),s({tone:"success",message:"App link updated."})}finally{const d=new Set(b);d.delete(f),b=d,t()}}async function F(c,h){const k=h.filter(d=>d.workspace_id===c&&d.status==="enabled"),f=await Promise.all(k.map(async d=>{try{return{app:d,payload:await Ne(d.app_id)}}catch(U){return{app:d,error:U instanceof Error?U.message:"Unable to load app links."}}}));return r=f.filter(d=>"error"in d).map(d=>({app_id:d.app.app_id,message:d.error,name:d.app.name||d.app.app_id})),f.filter(d=>"payload"in d&&d.payload.dependencies.length>0).map(d=>d.payload).sort((d,U)=>d.consumer_app_id.localeCompare(U.consumer_app_id))}return{ensureLoaded:L,invalidate:R,reset:C,saveDependencySelection:B,viewState:P}}function Ot(e,t){return`${e}:${t}`}function l(e){return e.replace(/[&<>"']/g,t=>t==="&"?"&amp;":t==="<"?"&lt;":t===">"?"&gt;":t==='"'?"&quot;":"&#39;")}function v(e){return l(e)}function j(e){return`<section class="settings-card settings-page-settings">
    <span class="settings-page-settings-icon material-symbols-rounded" aria-hidden="true">${l(e.icon)}</span>
    <span>
      <p class="settings-kicker">Settings page</p>
      <h2>${l(e.title)}</h2>
      <p class="settings-card-copy">${l(e.summary)}</p>
    </span>
  </section>`}function qt({appRegistry:e,dependencies:t,error:s,isLoading:n,loadErrors:a,page:o,savingKeys:r,workspaceApps:i}){return`${j(o)}
    <section class="settings-card settings-app-links">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">App links</p>
          <h2>Provider app links</h2>
        </div>
      </div>
      <p class="settings-card-copy">Provider links are workspace-scoped. A selected provider is reused until it becomes unavailable; otherwise one-provider interface links use the first available candidate as their automatic default.</p>
      ${s?`<p class="settings-platform-error">${l(s)}</p>`:""}
      ${a.length?`<div class="settings-app-link-errors">${a.map(Qt).join("")}</div>`:""}
      ${t.length>1?Nt(t,e,i):""}
      <div class="settings-app-link-list">
        ${t.length?t.map(p=>jt(p,e,i,r)).join(""):Ft(s,n)}
      </div>
    </section>`}function Nt(e,t,s){return`<nav class="settings-app-link-consumer-nav" aria-label="Provider link apps">
    ${e.map(n=>{const a=s.find(i=>i.workspace_id===n.workspace_id&&i.app_id===n.consumer_app_id),o=ae(t,n.consumer_app_id),r=a?.name||o?.name||n.consumer_app_id;return`<a class="settings-app-link-consumer-nav__item" href="#${v($e(n.consumer_app_id))}">
        <strong>${l(r)}</strong>
        <small>${l(String(n.dependencies.length))}</small>
      </a>`}).join("")}
  </nav>`}function jt(e,t,s,n){const a=s.find(r=>r.workspace_id===e.workspace_id&&r.app_id===e.consumer_app_id),o=ae(t,e.consumer_app_id);return`<article class="settings-app-link-consumer" id="${v($e(e.consumer_app_id))}">
    <header class="settings-app-link-consumer__header">
      ${ke(o,e.consumer_app_id)}
      <span class="settings-app-copy">
        <strong>${l(a?.name||e.consumer_app_id)}</strong>
        <small>${l(e.consumer_app_id)} - ${l(e.status)}</small>
      </span>
    </header>
    <div class="settings-app-link-dependencies">
      ${e.dependencies.map(r=>Bt(e.consumer_app_id,r,t,n)).join("")}
    </div>
  </article>`}function Bt(e,t,s,n){const a=n.has(zt(e,t.alias)),o=Wt(t),r=we(t);return`<section class="settings-app-link-row">
    <header class="settings-app-link-row__header">
      <span class="settings-app-link-row__copy">
        <strong>${l(t.alias)}</strong>
        <small>${l(t.interface)} ${l(t.version)}</small>
      </span>
      <span class="settings-pill ${t.status==="resolved"||r?"":"settings-pill-muted"}">${l(Jt(t,r))}</span>
    </header>
    <p class="settings-card-copy">${l(t.description||"No description.")}</p>
    ${t.blocked_reason?`<p class="settings-platform-error">${l(t.blocked_reason)}</p>`:""}
    ${t.stale_provider_app_ids.length?`<p class="settings-platform-error">Unavailable selection: ${l(t.stale_provider_app_ids.join(", "))}</p>`:""}
    ${t.candidates.length?`<div class="settings-app-link-candidates">
            ${t.candidates.map(i=>{const p=o.includes(i.app_id),b=t.cardinality==="many"?"checkbox":"radio",P=`dependency:${e}:${t.alias}`,C=ae(s,i.app_id);return`<label class="settings-app-link-candidate ${p?"is-selected":""}">
                <input
                  ${p?"checked":""}
                  ${a?"disabled":""}
                  data-dependency-choice="${v(oe(e,t.alias,i.app_id))}"
                  name="${v(P)}"
                  type="${b}"
                />
                ${ke(C,i.app_id)}
                <span>
                  <strong>${l(i.name||i.app_id)}</strong>
                  <small>${l(i.app_id)} - ${l(i.interface_version)}${i.app_id===r?" - automatic default":""}</small>
                </span>
              </label>`}).join("")}
          </div>`:'<p class="settings-card-copy">No enabled provider app is available for this interface.</p>'}
    ${r?`<button type="button" class="settings-secondary" data-dependency-save-default="${v(oe(e,t.alias,r))}" ${a?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">${a?"sync":"save"}</span>
          ${a?"Saving":"Save default"}
        </button>`:""}
  </section>`}function Ft(e,t){return e?"":t?'<p class="settings-card-copy">Loading app links...</p>':'<p class="settings-card-copy">No enabled app in the active workspace declares provider links.</p>'}function zt(e,t){return`${e}:${t}`}function oe(e,t,s){return`${e}:${t}:${s}`}function $e(e){return`settings-app-link-consumer-${e}`}function Wt(e){if(e.selected_provider_app_ids.length)return e.selected_provider_app_ids;const t=we(e);return t?[t]:[]}function we(e){return e.selected_provider_app_ids.length||e.status!=="optional_unset"||e.cardinality!=="one"||e.stale_provider_app_ids.length||e.blocked_reason?"":e.candidates[0]?.app_id||""}function Jt(e,t){return t?"auto default":e.status==="optional_unset"?"unset":e.status}function ae(e,t){return e.find(s=>s.app_id===t)||null}function Qt(e){return`<p class="settings-platform-error">${l(e.name||e.app_id)}: ${l(e.message)}</p>`}function ke(e,t){if(e?.logo?.kind==="image"&&e.logo.value)return`<span class="settings-app-link-logo is-image"><img alt="" loading="lazy" src="${v(e.logo.value)}" /></span>`;const s=e?.logo?.value||Kt(e,t);return`<span class="settings-app-link-logo is-glyph"><span class="material-symbols-rounded" aria-hidden="true">${l(s)}</span></span>`}function Kt(e,t){const s={agents:"smart_toy","app-store":"storefront","base-shell":"dashboard",chat:"forum",checklist:"checklist",crm:"contacts","developer-kit":"developer_board","docs-studio":"description","document-generator":"description","dynamic-views":"dashboard_customize","gmail-app":"mail",memory:"database","maverick-monitor":"monitor_heart",settings:"admin_panel_settings",skills:"school",speech:"record_voice_over",storage:"cloud","website-studio":"web_asset"};return s[t]?s[t]:e?.views.includes("chat")?"forum":e?.views.includes("agents")?"smart_toy":e?.views.includes("shell")?"dashboard":"apps"}function Vt(e){document.getElementById("dismiss-notice")?.addEventListener("click",e.dismissNotice),document.getElementById("create-user")?.addEventListener("submit",s=>{s.preventDefault(),e.createUser(s.currentTarget).catch(e.showError)});const t=e.selectedUser();document.getElementById("selected-user")?.addEventListener("change",s=>{e.selectUser(s.currentTarget.value)}),document.getElementById("edit-user")?.addEventListener("submit",s=>{s.preventDefault(),t&&e.updateSelectedUser(s.currentTarget,t).catch(e.showError)}),document.getElementById("reset-password")?.addEventListener("submit",s=>{s.preventDefault(),t&&e.resetSelectedUserPassword(s.currentTarget,t).catch(e.showError)}),document.getElementById("delete-user")?.addEventListener("click",()=>{t&&e.deleteSelectedUser(t).catch(e.showError)}),document.getElementById("save-memberships")?.addEventListener("click",()=>{t&&e.updateMemberships(t).catch(e.showError)}),Xt(e),Gt(e),Yt(e),dt({onClearAllRuntimeSessions:()=>{e.clearRuntimeSessionsFromPanel().catch(e.showError)},onClearRuntimeSession:s=>{s&&e.clearRuntimeSessionsFromPanel([s]).catch(e.showError)},onLogout:()=>{e.logoutFromSettings().catch(e.showError)},onHostedProviderModelChanged:e.onHostedProviderModelChanged,onHostedProviderRoutingChanged:e.onHostedProviderRoutingChanged,onProviderModelChanged:e.onProviderModelChanged,onProviderReasoningChanged:e.onProviderReasoningChanged,onSaveHostedProviderSettings:()=>{e.saveHostedProviderSettingsFromPanel().catch(e.showError)},onSaveProviderSettings:()=>{e.saveProviderSettingsFromPanel().catch(e.showError)}})}function Gt(e){document.querySelectorAll("[data-dependency-choice]").forEach(t=>{t.addEventListener("change",()=>{const s=le(t.dataset.dependencyChoice||"");if(!s)return;const n=e.appDependencies().find(o=>o.consumer_app_id===s.consumerAppId)?.dependencies.find(o=>o.alias===s.alias);if(!n)return;if(n.cardinality==="one"){e.saveDependencySelection(s.consumerAppId,s.alias,[s.providerAppId]).catch(e.showError);return}const a=new Set(n.selected_provider_app_ids);t.checked?a.add(s.providerAppId):a.delete(s.providerAppId),e.saveDependencySelection(s.consumerAppId,s.alias,Array.from(a)).catch(e.showError)})}),document.querySelectorAll("[data-dependency-save-default]").forEach(t=>{t.addEventListener("click",()=>{const s=le(t.dataset.dependencySaveDefault||"");s&&e.saveDependencySelection(s.consumerAppId,s.alias,[s.providerAppId]).catch(e.showError)})})}function le(e){const[t,s,...n]=e.split(":"),a=n.join(":");return!t||!s||!a?null:{alias:s,consumerAppId:t,providerAppId:a}}function Xt(e){document.querySelectorAll("[data-app-toggle]").forEach(t=>{t.addEventListener("change",()=>{const s=e.workspaceApps().find(n=>`${n.workspace_id}:${n.app_id}`===t.dataset.appToggle);s&&e.setWorkspaceAppStatus(s,t.checked).catch(e.showError)})}),document.querySelectorAll("[data-app-install]").forEach(t=>{t.addEventListener("click",()=>{const s=e.workspaceApps().find(n=>`${n.workspace_id}:${n.app_id}`===t.dataset.appInstall);s&&e.installWorkspaceApp(s).catch(e.showError)})}),document.querySelectorAll("[data-app-uninstall]").forEach(t=>{t.addEventListener("click",()=>{const s=e.workspaceApps().find(n=>`${n.workspace_id}:${n.app_id}`===t.dataset.appUninstall);s&&e.uninstallWorkspaceApp(s).catch(e.showError)})})}function Yt(e){document.querySelectorAll("[data-adapter-target]").forEach(t=>{t.addEventListener("click",()=>{const s=t.dataset.adapterTarget;(s==="json"||s==="mongo")&&e.persistenceController.prepare(s).catch(e.showError)})}),document.getElementById("close-migration-modal")?.addEventListener("click",()=>{e.persistenceController.cancel()}),document.getElementById("cancel-migration")?.addEventListener("click",()=>{e.persistenceController.cancel()}),document.getElementById("validate-migration")?.addEventListener("click",()=>{e.persistenceController.validateDraft().catch(e.showError)}),document.querySelectorAll("[data-migration-field]").forEach(t=>{const s=n=>{const a=t.dataset.migrationField;if(a&&a in(e.persistenceController.viewState().targetDraft||{})){const o=!!e.persistenceController.viewState().migrationPlan;e.persistenceController.updateDraft(a,t.value,{render:n}),!n&&o&&Zt()}};t.addEventListener("input",()=>s(!1)),t.addEventListener("change",()=>s(!0))}),document.getElementById("settings-delete-source")?.addEventListener("change",t=>{e.persistenceController.setDeleteSource(t.currentTarget.checked)}),document.getElementById("confirm-migration")?.addEventListener("click",()=>{e.persistenceController.apply().catch(e.showError)})}function Zt(){const e=document.getElementById("confirm-migration");e&&(e.disabled=!0);const t=document.querySelector(".settings-migration-plan");if(!t)return;const s=t.querySelector(".material-symbols-rounded"),n=t.querySelector("strong"),a=t.querySelector("small");s&&(s.textContent="rule"),n&&(n.textContent="Dry run changed"),a&&(a.textContent="Validate the dry run again before applying migration."),t.querySelector(".settings-migration-collections")?.remove()}function xt(e){let t=null,s=null,n="",a=null,o=null,r=null,i=!1;function p(){return{deleteSourceAfterMigration:i,migrationPlan:a,migrationProgress:r,migrationResult:o,migrationTarget:t,persistence:e.getPersistence(),targetDraft:s}}async function b(c){const h=e.getPersistence();if(!h||h.active_adapter.kind===c){R();return}t=c,s=es(c,h),n="",a=null,i=!1,r=null,e.setNotice(null),e.render()}function P(c,h,k={}){s&&(s={...s,[c]:h},a=null,n="",r=null,k.render!==!1&&e.render())}function C(c){i=c,e.render()}function R(){t=null,s=null,a=null,n="",r=null,e.render()}async function L(){if(!(!s||!t)){r={target:t,phase:"validating",percent:10,title:`Dry run to ${t.toUpperCase()}`,detail:"Validating target adapter and collection copy plan before applying changes."},e.setNotice(null),e.render();try{const c=ee(s);a=await Je(c),n=de(c)}catch(c){throw r=null,a=null,n="",c}r=null,a.same_adapter&&e.setNotice({tone:"info",message:"The selected persistence adapter is already active."}),e.render()}}async function B(){if(!s||!t)return;const c=ee(s),h=de(c);if(!a||n!==h){await L();return}if(a.same_adapter)return;r={target:t,phase:"applying",percent:38,title:`Migration to ${t.toUpperCase()}`,detail:"Copying the validated control-plane plan to the target adapter."},e.setNotice(null),e.render();try{o=await Qe({...c,delete_source:i,restart_backend:!0})}catch(f){throw r={target:t,phase:"failed",percent:100,title:"Migration failed",detail:f instanceof Error?f.message:"Unable to apply migration."},f}const k=t;t=null,s=null,a=null,n="",r={target:k,phase:"restarting",percent:68,title:"Restart backend",detail:o.backend_restart?.detail||"Backend restart scheduled."},e.render(),await F(k)}async function F(c){const h=Date.now(),k=9e4;for(;Date.now()-h<k;){r={target:c,phase:"polling",percent:84,title:"Verifying cutover",detail:"Waiting for the backend to become healthy with the new adapter."},e.render();const f=await e.requestPersistenceStatusQuiet();if(f?.active_adapter.kind===c){e.setPersistence(f);const d=o?.source_cleanup?.scheduled===!0;r={target:c,phase:"complete",percent:100,title:"Migration complete",detail:d?`Active adapter: ${c.toUpperCase()}. Source cleanup is scheduled after health check.`:`Active adapter: ${c.toUpperCase()}. Source storage was preserved.`},e.setNotice({tone:"success",message:`Migration to ${c.toUpperCase()} complete.`}),e.render();return}await new Promise(d=>window.setTimeout(d,1500))}r={target:c,phase:"failed",percent:100,title:"Verification not completed",detail:"The backend did not confirm the new adapter before the timeout. Check service health and logs."},e.setNotice({tone:"error",message:"Migration not confirmed before the timeout."}),e.render()}return{apply:B,cancel:R,prepare:b,setDeleteSource:C,updateDraft:P,validateDraft:L,viewState:p}}function es(e,t){const s=t.active_adapter;return{kind:e,json_root:s.json_root||"data/control-plane/json",mongodb_uri:s.mongo_uri||"mongodb://127.0.0.1:27017/maverick",mongodb_database:s.mongo_database||"maverick",mongodb_username:s.mongo_username||"",mongodb_password_ref:s.mongo_password_ref||""}}function ee(e){return{kind:e.kind,json_root:e.json_root.trim()||"data/control-plane/json",mongodb_uri:e.mongodb_uri.trim(),mongodb_database:e.mongodb_database.trim()||"maverick",mongodb_username:e.mongodb_username?.trim()||void 0,mongodb_password_ref:e.mongodb_password_ref?.trim()||void 0}}function de(e){return JSON.stringify(ee(e))}function ts(e,t){return`${j(e)}
    ${as(t)}`}function ss(e){const{deleteSourceAfterMigration:t,migrationPlan:s,migrationProgress:n,migrationTarget:a,persistence:o}=e;if(!a||!o)return"";const r=o.active_adapter.kind.toUpperCase(),i=a.toUpperCase(),p=!!(n&&!["complete","failed"].includes(n.phase)),b=!!(s&&!s.same_adapter&&!p);return`<div class="settings-modal-backdrop" role="presentation">
    <section class="settings-modal" role="dialog" aria-modal="true" aria-labelledby="adapter-migration-title">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Confirm migration</p>
          <h2 id="adapter-migration-title">${r} → ${i}</h2>
        </div>
        <button type="button" class="settings-icon-button" id="close-migration-modal" aria-label="Close" ${p?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">close</span>
        </button>
      </div>
      ${s?ls(s):os(n)}
      ${ns(e)}
      <label class="settings-toggle settings-migration-delete-source">
        <input id="settings-delete-source" type="checkbox" ${t?"checked":""} ${p?"disabled":""} />
        Schedule source cleanup after restart health check
      </label>
      <p class="settings-card-copy">Leave cleanup off to preserve the current source adapter data as a rollback point. Cleanup is a separate explicit choice and requires backend restart.</p>
      <div class="settings-modal-actions">
        <button type="button" class="settings-secondary" id="cancel-migration" ${p?"disabled":""}>Cancel</button>
        <button type="button" class="settings-secondary" id="validate-migration" ${p?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">rule</span>
          Validate dry run
        </button>
        <button type="button" class="${t?"settings-danger":"settings-secondary"}" id="confirm-migration" ${b?"":"disabled"}>
          <span class="material-symbols-rounded" aria-hidden="true">sync_alt</span>
          ${t?"Apply and schedule cleanup":"Apply migration"}
        </button>
      </div>
    </section>
  </div>`}function ns(e){const t=e.targetDraft;if(!t)return"";const s=!!(e.migrationProgress&&!["complete","failed"].includes(e.migrationProgress.phase));return`<div class="settings-migration-target">
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
  </div>`}function as(e){const{migrationProgress:t,migrationResult:s,persistence:n}=e;if(!n)return`<section class="settings-card settings-persistence">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Persistence</p>
          <h2>Control plane adapter</h2>
        </div>
        <span class="settings-pill settings-pill-muted">offline</span>
      </div>
      <p class="settings-card-copy">The core persistence surfaces are not available in the active backend.</p>
    </section>`;const a=n.active_adapter,o=n.collections.reduce((b,P)=>b+P.count,0),r=a.kind==="json",i=a.kind==="mongo",p=t&&!["complete","failed"].includes(t.phase);return`<section class="settings-card settings-persistence">
    <div class="settings-heading">
      <div>
        <p class="settings-kicker">Persistence</p>
        <h2>Control plane adapter</h2>
      </div>
      <span class="settings-pill">${o} documents</span>
    </div>
    <div class="settings-adapter-cards">
      <button type="button" class="settings-adapter-card ${r?"is-active":""}" ${r||p?"disabled":'data-adapter-target="json"'}>
        <span class="settings-adapter-card-icon material-symbols-rounded" aria-hidden="true">${r?"check_circle":"database"}</span>
        <span>
          <strong>JSON</strong>
          <small>${l(r?a.json_root:"data/control-plane/json")}</small>
        </span>
        <em>${r?"Current":"Review migration"}</em>
      </button>
      <button type="button" class="settings-adapter-card ${i?"is-active":""}" ${i||p?"disabled":'data-adapter-target="mongo"'}>
        <span class="settings-adapter-card-icon material-symbols-rounded" aria-hidden="true">${i?"check_circle":"database"}</span>
        <span>
          <strong>Mongo</strong>
          <small>${l(i?a.mongo_database:"mongodb://127.0.0.1:27017/maverick")}</small>
        </span>
        <em>${i?"Current":"Review migration"}</em>
      </button>
    </div>
    ${is(t)}
    ${rs(s)}
  </section>`}function is(e){return e?`<div class="settings-migration-progress ${e.phase==="failed"?"is-failed":""} ${e.phase==="complete"?"is-complete":""}">
    <div class="settings-migration-progress-heading">
      <span class="material-symbols-rounded" aria-hidden="true">${e.phase==="complete"?"check_circle":e.phase==="failed"?"error":"sync"}</span>
      <span>
        <strong>${l(e.title)}</strong>
        <small>${l(e.detail)}</small>
      </span>
      <em>${e.percent}%</em>
    </div>
    <div class="settings-progress-track" aria-label="Migration progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${e.percent}">
      <span style="width: ${e.percent}%"></span>
    </div>
  </div>`:""}function rs(e){return e?`<div class="settings-migration-result">
    <span class="material-symbols-rounded" aria-hidden="true">task_alt</span>
    <span>
      <strong>Last migration</strong>
      <small>${e.collections.reduce((s,n)=>s+n.count,0)} documents · target ${l(e.target_adapter.kind)} · cleanup ${e.source_cleanup?.scheduled?"scheduled":"not requested"}</small>
    </span>
  </div>`:""}function os(e){return`<div class="settings-migration-plan">
    <span class="material-symbols-rounded" aria-hidden="true">rule</span>
    <span>
      <strong>${l(e?.title||"Dry run not validated")}</strong>
      <small>${l(e?.detail||"Adjust the target fields, then validate the dry run before applying migration.")}</small>
    </span>
  </div>`}function ls(e){const t=e.collections.reduce((n,a)=>n+a.count,0),s=e.target_collections.reduce((n,a)=>n+a.count,0);return`<div class="settings-migration-plan">
    <span class="material-symbols-rounded" aria-hidden="true">${e.same_adapter?"block":"rule"}</span>
    <span>
      <strong>${e.same_adapter?"Target already active":"Dry run complete"}</strong>
      <small>${t} source documents · ${s} target documents before copy · env ${l(e.env_file)}</small>
    </span>
    <div class="settings-migration-collections">
      ${e.collections.map(n=>`<span><strong>${l(n.name)}</strong><small>${n.count}</small></span>`).join("")}
    </div>
  </div>`}async function ds(e){const t=e.settings?.provider.active_provider?.provider_id;if(!t||!e.state.draftModelId){e.state.providerError="Provider not loaded.",e.render();return}e.state.isSavingProvider=!0,e.state.providerError="",e.render();try{await Be({provider_id:t,model_id:e.state.draftModelId,model_reasoning_effort:e.state.draftReasoningEffort||null});const s=await G();e.setSettings(s),X(e.state,s),e.setNotice({tone:"success",message:"Provider settings updated."})}catch(s){e.state.providerError=s instanceof Error?s.message:"Unable to update provider settings."}finally{e.state.isSavingProvider=!1,e.render()}}async function cs(e){const t=e.settings?.provider.hosted_text?.active_provider?.provider_id;if(!t||!e.state.hostedDraftModelId){e.state.hostedProviderError="Hosted provider not loaded.",e.render();return}e.state.isSavingHostedProvider=!0,e.state.hostedProviderError="",e.render();try{await Fe({provider_id:t,model_id:e.state.hostedDraftModelId,openrouter_provider_routing:be(e.state)});const s=await G();e.setSettings(s),X(e.state,s),e.setNotice({tone:"success",message:"Hosted model settings updated."})}catch(s){e.state.hostedProviderError=s instanceof Error?s.message:"Unable to update hosted model settings."}finally{e.state.isSavingHostedProvider=!1,e.render()}}function ps({page:e,pendingDeleteUserId:t,selectedUser:s,users:n}){return`${j(e)}
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
    ${Se(n,s)}
    ${s?`<div class="settings-profile-row">
          <form class="settings-card settings-detail" id="edit-user">
            <div class="settings-heading">
              <div>
                <p class="settings-kicker">Selected user</p>
                <h2>${l(s.display_name||s.username)}</h2>
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
        </div>`:'<section class="settings-card"><h2>No users</h2></section>'}`}function us({page:e,selectedUser:t,users:s,workspaces:n}){return`${j(e)}
    ${Se(s,t)}
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
          <div class="settings-memberships">${gs(t,n)}</div>
        </section>`:'<section class="settings-card"><h2>No users</h2></section>'}`}function Se(e,t){return e.length?`<section class="settings-card settings-user-picker">
    <div>
      <p class="settings-kicker">User directory</p>
      <h2>${l(t?t.display_name||t.username:"Select user")}</h2>
      <p class="settings-card-copy">${e.length} user${e.length===1?"":"s"} available.</p>
    </div>
    <label class="settings-platform-field">
      <span>Selected user</span>
      <select id="selected-user">
        ${e.map(s=>`<option value="${v(s.user_id)}" ${s.user_id===t?.user_id?"selected":""}>${l(s.display_name||s.username)} (${l(s.username)})</option>`).join("")}
      </select>
    </label>
  </section>`:`<section class="settings-card settings-user-picker">
      <div>
        <p class="settings-kicker">User directory</p>
        <h2>No users</h2>
      </div>
      <p class="settings-card-copy">Create a user before editing profile or workspace access settings.</p>
    </section>`}function gs(e,t){return t.map(s=>{const n=e.memberships.find(a=>a.workspace_id===s.workspace_id);return`<label class="settings-membership">
        <input type="checkbox" data-workspace-enabled="${v(s.workspace_id)}" ${n?"checked":""} />
        <span class="settings-membership-icon material-symbols-rounded" aria-hidden="true">workspaces</span>
        <span>
          <strong>${l(s.name)}</strong>
          <small>${l(s.workspace_id)}</small>
        </span>
        <select data-workspace-role="${v(s.workspace_id)}">
          <option value="member" ${n?.role!=="admin"?"selected":""}>Member</option>
          <option value="admin" ${n?.role==="admin"?"selected":""}>Workspace admin</option>
        </select>
      </label>`}).join("")}function ms({page:e,workspaceApps:t,workspaces:s}){return`${j(e)}
    <section class="settings-card">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Workspace apps</p>
          <h2>Installation and visibility</h2>
        </div>
      </div>
      <p class="settings-card-copy">Installed means the app has a workspace binding. Only enabled apps are visible to users and served by the core.</p>
      <div class="settings-app-workspaces">${fs(s,t)}</div>
    </section>`}function fs(e,t){return e.map(s=>{const n=t.filter(r=>r.workspace_id===s.workspace_id),a=n.filter(r=>r.status==="enabled").length,o=n.filter(r=>r.installed).length;return`<details class="settings-app-workspace">
        <summary class="settings-app-workspace-heading">
          <span class="settings-summary-caret material-symbols-rounded" aria-hidden="true">chevron_right</span>
          <span class="settings-app-workspace-icon material-symbols-rounded" aria-hidden="true">deployed_code</span>
          <span>
            <strong>${l(s.name)}</strong>
            <small>${l(s.workspace_id)} · ${a}/${o} enabled</small>
          </span>
        </summary>
        <div class="settings-apps">
          ${n.map(vs).join("")}
        </div>
      </details>`}).join("")}function vs(e){const t=e.status==="enabled",s=e.installed,n=s?e.status:"not installed",a=`${e.workspace_id}:${e.app_id}`;return`<div class="settings-app-row">
    <span class="settings-app-icon material-symbols-rounded" aria-hidden="true">${l(hs(e))}</span>
    <span class="settings-app-copy">
      <strong>${l(e.name)}</strong>
      <small>${l(e.app_id)} · v${l(e.version)} · ${l(n)}</small>
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
  </div>`}function hs(e){return e.status!=="enabled"?"hide_source":{agents:"smart_toy","app-store":"storefront","base-shell":"dashboard",browser:"language",calendar:"calendar_month",chat:"forum",checklist:"checklist",crm:"contacts","developer-kit":"developer_board","docs-studio":"description","document-generator":"description","dynamic-views":"dashboard_customize","gmail-app":"mail",mail:"mail",memory:"database","maverick-monitor":"monitor_heart",settings:"admin_panel_settings",skills:"school",speech:"record_voice_over",storage:"cloud",vault:"key","website-studio":"web_asset"}[e.app_id]||"apps"}let H=[],K=[],z=[],te=null,S=null,y=at();const Pe=Object.fromEntries(new URLSearchParams(window.location.search).entries());let V=ge(Pe)||Ce,I=Re(Pe),O=!0,q="",w=null,ce="",pe="";const ie=xt({getPersistence:()=>te,render:()=>_(),requestPersistenceStatusQuiet:ws,setNotice:e=>{w=e},setPersistence:e=>{te=e}}),M=Tt({publishChanged:Us,render:()=>_(),setNotice:e=>{w=e}});function Ee(){return H.find(e=>e.user_id===I)||H[0]}function Re(e){const t=J(e.user_id)||J(e.selected_user_id)||J(e.id);if(t)return t;const s=J(e.app_page),n=/^users\/([^/?#]+)$/.exec(s);if(!n?.[1])return"";try{return decodeURIComponent(n[1])}catch{return n[1]}}function J(e){return typeof e=="string"?e.trim():""}function _s(e){const t=ge(e),s=Re(e);let n=!1;t&&t!==V&&(V=t,n=!0),s&&s!==I&&(I=s,q="",n=!0),n&&((H.length||O)&&_(),t==="app-links"&&Ae())}function bs(e){e.id===ce||window.parent===window||(ce=e.id,window.parent.postMessage({type:"maverick.app.selection-changed",owner_app_id:"settings",selection:{page_id:e.id}},window.location.origin))}function ys(e){!e||e.user_id===pe||window.parent===window||(pe=e.user_id,window.parent.postMessage({type:"maverick.app.selection-changed",owner_app_id:"settings",selection:{user_id:e.user_id}},window.location.origin))}function Y(){window.parent!==window&&window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"settings",resource:"users"},window.location.origin)}async function $s(){try{return await m("/api/admin/persistence")}catch(e){return w={tone:"error",message:e instanceof Error?e.message:"Persistence API unavailable"},null}}async function ws(){try{return await m("/api/admin/persistence")}catch{return null}}async function ks(){try{return await G()}catch{return null}}async function D(){O=!0,_();try{const[e,t,s,n,a]=await Promise.all([Me(),De(),Le(),$s(),ks()]),o=S?.workspace.workspace_id||"",r=a?.workspace.workspace_id||"";H=e,K=t,z=s,te=n,S=a,o!==r&&M.reset(),X(y,S),(!I||!H.some(i=>i.user_id===I))&&(I=H[0]?.user_id||"")}finally{O=!1}_(),V==="app-links"&&Ae()}async function Ae(e=!1){const t=S?.workspace.workspace_id||"";await M.ensureLoaded(t,z,e)}async function Ss(e){const t=new FormData(e);I=(await Ke({username:String(t.get("username")||""),password:String(t.get("password")||""),display_name:String(t.get("display_name")||""),email:String(t.get("email")||""),platform_role:String(t.get("platform_role")||"member")})).user_id,e.reset(),await D(),Y()}async function Ps(e,t){const s=new FormData(e);await Ve(t.user_id,{display_name:String(s.get("display_name")||""),email:String(s.get("email")||""),platform_role:String(s.get("platform_role")||"member"),account_type:String(s.get("account_type")||"standard"),is_active:s.get("is_active")==="on"}),await D(),Y()}async function Es(e,t){const s=new FormData(e),n=String(s.get("password")||""),a=String(s.get("password_confirmation")||"");if(n!==a)throw new Error("Passwords do not match");await Ge(t.user_id,n),e.reset(),w={tone:"success",message:"Password updated."},_()}async function Rs(e){const t=e.display_name||e.username;if(q!==e.user_id){q=e.user_id,w={tone:"info",message:`Press Delete user again to confirm permanent removal of ${t}.`},_();return}await Xe(e.user_id),I="",q="",w={tone:"success",message:`${t} deleted.`},await D(),Y()}async function As(e){const t=K.map(s=>{const n=document.querySelector(`[data-workspace-enabled="${s.workspace_id}"]`),a=document.querySelector(`[data-workspace-role="${s.workspace_id}"]`);return n?.checked?{workspace_id:s.workspace_id,role:a?.value||"member"}:null}).filter(s=>!!s);await Ye(e.user_id,t),await D(),Y()}async function Is(e){await Ze(e),M.invalidate(),await D()}async function Cs(e,t){await xe(e,t),M.invalidate(),await D()}async function Hs(e){await et(e),M.invalidate(),await D()}async function Ms(e,t,s){await M.saveDependencySelection(e,t,s)}async function Ds(e){const t=(e||[]).filter(Boolean);y.cleanupError="",t.length?t.forEach(s=>y.cleaningSessionIds.add(s)):y.clearingAllRuntime=!0,_();try{const s=await ze(t.length?t:void 0);Ls(s),S=await G(),X(y,S),w={tone:"success",message:t.length?"Runtime session cleaned.":"Runtime sessions cleaned."}}catch(s){y.cleanupError=s instanceof Error?s.message:"Unable to clean runtime sessions."}finally{t.forEach(s=>y.cleaningSessionIds.delete(s)),y.clearingAllRuntime=!1,_()}}function Ls(e){e.deleted_threads<=0||window.parent===window||(window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"chat",resource:"threads"},window.location.origin),e.deleted_thread_ids.forEach(t=>{window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"chat",resource:"threads",deleted_thread_id:t},window.location.origin)}))}function Us(e,t){window.parent!==window&&window.parent.postMessage({type:"maverick.app.dependencies-changed",app_id:e,status:t.status},window.location.origin)}async function Ts(){if(window.parent&&window.parent!==window){window.parent.postMessage({type:"maverick.shell.logout"},window.location.origin);return}await We(),window.location.href="/"}function Os(e,t){if(e.id==="users")return ps({page:e,pendingDeleteUserId:q,selectedUser:t,users:H});if(e.id==="workspace-access")return us({page:e,selectedUser:t,users:H,workspaces:K});if(e.id==="workspace-apps")return ms({page:e,workspaceApps:z,workspaces:K});if(e.id==="app-links"){const s=M.viewState();return qt({appRegistry:s.appRegistry,dependencies:s.dependencies,error:s.error,isLoading:s.isLoading,loadErrors:s.loadErrors,page:e,savingKeys:s.savingKeys,workspaceApps:z})}return e.id==="platform-settings"?qs(e):ts(e,ie.viewState())}function qs(e){return`${j(e)}
    ${lt(S,y)}`}function _(){const e=document.getElementById("app"),t=O?void 0:Ee(),s=He(V);e&&(e.innerHTML=`<main class="settings-shell">
    <section class="settings-main">
      <div class="settings-content">
        ${O?wt(s):`<header class="detail-header">
          <div class="detail-title-block">
            <h2>${l(s.title)}</h2>
            <span class="detail-title-separator" aria-hidden="true"></span>
            <p>${l(s.summary)}</p>
          </div>
        </header>
        ${js()}
        ${Os(s,t)}`}
      </div>
    </section>
    ${ss(ie.viewState())}
  </main>`,Ns(),bs(s),O||ys(t))}function Ns(){Vt({clearRuntimeSessionsFromPanel:Ds,createUser:Ss,deleteSelectedUser:Rs,dismissNotice:()=>{w=null,_()},installWorkspaceApp:Is,logoutFromSettings:Ts,onHostedProviderModelChanged:e=>{rt(y,S,e),_()},onHostedProviderRoutingChanged:(e,t)=>{ot(y,e,t),_()},onProviderModelChanged:e=>{it(y,S,e),_()},onProviderReasoningChanged:e=>{y.draftReasoningEffort=e,y.providerError="",_()},persistenceController:ie,render:_,resetSelectedUserPassword:Es,saveDependencySelection:Ms,saveHostedProviderSettingsFromPanel:()=>cs(ue()),saveProviderSettingsFromPanel:()=>ds(ue()),selectedUser:Ee,selectUser:e=>{I=e,q="",_()},setWorkspaceAppStatus:Cs,showError:Ie,uninstallWorkspaceApp:Hs,updateMemberships:As,updateSelectedUser:Ps,workspaceApps:()=>z,appDependencies:()=>M.viewState().dependencies})}function ue(){return{render:_,setNotice:e=>{w=e},setSettings:e=>{S=e},settings:S,state:y}}function Ie(e){w={tone:"error",message:e instanceof Error?e.message:"Unexpected error"},_()}function js(){return w?`<div class="settings-notice settings-notice-${w.tone}">
    <span class="material-symbols-rounded" aria-hidden="true">${w.tone==="error"?"error":w.tone==="success"?"task_alt":"info"}</span>
    <span>${l(w.message)}</span>
    <button type="button" class="settings-icon-button" id="dismiss-notice" aria-label="Close">
      <span class="material-symbols-rounded" aria-hidden="true">close</span>
    </button>
  </div>`:""}window.addEventListener("message",e=>{if(e.origin!==window.location.origin||!e.data||typeof e.data!="object")return;const t=e.data;t.type==="maverick.app.navigate"&&(!t.app_id||t.app_id==="settings")&&_s(t.params||{})});window.parent?.postMessage({type:"maverick.app.ready",app_id:"settings"},window.location.origin);D().catch(Ie);
