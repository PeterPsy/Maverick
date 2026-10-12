const __vite__mapDeps=(i,m=__vite__mapDeps,d=(m.f||(m.f=["assets/usageVisualizations-C29KQ_b0.js","assets/pages-BbZCQO9_.js"])))=>i.map(i=>d[i]);
import{i as ct,P as ks,a as Ss,b as Es,s as Gt,D as Is,c as As,d as Cs}from"./pages-BbZCQO9_.js";const Ms="modulepreload",Ps=function(e){return"/apps/settings/"+e},_t={},qs=function(t,s,n){let a=Promise.resolve();if(s&&s.length>0){let c=function(l){return Promise.all(l.map(p=>Promise.resolve(p).then(u=>({status:"fulfilled",value:u}),u=>({status:"rejected",reason:u}))))};document.getElementsByTagName("link");const r=document.querySelector("meta[property=csp-nonce]"),o=r?.nonce||r?.getAttribute("nonce");a=c(s.map(l=>{if(l=Ps(l),l in _t)return;_t[l]=!0;const p=l.endsWith(".css"),u=p?'[rel="stylesheet"]':"";if(document.querySelector(`link[href="${l}"]${u}`))return;const m=document.createElement("link");if(m.rel=p?"stylesheet":Ms,p||(m.as="script"),m.crossOrigin="",m.href=l,o&&m.setAttribute("nonce",o),document.head.appendChild(m),p)return new Promise((w,g)=>{m.addEventListener("load",w),m.addEventListener("error",()=>g(new Error(`Unable to preload CSS for ${l}`)))})}))}function i(r){const o=new Event("vite:preloadError",{cancelable:!0});if(o.payload=r,window.dispatchEvent(o),!o.defaultPrevented)throw r}return a.then(r=>{for(const o of r||[])o.status==="rejected"&&i(o.reason);return t().catch(i)})};let Qe=!0;const be=new Set;let ye=null;function Ye(e={}){return Qe&&!globalThis.document?.hidden&&(e.requireOnline===!1||globalThis.navigator?.onLine!==!1)}function Ds(e,t={}){if(typeof window>"u")return e(!0),()=>{};const s={notify:e,options:t,previous:Ye(t)};if(be.add(s),!ye){const n=()=>{for(const i of be){const r=Ye(i.options);r!==i.previous&&(i.previous=r,i.notify(r))}},a=i=>{!ct(i)||i.data?.type!=="maverick.app.visibility-changed"||typeof i.data.visible!="boolean"||(Qe=i.data.visible,n())};window.addEventListener?.("message",a),window.addEventListener?.("online",n),window.addEventListener?.("offline",n),globalThis.document?.addEventListener("visibilitychange",n),ye=()=>{window.removeEventListener?.("message",a),window.removeEventListener?.("online",n),window.removeEventListener?.("offline",n),globalThis.document?.removeEventListener("visibilitychange",n)}}return e(s.previous),()=>{be.delete(s),be.size||(ye?.(),ye=null,Qe=!0)}}const Rs=256;function Kt(){if(typeof window>"u")return null;const e=window.__MAVERICK_APP_FRAME_CONTEXT__;if(!e||typeof e!="object"||Array.isArray(e))return null;const t=e;return!bt(t.app_id)||!bt(t.workspace_id)?null:{appId:t.app_id,workspaceId:t.workspace_id}}function bt(e){return typeof e=="string"&&e.trim()===e&&e.length>0&&e.length<=Rs&&!/[\u0000-\u001f\u007f]/u.test(e)}const Ts="maverick.pwa.cache-operations.request.v1",Ls="maverick.pwa.cache-operations.accepted.v1",Hs="maverick.pwa.cache-operations.result.v1",Us=750,Os=1e4;function Ns(e={}){return Qt("diagnostics",e).then(t=>t?.dashboard??null)}function Bs(e={}){return Qt("clear",e).then(t=>t?.cleanup?{cleanup:t.cleanup,dashboard:t.dashboard}:null)}async function Qt(e,t){const s=t.parentWindow??Vs();if(!s)return null;const n=t.parentOrigin===void 0?Js():Xe(t.parentOrigin);if(!n)return null;const a=(t.createMessageChannel??(()=>new MessageChannel))(),i=Gs(),r={action:e,app_id:"settings",request_id:i,type:Ts};return new Promise((o,c)=>{let l=!1,p=!1,u=globalThis.setTimeout(()=>w(null),yt(t.acceptanceTimeoutMs,Us));function m(){globalThis.clearTimeout(u),a.port1.close()}function w(T){p||(p=!0,m(),o(T))}function g(){p||(p=!0,m(),c(new Error("Maverick cache diagnostics are unavailable.")))}a.port1.addEventListener("message",T=>{const k=te(T.data);if(!k||k.app_id!=="settings"||k.request_id!==i)return;if(k.type===Ls){if(l)return;l=!0,globalThis.clearTimeout(u),u=globalThis.setTimeout(g,yt(t.resultTimeoutMs,Os));return}if(!l||k.type!==Hs)return;if(k.status==="unavailable"){w(null);return}if(k.status!=="ok"){g();return}const b=js(k.dashboard),D=k.cleanup===void 0?void 0:Ws(k.cleanup);if(!b||e==="clear"&&!D){g();return}w({...D?{cleanup:D}:{},dashboard:b})}),a.port1.start();try{s.postMessage(r,n,[a.port2])}catch{w(null)}})}function js(e){const t=te(e),s=Fs(t?.diagnostics),n=zs(t?.metrics);return s&&n?{diagnostics:s,metrics:n}:null}function Fs(e){const t=te(e);return!t||t.backend!=="indexeddb"&&t.backend!=="memory"||typeof t.fileCacheAvailable!="boolean"||["cacheBytes","entryCount","fileCacheBytes","fileCacheEntryCount","pendingCleanupCount","structuredCacheBytes","structuredEntryCount"].some(n=>!fe(t[n]))||!oe(t.originQuotaBytes)||!oe(t.originUsageBytes)?null:t}function zs(e){const t=te(e),s=te(t?.counters),n=te(t?.quota),a=te(t?.requestWait);if(!t||t.schema!==ks||!s||!n||!a||!Ze(t.updatedAt)||!Ze(t.windowStartedAt)||Ss.some(i=>!fe(s[i]))||!oe(n.lastEstimatedAt)||!oe(n.quotaBytes)||!oe(n.usageBytes)||n.supported!==null&&typeof n.supported!="boolean")return null;for(const i of["averageDurationMs","durationObservations","maxDurationMs","pendingCount","totalDurationMs"])if(!fe(a[i]))return null;return oe(a.oldestPendingMs)?t:null}function Ws(e){const t=te(e);return!t||t.status!=="complete"&&t.status!=="pending"||!fe(t.pendingCleanupCount)||!fe(t.removed)?null:t}function Vs(){return typeof window<"u"&&window.parent!==window?window.parent:null}function Js(){if(typeof window>"u")return null;const e=Xe(window.__MAVERICK_PLATFORM_ORIGIN__),t=Xe(window.location.origin);return e&&t&&e!==t?e:null}function Xe(e){if(typeof e!="string"||!e)return null;try{const t=new URL(e);return t.origin===e&&(t.protocol==="http:"||t.protocol==="https:")?t.origin:null}catch{return null}}function Gs(){return globalThis.crypto?.randomUUID?.()??`${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`}function yt(e,t){return typeof e=="number"&&Number.isFinite(e)&&e>0?Math.min(Math.floor(e),3e4):t}function fe(e){return typeof e=="number"&&Number.isSafeInteger(e)&&e>=0}function Ze(e){return typeof e=="number"&&Number.isFinite(e)&&e>=0}function oe(e){return e===null||Ze(e)}function te(e){return e&&typeof e=="object"&&!Array.isArray(e)?e:null}const ge=new Set;let $e=null;function Ks(e,t){if(typeof window>"u")return()=>{};const s={event:e,refresh:t};return ge.add(s),$e||($e=Qs()),()=>{ge.delete(s),ge.size||($e?.(),$e=null)}}function Qs(){const e=Kt(),t=!!(e&&window.parent&&window.parent!==window),s=()=>!!(globalThis.document?.hidden||globalThis.navigator?.onLine===!1);let n=t&&s(),a=null,i,r=!1,o=!1,c=0;const l=Ye;let p=l();o=!p;const u=()=>{for(const $ of ge)$.refresh()},m=$=>{for(const A of ge)A.event($)};function w(){if(o=!0,r||!l()||i!==void 0)return;const $=Math.min(3e4,1e3*2**Math.min(c++,5)*(.8+Math.random()*.4));i=setTimeout(()=>{i=void 0,g()},$)}function g(){if(r||t||!l()||a||typeof WebSocket>"u")return;const $=window.location.protocol==="https:"?"wss:":"ws:";let A;try{A=new WebSocket(`${$}//${window.location.host}/api/apps/events/ws`)}catch{w();return}a=A;let F=!1;const U=()=>!r&&a===A;A.onopen=()=>{!U()||F||(F=!0,c=0,o&&(o=!1,u()))},A.onmessage=z=>{if(!U()||!l())return;let P;try{P=JSON.parse(z.data)}catch{return}m(P)},A.onclose=()=>{U()&&(a=null,w())},A.onerror=()=>{U()&&A.close()}}function T(){const $=l();if($!==p)if(p=$,$)t?o&&!n&&(o=!1,u()):g();else{t&&s()&&(n=!0),o=!0,clearTimeout(i),i=void 0;const A=a;a=null,A?.close()}}function k(){t&&s()&&(n=!0)}function b($){if(!t||!ct($)||!$.data||typeof $.data!="object")return;const A=$.data;if(A.type==="maverick.app.events-resync")n=!1,l()?(o=!1,u()):o=!0;else if(A.type==="maverick.app.event"&&A.event&&typeof A.event=="object"){if(A.event.workspace_id&&A.event.workspace_id!==e.workspaceId)return;l()?m(A.event):o=!0}}const D=Ds(T);return window.addEventListener?.("offline",k),globalThis.document?.addEventListener("visibilitychange",k),window.addEventListener?.("message",b),g(),()=>{r=!0,clearTimeout(i);const $=a;a=null,$?.close(),D(),window.removeEventListener?.("offline",k),globalThis.document?.removeEventListener("visibilitychange",k),window.removeEventListener?.("message",b)}}let ve=new WeakSet;const x=new Map;function Ys(e=document.getElementById("app")){x.clear(),ve=new WeakSet,e?.replaceChildren()}function Xs(e){const t=s=>{if(s.target instanceof Element&&!s.target.hasAttribute("data-settings-controlled")){ve.add(s.target);const n=s.target.closest("form, #workspace-assignments")?.querySelector("[data-action-status]");n&&(n.textContent="Unsaved changes")}};e.addEventListener("input",t,!0),e.addEventListener("change",t,!0)}function B(e){(typeof e=="string"?[...document.querySelectorAll(e),...Array.from(x.values()).flatMap(s=>[...s.matches(e)?[s]:[],...s.querySelectorAll(e)])]:[e]).forEach(s=>{ve.delete(s),s.querySelectorAll("[data-action-status]").forEach(n=>{n.textContent="",n.setAttribute("role","status")}),s.querySelectorAll("input, select, textarea").forEach(n=>ve.delete(n))})}function Zs(e,t){const s=document.activeElement,n=s instanceof HTMLInputElement||s instanceof HTMLTextAreaElement?[s.selectionStart,s.selectionEnd]:null,a=document.createElement("template");a.innerHTML=t,Yt(e,a.content),s?.isConnected&&document.activeElement!==s&&(s.focus({preventScroll:!0}),n&&n[0]!==null&&n[1]!==null&&s.setSelectionRange(n[0],n[1]))}function ee(e){return e instanceof Element?e.getAttribute("data-render-key")||e.id||["data-settings-model-accordion","data-hosted-model-accordion","data-runtime-row","data-workspace-row","data-app-row","data-dependency-row","data-agentic-provider-group","data-hosted-provider-group","data-execution-family"].map(t=>{const s=e.getAttribute(t);return s===null?"":`${t}:${s}`}).find(Boolean)||(e.classList.length?`${e.tagName}:${Array.from(e.classList).filter(t=>!t.startsWith("is-")).join(" ")}`:""):""}function je(e,t){return e.nodeType===t.nodeType&&e.nodeName===t.nodeName&&ee(e)===ee(t)}function Yt(e,t){let s=e.firstChild;for(const n of Array.from(t.childNodes)){if(s&&!je(s,n)&&ee(n)){const a=Array.from(e.childNodes).find(i=>je(i,n))||x.get(ee(n));a&&(x.delete(ee(n)),e.insertBefore(a,s),s=a)}if(!s||!je(s,n)){const a=n.cloneNode(!0);if(e.insertBefore(a,s),s&&!ee(s)){const i=s;s=s.nextSibling,i.remove()}continue}xs(s,n),s=s.nextSibling}for(;s;){const n=s;s=s.nextSibling,n instanceof Element&&ee(n).startsWith("page:")&&(x.set(ee(n),n),x.size>12&&x.delete(x.keys().next().value)),e.removeChild(n)}}function xs(e,t){if(!(e instanceof Element)||!(t instanceof Element)){e.nodeValue!==t.nodeValue&&(e.nodeValue=t.nodeValue);return}const s=ve.has(e)&&!t.hasAttribute("data-settings-controlled"),n=e instanceof HTMLDetailsElement?e.open:void 0,a=s&&"value"in e?String(e.value):void 0,i=s&&e instanceof HTMLInputElement?e.checked:void 0;if(!e.matches("[data-action-status]")){for(const r of Array.from(e.attributes))e.hasAttribute("data-pending-action")&&["data-pending-action","aria-busy"].includes(r.name)||t.hasAttribute(r.name)||e.removeAttribute(r.name);for(const r of Array.from(t.attributes))e.getAttribute(r.name)!==r.value&&e.setAttribute(r.name,r.value);e.closest("[data-pending-action]")&&e.matches("input, button, select")&&e.setAttribute("disabled",""),!e.matches("[data-usage-history-chart], [data-usage-history-filters]")&&(Yt(e,t),e instanceof HTMLDetailsElement&&n!==void 0&&(e.open=n),e instanceof HTMLInputElement&&(e.value=a??t.value,e.checked=i??t.checked),(e instanceof HTMLSelectElement||e instanceof HTMLTextAreaElement)&&(e.value=a??t.value))}}let xe=new AbortController;function en(){xe.abort(),xe=new AbortController}function f(e,t,s){e?.addEventListener(t,s,{signal:xe.signal})}async function q(e,t={}){const s=await fetch(e,{credentials:"same-origin",headers:{"Content-Type":"application/json",...t.headers||{}},...t}),n=await s.json();if(!s.ok)throw new Error(n.detail||n.error||`Request failed ${s.status}`);return n}function $t(e,t=""){return typeof e=="string"?e:t}function tn(e){return Array.isArray(e)?e.filter(t=>typeof t=="string"):[]}function sn(e){if(!e||typeof e!="object"||Array.isArray(e))return null;const t=e,s=t.kind==="image"||t.kind==="glyph"?t.kind:null;return s&&typeof t.value=="string"?{kind:s,value:t.value}:null}function nn(e){const t=e&&typeof e=="object"&&!Array.isArray(e)?e:{},s=$t(t.app_id);return{app_id:s,name:$t(t.name,s||"Unnamed app"),views:tn(t.views),logo:sn(t.logo)}}async function an(){return((await q("/api/apps")).items||[]).map(nn).filter(t=>t.app_id)}function pt(e){const t=new URLSearchParams({consumer_app_id:e});return q(`/api/apps/dependencies?${t.toString()}`)}function Xt(e,t,s){return q("/api/apps/dependencies",{method:"POST",body:JSON.stringify({consumer_app_id:e,alias:t,provider_app_ids:s})})}function wt(e="all"){return q(e==="all"?"/api/settings/platform":`/api/settings/platform?section=${e}`)}function rn(){return q("/api/providers/usage")}function on(e,t,s={}){const n=new URLSearchParams({resolution:e,periods:String(t)});return s.providerId&&n.set("provider_id",s.providerId),s.modelId&&n.set("model_id",s.modelId),q(`/api/usage/timeseries?${n.toString()}`)}function ln(e){return q("/api/providers/hosted/selection",{method:"POST",body:JSON.stringify(e)})}function dn(e){return q("/api/providers/speech/selection",{method:"POST",body:JSON.stringify(e)})}function cn(e){return q("/api/providers/agentic/workspace-bindings",{method:"POST",body:JSON.stringify(e)})}function pn(e){return q("/api/providers/native/activate",{method:"POST",body:JSON.stringify({provider_id:e,confirmation:"native-runtime-reviewed"})})}function un(e,t="settings_runtime_sessions_cleared"){return q("/api/settings/runtime-sessions/clear",{method:"POST",body:JSON.stringify({session_ids:e,reason:t})})}function gn(){return q("/api/auth/logout",{method:"POST"})}function mn(e){return q("/api/admin/persistence/migrations/dry-run",{method:"POST",body:JSON.stringify(e)})}function fn(e){return q("/api/admin/persistence/migrations/apply",{method:"POST",body:JSON.stringify(e)})}function d(e){return e.replace(/[&<>"']/g,t=>t==="&"?"&amp;":t==="<"?"&lt;":t===">"?"&gt;":t==='"'?"&quot;":"&#39;")}function y(e){return d(e)}function Zt(){return{workspaceId:"",providerAppId:"",engines:[],engine:"",language:"auto",savedEngine:"",savedLanguage:"auto",loading:!1,saving:!1,loaded:!1,error:""}}const kt={logical_names:["openrouter-api-key","deepinfra-api-key","google-ai-studio-api-key"],required:!1};function vn(e){const t=e.state;let s=0;function n(){s+=1,Object.assign(t,Zt())}async function a(c,l=!1){if(!c||(t.workspaceId!==c&&n(),t.loading||t.saving||t.loaded&&!l))return;t.workspaceId=c;const p=++s;t.loading=!0,t.error="",e.render();try{const u=await pt("settings");if(p!==s)return;if(u.workspace_id!==c)throw new Error("The active workspace changed. Reload voice settings.");const w=u.dependencies.find(T=>T.alias==="text-to-speech")?.selected_provider_app_ids[0]||"";if(!w)throw new Error("Select a text-to-speech provider for Settings in App links.");const g=await q(`/api/apps/${encodeURIComponent(w)}/backend`,{method:"POST",body:JSON.stringify({action:"engine_health",include_voices:!1,_app_secret_request:kt})});if(p!==s)return;t.providerAppId=w,i(g),t.loaded=!0}catch(u){p===s&&(t.error=u instanceof Error?u.message:"Unable to load text-to-speech settings.")}finally{p===s&&(t.loading=!1,e.render())}}function i(c,l=!1){t.engines=c.synthesis,(!t.loaded||l||t.engine===t.savedEngine)&&(t.engine=c.settings.synthesis_engine),(!t.loaded||l||t.language===t.savedLanguage)&&(t.language=c.settings.synthesis_language),t.savedEngine=c.settings.synthesis_engine,t.savedLanguage=c.settings.synthesis_language}async function r(){if(!t.providerAppId||t.saving||t.loading)return;const c=s;t.saving=!0,t.error="",e.render();try{const l=await q(`/api/apps/${encodeURIComponent(t.providerAppId)}/backend`,{method:"POST",body:JSON.stringify({action:"set_engine",synthesis_engine:t.engine,synthesis_language:t.language,_app_secret_request:kt})});if(c!==s)return;i(l.engines,!0),B(".settings-tts-group"),e.notify("Text-to-speech settings updated.")}catch(l){c===s&&(t.error=l instanceof Error?l.message:"Unable to save text-to-speech settings.")}finally{c===s&&(t.saving=!1,e.render())}}function o(){f(document.getElementById("settings-tts-discard"),"click",()=>{t.engine=t.savedEngine,t.language=t.savedLanguage,B(".settings-tts-group"),e.render()}),f(document.getElementById("settings-tts-engine"),"change",c=>{t.engine=c.currentTarget.value,t.error="",e.render()}),f(document.getElementById("settings-tts-language"),"input",c=>{t.language=c.currentTarget.value;const l=document.getElementById("settings-tts-discard");l&&(l.disabled=t.engine===t.savedEngine&&t.language===t.savedLanguage)}),f(document.getElementById("settings-tts-save"),"click",()=>{r()}),f(document.getElementById("settings-tts-retry"),"click",()=>{a(t.workspaceId,!0)})}return{load:a,save:r,reset:n,bind:o}}const hn={auto:"Automatic local voice",piper:"Piper","espeak-ng":"eSpeak NG",espeak:"eSpeak","kokoro-openrouter":"Kokoro · OpenRouter","kokoro-deepinfra":"Kokoro · DeepInfra",gemini:"Gemini 3.8 Flash-Lite TTS"};function _n(e){const t=e.engines.find(a=>a.engine===e.engine),s=e.loading||e.saving,n=[{engine:"auto",available:!0},...e.engines];return`<section class="settings-hosted-provider-group settings-tts-group" aria-labelledby="settings-tts-title">
    <div class="settings-heading"><div><p class="settings-kicker">Text to speech</p><h3 id="settings-tts-title">Read-aloud voice</h3></div></div>
    ${e.loading?'<p class="settings-card-copy" role="status">Loading voice settings…</p>':""}
    ${e.loaded?`<div class="settings-tts-controls">
      <label>Voice engine<select id="settings-tts-engine" ${s?"disabled":""}>
        ${n.map(a=>`<option value="${y(a.engine)}" ${a.engine===e.engine?"selected":""} ${!a.available&&a.engine!==e.engine?"disabled":""}>${d(hn[a.engine]||a.engine)}${a.available?"":" · unavailable"}</option>`).join("")}
      </select></label>
      <label>Language<input id="settings-tts-language" list="settings-tts-languages" value="${y(e.language)}" ${s?"disabled":""} autocomplete="off" placeholder="auto or it-IT">
        <datalist id="settings-tts-languages"><option value="auto">Automatic</option><option value="it-IT">Italian</option><option value="en-US">English</option></datalist>
      </label>
    </div>
    ${t&&!t.available?`<p class="settings-platform-error">${d(t.detail||"The selected voice engine is unavailable.")}</p>`:""}
    <button type="button" class="settings-secondary" id="settings-tts-discard" ${s||e.engine===e.savedEngine&&e.language===e.savedLanguage?"disabled":""}>Discard edits</button>
    <button type="button" class="settings-secondary" id="settings-tts-save" ${s||e.engine!=="auto"&&!t?.available?"disabled":""}>${e.saving?"Saving…":"Save voice settings"}</button>`:""}
    ${e.error?`<p class="settings-platform-error" role="alert">${d(e.error)}</p><button type="button" class="settings-secondary" id="settings-tts-retry" ${s?"disabled":""}>Retry</button>`:""}
  </section>`}function bn(){return{workspaceId:"",providerId:"",modelId:"",effort:"",executionMode:"delegated",fallbackModelId:"",fallbackEffort:"",saving:!1,error:"",generation:0,savedSelection:""}}function et(e,t,s=!1){const n=t?.computer_use,a=t?.workspace.workspace_id||"",i=e.workspaceId!==a,r=JSON.stringify([n?.provider_id,n?.model_id,n?.reasoning_effort,n?.execution_mode,n?.fallback_model_id,n?.fallback_reasoning_effort]);if(i&&(e.generation+=1,e.saving=!1,e.error=""),!i&&!s){if(e.savedSelection===r)return;const o=JSON.stringify([e.providerId||void 0,e.modelId||void 0,e.effort||void 0,e.executionMode,e.fallbackModelId||void 0,e.fallbackEffort||void 0]);if(e.savedSelection&&o!==e.savedSelection){e.savedSelection=r;return}}Object.assign(e,{workspaceId:a,providerId:n?.provider_id||"",modelId:n?.model_id||"",effort:n?.reasoning_effort||"",executionMode:n?.execution_mode||"delegated",fallbackModelId:n?.fallback_model_id||"",fallbackEffort:n?.fallback_reasoning_effort||"",savedSelection:r})}function xt(e,t){return e?.computer_use?.providers.find(s=>s.provider_id===t.providerId)?.models.find(s=>s.model_id===t.modelId)}function yn(e,t){const s=e.computer_use;if(!s)return"";const n=xt(e,t),a=n?.supported_reasoning_efforts||[],i=a.length?a.some(c=>c.effort===t.effort):!t.effort,r=t.providerId!==s.provider_id||t.modelId!==s.model_id||t.effort!==(s.reasoning_effort||"")||t.executionMode!==(s.execution_mode||"delegated")||t.fallbackModelId!==(s.fallback_model_id||"")||t.fallbackEffort!==(s.fallback_reasoning_effort||""),o=!s.can_configure||t.saving;return`<section class="settings-card settings-platform" aria-labelledby="settings-computer-use-title">
    <div class="settings-heading settings-platform-heading settings-model-card-heading">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">desktop_windows</span>
      <div><p class="settings-kicker">Models</p><h2 id="settings-computer-use-title">PC use decision model</h2></div>
    </div>
    <p class="settings-card-copy">Use the chat model directly or a separate interface operator. Reconnect PC use after changing execution mode. Operator model changes apply to the next UI task.</p>
    ${t.modelId==="gpt-6-luna"&&t.effort==="low"&&t.executionMode==="delegated"?'<p class="settings-card-copy">Luna Low uses planned UI steps. Choose a recovery model for tasks that need broader navigation.</p>':""}
    <div class="settings-platform-provider-forms">
      <label class="settings-platform-field settings-platform-field-wide"><span>UI execution</span>
        <select id="settings-computer-use-mode" ${o?"disabled":""}>
          <option value="direct" ${t.executionMode==="direct"?"selected":""}>Chat model directly</option>
          <option value="delegated" ${t.executionMode==="delegated"?"selected":""}>Separate interface operator</option>
        </select>
      </label>
      ${t.executionMode==="delegated"||!n||!i?`<label class="settings-platform-field settings-platform-field-wide"><span>Decision model</span>
        <select id="settings-computer-use-model" ${o?"disabled":""}>
          ${n?"":`<option selected disabled value="">Unavailable: ${d(t.modelId)}</option>`}
          ${s.providers.map(c=>`<optgroup label="${d(c.label)}">${c.models.map(l=>`<option value="${d(JSON.stringify([c.provider_id,l.model_id]))}" ${c.provider_id===t.providerId&&l.model_id===t.modelId?"selected":""}>${d(l.label)}</option>`).join("")}</optgroup>`).join("")}
        </select>
      </label>
      <label class="settings-platform-field settings-platform-field-wide"><span>Reasoning effort</span>
        <select id="settings-computer-use-effort" ${o||!n?"disabled":""}>
          ${i?"":`<option selected disabled value="${d(t.effort)}">Unavailable: ${d(t.effort)}</option>`}
          ${a.length?a.map(c=>`<option value="${d(c.effort)}" ${c.effort===t.effort?"selected":""}>${d(c.label)}</option>`).join(""):'<option value="">Default</option>'}
        </select>
      </label>
      ${t.executionMode==="delegated"?`<label class="settings-platform-field settings-platform-field-wide"><span>Recovery model</span>
        <select id="settings-computer-use-fallback" ${o?"disabled":""}>
          <option value="" ${t.fallbackModelId?"":"selected"}>Return to chat</option>
          ${t.fallbackModelId&&!s.providers.flatMap(c=>c.models).some(c=>c.model_id===t.fallbackModelId)?`<option selected disabled value="${d(t.fallbackModelId)}">Unavailable: ${d(t.fallbackModelId)}</option>`:""}
          ${s.providers.flatMap(c=>c.models).filter(c=>c.model_id!==t.modelId&&c.supported_reasoning_efforts.some(l=>l.effort==="medium")).map(c=>`<option value="${d(c.model_id)}" ${c.model_id===t.fallbackModelId?"selected":""}>${d(c.label)} · Mid</option>`).join("")}
        </select>
      </label>
      `:""}
      `:'<p class="settings-card-copy">The selected chat model controls the interface directly.</p>'}
      ${s.available?"":'<p class="settings-inline-error" role="alert">The saved model is unavailable. Choose an available model to continue PC use.</p>'}
      ${t.error?`<p class="settings-inline-error" role="alert">${d(t.error)}</p>`:""}
      <button type="button" id="settings-computer-use-discard" class="settings-secondary" ${r&&!o?"":"disabled"}>Discard edits</button>
      <button type="button" id="settings-computer-use-save" ${o||!n||!i||!r?"disabled":""}>
        <span class="material-symbols-rounded" aria-hidden="true">${t.saving?"sync":"save"}</span>
        ${t.saving?"Saving":"Save decision model"}
      </button>
    </div>
  </section>`}function $n(e){const{state:t,getSettings:s,render:n}=e;let a=0;async function i(){const o=s();if(!o?.computer_use?.can_configure||t.saving)return;const c=o.workspace.workspace_id;if(c!==t.workspaceId)return;const l=t.generation,p=++a,u=()=>t.generation===l&&p===a&&s()?.workspace.workspace_id===c;t.saving=!0,t.error="";const m={workspace_id:c,provider_id:t.providerId,model_id:t.modelId,reasoning_effort:t.effort||null,execution_mode:t.executionMode,fallback_model_id:t.fallbackModelId||null,fallback_reasoning_effort:t.fallbackEffort||null};n();try{const w=await q("/api/settings/computer-use",{method:"POST",body:JSON.stringify(m)});if(!u()||w.workspace_id!==c)return;e.setSelection(w),et(t,s(),!0),B('[aria-labelledby="settings-computer-use-title"]'),e.notify("PC use decision model updated.")}catch(w){u()&&(t.error=w instanceof Error?w.message:"Unable to update the decision model.")}finally{u()&&(t.saving=!1,n())}}function r(){f(document.getElementById("settings-computer-use-discard"),"click",()=>{et(t,s(),!0),B('[aria-labelledby="settings-computer-use-title"]'),n()}),f(document.getElementById("settings-computer-use-mode"),"change",o=>{t.executionMode=o.currentTarget.value,t.executionMode==="direct"&&(t.fallbackModelId="",t.fallbackEffort=""),t.error="",n()}),f(document.getElementById("settings-computer-use-fallback"),"change",o=>{t.fallbackModelId=o.currentTarget.value,t.fallbackEffort=t.fallbackModelId?"medium":"",t.error="",n()}),f(document.getElementById("settings-computer-use-model"),"change",o=>{const[c,l]=JSON.parse(o.currentTarget.value);t.providerId=c,t.modelId=l,t.fallbackModelId===l&&(t.fallbackModelId="",t.fallbackEffort="");const p=xt(s(),t);t.effort=p?.supported_reasoning_efforts.some(u=>u.effort==="low")?"low":p?.default_reasoning_effort||"",t.error="",n()}),f(document.getElementById("settings-computer-use-effort"),"change",o=>{t.effort=o.currentTarget.value,t.error="",n()}),f(document.getElementById("settings-computer-use-save"),"click",()=>{i()})}return{bind:r,save:i}}async function wn(){try{return await q("/api/admin/persistence")}catch{return null}}const kn={registry:"/api/apps",context:"/api/settings/platform?section=context",models:"/api/settings/platform?section=models",voice:"/api/settings/platform?section=voice","computer-use":"/api/settings/platform?section=computer-use",users:"/api/admin/users",workspaces:"/api/admin/workspaces",apps:"/api/admin/workspace-apps",persistence:"/api/admin/persistence",sessions:"/api/settings/runtime-sessions"};function ut(e){return e==="users"||e==="workspace-access"?["users","workspaces"]:e==="workspace-apps"?["context","workspaces","apps"]:e==="app-links"?["context","apps"]:e==="sessions"?["context","sessions"]:e==="usage"||e==="learning"?["context"]:e==="cache"?[]:[e]}function Sn(e){const t=new Map,s=new Map;function n(o){return t.has(o)||t.set(o,{loaded:!1,loading:!1,error:""}),t.get(o)}function a(o,c=!1){if(!c&&s.has(o))return s.get(o).promise;if(!c&&n(o).loaded)return Promise.resolve();s.get(o)?.controller.abort();const l=new AbortController;Object.assign(n(o),{loading:!0,error:""});const p=performance.now(),u=q(kn[o],{signal:l.signal}).then(m=>{l.signal.aborted||(e.publish(o,m),n(o).loaded=!0)}).catch(m=>{l.signal.aborted||(n(o).error=m instanceof Error?m.message:"Unable to load settings.")}).finally(()=>{s.get(o)?.controller===l&&(s.delete(o),n(o).loading=!1,performance.clearMeasures(`settings.load.${o}`),performance.measure(`settings.load.${o}`,{start:p,end:performance.now()}),e.changed(o))});return s.set(o,{controller:l,promise:u}),e.changed(o),u}function i(){s.forEach(({controller:o})=>o.abort()),s.clear(),t.clear()}function r(o){s.forEach(({controller:c},l)=>{o.includes(l)||(c.abort(),s.delete(l),n(l).loading=!1)})}return{state:n,ensure:a,reset:i,cancelExcept:r}}function En(e,t,s){e?.workspace.workspace_id!==t.workspace.workspace_id&&(e=null);const n=s==="models"?t.provider:s==="voice"?{...e?.provider||t.provider,hosted_text:t.provider.hosted_text,speech_stt:t.provider.speech_stt}:e?.provider||t.provider;return{...e,...t,provider:n,runtime:{...e?.runtime,...t.runtime,all_sessions:e?.runtime.all_sessions},computer_use:t.computer_use||e?.computer_use,agentic_admin:s==="models"?t.agentic_admin:e?.agentic_admin}}function gt(e){const t=document.activeElement,s=document.createElement("dialog");return s.className="settings-modal settings-confirm-dialog",s.setAttribute("aria-labelledby","settings-confirm-title"),s.setAttribute("aria-describedby","settings-confirm-detail"),s.innerHTML=`<h2 id="settings-confirm-title">${d(e.title)}</h2>
    <p id="settings-confirm-detail" class="settings-card-copy">${d(e.detail)}</p>
    <form method="dialog" class="settings-modal-actions">
      <button value="cancel" class="settings-secondary" autofocus>Cancel</button>
      <button value="confirm" class="settings-danger">${d(e.confirmLabel)}</button>
    </form>`,document.body.append(s),new Promise(n=>{s.addEventListener("close",()=>{const a=s.returnValue==="confirm";s.remove(),t?.isConnected&&t.focus(),n(a)},{once:!0}),s.showModal()})}let Fe=null,we=null;function In(e){const t=document.querySelector('.settings-modal[role="dialog"]');if(!t){we&&Fe?.isConnected&&Fe.focus(),we=null;return}const s=()=>Array.from(t.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex="0"]'));we!==t&&(Fe=document.activeElement,we=t,s()[0]?.focus()),t.onkeydown=n=>{if(n.key==="Escape"&&!t.querySelector("button#close-migration-modal:disabled")&&(n.preventDefault(),e()),n.key!=="Tab")return;const a=s(),i=a[0],r=a.at(-1);n.shiftKey&&document.activeElement===i&&(n.preventDefault(),r?.focus()),!n.shiftKey&&document.activeElement===r&&(n.preventDefault(),i?.focus())}}const ze=20,es=()=>({scope:"workspace",query:"",status:"",page:0});function mt(e,t){const s=e.runtime.all_sessions||e.runtime.sessions||[];return t.scope==="server"&&e.runtime.cleanup_scope==="server"?s:s.filter(n=>n.workspace_id===e.workspace.workspace_id)}function An(e,t){const s=t.query.trim().toLowerCase();return mt(e,t).filter(n=>(!t.status||n.status===t.status)&&`${n.session_id} ${n.agent_id} ${n.workspace_name||n.workspace_id} ${n.provider_id}`.toLowerCase().includes(s))}function Cn(e,t,s){const n=mt(e,s),a=An(e,s),i=Math.max(1,Math.ceil(a.length/ze));s.page=Math.min(s.page,i-1);const r=a.slice(s.page*ze,(s.page+1)*ze),o=e.runtime.cleanup_allowed===!0,c=s.scope==="server"?"All workspaces on this server":e.workspace.name;return`<section class="settings-card settings-runtime-settings-card">
    <div class="settings-heading"><div><p class="settings-kicker">${d(c)}</p><h2>Runtime sessions</h2></div>
      <button type="button" id="settings-clear-all-runtime" class="settings-danger" ${!o||!n.length||t.clearingAllRuntime?"disabled":""}>${t.clearingAllRuntime?"Deleting…":`Delete ${n.length} sessions`}</button>
    </div>
    <p class="settings-card-copy">Deletion stops active agents and removes their conversations, turns and runtime files. Review the confirmation before continuing.</p>
    <div class="settings-grid settings-session-filters">
      <label>Search sessions<input id="settings-session-search" type="search" value="${y(s.query)}" placeholder="Agent, workspace or session" /></label>
      <label>Status<select id="settings-session-status"><option value="">All statuses</option>${Array.from(new Set(n.map(l=>l.status))).sort().map(l=>`<option value="${y(l)}" ${s.status===l?"selected":""}>${d(l)}</option>`).join("")}</select></label>
      ${e.runtime.cleanup_scope==="server"?`<label>View scope<select id="settings-session-scope"><option value="workspace" ${s.scope==="workspace"?"selected":""}>Current workspace</option><option value="server" ${s.scope==="server"?"selected":""}>Entire server</option></select></label>`:""}
    </div>
    ${o?"":'<p role="status">You do not have permission to delete sessions in this workspace.</p>'}
    <div class="settings-platform-runtime-list">${r.map(l=>Mn(l,o,t)).join("")||'<p role="status">No sessions match this view.</p>'}</div>
    <div class="settings-pagination"><span role="status">${a.length} sessions · Page ${s.page+1} of ${i}</span>
      <button type="button" id="settings-sessions-prev" class="settings-secondary" ${s.page===0?"disabled":""}>Previous</button>
      <button type="button" id="settings-sessions-next" class="settings-secondary" ${s.page+1>=i?"disabled":""}>Next</button>
    </div>
    ${t.cleanupError?`<p class="settings-inline-error" role="alert">${d(t.cleanupError)}</p>`:""}
  </section>`}function Mn(e,t,s){const n=s.cleaningSessionIds.has(e.session_id)||s.clearingAllRuntime;return`<article class="settings-platform-runtime-row" data-runtime-row="${y(e.session_id)}">
    <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">terminal</span>
    <span class="settings-platform-runtime-copy"><span class="settings-platform-runtime-title"><strong>${d(e.agent_id||e.session_id)}</strong>
      <button type="button" class="settings-secondary" data-runtime-clear="${y(e.session_id)}" aria-label="Delete session ${y(e.agent_id||e.session_id)}" ${!t||n?"disabled":""}>${n?"Deleting…":"Delete"}</button></span>
      <small>${d(e.workspace_name||e.workspace_id)} · ${d(e.status)} · ${d(e.effective_mode)}</small>
      ${e.recovery_reason_code?`<small class="settings-inline-error">${d(e.recovery_reason_code)}</small>`:""}
      ${e.agentic_containment?.status==="NO-GO"?`<small class="settings-inline-error">Contained: ${d(e.agentic_containment.reason_code||"Unavailable")}</small>`:""}
      <code>${d(e.session_id)}</code></span>
  </article>`}const tt=[{value:"6h",label:"6 hours",resolution:"hour",periods:6},{value:"12h",label:"12 hours",resolution:"hour",periods:12},{value:"24h",label:"24 hours",resolution:"hour",periods:24},{value:"3d",label:"3 days",resolution:"hour",periods:72},{value:"7d",label:"7 days",resolution:"day",periods:7},{value:"30d",label:"30 days",resolution:"day",periods:30},{value:"90d",label:"90 days",resolution:"day",periods:90},{value:"180d",label:"180 days",resolution:"day",periods:180},{value:"1y",label:"1 year",resolution:"day",periods:365}],ts=[{value:"non_cached_tokens",label:"Non-cached"},{value:"total_tokens",label:"Processed total"},{value:"cached_input_tokens",label:"Cached input"},{value:"input_tokens",label:"Uncached input"},{value:"output_tokens",label:"Output"},{value:"reasoning_output_tokens",label:"Reasoning output"},{value:"cache_write_input_tokens",label:"Cache write"}];function st(){return{metric:"non_cached_tokens",providerId:"",modelId:"",timeRange:"24h"}}function Pn(e,t){const s=ts.some(a=>a.value===t.metric)?t.metric:e.metric,n=tt.some(a=>a.value===t.timeRange)?t.timeRange:e.timeRange;return{metric:s,providerId:St(t.providerId,e.providerId),modelId:St(t.modelId,e.modelId),timeRange:n}}function ss(e){return tt.find(t=>t.value===e)||tt[2]}function gr(e,t){return t==="non_cached_tokens"?Math.max(0,We(e.total_tokens)-We(e.cached_input_tokens)):Math.max(0,We(e[t]))}function mr(e){return ts.find(t=>t.value===e)?.label||"Non-cached"}function fr(e){const t=new Map,s=(i,r=[])=>{if(!i?.provider_id)return;const o=t.get(i.provider_id)||new Set;i.model_options.forEach(c=>c.model_id&&o.add(c.model_id)),r.forEach(c=>c&&o.add(c)),t.set(i.provider_id,o)},n=e?.provider;s(n?.active_provider,[n?.model_settings?.selected_model_id||"",...(n?.model_settings?.available_models||[]).map(i=>i.model_id)]),n?.available_providers?.forEach(i=>s(i));const a=n?.hosted_text;return s(a?.active_provider,[a?.model_settings?.selected_model_id||"",...(a?.model_settings?.available_models||[]).map(i=>i.model_id)]),a?.available_providers.forEach(i=>s(i)),e?.agentic_admin?.items.forEach(i=>{const r=t.get(i.model_provider_id)||new Set;i.model_id&&r.add(i.model_id),t.set(i.model_provider_id,r)}),Array.from(t,([i,r])=>({provider_id:i,model_ids:Array.from(r).sort((o,c)=>o.localeCompare(c))})).sort((i,r)=>i.provider_id.localeCompare(r.provider_id))}function We(e){return Number.isFinite(e)?e:0}function St(e,t){return typeof e=="string"?e.trim():t}function qn(e,t,s=Date.now()){const n=t.providerUsageItems.find(r=>r.provider_id===e);if(!n)return t.isLoadingProviderUsage?"Loading usage…":t.providerUsageError?"Usage unavailable":"Usage limit not reported";if(!n.available)return"Usage unavailable";const a=n.limits.map(r=>({limit:r,windows:[r.primary_window,r.secondary_window].filter(o=>o!==null)})).filter(({windows:r})=>r.length>0);if(!a.length)return"Usage limit not reported";const i=a.length>1;return a.map(({limit:r,windows:o})=>`${i?`${r.label} — `:""}${o.map(l=>Dn(l,s)).join("; ")}`).join(" · ")}function Dn(e,t){const s=Math.min(100,Math.max(0,e.used_percent)),n=Math.max(0,100-s),a=Tn(e,t);return`${Rn(e.limit_window_seconds)}: ${Et(s)} used · ${Et(n)} remaining before limit${a?` · ${a}`:""}`}function Et(e){return`${Number.isInteger(e)?e.toFixed(0):e.toFixed(1)}%`}function Rn(e){return!e||e<=0?"Rolling window":e%604800===0?`${e/604800}w window`:e%86400===0?`${e/86400}d window`:e%3600===0?`${e/3600}h window`:e%60===0?`${e/60}m window`:"Rolling window"}function Tn(e,t){let s=null;return e.reset_at_epoch_seconds!==null?s=Math.max(0,Math.ceil(e.reset_at_epoch_seconds-t/1e3)):s=e.reset_after_seconds,s===null?"":`resets ${Ln(s)}`}function Ln(e){if(e<=0)return"now";const t=Math.max(1,Math.ceil(e/60)),s=Math.floor(t/1440),n=Math.floor(t%1440/60),a=t%60;return s>0?`in ${s}d${n>0?` ${n}h`:""}`:n>0?`in ${n}h${a>0?` ${a}m`:""}`:`in ${a}m`}function Hn(e){const t=e.isLoadingUsageHistory?"sync":"refresh",s=ss(e.usageHistoryFilters.timeRange),n=s.resolution==="hour"?"Hourly consumption":"Daily consumption";return`<section class="settings-card settings-platform settings-usage-history-card" aria-labelledby="settings-usage-history-title">
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
  </section>`}function Un(e){return`<section class="settings-card"><div class="settings-heading"><h2>Provider subscriptions</h2></div>
    ${e.providerUsageError?`<p role="alert">${d(e.providerUsageError)}</p>`:""}
    ${e.isLoadingProviderUsage?'<p role="status">Loading subscription usage…</p>':""}
    ${e.providerUsageItems.map(t=>`<article class="settings-subscription-row"><strong>${d(t.provider_id)}</strong><p>${d(qn(t.provider_id,e))}</p></article>`).join("")}
    ${!e.isLoadingProviderUsage&&!e.providerUsageItems.length&&!e.providerUsageError?"<p>No subscription limits reported.</p>":""}
  </section>${Hn(e)}`}const _e=e=>["rejected","undone","undoing"].includes(e.status)?e.status:e.implementation?.status||e.status,On=[{id:"proposed",label:"Proposed",states:["pending"],hint:"Accept to start a Chat agent"},{id:"queued",label:"Queued",states:["accepted","queued","launching"],hint:"Starts when an agent slot is available"},{id:"running",label:"In progress",states:["running","stopping"],hint:"Follow the agent in Chat"},{id:"review",label:"To verify",states:["awaiting_review"],hint:"Check the result before completing"},{id:"attention",label:"Needs attention",states:["failed","cancelled"],hint:"Inspect the chat and retry when ready"},{id:"done",label:"Done",states:["implemented"],hint:"Implementation confirmed"},{id:"closed",label:"Dismissed",states:["rejected"],hint:"Proposals you chose to dismiss"}],Nn=[{id:"proposed",label:"Proposed",states:["pending","checking"],hint:"Accept to start a Memory agent"},{id:"queued",label:"Queued",states:["accepted","queued","launching"],hint:"One Memory chat at a time"},{id:"running",label:"In progress",states:["running","saving","stopping","undoing"],hint:"Verifies sources and saves the approved fact"},{id:"attention",label:"Needs attention",states:["failed","cancelled"],hint:"Read the chat before retrying"},{id:"done",label:"Saved",states:["saved"],hint:"Confirmed by the Memory provider"},{id:"undone",label:"Undone",states:["undone"],hint:"Saves you chose to undo"},{id:"closed",label:"Dismissed",states:["rejected"],hint:"Facts you chose to dismiss"}],Bn={pending:"Proposed",checking:"Checking Memory",saving:"Saving",saved:"Saved",undoing:"Undoing",undone:"Undone",accepted:"Accepted · not started",queued:"Queued",launching:"Starting chat",running:"In progress",stopping:"Stopping",awaiting_review:"To verify",failed:"Failed",cancelled:"Stopped",implemented:"Done",rejected:"Dismissed"},nt=e=>["implemented","rejected","saved","undone"].includes(_e(e));function jn(e){const t=_e(e);return t==="pending"?[[e.kind==="memory"?"approve":"accept",e.kind==="memory"?"Accept & save":"Accept & start"],["reject","Dismiss"]]:t==="saved"?e.details.node_created?[["undo","Undo save"]]:[]:t==="accepted"?[["start","Start implementation"],["reject","Dismiss"]]:["queued","launching","running"].includes(t)?[["stop",t==="queued"?"Remove from queue":"Stop implementation"]]:t==="awaiting_review"?[["implemented","Confirm implemented"],["retry","Continue fixing"]]:["failed","cancelled"].includes(t)?[["retry","Retry in same chat"],["reject","Dismiss"]]:[]}function Fn(e,t){const s=_e(e);if(t==="queued")return s==="pending"?e.kind==="memory"?"approve":"accept":s==="accepted"?"start":["failed","cancelled","awaiting_review"].includes(s)?"retry":void 0;if(t==="done"&&s==="awaiting_review")return"implemented";if(t==="closed"&&["pending","accepted","failed","cancelled"].includes(s))return"reject"}function It(e,t,s=!0){const n=_e(e),a=jn(e),i=(l,p)=>`<button class="settings-secondary ${l==="accept"?"ticket-primary":""}" data-learning-item="${d(e.id)}" data-learning-command="${l}" ${t?"disabled":""}>${p}</button>`,r=[...new Set(e.evidence.map(l=>l.session_id))],o=e.details.memory_matches||[],c=`${s?`<p>${d(e.body)}</p>`:""}<dl class="learning-proposal-details">${["generalization","expected_impact","verification"].filter(l=>e.details[l]).map(l=>`<dt>${{generalization:"Why this helps other tasks",verification:"Verification",expected_impact:"Expected impact"}[l]}</dt><dd>${d(e.details[l])}</dd>`).join("")}</dl>
    ${e.evidence.map(l=>`<blockquote><p>${d(l.quote)}</p><small>${d(l.role)} · ${d(l.turn_id)} · <a href="/app/chat/threads/${encodeURIComponent(l.session_id)}">Source chat</a></small></blockquote>`).join("")}
    ${e.implementation?.summary?`<details data-learning-disclosure="${d(e.id)}-summary"><summary>Agent result</summary><p class="ticket-summary">${d(e.implementation.summary)}</p></details>`:""}
    ${e.status==="pending"?`<details data-learning-disclosure="${d(e.id)}-edit"><summary>Edit proposal</summary><label>Title<input data-learning-title="${d(e.id)}" value="${d(e.title)}" maxlength="240"></label><label>Description<textarea data-learning-body="${d(e.id)}" rows="3" maxlength="4000">${d(e.body)}</textarea></label>${i("edit","Save edit")}</details>`:""}`;return`<article class="learning-ticket ${s?"":"ticket-list-row"}" data-ticket-id="${d(e.id)}" data-ticket-state="${d(n)}">
    <div class="ticket-top"><span>${d(e.details.category||"Improvement")}</span>${a.length?`<button class="ticket-grip" draggable="${!t}" data-learning-drag="${d(e.id)}" aria-label="Move ${d(e.title)} between columns" title="Drag to Queued, Done or Dismissed; actions below also work with keyboard" ${t?"disabled":""}><span class="material-symbols-rounded" aria-hidden="true">drag_indicator</span></button>`:""}</div>
    <h4>${d(e.title)}</h4><p class="ticket-description">${d(e.body)}</p>
    <div class="ticket-meta"><span>${d(Bn[n]||n)}</span>${e.details.effort?`<span>${d(e.details.effort)} effort</span>`:""}<span>${r.length} source chat${r.length===1?"":"s"}${e.occurrences>1?` · ${e.occurrences} observations`:""}</span></div>
    ${e.implementation?.error?`<p class="learning-error" role="status">${d(e.implementation.error)}</p>`:""}
    ${e.details.review_stale&&!nt(e)?'<p class="ticket-note">The source chat changed. Accepted tickets wait for reassessment before an agent starts.</p>':""}
    ${e.details.review_reason?`<p class="ticket-note">${d(e.details.review_reason)}</p>`:""}
    ${n==="awaiting_review"?'<p class="ticket-note">The agent finished its turn. Review the changes and checks in Chat.</p>':""}
    ${n==="pending"&&e.kind==="memory"&&o.length?`<label>Memory destination<select data-learning-target="${d(e.id)}" aria-label="Memory destination"><option value="">Choose destination</option>${o.map(l=>`<option value="${d(l.id)}">Attach to ${d(l.title)}</option>`).join("")}<option value="new">Create separate fact</option></select></label>`:""}
    ${e.details.memory_check_error||e.details.save_error?`<p class="learning-error">${d(e.details.save_error||e.details.memory_check_error)}</p>`:""}
    <div class="learning-actions">${e.kind==="memory"&&e.status==="saved"?`<a class="settings-secondary" href="/app/${encodeURIComponent(e.provider_id||"memory")}/nodes/${encodeURIComponent(e.node_id)}">Open Memory</a>`:""}${e.implementation?.session_id?`<a class="settings-secondary" href="/app/chat/threads/${encodeURIComponent(e.implementation.session_id)}">Open work chat <span aria-hidden="true">↗</span></a>`:""}${a.slice(0,1).map(([l,p])=>i(l,p)).join("")}</div>
    <details class="ticket-details" data-learning-disclosure="${d(e.id)}-ticket"><summary>Details &amp; evidence</summary>${c}${a.slice(1).map(([l,p])=>i(l,p)).join("")}</details>
  </article>`}function zn(e){const t=e.tab==="memory",s=t?"memory":"improvement",n=e.data.items.filter(u=>u.kind===s),a=e.ticketFilter||"open",i=e.ticketView||"board",r=(e.ticketSearch||"").trim().toLocaleLowerCase(),o=[...new Set(n.map(u=>u.details.category).filter(Boolean))].sort(),c=n.filter(u=>(a==="all"||(a==="closed"?nt(u):!nt(u)))&&(!e.ticketCategory||u.details.category===e.ticketCategory)&&(!r||`${u.title} ${u.body}`.toLocaleLowerCase().includes(r))),l=(t?Nn:On).filter(u=>a==="all"||(a==="closed"?["done","closed","undone"].includes(u.id):!["done","closed","undone"].includes(u.id))),p=e.data.projects?.[s];return`${e.error?`<p class="learning-error" role="alert">${d(e.error)}</p>`:""}${e.notice?`<p class="ticket-queue-note" role="status" aria-live="polite">${d(e.notice)}</p>`:""}<div class="ticket-toolbar"><div class="ticket-toolbar-title"><strong>${t?"Memory":"Improvement"} tickets <span>${n.length}</span></strong><small>${t?"Accept a fact to start a Chat agent that verifies its sources and saves it to Memory.":"Accept a proposal to start a Chat agent with its source context."}${p?` <a href="/app/chat/projects/${encodeURIComponent(p)}">Open ${t?"Memory":"Improvements"} project ↗</a>`:""}</small></div>
    <div class="ticket-toolbar-controls"><div class="ticket-segment" role="group" aria-label="Ticket status filter">${["open","all","closed"].map(u=>`<button data-ticket-filter="${u}" aria-pressed="${a===u}">${{open:"Open",all:"All",closed:"Closed"}[u]}</button>`).join("")}</div>
    <div class="ticket-segment" role="group" aria-label="Ticket view">${["board","list"].map(u=>`<button data-ticket-view="${u}" aria-pressed="${i===u}" aria-label="${u==="board"?"Kanban board":"Ticket list"}"><span class="material-symbols-rounded" aria-hidden="true">${u==="board"?"view_kanban":"view_list"}</span></button>`).join("")}</div></div>
    <input id="ticket-search" data-settings-controlled type="search" aria-label="Search improvement tickets" placeholder="Search tickets…" value="${d(e.ticketSearch||"")}"><select id="ticket-category" data-settings-controlled aria-label="Ticket category"><option value="">All categories</option>${o.map(u=>`<option value="${d(u)}" ${u===e.ticketCategory?"selected":""}>${d(u)}</option>`).join("")}</select></div>
    <p class="ticket-queue-note">${t?"One Memory work chat runs at a time. Saved means the provider confirmed the write.":`Up to ${e.data.settings.improvement_concurrency??4} improvement chats run in parallel. Configure the limit in Usage & retention.`} Accepted tickets use normal Chat usage; analysis pause and allowance apply to analysis.${e.data.items.length>=200?" Showing the first 200 learning results.":""}</p>
    ${e.data.runtime_ready===!1?'<p class="learning-notice" role="status">Work chats are waiting for the backend update. Accepted tickets stay queued until launching is available.</p>':""}
    ${i==="board"?`<div class="learning-kanban" role="region" aria-label="Improvement ticket board" tabindex="0">${l.map(u=>{const m=c.filter(w=>u.states.includes(_e(w)));return`<section class="ticket-column" data-ticket-column="${u.id}" aria-label="${u.label}"><header><h4><i aria-hidden="true"></i>${u.label}<span>${m.length}</span></h4><small>${u.hint}</small></header><div class="ticket-dropzone">${m.map(w=>It(w,e.saving)).join("")||'<div class="ticket-column-empty">No tickets</div>'}</div></section>`}).join("")}</div>`:`<div class="learning-list">${c.map(u=>It(u,e.saving,!1)).join("")||'<div class="learning-empty"><strong>No matching tickets</strong><p>Change the filters or wait for new proposals.</p></div>'}</div>`}`}function Wn(e,t,s){document.querySelectorAll("[data-ticket-filter]").forEach(a=>f(a,"click",()=>s({ticketFilter:a.dataset.ticketFilter}))),document.querySelectorAll("[data-ticket-view]").forEach(a=>f(a,"click",()=>s({ticketView:a.dataset.ticketView}))),f(document.querySelector("#ticket-search"),"input",a=>s({ticketSearch:a.target.value})),f(document.querySelector("#ticket-category"),"change",a=>s({ticketCategory:a.target.value}));let n="";document.querySelectorAll("[data-learning-drag]").forEach(a=>{f(a,"dragstart",i=>{if(e.saving){i.preventDefault();return}n=a.dataset.learningDrag,i.dataTransfer?.setData("text/plain",n),i.dataTransfer&&(i.dataTransfer.effectAllowed="move")}),f(a,"dragend",()=>{n="",document.querySelectorAll(".ticket-column.is-over").forEach(i=>i.classList.remove("is-over"))})}),document.querySelectorAll("[data-ticket-column]").forEach(a=>{const i=()=>{const r=e.data?.items.find(o=>o.id===n);return r&&Fn(r,a.dataset.ticketColumn)};f(a,"dragover",r=>{!e.saving&&i()&&(r.preventDefault(),a.classList.add("is-over"))}),f(a,"dragleave",r=>{a.contains(r.relatedTarget)||a.classList.remove("is-over")}),f(a,"drop",r=>{r.preventDefault();const o=i();a.classList.remove("is-over"),o&&!e.saving&&t(n,o),n=""})})}function Vn(e){let t={data:null,error:"",loading:!1,saving:!1,tab:"memory",detail:null,dependency:null,dirty:!1},s="",n=0,a=0,i=0,r=null,o=!1,c=!1;const l=new Map,p=new Map,u=new Map,m=P=>q("/api/apps/chat/backend",{method:"POST",body:JSON.stringify(P)});function w(){r?.(),r=null}function g(){const P=document.querySelector(".learning-kanban")?.scrollLeft||0,S=document.activeElement,v=S?.id?`#${S.id}`:S?.getAttribute("name")?`[name="${S.getAttribute("name")}"]`:["data-learning-title","data-learning-body","data-learning-target"].map(Q=>S?.hasAttribute(Q)?`[${Q}="${S.getAttribute(Q)}"]`:"").find(Boolean),h=S instanceof HTMLTextAreaElement||S instanceof HTMLInputElement?[S.selectionStart,S.selectionEnd]:null,_=new Set(t.openSections);document.querySelectorAll("[data-learning-disclosure]").forEach(Q=>{Q.open?_.add(Q.dataset.learningDisclosure):_.delete(Q.dataset.learningDisclosure)}),t.openSections=[..._],e.render();const I=document.querySelector(".learning-kanban");I&&(I.scrollLeft=P);const O=v?document.querySelector(v):null;O?.focus({preventScroll:!0}),h?.[0]!=null&&(O instanceof HTMLTextAreaElement||O instanceof HTMLInputElement&&["text","search"].includes(O.type))&&O.setSelectionRange(h[0],h[1])}function T(){n++,s="",c=!1,l.clear(),p.clear(),u.clear(),w(),t={data:null,error:"",loading:!1,saving:!1,tab:"memory",detail:null,dependency:null,dirty:!1}}function k(){if(!o||r)return;const P=n,S=()=>{P===n&&(c=!0,t.saving||b(!0))};r=Ks(v=>{v.workspace_id===s&&v.owner_app_id==="chat"&&v.resource==="learning"&&S()},S)}async function b(P=!1){const S=e.workspaceId();if(!S||(s!==S&&(T(),s=S),t.loading||!P&&t.data))return;const v=n,h=++a;c=!1,t.loading=!0,t.data||g();try{const[_,I]=await Promise.all([m({action:"learning.read"}),pt("chat")]);if(v!==n||h!==a||S!==e.workspaceId())return;t.data=_,t.dependency=I,t.error=""}catch(_){v===n&&h===a&&(t.error=Ve(_))}finally{v===n&&h===a&&(t.loading=!1,g(),c&&!t.saving&&o&&b(!0))}}async function D(P,S){if(t.saving)return;const v=n;a++,t.loading=!1,t.saving=!0,t.error="",t.notice="",g();try{if(S&&await S(),v!==n||(await m(P),v!==n))return;const h=P;if(h.action==="learning.configure"&&h.settings&&"enabled"in h.settings&&(l.clear(),B("#learning-settings")),t.notice=h.action==="learning.configure"?"Settings saved":["accept","approve","start","retry"].includes(h.command||"")?"Ticket queued. Its work chat appears when the agent starts.":h.command==="implemented"?"Implementation confirmed.":h.command==="stop"?"Stop requested. This chat keeps its slot until the turn ends.":"Action completed",h.item_id){const _=h.item_id;for(const I of p.keys())I.endsWith(":"+_)&&p.delete(I);B(["data-learning-title","data-learning-body","data-learning-target"].map(I=>`[${I}="${CSS.escape(_)}"]`).join(", "))}t.dirty=l.size>0||p.size>0,await b(!0)}catch(h){v===n&&(t.error=Ve(h))}finally{v===n&&(t.saving=!1,g(),c&&o&&b(!0))}}async function $(P){const S=new FormData(P),v={};v.paused=t.data.settings.paused;for(const I of["enabled","memory_enabled","improvements_enabled"])v[I]=S.get(I)==="on";for(const I of["idle_seconds","max_context_chars","max_output_tokens","timeout_seconds","daily_token_budget","retention_days"])v[I]=Number(S.get(I));S.has("improvement_concurrency")&&(v.improvement_concurrency=Number(S.get("improvement_concurrency")));for(const I of["memory_mode","model_source","model_id","reasoning_effort","instructions"])v[I]=String(S.get(I)||"");for(const I of["excluded_thread_ids","excluded_project_ids"])v[I]=String(S.get(I)||"").split(/[\s,]+/).filter(Boolean);const h=String(S.get("memory_provider")||""),_=t.dependency?.dependencies.find(I=>I.alias==="learning-memory")?.selected_provider_app_ids[0]||"";await D({action:"learning.configure",settings:v},h!==_?()=>Xt("chat","learning-memory",h?[h]:[]):void 0)}function A(){const P=(v,h)=>{const _=document.querySelector(`[data-learning-target="${v}"]`)?.value||"",I=document.querySelector(`[data-learning-title="${v}"]`)?.value,O=document.querySelector(`[data-learning-body="${v}"]`)?.value;D({action:"learning.review",item_id:v,command:h,target_node_id:_==="new"?"":_,confirm_new:_==="new",title:I,body:O})};Wn(t,P,v=>{Object.assign(t,v),g()});const S=document.querySelector("#learning-settings");if(S){for(const h of S.elements){if(!(h instanceof HTMLInputElement||h instanceof HTMLSelectElement||h instanceof HTMLTextAreaElement)||!h.name||!l.has(h.name))continue;const _=l.get(h.name);h instanceof HTMLInputElement&&h.type==="checkbox"?h.checked=_===!0:h.value=String(_)}const v=()=>{t.dirty=!0;for(const h of S.elements)(h instanceof HTMLInputElement||h instanceof HTMLSelectElement||h instanceof HTMLTextAreaElement)&&h.name&&l.set(h.name,h instanceof HTMLInputElement&&h.type==="checkbox"?h.checked:h.value);U()};f(S,"input",v),f(S,"change",v),U()}f(S,"submit",v=>{v.preventDefault(),$(S)}),f(document.querySelector("#learning-refresh"),"click",()=>{b(!0)}),f(document.querySelector("#learning-discard"),"click",()=>{t.dirty=!1,l.clear(),p.clear(),t.notice="",B("#learning-settings, .learning-results"),g()}),f(document.querySelector("#learning-pause"),"click",()=>{D({action:"learning.configure",settings:{paused:!t.data.settings.paused}})}),f(document.querySelector("#learning-session"),"change",v=>{t.selectedSession=v.target.value,g()}),document.querySelectorAll("[data-learning-disclosure]").forEach(v=>{v.open=!!t.openSections?.includes(v.dataset.learningDisclosure),f(v,"toggle",()=>{if(!v.isConnected)return;const h=new Set(t.openSections);v.open?h.add(v.dataset.learningDisclosure):h.delete(v.dataset.learningDisclosure),t.openSections=[...h]})}),f(document.querySelector("#learning-analyze"),"click",()=>{const v=document.querySelector("#learning-session")?.value;v&&D({action:"learning.analyze_now",session_id:v})});for(const v of["data-learning-title","data-learning-body","data-learning-target"])document.querySelectorAll(`[${v}]`).forEach(h=>{const _=v+":"+h.getAttribute(v);p.has(_)&&(h.value=p.get(_)),f(h,"input",()=>{p.set(_,h.value),t.dirty=!0,U()})});document.querySelectorAll('.learning-results a[href^="/app/"]').forEach(v=>f(v,"click",h=>{if(window.parent===window||h.ctrlKey||h.metaKey)return;h.preventDefault();const _=new URL(v.href).pathname.split("/").filter(Boolean),I=window.__MAVERICK_PLATFORM_ORIGIN__||"*";window.parent.postMessage({type:"maverick.app.open-app",app_id:decodeURIComponent(_[1]),params:{app_page:_.slice(2).map(decodeURIComponent).join("/")}},I)})),document.querySelectorAll("[data-learning-tab]").forEach(v=>f(v,"click",()=>{u.set(t.tab,{ticketView:t.ticketView,ticketFilter:t.ticketFilter,ticketSearch:t.ticketSearch,ticketCategory:t.ticketCategory}),i++,t.tab=v.dataset.learningTab,t.detail=null,Object.assign(t,{ticketView:void 0,ticketFilter:void 0,ticketSearch:void 0,ticketCategory:void 0},u.get(t.tab)),g()})),document.querySelectorAll("[data-learning-tab]").forEach((v,h,_)=>f(v,"keydown",I=>{const O={ArrowRight:(h+1)%_.length,ArrowLeft:(h+_.length-1)%_.length,Home:0,End:_.length-1}[I.key];O!==void 0&&(I.preventDefault(),_[O].click(),document.querySelector(`#${_[O].id}`)?.focus())})),document.querySelectorAll("[data-learning-job]").forEach(v=>f(v,"click",async()=>{const h=v.dataset.learningJob,_=v.dataset.learningCommand;if(_!=="inspect"){await D({action:"learning.job",job_id:h,command:_});return}const I=n,O=++i;try{const Q=await m({action:"learning.job",job_id:h,command:_});I===n&&O===i&&(t.detail=Q.job,g())}catch(Q){I===n&&O===i&&(t.error=Ve(Q),g())}})),document.querySelectorAll("[data-learning-item]").forEach(v=>f(v,"click",()=>{const h=v.dataset.learningItem;P(h,v.dataset.learningCommand)}))}function F(P){if(o=P,!P){w();return}s&&k(),c&&!t.saving&&b(!0)}function U(){const P=document.querySelector("#learning-draft-status");P&&(P.textContent=t.dirty?"Unsaved changes":t.notice||"Settings are up to date");const S=document.querySelector("#learning-discard");S&&(S.disabled=!t.dirty||t.saving);const v=document.querySelector("[name=memory_enabled]"),h=document.querySelector("#learning-memory-options");h&&v&&(h.hidden=!v.checked);const _=document.querySelector("[name=model_source]")?.value;document.querySelectorAll("[data-learning-native]").forEach(O=>{O.hidden=_!=="workspace"});const I=document.querySelector("#learning-mode-hint");I&&(I.textContent=document.querySelector("[name=memory_mode]")?.value==="automatic"?"Only explicit user facts with verified quotes and no Memory matches are saved automatically.":"You approve each fact before it enters Memory.")}function z(){const P={};for(const[S,v]of l){if(S==="memory_provider"||!t.data)continue;const h=t.data.settings[S];P[S]=typeof h=="number"?Number(v):Array.isArray(h)?String(v).split(/[\s,]+/).filter(Boolean):v}return{...t,draftSettings:P}}return{load:b,reset:T,bind:A,setVisible:F,viewState:z}}function Ve(e){return e instanceof Error?e.message:"Learning operation failed"}function Jn(e,t){const s={...e.data.settings,...e.draftSettings},n=e.saving?"disabled":"",a=e.dependency?.dependencies.find(c=>c.alias==="learning-memory"),i=a?.selected_provider_app_ids[0]||"",r=(c,l,p,u)=>`<label class="learning-toggle ${u?"learning-channel":""}">
    ${u?`<span class="material-symbols-rounded learning-channel-icon" aria-hidden="true">${u}</span>`:""}
    <span class="learning-toggle-copy"><strong>${l}</strong><small>${p}</small></span>
    <input type="checkbox" role="switch" name="${c}" ${s[c]?"checked":""} ${n}><span class="learning-toggle-track" aria-hidden="true"></span></label>`,o=(c,l,p,u,m)=>`<label>${l}<input type="number" name="${c}" min="${p}" max="${u}" value="${s[c]}" required ${n}><small>${m}</small></label>`;return`<form id="learning-settings" class="settings-card learning-controls" aria-busy="${e.saving}">
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
        ${o("idle_seconds","Quiet period (seconds)",0,3600,"Delay before review. New messages postpone it; this delay does not certify that work is finished.")}
        <label>Analysis model<select name="model_source" ${n}><option value="workspace" ${s.model_source==="workspace"?"selected":""}>Workspace Codex</option><option value="fast_model" ${s.model_source==="fast_model"?"selected":""}>Configured fast API model</option></select><small>API mode uses the fast model configured in platform settings.</small></label>
        <label data-learning-native ${s.model_source==="workspace"?"":"hidden"}>Codex model<select name="model_id" ${n}><option value="">Workspace default</option>${t.map(c=>`<option value="${d(c.model_id)}" ${c.model_id===s.model_id?"selected":""}>${d(c.label||c.model_id)}</option>`).join("")}${s.model_id&&!t.some(c=>c.model_id===s.model_id)?`<option selected value="${d(s.model_id)}">${d(s.model_id)} (unavailable)</option>`:""}</select></label>
        <label data-learning-native ${s.model_source==="workspace"?"":"hidden"}>Reasoning<select name="reasoning_effort" ${n}>${["low","medium","high"].map(c=>`<option value="${c}" ${s.reasoning_effort===c?"selected":""}>${{low:"Low · faster",medium:"Medium",high:"High · more thorough"}[c]}</option>`).join("")}</select></label>
      </div>
    </details>
    <details class="learning-advanced" data-learning-disclosure="limits" ${e.openSections?.includes("limits")?"open":""}>
      <summary><span><strong>Usage &amp; retention</strong><small>${s.daily_token_budget.toLocaleString()} tokens per day · ${s.retention_days} days of transcripts</small></span><span class="material-symbols-rounded" aria-hidden="true">expand_more</span></summary>
      <div class="learning-form-grid">
        ${o("daily_token_budget","Daily token allowance",1e3,1e7,"UTC day. Each analysis reserves tokens before it starts.")}
        ${o("max_context_chars","Context limit (characters)",4e3,6e4,"Maximum conversation evidence per analysis.")}
        ${o("max_output_tokens","Output limit (tokens)",128,8192,"Maximum size of the generated suggestions.")}
        ${o("timeout_seconds","Timeout (seconds)",10,300,"Stop an analysis if it takes too long.")}
        ${o("retention_days","Transcript retention (days)",1,365,"Saved Memory facts and review decisions remain available.")}
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
  </form>`}const Gn=e=>({pending:"To review",checking:"Checking Memory",saving:"Saving",saved:"Saved",undoing:"Undoing",undone:"Undone",rejected:"Rejected",accepted:"Accepted",implemented:"Implemented",queued:"Waiting",running:"Analyzing",completed:"Completed",failed:"Failed",cancelled:"Cancelled"})[e]||e;function At(e){return d(new Date(e*1e3).toLocaleString())}function Kn(e,t=[]){const{data:s,error:n,saving:a}=e;if(!s)return`<section class="settings-card learning-empty"><strong>${e.loading?"Loading learning settings…":"Learning is unavailable"}</strong>${n?`<p role="alert">${d(n)}</p>`:""}<button class="settings-secondary" id="learning-refresh">Retry</button></section>`;const i=s.settings,r=s.counts||{pending_memory:s.items.filter(g=>g.kind==="memory"&&g.status==="pending").length,pending_improvements:s.items.filter(g=>g.kind==="improvement"&&g.status==="pending").length,queued:s.jobs.filter(g=>g.status==="queued").length,running:s.jobs.filter(g=>g.status==="running").length,failed:s.jobs.filter(g=>g.status==="failed").length,budget_waiting:0},o=i.enabled?i.paused?"Paused":!i.memory_enabled&&!i.improvements_enabled?"No outputs selected":r.running?"Analyzing":"On":"Off",c=i.enabled?i.paused?"Chats are still captured. Resume when you are ready.":!i.memory_enabled&&!i.improvements_enabled?"Choose Memory or Improvements to start analysis.":r.running?"One conversation is being reviewed. The others wait in the queue.":"Quiet periods trigger review. Only completed work can produce proposals.":"Enable learning to capture future conversations.",l=s.daily_tokens_reserved_or_used,p=Math.min(100,Math.round(l/i.daily_token_budget*100)),u=a?"disabled":"",m=g=>s.conversations.find(T=>T.session_id===g)?.label||`Chat ${g.slice(0,8)}`,w={memory:r.open_memory??r.pending_memory,improvements:r.open_improvement??r.pending_improvements,analyses:r.queued+r.running,audit:0};return`<section class="settings-card learning-overview">
    <div class="learning-status-row"><div class="learning-status-copy"><span class="learning-status-dot ${i.enabled&&!i.paused?"is-on":""}" aria-hidden="true"></span><div><h3>Learning is ${o.toLowerCase()}</h3><p>${c}</p></div></div><div class="learning-actions">${i.enabled?`<button id="learning-pause" class="settings-secondary" ${u}>${i.paused?"Resume analysis":"Pause analysis"}</button>`:""}<button id="learning-refresh" class="learning-icon-button" aria-label="Refresh learning status" ${u}><span class="material-symbols-rounded" aria-hidden="true">refresh</span></button></div></div>
    <div class="learning-stats"><div><strong>${r.pending_memory+r.pending_improvements}</strong><span>To review</span></div><div><strong>${r.queued}</strong><span>In queue</span></div><div class="learning-usage"><div><span>Today’s token allowance</span><strong>${p}%</strong></div><progress value="${Math.min(l,i.daily_token_budget)}" max="${i.daily_token_budget}" aria-label="Daily learning token allowance"></progress><small>${l.toLocaleString()} / ${i.daily_token_budget.toLocaleString()} reserved or observed · resets at 00:00 UTC</small></div></div>
    ${l>=i.daily_token_budget?'<p class="learning-notice">Today’s allowance is reached. New analyses wait until the next UTC day or a higher saved allowance.</p>':""}
    ${r.budget_waiting&&l<i.daily_token_budget?'<p class="learning-notice">The remaining allowance cannot cover the next analysis. Increase it in Usage &amp; retention or wait for the UTC reset. Codex reserves extra tokens for its instructions.</p>':""}
    ${r.failed?`<p class="learning-notice">${r.failed} failed ${r.failed===1?"analysis":"analyses"}. Open the Analyses tab to inspect or retry.</p>`:""}
    ${n?`<p class="learning-error" role="alert">${d(n)}</p>`:""}
  </section>
  ${Jn(e,t)}
  <section class="settings-card learning-results">
    <div class="learning-section-heading"><div><h3>Results &amp; history</h3><p>Review suggestions and see what the agent has done.</p></div></div>
    <div class="learning-manual"><label for="learning-session">Analyze a captured chat</label><div class="learning-actions"><select id="learning-session" data-settings-controlled ${!s.conversations.length||a?"disabled":""}><option value="">${s.conversations.length?"Choose a conversation…":"No captured conversations yet"}</option>${s.conversations.map(g=>`<option value="${d(g.session_id)}" ${e.selectedSession===g.session_id?"selected":""}>${d(m(g.session_id))}</option>`).join("")}</select><button id="learning-analyze" class="settings-secondary" ${a||!i.enabled||i.paused||!e.selectedSession||!i.memory_enabled&&!i.improvements_enabled?"disabled":""}>Analyze now</button></div><p class="learning-note">${i.enabled?i.paused?"Resume analysis to use the queue.":"Adds new captured messages to the same serial queue; active chats wait until ready.":"Enable learning first. Only conversations captured after activation are available."}</p></div>
    <div class="learning-tabs" role="tablist" aria-label="Learning results">${["memory","improvements","analyses","audit"].map(g=>`<button id="learning-tab-${g}" role="tab" aria-controls="learning-panel" aria-selected="${e.tab===g}" tabindex="${e.tab===g?"0":"-1"}" class="${e.tab===g?"is-active":""}" data-learning-tab="${g}">${{memory:"Memory",improvements:"Improvements",analyses:"Analyses",audit:"Activity"}[g]}${w[g]?`<span>${w[g]}</span>`:""}</button>`).join("")}</div>
    <div id="learning-panel" role="tabpanel" aria-labelledby="learning-tab-${e.tab}" tabindex="0">
    ${e.tab==="improvements"||e.tab==="memory"?zn(e):""}
    ${e.tab==="analyses"?`<div class="learning-list">${s.jobs.map(g=>`<article class="learning-row"><div><div class="learning-item-heading"><strong>${d(m(g.session_id))}</strong><span class="settings-pill">${d(Gn(g.status))}</span></div><p>${At(g.created_at)} · ${g.attempts} attempt(s) · ${g.usage||g.reserved} tokens${g.model?` · ${d(g.model)}`:""}</p>${g.error?`<p class="learning-error">${d(g.error)}</p>`:""}</div><div class="learning-actions"><button class="settings-secondary" data-learning-job="${d(g.id)}" data-learning-command="inspect">Details</button>${["queued","running"].includes(g.status)?`<button class="settings-secondary" data-learning-job="${d(g.id)}" data-learning-command="cancel" ${u}>Cancel</button>`:["failed","cancelled"].includes(g.status)?`<button class="settings-secondary" data-learning-job="${d(g.id)}" data-learning-command="retry" ${u}>Retry</button>`:""}</div></article>`).join("")||'<div class="learning-empty"><strong>No analyses yet</strong><p>After activation, finish a chat and wait for the quiet period. Its analysis will appear here.</p></div>'}</div>`:""}
    ${e.tab==="audit"?`<div class="learning-list">${s.audit.map(g=>`<div class="learning-row"><span>${d(g.action.replaceAll("."," · ").replaceAll("_"," "))}</span><small>${At(g.created_at)} · ${d(g.actor)}</small></div>`).join("")||'<div class="learning-empty"><strong>No activity yet</strong><p>Settings changes and review decisions will appear here.</p></div>'}</div>`:""}
    ${e.detail?`<details class="learning-transcript" open><summary>Analysis details · ${d(e.detail.id)}</summary><h4>Conversation evidence</h4><pre>${d(JSON.stringify(e.detail.input,null,2))}</pre><h4>Agent result</h4><pre>${d(e.detail.output_text||"No output available. The run may be pending or its transcript retention period has ended.")}</pre></details>`:""}
    </div>
  </section>`}let ns=!0;const at=()=>ns&&!document.hidden;function Qn(e){window.addEventListener("message",t=>{if(!ct(t)||!t.data||typeof t.data!="object")return;const s=t.data;(s.type==="maverick.shell.theme-changed"||s.type==="maverick.app.navigate"&&(!s.app_id||s.app_id==="settings"))&&Es(s.theme),s.type==="maverick.app.visibility-changed"&&s.app_id==="settings"&&(ns=s.visible===!0,e.visibilityChanged(at())),s.type==="maverick.app.navigate"&&(!s.app_id||s.app_id==="settings")&&e.navigate(s.params||{})}),document.addEventListener("visibilitychange",()=>e.visibilityChanged(at())),window.parent?.postMessage({type:"maverick.app.ready",app_id:"settings"},"*")}function Yn(e){return q("/api/admin/users",{method:"POST",body:JSON.stringify(e)})}function Xn(e,t){return q(`/api/admin/users/${encodeURIComponent(e)}`,{method:"PATCH",body:JSON.stringify(t)})}function Zn(e,t){return q(`/api/admin/users/${encodeURIComponent(e)}/password`,{method:"POST",body:JSON.stringify({password:t})})}function xn(e){return q(`/api/admin/users/${encodeURIComponent(e)}`,{method:"DELETE"})}function ea(e,t){return q(`/api/admin/users/${encodeURIComponent(e)}/workspaces`,{method:"PUT",body:JSON.stringify({memberships:t})})}function ta(e){return q(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"POST",body:JSON.stringify({source_id:e.source_id,enabled:!0})})}function sa(e,t){return q(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"PATCH",body:JSON.stringify({status:t?"enabled":"disabled"})})}function na(e){return q(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"DELETE",body:JSON.stringify({})})}function it(e,t){if(!t)return e;const s="items"in t?t.items:t.sessions,n="cleanup_allowed"in t?t.cleanup_allowed:e.runtime.cleanup_allowed,a="cleanup_scope"in t?t.cleanup_scope:e.runtime.cleanup_scope;return{...e,runtime:{...e.runtime,all_sessions:s||[],cleanup_allowed:n,cleanup_scope:a}}}function aa(e){const t=e?.provider.hosted_text?.active_provider||null,s=e?.provider.hosted_text?.model_settings||null;return ia(t,s)}function as(e){const t=e?.provider.hosted_text||null,s=t?.active_provider||null;return(t?.available_providers?.length?t.available_providers:s?[s]:[]).flatMap(a=>{const i=a.provider_id===s?.provider_id&&t?.model_settings||null;return ra(a,i).map(r=>({...r,hosted_text_profile:t?.profiles?.find(o=>o.profile.provider_id===a.provider_id&&o.profile.model_id===r.model_id)||null,metadata:{...r.metadata||{},hosted_provider_id:a.provider_id,hosted_provider_label:a.label||a.provider_id,hosted_provider_status:a.status}}))})}function ia(e,t){return{modelId:t?.selected_model_id||e?.default_model_family||""}}function ra(e,t){const s=t?.selected_model_id||e?.default_model_family||"",n=Je(t?.available_models).length?Je(t?.available_models):Je(e?.model_options);return(n.length?n:s?[la(s,t?.selected_reasoning_effort||"")]:[]).map(oa)}function Je(e){return(e||[]).filter(t=>t.model_id)}function oa(e){return e.supported_reasoning_efforts.length||!e.default_reasoning_effort?e:{...e,supported_reasoning_efforts:[{effort:e.default_reasoning_effort,label:e.default_reasoning_effort,description:null}]}}function la(e,t){return{model_id:e,label:e,description:null,default_reasoning_effort:t||null,supported_reasoning_efforts:t?[{effort:t,label:t,description:null}]:[]}}function da(){return{computerUse:bn(),savedDrafts:null,speechSynthesis:Zt(),activatingNativeProviders:new Set,nativeProviderErrors:{},agenticBindingErrors:{},cleanupError:"",clearingAllRuntime:!1,cleaningSessionIds:new Set,hostedDraftModelId:"",hostedProviderError:"",hostedProviderErrorModelId:"",hostedRoutingDraftsByModel:{},isSavingHostedProvider:!1,isSavingSpeechProvider:!1,isLoadingProviderUsage:!1,isLoadingUsageHistory:!1,savingAgenticBindings:new Set,pendingAgenticEnabled:{},providerUsageError:"",providerUsageItems:[],usageHistory:null,usageHistoryFilters:st(),usageHistoryError:"",speechAudioModelId:"",speechConversationModelId:"",speechProviderError:""}}function ie(e,t,s={}){t?.computer_use&&et(e.computerUse,t);const n=t?.workspace.workspace_id||"",a=e.savedDrafts?.workspaceId===n?e.savedDrafts:null,{modelId:i}=aa(t),r=ma(t),o=new Set([...as(t).map(l=>l.model_id),i,...Object.keys(a?e.hostedRoutingDraftsByModel:{})].filter(Boolean)),c=Object.fromEntries(Array.from(o).map(l=>[l,Ue(He(t,l))]));(!a||e.hostedDraftModelId===a.hostedModelId||s.hostedModelId)&&(e.hostedDraftModelId=i),(!a||e.speechAudioModelId===a.audioModelId||s.speech)&&(e.speechAudioModelId=r.audioModelId),(!a||e.speechConversationModelId===a.conversationModelId||s.speech)&&(e.speechConversationModelId=r.conversationModelId),e.hostedRoutingDraftsByModel=Object.fromEntries(Array.from(o).map(l=>{const p=e.hostedRoutingDraftsByModel[l],u=a&&p&&JSON.stringify(p)!==JSON.stringify(a.routing[l]);return[l,u&&s.hostedModelId!==l?p:c[l]]})),e.savedDrafts={workspaceId:n,hostedModelId:i,audioModelId:r.audioModelId,conversationModelId:r.conversationModelId,routing:Object.fromEntries(Object.entries(c).map(([l,p])=>[l,{...p}]))}}function ca(e,t,s){e.hostedDraftModelId=s,os(e,t,s),e.hostedProviderError="",e.hostedProviderErrorModelId=""}function pa(e,t){e.speechAudioModelId=t,e.speechProviderError=""}function ua(e,t){e.speechConversationModelId=t,e.speechProviderError=""}function ga(e,t,s,n,a){if(!s)return;const i=os(e,t,s);e.hostedDraftModelId=s,n==="mode"&&typeof a=="string"&&["auto","prefer","only","ignore"].includes(a)?i.mode=a:n==="provider_id"&&typeof a=="string"?i.providerId=a:n==="allow_fallbacks"&&typeof a=="boolean"?i.allowFallbacks=a:n==="require_parameters"&&typeof a=="boolean"?i.requireParameters=a:n==="zdr"&&typeof a=="boolean"?i.zdr=a:n==="sort"&&typeof a=="string"&&["","price","throughput","latency"].includes(a)?i.sort=a:n==="data_collection"&&typeof a=="string"&&["","allow","deny"].includes(a)?i.dataCollection=a:n==="quantization"&&typeof a=="string"&&(i.quantization=a),e.hostedProviderError="",e.hostedProviderErrorModelId=""}function is(e,t=e.hostedDraftModelId){const s=e.hostedRoutingDraftsByModel[t]||ha();return{mode:s.mode,provider_id:s.providerId||void 0,allow_fallbacks:s.allowFallbacks,require_parameters:s.requireParameters,zdr:s.zdr,sort:s.sort,data_collection:s.dataCollection,quantizations:s.quantization?[s.quantization]:[]}}function ma(e){const t=e?.provider.speech_stt||null,s=t?.active_provider||t?.available_providers?.find(i=>i.provider_id==="deepgram")||null,n=Me(t,s,"prerecorded_transcription"),a=Me(t,s,"conversational_streaming");return{audioModelId:t?.model_settings?.audio_transcription_model_id||n.find(i=>i.model_id==="nova-3")?.model_id||n[0]?.model_id||"nova-3",conversationModelId:t?.model_settings?.conversation_model_id||a.find(i=>i.model_id==="flux-general-multi")?.model_id||a[0]?.model_id||"flux-general-multi"}}function Me(e,t,s){const n=s==="prerecorded_transcription"?e?.model_settings?.available_audio_transcription_models:e?.model_settings?.available_conversation_models;return n?.length?n:(e?.model_settings?.available_models?.length?e.model_settings.available_models:t?.model_options||[]).filter(i=>i.metadata?.purpose===s)}function He(e,t){const s=e?.provider.hosted_text?.selection?.openrouter_provider_routing_by_model?.[t];return{mode:s?.mode||"auto",provider_id:s?.provider_id||"",allow_fallbacks:s?.allow_fallbacks!==!1,require_parameters:s?.require_parameters===!0,zdr:s?.zdr===!0,sort:s?.sort||"",data_collection:s?.data_collection||"",quantizations:s?.quantizations||[]}}function rs(e,t,s){const n=He(t,s),a=is(e,s);return n.mode!==a.mode||(n.provider_id||"")!==(a.provider_id||"")||n.allow_fallbacks!==!1!=(a.allow_fallbacks!==!1)||n.require_parameters===!0!=(a.require_parameters===!0)||n.zdr===!0!=(a.zdr===!0)||(n.sort||"")!==(a.sort||"")||(n.data_collection||"")!==(a.data_collection||"")||(n.quantizations?.[0]||"")!==(a.quantizations?.[0]||"")}function fa(e,t){return t.hostedProviderErrorModelId?t.hostedProviderErrorModelId:!t.hostedDraftModelId||!rs(t,e,t.hostedDraftModelId)?"":t.hostedDraftModelId}function va(e,t,s){return e.hostedRoutingDraftsByModel[s]||Ue(He(t,s))}function os(e,t,s){return e.hostedRoutingDraftsByModel[s]||(e.hostedRoutingDraftsByModel[s]=Ue(He(t,s))),e.hostedRoutingDraftsByModel[s]}function Ue(e){return{allowFallbacks:e.allow_fallbacks!==!1,dataCollection:e.data_collection||"",mode:e.mode||"auto",providerId:e.provider_id||"",quantization:e.quantizations?.[0]||"",requireParameters:e.require_parameters===!0,sort:e.sort||"",zdr:e.zdr===!0}}function ha(){return Ue({mode:"auto",allow_fallbacks:!0,require_parameters:!1,zdr:!1,sort:"",data_collection:"",quantizations:[]})}function ae(e,t,s=""){return`<label class="settings-toggle settings-bouncy-toggle ${s}">
    ${e}
    <span class="settings-bouncy-toggle__label">${t}</span>
    <span class="settings-bouncy-toggle__track" aria-hidden="true">
      <span class="settings-bouncy-toggle__inner"></span>
      <span class="settings-bouncy-toggle__thumb"><span class="settings-bouncy-toggle__dot"></span></span>
    </span>
  </label>`}function _a(e=document){e.querySelectorAll(".settings-bouncy-toggle").forEach(t=>{const s=n=>t.classList.toggle("is-pressed",n);f(t,"pointerdown",()=>s(!0)),f(t,"pointerup",()=>s(!1)),f(t,"pointerleave",()=>s(!1))})}const ba=[{family_id:"native_agent",label:"CLI models",description:"Models running through an installed CLI.",workspace_actions:!0},{family_id:"maverick_agent",label:"API models",description:"Models running through a provider API.",workspace_actions:!0}];function Ct(e,t){return t?.find(s=>s.family_id===e)||ba.find(s=>s.family_id===e)}function ls(e,t){return`<div class="settings-heading settings-platform-heading settings-model-card-heading">
    <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">${d(e)}</span>
      <div>
        <p class="settings-kicker">Models</p>
        <h2>${d(t)}</h2>
      </div>
    </div>`}function ya(e,t,s,n,a){const i=new Set(n.filter(b=>a&&b.runtime_engine_id!=="codex"&&b.unavailable_reason==="native_agent_disabled"&&b.models.length>0).map(b=>b.runtime_engine_id)),r=e?.items||[],o=r,c=e?.release_decision||"GO",l=Ct("native_agent",s||e?.execution_families),p=Ct("maverick_agent",s||e?.execution_families),u=o.filter(b=>b.execution_family==="native_agent"||!b.execution_family&&b.runtime_engine_id==="codex"),m=o.filter(b=>b.execution_family==="maverick_agent"),w=new Set(r.filter(b=>b.execution_family==="native_agent"||!b.execution_family&&b.runtime_engine_id==="codex").map(b=>b.runtime_engine_id)),g=n.filter(b=>!w.has(b.runtime_engine_id)),T=[...ka(u).map(b=>({html:qt(b,t),providerId:b.runtime_engine_id,canActivate:i.has(b.runtime_engine_id),providerLabel:Ee(b.runtime_engine_id)})),...g.map(b=>({html:Sa(b),providerId:b.runtime_engine_id,canActivate:i.has(b.runtime_engine_id),providerLabel:b.label||Ee(b.runtime_engine_id)}))],k=m.map(b=>({html:qt(b,t),providerId:b.model_provider_id,providerLabel:Ee(b.model_provider_id)}));return`<section class="settings-card settings-platform settings-agentic-runtimes-card">
    ${ls("account_tree","Models")}
    ${c==="NO-GO"?'<p class="settings-platform-error settings-agentic-no-go"><strong>Remote agentic release: NO-GO</strong><br>Remote profiles remain visible for containment review but cannot be enabled or selected.</p>':""}
    ${Mt(l,T,t,"No native-agent runtime is registered by this installation.")}
    ${Mt(p,k,t,"No complete Maverick Agent profile is currently available.")}
  </section>`}function Mt(e,t,s,n){const a=$a(t);return`<section class="settings-runtime-family" data-execution-family="${y(e.family_id)}">
    <header class="settings-runtime-family-heading">
      <h3>${d(e.label)}</h3>
    </header>
    <div class="settings-runtime-provider-list">
      ${a.length?a.map(i=>wa(i,s)).join(""):`<div class="settings-provider-usage-unavailable">
        <span class="material-symbols-rounded" aria-hidden="true">info</span>
        <span><strong>No available profiles</strong><small>${d(n)}</small></span>
      </div>`}
    </div>
  </section>`}function $a(e){const t=new Map;e.forEach(n=>{const a=t.get(n.providerId)||[];a.push(n),t.set(n.providerId,a)});const s=new Map([["codex",0],["antigravity-cli",1],["openrouter",2],["google-ai-studio",3]]);return Array.from(t.entries()).map(([n,a])=>({providerId:n,providerLabel:a[0]?.providerLabel||Ee(n),items:a})).sort((n,a)=>(s.get(n.providerId)??100)-(s.get(a.providerId)??100)||n.providerLabel.localeCompare(a.providerLabel))}function wa(e,t){const s=e.items.some(i=>i.canActivate),n=t.activatingNativeProviders.has(e.providerId),a=t.nativeProviderErrors[e.providerId];return`<section class="settings-runtime-provider" data-agentic-provider-group="${y(e.providerId)}">
    <header class="settings-runtime-provider-heading">
      <h4>${d(e.providerLabel)}</h4>

    </header>
    ${s?`<div class="settings-native-provider-activation">
      <span>Connection disabled. Enable it for this installation to use the selected models.</span>
      <button type="button" data-native-provider-activate="${y(e.providerId)}" ${n?"disabled":""}>
        ${n?"Enabling…":`Enable ${d(e.providerLabel)}`}
      </button>
    </div>`:""}
    ${a?`<p class="settings-platform-error" role="alert">${d(a)}</p>`:""}
    <div class="settings-agentic-runtime-list">${e.items.map(i=>i.html).join("")}</div>
  </section>`}function Ee(e){return{"antigravity-cli":"Antigravity",codex:"Codex","google-ai-studio":"Google AI Studio",openrouter:"OpenRouter"}[e]||he(e)}function ka(e){const t=new Map,s=[];return e.forEach(n=>{const a=n.runtime_engine_id==="antigravity-cli"?n.model_id.replace(/-(high|medium|low)$/i,""):n.model_id,i=`${n.runtime_engine_id}\0${a}`;t.has(i)||s.push(i);const r=t.get(i);(!r||Pt(n.model_id)>Pt(r.model_id))&&t.set(i,n)}),s.map(n=>t.get(n)).filter(n=>!!n)}function Pt(e){const t=e.match(/-(high|medium|low)$/i)?.[1]?.toLowerCase();return t==="high"?3:t==="medium"?2:t==="low"?1:0}function Sa(e){const t=e.models[0],s=e.unavailable_reason||"native_agent_unavailable",n=e.selectable===!0;return`<article class="settings-agentic-runtime settings-native-runtime-installation settings-agentic-runtime-static">
    <div class="settings-agentic-runtime-static__content">
      <span class="settings-model-summary-copy">
        <strong>${d(t?.model_id||e.label)}</strong>
        <small>${d(ds(t?.model_id,null))}</small>
      </span>
      <span class="settings-agentic-summary-badges">
        <span class="settings-pill ${n?"is-healthy":"is-warning"}">${n?"Available":d(he(s))}</span>
      </span>
    </div>
  </article>`}function qt(e,t){const s=e.definition_id,n=e.binding,a=n?.workspace_policy_ceiling||e.profile_policy_ceiling,i=n?.actor_policy||{allow_workspace_admins:!0,allowed_workspace_role_ids:["admin","member"]},r=e.execution_family==="maverick_agent",o=e.effective_capabilities,c=e.containment_status==="NO-GO",l=t.savingAgenticBindings.has(s),p=t.agenticBindingErrors[s]||"",u=a.max_estimated_cost_microusd===null?"":String(a.max_estimated_cost_microusd/1e6),m=e.credential_bindings,w=n?.credential_binding_id||m[0]?.binding_id||"",g=t.pendingAgenticEnabled[s]??!!n?.enabled,T=e.selectable===!0||!g&&e.enable_eligible===!0,k=e.enable_blocked_reason||e.blocked_reason||(r&&o?.status!=="active"?o?.reason_code||"effective capabilities unavailable":"")||"Unavailable";return`<details class="settings-model-accordion settings-agentic-runtime" data-settings-model-accordion="agentic-${y(s)}">
    <summary>
      <span class="settings-model-summary-copy">
        <strong>${d(Dt(e))}</strong>
        <small>${d(ds(e.model_id,e.default_reasoning_effort))}</small>
      </span>
      <span class="settings-agentic-summary-badges">
        ${n?.is_default?'<span class="settings-pill">Default</span>':""}
        ${c?'<span class="settings-pill is-warning">NO-GO</span>':""}
        ${T?"":`<span class="settings-pill is-warning">${d(he(k))}</span>`}
        <label class="settings-model-toggle settings-toggle settings-bouncy-toggle" title="${g?"Disable model":"Enable model"}">
          <input type="checkbox" role="switch" data-agentic-model-toggle data-settings-controlled aria-label="Enable ${y(Dt(e))}"
            data-agentic-definition-id="${y(e.definition_id)}"
            ${g?"checked":""} ${l||e.enable_eligible!==!0&&!g?"disabled":""}>
          <span class="settings-bouncy-toggle__label">${g?"On":"Off"}</span>
          <span class="settings-bouncy-toggle__track" aria-hidden="true">
            <span class="settings-bouncy-toggle__inner"></span>
            <span class="settings-bouncy-toggle__thumb"><span class="settings-bouncy-toggle__dot"></span></span>
          </span>
        </label>
      </span>
    </summary>
    <div class="settings-model-content settings-agentic-runtime-content" data-agentic-binding-form data-agentic-definition-id="${y(e.definition_id)}">
      ${c?`<div class="settings-provider-usage-unavailable settings-agentic-containment-state">
        <span class="material-symbols-rounded" aria-hidden="true">block</span>
        <span>
          <strong>NO-GO · ${d(he(e.containment_reason||"remote agentic contained"))}</strong>
          <small>${d(e.data_destination.display_label)}</small>
        </span>
      </div>`:""}
      <div class="settings-agentic-controls">
        ${r?`<label class="settings-platform-field">
          <span>Credential binding</span>
          <select data-agentic-field="credential_binding_id" ${l||c?"disabled":""}>
            <option value="">${m.length?"No credential":"No active credential available"}</option>
            ${m.map(b=>`<option value="${y(b.binding_id)}" ${b.binding_id===w?"selected":""}>${d(b.label||b.binding_id)} · ${b.workspace_id?"workspace":"platform"}</option>`).join("")}
          </select>
        </label>`:'<input data-agentic-field="credential_binding_id" type="hidden" value="">'}
        <label class="settings-platform-field">
          <span>Maximum cost per turn (USD)</span>
          <input data-agentic-field="max_estimated_cost_usd" type="number" min="0" step="0.01" value="${y(u)}" placeholder="No explicit ceiling" ${l||c?"disabled":""}>
        </label>
        <div class="settings-platform-checks settings-agentic-checks">
          <input data-agentic-field="enabled" type="checkbox" ${g?"checked":""} hidden>
          ${ce("is_default","Use as workspace default",!!n?.is_default,l||c)}
          <details class="settings-agentic-advanced">
            <summary>Advanced controls</summary>
            ${ce("allow_workspace_admins","Workspace administrators",i.allow_workspace_admins,l||c)}
            ${ce("allow_workspace_members","Workspace members",i.allowed_workspace_role_ids.includes("member"),l||c)}
            ${ce("require_confirmation_for_mutating","Confirm mutating tools",a.require_confirmation_for_mutating,l||c,e.profile_policy_ceiling.require_confirmation_for_mutating)}
            ${ce("require_confirmation_for_destructive","Confirm destructive tools",a.require_confirmation_for_destructive,l||c,e.profile_policy_ceiling.require_confirmation_for_destructive)}
          </details>
        </div>
      </div>
      <button type="button" data-agentic-binding-save data-agentic-definition-id="${y(e.definition_id)}" ${l||c?"disabled":""}>
        <span class="material-symbols-rounded" aria-hidden="true">${l?"progress_activity":"verified_user"}</span>
        ${l?"Saving binding":n?"Save binding":"Create binding"}
      </button>
      ${p?`<p class="settings-platform-error" role="alert">${d(p)}</p>`:""}
    </div>
  </details>`}function ce(e,t,s,n,a=!1){return ae(`<input data-agentic-field="${y(e)}" type="checkbox" role="switch" ${s?"checked":""} ${n||a?"disabled":""}>`,d(t))}function Dt(e){return e.runtime_engine_id==="codex"||e.runtime_engine_id==="antigravity-cli"?e.model_id:e.display_name.replace(/^OpenRouter\s+/i,"").replace(/^Google\s+/i,"").replace(/\s+·\s+Relace$/i,"")}function ds(e,t){const s=e?.match(/-(max|xhigh|high|medium|low)$/i)?.[1]||"",n=t||s;return`Reasoning · ${n?he(n):"Preset"}`}function he(e){return e.replace(/[._-]+/g," ").replace(/\b\w/g,t=>t.toUpperCase())}function Ea({modelOptions:e,openHostedModel:t,hostedProvider:s,settings:n,state:a,emptyMessage:i,inactiveMessage:r}){const o=!!s,c=Ca(e,s);return`<div class="settings-hosted-models">
    ${e.length?c.map(l=>Ia(l,t,s,n,a)).join(""):`<p class="settings-card-copy settings-platform-note">${d(i)}</p>`}
    ${o?"":`<p class="settings-card-copy settings-platform-note">${d(r)}</p>`}
  </div>`}function Ia(e,t,s,n,a){const i=e.providerStatus==="active"?"Active provider":"Inactive provider";return`<section class="settings-hosted-provider-group" data-hosted-provider-group="${y(e.providerId)}">
    <div class="settings-hosted-provider-heading">
      <span>
        <strong>${d(e.providerLabel)}</strong>
        <small>${e.models.length} ${e.models.length===1?"model":"models"}</small>
      </span>
      <span class="settings-pill">${d(i)}</span>
    </div>
    ${e.models.map(r=>Aa(r,t,s,n,a)).join("")}
  </section>`}function Aa(e,t,s,n,a){const i=e.model_id,r=va(a,n,i),o=e.upstream_provider_options||[],c=o.length>0,l=Array.from(new Set(o.map($=>$.quantization||"").filter(Boolean))),p=cs(e,s),u=us(e,s),m=!!p,w=a.isSavingHostedProvider&&a.hostedDraftModelId===i,g=n.provider.hosted_text?.selection?.provider_id||s?.provider_id||"",T=p===g&&(n.provider.hosted_text?.model_settings?.selected_model_id||s?.default_model_family)||"",k=!!(m&&u==="active"&&i&&!a.isSavingHostedProvider&&(p!==g||i!==T||rs(a,n,i))),b=i===t,D=ps(e,s);return`<details class="settings-model-accordion settings-hosted-model-accordion" data-settings-model-accordion="hosted:${y(i)}" data-hosted-model-accordion="${y(i)}" id="settings-hosted-${y(encodeURIComponent(i))}" ${b?"open":""}>
    <summary class="settings-model-trigger">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">record_voice_over</span>
      <span class="settings-model-copy">
        <span class="settings-model-kicker">
          <span class="settings-kicker">Hosted speech model</span>
        </span>
        <strong>${d(e.label||i)} - ${d(D)}</strong>
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
      <select data-openrouter-routing="mode" data-hosted-model-id="${y(i)}" ${!m||!o.length||a.isSavingHostedProvider?"disabled":""}>
        ${[["auto","Auto"],["prefer","Prefer selected"],["only","Only selected"],["ignore","Ignore selected"]].map(([$,A])=>`<option value="${y($)}" ${$===r.mode?"selected":""}>${d(A)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Upstream provider</span>
      <select data-openrouter-routing="provider_id" data-hosted-model-id="${y(i)}" ${!m||!o.length||r.mode==="auto"||a.isSavingHostedProvider?"disabled":""}>
        <option value="">Select provider</option>
        ${o.map($=>`<option value="${y(String($.provider_id||$.tag||""))}" ${($.provider_id||$.tag)===r.providerId?"selected":""}>${d($.label||$.provider_id||$.tag||"Provider")}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Sort</span>
      <select data-openrouter-routing="sort" data-hosted-model-id="${y(i)}" ${!m||a.isSavingHostedProvider?"disabled":""}>
        ${[["","OpenRouter default"],["price","Price"],["throughput","Throughput"],["latency","Latency"]].map(([$,A])=>`<option value="${y($)}" ${$===r.sort?"selected":""}>${d(A)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Data collection</span>
      <select data-openrouter-routing="data_collection" data-hosted-model-id="${y(i)}" ${!m||a.isSavingHostedProvider?"disabled":""}>
        ${[["","OpenRouter default"],["allow","Allow"],["deny","Deny"]].map(([$,A])=>`<option value="${y($)}" ${$===r.dataCollection?"selected":""}>${d(A)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Quantization</span>
      <select data-openrouter-routing="quantization" data-hosted-model-id="${y(i)}" ${!m||!l.length||a.isSavingHostedProvider?"disabled":""}>
        <option value="">Any</option>
        ${l.map($=>`<option value="${y($)}" ${$===r.quantization?"selected":""}>${d($)}</option>`).join("")}
      </select>
    </label>
    <div class="settings-platform-checks">
      ${ae(`<input type="checkbox" role="switch" data-openrouter-routing="allow_fallbacks" data-hosted-model-id="${y(i)}" ${r.allowFallbacks?"checked":""} ${!m||a.isSavingHostedProvider?"disabled":""}>`,"Allow OpenRouter fallback")}
      ${ae(`<input type="checkbox" role="switch" data-openrouter-routing="require_parameters" data-hosted-model-id="${y(i)}" ${r.requireParameters?"checked":""} ${!m||a.isSavingHostedProvider?"disabled":""}>`,"Require supported parameters")}
      ${ae(`<input type="checkbox" role="switch" data-openrouter-routing="zdr" data-hosted-model-id="${y(i)}" ${r.zdr?"checked":""} ${!m||a.isSavingHostedProvider?"disabled":""}>`,"Require zero data retention")}
    </div>
    `:""}
    <button type="button" data-hosted-provider-save="${y(i)}" ${k?"":"disabled"}>
      <span class="material-symbols-rounded" aria-hidden="true">${w?"sync":"save"}</span>
      ${w?"Saving":"Save hosted model"}
    </button>
    ${a.hostedProviderError&&a.hostedProviderErrorModelId===i?`<p class="settings-platform-error">${d(a.hostedProviderError)}</p>`:""}
    </div>
  </details>`}function Ca(e,t){const s=new Map;for(const n of e){const a=cs(n,t)||"hosted-provider",i=s.get(a);if(i){i.models.push(n);continue}s.set(a,{providerId:a,providerLabel:ps(n,t),providerStatus:us(n,t),models:[n]})}return Array.from(s.values()).sort((n,a)=>n.providerStatus==="active"&&a.providerStatus!=="active"?-1:a.providerStatus==="active"&&n.providerStatus!=="active"?1:n.providerLabel.localeCompare(a.providerLabel))}function cs(e,t){const s=e.metadata?.hosted_provider_id;return typeof s=="string"&&s?s:t?.provider_id||""}function ps(e,t){const s=e.metadata?.hosted_provider_label;return typeof s=="string"&&s?s:t?.label||t?.provider_id||"Hosted provider"}function us(e,t){const s=e.metadata?.hosted_provider_status;return typeof s=="string"&&s?s:t?.status||""}function Ma(e,t){const s=e?.active_provider||e?.available_providers?.find(D=>D.provider_id==="deepgram")||null,n=Me(e,s,"prerecorded_transcription"),a=Me(e,s,"conversational_streaming"),i=e?.model_settings?.audio_transcription_model_id||n[0]?.model_id||"nova-3",r=e?.model_settings?.conversation_model_id||a[0]?.model_id||"flux-general-multi",o=t.speechAudioModelId||i,c=t.speechConversationModelId||r,l=n.find(D=>D.model_id===o)||n[0]||null,p=a.find(D=>D.model_id===c)||a[0]||null,u=Tt(l,e?.model_settings?.endpoints?.audio_transcription||`https://api.deepgram.com/v1/listen?model=${o}`),m=Tt(p,e?.model_settings?.endpoints?.conversation||`wss://api.deepgram.com/v2/listen?model=${c}`),w=!!(e?.active_provider&&e?.credential_binding),g=!!(w&&o&&c&&!t.isSavingSpeechProvider&&(o!==i||c!==r)),T=s?.label||s?.provider_id||"Deepgram",k=s?.provider_id||"deepgram",b=w?"Active provider":"Inactive provider";return`<div class="settings-hosted-models settings-speech-models">
    <section class="settings-hosted-provider-group" data-speech-provider-group="${y(k)}">
      <div class="settings-hosted-provider-heading">
        <span>
          <strong>${d(T)}</strong>
          <small>2 settings</small>
        </span>
        <span class="settings-pill">${d(b)}</span>
      </div>
      ${Rt({id:"settings-speech-audio-model",label:"Audio transcription model",icon:"hearing",value:o,options:n,endpoint:u,description:l?.description||"Deepgram model for prerecorded audio, files, and one-shot microphone transcription.",disabled:!w||t.isSavingSpeechProvider,canSave:g,isSaving:t.isSavingSpeechProvider})}
      ${Rt({id:"settings-speech-conversation-model",label:"Conversation model",icon:"forum",value:c,options:a,endpoint:m,description:p?.description||"Deepgram Flux model for realtime voice conversation and turn detection.",disabled:!w||t.isSavingSpeechProvider,canSave:g,isSaving:t.isSavingSpeechProvider})}
    </section>
    ${t.speechProviderError?`<p class="settings-platform-error">${d(t.speechProviderError)}</p>`:""}
    ${w?"":'<p class="settings-card-copy settings-platform-note">Activate Deepgram with a Core Secrets binding before using speech-to-text.</p>'}
  </div>`}function Rt({id:e,label:t,icon:s,value:n,options:a,endpoint:i,description:r,disabled:o,canSave:c,isSaving:l}){return a.length?`<details class="settings-model-accordion settings-speech-model-accordion">
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
        <select id="${y(e)}" ${o?"disabled":""}>
          ${a.map(p=>`<option value="${y(p.model_id)}" ${p.model_id===n?"selected":""}>${d(p.label||p.model_id)}</option>`).join("")}
        </select>
      </label>
      <div class="settings-platform-field settings-platform-field-wide">
        <span>Endpoint</span>
        <code class="settings-model-code">${d(i)}</code>
      </div>
      <p class="settings-card-copy">${d(r)}</p>
      <button type="button" data-speech-discard class="settings-secondary" ${c&&!l?"":"disabled"}>Discard edits</button>
      <button type="button" data-speech-save="${y(e)}" ${c?"":"disabled"}>
        <span class="material-symbols-rounded" aria-hidden="true">${l?"sync":"save"}</span>
        ${l?"Saving":"Save speech model"}
      </button>
    </div>
  </details>`:`<p class="settings-card-copy settings-platform-note">No ${d(t.toLowerCase())} options are available.</p>`}function Tt(e,t){const s=e?.metadata?.endpoint;return typeof s=="string"&&s?s:t}function Pa(e,t){const s=as(e).filter(Da);return qa(s,fa(e,t),e.provider.hosted_text?.active_provider||null,e.provider.speech_stt||null,e,t)}function qa(e,t,s,n,a,i){return`<section class="settings-card settings-platform settings-speech-model-settings-card">
    ${ls("record_voice_over","Speech model settings")}
    <div class="settings-platform-provider-forms">
      ${_n(i.speechSynthesis)}
      ${Ea({modelOptions:e,openHostedModel:t,hostedProvider:s,settings:a,state:i,emptyMessage:"No hosted speech models are available from the active hosted providers.",inactiveMessage:"Activate the hosted provider before saving speech model routing."})}
      ${Ma(n,i)}
    </div>
  </section>`}function Da(e){return(e.output_modalities||[]).includes("speech")}function Ra(e,t,s="models"){return e?s==="computer-use"?yn(e,t.computerUse):s==="voice"?Pa(e,t):ya(e.agentic_admin||null,t,e.provider.execution_families,e.provider.native_agents?.items||[],e.user.platform_role==="admin"):'<section class="settings-card"><p role="alert">Settings unavailable.</p></section>'}const Ta=5,La=4,Ha=4,Ua=3,Oa=4;function Na(e){return`<section class="settings-loading-skeleton" role="status" aria-label="Settings content is loading">
    <header class="detail-header settings-loading-skeleton__header" aria-hidden="true">
      <div class="detail-title-block">
        ${R("title")}
        <span class="detail-title-separator" aria-hidden="true"></span>
        ${R("subtitle")}
      </div>
    </header>
    ${Ba(e)}
  </section>`}function Ba(e){return e.id==="workspace-access"?za():e.id==="workspace-apps"?Wa():["models","voice","computer-use","usage","sessions"].includes(e.id)?Va():e.id==="persistence"?Ja():e.id==="cache"?ja():e.id==="learning"?`<section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">${se(!0)}<div class="settings-loading-skeleton__field-grid">${K(3,()=>R("copy"))}</div></section>
      <section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">${se(!0)}${K(2,()=>N("toggle"))}${K(3,()=>R("copy-wide"))}${N("button")}</section>`:Fa()}function ja(){return`<section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
    ${se(!0)}
    ${R("copy-wide")}
    <div class="settings-loading-skeleton__rows">
      ${K(4,()=>ms())}
    </div>
    ${N("button")}
  </section>`}function Fa(){return`<section class="settings-card settings-loading-skeleton__create" aria-hidden="true">
      ${Ga("short-title")}
      ${K(Ta,()=>N("field"))}
      ${N("button")}
    </section>
    ${gs()}
    <div class="settings-loading-skeleton__profile-row" aria-hidden="true">
      <section class="settings-card settings-loading-skeleton__detail-card">
        ${se(!0)}
        <div class="settings-loading-skeleton__field-grid">
          ${K(La,()=>Pe())}
        </div>
        ${N("toggle")}
        ${N("button")}
      </section>
      <section class="settings-card settings-loading-skeleton__password-card">
        ${se(!1)}
        ${R("copy")}
        <div class="settings-loading-skeleton__field-grid">
          ${K(2,()=>Pe())}
        </div>
        ${N("button")}
        ${N("danger-button")}
      </section>
    </div>`}function za(){return`${gs()}
    <section class="settings-card" aria-hidden="true">
      ${se(!0)}
      <div class="settings-loading-skeleton__rows">
        ${K(Ha,()=>Ka())}
      </div>
    </section>`}function Wa(){return`<section class="settings-card" aria-hidden="true">
      ${se(!1)}
      ${R("copy-wide")}
      <div class="settings-loading-skeleton__rows">
        ${K(Ua,()=>Qa())}
      </div>
    </section>`}function Va(){return`<section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
      ${Ge()}
    </section>
    <section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
      ${Ge()}
      <div class="settings-loading-skeleton__provider-form">
        ${K(2,()=>Pe())}
        ${N("button")}
      </div>
      ${Ge()}
    </section>
    <section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
      <div class="settings-loading-skeleton__runtime-toolbar">
        ${R("copy-wide")}
        ${N("button")}
      </div>
      <div class="settings-loading-skeleton__runtime-list">
        ${K(Oa,()=>Ya())}
      </div>
    </section>`}function Ja(){return`<section class="settings-card settings-loading-skeleton__persistence" aria-hidden="true">
      ${se(!0)}
      <div class="settings-loading-skeleton__adapter-cards">
        ${K(2,()=>Xa())}
      </div>
      ${ms()}
    </section>`}function gs(){return`<section class="settings-card settings-user-picker" aria-hidden="true">
    <div class="settings-loading-skeleton__copy-stack">
      ${R("kicker")}
      ${R("card-title")}
      ${R("copy-short")}
    </div>
    ${Pe()}
  </section>`}function se(e){return`<div class="settings-loading-skeleton__heading">
    <span class="settings-loading-skeleton__copy-stack">
      ${R("kicker")}
      ${R("card-title")}
    </span>
    ${e?N("pill"):""}
  </div>`}function Ga(e){return`<div class="settings-loading-skeleton__copy-stack">
    ${R("kicker")}
    ${R(e)}
  </div>`}function Pe(){return`<span class="settings-loading-skeleton__field-wrap">
    ${R("label")}
    ${N("field")}
  </span>`}function Ka(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--membership">
    ${N("checkbox")}
    ${de("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${R("row-title")}
      ${R("row-copy")}
    </span>
    ${N("select")}
  </span>`}function Qa(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--app">
    ${de("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${R("row-title")}
      ${R("row-copy")}
    </span>
    ${N("toggle-pill")}
    ${N("button")}
  </span>`}function Ge(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--tile">
    ${de("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${R("row-title")}
      ${R("row-copy")}
    </span>
  </span>`}function Ya(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--runtime">
    ${de("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${R("row-title")}
      ${R("row-copy")}
    </span>
    ${N("button")}
  </span>`}function Xa(){return`<span class="settings-loading-skeleton__adapter-card">
    ${de("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${R("row-title")}
      ${R("row-copy-wide")}
    </span>
    ${N("pill")}
  </span>`}function ms(){return`<span class="settings-loading-skeleton__result">
    ${de("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${R("row-title")}
      ${R("row-copy-wide")}
    </span>
  </span>`}function R(e){return`<span class="settings-loading-skeleton__line settings-loading-skeleton__line--${e}"></span>`}function N(e){return`<span class="settings-loading-skeleton__block settings-loading-skeleton__block--${e}"></span>`}function de(e){return`<span class="settings-loading-skeleton__icon settings-loading-skeleton__icon--${e}"></span>`}function K(e,t){return Array.from({length:e},t).join("")}function Za({publishChanged:e,render:t,setNotice:s}){let n=[],a=[],i="",r=[],o="",c=!1,l=0,p=0,u="";const m=new Map;function w(){return{appRegistry:n,error:i,isLoading:c,loadErrors:r,savingKeys:new Set(m.keys()),dependencies:a.map($=>({...$,dependencies:$.dependencies.map(A=>{const F=m.get(Lt($.consumer_app_id,A.alias));return F?{...A,selected_provider_app_ids:F.providerAppIds}:A})}))}}function g(){l+=1,p+=1,c=!1,u="",m.clear(),n=[],a=[],i="",r=[],o=""}function T(){o=""}async function k($,A,F=!1){if(!$||(u!==$&&(g(),u=$),c)||!F&&o===u)return;const U=++p;c=!0,i="",r=[],t();try{const[z,P]=await Promise.all([an(),D(u,A)]);if(U!==p)return;n=z,a=P.dependencies,r=P.errors,o=u}catch(z){if(U!==p)return;o="",i=z instanceof Error?z.message:"Unable to load app links."}finally{U===p&&(c=!1,t())}}async function b($,A,F){const U=l,z=Lt($,A);if(m.has(z))return;const P={providerAppIds:[...F]};m.set(z,P),t();try{const S=await Xt($,A,F);if(U!==l||S.workspace_id!==u)return;p+=1,c=!1;const v=a.find(_=>_.consumer_app_id===$),h={...S,dependencies:S.dependencies.map(_=>_.alias===A?_:v?.dependencies.find(I=>I.alias===_.alias)||_)};a=[...a.filter(_=>_.consumer_app_id!==$),h].sort((_,I)=>_.consumer_app_id.localeCompare(I.consumer_app_id)),e($,h),s({tone:"success",message:"App link updated."})}catch(S){if(U===l)throw S}finally{m.get(z)===P&&(m.delete(z),t())}}async function D($,A){const F=A.filter(_=>_.workspace_id===$&&_.status==="enabled"),U=new Array(F.length);let z=0;const P=p;await Promise.all(Array.from({length:Math.min(4,F.length)},async()=>{for(;z<F.length&&P===p;){const _=z++,I=F[_];try{U[_]={app:I,payload:await pt(I.app_id)}}catch(O){U[_]={app:I,error:O instanceof Error?O.message:"Unable to load app links."}}}}));const S=U.filter(Boolean),v=S.filter(_=>"error"in _).map(_=>({app_id:_.app.app_id,message:_.error,name:_.app.name||_.app.app_id}));return{dependencies:S.filter(_=>"payload"in _&&_.payload.dependencies.length>0).map(_=>_.payload).sort((_,I)=>_.consumer_app_id.localeCompare(I.consumer_app_id)),errors:v}}return{ensureLoaded:k,invalidate:T,reset:g,saveDependencySelection:b,viewState:w}}function Lt(e,t){return`${e}:${t}`}function xa(e){let t=0;const s=new Map,n=a=>`${a.workspace_id}:${a.app_id}`;return{reset:()=>{t++,s.clear()},savingKeys:()=>new Set(s.keys()),apps:a=>a.map(i=>s.has(n(i))?{...i,status:s.get(n(i))?"enabled":"disabled"}:i),setEnabled:async(a,i)=>{const r=t,o=n(a);if(!s.has(o)){s.set(o,i),e.render();try{await sa(a,i),r===t&&e.updated(a,i)}catch(c){if(r===t)throw c}finally{r===t&&(s.delete(o),e.render())}}}}}function ei({appRegistry:e,dependencies:t,error:s,isLoading:n,loadErrors:a,savingKeys:i,workspaceApps:r}){return`<section class="settings-card settings-app-links">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">App links</p>
          <h2>Provider app links</h2>
          <button type="button" id="settings-refresh-app-links" class="settings-secondary" ${n?"disabled":""}>Refresh links</button>
        </div>
      </div>
      <p class="settings-card-copy">Provider links are workspace-scoped. A selected provider is reused until it becomes unavailable; otherwise one-provider interface links use the first available candidate as their automatic default.</p>
      ${s?`<p class="settings-platform-error">${d(s)}</p>`:""}
      ${a.length?`<div class="settings-app-link-errors">${a.map(li).join("")}</div>`:""}
      ${t.length>1?ti(t,e,r):""}
      <div class="settings-app-link-list">
        ${t.length?t.map(o=>si(o,e,r,i)).join(""):ai(s,n)}
      </div>
    </section>`}function ti(e,t,s){return`<nav class="settings-app-link-consumer-nav" aria-label="Provider link apps">
    ${e.map(n=>{const a=s.find(o=>o.workspace_id===n.workspace_id&&o.app_id===n.consumer_app_id),i=ft(t,n.consumer_app_id),r=a?.name||i?.name||n.consumer_app_id;return`<a class="settings-app-link-consumer-nav__item" href="#${y(fs(n.consumer_app_id))}">
        <strong>${d(r)}</strong>
        <small>${d(String(n.dependencies.length))}</small>
      </a>`}).join("")}
  </nav>`}function si(e,t,s,n){const a=s.find(r=>r.workspace_id===e.workspace_id&&r.app_id===e.consumer_app_id),i=ft(t,e.consumer_app_id);return`<article class="settings-app-link-consumer" id="${y(fs(e.consumer_app_id))}">
    <header class="settings-app-link-consumer__header">
      ${hs(i)}
      <span class="settings-app-copy">
        <strong>${d(a?.name||e.consumer_app_id)}</strong>
        <small>${d(e.consumer_app_id)} - ${d(e.status)}</small>
      </span>
    </header>
    <div class="settings-app-link-dependencies">
      ${e.dependencies.map(r=>ni(e.consumer_app_id,r,t,n)).join("")}
    </div>
  </article>`}function ni(e,t,s,n){const a=n.has(ii(e,t.alias)),i=ri(t),r=vs(t);return`<section class="settings-app-link-row" data-dependency-row="${y(e)}:${y(t.alias)}">
    <header class="settings-app-link-row__header">
      <span class="settings-app-link-row__copy">
        <strong>${d(t.alias)}</strong>
        <small>${d(t.interface)} ${d(t.version)}</small>
      </span>
      <span class="settings-pill ${t.status==="resolved"||r?"":"settings-pill-muted"}">${d(oi(t,r))}</span>
    </header>
    <p class="settings-card-copy">${d(t.description||"No description.")}</p>
    ${t.blocked_reason?`<p class="settings-platform-error">${d(t.blocked_reason)}</p>`:""}
    ${t.stale_provider_app_ids.length?`<p class="settings-platform-error">Unavailable selection: ${d(t.stale_provider_app_ids.join(", "))}</p>`:""}
    ${t.candidates.length?`<div class="settings-app-link-candidates">
            ${t.candidates.map(o=>{const c=i.includes(o.app_id),l=t.cardinality==="many"?"checkbox":"radio",p=`dependency:${e}:${t.alias}`,u=ft(s,o.app_id);return`<label class="settings-app-link-candidate ${c?"is-selected":""}">
                <input
                  data-settings-controlled
                  ${c?"checked":""}
                  ${a?"disabled":""}
                  data-dependency-choice="${y(Ht(e,t.alias,o.app_id))}"
                  name="${y(p)}"
                  type="${l}"
                />
                ${hs(u)}
                <span>
                  <strong>${d(o.name||o.app_id)}</strong>
                  <small>${d(o.app_id)} - ${d(o.interface_version)}${o.app_id===r?" - automatic default":""}</small>
                </span>
              </label>`}).join("")}
          </div>`:'<p class="settings-card-copy">No enabled provider app is available for this interface.</p>'}
    ${r?`<button type="button" class="settings-secondary" data-dependency-save-default="${y(Ht(e,t.alias,r))}" ${a?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">${a?"sync":"save"}</span>
          ${a?"Saving":"Save default"}
        </button>`:""}
  </section>`}function ai(e,t){return e?"":t?'<p class="settings-card-copy">Loading app links...</p>':'<p class="settings-card-copy">No enabled app in the active workspace declares provider links.</p>'}function ii(e,t){return`${e}:${t}`}function Ht(e,t,s){return`${e}:${t}:${s}`}function fs(e){return`settings-app-link-consumer-${e}`}function ri(e){if(e.selected_provider_app_ids.length)return e.selected_provider_app_ids;const t=vs(e);return t?[t]:[]}function vs(e){return e.selected_provider_app_ids.length||e.status!=="optional_unset"||e.cardinality!=="one"||e.stale_provider_app_ids.length||e.blocked_reason?"":e.candidates[0]?.app_id||""}function oi(e,t){return t?"auto default":e.status==="optional_unset"?"unset":e.status}function ft(e,t){return e.find(s=>s.app_id===t)||null}function li(e){return`<p class="settings-platform-error">${d(e.name||e.app_id)}: ${d(e.message)}</p>`}function hs(e){if(e?.logo?.kind==="image"&&e.logo.value)return`<span class="settings-app-link-logo is-image"><img alt="" loading="lazy" src="${y(e.logo.value)}" /></span>`;const t=e?.logo?.value||"apps";return`<span class="settings-app-link-logo is-glyph"><span class="material-symbols-rounded" aria-hidden="true">${d(t)}</span></span>`}function di(e){const{dashboard:t,error:s,isClearing:n,isLoading:a}=e,i=n?"Clearing…":"Clear cache";return`<section class="settings-card settings-cache-diagnostics" aria-busy="${a||n}">
    <div class="settings-heading">
      <div>
        <span class="settings-kicker">This browser</span>
        <h3>Maverick cache</h3>
      </div>
      <span class="settings-pill settings-pill-muted">Disposable</span>
    </div>
    <p class="settings-card-copy">Inspect aggregate cache usage for this browser container. Cached entries and file copies are rebuildable and never authorize server actions.</p>
    ${s?`<div class="settings-cache-diagnostics__error" role="alert">${d(s)}</div>`:""}
    ${ci(t,a)}
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
  </section>`}function ci(e,t){if(!e||t)return`<div class="settings-cache-diagnostics__grid" aria-label="Loading cache diagnostics">
      ${C("Cache data","—")}
      ${C("Entries","—")}
      ${C("Origin usage","—")}
      ${C("Origin quota","—")}
    </div>`;const{diagnostics:s,metrics:n}=e;return`<div class="settings-cache-diagnostics__section">
    <h4>Storage and quota</h4>
    <div class="settings-cache-diagnostics__grid">
    ${C("Cache data",me(s.cacheBytes))}
    ${C("Entries",s.entryCount.toLocaleString())}
    ${C("Structured data",me(s.structuredCacheBytes))}
    ${C("Structured entries",s.structuredEntryCount.toLocaleString())}
    ${C("File data",me(s.fileCacheBytes))}
    ${C("File entries",s.fileCacheEntryCount.toLocaleString())}
    ${C("Origin usage",Ut(s.originUsageBytes))}
    ${C("Origin quota",Ut(s.originQuotaBytes))}
    ${C("Backend",s.backend==="indexeddb"?"IndexedDB":"Memory fallback")}
    ${C("File storage",s.fileCacheAvailable?"OPFS available":"Unavailable")}
    ${C("Pending cleanup",s.pendingCleanupCount.toLocaleString())}
    </div>
  </div>
  ${pi(n)}
  ${ui(n)}`}function pi(e){const t=e.counters;return`<div class="settings-cache-diagnostics__section">
    <h4>Cache activity</h4>
    <p>Aggregate events in this browser since ${d(mi(e.windowStartedAt))}.</p>
    <div class="settings-cache-diagnostics__grid">
      ${C("Static hit / miss",X(t.pwa_static_cache_hit,t.pwa_static_cache_miss))}
      ${C("Data hit / miss",X(t.pwa_data_cache_hit,t.pwa_data_cache_miss))}
      ${C("Data cache errors",G(t.pwa_data_cache_error))}
      ${C("Stale / expired",X(t.pwa_data_cache_stale,t.pwa_data_cache_expired))}
      ${C("Revalidated unchanged",G(t.pwa_revalidate_not_modified))}
      ${C("Revalidated changed",G(t.pwa_revalidate_modified))}
      ${C("Revalidation errors",G(t.pwa_revalidate_error))}
      ${C("File hit / miss",X(t.pwa_file_cache_hit,t.pwa_file_cache_miss))}
      ${C("File writes / ready",X(t.pwa_file_cache_write,t.pwa_file_cache_ready))}
      ${C("File errors",G(t.pwa_file_cache_error))}
      ${C("Evicted entries",G(t.pwa_eviction_count))}
      ${C("Evicted data",me(t.pwa_eviction_bytes))}
      ${C("Quota usage samples",G(t.pwa_quota_usage))}
      ${C("Quota checks / errors",X(t.pwa_quota_estimate,t.pwa_quota_error))}
    </div>
  </div>`}function ui(e){const t=e.counters,s=e.requestWait;return`<div class="settings-cache-diagnostics__section">
    <h4>Requests and recovery</h4>
    <div class="settings-cache-diagnostics__grid">
      ${C("Pending waits (this window)",G(s.pendingCount))}
      ${C("Oldest pending (this window)",gi(s.oldestPendingMs))}
      ${C("Average wait",rt(s.averageDurationMs))}
      ${C("Longest wait",rt(s.maxDurationMs))}
      ${C("Resolved / cancelled",X(t.pwa_request_wait_resolved,t.pwa_request_wait_cancelled))}
      ${C("Retry attempts",G(t.pwa_request_retry_attempt))}
      ${C("Worker installs / updates",X(t.pwa_sw_install,t.pwa_sw_update))}
      ${C("Worker recoveries / errors",X(t.pwa_sw_recovery,t.pwa_sw_error))}
      ${C("Static cache errors",G(t.pwa_static_cache_error))}
    </div>
  </div>`}function C(e,t){return`<div class="settings-cache-diagnostics__metric">
    <span>${d(e)}</span>
    <strong>${d(t)}</strong>
  </div>`}function Ut(e){return e===null?"Unavailable":me(e)}function me(e){if(!Number.isFinite(e)||e<=0)return"0 B";const t=["B","KB","MB","GB"],s=Math.min(t.length-1,Math.floor(Math.log(e)/Math.log(1024))),n=e/1024**s;return`${n>=10||s===0?n.toFixed(0):n.toFixed(1)} ${t[s]}`}function G(e){return e.toLocaleString()}function X(e,t){return`${G(e)} / ${G(t)}`}function gi(e){return e===null?"None":rt(e)}function rt(e){return!Number.isFinite(e)||e<=0?"0 ms":e<1e3?`${Math.round(e)} ms`:`${(e/1e3).toFixed(e<1e4?1:0)} s`}function mi(e){const t=new Date(e);return Number.isFinite(t.getTime())?t.toLocaleString():"this session"}function fi(e){return _i(e)}function vi(e){const{deleteSourceAfterMigration:t,migrationPlan:s,migrationProgress:n,migrationTarget:a,persistence:i}=e;if(!a||!i)return"";const r=i.active_adapter.kind.toUpperCase(),o=a.toUpperCase(),c=!!(n&&!["complete","failed"].includes(n.phase)),l=!!(s&&!s.same_adapter&&!c);return`<div class="settings-modal-backdrop" role="presentation">
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
      ${s?wi(s):$i(n)}
      ${hi(e)}
      ${ae(`<input id="settings-delete-source" type="checkbox" role="switch" ${t?"checked":""} ${c?"disabled":""} />`,"Schedule source cleanup after restart health check","settings-migration-delete-source")}
      <p class="settings-card-copy">Leave cleanup off to preserve the current source adapter data as a rollback point. Cleanup is a separate explicit choice and requires backend restart.</p>
      <div class="settings-modal-actions">
        <button type="button" class="settings-secondary" id="cancel-migration" ${c?"disabled":""}>Cancel</button>
        <button type="button" class="settings-secondary" id="validate-migration" ${c?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">rule</span>
          Validate dry run
        </button>
        <button type="button" class="${t?"settings-danger":"settings-secondary"}" id="confirm-migration" ${l?"":"disabled"}>
          <span class="material-symbols-rounded" aria-hidden="true">sync_alt</span>
          ${t?"Apply and schedule cleanup":"Apply migration"}
        </button>
      </div>
    </section>
  </div>`}function hi(e){const t=e.targetDraft;if(!t)return"";const s=!!(e.migrationProgress&&!["complete","failed"].includes(e.migrationProgress.phase));return`<div class="settings-migration-target">
    <label class="settings-platform-field">
      <span>JSON root</span>
      <input data-migration-field="json_root" value="${y(t.json_root)}" ${s?"disabled":""} />
    </label>
    ${t.kind==="mongo"?`<label class="settings-platform-field">
          <span>Mongo URI</span>
          <input data-migration-field="mongodb_uri" value="${y(t.mongodb_uri)}" ${s?"disabled":""} />
        </label>
        <label class="settings-platform-field">
          <span>Mongo database</span>
          <input data-migration-field="mongodb_database" value="${y(t.mongodb_database)}" ${s?"disabled":""} />
        </label>
        <label class="settings-platform-field">
          <span>Mongo username</span>
          <input data-migration-field="mongodb_username" value="${y(t.mongodb_username||"")}" ${s?"disabled":""} />
        </label>
        <label class="settings-platform-field">
          <span>Password secret ref</span>
          <input data-migration-field="mongodb_password_ref" value="${y(t.mongodb_password_ref||"")}" ${s?"disabled":""} />
        </label>`:""}
  </div>`}function _i(e){const{migrationProgress:t,migrationResult:s,persistence:n}=e;if(!n)return`<section class="settings-card settings-persistence">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Persistence</p>
          <h2>Control plane adapter</h2>
        </div>
        <span class="settings-pill settings-pill-muted">offline</span>
      </div>
      <p class="settings-card-copy">The core persistence surfaces are not available in the active backend.</p>
    </section>`;const a=n.active_adapter,i=n.collections.reduce((l,p)=>l+p.count,0),r=a.kind==="json",o=a.kind==="mongo",c=t&&!["complete","failed"].includes(t.phase);return`<section class="settings-card settings-persistence">
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
      <button type="button" class="settings-adapter-card ${o?"is-active":""}" ${o||c?"disabled":'data-adapter-target="mongo"'}>
        <span class="settings-adapter-card-icon material-symbols-rounded" aria-hidden="true">${o?"check_circle":"database"}</span>
        <span>
          <strong>Mongo</strong>
          <small>${d(o?a.mongo_database:"mongodb://127.0.0.1:27017/maverick")}</small>
        </span>
        <em>${o?"Current":"Review migration"}</em>
      </button>
    </div>
    ${bi(t)}
    ${yi(s)}
  </section>`}function bi(e){return e?`<div role="status" aria-live="polite" class="settings-migration-progress ${e.phase==="failed"?"is-failed":""} ${e.phase==="complete"?"is-complete":""}">
    <div class="settings-migration-progress-heading">
      <span class="material-symbols-rounded" aria-hidden="true">${e.phase==="complete"?"check_circle":e.phase==="failed"?"error":"sync"}</span>
      <span>
        <strong>${d(e.title)}</strong>
        <small>${d(e.detail)}</small>
      </span>

    </div>
  </div>`:""}function yi(e){return e?`<div class="settings-migration-result">
    <span class="material-symbols-rounded" aria-hidden="true">task_alt</span>
    <span>
      <strong>Last migration</strong>
      <small>${e.collections.reduce((s,n)=>s+n.count,0)} documents · target ${d(e.target_adapter.kind)} · cleanup ${e.source_cleanup?.scheduled?"scheduled":"not requested"}</small>
    </span>
  </div>`:""}function $i(e){return`<div class="settings-migration-plan">
    <span class="material-symbols-rounded" aria-hidden="true">rule</span>
    <span>
      <strong>${d(e?.title||"Dry run not validated")}</strong>
      <small>${d(e?.detail||"Adjust the target fields, then validate the dry run before applying migration.")}</small>
    </span>
  </div>`}function wi(e){const t=e.collections.reduce((n,a)=>n+a.count,0),s=e.target_collections.reduce((n,a)=>n+a.count,0);return`<div class="settings-migration-plan">
    <span class="material-symbols-rounded" aria-hidden="true">${e.same_adapter?"block":"rule"}</span>
    <span>
      <strong>${e.same_adapter?"Target already active":"Dry run complete"}</strong>
      <small>${t} source documents · ${s} target documents before copy · env ${d(e.env_file)}</small>
    </span>
    <div class="settings-migration-collections">
      ${e.collections.map(n=>`<span><strong>${d(n.name)}</strong><small>${n.count}</small></span>`).join("")}
    </div>
  </div>`}function ki({selectedUser:e,users:t}){return`<details class="settings-card settings-user-create"><summary>Create a user</summary><form class="settings-create" id="create-user">
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
    ${_s(t,e)}
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
              <label>Name<input name="display_name" value="${y(e.display_name||"")}" /></label>
              <label>Email<input name="email" type="email" value="${y(e.email||"")}" /></label>
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
        </div>`:'<section class="settings-card"><h2>No users</h2></section>'}`}function Ot({selectedUser:e,users:t,workspaces:s,showPicker:n=!0}){return`${n?_s(t,e):""}
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
          <div class="settings-memberships">${Si(e,s)}</div>
          <button type="button" data-user-discard class="settings-secondary">Discard edits</button><p data-action-status class="settings-action-status" role="status"></p>
        </section>`:'<section class="settings-card"><h2>No users</h2></section>'}`}function _s(e,t){return e.length?`<section class="settings-card settings-user-picker">
    <div>
      <p class="settings-kicker">User directory</p>
      <h2>${d(t?t.display_name||t.username:"Select user")}</h2>
      <p class="settings-card-copy">${e.length} user${e.length===1?"":"s"} available.</p>
    </div>
    <label class="settings-platform-field">
      <span>Selected user</span>
      <select id="selected-user" data-settings-controlled>
        ${e.map(s=>`<option value="${y(s.user_id)}" ${s.user_id===t?.user_id?"selected":""}>${d(s.display_name||s.username)} (${d(s.username)})</option>`).join("")}
      </select>
    </label>
  </section>`:`<section class="settings-card settings-user-picker">
      <div>
        <p class="settings-kicker">User directory</p>
        <h2>No users</h2>
      </div>
      <p class="settings-card-copy">Create a user before editing profile or workspace access settings.</p>
    </section>`}function Si(e,t){return t.map(s=>{const n=e.memberships.find(a=>a.workspace_id===s.workspace_id);return`<label class="settings-membership">
        <input type="checkbox" aria-label="Access to ${y(s.name)}" data-workspace-enabled="${y(s.workspace_id)}" ${n?"checked":""} />
        <span class="settings-membership-icon material-symbols-rounded" aria-hidden="true">workspaces</span>
        <span>
          <strong>${d(s.name)}</strong>
          <small>${d(s.workspace_id)}</small>
        </span>
        <select aria-label="Role in ${y(s.name)}" data-workspace-role="${y(s.workspace_id)}">
          <option value="member" ${n?.role!=="admin"?"selected":""}>Member</option>
          <option value="admin" ${n?.role==="admin"?"selected":""}>Workspace admin</option>
        </select>
      </label>`}).join("")}function Ei({workspaceApps:e,workspaces:t,savingKeys:s=new Set}){return`<details class="settings-card"><summary>Create a workspace</summary><form id="create-workspace" class="settings-grid">
    <label>Name<input name="name" required /></label><label>Description<input name="description" /></label><button type="submit">Create workspace</button>
    </form></details><section class="settings-card">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Workspace apps</p>
          <h2>Installation and visibility</h2>
        </div>
      </div>
      <p class="settings-card-copy">Installed means the app has a workspace binding. Only enabled apps are visible to users and served by the core.</p>
      <div class="settings-app-workspaces">${Ii(t,e,s)}</div>
    </section>`}function Ii(e,t,s){return e.map(n=>{const a=t.filter(o=>o.workspace_id===n.workspace_id),i=a.filter(o=>o.status==="enabled").length,r=a.filter(o=>o.installed).length;return`<details class="settings-app-workspace" data-workspace-row="${y(n.workspace_id)}">
        <summary class="settings-app-workspace-heading">
          <span class="settings-summary-caret material-symbols-rounded" aria-hidden="true">chevron_right</span>
          <span class="settings-app-workspace-icon material-symbols-rounded" aria-hidden="true">deployed_code</span>
          <span>
            <strong>${d(n.name)}</strong>
            <small>${d(n.workspace_id)} · ${i}/${r} enabled</small>
          </span>
        </summary>
        <div class="settings-apps">
          ${a.map(o=>Ai(o,s)).join("")}
        </div>
      </details>`}).join("")}function Ai(e,t){const s=e.status==="enabled",n=e.installed,a=n?e.status:"not installed",i=`${e.workspace_id}:${e.app_id}`,r=t.has(i);return`<div class="settings-app-row" data-app-row="${y(i)}">
    ${e.logo?.kind==="image"?`<img class="settings-app-icon" src="${y(e.logo.value)}" alt="" />`:`<span class="settings-app-icon material-symbols-rounded" aria-hidden="true">${d(e.logo?.kind==="glyph"?e.logo.value:"apps")}</span>`}
    <span class="settings-app-copy">
      <strong>${d(e.name)}</strong>
      <small>${d(e.app_id)} · v${d(e.version)} · ${d(a)}</small>
    </span>
    ${n?`${ae(`<input type="checkbox" role="switch" data-settings-controlled aria-label="Enable ${y(e.name)} in ${y(e.workspace_name)}" data-app-toggle="${y(i)}" ${s?"checked":""} ${r?"disabled":""} />`,"Enabled","settings-switch")}
        <button type="button" class="settings-secondary" data-app-uninstall="${y(i)}" ${r?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">link_off</span>
          Uninstall
        </button>`:`<button type="button" class="settings-secondary" data-app-install="${y(i)}">
          <span class="material-symbols-rounded" aria-hidden="true">add_link</span>
          Install
        </button>`}
  </div>`}function Ci(e){const{page:t,selectedUser:s}=e;if(t.id==="users")return ki({selectedUser:s,users:e.users})+Ot({selectedUser:s,users:e.users,workspaces:e.workspaces,showPicker:!1});if(t.id==="workspace-access")return Ot({selectedUser:s,users:e.users,workspaces:e.workspaces});if(t.id==="workspace-apps")return Ei({workspaceApps:e.workspaceApps,workspaces:e.workspaces,savingKeys:e.savingAppKeys});if(t.id==="app-links"){const n=e.appLinksController.viewState();return ei({appRegistry:n.appRegistry,dependencies:n.dependencies,error:n.error,isLoading:n.isLoading,loadErrors:n.loadErrors,savingKeys:n.savingKeys,workspaceApps:e.workspaceApps})}return["models","voice","computer-use"].includes(t.id)?e.platformSettingsHtml():t.id==="usage"?e.usageHtml():t.id==="sessions"?e.sessionsHtml():t.id==="learning"?e.learningHtml():t.id==="cache"?di(e.cacheDiagnosticsController.viewState()):fi(e.persistenceController.viewState())}async function ke(e,t,s){if(!e||e.hasAttribute("data-pending-action"))return;const n=Array.from(e.querySelectorAll("input, button, select")),a=n.map(r=>r.disabled);e.setAttribute("data-pending-action",""),e.setAttribute("aria-busy","true");const i=e.querySelector("[data-action-status]");i&&(i.setAttribute("role","status"),i.textContent="Saving…");try{const r=t();n.forEach(o=>{o.disabled=!0}),await r,i&&(i.textContent="Saved.")}catch(r){i&&(i.setAttribute("role","alert"),i.textContent=r instanceof Error?r.message:"Unable to save."),s(r)}finally{e.removeAttribute("data-pending-action"),e.removeAttribute("aria-busy"),n.forEach((r,o)=>{r.disabled=a[o]})}}function Mi(e){document.querySelectorAll("[data-native-provider-activate]").forEach(t=>{f(t,"click",()=>{e.onActivateNativeProvider(t.dataset.nativeProviderActivate||"")})}),document.querySelectorAll("[data-agentic-binding-save]").forEach(t=>{f(t,"click",()=>{e.onSaveAgenticBinding(t.dataset.agenticDefinitionId||"")})}),document.querySelectorAll("[data-agentic-model-toggle]").forEach(t=>{f(t,"click",s=>s.stopPropagation()),f(t.closest("label"),"click",s=>s.stopPropagation()),f(t,"change",()=>{const s=t.checked;e.onSaveAgenticBinding(t.dataset.agenticDefinitionId||"",{enabled:s})})}),f(document.getElementById("settings-speech-audio-model"),"change",t=>{e.onSpeechAudioModelChanged(t.currentTarget.value)}),f(document.getElementById("settings-speech-conversation-model"),"change",t=>{e.onSpeechConversationModelChanged(t.currentTarget.value)}),document.querySelectorAll("[data-speech-save]").forEach(t=>{f(t,"click",()=>{e.onSaveSpeechProviderSettings()})}),f(document.getElementById("settings-speech-save"),"click",()=>{e.onSaveSpeechProviderSettings()}),document.querySelectorAll("[data-settings-model-accordion]").forEach(t=>{f(t,"toggle",()=>{t.open&&document.querySelectorAll("[data-settings-model-accordion]").forEach(s=>{s!==t&&(s.open=!1)})})}),document.querySelectorAll("[data-openrouter-routing]").forEach(t=>{f(t,"change",s=>{const n=s.currentTarget,a=n.dataset.hostedModelId||n.closest("[data-hosted-model-accordion]")?.dataset.hostedModelAccordion||"";e.onHostedProviderRoutingChanged(a,n.dataset.openrouterRouting||"",n instanceof HTMLInputElement&&n.type==="checkbox"?n.checked:n.value)})}),f(document.getElementById("settings-refresh-usage-history"),"click",e.onRefreshProviderUsage),document.querySelectorAll("[data-hosted-provider-save]").forEach(t=>{f(t,"click",()=>e.onSaveHostedProviderSettings(t.dataset.hostedProviderSave||""))}),f(document.getElementById("settings-logout"),"click",e.onLogout),f(document.getElementById("settings-clear-all-runtime"),"click",e.onClearAllRuntimeSessions),document.querySelectorAll("[data-runtime-clear]").forEach(t=>{f(t,"click",()=>e.onClearRuntimeSession(t.dataset.runtimeClear||""))})}function Pi(e){_a(),f(document.getElementById("dismiss-notice"),"click",e.dismissNotice),f(document.getElementById("create-user"),"submit",s=>{s.preventDefault();const n=s.currentTarget;ke(n,()=>e.createUser(n),e.showError)});const t=e.selectedUser();f(document.getElementById("selected-user"),"change",s=>{e.selectUser(s.currentTarget.value)}),f(document.getElementById("edit-user"),"submit",s=>{s.preventDefault();const n=s.currentTarget;t&&ke(n,()=>e.updateSelectedUser(n,t),e.showError)}),f(document.getElementById("reset-password"),"submit",s=>{s.preventDefault();const n=s.currentTarget;t&&ke(n,()=>e.resetSelectedUserPassword(n,t),e.showError)}),f(document.getElementById("delete-user"),"click",()=>{t&&e.deleteSelectedUser(t).catch(e.showError)}),f(document.getElementById("save-memberships"),"click",()=>{t&&ke(document.getElementById("workspace-assignments"),()=>e.updateMemberships(t),e.showError)}),Ri(e),Di(e),Ti(e),qi(e),Mi({onClearAllRuntimeSessions:()=>{e.clearRuntimeSessionsFromPanel().catch(e.showError)},onClearRuntimeSession:s=>{s&&e.clearRuntimeSessionsFromPanel([s]).catch(e.showError)},onLogout:()=>{e.logoutFromSettings().catch(e.showError)},onHostedProviderRoutingChanged:e.onHostedProviderRoutingChanged,onActivateNativeProvider:s=>{e.activateNativeProviderFromPanel(s).catch(e.showError)},onSaveAgenticBinding:(s,n)=>{e.saveAgenticBindingFromPanel(s,n).catch(e.showError)},onRefreshProviderUsage:()=>{e.refreshProviderUsageFromPanel().catch(e.showError)},onSpeechAudioModelChanged:e.onSpeechAudioModelChanged,onSpeechConversationModelChanged:e.onSpeechConversationModelChanged,onSaveHostedProviderSettings:s=>{e.saveHostedProviderSettingsFromPanel(s).catch(e.showError)},onSaveSpeechProviderSettings:()=>{e.saveSpeechProviderSettingsFromPanel().catch(e.showError)}})}function qi(e){f(document.getElementById("refresh-pwa-cache"),"click",()=>{e.cacheDiagnosticsController.ensureLoaded(!0).catch(e.showError)}),f(document.getElementById("clear-pwa-cache"),"click",()=>{e.cacheDiagnosticsController.clear().catch(e.showError)})}function Di(e){document.querySelectorAll("[data-dependency-choice]").forEach(t=>{f(t,"change",()=>{const s=Nt(t.dataset.dependencyChoice||"");if(!s)return;const n=e.appDependencies().find(i=>i.consumer_app_id===s.consumerAppId)?.dependencies.find(i=>i.alias===s.alias);if(!n)return;if(n.cardinality==="one"){e.saveDependencySelection(s.consumerAppId,s.alias,[s.providerAppId]).catch(e.showError);return}const a=new Set(n.selected_provider_app_ids);t.checked?a.add(s.providerAppId):a.delete(s.providerAppId),e.saveDependencySelection(s.consumerAppId,s.alias,Array.from(a)).catch(e.showError)})}),document.querySelectorAll("[data-dependency-save-default]").forEach(t=>{f(t,"click",()=>{const s=Nt(t.dataset.dependencySaveDefault||"");s&&e.saveDependencySelection(s.consumerAppId,s.alias,[s.providerAppId]).catch(e.showError)})})}function Nt(e){const[t,s,...n]=e.split(":"),a=n.join(":");return!t||!s||!a?null:{alias:s,consumerAppId:t,providerAppId:a}}function Ri(e){document.querySelectorAll("[data-app-toggle]").forEach(t=>{f(t,"change",()=>{const s=e.workspaceApps().find(n=>`${n.workspace_id}:${n.app_id}`===t.dataset.appToggle);s&&e.setWorkspaceAppStatus(s,t.checked).catch(e.showError)})}),document.querySelectorAll("[data-app-install]").forEach(t=>{f(t,"click",()=>{const s=e.workspaceApps().find(n=>`${n.workspace_id}:${n.app_id}`===t.dataset.appInstall);s&&e.installWorkspaceApp(s).catch(e.showError)})}),document.querySelectorAll("[data-app-uninstall]").forEach(t=>{f(t,"click",()=>{const s=e.workspaceApps().find(n=>`${n.workspace_id}:${n.app_id}`===t.dataset.appUninstall);s&&e.uninstallWorkspaceApp(s).catch(e.showError)})})}function Ti(e){document.querySelectorAll("[data-adapter-target]").forEach(t=>{f(t,"click",()=>{const s=t.dataset.adapterTarget;(s==="json"||s==="mongo")&&e.persistenceController.prepare(s).catch(e.showError)})}),f(document.getElementById("close-migration-modal"),"click",()=>{e.persistenceController.cancel()}),f(document.getElementById("cancel-migration"),"click",()=>{e.persistenceController.cancel()}),f(document.getElementById("validate-migration"),"click",()=>{e.persistenceController.validateDraft().catch(e.showError)}),document.querySelectorAll("[data-migration-field]").forEach(t=>{const s=n=>{const a=t.dataset.migrationField;if(a&&a in(e.persistenceController.viewState().targetDraft||{})){const i=!!e.persistenceController.viewState().migrationPlan;e.persistenceController.updateDraft(a,t.value,{render:n}),!n&&i&&Li()}};f(t,"input",()=>s(!1)),f(t,"change",()=>s(!0))}),f(document.getElementById("settings-delete-source"),"change",t=>{e.persistenceController.setDeleteSource(t.currentTarget.checked)}),f(document.getElementById("confirm-migration"),"click",()=>{e.persistenceController.apply().catch(e.showError)})}function Li(){const e=document.getElementById("confirm-migration");e&&(e.disabled=!0);const t=document.querySelector(".settings-migration-plan");if(!t)return;const s=t.querySelector(".material-symbols-rounded"),n=t.querySelector("strong"),a=t.querySelector("small");s&&(s.textContent="rule"),n&&(n.textContent="Dry run changed"),a&&(a.textContent="Validate the dry run again before applying migration."),t.querySelector(".settings-migration-collections")?.remove()}function Hi(e){let t=null,s=null,n="",a=null,i=null,r=null,o=!1;function c(){return{deleteSourceAfterMigration:o,migrationPlan:a,migrationProgress:r,migrationResult:i,migrationTarget:t,persistence:e.getPersistence(),targetDraft:s}}async function l(k){const b=e.getPersistence();if(!b||b.active_adapter.kind===k){m();return}t=k,s=Ui(k,b),n="",a=null,o=!1,r=null,e.setNotice(null),e.render()}function p(k,b,D={}){s&&(s={...s,[k]:b},a=null,n="",r=null,D.render!==!1&&e.render())}function u(k){o=k,e.render()}function m(){t=null,s=null,a=null,n="",r=null,e.render()}async function w(){if(!(!s||!t)){r={target:t,phase:"validating",title:`Dry run to ${t.toUpperCase()}`,detail:"Validating target adapter and collection copy plan before applying changes."},e.setNotice(null),e.render();try{const k=ot(s);a=await mn(k),n=Bt(k)}catch(k){throw r=null,a=null,n="",k}r=null,a.same_adapter&&e.setNotice({tone:"info",message:"The selected persistence adapter is already active."}),e.render()}}async function g(){if(!s||!t)return;const k=ot(s),b=Bt(k);if(!a||n!==b){await w();return}if(a.same_adapter)return;r={target:t,phase:"applying",title:`Migration to ${t.toUpperCase()}`,detail:"Copying the validated control-plane plan to the target adapter."},e.setNotice(null),e.render();try{i=await fn({...k,delete_source:o,restart_backend:!0})}catch($){throw r={target:t,phase:"failed",title:"Migration failed",detail:$ instanceof Error?$.message:"Unable to apply migration."},$}const D=t;t=null,s=null,a=null,n="",r={target:D,phase:"restarting",title:"Restart backend",detail:i.backend_restart?.detail||"Backend restart scheduled."},e.render(),await T(D)}async function T(k){const b=Date.now(),D=9e4;for(;Date.now()-b<D;){r={target:k,phase:"polling",title:"Verifying cutover",detail:"Waiting for the backend to become healthy with the new adapter."},e.render();const $=await e.requestPersistenceStatusQuiet();if($?.active_adapter.kind===k){e.setPersistence($);const A=i?.source_cleanup?.scheduled===!0;r={target:k,phase:"complete",title:"Migration complete",detail:A?`Active adapter: ${k.toUpperCase()}. Source cleanup is scheduled after health check.`:`Active adapter: ${k.toUpperCase()}. Source storage was preserved.`},e.setNotice({tone:"success",message:`Migration to ${k.toUpperCase()} complete.`}),e.render();return}await new Promise(A=>window.setTimeout(A,1500))}r={target:k,phase:"failed",title:"Verification not completed",detail:"The backend did not confirm the new adapter before the timeout. Check service health and logs."},e.setNotice({tone:"error",message:"Migration not confirmed before the timeout."}),e.render()}return{apply:g,cancel:m,prepare:l,setDeleteSource:u,updateDraft:p,validateDraft:w,viewState:c}}function Ui(e,t){const s=t.active_adapter;return{kind:e,json_root:s.json_root||"data/control-plane/json",mongodb_uri:s.mongo_uri||"mongodb://127.0.0.1:27017/maverick",mongodb_database:s.mongo_database||"maverick",mongodb_username:s.mongo_username||"",mongodb_password_ref:s.mongo_password_ref||""}}function ot(e){return{kind:e.kind,json_root:e.json_root.trim()||"data/control-plane/json",mongodb_uri:e.mongodb_uri.trim(),mongodb_database:e.mongodb_database.trim()||"maverick",mongodb_username:e.mongodb_username?.trim()||void 0,mongodb_password_ref:e.mongodb_password_ref?.trim()||void 0}}function Bt(e){return JSON.stringify(ot(e))}async function Oi(e){const t=e.settings?.workspace.workspace_id,s=e.state.hostedDraftModelId,n=Ni(e.settings,e.state.hostedDraftModelId);if(!n||!e.state.hostedDraftModelId){e.state.hostedProviderErrorModelId=e.state.hostedDraftModelId,e.state.hostedProviderError="Hosted provider not loaded.",e.render();return}e.state.isSavingHostedProvider=!0,e.state.hostedProviderError="",e.state.hostedProviderErrorModelId=e.state.hostedDraftModelId,e.render();try{const a=await ln({provider_id:n,model_id:e.state.hostedDraftModelId,openrouter_provider_routing:is(e.state,e.state.hostedDraftModelId)});if(e.getSettings()?.workspace.workspace_id!==t||!e.settings)return;const i={...e.getSettings(),provider:a};e.setSettings(i),ie(e.state,i,{hostedModelId:s}),document.querySelectorAll("[data-hosted-model-accordion]").forEach(r=>{r.dataset.hostedModelAccordion===s&&B(r)}),e.setNotice({tone:"success",message:"Hosted model settings updated."})}catch(a){e.state.hostedProviderErrorModelId=e.state.hostedDraftModelId,e.state.hostedProviderError=a instanceof Error?a.message:"Unable to update hosted model settings."}finally{e.state.isSavingHostedProvider=!1,e.render()}}function Ni(e,t){const s=e?.provider.hosted_text||null;return[s?.active_provider,...s?.available_providers||[]].filter(Boolean).find(i=>!i||i.status!=="active"?!1:(i.model_options||[]).some(r=>r.model_id===t))?.provider_id||s?.active_provider?.provider_id||""}async function Bi(e){const t=e.settings?.workspace.workspace_id,s=e.settings?.provider.speech_stt?.active_provider?.provider_id;if(!s||!e.state.speechAudioModelId||!e.state.speechConversationModelId){e.state.speechProviderError="Speech provider not loaded.",e.render();return}e.state.isSavingSpeechProvider=!0,e.state.speechProviderError="",e.render();try{const n=await dn({provider_id:s,audio_transcription_model_id:e.state.speechAudioModelId,conversation_model_id:e.state.speechConversationModelId});if(e.getSettings()?.workspace.workspace_id!==t||!e.settings)return;const a={...e.getSettings(),provider:n};e.setSettings(a),ie(e.state,a,{speech:!0}),B(".settings-speech-model-accordion"),e.setNotice({tone:"success",message:"Speech model settings updated."})}catch(n){e.state.speechProviderError=n instanceof Error?n.message:"Unable to update speech model settings."}finally{e.state.isSavingSpeechProvider=!1,e.render()}}function ji(e){let t="",s=0,n=0;function a(){t="",s+=1,n+=1,e.state.providerUsageItems=[],e.state.providerUsageError="",e.state.isLoadingProviderUsage=!1,e.state.usageHistory=null,e.state.usageHistoryFilters=st(),e.state.usageHistoryError="",e.state.isLoadingUsageHistory=!1}async function i(p=!1){const m=e.getSettings()?.workspace.workspace_id||"";if(!m){a();return}!p&&t===m||(t&&t!==m&&(e.state.usageHistoryFilters=st()),t=m,await Promise.all([r(m),o(m)]))}async function r(p,u){const m=++s;e.state.providerUsageError="",e.state.isLoadingProviderUsage=!0,e.render();try{const w=await rn();l(p)&&m===s&&(e.state.providerUsageItems=w.items)}catch(w){l(p)&&m===s&&(e.state.providerUsageError=w instanceof Error?w.message:"Provider usage unavailable")}finally{l(p)&&m===s&&(e.state.isLoadingProviderUsage=!1,e.render())}}async function o(p,u=!1){const m=++n,w=e.state.usageHistoryFilters,g=ss(w.timeRange),T={providerId:w.providerId,modelId:w.modelId};e.state.isLoadingUsageHistory=!0,e.state.usageHistoryError="",u&&(e.state.usageHistory=null),e.render();try{const k=await on(g.resolution,g.periods,T);l(p)&&m===n&&(e.state.usageHistory=k)}catch(k){l(p)&&m===n&&(e.state.usageHistoryError=k instanceof Error?k.message:"Token usage history unavailable")}finally{l(p)&&m===n&&(e.state.isLoadingUsageHistory=!1,e.render())}}function c(p){const u=e.state.usageHistoryFilters,m=Pn(u,p);if(Fi(u,m))return Promise.resolve();e.state.usageHistoryFilters=m;const w=u.providerId!==m.providerId||u.modelId!==m.modelId||u.timeRange!==m.timeRange,g=e.getSettings()?.workspace.workspace_id||"";return!w||!g?(e.render(),Promise.resolve()):o(g,!0)}function l(p){return e.getSettings()?.workspace.workspace_id===p}return{ensureLoaded:i,refresh:()=>i(!0),reset:a,updateUsageHistoryFilters:c}}function Fi(e,t){return e.metric===t.metric&&e.providerId===t.providerId&&e.modelId===t.modelId&&e.timeRange===t.timeRange}function zi(e){return e?`<div class="settings-notice settings-notice-${e.tone}">
    <span class="material-symbols-rounded" aria-hidden="true">${e.tone==="error"?"error":e.tone==="success"?"task_alt":"info"}</span>
    <span>${d(e.message)}</span>
    <button type="button" class="settings-icon-button" id="dismiss-notice" aria-label="Close">
      <span class="material-symbols-rounded" aria-hidden="true">close</span>
    </button>
  </div>`:""}function Wi(e){let t=0;return{reset:()=>{t++,e.state.pendingAgenticEnabled={},e.state.savingAgenticBindings.clear(),e.state.activatingNativeProviders.clear(),e.state.agenticBindingErrors={},e.state.nativeProviderErrors={}},activateProvider:async s=>{const n=t,a=e.getSettings()?.workspace.workspace_id;if(!e.state.activatingNativeProviders.has(s)){e.state.activatingNativeProviders.add(s),e.state.nativeProviderErrors[s]="",e.render();try{await pn(s);const i=await wt("models");if(n!==t||e.getSettings()?.workspace.workspace_id!==a||i.workspace.workspace_id!==a)return;ie(e.state,i),e.setSettings(i,"Connection enabled. Selected models are available in Chat.")}catch(i){if(n!==t)return;e.state.nativeProviderErrors[s]=i instanceof Error?i.message:"Unable to enable connection."}finally{n===t&&(e.state.activatingNativeProviders.delete(s),e.render())}}},save:async(s,n={})=>{const a=t,i=e.getSettings()?.workspace.workspace_id,r=s;if(e.state.savingAgenticBindings.has(r))return;const o=e.getSettings()?.agentic_admin?.items.find(g=>g.definition_id===s),c=Array.from(document.querySelectorAll("[data-agentic-binding-form]")).find(g=>g.dataset.agenticDefinitionId===s);if(!o||!c){e.state.agenticBindingErrors[r]="Agentic binding form is no longer available.",e.render();return}const l=g=>c.querySelector(`[data-agentic-field="${g}"]`),p=g=>!!l(g)?.checked,u=n.enabled??p("enabled");if(o.containment_status==="NO-GO"&&u){e.state.agenticBindingErrors[r]=`Remote agentic release is NO-GO: ${o.containment_reason||"contained by operator policy"}.`,e.render();return}if(u&&(o.execution_family===null||o.runtime_status!=="complete"||o.enable_eligible!==!0)){e.state.agenticBindingErrors[r]=`This model is unavailable: ${o.enable_blocked_reason||o.runtime_status_reason||o.blocked_reason||"runtime unavailable"}.`,e.render();return}const m=l("max_estimated_cost_usd")?.value.trim()||"",w=Math.round(Number(m)*1e6);if(m&&(!Number.isFinite(w)||w<0)){e.state.agenticBindingErrors[r]="Maximum cost must be a non-negative amount.",e.render();return}e.state.savingAgenticBindings.add(r),n.enabled!==void 0&&(e.state.pendingAgenticEnabled[r]=u),e.state.agenticBindingErrors[r]="",e.render();try{await cn({definition_id:s,binding_id:o.binding?.binding_id||null,credential_binding_id:l("credential_binding_id")?.value||null,enabled:u,is_default:n.enabled===!1?!1:p("is_default"),actor_policy:{allow_workspace_admins:p("allow_workspace_admins"),allowed_user_ids:o.binding?.actor_policy.allowed_user_ids||[],allowed_workspace_role_ids:p("allow_workspace_members")?["member"]:[],allowed_agent_type_ids:o.binding?.actor_policy.allowed_agent_type_ids||[]},policy_patch:{max_estimated_cost_microusd:m?w:null,require_confirmation_for_mutating:p("require_confirmation_for_mutating"),require_confirmation_for_destructive:p("require_confirmation_for_destructive")}});const g=await wt("models");if(a!==t||e.getSettings()?.workspace.workspace_id!==i||g.workspace.workspace_id!==i)return;ie(e.state,g),B(c),e.setSettings(g,`${o.display_name} binding updated for new sessions.`)}catch(g){if(a!==t)return;e.state.agenticBindingErrors[r]=g instanceof Error?g.message:"Unable to save agentic binding."}finally{a===t&&(delete e.state.pendingAgenticEnabled[r],e.state.savingAgenticBindings.delete(r),e.render())}}}}function Vi(e){let t=null,s="",n=!1,a=!1,i=!1;async function r(l=!1){if(!(a||!l&&t)){a=!0,s="",e.render();try{if(t=await Ns(),!t)throw new Error("Cache diagnostics are unavailable outside the Maverick shell.")}catch(p){s=jt(p,"Unable to inspect this browser cache.")}finally{a=!1,e.render()}}}async function o(){if(n||i)return;i=!0;let l=!1;try{l=await gt({title:"Clear this browser cache?",detail:"Remove cached Maverick data and local file copies from this browser. Server files, conversations and settings are preserved.",confirmLabel:"Clear cache"})}finally{i=!1}if(l){n=!0,s="",e.render();try{const p=await Bs();if(!p)throw new Error("Cache cleanup is unavailable outside the Maverick shell.");const{cleanup:u}=p;if(u.status!=="complete"||u.pendingCleanupCount>0)throw new Error("Cache cleanup is still pending. Persistent cache reads remain blocked; retry Clear cache.");t=p.dashboard,e.setNotice({tone:"success",message:u.removed===1?"1 cached entry removed.":`${u.removed} cached entries removed.`})}catch(p){s=jt(p,"Unable to clear this browser cache."),e.setNotice({tone:"error",message:s})}finally{n=!1,e.render()}}}function c(){return{dashboard:t,error:s,isClearing:n,isLoading:a}}return{clear:o,ensureLoaded:r,viewState:c}}function jt(e,t){return e instanceof Error&&e.message?e.message:t}let qe=null,Ft=null,V=[],Ie=[],pe="",De=[],re=[],Re=null,E=null,lt=Kt()?.workspaceId||"",L=da();const bs=Object.fromEntries(new URLSearchParams(window.location.search).entries());let W=Gt(bs)||Is,Y=$s(bs),Z=!0,j=null,zt="",Wt="";const J=es();let Ke="",Ae="",Vt=!1;const vt=vn({state:L.speechSynthesis,render:M,notify:e=>{j={tone:"success",message:e}}}),Ji=$n({state:L.computerUse,getSettings:()=>E,render:M,setSelection:e=>{E&&(E={...E,computer_use:e})},notify:e=>{j={tone:"success",message:e}}}),Ce=Hi({getPersistence:()=>Re,render:()=>M(),requestPersistenceStatusQuiet:wn,setNotice:e=>{j=e},setPersistence:e=>{Re=e}}),ne=Za({publishChanged:lr,render:()=>M(),setNotice:e=>{j=e}}),Oe=ji({getSettings:()=>E,render:()=>M(),state:L}),Te=xa({render:M,updated:(e,t)=>{re=re.map(s=>s.workspace_id===e.workspace_id&&s.app_id===e.app_id?{...s,status:t?"enabled":"disabled"}:s),ne.invalidate(),H.ensure("apps",!0)}}),dt=Wi({getSettings:()=>E,render:M,state:L,setSettings:(e,t)=>{E={...E,...e,runtime:E?.runtime||e.runtime,computer_use:E?.computer_use},j={tone:"success",message:t}}}),ht=Vi({render:M,setNotice:e=>{j=e}}),le=Vn({render:M,workspaceId:()=>E?.workspace.workspace_id||""});function ys(){return V.find(e=>e.user_id===Y)||V[0]}function $s(e){const t=ue(e.user_id)||ue(e.selected_user_id)||ue(e.id);if(t)return t;const s=ue(e.app_page),n=/^users\/([^/?#]+)$/.exec(s);if(!n?.[1])return"";try{return decodeURIComponent(n[1])}catch{return n[1]}}function ue(e){return typeof e=="string"?e.trim():""}function Gi(e){const t=Gt(e),s=$s(e),n=ue(e.setting);Ae=["default-model","voice","password","cache","computer-use"].includes(n)?n:"",t&&(W=t),s&&s!==Y&&(Y=s),H.cancelExcept(ut(W)),M(),Be()}function Ki(e){e.id===zt||window.parent===window||(zt=e.id,window.parent.postMessage({type:"maverick.app.selection-changed",owner_app_id:"settings",selection:{page_id:e.id}},"*"))}function Qi(e){!e||e.user_id===Wt||window.parent===window||(Wt=e.user_id,window.parent.postMessage({type:"maverick.app.selection-changed",owner_app_id:"settings",selection:{user_id:e.user_id}},"*"))}function Ne(){window.parent!==window&&window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"settings",resource:"users"},"*")}const H=Sn({publish:(e,t)=>{if(e==="registry"){const s=t;Ie=s.items,pe=s.workspace_id||E?.workspace.workspace_id||""}else if(e==="users")V=t.items,(!Y||!V.some(s=>s.user_id===Y))&&(Y=V[0]?.user_id||"");else if(e==="workspaces")De=t.items;else if(e==="apps")re=t.items;else if(e==="persistence")Re=t;else if(e==="sessions")E?E=it(E,t):Se=t;else{const s=t,n=lt;n&&n!==s.workspace.workspace_id&&(qe?.unmountUsageVisualizations(),H.reset(),Ys(),E=null,V=[],De=[],re=[],Re=null,Se=null,Ie=[],pe="",L.savedDrafts=null,ne.reset(),le.reset(),Oe.reset(),vt.reset(),dt.reset(),Te.reset(),j=null,Object.assign(J,es()),queueMicrotask(()=>{M(),Be()})),Ie.length&&!pe&&(pe=s.workspace.workspace_id),lt=s.workspace.workspace_id;const a=e==="models"||e==="voice";E=En(E,s,e),Se&&(E=it(E,Se)),(a||e==="computer-use")&&ie(L,E)}},changed:()=>M()});let Se=null;async function Be(e=!1){const t=W;t==="workspace-apps"&&H.ensure("registry",e),await Promise.all(ut(t).map(s=>H.ensure(s,e))),W===t&&(t==="app-links"&&H.state("apps").loaded&&H.state("context").loaded&&await ws(e),t==="usage"&&E&&(Oe.ensureLoaded(e),Ft||=qs(()=>import("./usageVisualizations-C29KQ_b0.js"),__vite__mapDeps([0,1])).then(s=>{qe=s,W==="usage"&&M()}).catch(s=>{Ft=null,W==="usage"&&Le(s)})),t==="voice"&&E&&vt.load(E.workspace.workspace_id,e),t==="learning"&&E&&(le.load(e),H.ensure("models")),t==="cache"&&ht.ensureLoaded(e))}async function Yi(){await Be(!0)}async function ws(e=!1){await ne.ensureLoaded(E?.workspace.workspace_id||"",re,e)}async function Xi(e){const t=new FormData(e),s=await Yn({username:String(t.get("username")||""),password:String(t.get("password")||""),display_name:String(t.get("display_name")||""),email:String(t.get("email")||""),platform_role:String(t.get("platform_role")||"member")});V=[...V,s],Y=s.user_id,e.reset(),B(e),j={tone:"success",message:"User created."},M(),Ne()}async function Zi(e,t){const s=new FormData(e),n=await Xn(t.user_id,{display_name:String(s.get("display_name")||""),email:String(s.get("email")||""),platform_role:String(s.get("platform_role")||"member"),account_type:String(s.get("account_type")||"standard"),is_active:s.get("is_active")==="on"});V=V.map(a=>a.user_id===n.user_id?n:a),B(e),j={tone:"success",message:"User updated."},M(),Ne()}async function xi(e,t){const s=new FormData(e),n=String(s.get("password")||""),a=String(s.get("password_confirmation")||"");if(n!==a)throw new Error("Passwords do not match");await Zn(t.user_id,n),e.reset(),B(e),j={tone:"success",message:"Password updated."},M()}async function er(e){const t=e.display_name||e.username;await gt({title:`Delete ${t}?`,detail:"This permanently removes the user account and its workspace memberships. This action cannot be undone.",confirmLabel:"Delete user"})&&(await xn(e.user_id),Y="",j={tone:"success",message:`${t} deleted.`},V=V.filter(s=>s.user_id!==e.user_id),Y=V[0]?.user_id||"",M(),Ne())}async function tr(e){const t=De.map(n=>{const a=document.querySelector(`[data-workspace-enabled="${n.workspace_id}"]`),i=document.querySelector(`[data-workspace-role="${n.workspace_id}"]`);return a?.checked?{workspace_id:n.workspace_id,role:i?.value||"member"}:null}).filter(n=>!!n),s=await ea(e.user_id,t);V=V.map(n=>n.user_id===s.user_id?s:n),B(".settings-memberships"),j={tone:"success",message:"Workspace access updated."},M(),Ne()}async function sr(e){await ta(e),ne.invalidate(),await H.ensure("apps",!0)}async function nr(e,t){await Te.setEnabled(e,t)}async function ar(e){await na(e),ne.invalidate(),await H.ensure("apps",!0)}async function ir(e,t,s){await ne.saveDependencySelection(e,t,s)}async function rr(e){if(!E)return;const t=E.workspace.workspace_id,s=mt(E,J),n=e?.length?s.filter(o=>e.includes(o.session_id)):s;if(!n.length)return;const a=J.scope==="server"?"the entire server":`workspace ${E.workspace.name}`,i=n.filter(o=>!["closed","completed","failed","terminated","stopped"].includes(o.status)).length;if(!await gt({title:`Delete ${n.length} runtime session${n.length===1?"":"s"}?`,detail:`Scope: ${a}. ${i} sessions may have active agents. Their agents will stop and their conversations, turns and runtime files will be permanently removed.`,confirmLabel:"Delete sessions"})||E.workspace.workspace_id!==t)return;const r=n.map(o=>o.session_id);L.cleanupError="",L.clearingAllRuntime=!e?.length,r.forEach(o=>L.cleaningSessionIds.add(o)),M();try{const o=await un(r);if(E.workspace.workspace_id!==t)return;or(o),E=it(E,o),j={tone:"success",message:`${o.cleared_sessions} runtime sessions deleted.`}}catch(o){L.cleanupError=o instanceof Error?o.message:"Unable to delete runtime sessions."}finally{r.forEach(o=>L.cleaningSessionIds.delete(o)),L.clearingAllRuntime=!1,M()}}function or(e){e.deleted_threads<=0||window.parent===window||(window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"chat",resource:"threads"},"*"),e.deleted_thread_ids.forEach(t=>{window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"chat",resource:"threads",deleted_thread_id:t},"*")}))}function lr(e,t){window.parent!==window&&window.parent.postMessage({type:"maverick.app.dependencies-changed",app_id:e,status:t.status},"*")}async function dr(){if(window.parent&&window.parent!==window){window.parent.postMessage({type:"maverick.shell.logout"},"*");return}await gn(),window.location.href="/"}function cr(){return Ra(E,L,W)}function M(){const e=document.getElementById("app");if(!e)return;Vt||(Xs(e),Vt=!0);const t=performance.now(),s=As(W),n=ut(W);Z=n.some(l=>!H.state(l).loaded&&!H.state(l).error);const a=n.filter(l=>H.state(l).error&&!H.state(l).loaded),i=n.filter(l=>H.state(l).error&&H.state(l).loaded),r=ys();Ke==="usage"&&(W!=="usage"||Z||a.length)&&qe?.unmountUsageVisualizations();const o=Ke!==W;Ke=W;const c=Z?Na(s):a.length?a.map(l=>`<section class="settings-card"><h2>Unable to load ${d(l)}</h2><p role="alert">${d(H.state(l).error)}</p><button type="button" data-retry-resource="${l}">Retry</button></section>`).join(""):Ci({appLinksController:ne,cacheDiagnosticsController:ht,page:s,persistenceController:Ce,platformSettingsHtml:cr,sessionsHtml:()=>E?Cn(E,L,J):"",usageHtml:()=>Un(L),learningHtml:()=>Kn(le.viewState(),E?.provider.available_providers?.find(l=>l.provider_id==="codex")?.model_options||[]),selectedUser:r,users:V,workspaceApps:Te.apps(re).map(l=>({...l,logo:l.workspace_id===pe&&Ie.find(p=>p.app_id===l.app_id)?.logo||null})),savingAppKeys:Te.savingKeys(),workspaces:De});if(Zs(e,`<main class="settings-shell"><section class="settings-main"><div class="settings-content" data-render-key="${d(Cs(lt,s.id,r?.user_id))}">
    <header class="detail-header"><div class="detail-title-block"><h2>${d(s.title)}</h2><span class="detail-title-separator" aria-hidden="true"></span><p>${d(s.summary)}</p></div>
    ${E?`<div class="settings-context"><span>${d(E.workspace.name)}</span><span>${d(E.user.display_name||E.user.username)}</span><button type="button" id="settings-logout" class="settings-secondary">Logout</button></div>`:""}</header>
    ${zi(j)}${i.map(l=>`<p role="alert">${d(H.state(l).error)} <button type="button" data-retry-resource="${l}">Retry</button></p>`).join("")}${c}
    </div></section>${vi(Ce.viewState())}</main>`),pr(),In(Ce.cancel),le.setVisible(W==="learning"&&at()&&!Z),W==="usage"&&!Z&&!a.length&&qe?.mountUsageVisualizations({history:L.usageHistory,filters:L.usageHistoryFilters,isLoading:L.isLoadingUsageHistory,onFiltersChange:Oe.updateUsageHistoryFilters,settings:E}),o&&document.querySelector(".settings-main")?.scrollTo?.(0,0),Ki(s),!Z&&["users","workspace-access"].includes(W)&&Qi(r),Ae&&!Z){const l={"default-model":"[data-agentic-model-toggle]",voice:"#settings-tts-engine",password:"#reset-password input",cache:"#clear-pwa-cache","computer-use":"#settings-computer-use-mode"},p=document.querySelector(l[Ae]);p&&(p.closest("details")?.setAttribute("open",""),p.focus(),p.scrollIntoView?.({block:"center"}),Ae="")}performance.clearMeasures("settings.render"),performance.measure("settings.render",{start:t,end:performance.now()})}function pr(){en(),document.querySelectorAll("[data-user-discard]").forEach(e=>f(e,"click",()=>{const t=e.closest("form, #workspace-assignments");t&&(t instanceof HTMLFormElement&&t.reset(),B(t),M())})),document.querySelectorAll("[data-speech-discard]").forEach(e=>f(e,"click",()=>{ie(L,E,{speech:!0}),B(".settings-speech-model-accordion"),M()})),document.querySelectorAll("[data-hosted-discard]").forEach(e=>f(e,"click",()=>{ie(L,E,{hostedModelId:e.dataset.hostedDiscard}),B("[data-hosted-model-accordion]"),M()})),f(document.getElementById("settings-refresh-app-links"),"click",()=>{ws(!0)}),document.querySelectorAll("[data-retry-resource]").forEach(e=>f(e,"click",()=>{H.ensure(e.dataset.retryResource,!0).then(()=>Be())})),f(document.getElementById("settings-session-search"),"input",e=>{J.query=e.target.value,J.page=0,M()}),f(document.getElementById("settings-session-status"),"change",e=>{J.status=e.target.value,J.page=0,M()}),f(document.getElementById("settings-session-scope"),"change",e=>{J.scope=e.target.value==="server"?"server":"workspace",J.page=0,J.status="",B(".settings-session-filters"),M()}),f(document.getElementById("settings-sessions-prev"),"click",()=>{J.page-=1,M()}),f(document.getElementById("settings-sessions-next"),"click",()=>{J.page+=1,M()}),f(document.getElementById("create-workspace"),"submit",e=>{e.preventDefault();const t=e.target;q("/api/workspaces",{method:"POST",body:JSON.stringify(Object.fromEntries(new FormData(t)))}).then(async()=>{t.reset(),B("#create-workspace"),await H.ensure("workspaces",!0),await H.ensure("apps",!0),j={tone:"success",message:"Workspace created."},M()}).catch(Le)}),vt.bind(),le.bind(),Ji.bind(),Pi({clearRuntimeSessionsFromPanel:rr,cacheDiagnosticsController:ht,createUser:Xi,deleteSelectedUser:er,dismissNotice:()=>{j=null,M()},installWorkspaceApp:sr,logoutFromSettings:dr,onHostedProviderRoutingChanged:(e,t,s)=>{ga(L,E,e,t,s),M()},saveAgenticBindingFromPanel:dt.save,activateNativeProviderFromPanel:dt.activateProvider,onSpeechAudioModelChanged:e=>{pa(L,e),M()},onSpeechConversationModelChanged:e=>{ua(L,e),M()},persistenceController:Ce,refreshProviderUsageFromPanel:Oe.refresh,render:M,resetSelectedUserPassword:xi,saveDependencySelection:ir,saveHostedProviderSettingsFromPanel:e=>(e&&ca(L,E,e),Oi(Jt())),saveSpeechProviderSettingsFromPanel:()=>Bi(Jt()),selectedUser:ys,selectUser:e=>{Y=e,M()},setWorkspaceAppStatus:nr,showError:Le,uninstallWorkspaceApp:ar,updateMemberships:tr,updateSelectedUser:Zi,workspaceApps:()=>re,appDependencies:()=>ne.viewState().dependencies})}function Jt(){return{render:M,setNotice:e=>{j=e},setSettings:e=>{E=e},settings:E,getSettings:()=>E,state:L}}function Le(e){j={tone:"error",message:e instanceof Error?e.message:"Unexpected error"},M()}Qn({navigate:Gi,visibilityChanged:e=>le.setVisible(W==="learning"&&e&&!Z)});Yi().catch(Le);export{ts as U,fr as a,tt as b,mr as c,gr as d,ss as u};
