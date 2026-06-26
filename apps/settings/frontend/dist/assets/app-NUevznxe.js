import{s as ye,D as ze,a as We}from"./pages-BZUBskpf.js";async function _(e,t={}){const s=await fetch(e,{credentials:"same-origin",headers:{"Content-Type":"application/json",...t.headers||{}},...t}),n=await s.json();if(!s.ok)throw new Error(n.detail||n.error||`Request failed ${s.status}`);return n}async function Je(){return(await _("/api/admin/users")).items}async function Ke(){return(await _("/api/admin/workspaces")).items}async function Ve(){return(await _("/api/admin/workspace-apps")).items}function ue(e,t=""){return typeof e=="string"?e:t}function Ge(e){return Array.isArray(e)?e.filter(t=>typeof t=="string"):[]}function Qe(e){if(!e||typeof e!="object"||Array.isArray(e))return null;const t=e,s=t.kind==="image"||t.kind==="glyph"?t.kind:null;return s&&typeof t.value=="string"?{kind:s,value:t.value}:null}function Xe(e){const t=e&&typeof e=="object"&&!Array.isArray(e)?e:{},s=ue(t.app_id);return{app_id:s,name:ue(t.name,s||"Unnamed app"),views:Ge(t.views),logo:Qe(t.logo)}}async function Ye(){return((await _("/api/apps")).items||[]).map(Xe).filter(t=>t.app_id)}function Ze(e){const t=new URLSearchParams({consumer_app_id:e});return _(`/api/apps/dependencies?${t.toString()}`)}function xe(e,t,s){return _("/api/apps/dependencies",{method:"POST",body:JSON.stringify({consumer_app_id:e,alias:t,provider_app_ids:s})})}function J(){return _("/api/settings/platform")}function et(e){return _("/api/providers/active",{method:"POST",body:JSON.stringify(e)})}function tt(e){return _("/api/providers/hosted/selection",{method:"POST",body:JSON.stringify(e)})}function st(e){return _("/api/providers/speech/selection",{method:"POST",body:JSON.stringify(e)})}function nt(e,t="settings_runtime_sessions_cleared"){return _("/api/settings/runtime-sessions/clear",{method:"POST",body:JSON.stringify({session_ids:e,reason:t})})}function at(){return _("/api/auth/logout",{method:"POST"})}function it(e){return _("/api/admin/persistence/migrations/dry-run",{method:"POST",body:JSON.stringify(e)})}function rt(e){return _("/api/admin/persistence/migrations/apply",{method:"POST",body:JSON.stringify(e)})}function ot(e){return _("/api/admin/users",{method:"POST",body:JSON.stringify(e)})}function dt(e,t){return _(`/api/admin/users/${encodeURIComponent(e)}`,{method:"PATCH",body:JSON.stringify(t)})}function lt(e,t){return _(`/api/admin/users/${encodeURIComponent(e)}/password`,{method:"POST",body:JSON.stringify({password:t})})}function ct(e){return _(`/api/admin/users/${encodeURIComponent(e)}`,{method:"DELETE"})}function pt(e,t){return _(`/api/admin/users/${encodeURIComponent(e)}/workspaces`,{method:"PUT",body:JSON.stringify({memberships:t})})}function ut(e){return _(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"POST",body:JSON.stringify({source_id:e.source_id,enabled:!0})})}function mt(e,t){return _(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"PATCH",body:JSON.stringify({status:t?"enabled":"disabled"})})}function gt(e){return _(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"DELETE",body:JSON.stringify({})})}function ae(e){const t=e?.provider.active_provider,s=e?.provider.model_settings;return $e(t,s,oe(e))}function oe(e){const t=e?.provider.active_provider,s=e?.provider.model_settings;return we(t,s)}function ft(e){const t=e?.provider.hosted_text?.active_provider||null,s=e?.provider.hosted_text?.model_settings||null;return $e(t,s,de(e))}function de(e){const t=e?.provider.hosted_text||null,s=t?.active_provider||null;return(t?.available_providers?.length?t.available_providers:s?[s]:[]).flatMap(a=>{const i=a.provider_id===s?.provider_id&&t?.model_settings||null;return we(a,i).map(r=>({...r,metadata:{...r.metadata||{},hosted_provider_id:a.provider_id,hosted_provider_label:a.label||a.provider_id,hosted_provider_status:a.status}}))})}function $e(e,t,s){const n=t?.selected_model_id||e?.default_model_family||"",a=s.find(i=>i.model_id===n)||null;return{modelId:n,reasoningEffort:t?.selected_reasoning_effort||ke(a)}}function we(e,t){const s=t?.selected_model_id||e?.default_model_family||"",n=te(t?.available_models).length?te(t?.available_models):te(e?.model_options);return(n.length?n:s?[ht(s,t?.selected_reasoning_effort||"")]:[]).map(vt)}function ke(e){return e?.default_reasoning_effort||e?.supported_reasoning_efforts[0]?.effort||""}function te(e){return(e||[]).filter(t=>t.model_id)}function vt(e){return e.supported_reasoning_efforts.length||!e.default_reasoning_effort?e:{...e,supported_reasoning_efforts:[{effort:e.default_reasoning_effort,label:e.default_reasoning_effort,description:null}]}}function ht(e,t){return{model_id:e,label:e,description:null,default_reasoning_effort:t||null,supported_reasoning_efforts:t?[{effort:t,label:t,description:null}]:[]}}const _t=new Set(["created","running","stopping"]);function bt(){return{cleanupError:"",clearingAllRuntime:!1,cleaningSessionIds:new Set,draftModelId:"",draftReasoningEffort:"",hostedDraftModelId:"",hostedProviderError:"",hostedProviderErrorModelId:"",hostedRoutingDraftsByModel:{},isSavingHostedProvider:!1,isSavingProvider:!1,isSavingSpeechProvider:!1,providerError:"",speechAudioModelId:"",speechConversationModelId:"",speechProviderError:""}}function K(e,t){const{modelId:s,reasoningEffort:n}=ae(t),{modelId:a}=ft(t),i=Pt(t),r=new Set(de(t).map(o=>o.model_id).filter(Boolean));a&&r.add(a),e.draftModelId=s,e.draftReasoningEffort=n,e.hostedDraftModelId=a,e.speechAudioModelId=i.audioModelId,e.speechConversationModelId=i.conversationModelId,e.hostedRoutingDraftsByModel=Object.fromEntries(Array.from(r).map(o=>[o,x(Z(t,o))]))}function yt(e,t,s){const n=oe(t).find(a=>a.model_id===s)||null;e.draftModelId=s,e.draftReasoningEffort=ke(n),e.providerError=""}function $t(e,t,s){e.hostedDraftModelId=s,Re(e,t,s),e.hostedProviderError="",e.hostedProviderErrorModelId=""}function wt(e,t){e.speechAudioModelId=t,e.speechProviderError=""}function kt(e,t){e.speechConversationModelId=t,e.speechProviderError=""}function St(e,t,s,n,a){if(!s)return;const i=Re(e,t,s);e.hostedDraftModelId=s,n==="mode"&&typeof a=="string"&&["auto","prefer","only","ignore"].includes(a)?i.mode=a:n==="provider_id"&&typeof a=="string"?i.providerId=a:n==="allow_fallbacks"&&typeof a=="boolean"?i.allowFallbacks=a:n==="require_parameters"&&typeof a=="boolean"?i.requireParameters=a:n==="sort"&&typeof a=="string"&&["","price","throughput","latency"].includes(a)?i.sort=a:n==="data_collection"&&typeof a=="string"&&["","allow","deny"].includes(a)?i.dataCollection=a:n==="quantization"&&typeof a=="string"&&(i.quantization=a),e.hostedProviderError="",e.hostedProviderErrorModelId=""}function Se(e,t=e.hostedDraftModelId){const s=e.hostedRoutingDraftsByModel[t]||zt();return{mode:s.mode,provider_id:s.providerId||void 0,allow_fallbacks:s.allowFallbacks,require_parameters:s.requireParameters,sort:s.sort,data_collection:s.dataCollection,quantizations:s.quantization?[s.quantization]:[]}}function Pt(e){const t=e?.provider.speech_stt||null,s=t?.active_provider||t?.available_providers?.find(i=>i.provider_id==="deepgram")||null,n=G(t,s,"prerecorded_transcription"),a=G(t,s,"conversational_streaming");return{audioModelId:t?.model_settings?.audio_transcription_model_id||n.find(i=>i.model_id==="nova-3")?.model_id||n[0]?.model_id||"nova-3",conversationModelId:t?.model_settings?.conversation_model_id||a.find(i=>i.model_id==="flux-general-multi")?.model_id||a[0]?.model_id||"flux-general-multi"}}function Et(e,t){if(!e)return`<section class="settings-card settings-platform">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Settings</p>
          <h2>Platform settings</h2>
        </div>
      </div>
      <p class="settings-card-copy">Platform settings are not available from the active backend.</p>
    </section>`;const s=e.provider.active_provider,n=e.provider.hosted_text?.active_provider||null,a=e.provider.speech_stt||null,i=Bt(e),r=i.filter(b=>_t.has(b.status)),o=e.runtime.cleanup_allowed??!1,c=e.runtime.cleanup_scope||"none",m=oe(e),v=de(e),C=v.filter(Ee),S=v.filter(qt),M=ae(e).modelId,R=ae(e).reasoningEffort,p=(m.find(b=>b.model_id===t.draftModelId)||m[0]||null)?.supported_reasoning_efforts||[],g=Ft(e,t),y=!!(s&&t.draftModelId&&!t.isSavingProvider&&(t.draftModelId!==M||t.draftReasoningEffort!==R));return`${Mt(e)}
    ${At(s,m,p,y,r.length,i.length,!1,t)}
    ${It(g,C,n,e,t)}
    ${Ct(S,g,n,a,e,t)}
    ${Ut(i,o,c,t)}`}function Mt(e){return`<section class="settings-card settings-platform settings-user-settings-card">
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
        <h3>${d(e.user.display_name||e.user.username||"Unavailable")}</h3>
        <p>${d(e.user.platform_role||"member")} · ${d(e.workspace.name||e.workspace.workspace_id)}</p>
        <button type="button" class="settings-secondary settings-platform-logout" id="settings-logout">
          <span class="material-symbols-rounded" aria-hidden="true">logout</span>
          Logout
        </button>
      </div>
    </article>
  </section>`}function It(e,t,s,n,a){return`<section class="settings-card settings-platform settings-hosted-text-model-settings-card">
    ${le("route","Hosted text model settings")}
    ${Pe({modelOptions:t,openHostedModel:e,hostedProvider:s,settings:n,state:a,emptyMessage:"No hosted text models are available from the active hosted providers.",inactiveMessage:"Activate a hosted text provider before selecting a fast model."})}
  </section>`}function le(e,t){return`<div class="settings-heading settings-platform-heading settings-model-card-heading">
    <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">${d(e)}</span>
      <div>
        <p class="settings-kicker">Models</p>
        <h2>${d(t)}</h2>
      </div>
    </div>`}function At(e,t,s,n,a,i,r,o){return`<section class="settings-card settings-platform settings-agentic-model-settings-card">
    ${le("memory","Agentic model settings")}
    <div class="settings-platform-provider-forms">
      ${Ht(e,t,s,n,a,i,r,o)}
    </div>
  </section>`}function Ct(e,t,s,n,a,i){return`<section class="settings-card settings-platform settings-speech-model-settings-card">
    ${le("record_voice_over","Speech model settings")}
    <div class="settings-platform-provider-forms">
      ${Pe({modelOptions:e,openHostedModel:t,hostedProvider:s,settings:a,state:i,emptyMessage:"No hosted speech models are available from the active hosted providers.",inactiveMessage:"Activate the hosted provider before saving speech model routing."})}
      ${Tt(n,i)}
    </div>
  </section>`}function Rt(e){document.getElementById("settings-provider-model")?.addEventListener("change",t=>{e.onProviderModelChanged(t.currentTarget.value)}),document.getElementById("settings-provider-reasoning")?.addEventListener("change",t=>{e.onProviderReasoningChanged(t.currentTarget.value)}),document.getElementById("settings-speech-audio-model")?.addEventListener("change",t=>{e.onSpeechAudioModelChanged(t.currentTarget.value)}),document.getElementById("settings-speech-conversation-model")?.addEventListener("change",t=>{e.onSpeechConversationModelChanged(t.currentTarget.value)}),document.querySelectorAll("[data-speech-save]").forEach(t=>{t.addEventListener("click",()=>{e.onSaveSpeechProviderSettings()})}),document.getElementById("settings-speech-save")?.addEventListener("click",()=>{e.onSaveSpeechProviderSettings()}),document.querySelectorAll("[data-settings-model-accordion]").forEach(t=>{t.addEventListener("toggle",()=>{t.open&&document.querySelectorAll("[data-settings-model-accordion]").forEach(s=>{s!==t&&(s.open=!1)})})}),document.querySelectorAll("[data-openrouter-routing]").forEach(t=>{t.addEventListener("change",s=>{const n=s.currentTarget,a=n.dataset.hostedModelId||n.closest("[data-hosted-model-accordion]")?.dataset.hostedModelAccordion||"";e.onHostedProviderRoutingChanged(a,n.dataset.openrouterRouting||"",n instanceof HTMLInputElement&&n.type==="checkbox"?n.checked:n.value)})}),document.getElementById("settings-save-provider")?.addEventListener("click",e.onSaveProviderSettings),document.querySelectorAll("[data-hosted-provider-save]").forEach(t=>{t.addEventListener("click",()=>e.onSaveHostedProviderSettings(t.dataset.hostedProviderSave||""))}),document.getElementById("settings-logout")?.addEventListener("click",e.onLogout),document.getElementById("settings-clear-all-runtime")?.addEventListener("click",e.onClearAllRuntimeSessions),document.querySelectorAll("[data-runtime-clear]").forEach(t=>{t.addEventListener("click",()=>e.onClearRuntimeSession(t.dataset.runtimeClear||""))})}function Ht(e,t,s,n,a,i,r,o){return`<details class="settings-model-accordion settings-agentic-provider-accordion" data-settings-model-accordion="agentic-provider" data-agentic-provider-accordion >
    <summary class="settings-model-trigger">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">memory</span>
      <span class="settings-model-copy">
        <span class="settings-model-kicker">
          <span class="settings-kicker">Agentic provider</span>
        </span>
        <strong>${d(e?.label||"Provider not loaded")}</strong>
        <small>${d(o.draftModelId||"model")} · ${d(o.draftReasoningEffort||"reasoning")} · Codex tools/filesystem/MCP · ${a} active / ${i} in scope</small>
      </span>
      <span class="settings-model-chevron material-symbols-rounded" aria-hidden="true">expand_more</span>
    </summary>
    <div class="settings-model-content settings-agentic-provider-content">
    <label class="settings-platform-field">
      <span>Model</span>
      <select id="settings-provider-model" ${!t.length||o.isSavingProvider?"disabled":""}>
        ${t.map(c=>`<option value="${h(c.model_id)}" ${c.model_id===o.draftModelId?"selected":""}>${d(c.label||c.model_id)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Reasoning</span>
      <select id="settings-provider-reasoning" ${!s.length||o.isSavingProvider?"disabled":""}>
        ${s.map(c=>`<option value="${h(c.effort)}" ${c.effort===o.draftReasoningEffort?"selected":""}>${d(c.label||c.effort)}</option>`).join("")}
      </select>
    </label>
    <button type="button" id="settings-save-provider" ${n?"":"disabled"}>
      <span class="material-symbols-rounded" aria-hidden="true">${o.isSavingProvider?"sync":"save"}</span>
      ${o.isSavingProvider?"Saving":"Save model"}
    </button>
    ${o.providerError?`<p class="settings-platform-error">${d(o.providerError)}</p>`:""}
    </div>
  </details>`}function Pe({modelOptions:e,openHostedModel:t,hostedProvider:s,settings:n,state:a,emptyMessage:i,inactiveMessage:r}){const o=!!s,c=Ot(e,s);return`<div class="settings-hosted-models">
    ${e.length?c.map(m=>Dt(m,t,s,n,a)).join(""):`<p class="settings-card-copy settings-platform-note">${d(i)}</p>`}
    ${o?"":`<p class="settings-card-copy settings-platform-note">${d(r)}</p>`}
  </div>`}function Dt(e,t,s,n,a){const i=e.providerStatus==="active"?"Active provider":"Inactive provider";return`<section class="settings-hosted-provider-group" data-hosted-provider-group="${h(e.providerId)}">
    <div class="settings-hosted-provider-heading">
      <span>
        <strong>${d(e.providerLabel)}</strong>
        <small>${e.models.length} ${e.models.length===1?"model":"models"}</small>
      </span>
      <span class="settings-pill">${d(i)}</span>
    </div>
    ${e.models.map(r=>Lt(r,t,s,n,a)).join("")}
  </section>`}function Lt(e,t,s,n,a){const i=e.model_id,r=jt(a,n,i),o=e.upstream_provider_options||[],c=o.length>0,m=Array.from(new Set(o.map($=>$.quantization||"").filter(Boolean))),v=Me(e,s),C=Ae(e,s),S=!!v,M=a.isSavingHostedProvider&&a.hostedDraftModelId===i,R=n.provider.hosted_text?.selection?.provider_id||s?.provider_id||"",L=v===R&&(n.provider.hosted_text?.model_settings?.selected_model_id||s?.default_model_family)||"",p=!!(S&&C==="active"&&i&&!a.isSavingHostedProvider&&(v!==R||i!==L||Ce(a,n,i))),g=Ee(e),y=g?"Hosted chat / fast model":"Hosted speech model",b=g?"plain hosted chat capable · runtime engine remains Codex":"speech synthesis metadata · not used by plain hosted chat",u=g?"bolt":"record_voice_over",H=i===t,je=Ie(e,s);return`<details class="settings-model-accordion settings-hosted-model-accordion" data-settings-model-accordion="hosted:${h(i)}" data-hosted-model-accordion="${h(i)}" ${H?"open":""}>
    <summary class="settings-model-trigger">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">${u}</span>
      <span class="settings-model-copy">
        <span class="settings-model-kicker">
          <span class="settings-kicker">${y}</span>
        </span>
        <strong>${d(e.label||i)} - ${d(je)}</strong>
        <small>${d(i||"model not selected")} · ${b}</small>
      </span>
      <span class="settings-model-chevron material-symbols-rounded" aria-hidden="true">expand_more</span>
    </summary>
    <div class="settings-model-content settings-hosted-model-content">
      <div class="settings-platform-field settings-platform-field-wide">
        <span>Model</span>
        <code class="settings-model-code">${d(i||"model not selected")}</code>
      </div>
    ${c?`
    <label class="settings-platform-field">
      <span>OpenRouter upstream</span>
      <select data-openrouter-routing="mode" data-hosted-model-id="${h(i)}" ${!S||!o.length||a.isSavingHostedProvider?"disabled":""}>
        ${[["auto","Auto"],["prefer","Prefer selected"],["only","Only selected"],["ignore","Ignore selected"]].map(([$,j])=>`<option value="${h($)}" ${$===r.mode?"selected":""}>${d(j)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Upstream provider</span>
      <select data-openrouter-routing="provider_id" data-hosted-model-id="${h(i)}" ${!S||!o.length||r.mode==="auto"||a.isSavingHostedProvider?"disabled":""}>
        <option value="">Select provider</option>
        ${o.map($=>`<option value="${h(String($.provider_id||$.tag||""))}" ${($.provider_id||$.tag)===r.providerId?"selected":""}>${d($.label||$.provider_id||$.tag||"Provider")}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Sort</span>
      <select data-openrouter-routing="sort" data-hosted-model-id="${h(i)}" ${!S||a.isSavingHostedProvider?"disabled":""}>
        ${[["","OpenRouter default"],["price","Price"],["throughput","Throughput"],["latency","Latency"]].map(([$,j])=>`<option value="${h($)}" ${$===r.sort?"selected":""}>${d(j)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Data collection</span>
      <select data-openrouter-routing="data_collection" data-hosted-model-id="${h(i)}" ${!S||a.isSavingHostedProvider?"disabled":""}>
        ${[["","OpenRouter default"],["allow","Allow"],["deny","Deny"]].map(([$,j])=>`<option value="${h($)}" ${$===r.dataCollection?"selected":""}>${d(j)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Quantization</span>
      <select data-openrouter-routing="quantization" data-hosted-model-id="${h(i)}" ${!S||!m.length||a.isSavingHostedProvider?"disabled":""}>
        <option value="">Any</option>
        ${m.map($=>`<option value="${h($)}" ${$===r.quantization?"selected":""}>${d($)}</option>`).join("")}
      </select>
    </label>
    <div class="settings-platform-checks">
      <label><input type="checkbox" data-openrouter-routing="allow_fallbacks" data-hosted-model-id="${h(i)}" ${r.allowFallbacks?"checked":""} ${!S||a.isSavingHostedProvider?"disabled":""}> Allow OpenRouter fallback</label>
      <label><input type="checkbox" data-openrouter-routing="require_parameters" data-hosted-model-id="${h(i)}" ${r.requireParameters?"checked":""} ${!S||a.isSavingHostedProvider?"disabled":""}> Require supported parameters</label>
    </div>
    `:""}
    <button type="button" data-hosted-provider-save="${h(i)}" ${p?"":"disabled"}>
      <span class="material-symbols-rounded" aria-hidden="true">${M?"sync":"save"}</span>
      ${M?"Saving":"Save hosted model"}
    </button>
    ${a.hostedProviderError&&a.hostedProviderErrorModelId===i?`<p class="settings-platform-error">${d(a.hostedProviderError)}</p>`:""}
    </div>
  </details>`}function Ot(e,t){const s=new Map;for(const n of e){const a=Me(n,t)||"hosted-provider",i=s.get(a);if(i){i.models.push(n);continue}s.set(a,{providerId:a,providerLabel:Ie(n,t),providerStatus:Ae(n,t),models:[n]})}return Array.from(s.values()).sort((n,a)=>n.providerStatus==="active"&&a.providerStatus!=="active"?-1:a.providerStatus==="active"&&n.providerStatus!=="active"?1:n.providerLabel.localeCompare(a.providerLabel))}function Ee(e){const t=e.output_modalities||[];return!t.length||t.includes("text")}function qt(e){return(e.output_modalities||[]).includes("speech")}function Me(e,t){const s=e.metadata?.hosted_provider_id;return typeof s=="string"&&s?s:t?.provider_id||""}function Ie(e,t){const s=e.metadata?.hosted_provider_label;return typeof s=="string"&&s?s:t?.label||t?.provider_id||"Hosted provider"}function Ae(e,t){const s=e.metadata?.hosted_provider_status;return typeof s=="string"&&s?s:t?.status||""}function Tt(e,t){const s=e?.active_provider||e?.available_providers?.find(y=>y.provider_id==="deepgram")||null,n=G(e,s,"prerecorded_transcription"),a=G(e,s,"conversational_streaming"),i=e?.model_settings?.audio_transcription_model_id||n[0]?.model_id||"nova-3",r=e?.model_settings?.conversation_model_id||a[0]?.model_id||"flux-general-multi",o=t.speechAudioModelId||i,c=t.speechConversationModelId||r,m=n.find(y=>y.model_id===o)||n[0]||null,v=a.find(y=>y.model_id===c)||a[0]||null,C=ge(m,e?.model_settings?.endpoints?.audio_transcription||`https://api.deepgram.com/v1/listen?model=${o}`),S=ge(v,e?.model_settings?.endpoints?.conversation||`wss://api.deepgram.com/v2/listen?model=${c}`),M=!!(e?.active_provider&&e?.credential_binding),R=!!(M&&o&&c&&!t.isSavingSpeechProvider&&(o!==i||c!==r)),L=s?.label||s?.provider_id||"Deepgram",p=s?.provider_id||"deepgram",g=M?"Active provider":"Inactive provider";return`<div class="settings-hosted-models settings-speech-models">
    <section class="settings-hosted-provider-group" data-speech-provider-group="${h(p)}">
      <div class="settings-hosted-provider-heading">
        <span>
          <strong>${d(L)}</strong>
          <small>2 settings</small>
        </span>
        <span class="settings-pill">${d(g)}</span>
      </div>
      ${me({id:"settings-speech-audio-model",label:"Audio transcription model",icon:"hearing",value:o,options:n,endpoint:C,description:m?.description||"Deepgram model for prerecorded audio, files, and one-shot microphone transcription.",disabled:!M||t.isSavingSpeechProvider,canSave:R,isSaving:t.isSavingSpeechProvider})}
      ${me({id:"settings-speech-conversation-model",label:"Conversation model",icon:"forum",value:c,options:a,endpoint:S,description:v?.description||"Deepgram Flux model for realtime voice conversation and turn detection.",disabled:!M||t.isSavingSpeechProvider,canSave:R,isSaving:t.isSavingSpeechProvider})}
    </section>
    ${t.speechProviderError?`<p class="settings-platform-error">${d(t.speechProviderError)}</p>`:""}
    ${M?"":'<p class="settings-card-copy settings-platform-note">Activate Deepgram with a Core Secrets binding before using speech-to-text.</p>'}
  </div>`}function me({id:e,label:t,icon:s,value:n,options:a,endpoint:i,description:r,disabled:o,canSave:c,isSaving:m}){return a.length?`<details class="settings-model-accordion settings-speech-model-accordion">
    <summary class="settings-model-trigger">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">${d(s)}</span>
      <span class="settings-model-copy">
        <span class="settings-model-kicker">
          <span class="settings-kicker">${d(t)}</span>
        </span>
        <strong>${d(a.find(v=>v.model_id===n)?.label||n)}</strong>
        <small>${d(n)} · ${d(i)}</small>
      </span>
      <span class="settings-model-chevron material-symbols-rounded" aria-hidden="true">expand_more</span>
    </summary>
    <div class="settings-model-content settings-hosted-model-content">
      <label class="settings-platform-field settings-platform-field-wide">
        <span>${d(t)}</span>
        <select id="${h(e)}" ${o?"disabled":""}>
          ${a.map(v=>`<option value="${h(v.model_id)}" ${v.model_id===n?"selected":""}>${d(v.label||v.model_id)}</option>`).join("")}
        </select>
      </label>
      <div class="settings-platform-field settings-platform-field-wide">
        <span>Endpoint</span>
        <code class="settings-model-code">${d(i)}</code>
      </div>
      <p class="settings-card-copy">${d(r)}</p>
      <button type="button" data-speech-save="${h(e)}" ${c?"":"disabled"}>
        <span class="material-symbols-rounded" aria-hidden="true">${m?"sync":"save"}</span>
        ${m?"Saving":"Save speech model"}
      </button>
    </div>
  </details>`:`<p class="settings-card-copy settings-platform-note">No ${d(t.toLowerCase())} options are available.</p>`}function G(e,t,s){const n=s==="prerecorded_transcription"?e?.model_settings?.available_audio_transcription_models:e?.model_settings?.available_conversation_models;return n?.length?n:(e?.model_settings?.available_models?.length?e.model_settings.available_models:t?.model_options||[]).filter(i=>i.metadata?.purpose===s)}function ge(e,t){const s=e?.metadata?.endpoint;return typeof s=="string"&&s?s:t}function Ut(e,t,s,n){return`<section class="settings-card settings-platform settings-runtime-settings-card">
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
      ${e.length?e.map(i=>Nt(i,t,n)).join(""):'<p class="settings-card-copy">No runtime sessions.</p>'}
    </div>
    ${n.cleanupError?`<p class="settings-platform-error">${d(n.cleanupError)}</p>`:""}
  </details>
  </section>`}function Nt(e,t,s){const n=s.cleaningSessionIds.has(e.session_id);return`<div class="settings-platform-runtime-row">
    <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">terminal</span>
    <span class="settings-platform-runtime-copy">
      <span class="settings-platform-runtime-title">
        <strong>${d(e.agent_id||e.session_id)}</strong>
        <button type="button" class="settings-secondary settings-platform-runtime-clear" data-runtime-clear="${h(e.session_id)}" aria-label="Clean runtime session ${h(e.agent_id||e.session_id)}" ${!t||s.clearingAllRuntime||n?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">${n?"sync":"delete_sweep"}</span>
          <span class="settings-platform-runtime-clear-label">${n?"Cleaning":"Clean"}</span>
        </button>
      </span>
      <small>${d(e.workspace_name||e.workspace_id)} · ${d(e.effective_mode)} · ${d(e.status)}</small>
      <code>${d(e.session_id)}</code>
    </span>
  </div>`}function Bt(e){return e.runtime.all_sessions||e.runtime.sessions||[]}function Z(e,t){const s=e?.provider.hosted_text?.selection?.openrouter_provider_routing_by_model?.[t];return{mode:s?.mode||"auto",provider_id:s?.provider_id||"",allow_fallbacks:s?.allow_fallbacks!==!1,require_parameters:s?.require_parameters===!0,sort:s?.sort||"",data_collection:s?.data_collection||"",quantizations:s?.quantizations||[]}}function Ce(e,t,s){const n=Z(t,s),a=Se(e,s);return n.mode!==a.mode||(n.provider_id||"")!==(a.provider_id||"")||n.allow_fallbacks!==!1!=(a.allow_fallbacks!==!1)||n.require_parameters===!0!=(a.require_parameters===!0)||(n.sort||"")!==(a.sort||"")||(n.data_collection||"")!==(a.data_collection||"")||(n.quantizations?.[0]||"")!==(a.quantizations?.[0]||"")}function Ft(e,t){return t.hostedProviderErrorModelId?t.hostedProviderErrorModelId:!t.hostedDraftModelId||!Ce(t,e,t.hostedDraftModelId)?"":t.hostedDraftModelId}function jt(e,t,s){return e.hostedRoutingDraftsByModel[s]||x(Z(t,s))}function Re(e,t,s){return e.hostedRoutingDraftsByModel[s]||(e.hostedRoutingDraftsByModel[s]=x(Z(t,s))),e.hostedRoutingDraftsByModel[s]}function x(e){return{allowFallbacks:e.allow_fallbacks!==!1,dataCollection:e.data_collection||"",mode:e.mode||"auto",providerId:e.provider_id||"",quantization:e.quantizations?.[0]||"",requireParameters:e.require_parameters===!0,sort:e.sort||""}}function zt(){return x({mode:"auto",allow_fallbacks:!0,require_parameters:!1,sort:"",data_collection:"",quantizations:[]})}function d(e){return e.replace(/[&<>"']/g,t=>t==="&"?"&amp;":t==="<"?"&lt;":t===">"?"&gt;":t==='"'?"&quot;":"&#39;")}function h(e){return d(e)}const Wt=5,Jt=4,Kt=4,Vt=3,Gt=4;function Qt(e){return`<section class="settings-loading-skeleton" role="status" aria-label="Settings content is loading">
    <header class="detail-header settings-loading-skeleton__header" aria-hidden="true">
      <div class="detail-title-block">
        ${f("title")}
        <span class="detail-title-separator" aria-hidden="true"></span>
        ${f("subtitle")}
      </div>
    </header>
    ${Xt(e)}
  </section>`}function Xt(e){return e.id==="workspace-access"?Zt():e.id==="workspace-apps"?xt():e.id==="platform-settings"?es():e.id==="persistence"?ts():Yt()}function Yt(){return`<section class="settings-card settings-loading-skeleton__create" aria-hidden="true">
      ${ss("short-title")}
      ${O(Wt,()=>E("field"))}
      ${E("button")}
    </section>
    ${He()}
    <div class="settings-loading-skeleton__profile-row" aria-hidden="true">
      <section class="settings-card settings-loading-skeleton__detail-card">
        ${z(!0)}
        <div class="settings-loading-skeleton__field-grid">
          ${O(Jt,()=>Q())}
        </div>
        ${E("toggle")}
        ${E("button")}
      </section>
      <section class="settings-card settings-loading-skeleton__password-card">
        ${z(!1)}
        ${f("copy")}
        <div class="settings-loading-skeleton__field-grid">
          ${O(2,()=>Q())}
        </div>
        ${E("button")}
        ${E("danger-button")}
      </section>
    </div>`}function Zt(){return`${He()}
    <section class="settings-card" aria-hidden="true">
      ${z(!0)}
      <div class="settings-loading-skeleton__rows">
        ${O(Kt,()=>ns())}
      </div>
    </section>`}function xt(){return`<section class="settings-card" aria-hidden="true">
      ${z(!1)}
      ${f("copy-wide")}
      <div class="settings-loading-skeleton__rows">
        ${O(Vt,()=>as())}
      </div>
    </section>`}function es(){return`<section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
      ${se()}
    </section>
    <section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
      ${se()}
      <div class="settings-loading-skeleton__provider-form">
        ${O(2,()=>Q())}
        ${E("button")}
      </div>
      ${se()}
    </section>
    <section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
      <div class="settings-loading-skeleton__runtime-toolbar">
        ${f("copy-wide")}
        ${E("button")}
      </div>
      <div class="settings-loading-skeleton__runtime-list">
        ${O(Gt,()=>is())}
      </div>
    </section>`}function ts(){return`<section class="settings-card settings-loading-skeleton__persistence" aria-hidden="true">
      ${z(!0)}
      <div class="settings-loading-skeleton__adapter-cards">
        ${O(2,()=>rs())}
      </div>
      ${os()}
    </section>`}function He(){return`<section class="settings-card settings-user-picker" aria-hidden="true">
    <div class="settings-loading-skeleton__copy-stack">
      ${f("kicker")}
      ${f("card-title")}
      ${f("copy-short")}
    </div>
    ${Q()}
  </section>`}function z(e){return`<div class="settings-loading-skeleton__heading">
    <span class="settings-loading-skeleton__copy-stack">
      ${f("kicker")}
      ${f("card-title")}
    </span>
    ${e?E("pill"):""}
  </div>`}function ss(e){return`<div class="settings-loading-skeleton__copy-stack">
    ${f("kicker")}
    ${f(e)}
  </div>`}function Q(){return`<span class="settings-loading-skeleton__field-wrap">
    ${f("label")}
    ${E("field")}
  </span>`}function ns(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--membership">
    ${E("checkbox")}
    ${F("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${f("row-title")}
      ${f("row-copy")}
    </span>
    ${E("select")}
  </span>`}function as(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--app">
    ${F("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${f("row-title")}
      ${f("row-copy")}
    </span>
    ${E("toggle-pill")}
    ${E("button")}
  </span>`}function se(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--tile">
    ${F("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${f("row-title")}
      ${f("row-copy")}
    </span>
  </span>`}function is(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--runtime">
    ${F("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${f("row-title")}
      ${f("row-copy")}
    </span>
    ${E("button")}
  </span>`}function rs(){return`<span class="settings-loading-skeleton__adapter-card">
    ${F("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${f("row-title")}
      ${f("row-copy-wide")}
    </span>
    ${E("pill")}
  </span>`}function os(){return`<span class="settings-loading-skeleton__result">
    ${F("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${f("row-title")}
      ${f("row-copy-wide")}
    </span>
  </span>`}function f(e){return`<span class="settings-loading-skeleton__line settings-loading-skeleton__line--${e}"></span>`}function E(e){return`<span class="settings-loading-skeleton__block settings-loading-skeleton__block--${e}"></span>`}function F(e){return`<span class="settings-loading-skeleton__icon settings-loading-skeleton__icon--${e}"></span>`}function O(e,t){return Array.from({length:e},t).join("")}function ds({publishChanged:e,render:t,setNotice:s}){let n=[],a=[],i="",r=[],o="",c=!1,m=new Set;function v(){return{appRegistry:n,dependencies:a,error:i,isLoading:c,loadErrors:r,savingKeys:m}}function C(){n=[],a=[],i="",r=[],o=""}function S(){o=""}async function M(p,g,y=!1){if(!(!p||c)&&!(!y&&o===p)){c=!0,i="",r=[],t();try{const[b,u]=await Promise.all([Ye(),L(p,g)]);n=b,a=u,o=p}catch(b){a=[],o="",i=b instanceof Error?b.message:"Unable to load app links."}finally{c=!1,t()}}}async function R(p,g,y){const b=ls(p,g);m=new Set([...m,b]),t();try{const u=await xe(p,g,y);a=a.map(H=>H.consumer_app_id===p?u:H),e(p,u),s({tone:"success",message:"App link updated."})}finally{const u=new Set(m);u.delete(b),m=u,t()}}async function L(p,g){const y=g.filter(u=>u.workspace_id===p&&u.status==="enabled"),b=await Promise.all(y.map(async u=>{try{return{app:u,payload:await Ze(u.app_id)}}catch(H){return{app:u,error:H instanceof Error?H.message:"Unable to load app links."}}}));return r=b.filter(u=>"error"in u).map(u=>({app_id:u.app.app_id,message:u.error,name:u.app.name||u.app.app_id})),b.filter(u=>"payload"in u&&u.payload.dependencies.length>0).map(u=>u.payload).sort((u,H)=>u.consumer_app_id.localeCompare(H.consumer_app_id))}return{ensureLoaded:M,invalidate:S,reset:C,saveDependencySelection:R,viewState:v}}function ls(e,t){return`${e}:${t}`}function l(e){return e.replace(/[&<>"']/g,t=>t==="&"?"&amp;":t==="<"?"&lt;":t===">"?"&gt;":t==='"'?"&quot;":"&#39;")}function k(e){return l(e)}function cs({appRegistry:e,dependencies:t,error:s,isLoading:n,loadErrors:a,savingKeys:i,workspaceApps:r}){return`<section class="settings-card settings-app-links">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">App links</p>
          <h2>Provider app links</h2>
        </div>
      </div>
      <p class="settings-card-copy">Provider links are workspace-scoped. A selected provider is reused until it becomes unavailable; otherwise one-provider interface links use the first available candidate as their automatic default.</p>
      ${s?`<p class="settings-platform-error">${l(s)}</p>`:""}
      ${a.length?`<div class="settings-app-link-errors">${a.map(_s).join("")}</div>`:""}
      ${t.length>1?ps(t,e,r):""}
      <div class="settings-app-link-list">
        ${t.length?t.map(o=>us(o,e,r,i)).join(""):gs(s,n)}
      </div>
    </section>`}function ps(e,t,s){return`<nav class="settings-app-link-consumer-nav" aria-label="Provider link apps">
    ${e.map(n=>{const a=s.find(o=>o.workspace_id===n.workspace_id&&o.app_id===n.consumer_app_id),i=ce(t,n.consumer_app_id),r=a?.name||i?.name||n.consumer_app_id;return`<a class="settings-app-link-consumer-nav__item" href="#${k(De(n.consumer_app_id))}">
        <strong>${l(r)}</strong>
        <small>${l(String(n.dependencies.length))}</small>
      </a>`}).join("")}
  </nav>`}function us(e,t,s,n){const a=s.find(r=>r.workspace_id===e.workspace_id&&r.app_id===e.consumer_app_id),i=ce(t,e.consumer_app_id);return`<article class="settings-app-link-consumer" id="${k(De(e.consumer_app_id))}">
    <header class="settings-app-link-consumer__header">
      ${Oe(i,e.consumer_app_id)}
      <span class="settings-app-copy">
        <strong>${l(a?.name||e.consumer_app_id)}</strong>
        <small>${l(e.consumer_app_id)} - ${l(e.status)}</small>
      </span>
    </header>
    <div class="settings-app-link-dependencies">
      ${e.dependencies.map(r=>ms(e.consumer_app_id,r,t,n)).join("")}
    </div>
  </article>`}function ms(e,t,s,n){const a=n.has(fs(e,t.alias)),i=vs(t),r=Le(t);return`<section class="settings-app-link-row">
    <header class="settings-app-link-row__header">
      <span class="settings-app-link-row__copy">
        <strong>${l(t.alias)}</strong>
        <small>${l(t.interface)} ${l(t.version)}</small>
      </span>
      <span class="settings-pill ${t.status==="resolved"||r?"":"settings-pill-muted"}">${l(hs(t,r))}</span>
    </header>
    <p class="settings-card-copy">${l(t.description||"No description.")}</p>
    ${t.blocked_reason?`<p class="settings-platform-error">${l(t.blocked_reason)}</p>`:""}
    ${t.stale_provider_app_ids.length?`<p class="settings-platform-error">Unavailable selection: ${l(t.stale_provider_app_ids.join(", "))}</p>`:""}
    ${t.candidates.length?`<div class="settings-app-link-candidates">
            ${t.candidates.map(o=>{const c=i.includes(o.app_id),m=t.cardinality==="many"?"checkbox":"radio",v=`dependency:${e}:${t.alias}`,C=ce(s,o.app_id);return`<label class="settings-app-link-candidate ${c?"is-selected":""}">
                <input
                  ${c?"checked":""}
                  ${a?"disabled":""}
                  data-dependency-choice="${k(fe(e,t.alias,o.app_id))}"
                  name="${k(v)}"
                  type="${m}"
                />
                ${Oe(C,o.app_id)}
                <span>
                  <strong>${l(o.name||o.app_id)}</strong>
                  <small>${l(o.app_id)} - ${l(o.interface_version)}${o.app_id===r?" - automatic default":""}</small>
                </span>
              </label>`}).join("")}
          </div>`:'<p class="settings-card-copy">No enabled provider app is available for this interface.</p>'}
    ${r?`<button type="button" class="settings-secondary" data-dependency-save-default="${k(fe(e,t.alias,r))}" ${a?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">${a?"sync":"save"}</span>
          ${a?"Saving":"Save default"}
        </button>`:""}
  </section>`}function gs(e,t){return e?"":t?'<p class="settings-card-copy">Loading app links...</p>':'<p class="settings-card-copy">No enabled app in the active workspace declares provider links.</p>'}function fs(e,t){return`${e}:${t}`}function fe(e,t,s){return`${e}:${t}:${s}`}function De(e){return`settings-app-link-consumer-${e}`}function vs(e){if(e.selected_provider_app_ids.length)return e.selected_provider_app_ids;const t=Le(e);return t?[t]:[]}function Le(e){return e.selected_provider_app_ids.length||e.status!=="optional_unset"||e.cardinality!=="one"||e.stale_provider_app_ids.length||e.blocked_reason?"":e.candidates[0]?.app_id||""}function hs(e,t){return t?"auto default":e.status==="optional_unset"?"unset":e.status}function ce(e,t){return e.find(s=>s.app_id===t)||null}function _s(e){return`<p class="settings-platform-error">${l(e.name||e.app_id)}: ${l(e.message)}</p>`}function Oe(e,t){if(e?.logo?.kind==="image"&&e.logo.value)return`<span class="settings-app-link-logo is-image"><img alt="" loading="lazy" src="${k(e.logo.value)}" /></span>`;const s=e?.logo?.value||bs(e,t);return`<span class="settings-app-link-logo is-glyph"><span class="material-symbols-rounded" aria-hidden="true">${l(s)}</span></span>`}function bs(e,t){const s={agents:"smart_toy","app-store":"storefront","base-shell":"dashboard",chat:"forum",checklist:"checklist",crm:"contacts","developer-kit":"developer_board","docs-studio":"description","document-generator":"description","dynamic-views":"dashboard_customize","gmail-app":"mail",memory:"database","maverick-monitor":"monitor_heart",settings:"admin_panel_settings",skills:"school",speech:"record_voice_over",storage:"cloud","website-studio":"web_asset"};return s[t]?s[t]:e?.views.includes("chat")?"forum":e?.views.includes("agents")?"smart_toy":e?.views.includes("shell")?"dashboard":"apps"}function ys(e){document.getElementById("dismiss-notice")?.addEventListener("click",e.dismissNotice),document.getElementById("create-user")?.addEventListener("submit",s=>{s.preventDefault(),e.createUser(s.currentTarget).catch(e.showError)});const t=e.selectedUser();document.getElementById("selected-user")?.addEventListener("change",s=>{e.selectUser(s.currentTarget.value)}),document.getElementById("edit-user")?.addEventListener("submit",s=>{s.preventDefault(),t&&e.updateSelectedUser(s.currentTarget,t).catch(e.showError)}),document.getElementById("reset-password")?.addEventListener("submit",s=>{s.preventDefault(),t&&e.resetSelectedUserPassword(s.currentTarget,t).catch(e.showError)}),document.getElementById("delete-user")?.addEventListener("click",()=>{t&&e.deleteSelectedUser(t).catch(e.showError)}),document.getElementById("save-memberships")?.addEventListener("click",()=>{t&&e.updateMemberships(t).catch(e.showError)}),ws(e),$s(e),ks(e),Rt({onClearAllRuntimeSessions:()=>{e.clearRuntimeSessionsFromPanel().catch(e.showError)},onClearRuntimeSession:s=>{s&&e.clearRuntimeSessionsFromPanel([s]).catch(e.showError)},onLogout:()=>{e.logoutFromSettings().catch(e.showError)},onHostedProviderRoutingChanged:e.onHostedProviderRoutingChanged,onProviderModelChanged:e.onProviderModelChanged,onProviderReasoningChanged:e.onProviderReasoningChanged,onSpeechAudioModelChanged:e.onSpeechAudioModelChanged,onSpeechConversationModelChanged:e.onSpeechConversationModelChanged,onSaveHostedProviderSettings:s=>{e.saveHostedProviderSettingsFromPanel(s).catch(e.showError)},onSaveProviderSettings:()=>{e.saveProviderSettingsFromPanel().catch(e.showError)},onSaveSpeechProviderSettings:()=>{e.saveSpeechProviderSettingsFromPanel().catch(e.showError)}})}function $s(e){document.querySelectorAll("[data-dependency-choice]").forEach(t=>{t.addEventListener("change",()=>{const s=ve(t.dataset.dependencyChoice||"");if(!s)return;const n=e.appDependencies().find(i=>i.consumer_app_id===s.consumerAppId)?.dependencies.find(i=>i.alias===s.alias);if(!n)return;if(n.cardinality==="one"){e.saveDependencySelection(s.consumerAppId,s.alias,[s.providerAppId]).catch(e.showError);return}const a=new Set(n.selected_provider_app_ids);t.checked?a.add(s.providerAppId):a.delete(s.providerAppId),e.saveDependencySelection(s.consumerAppId,s.alias,Array.from(a)).catch(e.showError)})}),document.querySelectorAll("[data-dependency-save-default]").forEach(t=>{t.addEventListener("click",()=>{const s=ve(t.dataset.dependencySaveDefault||"");s&&e.saveDependencySelection(s.consumerAppId,s.alias,[s.providerAppId]).catch(e.showError)})})}function ve(e){const[t,s,...n]=e.split(":"),a=n.join(":");return!t||!s||!a?null:{alias:s,consumerAppId:t,providerAppId:a}}function ws(e){document.querySelectorAll("[data-app-toggle]").forEach(t=>{t.addEventListener("change",()=>{const s=e.workspaceApps().find(n=>`${n.workspace_id}:${n.app_id}`===t.dataset.appToggle);s&&e.setWorkspaceAppStatus(s,t.checked).catch(e.showError)})}),document.querySelectorAll("[data-app-install]").forEach(t=>{t.addEventListener("click",()=>{const s=e.workspaceApps().find(n=>`${n.workspace_id}:${n.app_id}`===t.dataset.appInstall);s&&e.installWorkspaceApp(s).catch(e.showError)})}),document.querySelectorAll("[data-app-uninstall]").forEach(t=>{t.addEventListener("click",()=>{const s=e.workspaceApps().find(n=>`${n.workspace_id}:${n.app_id}`===t.dataset.appUninstall);s&&e.uninstallWorkspaceApp(s).catch(e.showError)})})}function ks(e){document.querySelectorAll("[data-adapter-target]").forEach(t=>{t.addEventListener("click",()=>{const s=t.dataset.adapterTarget;(s==="json"||s==="mongo")&&e.persistenceController.prepare(s).catch(e.showError)})}),document.getElementById("close-migration-modal")?.addEventListener("click",()=>{e.persistenceController.cancel()}),document.getElementById("cancel-migration")?.addEventListener("click",()=>{e.persistenceController.cancel()}),document.getElementById("validate-migration")?.addEventListener("click",()=>{e.persistenceController.validateDraft().catch(e.showError)}),document.querySelectorAll("[data-migration-field]").forEach(t=>{const s=n=>{const a=t.dataset.migrationField;if(a&&a in(e.persistenceController.viewState().targetDraft||{})){const i=!!e.persistenceController.viewState().migrationPlan;e.persistenceController.updateDraft(a,t.value,{render:n}),!n&&i&&Ss()}};t.addEventListener("input",()=>s(!1)),t.addEventListener("change",()=>s(!0))}),document.getElementById("settings-delete-source")?.addEventListener("change",t=>{e.persistenceController.setDeleteSource(t.currentTarget.checked)}),document.getElementById("confirm-migration")?.addEventListener("click",()=>{e.persistenceController.apply().catch(e.showError)})}function Ss(){const e=document.getElementById("confirm-migration");e&&(e.disabled=!0);const t=document.querySelector(".settings-migration-plan");if(!t)return;const s=t.querySelector(".material-symbols-rounded"),n=t.querySelector("strong"),a=t.querySelector("small");s&&(s.textContent="rule"),n&&(n.textContent="Dry run changed"),a&&(a.textContent="Validate the dry run again before applying migration."),t.querySelector(".settings-migration-collections")?.remove()}function Ps(e){let t=null,s=null,n="",a=null,i=null,r=null,o=!1;function c(){return{deleteSourceAfterMigration:o,migrationPlan:a,migrationProgress:r,migrationResult:i,migrationTarget:t,persistence:e.getPersistence(),targetDraft:s}}async function m(p){const g=e.getPersistence();if(!g||g.active_adapter.kind===p){S();return}t=p,s=Es(p,g),n="",a=null,o=!1,r=null,e.setNotice(null),e.render()}function v(p,g,y={}){s&&(s={...s,[p]:g},a=null,n="",r=null,y.render!==!1&&e.render())}function C(p){o=p,e.render()}function S(){t=null,s=null,a=null,n="",r=null,e.render()}async function M(){if(!(!s||!t)){r={target:t,phase:"validating",percent:10,title:`Dry run to ${t.toUpperCase()}`,detail:"Validating target adapter and collection copy plan before applying changes."},e.setNotice(null),e.render();try{const p=ie(s);a=await it(p),n=he(p)}catch(p){throw r=null,a=null,n="",p}r=null,a.same_adapter&&e.setNotice({tone:"info",message:"The selected persistence adapter is already active."}),e.render()}}async function R(){if(!s||!t)return;const p=ie(s),g=he(p);if(!a||n!==g){await M();return}if(a.same_adapter)return;r={target:t,phase:"applying",percent:38,title:`Migration to ${t.toUpperCase()}`,detail:"Copying the validated control-plane plan to the target adapter."},e.setNotice(null),e.render();try{i=await rt({...p,delete_source:o,restart_backend:!0})}catch(b){throw r={target:t,phase:"failed",percent:100,title:"Migration failed",detail:b instanceof Error?b.message:"Unable to apply migration."},b}const y=t;t=null,s=null,a=null,n="",r={target:y,phase:"restarting",percent:68,title:"Restart backend",detail:i.backend_restart?.detail||"Backend restart scheduled."},e.render(),await L(y)}async function L(p){const g=Date.now(),y=9e4;for(;Date.now()-g<y;){r={target:p,phase:"polling",percent:84,title:"Verifying cutover",detail:"Waiting for the backend to become healthy with the new adapter."},e.render();const b=await e.requestPersistenceStatusQuiet();if(b?.active_adapter.kind===p){e.setPersistence(b);const u=i?.source_cleanup?.scheduled===!0;r={target:p,phase:"complete",percent:100,title:"Migration complete",detail:u?`Active adapter: ${p.toUpperCase()}. Source cleanup is scheduled after health check.`:`Active adapter: ${p.toUpperCase()}. Source storage was preserved.`},e.setNotice({tone:"success",message:`Migration to ${p.toUpperCase()} complete.`}),e.render();return}await new Promise(u=>window.setTimeout(u,1500))}r={target:p,phase:"failed",percent:100,title:"Verification not completed",detail:"The backend did not confirm the new adapter before the timeout. Check service health and logs."},e.setNotice({tone:"error",message:"Migration not confirmed before the timeout."}),e.render()}return{apply:R,cancel:S,prepare:m,setDeleteSource:C,updateDraft:v,validateDraft:M,viewState:c}}function Es(e,t){const s=t.active_adapter;return{kind:e,json_root:s.json_root||"data/control-plane/json",mongodb_uri:s.mongo_uri||"mongodb://127.0.0.1:27017/maverick",mongodb_database:s.mongo_database||"maverick",mongodb_username:s.mongo_username||"",mongodb_password_ref:s.mongo_password_ref||""}}function ie(e){return{kind:e.kind,json_root:e.json_root.trim()||"data/control-plane/json",mongodb_uri:e.mongodb_uri.trim(),mongodb_database:e.mongodb_database.trim()||"maverick",mongodb_username:e.mongodb_username?.trim()||void 0,mongodb_password_ref:e.mongodb_password_ref?.trim()||void 0}}function he(e){return JSON.stringify(ie(e))}function Ms(e){return Cs(e)}function Is(e){const{deleteSourceAfterMigration:t,migrationPlan:s,migrationProgress:n,migrationTarget:a,persistence:i}=e;if(!a||!i)return"";const r=i.active_adapter.kind.toUpperCase(),o=a.toUpperCase(),c=!!(n&&!["complete","failed"].includes(n.phase)),m=!!(s&&!s.same_adapter&&!c);return`<div class="settings-modal-backdrop" role="presentation">
    <section class="settings-modal" role="dialog" aria-modal="true" aria-labelledby="adapter-migration-title">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Confirm migration</p>
          <h2 id="adapter-migration-title">${r} → ${o}</h2>
        </div>
        <button type="button" class="settings-icon-button" id="close-migration-modal" aria-label="Close" ${c?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">close</span>
        </button>
      </div>
      ${s?Ls(s):Ds(n)}
      ${As(e)}
      <label class="settings-toggle settings-migration-delete-source">
        <input id="settings-delete-source" type="checkbox" ${t?"checked":""} ${c?"disabled":""} />
        Schedule source cleanup after restart health check
      </label>
      <p class="settings-card-copy">Leave cleanup off to preserve the current source adapter data as a rollback point. Cleanup is a separate explicit choice and requires backend restart.</p>
      <div class="settings-modal-actions">
        <button type="button" class="settings-secondary" id="cancel-migration" ${c?"disabled":""}>Cancel</button>
        <button type="button" class="settings-secondary" id="validate-migration" ${c?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">rule</span>
          Validate dry run
        </button>
        <button type="button" class="${t?"settings-danger":"settings-secondary"}" id="confirm-migration" ${m?"":"disabled"}>
          <span class="material-symbols-rounded" aria-hidden="true">sync_alt</span>
          ${t?"Apply and schedule cleanup":"Apply migration"}
        </button>
      </div>
    </section>
  </div>`}function As(e){const t=e.targetDraft;if(!t)return"";const s=!!(e.migrationProgress&&!["complete","failed"].includes(e.migrationProgress.phase));return`<div class="settings-migration-target">
    <label class="settings-platform-field">
      <span>JSON root</span>
      <input data-migration-field="json_root" value="${k(t.json_root)}" ${s?"disabled":""} />
    </label>
    ${t.kind==="mongo"?`<label class="settings-platform-field">
          <span>Mongo URI</span>
          <input data-migration-field="mongodb_uri" value="${k(t.mongodb_uri)}" ${s?"disabled":""} />
        </label>
        <label class="settings-platform-field">
          <span>Mongo database</span>
          <input data-migration-field="mongodb_database" value="${k(t.mongodb_database)}" ${s?"disabled":""} />
        </label>
        <label class="settings-platform-field">
          <span>Mongo username</span>
          <input data-migration-field="mongodb_username" value="${k(t.mongodb_username||"")}" ${s?"disabled":""} />
        </label>
        <label class="settings-platform-field">
          <span>Password secret ref</span>
          <input data-migration-field="mongodb_password_ref" value="${k(t.mongodb_password_ref||"")}" ${s?"disabled":""} />
        </label>`:""}
  </div>`}function Cs(e){const{migrationProgress:t,migrationResult:s,persistence:n}=e;if(!n)return`<section class="settings-card settings-persistence">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Persistence</p>
          <h2>Control plane adapter</h2>
        </div>
        <span class="settings-pill settings-pill-muted">offline</span>
      </div>
      <p class="settings-card-copy">The core persistence surfaces are not available in the active backend.</p>
    </section>`;const a=n.active_adapter,i=n.collections.reduce((m,v)=>m+v.count,0),r=a.kind==="json",o=a.kind==="mongo",c=t&&!["complete","failed"].includes(t.phase);return`<section class="settings-card settings-persistence">
    <div class="settings-heading">
      <div>
        <p class="settings-kicker">Persistence</p>
        <h2>Control plane adapter</h2>
      </div>
      <span class="settings-pill">${i} documents</span>
    </div>
    <div class="settings-adapter-cards">
      <button type="button" class="settings-adapter-card ${r?"is-active":""}" ${r||c?"disabled":'data-adapter-target="json"'}>
        <span class="settings-adapter-card-icon material-symbols-rounded" aria-hidden="true">${r?"check_circle":"database"}</span>
        <span>
          <strong>JSON</strong>
          <small>${l(r?a.json_root:"data/control-plane/json")}</small>
        </span>
        <em>${r?"Current":"Review migration"}</em>
      </button>
      <button type="button" class="settings-adapter-card ${o?"is-active":""}" ${o||c?"disabled":'data-adapter-target="mongo"'}>
        <span class="settings-adapter-card-icon material-symbols-rounded" aria-hidden="true">${o?"check_circle":"database"}</span>
        <span>
          <strong>Mongo</strong>
          <small>${l(o?a.mongo_database:"mongodb://127.0.0.1:27017/maverick")}</small>
        </span>
        <em>${o?"Current":"Review migration"}</em>
      </button>
    </div>
    ${Rs(t)}
    ${Hs(s)}
  </section>`}function Rs(e){return e?`<div class="settings-migration-progress ${e.phase==="failed"?"is-failed":""} ${e.phase==="complete"?"is-complete":""}">
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
  </div>`:""}function Hs(e){return e?`<div class="settings-migration-result">
    <span class="material-symbols-rounded" aria-hidden="true">task_alt</span>
    <span>
      <strong>Last migration</strong>
      <small>${e.collections.reduce((s,n)=>s+n.count,0)} documents · target ${l(e.target_adapter.kind)} · cleanup ${e.source_cleanup?.scheduled?"scheduled":"not requested"}</small>
    </span>
  </div>`:""}function Ds(e){return`<div class="settings-migration-plan">
    <span class="material-symbols-rounded" aria-hidden="true">rule</span>
    <span>
      <strong>${l(e?.title||"Dry run not validated")}</strong>
      <small>${l(e?.detail||"Adjust the target fields, then validate the dry run before applying migration.")}</small>
    </span>
  </div>`}function Ls(e){const t=e.collections.reduce((n,a)=>n+a.count,0),s=e.target_collections.reduce((n,a)=>n+a.count,0);return`<div class="settings-migration-plan">
    <span class="material-symbols-rounded" aria-hidden="true">${e.same_adapter?"block":"rule"}</span>
    <span>
      <strong>${e.same_adapter?"Target already active":"Dry run complete"}</strong>
      <small>${t} source documents · ${s} target documents before copy · env ${l(e.env_file)}</small>
    </span>
    <div class="settings-migration-collections">
      ${e.collections.map(n=>`<span><strong>${l(n.name)}</strong><small>${n.count}</small></span>`).join("")}
    </div>
  </div>`}async function Os(e){const t=e.settings?.provider.active_provider?.provider_id;if(!t||!e.state.draftModelId){e.state.providerError="Provider not loaded.",e.render();return}e.state.isSavingProvider=!0,e.state.providerError="",e.render();try{await et({provider_id:t,model_id:e.state.draftModelId,model_reasoning_effort:e.state.draftReasoningEffort||null});const s=await J();e.setSettings(s),K(e.state,s),e.setNotice({tone:"success",message:"Provider settings updated."})}catch(s){e.state.providerError=s instanceof Error?s.message:"Unable to update provider settings."}finally{e.state.isSavingProvider=!1,e.render()}}async function qs(e){const t=Ts(e.settings,e.state.hostedDraftModelId);if(!t||!e.state.hostedDraftModelId){e.state.hostedProviderErrorModelId=e.state.hostedDraftModelId,e.state.hostedProviderError="Hosted provider not loaded.",e.render();return}e.state.isSavingHostedProvider=!0,e.state.hostedProviderError="",e.state.hostedProviderErrorModelId=e.state.hostedDraftModelId,e.render();try{await tt({provider_id:t,model_id:e.state.hostedDraftModelId,openrouter_provider_routing:Se(e.state,e.state.hostedDraftModelId)});const s=await J();e.setSettings(s),K(e.state,s),e.setNotice({tone:"success",message:"Hosted model settings updated."})}catch(s){e.state.hostedProviderErrorModelId=e.state.hostedDraftModelId,e.state.hostedProviderError=s instanceof Error?s.message:"Unable to update hosted model settings."}finally{e.state.isSavingHostedProvider=!1,e.render()}}function Ts(e,t){const s=e?.provider.hosted_text||null;return[s?.active_provider,...s?.available_providers||[]].filter(Boolean).find(i=>!i||i.status!=="active"?!1:(i.model_options||[]).some(r=>r.model_id===t))?.provider_id||s?.active_provider?.provider_id||""}async function Us(e){const t=e.settings?.provider.speech_stt?.active_provider?.provider_id;if(!t||!e.state.speechAudioModelId||!e.state.speechConversationModelId){e.state.speechProviderError="Speech provider not loaded.",e.render();return}e.state.isSavingSpeechProvider=!0,e.state.speechProviderError="",e.render();try{await st({provider_id:t,audio_transcription_model_id:e.state.speechAudioModelId,conversation_model_id:e.state.speechConversationModelId});const s=await J();e.setSettings(s),K(e.state,s),e.setNotice({tone:"success",message:"Speech model settings updated."})}catch(s){e.state.speechProviderError=s instanceof Error?s.message:"Unable to update speech model settings."}finally{e.state.isSavingSpeechProvider=!1,e.render()}}function Ns({pendingDeleteUserId:e,selectedUser:t,users:s}){return`<form class="settings-card settings-create" id="create-user">
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
    ${qe(s,t)}
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
              <label>Name<input name="display_name" value="${k(t.display_name||"")}" /></label>
              <label>Email<input name="email" type="email" value="${k(t.email||"")}" /></label>
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
        </div>`:'<section class="settings-card"><h2>No users</h2></section>'}`}function Bs({selectedUser:e,users:t,workspaces:s}){return`${qe(t,e)}
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
          <div class="settings-memberships">${Fs(e,s)}</div>
        </section>`:'<section class="settings-card"><h2>No users</h2></section>'}`}function qe(e,t){return e.length?`<section class="settings-card settings-user-picker">
    <div>
      <p class="settings-kicker">User directory</p>
      <h2>${l(t?t.display_name||t.username:"Select user")}</h2>
      <p class="settings-card-copy">${e.length} user${e.length===1?"":"s"} available.</p>
    </div>
    <label class="settings-platform-field">
      <span>Selected user</span>
      <select id="selected-user">
        ${e.map(s=>`<option value="${k(s.user_id)}" ${s.user_id===t?.user_id?"selected":""}>${l(s.display_name||s.username)} (${l(s.username)})</option>`).join("")}
      </select>
    </label>
  </section>`:`<section class="settings-card settings-user-picker">
      <div>
        <p class="settings-kicker">User directory</p>
        <h2>No users</h2>
      </div>
      <p class="settings-card-copy">Create a user before editing profile or workspace access settings.</p>
    </section>`}function Fs(e,t){return t.map(s=>{const n=e.memberships.find(a=>a.workspace_id===s.workspace_id);return`<label class="settings-membership">
        <input type="checkbox" data-workspace-enabled="${k(s.workspace_id)}" ${n?"checked":""} />
        <span class="settings-membership-icon material-symbols-rounded" aria-hidden="true">workspaces</span>
        <span>
          <strong>${l(s.name)}</strong>
          <small>${l(s.workspace_id)}</small>
        </span>
        <select data-workspace-role="${k(s.workspace_id)}">
          <option value="member" ${n?.role!=="admin"?"selected":""}>Member</option>
          <option value="admin" ${n?.role==="admin"?"selected":""}>Workspace admin</option>
        </select>
      </label>`}).join("")}function js({workspaceApps:e,workspaces:t}){return`<section class="settings-card">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Workspace apps</p>
          <h2>Installation and visibility</h2>
        </div>
      </div>
      <p class="settings-card-copy">Installed means the app has a workspace binding. Only enabled apps are visible to users and served by the core.</p>
      <div class="settings-app-workspaces">${zs(t,e)}</div>
    </section>`}function zs(e,t){return e.map(s=>{const n=t.filter(r=>r.workspace_id===s.workspace_id),a=n.filter(r=>r.status==="enabled").length,i=n.filter(r=>r.installed).length;return`<details class="settings-app-workspace">
        <summary class="settings-app-workspace-heading">
          <span class="settings-summary-caret material-symbols-rounded" aria-hidden="true">chevron_right</span>
          <span class="settings-app-workspace-icon material-symbols-rounded" aria-hidden="true">deployed_code</span>
          <span>
            <strong>${l(s.name)}</strong>
            <small>${l(s.workspace_id)} · ${a}/${i} enabled</small>
          </span>
        </summary>
        <div class="settings-apps">
          ${n.map(Ws).join("")}
        </div>
      </details>`}).join("")}function Ws(e){const t=e.status==="enabled",s=e.installed,n=s?e.status:"not installed",a=`${e.workspace_id}:${e.app_id}`;return`<div class="settings-app-row">
    <span class="settings-app-icon material-symbols-rounded" aria-hidden="true">${l(Js(e))}</span>
    <span class="settings-app-copy">
      <strong>${l(e.name)}</strong>
      <small>${l(e.app_id)} · v${l(e.version)} · ${l(n)}</small>
    </span>
    ${s?`<label class="settings-switch">
          <input type="checkbox" data-app-toggle="${k(a)}" ${t?"checked":""} />
          <span>Enabled</span>
        </label>
        <button type="button" class="settings-secondary" data-app-uninstall="${k(a)}">
          <span class="material-symbols-rounded" aria-hidden="true">link_off</span>
          Uninstall
        </button>`:`<button type="button" class="settings-secondary" data-app-install="${k(a)}">
          <span class="material-symbols-rounded" aria-hidden="true">add_link</span>
          Install
        </button>`}
  </div>`}function Js(e){return e.status!=="enabled"?"hide_source":{agents:"smart_toy","app-store":"storefront","base-shell":"dashboard",browser:"language",calendar:"calendar_month",chat:"forum",checklist:"checklist",crm:"contacts","developer-kit":"developer_board","docs-studio":"description","document-generator":"description","dynamic-views":"dashboard_customize","gmail-app":"mail",mail:"mail",memory:"database","maverick-monitor":"monitor_heart",settings:"admin_panel_settings",senses:"sensors",skills:"school",speech:"record_voice_over",storage:"cloud",vault:"key","website-studio":"web_asset"}[e.app_id]||"apps"}let q=[],X=[],W=[],re=null,A=null,P=bt();const Te=Object.fromEntries(new URLSearchParams(window.location.search).entries());let Y=ye(Te)||ze,D=Ne(Te),N=!0,B="",I=null,_e="",be="";const pe=Ps({getPersistence:()=>re,render:()=>w(),requestPersistenceStatusQuiet:Xs,setNotice:e=>{I=e},setPersistence:e=>{re=e}}),T=ds({publishChanged:cn,render:()=>w(),setNotice:e=>{I=e}});function Ue(){return q.find(e=>e.user_id===D)||q[0]}function Ne(e){const t=V(e.user_id)||V(e.selected_user_id)||V(e.id);if(t)return t;const s=V(e.app_page),n=/^users\/([^/?#]+)$/.exec(s);if(!n?.[1])return"";try{return decodeURIComponent(n[1])}catch{return n[1]}}function V(e){return typeof e=="string"?e.trim():""}function Ks(e){const t=ye(e),s=Ne(e);let n=!1;t&&t!==Y&&(Y=t,n=!0),s&&s!==D&&(D=s,B="",n=!0),n&&((q.length||N)&&w(),t==="app-links"&&Be())}function Vs(e){e.id===_e||window.parent===window||(_e=e.id,window.parent.postMessage({type:"maverick.app.selection-changed",owner_app_id:"settings",selection:{page_id:e.id}},window.location.origin))}function Gs(e){!e||e.user_id===be||window.parent===window||(be=e.user_id,window.parent.postMessage({type:"maverick.app.selection-changed",owner_app_id:"settings",selection:{user_id:e.user_id}},window.location.origin))}function ee(){window.parent!==window&&window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"settings",resource:"users"},window.location.origin)}async function Qs(){try{return await _("/api/admin/persistence")}catch(e){return I={tone:"error",message:e instanceof Error?e.message:"Persistence API unavailable"},null}}async function Xs(){try{return await _("/api/admin/persistence")}catch{return null}}async function Ys(){try{return await J()}catch{return null}}async function U(){N=!0,w();try{const[e,t,s,n,a]=await Promise.all([Je(),Ke(),Ve(),Qs(),Ys()]),i=A?.workspace.workspace_id||"",r=a?.workspace.workspace_id||"";q=e,X=t,W=s,re=n,A=a,i!==r&&T.reset(),K(P,A),(!D||!q.some(o=>o.user_id===D))&&(D=q[0]?.user_id||"")}finally{N=!1}w(),Y==="app-links"&&Be()}async function Be(e=!1){const t=A?.workspace.workspace_id||"";await T.ensureLoaded(t,W,e)}async function Zs(e){const t=new FormData(e);D=(await ot({username:String(t.get("username")||""),password:String(t.get("password")||""),display_name:String(t.get("display_name")||""),email:String(t.get("email")||""),platform_role:String(t.get("platform_role")||"member")})).user_id,e.reset(),await U(),ee()}async function xs(e,t){const s=new FormData(e);await dt(t.user_id,{display_name:String(s.get("display_name")||""),email:String(s.get("email")||""),platform_role:String(s.get("platform_role")||"member"),account_type:String(s.get("account_type")||"standard"),is_active:s.get("is_active")==="on"}),await U(),ee()}async function en(e,t){const s=new FormData(e),n=String(s.get("password")||""),a=String(s.get("password_confirmation")||"");if(n!==a)throw new Error("Passwords do not match");await lt(t.user_id,n),e.reset(),I={tone:"success",message:"Password updated."},w()}async function tn(e){const t=e.display_name||e.username;if(B!==e.user_id){B=e.user_id,I={tone:"info",message:`Press Delete user again to confirm permanent removal of ${t}.`},w();return}await ct(e.user_id),D="",B="",I={tone:"success",message:`${t} deleted.`},await U(),ee()}async function sn(e){const t=X.map(s=>{const n=document.querySelector(`[data-workspace-enabled="${s.workspace_id}"]`),a=document.querySelector(`[data-workspace-role="${s.workspace_id}"]`);return n?.checked?{workspace_id:s.workspace_id,role:a?.value||"member"}:null}).filter(s=>!!s);await pt(e.user_id,t),await U(),ee()}async function nn(e){await ut(e),T.invalidate(),await U()}async function an(e,t){await mt(e,t),T.invalidate(),await U()}async function rn(e){await gt(e),T.invalidate(),await U()}async function on(e,t,s){await T.saveDependencySelection(e,t,s)}async function dn(e){const t=(e||[]).filter(Boolean);P.cleanupError="",t.length?t.forEach(s=>P.cleaningSessionIds.add(s)):P.clearingAllRuntime=!0,w();try{const s=await nt(t.length?t:void 0);ln(s),A=await J(),K(P,A),I={tone:"success",message:t.length?"Runtime session cleaned.":"Runtime sessions cleaned."}}catch(s){P.cleanupError=s instanceof Error?s.message:"Unable to clean runtime sessions."}finally{t.forEach(s=>P.cleaningSessionIds.delete(s)),P.clearingAllRuntime=!1,w()}}function ln(e){e.deleted_threads<=0||window.parent===window||(window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"chat",resource:"threads"},window.location.origin),e.deleted_thread_ids.forEach(t=>{window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"chat",resource:"threads",deleted_thread_id:t},window.location.origin)}))}function cn(e,t){window.parent!==window&&window.parent.postMessage({type:"maverick.app.dependencies-changed",app_id:e,status:t.status},window.location.origin)}async function pn(){if(window.parent&&window.parent!==window){window.parent.postMessage({type:"maverick.shell.logout"},window.location.origin);return}await at(),window.location.href="/"}function un(e,t){if(e.id==="users")return Ns({pendingDeleteUserId:B,selectedUser:t,users:q});if(e.id==="workspace-access")return Bs({selectedUser:t,users:q,workspaces:X});if(e.id==="workspace-apps")return js({workspaceApps:W,workspaces:X});if(e.id==="app-links"){const s=T.viewState();return cs({appRegistry:s.appRegistry,dependencies:s.dependencies,error:s.error,isLoading:s.isLoading,loadErrors:s.loadErrors,savingKeys:s.savingKeys,workspaceApps:W})}return e.id==="platform-settings"?mn():Ms(pe.viewState())}function mn(){return Et(A,P)}function w(){const e=document.getElementById("app"),t=N?void 0:Ue(),s=We(Y);e&&(e.innerHTML=`<main class="settings-shell">
    <section class="settings-main">
      <div class="settings-content">
        ${N?Qt(s):`<header class="detail-header">
          <div class="detail-title-block">
            <h2>${l(s.title)}</h2>
            <span class="detail-title-separator" aria-hidden="true"></span>
            <p>${l(s.summary)}</p>
          </div>
        </header>
        ${fn()}
        ${un(s,t)}`}
      </div>
    </section>
    ${Is(pe.viewState())}
  </main>`,gn(),Vs(s),N||Gs(t))}function gn(){ys({clearRuntimeSessionsFromPanel:dn,createUser:Zs,deleteSelectedUser:tn,dismissNotice:()=>{I=null,w()},installWorkspaceApp:nn,logoutFromSettings:pn,onHostedProviderRoutingChanged:(e,t,s)=>{St(P,A,e,t,s),w()},onProviderModelChanged:e=>{yt(P,A,e),w()},onProviderReasoningChanged:e=>{P.draftReasoningEffort=e,P.providerError="",w()},onSpeechAudioModelChanged:e=>{wt(P,e),w()},onSpeechConversationModelChanged:e=>{kt(P,e),w()},persistenceController:pe,render:w,resetSelectedUserPassword:en,saveDependencySelection:on,saveHostedProviderSettingsFromPanel:e=>(e&&$t(P,A,e),qs(ne())),saveProviderSettingsFromPanel:()=>Os(ne()),saveSpeechProviderSettingsFromPanel:()=>Us(ne()),selectedUser:Ue,selectUser:e=>{D=e,B="",w()},setWorkspaceAppStatus:an,showError:Fe,uninstallWorkspaceApp:rn,updateMemberships:sn,updateSelectedUser:xs,workspaceApps:()=>W,appDependencies:()=>T.viewState().dependencies})}function ne(){return{render:w,setNotice:e=>{I=e},setSettings:e=>{A=e},settings:A,state:P}}function Fe(e){I={tone:"error",message:e instanceof Error?e.message:"Unexpected error"},w()}function fn(){return I?`<div class="settings-notice settings-notice-${I.tone}">
    <span class="material-symbols-rounded" aria-hidden="true">${I.tone==="error"?"error":I.tone==="success"?"task_alt":"info"}</span>
    <span>${l(I.message)}</span>
    <button type="button" class="settings-icon-button" id="dismiss-notice" aria-label="Close">
      <span class="material-symbols-rounded" aria-hidden="true">close</span>
    </button>
  </div>`:""}window.addEventListener("message",e=>{if(e.origin!==window.location.origin||!e.data||typeof e.data!="object")return;const t=e.data;t.type==="maverick.app.navigate"&&(!t.app_id||t.app_id==="settings")&&Ks(t.params||{})});window.parent?.postMessage({type:"maverick.app.ready",app_id:"settings"},window.location.origin);U().catch(Fe);
