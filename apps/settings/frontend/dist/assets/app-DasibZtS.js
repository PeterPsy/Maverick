const __vite__mapDeps=(i,m=__vite__mapDeps,d=(m.f||(m.f=["assets/usageVisualizations-BfsyzMIn.js","assets/pages-DhW5MLpK.js"])))=>i.map(i=>d[i]);
import{i as ot,P as bs,a as ys,b as $s,s as Wt,D as ws,c as ks}from"./pages-DhW5MLpK.js";const Ss="modulepreload",Es=function(e){return"/apps/settings/"+e},ft={},Is=function(t,s,n){let a=Promise.resolve();if(s&&s.length>0){let c=function(o){return Promise.all(o.map(p=>Promise.resolve(p).then(u=>({status:"fulfilled",value:u}),u=>({status:"rejected",reason:u}))))};document.getElementsByTagName("link");const r=document.querySelector("meta[property=csp-nonce]"),l=r?.nonce||r?.getAttribute("nonce");a=c(s.map(o=>{if(o=Es(o),o in ft)return;ft[o]=!0;const p=o.endsWith(".css"),u=p?'[rel="stylesheet"]':"";if(document.querySelector(`link[href="${o}"]${u}`))return;const f=document.createElement("link");if(f.rel=p?"stylesheet":Ss,p||(f.as="script"),f.crossOrigin="",f.href=o,l&&f.setAttribute("nonce",l),document.head.appendChild(f),p)return new Promise(($,m)=>{f.addEventListener("load",$),f.addEventListener("error",()=>m(new Error(`Unable to preload CSS for ${o}`)))})}))}function i(r){const l=new Event("vite:preloadError",{cancelable:!0});if(l.payload=r,window.dispatchEvent(l),!l.defaultPrevented)throw r}return a.then(r=>{for(const l of r||[])l.status==="rejected"&&i(l.reason);return t().catch(i)})},Ce=new WeakSet,ne=new Map;function As(){ne.clear()}function Cs(e){const t=s=>{if(s.target instanceof Element){Ce.add(s.target);const n=s.target.closest("form, #workspace-assignments")?.querySelector("[data-action-status]");n&&(n.textContent="Unsaved changes")}};e.addEventListener("input",t,!0),e.addEventListener("change",t,!0)}function F(e){(typeof e=="string"?Array.from(document.querySelectorAll(e)):[e]).forEach(t=>{Ce.delete(t),t.querySelectorAll("[data-action-status]").forEach(s=>{s.textContent="",s.setAttribute("role","status")}),t.querySelectorAll("input, select, textarea").forEach(s=>Ce.delete(s))})}function Ms(e,t){const s=document.activeElement,n=s instanceof HTMLInputElement||s instanceof HTMLTextAreaElement?[s.selectionStart,s.selectionEnd]:null,a=document.createElement("template");a.innerHTML=t,Vt(e,a.content),s?.isConnected&&document.activeElement!==s&&(s.focus({preventScroll:!0}),n&&n[0]!==null&&n[1]!==null&&s.setSelectionRange(n[0],n[1]))}function x(e){return e instanceof Element?e.getAttribute("data-render-key")||e.id||["data-settings-model-accordion","data-hosted-model-accordion","data-runtime-row","data-workspace-row","data-app-row","data-dependency-row","data-agentic-provider-group","data-hosted-provider-group","data-execution-family"].map(t=>{const s=e.getAttribute(t);return s===null?"":`${t}:${s}`}).find(Boolean)||(e.classList.length?`${e.tagName}:${Array.from(e.classList).filter(t=>!t.startsWith("is-")).join(" ")}`:""):""}function Ne(e,t){return e.nodeType===t.nodeType&&e.nodeName===t.nodeName&&x(e)===x(t)}function Vt(e,t){let s=e.firstChild;for(const n of Array.from(t.childNodes)){if(s&&!Ne(s,n)&&x(n)){const a=Array.from(e.childNodes).find(i=>Ne(i,n))||ne.get(x(n));a&&(ne.delete(x(n)),e.insertBefore(a,s),s=a)}if(!s||!Ne(s,n)){const a=n.cloneNode(!0);if(e.insertBefore(a,s),s&&!x(s)){const i=s;s=s.nextSibling,i.remove()}continue}Ps(s,n),s=s.nextSibling}for(;s;){const n=s;s=s.nextSibling,n instanceof Element&&x(n).startsWith("page:")&&(ne.set(x(n),n),ne.size>12&&ne.delete(ne.keys().next().value)),e.removeChild(n)}}function Ps(e,t){if(!(e instanceof Element)||!(t instanceof Element)){e.nodeValue!==t.nodeValue&&(e.nodeValue=t.nodeValue);return}const s=Ce.has(e),n=e instanceof HTMLDetailsElement?e.open:void 0,a=s&&"value"in e?String(e.value):void 0,i=s&&e instanceof HTMLInputElement?e.checked:void 0;if(!e.matches("[data-action-status]")){for(const r of Array.from(e.attributes))e.hasAttribute("data-pending-action")&&["data-pending-action","aria-busy"].includes(r.name)||t.hasAttribute(r.name)||e.removeAttribute(r.name);for(const r of Array.from(t.attributes))e.getAttribute(r.name)!==r.value&&e.setAttribute(r.name,r.value);e.closest("[data-pending-action]")&&e.matches("input, button, select")&&e.setAttribute("disabled",""),!e.matches("[data-usage-history-chart], [data-usage-history-filters]")&&(Vt(e,t),e instanceof HTMLDetailsElement&&n!==void 0&&(e.open=n),e instanceof HTMLInputElement&&(e.value=a??t.value,e.checked=i??t.checked),(e instanceof HTMLSelectElement||e instanceof HTMLTextAreaElement)&&(e.value=a??t.value))}}let Ge=new AbortController;function qs(){Ge.abort(),Ge=new AbortController}function v(e,t,s){e?.addEventListener(t,s,{signal:Ge.signal})}async function D(e,t={}){const s=await fetch(e,{credentials:"same-origin",headers:{"Content-Type":"application/json",...t.headers||{}},...t}),n=await s.json();if(!s.ok)throw new Error(n.detail||n.error||`Request failed ${s.status}`);return n}function vt(e,t=""){return typeof e=="string"?e:t}function Ds(e){return Array.isArray(e)?e.filter(t=>typeof t=="string"):[]}function Rs(e){if(!e||typeof e!="object"||Array.isArray(e))return null;const t=e,s=t.kind==="image"||t.kind==="glyph"?t.kind:null;return s&&typeof t.value=="string"?{kind:s,value:t.value}:null}function Ts(e){const t=e&&typeof e=="object"&&!Array.isArray(e)?e:{},s=vt(t.app_id);return{app_id:s,name:vt(t.name,s||"Unnamed app"),views:Ds(t.views),logo:Rs(t.logo)}}async function Ls(){return((await D("/api/apps")).items||[]).map(Ts).filter(t=>t.app_id)}function lt(e){const t=new URLSearchParams({consumer_app_id:e});return D(`/api/apps/dependencies?${t.toString()}`)}function Jt(e,t,s){return D("/api/apps/dependencies",{method:"POST",body:JSON.stringify({consumer_app_id:e,alias:t,provider_app_ids:s})})}function ht(e="all"){return D(e==="all"?"/api/settings/platform":`/api/settings/platform?section=${e}`)}function Hs(){return D("/api/providers/usage")}function Us(e,t,s={}){const n=new URLSearchParams({resolution:e,periods:String(t)});return s.providerId&&n.set("provider_id",s.providerId),s.modelId&&n.set("model_id",s.modelId),D(`/api/usage/timeseries?${n.toString()}`)}function Os(e){return D("/api/providers/hosted/selection",{method:"POST",body:JSON.stringify(e)})}function Ns(e){return D("/api/providers/speech/selection",{method:"POST",body:JSON.stringify(e)})}function Bs(e){return D("/api/providers/agentic/workspace-bindings",{method:"POST",body:JSON.stringify(e)})}function js(e){return D("/api/providers/native/activate",{method:"POST",body:JSON.stringify({provider_id:e,confirmation:"native-runtime-reviewed"})})}function Fs(e,t="settings_runtime_sessions_cleared"){return D("/api/settings/runtime-sessions/clear",{method:"POST",body:JSON.stringify({session_ids:e,reason:t})})}function zs(){return D("/api/auth/logout",{method:"POST"})}function Ws(e){return D("/api/admin/persistence/migrations/dry-run",{method:"POST",body:JSON.stringify(e)})}function Vs(e){return D("/api/admin/persistence/migrations/apply",{method:"POST",body:JSON.stringify(e)})}function d(e){return e.replace(/[&<>"']/g,t=>t==="&"?"&amp;":t==="<"?"&lt;":t===">"?"&gt;":t==='"'?"&quot;":"&#39;")}function b(e){return d(e)}function Gt(){return{workspaceId:"",providerAppId:"",engines:[],engine:"",language:"auto",savedEngine:"",savedLanguage:"auto",loading:!1,saving:!1,loaded:!1,error:""}}const _t={logical_names:["openrouter-api-key","deepinfra-api-key","google-ai-studio-api-key"],required:!1};function Js(e){const t=e.state;let s=0;function n(){s+=1,Object.assign(t,Gt())}async function a(c,o=!1){if(!c||(t.workspaceId!==c&&n(),t.loading||t.saving||t.loaded&&!o))return;t.workspaceId=c;const p=++s;t.loading=!0,t.error="",e.render();try{const u=await lt("settings");if(p!==s)return;if(u.workspace_id!==c)throw new Error("The active workspace changed. Reload voice settings.");const $=u.dependencies.find(T=>T.alias==="text-to-speech")?.selected_provider_app_ids[0]||"";if(!$)throw new Error("Select a text-to-speech provider for Settings in App links.");const m=await D(`/api/apps/${encodeURIComponent($)}/backend`,{method:"POST",body:JSON.stringify({action:"engine_health",include_voices:!1,_app_secret_request:_t})});if(p!==s)return;t.providerAppId=$,i(m),t.loaded=!0}catch(u){p===s&&(t.error=u instanceof Error?u.message:"Unable to load text-to-speech settings.")}finally{p===s&&(t.loading=!1,e.render())}}function i(c,o=!1){t.engines=c.synthesis,(!t.loaded||o||t.engine===t.savedEngine)&&(t.engine=c.settings.synthesis_engine),(!t.loaded||o||t.language===t.savedLanguage)&&(t.language=c.settings.synthesis_language),t.savedEngine=c.settings.synthesis_engine,t.savedLanguage=c.settings.synthesis_language}async function r(){if(!t.providerAppId||t.saving||t.loading)return;const c=s;t.saving=!0,t.error="",e.render();try{const o=await D(`/api/apps/${encodeURIComponent(t.providerAppId)}/backend`,{method:"POST",body:JSON.stringify({action:"set_engine",synthesis_engine:t.engine,synthesis_language:t.language,_app_secret_request:_t})});if(c!==s)return;i(o.engines,!0),F(".settings-tts-group"),e.notify("Text-to-speech settings updated.")}catch(o){c===s&&(t.error=o instanceof Error?o.message:"Unable to save text-to-speech settings.")}finally{c===s&&(t.saving=!1,e.render())}}function l(){v(document.getElementById("settings-tts-discard"),"click",()=>{t.engine=t.savedEngine,t.language=t.savedLanguage,F(".settings-tts-group"),e.render()}),v(document.getElementById("settings-tts-engine"),"change",c=>{t.engine=c.currentTarget.value,t.error="",e.render()}),v(document.getElementById("settings-tts-language"),"input",c=>{t.language=c.currentTarget.value;const o=document.getElementById("settings-tts-discard");o&&(o.disabled=t.engine===t.savedEngine&&t.language===t.savedLanguage)}),v(document.getElementById("settings-tts-save"),"click",()=>{r()}),v(document.getElementById("settings-tts-retry"),"click",()=>{a(t.workspaceId,!0)})}return{load:a,save:r,reset:n,bind:l}}const Gs={auto:"Automatic local voice",piper:"Piper","espeak-ng":"eSpeak NG",espeak:"eSpeak","kokoro-openrouter":"Kokoro · OpenRouter","kokoro-deepinfra":"Kokoro · DeepInfra",gemini:"Gemini 3.8 Flash-Lite TTS"};function Ks(e){const t=e.engines.find(a=>a.engine===e.engine),s=e.loading||e.saving,n=[{engine:"auto",available:!0},...e.engines];return`<section class="settings-hosted-provider-group settings-tts-group" aria-labelledby="settings-tts-title">
    <div class="settings-heading"><div><p class="settings-kicker">Text to speech</p><h3 id="settings-tts-title">Read-aloud voice</h3></div></div>
    ${e.loading?'<p class="settings-card-copy" role="status">Loading voice settings…</p>':""}
    ${e.loaded?`<div class="settings-tts-controls">
      <label>Voice engine<select id="settings-tts-engine" ${s?"disabled":""}>
        ${n.map(a=>`<option value="${b(a.engine)}" ${a.engine===e.engine?"selected":""} ${!a.available&&a.engine!==e.engine?"disabled":""}>${d(Gs[a.engine]||a.engine)}${a.available?"":" · unavailable"}</option>`).join("")}
      </select></label>
      <label>Language<input id="settings-tts-language" list="settings-tts-languages" value="${b(e.language)}" ${s?"disabled":""} autocomplete="off" placeholder="auto or it-IT">
        <datalist id="settings-tts-languages"><option value="auto">Automatic</option><option value="it-IT">Italian</option><option value="en-US">English</option></datalist>
      </label>
    </div>
    ${t&&!t.available?`<p class="settings-platform-error">${d(t.detail||"The selected voice engine is unavailable.")}</p>`:""}
    <button type="button" class="settings-secondary" id="settings-tts-discard" ${s||e.engine===e.savedEngine&&e.language===e.savedLanguage?"disabled":""}>Discard edits</button>
    <button type="button" class="settings-secondary" id="settings-tts-save" ${s||e.engine!=="auto"&&!t?.available?"disabled":""}>${e.saving?"Saving…":"Save voice settings"}</button>`:""}
    ${e.error?`<p class="settings-platform-error" role="alert">${d(e.error)}</p><button type="button" class="settings-secondary" id="settings-tts-retry" ${s?"disabled":""}>Retry</button>`:""}
  </section>`}function Qs(){return{workspaceId:"",providerId:"",modelId:"",effort:"",executionMode:"delegated",fallbackModelId:"",fallbackEffort:"",saving:!1,error:"",generation:0,savedSelection:""}}function Ke(e,t,s=!1){const n=t?.computer_use,a=t?.workspace.workspace_id||"",i=e.workspaceId!==a,r=JSON.stringify([n?.provider_id,n?.model_id,n?.reasoning_effort,n?.execution_mode,n?.fallback_model_id,n?.fallback_reasoning_effort]);if(i&&(e.generation+=1,e.saving=!1,e.error=""),!i&&!s){if(e.savedSelection===r)return;const l=JSON.stringify([e.providerId||void 0,e.modelId||void 0,e.effort||void 0,e.executionMode,e.fallbackModelId||void 0,e.fallbackEffort||void 0]);if(e.savedSelection&&l!==e.savedSelection){e.savedSelection=r;return}}Object.assign(e,{workspaceId:a,providerId:n?.provider_id||"",modelId:n?.model_id||"",effort:n?.reasoning_effort||"",executionMode:n?.execution_mode||"delegated",fallbackModelId:n?.fallback_model_id||"",fallbackEffort:n?.fallback_reasoning_effort||"",savedSelection:r})}function Kt(e,t){return e?.computer_use?.providers.find(s=>s.provider_id===t.providerId)?.models.find(s=>s.model_id===t.modelId)}function Ys(e,t){const s=e.computer_use;if(!s)return"";const n=Kt(e,t),a=n?.supported_reasoning_efforts||[],i=a.length?a.some(c=>c.effort===t.effort):!t.effort,r=t.providerId!==s.provider_id||t.modelId!==s.model_id||t.effort!==(s.reasoning_effort||"")||t.executionMode!==(s.execution_mode||"delegated")||t.fallbackModelId!==(s.fallback_model_id||"")||t.fallbackEffort!==(s.fallback_reasoning_effort||""),l=!s.can_configure||t.saving;return`<section class="settings-card settings-platform" aria-labelledby="settings-computer-use-title">
    <div class="settings-heading settings-platform-heading settings-model-card-heading">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">desktop_windows</span>
      <div><p class="settings-kicker">Models</p><h2 id="settings-computer-use-title">PC use decision model</h2></div>
    </div>
    <p class="settings-card-copy">Use the chat model directly or a separate interface operator. Reconnect PC use after changing execution mode. Operator model changes apply to the next UI task.</p>
    ${t.modelId==="gpt-6-luna"&&t.effort==="low"&&t.executionMode==="delegated"?'<p class="settings-card-copy">Luna Low uses planned UI steps. Choose a recovery model for tasks that need broader navigation.</p>':""}
    <div class="settings-platform-provider-forms">
      <label class="settings-platform-field settings-platform-field-wide"><span>UI execution</span>
        <select id="settings-computer-use-mode" ${l?"disabled":""}>
          <option value="direct" ${t.executionMode==="direct"?"selected":""}>Chat model directly</option>
          <option value="delegated" ${t.executionMode==="delegated"?"selected":""}>Separate interface operator</option>
        </select>
      </label>
      ${t.executionMode==="delegated"||!n||!i?`<label class="settings-platform-field settings-platform-field-wide"><span>Decision model</span>
        <select id="settings-computer-use-model" ${l?"disabled":""}>
          ${n?"":`<option selected disabled value="">Unavailable: ${d(t.modelId)}</option>`}
          ${s.providers.map(c=>`<optgroup label="${d(c.label)}">${c.models.map(o=>`<option value="${d(JSON.stringify([c.provider_id,o.model_id]))}" ${c.provider_id===t.providerId&&o.model_id===t.modelId?"selected":""}>${d(o.label)}</option>`).join("")}</optgroup>`).join("")}
        </select>
      </label>
      <label class="settings-platform-field settings-platform-field-wide"><span>Reasoning effort</span>
        <select id="settings-computer-use-effort" ${l||!n?"disabled":""}>
          ${i?"":`<option selected disabled value="${d(t.effort)}">Unavailable: ${d(t.effort)}</option>`}
          ${a.length?a.map(c=>`<option value="${d(c.effort)}" ${c.effort===t.effort?"selected":""}>${d(c.label)}</option>`).join(""):'<option value="">Default</option>'}
        </select>
      </label>
      ${t.executionMode==="delegated"?`<label class="settings-platform-field settings-platform-field-wide"><span>Recovery model</span>
        <select id="settings-computer-use-fallback" ${l?"disabled":""}>
          <option value="" ${t.fallbackModelId?"":"selected"}>Return to chat</option>
          ${t.fallbackModelId&&!s.providers.flatMap(c=>c.models).some(c=>c.model_id===t.fallbackModelId)?`<option selected disabled value="${d(t.fallbackModelId)}">Unavailable: ${d(t.fallbackModelId)}</option>`:""}
          ${s.providers.flatMap(c=>c.models).filter(c=>c.model_id!==t.modelId&&c.supported_reasoning_efforts.some(o=>o.effort==="medium")).map(c=>`<option value="${d(c.model_id)}" ${c.model_id===t.fallbackModelId?"selected":""}>${d(c.label)} · Mid</option>`).join("")}
        </select>
      </label>
      `:""}
      `:'<p class="settings-card-copy">The selected chat model controls the interface directly.</p>'}
      ${s.available?"":'<p class="settings-inline-error" role="alert">The saved model is unavailable. Choose an available model to continue PC use.</p>'}
      ${t.error?`<p class="settings-inline-error" role="alert">${d(t.error)}</p>`:""}
      <button type="button" id="settings-computer-use-discard" class="settings-secondary" ${r&&!l?"":"disabled"}>Discard edits</button>
      <button type="button" id="settings-computer-use-save" ${l||!n||!i||!r?"disabled":""}>
        <span class="material-symbols-rounded" aria-hidden="true">${t.saving?"sync":"save"}</span>
        ${t.saving?"Saving":"Save decision model"}
      </button>
    </div>
  </section>`}function Xs(e){const{state:t,getSettings:s,render:n}=e;let a=0;async function i(){const l=s();if(!l?.computer_use?.can_configure||t.saving)return;const c=l.workspace.workspace_id;if(c!==t.workspaceId)return;const o=t.generation,p=++a,u=()=>t.generation===o&&p===a&&s()?.workspace.workspace_id===c;t.saving=!0,t.error="";const f={workspace_id:c,provider_id:t.providerId,model_id:t.modelId,reasoning_effort:t.effort||null,execution_mode:t.executionMode,fallback_model_id:t.fallbackModelId||null,fallback_reasoning_effort:t.fallbackEffort||null};n();try{const $=await D("/api/settings/computer-use",{method:"POST",body:JSON.stringify(f)});if(!u()||$.workspace_id!==c)return;e.setSelection($),Ke(t,s(),!0),F('[aria-labelledby="settings-computer-use-title"]'),e.notify("PC use decision model updated.")}catch($){u()&&(t.error=$ instanceof Error?$.message:"Unable to update the decision model.")}finally{u()&&(t.saving=!1,n())}}function r(){v(document.getElementById("settings-computer-use-discard"),"click",()=>{Ke(t,s(),!0),F('[aria-labelledby="settings-computer-use-title"]'),n()}),v(document.getElementById("settings-computer-use-mode"),"change",l=>{t.executionMode=l.currentTarget.value,t.executionMode==="direct"&&(t.fallbackModelId="",t.fallbackEffort=""),t.error="",n()}),v(document.getElementById("settings-computer-use-fallback"),"change",l=>{t.fallbackModelId=l.currentTarget.value,t.fallbackEffort=t.fallbackModelId?"medium":"",t.error="",n()}),v(document.getElementById("settings-computer-use-model"),"change",l=>{const[c,o]=JSON.parse(l.currentTarget.value);t.providerId=c,t.modelId=o,t.fallbackModelId===o&&(t.fallbackModelId="",t.fallbackEffort="");const p=Kt(s(),t);t.effort=p?.supported_reasoning_efforts.some(u=>u.effort==="low")?"low":p?.default_reasoning_effort||"",t.error="",n()}),v(document.getElementById("settings-computer-use-effort"),"change",l=>{t.effort=l.currentTarget.value,t.error="",n()}),v(document.getElementById("settings-computer-use-save"),"click",()=>{i()})}return{bind:r,save:i}}async function Zs(){try{return await D("/api/admin/persistence")}catch{return null}}const xs={registry:"/api/apps",context:"/api/settings/platform?section=context",models:"/api/settings/platform?section=models",voice:"/api/settings/platform?section=voice","computer-use":"/api/settings/platform?section=computer-use",users:"/api/admin/users",workspaces:"/api/admin/workspaces",apps:"/api/admin/workspace-apps",persistence:"/api/admin/persistence",sessions:"/api/settings/runtime-sessions"};function dt(e){return e==="users"||e==="workspace-access"?["users","workspaces"]:e==="workspace-apps"?["context","workspaces","apps"]:e==="app-links"?["context","apps"]:e==="sessions"?["context","sessions"]:e==="usage"||e==="learning"?["context"]:e==="cache"?[]:[e]}function en(e){const t=new Map,s=new Map;function n(l){return t.has(l)||t.set(l,{loaded:!1,loading:!1,error:""}),t.get(l)}function a(l,c=!1){if(!c&&s.has(l))return s.get(l).promise;if(!c&&n(l).loaded)return Promise.resolve();s.get(l)?.controller.abort();const o=new AbortController;Object.assign(n(l),{loading:!0,error:""});const p=performance.now(),u=D(xs[l],{signal:o.signal}).then(f=>{o.signal.aborted||(e.publish(l,f),n(l).loaded=!0)}).catch(f=>{o.signal.aborted||(n(l).error=f instanceof Error?f.message:"Unable to load settings.")}).finally(()=>{s.get(l)?.controller===o&&(s.delete(l),n(l).loading=!1,performance.clearMeasures(`settings.load.${l}`),performance.measure(`settings.load.${l}`,{start:p,end:performance.now()}),e.changed(l))});return s.set(l,{controller:o,promise:u}),e.changed(l),u}function i(){s.forEach(({controller:l})=>l.abort()),s.clear(),t.clear()}function r(l){s.forEach(({controller:c},o)=>{l.includes(o)||(c.abort(),s.delete(o),n(o).loading=!1)})}return{state:n,ensure:a,reset:i,cancelExcept:r}}function tn(e,t,s){e?.workspace.workspace_id!==t.workspace.workspace_id&&(e=null);const n=s==="models"?t.provider:s==="voice"?{...e?.provider||t.provider,hosted_text:t.provider.hosted_text,speech_stt:t.provider.speech_stt}:e?.provider||t.provider;return{...e,...t,provider:n,runtime:{...e?.runtime,...t.runtime,all_sessions:e?.runtime.all_sessions},computer_use:t.computer_use||e?.computer_use,agentic_admin:s==="models"?t.agentic_admin:e?.agentic_admin}}function ct(e){const t=document.activeElement,s=document.createElement("dialog");return s.className="settings-modal settings-confirm-dialog",s.setAttribute("aria-labelledby","settings-confirm-title"),s.setAttribute("aria-describedby","settings-confirm-detail"),s.innerHTML=`<h2 id="settings-confirm-title">${d(e.title)}</h2>
    <p id="settings-confirm-detail" class="settings-card-copy">${d(e.detail)}</p>
    <form method="dialog" class="settings-modal-actions">
      <button value="cancel" class="settings-secondary" autofocus>Cancel</button>
      <button value="confirm" class="settings-danger">${d(e.confirmLabel)}</button>
    </form>`,document.body.append(s),new Promise(n=>{s.addEventListener("close",()=>{const a=s.returnValue==="confirm";s.remove(),t?.isConnected&&t.focus(),n(a)},{once:!0}),s.showModal()})}let Be=null,_e=null;function sn(e){const t=document.querySelector('.settings-modal[role="dialog"]');if(!t){_e&&Be?.isConnected&&Be.focus(),_e=null;return}const s=()=>Array.from(t.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex="0"]'));_e!==t&&(Be=document.activeElement,_e=t,s()[0]?.focus()),t.onkeydown=n=>{if(n.key==="Escape"&&!t.querySelector("button#close-migration-modal:disabled")&&(n.preventDefault(),e()),n.key!=="Tab")return;const a=s(),i=a[0],r=a.at(-1);n.shiftKey&&document.activeElement===i&&(n.preventDefault(),r?.focus()),!n.shiftKey&&document.activeElement===r&&(n.preventDefault(),i?.focus())}}const je=20,Qt=()=>({scope:"workspace",query:"",status:"",page:0});function pt(e,t){const s=e.runtime.all_sessions||e.runtime.sessions||[];return t.scope==="server"&&e.runtime.cleanup_scope==="server"?s:s.filter(n=>n.workspace_id===e.workspace.workspace_id)}function nn(e,t){const s=t.query.trim().toLowerCase();return pt(e,t).filter(n=>(!t.status||n.status===t.status)&&`${n.session_id} ${n.agent_id} ${n.workspace_name||n.workspace_id} ${n.provider_id}`.toLowerCase().includes(s))}function an(e,t,s){const n=pt(e,s),a=nn(e,s),i=Math.max(1,Math.ceil(a.length/je));s.page=Math.min(s.page,i-1);const r=a.slice(s.page*je,(s.page+1)*je),l=e.runtime.cleanup_allowed===!0,c=s.scope==="server"?"All workspaces on this server":e.workspace.name;return`<section class="settings-card settings-runtime-settings-card">
    <div class="settings-heading"><div><p class="settings-kicker">${d(c)}</p><h2>Runtime sessions</h2></div>
      <button type="button" id="settings-clear-all-runtime" class="settings-danger" ${!l||!n.length||t.clearingAllRuntime?"disabled":""}>${t.clearingAllRuntime?"Deleting…":`Delete ${n.length} sessions`}</button>
    </div>
    <p class="settings-card-copy">Deletion stops active agents and removes their conversations, turns and runtime files. Review the confirmation before continuing.</p>
    <div class="settings-grid settings-session-filters">
      <label>Search sessions<input id="settings-session-search" type="search" value="${b(s.query)}" placeholder="Agent, workspace or session" /></label>
      <label>Status<select id="settings-session-status"><option value="">All statuses</option>${Array.from(new Set(n.map(o=>o.status))).sort().map(o=>`<option value="${b(o)}" ${s.status===o?"selected":""}>${d(o)}</option>`).join("")}</select></label>
      ${e.runtime.cleanup_scope==="server"?`<label>View scope<select id="settings-session-scope"><option value="workspace" ${s.scope==="workspace"?"selected":""}>Current workspace</option><option value="server" ${s.scope==="server"?"selected":""}>Entire server</option></select></label>`:""}
    </div>
    ${l?"":'<p role="status">You do not have permission to delete sessions in this workspace.</p>'}
    <div class="settings-platform-runtime-list">${r.map(o=>rn(o,l,t)).join("")||'<p role="status">No sessions match this view.</p>'}</div>
    <div class="settings-pagination"><span role="status">${a.length} sessions · Page ${s.page+1} of ${i}</span>
      <button type="button" id="settings-sessions-prev" class="settings-secondary" ${s.page===0?"disabled":""}>Previous</button>
      <button type="button" id="settings-sessions-next" class="settings-secondary" ${s.page+1>=i?"disabled":""}>Next</button>
    </div>
    ${t.cleanupError?`<p class="settings-inline-error" role="alert">${d(t.cleanupError)}</p>`:""}
  </section>`}function rn(e,t,s){const n=s.cleaningSessionIds.has(e.session_id)||s.clearingAllRuntime;return`<article class="settings-platform-runtime-row" data-runtime-row="${b(e.session_id)}">
    <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">terminal</span>
    <span class="settings-platform-runtime-copy"><span class="settings-platform-runtime-title"><strong>${d(e.agent_id||e.session_id)}</strong>
      <button type="button" class="settings-secondary" data-runtime-clear="${b(e.session_id)}" aria-label="Delete session ${b(e.agent_id||e.session_id)}" ${!t||n?"disabled":""}>${n?"Deleting…":"Delete"}</button></span>
      <small>${d(e.workspace_name||e.workspace_id)} · ${d(e.status)} · ${d(e.effective_mode)}</small>
      ${e.recovery_reason_code?`<small class="settings-inline-error">${d(e.recovery_reason_code)}</small>`:""}
      ${e.agentic_containment?.status==="NO-GO"?`<small class="settings-inline-error">Contained: ${d(e.agentic_containment.reason_code||"Unavailable")}</small>`:""}
      <code>${d(e.session_id)}</code></span>
  </article>`}const Qe=[{value:"6h",label:"6 hours",resolution:"hour",periods:6},{value:"12h",label:"12 hours",resolution:"hour",periods:12},{value:"24h",label:"24 hours",resolution:"hour",periods:24},{value:"3d",label:"3 days",resolution:"hour",periods:72},{value:"7d",label:"7 days",resolution:"day",periods:7},{value:"30d",label:"30 days",resolution:"day",periods:30},{value:"90d",label:"90 days",resolution:"day",periods:90},{value:"180d",label:"180 days",resolution:"day",periods:180},{value:"1y",label:"1 year",resolution:"day",periods:365}],Yt=[{value:"non_cached_tokens",label:"Non-cached"},{value:"total_tokens",label:"Processed total"},{value:"cached_input_tokens",label:"Cached input"},{value:"input_tokens",label:"Uncached input"},{value:"output_tokens",label:"Output"},{value:"reasoning_output_tokens",label:"Reasoning output"},{value:"cache_write_input_tokens",label:"Cache write"}];function Ye(){return{metric:"non_cached_tokens",providerId:"",modelId:"",timeRange:"24h"}}function on(e,t){const s=Yt.some(a=>a.value===t.metric)?t.metric:e.metric,n=Qe.some(a=>a.value===t.timeRange)?t.timeRange:e.timeRange;return{metric:s,providerId:bt(t.providerId,e.providerId),modelId:bt(t.modelId,e.modelId),timeRange:n}}function Xt(e){return Qe.find(t=>t.value===e)||Qe[2]}function dr(e,t){return t==="non_cached_tokens"?Math.max(0,Fe(e.total_tokens)-Fe(e.cached_input_tokens)):Math.max(0,Fe(e[t]))}function cr(e){return Yt.find(t=>t.value===e)?.label||"Non-cached"}function pr(e){const t=new Map,s=(i,r=[])=>{if(!i?.provider_id)return;const l=t.get(i.provider_id)||new Set;i.model_options.forEach(c=>c.model_id&&l.add(c.model_id)),r.forEach(c=>c&&l.add(c)),t.set(i.provider_id,l)},n=e?.provider;s(n?.active_provider,[n?.model_settings?.selected_model_id||"",...(n?.model_settings?.available_models||[]).map(i=>i.model_id)]),n?.available_providers?.forEach(i=>s(i));const a=n?.hosted_text;return s(a?.active_provider,[a?.model_settings?.selected_model_id||"",...(a?.model_settings?.available_models||[]).map(i=>i.model_id)]),a?.available_providers.forEach(i=>s(i)),e?.agentic_admin?.items.forEach(i=>{const r=t.get(i.model_provider_id)||new Set;i.model_id&&r.add(i.model_id),t.set(i.model_provider_id,r)}),Array.from(t,([i,r])=>({provider_id:i,model_ids:Array.from(r).sort((l,c)=>l.localeCompare(c))})).sort((i,r)=>i.provider_id.localeCompare(r.provider_id))}function Fe(e){return Number.isFinite(e)?e:0}function bt(e,t){return typeof e=="string"?e.trim():t}function ln(e,t,s=Date.now()){const n=t.providerUsageItems.find(r=>r.provider_id===e);if(!n)return t.isLoadingProviderUsage?"Loading usage…":t.providerUsageError?"Usage unavailable":"Usage limit not reported";if(!n.available)return"Usage unavailable";const a=n.limits.map(r=>({limit:r,windows:[r.primary_window,r.secondary_window].filter(l=>l!==null)})).filter(({windows:r})=>r.length>0);if(!a.length)return"Usage limit not reported";const i=a.length>1;return a.map(({limit:r,windows:l})=>`${i?`${r.label} — `:""}${l.map(o=>dn(o,s)).join("; ")}`).join(" · ")}function dn(e,t){const s=Math.min(100,Math.max(0,e.used_percent)),n=Math.max(0,100-s),a=pn(e,t);return`${cn(e.limit_window_seconds)}: ${yt(s)} used · ${yt(n)} remaining before limit${a?` · ${a}`:""}`}function yt(e){return`${Number.isInteger(e)?e.toFixed(0):e.toFixed(1)}%`}function cn(e){return!e||e<=0?"Rolling window":e%604800===0?`${e/604800}w window`:e%86400===0?`${e/86400}d window`:e%3600===0?`${e/3600}h window`:e%60===0?`${e/60}m window`:"Rolling window"}function pn(e,t){let s=null;return e.reset_at_epoch_seconds!==null?s=Math.max(0,Math.ceil(e.reset_at_epoch_seconds-t/1e3)):s=e.reset_after_seconds,s===null?"":`resets ${un(s)}`}function un(e){if(e<=0)return"now";const t=Math.max(1,Math.ceil(e/60)),s=Math.floor(t/1440),n=Math.floor(t%1440/60),a=t%60;return s>0?`in ${s}d${n>0?` ${n}h`:""}`:n>0?`in ${n}h${a>0?` ${a}m`:""}`:`in ${a}m`}function gn(e){const t=e.isLoadingUsageHistory?"sync":"refresh",s=Xt(e.usageHistoryFilters.timeRange),n=s.resolution==="hour"?"Hourly consumption":"Daily consumption";return`<section class="settings-card settings-platform settings-usage-history-card" aria-labelledby="settings-usage-history-title">
    <div class="settings-heading settings-platform-heading settings-usage-history-heading">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">monitoring</span>
      <div>
        <p class="settings-kicker">Workspace metering</p>
        <h2 id="settings-usage-history-title">Token usage history</h2>
      </div>
      <button type="button" class="settings-secondary settings-provider-usage-refresh" id="settings-refresh-usage-history" ${e.isLoadingUsageHistory?"disabled":""}>
        <span class="material-symbols-rounded ${e.isLoadingUsageHistory?"is-spinning":""}" aria-hidden="true">${t}</span>
        Refresh
      </button>
    </div>
    <p class="settings-card-copy">Usage across root and delegated runtime sessions. The chart defaults to non-cached tokens; use the filters to inspect processed totals, cache, providers, models, and time ranges.</p>
    ${e.usageHistoryError?`<p class="settings-inline-error" role="alert">${d(e.usageHistoryError)}</p>`:""}
    <div class="settings-usage-history-filters" data-usage-history-filters aria-label="Token history filters"></div>
    <article class="settings-usage-history-panel">
      <div>
        <p class="settings-kicker">Last ${d(s.label)}</p>
        <h3>${n}</h3>
      </div>
      <div data-usage-history-chart aria-live="polite"></div>
    </article>
  </section>`}function mn(e){return`<section class="settings-card"><div class="settings-heading"><h2>Provider subscriptions</h2></div>
    ${e.providerUsageError?`<p role="alert">${d(e.providerUsageError)}</p>`:""}
    ${e.isLoadingProviderUsage?'<p role="status">Loading subscription usage…</p>':""}
    ${e.providerUsageItems.map(t=>`<article class="settings-subscription-row"><strong>${d(t.provider_id)}</strong><p>${d(ln(t.provider_id,e))}</p></article>`).join("")}
    ${!e.isLoadingProviderUsage&&!e.providerUsageItems.length&&!e.providerUsageError?"<p>No subscription limits reported.</p>":""}
  </section>${gn(e)}`}let Xe=!0;const be=new Set;let ye=null;function Ze(e={}){return Xe&&!globalThis.document?.hidden&&(e.requireOnline===!1||globalThis.navigator?.onLine!==!1)}function fn(e,t={}){if(typeof window>"u")return e(!0),()=>{};const s={notify:e,options:t,previous:Ze(t)};if(be.add(s),!ye){const n=()=>{for(const i of be){const r=Ze(i.options);r!==i.previous&&(i.previous=r,i.notify(r))}},a=i=>{!ot(i)||i.data?.type!=="maverick.app.visibility-changed"||typeof i.data.visible!="boolean"||(Xe=i.data.visible,n())};window.addEventListener?.("message",a),window.addEventListener?.("online",n),window.addEventListener?.("offline",n),globalThis.document?.addEventListener("visibilitychange",n),ye=()=>{window.removeEventListener?.("message",a),window.removeEventListener?.("online",n),window.removeEventListener?.("offline",n),globalThis.document?.removeEventListener("visibilitychange",n)}}return e(s.previous),()=>{be.delete(s),be.size||(ye?.(),ye=null,Xe=!0)}}const vn=256;function hn(){if(typeof window>"u")return null;const e=window.__MAVERICK_APP_FRAME_CONTEXT__;if(!e||typeof e!="object"||Array.isArray(e))return null;const t=e;return!$t(t.app_id)||!$t(t.workspace_id)?null:{appId:t.app_id,workspaceId:t.workspace_id}}function $t(e){return typeof e=="string"&&e.trim()===e&&e.length>0&&e.length<=vn&&!/[\u0000-\u001f\u007f]/u.test(e)}const _n="maverick.pwa.cache-operations.request.v1",bn="maverick.pwa.cache-operations.accepted.v1",yn="maverick.pwa.cache-operations.result.v1",$n=750,wn=1e4;function kn(e={}){return Zt("diagnostics",e).then(t=>t?.dashboard??null)}function Sn(e={}){return Zt("clear",e).then(t=>t?.cleanup?{cleanup:t.cleanup,dashboard:t.dashboard}:null)}async function Zt(e,t){const s=t.parentWindow??Mn();if(!s)return null;const n=t.parentOrigin===void 0?Pn():xe(t.parentOrigin);if(!n)return null;const a=(t.createMessageChannel??(()=>new MessageChannel))(),i=qn(),r={action:e,app_id:"settings",request_id:i,type:_n};return new Promise((l,c)=>{let o=!1,p=!1,u=globalThis.setTimeout(()=>$(null),wt(t.acceptanceTimeoutMs,$n));function f(){globalThis.clearTimeout(u),a.port1.close()}function $(T){p||(p=!0,f(),l(T))}function m(){p||(p=!0,f(),c(new Error("Maverick cache diagnostics are unavailable.")))}a.port1.addEventListener("message",T=>{const w=ee(T.data);if(!w||w.app_id!=="settings"||w.request_id!==i)return;if(w.type===bn){if(o)return;o=!0,globalThis.clearTimeout(u),u=globalThis.setTimeout(m,wt(t.resultTimeoutMs,wn));return}if(!o||w.type!==yn)return;if(w.status==="unavailable"){$(null);return}if(w.status!=="ok"){m();return}const h=En(w.dashboard),M=w.cleanup===void 0?void 0:Cn(w.cleanup);if(!h||e==="clear"&&!M){m();return}$({...M?{cleanup:M}:{},dashboard:h})}),a.port1.start();try{s.postMessage(r,n,[a.port2])}catch{$(null)}})}function En(e){const t=ee(e),s=In(t?.diagnostics),n=An(t?.metrics);return s&&n?{diagnostics:s,metrics:n}:null}function In(e){const t=ee(e);return!t||t.backend!=="indexeddb"&&t.backend!=="memory"||typeof t.fileCacheAvailable!="boolean"||["cacheBytes","entryCount","fileCacheBytes","fileCacheEntryCount","pendingCleanupCount","structuredCacheBytes","structuredEntryCount"].some(n=>!me(t[n]))||!re(t.originQuotaBytes)||!re(t.originUsageBytes)?null:t}function An(e){const t=ee(e),s=ee(t?.counters),n=ee(t?.quota),a=ee(t?.requestWait);if(!t||t.schema!==bs||!s||!n||!a||!et(t.updatedAt)||!et(t.windowStartedAt)||ys.some(i=>!me(s[i]))||!re(n.lastEstimatedAt)||!re(n.quotaBytes)||!re(n.usageBytes)||n.supported!==null&&typeof n.supported!="boolean")return null;for(const i of["averageDurationMs","durationObservations","maxDurationMs","pendingCount","totalDurationMs"])if(!me(a[i]))return null;return re(a.oldestPendingMs)?t:null}function Cn(e){const t=ee(e);return!t||t.status!=="complete"&&t.status!=="pending"||!me(t.pendingCleanupCount)||!me(t.removed)?null:t}function Mn(){return typeof window<"u"&&window.parent!==window?window.parent:null}function Pn(){if(typeof window>"u")return null;const e=xe(window.__MAVERICK_PLATFORM_ORIGIN__),t=xe(window.location.origin);return e&&t&&e!==t?e:null}function xe(e){if(typeof e!="string"||!e)return null;try{const t=new URL(e);return t.origin===e&&(t.protocol==="http:"||t.protocol==="https:")?t.origin:null}catch{return null}}function qn(){return globalThis.crypto?.randomUUID?.()??`${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`}function wt(e,t){return typeof e=="number"&&Number.isFinite(e)&&e>0?Math.min(Math.floor(e),3e4):t}function me(e){return typeof e=="number"&&Number.isSafeInteger(e)&&e>=0}function et(e){return typeof e=="number"&&Number.isFinite(e)&&e>=0}function re(e){return e===null||et(e)}function ee(e){return e&&typeof e=="object"&&!Array.isArray(e)?e:null}const ue=new Set;let $e=null;function Dn(e,t){if(typeof window>"u")return()=>{};const s={event:e,refresh:t};return ue.add(s),$e||($e=Rn()),()=>{ue.delete(s),ue.size||($e?.(),$e=null)}}function Rn(){const e=hn(),t=!!(e&&window.parent&&window.parent!==window),s=()=>!!(globalThis.document?.hidden||globalThis.navigator?.onLine===!1);let n=t&&s(),a=null,i,r=!1,l=!1,c=0;const o=Ze;let p=o();l=!p;const u=()=>{for(const y of ue)y.refresh()},f=y=>{for(const E of ue)E.event(y)};function $(){if(l=!0,r||!o()||i!==void 0)return;const y=Math.min(3e4,1e3*2**Math.min(c++,5)*(.8+Math.random()*.4));i=setTimeout(()=>{i=void 0,m()},y)}function m(){if(r||t||!o()||a||typeof WebSocket>"u")return;const y=window.location.protocol==="https:"?"wss:":"ws:";let E;try{E=new WebSocket(`${y}//${window.location.host}/api/apps/events/ws`)}catch{$();return}a=E;let W=!1;const U=()=>!r&&a===E;E.onopen=()=>{!U()||W||(W=!0,c=0,l&&(l=!1,u()))},E.onmessage=Y=>{if(!U()||!o())return;let q;try{q=JSON.parse(Y.data)}catch{return}f(q)},E.onclose=()=>{U()&&(a=null,$())},E.onerror=()=>{U()&&E.close()}}function T(){const y=o();if(y!==p)if(p=y,y)t?l&&!n&&(l=!1,u()):m();else{t&&s()&&(n=!0),l=!0,clearTimeout(i),i=void 0;const E=a;a=null,E?.close()}}function w(){t&&s()&&(n=!0)}function h(y){if(!t||!ot(y)||!y.data||typeof y.data!="object")return;const E=y.data;if(E.type==="maverick.app.events-resync")n=!1,o()?(l=!1,u()):l=!0;else if(E.type==="maverick.app.event"&&E.event&&typeof E.event=="object"){if(E.event.workspace_id&&E.event.workspace_id!==e.workspaceId)return;o()?f(E.event):l=!0}}const M=fn(T);return window.addEventListener?.("offline",w),globalThis.document?.addEventListener("visibilitychange",w),window.addEventListener?.("message",h),m(),()=>{r=!0,clearTimeout(i);const y=a;a=null,y?.close(),M(),window.removeEventListener?.("offline",w),globalThis.document?.removeEventListener("visibilitychange",w),window.removeEventListener?.("message",h)}}const he=e=>["rejected","undone","undoing"].includes(e.status)?e.status:e.implementation?.status||e.status,Tn=[{id:"proposed",label:"Proposed",states:["pending"],hint:"Accept to start a Chat agent"},{id:"queued",label:"Queued",states:["accepted","queued","launching"],hint:"Starts when an agent slot is available"},{id:"running",label:"In progress",states:["running","stopping"],hint:"Follow the agent in Chat"},{id:"review",label:"To verify",states:["awaiting_review"],hint:"Check the result before completing"},{id:"attention",label:"Needs attention",states:["failed","cancelled"],hint:"Inspect the chat and retry when ready"},{id:"done",label:"Done",states:["implemented"],hint:"Implementation confirmed"},{id:"closed",label:"Dismissed",states:["rejected"],hint:"Proposals you chose to dismiss"}],Ln=[{id:"proposed",label:"Proposed",states:["pending","checking"],hint:"Accept to start a Memory agent"},{id:"queued",label:"Queued",states:["accepted","queued","launching"],hint:"One Memory chat at a time"},{id:"running",label:"In progress",states:["running","saving","stopping","undoing"],hint:"Verifies sources and saves the approved fact"},{id:"attention",label:"Needs attention",states:["failed","cancelled"],hint:"Read the chat before retrying"},{id:"done",label:"Saved",states:["saved"],hint:"Confirmed by the Memory provider"},{id:"undone",label:"Undone",states:["undone"],hint:"Saves you chose to undo"},{id:"closed",label:"Dismissed",states:["rejected"],hint:"Facts you chose to dismiss"}],Hn={pending:"Proposed",checking:"Checking Memory",saving:"Saving",saved:"Saved",undoing:"Undoing",undone:"Undone",accepted:"Accepted · not started",queued:"Queued",launching:"Starting chat",running:"In progress",stopping:"Stopping",awaiting_review:"To verify",failed:"Failed",cancelled:"Stopped",implemented:"Done",rejected:"Dismissed"},tt=e=>["implemented","rejected","saved","undone"].includes(he(e));function Un(e){const t=he(e);return t==="pending"?[[e.kind==="memory"?"approve":"accept",e.kind==="memory"?"Accept & save":"Accept & start"],["reject","Dismiss"]]:t==="saved"?e.details.node_created?[["undo","Undo save"]]:[]:t==="accepted"?[["start","Start implementation"],["reject","Dismiss"]]:["queued","launching","running"].includes(t)?[["stop",t==="queued"?"Remove from queue":"Stop implementation"]]:t==="awaiting_review"?[["implemented","Confirm implemented"],["retry","Continue fixing"]]:["failed","cancelled"].includes(t)?[["retry","Retry in same chat"],["reject","Dismiss"]]:[]}function On(e,t){const s=he(e);if(t==="queued")return s==="pending"?e.kind==="memory"?"approve":"accept":s==="accepted"?"start":["failed","cancelled","awaiting_review"].includes(s)?"retry":void 0;if(t==="done"&&s==="awaiting_review")return"implemented";if(t==="closed"&&["pending","accepted","failed","cancelled"].includes(s))return"reject"}function kt(e,t,s=!0){const n=he(e),a=Un(e),i=(o,p)=>`<button class="settings-secondary ${o==="accept"?"ticket-primary":""}" data-learning-item="${d(e.id)}" data-learning-command="${o}" ${t?"disabled":""}>${p}</button>`,r=[...new Set(e.evidence.map(o=>o.session_id))],l=e.details.memory_matches||[],c=`${s?`<p>${d(e.body)}</p>`:""}<dl class="learning-proposal-details">${["generalization","expected_impact","verification"].filter(o=>e.details[o]).map(o=>`<dt>${{generalization:"Why this helps other tasks",verification:"Verification",expected_impact:"Expected impact"}[o]}</dt><dd>${d(e.details[o])}</dd>`).join("")}</dl>
    ${e.evidence.map(o=>`<blockquote><p>${d(o.quote)}</p><small>${d(o.role)} · ${d(o.turn_id)} · <a href="/app/chat/threads/${encodeURIComponent(o.session_id)}">Source chat</a></small></blockquote>`).join("")}
    ${e.implementation?.summary?`<details data-learning-disclosure="${d(e.id)}-summary"><summary>Agent result</summary><p class="ticket-summary">${d(e.implementation.summary)}</p></details>`:""}
    ${e.status==="pending"?`<details data-learning-disclosure="${d(e.id)}-edit"><summary>Edit proposal</summary><label>Title<input data-learning-title="${d(e.id)}" value="${d(e.title)}" maxlength="240"></label><label>Description<textarea data-learning-body="${d(e.id)}" rows="3" maxlength="4000">${d(e.body)}</textarea></label>${i("edit","Save edit")}</details>`:""}`;return`<article class="learning-ticket ${s?"":"ticket-list-row"}" data-ticket-id="${d(e.id)}" data-ticket-state="${d(n)}">
    <div class="ticket-top"><span>${d(e.details.category||"Improvement")}</span>${a.length?`<button class="ticket-grip" draggable="${!t}" data-learning-drag="${d(e.id)}" aria-label="Move ${d(e.title)} between columns" title="Drag to Queued, Done or Dismissed; actions below also work with keyboard" ${t?"disabled":""}><span class="material-symbols-rounded" aria-hidden="true">drag_indicator</span></button>`:""}</div>
    <h4>${d(e.title)}</h4><p class="ticket-description">${d(e.body)}</p>
    <div class="ticket-meta"><span>${d(Hn[n]||n)}</span>${e.details.effort?`<span>${d(e.details.effort)} effort</span>`:""}<span>${r.length} source chat${r.length===1?"":"s"}${e.occurrences>1?` · ${e.occurrences} observations`:""}</span></div>
    ${e.implementation?.error?`<p class="learning-error" role="status">${d(e.implementation.error)}</p>`:""}
    ${e.details.review_stale&&!tt(e)?'<p class="ticket-note">The source chat changed. Accepted tickets wait for reassessment before an agent starts.</p>':""}
    ${e.details.review_reason?`<p class="ticket-note">${d(e.details.review_reason)}</p>`:""}
    ${n==="awaiting_review"?'<p class="ticket-note">The agent finished its turn. Review the changes and checks in Chat.</p>':""}
    ${n==="pending"&&e.kind==="memory"&&l.length?`<label>Memory destination<select data-learning-target="${d(e.id)}" aria-label="Memory destination"><option value="">Choose destination</option>${l.map(o=>`<option value="${d(o.id)}">Attach to ${d(o.title)}</option>`).join("")}<option value="new">Create separate fact</option></select></label>`:""}
    ${e.details.memory_check_error||e.details.save_error?`<p class="learning-error">${d(e.details.save_error||e.details.memory_check_error)}</p>`:""}
    <div class="learning-actions">${e.kind==="memory"&&e.status==="saved"?`<a class="settings-secondary" href="/app/${encodeURIComponent(e.provider_id||"memory")}/nodes/${encodeURIComponent(e.node_id)}">Open Memory</a>`:""}${e.implementation?.session_id?`<a class="settings-secondary" href="/app/chat/threads/${encodeURIComponent(e.implementation.session_id)}">Open work chat <span aria-hidden="true">↗</span></a>`:""}${a.slice(0,1).map(([o,p])=>i(o,p)).join("")}</div>
    <details class="ticket-details" data-learning-disclosure="${d(e.id)}-ticket"><summary>Details &amp; evidence</summary>${c}${a.slice(1).map(([o,p])=>i(o,p)).join("")}</details>
  </article>`}function Nn(e){const t=e.tab==="memory",s=t?"memory":"improvement",n=e.data.items.filter(u=>u.kind===s),a=e.ticketFilter||"open",i=e.ticketView||"board",r=(e.ticketSearch||"").trim().toLocaleLowerCase(),l=[...new Set(n.map(u=>u.details.category).filter(Boolean))].sort(),c=n.filter(u=>(a==="all"||(a==="closed"?tt(u):!tt(u)))&&(!e.ticketCategory||u.details.category===e.ticketCategory)&&(!r||`${u.title} ${u.body}`.toLocaleLowerCase().includes(r))),o=(t?Ln:Tn).filter(u=>a==="all"||(a==="closed"?["done","closed","undone"].includes(u.id):!["done","closed","undone"].includes(u.id))),p=e.data.projects?.[s];return`${e.error?`<p class="learning-error" role="alert">${d(e.error)}</p>`:""}${e.notice?`<p class="ticket-queue-note" role="status" aria-live="polite">${d(e.notice)}</p>`:""}<div class="ticket-toolbar"><div class="ticket-toolbar-title"><strong>${t?"Memory":"Improvement"} tickets <span>${n.length}</span></strong><small>${t?"Accept a fact to start a Chat agent that verifies its sources and saves it to Memory.":"Accept a proposal to start a Chat agent with its source context."}${p?` <a href="/app/chat/projects/${encodeURIComponent(p)}">Open ${t?"Memory":"Improvements"} project ↗</a>`:""}</small></div>
    <div class="ticket-toolbar-controls"><div class="ticket-segment" role="group" aria-label="Ticket status filter">${["open","all","closed"].map(u=>`<button data-ticket-filter="${u}" aria-pressed="${a===u}">${{open:"Open",all:"All",closed:"Closed"}[u]}</button>`).join("")}</div>
    <div class="ticket-segment" role="group" aria-label="Ticket view">${["board","list"].map(u=>`<button data-ticket-view="${u}" aria-pressed="${i===u}" aria-label="${u==="board"?"Kanban board":"Ticket list"}"><span class="material-symbols-rounded" aria-hidden="true">${u==="board"?"view_kanban":"view_list"}</span></button>`).join("")}</div></div>
    <input id="ticket-search" type="search" aria-label="Search improvement tickets" placeholder="Search tickets…" value="${d(e.ticketSearch||"")}"><select id="ticket-category" aria-label="Ticket category"><option value="">All categories</option>${l.map(u=>`<option value="${d(u)}" ${u===e.ticketCategory?"selected":""}>${d(u)}</option>`).join("")}</select></div>
    <p class="ticket-queue-note">${t?"One Memory work chat runs at a time. Saved means the provider confirmed the write.":`Up to ${e.data.settings.improvement_concurrency??4} improvement chats run in parallel. Configure the limit in Usage & retention.`} Accepted tickets use normal Chat usage; analysis pause and allowance apply to analysis.${e.data.items.length>=200?" Showing the first 200 learning results.":""}</p>
    ${e.data.runtime_ready===!1?'<p class="learning-notice" role="status">Work chats are waiting for the backend update. Accepted tickets stay queued until launching is available.</p>':""}
    ${i==="board"?`<div class="learning-kanban" role="region" aria-label="Improvement ticket board" tabindex="0">${o.map(u=>{const f=c.filter($=>u.states.includes(he($)));return`<section class="ticket-column" data-ticket-column="${u.id}" aria-label="${u.label}"><header><h4><i aria-hidden="true"></i>${u.label}<span>${f.length}</span></h4><small>${u.hint}</small></header><div class="ticket-dropzone">${f.map($=>kt($,e.saving)).join("")||'<div class="ticket-column-empty">No tickets</div>'}</div></section>`}).join("")}</div>`:`<div class="learning-list">${c.map(u=>kt(u,e.saving,!1)).join("")||'<div class="learning-empty"><strong>No matching tickets</strong><p>Change the filters or wait for new proposals.</p></div>'}</div>`}`}function Bn(e,t,s){document.querySelectorAll("[data-ticket-filter]").forEach(a=>v(a,"click",()=>s({ticketFilter:a.dataset.ticketFilter}))),document.querySelectorAll("[data-ticket-view]").forEach(a=>v(a,"click",()=>s({ticketView:a.dataset.ticketView}))),v(document.querySelector("#ticket-search"),"input",a=>s({ticketSearch:a.target.value})),v(document.querySelector("#ticket-category"),"change",a=>s({ticketCategory:a.target.value}));let n="";document.querySelectorAll("[data-learning-drag]").forEach(a=>{v(a,"dragstart",i=>{if(e.saving){i.preventDefault();return}n=a.dataset.learningDrag,i.dataTransfer?.setData("text/plain",n),i.dataTransfer&&(i.dataTransfer.effectAllowed="move")}),v(a,"dragend",()=>{n="",document.querySelectorAll(".ticket-column.is-over").forEach(i=>i.classList.remove("is-over"))})}),document.querySelectorAll("[data-ticket-column]").forEach(a=>{const i=()=>{const r=e.data?.items.find(l=>l.id===n);return r&&On(r,a.dataset.ticketColumn)};v(a,"dragover",r=>{!e.saving&&i()&&(r.preventDefault(),a.classList.add("is-over"))}),v(a,"dragleave",r=>{a.contains(r.relatedTarget)||a.classList.remove("is-over")}),v(a,"drop",r=>{r.preventDefault();const l=i();a.classList.remove("is-over"),l&&!e.saving&&t(n,l),n=""})})}function jn(e){let t={data:null,error:"",loading:!1,saving:!1,tab:"memory",detail:null,dependency:null,dirty:!1},s="",n=0,a=0,i=0,r=null,l=!1,c=!1;const o=new Map,p=new Map,u=new Map,f=q=>D("/api/apps/chat/backend",{method:"POST",body:JSON.stringify(q)});function $(){r?.(),r=null}function m(){const q=document.querySelector(".learning-kanban")?.scrollLeft||0,S=document.activeElement,g=S?.id?`#${S.id}`:S?.getAttribute("name")?`[name="${S.getAttribute("name")}"]`:["data-learning-title","data-learning-body","data-learning-target"].map(K=>S?.hasAttribute(K)?`[${K}="${S.getAttribute(K)}"]`:"").find(Boolean),_=S instanceof HTMLTextAreaElement||S instanceof HTMLInputElement?[S.selectionStart,S.selectionEnd]:null,I=new Set(t.openSections);document.querySelectorAll("[data-learning-disclosure]").forEach(K=>{K.open?I.add(K.dataset.learningDisclosure):I.delete(K.dataset.learningDisclosure)}),t.openSections=[...I],e.render();const P=document.querySelector(".learning-kanban");P&&(P.scrollLeft=q);const B=g?document.querySelector(g):null;B?.focus({preventScroll:!0}),_?.[0]!=null&&(B instanceof HTMLTextAreaElement||B instanceof HTMLInputElement&&["text","search"].includes(B.type))&&B.setSelectionRange(_[0],_[1])}function T(){n++,s="",c=!1,o.clear(),p.clear(),u.clear(),$(),t={data:null,error:"",loading:!1,saving:!1,tab:"memory",detail:null,dependency:null,dirty:!1}}function w(){if(!l||r)return;const q=n,S=()=>{q===n&&(c=!0,t.saving||h(!0))};r=Dn(g=>{g.workspace_id===s&&g.owner_app_id==="chat"&&g.resource==="learning"&&S()},S)}async function h(q=!1){const S=e.workspaceId();if(!S||(s!==S&&(T(),s=S),t.loading||!q&&t.data))return;const g=n,_=++a;c=!1,t.loading=!0,t.data||m();try{const[I,P]=await Promise.all([f({action:"learning.read"}),lt("chat")]);if(g!==n||_!==a||S!==e.workspaceId())return;t.data=I,t.dependency=P,t.error=""}catch(I){g===n&&_===a&&(t.error=ze(I))}finally{g===n&&_===a&&(t.loading=!1,m(),c&&!t.saving&&l&&h(!0))}}async function M(q,S){if(t.saving)return;const g=n;a++,t.loading=!1,t.saving=!0,t.error="",t.notice="",m();try{if(S&&await S(),g!==n||(await f(q),g!==n))return;const _=q;if(_.action==="learning.configure"&&_.settings&&"enabled"in _.settings&&o.clear(),t.notice=_.action==="learning.configure"?"Settings saved":["accept","approve","start","retry"].includes(_.command||"")?"Ticket queued. Its work chat appears when the agent starts.":_.command==="implemented"?"Implementation confirmed.":_.command==="stop"?"Stop requested. This chat keeps its slot until the turn ends.":"Action completed",_.item_id)for(const I of p.keys())I.endsWith(":"+_.item_id)&&p.delete(I);t.dirty=o.size>0||p.size>0,await h(!0)}catch(_){g===n&&(t.error=ze(_))}finally{g===n&&(t.saving=!1,m(),c&&l&&h(!0))}}async function y(q){const S=new FormData(q),g={};g.paused=t.data.settings.paused;for(const P of["enabled","memory_enabled","improvements_enabled"])g[P]=S.get(P)==="on";for(const P of["idle_seconds","max_context_chars","max_output_tokens","timeout_seconds","daily_token_budget","retention_days"])g[P]=Number(S.get(P));S.has("improvement_concurrency")&&(g.improvement_concurrency=Number(S.get("improvement_concurrency")));for(const P of["memory_mode","model_source","model_id","reasoning_effort","instructions"])g[P]=String(S.get(P)||"");for(const P of["excluded_thread_ids","excluded_project_ids"])g[P]=String(S.get(P)||"").split(/[\s,]+/).filter(Boolean);const _=String(S.get("memory_provider")||""),I=t.dependency?.dependencies.find(P=>P.alias==="learning-memory")?.selected_provider_app_ids[0]||"";await M({action:"learning.configure",settings:g},_!==I?()=>Jt("chat","learning-memory",_?[_]:[]):void 0)}function E(){const q=(g,_)=>{const I=document.querySelector(`[data-learning-target="${g}"]`)?.value||"",P=document.querySelector(`[data-learning-title="${g}"]`)?.value,B=document.querySelector(`[data-learning-body="${g}"]`)?.value;M({action:"learning.review",item_id:g,command:_,target_node_id:I==="new"?"":I,confirm_new:I==="new",title:P,body:B})};Bn(t,q,g=>{Object.assign(t,g),m()});const S=document.querySelector("#learning-settings");if(S){for(const _ of S.elements){if(!(_ instanceof HTMLInputElement||_ instanceof HTMLSelectElement||_ instanceof HTMLTextAreaElement)||!_.name||!o.has(_.name))continue;const I=o.get(_.name);_ instanceof HTMLInputElement&&_.type==="checkbox"?_.checked=I===!0:_.value=String(I)}const g=()=>{t.dirty=!0;for(const _ of S.elements)(_ instanceof HTMLInputElement||_ instanceof HTMLSelectElement||_ instanceof HTMLTextAreaElement)&&_.name&&o.set(_.name,_ instanceof HTMLInputElement&&_.type==="checkbox"?_.checked:_.value);U()};v(S,"input",g),v(S,"change",g),U()}v(S,"submit",g=>{g.preventDefault(),y(S)}),v(document.querySelector("#learning-refresh"),"click",()=>{h(!0)}),v(document.querySelector("#learning-discard"),"click",()=>{t.dirty=!1,o.clear(),p.clear(),t.notice="",m()}),v(document.querySelector("#learning-pause"),"click",()=>{M({action:"learning.configure",settings:{paused:!t.data.settings.paused}})}),v(document.querySelector("#learning-session"),"change",g=>{t.selectedSession=g.target.value,m()}),document.querySelectorAll("[data-learning-disclosure]").forEach(g=>{g.open=!!t.openSections?.includes(g.dataset.learningDisclosure),v(g,"toggle",()=>{if(!g.isConnected)return;const _=new Set(t.openSections);g.open?_.add(g.dataset.learningDisclosure):_.delete(g.dataset.learningDisclosure),t.openSections=[..._]})}),v(document.querySelector("#learning-analyze"),"click",()=>{const g=document.querySelector("#learning-session")?.value;g&&M({action:"learning.analyze_now",session_id:g})});for(const g of["data-learning-title","data-learning-body","data-learning-target"])document.querySelectorAll(`[${g}]`).forEach(_=>{const I=g+":"+_.getAttribute(g);p.has(I)&&(_.value=p.get(I)),v(_,"input",()=>{p.set(I,_.value),t.dirty=!0,U()})});document.querySelectorAll('.learning-results a[href^="/app/"]').forEach(g=>v(g,"click",_=>{if(window.parent===window||_.ctrlKey||_.metaKey)return;_.preventDefault();const I=new URL(g.href).pathname.split("/").filter(Boolean),P=window.__MAVERICK_PLATFORM_ORIGIN__||"*";window.parent.postMessage({type:"maverick.app.open-app",app_id:decodeURIComponent(I[1]),params:{app_page:I.slice(2).map(decodeURIComponent).join("/")}},P)})),document.querySelectorAll("[data-learning-tab]").forEach(g=>v(g,"click",()=>{u.set(t.tab,{ticketView:t.ticketView,ticketFilter:t.ticketFilter,ticketSearch:t.ticketSearch,ticketCategory:t.ticketCategory}),i++,t.tab=g.dataset.learningTab,t.detail=null,Object.assign(t,{ticketView:void 0,ticketFilter:void 0,ticketSearch:void 0,ticketCategory:void 0},u.get(t.tab)),m()})),document.querySelectorAll("[data-learning-tab]").forEach((g,_,I)=>v(g,"keydown",P=>{const B={ArrowRight:(_+1)%I.length,ArrowLeft:(_+I.length-1)%I.length,Home:0,End:I.length-1}[P.key];B!==void 0&&(P.preventDefault(),I[B].click(),document.querySelector(`#${I[B].id}`)?.focus())})),document.querySelectorAll("[data-learning-job]").forEach(g=>v(g,"click",async()=>{const _=g.dataset.learningJob,I=g.dataset.learningCommand;if(I!=="inspect"){await M({action:"learning.job",job_id:_,command:I});return}const P=n,B=++i;try{const K=await f({action:"learning.job",job_id:_,command:I});P===n&&B===i&&(t.detail=K.job,m())}catch(K){P===n&&B===i&&(t.error=ze(K),m())}})),document.querySelectorAll("[data-learning-item]").forEach(g=>v(g,"click",()=>{const _=g.dataset.learningItem;q(_,g.dataset.learningCommand)}))}function W(q){if(l=q,!q){$();return}s&&w(),c&&!t.saving&&h(!0)}function U(){const q=document.querySelector("#learning-draft-status");q&&(q.textContent=t.dirty?"Unsaved changes":t.notice||"Settings are up to date");const S=document.querySelector("#learning-discard");S&&(S.disabled=!t.dirty||t.saving);const g=document.querySelector("[name=memory_enabled]"),_=document.querySelector("#learning-memory-options");_&&g&&(_.hidden=!g.checked);const I=document.querySelector("[name=model_source]")?.value;document.querySelectorAll("[data-learning-native]").forEach(B=>{B.hidden=I!=="workspace"});const P=document.querySelector("#learning-mode-hint");P&&(P.textContent=document.querySelector("[name=memory_mode]")?.value==="automatic"?"Only explicit user facts with verified quotes and no Memory matches are saved automatically.":"You approve each fact before it enters Memory.")}function Y(){const q={};for(const[S,g]of o){if(S==="memory_provider"||!t.data)continue;const _=t.data.settings[S];q[S]=typeof _=="number"?Number(g):Array.isArray(_)?String(g).split(/[\s,]+/).filter(Boolean):g}return{...t,draftSettings:q}}return{load:h,reset:T,bind:E,setVisible:W,viewState:Y}}function ze(e){return e instanceof Error?e.message:"Learning operation failed"}function Fn(e,t){const s={...e.data.settings,...e.draftSettings},n=e.saving?"disabled":"",a=e.dependency?.dependencies.find(c=>c.alias==="learning-memory"),i=a?.selected_provider_app_ids[0]||"",r=(c,o,p,u)=>`<label class="learning-toggle ${u?"learning-channel":""}">
    ${u?`<span class="material-symbols-rounded learning-channel-icon" aria-hidden="true">${u}</span>`:""}
    <span class="learning-toggle-copy"><strong>${o}</strong><small>${p}</small></span>
    <input type="checkbox" role="switch" name="${c}" ${s[c]?"checked":""} ${n}><span class="learning-toggle-track" aria-hidden="true"></span></label>`,l=(c,o,p,u,f)=>`<label>${o}<input type="number" name="${c}" min="${p}" max="${u}" value="${s[c]}" required ${n}><small>${f}</small></label>`;return`<form id="learning-settings" class="settings-card learning-controls" aria-busy="${e.saving}">
    <div class="learning-section-heading"><div><h3>Automatic learning</h3><p>Learn lasting knowledge and new Maverick improvements from completed work.</p></div><span class="settings-pill">One analysis at a time</span></div>
    ${r("enabled","Enable learning","Review conversations after a quiet period. Unfinished work stays under observation.")}
    <div class="learning-channel-grid">
      ${r("memory_enabled","Memory","Keep sourced discoveries, people, events and lasting knowledge.","neurology")}
      ${r("improvements_enabled","Improvements","Find general limits of Maverick; skip work already requested or underway.","lightbulb")}
    </div>
    <div class="learning-form-grid" id="learning-memory-options" ${s.memory_enabled?"":"hidden"}>
      <label>Save to<select name="memory_provider" ${n}><option value="">Choose a Memory provider</option>${a?.candidates.map(c=>`<option value="${d(c.app_id)}" ${c.app_id===i?"selected":""}>${d(c.name)}</option>`).join("")||""}</select><small id="learning-provider-hint">${i?"Facts and their chat evidence are saved to this app.":"Choose a provider to check existing knowledge and save facts."}</small></label>
      <label>Saving mode<select name="memory_mode" ${n}><option value="review" ${s.memory_mode==="review"?"selected":""}>Review before saving</option><option value="automatic" ${s.memory_mode==="automatic"?"selected":""}>Save supported explicit facts automatically</option></select><small id="learning-mode-hint">${s.memory_mode==="automatic"?"Only explicit user facts with verified quotes and no Memory matches are saved automatically.":"You approve each fact before it enters Memory."}</small></label>
    </div>
    <p class="learning-note">A quiet chat is not necessarily finished. Proposals require a completed work episode; development instructions do not become Memory.</p>
    <details class="learning-advanced" data-learning-disclosure="timing" ${e.openSections?.includes("timing")?"open":""}>
      <summary><span><strong>Timing &amp; model</strong><small>${s.idle_seconds} seconds after the last response · ${s.model_source==="workspace"?"Workspace Codex":"Fast API model"}</small></span><span class="material-symbols-rounded" aria-hidden="true">expand_more</span></summary>
      <div class="learning-form-grid">
        ${l("idle_seconds","Quiet period (seconds)",0,3600,"Delay before review. New messages postpone it; this delay does not certify that work is finished.")}
        <label>Analysis model<select name="model_source" ${n}><option value="workspace" ${s.model_source==="workspace"?"selected":""}>Workspace Codex</option><option value="fast_model" ${s.model_source==="fast_model"?"selected":""}>Configured fast API model</option></select><small>API mode uses the fast model configured in platform settings.</small></label>
        <label data-learning-native ${s.model_source==="workspace"?"":"hidden"}>Codex model<select name="model_id" ${n}><option value="">Workspace default</option>${t.map(c=>`<option value="${d(c.model_id)}" ${c.model_id===s.model_id?"selected":""}>${d(c.label||c.model_id)}</option>`).join("")}${s.model_id&&!t.some(c=>c.model_id===s.model_id)?`<option selected value="${d(s.model_id)}">${d(s.model_id)} (unavailable)</option>`:""}</select></label>
        <label data-learning-native ${s.model_source==="workspace"?"":"hidden"}>Reasoning<select name="reasoning_effort" ${n}>${["low","medium","high"].map(c=>`<option value="${c}" ${s.reasoning_effort===c?"selected":""}>${{low:"Low · faster",medium:"Medium",high:"High · more thorough"}[c]}</option>`).join("")}</select></label>
      </div>
    </details>
    <details class="learning-advanced" data-learning-disclosure="limits" ${e.openSections?.includes("limits")?"open":""}>
      <summary><span><strong>Usage &amp; retention</strong><small>${s.daily_token_budget.toLocaleString()} tokens per day · ${s.retention_days} days of transcripts</small></span><span class="material-symbols-rounded" aria-hidden="true">expand_more</span></summary>
      <div class="learning-form-grid">
        ${l("daily_token_budget","Daily token allowance",1e3,1e7,"UTC day. Each analysis reserves tokens before it starts.")}
        ${l("max_context_chars","Context limit (characters)",4e3,6e4,"Maximum conversation evidence per analysis.")}
        ${l("max_output_tokens","Output limit (tokens)",128,8192,"Maximum size of the generated suggestions.")}
        ${l("timeout_seconds","Timeout (seconds)",10,300,"Stop an analysis if it takes too long.")}
        ${l("retention_days","Transcript retention (days)",1,365,"Saved Memory facts and review decisions remain available.")}
        <label>Parallel improvement agents<input type="number" name="improvement_concurrency" min="1" max="8" value="${s.improvement_concurrency??4}" required ${n}><small>Up to this many improvement chats run together. Memory always runs one chat at a time.</small></label>
      </div>
    </details>
    <details class="learning-advanced" data-learning-disclosure="scope" ${e.openSections?.includes("scope")?"open":""}>
      <summary><span><strong>Exclusions &amp; instructions</strong><small>${s.excluded_thread_ids.length+s.excluded_project_ids.length?`${s.excluded_thread_ids.length+s.excluded_project_ids.length} exclusions`:"All eligible chats"} · optional guidance</small></span><span class="material-symbols-rounded" aria-hidden="true">expand_more</span></summary>
      <div class="learning-form-grid">
        <label>Excluded chat IDs<textarea name="excluded_thread_ids" rows="2" ${n}>${d(s.excluded_thread_ids.join(`
`))}</textarea><small>One ID per line. The ID is the last part of a chat URL.</small></label>
        <label>Excluded project IDs<textarea name="excluded_project_ids" rows="2" ${n}>${d(s.excluded_project_ids.join(`
`))}</textarea><small>One ID per line. Chats in these projects are skipped.</small></label>
        <label class="learning-wide">Additional guidance<textarea name="instructions" rows="3" maxlength="4000" placeholder="For example: focus on tool failures, missing capabilities and sourced discoveries…" ${n}>${d(s.instructions)}</textarea></label>
      </div>
    </details>
    <div class="learning-save-bar"><span id="learning-draft-status" role="status">${e.dirty?"Unsaved changes":e.notice||"Settings are up to date"}</span><div class="learning-actions"><button type="button" class="settings-secondary" id="learning-discard" ${e.dirty&&!e.saving?"":"disabled"}>Discard edits</button><button class="settings-primary" type="submit" ${n}>${e.saving?"Saving…":"Save settings"}</button></div></div>
  </form>`}const zn=e=>({pending:"To review",checking:"Checking Memory",saving:"Saving",saved:"Saved",undoing:"Undoing",undone:"Undone",rejected:"Rejected",accepted:"Accepted",implemented:"Implemented",queued:"Waiting",running:"Analyzing",completed:"Completed",failed:"Failed",cancelled:"Cancelled"})[e]||e;function St(e){return d(new Date(e*1e3).toLocaleString())}function Wn(e,t=[]){const{data:s,error:n,saving:a}=e;if(!s)return`<section class="settings-card learning-empty"><strong>${e.loading?"Loading learning settings…":"Learning is unavailable"}</strong>${n?`<p role="alert">${d(n)}</p>`:""}<button class="settings-secondary" id="learning-refresh">Retry</button></section>`;const i=s.settings,r=s.counts||{pending_memory:s.items.filter(m=>m.kind==="memory"&&m.status==="pending").length,pending_improvements:s.items.filter(m=>m.kind==="improvement"&&m.status==="pending").length,queued:s.jobs.filter(m=>m.status==="queued").length,running:s.jobs.filter(m=>m.status==="running").length,failed:s.jobs.filter(m=>m.status==="failed").length,budget_waiting:0},l=i.enabled?i.paused?"Paused":!i.memory_enabled&&!i.improvements_enabled?"No outputs selected":r.running?"Analyzing":"On":"Off",c=i.enabled?i.paused?"Chats are still captured. Resume when you are ready.":!i.memory_enabled&&!i.improvements_enabled?"Choose Memory or Improvements to start analysis.":r.running?"One conversation is being reviewed. The others wait in the queue.":"Quiet periods trigger review. Only completed work can produce proposals.":"Enable learning to capture future conversations.",o=s.daily_tokens_reserved_or_used,p=Math.min(100,Math.round(o/i.daily_token_budget*100)),u=a?"disabled":"",f=m=>s.conversations.find(T=>T.session_id===m)?.label||`Chat ${m.slice(0,8)}`,$={memory:r.open_memory??r.pending_memory,improvements:r.open_improvement??r.pending_improvements,analyses:r.queued+r.running,audit:0};return`<section class="settings-card learning-overview">
    <div class="learning-status-row"><div class="learning-status-copy"><span class="learning-status-dot ${i.enabled&&!i.paused?"is-on":""}" aria-hidden="true"></span><div><h3>Learning is ${l.toLowerCase()}</h3><p>${c}</p></div></div><div class="learning-actions">${i.enabled?`<button id="learning-pause" class="settings-secondary" ${u}>${i.paused?"Resume analysis":"Pause analysis"}</button>`:""}<button id="learning-refresh" class="learning-icon-button" aria-label="Refresh learning status" ${u}><span class="material-symbols-rounded" aria-hidden="true">refresh</span></button></div></div>
    <div class="learning-stats"><div><strong>${r.pending_memory+r.pending_improvements}</strong><span>To review</span></div><div><strong>${r.queued}</strong><span>In queue</span></div><div class="learning-usage"><div><span>Today’s token allowance</span><strong>${p}%</strong></div><progress value="${Math.min(o,i.daily_token_budget)}" max="${i.daily_token_budget}" aria-label="Daily learning token allowance"></progress><small>${o.toLocaleString()} / ${i.daily_token_budget.toLocaleString()} reserved or observed · resets at 00:00 UTC</small></div></div>
    ${o>=i.daily_token_budget?'<p class="learning-notice">Today’s allowance is reached. New analyses wait until the next UTC day or a higher saved allowance.</p>':""}
    ${r.budget_waiting&&o<i.daily_token_budget?'<p class="learning-notice">The remaining allowance cannot cover the next analysis. Increase it in Usage &amp; retention or wait for the UTC reset. Codex reserves extra tokens for its instructions.</p>':""}
    ${r.failed?`<p class="learning-notice">${r.failed} failed ${r.failed===1?"analysis":"analyses"}. Open the Analyses tab to inspect or retry.</p>`:""}
    ${n?`<p class="learning-error" role="alert">${d(n)}</p>`:""}
  </section>
  ${Fn(e,t)}
  <section class="settings-card learning-results">
    <div class="learning-section-heading"><div><h3>Results &amp; history</h3><p>Review suggestions and see what the agent has done.</p></div></div>
    <div class="learning-manual"><label for="learning-session">Analyze a captured chat</label><div class="learning-actions"><select id="learning-session" ${!s.conversations.length||a?"disabled":""}><option value="">${s.conversations.length?"Choose a conversation…":"No captured conversations yet"}</option>${s.conversations.map(m=>`<option value="${d(m.session_id)}" ${e.selectedSession===m.session_id?"selected":""}>${d(f(m.session_id))}</option>`).join("")}</select><button id="learning-analyze" class="settings-secondary" ${a||!i.enabled||i.paused||!e.selectedSession||!i.memory_enabled&&!i.improvements_enabled?"disabled":""}>Analyze now</button></div><p class="learning-note">${i.enabled?i.paused?"Resume analysis to use the queue.":"Adds new captured messages to the same serial queue; active chats wait until ready.":"Enable learning first. Only conversations captured after activation are available."}</p></div>
    <div class="learning-tabs" role="tablist" aria-label="Learning results">${["memory","improvements","analyses","audit"].map(m=>`<button id="learning-tab-${m}" role="tab" aria-controls="learning-panel" aria-selected="${e.tab===m}" tabindex="${e.tab===m?"0":"-1"}" class="${e.tab===m?"is-active":""}" data-learning-tab="${m}">${{memory:"Memory",improvements:"Improvements",analyses:"Analyses",audit:"Activity"}[m]}${$[m]?`<span>${$[m]}</span>`:""}</button>`).join("")}</div>
    <div id="learning-panel" role="tabpanel" aria-labelledby="learning-tab-${e.tab}" tabindex="0">
    ${e.tab==="improvements"||e.tab==="memory"?Nn(e):""}
    ${e.tab==="analyses"?`<div class="learning-list">${s.jobs.map(m=>`<article class="learning-row"><div><div class="learning-item-heading"><strong>${d(f(m.session_id))}</strong><span class="settings-pill">${d(zn(m.status))}</span></div><p>${St(m.created_at)} · ${m.attempts} attempt(s) · ${m.usage||m.reserved} tokens${m.model?` · ${d(m.model)}`:""}</p>${m.error?`<p class="learning-error">${d(m.error)}</p>`:""}</div><div class="learning-actions"><button class="settings-secondary" data-learning-job="${d(m.id)}" data-learning-command="inspect">Details</button>${["queued","running"].includes(m.status)?`<button class="settings-secondary" data-learning-job="${d(m.id)}" data-learning-command="cancel" ${u}>Cancel</button>`:["failed","cancelled"].includes(m.status)?`<button class="settings-secondary" data-learning-job="${d(m.id)}" data-learning-command="retry" ${u}>Retry</button>`:""}</div></article>`).join("")||'<div class="learning-empty"><strong>No analyses yet</strong><p>After activation, finish a chat and wait for the quiet period. Its analysis will appear here.</p></div>'}</div>`:""}
    ${e.tab==="audit"?`<div class="learning-list">${s.audit.map(m=>`<div class="learning-row"><span>${d(m.action.replaceAll("."," · ").replaceAll("_"," "))}</span><small>${St(m.created_at)} · ${d(m.actor)}</small></div>`).join("")||'<div class="learning-empty"><strong>No activity yet</strong><p>Settings changes and review decisions will appear here.</p></div>'}</div>`:""}
    ${e.detail?`<details class="learning-transcript" open><summary>Analysis details · ${d(e.detail.id)}</summary><h4>Conversation evidence</h4><pre>${d(JSON.stringify(e.detail.input,null,2))}</pre><h4>Agent result</h4><pre>${d(e.detail.output_text||"No output available. The run may be pending or its transcript retention period has ended.")}</pre></details>`:""}
    </div>
  </section>`}let xt=!0;const st=()=>xt&&!document.hidden;function Vn(e){window.addEventListener("message",t=>{if(!ot(t)||!t.data||typeof t.data!="object")return;const s=t.data;(s.type==="maverick.shell.theme-changed"||s.type==="maverick.app.navigate"&&(!s.app_id||s.app_id==="settings"))&&$s(s.theme),s.type==="maverick.app.visibility-changed"&&s.app_id==="settings"&&(xt=s.visible===!0,e.visibilityChanged(st())),s.type==="maverick.app.navigate"&&(!s.app_id||s.app_id==="settings")&&e.navigate(s.params||{})}),document.addEventListener("visibilitychange",()=>e.visibilityChanged(st())),window.parent?.postMessage({type:"maverick.app.ready",app_id:"settings"},"*")}function Jn(e){return D("/api/admin/users",{method:"POST",body:JSON.stringify(e)})}function Gn(e,t){return D(`/api/admin/users/${encodeURIComponent(e)}`,{method:"PATCH",body:JSON.stringify(t)})}function Kn(e,t){return D(`/api/admin/users/${encodeURIComponent(e)}/password`,{method:"POST",body:JSON.stringify({password:t})})}function Qn(e){return D(`/api/admin/users/${encodeURIComponent(e)}`,{method:"DELETE"})}function Yn(e,t){return D(`/api/admin/users/${encodeURIComponent(e)}/workspaces`,{method:"PUT",body:JSON.stringify({memberships:t})})}function Xn(e){return D(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"POST",body:JSON.stringify({source_id:e.source_id,enabled:!0})})}function Zn(e,t){return D(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"PATCH",body:JSON.stringify({status:t?"enabled":"disabled"})})}function xn(e){return D(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"DELETE",body:JSON.stringify({})})}function nt(e,t){if(!t)return e;const s="items"in t?t.items:t.sessions,n="cleanup_allowed"in t?t.cleanup_allowed:e.runtime.cleanup_allowed,a="cleanup_scope"in t?t.cleanup_scope:e.runtime.cleanup_scope;return{...e,runtime:{...e.runtime,all_sessions:s||[],cleanup_allowed:n,cleanup_scope:a}}}function ea(e){const t=e?.provider.hosted_text?.active_provider||null,s=e?.provider.hosted_text?.model_settings||null;return ta(t,s)}function es(e){const t=e?.provider.hosted_text||null,s=t?.active_provider||null;return(t?.available_providers?.length?t.available_providers:s?[s]:[]).flatMap(a=>{const i=a.provider_id===s?.provider_id&&t?.model_settings||null;return sa(a,i).map(r=>({...r,hosted_text_profile:t?.profiles?.find(l=>l.profile.provider_id===a.provider_id&&l.profile.model_id===r.model_id)||null,metadata:{...r.metadata||{},hosted_provider_id:a.provider_id,hosted_provider_label:a.label||a.provider_id,hosted_provider_status:a.status}}))})}function ta(e,t){return{modelId:t?.selected_model_id||e?.default_model_family||""}}function sa(e,t){const s=t?.selected_model_id||e?.default_model_family||"",n=We(t?.available_models).length?We(t?.available_models):We(e?.model_options);return(n.length?n:s?[aa(s,t?.selected_reasoning_effort||"")]:[]).map(na)}function We(e){return(e||[]).filter(t=>t.model_id)}function na(e){return e.supported_reasoning_efforts.length||!e.default_reasoning_effort?e:{...e,supported_reasoning_efforts:[{effort:e.default_reasoning_effort,label:e.default_reasoning_effort,description:null}]}}function aa(e,t){return{model_id:e,label:e,description:null,default_reasoning_effort:t||null,supported_reasoning_efforts:t?[{effort:t,label:t,description:null}]:[]}}function ia(){return{computerUse:Qs(),savedDrafts:null,speechSynthesis:Gt(),activatingNativeProviders:new Set,nativeProviderErrors:{},agenticBindingErrors:{},cleanupError:"",clearingAllRuntime:!1,cleaningSessionIds:new Set,hostedDraftModelId:"",hostedProviderError:"",hostedProviderErrorModelId:"",hostedRoutingDraftsByModel:{},isSavingHostedProvider:!1,isSavingSpeechProvider:!1,isLoadingProviderUsage:!1,isLoadingUsageHistory:!1,savingAgenticBindings:new Set,providerUsageError:"",providerUsageItems:[],usageHistory:null,usageHistoryFilters:Ye(),usageHistoryError:"",speechAudioModelId:"",speechConversationModelId:"",speechProviderError:""}}function ie(e,t,s={}){t?.computer_use&&Ke(e.computerUse,t);const n=t?.workspace.workspace_id||"",a=e.savedDrafts?.workspaceId===n?e.savedDrafts:null,{modelId:i}=ea(t),r=ca(t),l=new Set([...es(t).map(o=>o.model_id),i,...Object.keys(a?e.hostedRoutingDraftsByModel:{})].filter(Boolean)),c=Object.fromEntries(Array.from(l).map(o=>[o,Le(Te(t,o))]));(!a||e.hostedDraftModelId===a.hostedModelId||s.hostedModelId)&&(e.hostedDraftModelId=i),(!a||e.speechAudioModelId===a.audioModelId||s.speech)&&(e.speechAudioModelId=r.audioModelId),(!a||e.speechConversationModelId===a.conversationModelId||s.speech)&&(e.speechConversationModelId=r.conversationModelId),e.hostedRoutingDraftsByModel=Object.fromEntries(Array.from(l).map(o=>{const p=e.hostedRoutingDraftsByModel[o],u=a&&p&&JSON.stringify(p)!==JSON.stringify(a.routing[o]);return[o,u&&s.hostedModelId!==o?p:c[o]]})),e.savedDrafts={workspaceId:n,hostedModelId:i,audioModelId:r.audioModelId,conversationModelId:r.conversationModelId,routing:Object.fromEntries(Object.entries(c).map(([o,p])=>[o,{...p}]))}}function ra(e,t,s){e.hostedDraftModelId=s,ns(e,t,s),e.hostedProviderError="",e.hostedProviderErrorModelId=""}function oa(e,t){e.speechAudioModelId=t,e.speechProviderError=""}function la(e,t){e.speechConversationModelId=t,e.speechProviderError=""}function da(e,t,s,n,a){if(!s)return;const i=ns(e,t,s);e.hostedDraftModelId=s,n==="mode"&&typeof a=="string"&&["auto","prefer","only","ignore"].includes(a)?i.mode=a:n==="provider_id"&&typeof a=="string"?i.providerId=a:n==="allow_fallbacks"&&typeof a=="boolean"?i.allowFallbacks=a:n==="require_parameters"&&typeof a=="boolean"?i.requireParameters=a:n==="zdr"&&typeof a=="boolean"?i.zdr=a:n==="sort"&&typeof a=="string"&&["","price","throughput","latency"].includes(a)?i.sort=a:n==="data_collection"&&typeof a=="string"&&["","allow","deny"].includes(a)?i.dataCollection=a:n==="quantization"&&typeof a=="string"&&(i.quantization=a),e.hostedProviderError="",e.hostedProviderErrorModelId=""}function ts(e,t=e.hostedDraftModelId){const s=e.hostedRoutingDraftsByModel[t]||ga();return{mode:s.mode,provider_id:s.providerId||void 0,allow_fallbacks:s.allowFallbacks,require_parameters:s.requireParameters,zdr:s.zdr,sort:s.sort,data_collection:s.dataCollection,quantizations:s.quantization?[s.quantization]:[]}}function ca(e){const t=e?.provider.speech_stt||null,s=t?.active_provider||t?.available_providers?.find(i=>i.provider_id==="deepgram")||null,n=Me(t,s,"prerecorded_transcription"),a=Me(t,s,"conversational_streaming");return{audioModelId:t?.model_settings?.audio_transcription_model_id||n.find(i=>i.model_id==="nova-3")?.model_id||n[0]?.model_id||"nova-3",conversationModelId:t?.model_settings?.conversation_model_id||a.find(i=>i.model_id==="flux-general-multi")?.model_id||a[0]?.model_id||"flux-general-multi"}}function Me(e,t,s){const n=s==="prerecorded_transcription"?e?.model_settings?.available_audio_transcription_models:e?.model_settings?.available_conversation_models;return n?.length?n:(e?.model_settings?.available_models?.length?e.model_settings.available_models:t?.model_options||[]).filter(i=>i.metadata?.purpose===s)}function Te(e,t){const s=e?.provider.hosted_text?.selection?.openrouter_provider_routing_by_model?.[t];return{mode:s?.mode||"auto",provider_id:s?.provider_id||"",allow_fallbacks:s?.allow_fallbacks!==!1,require_parameters:s?.require_parameters===!0,zdr:s?.zdr===!0,sort:s?.sort||"",data_collection:s?.data_collection||"",quantizations:s?.quantizations||[]}}function ss(e,t,s){const n=Te(t,s),a=ts(e,s);return n.mode!==a.mode||(n.provider_id||"")!==(a.provider_id||"")||n.allow_fallbacks!==!1!=(a.allow_fallbacks!==!1)||n.require_parameters===!0!=(a.require_parameters===!0)||n.zdr===!0!=(a.zdr===!0)||(n.sort||"")!==(a.sort||"")||(n.data_collection||"")!==(a.data_collection||"")||(n.quantizations?.[0]||"")!==(a.quantizations?.[0]||"")}function pa(e,t){return t.hostedProviderErrorModelId?t.hostedProviderErrorModelId:!t.hostedDraftModelId||!ss(t,e,t.hostedDraftModelId)?"":t.hostedDraftModelId}function ua(e,t,s){return e.hostedRoutingDraftsByModel[s]||Le(Te(t,s))}function ns(e,t,s){return e.hostedRoutingDraftsByModel[s]||(e.hostedRoutingDraftsByModel[s]=Le(Te(t,s))),e.hostedRoutingDraftsByModel[s]}function Le(e){return{allowFallbacks:e.allow_fallbacks!==!1,dataCollection:e.data_collection||"",mode:e.mode||"auto",providerId:e.provider_id||"",quantization:e.quantizations?.[0]||"",requireParameters:e.require_parameters===!0,sort:e.sort||"",zdr:e.zdr===!0}}function ga(){return Le({mode:"auto",allow_fallbacks:!0,require_parameters:!1,zdr:!1,sort:"",data_collection:"",quantizations:[]})}function ae(e,t,s=""){return`<label class="settings-toggle settings-bouncy-toggle ${s}">
    ${e}
    <span class="settings-bouncy-toggle__label">${t}</span>
    <span class="settings-bouncy-toggle__track" aria-hidden="true">
      <span class="settings-bouncy-toggle__inner"></span>
      <span class="settings-bouncy-toggle__thumb"><span class="settings-bouncy-toggle__dot"></span></span>
    </span>
  </label>`}function ma(e=document){e.querySelectorAll(".settings-bouncy-toggle").forEach(t=>{const s=n=>t.classList.toggle("is-pressed",n);v(t,"pointerdown",()=>s(!0)),v(t,"pointerup",()=>s(!1)),v(t,"pointerleave",()=>s(!1))})}const fa=[{family_id:"native_agent",label:"CLI models",description:"Models running through an installed CLI.",workspace_actions:!0},{family_id:"maverick_agent",label:"API models",description:"Models running through a provider API.",workspace_actions:!0}];function Et(e,t){return t?.find(s=>s.family_id===e)||fa.find(s=>s.family_id===e)}function as(e,t){return`<div class="settings-heading settings-platform-heading settings-model-card-heading">
    <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">${d(e)}</span>
      <div>
        <p class="settings-kicker">Models</p>
        <h2>${d(t)}</h2>
      </div>
    </div>`}function va(e,t,s,n,a){const i=new Set(n.filter(h=>a&&h.runtime_engine_id!=="codex"&&h.unavailable_reason==="native_agent_disabled"&&h.models.length>0).map(h=>h.runtime_engine_id)),r=e?.items||[],l=r,c=e?.release_decision||"GO",o=Et("native_agent",s||e?.execution_families),p=Et("maverick_agent",s||e?.execution_families),u=l.filter(h=>h.execution_family==="native_agent"||!h.execution_family&&h.runtime_engine_id==="codex"),f=l.filter(h=>h.execution_family==="maverick_agent"),$=new Set(r.filter(h=>h.execution_family==="native_agent"||!h.execution_family&&h.runtime_engine_id==="codex").map(h=>h.runtime_engine_id)),m=n.filter(h=>!$.has(h.runtime_engine_id)),T=[...ba(u).map(h=>({html:Ct(h,t),providerId:h.runtime_engine_id,canActivate:i.has(h.runtime_engine_id),providerLabel:Se(h.runtime_engine_id)})),...m.map(h=>({html:ya(h),providerId:h.runtime_engine_id,canActivate:i.has(h.runtime_engine_id),providerLabel:h.label||Se(h.runtime_engine_id)}))],w=f.map(h=>({html:Ct(h,t),providerId:h.model_provider_id,providerLabel:Se(h.model_provider_id)}));return`<section class="settings-card settings-platform settings-agentic-runtimes-card">
    ${as("account_tree","Models")}
    ${c==="NO-GO"?'<p class="settings-platform-error settings-agentic-no-go"><strong>Remote agentic release: NO-GO</strong><br>Remote profiles remain visible for containment review but cannot be enabled or selected.</p>':""}
    ${It(o,T,t,"No native-agent runtime is registered by this installation.")}
    ${It(p,w,t,"No complete Maverick Agent profile is currently available.")}
  </section>`}function It(e,t,s,n){const a=ha(t);return`<section class="settings-runtime-family" data-execution-family="${b(e.family_id)}">
    <header class="settings-runtime-family-heading">
      <h3>${d(e.label)}</h3>
    </header>
    <div class="settings-runtime-provider-list">
      ${a.length?a.map(i=>_a(i,s)).join(""):`<div class="settings-provider-usage-unavailable">
        <span class="material-symbols-rounded" aria-hidden="true">info</span>
        <span><strong>No available profiles</strong><small>${d(n)}</small></span>
      </div>`}
    </div>
  </section>`}function ha(e){const t=new Map;e.forEach(n=>{const a=t.get(n.providerId)||[];a.push(n),t.set(n.providerId,a)});const s=new Map([["codex",0],["antigravity-cli",1],["openrouter",2],["google-ai-studio",3]]);return Array.from(t.entries()).map(([n,a])=>({providerId:n,providerLabel:a[0]?.providerLabel||Se(n),items:a})).sort((n,a)=>(s.get(n.providerId)??100)-(s.get(a.providerId)??100)||n.providerLabel.localeCompare(a.providerLabel))}function _a(e,t){const s=e.items.some(i=>i.canActivate),n=t.activatingNativeProviders.has(e.providerId),a=t.nativeProviderErrors[e.providerId];return`<section class="settings-runtime-provider" data-agentic-provider-group="${b(e.providerId)}">
    <header class="settings-runtime-provider-heading">
      <h4>${d(e.providerLabel)}</h4>

    </header>
    ${s?`<div class="settings-native-provider-activation">
      <span>Connection disabled. Enable it for this installation to use the selected models.</span>
      <button type="button" data-native-provider-activate="${b(e.providerId)}" ${n?"disabled":""}>
        ${n?"Enabling…":`Enable ${d(e.providerLabel)}`}
      </button>
    </div>`:""}
    ${a?`<p class="settings-platform-error" role="alert">${d(a)}</p>`:""}
    <div class="settings-agentic-runtime-list">${e.items.map(i=>i.html).join("")}</div>
  </section>`}function Se(e){return{"antigravity-cli":"Antigravity",codex:"Codex","google-ai-studio":"Google AI Studio",openrouter:"OpenRouter"}[e]||fe(e)}function ba(e){const t=new Map,s=[];return e.forEach(n=>{const a=n.runtime_engine_id==="antigravity-cli"?n.model_id.replace(/-(high|medium|low)$/i,""):n.model_id,i=`${n.runtime_engine_id}\0${a}`;t.has(i)||s.push(i);const r=t.get(i);(!r||At(n.model_id)>At(r.model_id))&&t.set(i,n)}),s.map(n=>t.get(n)).filter(n=>!!n)}function At(e){const t=e.match(/-(high|medium|low)$/i)?.[1]?.toLowerCase();return t==="high"?3:t==="medium"?2:t==="low"?1:0}function ya(e){const t=e.models[0],s=e.unavailable_reason||"native_agent_unavailable",n=e.selectable===!0;return`<article class="settings-agentic-runtime settings-native-runtime-installation settings-agentic-runtime-static">
    <div class="settings-agentic-runtime-static__content">
      <span class="settings-model-summary-copy">
        <strong>${d(t?.model_id||e.label)}</strong>
        <small>${d(is(t?.model_id,null))}</small>
      </span>
      <span class="settings-agentic-summary-badges">
        <span class="settings-pill ${n?"is-healthy":"is-warning"}">${n?"Available":d(fe(s))}</span>
      </span>
    </div>
  </article>`}function Ct(e,t){const s=e.definition_id,n=e.binding,a=n?.workspace_policy_ceiling||e.profile_policy_ceiling,i=n?.actor_policy||{allow_workspace_admins:!0,allowed_workspace_role_ids:["admin","member"]},r=e.execution_family==="maverick_agent",l=e.effective_capabilities,c=e.containment_status==="NO-GO",o=t.savingAgenticBindings.has(s),p=t.agenticBindingErrors[s]||"",u=a.max_estimated_cost_microusd===null?"":String(a.max_estimated_cost_microusd/1e6),f=e.credential_bindings,$=n?.credential_binding_id||f[0]?.binding_id||"",m=!!n?.enabled,T=e.selectable===!0||!m&&e.enable_eligible===!0,w=e.enable_blocked_reason||e.blocked_reason||(r&&l?.status!=="active"?l?.reason_code||"effective capabilities unavailable":"")||"Unavailable";return`<details class="settings-model-accordion settings-agentic-runtime" data-settings-model-accordion="agentic-${b(s)}">
    <summary>
      <span class="settings-model-summary-copy">
        <strong>${d(Mt(e))}</strong>
        <small>${d(is(e.model_id,e.default_reasoning_effort))}</small>
      </span>
      <span class="settings-agentic-summary-badges">
        ${n?.is_default?'<span class="settings-pill">Default</span>':""}
        ${c?'<span class="settings-pill is-warning">NO-GO</span>':""}
        ${T?"":`<span class="settings-pill is-warning">${d(fe(w))}</span>`}
        <label class="settings-model-toggle settings-toggle settings-bouncy-toggle" title="${m?"Disable model":"Enable model"}">
          <input type="checkbox" role="switch" data-agentic-model-toggle aria-label="Enable ${b(Mt(e))}"
            data-agentic-definition-id="${b(e.definition_id)}"
            ${m?"checked":""} ${o||e.enable_eligible!==!0&&!m?"disabled":""}>
          <span class="settings-bouncy-toggle__label">${m?"On":"Off"}</span>
          <span class="settings-bouncy-toggle__track" aria-hidden="true">
            <span class="settings-bouncy-toggle__inner"></span>
            <span class="settings-bouncy-toggle__thumb"><span class="settings-bouncy-toggle__dot"></span></span>
          </span>
        </label>
      </span>
    </summary>
    <div class="settings-model-content settings-agentic-runtime-content" data-agentic-binding-form data-agentic-definition-id="${b(e.definition_id)}">
      ${c?`<div class="settings-provider-usage-unavailable settings-agentic-containment-state">
        <span class="material-symbols-rounded" aria-hidden="true">block</span>
        <span>
          <strong>NO-GO · ${d(fe(e.containment_reason||"remote agentic contained"))}</strong>
          <small>${d(e.data_destination.display_label)}</small>
        </span>
      </div>`:""}
      <div class="settings-agentic-controls">
        ${r?`<label class="settings-platform-field">
          <span>Credential binding</span>
          <select data-agentic-field="credential_binding_id" ${o||c?"disabled":""}>
            <option value="">${f.length?"No credential":"No active credential available"}</option>
            ${f.map(h=>`<option value="${b(h.binding_id)}" ${h.binding_id===$?"selected":""}>${d(h.label||h.binding_id)} · ${h.workspace_id?"workspace":"platform"}</option>`).join("")}
          </select>
        </label>`:'<input data-agentic-field="credential_binding_id" type="hidden" value="">'}
        <label class="settings-platform-field">
          <span>Maximum cost per turn (USD)</span>
          <input data-agentic-field="max_estimated_cost_usd" type="number" min="0" step="0.01" value="${b(u)}" placeholder="No explicit ceiling" ${o||c?"disabled":""}>
        </label>
        <div class="settings-platform-checks settings-agentic-checks">
          <input data-agentic-field="enabled" type="checkbox" ${m?"checked":""} hidden>
          ${de("is_default","Use as workspace default",!!n?.is_default,o||c)}
          <details class="settings-agentic-advanced">
            <summary>Advanced controls</summary>
            ${de("allow_workspace_admins","Workspace administrators",i.allow_workspace_admins,o||c)}
            ${de("allow_workspace_members","Workspace members",i.allowed_workspace_role_ids.includes("member"),o||c)}
            ${de("require_confirmation_for_mutating","Confirm mutating tools",a.require_confirmation_for_mutating,o||c,e.profile_policy_ceiling.require_confirmation_for_mutating)}
            ${de("require_confirmation_for_destructive","Confirm destructive tools",a.require_confirmation_for_destructive,o||c,e.profile_policy_ceiling.require_confirmation_for_destructive)}
          </details>
        </div>
      </div>
      <button type="button" data-agentic-binding-save data-agentic-definition-id="${b(e.definition_id)}" ${o||c?"disabled":""}>
        <span class="material-symbols-rounded" aria-hidden="true">${o?"progress_activity":"verified_user"}</span>
        ${o?"Saving binding":n?"Save binding":"Create binding"}
      </button>
      ${p?`<p class="settings-platform-error" role="alert">${d(p)}</p>`:""}
    </div>
  </details>`}function de(e,t,s,n,a=!1){return ae(`<input data-agentic-field="${b(e)}" type="checkbox" role="switch" ${s?"checked":""} ${n||a?"disabled":""}>`,d(t))}function Mt(e){return e.runtime_engine_id==="codex"||e.runtime_engine_id==="antigravity-cli"?e.model_id:e.display_name.replace(/^OpenRouter\s+/i,"").replace(/^Google\s+/i,"").replace(/\s+·\s+Relace$/i,"")}function is(e,t){const s=e?.match(/-(max|xhigh|high|medium|low)$/i)?.[1]||"",n=t||s;return`Reasoning · ${n?fe(n):"Preset"}`}function fe(e){return e.replace(/[._-]+/g," ").replace(/\b\w/g,t=>t.toUpperCase())}function $a({modelOptions:e,openHostedModel:t,hostedProvider:s,settings:n,state:a,emptyMessage:i,inactiveMessage:r}){const l=!!s,c=Sa(e,s);return`<div class="settings-hosted-models">
    ${e.length?c.map(o=>wa(o,t,s,n,a)).join(""):`<p class="settings-card-copy settings-platform-note">${d(i)}</p>`}
    ${l?"":`<p class="settings-card-copy settings-platform-note">${d(r)}</p>`}
  </div>`}function wa(e,t,s,n,a){const i=e.providerStatus==="active"?"Active provider":"Inactive provider";return`<section class="settings-hosted-provider-group" data-hosted-provider-group="${b(e.providerId)}">
    <div class="settings-hosted-provider-heading">
      <span>
        <strong>${d(e.providerLabel)}</strong>
        <small>${e.models.length} ${e.models.length===1?"model":"models"}</small>
      </span>
      <span class="settings-pill">${d(i)}</span>
    </div>
    ${e.models.map(r=>ka(r,t,s,n,a)).join("")}
  </section>`}function ka(e,t,s,n,a){const i=e.model_id,r=ua(a,n,i),l=e.upstream_provider_options||[],c=l.length>0,o=Array.from(new Set(l.map(y=>y.quantization||"").filter(Boolean))),p=rs(e,s),u=ls(e,s),f=!!p,$=a.isSavingHostedProvider&&a.hostedDraftModelId===i,m=n.provider.hosted_text?.selection?.provider_id||s?.provider_id||"",T=p===m&&(n.provider.hosted_text?.model_settings?.selected_model_id||s?.default_model_family)||"",w=!!(f&&u==="active"&&i&&!a.isSavingHostedProvider&&(p!==m||i!==T||ss(a,n,i))),h=i===t,M=os(e,s);return`<details class="settings-model-accordion settings-hosted-model-accordion" data-settings-model-accordion="hosted:${b(i)}" data-hosted-model-accordion="${b(i)}" id="settings-hosted-${b(encodeURIComponent(i))}" ${h?"open":""}>
    <summary class="settings-model-trigger">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">record_voice_over</span>
      <span class="settings-model-copy">
        <span class="settings-model-kicker">
          <span class="settings-kicker">Hosted speech model</span>
        </span>
        <strong>${d(e.label||i)} - ${d(M)}</strong>
        <small>${d(i||"model not selected")} · speech synthesis metadata</small>
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
      <select data-openrouter-routing="mode" data-hosted-model-id="${b(i)}" ${!f||!l.length||a.isSavingHostedProvider?"disabled":""}>
        ${[["auto","Auto"],["prefer","Prefer selected"],["only","Only selected"],["ignore","Ignore selected"]].map(([y,E])=>`<option value="${b(y)}" ${y===r.mode?"selected":""}>${d(E)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Upstream provider</span>
      <select data-openrouter-routing="provider_id" data-hosted-model-id="${b(i)}" ${!f||!l.length||r.mode==="auto"||a.isSavingHostedProvider?"disabled":""}>
        <option value="">Select provider</option>
        ${l.map(y=>`<option value="${b(String(y.provider_id||y.tag||""))}" ${(y.provider_id||y.tag)===r.providerId?"selected":""}>${d(y.label||y.provider_id||y.tag||"Provider")}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Sort</span>
      <select data-openrouter-routing="sort" data-hosted-model-id="${b(i)}" ${!f||a.isSavingHostedProvider?"disabled":""}>
        ${[["","OpenRouter default"],["price","Price"],["throughput","Throughput"],["latency","Latency"]].map(([y,E])=>`<option value="${b(y)}" ${y===r.sort?"selected":""}>${d(E)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Data collection</span>
      <select data-openrouter-routing="data_collection" data-hosted-model-id="${b(i)}" ${!f||a.isSavingHostedProvider?"disabled":""}>
        ${[["","OpenRouter default"],["allow","Allow"],["deny","Deny"]].map(([y,E])=>`<option value="${b(y)}" ${y===r.dataCollection?"selected":""}>${d(E)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Quantization</span>
      <select data-openrouter-routing="quantization" data-hosted-model-id="${b(i)}" ${!f||!o.length||a.isSavingHostedProvider?"disabled":""}>
        <option value="">Any</option>
        ${o.map(y=>`<option value="${b(y)}" ${y===r.quantization?"selected":""}>${d(y)}</option>`).join("")}
      </select>
    </label>
    <div class="settings-platform-checks">
      ${ae(`<input type="checkbox" role="switch" data-openrouter-routing="allow_fallbacks" data-hosted-model-id="${b(i)}" ${r.allowFallbacks?"checked":""} ${!f||a.isSavingHostedProvider?"disabled":""}>`,"Allow OpenRouter fallback")}
      ${ae(`<input type="checkbox" role="switch" data-openrouter-routing="require_parameters" data-hosted-model-id="${b(i)}" ${r.requireParameters?"checked":""} ${!f||a.isSavingHostedProvider?"disabled":""}>`,"Require supported parameters")}
      ${ae(`<input type="checkbox" role="switch" data-openrouter-routing="zdr" data-hosted-model-id="${b(i)}" ${r.zdr?"checked":""} ${!f||a.isSavingHostedProvider?"disabled":""}>`,"Require zero data retention")}
    </div>
    `:""}
    <button type="button" data-hosted-provider-save="${b(i)}" ${w?"":"disabled"}>
      <span class="material-symbols-rounded" aria-hidden="true">${$?"sync":"save"}</span>
      ${$?"Saving":"Save hosted model"}
    </button>
    ${a.hostedProviderError&&a.hostedProviderErrorModelId===i?`<p class="settings-platform-error">${d(a.hostedProviderError)}</p>`:""}
    </div>
  </details>`}function Sa(e,t){const s=new Map;for(const n of e){const a=rs(n,t)||"hosted-provider",i=s.get(a);if(i){i.models.push(n);continue}s.set(a,{providerId:a,providerLabel:os(n,t),providerStatus:ls(n,t),models:[n]})}return Array.from(s.values()).sort((n,a)=>n.providerStatus==="active"&&a.providerStatus!=="active"?-1:a.providerStatus==="active"&&n.providerStatus!=="active"?1:n.providerLabel.localeCompare(a.providerLabel))}function rs(e,t){const s=e.metadata?.hosted_provider_id;return typeof s=="string"&&s?s:t?.provider_id||""}function os(e,t){const s=e.metadata?.hosted_provider_label;return typeof s=="string"&&s?s:t?.label||t?.provider_id||"Hosted provider"}function ls(e,t){const s=e.metadata?.hosted_provider_status;return typeof s=="string"&&s?s:t?.status||""}function Ea(e,t){const s=e?.active_provider||e?.available_providers?.find(M=>M.provider_id==="deepgram")||null,n=Me(e,s,"prerecorded_transcription"),a=Me(e,s,"conversational_streaming"),i=e?.model_settings?.audio_transcription_model_id||n[0]?.model_id||"nova-3",r=e?.model_settings?.conversation_model_id||a[0]?.model_id||"flux-general-multi",l=t.speechAudioModelId||i,c=t.speechConversationModelId||r,o=n.find(M=>M.model_id===l)||n[0]||null,p=a.find(M=>M.model_id===c)||a[0]||null,u=qt(o,e?.model_settings?.endpoints?.audio_transcription||`https://api.deepgram.com/v1/listen?model=${l}`),f=qt(p,e?.model_settings?.endpoints?.conversation||`wss://api.deepgram.com/v2/listen?model=${c}`),$=!!(e?.active_provider&&e?.credential_binding),m=!!($&&l&&c&&!t.isSavingSpeechProvider&&(l!==i||c!==r)),T=s?.label||s?.provider_id||"Deepgram",w=s?.provider_id||"deepgram",h=$?"Active provider":"Inactive provider";return`<div class="settings-hosted-models settings-speech-models">
    <section class="settings-hosted-provider-group" data-speech-provider-group="${b(w)}">
      <div class="settings-hosted-provider-heading">
        <span>
          <strong>${d(T)}</strong>
          <small>2 settings</small>
        </span>
        <span class="settings-pill">${d(h)}</span>
      </div>
      ${Pt({id:"settings-speech-audio-model",label:"Audio transcription model",icon:"hearing",value:l,options:n,endpoint:u,description:o?.description||"Deepgram model for prerecorded audio, files, and one-shot microphone transcription.",disabled:!$||t.isSavingSpeechProvider,canSave:m,isSaving:t.isSavingSpeechProvider})}
      ${Pt({id:"settings-speech-conversation-model",label:"Conversation model",icon:"forum",value:c,options:a,endpoint:f,description:p?.description||"Deepgram Flux model for realtime voice conversation and turn detection.",disabled:!$||t.isSavingSpeechProvider,canSave:m,isSaving:t.isSavingSpeechProvider})}
    </section>
    ${t.speechProviderError?`<p class="settings-platform-error">${d(t.speechProviderError)}</p>`:""}
    ${$?"":'<p class="settings-card-copy settings-platform-note">Activate Deepgram with a Core Secrets binding before using speech-to-text.</p>'}
  </div>`}function Pt({id:e,label:t,icon:s,value:n,options:a,endpoint:i,description:r,disabled:l,canSave:c,isSaving:o}){return a.length?`<details class="settings-model-accordion settings-speech-model-accordion">
    <summary class="settings-model-trigger">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">${d(s)}</span>
      <span class="settings-model-copy">
        <span class="settings-model-kicker">
          <span class="settings-kicker">${d(t)}</span>
        </span>
        <strong>${d(a.find(p=>p.model_id===n)?.label||n)}</strong>
        <small>${d(n)} · ${d(i)}</small>
      </span>
      <span class="settings-model-chevron material-symbols-rounded" aria-hidden="true">expand_more</span>
    </summary>
    <div class="settings-model-content settings-hosted-model-content">
      <label class="settings-platform-field settings-platform-field-wide">
        <span>${d(t)}</span>
        <select id="${b(e)}" ${l?"disabled":""}>
          ${a.map(p=>`<option value="${b(p.model_id)}" ${p.model_id===n?"selected":""}>${d(p.label||p.model_id)}</option>`).join("")}
        </select>
      </label>
      <div class="settings-platform-field settings-platform-field-wide">
        <span>Endpoint</span>
        <code class="settings-model-code">${d(i)}</code>
      </div>
      <p class="settings-card-copy">${d(r)}</p>
      <button type="button" data-speech-discard class="settings-secondary" ${c&&!o?"":"disabled"}>Discard edits</button>
      <button type="button" data-speech-save="${b(e)}" ${c?"":"disabled"}>
        <span class="material-symbols-rounded" aria-hidden="true">${o?"sync":"save"}</span>
        ${o?"Saving":"Save speech model"}
      </button>
    </div>
  </details>`:`<p class="settings-card-copy settings-platform-note">No ${d(t.toLowerCase())} options are available.</p>`}function qt(e,t){const s=e?.metadata?.endpoint;return typeof s=="string"&&s?s:t}function Ia(e,t){const s=es(e).filter(Ca);return Aa(s,pa(e,t),e.provider.hosted_text?.active_provider||null,e.provider.speech_stt||null,e,t)}function Aa(e,t,s,n,a,i){return`<section class="settings-card settings-platform settings-speech-model-settings-card">
    ${as("record_voice_over","Speech model settings")}
    <div class="settings-platform-provider-forms">
      ${Ks(i.speechSynthesis)}
      ${$a({modelOptions:e,openHostedModel:t,hostedProvider:s,settings:a,state:i,emptyMessage:"No hosted speech models are available from the active hosted providers.",inactiveMessage:"Activate the hosted provider before saving speech model routing."})}
      ${Ea(n,i)}
    </div>
  </section>`}function Ca(e){return(e.output_modalities||[]).includes("speech")}function Ma(e,t,s="models"){return e?s==="computer-use"?Ys(e,t.computerUse):s==="voice"?Ia(e,t):va(e.agentic_admin||null,t,e.provider.execution_families,e.provider.native_agents?.items||[],e.user.platform_role==="admin"):'<section class="settings-card"><p role="alert">Settings unavailable.</p></section>'}const Pa=5,qa=4,Da=4,Ra=3,Ta=4;function La(e){return`<section class="settings-loading-skeleton" role="status" aria-label="Settings content is loading">
    <header class="detail-header settings-loading-skeleton__header" aria-hidden="true">
      <div class="detail-title-block">
        ${R("title")}
        <span class="detail-title-separator" aria-hidden="true"></span>
        ${R("subtitle")}
      </div>
    </header>
    ${Ha(e)}
  </section>`}function Ha(e){return e.id==="workspace-access"?Na():e.id==="workspace-apps"?Ba():["models","voice","computer-use","usage","sessions"].includes(e.id)?ja():e.id==="persistence"?Fa():e.id==="cache"?Ua():e.id==="learning"?`<section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">${te(!0)}<div class="settings-loading-skeleton__field-grid">${G(3,()=>R("copy"))}</div></section>
      <section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">${te(!0)}${G(2,()=>O("toggle"))}${G(3,()=>R("copy-wide"))}${O("button")}</section>`:Oa()}function Ua(){return`<section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
    ${te(!0)}
    ${R("copy-wide")}
    <div class="settings-loading-skeleton__rows">
      ${G(4,()=>cs())}
    </div>
    ${O("button")}
  </section>`}function Oa(){return`<section class="settings-card settings-loading-skeleton__create" aria-hidden="true">
      ${za("short-title")}
      ${G(Pa,()=>O("field"))}
      ${O("button")}
    </section>
    ${ds()}
    <div class="settings-loading-skeleton__profile-row" aria-hidden="true">
      <section class="settings-card settings-loading-skeleton__detail-card">
        ${te(!0)}
        <div class="settings-loading-skeleton__field-grid">
          ${G(qa,()=>Pe())}
        </div>
        ${O("toggle")}
        ${O("button")}
      </section>
      <section class="settings-card settings-loading-skeleton__password-card">
        ${te(!1)}
        ${R("copy")}
        <div class="settings-loading-skeleton__field-grid">
          ${G(2,()=>Pe())}
        </div>
        ${O("button")}
        ${O("danger-button")}
      </section>
    </div>`}function Na(){return`${ds()}
    <section class="settings-card" aria-hidden="true">
      ${te(!0)}
      <div class="settings-loading-skeleton__rows">
        ${G(Da,()=>Wa())}
      </div>
    </section>`}function Ba(){return`<section class="settings-card" aria-hidden="true">
      ${te(!1)}
      ${R("copy-wide")}
      <div class="settings-loading-skeleton__rows">
        ${G(Ra,()=>Va())}
      </div>
    </section>`}function ja(){return`<section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
      ${Ve()}
    </section>
    <section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
      ${Ve()}
      <div class="settings-loading-skeleton__provider-form">
        ${G(2,()=>Pe())}
        ${O("button")}
      </div>
      ${Ve()}
    </section>
    <section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
      <div class="settings-loading-skeleton__runtime-toolbar">
        ${R("copy-wide")}
        ${O("button")}
      </div>
      <div class="settings-loading-skeleton__runtime-list">
        ${G(Ta,()=>Ja())}
      </div>
    </section>`}function Fa(){return`<section class="settings-card settings-loading-skeleton__persistence" aria-hidden="true">
      ${te(!0)}
      <div class="settings-loading-skeleton__adapter-cards">
        ${G(2,()=>Ga())}
      </div>
      ${cs()}
    </section>`}function ds(){return`<section class="settings-card settings-user-picker" aria-hidden="true">
    <div class="settings-loading-skeleton__copy-stack">
      ${R("kicker")}
      ${R("card-title")}
      ${R("copy-short")}
    </div>
    ${Pe()}
  </section>`}function te(e){return`<div class="settings-loading-skeleton__heading">
    <span class="settings-loading-skeleton__copy-stack">
      ${R("kicker")}
      ${R("card-title")}
    </span>
    ${e?O("pill"):""}
  </div>`}function za(e){return`<div class="settings-loading-skeleton__copy-stack">
    ${R("kicker")}
    ${R(e)}
  </div>`}function Pe(){return`<span class="settings-loading-skeleton__field-wrap">
    ${R("label")}
    ${O("field")}
  </span>`}function Wa(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--membership">
    ${O("checkbox")}
    ${le("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${R("row-title")}
      ${R("row-copy")}
    </span>
    ${O("select")}
  </span>`}function Va(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--app">
    ${le("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${R("row-title")}
      ${R("row-copy")}
    </span>
    ${O("toggle-pill")}
    ${O("button")}
  </span>`}function Ve(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--tile">
    ${le("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${R("row-title")}
      ${R("row-copy")}
    </span>
  </span>`}function Ja(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--runtime">
    ${le("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${R("row-title")}
      ${R("row-copy")}
    </span>
    ${O("button")}
  </span>`}function Ga(){return`<span class="settings-loading-skeleton__adapter-card">
    ${le("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${R("row-title")}
      ${R("row-copy-wide")}
    </span>
    ${O("pill")}
  </span>`}function cs(){return`<span class="settings-loading-skeleton__result">
    ${le("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${R("row-title")}
      ${R("row-copy-wide")}
    </span>
  </span>`}function R(e){return`<span class="settings-loading-skeleton__line settings-loading-skeleton__line--${e}"></span>`}function O(e){return`<span class="settings-loading-skeleton__block settings-loading-skeleton__block--${e}"></span>`}function le(e){return`<span class="settings-loading-skeleton__icon settings-loading-skeleton__icon--${e}"></span>`}function G(e,t){return Array.from({length:e},t).join("")}function Ka({publishChanged:e,render:t,setNotice:s}){let n=[],a=[],i="",r=[],l="",c=!1,o=0,p=new Set;function u(){return{appRegistry:n,dependencies:a,error:i,isLoading:c,loadErrors:r,savingKeys:p}}function f(){o+=1,c=!1,n=[],a=[],i="",r=[],l=""}function $(){l=""}async function m(h,M,y=!1){if(!h||c||!y&&l===h)return;const E=++o;c=!0,i="",r=[],t();try{const[W,U]=await Promise.all([Ls(),w(h,M)]);if(E!==o)return;n=W,a=U.dependencies,r=U.errors,l=h}catch(W){if(E!==o)return;l="",i=W instanceof Error?W.message:"Unable to load app links."}finally{if(E!==o)return;c=!1,t()}}async function T(h,M,y){const E=o,W=Qa(h,M);p=new Set([...p,W]),t();try{const U=await Jt(h,M,y);if(E!==o)return;a=a.map(Y=>Y.consumer_app_id===h?U:Y),e(h,U),s({tone:"success",message:"App link updated."})}finally{if(E!==o)return;const U=new Set(p);U.delete(W),p=U,t()}}async function w(h,M){const y=M.filter(g=>g.workspace_id===h&&g.status==="enabled"),E=new Array(y.length);let W=0;const U=o;await Promise.all(Array.from({length:Math.min(4,y.length)},async()=>{for(;W<y.length&&U===o;){const g=W++,_=y[g];try{E[g]={app:_,payload:await lt(_.app_id)}}catch(I){E[g]={app:_,error:I instanceof Error?I.message:"Unable to load app links."}}}}));const Y=E.filter(Boolean),q=Y.filter(g=>"error"in g).map(g=>({app_id:g.app.app_id,message:g.error,name:g.app.name||g.app.app_id}));return{dependencies:Y.filter(g=>"payload"in g&&g.payload.dependencies.length>0).map(g=>g.payload).sort((g,_)=>g.consumer_app_id.localeCompare(_.consumer_app_id)),errors:q}}return{ensureLoaded:m,invalidate:$,reset:f,saveDependencySelection:T,viewState:u}}function Qa(e,t){return`${e}:${t}`}function Ya({appRegistry:e,dependencies:t,error:s,isLoading:n,loadErrors:a,savingKeys:i,workspaceApps:r}){return`<section class="settings-card settings-app-links">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">App links</p>
          <h2>Provider app links</h2>
          <button type="button" id="settings-refresh-app-links" class="settings-secondary" ${n?"disabled":""}>Refresh links</button>
        </div>
      </div>
      <p class="settings-card-copy">Provider links are workspace-scoped. A selected provider is reused until it becomes unavailable; otherwise one-provider interface links use the first available candidate as their automatic default.</p>
      ${s?`<p class="settings-platform-error">${d(s)}</p>`:""}
      ${a.length?`<div class="settings-app-link-errors">${a.map(ai).join("")}</div>`:""}
      ${t.length>1?Xa(t,e,r):""}
      <div class="settings-app-link-list">
        ${t.length?t.map(l=>Za(l,e,r,i)).join(""):ei(s,n)}
      </div>
    </section>`}function Xa(e,t,s){return`<nav class="settings-app-link-consumer-nav" aria-label="Provider link apps">
    ${e.map(n=>{const a=s.find(l=>l.workspace_id===n.workspace_id&&l.app_id===n.consumer_app_id),i=ut(t,n.consumer_app_id),r=a?.name||i?.name||n.consumer_app_id;return`<a class="settings-app-link-consumer-nav__item" href="#${b(ps(n.consumer_app_id))}">
        <strong>${d(r)}</strong>
        <small>${d(String(n.dependencies.length))}</small>
      </a>`}).join("")}
  </nav>`}function Za(e,t,s,n){const a=s.find(r=>r.workspace_id===e.workspace_id&&r.app_id===e.consumer_app_id),i=ut(t,e.consumer_app_id);return`<article class="settings-app-link-consumer" id="${b(ps(e.consumer_app_id))}">
    <header class="settings-app-link-consumer__header">
      ${gs(i)}
      <span class="settings-app-copy">
        <strong>${d(a?.name||e.consumer_app_id)}</strong>
        <small>${d(e.consumer_app_id)} - ${d(e.status)}</small>
      </span>
    </header>
    <div class="settings-app-link-dependencies">
      ${e.dependencies.map(r=>xa(e.consumer_app_id,r,t,n)).join("")}
    </div>
  </article>`}function xa(e,t,s,n){const a=n.has(ti(e,t.alias)),i=si(t),r=us(t);return`<section class="settings-app-link-row" data-dependency-row="${b(e)}:${b(t.alias)}">
    <header class="settings-app-link-row__header">
      <span class="settings-app-link-row__copy">
        <strong>${d(t.alias)}</strong>
        <small>${d(t.interface)} ${d(t.version)}</small>
      </span>
      <span class="settings-pill ${t.status==="resolved"||r?"":"settings-pill-muted"}">${d(ni(t,r))}</span>
    </header>
    <p class="settings-card-copy">${d(t.description||"No description.")}</p>
    ${t.blocked_reason?`<p class="settings-platform-error">${d(t.blocked_reason)}</p>`:""}
    ${t.stale_provider_app_ids.length?`<p class="settings-platform-error">Unavailable selection: ${d(t.stale_provider_app_ids.join(", "))}</p>`:""}
    ${t.candidates.length?`<div class="settings-app-link-candidates">
            ${t.candidates.map(l=>{const c=i.includes(l.app_id),o=t.cardinality==="many"?"checkbox":"radio",p=`dependency:${e}:${t.alias}`,u=ut(s,l.app_id);return`<label class="settings-app-link-candidate ${c?"is-selected":""}">
                <input
                  ${c?"checked":""}
                  ${a?"disabled":""}
                  data-dependency-choice="${b(Dt(e,t.alias,l.app_id))}"
                  name="${b(p)}"
                  type="${o}"
                />
                ${gs(u)}
                <span>
                  <strong>${d(l.name||l.app_id)}</strong>
                  <small>${d(l.app_id)} - ${d(l.interface_version)}${l.app_id===r?" - automatic default":""}</small>
                </span>
              </label>`}).join("")}
          </div>`:'<p class="settings-card-copy">No enabled provider app is available for this interface.</p>'}
    ${r?`<button type="button" class="settings-secondary" data-dependency-save-default="${b(Dt(e,t.alias,r))}" ${a?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">${a?"sync":"save"}</span>
          ${a?"Saving":"Save default"}
        </button>`:""}
  </section>`}function ei(e,t){return e?"":t?'<p class="settings-card-copy">Loading app links...</p>':'<p class="settings-card-copy">No enabled app in the active workspace declares provider links.</p>'}function ti(e,t){return`${e}:${t}`}function Dt(e,t,s){return`${e}:${t}:${s}`}function ps(e){return`settings-app-link-consumer-${e}`}function si(e){if(e.selected_provider_app_ids.length)return e.selected_provider_app_ids;const t=us(e);return t?[t]:[]}function us(e){return e.selected_provider_app_ids.length||e.status!=="optional_unset"||e.cardinality!=="one"||e.stale_provider_app_ids.length||e.blocked_reason?"":e.candidates[0]?.app_id||""}function ni(e,t){return t?"auto default":e.status==="optional_unset"?"unset":e.status}function ut(e,t){return e.find(s=>s.app_id===t)||null}function ai(e){return`<p class="settings-platform-error">${d(e.name||e.app_id)}: ${d(e.message)}</p>`}function gs(e){if(e?.logo?.kind==="image"&&e.logo.value)return`<span class="settings-app-link-logo is-image"><img alt="" loading="lazy" src="${b(e.logo.value)}" /></span>`;const t=e?.logo?.value||"apps";return`<span class="settings-app-link-logo is-glyph"><span class="material-symbols-rounded" aria-hidden="true">${d(t)}</span></span>`}function ii(e){const{dashboard:t,error:s,isClearing:n,isLoading:a}=e,i=n?"Clearing…":"Clear cache";return`<section class="settings-card settings-cache-diagnostics" aria-busy="${a||n}">
    <div class="settings-heading">
      <div>
        <span class="settings-kicker">This browser</span>
        <h3>Maverick cache</h3>
      </div>
      <span class="settings-pill settings-pill-muted">Disposable</span>
    </div>
    <p class="settings-card-copy">Inspect aggregate cache usage for this browser container. Cached entries and file copies are rebuildable and never authorize server actions.</p>
    ${s?`<div class="settings-cache-diagnostics__error" role="alert">${d(s)}</div>`:""}
    ${ri(t,a)}
    <div class="settings-cache-diagnostics__actions">
      <button class="settings-secondary" id="refresh-pwa-cache" type="button" ${a||n?"disabled":""}>
        <span class="material-symbols-rounded" aria-hidden="true">refresh</span>
        Refresh
      </button>
      <button class="settings-secondary" id="clear-pwa-cache" type="button" ${a||n?"disabled":""}>
        <span class="material-symbols-rounded" aria-hidden="true">delete_sweep</span>
        ${i}
      </button>

    </div>
    <p class="settings-cache-diagnostics__note">Clear cache removes only Maverick's structured data and versioned file cache from this browser container. It does not delete server files, static app assets, or unrelated origin storage.</p>
  </section>`}function ri(e,t){if(!e||t)return`<div class="settings-cache-diagnostics__grid" aria-label="Loading cache diagnostics">
      ${A("Cache data","—")}
      ${A("Entries","—")}
      ${A("Origin usage","—")}
      ${A("Origin quota","—")}
    </div>`;const{diagnostics:s,metrics:n}=e;return`<div class="settings-cache-diagnostics__section">
    <h4>Storage and quota</h4>
    <div class="settings-cache-diagnostics__grid">
    ${A("Cache data",ge(s.cacheBytes))}
    ${A("Entries",s.entryCount.toLocaleString())}
    ${A("Structured data",ge(s.structuredCacheBytes))}
    ${A("Structured entries",s.structuredEntryCount.toLocaleString())}
    ${A("File data",ge(s.fileCacheBytes))}
    ${A("File entries",s.fileCacheEntryCount.toLocaleString())}
    ${A("Origin usage",Rt(s.originUsageBytes))}
    ${A("Origin quota",Rt(s.originQuotaBytes))}
    ${A("Backend",s.backend==="indexeddb"?"IndexedDB":"Memory fallback")}
    ${A("File storage",s.fileCacheAvailable?"OPFS available":"Unavailable")}
    ${A("Pending cleanup",s.pendingCleanupCount.toLocaleString())}
    </div>
  </div>
  ${oi(n)}
  ${li(n)}`}function oi(e){const t=e.counters;return`<div class="settings-cache-diagnostics__section">
    <h4>Cache activity</h4>
    <p>Aggregate events in this browser since ${d(ci(e.windowStartedAt))}.</p>
    <div class="settings-cache-diagnostics__grid">
      ${A("Static hit / miss",X(t.pwa_static_cache_hit,t.pwa_static_cache_miss))}
      ${A("Data hit / miss",X(t.pwa_data_cache_hit,t.pwa_data_cache_miss))}
      ${A("Data cache errors",J(t.pwa_data_cache_error))}
      ${A("Stale / expired",X(t.pwa_data_cache_stale,t.pwa_data_cache_expired))}
      ${A("Revalidated unchanged",J(t.pwa_revalidate_not_modified))}
      ${A("Revalidated changed",J(t.pwa_revalidate_modified))}
      ${A("Revalidation errors",J(t.pwa_revalidate_error))}
      ${A("File hit / miss",X(t.pwa_file_cache_hit,t.pwa_file_cache_miss))}
      ${A("File writes / ready",X(t.pwa_file_cache_write,t.pwa_file_cache_ready))}
      ${A("File errors",J(t.pwa_file_cache_error))}
      ${A("Evicted entries",J(t.pwa_eviction_count))}
      ${A("Evicted data",ge(t.pwa_eviction_bytes))}
      ${A("Quota usage samples",J(t.pwa_quota_usage))}
      ${A("Quota checks / errors",X(t.pwa_quota_estimate,t.pwa_quota_error))}
    </div>
  </div>`}function li(e){const t=e.counters,s=e.requestWait;return`<div class="settings-cache-diagnostics__section">
    <h4>Requests and recovery</h4>
    <div class="settings-cache-diagnostics__grid">
      ${A("Pending waits (this window)",J(s.pendingCount))}
      ${A("Oldest pending (this window)",di(s.oldestPendingMs))}
      ${A("Average wait",at(s.averageDurationMs))}
      ${A("Longest wait",at(s.maxDurationMs))}
      ${A("Resolved / cancelled",X(t.pwa_request_wait_resolved,t.pwa_request_wait_cancelled))}
      ${A("Retry attempts",J(t.pwa_request_retry_attempt))}
      ${A("Worker installs / updates",X(t.pwa_sw_install,t.pwa_sw_update))}
      ${A("Worker recoveries / errors",X(t.pwa_sw_recovery,t.pwa_sw_error))}
      ${A("Static cache errors",J(t.pwa_static_cache_error))}
    </div>
  </div>`}function A(e,t){return`<div class="settings-cache-diagnostics__metric">
    <span>${d(e)}</span>
    <strong>${d(t)}</strong>
  </div>`}function Rt(e){return e===null?"Unavailable":ge(e)}function ge(e){if(!Number.isFinite(e)||e<=0)return"0 B";const t=["B","KB","MB","GB"],s=Math.min(t.length-1,Math.floor(Math.log(e)/Math.log(1024))),n=e/1024**s;return`${n>=10||s===0?n.toFixed(0):n.toFixed(1)} ${t[s]}`}function J(e){return e.toLocaleString()}function X(e,t){return`${J(e)} / ${J(t)}`}function di(e){return e===null?"None":at(e)}function at(e){return!Number.isFinite(e)||e<=0?"0 ms":e<1e3?`${Math.round(e)} ms`:`${(e/1e3).toFixed(e<1e4?1:0)} s`}function ci(e){const t=new Date(e);return Number.isFinite(t.getTime())?t.toLocaleString():"this session"}function pi(e){return mi(e)}function ui(e){const{deleteSourceAfterMigration:t,migrationPlan:s,migrationProgress:n,migrationTarget:a,persistence:i}=e;if(!a||!i)return"";const r=i.active_adapter.kind.toUpperCase(),l=a.toUpperCase(),c=!!(n&&!["complete","failed"].includes(n.phase)),o=!!(s&&!s.same_adapter&&!c);return`<div class="settings-modal-backdrop" role="presentation">
    <section class="settings-modal" role="dialog" aria-modal="true" aria-labelledby="adapter-migration-title">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Confirm migration</p>
          <h2 id="adapter-migration-title">${r} → ${l}</h2>
        </div>
        <button type="button" class="settings-icon-button" id="close-migration-modal" aria-label="Close" ${c?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">close</span>
        </button>
      </div>
      ${s?_i(s):hi(n)}
      ${gi(e)}
      ${ae(`<input id="settings-delete-source" type="checkbox" role="switch" ${t?"checked":""} ${c?"disabled":""} />`,"Schedule source cleanup after restart health check","settings-migration-delete-source")}
      <p class="settings-card-copy">Leave cleanup off to preserve the current source adapter data as a rollback point. Cleanup is a separate explicit choice and requires backend restart.</p>
      <div class="settings-modal-actions">
        <button type="button" class="settings-secondary" id="cancel-migration" ${c?"disabled":""}>Cancel</button>
        <button type="button" class="settings-secondary" id="validate-migration" ${c?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">rule</span>
          Validate dry run
        </button>
        <button type="button" class="${t?"settings-danger":"settings-secondary"}" id="confirm-migration" ${o?"":"disabled"}>
          <span class="material-symbols-rounded" aria-hidden="true">sync_alt</span>
          ${t?"Apply and schedule cleanup":"Apply migration"}
        </button>
      </div>
    </section>
  </div>`}function gi(e){const t=e.targetDraft;if(!t)return"";const s=!!(e.migrationProgress&&!["complete","failed"].includes(e.migrationProgress.phase));return`<div class="settings-migration-target">
    <label class="settings-platform-field">
      <span>JSON root</span>
      <input data-migration-field="json_root" value="${b(t.json_root)}" ${s?"disabled":""} />
    </label>
    ${t.kind==="mongo"?`<label class="settings-platform-field">
          <span>Mongo URI</span>
          <input data-migration-field="mongodb_uri" value="${b(t.mongodb_uri)}" ${s?"disabled":""} />
        </label>
        <label class="settings-platform-field">
          <span>Mongo database</span>
          <input data-migration-field="mongodb_database" value="${b(t.mongodb_database)}" ${s?"disabled":""} />
        </label>
        <label class="settings-platform-field">
          <span>Mongo username</span>
          <input data-migration-field="mongodb_username" value="${b(t.mongodb_username||"")}" ${s?"disabled":""} />
        </label>
        <label class="settings-platform-field">
          <span>Password secret ref</span>
          <input data-migration-field="mongodb_password_ref" value="${b(t.mongodb_password_ref||"")}" ${s?"disabled":""} />
        </label>`:""}
  </div>`}function mi(e){const{migrationProgress:t,migrationResult:s,persistence:n}=e;if(!n)return`<section class="settings-card settings-persistence">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Persistence</p>
          <h2>Control plane adapter</h2>
        </div>
        <span class="settings-pill settings-pill-muted">offline</span>
      </div>
      <p class="settings-card-copy">The core persistence surfaces are not available in the active backend.</p>
    </section>`;const a=n.active_adapter,i=n.collections.reduce((o,p)=>o+p.count,0),r=a.kind==="json",l=a.kind==="mongo",c=t&&!["complete","failed"].includes(t.phase);return`<section class="settings-card settings-persistence">
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
          <small>${d(r?a.json_root:"data/control-plane/json")}</small>
        </span>
        <em>${r?"Current":"Review migration"}</em>
      </button>
      <button type="button" class="settings-adapter-card ${l?"is-active":""}" ${l||c?"disabled":'data-adapter-target="mongo"'}>
        <span class="settings-adapter-card-icon material-symbols-rounded" aria-hidden="true">${l?"check_circle":"database"}</span>
        <span>
          <strong>Mongo</strong>
          <small>${d(l?a.mongo_database:"mongodb://127.0.0.1:27017/maverick")}</small>
        </span>
        <em>${l?"Current":"Review migration"}</em>
      </button>
    </div>
    ${fi(t)}
    ${vi(s)}
  </section>`}function fi(e){return e?`<div role="status" aria-live="polite" class="settings-migration-progress ${e.phase==="failed"?"is-failed":""} ${e.phase==="complete"?"is-complete":""}">
    <div class="settings-migration-progress-heading">
      <span class="material-symbols-rounded" aria-hidden="true">${e.phase==="complete"?"check_circle":e.phase==="failed"?"error":"sync"}</span>
      <span>
        <strong>${d(e.title)}</strong>
        <small>${d(e.detail)}</small>
      </span>

    </div>
  </div>`:""}function vi(e){return e?`<div class="settings-migration-result">
    <span class="material-symbols-rounded" aria-hidden="true">task_alt</span>
    <span>
      <strong>Last migration</strong>
      <small>${e.collections.reduce((s,n)=>s+n.count,0)} documents · target ${d(e.target_adapter.kind)} · cleanup ${e.source_cleanup?.scheduled?"scheduled":"not requested"}</small>
    </span>
  </div>`:""}function hi(e){return`<div class="settings-migration-plan">
    <span class="material-symbols-rounded" aria-hidden="true">rule</span>
    <span>
      <strong>${d(e?.title||"Dry run not validated")}</strong>
      <small>${d(e?.detail||"Adjust the target fields, then validate the dry run before applying migration.")}</small>
    </span>
  </div>`}function _i(e){const t=e.collections.reduce((n,a)=>n+a.count,0),s=e.target_collections.reduce((n,a)=>n+a.count,0);return`<div class="settings-migration-plan">
    <span class="material-symbols-rounded" aria-hidden="true">${e.same_adapter?"block":"rule"}</span>
    <span>
      <strong>${e.same_adapter?"Target already active":"Dry run complete"}</strong>
      <small>${t} source documents · ${s} target documents before copy · env ${d(e.env_file)}</small>
    </span>
    <div class="settings-migration-collections">
      ${e.collections.map(n=>`<span><strong>${d(n.name)}</strong><small>${n.count}</small></span>`).join("")}
    </div>
  </div>`}function bi({selectedUser:e,users:t}){return`<details class="settings-card settings-user-create"><summary>Create a user</summary><form class="settings-create" id="create-user">
      <div>
        <p class="settings-kicker">New user</p>
        <h2>Create access</h2>
      </div>
      <label>Username<input name="username" required autocomplete="username" /></label>
      <label>Temporary password<input name="password" type="password" minlength="8" required autocomplete="new-password" /></label>
      <label>Display name<input name="display_name"  /></label>
      <label>Email<input name="email" type="email" /></label>
      <label>Platform role<select name="platform_role">
        <option value="member">Member</option>
        <option value="admin">Admin</option>
      </select></label>
      <button type="submit">
        <span class="material-symbols-rounded" aria-hidden="true">person_add</span>
        Create user
      </button>
      <button type="button" data-user-discard class="settings-secondary">Discard edits</button><p data-action-status class="settings-action-status" role="status"></p>
    </form></details>
    ${ms(t,e)}
    ${e?`<div class="settings-profile-row">
          <form class="settings-card settings-detail" id="edit-user">
            <div class="settings-heading">
              <div>
                <p class="settings-kicker">Selected user</p>
                <h2>${d(e.display_name||e.username)}</h2>
              </div>
              <span class="settings-pill">${e.is_active?"active":"disabled"}</span>
            </div>
            <div class="settings-grid">
              <label>Name<input name="display_name" value="${b(e.display_name||"")}" /></label>
              <label>Email<input name="email" type="email" value="${b(e.email||"")}" /></label>
              <label>Platform role<select name="platform_role">
                <option value="member" ${e.platform_role==="member"?"selected":""}>Member</option>
                <option value="admin" ${e.platform_role==="admin"?"selected":""}>Admin</option>
              </select></label>
              <label>Account type<select name="account_type">
                <option value="standard" ${e.account_type==="standard"?"selected":""}>Standard</option>
                <option value="facilitated" ${e.account_type==="facilitated"?"selected":""}>Facilitated</option>
              </select></label>
            </div>
            ${ae(`<input name="is_active" type="checkbox" role="switch" ${e.is_active?"checked":""} />`,"Account active")}
            <button type="submit">
              <span class="material-symbols-rounded" aria-hidden="true">save</span>
              Save user
            </button>
            <button type="button" data-user-discard class="settings-secondary">Discard edits</button><p data-action-status class="settings-action-status" role="status"></p>
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
              Delete user
            </button>
            <button type="button" data-user-discard class="settings-secondary">Discard edits</button><p data-action-status class="settings-action-status" role="status"></p>
          </form>
        </div>`:'<section class="settings-card"><h2>No users</h2></section>'}`}function Tt({selectedUser:e,users:t,workspaces:s,showPicker:n=!0}){return`${n?ms(t,e):""}
    ${e?`<section class="settings-card" id="workspace-assignments">
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
          <div class="settings-memberships">${yi(e,s)}</div>
          <button type="button" data-user-discard class="settings-secondary">Discard edits</button><p data-action-status class="settings-action-status" role="status"></p>
        </section>`:'<section class="settings-card"><h2>No users</h2></section>'}`}function ms(e,t){return e.length?`<section class="settings-card settings-user-picker">
    <div>
      <p class="settings-kicker">User directory</p>
      <h2>${d(t?t.display_name||t.username:"Select user")}</h2>
      <p class="settings-card-copy">${e.length} user${e.length===1?"":"s"} available.</p>
    </div>
    <label class="settings-platform-field">
      <span>Selected user</span>
      <select id="selected-user">
        ${e.map(s=>`<option value="${b(s.user_id)}" ${s.user_id===t?.user_id?"selected":""}>${d(s.display_name||s.username)} (${d(s.username)})</option>`).join("")}
      </select>
    </label>
  </section>`:`<section class="settings-card settings-user-picker">
      <div>
        <p class="settings-kicker">User directory</p>
        <h2>No users</h2>
      </div>
      <p class="settings-card-copy">Create a user before editing profile or workspace access settings.</p>
    </section>`}function yi(e,t){return t.map(s=>{const n=e.memberships.find(a=>a.workspace_id===s.workspace_id);return`<label class="settings-membership">
        <input type="checkbox" aria-label="Access to ${b(s.name)}" data-workspace-enabled="${b(s.workspace_id)}" ${n?"checked":""} />
        <span class="settings-membership-icon material-symbols-rounded" aria-hidden="true">workspaces</span>
        <span>
          <strong>${d(s.name)}</strong>
          <small>${d(s.workspace_id)}</small>
        </span>
        <select aria-label="Role in ${b(s.name)}" data-workspace-role="${b(s.workspace_id)}">
          <option value="member" ${n?.role!=="admin"?"selected":""}>Member</option>
          <option value="admin" ${n?.role==="admin"?"selected":""}>Workspace admin</option>
        </select>
      </label>`}).join("")}function $i({workspaceApps:e,workspaces:t}){return`<details class="settings-card"><summary>Create a workspace</summary><form id="create-workspace" class="settings-grid">
    <label>Name<input name="name" required /></label><label>Description<input name="description" /></label><button type="submit">Create workspace</button>
    </form></details><section class="settings-card">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Workspace apps</p>
          <h2>Installation and visibility</h2>
        </div>
      </div>
      <p class="settings-card-copy">Installed means the app has a workspace binding. Only enabled apps are visible to users and served by the core.</p>
      <div class="settings-app-workspaces">${wi(t,e)}</div>
    </section>`}function wi(e,t){return e.map(s=>{const n=t.filter(r=>r.workspace_id===s.workspace_id),a=n.filter(r=>r.status==="enabled").length,i=n.filter(r=>r.installed).length;return`<details class="settings-app-workspace" data-workspace-row="${b(s.workspace_id)}">
        <summary class="settings-app-workspace-heading">
          <span class="settings-summary-caret material-symbols-rounded" aria-hidden="true">chevron_right</span>
          <span class="settings-app-workspace-icon material-symbols-rounded" aria-hidden="true">deployed_code</span>
          <span>
            <strong>${d(s.name)}</strong>
            <small>${d(s.workspace_id)} · ${a}/${i} enabled</small>
          </span>
        </summary>
        <div class="settings-apps">
          ${n.map(ki).join("")}
        </div>
      </details>`}).join("")}function ki(e){const t=e.status==="enabled",s=e.installed,n=s?e.status:"not installed",a=`${e.workspace_id}:${e.app_id}`;return`<div class="settings-app-row" data-app-row="${b(a)}">
    ${e.logo?.kind==="image"?`<img class="settings-app-icon" src="${b(e.logo.value)}" alt="" />`:`<span class="settings-app-icon material-symbols-rounded" aria-hidden="true">${d(e.logo?.kind==="glyph"?e.logo.value:"apps")}</span>`}
    <span class="settings-app-copy">
      <strong>${d(e.name)}</strong>
      <small>${d(e.app_id)} · v${d(e.version)} · ${d(n)}</small>
    </span>
    ${s?`${ae(`<input type="checkbox" role="switch" aria-label="Enable ${b(e.name)} in ${b(e.workspace_name)}" data-app-toggle="${b(a)}" ${t?"checked":""} />`,"Enabled","settings-switch")}
        <button type="button" class="settings-secondary" data-app-uninstall="${b(a)}">
          <span class="material-symbols-rounded" aria-hidden="true">link_off</span>
          Uninstall
        </button>`:`<button type="button" class="settings-secondary" data-app-install="${b(a)}">
          <span class="material-symbols-rounded" aria-hidden="true">add_link</span>
          Install
        </button>`}
  </div>`}function Si(e){const{page:t,selectedUser:s}=e;if(t.id==="users")return bi({selectedUser:s,users:e.users})+Tt({selectedUser:s,users:e.users,workspaces:e.workspaces,showPicker:!1});if(t.id==="workspace-access")return Tt({selectedUser:s,users:e.users,workspaces:e.workspaces});if(t.id==="workspace-apps")return $i({workspaceApps:e.workspaceApps,workspaces:e.workspaces});if(t.id==="app-links"){const n=e.appLinksController.viewState();return Ya({appRegistry:n.appRegistry,dependencies:n.dependencies,error:n.error,isLoading:n.isLoading,loadErrors:n.loadErrors,savingKeys:n.savingKeys,workspaceApps:e.workspaceApps})}return["models","voice","computer-use"].includes(t.id)?e.platformSettingsHtml():t.id==="usage"?e.usageHtml():t.id==="sessions"?e.sessionsHtml():t.id==="learning"?e.learningHtml():t.id==="cache"?ii(e.cacheDiagnosticsController.viewState()):pi(e.persistenceController.viewState())}async function we(e,t,s){if(!e||e.hasAttribute("data-pending-action"))return;const n=Array.from(e.querySelectorAll("input, button, select")),a=n.map(r=>r.disabled);e.setAttribute("data-pending-action",""),e.setAttribute("aria-busy","true");const i=e.querySelector("[data-action-status]");i&&(i.setAttribute("role","status"),i.textContent="Saving…");try{const r=t();n.forEach(l=>{l.disabled=!0}),await r,i&&(i.textContent="Saved.")}catch(r){i&&(i.setAttribute("role","alert"),i.textContent=r instanceof Error?r.message:"Unable to save."),s(r)}finally{e.removeAttribute("data-pending-action"),e.removeAttribute("aria-busy"),n.forEach((r,l)=>{r.disabled=a[l]})}}function Ei(e){document.querySelectorAll("[data-native-provider-activate]").forEach(t=>{v(t,"click",()=>{e.onActivateNativeProvider(t.dataset.nativeProviderActivate||"")})}),document.querySelectorAll("[data-agentic-binding-save]").forEach(t=>{v(t,"click",()=>{e.onSaveAgenticBinding(t.dataset.agenticDefinitionId||"")})}),document.querySelectorAll("[data-agentic-model-toggle]").forEach(t=>{const s=t.closest(".settings-bouncy-toggle");v(t,"click",n=>n.stopPropagation()),v(t.closest("label"),"click",n=>n.stopPropagation()),v(t,"change",()=>{const n=t.checked,a=s?.querySelector(".settings-bouncy-toggle__label");a&&(a.textContent=n?"On":"Off"),e.onSaveAgenticBinding(t.dataset.agenticDefinitionId||"",{enabled:n})})}),v(document.getElementById("settings-speech-audio-model"),"change",t=>{e.onSpeechAudioModelChanged(t.currentTarget.value)}),v(document.getElementById("settings-speech-conversation-model"),"change",t=>{e.onSpeechConversationModelChanged(t.currentTarget.value)}),document.querySelectorAll("[data-speech-save]").forEach(t=>{v(t,"click",()=>{e.onSaveSpeechProviderSettings()})}),v(document.getElementById("settings-speech-save"),"click",()=>{e.onSaveSpeechProviderSettings()}),document.querySelectorAll("[data-settings-model-accordion]").forEach(t=>{v(t,"toggle",()=>{t.open&&document.querySelectorAll("[data-settings-model-accordion]").forEach(s=>{s!==t&&(s.open=!1)})})}),document.querySelectorAll("[data-openrouter-routing]").forEach(t=>{v(t,"change",s=>{const n=s.currentTarget,a=n.dataset.hostedModelId||n.closest("[data-hosted-model-accordion]")?.dataset.hostedModelAccordion||"";e.onHostedProviderRoutingChanged(a,n.dataset.openrouterRouting||"",n instanceof HTMLInputElement&&n.type==="checkbox"?n.checked:n.value)})}),v(document.getElementById("settings-refresh-usage-history"),"click",e.onRefreshProviderUsage),document.querySelectorAll("[data-hosted-provider-save]").forEach(t=>{v(t,"click",()=>e.onSaveHostedProviderSettings(t.dataset.hostedProviderSave||""))}),v(document.getElementById("settings-logout"),"click",e.onLogout),v(document.getElementById("settings-clear-all-runtime"),"click",e.onClearAllRuntimeSessions),document.querySelectorAll("[data-runtime-clear]").forEach(t=>{v(t,"click",()=>e.onClearRuntimeSession(t.dataset.runtimeClear||""))})}function Ii(e){ma(),v(document.getElementById("dismiss-notice"),"click",e.dismissNotice),v(document.getElementById("create-user"),"submit",s=>{s.preventDefault();const n=s.currentTarget;we(n,()=>e.createUser(n),e.showError)});const t=e.selectedUser();v(document.getElementById("selected-user"),"change",s=>{e.selectUser(s.currentTarget.value)}),v(document.getElementById("edit-user"),"submit",s=>{s.preventDefault();const n=s.currentTarget;t&&we(n,()=>e.updateSelectedUser(n,t),e.showError)}),v(document.getElementById("reset-password"),"submit",s=>{s.preventDefault();const n=s.currentTarget;t&&we(n,()=>e.resetSelectedUserPassword(n,t),e.showError)}),v(document.getElementById("delete-user"),"click",()=>{t&&e.deleteSelectedUser(t).catch(e.showError)}),v(document.getElementById("save-memberships"),"click",()=>{t&&we(document.getElementById("workspace-assignments"),()=>e.updateMemberships(t),e.showError)}),Mi(e),Ci(e),Pi(e),Ai(e),Ei({onClearAllRuntimeSessions:()=>{e.clearRuntimeSessionsFromPanel().catch(e.showError)},onClearRuntimeSession:s=>{s&&e.clearRuntimeSessionsFromPanel([s]).catch(e.showError)},onLogout:()=>{e.logoutFromSettings().catch(e.showError)},onHostedProviderRoutingChanged:e.onHostedProviderRoutingChanged,onActivateNativeProvider:s=>{e.activateNativeProviderFromPanel(s).catch(e.showError)},onSaveAgenticBinding:(s,n)=>{e.saveAgenticBindingFromPanel(s,n).catch(e.showError)},onRefreshProviderUsage:()=>{e.refreshProviderUsageFromPanel().catch(e.showError)},onSpeechAudioModelChanged:e.onSpeechAudioModelChanged,onSpeechConversationModelChanged:e.onSpeechConversationModelChanged,onSaveHostedProviderSettings:s=>{e.saveHostedProviderSettingsFromPanel(s).catch(e.showError)},onSaveSpeechProviderSettings:()=>{e.saveSpeechProviderSettingsFromPanel().catch(e.showError)}})}function Ai(e){v(document.getElementById("refresh-pwa-cache"),"click",()=>{e.cacheDiagnosticsController.ensureLoaded(!0).catch(e.showError)}),v(document.getElementById("clear-pwa-cache"),"click",()=>{e.cacheDiagnosticsController.clear().catch(e.showError)})}function Ci(e){document.querySelectorAll("[data-dependency-choice]").forEach(t=>{v(t,"change",()=>{const s=Lt(t.dataset.dependencyChoice||"");if(!s)return;const n=e.appDependencies().find(i=>i.consumer_app_id===s.consumerAppId)?.dependencies.find(i=>i.alias===s.alias);if(!n)return;if(n.cardinality==="one"){e.saveDependencySelection(s.consumerAppId,s.alias,[s.providerAppId]).catch(e.showError);return}const a=new Set(n.selected_provider_app_ids);t.checked?a.add(s.providerAppId):a.delete(s.providerAppId),e.saveDependencySelection(s.consumerAppId,s.alias,Array.from(a)).catch(e.showError)})}),document.querySelectorAll("[data-dependency-save-default]").forEach(t=>{v(t,"click",()=>{const s=Lt(t.dataset.dependencySaveDefault||"");s&&e.saveDependencySelection(s.consumerAppId,s.alias,[s.providerAppId]).catch(e.showError)})})}function Lt(e){const[t,s,...n]=e.split(":"),a=n.join(":");return!t||!s||!a?null:{alias:s,consumerAppId:t,providerAppId:a}}function Mi(e){document.querySelectorAll("[data-app-toggle]").forEach(t=>{v(t,"change",()=>{const s=e.workspaceApps().find(n=>`${n.workspace_id}:${n.app_id}`===t.dataset.appToggle);s&&e.setWorkspaceAppStatus(s,t.checked).catch(e.showError)})}),document.querySelectorAll("[data-app-install]").forEach(t=>{v(t,"click",()=>{const s=e.workspaceApps().find(n=>`${n.workspace_id}:${n.app_id}`===t.dataset.appInstall);s&&e.installWorkspaceApp(s).catch(e.showError)})}),document.querySelectorAll("[data-app-uninstall]").forEach(t=>{v(t,"click",()=>{const s=e.workspaceApps().find(n=>`${n.workspace_id}:${n.app_id}`===t.dataset.appUninstall);s&&e.uninstallWorkspaceApp(s).catch(e.showError)})})}function Pi(e){document.querySelectorAll("[data-adapter-target]").forEach(t=>{v(t,"click",()=>{const s=t.dataset.adapterTarget;(s==="json"||s==="mongo")&&e.persistenceController.prepare(s).catch(e.showError)})}),v(document.getElementById("close-migration-modal"),"click",()=>{e.persistenceController.cancel()}),v(document.getElementById("cancel-migration"),"click",()=>{e.persistenceController.cancel()}),v(document.getElementById("validate-migration"),"click",()=>{e.persistenceController.validateDraft().catch(e.showError)}),document.querySelectorAll("[data-migration-field]").forEach(t=>{const s=n=>{const a=t.dataset.migrationField;if(a&&a in(e.persistenceController.viewState().targetDraft||{})){const i=!!e.persistenceController.viewState().migrationPlan;e.persistenceController.updateDraft(a,t.value,{render:n}),!n&&i&&qi()}};v(t,"input",()=>s(!1)),v(t,"change",()=>s(!0))}),v(document.getElementById("settings-delete-source"),"change",t=>{e.persistenceController.setDeleteSource(t.currentTarget.checked)}),v(document.getElementById("confirm-migration"),"click",()=>{e.persistenceController.apply().catch(e.showError)})}function qi(){const e=document.getElementById("confirm-migration");e&&(e.disabled=!0);const t=document.querySelector(".settings-migration-plan");if(!t)return;const s=t.querySelector(".material-symbols-rounded"),n=t.querySelector("strong"),a=t.querySelector("small");s&&(s.textContent="rule"),n&&(n.textContent="Dry run changed"),a&&(a.textContent="Validate the dry run again before applying migration."),t.querySelector(".settings-migration-collections")?.remove()}function Di(e){let t=null,s=null,n="",a=null,i=null,r=null,l=!1;function c(){return{deleteSourceAfterMigration:l,migrationPlan:a,migrationProgress:r,migrationResult:i,migrationTarget:t,persistence:e.getPersistence(),targetDraft:s}}async function o(w){const h=e.getPersistence();if(!h||h.active_adapter.kind===w){f();return}t=w,s=Ri(w,h),n="",a=null,l=!1,r=null,e.setNotice(null),e.render()}function p(w,h,M={}){s&&(s={...s,[w]:h},a=null,n="",r=null,M.render!==!1&&e.render())}function u(w){l=w,e.render()}function f(){t=null,s=null,a=null,n="",r=null,e.render()}async function $(){if(!(!s||!t)){r={target:t,phase:"validating",title:`Dry run to ${t.toUpperCase()}`,detail:"Validating target adapter and collection copy plan before applying changes."},e.setNotice(null),e.render();try{const w=it(s);a=await Ws(w),n=Ht(w)}catch(w){throw r=null,a=null,n="",w}r=null,a.same_adapter&&e.setNotice({tone:"info",message:"The selected persistence adapter is already active."}),e.render()}}async function m(){if(!s||!t)return;const w=it(s),h=Ht(w);if(!a||n!==h){await $();return}if(a.same_adapter)return;r={target:t,phase:"applying",title:`Migration to ${t.toUpperCase()}`,detail:"Copying the validated control-plane plan to the target adapter."},e.setNotice(null),e.render();try{i=await Vs({...w,delete_source:l,restart_backend:!0})}catch(y){throw r={target:t,phase:"failed",title:"Migration failed",detail:y instanceof Error?y.message:"Unable to apply migration."},y}const M=t;t=null,s=null,a=null,n="",r={target:M,phase:"restarting",title:"Restart backend",detail:i.backend_restart?.detail||"Backend restart scheduled."},e.render(),await T(M)}async function T(w){const h=Date.now(),M=9e4;for(;Date.now()-h<M;){r={target:w,phase:"polling",title:"Verifying cutover",detail:"Waiting for the backend to become healthy with the new adapter."},e.render();const y=await e.requestPersistenceStatusQuiet();if(y?.active_adapter.kind===w){e.setPersistence(y);const E=i?.source_cleanup?.scheduled===!0;r={target:w,phase:"complete",title:"Migration complete",detail:E?`Active adapter: ${w.toUpperCase()}. Source cleanup is scheduled after health check.`:`Active adapter: ${w.toUpperCase()}. Source storage was preserved.`},e.setNotice({tone:"success",message:`Migration to ${w.toUpperCase()} complete.`}),e.render();return}await new Promise(E=>window.setTimeout(E,1500))}r={target:w,phase:"failed",title:"Verification not completed",detail:"The backend did not confirm the new adapter before the timeout. Check service health and logs."},e.setNotice({tone:"error",message:"Migration not confirmed before the timeout."}),e.render()}return{apply:m,cancel:f,prepare:o,setDeleteSource:u,updateDraft:p,validateDraft:$,viewState:c}}function Ri(e,t){const s=t.active_adapter;return{kind:e,json_root:s.json_root||"data/control-plane/json",mongodb_uri:s.mongo_uri||"mongodb://127.0.0.1:27017/maverick",mongodb_database:s.mongo_database||"maverick",mongodb_username:s.mongo_username||"",mongodb_password_ref:s.mongo_password_ref||""}}function it(e){return{kind:e.kind,json_root:e.json_root.trim()||"data/control-plane/json",mongodb_uri:e.mongodb_uri.trim(),mongodb_database:e.mongodb_database.trim()||"maverick",mongodb_username:e.mongodb_username?.trim()||void 0,mongodb_password_ref:e.mongodb_password_ref?.trim()||void 0}}function Ht(e){return JSON.stringify(it(e))}async function Ti(e){const t=e.settings?.workspace.workspace_id,s=e.state.hostedDraftModelId,n=Li(e.settings,e.state.hostedDraftModelId);if(!n||!e.state.hostedDraftModelId){e.state.hostedProviderErrorModelId=e.state.hostedDraftModelId,e.state.hostedProviderError="Hosted provider not loaded.",e.render();return}e.state.isSavingHostedProvider=!0,e.state.hostedProviderError="",e.state.hostedProviderErrorModelId=e.state.hostedDraftModelId,e.render();try{const a=await Os({provider_id:n,model_id:e.state.hostedDraftModelId,openrouter_provider_routing:ts(e.state,e.state.hostedDraftModelId)});if(e.getSettings()?.workspace.workspace_id!==t||!e.settings)return;const i={...e.getSettings(),provider:a};e.setSettings(i),ie(e.state,i,{hostedModelId:s}),document.querySelectorAll("[data-hosted-model-accordion]").forEach(r=>{r.dataset.hostedModelAccordion===s&&F(r)}),e.setNotice({tone:"success",message:"Hosted model settings updated."})}catch(a){e.state.hostedProviderErrorModelId=e.state.hostedDraftModelId,e.state.hostedProviderError=a instanceof Error?a.message:"Unable to update hosted model settings."}finally{e.state.isSavingHostedProvider=!1,e.render()}}function Li(e,t){const s=e?.provider.hosted_text||null;return[s?.active_provider,...s?.available_providers||[]].filter(Boolean).find(i=>!i||i.status!=="active"?!1:(i.model_options||[]).some(r=>r.model_id===t))?.provider_id||s?.active_provider?.provider_id||""}async function Hi(e){const t=e.settings?.workspace.workspace_id,s=e.settings?.provider.speech_stt?.active_provider?.provider_id;if(!s||!e.state.speechAudioModelId||!e.state.speechConversationModelId){e.state.speechProviderError="Speech provider not loaded.",e.render();return}e.state.isSavingSpeechProvider=!0,e.state.speechProviderError="",e.render();try{const n=await Ns({provider_id:s,audio_transcription_model_id:e.state.speechAudioModelId,conversation_model_id:e.state.speechConversationModelId});if(e.getSettings()?.workspace.workspace_id!==t||!e.settings)return;const a={...e.getSettings(),provider:n};e.setSettings(a),ie(e.state,a,{speech:!0}),F(".settings-speech-model-accordion"),e.setNotice({tone:"success",message:"Speech model settings updated."})}catch(n){e.state.speechProviderError=n instanceof Error?n.message:"Unable to update speech model settings."}finally{e.state.isSavingSpeechProvider=!1,e.render()}}function Ui(e){let t="",s=0,n=0;function a(){t="",s+=1,n+=1,e.state.providerUsageItems=[],e.state.providerUsageError="",e.state.isLoadingProviderUsage=!1,e.state.usageHistory=null,e.state.usageHistoryFilters=Ye(),e.state.usageHistoryError="",e.state.isLoadingUsageHistory=!1}async function i(p=!1){const f=e.getSettings()?.workspace.workspace_id||"";if(!f){a();return}!p&&t===f||(t&&t!==f&&(e.state.usageHistoryFilters=Ye()),t=f,await Promise.all([r(f),l(f)]))}async function r(p,u){const f=++s;e.state.providerUsageError="",e.state.isLoadingProviderUsage=!0,e.render();try{const $=await Hs();o(p)&&f===s&&(e.state.providerUsageItems=$.items)}catch($){o(p)&&f===s&&(e.state.providerUsageError=$ instanceof Error?$.message:"Provider usage unavailable")}finally{o(p)&&f===s&&(e.state.isLoadingProviderUsage=!1,e.render())}}async function l(p,u=!1){const f=++n,$=e.state.usageHistoryFilters,m=Xt($.timeRange),T={providerId:$.providerId,modelId:$.modelId};e.state.isLoadingUsageHistory=!0,e.state.usageHistoryError="",u&&(e.state.usageHistory=null),e.render();try{const w=await Us(m.resolution,m.periods,T);o(p)&&f===n&&(e.state.usageHistory=w)}catch(w){o(p)&&f===n&&(e.state.usageHistoryError=w instanceof Error?w.message:"Token usage history unavailable")}finally{o(p)&&f===n&&(e.state.isLoadingUsageHistory=!1,e.render())}}function c(p){const u=e.state.usageHistoryFilters,f=on(u,p);if(Oi(u,f))return Promise.resolve();e.state.usageHistoryFilters=f;const $=u.providerId!==f.providerId||u.modelId!==f.modelId||u.timeRange!==f.timeRange,m=e.getSettings()?.workspace.workspace_id||"";return!$||!m?(e.render(),Promise.resolve()):l(m,!0)}function o(p){return e.getSettings()?.workspace.workspace_id===p}return{ensureLoaded:i,refresh:()=>i(!0),reset:a,updateUsageHistoryFilters:c}}function Oi(e,t){return e.metric===t.metric&&e.providerId===t.providerId&&e.modelId===t.modelId&&e.timeRange===t.timeRange}function Ni(e){return e?`<div class="settings-notice settings-notice-${e.tone}">
    <span class="material-symbols-rounded" aria-hidden="true">${e.tone==="error"?"error":e.tone==="success"?"task_alt":"info"}</span>
    <span>${d(e.message)}</span>
    <button type="button" class="settings-icon-button" id="dismiss-notice" aria-label="Close">
      <span class="material-symbols-rounded" aria-hidden="true">close</span>
    </button>
  </div>`:""}function Bi(e){return{activateProvider:async t=>{const s=e.getSettings()?.workspace.workspace_id;if(!e.state.activatingNativeProviders.has(t)){e.state.activatingNativeProviders.add(t),e.state.nativeProviderErrors[t]="",e.render();try{await js(t);const n=await ht("models");if(e.getSettings()?.workspace.workspace_id!==s||n.workspace.workspace_id!==s)return;ie(e.state,n),e.setSettings(n,"Connection enabled. Selected models are available in Chat.")}catch(n){e.state.nativeProviderErrors[t]=n instanceof Error?n.message:"Unable to enable connection."}finally{e.state.activatingNativeProviders.delete(t),e.render()}}},save:async(t,s={})=>{const n=e.getSettings()?.workspace.workspace_id,a=t,i=e.getSettings()?.agentic_admin?.items.find(f=>f.definition_id===t),r=Array.from(document.querySelectorAll("[data-agentic-binding-form]")).find(f=>f.dataset.agenticDefinitionId===t);if(!i||!r){e.state.agenticBindingErrors[a]="Agentic binding form is no longer available.",e.render();return}const l=f=>r.querySelector(`[data-agentic-field="${f}"]`),c=f=>!!l(f)?.checked,o=s.enabled??c("enabled");if(i.containment_status==="NO-GO"&&o){e.state.agenticBindingErrors[a]=`Remote agentic release is NO-GO: ${i.containment_reason||"contained by operator policy"}.`,e.render();return}if(o&&(i.execution_family===null||i.runtime_status!=="complete"||i.enable_eligible!==!0)){e.state.agenticBindingErrors[a]=`This model is unavailable: ${i.enable_blocked_reason||i.runtime_status_reason||i.blocked_reason||"runtime unavailable"}.`,e.render();return}const p=l("max_estimated_cost_usd")?.value.trim()||"",u=Math.round(Number(p)*1e6);if(p&&(!Number.isFinite(u)||u<0)){e.state.agenticBindingErrors[a]="Maximum cost must be a non-negative amount.",e.render();return}e.state.savingAgenticBindings.add(a),e.state.agenticBindingErrors[a]="",e.render();try{await Bs({definition_id:t,binding_id:i.binding?.binding_id||null,credential_binding_id:l("credential_binding_id")?.value||null,enabled:o,is_default:s.enabled===!1?!1:c("is_default"),actor_policy:{allow_workspace_admins:c("allow_workspace_admins"),allowed_user_ids:i.binding?.actor_policy.allowed_user_ids||[],allowed_workspace_role_ids:c("allow_workspace_members")?["member"]:[],allowed_agent_type_ids:i.binding?.actor_policy.allowed_agent_type_ids||[]},policy_patch:{max_estimated_cost_microusd:p?u:null,require_confirmation_for_mutating:c("require_confirmation_for_mutating"),require_confirmation_for_destructive:c("require_confirmation_for_destructive")}});const f=await ht("models");if(e.getSettings()?.workspace.workspace_id!==n||f.workspace.workspace_id!==n)return;ie(e.state,f),F(r),e.setSettings(f,`${i.display_name} binding updated for new sessions.`)}catch(f){e.state.agenticBindingErrors[a]=f instanceof Error?f.message:"Unable to save agentic binding."}finally{e.state.savingAgenticBindings.delete(a),e.render()}}}}function ji(e){let t=null,s="",n=!1,a=!1,i=!1;async function r(o=!1){if(!(a||!o&&t)){a=!0,s="",e.render();try{if(t=await kn(),!t)throw new Error("Cache diagnostics are unavailable outside the Maverick shell.")}catch(p){s=Ut(p,"Unable to inspect this browser cache.")}finally{a=!1,e.render()}}}async function l(){if(n||i)return;i=!0;let o=!1;try{o=await ct({title:"Clear this browser cache?",detail:"Remove cached Maverick data and local file copies from this browser. Server files, conversations and settings are preserved.",confirmLabel:"Clear cache"})}finally{i=!1}if(o){n=!0,s="",e.render();try{const p=await Sn();if(!p)throw new Error("Cache cleanup is unavailable outside the Maverick shell.");const{cleanup:u}=p;if(u.status!=="complete"||u.pendingCleanupCount>0)throw new Error("Cache cleanup is still pending. Persistent cache reads remain blocked; retry Clear cache.");t=p.dashboard,e.setNotice({tone:"success",message:u.removed===1?"1 cached entry removed.":`${u.removed} cached entries removed.`})}catch(p){s=Ut(p,"Unable to clear this browser cache."),e.setNotice({tone:"error",message:s})}finally{n=!1,e.render()}}}function c(){return{dashboard:t,error:s,isClearing:n,isLoading:a}}return{clear:l,ensureLoaded:r,viewState:c}}function Ut(e,t){return e instanceof Error&&e.message?e.message:t}let rt=null,Ot=null,z=[],Ee=[],ce="",qe=[],ve=[],De=null,k=null,L=ia();const fs=Object.fromEntries(new URLSearchParams(window.location.search).entries());let j=Wt(fs)||ws,Q=hs(fs),Z=!0,N=null,Nt="",Bt="";const V=Qt();let Je="",Ie="",jt=!1;const gt=Js({state:L.speechSynthesis,render:C,notify:e=>{N={tone:"success",message:e}}}),Fi=Xs({state:L.computerUse,getSettings:()=>k,render:C,setSelection:e=>{k&&(k={...k,computer_use:e})},notify:e=>{N={tone:"success",message:e}}}),Ae=Di({getPersistence:()=>De,render:()=>C(),requestPersistenceStatusQuiet:Zs,setNotice:e=>{N=e},setPersistence:e=>{De=e}}),se=Ka({publishChanged:ar,render:()=>C(),setNotice:e=>{N=e}}),He=Ui({getSettings:()=>k,render:()=>C(),state:L}),Ft=Bi({getSettings:()=>k,render:C,state:L,setSettings:(e,t)=>{k={...k,...e,runtime:k?.runtime||e.runtime,computer_use:k?.computer_use},N={tone:"success",message:t}}}),mt=ji({render:C,setNotice:e=>{N=e}}),oe=jn({render:C,workspaceId:()=>k?.workspace.workspace_id||""});function vs(){return z.find(e=>e.user_id===Q)||z[0]}function hs(e){const t=pe(e.user_id)||pe(e.selected_user_id)||pe(e.id);if(t)return t;const s=pe(e.app_page),n=/^users\/([^/?#]+)$/.exec(s);if(!n?.[1])return"";try{return decodeURIComponent(n[1])}catch{return n[1]}}function pe(e){return typeof e=="string"?e.trim():""}function zi(e){const t=Wt(e),s=hs(e),n=pe(e.setting);Ie=["default-model","voice","password","cache","computer-use"].includes(n)?n:"",t&&(j=t),s&&s!==Q&&(Q=s),H.cancelExcept(dt(j)),C(),Oe()}function Wi(e){e.id===Nt||window.parent===window||(Nt=e.id,window.parent.postMessage({type:"maverick.app.selection-changed",owner_app_id:"settings",selection:{page_id:e.id}},"*"))}function Vi(e){!e||e.user_id===Bt||window.parent===window||(Bt=e.user_id,window.parent.postMessage({type:"maverick.app.selection-changed",owner_app_id:"settings",selection:{user_id:e.user_id}},"*"))}function Ue(){window.parent!==window&&window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"settings",resource:"users"},"*")}const H=en({publish:(e,t)=>{if(e==="registry"){const s=t;Ee=s.items,ce=s.workspace_id||k?.workspace.workspace_id||""}else if(e==="users")z=t.items,(!Q||!z.some(s=>s.user_id===Q))&&(Q=z[0]?.user_id||"");else if(e==="workspaces")qe=t.items;else if(e==="apps")ve=t.items;else if(e==="persistence")De=t;else if(e==="sessions")k?k=nt(k,t):ke=t;else{const s=t,n=k?.workspace.workspace_id;n&&n!==s.workspace.workspace_id&&(H.reset(),As(),k=null,z=[],qe=[],ve=[],De=null,ke=null,Ee=[],ce="",L.savedDrafts=null,se.reset(),oe.reset(),He.reset(),gt.reset(),Object.assign(V,Qt()),queueMicrotask(()=>{C(),Oe()})),Ee.length&&!ce&&(ce=s.workspace.workspace_id);const a=e==="models"||e==="voice";k=tn(k,s,e),ke&&(k=nt(k,ke)),(a||e==="computer-use")&&ie(L,k)}},changed:()=>C()});let ke=null;async function Oe(e=!1){const t=j;t==="workspace-apps"&&H.ensure("registry",e),await Promise.all(dt(t).map(s=>H.ensure(s,e))),j===t&&(t==="app-links"&&H.state("apps").loaded&&H.state("context").loaded&&await _s(e),t==="usage"&&k&&(He.ensureLoaded(e),Ot||=Is(()=>import("./usageVisualizations-BfsyzMIn.js"),__vite__mapDeps([0,1])).then(s=>{rt=s,j==="usage"&&C()}).catch(s=>{Ot=null,j==="usage"&&Re(s)})),t==="voice"&&k&&gt.load(k.workspace.workspace_id,e),t==="learning"&&k&&(oe.load(e),H.ensure("models")),t==="cache"&&mt.ensureLoaded(e))}async function Ji(){await Oe(!0)}async function _s(e=!1){await se.ensureLoaded(k?.workspace.workspace_id||"",ve,e)}async function Gi(e){const t=new FormData(e),s=await Jn({username:String(t.get("username")||""),password:String(t.get("password")||""),display_name:String(t.get("display_name")||""),email:String(t.get("email")||""),platform_role:String(t.get("platform_role")||"member")});z=[...z,s],Q=s.user_id,e.reset(),F(e),N={tone:"success",message:"User created."},C(),Ue()}async function Ki(e,t){const s=new FormData(e),n=await Gn(t.user_id,{display_name:String(s.get("display_name")||""),email:String(s.get("email")||""),platform_role:String(s.get("platform_role")||"member"),account_type:String(s.get("account_type")||"standard"),is_active:s.get("is_active")==="on"});z=z.map(a=>a.user_id===n.user_id?n:a),F(e),N={tone:"success",message:"User updated."},C(),Ue()}async function Qi(e,t){const s=new FormData(e),n=String(s.get("password")||""),a=String(s.get("password_confirmation")||"");if(n!==a)throw new Error("Passwords do not match");await Kn(t.user_id,n),e.reset(),F(e),N={tone:"success",message:"Password updated."},C()}async function Yi(e){const t=e.display_name||e.username;await ct({title:`Delete ${t}?`,detail:"This permanently removes the user account and its workspace memberships. This action cannot be undone.",confirmLabel:"Delete user"})&&(await Qn(e.user_id),Q="",N={tone:"success",message:`${t} deleted.`},z=z.filter(s=>s.user_id!==e.user_id),Q=z[0]?.user_id||"",C(),Ue())}async function Xi(e){const t=qe.map(n=>{const a=document.querySelector(`[data-workspace-enabled="${n.workspace_id}"]`),i=document.querySelector(`[data-workspace-role="${n.workspace_id}"]`);return a?.checked?{workspace_id:n.workspace_id,role:i?.value||"member"}:null}).filter(n=>!!n),s=await Yn(e.user_id,t);z=z.map(n=>n.user_id===s.user_id?s:n),F(".settings-memberships"),N={tone:"success",message:"Workspace access updated."},C(),Ue()}async function Zi(e){await Xn(e),se.invalidate(),await H.ensure("apps",!0)}async function xi(e,t){await Zn(e,t),se.invalidate(),await H.ensure("apps",!0)}async function er(e){await xn(e),se.invalidate(),await H.ensure("apps",!0)}async function tr(e,t,s){await se.saveDependencySelection(e,t,s)}async function sr(e){if(!k)return;const t=k.workspace.workspace_id,s=pt(k,V),n=e?.length?s.filter(l=>e.includes(l.session_id)):s;if(!n.length)return;const a=V.scope==="server"?"the entire server":`workspace ${k.workspace.name}`,i=n.filter(l=>!["closed","completed","failed","terminated","stopped"].includes(l.status)).length;if(!await ct({title:`Delete ${n.length} runtime session${n.length===1?"":"s"}?`,detail:`Scope: ${a}. ${i} sessions may have active agents. Their agents will stop and their conversations, turns and runtime files will be permanently removed.`,confirmLabel:"Delete sessions"})||k.workspace.workspace_id!==t)return;const r=n.map(l=>l.session_id);L.cleanupError="",L.clearingAllRuntime=!e?.length,r.forEach(l=>L.cleaningSessionIds.add(l)),C();try{const l=await Fs(r);if(k.workspace.workspace_id!==t)return;nr(l),k=nt(k,l),N={tone:"success",message:`${l.cleared_sessions} runtime sessions deleted.`}}catch(l){L.cleanupError=l instanceof Error?l.message:"Unable to delete runtime sessions."}finally{r.forEach(l=>L.cleaningSessionIds.delete(l)),L.clearingAllRuntime=!1,C()}}function nr(e){e.deleted_threads<=0||window.parent===window||(window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"chat",resource:"threads"},"*"),e.deleted_thread_ids.forEach(t=>{window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"chat",resource:"threads",deleted_thread_id:t},"*")}))}function ar(e,t){window.parent!==window&&window.parent.postMessage({type:"maverick.app.dependencies-changed",app_id:e,status:t.status},"*")}async function ir(){if(window.parent&&window.parent!==window){window.parent.postMessage({type:"maverick.shell.logout"},"*");return}await zs(),window.location.href="/"}function rr(){return Ma(k,L,j)}function C(){const e=document.getElementById("app");if(!e)return;jt||(Cs(e),jt=!0);const t=performance.now(),s=ks(j),n=dt(j);Z=n.some(o=>!H.state(o).loaded&&!H.state(o).error);const a=n.filter(o=>H.state(o).error&&!H.state(o).loaded),i=n.filter(o=>H.state(o).error&&H.state(o).loaded),r=vs();Je==="usage"&&(j!=="usage"||Z||a.length)&&rt?.unmountUsageVisualizations();const l=Je!==j;Je=j;const c=Z?La(s):a.length?a.map(o=>`<section class="settings-card"><h2>Unable to load ${d(o)}</h2><p role="alert">${d(H.state(o).error)}</p><button type="button" data-retry-resource="${o}">Retry</button></section>`).join(""):Si({appLinksController:se,cacheDiagnosticsController:mt,page:s,persistenceController:Ae,platformSettingsHtml:rr,sessionsHtml:()=>k?an(k,L,V):"",usageHtml:()=>mn(L),learningHtml:()=>Wn(oe.viewState(),k?.provider.available_providers?.find(o=>o.provider_id==="codex")?.model_options||[]),selectedUser:r,users:z,workspaceApps:ve.map(o=>({...o,logo:o.workspace_id===ce&&Ee.find(p=>p.app_id===o.app_id)?.logo||null})),workspaces:qe});if(Ms(e,`<main class="settings-shell"><section class="settings-main"><div class="settings-content" data-render-key="page:${s.id}:${["users","workspace-access"].includes(s.id)?Q:""}">
    <header class="detail-header"><div class="detail-title-block"><h2>${d(s.title)}</h2><span class="detail-title-separator" aria-hidden="true"></span><p>${d(s.summary)}</p></div>
    ${k?`<div class="settings-context"><span>${d(k.workspace.name)}</span><span>${d(k.user.display_name||k.user.username)}</span><button type="button" id="settings-logout" class="settings-secondary">Logout</button></div>`:""}</header>
    ${Ni(N)}${i.map(o=>`<p role="alert">${d(H.state(o).error)} <button type="button" data-retry-resource="${o}">Retry</button></p>`).join("")}${c}
    </div></section>${ui(Ae.viewState())}</main>`),or(),sn(Ae.cancel),oe.setVisible(j==="learning"&&st()&&!Z),j==="usage"&&!Z&&!a.length&&rt?.mountUsageVisualizations({history:L.usageHistory,filters:L.usageHistoryFilters,isLoading:L.isLoadingUsageHistory,onFiltersChange:He.updateUsageHistoryFilters,settings:k}),l&&document.querySelector(".settings-main")?.scrollTo?.(0,0),Wi(s),!Z&&["users","workspace-access"].includes(j)&&Vi(r),Ie&&!Z){const o={"default-model":"[data-agentic-model-toggle]",voice:"#settings-tts-engine",password:"#reset-password input",cache:"#clear-pwa-cache","computer-use":"#settings-computer-use-mode"},p=document.querySelector(o[Ie]);p&&(p.closest("details")?.setAttribute("open",""),p.focus(),p.scrollIntoView?.({block:"center"}),Ie="")}performance.clearMeasures("settings.render"),performance.measure("settings.render",{start:t,end:performance.now()})}function or(){qs(),document.querySelectorAll("[data-user-discard]").forEach(e=>v(e,"click",()=>{const t=e.closest("form, #workspace-assignments");t&&(t instanceof HTMLFormElement&&t.reset(),F(t),C())})),document.querySelectorAll("[data-speech-discard]").forEach(e=>v(e,"click",()=>{ie(L,k,{speech:!0}),F(".settings-speech-model-accordion"),C()})),document.querySelectorAll("[data-hosted-discard]").forEach(e=>v(e,"click",()=>{ie(L,k,{hostedModelId:e.dataset.hostedDiscard}),F("[data-hosted-model-accordion]"),C()})),v(document.getElementById("settings-refresh-app-links"),"click",()=>{_s(!0)}),document.querySelectorAll("[data-retry-resource]").forEach(e=>v(e,"click",()=>{H.ensure(e.dataset.retryResource,!0).then(()=>Oe())})),v(document.getElementById("settings-session-search"),"input",e=>{V.query=e.target.value,V.page=0,C()}),v(document.getElementById("settings-session-status"),"change",e=>{V.status=e.target.value,V.page=0,C()}),v(document.getElementById("settings-session-scope"),"change",e=>{V.scope=e.target.value==="server"?"server":"workspace",V.page=0,V.status="",F(".settings-session-filters"),C()}),v(document.getElementById("settings-sessions-prev"),"click",()=>{V.page-=1,C()}),v(document.getElementById("settings-sessions-next"),"click",()=>{V.page+=1,C()}),v(document.getElementById("create-workspace"),"submit",e=>{e.preventDefault();const t=e.target;D("/api/workspaces",{method:"POST",body:JSON.stringify(Object.fromEntries(new FormData(t)))}).then(async()=>{t.reset(),F("#create-workspace"),await H.ensure("workspaces",!0),await H.ensure("apps",!0),N={tone:"success",message:"Workspace created."},C()}).catch(Re)}),gt.bind(),oe.bind(),Fi.bind(),Ii({clearRuntimeSessionsFromPanel:sr,cacheDiagnosticsController:mt,createUser:Gi,deleteSelectedUser:Yi,dismissNotice:()=>{N=null,C()},installWorkspaceApp:Zi,logoutFromSettings:ir,onHostedProviderRoutingChanged:(e,t,s)=>{da(L,k,e,t,s),C()},saveAgenticBindingFromPanel:Ft.save,activateNativeProviderFromPanel:Ft.activateProvider,onSpeechAudioModelChanged:e=>{oa(L,e),C()},onSpeechConversationModelChanged:e=>{la(L,e),C()},persistenceController:Ae,refreshProviderUsageFromPanel:He.refresh,render:C,resetSelectedUserPassword:Qi,saveDependencySelection:tr,saveHostedProviderSettingsFromPanel:e=>(e&&ra(L,k,e),Ti(zt())),saveSpeechProviderSettingsFromPanel:()=>Hi(zt()),selectedUser:vs,selectUser:e=>{Q=e,C()},setWorkspaceAppStatus:xi,showError:Re,uninstallWorkspaceApp:er,updateMemberships:Xi,updateSelectedUser:Ki,workspaceApps:()=>ve,appDependencies:()=>se.viewState().dependencies})}function zt(){return{render:C,setNotice:e=>{N=e},setSettings:e=>{k=e},settings:k,getSettings:()=>k,state:L}}function Re(e){N={tone:"error",message:e instanceof Error?e.message:"Unexpected error"},C()}Vn({navigate:zi,visibilityChanged:e=>oe.setVisible(j==="learning"&&e&&!Z)});Ji().catch(Re);export{Yt as U,pr as a,Qe as b,cr as c,dr as d,Xt as u};
