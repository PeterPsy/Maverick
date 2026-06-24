import{s as he,D as Le,a as Oe}from"./pages-BZUBskpf.js";async function v(e,t={}){const s=await fetch(e,{credentials:"same-origin",headers:{"Content-Type":"application/json",...t.headers||{}},...t}),n=await s.json();if(!s.ok)throw new Error(n.detail||n.error||`Request failed ${s.status}`);return n}async function qe(){return(await v("/api/admin/users")).items}async function Ue(){return(await v("/api/admin/workspaces")).items}async function Te(){return(await v("/api/admin/workspace-apps")).items}function le(e,t=""){return typeof e=="string"?e:t}function Ne(e){return Array.isArray(e)?e.filter(t=>typeof t=="string"):[]}function Be(e){if(!e||typeof e!="object"||Array.isArray(e))return null;const t=e,s=t.kind==="image"||t.kind==="glyph"?t.kind:null;return s&&typeof t.value=="string"?{kind:s,value:t.value}:null}function je(e){const t=e&&typeof e=="object"&&!Array.isArray(e)?e:{},s=le(t.app_id);return{app_id:s,name:le(t.name,s||"Unnamed app"),views:Ne(t.views),logo:Be(t.logo)}}async function Fe(){return((await v("/api/apps")).items||[]).map(je).filter(t=>t.app_id)}function ze(e){const t=new URLSearchParams({consumer_app_id:e});return v(`/api/apps/dependencies?${t.toString()}`)}function We(e,t,s){return v("/api/apps/dependencies",{method:"POST",body:JSON.stringify({consumer_app_id:e,alias:t,provider_app_ids:s})})}function z(){return v("/api/settings/platform")}function Je(e){return v("/api/providers/active",{method:"POST",body:JSON.stringify(e)})}function Ke(e){return v("/api/providers/hosted/selection",{method:"POST",body:JSON.stringify(e)})}function Ve(e){return v("/api/providers/speech/selection",{method:"POST",body:JSON.stringify(e)})}function Qe(e,t="settings_runtime_sessions_cleared"){return v("/api/settings/runtime-sessions/clear",{method:"POST",body:JSON.stringify({session_ids:e,reason:t})})}function Ge(){return v("/api/auth/logout",{method:"POST"})}function Xe(e){return v("/api/admin/persistence/migrations/dry-run",{method:"POST",body:JSON.stringify(e)})}function Ye(e){return v("/api/admin/persistence/migrations/apply",{method:"POST",body:JSON.stringify(e)})}function Ze(e){return v("/api/admin/users",{method:"POST",body:JSON.stringify(e)})}function xe(e,t){return v(`/api/admin/users/${encodeURIComponent(e)}`,{method:"PATCH",body:JSON.stringify(t)})}function et(e,t){return v(`/api/admin/users/${encodeURIComponent(e)}/password`,{method:"POST",body:JSON.stringify({password:t})})}function tt(e){return v(`/api/admin/users/${encodeURIComponent(e)}`,{method:"DELETE"})}function st(e,t){return v(`/api/admin/users/${encodeURIComponent(e)}/workspaces`,{method:"PUT",body:JSON.stringify({memberships:t})})}function nt(e){return v(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"POST",body:JSON.stringify({source_id:e.source_id,enabled:!0})})}function at(e,t){return v(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"PATCH",body:JSON.stringify({status:t?"enabled":"disabled"})})}function it(e){return v(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"DELETE",body:JSON.stringify({})})}function se(e){const t=e?.provider.active_provider,s=e?.provider.model_settings;return _e(t,s,ie(e))}function ie(e){const t=e?.provider.active_provider,s=e?.provider.model_settings;return be(t,s)}function rt(e){const t=e?.provider.hosted_text?.active_provider||null,s=e?.provider.hosted_text?.model_settings||null;return _e(t,s,re(e))}function re(e){const t=e?.provider.hosted_text?.active_provider||null,s=e?.provider.hosted_text?.model_settings||null;return be(t,s)}function _e(e,t,s){const n=t?.selected_model_id||e?.default_model_family||"",a=s.find(i=>i.model_id===n)||null;return{modelId:n,reasoningEffort:t?.selected_reasoning_effort||ye(a)}}function be(e,t){const s=t?.selected_model_id||e?.default_model_family||"",n=x(t?.available_models).length?x(t?.available_models):x(e?.model_options);return(n.length?n:s?[dt(s,t?.selected_reasoning_effort||"")]:[]).map(ot)}function ye(e){return e?.default_reasoning_effort||e?.supported_reasoning_efforts[0]?.effort||""}function x(e){return(e||[]).filter(t=>t.model_id)}function ot(e){return e.supported_reasoning_efforts.length||!e.default_reasoning_effort?e:{...e,supported_reasoning_efforts:[{effort:e.default_reasoning_effort,label:e.default_reasoning_effort,description:null}]}}function dt(e,t){return{model_id:e,label:e,description:null,default_reasoning_effort:t||null,supported_reasoning_efforts:t?[{effort:t,label:t,description:null}]:[]}}const lt=new Set(["created","running","stopping"]);function ct(){return{cleanupError:"",clearingAllRuntime:!1,cleaningSessionIds:new Set,draftModelId:"",draftReasoningEffort:"",hostedDraftModelId:"",hostedProviderError:"",hostedProviderErrorModelId:"",hostedRoutingDraftsByModel:{},isSavingHostedProvider:!1,isSavingProvider:!1,isSavingSpeechProvider:!1,providerError:"",speechAudioModelId:"",speechConversationModelId:"",speechProviderError:""}}function W(e,t){const{modelId:s,reasoningEffort:n}=se(t),{modelId:a}=rt(t),i=vt(t),r=new Set(re(t).map(o=>o.model_id).filter(Boolean));a&&r.add(a),e.draftModelId=s,e.draftReasoningEffort=n,e.hostedDraftModelId=a,e.speechAudioModelId=i.audioModelId,e.speechConversationModelId=i.conversationModelId,e.hostedRoutingDraftsByModel=Object.fromEntries(Array.from(r).map(o=>[o,Y(X(t,o))]))}function pt(e,t,s){const n=ie(t).find(a=>a.model_id===s)||null;e.draftModelId=s,e.draftReasoningEffort=ye(n),e.providerError=""}function ut(e,t,s){e.hostedDraftModelId=s,ke(e,t,s),e.hostedProviderError="",e.hostedProviderErrorModelId=""}function gt(e,t){e.speechAudioModelId=t,e.speechProviderError=""}function mt(e,t){e.speechConversationModelId=t,e.speechProviderError=""}function ft(e,t,s,n,a){if(!s)return;const i=ke(e,t,s);e.hostedDraftModelId=s,n==="mode"&&typeof a=="string"&&["auto","prefer","only","ignore"].includes(a)?i.mode=a:n==="provider_id"&&typeof a=="string"?i.providerId=a:n==="allow_fallbacks"&&typeof a=="boolean"?i.allowFallbacks=a:n==="require_parameters"&&typeof a=="boolean"?i.requireParameters=a:n==="sort"&&typeof a=="string"&&["","price","throughput","latency"].includes(a)?i.sort=a:n==="data_collection"&&typeof a=="string"&&["","allow","deny"].includes(a)?i.dataCollection=a:n==="quantization"&&typeof a=="string"&&(i.quantization=a),e.hostedProviderError="",e.hostedProviderErrorModelId=""}function $e(e,t=e.hostedDraftModelId){const s=e.hostedRoutingDraftsByModel[t]||Rt();return{mode:s.mode,provider_id:s.providerId||void 0,allow_fallbacks:s.allowFallbacks,require_parameters:s.requireParameters,sort:s.sort,data_collection:s.dataCollection,quantizations:s.quantization?[s.quantization]:[]}}function vt(e){const t=e?.provider.speech_stt||null,s=t?.active_provider||t?.available_providers?.find(i=>i.provider_id==="deepgram")||null,n=K(t,s,"prerecorded_transcription"),a=K(t,s,"conversational_streaming");return{audioModelId:t?.model_settings?.audio_transcription_model_id||n.find(i=>i.model_id==="nova-3")?.model_id||n[0]?.model_id||"nova-3",conversationModelId:t?.model_settings?.conversation_model_id||a.find(i=>i.model_id==="flux-general-multi")?.model_id||a[0]?.model_id||"flux-general-multi"}}function ht(e,t){if(!e)return`<section class="settings-card settings-platform">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Settings</p>
          <h2>Platform settings</h2>
        </div>
      </div>
      <p class="settings-card-copy">Platform settings are not available from the active backend.</p>
    </section>`;const s=e.provider.active_provider,n=e.provider.hosted_text?.active_provider||null,a=e.provider.speech_stt||null,i=Mt(e),r=i.filter(_=>lt.has(_.status)),o=e.runtime.cleanup_allowed??!1,d=e.runtime.cleanup_scope||"none",m=ie(e),w=re(e),P=se(e).modelId,M=se(e).reasoningEffort,R=(m.find(_=>_.model_id===t.draftModelId)||m[0]||null)?.supported_reasoning_efforts||[],I=At(e,t),c=!!(s&&t.draftModelId&&!t.isSavingProvider&&(t.draftModelId!==P||t.draftReasoningEffort!==M));return`${_t(e)}
    ${bt(s,m,R,c,r.length,i.length,I,w,n,a,e,t)}
    ${Et(i,o,d,t)}`}function _t(e){return`<section class="settings-card settings-platform settings-user-settings-card">
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
        <h3>${p(e.user.display_name||e.user.username||"Unavailable")}</h3>
        <p>${p(e.user.platform_role||"member")} · ${p(e.workspace.name||e.workspace.workspace_id)}</p>
        <button type="button" class="settings-secondary settings-platform-logout" id="settings-logout">
          <span class="material-symbols-rounded" aria-hidden="true">logout</span>
          Logout
        </button>
      </div>
    </article>
  </section>`}function bt(e,t,s,n,a,i,r,o,d,m,w,P){return`<section class="settings-card settings-platform settings-model-settings-card">
    <div class="settings-heading settings-platform-heading">
      <div>
        <p class="settings-kicker">Models</p>
        <h2>Model settings</h2>
      </div>
    </div>
    <div class="settings-platform-provider-forms">
      ${$t(e,t,s,n,a,i,!r,P)}
      ${wt(o,r,d,w,P)}
      ${Pt(m,P)}
    </div>
  </section>`}function yt(e){document.getElementById("settings-provider-model")?.addEventListener("change",t=>{e.onProviderModelChanged(t.currentTarget.value)}),document.getElementById("settings-provider-reasoning")?.addEventListener("change",t=>{e.onProviderReasoningChanged(t.currentTarget.value)}),document.getElementById("settings-speech-audio-model")?.addEventListener("change",t=>{e.onSpeechAudioModelChanged(t.currentTarget.value)}),document.getElementById("settings-speech-conversation-model")?.addEventListener("change",t=>{e.onSpeechConversationModelChanged(t.currentTarget.value)}),document.getElementById("settings-speech-save")?.addEventListener("click",()=>{e.onSaveSpeechProviderSettings()}),document.querySelectorAll("[data-settings-model-accordion]").forEach(t=>{t.addEventListener("toggle",()=>{t.open&&document.querySelectorAll("[data-settings-model-accordion]").forEach(s=>{s!==t&&(s.open=!1)})})}),document.querySelectorAll("[data-openrouter-routing]").forEach(t=>{t.addEventListener("change",s=>{const n=s.currentTarget,a=n.dataset.hostedModelId||n.closest("[data-hosted-model-accordion]")?.dataset.hostedModelAccordion||"";e.onHostedProviderRoutingChanged(a,n.dataset.openrouterRouting||"",n instanceof HTMLInputElement&&n.type==="checkbox"?n.checked:n.value)})}),document.getElementById("settings-save-provider")?.addEventListener("click",e.onSaveProviderSettings),document.querySelectorAll("[data-hosted-provider-save]").forEach(t=>{t.addEventListener("click",()=>e.onSaveHostedProviderSettings(t.dataset.hostedProviderSave||""))}),document.getElementById("settings-logout")?.addEventListener("click",e.onLogout),document.getElementById("settings-clear-all-runtime")?.addEventListener("click",e.onClearAllRuntimeSessions),document.querySelectorAll("[data-runtime-clear]").forEach(t=>{t.addEventListener("click",()=>e.onClearRuntimeSession(t.dataset.runtimeClear||""))})}function $t(e,t,s,n,a,i,r,o){return`<details class="settings-model-accordion settings-agentic-provider-accordion" data-settings-model-accordion="agentic-provider" data-agentic-provider-accordion ${r?"open":""}>
    <summary class="settings-model-trigger">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">memory</span>
      <span class="settings-model-copy">
        <span class="settings-model-kicker">
          <span class="settings-kicker">Agentic provider</span>
        </span>
        <strong>${p(e?.label||"Provider not loaded")}</strong>
        <small>${p(o.draftModelId||"model")} · ${p(o.draftReasoningEffort||"reasoning")} · Codex tools/filesystem/MCP · ${a} active / ${i} in scope</small>
      </span>
      <span class="settings-model-chevron material-symbols-rounded" aria-hidden="true">expand_more</span>
    </summary>
    <div class="settings-model-content settings-agentic-provider-content">
    <label class="settings-platform-field">
      <span>Model</span>
      <select id="settings-provider-model" ${!t.length||o.isSavingProvider?"disabled":""}>
        ${t.map(d=>`<option value="${b(d.model_id)}" ${d.model_id===o.draftModelId?"selected":""}>${p(d.label||d.model_id)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Reasoning</span>
      <select id="settings-provider-reasoning" ${!s.length||o.isSavingProvider?"disabled":""}>
        ${s.map(d=>`<option value="${b(d.effort)}" ${d.effort===o.draftReasoningEffort?"selected":""}>${p(d.label||d.effort)}</option>`).join("")}
      </select>
    </label>
    <button type="button" id="settings-save-provider" ${n?"":"disabled"}>
      <span class="material-symbols-rounded" aria-hidden="true">${o.isSavingProvider?"sync":"save"}</span>
      ${o.isSavingProvider?"Saving":"Save model"}
    </button>
    ${o.providerError?`<p class="settings-platform-error">${p(o.providerError)}</p>`:""}
    </div>
  </details>`}function wt(e,t,s,n,a){const i=!!s;return`<div class="settings-hosted-models">
    <div class="settings-platform-form-heading settings-hosted-models-heading">
      <span class="material-symbols-rounded" aria-hidden="true">route</span>
      <span>
        <strong>Hosted OpenRouter models</strong>
        <small>Settings manages model defaults and upstream routing; Chat only uses text-output fast models.</small>
      </span>
    </div>
    ${e.length?e.map(r=>kt(r,t,s,n,a)).join(""):'<p class="settings-card-copy settings-platform-note">No hosted models are available from the active hosted provider.</p>'}
    ${i?"":'<p class="settings-card-copy settings-platform-note">Activate a hosted text provider before selecting a fast model.</p>'}
  </div>`}function kt(e,t,s,n,a){const i=e.model_id,r=Ct(a,n,i),o=e.upstream_provider_options||[],d=Array.from(new Set(o.map(u=>u.quantization||"").filter(Boolean))),m=!!s,w=a.isSavingHostedProvider&&a.hostedDraftModelId===i,P=!!(m&&i&&!a.isSavingHostedProvider&&we(a,n,i)),M=St(e),A=M?"Hosted chat / fast model":"Hosted speech model",R=M?"plain hosted chat capable · runtime engine remains Codex":"speech synthesis metadata · not used by plain hosted chat",I=M?"bolt":"record_voice_over",c=i===t,_=s?.label||s?.provider_id||"Hosted provider";return`<details class="settings-model-accordion settings-hosted-model-accordion" data-settings-model-accordion="hosted:${b(i)}" data-hosted-model-accordion="${b(i)}" ${c?"open":""}>
    <summary class="settings-model-trigger">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">${I}</span>
      <span class="settings-model-copy">
        <span class="settings-model-kicker">
          <span class="settings-kicker">${A}</span>
          <span class="settings-pill">Active</span>
        </span>
        <strong>${p(e.label||i)} - ${p(_)}</strong>
        <small>${p(i||"model not selected")} · ${R}</small>
      </span>
      <span class="settings-model-chevron material-symbols-rounded" aria-hidden="true">expand_more</span>
    </summary>
    <div class="settings-model-content settings-hosted-model-content">
      <div class="settings-platform-field settings-platform-field-wide">
        <span>Model</span>
        <code class="settings-model-code">${p(i||"model not selected")}</code>
      </div>
    <label class="settings-platform-field">
      <span>OpenRouter upstream</span>
      <select data-openrouter-routing="mode" data-hosted-model-id="${b(i)}" ${!m||!o.length||a.isSavingHostedProvider?"disabled":""}>
        ${[["auto","Auto"],["prefer","Prefer selected"],["only","Only selected"],["ignore","Ignore selected"]].map(([u,h])=>`<option value="${b(u)}" ${u===r.mode?"selected":""}>${p(h)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Upstream provider</span>
      <select data-openrouter-routing="provider_id" data-hosted-model-id="${b(i)}" ${!m||!o.length||r.mode==="auto"||a.isSavingHostedProvider?"disabled":""}>
        <option value="">Select provider</option>
        ${o.map(u=>`<option value="${b(String(u.provider_id||u.tag||""))}" ${(u.provider_id||u.tag)===r.providerId?"selected":""}>${p(u.label||u.provider_id||u.tag||"Provider")}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Sort</span>
      <select data-openrouter-routing="sort" data-hosted-model-id="${b(i)}" ${!m||a.isSavingHostedProvider?"disabled":""}>
        ${[["","OpenRouter default"],["price","Price"],["throughput","Throughput"],["latency","Latency"]].map(([u,h])=>`<option value="${b(u)}" ${u===r.sort?"selected":""}>${p(h)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Data collection</span>
      <select data-openrouter-routing="data_collection" data-hosted-model-id="${b(i)}" ${!m||a.isSavingHostedProvider?"disabled":""}>
        ${[["","OpenRouter default"],["allow","Allow"],["deny","Deny"]].map(([u,h])=>`<option value="${b(u)}" ${u===r.dataCollection?"selected":""}>${p(h)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Quantization</span>
      <select data-openrouter-routing="quantization" data-hosted-model-id="${b(i)}" ${!m||!d.length||a.isSavingHostedProvider?"disabled":""}>
        <option value="">Any</option>
        ${d.map(u=>`<option value="${b(u)}" ${u===r.quantization?"selected":""}>${p(u)}</option>`).join("")}
      </select>
    </label>
    <div class="settings-platform-checks">
      <label><input type="checkbox" data-openrouter-routing="allow_fallbacks" data-hosted-model-id="${b(i)}" ${r.allowFallbacks?"checked":""} ${!m||a.isSavingHostedProvider?"disabled":""}> Allow OpenRouter fallback</label>
      <label><input type="checkbox" data-openrouter-routing="require_parameters" data-hosted-model-id="${b(i)}" ${r.requireParameters?"checked":""} ${!m||a.isSavingHostedProvider?"disabled":""}> Require supported parameters</label>
    </div>
    <button type="button" data-hosted-provider-save="${b(i)}" ${P?"":"disabled"}>
      <span class="material-symbols-rounded" aria-hidden="true">${w?"sync":"save"}</span>
      ${w?"Saving":"Save hosted model"}
    </button>
    ${a.hostedProviderError&&a.hostedProviderErrorModelId===i?`<p class="settings-platform-error">${p(a.hostedProviderError)}</p>`:""}
    </div>
  </details>`}function St(e){const t=e.output_modalities||[];return!t.length||t.includes("text")}function Pt(e,t){const s=e?.active_provider||e?.available_providers?.find(I=>I.provider_id==="deepgram")||null,n=K(e,s,"prerecorded_transcription"),a=K(e,s,"conversational_streaming"),i=e?.model_settings?.audio_transcription_model_id||n[0]?.model_id||"nova-3",r=e?.model_settings?.conversation_model_id||a[0]?.model_id||"flux-general-multi",o=t.speechAudioModelId||i,d=t.speechConversationModelId||r,m=n.find(I=>I.model_id===o)||n[0]||null,w=a.find(I=>I.model_id===d)||a[0]||null,P=pe(m,e?.model_settings?.endpoints?.audio_transcription||`https://api.deepgram.com/v1/listen?model=${o}`),M=pe(w,e?.model_settings?.endpoints?.conversation||`wss://api.deepgram.com/v2/listen?model=${d}`),A=!!(e?.active_provider&&e?.credential_binding),R=!!(A&&o&&d&&!t.isSavingSpeechProvider&&(o!==i||d!==r));return`<div class="settings-hosted-models settings-speech-models">
    <div class="settings-platform-form-heading settings-hosted-models-heading">
      <span class="material-symbols-rounded" aria-hidden="true">graphic_eq</span>
      <span>
        <strong>Deepgram models</strong>
        <small>Audio transcription uses Nova-3; realtime conversation uses Flux turn-taking models.</small>
      </span>
    </div>
    ${ce({id:"settings-speech-audio-model",label:"Audio transcription model",icon:"hearing",value:o,options:n,endpoint:P,description:m?.description||"Deepgram model for prerecorded audio, files, and one-shot microphone transcription.",disabled:!A||t.isSavingSpeechProvider})}
    ${ce({id:"settings-speech-conversation-model",label:"Conversation model",icon:"forum",value:d,options:a,endpoint:M,description:w?.description||"Deepgram Flux model for realtime voice conversation and turn detection.",disabled:!A||t.isSavingSpeechProvider})}
    <button type="button" id="settings-speech-save" ${R?"":"disabled"}>
      <span class="material-symbols-rounded" aria-hidden="true">${t.isSavingSpeechProvider?"sync":"save"}</span>
      ${t.isSavingSpeechProvider?"Saving":"Save speech models"}
    </button>
    ${t.speechProviderError?`<p class="settings-platform-error">${p(t.speechProviderError)}</p>`:""}
    ${A?"":'<p class="settings-card-copy settings-platform-note">Activate Deepgram with a Core Secrets binding before using speech-to-text.</p>'}
  </div>`}function ce({id:e,label:t,icon:s,value:n,options:a,endpoint:i,description:r,disabled:o}){return a.length?`<article class="settings-model-accordion settings-speech-model-accordion">
    <div class="settings-model-trigger">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">${p(s)}</span>
      <span class="settings-model-copy">
        <span class="settings-model-kicker">
          <span class="settings-kicker">${p(t)}</span>
          <span class="settings-pill">Active</span>
        </span>
        <strong>${p(a.find(d=>d.model_id===n)?.label||n)}</strong>
        <small>${p(n)} · ${p(i)}</small>
      </span>
    </div>
    <div class="settings-model-content settings-hosted-model-content">
      <label class="settings-platform-field settings-platform-field-wide">
        <span>${p(t)}</span>
        <select id="${b(e)}" ${o?"disabled":""}>
          ${a.map(d=>`<option value="${b(d.model_id)}" ${d.model_id===n?"selected":""}>${p(d.label||d.model_id)}</option>`).join("")}
        </select>
      </label>
      <div class="settings-platform-field settings-platform-field-wide">
        <span>Endpoint</span>
        <code class="settings-model-code">${p(i)}</code>
      </div>
      <p class="settings-card-copy">${p(r)}</p>
    </div>
  </article>`:`<p class="settings-card-copy settings-platform-note">No ${p(t.toLowerCase())} options are available.</p>`}function K(e,t,s){const n=s==="prerecorded_transcription"?e?.model_settings?.available_audio_transcription_models:e?.model_settings?.available_conversation_models;return n?.length?n:(e?.model_settings?.available_models?.length?e.model_settings.available_models:t?.model_options||[]).filter(i=>i.metadata?.purpose===s)}function pe(e,t){const s=e?.metadata?.endpoint;return typeof s=="string"&&s?s:t}function Et(e,t,s,n){return`<section class="settings-card settings-platform settings-runtime-settings-card">
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
      ${e.length?e.map(i=>It(i,t,n)).join(""):'<p class="settings-card-copy">No runtime sessions.</p>'}
    </div>
    ${n.cleanupError?`<p class="settings-platform-error">${p(n.cleanupError)}</p>`:""}
  </details>
  </section>`}function It(e,t,s){const n=s.cleaningSessionIds.has(e.session_id);return`<div class="settings-platform-runtime-row">
    <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">terminal</span>
    <span class="settings-platform-runtime-copy">
      <span class="settings-platform-runtime-title">
        <strong>${p(e.agent_id||e.session_id)}</strong>
        <button type="button" class="settings-secondary settings-platform-runtime-clear" data-runtime-clear="${b(e.session_id)}" aria-label="Clean runtime session ${b(e.agent_id||e.session_id)}" ${!t||s.clearingAllRuntime||n?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">${n?"sync":"delete_sweep"}</span>
          <span class="settings-platform-runtime-clear-label">${n?"Cleaning":"Clean"}</span>
        </button>
      </span>
      <small>${p(e.workspace_name||e.workspace_id)} · ${p(e.effective_mode)} · ${p(e.status)}</small>
      <code>${p(e.session_id)}</code>
    </span>
  </div>`}function Mt(e){return e.runtime.all_sessions||e.runtime.sessions||[]}function X(e,t){const s=e?.provider.hosted_text?.selection?.openrouter_provider_routing_by_model?.[t];return{mode:s?.mode||"auto",provider_id:s?.provider_id||"",allow_fallbacks:s?.allow_fallbacks!==!1,require_parameters:s?.require_parameters===!0,sort:s?.sort||"",data_collection:s?.data_collection||"",quantizations:s?.quantizations||[]}}function we(e,t,s){const n=X(t,s),a=$e(e,s);return n.mode!==a.mode||(n.provider_id||"")!==(a.provider_id||"")||n.allow_fallbacks!==!1!=(a.allow_fallbacks!==!1)||n.require_parameters===!0!=(a.require_parameters===!0)||(n.sort||"")!==(a.sort||"")||(n.data_collection||"")!==(a.data_collection||"")||(n.quantizations?.[0]||"")!==(a.quantizations?.[0]||"")}function At(e,t){return t.hostedProviderErrorModelId?t.hostedProviderErrorModelId:!t.hostedDraftModelId||!we(t,e,t.hostedDraftModelId)?"":t.hostedDraftModelId}function Ct(e,t,s){return e.hostedRoutingDraftsByModel[s]||Y(X(t,s))}function ke(e,t,s){return e.hostedRoutingDraftsByModel[s]||(e.hostedRoutingDraftsByModel[s]=Y(X(t,s))),e.hostedRoutingDraftsByModel[s]}function Y(e){return{allowFallbacks:e.allow_fallbacks!==!1,dataCollection:e.data_collection||"",mode:e.mode||"auto",providerId:e.provider_id||"",quantization:e.quantizations?.[0]||"",requireParameters:e.require_parameters===!0,sort:e.sort||""}}function Rt(){return Y({mode:"auto",allow_fallbacks:!0,require_parameters:!1,sort:"",data_collection:"",quantizations:[]})}function p(e){return e.replace(/[&<>"']/g,t=>t==="&"?"&amp;":t==="<"?"&lt;":t===">"?"&gt;":t==='"'?"&quot;":"&#39;")}function b(e){return p(e)}const Ht=5,Dt=4,Lt=4,Ot=3,qt=4;function Ut(e){return`<section class="settings-loading-skeleton" role="status" aria-label="Settings content is loading">
    <header class="detail-header settings-loading-skeleton__header" aria-hidden="true">
      <div class="detail-title-block">
        ${f("title")}
        <span class="detail-title-separator" aria-hidden="true"></span>
        ${f("subtitle")}
      </div>
    </header>
    ${Tt(e)}
  </section>`}function Tt(e){return e.id==="workspace-access"?Bt():e.id==="workspace-apps"?jt():e.id==="platform-settings"?Ft():e.id==="persistence"?zt():Nt()}function Nt(){return`<section class="settings-card settings-loading-skeleton__create" aria-hidden="true">
      ${Wt("short-title")}
      ${D(Ht,()=>S("field"))}
      ${S("button")}
    </section>
    ${Se()}
    <div class="settings-loading-skeleton__profile-row" aria-hidden="true">
      <section class="settings-card settings-loading-skeleton__detail-card">
        ${j(!0)}
        <div class="settings-loading-skeleton__field-grid">
          ${D(Dt,()=>V())}
        </div>
        ${S("toggle")}
        ${S("button")}
      </section>
      <section class="settings-card settings-loading-skeleton__password-card">
        ${j(!1)}
        ${f("copy")}
        <div class="settings-loading-skeleton__field-grid">
          ${D(2,()=>V())}
        </div>
        ${S("button")}
        ${S("danger-button")}
      </section>
    </div>`}function Bt(){return`${Se()}
    <section class="settings-card" aria-hidden="true">
      ${j(!0)}
      <div class="settings-loading-skeleton__rows">
        ${D(Lt,()=>Jt())}
      </div>
    </section>`}function jt(){return`<section class="settings-card" aria-hidden="true">
      ${j(!1)}
      ${f("copy-wide")}
      <div class="settings-loading-skeleton__rows">
        ${D(Ot,()=>Kt())}
      </div>
    </section>`}function Ft(){return`<section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
      ${ee()}
    </section>
    <section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
      ${ee()}
      <div class="settings-loading-skeleton__provider-form">
        ${D(2,()=>V())}
        ${S("button")}
      </div>
      ${ee()}
    </section>
    <section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
      <div class="settings-loading-skeleton__runtime-toolbar">
        ${f("copy-wide")}
        ${S("button")}
      </div>
      <div class="settings-loading-skeleton__runtime-list">
        ${D(qt,()=>Vt())}
      </div>
    </section>`}function zt(){return`<section class="settings-card settings-loading-skeleton__persistence" aria-hidden="true">
      ${j(!0)}
      <div class="settings-loading-skeleton__adapter-cards">
        ${D(2,()=>Qt())}
      </div>
      ${Gt()}
    </section>`}function Se(){return`<section class="settings-card settings-user-picker" aria-hidden="true">
    <div class="settings-loading-skeleton__copy-stack">
      ${f("kicker")}
      ${f("card-title")}
      ${f("copy-short")}
    </div>
    ${V()}
  </section>`}function j(e){return`<div class="settings-loading-skeleton__heading">
    <span class="settings-loading-skeleton__copy-stack">
      ${f("kicker")}
      ${f("card-title")}
    </span>
    ${e?S("pill"):""}
  </div>`}function Wt(e){return`<div class="settings-loading-skeleton__copy-stack">
    ${f("kicker")}
    ${f(e)}
  </div>`}function V(){return`<span class="settings-loading-skeleton__field-wrap">
    ${f("label")}
    ${S("field")}
  </span>`}function Jt(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--membership">
    ${S("checkbox")}
    ${B("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${f("row-title")}
      ${f("row-copy")}
    </span>
    ${S("select")}
  </span>`}function Kt(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--app">
    ${B("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${f("row-title")}
      ${f("row-copy")}
    </span>
    ${S("toggle-pill")}
    ${S("button")}
  </span>`}function ee(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--tile">
    ${B("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${f("row-title")}
      ${f("row-copy")}
    </span>
  </span>`}function Vt(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--runtime">
    ${B("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${f("row-title")}
      ${f("row-copy")}
    </span>
    ${S("button")}
  </span>`}function Qt(){return`<span class="settings-loading-skeleton__adapter-card">
    ${B("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${f("row-title")}
      ${f("row-copy-wide")}
    </span>
    ${S("pill")}
  </span>`}function Gt(){return`<span class="settings-loading-skeleton__result">
    ${B("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${f("row-title")}
      ${f("row-copy-wide")}
    </span>
  </span>`}function f(e){return`<span class="settings-loading-skeleton__line settings-loading-skeleton__line--${e}"></span>`}function S(e){return`<span class="settings-loading-skeleton__block settings-loading-skeleton__block--${e}"></span>`}function B(e){return`<span class="settings-loading-skeleton__icon settings-loading-skeleton__icon--${e}"></span>`}function D(e,t){return Array.from({length:e},t).join("")}function Xt({publishChanged:e,render:t,setNotice:s}){let n=[],a=[],i="",r=[],o="",d=!1,m=new Set;function w(){return{appRegistry:n,dependencies:a,error:i,isLoading:d,loadErrors:r,savingKeys:m}}function P(){n=[],a=[],i="",r=[],o=""}function M(){o=""}async function A(c,_,u=!1){if(!(!c||d)&&!(!u&&o===c)){d=!0,i="",r=[],t();try{const[h,g]=await Promise.all([Fe(),I(c,_)]);n=h,a=g,o=c}catch(h){a=[],o="",i=h instanceof Error?h.message:"Unable to load app links."}finally{d=!1,t()}}}async function R(c,_,u){const h=Yt(c,_);m=new Set([...m,h]),t();try{const g=await We(c,_,u);a=a.map(U=>U.consumer_app_id===c?g:U),e(c,g),s({tone:"success",message:"App link updated."})}finally{const g=new Set(m);g.delete(h),m=g,t()}}async function I(c,_){const u=_.filter(g=>g.workspace_id===c&&g.status==="enabled"),h=await Promise.all(u.map(async g=>{try{return{app:g,payload:await ze(g.app_id)}}catch(U){return{app:g,error:U instanceof Error?U.message:"Unable to load app links."}}}));return r=h.filter(g=>"error"in g).map(g=>({app_id:g.app.app_id,message:g.error,name:g.app.name||g.app.app_id})),h.filter(g=>"payload"in g&&g.payload.dependencies.length>0).map(g=>g.payload).sort((g,U)=>g.consumer_app_id.localeCompare(U.consumer_app_id))}return{ensureLoaded:A,invalidate:M,reset:P,saveDependencySelection:R,viewState:w}}function Yt(e,t){return`${e}:${t}`}function l(e){return e.replace(/[&<>"']/g,t=>t==="&"?"&amp;":t==="<"?"&lt;":t===">"?"&gt;":t==='"'?"&quot;":"&#39;")}function $(e){return l(e)}function Zt({appRegistry:e,dependencies:t,error:s,isLoading:n,loadErrors:a,savingKeys:i,workspaceApps:r}){return`<section class="settings-card settings-app-links">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">App links</p>
          <h2>Provider app links</h2>
        </div>
      </div>
      <p class="settings-card-copy">Provider links are workspace-scoped. A selected provider is reused until it becomes unavailable; otherwise one-provider interface links use the first available candidate as their automatic default.</p>
      ${s?`<p class="settings-platform-error">${l(s)}</p>`:""}
      ${a.length?`<div class="settings-app-link-errors">${a.map(rs).join("")}</div>`:""}
      ${t.length>1?xt(t,e,r):""}
      <div class="settings-app-link-list">
        ${t.length?t.map(o=>es(o,e,r,i)).join(""):ss(s,n)}
      </div>
    </section>`}function xt(e,t,s){return`<nav class="settings-app-link-consumer-nav" aria-label="Provider link apps">
    ${e.map(n=>{const a=s.find(o=>o.workspace_id===n.workspace_id&&o.app_id===n.consumer_app_id),i=oe(t,n.consumer_app_id),r=a?.name||i?.name||n.consumer_app_id;return`<a class="settings-app-link-consumer-nav__item" href="#${$(Pe(n.consumer_app_id))}">
        <strong>${l(r)}</strong>
        <small>${l(String(n.dependencies.length))}</small>
      </a>`}).join("")}
  </nav>`}function es(e,t,s,n){const a=s.find(r=>r.workspace_id===e.workspace_id&&r.app_id===e.consumer_app_id),i=oe(t,e.consumer_app_id);return`<article class="settings-app-link-consumer" id="${$(Pe(e.consumer_app_id))}">
    <header class="settings-app-link-consumer__header">
      ${Ie(i,e.consumer_app_id)}
      <span class="settings-app-copy">
        <strong>${l(a?.name||e.consumer_app_id)}</strong>
        <small>${l(e.consumer_app_id)} - ${l(e.status)}</small>
      </span>
    </header>
    <div class="settings-app-link-dependencies">
      ${e.dependencies.map(r=>ts(e.consumer_app_id,r,t,n)).join("")}
    </div>
  </article>`}function ts(e,t,s,n){const a=n.has(ns(e,t.alias)),i=as(t),r=Ee(t);return`<section class="settings-app-link-row">
    <header class="settings-app-link-row__header">
      <span class="settings-app-link-row__copy">
        <strong>${l(t.alias)}</strong>
        <small>${l(t.interface)} ${l(t.version)}</small>
      </span>
      <span class="settings-pill ${t.status==="resolved"||r?"":"settings-pill-muted"}">${l(is(t,r))}</span>
    </header>
    <p class="settings-card-copy">${l(t.description||"No description.")}</p>
    ${t.blocked_reason?`<p class="settings-platform-error">${l(t.blocked_reason)}</p>`:""}
    ${t.stale_provider_app_ids.length?`<p class="settings-platform-error">Unavailable selection: ${l(t.stale_provider_app_ids.join(", "))}</p>`:""}
    ${t.candidates.length?`<div class="settings-app-link-candidates">
            ${t.candidates.map(o=>{const d=i.includes(o.app_id),m=t.cardinality==="many"?"checkbox":"radio",w=`dependency:${e}:${t.alias}`,P=oe(s,o.app_id);return`<label class="settings-app-link-candidate ${d?"is-selected":""}">
                <input
                  ${d?"checked":""}
                  ${a?"disabled":""}
                  data-dependency-choice="${$(ue(e,t.alias,o.app_id))}"
                  name="${$(w)}"
                  type="${m}"
                />
                ${Ie(P,o.app_id)}
                <span>
                  <strong>${l(o.name||o.app_id)}</strong>
                  <small>${l(o.app_id)} - ${l(o.interface_version)}${o.app_id===r?" - automatic default":""}</small>
                </span>
              </label>`}).join("")}
          </div>`:'<p class="settings-card-copy">No enabled provider app is available for this interface.</p>'}
    ${r?`<button type="button" class="settings-secondary" data-dependency-save-default="${$(ue(e,t.alias,r))}" ${a?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">${a?"sync":"save"}</span>
          ${a?"Saving":"Save default"}
        </button>`:""}
  </section>`}function ss(e,t){return e?"":t?'<p class="settings-card-copy">Loading app links...</p>':'<p class="settings-card-copy">No enabled app in the active workspace declares provider links.</p>'}function ns(e,t){return`${e}:${t}`}function ue(e,t,s){return`${e}:${t}:${s}`}function Pe(e){return`settings-app-link-consumer-${e}`}function as(e){if(e.selected_provider_app_ids.length)return e.selected_provider_app_ids;const t=Ee(e);return t?[t]:[]}function Ee(e){return e.selected_provider_app_ids.length||e.status!=="optional_unset"||e.cardinality!=="one"||e.stale_provider_app_ids.length||e.blocked_reason?"":e.candidates[0]?.app_id||""}function is(e,t){return t?"auto default":e.status==="optional_unset"?"unset":e.status}function oe(e,t){return e.find(s=>s.app_id===t)||null}function rs(e){return`<p class="settings-platform-error">${l(e.name||e.app_id)}: ${l(e.message)}</p>`}function Ie(e,t){if(e?.logo?.kind==="image"&&e.logo.value)return`<span class="settings-app-link-logo is-image"><img alt="" loading="lazy" src="${$(e.logo.value)}" /></span>`;const s=e?.logo?.value||os(e,t);return`<span class="settings-app-link-logo is-glyph"><span class="material-symbols-rounded" aria-hidden="true">${l(s)}</span></span>`}function os(e,t){const s={agents:"smart_toy","app-store":"storefront","base-shell":"dashboard",chat:"forum",checklist:"checklist",crm:"contacts","developer-kit":"developer_board","docs-studio":"description","document-generator":"description","dynamic-views":"dashboard_customize","gmail-app":"mail",memory:"database","maverick-monitor":"monitor_heart",settings:"admin_panel_settings",skills:"school",speech:"record_voice_over",storage:"cloud","website-studio":"web_asset"};return s[t]?s[t]:e?.views.includes("chat")?"forum":e?.views.includes("agents")?"smart_toy":e?.views.includes("shell")?"dashboard":"apps"}function ds(e){document.getElementById("dismiss-notice")?.addEventListener("click",e.dismissNotice),document.getElementById("create-user")?.addEventListener("submit",s=>{s.preventDefault(),e.createUser(s.currentTarget).catch(e.showError)});const t=e.selectedUser();document.getElementById("selected-user")?.addEventListener("change",s=>{e.selectUser(s.currentTarget.value)}),document.getElementById("edit-user")?.addEventListener("submit",s=>{s.preventDefault(),t&&e.updateSelectedUser(s.currentTarget,t).catch(e.showError)}),document.getElementById("reset-password")?.addEventListener("submit",s=>{s.preventDefault(),t&&e.resetSelectedUserPassword(s.currentTarget,t).catch(e.showError)}),document.getElementById("delete-user")?.addEventListener("click",()=>{t&&e.deleteSelectedUser(t).catch(e.showError)}),document.getElementById("save-memberships")?.addEventListener("click",()=>{t&&e.updateMemberships(t).catch(e.showError)}),cs(e),ls(e),ps(e),yt({onClearAllRuntimeSessions:()=>{e.clearRuntimeSessionsFromPanel().catch(e.showError)},onClearRuntimeSession:s=>{s&&e.clearRuntimeSessionsFromPanel([s]).catch(e.showError)},onLogout:()=>{e.logoutFromSettings().catch(e.showError)},onHostedProviderRoutingChanged:e.onHostedProviderRoutingChanged,onProviderModelChanged:e.onProviderModelChanged,onProviderReasoningChanged:e.onProviderReasoningChanged,onSpeechAudioModelChanged:e.onSpeechAudioModelChanged,onSpeechConversationModelChanged:e.onSpeechConversationModelChanged,onSaveHostedProviderSettings:s=>{e.saveHostedProviderSettingsFromPanel(s).catch(e.showError)},onSaveProviderSettings:()=>{e.saveProviderSettingsFromPanel().catch(e.showError)},onSaveSpeechProviderSettings:()=>{e.saveSpeechProviderSettingsFromPanel().catch(e.showError)}})}function ls(e){document.querySelectorAll("[data-dependency-choice]").forEach(t=>{t.addEventListener("change",()=>{const s=ge(t.dataset.dependencyChoice||"");if(!s)return;const n=e.appDependencies().find(i=>i.consumer_app_id===s.consumerAppId)?.dependencies.find(i=>i.alias===s.alias);if(!n)return;if(n.cardinality==="one"){e.saveDependencySelection(s.consumerAppId,s.alias,[s.providerAppId]).catch(e.showError);return}const a=new Set(n.selected_provider_app_ids);t.checked?a.add(s.providerAppId):a.delete(s.providerAppId),e.saveDependencySelection(s.consumerAppId,s.alias,Array.from(a)).catch(e.showError)})}),document.querySelectorAll("[data-dependency-save-default]").forEach(t=>{t.addEventListener("click",()=>{const s=ge(t.dataset.dependencySaveDefault||"");s&&e.saveDependencySelection(s.consumerAppId,s.alias,[s.providerAppId]).catch(e.showError)})})}function ge(e){const[t,s,...n]=e.split(":"),a=n.join(":");return!t||!s||!a?null:{alias:s,consumerAppId:t,providerAppId:a}}function cs(e){document.querySelectorAll("[data-app-toggle]").forEach(t=>{t.addEventListener("change",()=>{const s=e.workspaceApps().find(n=>`${n.workspace_id}:${n.app_id}`===t.dataset.appToggle);s&&e.setWorkspaceAppStatus(s,t.checked).catch(e.showError)})}),document.querySelectorAll("[data-app-install]").forEach(t=>{t.addEventListener("click",()=>{const s=e.workspaceApps().find(n=>`${n.workspace_id}:${n.app_id}`===t.dataset.appInstall);s&&e.installWorkspaceApp(s).catch(e.showError)})}),document.querySelectorAll("[data-app-uninstall]").forEach(t=>{t.addEventListener("click",()=>{const s=e.workspaceApps().find(n=>`${n.workspace_id}:${n.app_id}`===t.dataset.appUninstall);s&&e.uninstallWorkspaceApp(s).catch(e.showError)})})}function ps(e){document.querySelectorAll("[data-adapter-target]").forEach(t=>{t.addEventListener("click",()=>{const s=t.dataset.adapterTarget;(s==="json"||s==="mongo")&&e.persistenceController.prepare(s).catch(e.showError)})}),document.getElementById("close-migration-modal")?.addEventListener("click",()=>{e.persistenceController.cancel()}),document.getElementById("cancel-migration")?.addEventListener("click",()=>{e.persistenceController.cancel()}),document.getElementById("validate-migration")?.addEventListener("click",()=>{e.persistenceController.validateDraft().catch(e.showError)}),document.querySelectorAll("[data-migration-field]").forEach(t=>{const s=n=>{const a=t.dataset.migrationField;if(a&&a in(e.persistenceController.viewState().targetDraft||{})){const i=!!e.persistenceController.viewState().migrationPlan;e.persistenceController.updateDraft(a,t.value,{render:n}),!n&&i&&us()}};t.addEventListener("input",()=>s(!1)),t.addEventListener("change",()=>s(!0))}),document.getElementById("settings-delete-source")?.addEventListener("change",t=>{e.persistenceController.setDeleteSource(t.currentTarget.checked)}),document.getElementById("confirm-migration")?.addEventListener("click",()=>{e.persistenceController.apply().catch(e.showError)})}function us(){const e=document.getElementById("confirm-migration");e&&(e.disabled=!0);const t=document.querySelector(".settings-migration-plan");if(!t)return;const s=t.querySelector(".material-symbols-rounded"),n=t.querySelector("strong"),a=t.querySelector("small");s&&(s.textContent="rule"),n&&(n.textContent="Dry run changed"),a&&(a.textContent="Validate the dry run again before applying migration."),t.querySelector(".settings-migration-collections")?.remove()}function gs(e){let t=null,s=null,n="",a=null,i=null,r=null,o=!1;function d(){return{deleteSourceAfterMigration:o,migrationPlan:a,migrationProgress:r,migrationResult:i,migrationTarget:t,persistence:e.getPersistence(),targetDraft:s}}async function m(c){const _=e.getPersistence();if(!_||_.active_adapter.kind===c){M();return}t=c,s=ms(c,_),n="",a=null,o=!1,r=null,e.setNotice(null),e.render()}function w(c,_,u={}){s&&(s={...s,[c]:_},a=null,n="",r=null,u.render!==!1&&e.render())}function P(c){o=c,e.render()}function M(){t=null,s=null,a=null,n="",r=null,e.render()}async function A(){if(!(!s||!t)){r={target:t,phase:"validating",percent:10,title:`Dry run to ${t.toUpperCase()}`,detail:"Validating target adapter and collection copy plan before applying changes."},e.setNotice(null),e.render();try{const c=ne(s);a=await Xe(c),n=me(c)}catch(c){throw r=null,a=null,n="",c}r=null,a.same_adapter&&e.setNotice({tone:"info",message:"The selected persistence adapter is already active."}),e.render()}}async function R(){if(!s||!t)return;const c=ne(s),_=me(c);if(!a||n!==_){await A();return}if(a.same_adapter)return;r={target:t,phase:"applying",percent:38,title:`Migration to ${t.toUpperCase()}`,detail:"Copying the validated control-plane plan to the target adapter."},e.setNotice(null),e.render();try{i=await Ye({...c,delete_source:o,restart_backend:!0})}catch(h){throw r={target:t,phase:"failed",percent:100,title:"Migration failed",detail:h instanceof Error?h.message:"Unable to apply migration."},h}const u=t;t=null,s=null,a=null,n="",r={target:u,phase:"restarting",percent:68,title:"Restart backend",detail:i.backend_restart?.detail||"Backend restart scheduled."},e.render(),await I(u)}async function I(c){const _=Date.now(),u=9e4;for(;Date.now()-_<u;){r={target:c,phase:"polling",percent:84,title:"Verifying cutover",detail:"Waiting for the backend to become healthy with the new adapter."},e.render();const h=await e.requestPersistenceStatusQuiet();if(h?.active_adapter.kind===c){e.setPersistence(h);const g=i?.source_cleanup?.scheduled===!0;r={target:c,phase:"complete",percent:100,title:"Migration complete",detail:g?`Active adapter: ${c.toUpperCase()}. Source cleanup is scheduled after health check.`:`Active adapter: ${c.toUpperCase()}. Source storage was preserved.`},e.setNotice({tone:"success",message:`Migration to ${c.toUpperCase()} complete.`}),e.render();return}await new Promise(g=>window.setTimeout(g,1500))}r={target:c,phase:"failed",percent:100,title:"Verification not completed",detail:"The backend did not confirm the new adapter before the timeout. Check service health and logs."},e.setNotice({tone:"error",message:"Migration not confirmed before the timeout."}),e.render()}return{apply:R,cancel:M,prepare:m,setDeleteSource:P,updateDraft:w,validateDraft:A,viewState:d}}function ms(e,t){const s=t.active_adapter;return{kind:e,json_root:s.json_root||"data/control-plane/json",mongodb_uri:s.mongo_uri||"mongodb://127.0.0.1:27017/maverick",mongodb_database:s.mongo_database||"maverick",mongodb_username:s.mongo_username||"",mongodb_password_ref:s.mongo_password_ref||""}}function ne(e){return{kind:e.kind,json_root:e.json_root.trim()||"data/control-plane/json",mongodb_uri:e.mongodb_uri.trim(),mongodb_database:e.mongodb_database.trim()||"maverick",mongodb_username:e.mongodb_username?.trim()||void 0,mongodb_password_ref:e.mongodb_password_ref?.trim()||void 0}}function me(e){return JSON.stringify(ne(e))}function fs(e){return _s(e)}function vs(e){const{deleteSourceAfterMigration:t,migrationPlan:s,migrationProgress:n,migrationTarget:a,persistence:i}=e;if(!a||!i)return"";const r=i.active_adapter.kind.toUpperCase(),o=a.toUpperCase(),d=!!(n&&!["complete","failed"].includes(n.phase)),m=!!(s&&!s.same_adapter&&!d);return`<div class="settings-modal-backdrop" role="presentation">
    <section class="settings-modal" role="dialog" aria-modal="true" aria-labelledby="adapter-migration-title">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Confirm migration</p>
          <h2 id="adapter-migration-title">${r} → ${o}</h2>
        </div>
        <button type="button" class="settings-icon-button" id="close-migration-modal" aria-label="Close" ${d?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">close</span>
        </button>
      </div>
      ${s?ws(s):$s(n)}
      ${hs(e)}
      <label class="settings-toggle settings-migration-delete-source">
        <input id="settings-delete-source" type="checkbox" ${t?"checked":""} ${d?"disabled":""} />
        Schedule source cleanup after restart health check
      </label>
      <p class="settings-card-copy">Leave cleanup off to preserve the current source adapter data as a rollback point. Cleanup is a separate explicit choice and requires backend restart.</p>
      <div class="settings-modal-actions">
        <button type="button" class="settings-secondary" id="cancel-migration" ${d?"disabled":""}>Cancel</button>
        <button type="button" class="settings-secondary" id="validate-migration" ${d?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">rule</span>
          Validate dry run
        </button>
        <button type="button" class="${t?"settings-danger":"settings-secondary"}" id="confirm-migration" ${m?"":"disabled"}>
          <span class="material-symbols-rounded" aria-hidden="true">sync_alt</span>
          ${t?"Apply and schedule cleanup":"Apply migration"}
        </button>
      </div>
    </section>
  </div>`}function hs(e){const t=e.targetDraft;if(!t)return"";const s=!!(e.migrationProgress&&!["complete","failed"].includes(e.migrationProgress.phase));return`<div class="settings-migration-target">
    <label class="settings-platform-field">
      <span>JSON root</span>
      <input data-migration-field="json_root" value="${$(t.json_root)}" ${s?"disabled":""} />
    </label>
    ${t.kind==="mongo"?`<label class="settings-platform-field">
          <span>Mongo URI</span>
          <input data-migration-field="mongodb_uri" value="${$(t.mongodb_uri)}" ${s?"disabled":""} />
        </label>
        <label class="settings-platform-field">
          <span>Mongo database</span>
          <input data-migration-field="mongodb_database" value="${$(t.mongodb_database)}" ${s?"disabled":""} />
        </label>
        <label class="settings-platform-field">
          <span>Mongo username</span>
          <input data-migration-field="mongodb_username" value="${$(t.mongodb_username||"")}" ${s?"disabled":""} />
        </label>
        <label class="settings-platform-field">
          <span>Password secret ref</span>
          <input data-migration-field="mongodb_password_ref" value="${$(t.mongodb_password_ref||"")}" ${s?"disabled":""} />
        </label>`:""}
  </div>`}function _s(e){const{migrationProgress:t,migrationResult:s,persistence:n}=e;if(!n)return`<section class="settings-card settings-persistence">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Persistence</p>
          <h2>Control plane adapter</h2>
        </div>
        <span class="settings-pill settings-pill-muted">offline</span>
      </div>
      <p class="settings-card-copy">The core persistence surfaces are not available in the active backend.</p>
    </section>`;const a=n.active_adapter,i=n.collections.reduce((m,w)=>m+w.count,0),r=a.kind==="json",o=a.kind==="mongo",d=t&&!["complete","failed"].includes(t.phase);return`<section class="settings-card settings-persistence">
    <div class="settings-heading">
      <div>
        <p class="settings-kicker">Persistence</p>
        <h2>Control plane adapter</h2>
      </div>
      <span class="settings-pill">${i} documents</span>
    </div>
    <div class="settings-adapter-cards">
      <button type="button" class="settings-adapter-card ${r?"is-active":""}" ${r||d?"disabled":'data-adapter-target="json"'}>
        <span class="settings-adapter-card-icon material-symbols-rounded" aria-hidden="true">${r?"check_circle":"database"}</span>
        <span>
          <strong>JSON</strong>
          <small>${l(r?a.json_root:"data/control-plane/json")}</small>
        </span>
        <em>${r?"Current":"Review migration"}</em>
      </button>
      <button type="button" class="settings-adapter-card ${o?"is-active":""}" ${o||d?"disabled":'data-adapter-target="mongo"'}>
        <span class="settings-adapter-card-icon material-symbols-rounded" aria-hidden="true">${o?"check_circle":"database"}</span>
        <span>
          <strong>Mongo</strong>
          <small>${l(o?a.mongo_database:"mongodb://127.0.0.1:27017/maverick")}</small>
        </span>
        <em>${o?"Current":"Review migration"}</em>
      </button>
    </div>
    ${bs(t)}
    ${ys(s)}
  </section>`}function bs(e){return e?`<div class="settings-migration-progress ${e.phase==="failed"?"is-failed":""} ${e.phase==="complete"?"is-complete":""}">
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
  </div>`:""}function ys(e){return e?`<div class="settings-migration-result">
    <span class="material-symbols-rounded" aria-hidden="true">task_alt</span>
    <span>
      <strong>Last migration</strong>
      <small>${e.collections.reduce((s,n)=>s+n.count,0)} documents · target ${l(e.target_adapter.kind)} · cleanup ${e.source_cleanup?.scheduled?"scheduled":"not requested"}</small>
    </span>
  </div>`:""}function $s(e){return`<div class="settings-migration-plan">
    <span class="material-symbols-rounded" aria-hidden="true">rule</span>
    <span>
      <strong>${l(e?.title||"Dry run not validated")}</strong>
      <small>${l(e?.detail||"Adjust the target fields, then validate the dry run before applying migration.")}</small>
    </span>
  </div>`}function ws(e){const t=e.collections.reduce((n,a)=>n+a.count,0),s=e.target_collections.reduce((n,a)=>n+a.count,0);return`<div class="settings-migration-plan">
    <span class="material-symbols-rounded" aria-hidden="true">${e.same_adapter?"block":"rule"}</span>
    <span>
      <strong>${e.same_adapter?"Target already active":"Dry run complete"}</strong>
      <small>${t} source documents · ${s} target documents before copy · env ${l(e.env_file)}</small>
    </span>
    <div class="settings-migration-collections">
      ${e.collections.map(n=>`<span><strong>${l(n.name)}</strong><small>${n.count}</small></span>`).join("")}
    </div>
  </div>`}async function ks(e){const t=e.settings?.provider.active_provider?.provider_id;if(!t||!e.state.draftModelId){e.state.providerError="Provider not loaded.",e.render();return}e.state.isSavingProvider=!0,e.state.providerError="",e.render();try{await Je({provider_id:t,model_id:e.state.draftModelId,model_reasoning_effort:e.state.draftReasoningEffort||null});const s=await z();e.setSettings(s),W(e.state,s),e.setNotice({tone:"success",message:"Provider settings updated."})}catch(s){e.state.providerError=s instanceof Error?s.message:"Unable to update provider settings."}finally{e.state.isSavingProvider=!1,e.render()}}async function Ss(e){const t=e.settings?.provider.hosted_text?.active_provider?.provider_id;if(!t||!e.state.hostedDraftModelId){e.state.hostedProviderErrorModelId=e.state.hostedDraftModelId,e.state.hostedProviderError="Hosted provider not loaded.",e.render();return}e.state.isSavingHostedProvider=!0,e.state.hostedProviderError="",e.state.hostedProviderErrorModelId=e.state.hostedDraftModelId,e.render();try{await Ke({provider_id:t,model_id:e.state.hostedDraftModelId,openrouter_provider_routing:$e(e.state,e.state.hostedDraftModelId)});const s=await z();e.setSettings(s),W(e.state,s),e.setNotice({tone:"success",message:"Hosted model settings updated."})}catch(s){e.state.hostedProviderErrorModelId=e.state.hostedDraftModelId,e.state.hostedProviderError=s instanceof Error?s.message:"Unable to update hosted model settings."}finally{e.state.isSavingHostedProvider=!1,e.render()}}async function Ps(e){const t=e.settings?.provider.speech_stt?.active_provider?.provider_id;if(!t||!e.state.speechAudioModelId||!e.state.speechConversationModelId){e.state.speechProviderError="Speech provider not loaded.",e.render();return}e.state.isSavingSpeechProvider=!0,e.state.speechProviderError="",e.render();try{await Ve({provider_id:t,audio_transcription_model_id:e.state.speechAudioModelId,conversation_model_id:e.state.speechConversationModelId});const s=await z();e.setSettings(s),W(e.state,s),e.setNotice({tone:"success",message:"Speech model settings updated."})}catch(s){e.state.speechProviderError=s instanceof Error?s.message:"Unable to update speech model settings."}finally{e.state.isSavingSpeechProvider=!1,e.render()}}function Es({pendingDeleteUserId:e,selectedUser:t,users:s}){return`<form class="settings-card settings-create" id="create-user">
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
    ${Me(s,t)}
    ${t?`<div class="settings-profile-row">
          <form class="settings-card settings-detail" id="edit-user">
            <div class="settings-heading">
              <div>
                <p class="settings-kicker">Selected user</p>
                <h2>${l(t.display_name||t.username)}</h2>
              </div>
              <span class="settings-pill">${t.is_active?"active":"disabled"}</span>
            </div>
            <div class="settings-grid">
              <label>Name<input name="display_name" value="${$(t.display_name||"")}" /></label>
              <label>Email<input name="email" type="email" value="${$(t.email||"")}" /></label>
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
        </div>`:'<section class="settings-card"><h2>No users</h2></section>'}`}function Is({selectedUser:e,users:t,workspaces:s}){return`${Me(t,e)}
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
          <div class="settings-memberships">${Ms(e,s)}</div>
        </section>`:'<section class="settings-card"><h2>No users</h2></section>'}`}function Me(e,t){return e.length?`<section class="settings-card settings-user-picker">
    <div>
      <p class="settings-kicker">User directory</p>
      <h2>${l(t?t.display_name||t.username:"Select user")}</h2>
      <p class="settings-card-copy">${e.length} user${e.length===1?"":"s"} available.</p>
    </div>
    <label class="settings-platform-field">
      <span>Selected user</span>
      <select id="selected-user">
        ${e.map(s=>`<option value="${$(s.user_id)}" ${s.user_id===t?.user_id?"selected":""}>${l(s.display_name||s.username)} (${l(s.username)})</option>`).join("")}
      </select>
    </label>
  </section>`:`<section class="settings-card settings-user-picker">
      <div>
        <p class="settings-kicker">User directory</p>
        <h2>No users</h2>
      </div>
      <p class="settings-card-copy">Create a user before editing profile or workspace access settings.</p>
    </section>`}function Ms(e,t){return t.map(s=>{const n=e.memberships.find(a=>a.workspace_id===s.workspace_id);return`<label class="settings-membership">
        <input type="checkbox" data-workspace-enabled="${$(s.workspace_id)}" ${n?"checked":""} />
        <span class="settings-membership-icon material-symbols-rounded" aria-hidden="true">workspaces</span>
        <span>
          <strong>${l(s.name)}</strong>
          <small>${l(s.workspace_id)}</small>
        </span>
        <select data-workspace-role="${$(s.workspace_id)}">
          <option value="member" ${n?.role!=="admin"?"selected":""}>Member</option>
          <option value="admin" ${n?.role==="admin"?"selected":""}>Workspace admin</option>
        </select>
      </label>`}).join("")}function As({workspaceApps:e,workspaces:t}){return`<section class="settings-card">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Workspace apps</p>
          <h2>Installation and visibility</h2>
        </div>
      </div>
      <p class="settings-card-copy">Installed means the app has a workspace binding. Only enabled apps are visible to users and served by the core.</p>
      <div class="settings-app-workspaces">${Cs(t,e)}</div>
    </section>`}function Cs(e,t){return e.map(s=>{const n=t.filter(r=>r.workspace_id===s.workspace_id),a=n.filter(r=>r.status==="enabled").length,i=n.filter(r=>r.installed).length;return`<details class="settings-app-workspace">
        <summary class="settings-app-workspace-heading">
          <span class="settings-summary-caret material-symbols-rounded" aria-hidden="true">chevron_right</span>
          <span class="settings-app-workspace-icon material-symbols-rounded" aria-hidden="true">deployed_code</span>
          <span>
            <strong>${l(s.name)}</strong>
            <small>${l(s.workspace_id)} · ${a}/${i} enabled</small>
          </span>
        </summary>
        <div class="settings-apps">
          ${n.map(Rs).join("")}
        </div>
      </details>`}).join("")}function Rs(e){const t=e.status==="enabled",s=e.installed,n=s?e.status:"not installed",a=`${e.workspace_id}:${e.app_id}`;return`<div class="settings-app-row">
    <span class="settings-app-icon material-symbols-rounded" aria-hidden="true">${l(Hs(e))}</span>
    <span class="settings-app-copy">
      <strong>${l(e.name)}</strong>
      <small>${l(e.app_id)} · v${l(e.version)} · ${l(n)}</small>
    </span>
    ${s?`<label class="settings-switch">
          <input type="checkbox" data-app-toggle="${$(a)}" ${t?"checked":""} />
          <span>Enabled</span>
        </label>
        <button type="button" class="settings-secondary" data-app-uninstall="${$(a)}">
          <span class="material-symbols-rounded" aria-hidden="true">link_off</span>
          Uninstall
        </button>`:`<button type="button" class="settings-secondary" data-app-install="${$(a)}">
          <span class="material-symbols-rounded" aria-hidden="true">add_link</span>
          Install
        </button>`}
  </div>`}function Hs(e){return e.status!=="enabled"?"hide_source":{agents:"smart_toy","app-store":"storefront","base-shell":"dashboard",browser:"language",calendar:"calendar_month",chat:"forum",checklist:"checklist",crm:"contacts","developer-kit":"developer_board","docs-studio":"description","document-generator":"description","dynamic-views":"dashboard_customize","gmail-app":"mail",mail:"mail",memory:"database","maverick-monitor":"monitor_heart",settings:"admin_panel_settings",senses:"sensors",skills:"school",speech:"record_voice_over",storage:"cloud",vault:"key","website-studio":"web_asset"}[e.app_id]||"apps"}let L=[],Q=[],F=[],ae=null,C=null,k=ct();const Ae=Object.fromEntries(new URLSearchParams(window.location.search).entries());let G=he(Ae)||Le,H=Re(Ae),T=!0,N="",E=null,fe="",ve="";const de=gs({getPersistence:()=>ae,render:()=>y(),requestPersistenceStatusQuiet:Us,setNotice:e=>{E=e},setPersistence:e=>{ae=e}}),O=Xt({publishChanged:Xs,render:()=>y(),setNotice:e=>{E=e}});function Ce(){return L.find(e=>e.user_id===H)||L[0]}function Re(e){const t=J(e.user_id)||J(e.selected_user_id)||J(e.id);if(t)return t;const s=J(e.app_page),n=/^users\/([^/?#]+)$/.exec(s);if(!n?.[1])return"";try{return decodeURIComponent(n[1])}catch{return n[1]}}function J(e){return typeof e=="string"?e.trim():""}function Ds(e){const t=he(e),s=Re(e);let n=!1;t&&t!==G&&(G=t,n=!0),s&&s!==H&&(H=s,N="",n=!0),n&&((L.length||T)&&y(),t==="app-links"&&He())}function Ls(e){e.id===fe||window.parent===window||(fe=e.id,window.parent.postMessage({type:"maverick.app.selection-changed",owner_app_id:"settings",selection:{page_id:e.id}},window.location.origin))}function Os(e){!e||e.user_id===ve||window.parent===window||(ve=e.user_id,window.parent.postMessage({type:"maverick.app.selection-changed",owner_app_id:"settings",selection:{user_id:e.user_id}},window.location.origin))}function Z(){window.parent!==window&&window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"settings",resource:"users"},window.location.origin)}async function qs(){try{return await v("/api/admin/persistence")}catch(e){return E={tone:"error",message:e instanceof Error?e.message:"Persistence API unavailable"},null}}async function Us(){try{return await v("/api/admin/persistence")}catch{return null}}async function Ts(){try{return await z()}catch{return null}}async function q(){T=!0,y();try{const[e,t,s,n,a]=await Promise.all([qe(),Ue(),Te(),qs(),Ts()]),i=C?.workspace.workspace_id||"",r=a?.workspace.workspace_id||"";L=e,Q=t,F=s,ae=n,C=a,i!==r&&O.reset(),W(k,C),(!H||!L.some(o=>o.user_id===H))&&(H=L[0]?.user_id||"")}finally{T=!1}y(),G==="app-links"&&He()}async function He(e=!1){const t=C?.workspace.workspace_id||"";await O.ensureLoaded(t,F,e)}async function Ns(e){const t=new FormData(e);H=(await Ze({username:String(t.get("username")||""),password:String(t.get("password")||""),display_name:String(t.get("display_name")||""),email:String(t.get("email")||""),platform_role:String(t.get("platform_role")||"member")})).user_id,e.reset(),await q(),Z()}async function Bs(e,t){const s=new FormData(e);await xe(t.user_id,{display_name:String(s.get("display_name")||""),email:String(s.get("email")||""),platform_role:String(s.get("platform_role")||"member"),account_type:String(s.get("account_type")||"standard"),is_active:s.get("is_active")==="on"}),await q(),Z()}async function js(e,t){const s=new FormData(e),n=String(s.get("password")||""),a=String(s.get("password_confirmation")||"");if(n!==a)throw new Error("Passwords do not match");await et(t.user_id,n),e.reset(),E={tone:"success",message:"Password updated."},y()}async function Fs(e){const t=e.display_name||e.username;if(N!==e.user_id){N=e.user_id,E={tone:"info",message:`Press Delete user again to confirm permanent removal of ${t}.`},y();return}await tt(e.user_id),H="",N="",E={tone:"success",message:`${t} deleted.`},await q(),Z()}async function zs(e){const t=Q.map(s=>{const n=document.querySelector(`[data-workspace-enabled="${s.workspace_id}"]`),a=document.querySelector(`[data-workspace-role="${s.workspace_id}"]`);return n?.checked?{workspace_id:s.workspace_id,role:a?.value||"member"}:null}).filter(s=>!!s);await st(e.user_id,t),await q(),Z()}async function Ws(e){await nt(e),O.invalidate(),await q()}async function Js(e,t){await at(e,t),O.invalidate(),await q()}async function Ks(e){await it(e),O.invalidate(),await q()}async function Vs(e,t,s){await O.saveDependencySelection(e,t,s)}async function Qs(e){const t=(e||[]).filter(Boolean);k.cleanupError="",t.length?t.forEach(s=>k.cleaningSessionIds.add(s)):k.clearingAllRuntime=!0,y();try{const s=await Qe(t.length?t:void 0);Gs(s),C=await z(),W(k,C),E={tone:"success",message:t.length?"Runtime session cleaned.":"Runtime sessions cleaned."}}catch(s){k.cleanupError=s instanceof Error?s.message:"Unable to clean runtime sessions."}finally{t.forEach(s=>k.cleaningSessionIds.delete(s)),k.clearingAllRuntime=!1,y()}}function Gs(e){e.deleted_threads<=0||window.parent===window||(window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"chat",resource:"threads"},window.location.origin),e.deleted_thread_ids.forEach(t=>{window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"chat",resource:"threads",deleted_thread_id:t},window.location.origin)}))}function Xs(e,t){window.parent!==window&&window.parent.postMessage({type:"maverick.app.dependencies-changed",app_id:e,status:t.status},window.location.origin)}async function Ys(){if(window.parent&&window.parent!==window){window.parent.postMessage({type:"maverick.shell.logout"},window.location.origin);return}await Ge(),window.location.href="/"}function Zs(e,t){if(e.id==="users")return Es({pendingDeleteUserId:N,selectedUser:t,users:L});if(e.id==="workspace-access")return Is({selectedUser:t,users:L,workspaces:Q});if(e.id==="workspace-apps")return As({workspaceApps:F,workspaces:Q});if(e.id==="app-links"){const s=O.viewState();return Zt({appRegistry:s.appRegistry,dependencies:s.dependencies,error:s.error,isLoading:s.isLoading,loadErrors:s.loadErrors,savingKeys:s.savingKeys,workspaceApps:F})}return e.id==="platform-settings"?xs():fs(de.viewState())}function xs(){return ht(C,k)}function y(){const e=document.getElementById("app"),t=T?void 0:Ce(),s=Oe(G);e&&(e.innerHTML=`<main class="settings-shell">
    <section class="settings-main">
      <div class="settings-content">
        ${T?Ut(s):`<header class="detail-header">
          <div class="detail-title-block">
            <h2>${l(s.title)}</h2>
            <span class="detail-title-separator" aria-hidden="true"></span>
            <p>${l(s.summary)}</p>
          </div>
        </header>
        ${tn()}
        ${Zs(s,t)}`}
      </div>
    </section>
    ${vs(de.viewState())}
  </main>`,en(),Ls(s),T||Os(t))}function en(){ds({clearRuntimeSessionsFromPanel:Qs,createUser:Ns,deleteSelectedUser:Fs,dismissNotice:()=>{E=null,y()},installWorkspaceApp:Ws,logoutFromSettings:Ys,onHostedProviderRoutingChanged:(e,t,s)=>{ft(k,C,e,t,s),y()},onProviderModelChanged:e=>{pt(k,C,e),y()},onProviderReasoningChanged:e=>{k.draftReasoningEffort=e,k.providerError="",y()},onSpeechAudioModelChanged:e=>{gt(k,e),y()},onSpeechConversationModelChanged:e=>{mt(k,e),y()},persistenceController:de,render:y,resetSelectedUserPassword:js,saveDependencySelection:Vs,saveHostedProviderSettingsFromPanel:e=>(e&&ut(k,C,e),Ss(te())),saveProviderSettingsFromPanel:()=>ks(te()),saveSpeechProviderSettingsFromPanel:()=>Ps(te()),selectedUser:Ce,selectUser:e=>{H=e,N="",y()},setWorkspaceAppStatus:Js,showError:De,uninstallWorkspaceApp:Ks,updateMemberships:zs,updateSelectedUser:Bs,workspaceApps:()=>F,appDependencies:()=>O.viewState().dependencies})}function te(){return{render:y,setNotice:e=>{E=e},setSettings:e=>{C=e},settings:C,state:k}}function De(e){E={tone:"error",message:e instanceof Error?e.message:"Unexpected error"},y()}function tn(){return E?`<div class="settings-notice settings-notice-${E.tone}">
    <span class="material-symbols-rounded" aria-hidden="true">${E.tone==="error"?"error":E.tone==="success"?"task_alt":"info"}</span>
    <span>${l(E.message)}</span>
    <button type="button" class="settings-icon-button" id="dismiss-notice" aria-label="Close">
      <span class="material-symbols-rounded" aria-hidden="true">close</span>
    </button>
  </div>`:""}window.addEventListener("message",e=>{if(e.origin!==window.location.origin||!e.data||typeof e.data!="object")return;const t=e.data;t.type==="maverick.app.navigate"&&(!t.app_id||t.app_id==="settings")&&Ds(t.params||{})});window.parent?.postMessage({type:"maverick.app.ready",app_id:"settings"},window.location.origin);q().catch(De);
