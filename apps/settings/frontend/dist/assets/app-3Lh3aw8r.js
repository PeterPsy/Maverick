import{s as me,D as Ce,a as He}from"./pages-BZUBskpf.js";async function v(e,t={}){const s=await fetch(e,{credentials:"same-origin",headers:{"Content-Type":"application/json",...t.headers||{}},...t}),n=await s.json();if(!s.ok)throw new Error(n.detail||n.error||`Request failed ${s.status}`);return n}async function De(){return(await v("/api/admin/users")).items}async function Le(){return(await v("/api/admin/workspaces")).items}async function qe(){return(await v("/api/admin/workspace-apps")).items}function oe(e,t=""){return typeof e=="string"?e:t}function Oe(e){return Array.isArray(e)?e.filter(t=>typeof t=="string"):[]}function Ue(e){if(!e||typeof e!="object"||Array.isArray(e))return null;const t=e,s=t.kind==="image"||t.kind==="glyph"?t.kind:null;return s&&typeof t.value=="string"?{kind:s,value:t.value}:null}function Te(e){const t=e&&typeof e=="object"&&!Array.isArray(e)?e:{},s=oe(t.app_id);return{app_id:s,name:oe(t.name,s||"Unnamed app"),views:Oe(t.views),logo:Ue(t.logo)}}async function Ne(){return((await v("/api/apps")).items||[]).map(Te).filter(t=>t.app_id)}function Be(e){const t=new URLSearchParams({consumer_app_id:e});return v(`/api/apps/dependencies?${t.toString()}`)}function je(e,t,s){return v("/api/apps/dependencies",{method:"POST",body:JSON.stringify({consumer_app_id:e,alias:t,provider_app_ids:s})})}function V(){return v("/api/settings/platform")}function Fe(e){return v("/api/providers/active",{method:"POST",body:JSON.stringify(e)})}function ze(e){return v("/api/providers/hosted/selection",{method:"POST",body:JSON.stringify(e)})}function We(e,t="settings_runtime_sessions_cleared"){return v("/api/settings/runtime-sessions/clear",{method:"POST",body:JSON.stringify({session_ids:e,reason:t})})}function Je(){return v("/api/auth/logout",{method:"POST"})}function Ke(e){return v("/api/admin/persistence/migrations/dry-run",{method:"POST",body:JSON.stringify(e)})}function Ve(e){return v("/api/admin/persistence/migrations/apply",{method:"POST",body:JSON.stringify(e)})}function Qe(e){return v("/api/admin/users",{method:"POST",body:JSON.stringify(e)})}function Ge(e,t){return v(`/api/admin/users/${encodeURIComponent(e)}`,{method:"PATCH",body:JSON.stringify(t)})}function Xe(e,t){return v(`/api/admin/users/${encodeURIComponent(e)}/password`,{method:"POST",body:JSON.stringify({password:t})})}function Ye(e){return v(`/api/admin/users/${encodeURIComponent(e)}`,{method:"DELETE"})}function Ze(e,t){return v(`/api/admin/users/${encodeURIComponent(e)}/workspaces`,{method:"PUT",body:JSON.stringify({memberships:t})})}function xe(e){return v(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"POST",body:JSON.stringify({source_id:e.source_id,enabled:!0})})}function et(e,t){return v(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"PATCH",body:JSON.stringify({status:t?"enabled":"disabled"})})}function tt(e){return v(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"DELETE",body:JSON.stringify({})})}function ee(e){const t=e?.provider.active_provider,s=e?.provider.model_settings;return fe(t,s,ne(e))}function ne(e){const t=e?.provider.active_provider,s=e?.provider.model_settings;return ve(t,s)}function st(e){const t=e?.provider.hosted_text?.active_provider||null,s=e?.provider.hosted_text?.model_settings||null;return fe(t,s,ae(e))}function ae(e){const t=e?.provider.hosted_text?.active_provider||null,s=e?.provider.hosted_text?.model_settings||null;return ve(t,s)}function fe(e,t,s){const n=t?.selected_model_id||e?.default_model_family||"",a=s.find(i=>i.model_id===n)||null;return{modelId:n,reasoningEffort:t?.selected_reasoning_effort||he(a)}}function ve(e,t){const s=t?.selected_model_id||e?.default_model_family||"",n=Z(t?.available_models).length?Z(t?.available_models):Z(e?.model_options);return(n.length?n:s?[at(s,t?.selected_reasoning_effort||"")]:[]).map(nt)}function he(e){return e?.default_reasoning_effort||e?.supported_reasoning_efforts[0]?.effort||""}function Z(e){return(e||[]).filter(t=>t.model_id)}function nt(e){return e.supported_reasoning_efforts.length||!e.default_reasoning_effort?e:{...e,supported_reasoning_efforts:[{effort:e.default_reasoning_effort,label:e.default_reasoning_effort,description:null}]}}function at(e,t){return{model_id:e,label:e,description:null,default_reasoning_effort:t||null,supported_reasoning_efforts:t?[{effort:t,label:t,description:null}]:[]}}const it=new Set(["created","running","stopping"]);function rt(){return{cleanupError:"",clearingAllRuntime:!1,cleaningSessionIds:new Set,draftModelId:"",draftReasoningEffort:"",hostedDraftModelId:"",hostedProviderError:"",hostedProviderErrorModelId:"",hostedRoutingDraftsByModel:{},isSavingHostedProvider:!1,isSavingProvider:!1,providerError:""}}function Q(e,t){const{modelId:s,reasoningEffort:n}=ee(t),{modelId:a}=st(t),i=new Set(ae(t).map(r=>r.model_id).filter(Boolean));a&&i.add(a),e.draftModelId=s,e.draftReasoningEffort=n,e.hostedDraftModelId=a,e.hostedRoutingDraftsByModel=Object.fromEntries(Array.from(i).map(r=>[r,X(G(t,r))]))}function ot(e,t,s){const n=ne(t).find(a=>a.model_id===s)||null;e.draftModelId=s,e.draftReasoningEffort=he(n),e.providerError=""}function dt(e,t,s){e.hostedDraftModelId=s,ye(e,t,s),e.hostedProviderError="",e.hostedProviderErrorModelId=""}function lt(e,t,s,n,a){if(!s)return;const i=ye(e,t,s);e.hostedDraftModelId=s,n==="mode"&&typeof a=="string"&&["auto","prefer","only","ignore"].includes(a)?i.mode=a:n==="provider_id"&&typeof a=="string"?i.providerId=a:n==="allow_fallbacks"&&typeof a=="boolean"?i.allowFallbacks=a:n==="require_parameters"&&typeof a=="boolean"?i.requireParameters=a:n==="sort"&&typeof a=="string"&&["","price","throughput","latency"].includes(a)?i.sort=a:n==="data_collection"&&typeof a=="string"&&["","allow","deny"].includes(a)?i.dataCollection=a:n==="quantization"&&typeof a=="string"&&(i.quantization=a),e.hostedProviderError="",e.hostedProviderErrorModelId=""}function _e(e,t=e.hostedDraftModelId){const s=e.hostedRoutingDraftsByModel[t]||kt();return{mode:s.mode,provider_id:s.providerId||void 0,allow_fallbacks:s.allowFallbacks,require_parameters:s.requireParameters,sort:s.sort,data_collection:s.dataCollection,quantizations:s.quantization?[s.quantization]:[]}}function ct(e,t){if(!e)return`<section class="settings-card settings-platform">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Settings</p>
          <h2>Platform settings</h2>
        </div>
      </div>
      <p class="settings-card-copy">Platform settings are not available from the active backend.</p>
    </section>`;const s=e.provider.active_provider,n=e.provider.hosted_text?.active_provider||null,a=yt(e),i=a.filter(l=>it.has(l.status)),r=e.runtime.cleanup_allowed??!1,o=e.runtime.cleanup_scope||"none",p=ne(e),g=ae(e),k=ee(e).modelId,A=ee(e).reasoningEffort,R=(p.find(l=>l.model_id===t.draftModelId)||p[0]||null)?.supported_reasoning_efforts||[],q=$t(e,t),O=!!(s&&t.draftModelId&&!t.isSavingProvider&&(t.draftModelId!==k||t.draftReasoningEffort!==A));return`${pt(e)}
    ${ut(s,p,R,O,i.length,a.length,q,g,n,e,t)}
    ${_t(a,r,o,t)}`}function pt(e){return`<section class="settings-card settings-platform settings-user-settings-card">
    <div class="settings-heading settings-platform-heading">
      <div>
        <p class="settings-kicker">Account</p>
        <h2>User settings</h2>
      </div>
    </div>
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
  </section>`}function ut(e,t,s,n,a,i,r,o,p,g,k){return`<section class="settings-card settings-platform settings-model-settings-card">
    <div class="settings-heading settings-platform-heading">
      <div>
        <p class="settings-kicker">Models</p>
        <h2>Model settings</h2>
      </div>
    </div>
    <div class="settings-platform-provider-forms">
      ${mt(e,t,s,n,a,i,!r,k)}
      ${ft(o,r,p,g,k)}
    </div>
  </section>`}function gt(e){document.getElementById("settings-provider-model")?.addEventListener("change",t=>{e.onProviderModelChanged(t.currentTarget.value)}),document.getElementById("settings-provider-reasoning")?.addEventListener("change",t=>{e.onProviderReasoningChanged(t.currentTarget.value)}),document.querySelectorAll("[data-settings-model-accordion]").forEach(t=>{t.addEventListener("toggle",()=>{t.open&&document.querySelectorAll("[data-settings-model-accordion]").forEach(s=>{s!==t&&(s.open=!1)})})}),document.querySelectorAll("[data-openrouter-routing]").forEach(t=>{t.addEventListener("change",s=>{const n=s.currentTarget,a=n.dataset.hostedModelId||n.closest("[data-hosted-model-accordion]")?.dataset.hostedModelAccordion||"";e.onHostedProviderRoutingChanged(a,n.dataset.openrouterRouting||"",n instanceof HTMLInputElement&&n.type==="checkbox"?n.checked:n.value)})}),document.getElementById("settings-save-provider")?.addEventListener("click",e.onSaveProviderSettings),document.querySelectorAll("[data-hosted-provider-save]").forEach(t=>{t.addEventListener("click",()=>e.onSaveHostedProviderSettings(t.dataset.hostedProviderSave||""))}),document.getElementById("settings-logout")?.addEventListener("click",e.onLogout),document.getElementById("settings-clear-all-runtime")?.addEventListener("click",e.onClearAllRuntimeSessions),document.querySelectorAll("[data-runtime-clear]").forEach(t=>{t.addEventListener("click",()=>e.onClearRuntimeSession(t.dataset.runtimeClear||""))})}function mt(e,t,s,n,a,i,r,o){return`<details class="settings-model-accordion settings-agentic-provider-accordion" data-settings-model-accordion="agentic-provider" data-agentic-provider-accordion ${r?"open":""}>
    <summary class="settings-model-trigger">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">memory</span>
      <span class="settings-model-copy">
        <span class="settings-model-kicker">
          <span class="settings-kicker">Agentic provider</span>
        </span>
        <strong>${m(e?.label||"Provider not loaded")}</strong>
        <small>${m(o.draftModelId||"model")} · ${m(o.draftReasoningEffort||"reasoning")} · Codex tools/filesystem/MCP · ${a} active / ${i} in scope</small>
      </span>
      <span class="settings-model-chevron material-symbols-rounded" aria-hidden="true">expand_more</span>
    </summary>
    <div class="settings-model-content settings-agentic-provider-content">
    <label class="settings-platform-field">
      <span>Model</span>
      <select id="settings-provider-model" ${!t.length||o.isSavingProvider?"disabled":""}>
        ${t.map(p=>`<option value="${h(p.model_id)}" ${p.model_id===o.draftModelId?"selected":""}>${m(p.label||p.model_id)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Reasoning</span>
      <select id="settings-provider-reasoning" ${!s.length||o.isSavingProvider?"disabled":""}>
        ${s.map(p=>`<option value="${h(p.effort)}" ${p.effort===o.draftReasoningEffort?"selected":""}>${m(p.label||p.effort)}</option>`).join("")}
      </select>
    </label>
    <button type="button" id="settings-save-provider" ${n?"":"disabled"}>
      <span class="material-symbols-rounded" aria-hidden="true">${o.isSavingProvider?"sync":"save"}</span>
      ${o.isSavingProvider?"Saving":"Save model"}
    </button>
    ${o.providerError?`<p class="settings-platform-error">${m(o.providerError)}</p>`:""}
    </div>
  </details>`}function ft(e,t,s,n,a){const i=!!s;return`<div class="settings-hosted-models">
    <div class="settings-platform-form-heading settings-hosted-models-heading">
      <span class="material-symbols-rounded" aria-hidden="true">route</span>
      <span>
        <strong>Hosted OpenRouter models</strong>
        <small>Settings manages model defaults and upstream routing; Chat only uses text-output fast models.</small>
      </span>
    </div>
    ${e.length?e.map(r=>vt(r,t,s,n,a)).join(""):'<p class="settings-card-copy settings-platform-note">No hosted models are available from the active hosted provider.</p>'}
    ${i?"":'<p class="settings-card-copy settings-platform-note">Activate a hosted text provider before selecting a fast model.</p>'}
  </div>`}function vt(e,t,s,n,a){const i=e.model_id,r=wt(a,n,i),o=e.upstream_provider_options||[],p=Array.from(new Set(o.map(c=>c.quantization||"").filter(Boolean))),g=!!s,k=a.isSavingHostedProvider&&a.hostedDraftModelId===i,A=!!(g&&i&&!a.isSavingHostedProvider&&be(a,n,i)),M=ht(e),R=M?"Hosted chat / fast model":"Hosted speech model",q=M?"plain hosted chat capable · runtime engine remains Codex":"speech synthesis metadata · not used by plain hosted chat",O=i===t,l=s?.label||s?.provider_id||"Hosted provider";return`<details class="settings-model-accordion settings-hosted-model-accordion" data-settings-model-accordion="hosted:${h(i)}" data-hosted-model-accordion="${h(i)}" ${O?"open":""}>
    <summary class="settings-model-trigger">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">bolt</span>
      <span class="settings-model-copy">
        <span class="settings-model-kicker">
          <span class="settings-kicker">${R}</span>
          <span class="settings-pill">Active</span>
        </span>
        <strong>${m(e.label||i)} - ${m(l)}</strong>
        <small>${m(i||"model not selected")} · ${q}</small>
      </span>
      <span class="settings-model-chevron material-symbols-rounded" aria-hidden="true">expand_more</span>
    </summary>
    <div class="settings-model-content settings-hosted-model-content">
      <div class="settings-platform-field settings-platform-field-wide">
        <span>Model</span>
        <code class="settings-model-code">${m(i||"model not selected")}</code>
      </div>
    <label class="settings-platform-field">
      <span>OpenRouter upstream</span>
      <select data-openrouter-routing="mode" data-hosted-model-id="${h(i)}" ${!g||!o.length||a.isSavingHostedProvider?"disabled":""}>
        ${[["auto","Auto"],["prefer","Prefer selected"],["only","Only selected"],["ignore","Ignore selected"]].map(([c,b])=>`<option value="${h(c)}" ${c===r.mode?"selected":""}>${m(b)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Upstream provider</span>
      <select data-openrouter-routing="provider_id" data-hosted-model-id="${h(i)}" ${!g||!o.length||r.mode==="auto"||a.isSavingHostedProvider?"disabled":""}>
        <option value="">Select provider</option>
        ${o.map(c=>`<option value="${h(String(c.provider_id||c.tag||""))}" ${(c.provider_id||c.tag)===r.providerId?"selected":""}>${m(c.label||c.provider_id||c.tag||"Provider")}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Sort</span>
      <select data-openrouter-routing="sort" data-hosted-model-id="${h(i)}" ${!g||a.isSavingHostedProvider?"disabled":""}>
        ${[["","OpenRouter default"],["price","Price"],["throughput","Throughput"],["latency","Latency"]].map(([c,b])=>`<option value="${h(c)}" ${c===r.sort?"selected":""}>${m(b)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Data collection</span>
      <select data-openrouter-routing="data_collection" data-hosted-model-id="${h(i)}" ${!g||a.isSavingHostedProvider?"disabled":""}>
        ${[["","OpenRouter default"],["allow","Allow"],["deny","Deny"]].map(([c,b])=>`<option value="${h(c)}" ${c===r.dataCollection?"selected":""}>${m(b)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Quantization</span>
      <select data-openrouter-routing="quantization" data-hosted-model-id="${h(i)}" ${!g||!p.length||a.isSavingHostedProvider?"disabled":""}>
        <option value="">Any</option>
        ${p.map(c=>`<option value="${h(c)}" ${c===r.quantization?"selected":""}>${m(c)}</option>`).join("")}
      </select>
    </label>
    <div class="settings-platform-checks">
      <label><input type="checkbox" data-openrouter-routing="allow_fallbacks" data-hosted-model-id="${h(i)}" ${r.allowFallbacks?"checked":""} ${!g||a.isSavingHostedProvider?"disabled":""}> Allow OpenRouter fallback</label>
      <label><input type="checkbox" data-openrouter-routing="require_parameters" data-hosted-model-id="${h(i)}" ${r.requireParameters?"checked":""} ${!g||a.isSavingHostedProvider?"disabled":""}> Require supported parameters</label>
    </div>
    <button type="button" data-hosted-provider-save="${h(i)}" ${A?"":"disabled"}>
      <span class="material-symbols-rounded" aria-hidden="true">${k?"sync":"save"}</span>
      ${k?"Saving":"Save hosted model"}
    </button>
    ${a.hostedProviderError&&a.hostedProviderErrorModelId===i?`<p class="settings-platform-error">${m(a.hostedProviderError)}</p>`:""}
    </div>
  </details>`}function ht(e){const t=e.output_modalities||[];return!t.length||t.includes("text")}function _t(e,t,s,n){return`<section class="settings-card settings-platform settings-runtime-settings-card">
    <details class="settings-platform-runtime" open>
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
      ${e.length?e.map(i=>bt(i,t,n)).join(""):'<p class="settings-card-copy">No runtime sessions.</p>'}
    </div>
    ${n.cleanupError?`<p class="settings-platform-error">${m(n.cleanupError)}</p>`:""}
  </details>
  </section>`}function bt(e,t,s){const n=s.cleaningSessionIds.has(e.session_id);return`<div class="settings-platform-runtime-row">
    <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">terminal</span>
    <span class="settings-platform-runtime-copy">
      <span class="settings-platform-runtime-title">
        <strong>${m(e.agent_id||e.session_id)}</strong>
        <button type="button" class="settings-secondary settings-platform-runtime-clear" data-runtime-clear="${h(e.session_id)}" aria-label="Clean runtime session ${h(e.agent_id||e.session_id)}" ${!t||s.clearingAllRuntime||n?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">${n?"sync":"delete_sweep"}</span>
          <span class="settings-platform-runtime-clear-label">${n?"Cleaning":"Clean"}</span>
        </button>
      </span>
      <small>${m(e.workspace_name||e.workspace_id)} · ${m(e.effective_mode)} · ${m(e.status)}</small>
      <code>${m(e.session_id)}</code>
    </span>
  </div>`}function yt(e){return e.runtime.all_sessions||e.runtime.sessions||[]}function G(e,t){const s=e?.provider.hosted_text?.selection?.openrouter_provider_routing_by_model?.[t];return{mode:s?.mode||"auto",provider_id:s?.provider_id||"",allow_fallbacks:s?.allow_fallbacks!==!1,require_parameters:s?.require_parameters===!0,sort:s?.sort||"",data_collection:s?.data_collection||"",quantizations:s?.quantizations||[]}}function be(e,t,s){const n=G(t,s),a=_e(e,s);return n.mode!==a.mode||(n.provider_id||"")!==(a.provider_id||"")||n.allow_fallbacks!==!1!=(a.allow_fallbacks!==!1)||n.require_parameters===!0!=(a.require_parameters===!0)||(n.sort||"")!==(a.sort||"")||(n.data_collection||"")!==(a.data_collection||"")||(n.quantizations?.[0]||"")!==(a.quantizations?.[0]||"")}function $t(e,t){return t.hostedProviderErrorModelId?t.hostedProviderErrorModelId:!t.hostedDraftModelId||!be(t,e,t.hostedDraftModelId)?"":t.hostedDraftModelId}function wt(e,t,s){return e.hostedRoutingDraftsByModel[s]||X(G(t,s))}function ye(e,t,s){return e.hostedRoutingDraftsByModel[s]||(e.hostedRoutingDraftsByModel[s]=X(G(t,s))),e.hostedRoutingDraftsByModel[s]}function X(e){return{allowFallbacks:e.allow_fallbacks!==!1,dataCollection:e.data_collection||"",mode:e.mode||"auto",providerId:e.provider_id||"",quantization:e.quantizations?.[0]||"",requireParameters:e.require_parameters===!0,sort:e.sort||""}}function kt(){return X({mode:"auto",allow_fallbacks:!0,require_parameters:!1,sort:"",data_collection:"",quantizations:[]})}function m(e){return e.replace(/[&<>"']/g,t=>t==="&"?"&amp;":t==="<"?"&lt;":t===">"?"&gt;":t==='"'?"&quot;":"&#39;")}function h(e){return m(e)}const St=5,Pt=4,Et=4,At=3,It=4;function Mt(e){return`<section class="settings-loading-skeleton" role="status" aria-label="Settings content is loading">
    <header class="detail-header settings-loading-skeleton__header" aria-hidden="true">
      <div class="detail-title-block">
        ${f("title")}
        <span class="detail-title-separator" aria-hidden="true"></span>
        ${f("subtitle")}
      </div>
    </header>
    ${Rt(e)}
  </section>`}function Rt(e){return e.id==="workspace-access"?Ht():e.id==="workspace-apps"?Dt():e.id==="platform-settings"?Lt():e.id==="persistence"?qt():Ct()}function Ct(){return`<section class="settings-card settings-loading-skeleton__create" aria-hidden="true">
      ${Ot("short-title")}
      ${C(St,()=>w("field"))}
      ${w("button")}
    </section>
    ${$e()}
    <div class="settings-loading-skeleton__profile-row" aria-hidden="true">
      <section class="settings-card settings-loading-skeleton__detail-card">
        ${j(!0)}
        <div class="settings-loading-skeleton__field-grid">
          ${C(Pt,()=>W())}
        </div>
        ${w("toggle")}
        ${w("button")}
      </section>
      <section class="settings-card settings-loading-skeleton__password-card">
        ${j(!1)}
        ${f("copy")}
        <div class="settings-loading-skeleton__field-grid">
          ${C(2,()=>W())}
        </div>
        ${w("button")}
        ${w("danger-button")}
      </section>
    </div>`}function Ht(){return`${$e()}
    <section class="settings-card" aria-hidden="true">
      ${j(!0)}
      <div class="settings-loading-skeleton__rows">
        ${C(Et,()=>Ut())}
      </div>
    </section>`}function Dt(){return`<section class="settings-card" aria-hidden="true">
      ${j(!1)}
      ${f("copy-wide")}
      <div class="settings-loading-skeleton__rows">
        ${C(At,()=>Tt())}
      </div>
    </section>`}function Lt(){return`<section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
      ${x()}
    </section>
    <section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
      ${x()}
      <div class="settings-loading-skeleton__provider-form">
        ${C(2,()=>W())}
        ${w("button")}
      </div>
      ${x()}
    </section>
    <section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
      <div class="settings-loading-skeleton__runtime-toolbar">
        ${f("copy-wide")}
        ${w("button")}
      </div>
      <div class="settings-loading-skeleton__runtime-list">
        ${C(It,()=>Nt())}
      </div>
    </section>`}function qt(){return`<section class="settings-card settings-loading-skeleton__persistence" aria-hidden="true">
      ${j(!0)}
      <div class="settings-loading-skeleton__adapter-cards">
        ${C(2,()=>Bt())}
      </div>
      ${jt()}
    </section>`}function $e(){return`<section class="settings-card settings-user-picker" aria-hidden="true">
    <div class="settings-loading-skeleton__copy-stack">
      ${f("kicker")}
      ${f("card-title")}
      ${f("copy-short")}
    </div>
    ${W()}
  </section>`}function j(e){return`<div class="settings-loading-skeleton__heading">
    <span class="settings-loading-skeleton__copy-stack">
      ${f("kicker")}
      ${f("card-title")}
    </span>
    ${e?w("pill"):""}
  </div>`}function Ot(e){return`<div class="settings-loading-skeleton__copy-stack">
    ${f("kicker")}
    ${f(e)}
  </div>`}function W(){return`<span class="settings-loading-skeleton__field-wrap">
    ${f("label")}
    ${w("field")}
  </span>`}function Ut(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--membership">
    ${w("checkbox")}
    ${B("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${f("row-title")}
      ${f("row-copy")}
    </span>
    ${w("select")}
  </span>`}function Tt(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--app">
    ${B("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${f("row-title")}
      ${f("row-copy")}
    </span>
    ${w("toggle-pill")}
    ${w("button")}
  </span>`}function x(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--tile">
    ${B("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${f("row-title")}
      ${f("row-copy")}
    </span>
  </span>`}function Nt(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--runtime">
    ${B("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${f("row-title")}
      ${f("row-copy")}
    </span>
    ${w("button")}
  </span>`}function Bt(){return`<span class="settings-loading-skeleton__adapter-card">
    ${B("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${f("row-title")}
      ${f("row-copy-wide")}
    </span>
    ${w("pill")}
  </span>`}function jt(){return`<span class="settings-loading-skeleton__result">
    ${B("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${f("row-title")}
      ${f("row-copy-wide")}
    </span>
  </span>`}function f(e){return`<span class="settings-loading-skeleton__line settings-loading-skeleton__line--${e}"></span>`}function w(e){return`<span class="settings-loading-skeleton__block settings-loading-skeleton__block--${e}"></span>`}function B(e){return`<span class="settings-loading-skeleton__icon settings-loading-skeleton__icon--${e}"></span>`}function C(e,t){return Array.from({length:e},t).join("")}function Ft({publishChanged:e,render:t,setNotice:s}){let n=[],a=[],i="",r=[],o="",p=!1,g=new Set;function k(){return{appRegistry:n,dependencies:a,error:i,isLoading:p,loadErrors:r,savingKeys:g}}function A(){n=[],a=[],i="",r=[],o=""}function M(){o=""}async function R(l,c,b=!1){if(!(!l||p)&&!(!b&&o===l)){p=!0,i="",r=[],t();try{const[y,u]=await Promise.all([Ne(),O(l,c)]);n=y,a=u,o=l}catch(y){a=[],o="",i=y instanceof Error?y.message:"Unable to load app links."}finally{p=!1,t()}}}async function q(l,c,b){const y=zt(l,c);g=new Set([...g,y]),t();try{const u=await je(l,c,b);a=a.map(U=>U.consumer_app_id===l?u:U),e(l,u),s({tone:"success",message:"App link updated."})}finally{const u=new Set(g);u.delete(y),g=u,t()}}async function O(l,c){const b=c.filter(u=>u.workspace_id===l&&u.status==="enabled"),y=await Promise.all(b.map(async u=>{try{return{app:u,payload:await Be(u.app_id)}}catch(U){return{app:u,error:U instanceof Error?U.message:"Unable to load app links."}}}));return r=y.filter(u=>"error"in u).map(u=>({app_id:u.app.app_id,message:u.error,name:u.app.name||u.app.app_id})),y.filter(u=>"payload"in u&&u.payload.dependencies.length>0).map(u=>u.payload).sort((u,U)=>u.consumer_app_id.localeCompare(U.consumer_app_id))}return{ensureLoaded:R,invalidate:M,reset:A,saveDependencySelection:q,viewState:k}}function zt(e,t){return`${e}:${t}`}function d(e){return e.replace(/[&<>"']/g,t=>t==="&"?"&amp;":t==="<"?"&lt;":t===">"?"&gt;":t==='"'?"&quot;":"&#39;")}function _(e){return d(e)}function Wt({appRegistry:e,dependencies:t,error:s,isLoading:n,loadErrors:a,savingKeys:i,workspaceApps:r}){return`<section class="settings-card settings-app-links">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">App links</p>
          <h2>Provider app links</h2>
        </div>
      </div>
      <p class="settings-card-copy">Provider links are workspace-scoped. A selected provider is reused until it becomes unavailable; otherwise one-provider interface links use the first available candidate as their automatic default.</p>
      ${s?`<p class="settings-platform-error">${d(s)}</p>`:""}
      ${a.length?`<div class="settings-app-link-errors">${a.map(Zt).join("")}</div>`:""}
      ${t.length>1?Jt(t,e,r):""}
      <div class="settings-app-link-list">
        ${t.length?t.map(o=>Kt(o,e,r,i)).join(""):Qt(s,n)}
      </div>
    </section>`}function Jt(e,t,s){return`<nav class="settings-app-link-consumer-nav" aria-label="Provider link apps">
    ${e.map(n=>{const a=s.find(o=>o.workspace_id===n.workspace_id&&o.app_id===n.consumer_app_id),i=ie(t,n.consumer_app_id),r=a?.name||i?.name||n.consumer_app_id;return`<a class="settings-app-link-consumer-nav__item" href="#${_(we(n.consumer_app_id))}">
        <strong>${d(r)}</strong>
        <small>${d(String(n.dependencies.length))}</small>
      </a>`}).join("")}
  </nav>`}function Kt(e,t,s,n){const a=s.find(r=>r.workspace_id===e.workspace_id&&r.app_id===e.consumer_app_id),i=ie(t,e.consumer_app_id);return`<article class="settings-app-link-consumer" id="${_(we(e.consumer_app_id))}">
    <header class="settings-app-link-consumer__header">
      ${Se(i,e.consumer_app_id)}
      <span class="settings-app-copy">
        <strong>${d(a?.name||e.consumer_app_id)}</strong>
        <small>${d(e.consumer_app_id)} - ${d(e.status)}</small>
      </span>
    </header>
    <div class="settings-app-link-dependencies">
      ${e.dependencies.map(r=>Vt(e.consumer_app_id,r,t,n)).join("")}
    </div>
  </article>`}function Vt(e,t,s,n){const a=n.has(Gt(e,t.alias)),i=Xt(t),r=ke(t);return`<section class="settings-app-link-row">
    <header class="settings-app-link-row__header">
      <span class="settings-app-link-row__copy">
        <strong>${d(t.alias)}</strong>
        <small>${d(t.interface)} ${d(t.version)}</small>
      </span>
      <span class="settings-pill ${t.status==="resolved"||r?"":"settings-pill-muted"}">${d(Yt(t,r))}</span>
    </header>
    <p class="settings-card-copy">${d(t.description||"No description.")}</p>
    ${t.blocked_reason?`<p class="settings-platform-error">${d(t.blocked_reason)}</p>`:""}
    ${t.stale_provider_app_ids.length?`<p class="settings-platform-error">Unavailable selection: ${d(t.stale_provider_app_ids.join(", "))}</p>`:""}
    ${t.candidates.length?`<div class="settings-app-link-candidates">
            ${t.candidates.map(o=>{const p=i.includes(o.app_id),g=t.cardinality==="many"?"checkbox":"radio",k=`dependency:${e}:${t.alias}`,A=ie(s,o.app_id);return`<label class="settings-app-link-candidate ${p?"is-selected":""}">
                <input
                  ${p?"checked":""}
                  ${a?"disabled":""}
                  data-dependency-choice="${_(de(e,t.alias,o.app_id))}"
                  name="${_(k)}"
                  type="${g}"
                />
                ${Se(A,o.app_id)}
                <span>
                  <strong>${d(o.name||o.app_id)}</strong>
                  <small>${d(o.app_id)} - ${d(o.interface_version)}${o.app_id===r?" - automatic default":""}</small>
                </span>
              </label>`}).join("")}
          </div>`:'<p class="settings-card-copy">No enabled provider app is available for this interface.</p>'}
    ${r?`<button type="button" class="settings-secondary" data-dependency-save-default="${_(de(e,t.alias,r))}" ${a?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">${a?"sync":"save"}</span>
          ${a?"Saving":"Save default"}
        </button>`:""}
  </section>`}function Qt(e,t){return e?"":t?'<p class="settings-card-copy">Loading app links...</p>':'<p class="settings-card-copy">No enabled app in the active workspace declares provider links.</p>'}function Gt(e,t){return`${e}:${t}`}function de(e,t,s){return`${e}:${t}:${s}`}function we(e){return`settings-app-link-consumer-${e}`}function Xt(e){if(e.selected_provider_app_ids.length)return e.selected_provider_app_ids;const t=ke(e);return t?[t]:[]}function ke(e){return e.selected_provider_app_ids.length||e.status!=="optional_unset"||e.cardinality!=="one"||e.stale_provider_app_ids.length||e.blocked_reason?"":e.candidates[0]?.app_id||""}function Yt(e,t){return t?"auto default":e.status==="optional_unset"?"unset":e.status}function ie(e,t){return e.find(s=>s.app_id===t)||null}function Zt(e){return`<p class="settings-platform-error">${d(e.name||e.app_id)}: ${d(e.message)}</p>`}function Se(e,t){if(e?.logo?.kind==="image"&&e.logo.value)return`<span class="settings-app-link-logo is-image"><img alt="" loading="lazy" src="${_(e.logo.value)}" /></span>`;const s=e?.logo?.value||xt(e,t);return`<span class="settings-app-link-logo is-glyph"><span class="material-symbols-rounded" aria-hidden="true">${d(s)}</span></span>`}function xt(e,t){const s={agents:"smart_toy","app-store":"storefront","base-shell":"dashboard",chat:"forum",checklist:"checklist",crm:"contacts","developer-kit":"developer_board","docs-studio":"description","document-generator":"description","dynamic-views":"dashboard_customize","gmail-app":"mail",memory:"database","maverick-monitor":"monitor_heart",settings:"admin_panel_settings",skills:"school",speech:"record_voice_over",storage:"cloud","website-studio":"web_asset"};return s[t]?s[t]:e?.views.includes("chat")?"forum":e?.views.includes("agents")?"smart_toy":e?.views.includes("shell")?"dashboard":"apps"}function es(e){document.getElementById("dismiss-notice")?.addEventListener("click",e.dismissNotice),document.getElementById("create-user")?.addEventListener("submit",s=>{s.preventDefault(),e.createUser(s.currentTarget).catch(e.showError)});const t=e.selectedUser();document.getElementById("selected-user")?.addEventListener("change",s=>{e.selectUser(s.currentTarget.value)}),document.getElementById("edit-user")?.addEventListener("submit",s=>{s.preventDefault(),t&&e.updateSelectedUser(s.currentTarget,t).catch(e.showError)}),document.getElementById("reset-password")?.addEventListener("submit",s=>{s.preventDefault(),t&&e.resetSelectedUserPassword(s.currentTarget,t).catch(e.showError)}),document.getElementById("delete-user")?.addEventListener("click",()=>{t&&e.deleteSelectedUser(t).catch(e.showError)}),document.getElementById("save-memberships")?.addEventListener("click",()=>{t&&e.updateMemberships(t).catch(e.showError)}),ss(e),ts(e),ns(e),gt({onClearAllRuntimeSessions:()=>{e.clearRuntimeSessionsFromPanel().catch(e.showError)},onClearRuntimeSession:s=>{s&&e.clearRuntimeSessionsFromPanel([s]).catch(e.showError)},onLogout:()=>{e.logoutFromSettings().catch(e.showError)},onHostedProviderRoutingChanged:e.onHostedProviderRoutingChanged,onProviderModelChanged:e.onProviderModelChanged,onProviderReasoningChanged:e.onProviderReasoningChanged,onSaveHostedProviderSettings:s=>{e.saveHostedProviderSettingsFromPanel(s).catch(e.showError)},onSaveProviderSettings:()=>{e.saveProviderSettingsFromPanel().catch(e.showError)}})}function ts(e){document.querySelectorAll("[data-dependency-choice]").forEach(t=>{t.addEventListener("change",()=>{const s=le(t.dataset.dependencyChoice||"");if(!s)return;const n=e.appDependencies().find(i=>i.consumer_app_id===s.consumerAppId)?.dependencies.find(i=>i.alias===s.alias);if(!n)return;if(n.cardinality==="one"){e.saveDependencySelection(s.consumerAppId,s.alias,[s.providerAppId]).catch(e.showError);return}const a=new Set(n.selected_provider_app_ids);t.checked?a.add(s.providerAppId):a.delete(s.providerAppId),e.saveDependencySelection(s.consumerAppId,s.alias,Array.from(a)).catch(e.showError)})}),document.querySelectorAll("[data-dependency-save-default]").forEach(t=>{t.addEventListener("click",()=>{const s=le(t.dataset.dependencySaveDefault||"");s&&e.saveDependencySelection(s.consumerAppId,s.alias,[s.providerAppId]).catch(e.showError)})})}function le(e){const[t,s,...n]=e.split(":"),a=n.join(":");return!t||!s||!a?null:{alias:s,consumerAppId:t,providerAppId:a}}function ss(e){document.querySelectorAll("[data-app-toggle]").forEach(t=>{t.addEventListener("change",()=>{const s=e.workspaceApps().find(n=>`${n.workspace_id}:${n.app_id}`===t.dataset.appToggle);s&&e.setWorkspaceAppStatus(s,t.checked).catch(e.showError)})}),document.querySelectorAll("[data-app-install]").forEach(t=>{t.addEventListener("click",()=>{const s=e.workspaceApps().find(n=>`${n.workspace_id}:${n.app_id}`===t.dataset.appInstall);s&&e.installWorkspaceApp(s).catch(e.showError)})}),document.querySelectorAll("[data-app-uninstall]").forEach(t=>{t.addEventListener("click",()=>{const s=e.workspaceApps().find(n=>`${n.workspace_id}:${n.app_id}`===t.dataset.appUninstall);s&&e.uninstallWorkspaceApp(s).catch(e.showError)})})}function ns(e){document.querySelectorAll("[data-adapter-target]").forEach(t=>{t.addEventListener("click",()=>{const s=t.dataset.adapterTarget;(s==="json"||s==="mongo")&&e.persistenceController.prepare(s).catch(e.showError)})}),document.getElementById("close-migration-modal")?.addEventListener("click",()=>{e.persistenceController.cancel()}),document.getElementById("cancel-migration")?.addEventListener("click",()=>{e.persistenceController.cancel()}),document.getElementById("validate-migration")?.addEventListener("click",()=>{e.persistenceController.validateDraft().catch(e.showError)}),document.querySelectorAll("[data-migration-field]").forEach(t=>{const s=n=>{const a=t.dataset.migrationField;if(a&&a in(e.persistenceController.viewState().targetDraft||{})){const i=!!e.persistenceController.viewState().migrationPlan;e.persistenceController.updateDraft(a,t.value,{render:n}),!n&&i&&as()}};t.addEventListener("input",()=>s(!1)),t.addEventListener("change",()=>s(!0))}),document.getElementById("settings-delete-source")?.addEventListener("change",t=>{e.persistenceController.setDeleteSource(t.currentTarget.checked)}),document.getElementById("confirm-migration")?.addEventListener("click",()=>{e.persistenceController.apply().catch(e.showError)})}function as(){const e=document.getElementById("confirm-migration");e&&(e.disabled=!0);const t=document.querySelector(".settings-migration-plan");if(!t)return;const s=t.querySelector(".material-symbols-rounded"),n=t.querySelector("strong"),a=t.querySelector("small");s&&(s.textContent="rule"),n&&(n.textContent="Dry run changed"),a&&(a.textContent="Validate the dry run again before applying migration."),t.querySelector(".settings-migration-collections")?.remove()}function is(e){let t=null,s=null,n="",a=null,i=null,r=null,o=!1;function p(){return{deleteSourceAfterMigration:o,migrationPlan:a,migrationProgress:r,migrationResult:i,migrationTarget:t,persistence:e.getPersistence(),targetDraft:s}}async function g(l){const c=e.getPersistence();if(!c||c.active_adapter.kind===l){M();return}t=l,s=rs(l,c),n="",a=null,o=!1,r=null,e.setNotice(null),e.render()}function k(l,c,b={}){s&&(s={...s,[l]:c},a=null,n="",r=null,b.render!==!1&&e.render())}function A(l){o=l,e.render()}function M(){t=null,s=null,a=null,n="",r=null,e.render()}async function R(){if(!(!s||!t)){r={target:t,phase:"validating",percent:10,title:`Dry run to ${t.toUpperCase()}`,detail:"Validating target adapter and collection copy plan before applying changes."},e.setNotice(null),e.render();try{const l=te(s);a=await Ke(l),n=ce(l)}catch(l){throw r=null,a=null,n="",l}r=null,a.same_adapter&&e.setNotice({tone:"info",message:"The selected persistence adapter is already active."}),e.render()}}async function q(){if(!s||!t)return;const l=te(s),c=ce(l);if(!a||n!==c){await R();return}if(a.same_adapter)return;r={target:t,phase:"applying",percent:38,title:`Migration to ${t.toUpperCase()}`,detail:"Copying the validated control-plane plan to the target adapter."},e.setNotice(null),e.render();try{i=await Ve({...l,delete_source:o,restart_backend:!0})}catch(y){throw r={target:t,phase:"failed",percent:100,title:"Migration failed",detail:y instanceof Error?y.message:"Unable to apply migration."},y}const b=t;t=null,s=null,a=null,n="",r={target:b,phase:"restarting",percent:68,title:"Restart backend",detail:i.backend_restart?.detail||"Backend restart scheduled."},e.render(),await O(b)}async function O(l){const c=Date.now(),b=9e4;for(;Date.now()-c<b;){r={target:l,phase:"polling",percent:84,title:"Verifying cutover",detail:"Waiting for the backend to become healthy with the new adapter."},e.render();const y=await e.requestPersistenceStatusQuiet();if(y?.active_adapter.kind===l){e.setPersistence(y);const u=i?.source_cleanup?.scheduled===!0;r={target:l,phase:"complete",percent:100,title:"Migration complete",detail:u?`Active adapter: ${l.toUpperCase()}. Source cleanup is scheduled after health check.`:`Active adapter: ${l.toUpperCase()}. Source storage was preserved.`},e.setNotice({tone:"success",message:`Migration to ${l.toUpperCase()} complete.`}),e.render();return}await new Promise(u=>window.setTimeout(u,1500))}r={target:l,phase:"failed",percent:100,title:"Verification not completed",detail:"The backend did not confirm the new adapter before the timeout. Check service health and logs."},e.setNotice({tone:"error",message:"Migration not confirmed before the timeout."}),e.render()}return{apply:q,cancel:M,prepare:g,setDeleteSource:A,updateDraft:k,validateDraft:R,viewState:p}}function rs(e,t){const s=t.active_adapter;return{kind:e,json_root:s.json_root||"data/control-plane/json",mongodb_uri:s.mongo_uri||"mongodb://127.0.0.1:27017/maverick",mongodb_database:s.mongo_database||"maverick",mongodb_username:s.mongo_username||"",mongodb_password_ref:s.mongo_password_ref||""}}function te(e){return{kind:e.kind,json_root:e.json_root.trim()||"data/control-plane/json",mongodb_uri:e.mongodb_uri.trim(),mongodb_database:e.mongodb_database.trim()||"maverick",mongodb_username:e.mongodb_username?.trim()||void 0,mongodb_password_ref:e.mongodb_password_ref?.trim()||void 0}}function ce(e){return JSON.stringify(te(e))}function os(e){return cs(e)}function ds(e){const{deleteSourceAfterMigration:t,migrationPlan:s,migrationProgress:n,migrationTarget:a,persistence:i}=e;if(!a||!i)return"";const r=i.active_adapter.kind.toUpperCase(),o=a.toUpperCase(),p=!!(n&&!["complete","failed"].includes(n.phase)),g=!!(s&&!s.same_adapter&&!p);return`<div class="settings-modal-backdrop" role="presentation">
    <section class="settings-modal" role="dialog" aria-modal="true" aria-labelledby="adapter-migration-title">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Confirm migration</p>
          <h2 id="adapter-migration-title">${r} → ${o}</h2>
        </div>
        <button type="button" class="settings-icon-button" id="close-migration-modal" aria-label="Close" ${p?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">close</span>
        </button>
      </div>
      ${s?ms(s):gs(n)}
      ${ls(e)}
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
        <button type="button" class="${t?"settings-danger":"settings-secondary"}" id="confirm-migration" ${g?"":"disabled"}>
          <span class="material-symbols-rounded" aria-hidden="true">sync_alt</span>
          ${t?"Apply and schedule cleanup":"Apply migration"}
        </button>
      </div>
    </section>
  </div>`}function ls(e){const t=e.targetDraft;if(!t)return"";const s=!!(e.migrationProgress&&!["complete","failed"].includes(e.migrationProgress.phase));return`<div class="settings-migration-target">
    <label class="settings-platform-field">
      <span>JSON root</span>
      <input data-migration-field="json_root" value="${_(t.json_root)}" ${s?"disabled":""} />
    </label>
    ${t.kind==="mongo"?`<label class="settings-platform-field">
          <span>Mongo URI</span>
          <input data-migration-field="mongodb_uri" value="${_(t.mongodb_uri)}" ${s?"disabled":""} />
        </label>
        <label class="settings-platform-field">
          <span>Mongo database</span>
          <input data-migration-field="mongodb_database" value="${_(t.mongodb_database)}" ${s?"disabled":""} />
        </label>
        <label class="settings-platform-field">
          <span>Mongo username</span>
          <input data-migration-field="mongodb_username" value="${_(t.mongodb_username||"")}" ${s?"disabled":""} />
        </label>
        <label class="settings-platform-field">
          <span>Password secret ref</span>
          <input data-migration-field="mongodb_password_ref" value="${_(t.mongodb_password_ref||"")}" ${s?"disabled":""} />
        </label>`:""}
  </div>`}function cs(e){const{migrationProgress:t,migrationResult:s,persistence:n}=e;if(!n)return`<section class="settings-card settings-persistence">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Persistence</p>
          <h2>Control plane adapter</h2>
        </div>
        <span class="settings-pill settings-pill-muted">offline</span>
      </div>
      <p class="settings-card-copy">The core persistence surfaces are not available in the active backend.</p>
    </section>`;const a=n.active_adapter,i=n.collections.reduce((g,k)=>g+k.count,0),r=a.kind==="json",o=a.kind==="mongo",p=t&&!["complete","failed"].includes(t.phase);return`<section class="settings-card settings-persistence">
    <div class="settings-heading">
      <div>
        <p class="settings-kicker">Persistence</p>
        <h2>Control plane adapter</h2>
      </div>
      <span class="settings-pill">${i} documents</span>
    </div>
    <div class="settings-adapter-cards">
      <button type="button" class="settings-adapter-card ${r?"is-active":""}" ${r||p?"disabled":'data-adapter-target="json"'}>
        <span class="settings-adapter-card-icon material-symbols-rounded" aria-hidden="true">${r?"check_circle":"database"}</span>
        <span>
          <strong>JSON</strong>
          <small>${d(r?a.json_root:"data/control-plane/json")}</small>
        </span>
        <em>${r?"Current":"Review migration"}</em>
      </button>
      <button type="button" class="settings-adapter-card ${o?"is-active":""}" ${o||p?"disabled":'data-adapter-target="mongo"'}>
        <span class="settings-adapter-card-icon material-symbols-rounded" aria-hidden="true">${o?"check_circle":"database"}</span>
        <span>
          <strong>Mongo</strong>
          <small>${d(o?a.mongo_database:"mongodb://127.0.0.1:27017/maverick")}</small>
        </span>
        <em>${o?"Current":"Review migration"}</em>
      </button>
    </div>
    ${ps(t)}
    ${us(s)}
  </section>`}function ps(e){return e?`<div class="settings-migration-progress ${e.phase==="failed"?"is-failed":""} ${e.phase==="complete"?"is-complete":""}">
    <div class="settings-migration-progress-heading">
      <span class="material-symbols-rounded" aria-hidden="true">${e.phase==="complete"?"check_circle":e.phase==="failed"?"error":"sync"}</span>
      <span>
        <strong>${d(e.title)}</strong>
        <small>${d(e.detail)}</small>
      </span>
      <em>${e.percent}%</em>
    </div>
    <div class="settings-progress-track" aria-label="Migration progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${e.percent}">
      <span style="width: ${e.percent}%"></span>
    </div>
  </div>`:""}function us(e){return e?`<div class="settings-migration-result">
    <span class="material-symbols-rounded" aria-hidden="true">task_alt</span>
    <span>
      <strong>Last migration</strong>
      <small>${e.collections.reduce((s,n)=>s+n.count,0)} documents · target ${d(e.target_adapter.kind)} · cleanup ${e.source_cleanup?.scheduled?"scheduled":"not requested"}</small>
    </span>
  </div>`:""}function gs(e){return`<div class="settings-migration-plan">
    <span class="material-symbols-rounded" aria-hidden="true">rule</span>
    <span>
      <strong>${d(e?.title||"Dry run not validated")}</strong>
      <small>${d(e?.detail||"Adjust the target fields, then validate the dry run before applying migration.")}</small>
    </span>
  </div>`}function ms(e){const t=e.collections.reduce((n,a)=>n+a.count,0),s=e.target_collections.reduce((n,a)=>n+a.count,0);return`<div class="settings-migration-plan">
    <span class="material-symbols-rounded" aria-hidden="true">${e.same_adapter?"block":"rule"}</span>
    <span>
      <strong>${e.same_adapter?"Target already active":"Dry run complete"}</strong>
      <small>${t} source documents · ${s} target documents before copy · env ${d(e.env_file)}</small>
    </span>
    <div class="settings-migration-collections">
      ${e.collections.map(n=>`<span><strong>${d(n.name)}</strong><small>${n.count}</small></span>`).join("")}
    </div>
  </div>`}async function fs(e){const t=e.settings?.provider.active_provider?.provider_id;if(!t||!e.state.draftModelId){e.state.providerError="Provider not loaded.",e.render();return}e.state.isSavingProvider=!0,e.state.providerError="",e.render();try{await Fe({provider_id:t,model_id:e.state.draftModelId,model_reasoning_effort:e.state.draftReasoningEffort||null});const s=await V();e.setSettings(s),Q(e.state,s),e.setNotice({tone:"success",message:"Provider settings updated."})}catch(s){e.state.providerError=s instanceof Error?s.message:"Unable to update provider settings."}finally{e.state.isSavingProvider=!1,e.render()}}async function vs(e){const t=e.settings?.provider.hosted_text?.active_provider?.provider_id;if(!t||!e.state.hostedDraftModelId){e.state.hostedProviderErrorModelId=e.state.hostedDraftModelId,e.state.hostedProviderError="Hosted provider not loaded.",e.render();return}e.state.isSavingHostedProvider=!0,e.state.hostedProviderError="",e.state.hostedProviderErrorModelId=e.state.hostedDraftModelId,e.render();try{await ze({provider_id:t,model_id:e.state.hostedDraftModelId,openrouter_provider_routing:_e(e.state,e.state.hostedDraftModelId)});const s=await V();e.setSettings(s),Q(e.state,s),e.setNotice({tone:"success",message:"Hosted model settings updated."})}catch(s){e.state.hostedProviderErrorModelId=e.state.hostedDraftModelId,e.state.hostedProviderError=s instanceof Error?s.message:"Unable to update hosted model settings."}finally{e.state.isSavingHostedProvider=!1,e.render()}}function hs({pendingDeleteUserId:e,selectedUser:t,users:s}){return`<form class="settings-card settings-create" id="create-user">
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
    ${Pe(s,t)}
    ${t?`<div class="settings-profile-row">
          <form class="settings-card settings-detail" id="edit-user">
            <div class="settings-heading">
              <div>
                <p class="settings-kicker">Selected user</p>
                <h2>${d(t.display_name||t.username)}</h2>
              </div>
              <span class="settings-pill">${t.is_active?"active":"disabled"}</span>
            </div>
            <div class="settings-grid">
              <label>Name<input name="display_name" value="${_(t.display_name||"")}" /></label>
              <label>Email<input name="email" type="email" value="${_(t.email||"")}" /></label>
              <label>Platform role<select name="platform_role">
                <option value="member" ${t.platform_role==="member"?"selected":""}>Member</option>
                <option value="admin" ${t.platform_role==="admin"?"selected":""}>Admin</option>
              </select></label>
              <label>Account type<select name="account_type">
                <option value="standard" ${t.account_type==="standard"?"selected":""}>Standard</option>
                <option value="facilitated" ${t.account_type==="facilitated"?"selected":""}>Facilitated</option>
              </select></label>
            </div>
            <label class="settings-toggle"><input name="is_active" type="checkbox" ${t.is_active?"checked":""} /> Account active</label>
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
              ${e===t.user_id?"Confirm delete":"Delete user"}
            </button>
          </form>
        </div>`:'<section class="settings-card"><h2>No users</h2></section>'}`}function _s({selectedUser:e,users:t,workspaces:s}){return`${Pe(t,e)}
    ${e?`<section class="settings-card">
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
          <div class="settings-memberships">${bs(e,s)}</div>
        </section>`:'<section class="settings-card"><h2>No users</h2></section>'}`}function Pe(e,t){return e.length?`<section class="settings-card settings-user-picker">
    <div>
      <p class="settings-kicker">User directory</p>
      <h2>${d(t?t.display_name||t.username:"Select user")}</h2>
      <p class="settings-card-copy">${e.length} user${e.length===1?"":"s"} available.</p>
    </div>
    <label class="settings-platform-field">
      <span>Selected user</span>
      <select id="selected-user">
        ${e.map(s=>`<option value="${_(s.user_id)}" ${s.user_id===t?.user_id?"selected":""}>${d(s.display_name||s.username)} (${d(s.username)})</option>`).join("")}
      </select>
    </label>
  </section>`:`<section class="settings-card settings-user-picker">
      <div>
        <p class="settings-kicker">User directory</p>
        <h2>No users</h2>
      </div>
      <p class="settings-card-copy">Create a user before editing profile or workspace access settings.</p>
    </section>`}function bs(e,t){return t.map(s=>{const n=e.memberships.find(a=>a.workspace_id===s.workspace_id);return`<label class="settings-membership">
        <input type="checkbox" data-workspace-enabled="${_(s.workspace_id)}" ${n?"checked":""} />
        <span class="settings-membership-icon material-symbols-rounded" aria-hidden="true">workspaces</span>
        <span>
          <strong>${d(s.name)}</strong>
          <small>${d(s.workspace_id)}</small>
        </span>
        <select data-workspace-role="${_(s.workspace_id)}">
          <option value="member" ${n?.role!=="admin"?"selected":""}>Member</option>
          <option value="admin" ${n?.role==="admin"?"selected":""}>Workspace admin</option>
        </select>
      </label>`}).join("")}function ys({workspaceApps:e,workspaces:t}){return`<section class="settings-card">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Workspace apps</p>
          <h2>Installation and visibility</h2>
        </div>
      </div>
      <p class="settings-card-copy">Installed means the app has a workspace binding. Only enabled apps are visible to users and served by the core.</p>
      <div class="settings-app-workspaces">${$s(t,e)}</div>
    </section>`}function $s(e,t){return e.map(s=>{const n=t.filter(r=>r.workspace_id===s.workspace_id),a=n.filter(r=>r.status==="enabled").length,i=n.filter(r=>r.installed).length;return`<details class="settings-app-workspace">
        <summary class="settings-app-workspace-heading">
          <span class="settings-summary-caret material-symbols-rounded" aria-hidden="true">chevron_right</span>
          <span class="settings-app-workspace-icon material-symbols-rounded" aria-hidden="true">deployed_code</span>
          <span>
            <strong>${d(s.name)}</strong>
            <small>${d(s.workspace_id)} · ${a}/${i} enabled</small>
          </span>
        </summary>
        <div class="settings-apps">
          ${n.map(ws).join("")}
        </div>
      </details>`}).join("")}function ws(e){const t=e.status==="enabled",s=e.installed,n=s?e.status:"not installed",a=`${e.workspace_id}:${e.app_id}`;return`<div class="settings-app-row">
    <span class="settings-app-icon material-symbols-rounded" aria-hidden="true">${d(ks(e))}</span>
    <span class="settings-app-copy">
      <strong>${d(e.name)}</strong>
      <small>${d(e.app_id)} · v${d(e.version)} · ${d(n)}</small>
    </span>
    ${s?`<label class="settings-switch">
          <input type="checkbox" data-app-toggle="${_(a)}" ${t?"checked":""} />
          <span>Enabled</span>
        </label>
        <button type="button" class="settings-secondary" data-app-uninstall="${_(a)}">
          <span class="material-symbols-rounded" aria-hidden="true">link_off</span>
          Uninstall
        </button>`:`<button type="button" class="settings-secondary" data-app-install="${_(a)}">
          <span class="material-symbols-rounded" aria-hidden="true">add_link</span>
          Install
        </button>`}
  </div>`}function ks(e){return e.status!=="enabled"?"hide_source":{agents:"smart_toy","app-store":"storefront","base-shell":"dashboard",browser:"language",calendar:"calendar_month",chat:"forum",checklist:"checklist",crm:"contacts","developer-kit":"developer_board","docs-studio":"description","document-generator":"description","dynamic-views":"dashboard_customize","gmail-app":"mail",mail:"mail",memory:"database","maverick-monitor":"monitor_heart",settings:"admin_panel_settings",senses:"sensors",skills:"school",speech:"record_voice_over",storage:"cloud",vault:"key","website-studio":"web_asset"}[e.app_id]||"apps"}let H=[],J=[],F=[],se=null,E=null,S=rt();const Ee=Object.fromEntries(new URLSearchParams(window.location.search).entries());let K=me(Ee)||Ce,I=Ie(Ee),T=!0,N="",P=null,pe="",ue="";const re=is({getPersistence:()=>se,render:()=>$(),requestPersistenceStatusQuiet:Is,setNotice:e=>{P=e},setPersistence:e=>{se=e}}),D=Ft({publishChanged:js,render:()=>$(),setNotice:e=>{P=e}});function Ae(){return H.find(e=>e.user_id===I)||H[0]}function Ie(e){const t=z(e.user_id)||z(e.selected_user_id)||z(e.id);if(t)return t;const s=z(e.app_page),n=/^users\/([^/?#]+)$/.exec(s);if(!n?.[1])return"";try{return decodeURIComponent(n[1])}catch{return n[1]}}function z(e){return typeof e=="string"?e.trim():""}function Ss(e){const t=me(e),s=Ie(e);let n=!1;t&&t!==K&&(K=t,n=!0),s&&s!==I&&(I=s,N="",n=!0),n&&((H.length||T)&&$(),t==="app-links"&&Me())}function Ps(e){e.id===pe||window.parent===window||(pe=e.id,window.parent.postMessage({type:"maverick.app.selection-changed",owner_app_id:"settings",selection:{page_id:e.id}},window.location.origin))}function Es(e){!e||e.user_id===ue||window.parent===window||(ue=e.user_id,window.parent.postMessage({type:"maverick.app.selection-changed",owner_app_id:"settings",selection:{user_id:e.user_id}},window.location.origin))}function Y(){window.parent!==window&&window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"settings",resource:"users"},window.location.origin)}async function As(){try{return await v("/api/admin/persistence")}catch(e){return P={tone:"error",message:e instanceof Error?e.message:"Persistence API unavailable"},null}}async function Is(){try{return await v("/api/admin/persistence")}catch{return null}}async function Ms(){try{return await V()}catch{return null}}async function L(){T=!0,$();try{const[e,t,s,n,a]=await Promise.all([De(),Le(),qe(),As(),Ms()]),i=E?.workspace.workspace_id||"",r=a?.workspace.workspace_id||"";H=e,J=t,F=s,se=n,E=a,i!==r&&D.reset(),Q(S,E),(!I||!H.some(o=>o.user_id===I))&&(I=H[0]?.user_id||"")}finally{T=!1}$(),K==="app-links"&&Me()}async function Me(e=!1){const t=E?.workspace.workspace_id||"";await D.ensureLoaded(t,F,e)}async function Rs(e){const t=new FormData(e);I=(await Qe({username:String(t.get("username")||""),password:String(t.get("password")||""),display_name:String(t.get("display_name")||""),email:String(t.get("email")||""),platform_role:String(t.get("platform_role")||"member")})).user_id,e.reset(),await L(),Y()}async function Cs(e,t){const s=new FormData(e);await Ge(t.user_id,{display_name:String(s.get("display_name")||""),email:String(s.get("email")||""),platform_role:String(s.get("platform_role")||"member"),account_type:String(s.get("account_type")||"standard"),is_active:s.get("is_active")==="on"}),await L(),Y()}async function Hs(e,t){const s=new FormData(e),n=String(s.get("password")||""),a=String(s.get("password_confirmation")||"");if(n!==a)throw new Error("Passwords do not match");await Xe(t.user_id,n),e.reset(),P={tone:"success",message:"Password updated."},$()}async function Ds(e){const t=e.display_name||e.username;if(N!==e.user_id){N=e.user_id,P={tone:"info",message:`Press Delete user again to confirm permanent removal of ${t}.`},$();return}await Ye(e.user_id),I="",N="",P={tone:"success",message:`${t} deleted.`},await L(),Y()}async function Ls(e){const t=J.map(s=>{const n=document.querySelector(`[data-workspace-enabled="${s.workspace_id}"]`),a=document.querySelector(`[data-workspace-role="${s.workspace_id}"]`);return n?.checked?{workspace_id:s.workspace_id,role:a?.value||"member"}:null}).filter(s=>!!s);await Ze(e.user_id,t),await L(),Y()}async function qs(e){await xe(e),D.invalidate(),await L()}async function Os(e,t){await et(e,t),D.invalidate(),await L()}async function Us(e){await tt(e),D.invalidate(),await L()}async function Ts(e,t,s){await D.saveDependencySelection(e,t,s)}async function Ns(e){const t=(e||[]).filter(Boolean);S.cleanupError="",t.length?t.forEach(s=>S.cleaningSessionIds.add(s)):S.clearingAllRuntime=!0,$();try{const s=await We(t.length?t:void 0);Bs(s),E=await V(),Q(S,E),P={tone:"success",message:t.length?"Runtime session cleaned.":"Runtime sessions cleaned."}}catch(s){S.cleanupError=s instanceof Error?s.message:"Unable to clean runtime sessions."}finally{t.forEach(s=>S.cleaningSessionIds.delete(s)),S.clearingAllRuntime=!1,$()}}function Bs(e){e.deleted_threads<=0||window.parent===window||(window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"chat",resource:"threads"},window.location.origin),e.deleted_thread_ids.forEach(t=>{window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"chat",resource:"threads",deleted_thread_id:t},window.location.origin)}))}function js(e,t){window.parent!==window&&window.parent.postMessage({type:"maverick.app.dependencies-changed",app_id:e,status:t.status},window.location.origin)}async function Fs(){if(window.parent&&window.parent!==window){window.parent.postMessage({type:"maverick.shell.logout"},window.location.origin);return}await Je(),window.location.href="/"}function zs(e,t){if(e.id==="users")return hs({pendingDeleteUserId:N,selectedUser:t,users:H});if(e.id==="workspace-access")return _s({selectedUser:t,users:H,workspaces:J});if(e.id==="workspace-apps")return ys({workspaceApps:F,workspaces:J});if(e.id==="app-links"){const s=D.viewState();return Wt({appRegistry:s.appRegistry,dependencies:s.dependencies,error:s.error,isLoading:s.isLoading,loadErrors:s.loadErrors,savingKeys:s.savingKeys,workspaceApps:F})}return e.id==="platform-settings"?Ws():os(re.viewState())}function Ws(){return ct(E,S)}function $(){const e=document.getElementById("app"),t=T?void 0:Ae(),s=He(K);e&&(e.innerHTML=`<main class="settings-shell">
    <section class="settings-main">
      <div class="settings-content">
        ${T?Mt(s):`<header class="detail-header">
          <div class="detail-title-block">
            <h2>${d(s.title)}</h2>
            <span class="detail-title-separator" aria-hidden="true"></span>
            <p>${d(s.summary)}</p>
          </div>
        </header>
        ${Ks()}
        ${zs(s,t)}`}
      </div>
    </section>
    ${ds(re.viewState())}
  </main>`,Js(),Ps(s),T||Es(t))}function Js(){es({clearRuntimeSessionsFromPanel:Ns,createUser:Rs,deleteSelectedUser:Ds,dismissNotice:()=>{P=null,$()},installWorkspaceApp:qs,logoutFromSettings:Fs,onHostedProviderRoutingChanged:(e,t,s)=>{lt(S,E,e,t,s),$()},onProviderModelChanged:e=>{ot(S,E,e),$()},onProviderReasoningChanged:e=>{S.draftReasoningEffort=e,S.providerError="",$()},persistenceController:re,render:$,resetSelectedUserPassword:Hs,saveDependencySelection:Ts,saveHostedProviderSettingsFromPanel:e=>(e&&dt(S,E,e),vs(ge())),saveProviderSettingsFromPanel:()=>fs(ge()),selectedUser:Ae,selectUser:e=>{I=e,N="",$()},setWorkspaceAppStatus:Os,showError:Re,uninstallWorkspaceApp:Us,updateMemberships:Ls,updateSelectedUser:Cs,workspaceApps:()=>F,appDependencies:()=>D.viewState().dependencies})}function ge(){return{render:$,setNotice:e=>{P=e},setSettings:e=>{E=e},settings:E,state:S}}function Re(e){P={tone:"error",message:e instanceof Error?e.message:"Unexpected error"},$()}function Ks(){return P?`<div class="settings-notice settings-notice-${P.tone}">
    <span class="material-symbols-rounded" aria-hidden="true">${P.tone==="error"?"error":P.tone==="success"?"task_alt":"info"}</span>
    <span>${d(P.message)}</span>
    <button type="button" class="settings-icon-button" id="dismiss-notice" aria-label="Close">
      <span class="material-symbols-rounded" aria-hidden="true">close</span>
    </button>
  </div>`:""}window.addEventListener("message",e=>{if(e.origin!==window.location.origin||!e.data||typeof e.data!="object")return;const t=e.data;t.type==="maverick.app.navigate"&&(!t.app_id||t.app_id==="settings")&&Ss(t.params||{})});window.parent?.postMessage({type:"maverick.app.ready",app_id:"settings"},window.location.origin);L().catch(Re);
