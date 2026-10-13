const __vite__mapDeps=(i,m=__vite__mapDeps,d=(m.f||(m.f=["assets/usageVisualizations-D_vPiW1S.js","assets/pages-ZxBuXJVj.js"])))=>i.map(i=>d[i]);
import{i as ft,P as Pn,a as Tn,b as qn,s as Xt,D as Dn,c as Rn,d as Ln}from"./pages-ZxBuXJVj.js";const Hn="modulepreload",Un=function(e){return"/apps/settings/"+e},St={},On=function(t,n,s){let a=Promise.resolve();if(n&&n.length>0){let c=function(l){return Promise.all(l.map(p=>Promise.resolve(p).then(u=>({status:"fulfilled",value:u}),u=>({status:"rejected",reason:u}))))};document.getElementsByTagName("link");const r=document.querySelector("meta[property=csp-nonce]"),o=r?.nonce||r?.getAttribute("nonce");a=c(n.map(l=>{if(l=Un(l),l in St)return;St[l]=!0;const p=l.endsWith(".css"),u=p?'[rel="stylesheet"]':"";if(document.querySelector(`link[href="${l}"]${u}`))return;const m=document.createElement("link");if(m.rel=p?"stylesheet":Hn,p||(m.as="script"),m.crossOrigin="",m.href=l,o&&m.setAttribute("nonce",o),document.head.appendChild(m),p)return new Promise((S,g)=>{m.addEventListener("load",S),m.addEventListener("error",()=>g(new Error(`Unable to preload CSS for ${l}`)))})}))}function i(r){const o=new Event("vite:preloadError",{cancelable:!0});if(o.payload=r,window.dispatchEvent(o),!o.defaultPrevented)throw r}return a.then(r=>{for(const o of r||[])o.status==="rejected"&&i(o.reason);return t().catch(i)})},Nn=e=>["ready","rolled_back","failed","rollback_requested"].includes(e.status);class qe extends Error{constructor(t,n){super(t),this.code=t,this.status=n}}async function ie(e,t,n){const s=await fetch("/api/admin/installation"+(e==="inspect"?"":"/"+e),{method:t===void 0?"GET":"POST",credentials:"same-origin",signal:n,headers:{Accept:"application/json",...t===void 0?{}:{"Content-Type":"application/json"}},...t===void 0?{}:{body:JSON.stringify(t)}}),a=await s.json();if(!s.ok)throw new qe(a.error||"installation_operation_failed",s.status);return a}async function Bn(e,t){if(!window.isSecureContext)throw new qe("secure_connection_required",400);const n=await fetch("/api/secrets",{method:"POST",credentials:"same-origin",signal:t,headers:{"Content-Type":"application/json"},body:JSON.stringify({label:"Cloudflare DNS",kind:"api_key",alias:"cloudflare-dns-"+crypto.randomUUID().slice(0,8),raw_value:e})}),s=await n.json();if(!n.ok)throw new qe(s.error||"credential_save_failed",n.status);return"platform:secrets/"+s.secret.secret_id}const xe=e=>String(e??"").replace(/[&<>"']/g,t=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[t]),O=xe,he=(e,t)=>e.startsWith("https://")?`<a href="${O(e)}" target="_blank" rel="noopener noreferrer">${O(t)} ↗</a>`:"",jn={queued:"Queued",preparing:"Preparing DNS & certificates",waiting_dns:"Waiting for DNS",waiting_ca:"Waiting for certificate authority",waiting_external_actions:"Provider update needed",activating:"Activating address",verifying:"Checking the new connection",rolling_back:"Restoring previous setup",rolled_back:"Previous setup restored",ready:"Ready",failed:"Needs attention",rollback_requested:"Restoration requested"},Fn=e=>jn[e]||e,zn={dns_zone_not_authorized:"This token cannot access the domain. Add Zone · DNS · Edit and Zone · Zone · Read for this domain.",dns_access_denied:"Cloudflare rejected this connection. Check the token permissions in Vault.",dns_automation_connection_required:"Connect Cloudflare to automate wildcard certificates and renewal. Other providers can delegate DNS to Cloudflare while keeping the domain at the same registrar.",invalid_hostname:"Enter a public domain such as maverick.example.com, without a path or port.",invalid_server_ip:"Enter the public IP address of this server.",public_server_ip_required:"Use the public server IP.",stale_installation_plan:"The setup changed. Review a fresh plan before applying.",installation_change_in_progress:"An installation change is already running. Follow its progress below.",wrong_server_at_target_address:"The address reaches another server. Check the public IP before retrying.",secure_connection_required:"Open setup over HTTPS or a local connection before saving a credential.",admin_required:"Sign in with a platform administrator account to configure this installation.",plan_integrity_failed:"This plan changed after review. Create a fresh plan.",renewal_verification_failed:"The automatic renewal test failed. Check DNS access before retrying."},vt=e=>zn[e]||"The operation could not complete. Diagnostic: "+e.replaceAll("_"," ");function Wn(e){const t=e.configuration,n=e.worker?.checked_at&&Date.now()-Date.parse(e.worker.checked_at)<1200*1e3;return`<section class="installation-card"><div class="installation-card-heading"><div><p class="installation-eyebrow">This installation</p><h2>${O(t.hostname||"Choose your address")}</h2></div><span class="installation-badge">${t.managed?"Managed":"Setup available"}</span></div>
    <div class="installation-facts"><div><span>Public address</span><strong>${t.public_url?he(t.public_url,t.public_url):"Not configured"}</strong></div><div><span>Automation</span><strong>${n?"Worker online":"Worker unavailable"}</strong></div><div><span>Certificate renewal</span><strong>${O(e.worker?.renewal_state||(t.managed?"Scheduled":"Complete setup to manage"))}</strong></div></div>
    ${n?"":'<p class="installation-muted">The server administrator can enable automation with <code>sudo /usr/bin/python3 scripts/deploy/install_installation_worker.py</code>.</p>'}
    ${e.requirements.length?`<details><summary>Service connections</summary>${e.requirements.map(s=>`<div class="installation-notice"><strong>${O(s.label)}</strong><p>${s.configured?"Provider configured · check registration when changing address":"Connection required · web setup can continue"}</p><code>${O(s.url)}</code>${s.provider_url?`<p>${he(s.provider_url,"Open provider")}</p>`:""}</div>`).join("")}</details>`:""}
    <div class="installation-actions"><button type="button" data-installation-action="verify">Check connection</button><a href="${O(t.public_url+"/setup")}" target="_blank" rel="noopener">Open recovery setup ↗</a></div></section>`}function Vn(e,t){const n=e.blocking_issues.some(s=>s.code==="dns_automation_connection_required");return`<section class="installation-card"><p class="installation-eyebrow">Review your setup</p><h2>${O(e.hostname)}</h2><p class="installation-muted">Server ${O(e.target_ip)} · DNS only · ${n?"Connect DNS automation to enable renewal":"HTTPS with automatic renewal"}</p>
    <ul class="installation-records">${e.dns_changes.map(s=>`<li><code>${O(s.name)}</code><span>${s.action==="keep"?"Already correct":O(s.after?.type+" → "+s.after?.content)}</span></li>`).join("")}</ul>
    <p class="installation-muted">Certificates: ${e.certificate_names.map(O).join(", ")}</p>
    ${e.blocking_issues.map(s=>`<div class="installation-notice">${s.code==="dns_delegation_pending"?`Set these nameservers at your registrar once, then Maverick will continue automatically: <ul>${(s.nameservers||[]).map(a=>`<li><code>${O(a)}</code></li>`).join("")}</ul>`:O(vt(s.code))}</div>`).join("")}
    ${e.external_actions.length?"<p>Keep the current provider callback registered until the new connection is ready. Maverick will pause for your confirmation.</p>":""}
    <div class="installation-actions"><button class="installation-primary" type="button" data-installation-action="apply" ${n||t?"disabled":""}>Apply setup</button>${e.token_template_url?he(e.token_template_url,"Scoped token template"):""}</div></section>`}function Jn(e,t){const n=!["ready","rolled_back","failed","rollback_requested"].includes(e.status);return`<section class="installation-card" aria-label="Installation progress"><div class="installation-card-heading"><h2>${O(Fn(e.status))}</h2><span class="installation-badge">${n?"In progress":"Completed check"}</span></div>
    <ol class="installation-steps"><li>DNS & delegation</li><li>Certificates & renewal test</li><li>Provider connections</li><li>Activate & verify</li></ol>
    <p class="installation-muted" role="status">${n?"This operation continues on the server if you close this page.":""}${e.retry_at?" Next check: "+O(new Date(e.retry_at).toLocaleString()):""}</p>
    ${e.error_code?`<p role="alert">${O(vt(e.error_code))}</p>`:""}
    ${e.status==="waiting_external_actions"&&t?`<form data-installation-confirm="${O(e.job_id)}"><p>Add each new address in its provider console, then confirm.</p>${t.external_actions.map(s=>`<label class="installation-confirm-row"><input type="checkbox" name="action_id" value="${O(s.id)}" ${e.confirmed_actions?.includes(s.id)?"checked":""}><span><strong>${O(s.label)}</strong><code>${O(s.url)}</code>${s.provider_url?he(s.provider_url,"Open provider"):""}</span></label>`).join("")}<button class="installation-primary" type="submit">Confirm provider updates</button></form>`:""}
    ${e.verification?xt(e.verification):""}
    ${e.status==="ready"&&t?.change_kind==="address_change"?'<p class="installation-muted">Use the new address for saved server connections and installed apps. Saved web links on this server will forward to the new address.</p>':""}
    <div class="installation-actions">${e.status==="failed"?'<button type="button" data-installation-action="retry">Retry</button>':""}${e.status!=="rolled_back"&&e.status!=="rollback_requested"?'<button type="button" data-installation-action="rollback-review">Restore previous setup</button>':""}${e.status==="ready"&&t?he(t.public_url,"Open Maverick"):""}</div>
    <div data-installation-rollback hidden><p>Restore the DNS and address settings saved before this change. Provider registrations remain under your control.</p><button type="button" data-installation-action="rollback">Confirm restoration</button></div></section>`}function xt(e){return`<div class="installation-verification" role="status"><strong>${e.healthy?"Connection verified":"Some connections need attention"}</strong><ul>${e.checks.map(t=>`<li><code>${O(t.host)}</code><span>${t.healthy?"HTTPS ready":O(t.error||"Unavailable")}</span></li>`).join("")}</ul></div>`}function Gn(e){let t,n,s,a,i=!1,r=0;const o=new Map;let c=!1,l;const p=new Set;e.classList.add("installation-view"),e.innerHTML=`<div data-installation-overview><p role="status">Loading installation…</p></div><div data-installation-message role="status" aria-live="polite"></div>
    <form class="installation-card" data-installation-form><p class="installation-eyebrow">Address & connection</p><h2>Give Maverick a home</h2><p class="installation-muted">Use a domain you own. Maverick connects DNS, secures the address and checks its apps.</p>
    <label class="installation-field">Public address<input data-settings-controlled name="address" placeholder="maverick.example.com" required autocomplete="url" spellcheck="false"></label>
    <div class="installation-columns"><label class="installation-field">DNS provider<select data-settings-controlled name="dns_provider"><option value="cloudflare">Cloudflare · automatic</option><option value="manual">Another provider · guided</option></select></label>
    <label class="installation-field">Vault connection<select data-settings-controlled name="dns_secret_ref" aria-label="Vault connection"><option value="">Choose a connection</option></select></label></div>
    <details data-installation-credential><summary>Add a Cloudflare connection</summary><p class="installation-muted">Create a token with Zone · DNS · Edit and Zone · Zone · Read, restricted to your domain. The token is saved in Vault.</p><a href="https://dash.cloudflare.com/profile/api-tokens" target="_blank" rel="noopener noreferrer">Create a token ↗</a>
    <label class="installation-field">API token<input data-settings-controlled data-installation-token type="password" autocomplete="new-password" spellcheck="false"></label><button type="button" data-installation-action="save-token">Save in Vault</button></details>
    <details data-installation-server><summary>Server settings</summary><label class="installation-field">Public server IP<input data-settings-controlled name="target_ip" placeholder="Detected automatically" required spellcheck="false"></label><p class="installation-muted">Check this value if the server uses NAT or a separate public IP.</p></details>
    <div class="installation-actions"><button class="installation-primary" type="submit">Review setup</button></div></form><div data-installation-plan></div><div data-installation-job></div><div data-installation-verification></div>`;const u=P=>e.querySelector(P),m=u("[data-installation-form]"),S=u("[data-installation-token]"),g=(P,M=!1)=>{if(c)return;const E=u("[data-installation-message]");E.textContent=P,E.setAttribute("role",M?"alert":"status")};function T(){if(c)return;const P=e.querySelector("[data-installation-confirm]");P&&o.set(P.dataset.installationConfirm,new FormData(P).getAll("action_id").map(String)),u("[data-installation-plan]").innerHTML=n?Vn(n,i):"",u("[data-installation-job]").innerHTML=a?Jn(a,s):"",a&&o.has(a.job_id)&&e.querySelectorAll("[data-installation-confirm] input").forEach(M=>{M.checked=o.get(a.job_id).includes(M.value)}),e.querySelectorAll("[data-installation-job] button").forEach(M=>{M.disabled=i}),m.querySelectorAll("button").forEach(M=>{M.disabled=i})}async function $(P,M=!0){const E=new AbortController;p.add(E),M&&(r+=1,i=!0,T(),g("Working…"));try{const _=await P(E.signal);return c?void 0:(M&&g(""),_)}catch(_){!c&&!E.signal.aborted&&g(_ instanceof qe?vt(_.code):"Reconnecting to the server. Progress will resume automatically.",!0);return}finally{p.delete(E),M&&(i=!1,T())}}async function b(P=!1){const M=r,E=await $(_=>ie("inspect",void 0,_),!1);if(!c){if(E&&M===r){t=E,u("[data-installation-overview]").innerHTML=Wn(t);const _=u("[name=dns_secret_ref]"),h=_.value;if(_.innerHTML='<option value="">Choose a connection</option>'+t.dns_credentials.map(f=>`<option value="${xe(f.ref)}">${xe(f.label)}</option>`).join(""),_.value=t.dns_credentials.some(f=>f.ref===h)?h:t.dns_credentials[0]?.ref||"",P){u("[name=address]").value=t.configuration.hostname;const f=t.configuration.target_ip||t.worker?.public_ip||"";u("[name=target_ip]").value=f,u("[data-installation-server]").open=!f}if(a=t.latest_job||a,a){const f=await $(y=>ie("status",{job_id:a.job_id},y),!1);f&&M===r&&(a=f.job,s=f.plan)}T()}c||(l=setTimeout(()=>{b()},a&&!Nn(a)?5e3:3e4))}}const R=async P=>{const M=P.target;if(M===m){if(P.preventDefault(),i)return;const E=new FormData(m),_=await $(h=>ie("plan",Object.fromEntries(E.entries()),h));_&&(n=_,T(),u("[data-installation-plan]").scrollIntoView?.({block:"nearest",behavior:"smooth"}))}else if(M.matches("[data-installation-confirm]")){if(P.preventDefault(),i||!a)return;const E=await $(_=>ie("confirm",{job_id:a.job_id,action_ids:new FormData(M).getAll("action_id")},_));E&&(a=E,T())}},w=async P=>{const M=P.target.closest("[data-installation-action]")?.dataset.installationAction;if(!(!M||i)){if(M==="rollback-review"){u("[data-installation-rollback]").removeAttribute("hidden");return}if(M==="save-token"){if(!S.value.trim()){g("Enter the Cloudflare API token.",!0);return}const E=await $(_=>Bn(S.value.trim(),_));S.value="",E&&(u("[data-installation-credential]").open=!1,l&&clearTimeout(l),await b(),c||(u("[name=dns_secret_ref]").value=E))}else if(M==="verify"){const E=await $(_=>ie("verify",void 0,_));E&&(u("[data-installation-verification]").innerHTML=xt(E.verification))}else if(M==="apply"&&n){const E=await $(_=>ie("apply",{plan_id:n.plan_id},_));E&&(a=E,s=n,n=void 0,T(),l&&clearTimeout(l),b())}else if(["retry","rollback"].includes(M)&&a){const E=await $(_=>ie(M,{job_id:a.job_id},_));E&&(a=E,T(),l&&clearTimeout(l),b())}}},C=P=>{P.target.closest("[data-installation-form]")&&(n=void 0,T())},B=P=>C(P);return e.addEventListener("change",B),e.addEventListener("submit",R),e.addEventListener("click",w),e.addEventListener("input",C),b(!0),{destroy(){c=!0,l&&clearTimeout(l),p.forEach(P=>P.abort()),S.value="",e.replaceChildren(),e.removeEventListener("submit",R),e.removeEventListener("click",w),e.removeEventListener("input",C),e.removeEventListener("change",B)}}}function Kn(){let e=null,t;return{attach(n){e!==n&&(t?.destroy(),e=n,t=n?Gn(n):void 0)}}}let et=!0;const $e=new Set;let ke=null;function tt(e={}){return et&&!globalThis.document?.hidden&&(e.requireOnline===!1||globalThis.navigator?.onLine!==!1)}function Qn(e,t={}){if(typeof window>"u")return e(!0),()=>{};const n={notify:e,options:t,previous:tt(t)};if($e.add(n),!ke){const s=()=>{for(const i of $e){const r=tt(i.options);r!==i.previous&&(i.previous=r,i.notify(r))}},a=i=>{!ft(i)||i.data?.type!=="maverick.app.visibility-changed"||typeof i.data.visible!="boolean"||(et=i.data.visible,s())};window.addEventListener?.("message",a),window.addEventListener?.("online",s),window.addEventListener?.("offline",s),globalThis.document?.addEventListener("visibilitychange",s),ke=()=>{window.removeEventListener?.("message",a),window.removeEventListener?.("online",s),window.removeEventListener?.("offline",s),globalThis.document?.removeEventListener("visibilitychange",s)}}return e(n.previous),()=>{$e.delete(n),$e.size||(ke?.(),ke=null,et=!0)}}const Zn=256;function en(){if(typeof window>"u")return null;const e=window.__MAVERICK_APP_FRAME_CONTEXT__;if(!e||typeof e!="object"||Array.isArray(e))return null;const t=e;return!Et(t.app_id)||!Et(t.workspace_id)?null:{appId:t.app_id,workspaceId:t.workspace_id}}function Et(e){return typeof e=="string"&&e.trim()===e&&e.length>0&&e.length<=Zn&&!/[\u0000-\u001f\u007f]/u.test(e)}const Yn="maverick.pwa.cache-operations.request.v1",Xn="maverick.pwa.cache-operations.accepted.v1",xn="maverick.pwa.cache-operations.result.v1",es=750,ts=1e4;function ns(e={}){return tn("diagnostics",e).then(t=>t?.dashboard??null)}function ss(e={}){return tn("clear",e).then(t=>t?.cleanup?{cleanup:t.cleanup,dashboard:t.dashboard}:null)}async function tn(e,t){const n=t.parentWindow??ls();if(!n)return null;const s=t.parentOrigin===void 0?ds():nt(t.parentOrigin);if(!s)return null;const a=(t.createMessageChannel??(()=>new MessageChannel))(),i=cs(),r={action:e,app_id:"settings",request_id:i,type:Yn};return new Promise((o,c)=>{let l=!1,p=!1,u=globalThis.setTimeout(()=>S(null),At(t.acceptanceTimeoutMs,es));function m(){globalThis.clearTimeout(u),a.port1.close()}function S(T){p||(p=!0,m(),o(T))}function g(){p||(p=!0,m(),c(new Error("Maverick cache diagnostics are unavailable.")))}a.port1.addEventListener("message",T=>{const $=ne(T.data);if(!$||$.app_id!=="settings"||$.request_id!==i)return;if($.type===Xn){if(l)return;l=!0,globalThis.clearTimeout(u),u=globalThis.setTimeout(g,At(t.resultTimeoutMs,ts));return}if(!l||$.type!==xn)return;if($.status==="unavailable"){S(null);return}if($.status!=="ok"){g();return}const b=as($.dashboard),R=$.cleanup===void 0?void 0:os($.cleanup);if(!b||e==="clear"&&!R){g();return}S({...R?{cleanup:R}:{},dashboard:b})}),a.port1.start();try{n.postMessage(r,s,[a.port2])}catch{S(null)}})}function as(e){const t=ne(e),n=is(t?.diagnostics),s=rs(t?.metrics);return n&&s?{diagnostics:n,metrics:s}:null}function is(e){const t=ne(e);return!t||t.backend!=="indexeddb"&&t.backend!=="memory"||typeof t.fileCacheAvailable!="boolean"||["cacheBytes","entryCount","fileCacheBytes","fileCacheEntryCount","pendingCleanupCount","structuredCacheBytes","structuredEntryCount"].some(s=>!_e(t[s]))||!de(t.originQuotaBytes)||!de(t.originUsageBytes)?null:t}function rs(e){const t=ne(e),n=ne(t?.counters),s=ne(t?.quota),a=ne(t?.requestWait);if(!t||t.schema!==Pn||!n||!s||!a||!st(t.updatedAt)||!st(t.windowStartedAt)||Tn.some(i=>!_e(n[i]))||!de(s.lastEstimatedAt)||!de(s.quotaBytes)||!de(s.usageBytes)||s.supported!==null&&typeof s.supported!="boolean")return null;for(const i of["averageDurationMs","durationObservations","maxDurationMs","pendingCount","totalDurationMs"])if(!_e(a[i]))return null;return de(a.oldestPendingMs)?t:null}function os(e){const t=ne(e);return!t||t.status!=="complete"&&t.status!=="pending"||!_e(t.pendingCleanupCount)||!_e(t.removed)?null:t}function ls(){return typeof window<"u"&&window.parent!==window?window.parent:null}function ds(){if(typeof window>"u")return null;const e=nt(window.__MAVERICK_PLATFORM_ORIGIN__),t=nt(window.location.origin);return e&&t&&e!==t?e:null}function nt(e){if(typeof e!="string"||!e)return null;try{const t=new URL(e);return t.origin===e&&(t.protocol==="http:"||t.protocol==="https:")?t.origin:null}catch{return null}}function cs(){return globalThis.crypto?.randomUUID?.()??`${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`}function At(e,t){return typeof e=="number"&&Number.isFinite(e)&&e>0?Math.min(Math.floor(e),3e4):t}function _e(e){return typeof e=="number"&&Number.isSafeInteger(e)&&e>=0}function st(e){return typeof e=="number"&&Number.isFinite(e)&&e>=0}function de(e){return e===null||st(e)}function ne(e){return e&&typeof e=="object"&&!Array.isArray(e)?e:null}const fe=new Set;let Se=null;function us(e,t){if(typeof window>"u")return()=>{};const n={event:e,refresh:t};return fe.add(n),Se||(Se=ps()),()=>{fe.delete(n),fe.size||(Se?.(),Se=null)}}function ps(){const e=en(),t=!!(e&&window.parent&&window.parent!==window),n=()=>!!(globalThis.document?.hidden||globalThis.navigator?.onLine===!1);let s=t&&n(),a=null,i,r=!1,o=!1,c=0;const l=tt;let p=l();o=!p;const u=()=>{for(const w of fe)w.refresh()},m=w=>{for(const C of fe)C.event(w)};function S(){if(o=!0,r||!l()||i!==void 0)return;const w=Math.min(3e4,1e3*2**Math.min(c++,5)*(.8+Math.random()*.4));i=setTimeout(()=>{i=void 0,g()},w)}function g(){if(r||t||!l()||a||typeof WebSocket>"u")return;const w=window.location.protocol==="https:"?"wss:":"ws:";let C;try{C=new WebSocket(`${w}//${window.location.host}/api/apps/events/ws`)}catch{S();return}a=C;let B=!1;const P=()=>!r&&a===C;C.onopen=()=>{!P()||B||(B=!0,c=0,o&&(o=!1,u()))},C.onmessage=M=>{if(!P()||!l())return;let E;try{E=JSON.parse(M.data)}catch{return}m(E)},C.onclose=()=>{P()&&(a=null,S())},C.onerror=()=>{P()&&C.close()}}function T(){const w=l();if(w!==p)if(p=w,w)t?o&&!s&&(o=!1,u()):g();else{t&&n()&&(s=!0),o=!0,clearTimeout(i),i=void 0;const C=a;a=null,C?.close()}}function $(){t&&n()&&(s=!0)}function b(w){if(!t||!ft(w)||!w.data||typeof w.data!="object")return;const C=w.data;if(C.type==="maverick.app.events-resync")s=!1,l()?(o=!1,u()):o=!0;else if(C.type==="maverick.app.event"&&C.event&&typeof C.event=="object"){if(C.event.workspace_id&&C.event.workspace_id!==e.workspaceId)return;l()?m(C.event):o=!0}}const R=Qn(T);return window.addEventListener?.("offline",$),globalThis.document?.addEventListener("visibilitychange",$),window.addEventListener?.("message",b),g(),()=>{r=!0,clearTimeout(i);const w=a;a=null,w?.close(),R(),window.removeEventListener?.("offline",$),globalThis.document?.removeEventListener("visibilitychange",$),window.removeEventListener?.("message",b)}}let be=new WeakSet;const ee=new Map;function gs(e=document.getElementById("app")){ee.clear(),be=new WeakSet,e?.replaceChildren()}function ms(e){const t=n=>{if(n.target instanceof Element&&!n.target.hasAttribute("data-settings-controlled")){be.add(n.target);const s=n.target.closest("form, #workspace-assignments")?.querySelector("[data-action-status]");s&&(s.textContent="Unsaved changes")}};e.addEventListener("input",t,!0),e.addEventListener("change",t,!0)}function z(e){(typeof e=="string"?[...document.querySelectorAll(e),...Array.from(ee.values()).flatMap(n=>[...n.matches(e)?[n]:[],...n.querySelectorAll(e)])]:[e]).forEach(n=>{be.delete(n),n.querySelectorAll("[data-action-status]").forEach(s=>{s.textContent="",s.setAttribute("role","status")}),n.querySelectorAll("input, select, textarea").forEach(s=>be.delete(s))})}function fs(e,t){const n=document.activeElement,s=n instanceof HTMLInputElement||n instanceof HTMLTextAreaElement?[n.selectionStart,n.selectionEnd]:null,a=document.createElement("template");a.innerHTML=t,nn(e,a.content),n?.isConnected&&document.activeElement!==n&&(n.focus({preventScroll:!0}),s&&s[0]!==null&&s[1]!==null&&n.setSelectionRange(s[0],s[1]))}function te(e){return e instanceof Element?e.getAttribute("data-render-key")||e.id||["data-settings-model-accordion","data-hosted-model-accordion","data-runtime-row","data-workspace-row","data-app-row","data-dependency-row","data-agentic-provider-group","data-hosted-provider-group","data-execution-family"].map(t=>{const n=e.getAttribute(t);return n===null?"":`${t}:${n}`}).find(Boolean)||(e.classList.length?`${e.tagName}:${Array.from(e.classList).filter(t=>!t.startsWith("is-")).join(" ")}`:""):""}function Ve(e,t){return e.nodeType===t.nodeType&&e.nodeName===t.nodeName&&te(e)===te(t)}function nn(e,t){let n=e.firstChild;for(const s of Array.from(t.childNodes)){if(n&&!Ve(n,s)&&te(s)){const a=Array.from(e.childNodes).find(i=>Ve(i,s))||ee.get(te(s));a&&(ee.delete(te(s)),e.insertBefore(a,n),n=a)}if(!n||!Ve(n,s)){const a=s.cloneNode(!0);if(e.insertBefore(a,n),n&&!te(n)){const i=n;n=n.nextSibling,i.remove()}continue}vs(n,s),n=n.nextSibling}for(;n;){const s=n;n=n.nextSibling,s instanceof Element&&te(s).startsWith("page:")&&(ee.set(te(s),s),ee.size>12&&ee.delete(ee.keys().next().value)),e.removeChild(s)}}function vs(e,t){if(!(e instanceof Element)||!(t instanceof Element)){e.nodeValue!==t.nodeValue&&(e.nodeValue=t.nodeValue);return}const n=be.has(e)&&!t.hasAttribute("data-settings-controlled"),s=e instanceof HTMLDetailsElement?e.open:void 0,a=n&&"value"in e?String(e.value):void 0,i=n&&e instanceof HTMLInputElement?e.checked:void 0;if(!e.matches("[data-action-status]")&&!(e.hasAttribute("data-settings-owned-view")&&e.getAttribute("data-settings-owned-view")===t.getAttribute("data-settings-owned-view"))){for(const r of Array.from(e.attributes))e.hasAttribute("data-pending-action")&&["data-pending-action","aria-busy"].includes(r.name)||t.hasAttribute(r.name)||e.removeAttribute(r.name);for(const r of Array.from(t.attributes))e.getAttribute(r.name)!==r.value&&e.setAttribute(r.name,r.value);e.closest("[data-pending-action]")&&e.matches("input, button, select")&&e.setAttribute("disabled",""),!e.matches("[data-usage-history-chart], [data-usage-history-filters]")&&(nn(e,t),e instanceof HTMLDetailsElement&&s!==void 0&&(e.open=s),e instanceof HTMLInputElement&&(e.value=a??t.value,e.checked=i??t.checked),(e instanceof HTMLSelectElement||e instanceof HTMLTextAreaElement)&&(e.value=a??t.value))}}let at=new AbortController;function hs(){at.abort(),at=new AbortController}function v(e,t,n){e?.addEventListener(t,n,{signal:at.signal})}async function L(e,t={}){const n=await fetch(e,{credentials:"same-origin",headers:{"Content-Type":"application/json",...t.headers||{}},...t}),s=await n.json();if(!n.ok)throw new Error(s.detail||s.error||`Request failed ${n.status}`);return s}function Ct(e,t=""){return typeof e=="string"?e:t}function _s(e){return Array.isArray(e)?e.filter(t=>typeof t=="string"):[]}function bs(e){if(!e||typeof e!="object"||Array.isArray(e))return null;const t=e,n=t.kind==="image"||t.kind==="glyph"?t.kind:null;return n&&typeof t.value=="string"?{kind:n,value:t.value}:null}function ys(e){const t=e&&typeof e=="object"&&!Array.isArray(e)?e:{},n=Ct(t.app_id);return{app_id:n,name:Ct(t.name,n||"Unnamed app"),views:_s(t.views),logo:bs(t.logo)}}async function ws(){return((await L("/api/apps")).items||[]).map(ys).filter(t=>t.app_id)}function ht(e){const t=new URLSearchParams({consumer_app_id:e});return L(`/api/apps/dependencies?${t.toString()}`)}function sn(e,t,n){return L("/api/apps/dependencies",{method:"POST",body:JSON.stringify({consumer_app_id:e,alias:t,provider_app_ids:n})})}function $s(e="all"){return L(e==="all"?"/api/settings/platform":`/api/settings/platform?section=${e}`)}function ks(){return L("/api/providers/usage")}function Ss(e,t,n={}){const s=new URLSearchParams({resolution:e,periods:String(t)});return n.providerId&&s.set("provider_id",n.providerId),n.modelId&&s.set("model_id",n.modelId),L(`/api/usage/timeseries?${s.toString()}`)}function Es(e){return L("/api/providers/hosted/selection",{method:"POST",body:JSON.stringify(e)})}function As(e){return L("/api/providers/speech/selection",{method:"POST",body:JSON.stringify(e)})}function Cs(e){return L("/api/providers/agentic/workspace-bindings",{method:"POST",body:JSON.stringify(e)})}function Is(e){return L("/api/providers/native/activate",{method:"POST",body:JSON.stringify({provider_id:e,confirmation:"native-runtime-reviewed"})})}function Ms(e,t="settings_runtime_sessions_cleared"){return L("/api/settings/runtime-sessions/clear",{method:"POST",body:JSON.stringify({session_ids:e,reason:t})})}function Ps(){return L("/api/auth/logout",{method:"POST"})}function Ts(e){return L("/api/admin/persistence/migrations/dry-run",{method:"POST",body:JSON.stringify(e)})}function qs(e){return L("/api/admin/persistence/migrations/apply",{method:"POST",body:JSON.stringify(e)})}function d(e){return e.replace(/[&<>"']/g,t=>t==="&"?"&amp;":t==="<"?"&lt;":t===">"?"&gt;":t==='"'?"&quot;":"&#39;")}function k(e){return d(e)}function an(){return{workspaceId:"",providerAppId:"",engines:[],engine:"",language:"auto",savedEngine:"",savedLanguage:"auto",loading:!1,saving:!1,loaded:!1,error:""}}const It={logical_names:["openrouter-api-key","deepinfra-api-key","google-ai-studio-api-key"],required:!1};function Ds(e){const t=e.state;let n=0;function s(){n+=1,Object.assign(t,an())}async function a(c,l=!1){if(!c||(t.workspaceId!==c&&s(),t.loading||t.saving||t.loaded&&!l))return;t.workspaceId=c;const p=++n;t.loading=!0,t.error="",e.render();try{const u=await ht("settings");if(p!==n)return;if(u.workspace_id!==c)throw new Error("The active workspace changed. Reload voice settings.");const S=u.dependencies.find(T=>T.alias==="text-to-speech")?.selected_provider_app_ids[0]||"";if(!S)throw new Error("Select a text-to-speech provider for Settings in App links.");const g=await L(`/api/apps/${encodeURIComponent(S)}/backend`,{method:"POST",body:JSON.stringify({action:"engine_health",include_voices:!1,_app_secret_request:It})});if(p!==n)return;t.providerAppId=S,i(g),t.loaded=!0}catch(u){p===n&&(t.error=u instanceof Error?u.message:"Unable to load text-to-speech settings.")}finally{p===n&&(t.loading=!1,e.render())}}function i(c,l=!1){t.engines=c.synthesis,(!t.loaded||l||t.engine===t.savedEngine)&&(t.engine=c.settings.synthesis_engine),(!t.loaded||l||t.language===t.savedLanguage)&&(t.language=c.settings.synthesis_language),t.savedEngine=c.settings.synthesis_engine,t.savedLanguage=c.settings.synthesis_language}async function r(){if(!t.providerAppId||t.saving||t.loading)return;const c=n;t.saving=!0,t.error="",e.render();try{const l=await L(`/api/apps/${encodeURIComponent(t.providerAppId)}/backend`,{method:"POST",body:JSON.stringify({action:"set_engine",synthesis_engine:t.engine,synthesis_language:t.language,_app_secret_request:It})});if(c!==n)return;i(l.engines,!0),z(".settings-tts-group"),e.notify("Text-to-speech settings updated.")}catch(l){c===n&&(t.error=l instanceof Error?l.message:"Unable to save text-to-speech settings.")}finally{c===n&&(t.saving=!1,e.render())}}function o(){v(document.getElementById("settings-tts-discard"),"click",()=>{t.engine=t.savedEngine,t.language=t.savedLanguage,z(".settings-tts-group"),e.render()}),v(document.getElementById("settings-tts-engine"),"change",c=>{t.engine=c.currentTarget.value,t.error="",e.render()}),v(document.getElementById("settings-tts-language"),"input",c=>{t.language=c.currentTarget.value;const l=document.getElementById("settings-tts-discard");l&&(l.disabled=t.engine===t.savedEngine&&t.language===t.savedLanguage)}),v(document.getElementById("settings-tts-save"),"click",()=>{r()}),v(document.getElementById("settings-tts-retry"),"click",()=>{a(t.workspaceId,!0)})}return{load:a,save:r,reset:s,bind:o}}const Rs={auto:"Automatic local voice",piper:"Piper","espeak-ng":"eSpeak NG",espeak:"eSpeak","kokoro-openrouter":"Kokoro · OpenRouter","kokoro-deepinfra":"Kokoro · DeepInfra",gemini:"Gemini 3.8 Flash-Lite TTS"};function Ls(e){const t=e.engines.find(a=>a.engine===e.engine),n=e.loading||e.saving,s=[{engine:"auto",available:!0},...e.engines];return`<section class="settings-hosted-provider-group settings-tts-group" aria-labelledby="settings-tts-title">
    <div class="settings-heading"><div><p class="settings-kicker">Text to speech</p><h3 id="settings-tts-title">Read-aloud voice</h3></div></div>
    ${e.loading?'<p class="settings-card-copy" role="status">Loading voice settings…</p>':""}
    ${e.loaded?`<div class="settings-tts-controls">
      <label>Voice engine<select id="settings-tts-engine" ${n?"disabled":""}>
        ${s.map(a=>`<option value="${k(a.engine)}" ${a.engine===e.engine?"selected":""} ${!a.available&&a.engine!==e.engine?"disabled":""}>${d(Rs[a.engine]||a.engine)}${a.available?"":" · unavailable"}</option>`).join("")}
      </select></label>
      <label>Language<input id="settings-tts-language" list="settings-tts-languages" value="${k(e.language)}" ${n?"disabled":""} autocomplete="off" placeholder="auto or it-IT">
        <datalist id="settings-tts-languages"><option value="auto">Automatic</option><option value="it-IT">Italian</option><option value="en-US">English</option></datalist>
      </label>
    </div>
    ${t&&!t.available?`<p class="settings-platform-error">${d(t.detail||"The selected voice engine is unavailable.")}</p>`:""}
    <button type="button" class="settings-secondary" id="settings-tts-discard" ${n||e.engine===e.savedEngine&&e.language===e.savedLanguage?"disabled":""}>Discard edits</button>
    <button type="button" class="settings-secondary" id="settings-tts-save" ${n||e.engine!=="auto"&&!t?.available?"disabled":""}>${e.saving?"Saving…":"Save voice settings"}</button>`:""}
    ${e.error?`<p class="settings-platform-error" role="alert">${d(e.error)}</p><button type="button" class="settings-secondary" id="settings-tts-retry" ${n?"disabled":""}>Retry</button>`:""}
  </section>`}function Hs(){return{workspaceId:"",providerId:"",modelId:"",effort:"",executionMode:"delegated",fallbackModelId:"",fallbackEffort:"",saving:!1,error:"",generation:0,savedSelection:""}}function it(e,t,n=!1){const s=t?.computer_use,a=t?.workspace.workspace_id||"",i=e.workspaceId!==a,r=JSON.stringify([s?.provider_id,s?.model_id,s?.reasoning_effort,s?.execution_mode,s?.fallback_model_id,s?.fallback_reasoning_effort]);if(i&&(e.generation+=1,e.saving=!1,e.error=""),!i&&!n){if(e.savedSelection===r)return;const o=JSON.stringify([e.providerId||void 0,e.modelId||void 0,e.effort||void 0,e.executionMode,e.fallbackModelId||void 0,e.fallbackEffort||void 0]);if(e.savedSelection&&o!==e.savedSelection){e.savedSelection=r;return}}Object.assign(e,{workspaceId:a,providerId:s?.provider_id||"",modelId:s?.model_id||"",effort:s?.reasoning_effort||"",executionMode:s?.execution_mode||"delegated",fallbackModelId:s?.fallback_model_id||"",fallbackEffort:s?.fallback_reasoning_effort||"",savedSelection:r})}function rn(e,t){return e?.computer_use?.providers.find(n=>n.provider_id===t.providerId)?.models.find(n=>n.model_id===t.modelId)}function Us(e,t){const n=e.computer_use;if(!n)return"";const s=rn(e,t),a=s?.supported_reasoning_efforts||[],i=a.length?a.some(c=>c.effort===t.effort):!t.effort,r=t.providerId!==n.provider_id||t.modelId!==n.model_id||t.effort!==(n.reasoning_effort||"")||t.executionMode!==(n.execution_mode||"delegated")||t.fallbackModelId!==(n.fallback_model_id||"")||t.fallbackEffort!==(n.fallback_reasoning_effort||""),o=!n.can_configure||t.saving;return`<section class="settings-card settings-platform" aria-labelledby="settings-computer-use-title">
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
      ${t.executionMode==="delegated"||!s||!i?`<label class="settings-platform-field settings-platform-field-wide"><span>Decision model</span>
        <select id="settings-computer-use-model" ${o?"disabled":""}>
          ${s?"":`<option selected disabled value="">Unavailable: ${d(t.modelId)}</option>`}
          ${n.providers.map(c=>`<optgroup label="${d(c.label)}">${c.models.map(l=>`<option value="${d(JSON.stringify([c.provider_id,l.model_id]))}" ${c.provider_id===t.providerId&&l.model_id===t.modelId?"selected":""}>${d(l.label)}</option>`).join("")}</optgroup>`).join("")}
        </select>
      </label>
      <label class="settings-platform-field settings-platform-field-wide"><span>Reasoning effort</span>
        <select id="settings-computer-use-effort" ${o||!s?"disabled":""}>
          ${i?"":`<option selected disabled value="${d(t.effort)}">Unavailable: ${d(t.effort)}</option>`}
          ${a.length?a.map(c=>`<option value="${d(c.effort)}" ${c.effort===t.effort?"selected":""}>${d(c.label)}</option>`).join(""):'<option value="">Default</option>'}
        </select>
      </label>
      ${t.executionMode==="delegated"?`<label class="settings-platform-field settings-platform-field-wide"><span>Recovery model</span>
        <select id="settings-computer-use-fallback" ${o?"disabled":""}>
          <option value="" ${t.fallbackModelId?"":"selected"}>Return to chat</option>
          ${t.fallbackModelId&&!n.providers.flatMap(c=>c.models).some(c=>c.model_id===t.fallbackModelId)?`<option selected disabled value="${d(t.fallbackModelId)}">Unavailable: ${d(t.fallbackModelId)}</option>`:""}
          ${n.providers.flatMap(c=>c.models).filter(c=>c.model_id!==t.modelId&&c.supported_reasoning_efforts.some(l=>l.effort==="medium")).map(c=>`<option value="${d(c.model_id)}" ${c.model_id===t.fallbackModelId?"selected":""}>${d(c.label)} · Mid</option>`).join("")}
        </select>
      </label>
      `:""}
      `:'<p class="settings-card-copy">The selected chat model controls the interface directly.</p>'}
      ${n.available?"":'<p class="settings-inline-error" role="alert">The saved model is unavailable. Choose an available model to continue PC use.</p>'}
      ${t.error?`<p class="settings-inline-error" role="alert">${d(t.error)}</p>`:""}
      <button type="button" id="settings-computer-use-discard" class="settings-secondary" ${r&&!o?"":"disabled"}>Discard edits</button>
      <button type="button" id="settings-computer-use-save" ${o||!s||!i||!r?"disabled":""}>
        <span class="material-symbols-rounded" aria-hidden="true">${t.saving?"sync":"save"}</span>
        ${t.saving?"Saving":"Save decision model"}
      </button>
    </div>
  </section>`}function Os(e){const{state:t,getSettings:n,render:s}=e;let a=0;async function i(){const o=n();if(!o?.computer_use?.can_configure||t.saving)return;const c=o.workspace.workspace_id;if(c!==t.workspaceId)return;const l=t.generation,p=++a,u=()=>t.generation===l&&p===a&&n()?.workspace.workspace_id===c;t.saving=!0,t.error="";const m={workspace_id:c,provider_id:t.providerId,model_id:t.modelId,reasoning_effort:t.effort||null,execution_mode:t.executionMode,fallback_model_id:t.fallbackModelId||null,fallback_reasoning_effort:t.fallbackEffort||null};s();try{const S=await L("/api/settings/computer-use",{method:"POST",body:JSON.stringify(m)});if(!u()||S.workspace_id!==c)return;e.setSelection(S),it(t,n(),!0),z('[aria-labelledby="settings-computer-use-title"]'),e.notify("PC use decision model updated.")}catch(S){u()&&(t.error=S instanceof Error?S.message:"Unable to update the decision model.")}finally{u()&&(t.saving=!1,s())}}function r(){v(document.getElementById("settings-computer-use-discard"),"click",()=>{it(t,n(),!0),z('[aria-labelledby="settings-computer-use-title"]'),s()}),v(document.getElementById("settings-computer-use-mode"),"change",o=>{t.executionMode=o.currentTarget.value,t.executionMode==="direct"&&(t.fallbackModelId="",t.fallbackEffort=""),t.error="",s()}),v(document.getElementById("settings-computer-use-fallback"),"change",o=>{t.fallbackModelId=o.currentTarget.value,t.fallbackEffort=t.fallbackModelId?"medium":"",t.error="",s()}),v(document.getElementById("settings-computer-use-model"),"change",o=>{const[c,l]=JSON.parse(o.currentTarget.value);t.providerId=c,t.modelId=l,t.fallbackModelId===l&&(t.fallbackModelId="",t.fallbackEffort="");const p=rn(n(),t);t.effort=p?.supported_reasoning_efforts.some(u=>u.effort==="low")?"low":p?.default_reasoning_effort||"",t.error="",s()}),v(document.getElementById("settings-computer-use-effort"),"change",o=>{t.effort=o.currentTarget.value,t.error="",s()}),v(document.getElementById("settings-computer-use-save"),"click",()=>{i()})}return{bind:r,save:i}}async function Ns(){try{return await L("/api/admin/persistence")}catch{return null}}const Bs={registry:"/api/apps",context:"/api/settings/platform?section=context",models:"/api/settings/platform?section=models",voice:"/api/settings/platform?section=voice","computer-use":"/api/settings/platform?section=computer-use",users:"/api/admin/users",workspaces:"/api/admin/workspaces",apps:"/api/admin/workspace-apps",persistence:"/api/admin/persistence",sessions:"/api/settings/runtime-sessions"};function _t(e){return e==="users"||e==="workspace-access"?["users","workspaces"]:e==="workspace-apps"?["context","workspaces","apps"]:e==="app-links"?["context","apps"]:e==="sessions"?["context","sessions"]:e==="usage"||e==="learning"?["context"]:e==="cache"||e==="installation"?[]:[e]}function js(e){const t=new Map,n=new Map;function s(o){return t.has(o)||t.set(o,{loaded:!1,loading:!1,error:""}),t.get(o)}function a(o,c=!1){if(!c&&n.has(o))return n.get(o).promise;if(!c&&s(o).loaded)return Promise.resolve();n.get(o)?.controller.abort();const l=new AbortController;Object.assign(s(o),{loading:!0,error:""});const p=performance.now(),u=L(Bs[o],{signal:l.signal}).then(m=>{l.signal.aborted||(e.publish(o,m),s(o).loaded=!0)}).catch(m=>{l.signal.aborted||(s(o).error=m instanceof Error?m.message:"Unable to load settings.")}).finally(()=>{n.get(o)?.controller===l&&(n.delete(o),s(o).loading=!1,performance.clearMeasures(`settings.load.${o}`),performance.measure(`settings.load.${o}`,{start:p,end:performance.now()}),e.changed(o))});return n.set(o,{controller:l,promise:u}),e.changed(o),u}function i(){n.forEach(({controller:o})=>o.abort()),n.clear(),t.clear()}function r(o){n.forEach(({controller:c},l)=>{o.includes(l)||(c.abort(),n.delete(l),s(l).loading=!1)})}return{state:s,ensure:a,reset:i,cancelExcept:r}}function Fs(e,t,n){e?.workspace.workspace_id!==t.workspace.workspace_id&&(e=null);const s=n==="models"?t.provider:n==="voice"?{...e?.provider||t.provider,hosted_text:t.provider.hosted_text,speech_stt:t.provider.speech_stt}:e?.provider||t.provider;return{...e,...t,provider:s,runtime:{...e?.runtime,...t.runtime,all_sessions:e?.runtime.all_sessions},computer_use:t.computer_use||e?.computer_use,agentic_admin:n==="models"?t.agentic_admin:e?.agentic_admin}}function bt(e){const t=document.activeElement,n=document.createElement("dialog");return n.className="settings-modal settings-confirm-dialog",n.setAttribute("aria-labelledby","settings-confirm-title"),n.setAttribute("aria-describedby","settings-confirm-detail"),n.innerHTML=`<h2 id="settings-confirm-title">${d(e.title)}</h2>
    <p id="settings-confirm-detail" class="settings-card-copy">${d(e.detail)}</p>
    <form method="dialog" class="settings-modal-actions">
      <button value="cancel" class="settings-secondary" autofocus>Cancel</button>
      <button value="confirm" class="settings-danger">${d(e.confirmLabel)}</button>
    </form>`,document.body.append(n),new Promise(s=>{n.addEventListener("close",()=>{const a=n.returnValue==="confirm";n.remove(),t?.isConnected&&t.focus(),s(a)},{once:!0}),n.showModal()})}let Je=null,Ee=null;function zs(e){const t=document.querySelector('.settings-modal[role="dialog"]');if(!t){Ee&&Je?.isConnected&&Je.focus(),Ee=null;return}const n=()=>Array.from(t.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex="0"]'));Ee!==t&&(Je=document.activeElement,Ee=t,n()[0]?.focus()),t.onkeydown=s=>{if(s.key==="Escape"&&!t.querySelector("button#close-migration-modal:disabled")&&(s.preventDefault(),e()),s.key!=="Tab")return;const a=n(),i=a[0],r=a.at(-1);s.shiftKey&&document.activeElement===i&&(s.preventDefault(),r?.focus()),!s.shiftKey&&document.activeElement===r&&(s.preventDefault(),i?.focus())}}const Ge=20,on=()=>({scope:"workspace",query:"",status:"",page:0});function yt(e,t){const n=e.runtime.all_sessions||e.runtime.sessions||[];return t.scope==="server"&&e.runtime.cleanup_scope==="server"?n:n.filter(s=>s.workspace_id===e.workspace.workspace_id)}function Ws(e,t){const n=t.query.trim().toLowerCase();return yt(e,t).filter(s=>(!t.status||s.status===t.status)&&`${s.session_id} ${s.agent_id} ${s.workspace_name||s.workspace_id} ${s.provider_id}`.toLowerCase().includes(n))}function Vs(e,t,n){const s=yt(e,n),a=Ws(e,n),i=Math.max(1,Math.ceil(a.length/Ge));n.page=Math.min(n.page,i-1);const r=a.slice(n.page*Ge,(n.page+1)*Ge),o=e.runtime.cleanup_allowed===!0,c=n.scope==="server"?"All workspaces on this server":e.workspace.name;return`<section class="settings-card settings-runtime-settings-card">
    <div class="settings-heading"><div><p class="settings-kicker">${d(c)}</p><h2>Runtime sessions</h2></div>
      <button type="button" id="settings-clear-all-runtime" class="settings-danger" ${!o||!s.length||t.clearingAllRuntime?"disabled":""}>${t.clearingAllRuntime?"Deleting…":`Delete ${s.length} sessions`}</button>
    </div>
    <p class="settings-card-copy">Deletion stops active agents and removes their conversations, turns and runtime files. Review the confirmation before continuing.</p>
    <div class="settings-grid settings-session-filters">
      <label>Search sessions<input id="settings-session-search" type="search" value="${k(n.query)}" placeholder="Agent, workspace or session" /></label>
      <label>Status<select id="settings-session-status"><option value="">All statuses</option>${Array.from(new Set(s.map(l=>l.status))).sort().map(l=>`<option value="${k(l)}" ${n.status===l?"selected":""}>${d(l)}</option>`).join("")}</select></label>
      ${e.runtime.cleanup_scope==="server"?`<label>View scope<select id="settings-session-scope"><option value="workspace" ${n.scope==="workspace"?"selected":""}>Current workspace</option><option value="server" ${n.scope==="server"?"selected":""}>Entire server</option></select></label>`:""}
    </div>
    ${o?"":'<p role="status">You do not have permission to delete sessions in this workspace.</p>'}
    <div class="settings-platform-runtime-list">${r.map(l=>Js(l,o,t)).join("")||'<p role="status">No sessions match this view.</p>'}</div>
    <div class="settings-pagination"><span role="status">${a.length} sessions · Page ${n.page+1} of ${i}</span>
      <button type="button" id="settings-sessions-prev" class="settings-secondary" ${n.page===0?"disabled":""}>Previous</button>
      <button type="button" id="settings-sessions-next" class="settings-secondary" ${n.page+1>=i?"disabled":""}>Next</button>
    </div>
    ${t.cleanupError?`<p class="settings-inline-error" role="alert">${d(t.cleanupError)}</p>`:""}
  </section>`}function Js(e,t,n){const s=n.cleaningSessionIds.has(e.session_id)||n.clearingAllRuntime;return`<article class="settings-platform-runtime-row" data-runtime-row="${k(e.session_id)}">
    <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">terminal</span>
    <span class="settings-platform-runtime-copy"><span class="settings-platform-runtime-title"><strong>${d(e.agent_id||e.session_id)}</strong>
      <button type="button" class="settings-secondary" data-runtime-clear="${k(e.session_id)}" aria-label="Delete session ${k(e.agent_id||e.session_id)}" ${!t||s?"disabled":""}>${s?"Deleting…":"Delete"}</button></span>
      <small>${d(e.workspace_name||e.workspace_id)} · ${d(e.status)} · ${d(e.effective_mode)}</small>
      ${e.recovery_reason_code?`<small class="settings-inline-error">${d(e.recovery_reason_code)}</small>`:""}
      ${e.agentic_containment?.status==="NO-GO"?`<small class="settings-inline-error">Contained: ${d(e.agentic_containment.reason_code||"Unavailable")}</small>`:""}
      <code>${d(e.session_id)}</code></span>
  </article>`}const rt=[{value:"6h",label:"6 hours",resolution:"hour",periods:6},{value:"12h",label:"12 hours",resolution:"hour",periods:12},{value:"24h",label:"24 hours",resolution:"hour",periods:24},{value:"3d",label:"3 days",resolution:"hour",periods:72},{value:"7d",label:"7 days",resolution:"day",periods:7},{value:"30d",label:"30 days",resolution:"day",periods:30},{value:"90d",label:"90 days",resolution:"day",periods:90},{value:"180d",label:"180 days",resolution:"day",periods:180},{value:"1y",label:"1 year",resolution:"day",periods:365}],ln=[{value:"non_cached_tokens",label:"Non-cached"},{value:"total_tokens",label:"Processed total"},{value:"cached_input_tokens",label:"Cached input"},{value:"input_tokens",label:"Uncached input"},{value:"output_tokens",label:"Output"},{value:"reasoning_output_tokens",label:"Reasoning output"},{value:"cache_write_input_tokens",label:"Cache write"}];function ot(){return{metric:"non_cached_tokens",providerId:"",modelId:"",timeRange:"24h"}}function Gs(e,t){const n=ln.some(a=>a.value===t.metric)?t.metric:e.metric,s=rt.some(a=>a.value===t.timeRange)?t.timeRange:e.timeRange;return{metric:n,providerId:Mt(t.providerId,e.providerId),modelId:Mt(t.modelId,e.modelId),timeRange:s}}function dn(e){return rt.find(t=>t.value===e)||rt[2]}function Tr(e,t){return t==="non_cached_tokens"?Math.max(0,Ke(e.total_tokens)-Ke(e.cached_input_tokens)):Math.max(0,Ke(e[t]))}function qr(e){return ln.find(t=>t.value===e)?.label||"Non-cached"}function Dr(e){const t=new Map,n=(i,r=[])=>{if(!i?.provider_id)return;const o=t.get(i.provider_id)||new Set;i.model_options.forEach(c=>c.model_id&&o.add(c.model_id)),r.forEach(c=>c&&o.add(c)),t.set(i.provider_id,o)},s=e?.provider;n(s?.active_provider,[s?.model_settings?.selected_model_id||"",...(s?.model_settings?.available_models||[]).map(i=>i.model_id)]),s?.available_providers?.forEach(i=>n(i));const a=s?.hosted_text;return n(a?.active_provider,[a?.model_settings?.selected_model_id||"",...(a?.model_settings?.available_models||[]).map(i=>i.model_id)]),a?.available_providers.forEach(i=>n(i)),e?.agentic_admin?.items.forEach(i=>{const r=t.get(i.model_provider_id)||new Set;i.model_id&&r.add(i.model_id),t.set(i.model_provider_id,r)}),Array.from(t,([i,r])=>({provider_id:i,model_ids:Array.from(r).sort((o,c)=>o.localeCompare(c))})).sort((i,r)=>i.provider_id.localeCompare(r.provider_id))}function Ke(e){return Number.isFinite(e)?e:0}function Mt(e,t){return typeof e=="string"?e.trim():t}function Ks(e,t,n=Date.now()){const s=t.providerUsageItems.find(r=>r.provider_id===e);if(!s)return t.isLoadingProviderUsage?"Loading usage…":t.providerUsageError?"Usage unavailable":"Usage limit not reported";if(!s.available)return"Usage unavailable";const a=s.limits.map(r=>({limit:r,windows:[r.primary_window,r.secondary_window].filter(o=>o!==null)})).filter(({windows:r})=>r.length>0);if(!a.length)return"Usage limit not reported";const i=a.length>1;return a.map(({limit:r,windows:o})=>`${i?`${r.label} — `:""}${o.map(l=>Qs(l,n)).join("; ")}`).join(" · ")}function Qs(e,t){const n=Math.min(100,Math.max(0,e.used_percent)),s=Math.max(0,100-n),a=Ys(e,t);return`${Zs(e.limit_window_seconds)}: ${Pt(n)} used · ${Pt(s)} remaining before limit${a?` · ${a}`:""}`}function Pt(e){return`${Number.isInteger(e)?e.toFixed(0):e.toFixed(1)}%`}function Zs(e){return!e||e<=0?"Rolling window":e%604800===0?`${e/604800}w window`:e%86400===0?`${e/86400}d window`:e%3600===0?`${e/3600}h window`:e%60===0?`${e/60}m window`:"Rolling window"}function Ys(e,t){let n=null;return e.reset_at_epoch_seconds!==null?n=Math.max(0,Math.ceil(e.reset_at_epoch_seconds-t/1e3)):n=e.reset_after_seconds,n===null?"":`resets ${Xs(n)}`}function Xs(e){if(e<=0)return"now";const t=Math.max(1,Math.ceil(e/60)),n=Math.floor(t/1440),s=Math.floor(t%1440/60),a=t%60;return n>0?`in ${n}d${s>0?` ${s}h`:""}`:s>0?`in ${s}h${a>0?` ${a}m`:""}`:`in ${a}m`}function xs(e){const t=e.isLoadingUsageHistory?"sync":"refresh",n=dn(e.usageHistoryFilters.timeRange),s=n.resolution==="hour"?"Hourly consumption":"Daily consumption";return`<section class="settings-card settings-platform settings-usage-history-card" aria-labelledby="settings-usage-history-title">
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
        <p class="settings-kicker">Last ${d(n.label)}</p>
        <h3>${s}</h3>
      </div>
      <div data-usage-history-chart aria-live="polite"></div>
    </article>
  </section>`}function ea(e){return`<section class="settings-card"><div class="settings-heading"><h2>Provider subscriptions</h2></div>
    ${e.providerUsageError?`<p role="alert">${d(e.providerUsageError)}</p>`:""}
    ${e.isLoadingProviderUsage?'<p role="status">Loading subscription usage…</p>':""}
    ${e.providerUsageItems.map(t=>`<article class="settings-subscription-row"><strong>${d(t.provider_id)}</strong><p>${d(Ks(t.provider_id,e))}</p></article>`).join("")}
    ${!e.isLoadingProviderUsage&&!e.providerUsageItems.length&&!e.providerUsageError?"<p>No subscription limits reported.</p>":""}
  </section>${xs(e)}`}const we=e=>["rejected","undone","undoing"].includes(e.status)?e.status:e.implementation?.status||e.status,ta=[{id:"proposed",label:"Proposed",states:["pending"],hint:"Accept to start a Chat agent"},{id:"queued",label:"Queued",states:["accepted","queued","launching"],hint:"Starts when an agent slot is available"},{id:"running",label:"In progress",states:["running","stopping"],hint:"Follow the agent in Chat"},{id:"review",label:"To verify",states:["awaiting_review"],hint:"Check the result before completing"},{id:"attention",label:"Needs attention",states:["failed","cancelled"],hint:"Inspect the chat and retry when ready"},{id:"done",label:"Done",states:["implemented"],hint:"Implementation confirmed"},{id:"closed",label:"Dismissed",states:["rejected"],hint:"Proposals you chose to dismiss"}],na=[{id:"proposed",label:"Proposed",states:["pending","checking"],hint:"Accept to start a Memory agent"},{id:"queued",label:"Queued",states:["accepted","queued","launching"],hint:"One Memory chat at a time"},{id:"running",label:"In progress",states:["running","saving","stopping","undoing"],hint:"Verifies sources and saves the approved fact"},{id:"attention",label:"Needs attention",states:["failed","cancelled"],hint:"Read the chat before retrying"},{id:"done",label:"Saved",states:["saved"],hint:"Confirmed by the Memory provider"},{id:"undone",label:"Undone",states:["undone"],hint:"Saves you chose to undo"},{id:"closed",label:"Dismissed",states:["rejected"],hint:"Facts you chose to dismiss"}],sa={pending:"Proposed",checking:"Checking Memory",saving:"Saving",saved:"Saved",undoing:"Undoing",undone:"Undone",accepted:"Accepted · not started",queued:"Queued",launching:"Starting chat",running:"In progress",stopping:"Stopping",awaiting_review:"To verify",failed:"Failed",cancelled:"Stopped",implemented:"Done",rejected:"Dismissed"},lt=e=>["implemented","rejected","saved","undone"].includes(we(e));function aa(e){const t=we(e);return t==="pending"?[[e.kind==="memory"?"approve":"accept",e.kind==="memory"?"Accept & save":"Accept & start"],["reject","Dismiss"]]:t==="saved"?e.details.node_created?[["undo","Undo save"]]:[]:t==="accepted"?[["start","Start implementation"],["reject","Dismiss"]]:["queued","launching","running"].includes(t)?[["stop",t==="queued"?"Remove from queue":"Stop implementation"]]:t==="awaiting_review"?[["implemented","Confirm implemented"],["retry","Continue fixing"]]:["failed","cancelled"].includes(t)?[["retry","Retry in same chat"],["reject","Dismiss"]]:[]}function ia(e,t){const n=we(e);if(t==="queued")return n==="pending"?e.kind==="memory"?"approve":"accept":n==="accepted"?"start":["failed","cancelled","awaiting_review"].includes(n)?"retry":void 0;if(t==="done"&&n==="awaiting_review")return"implemented";if(t==="closed"&&["pending","accepted","failed","cancelled"].includes(n))return"reject"}function Tt(e,t,n=!0){const s=we(e),a=aa(e),i=(l,p)=>`<button class="settings-secondary ${l==="accept"?"ticket-primary":""}" data-learning-item="${d(e.id)}" data-learning-command="${l}" ${t?"disabled":""}>${p}</button>`,r=[...new Set(e.evidence.map(l=>l.session_id))],o=e.details.memory_matches||[],c=`${n?`<p>${d(e.body)}</p>`:""}<dl class="learning-proposal-details">${["generalization","expected_impact","verification"].filter(l=>e.details[l]).map(l=>`<dt>${{generalization:"Why this helps other tasks",verification:"Verification",expected_impact:"Expected impact"}[l]}</dt><dd>${d(e.details[l])}</dd>`).join("")}</dl>
    ${e.evidence.map(l=>`<blockquote><p>${d(l.quote)}</p><small>${d(l.role)} · ${d(l.turn_id)} · <a href="/app/chat/threads/${encodeURIComponent(l.session_id)}">Source chat</a></small></blockquote>`).join("")}
    ${e.implementation?.summary?`<details data-learning-disclosure="${d(e.id)}-summary"><summary>Agent result</summary><p class="ticket-summary">${d(e.implementation.summary)}</p></details>`:""}
    ${e.status==="pending"?`<details data-learning-disclosure="${d(e.id)}-edit"><summary>Edit proposal</summary><label>Title<input data-learning-title="${d(e.id)}" value="${d(e.title)}" maxlength="240"></label><label>Description<textarea data-learning-body="${d(e.id)}" rows="3" maxlength="4000">${d(e.body)}</textarea></label>${i("edit","Save edit")}</details>`:""}`;return`<article class="learning-ticket ${n?"":"ticket-list-row"}" data-ticket-id="${d(e.id)}" data-ticket-state="${d(s)}">
    <div class="ticket-top"><span>${d(e.details.category||"Improvement")}</span>${a.length?`<button class="ticket-grip" draggable="${!t}" data-learning-drag="${d(e.id)}" aria-label="Move ${d(e.title)} between columns" title="Drag to Queued, Done or Dismissed; actions below also work with keyboard" ${t?"disabled":""}><span class="material-symbols-rounded" aria-hidden="true">drag_indicator</span></button>`:""}</div>
    <h4>${d(e.title)}</h4><p class="ticket-description">${d(e.body)}</p>
    <div class="ticket-meta"><span>${d(sa[s]||s)}</span>${e.details.effort?`<span>${d(e.details.effort)} effort</span>`:""}<span>${r.length} source chat${r.length===1?"":"s"}${e.occurrences>1?` · ${e.occurrences} observations`:""}</span></div>
    ${e.implementation?.error?`<p class="learning-error" role="status">${d(e.implementation.error)}</p>`:""}
    ${e.details.review_stale&&!lt(e)?'<p class="ticket-note">The source chat changed. Accepted tickets wait for reassessment before an agent starts.</p>':""}
    ${e.details.review_reason?`<p class="ticket-note">${d(e.details.review_reason)}</p>`:""}
    ${s==="awaiting_review"?'<p class="ticket-note">The agent finished its turn. Review the changes and checks in Chat.</p>':""}
    ${s==="pending"&&e.kind==="memory"&&o.length?`<label>Memory destination<select data-learning-target="${d(e.id)}" aria-label="Memory destination"><option value="">Choose destination</option>${o.map(l=>`<option value="${d(l.id)}">Attach to ${d(l.title)}</option>`).join("")}<option value="new">Create separate fact</option></select></label>`:""}
    ${e.details.memory_check_error||e.details.save_error?`<p class="learning-error">${d(e.details.save_error||e.details.memory_check_error)}</p>`:""}
    <div class="learning-actions">${e.kind==="memory"&&e.status==="saved"?`<a class="settings-secondary" href="/app/${encodeURIComponent(e.provider_id||"memory")}/nodes/${encodeURIComponent(e.node_id)}">Open Memory</a>`:""}${e.implementation?.session_id?`<a class="settings-secondary" href="/app/chat/threads/${encodeURIComponent(e.implementation.session_id)}">Open work chat <span aria-hidden="true">↗</span></a>`:""}${a.slice(0,1).map(([l,p])=>i(l,p)).join("")}</div>
    <details class="ticket-details" data-learning-disclosure="${d(e.id)}-ticket"><summary>Details &amp; evidence</summary>${c}${a.slice(1).map(([l,p])=>i(l,p)).join("")}</details>
  </article>`}function ra(e){const t=e.tab==="memory",n=t?"memory":"improvement",s=e.data.items.filter(u=>u.kind===n),a=e.ticketFilter||"open",i=e.ticketView||"board",r=(e.ticketSearch||"").trim().toLocaleLowerCase(),o=[...new Set(s.map(u=>u.details.category).filter(Boolean))].sort(),c=s.filter(u=>(a==="all"||(a==="closed"?lt(u):!lt(u)))&&(!e.ticketCategory||u.details.category===e.ticketCategory)&&(!r||`${u.title} ${u.body}`.toLocaleLowerCase().includes(r))),l=(t?na:ta).filter(u=>a==="all"||(a==="closed"?["done","closed","undone"].includes(u.id):!["done","closed","undone"].includes(u.id))),p=e.data.projects?.[n];return`${e.error?`<p class="learning-error" role="alert">${d(e.error)}</p>`:""}${e.notice?`<p class="ticket-queue-note" role="status" aria-live="polite">${d(e.notice)}</p>`:""}<div class="ticket-toolbar"><div class="ticket-toolbar-title"><strong>${t?"Memory":"Improvement"} tickets <span>${s.length}</span></strong><small>${t?"Accept a fact to start a Chat agent that verifies its sources and saves it to Memory.":"Accept a proposal to start a Chat agent with its source context."}${p?` <a href="/app/chat/projects/${encodeURIComponent(p)}">Open ${t?"Memory":"Improvements"} project ↗</a>`:""}</small></div>
    <div class="ticket-toolbar-controls"><div class="ticket-segment" role="group" aria-label="Ticket status filter">${["open","all","closed"].map(u=>`<button data-ticket-filter="${u}" aria-pressed="${a===u}">${{open:"Open",all:"All",closed:"Closed"}[u]}</button>`).join("")}</div>
    <div class="ticket-segment" role="group" aria-label="Ticket view">${["board","list"].map(u=>`<button data-ticket-view="${u}" aria-pressed="${i===u}" aria-label="${u==="board"?"Kanban board":"Ticket list"}"><span class="material-symbols-rounded" aria-hidden="true">${u==="board"?"view_kanban":"view_list"}</span></button>`).join("")}</div></div>
    <input id="ticket-search" data-settings-controlled type="search" aria-label="Search improvement tickets" placeholder="Search tickets…" value="${d(e.ticketSearch||"")}"><select id="ticket-category" data-settings-controlled aria-label="Ticket category"><option value="">All categories</option>${o.map(u=>`<option value="${d(u)}" ${u===e.ticketCategory?"selected":""}>${d(u)}</option>`).join("")}</select></div>
    <p class="ticket-queue-note">${t?"One Memory work chat runs at a time. Saved means the provider confirmed the write.":`Up to ${e.data.settings.improvement_concurrency??4} improvement chats run in parallel. Configure the limit in Usage & retention.`} Accepted tickets use normal Chat usage; analysis pause and allowance apply to analysis.${e.data.items.length>=200?" Showing the first 200 learning results.":""}</p>
    ${e.data.runtime_ready===!1?'<p class="learning-notice" role="status">Work chats are waiting for the backend update. Accepted tickets stay queued until launching is available.</p>':""}
    ${i==="board"?`<div class="learning-kanban" role="region" aria-label="Improvement ticket board" tabindex="0">${l.map(u=>{const m=c.filter(S=>u.states.includes(we(S)));return`<section class="ticket-column" data-ticket-column="${u.id}" aria-label="${u.label}"><header><h4><i aria-hidden="true"></i>${u.label}<span>${m.length}</span></h4><small>${u.hint}</small></header><div class="ticket-dropzone">${m.map(S=>Tt(S,e.saving)).join("")||'<div class="ticket-column-empty">No tickets</div>'}</div></section>`}).join("")}</div>`:`<div class="learning-list">${c.map(u=>Tt(u,e.saving,!1)).join("")||'<div class="learning-empty"><strong>No matching tickets</strong><p>Change the filters or wait for new proposals.</p></div>'}</div>`}`}function oa(e,t,n){document.querySelectorAll("[data-ticket-filter]").forEach(a=>v(a,"click",()=>n({ticketFilter:a.dataset.ticketFilter}))),document.querySelectorAll("[data-ticket-view]").forEach(a=>v(a,"click",()=>n({ticketView:a.dataset.ticketView}))),v(document.querySelector("#ticket-search"),"input",a=>n({ticketSearch:a.target.value})),v(document.querySelector("#ticket-category"),"change",a=>n({ticketCategory:a.target.value}));let s="";document.querySelectorAll("[data-learning-drag]").forEach(a=>{v(a,"dragstart",i=>{if(e.saving){i.preventDefault();return}s=a.dataset.learningDrag,i.dataTransfer?.setData("text/plain",s),i.dataTransfer&&(i.dataTransfer.effectAllowed="move")}),v(a,"dragend",()=>{s="",document.querySelectorAll(".ticket-column.is-over").forEach(i=>i.classList.remove("is-over"))})}),document.querySelectorAll("[data-ticket-column]").forEach(a=>{const i=()=>{const r=e.data?.items.find(o=>o.id===s);return r&&ia(r,a.dataset.ticketColumn)};v(a,"dragover",r=>{!e.saving&&i()&&(r.preventDefault(),a.classList.add("is-over"))}),v(a,"dragleave",r=>{a.contains(r.relatedTarget)||a.classList.remove("is-over")}),v(a,"drop",r=>{r.preventDefault();const o=i();a.classList.remove("is-over"),o&&!e.saving&&t(s,o),s=""})})}function la(e){let t={data:null,error:"",loading:!1,saving:!1,tab:"memory",detail:null,dependency:null,dirty:!1},n="",s=0,a=0,i=0,r=null,o=!1,c=!1;const l=new Map,p=new Map,u=new Map,m=E=>L("/api/apps/chat/backend",{method:"POST",body:JSON.stringify(E)});function S(){r?.(),r=null}function g(){const E=document.querySelector(".learning-kanban")?.scrollLeft||0,_=document.activeElement,h=_?.id?`#${_.id}`:_?.getAttribute("name")?`[name="${_.getAttribute("name")}"]`:["data-learning-title","data-learning-body","data-learning-target"].map(Z=>_?.hasAttribute(Z)?`[${Z}="${_.getAttribute(Z)}"]`:"").find(Boolean),f=_ instanceof HTMLTextAreaElement||_ instanceof HTMLInputElement?[_.selectionStart,_.selectionEnd]:null,y=new Set(t.openSections);document.querySelectorAll("[data-learning-disclosure]").forEach(Z=>{Z.open?y.add(Z.dataset.learningDisclosure):y.delete(Z.dataset.learningDisclosure)}),t.openSections=[...y],e.render();const I=document.querySelector(".learning-kanban");I&&(I.scrollLeft=E);const j=h?document.querySelector(h):null;j?.focus({preventScroll:!0}),f?.[0]!=null&&(j instanceof HTMLTextAreaElement||j instanceof HTMLInputElement&&["text","search"].includes(j.type))&&j.setSelectionRange(f[0],f[1])}function T(){s++,n="",c=!1,l.clear(),p.clear(),u.clear(),S(),t={data:null,error:"",loading:!1,saving:!1,tab:"memory",detail:null,dependency:null,dirty:!1}}function $(){if(!o||r)return;const E=s,_=()=>{E===s&&(c=!0,t.saving||b(!0))};r=us(h=>{h.workspace_id===n&&h.owner_app_id==="chat"&&h.resource==="learning"&&_()},_)}async function b(E=!1){const _=e.workspaceId();if(!_||(n!==_&&(T(),n=_),t.loading||!E&&t.data))return;const h=s,f=++a;c=!1,t.loading=!0,t.data||g();try{const[y,I]=await Promise.all([m({action:"learning.read"}),ht("chat")]);if(h!==s||f!==a||_!==e.workspaceId())return;t.data=y,t.dependency=I,t.error=""}catch(y){h===s&&f===a&&(t.error=Qe(y))}finally{h===s&&f===a&&(t.loading=!1,g(),c&&!t.saving&&o&&b(!0))}}async function R(E,_){if(t.saving)return;const h=s;a++,t.loading=!1,t.saving=!0,t.error="",t.notice="",g();try{if(_&&await _(),h!==s||(await m(E),h!==s))return;const f=E;if(f.action==="learning.configure"&&f.settings&&"enabled"in f.settings&&(l.clear(),z("#learning-settings")),t.notice=f.action==="learning.configure"?"Settings saved":["accept","approve","start","retry"].includes(f.command||"")?"Ticket queued. Its work chat appears when the agent starts.":f.command==="implemented"?"Implementation confirmed.":f.command==="stop"?"Stop requested. This chat keeps its slot until the turn ends.":"Action completed",f.item_id){const y=f.item_id;for(const I of p.keys())I.endsWith(":"+y)&&p.delete(I);z(["data-learning-title","data-learning-body","data-learning-target"].map(I=>`[${I}="${CSS.escape(y)}"]`).join(", "))}t.dirty=l.size>0||p.size>0,await b(!0)}catch(f){h===s&&(t.error=Qe(f))}finally{h===s&&(t.saving=!1,g(),c&&o&&b(!0))}}async function w(E){const _=new FormData(E),h={};h.paused=t.data.settings.paused;for(const I of["enabled","memory_enabled","improvements_enabled"])h[I]=_.get(I)==="on";for(const I of["idle_seconds","max_context_chars","max_output_tokens","timeout_seconds","daily_token_budget","retention_days"])h[I]=Number(_.get(I));_.has("improvement_concurrency")&&(h.improvement_concurrency=Number(_.get("improvement_concurrency")));for(const I of["memory_mode","model_source","model_id","reasoning_effort","instructions"])h[I]=String(_.get(I)||"");for(const I of["excluded_thread_ids","excluded_project_ids"])h[I]=String(_.get(I)||"").split(/[\s,]+/).filter(Boolean);const f=String(_.get("memory_provider")||""),y=t.dependency?.dependencies.find(I=>I.alias==="learning-memory")?.selected_provider_app_ids[0]||"";await R({action:"learning.configure",settings:h},f!==y?()=>sn("chat","learning-memory",f?[f]:[]):void 0)}function C(){const E=(h,f)=>{const y=document.querySelector(`[data-learning-target="${h}"]`)?.value||"",I=document.querySelector(`[data-learning-title="${h}"]`)?.value,j=document.querySelector(`[data-learning-body="${h}"]`)?.value;R({action:"learning.review",item_id:h,command:f,target_node_id:y==="new"?"":y,confirm_new:y==="new",title:I,body:j})};oa(t,E,h=>{Object.assign(t,h),g()});const _=document.querySelector("#learning-settings");if(_){for(const f of _.elements){if(!(f instanceof HTMLInputElement||f instanceof HTMLSelectElement||f instanceof HTMLTextAreaElement)||!f.name||!l.has(f.name))continue;const y=l.get(f.name);f instanceof HTMLInputElement&&f.type==="checkbox"?f.checked=y===!0:f.value=String(y)}const h=()=>{t.dirty=!0;for(const f of _.elements)(f instanceof HTMLInputElement||f instanceof HTMLSelectElement||f instanceof HTMLTextAreaElement)&&f.name&&l.set(f.name,f instanceof HTMLInputElement&&f.type==="checkbox"?f.checked:f.value);P()};v(_,"input",h),v(_,"change",h),P()}v(_,"submit",h=>{h.preventDefault(),w(_)}),v(document.querySelector("#learning-refresh"),"click",()=>{b(!0)}),v(document.querySelector("#learning-discard"),"click",()=>{t.dirty=!1,l.clear(),p.clear(),t.notice="",z("#learning-settings, .learning-results"),g()}),v(document.querySelector("#learning-pause"),"click",()=>{R({action:"learning.configure",settings:{paused:!t.data.settings.paused}})}),v(document.querySelector("#learning-session"),"change",h=>{t.selectedSession=h.target.value,g()}),document.querySelectorAll("[data-learning-disclosure]").forEach(h=>{h.open=!!t.openSections?.includes(h.dataset.learningDisclosure),v(h,"toggle",()=>{if(!h.isConnected)return;const f=new Set(t.openSections);h.open?f.add(h.dataset.learningDisclosure):f.delete(h.dataset.learningDisclosure),t.openSections=[...f]})}),v(document.querySelector("#learning-analyze"),"click",()=>{const h=document.querySelector("#learning-session")?.value;h&&R({action:"learning.analyze_now",session_id:h})});for(const h of["data-learning-title","data-learning-body","data-learning-target"])document.querySelectorAll(`[${h}]`).forEach(f=>{const y=h+":"+f.getAttribute(h);p.has(y)&&(f.value=p.get(y)),v(f,"input",()=>{p.set(y,f.value),t.dirty=!0,P()})});document.querySelectorAll('.learning-results a[href^="/app/"]').forEach(h=>v(h,"click",f=>{if(window.parent===window||f.ctrlKey||f.metaKey)return;f.preventDefault();const y=new URL(h.href).pathname.split("/").filter(Boolean),I=window.__MAVERICK_PLATFORM_ORIGIN__||"*";window.parent.postMessage({type:"maverick.app.open-app",app_id:decodeURIComponent(y[1]),params:{app_page:y.slice(2).map(decodeURIComponent).join("/")}},I)})),document.querySelectorAll("[data-learning-tab]").forEach(h=>v(h,"click",()=>{u.set(t.tab,{ticketView:t.ticketView,ticketFilter:t.ticketFilter,ticketSearch:t.ticketSearch,ticketCategory:t.ticketCategory}),i++,t.tab=h.dataset.learningTab,t.detail=null,Object.assign(t,{ticketView:void 0,ticketFilter:void 0,ticketSearch:void 0,ticketCategory:void 0},u.get(t.tab)),g()})),document.querySelectorAll("[data-learning-tab]").forEach((h,f,y)=>v(h,"keydown",I=>{const j={ArrowRight:(f+1)%y.length,ArrowLeft:(f+y.length-1)%y.length,Home:0,End:y.length-1}[I.key];j!==void 0&&(I.preventDefault(),y[j].click(),document.querySelector(`#${y[j].id}`)?.focus())})),document.querySelectorAll("[data-learning-job]").forEach(h=>v(h,"click",async()=>{const f=h.dataset.learningJob,y=h.dataset.learningCommand;if(y!=="inspect"){await R({action:"learning.job",job_id:f,command:y});return}const I=s,j=++i;try{const Z=await m({action:"learning.job",job_id:f,command:y});I===s&&j===i&&(t.detail=Z.job,g())}catch(Z){I===s&&j===i&&(t.error=Qe(Z),g())}})),document.querySelectorAll("[data-learning-item]").forEach(h=>v(h,"click",()=>{const f=h.dataset.learningItem;E(f,h.dataset.learningCommand)}))}function B(E){if(o=E,!E){S();return}n&&$(),c&&!t.saving&&b(!0)}function P(){const E=document.querySelector("#learning-draft-status");E&&(E.textContent=t.dirty?"Unsaved changes":t.notice||"Settings are up to date");const _=document.querySelector("#learning-discard");_&&(_.disabled=!t.dirty||t.saving);const h=document.querySelector("[name=memory_enabled]"),f=document.querySelector("#learning-memory-options");f&&h&&(f.hidden=!h.checked);const y=document.querySelector("[name=model_source]")?.value;document.querySelectorAll("[data-learning-native]").forEach(j=>{j.hidden=y!=="workspace"});const I=document.querySelector("#learning-mode-hint");I&&(I.textContent=document.querySelector("[name=memory_mode]")?.value==="automatic"?"Only explicit user facts with verified quotes and no Memory matches are saved automatically.":"You approve each fact before it enters Memory.")}function M(){const E={};for(const[_,h]of l){if(_==="memory_provider"||!t.data)continue;const f=t.data.settings[_];E[_]=typeof f=="number"?Number(h):Array.isArray(f)?String(h).split(/[\s,]+/).filter(Boolean):h}return{...t,draftSettings:E}}return{load:b,reset:T,bind:C,setVisible:B,viewState:M}}function Qe(e){return e instanceof Error?e.message:"Learning operation failed"}function da(e,t){const n={...e.data.settings,...e.draftSettings},s=e.saving?"disabled":"",a=e.dependency?.dependencies.find(c=>c.alias==="learning-memory"),i=a?.selected_provider_app_ids[0]||"",r=(c,l,p,u)=>`<label class="learning-toggle ${u?"learning-channel":""}">
    ${u?`<span class="material-symbols-rounded learning-channel-icon" aria-hidden="true">${u}</span>`:""}
    <span class="learning-toggle-copy"><strong>${l}</strong><small>${p}</small></span>
    <input type="checkbox" role="switch" name="${c}" ${n[c]?"checked":""} ${s}><span class="learning-toggle-track" aria-hidden="true"></span></label>`,o=(c,l,p,u,m)=>`<label>${l}<input type="number" name="${c}" min="${p}" max="${u}" value="${n[c]}" required ${s}><small>${m}</small></label>`;return`<form id="learning-settings" class="settings-card learning-controls" aria-busy="${e.saving}">
    <div class="learning-section-heading"><div><h3>Automatic learning</h3><p>Learn lasting knowledge and new Maverick improvements from completed work.</p></div><span class="settings-pill">One analysis at a time</span></div>
    ${r("enabled","Enable learning","Review conversations after a quiet period. Unfinished work stays under observation.")}
    <div class="learning-channel-grid">
      ${r("memory_enabled","Memory","Keep sourced discoveries, people, events and lasting knowledge.","neurology")}
      ${r("improvements_enabled","Improvements","Find general limits of Maverick; skip work already requested or underway.","lightbulb")}
    </div>
    <div class="learning-form-grid" id="learning-memory-options" ${n.memory_enabled?"":"hidden"}>
      <label>Save to<select name="memory_provider" ${s}><option value="">Choose a Memory provider</option>${a?.candidates.map(c=>`<option value="${d(c.app_id)}" ${c.app_id===i?"selected":""}>${d(c.name)}</option>`).join("")||""}</select><small id="learning-provider-hint">${i?"Facts and their chat evidence are saved to this app.":"Choose a provider to check existing knowledge and save facts."}</small></label>
      <label>Saving mode<select name="memory_mode" ${s}><option value="review" ${n.memory_mode==="review"?"selected":""}>Review before saving</option><option value="automatic" ${n.memory_mode==="automatic"?"selected":""}>Save supported explicit facts automatically</option></select><small id="learning-mode-hint">${n.memory_mode==="automatic"?"Only explicit user facts with verified quotes and no Memory matches are saved automatically.":"You approve each fact before it enters Memory."}</small></label>
    </div>
    <p class="learning-note">A quiet chat is not necessarily finished. Proposals require a completed work episode; development instructions do not become Memory.</p>
    <details class="learning-advanced" data-learning-disclosure="timing" ${e.openSections?.includes("timing")?"open":""}>
      <summary><span><strong>Timing &amp; model</strong><small>${n.idle_seconds} seconds after the last response · ${n.model_source==="workspace"?"Workspace Codex":"Fast API model"}</small></span><span class="material-symbols-rounded" aria-hidden="true">expand_more</span></summary>
      <div class="learning-form-grid">
        ${o("idle_seconds","Quiet period (seconds)",0,3600,"Delay before review. New messages postpone it; this delay does not certify that work is finished.")}
        <label>Analysis model<select name="model_source" ${s}><option value="workspace" ${n.model_source==="workspace"?"selected":""}>Workspace Codex</option><option value="fast_model" ${n.model_source==="fast_model"?"selected":""}>Configured fast API model</option></select><small>API mode uses the fast model configured in platform settings.</small></label>
        <label data-learning-native ${n.model_source==="workspace"?"":"hidden"}>Codex model<select name="model_id" ${s}><option value="">Workspace default</option>${t.map(c=>`<option value="${d(c.model_id)}" ${c.model_id===n.model_id?"selected":""}>${d(c.label||c.model_id)}</option>`).join("")}${n.model_id&&!t.some(c=>c.model_id===n.model_id)?`<option selected value="${d(n.model_id)}">${d(n.model_id)} (unavailable)</option>`:""}</select></label>
        <label data-learning-native ${n.model_source==="workspace"?"":"hidden"}>Reasoning<select name="reasoning_effort" ${s}>${["low","medium","high"].map(c=>`<option value="${c}" ${n.reasoning_effort===c?"selected":""}>${{low:"Low · faster",medium:"Medium",high:"High · more thorough"}[c]}</option>`).join("")}</select></label>
      </div>
    </details>
    <details class="learning-advanced" data-learning-disclosure="limits" ${e.openSections?.includes("limits")?"open":""}>
      <summary><span><strong>Usage &amp; retention</strong><small>${n.daily_token_budget.toLocaleString()} tokens per day · ${n.retention_days} days of transcripts</small></span><span class="material-symbols-rounded" aria-hidden="true">expand_more</span></summary>
      <div class="learning-form-grid">
        ${o("daily_token_budget","Daily token allowance",1e3,1e7,"UTC day. Each analysis reserves tokens before it starts.")}
        ${o("max_context_chars","Context limit (characters)",4e3,6e4,"Maximum conversation evidence per analysis.")}
        ${o("max_output_tokens","Output limit (tokens)",128,8192,"Maximum size of the generated suggestions.")}
        ${o("timeout_seconds","Timeout (seconds)",10,300,"Stop an analysis if it takes too long.")}
        ${o("retention_days","Transcript retention (days)",1,365,"Saved Memory facts and review decisions remain available.")}
        <label>Parallel improvement agents<input type="number" name="improvement_concurrency" min="1" max="8" value="${n.improvement_concurrency??4}" required ${s}><small>Up to this many improvement chats run together. Memory always runs one chat at a time.</small></label>
      </div>
    </details>
    <details class="learning-advanced" data-learning-disclosure="scope" ${e.openSections?.includes("scope")?"open":""}>
      <summary><span><strong>Exclusions &amp; instructions</strong><small>${n.excluded_thread_ids.length+n.excluded_project_ids.length?`${n.excluded_thread_ids.length+n.excluded_project_ids.length} exclusions`:"All eligible chats"} · optional guidance</small></span><span class="material-symbols-rounded" aria-hidden="true">expand_more</span></summary>
      <div class="learning-form-grid">
        <label>Excluded chat IDs<textarea name="excluded_thread_ids" rows="2" ${s}>${d(n.excluded_thread_ids.join(`
`))}</textarea><small>One ID per line. The ID is the last part of a chat URL.</small></label>
        <label>Excluded project IDs<textarea name="excluded_project_ids" rows="2" ${s}>${d(n.excluded_project_ids.join(`
`))}</textarea><small>One ID per line. Chats in these projects are skipped.</small></label>
        <label class="learning-wide">Additional guidance<textarea name="instructions" rows="3" maxlength="4000" placeholder="For example: focus on tool failures, missing capabilities and sourced discoveries…" ${s}>${d(n.instructions)}</textarea></label>
      </div>
    </details>
    <div class="learning-save-bar"><span id="learning-draft-status" role="status">${e.dirty?"Unsaved changes":e.notice||"Settings are up to date"}</span><div class="learning-actions"><button type="button" class="settings-secondary" id="learning-discard" ${e.dirty&&!e.saving?"":"disabled"}>Discard edits</button><button class="settings-primary" type="submit" ${s}>${e.saving?"Saving…":"Save settings"}</button></div></div>
  </form>`}const ca=e=>({pending:"To review",checking:"Checking Memory",saving:"Saving",saved:"Saved",undoing:"Undoing",undone:"Undone",rejected:"Rejected",accepted:"Accepted",implemented:"Implemented",queued:"Waiting",running:"Analyzing",completed:"Completed",failed:"Failed",cancelled:"Cancelled"})[e]||e;function qt(e){return d(new Date(e*1e3).toLocaleString())}function ua(e,t=[]){const{data:n,error:s,saving:a}=e;if(!n)return`<section class="settings-card learning-empty"><strong>${e.loading?"Loading learning settings…":"Learning is unavailable"}</strong>${s?`<p role="alert">${d(s)}</p>`:""}<button class="settings-secondary" id="learning-refresh">Retry</button></section>`;const i=n.settings,r=n.counts||{pending_memory:n.items.filter(g=>g.kind==="memory"&&g.status==="pending").length,pending_improvements:n.items.filter(g=>g.kind==="improvement"&&g.status==="pending").length,queued:n.jobs.filter(g=>g.status==="queued").length,running:n.jobs.filter(g=>g.status==="running").length,failed:n.jobs.filter(g=>g.status==="failed").length,budget_waiting:0},o=i.enabled?i.paused?"Paused":!i.memory_enabled&&!i.improvements_enabled?"No outputs selected":r.running?"Analyzing":"On":"Off",c=i.enabled?i.paused?"Chats are still captured. Resume when you are ready.":!i.memory_enabled&&!i.improvements_enabled?"Choose Memory or Improvements to start analysis.":r.running?"One conversation is being reviewed. The others wait in the queue.":"Quiet periods trigger review. Only completed work can produce proposals.":"Enable learning to capture future conversations.",l=n.daily_tokens_reserved_or_used,p=Math.min(100,Math.round(l/i.daily_token_budget*100)),u=a?"disabled":"",m=g=>n.conversations.find(T=>T.session_id===g)?.label||`Chat ${g.slice(0,8)}`,S={memory:r.open_memory??r.pending_memory,improvements:r.open_improvement??r.pending_improvements,analyses:r.queued+r.running,audit:0};return`<section class="settings-card learning-overview">
    <div class="learning-status-row"><div class="learning-status-copy"><span class="learning-status-dot ${i.enabled&&!i.paused?"is-on":""}" aria-hidden="true"></span><div><h3>Learning is ${o.toLowerCase()}</h3><p>${c}</p></div></div><div class="learning-actions">${i.enabled?`<button id="learning-pause" class="settings-secondary" ${u}>${i.paused?"Resume analysis":"Pause analysis"}</button>`:""}<button id="learning-refresh" class="learning-icon-button" aria-label="Refresh learning status" ${u}><span class="material-symbols-rounded" aria-hidden="true">refresh</span></button></div></div>
    <div class="learning-stats"><div><strong>${r.pending_memory+r.pending_improvements}</strong><span>To review</span></div><div><strong>${r.queued}</strong><span>In queue</span></div><div class="learning-usage"><div><span>Today’s token allowance</span><strong>${p}%</strong></div><progress value="${Math.min(l,i.daily_token_budget)}" max="${i.daily_token_budget}" aria-label="Daily learning token allowance"></progress><small>${l.toLocaleString()} / ${i.daily_token_budget.toLocaleString()} reserved or observed · resets at 00:00 UTC</small></div></div>
    ${l>=i.daily_token_budget?'<p class="learning-notice">Today’s allowance is reached. New analyses wait until the next UTC day or a higher saved allowance.</p>':""}
    ${r.budget_waiting&&l<i.daily_token_budget?'<p class="learning-notice">The remaining allowance cannot cover the next analysis. Increase it in Usage &amp; retention or wait for the UTC reset. Codex reserves extra tokens for its instructions.</p>':""}
    ${r.failed?`<p class="learning-notice">${r.failed} failed ${r.failed===1?"analysis":"analyses"}. Open the Analyses tab to inspect or retry.</p>`:""}
    ${s?`<p class="learning-error" role="alert">${d(s)}</p>`:""}
  </section>
  ${da(e,t)}
  <section class="settings-card learning-results">
    <div class="learning-section-heading"><div><h3>Results &amp; history</h3><p>Review suggestions and see what the agent has done.</p></div></div>
    <div class="learning-manual"><label for="learning-session">Analyze a captured chat</label><div class="learning-actions"><select id="learning-session" data-settings-controlled ${!n.conversations.length||a?"disabled":""}><option value="">${n.conversations.length?"Choose a conversation…":"No captured conversations yet"}</option>${n.conversations.map(g=>`<option value="${d(g.session_id)}" ${e.selectedSession===g.session_id?"selected":""}>${d(m(g.session_id))}</option>`).join("")}</select><button id="learning-analyze" class="settings-secondary" ${a||!i.enabled||i.paused||!e.selectedSession||!i.memory_enabled&&!i.improvements_enabled?"disabled":""}>Analyze now</button></div><p class="learning-note">${i.enabled?i.paused?"Resume analysis to use the queue.":"Adds new captured messages to the same serial queue; active chats wait until ready.":"Enable learning first. Only conversations captured after activation are available."}</p></div>
    <div class="learning-tabs" role="tablist" aria-label="Learning results">${["memory","improvements","analyses","audit"].map(g=>`<button id="learning-tab-${g}" role="tab" aria-controls="learning-panel" aria-selected="${e.tab===g}" tabindex="${e.tab===g?"0":"-1"}" class="${e.tab===g?"is-active":""}" data-learning-tab="${g}">${{memory:"Memory",improvements:"Improvements",analyses:"Analyses",audit:"Activity"}[g]}${S[g]?`<span>${S[g]}</span>`:""}</button>`).join("")}</div>
    <div id="learning-panel" role="tabpanel" aria-labelledby="learning-tab-${e.tab}" tabindex="0">
    ${e.tab==="improvements"||e.tab==="memory"?ra(e):""}
    ${e.tab==="analyses"?`<div class="learning-list">${n.jobs.map(g=>`<article class="learning-row"><div><div class="learning-item-heading"><strong>${d(m(g.session_id))}</strong><span class="settings-pill">${d(ca(g.status))}</span></div><p>${qt(g.created_at)} · ${g.attempts} attempt(s) · ${g.usage||g.reserved} tokens${g.model?` · ${d(g.model)}`:""}</p>${g.error?`<p class="learning-error">${d(g.error)}</p>`:""}</div><div class="learning-actions"><button class="settings-secondary" data-learning-job="${d(g.id)}" data-learning-command="inspect">Details</button>${["queued","running"].includes(g.status)?`<button class="settings-secondary" data-learning-job="${d(g.id)}" data-learning-command="cancel" ${u}>Cancel</button>`:["failed","cancelled"].includes(g.status)?`<button class="settings-secondary" data-learning-job="${d(g.id)}" data-learning-command="retry" ${u}>Retry</button>`:""}</div></article>`).join("")||'<div class="learning-empty"><strong>No analyses yet</strong><p>After activation, finish a chat and wait for the quiet period. Its analysis will appear here.</p></div>'}</div>`:""}
    ${e.tab==="audit"?`<div class="learning-list">${n.audit.map(g=>`<div class="learning-row"><span>${d(g.action.replaceAll("."," · ").replaceAll("_"," "))}</span><small>${qt(g.created_at)} · ${d(g.actor)}</small></div>`).join("")||'<div class="learning-empty"><strong>No activity yet</strong><p>Settings changes and review decisions will appear here.</p></div>'}</div>`:""}
    ${e.detail?`<details class="learning-transcript" open><summary>Analysis details · ${d(e.detail.id)}</summary><h4>Conversation evidence</h4><pre>${d(JSON.stringify(e.detail.input,null,2))}</pre><h4>Agent result</h4><pre>${d(e.detail.output_text||"No output available. The run may be pending or its transcript retention period has ended.")}</pre></details>`:""}
    </div>
  </section>`}let cn=!0;const dt=()=>cn&&!document.hidden;function pa(e){window.addEventListener("message",t=>{if(!ft(t)||!t.data||typeof t.data!="object")return;const n=t.data;(n.type==="maverick.shell.theme-changed"||n.type==="maverick.app.navigate"&&(!n.app_id||n.app_id==="settings"))&&qn(n.theme),n.type==="maverick.app.visibility-changed"&&n.app_id==="settings"&&(cn=n.visible===!0,e.visibilityChanged(dt())),n.type==="maverick.app.navigate"&&(!n.app_id||n.app_id==="settings")&&e.navigate(n.params||{})}),document.addEventListener("visibilitychange",()=>e.visibilityChanged(dt())),window.parent?.postMessage({type:"maverick.app.ready",app_id:"settings"},"*")}function ga(e){return L("/api/admin/users",{method:"POST",body:JSON.stringify(e)})}function ma(e,t){return L(`/api/admin/users/${encodeURIComponent(e)}`,{method:"PATCH",body:JSON.stringify(t)})}function fa(e,t){return L(`/api/admin/users/${encodeURIComponent(e)}/password`,{method:"POST",body:JSON.stringify({password:t})})}function va(e){return L(`/api/admin/users/${encodeURIComponent(e)}`,{method:"DELETE"})}function ha(e,t){return L(`/api/admin/users/${encodeURIComponent(e)}/workspaces`,{method:"PUT",body:JSON.stringify({memberships:t})})}function _a(e){return L(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"POST",body:JSON.stringify({source_id:e.source_id,enabled:!0})})}function ba(e,t){return L(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"PATCH",body:JSON.stringify({status:t?"enabled":"disabled"})})}function ya(e){return L(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"DELETE",body:JSON.stringify({})})}function ct(e,t){if(!t)return e;const n="items"in t?t.items:t.sessions,s="cleanup_allowed"in t?t.cleanup_allowed:e.runtime.cleanup_allowed,a="cleanup_scope"in t?t.cleanup_scope:e.runtime.cleanup_scope;return{...e,runtime:{...e.runtime,all_sessions:n||[],cleanup_allowed:s,cleanup_scope:a}}}function wa(e){const t=e?.provider.hosted_text?.active_provider||null,n=e?.provider.hosted_text?.model_settings||null;return $a(t,n)}function un(e){const t=e?.provider.hosted_text||null,n=t?.active_provider||null;return(t?.available_providers?.length?t.available_providers:n?[n]:[]).flatMap(a=>{const i=a.provider_id===n?.provider_id&&t?.model_settings||null;return ka(a,i).map(r=>({...r,hosted_text_profile:t?.profiles?.find(o=>o.profile.provider_id===a.provider_id&&o.profile.model_id===r.model_id)||null,metadata:{...r.metadata||{},hosted_provider_id:a.provider_id,hosted_provider_label:a.label||a.provider_id,hosted_provider_status:a.status}}))})}function $a(e,t){return{modelId:t?.selected_model_id||e?.default_model_family||""}}function ka(e,t){const n=t?.selected_model_id||e?.default_model_family||"",s=Ze(t?.available_models).length?Ze(t?.available_models):Ze(e?.model_options);return(s.length?s:n?[Ea(n,t?.selected_reasoning_effort||"")]:[]).map(Sa)}function Ze(e){return(e||[]).filter(t=>t.model_id)}function Sa(e){return e.supported_reasoning_efforts.length||!e.default_reasoning_effort?e:{...e,supported_reasoning_efforts:[{effort:e.default_reasoning_effort,label:e.default_reasoning_effort,description:null}]}}function Ea(e,t){return{model_id:e,label:e,description:null,default_reasoning_effort:t||null,supported_reasoning_efforts:t?[{effort:t,label:t,description:null}]:[]}}function Aa(){return{computerUse:Hs(),savedDrafts:null,speechSynthesis:an(),activatingNativeProviders:new Set,nativeProviderErrors:{},agenticBindingErrors:{},cleanupError:"",clearingAllRuntime:!1,cleaningSessionIds:new Set,hostedDraftModelId:"",hostedProviderError:"",hostedProviderErrorModelId:"",hostedRoutingDraftsByModel:{},isSavingHostedProvider:!1,isSavingSpeechProvider:!1,isLoadingProviderUsage:!1,isLoadingUsageHistory:!1,savingAgenticBindings:new Set,pendingAgenticEnabled:{},providerUsageError:"",providerUsageItems:[],usageHistory:null,usageHistoryFilters:ot(),usageHistoryError:"",speechAudioModelId:"",speechConversationModelId:"",speechProviderError:""}}function oe(e,t,n={}){t?.computer_use&&it(e.computerUse,t);const s=t?.workspace.workspace_id||"",a=e.savedDrafts?.workspaceId===s?e.savedDrafts:null,{modelId:i}=wa(t),r=Ta(t),o=new Set([...un(t).map(l=>l.model_id),i,...Object.keys(a?e.hostedRoutingDraftsByModel:{})].filter(Boolean)),c=Object.fromEntries(Array.from(o).map(l=>[l,je(Be(t,l))]));(!a||e.hostedDraftModelId===a.hostedModelId||n.hostedModelId)&&(e.hostedDraftModelId=i),(!a||e.speechAudioModelId===a.audioModelId||n.speech)&&(e.speechAudioModelId=r.audioModelId),(!a||e.speechConversationModelId===a.conversationModelId||n.speech)&&(e.speechConversationModelId=r.conversationModelId),e.hostedRoutingDraftsByModel=Object.fromEntries(Array.from(o).map(l=>{const p=e.hostedRoutingDraftsByModel[l],u=a&&p&&JSON.stringify(p)!==JSON.stringify(a.routing[l]);return[l,u&&n.hostedModelId!==l?p:c[l]]})),e.savedDrafts={workspaceId:s,hostedModelId:i,audioModelId:r.audioModelId,conversationModelId:r.conversationModelId,routing:Object.fromEntries(Object.entries(c).map(([l,p])=>[l,{...p}]))}}function Ca(e,t,n){e.hostedDraftModelId=n,mn(e,t,n),e.hostedProviderError="",e.hostedProviderErrorModelId=""}function Ia(e,t){e.speechAudioModelId=t,e.speechProviderError=""}function Ma(e,t){e.speechConversationModelId=t,e.speechProviderError=""}function Pa(e,t,n,s,a){if(!n)return;const i=mn(e,t,n);e.hostedDraftModelId=n,s==="mode"&&typeof a=="string"&&["auto","prefer","only","ignore"].includes(a)?i.mode=a:s==="provider_id"&&typeof a=="string"?i.providerId=a:s==="allow_fallbacks"&&typeof a=="boolean"?i.allowFallbacks=a:s==="require_parameters"&&typeof a=="boolean"?i.requireParameters=a:s==="zdr"&&typeof a=="boolean"?i.zdr=a:s==="sort"&&typeof a=="string"&&["","price","throughput","latency"].includes(a)?i.sort=a:s==="data_collection"&&typeof a=="string"&&["","allow","deny"].includes(a)?i.dataCollection=a:s==="quantization"&&typeof a=="string"&&(i.quantization=a),e.hostedProviderError="",e.hostedProviderErrorModelId=""}function pn(e,t=e.hostedDraftModelId){const n=e.hostedRoutingDraftsByModel[t]||Ra();return{mode:n.mode,provider_id:n.providerId||void 0,allow_fallbacks:n.allowFallbacks,require_parameters:n.requireParameters,zdr:n.zdr,sort:n.sort,data_collection:n.dataCollection,quantizations:n.quantization?[n.quantization]:[]}}function Ta(e){const t=e?.provider.speech_stt||null,n=t?.active_provider||t?.available_providers?.find(i=>i.provider_id==="deepgram")||null,s=De(t,n,"prerecorded_transcription"),a=De(t,n,"conversational_streaming");return{audioModelId:t?.model_settings?.audio_transcription_model_id||s.find(i=>i.model_id==="nova-3")?.model_id||s[0]?.model_id||"nova-3",conversationModelId:t?.model_settings?.conversation_model_id||a.find(i=>i.model_id==="flux-general-multi")?.model_id||a[0]?.model_id||"flux-general-multi"}}function De(e,t,n){const s=n==="prerecorded_transcription"?e?.model_settings?.available_audio_transcription_models:e?.model_settings?.available_conversation_models;return s?.length?s:(e?.model_settings?.available_models?.length?e.model_settings.available_models:t?.model_options||[]).filter(i=>i.metadata?.purpose===n)}function Be(e,t){const n=e?.provider.hosted_text?.selection?.openrouter_provider_routing_by_model?.[t];return{mode:n?.mode||"auto",provider_id:n?.provider_id||"",allow_fallbacks:n?.allow_fallbacks!==!1,require_parameters:n?.require_parameters===!0,zdr:n?.zdr===!0,sort:n?.sort||"",data_collection:n?.data_collection||"",quantizations:n?.quantizations||[]}}function gn(e,t,n){const s=Be(t,n),a=pn(e,n);return s.mode!==a.mode||(s.provider_id||"")!==(a.provider_id||"")||s.allow_fallbacks!==!1!=(a.allow_fallbacks!==!1)||s.require_parameters===!0!=(a.require_parameters===!0)||s.zdr===!0!=(a.zdr===!0)||(s.sort||"")!==(a.sort||"")||(s.data_collection||"")!==(a.data_collection||"")||(s.quantizations?.[0]||"")!==(a.quantizations?.[0]||"")}function qa(e,t){return t.hostedProviderErrorModelId?t.hostedProviderErrorModelId:!t.hostedDraftModelId||!gn(t,e,t.hostedDraftModelId)?"":t.hostedDraftModelId}function Da(e,t,n){return e.hostedRoutingDraftsByModel[n]||je(Be(t,n))}function mn(e,t,n){return e.hostedRoutingDraftsByModel[n]||(e.hostedRoutingDraftsByModel[n]=je(Be(t,n))),e.hostedRoutingDraftsByModel[n]}function je(e){return{allowFallbacks:e.allow_fallbacks!==!1,dataCollection:e.data_collection||"",mode:e.mode||"auto",providerId:e.provider_id||"",quantization:e.quantizations?.[0]||"",requireParameters:e.require_parameters===!0,sort:e.sort||"",zdr:e.zdr===!0}}function Ra(){return je({mode:"auto",allow_fallbacks:!0,require_parameters:!1,zdr:!1,sort:"",data_collection:"",quantizations:[]})}function re(e,t,n=""){return`<label class="settings-toggle settings-bouncy-toggle ${n}">
    ${e}
    <span class="settings-bouncy-toggle__label">${t}</span>
    <span class="settings-bouncy-toggle__track" aria-hidden="true">
      <span class="settings-bouncy-toggle__inner"></span>
      <span class="settings-bouncy-toggle__thumb"><span class="settings-bouncy-toggle__dot"></span></span>
    </span>
  </label>`}function La(e=document){e.querySelectorAll(".settings-bouncy-toggle").forEach(t=>{const n=s=>t.classList.toggle("is-pressed",s);v(t,"pointerdown",()=>n(!0)),v(t,"pointerup",()=>n(!1)),v(t,"pointerleave",()=>n(!1))})}const Ha=[{family_id:"native_agent",label:"CLI models",description:"Models running through an installed CLI.",workspace_actions:!0},{family_id:"maverick_agent",label:"API models",description:"Models running through a provider API.",workspace_actions:!0}];function Dt(e,t){return t?.find(n=>n.family_id===e)||Ha.find(n=>n.family_id===e)}function fn(e,t){return`<div class="settings-heading settings-platform-heading settings-model-card-heading">
    <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">${d(e)}</span>
      <div>
        <p class="settings-kicker">Models</p>
        <h2>${d(t)}</h2>
      </div>
    </div>`}function Ua(e,t,n,s,a){const i=new Set(s.filter(b=>a&&b.runtime_engine_id!=="codex"&&b.unavailable_reason==="native_agent_disabled"&&b.models.length>0).map(b=>b.runtime_engine_id)),r=e?.items||[],o=r,c=e?.release_decision||"GO",l=Dt("native_agent",n||e?.execution_families),p=Dt("maverick_agent",n||e?.execution_families),u=o.filter(b=>b.execution_family==="native_agent"||!b.execution_family&&b.runtime_engine_id==="codex"),m=o.filter(b=>b.execution_family==="maverick_agent"),S=new Set(r.filter(b=>b.execution_family==="native_agent"||!b.execution_family&&b.runtime_engine_id==="codex").map(b=>b.runtime_engine_id)),g=s.filter(b=>!S.has(b.runtime_engine_id)),T=[...Ba(u).map(b=>({html:Ht(b,t),providerId:b.runtime_engine_id,canActivate:i.has(b.runtime_engine_id),providerLabel:Ie(b.runtime_engine_id)})),...g.map(b=>({html:ja(b),providerId:b.runtime_engine_id,canActivate:i.has(b.runtime_engine_id),providerLabel:b.label||Ie(b.runtime_engine_id)}))],$=m.map(b=>({html:Ht(b,t),providerId:b.model_provider_id,providerLabel:Ie(b.model_provider_id)}));return`<section class="settings-card settings-platform settings-agentic-runtimes-card">
    ${fn("account_tree","Models")}
    ${c==="NO-GO"?'<p class="settings-platform-error settings-agentic-no-go"><strong>Remote agentic release: NO-GO</strong><br>Remote profiles remain visible for containment review but cannot be enabled or selected.</p>':""}
    ${Rt(l,T,t,"No native-agent runtime is registered by this installation.")}
    ${Rt(p,$,t,"No complete Maverick Agent profile is currently available.")}
  </section>`}function Rt(e,t,n,s){const a=Oa(t);return`<section class="settings-runtime-family" data-execution-family="${k(e.family_id)}">
    <header class="settings-runtime-family-heading">
      <h3>${d(e.label)}</h3>
    </header>
    <div class="settings-runtime-provider-list">
      ${a.length?a.map(i=>Na(i,n)).join(""):`<div class="settings-provider-usage-unavailable">
        <span class="material-symbols-rounded" aria-hidden="true">info</span>
        <span><strong>No available profiles</strong><small>${d(s)}</small></span>
      </div>`}
    </div>
  </section>`}function Oa(e){const t=new Map;e.forEach(s=>{const a=t.get(s.providerId)||[];a.push(s),t.set(s.providerId,a)});const n=new Map([["codex",0],["antigravity-cli",1],["openrouter",2],["google-ai-studio",3]]);return Array.from(t.entries()).map(([s,a])=>({providerId:s,providerLabel:a[0]?.providerLabel||Ie(s),items:a})).sort((s,a)=>(n.get(s.providerId)??100)-(n.get(a.providerId)??100)||s.providerLabel.localeCompare(a.providerLabel))}function Na(e,t){const n=e.items.some(i=>i.canActivate),s=t.activatingNativeProviders.has(e.providerId),a=t.nativeProviderErrors[e.providerId];return`<section class="settings-runtime-provider" data-agentic-provider-group="${k(e.providerId)}">
    <header class="settings-runtime-provider-heading">
      <h4>${d(e.providerLabel)}</h4>

    </header>
    ${n?`<div class="settings-native-provider-activation">
      <span>Connection disabled. Enable it for this installation to use the selected models.</span>
      <button type="button" data-native-provider-activate="${k(e.providerId)}" ${s?"disabled":""}>
        ${s?"Enabling…":`Enable ${d(e.providerLabel)}`}
      </button>
    </div>`:""}
    ${a?`<p class="settings-platform-error" role="alert">${d(a)}</p>`:""}
    <div class="settings-agentic-runtime-list">${e.items.map(i=>i.html).join("")}</div>
  </section>`}function Ie(e){return{"antigravity-cli":"Antigravity",codex:"Codex","google-ai-studio":"Google AI Studio",openrouter:"OpenRouter"}[e]||ye(e)}function Ba(e){const t=new Map,n=[];return e.forEach(s=>{const a=s.runtime_engine_id==="antigravity-cli"?s.model_id.replace(/-(high|medium|low)$/i,""):s.model_id,i=`${s.runtime_engine_id}\0${a}`;t.has(i)||n.push(i);const r=t.get(i);(!r||Lt(s.model_id)>Lt(r.model_id))&&t.set(i,s)}),n.map(s=>t.get(s)).filter(s=>!!s)}function Lt(e){const t=e.match(/-(high|medium|low)$/i)?.[1]?.toLowerCase();return t==="high"?3:t==="medium"?2:t==="low"?1:0}function ja(e){const t=e.models[0],n=e.unavailable_reason||"native_agent_unavailable",s=e.selectable===!0;return`<article class="settings-agentic-runtime settings-native-runtime-installation settings-agentic-runtime-static">
    <div class="settings-agentic-runtime-static__content">
      <span class="settings-model-summary-copy">
        <strong>${d(t?.model_id||e.label)}</strong>
        <small>${d(vn(t?.model_id,null))}</small>
      </span>
      <span class="settings-agentic-summary-badges">
        <span class="settings-pill ${s?"is-healthy":"is-warning"}">${s?"Available":d(ye(n))}</span>
      </span>
    </div>
  </article>`}function Ht(e,t){const n=e.definition_id,s=e.binding,a=s?.workspace_policy_ceiling||e.profile_policy_ceiling,i=s?.actor_policy||{allow_workspace_admins:!0,allowed_workspace_role_ids:["admin","member"]},r=e.execution_family==="maverick_agent",o=e.effective_capabilities,c=e.containment_status==="NO-GO",l=t.savingAgenticBindings.has(n),p=t.agenticBindingErrors[n]||"",u=a.max_estimated_cost_microusd===null?"":String(a.max_estimated_cost_microusd/1e6),m=e.credential_bindings,S=s?.credential_binding_id||m[0]?.binding_id||"",g=t.pendingAgenticEnabled[n]??!!s?.enabled,T=e.selectable===!0||!g&&e.enable_eligible===!0,$=e.enable_blocked_reason||e.blocked_reason||(r&&o?.status!=="active"?o?.reason_code||"effective capabilities unavailable":"")||"Unavailable";return`<details class="settings-model-accordion settings-agentic-runtime" data-settings-model-accordion="agentic-${k(n)}">
    <summary>
      <span class="settings-model-summary-copy">
        <strong>${d(Ut(e))}</strong>
        <small>${d(vn(e.model_id,e.default_reasoning_effort))}</small>
      </span>
      <span class="settings-agentic-summary-badges">
        ${s?.is_default?'<span class="settings-pill">Default</span>':""}
        ${c?'<span class="settings-pill is-warning">NO-GO</span>':""}
        ${T?"":`<span class="settings-pill is-warning">${d(ye($))}</span>`}
        <label class="settings-model-toggle settings-toggle settings-bouncy-toggle" title="${g?"Disable model":"Enable model"}">
          <input type="checkbox" role="switch" data-agentic-model-toggle data-settings-controlled aria-label="Enable ${k(Ut(e))}"
            data-agentic-definition-id="${k(e.definition_id)}"
            ${g?"checked":""} ${l||e.enable_eligible!==!0&&!g?"disabled":""}>
          <span class="settings-bouncy-toggle__label">${g?"On":"Off"}</span>
          <span class="settings-bouncy-toggle__track" aria-hidden="true">
            <span class="settings-bouncy-toggle__inner"></span>
            <span class="settings-bouncy-toggle__thumb"><span class="settings-bouncy-toggle__dot"></span></span>
          </span>
        </label>
      </span>
    </summary>
    <div class="settings-model-content settings-agentic-runtime-content" data-agentic-binding-form data-agentic-definition-id="${k(e.definition_id)}">
      ${c?`<div class="settings-provider-usage-unavailable settings-agentic-containment-state">
        <span class="material-symbols-rounded" aria-hidden="true">block</span>
        <span>
          <strong>NO-GO · ${d(ye(e.containment_reason||"remote agentic contained"))}</strong>
          <small>${d(e.data_destination.display_label)}</small>
        </span>
      </div>`:""}
      <div class="settings-agentic-controls">
        ${r?`<label class="settings-platform-field">
          <span>Credential binding</span>
          <select data-agentic-field="credential_binding_id" ${l||c?"disabled":""}>
            <option value="">${m.length?"No credential":"No active credential available"}</option>
            ${m.map(b=>`<option value="${k(b.binding_id)}" ${b.binding_id===S?"selected":""}>${d(b.label||b.binding_id)} · ${b.workspace_id?"workspace":"platform"}</option>`).join("")}
          </select>
        </label>`:'<input data-agentic-field="credential_binding_id" type="hidden" value="">'}
        <label class="settings-platform-field">
          <span>Maximum cost per turn (USD)</span>
          <input data-agentic-field="max_estimated_cost_usd" type="number" min="0" step="0.01" value="${k(u)}" placeholder="No explicit ceiling" ${l||c?"disabled":""}>
        </label>
        <div class="settings-platform-checks settings-agentic-checks">
          <input data-agentic-field="enabled" type="checkbox" ${g?"checked":""} hidden>
          ${pe("is_default","Use as workspace default",!!s?.is_default,l||c)}
          <details class="settings-agentic-advanced">
            <summary>Advanced controls</summary>
            ${pe("allow_workspace_admins","Workspace administrators",i.allow_workspace_admins,l||c)}
            ${pe("allow_workspace_members","Workspace members",i.allowed_workspace_role_ids.includes("member"),l||c)}
            ${pe("require_confirmation_for_mutating","Confirm mutating tools",a.require_confirmation_for_mutating,l||c,e.profile_policy_ceiling.require_confirmation_for_mutating)}
            ${pe("require_confirmation_for_destructive","Confirm destructive tools",a.require_confirmation_for_destructive,l||c,e.profile_policy_ceiling.require_confirmation_for_destructive)}
          </details>
        </div>
      </div>
      <button type="button" data-agentic-binding-save data-agentic-definition-id="${k(e.definition_id)}" ${l||c?"disabled":""}>
        <span class="material-symbols-rounded" aria-hidden="true">${l?"progress_activity":"verified_user"}</span>
        ${l?"Saving binding":s?"Save binding":"Create binding"}
      </button>
      ${p?`<p class="settings-platform-error" role="alert">${d(p)}</p>`:""}
    </div>
  </details>`}function pe(e,t,n,s,a=!1){return re(`<input data-agentic-field="${k(e)}" type="checkbox" role="switch" ${n?"checked":""} ${s||a?"disabled":""}>`,d(t))}function Ut(e){return e.runtime_engine_id==="codex"||e.runtime_engine_id==="antigravity-cli"?e.model_id:e.display_name.replace(/^OpenRouter\s+/i,"").replace(/^Google\s+/i,"").replace(/\s+·\s+Relace$/i,"")}function vn(e,t){const n=e?.match(/-(max|xhigh|high|medium|low)$/i)?.[1]||"",s=t||n;return`Reasoning · ${s?ye(s):"Preset"}`}function ye(e){return e.replace(/[._-]+/g," ").replace(/\b\w/g,t=>t.toUpperCase())}function Fa({modelOptions:e,openHostedModel:t,hostedProvider:n,settings:s,state:a,emptyMessage:i,inactiveMessage:r}){const o=!!n,c=Va(e,n);return`<div class="settings-hosted-models">
    ${e.length?c.map(l=>za(l,t,n,s,a)).join(""):`<p class="settings-card-copy settings-platform-note">${d(i)}</p>`}
    ${o?"":`<p class="settings-card-copy settings-platform-note">${d(r)}</p>`}
  </div>`}function za(e,t,n,s,a){const i=e.providerStatus==="active"?"Active provider":"Inactive provider";return`<section class="settings-hosted-provider-group" data-hosted-provider-group="${k(e.providerId)}">
    <div class="settings-hosted-provider-heading">
      <span>
        <strong>${d(e.providerLabel)}</strong>
        <small>${e.models.length} ${e.models.length===1?"model":"models"}</small>
      </span>
      <span class="settings-pill">${d(i)}</span>
    </div>
    ${e.models.map(r=>Wa(r,t,n,s,a)).join("")}
  </section>`}function Wa(e,t,n,s,a){const i=e.model_id,r=Da(a,s,i),o=e.upstream_provider_options||[],c=o.length>0,l=Array.from(new Set(o.map(w=>w.quantization||"").filter(Boolean))),p=hn(e,n),u=bn(e,n),m=!!p,S=a.isSavingHostedProvider&&a.hostedDraftModelId===i,g=s.provider.hosted_text?.selection?.provider_id||n?.provider_id||"",T=p===g&&(s.provider.hosted_text?.model_settings?.selected_model_id||n?.default_model_family)||"",$=!!(m&&u==="active"&&i&&!a.isSavingHostedProvider&&(p!==g||i!==T||gn(a,s,i))),b=i===t,R=_n(e,n);return`<details class="settings-model-accordion settings-hosted-model-accordion" data-settings-model-accordion="hosted:${k(i)}" data-hosted-model-accordion="${k(i)}" id="settings-hosted-${k(encodeURIComponent(i))}" ${b?"open":""}>
    <summary class="settings-model-trigger">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">record_voice_over</span>
      <span class="settings-model-copy">
        <span class="settings-model-kicker">
          <span class="settings-kicker">Hosted speech model</span>
        </span>
        <strong>${d(e.label||i)} - ${d(R)}</strong>
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
      <select data-openrouter-routing="mode" data-hosted-model-id="${k(i)}" ${!m||!o.length||a.isSavingHostedProvider?"disabled":""}>
        ${[["auto","Auto"],["prefer","Prefer selected"],["only","Only selected"],["ignore","Ignore selected"]].map(([w,C])=>`<option value="${k(w)}" ${w===r.mode?"selected":""}>${d(C)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Upstream provider</span>
      <select data-openrouter-routing="provider_id" data-hosted-model-id="${k(i)}" ${!m||!o.length||r.mode==="auto"||a.isSavingHostedProvider?"disabled":""}>
        <option value="">Select provider</option>
        ${o.map(w=>`<option value="${k(String(w.provider_id||w.tag||""))}" ${(w.provider_id||w.tag)===r.providerId?"selected":""}>${d(w.label||w.provider_id||w.tag||"Provider")}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Sort</span>
      <select data-openrouter-routing="sort" data-hosted-model-id="${k(i)}" ${!m||a.isSavingHostedProvider?"disabled":""}>
        ${[["","OpenRouter default"],["price","Price"],["throughput","Throughput"],["latency","Latency"]].map(([w,C])=>`<option value="${k(w)}" ${w===r.sort?"selected":""}>${d(C)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Data collection</span>
      <select data-openrouter-routing="data_collection" data-hosted-model-id="${k(i)}" ${!m||a.isSavingHostedProvider?"disabled":""}>
        ${[["","OpenRouter default"],["allow","Allow"],["deny","Deny"]].map(([w,C])=>`<option value="${k(w)}" ${w===r.dataCollection?"selected":""}>${d(C)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Quantization</span>
      <select data-openrouter-routing="quantization" data-hosted-model-id="${k(i)}" ${!m||!l.length||a.isSavingHostedProvider?"disabled":""}>
        <option value="">Any</option>
        ${l.map(w=>`<option value="${k(w)}" ${w===r.quantization?"selected":""}>${d(w)}</option>`).join("")}
      </select>
    </label>
    <div class="settings-platform-checks">
      ${re(`<input type="checkbox" role="switch" data-openrouter-routing="allow_fallbacks" data-hosted-model-id="${k(i)}" ${r.allowFallbacks?"checked":""} ${!m||a.isSavingHostedProvider?"disabled":""}>`,"Allow OpenRouter fallback")}
      ${re(`<input type="checkbox" role="switch" data-openrouter-routing="require_parameters" data-hosted-model-id="${k(i)}" ${r.requireParameters?"checked":""} ${!m||a.isSavingHostedProvider?"disabled":""}>`,"Require supported parameters")}
      ${re(`<input type="checkbox" role="switch" data-openrouter-routing="zdr" data-hosted-model-id="${k(i)}" ${r.zdr?"checked":""} ${!m||a.isSavingHostedProvider?"disabled":""}>`,"Require zero data retention")}
    </div>
    `:""}
    <button type="button" data-hosted-provider-save="${k(i)}" ${$?"":"disabled"}>
      <span class="material-symbols-rounded" aria-hidden="true">${S?"sync":"save"}</span>
      ${S?"Saving":"Save hosted model"}
    </button>
    ${a.hostedProviderError&&a.hostedProviderErrorModelId===i?`<p class="settings-platform-error">${d(a.hostedProviderError)}</p>`:""}
    </div>
  </details>`}function Va(e,t){const n=new Map;for(const s of e){const a=hn(s,t)||"hosted-provider",i=n.get(a);if(i){i.models.push(s);continue}n.set(a,{providerId:a,providerLabel:_n(s,t),providerStatus:bn(s,t),models:[s]})}return Array.from(n.values()).sort((s,a)=>s.providerStatus==="active"&&a.providerStatus!=="active"?-1:a.providerStatus==="active"&&s.providerStatus!=="active"?1:s.providerLabel.localeCompare(a.providerLabel))}function hn(e,t){const n=e.metadata?.hosted_provider_id;return typeof n=="string"&&n?n:t?.provider_id||""}function _n(e,t){const n=e.metadata?.hosted_provider_label;return typeof n=="string"&&n?n:t?.label||t?.provider_id||"Hosted provider"}function bn(e,t){const n=e.metadata?.hosted_provider_status;return typeof n=="string"&&n?n:t?.status||""}function Ja(e,t){const n=e?.active_provider||e?.available_providers?.find(R=>R.provider_id==="deepgram")||null,s=De(e,n,"prerecorded_transcription"),a=De(e,n,"conversational_streaming"),i=e?.model_settings?.audio_transcription_model_id||s[0]?.model_id||"nova-3",r=e?.model_settings?.conversation_model_id||a[0]?.model_id||"flux-general-multi",o=t.speechAudioModelId||i,c=t.speechConversationModelId||r,l=s.find(R=>R.model_id===o)||s[0]||null,p=a.find(R=>R.model_id===c)||a[0]||null,u=Nt(l,e?.model_settings?.endpoints?.audio_transcription||`https://api.deepgram.com/v1/listen?model=${o}`),m=Nt(p,e?.model_settings?.endpoints?.conversation||`wss://api.deepgram.com/v2/listen?model=${c}`),S=!!(e?.active_provider&&e?.credential_binding),g=!!(S&&o&&c&&!t.isSavingSpeechProvider&&(o!==i||c!==r)),T=n?.label||n?.provider_id||"Deepgram",$=n?.provider_id||"deepgram",b=S?"Active provider":"Inactive provider";return`<div class="settings-hosted-models settings-speech-models">
    <section class="settings-hosted-provider-group" data-speech-provider-group="${k($)}">
      <div class="settings-hosted-provider-heading">
        <span>
          <strong>${d(T)}</strong>
          <small>2 settings</small>
        </span>
        <span class="settings-pill">${d(b)}</span>
      </div>
      ${Ot({id:"settings-speech-audio-model",label:"Audio transcription model",icon:"hearing",value:o,options:s,endpoint:u,description:l?.description||"Deepgram model for prerecorded audio, files, and one-shot microphone transcription.",disabled:!S||t.isSavingSpeechProvider,canSave:g,isSaving:t.isSavingSpeechProvider})}
      ${Ot({id:"settings-speech-conversation-model",label:"Conversation model",icon:"forum",value:c,options:a,endpoint:m,description:p?.description||"Deepgram Flux model for realtime voice conversation and turn detection.",disabled:!S||t.isSavingSpeechProvider,canSave:g,isSaving:t.isSavingSpeechProvider})}
    </section>
    ${t.speechProviderError?`<p class="settings-platform-error">${d(t.speechProviderError)}</p>`:""}
    ${S?"":'<p class="settings-card-copy settings-platform-note">Activate Deepgram with a Core Secrets binding before using speech-to-text.</p>'}
  </div>`}function Ot({id:e,label:t,icon:n,value:s,options:a,endpoint:i,description:r,disabled:o,canSave:c,isSaving:l}){return a.length?`<details class="settings-model-accordion settings-speech-model-accordion">
    <summary class="settings-model-trigger">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">${d(n)}</span>
      <span class="settings-model-copy">
        <span class="settings-model-kicker">
          <span class="settings-kicker">${d(t)}</span>
        </span>
        <strong>${d(a.find(p=>p.model_id===s)?.label||s)}</strong>
        <small>${d(s)} · ${d(i)}</small>
      </span>
      <span class="settings-model-chevron material-symbols-rounded" aria-hidden="true">expand_more</span>
    </summary>
    <div class="settings-model-content settings-hosted-model-content">
      <label class="settings-platform-field settings-platform-field-wide">
        <span>${d(t)}</span>
        <select id="${k(e)}" ${o?"disabled":""}>
          ${a.map(p=>`<option value="${k(p.model_id)}" ${p.model_id===s?"selected":""}>${d(p.label||p.model_id)}</option>`).join("")}
        </select>
      </label>
      <div class="settings-platform-field settings-platform-field-wide">
        <span>Endpoint</span>
        <code class="settings-model-code">${d(i)}</code>
      </div>
      <p class="settings-card-copy">${d(r)}</p>
      <button type="button" data-speech-discard class="settings-secondary" ${c&&!l?"":"disabled"}>Discard edits</button>
      <button type="button" data-speech-save="${k(e)}" ${c?"":"disabled"}>
        <span class="material-symbols-rounded" aria-hidden="true">${l?"sync":"save"}</span>
        ${l?"Saving":"Save speech model"}
      </button>
    </div>
  </details>`:`<p class="settings-card-copy settings-platform-note">No ${d(t.toLowerCase())} options are available.</p>`}function Nt(e,t){const n=e?.metadata?.endpoint;return typeof n=="string"&&n?n:t}function Ga(e,t){const n=un(e).filter(Qa);return Ka(n,qa(e,t),e.provider.hosted_text?.active_provider||null,e.provider.speech_stt||null,e,t)}function Ka(e,t,n,s,a,i){return`<section class="settings-card settings-platform settings-speech-model-settings-card">
    ${fn("record_voice_over","Speech model settings")}
    <div class="settings-platform-provider-forms">
      ${Ls(i.speechSynthesis)}
      ${Fa({modelOptions:e,openHostedModel:t,hostedProvider:n,settings:a,state:i,emptyMessage:"No hosted speech models are available from the active hosted providers.",inactiveMessage:"Activate the hosted provider before saving speech model routing."})}
      ${Ja(s,i)}
    </div>
  </section>`}function Qa(e){return(e.output_modalities||[]).includes("speech")}function Za(e,t,n="models"){return e?n==="computer-use"?Us(e,t.computerUse):n==="voice"?Ga(e,t):Ua(e.agentic_admin||null,t,e.provider.execution_families,e.provider.native_agents?.items||[],e.user.platform_role==="admin"):'<section class="settings-card"><p role="alert">Settings unavailable.</p></section>'}const Ya=5,Xa=4,xa=4,ei=3,ti=4;function ni(e){return`<section class="settings-loading-skeleton" role="status" aria-label="Settings content is loading">
    <header class="detail-header settings-loading-skeleton__header" aria-hidden="true">
      <div class="detail-title-block">
        ${H("title")}
        <span class="detail-title-separator" aria-hidden="true"></span>
        ${H("subtitle")}
      </div>
    </header>
    ${si(e)}
  </section>`}function si(e){return e.id==="workspace-access"?ri():e.id==="workspace-apps"?oi():["models","voice","computer-use","usage","sessions"].includes(e.id)?li():e.id==="persistence"?di():e.id==="cache"?ai():e.id==="learning"?`<section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">${se(!0)}<div class="settings-loading-skeleton__field-grid">${Q(3,()=>H("copy"))}</div></section>
      <section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">${se(!0)}${Q(2,()=>F("toggle"))}${Q(3,()=>H("copy-wide"))}${F("button")}</section>`:ii()}function ai(){return`<section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
    ${se(!0)}
    ${H("copy-wide")}
    <div class="settings-loading-skeleton__rows">
      ${Q(4,()=>wn())}
    </div>
    ${F("button")}
  </section>`}function ii(){return`<section class="settings-card settings-loading-skeleton__create" aria-hidden="true">
      ${ci("short-title")}
      ${Q(Ya,()=>F("field"))}
      ${F("button")}
    </section>
    ${yn()}
    <div class="settings-loading-skeleton__profile-row" aria-hidden="true">
      <section class="settings-card settings-loading-skeleton__detail-card">
        ${se(!0)}
        <div class="settings-loading-skeleton__field-grid">
          ${Q(Xa,()=>Re())}
        </div>
        ${F("toggle")}
        ${F("button")}
      </section>
      <section class="settings-card settings-loading-skeleton__password-card">
        ${se(!1)}
        ${H("copy")}
        <div class="settings-loading-skeleton__field-grid">
          ${Q(2,()=>Re())}
        </div>
        ${F("button")}
        ${F("danger-button")}
      </section>
    </div>`}function ri(){return`${yn()}
    <section class="settings-card" aria-hidden="true">
      ${se(!0)}
      <div class="settings-loading-skeleton__rows">
        ${Q(xa,()=>ui())}
      </div>
    </section>`}function oi(){return`<section class="settings-card" aria-hidden="true">
      ${se(!1)}
      ${H("copy-wide")}
      <div class="settings-loading-skeleton__rows">
        ${Q(ei,()=>pi())}
      </div>
    </section>`}function li(){return`<section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
      ${Ye()}
    </section>
    <section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
      ${Ye()}
      <div class="settings-loading-skeleton__provider-form">
        ${Q(2,()=>Re())}
        ${F("button")}
      </div>
      ${Ye()}
    </section>
    <section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
      <div class="settings-loading-skeleton__runtime-toolbar">
        ${H("copy-wide")}
        ${F("button")}
      </div>
      <div class="settings-loading-skeleton__runtime-list">
        ${Q(ti,()=>gi())}
      </div>
    </section>`}function di(){return`<section class="settings-card settings-loading-skeleton__persistence" aria-hidden="true">
      ${se(!0)}
      <div class="settings-loading-skeleton__adapter-cards">
        ${Q(2,()=>mi())}
      </div>
      ${wn()}
    </section>`}function yn(){return`<section class="settings-card settings-user-picker" aria-hidden="true">
    <div class="settings-loading-skeleton__copy-stack">
      ${H("kicker")}
      ${H("card-title")}
      ${H("copy-short")}
    </div>
    ${Re()}
  </section>`}function se(e){return`<div class="settings-loading-skeleton__heading">
    <span class="settings-loading-skeleton__copy-stack">
      ${H("kicker")}
      ${H("card-title")}
    </span>
    ${e?F("pill"):""}
  </div>`}function ci(e){return`<div class="settings-loading-skeleton__copy-stack">
    ${H("kicker")}
    ${H(e)}
  </div>`}function Re(){return`<span class="settings-loading-skeleton__field-wrap">
    ${H("label")}
    ${F("field")}
  </span>`}function ui(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--membership">
    ${F("checkbox")}
    ${ue("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${H("row-title")}
      ${H("row-copy")}
    </span>
    ${F("select")}
  </span>`}function pi(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--app">
    ${ue("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${H("row-title")}
      ${H("row-copy")}
    </span>
    ${F("toggle-pill")}
    ${F("button")}
  </span>`}function Ye(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--tile">
    ${ue("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${H("row-title")}
      ${H("row-copy")}
    </span>
  </span>`}function gi(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--runtime">
    ${ue("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${H("row-title")}
      ${H("row-copy")}
    </span>
    ${F("button")}
  </span>`}function mi(){return`<span class="settings-loading-skeleton__adapter-card">
    ${ue("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${H("row-title")}
      ${H("row-copy-wide")}
    </span>
    ${F("pill")}
  </span>`}function wn(){return`<span class="settings-loading-skeleton__result">
    ${ue("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${H("row-title")}
      ${H("row-copy-wide")}
    </span>
  </span>`}function H(e){return`<span class="settings-loading-skeleton__line settings-loading-skeleton__line--${e}"></span>`}function F(e){return`<span class="settings-loading-skeleton__block settings-loading-skeleton__block--${e}"></span>`}function ue(e){return`<span class="settings-loading-skeleton__icon settings-loading-skeleton__icon--${e}"></span>`}function Q(e,t){return Array.from({length:e},t).join("")}function fi({publishChanged:e,render:t,setNotice:n}){let s=[],a=[],i="",r=[],o="",c=!1,l=0,p=0,u="";const m=new Map;function S(){return{appRegistry:s,error:i,isLoading:c,loadErrors:r,savingKeys:new Set(m.keys()),dependencies:a.map(w=>({...w,dependencies:w.dependencies.map(C=>{const B=m.get(Bt(w.consumer_app_id,C.alias));return B?{...C,selected_provider_app_ids:B.providerAppIds}:C})}))}}function g(){l+=1,p+=1,c=!1,u="",m.clear(),s=[],a=[],i="",r=[],o=""}function T(){o=""}async function $(w,C,B=!1){if(!w||(u!==w&&(g(),u=w),c)||!B&&o===u)return;const P=++p;c=!0,i="",r=[],t();try{const[M,E]=await Promise.all([ws(),R(u,C)]);if(P!==p)return;s=M,a=E.dependencies,r=E.errors,o=u}catch(M){if(P!==p)return;o="",i=M instanceof Error?M.message:"Unable to load app links."}finally{P===p&&(c=!1,t())}}async function b(w,C,B){const P=l,M=Bt(w,C);if(m.has(M))return;const E={providerAppIds:[...B]};m.set(M,E),t();try{const _=await sn(w,C,B);if(P!==l||_.workspace_id!==u)return;p+=1,c=!1;const h=a.find(y=>y.consumer_app_id===w),f={..._,dependencies:_.dependencies.map(y=>y.alias===C?y:h?.dependencies.find(I=>I.alias===y.alias)||y)};a=[...a.filter(y=>y.consumer_app_id!==w),f].sort((y,I)=>y.consumer_app_id.localeCompare(I.consumer_app_id)),e(w,f),n({tone:"success",message:"App link updated."})}catch(_){if(P===l)throw _}finally{m.get(M)===E&&(m.delete(M),t())}}async function R(w,C){const B=C.filter(y=>y.workspace_id===w&&y.status==="enabled"),P=new Array(B.length);let M=0;const E=p;await Promise.all(Array.from({length:Math.min(4,B.length)},async()=>{for(;M<B.length&&E===p;){const y=M++,I=B[y];try{P[y]={app:I,payload:await ht(I.app_id)}}catch(j){P[y]={app:I,error:j instanceof Error?j.message:"Unable to load app links."}}}}));const _=P.filter(Boolean),h=_.filter(y=>"error"in y).map(y=>({app_id:y.app.app_id,message:y.error,name:y.app.name||y.app.app_id}));return{dependencies:_.filter(y=>"payload"in y&&y.payload.dependencies.length>0).map(y=>y.payload).sort((y,I)=>y.consumer_app_id.localeCompare(I.consumer_app_id)),errors:h}}return{ensureLoaded:$,invalidate:T,reset:g,saveDependencySelection:b,viewState:S}}function Bt(e,t){return`${e}:${t}`}function vi(e){let t=0;const n=new Map,s=a=>`${a.workspace_id}:${a.app_id}`;return{reset:()=>{t++,n.clear()},savingKeys:()=>new Set(n.keys()),apps:a=>a.map(i=>n.has(s(i))?{...i,status:n.get(s(i))?"enabled":"disabled"}:i),setEnabled:async(a,i)=>{const r=t,o=s(a);if(!n.has(o)){n.set(o,i),e.render();try{await ba(a,i),r===t&&e.updated(a,i)}catch(c){if(r===t)throw c}finally{r===t&&(n.delete(o),e.render())}}}}}function hi({appRegistry:e,dependencies:t,error:n,isLoading:s,loadErrors:a,savingKeys:i,workspaceApps:r}){return`<section class="settings-card settings-app-links">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">App links</p>
          <h2>Provider app links</h2>
          <button type="button" id="settings-refresh-app-links" class="settings-secondary" ${s?"disabled":""}>Refresh links</button>
        </div>
      </div>
      <p class="settings-card-copy">Provider links are workspace-scoped. A selected provider is reused until it becomes unavailable; otherwise one-provider interface links use the first available candidate as their automatic default.</p>
      ${n?`<p class="settings-platform-error">${d(n)}</p>`:""}
      ${a.length?`<div class="settings-app-link-errors">${a.map(Ei).join("")}</div>`:""}
      ${t.length>1?_i(t,e,r):""}
      <div class="settings-app-link-list">
        ${t.length?t.map(o=>bi(o,e,r,i)).join(""):wi(n,s)}
      </div>
    </section>`}function _i(e,t,n){return`<nav class="settings-app-link-consumer-nav" aria-label="Provider link apps">
    ${e.map(s=>{const a=n.find(o=>o.workspace_id===s.workspace_id&&o.app_id===s.consumer_app_id),i=wt(t,s.consumer_app_id),r=a?.name||i?.name||s.consumer_app_id;return`<a class="settings-app-link-consumer-nav__item" href="#${k($n(s.consumer_app_id))}">
        <strong>${d(r)}</strong>
        <small>${d(String(s.dependencies.length))}</small>
      </a>`}).join("")}
  </nav>`}function bi(e,t,n,s){const a=n.find(r=>r.workspace_id===e.workspace_id&&r.app_id===e.consumer_app_id),i=wt(t,e.consumer_app_id);return`<article class="settings-app-link-consumer" id="${k($n(e.consumer_app_id))}">
    <header class="settings-app-link-consumer__header">
      ${Sn(i)}
      <span class="settings-app-copy">
        <strong>${d(a?.name||e.consumer_app_id)}</strong>
        <small>${d(e.consumer_app_id)} - ${d(e.status)}</small>
      </span>
    </header>
    <div class="settings-app-link-dependencies">
      ${e.dependencies.map(r=>yi(e.consumer_app_id,r,t,s)).join("")}
    </div>
  </article>`}function yi(e,t,n,s){const a=s.has($i(e,t.alias)),i=ki(t),r=kn(t);return`<section class="settings-app-link-row" data-dependency-row="${k(e)}:${k(t.alias)}">
    <header class="settings-app-link-row__header">
      <span class="settings-app-link-row__copy">
        <strong>${d(t.alias)}</strong>
        <small>${d(t.interface)} ${d(t.version)}</small>
      </span>
      <span class="settings-pill ${t.status==="resolved"||r?"":"settings-pill-muted"}">${d(Si(t,r))}</span>
    </header>
    <p class="settings-card-copy">${d(t.description||"No description.")}</p>
    ${t.blocked_reason?`<p class="settings-platform-error">${d(t.blocked_reason)}</p>`:""}
    ${t.stale_provider_app_ids.length?`<p class="settings-platform-error">Unavailable selection: ${d(t.stale_provider_app_ids.join(", "))}</p>`:""}
    ${t.candidates.length?`<div class="settings-app-link-candidates">
            ${t.candidates.map(o=>{const c=i.includes(o.app_id),l=t.cardinality==="many"?"checkbox":"radio",p=`dependency:${e}:${t.alias}`,u=wt(n,o.app_id);return`<label class="settings-app-link-candidate ${c?"is-selected":""}">
                <input
                  data-settings-controlled
                  ${c?"checked":""}
                  ${a?"disabled":""}
                  data-dependency-choice="${k(jt(e,t.alias,o.app_id))}"
                  name="${k(p)}"
                  type="${l}"
                />
                ${Sn(u)}
                <span>
                  <strong>${d(o.name||o.app_id)}</strong>
                  <small>${d(o.app_id)} - ${d(o.interface_version)}${o.app_id===r?" - automatic default":""}</small>
                </span>
              </label>`}).join("")}
          </div>`:'<p class="settings-card-copy">No enabled provider app is available for this interface.</p>'}
    ${r?`<button type="button" class="settings-secondary" data-dependency-save-default="${k(jt(e,t.alias,r))}" ${a?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">${a?"sync":"save"}</span>
          ${a?"Saving":"Save default"}
        </button>`:""}
  </section>`}function wi(e,t){return e?"":t?'<p class="settings-card-copy">Loading app links...</p>':'<p class="settings-card-copy">No enabled app in the active workspace declares provider links.</p>'}function $i(e,t){return`${e}:${t}`}function jt(e,t,n){return`${e}:${t}:${n}`}function $n(e){return`settings-app-link-consumer-${e}`}function ki(e){if(e.selected_provider_app_ids.length)return e.selected_provider_app_ids;const t=kn(e);return t?[t]:[]}function kn(e){return e.selected_provider_app_ids.length||e.status!=="optional_unset"||e.cardinality!=="one"||e.stale_provider_app_ids.length||e.blocked_reason?"":e.candidates[0]?.app_id||""}function Si(e,t){return t?"auto default":e.status==="optional_unset"?"unset":e.status}function wt(e,t){return e.find(n=>n.app_id===t)||null}function Ei(e){return`<p class="settings-platform-error">${d(e.name||e.app_id)}: ${d(e.message)}</p>`}function Sn(e){if(e?.logo?.kind==="image"&&e.logo.value)return`<span class="settings-app-link-logo is-image"><img alt="" loading="lazy" src="${k(e.logo.value)}" /></span>`;const t=e?.logo?.value||"apps";return`<span class="settings-app-link-logo is-glyph"><span class="material-symbols-rounded" aria-hidden="true">${d(t)}</span></span>`}function Ai(e){const{dashboard:t,error:n,isClearing:s,isLoading:a}=e,i=s?"Clearing…":"Clear cache";return`<section class="settings-card settings-cache-diagnostics" aria-busy="${a||s}">
    <div class="settings-heading">
      <div>
        <span class="settings-kicker">This browser</span>
        <h3>Maverick cache</h3>
      </div>
      <span class="settings-pill settings-pill-muted">Disposable</span>
    </div>
    <p class="settings-card-copy">Inspect aggregate cache usage for this browser container. Cached entries and file copies are rebuildable and never authorize server actions.</p>
    ${n?`<div class="settings-cache-diagnostics__error" role="alert">${d(n)}</div>`:""}
    ${Ci(t,a)}
    <div class="settings-cache-diagnostics__actions">
      <button class="settings-secondary" id="refresh-pwa-cache" type="button" ${a||s?"disabled":""}>
        <span class="material-symbols-rounded" aria-hidden="true">refresh</span>
        Refresh
      </button>
      <button class="settings-secondary" id="clear-pwa-cache" type="button" ${a||s?"disabled":""}>
        <span class="material-symbols-rounded" aria-hidden="true">delete_sweep</span>
        ${i}
      </button>

    </div>
    <p class="settings-cache-diagnostics__note">Clear cache removes only Maverick's structured data and versioned file cache from this browser container. It does not delete server files, static app assets, or unrelated origin storage.</p>
  </section>`}function Ci(e,t){if(!e||t)return`<div class="settings-cache-diagnostics__grid" aria-label="Loading cache diagnostics">
      ${q("Cache data","—")}
      ${q("Entries","—")}
      ${q("Origin usage","—")}
      ${q("Origin quota","—")}
    </div>`;const{diagnostics:n,metrics:s}=e;return`<div class="settings-cache-diagnostics__section">
    <h4>Storage and quota</h4>
    <div class="settings-cache-diagnostics__grid">
    ${q("Cache data",ve(n.cacheBytes))}
    ${q("Entries",n.entryCount.toLocaleString())}
    ${q("Structured data",ve(n.structuredCacheBytes))}
    ${q("Structured entries",n.structuredEntryCount.toLocaleString())}
    ${q("File data",ve(n.fileCacheBytes))}
    ${q("File entries",n.fileCacheEntryCount.toLocaleString())}
    ${q("Origin usage",Ft(n.originUsageBytes))}
    ${q("Origin quota",Ft(n.originQuotaBytes))}
    ${q("Backend",n.backend==="indexeddb"?"IndexedDB":"Memory fallback")}
    ${q("File storage",n.fileCacheAvailable?"OPFS available":"Unavailable")}
    ${q("Pending cleanup",n.pendingCleanupCount.toLocaleString())}
    </div>
  </div>
  ${Ii(s)}
  ${Mi(s)}`}function Ii(e){const t=e.counters;return`<div class="settings-cache-diagnostics__section">
    <h4>Cache activity</h4>
    <p>Aggregate events in this browser since ${d(Ti(e.windowStartedAt))}.</p>
    <div class="settings-cache-diagnostics__grid">
      ${q("Static hit / miss",X(t.pwa_static_cache_hit,t.pwa_static_cache_miss))}
      ${q("Data hit / miss",X(t.pwa_data_cache_hit,t.pwa_data_cache_miss))}
      ${q("Data cache errors",K(t.pwa_data_cache_error))}
      ${q("Stale / expired",X(t.pwa_data_cache_stale,t.pwa_data_cache_expired))}
      ${q("Revalidated unchanged",K(t.pwa_revalidate_not_modified))}
      ${q("Revalidated changed",K(t.pwa_revalidate_modified))}
      ${q("Revalidation errors",K(t.pwa_revalidate_error))}
      ${q("File hit / miss",X(t.pwa_file_cache_hit,t.pwa_file_cache_miss))}
      ${q("File writes / ready",X(t.pwa_file_cache_write,t.pwa_file_cache_ready))}
      ${q("File errors",K(t.pwa_file_cache_error))}
      ${q("Evicted entries",K(t.pwa_eviction_count))}
      ${q("Evicted data",ve(t.pwa_eviction_bytes))}
      ${q("Quota usage samples",K(t.pwa_quota_usage))}
      ${q("Quota checks / errors",X(t.pwa_quota_estimate,t.pwa_quota_error))}
    </div>
  </div>`}function Mi(e){const t=e.counters,n=e.requestWait;return`<div class="settings-cache-diagnostics__section">
    <h4>Requests and recovery</h4>
    <div class="settings-cache-diagnostics__grid">
      ${q("Pending waits (this window)",K(n.pendingCount))}
      ${q("Oldest pending (this window)",Pi(n.oldestPendingMs))}
      ${q("Average wait",ut(n.averageDurationMs))}
      ${q("Longest wait",ut(n.maxDurationMs))}
      ${q("Resolved / cancelled",X(t.pwa_request_wait_resolved,t.pwa_request_wait_cancelled))}
      ${q("Retry attempts",K(t.pwa_request_retry_attempt))}
      ${q("Worker installs / updates",X(t.pwa_sw_install,t.pwa_sw_update))}
      ${q("Worker recoveries / errors",X(t.pwa_sw_recovery,t.pwa_sw_error))}
      ${q("Static cache errors",K(t.pwa_static_cache_error))}
    </div>
  </div>`}function q(e,t){return`<div class="settings-cache-diagnostics__metric">
    <span>${d(e)}</span>
    <strong>${d(t)}</strong>
  </div>`}function Ft(e){return e===null?"Unavailable":ve(e)}function ve(e){if(!Number.isFinite(e)||e<=0)return"0 B";const t=["B","KB","MB","GB"],n=Math.min(t.length-1,Math.floor(Math.log(e)/Math.log(1024))),s=e/1024**n;return`${s>=10||n===0?s.toFixed(0):s.toFixed(1)} ${t[n]}`}function K(e){return e.toLocaleString()}function X(e,t){return`${K(e)} / ${K(t)}`}function Pi(e){return e===null?"None":ut(e)}function ut(e){return!Number.isFinite(e)||e<=0?"0 ms":e<1e3?`${Math.round(e)} ms`:`${(e/1e3).toFixed(e<1e4?1:0)} s`}function Ti(e){const t=new Date(e);return Number.isFinite(t.getTime())?t.toLocaleString():"this session"}function qi(e){return Li(e)}function Di(e){const{deleteSourceAfterMigration:t,migrationPlan:n,migrationProgress:s,migrationTarget:a,persistence:i}=e;if(!a||!i)return"";const r=i.active_adapter.kind.toUpperCase(),o=a.toUpperCase(),c=!!(s&&!["complete","failed"].includes(s.phase)),l=!!(n&&!n.same_adapter&&!c);return`<div class="settings-modal-backdrop" role="presentation">
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
      ${n?Ni(n):Oi(s)}
      ${Ri(e)}
      ${re(`<input id="settings-delete-source" type="checkbox" role="switch" ${t?"checked":""} ${c?"disabled":""} />`,"Schedule source cleanup after restart health check","settings-migration-delete-source")}
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
  </div>`}function Ri(e){const t=e.targetDraft;if(!t)return"";const n=!!(e.migrationProgress&&!["complete","failed"].includes(e.migrationProgress.phase));return`<div class="settings-migration-target">
    <label class="settings-platform-field">
      <span>JSON root</span>
      <input data-migration-field="json_root" value="${k(t.json_root)}" ${n?"disabled":""} />
    </label>
    ${t.kind==="mongo"?`<label class="settings-platform-field">
          <span>Mongo URI</span>
          <input data-migration-field="mongodb_uri" value="${k(t.mongodb_uri)}" ${n?"disabled":""} />
        </label>
        <label class="settings-platform-field">
          <span>Mongo database</span>
          <input data-migration-field="mongodb_database" value="${k(t.mongodb_database)}" ${n?"disabled":""} />
        </label>
        <label class="settings-platform-field">
          <span>Mongo username</span>
          <input data-migration-field="mongodb_username" value="${k(t.mongodb_username||"")}" ${n?"disabled":""} />
        </label>
        <label class="settings-platform-field">
          <span>Password secret ref</span>
          <input data-migration-field="mongodb_password_ref" value="${k(t.mongodb_password_ref||"")}" ${n?"disabled":""} />
        </label>`:""}
  </div>`}function Li(e){const{migrationProgress:t,migrationResult:n,persistence:s}=e;if(!s)return`<section class="settings-card settings-persistence">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Persistence</p>
          <h2>Control plane adapter</h2>
        </div>
        <span class="settings-pill settings-pill-muted">offline</span>
      </div>
      <p class="settings-card-copy">The core persistence surfaces are not available in the active backend.</p>
    </section>`;const a=s.active_adapter,i=s.collections.reduce((l,p)=>l+p.count,0),r=a.kind==="json",o=a.kind==="mongo",c=t&&!["complete","failed"].includes(t.phase);return`<section class="settings-card settings-persistence">
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
    ${Hi(t)}
    ${Ui(n)}
  </section>`}function Hi(e){return e?`<div role="status" aria-live="polite" class="settings-migration-progress ${e.phase==="failed"?"is-failed":""} ${e.phase==="complete"?"is-complete":""}">
    <div class="settings-migration-progress-heading">
      <span class="material-symbols-rounded" aria-hidden="true">${e.phase==="complete"?"check_circle":e.phase==="failed"?"error":"sync"}</span>
      <span>
        <strong>${d(e.title)}</strong>
        <small>${d(e.detail)}</small>
      </span>

    </div>
  </div>`:""}function Ui(e){return e?`<div class="settings-migration-result">
    <span class="material-symbols-rounded" aria-hidden="true">task_alt</span>
    <span>
      <strong>Last migration</strong>
      <small>${e.collections.reduce((n,s)=>n+s.count,0)} documents · target ${d(e.target_adapter.kind)} · cleanup ${e.source_cleanup?.scheduled?"scheduled":"not requested"}</small>
    </span>
  </div>`:""}function Oi(e){return`<div class="settings-migration-plan">
    <span class="material-symbols-rounded" aria-hidden="true">rule</span>
    <span>
      <strong>${d(e?.title||"Dry run not validated")}</strong>
      <small>${d(e?.detail||"Adjust the target fields, then validate the dry run before applying migration.")}</small>
    </span>
  </div>`}function Ni(e){const t=e.collections.reduce((s,a)=>s+a.count,0),n=e.target_collections.reduce((s,a)=>s+a.count,0);return`<div class="settings-migration-plan">
    <span class="material-symbols-rounded" aria-hidden="true">${e.same_adapter?"block":"rule"}</span>
    <span>
      <strong>${e.same_adapter?"Target already active":"Dry run complete"}</strong>
      <small>${t} source documents · ${n} target documents before copy · env ${d(e.env_file)}</small>
    </span>
    <div class="settings-migration-collections">
      ${e.collections.map(s=>`<span><strong>${d(s.name)}</strong><small>${s.count}</small></span>`).join("")}
    </div>
  </div>`}function Bi({selectedUser:e,users:t}){return`<details class="settings-card settings-user-create"><summary>Create a user</summary><form class="settings-create" id="create-user">
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
    ${En(t,e)}
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
              <label>Name<input name="display_name" value="${k(e.display_name||"")}" /></label>
              <label>Email<input name="email" type="email" value="${k(e.email||"")}" /></label>
              <label>Platform role<select name="platform_role">
                <option value="member" ${e.platform_role==="member"?"selected":""}>Member</option>
                <option value="admin" ${e.platform_role==="admin"?"selected":""}>Admin</option>
              </select></label>
              <label>Account type<select name="account_type">
                <option value="standard" ${e.account_type==="standard"?"selected":""}>Standard</option>
                <option value="facilitated" ${e.account_type==="facilitated"?"selected":""}>Facilitated</option>
              </select></label>
            </div>
            ${re(`<input name="is_active" type="checkbox" role="switch" ${e.is_active?"checked":""} />`,"Account active")}
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
        </div>`:'<section class="settings-card"><h2>No users</h2></section>'}`}function zt({selectedUser:e,users:t,workspaces:n,showPicker:s=!0}){return`${s?En(t,e):""}
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
          <div class="settings-memberships">${ji(e,n)}</div>
          <button type="button" data-user-discard class="settings-secondary">Discard edits</button><p data-action-status class="settings-action-status" role="status"></p>
        </section>`:'<section class="settings-card"><h2>No users</h2></section>'}`}function En(e,t){return e.length?`<section class="settings-card settings-user-picker">
    <div>
      <p class="settings-kicker">User directory</p>
      <h2>${d(t?t.display_name||t.username:"Select user")}</h2>
      <p class="settings-card-copy">${e.length} user${e.length===1?"":"s"} available.</p>
    </div>
    <label class="settings-platform-field">
      <span>Selected user</span>
      <select id="selected-user" data-settings-controlled>
        ${e.map(n=>`<option value="${k(n.user_id)}" ${n.user_id===t?.user_id?"selected":""}>${d(n.display_name||n.username)} (${d(n.username)})</option>`).join("")}
      </select>
    </label>
  </section>`:`<section class="settings-card settings-user-picker">
      <div>
        <p class="settings-kicker">User directory</p>
        <h2>No users</h2>
      </div>
      <p class="settings-card-copy">Create a user before editing profile or workspace access settings.</p>
    </section>`}function ji(e,t){return t.map(n=>{const s=e.memberships.find(a=>a.workspace_id===n.workspace_id);return`<label class="settings-membership">
        <input type="checkbox" aria-label="Access to ${k(n.name)}" data-workspace-enabled="${k(n.workspace_id)}" ${s?"checked":""} />
        <span class="settings-membership-icon material-symbols-rounded" aria-hidden="true">workspaces</span>
        <span>
          <strong>${d(n.name)}</strong>
          <small>${d(n.workspace_id)}</small>
        </span>
        <select aria-label="Role in ${k(n.name)}" data-workspace-role="${k(n.workspace_id)}">
          <option value="member" ${s?.role!=="admin"?"selected":""}>Member</option>
          <option value="admin" ${s?.role==="admin"?"selected":""}>Workspace admin</option>
        </select>
      </label>`}).join("")}function Fi({workspaceApps:e,workspaces:t,savingKeys:n=new Set}){return`<details class="settings-card"><summary>Create a workspace</summary><form id="create-workspace" class="settings-grid">
    <label>Name<input name="name" required /></label><label>Description<input name="description" /></label><button type="submit">Create workspace</button>
    </form></details><section class="settings-card">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Workspace apps</p>
          <h2>Installation and visibility</h2>
        </div>
      </div>
      <p class="settings-card-copy">Installed means the app has a workspace binding. Only enabled apps are visible to users and served by the core.</p>
      <div class="settings-app-workspaces">${zi(t,e,n)}</div>
    </section>`}function zi(e,t,n){return e.map(s=>{const a=t.filter(o=>o.workspace_id===s.workspace_id),i=a.filter(o=>o.status==="enabled").length,r=a.filter(o=>o.installed).length;return`<details class="settings-app-workspace" data-workspace-row="${k(s.workspace_id)}">
        <summary class="settings-app-workspace-heading">
          <span class="settings-summary-caret material-symbols-rounded" aria-hidden="true">chevron_right</span>
          <span class="settings-app-workspace-icon material-symbols-rounded" aria-hidden="true">deployed_code</span>
          <span>
            <strong>${d(s.name)}</strong>
            <small>${d(s.workspace_id)} · ${i}/${r} enabled</small>
          </span>
        </summary>
        <div class="settings-apps">
          ${a.map(o=>Wi(o,n)).join("")}
        </div>
      </details>`}).join("")}function Wi(e,t){const n=e.status==="enabled",s=e.installed,a=s?e.status:"not installed",i=`${e.workspace_id}:${e.app_id}`,r=t.has(i);return`<div class="settings-app-row" data-app-row="${k(i)}">
    ${e.logo?.kind==="image"?`<img class="settings-app-icon" src="${k(e.logo.value)}" alt="" />`:`<span class="settings-app-icon material-symbols-rounded" aria-hidden="true">${d(e.logo?.kind==="glyph"?e.logo.value:"apps")}</span>`}
    <span class="settings-app-copy">
      <strong>${d(e.name)}</strong>
      <small>${d(e.app_id)} · v${d(e.version)} · ${d(a)}</small>
    </span>
    ${s?`${re(`<input type="checkbox" role="switch" data-settings-controlled aria-label="Enable ${k(e.name)} in ${k(e.workspace_name)}" data-app-toggle="${k(i)}" ${n?"checked":""} ${r?"disabled":""} />`,"Enabled","settings-switch")}
        <button type="button" class="settings-secondary" data-app-uninstall="${k(i)}" ${r?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">link_off</span>
          Uninstall
        </button>`:`<button type="button" class="settings-secondary" data-app-install="${k(i)}">
          <span class="material-symbols-rounded" aria-hidden="true">add_link</span>
          Install
        </button>`}
  </div>`}function Vi(e){const{page:t,selectedUser:n}=e;if(t.id==="installation")return'<div id="installation-root" data-settings-owned-view="installation"></div>';if(t.id==="users")return Bi({selectedUser:n,users:e.users})+zt({selectedUser:n,users:e.users,workspaces:e.workspaces,showPicker:!1});if(t.id==="workspace-access")return zt({selectedUser:n,users:e.users,workspaces:e.workspaces});if(t.id==="workspace-apps")return Fi({workspaceApps:e.workspaceApps,workspaces:e.workspaces,savingKeys:e.savingAppKeys});if(t.id==="app-links"){const s=e.appLinksController.viewState();return hi({appRegistry:s.appRegistry,dependencies:s.dependencies,error:s.error,isLoading:s.isLoading,loadErrors:s.loadErrors,savingKeys:s.savingKeys,workspaceApps:e.workspaceApps})}return["models","voice","computer-use"].includes(t.id)?e.platformSettingsHtml():t.id==="usage"?e.usageHtml():t.id==="sessions"?e.sessionsHtml():t.id==="learning"?e.learningHtml():t.id==="cache"?Ai(e.cacheDiagnosticsController.viewState()):qi(e.persistenceController.viewState())}async function Ae(e,t,n){if(!e||e.hasAttribute("data-pending-action"))return;const s=Array.from(e.querySelectorAll("input, button, select")),a=s.map(r=>r.disabled);e.setAttribute("data-pending-action",""),e.setAttribute("aria-busy","true");const i=e.querySelector("[data-action-status]");i&&(i.setAttribute("role","status"),i.textContent="Saving…");try{const r=t();s.forEach(o=>{o.disabled=!0}),await r,i&&(i.textContent="Saved.")}catch(r){i&&(i.setAttribute("role","alert"),i.textContent=r instanceof Error?r.message:"Unable to save."),n(r)}finally{e.removeAttribute("data-pending-action"),e.removeAttribute("aria-busy"),s.forEach((r,o)=>{r.disabled=a[o]})}}function Ji(e){document.querySelectorAll("[data-native-provider-activate]").forEach(t=>{v(t,"click",()=>{e.onActivateNativeProvider(t.dataset.nativeProviderActivate||"")})}),document.querySelectorAll("[data-agentic-binding-save]").forEach(t=>{v(t,"click",()=>{e.onSaveAgenticBinding(t.dataset.agenticDefinitionId||"")})}),document.querySelectorAll("[data-agentic-model-toggle]").forEach(t=>{v(t,"click",n=>n.stopPropagation()),v(t.closest("label"),"click",n=>n.stopPropagation()),v(t,"change",()=>{const n=t.checked;e.onSaveAgenticBinding(t.dataset.agenticDefinitionId||"",{enabled:n})})}),v(document.getElementById("settings-speech-audio-model"),"change",t=>{e.onSpeechAudioModelChanged(t.currentTarget.value)}),v(document.getElementById("settings-speech-conversation-model"),"change",t=>{e.onSpeechConversationModelChanged(t.currentTarget.value)}),document.querySelectorAll("[data-speech-save]").forEach(t=>{v(t,"click",()=>{e.onSaveSpeechProviderSettings()})}),v(document.getElementById("settings-speech-save"),"click",()=>{e.onSaveSpeechProviderSettings()}),document.querySelectorAll("[data-settings-model-accordion]").forEach(t=>{v(t,"toggle",()=>{t.open&&document.querySelectorAll("[data-settings-model-accordion]").forEach(n=>{n!==t&&(n.open=!1)})})}),document.querySelectorAll("[data-openrouter-routing]").forEach(t=>{v(t,"change",n=>{const s=n.currentTarget,a=s.dataset.hostedModelId||s.closest("[data-hosted-model-accordion]")?.dataset.hostedModelAccordion||"";e.onHostedProviderRoutingChanged(a,s.dataset.openrouterRouting||"",s instanceof HTMLInputElement&&s.type==="checkbox"?s.checked:s.value)})}),v(document.getElementById("settings-refresh-usage-history"),"click",e.onRefreshProviderUsage),document.querySelectorAll("[data-hosted-provider-save]").forEach(t=>{v(t,"click",()=>e.onSaveHostedProviderSettings(t.dataset.hostedProviderSave||""))}),v(document.getElementById("settings-logout"),"click",e.onLogout),v(document.getElementById("settings-clear-all-runtime"),"click",e.onClearAllRuntimeSessions),document.querySelectorAll("[data-runtime-clear]").forEach(t=>{v(t,"click",()=>e.onClearRuntimeSession(t.dataset.runtimeClear||""))})}function Gi(e){La(),v(document.getElementById("dismiss-notice"),"click",e.dismissNotice),v(document.getElementById("create-user"),"submit",n=>{n.preventDefault();const s=n.currentTarget;Ae(s,()=>e.createUser(s),e.showError)});const t=e.selectedUser();v(document.getElementById("selected-user"),"change",n=>{e.selectUser(n.currentTarget.value)}),v(document.getElementById("edit-user"),"submit",n=>{n.preventDefault();const s=n.currentTarget;t&&Ae(s,()=>e.updateSelectedUser(s,t),e.showError)}),v(document.getElementById("reset-password"),"submit",n=>{n.preventDefault();const s=n.currentTarget;t&&Ae(s,()=>e.resetSelectedUserPassword(s,t),e.showError)}),v(document.getElementById("delete-user"),"click",()=>{t&&e.deleteSelectedUser(t).catch(e.showError)}),v(document.getElementById("save-memberships"),"click",()=>{t&&Ae(document.getElementById("workspace-assignments"),()=>e.updateMemberships(t),e.showError)}),Zi(e),Qi(e),Yi(e),Ki(e),Ji({onClearAllRuntimeSessions:()=>{e.clearRuntimeSessionsFromPanel().catch(e.showError)},onClearRuntimeSession:n=>{n&&e.clearRuntimeSessionsFromPanel([n]).catch(e.showError)},onLogout:()=>{e.logoutFromSettings().catch(e.showError)},onHostedProviderRoutingChanged:e.onHostedProviderRoutingChanged,onActivateNativeProvider:n=>{e.activateNativeProviderFromPanel(n).catch(e.showError)},onSaveAgenticBinding:(n,s)=>{e.saveAgenticBindingFromPanel(n,s).catch(e.showError)},onRefreshProviderUsage:()=>{e.refreshProviderUsageFromPanel().catch(e.showError)},onSpeechAudioModelChanged:e.onSpeechAudioModelChanged,onSpeechConversationModelChanged:e.onSpeechConversationModelChanged,onSaveHostedProviderSettings:n=>{e.saveHostedProviderSettingsFromPanel(n).catch(e.showError)},onSaveSpeechProviderSettings:()=>{e.saveSpeechProviderSettingsFromPanel().catch(e.showError)}})}function Ki(e){v(document.getElementById("refresh-pwa-cache"),"click",()=>{e.cacheDiagnosticsController.ensureLoaded(!0).catch(e.showError)}),v(document.getElementById("clear-pwa-cache"),"click",()=>{e.cacheDiagnosticsController.clear().catch(e.showError)})}function Qi(e){document.querySelectorAll("[data-dependency-choice]").forEach(t=>{v(t,"change",()=>{const n=Wt(t.dataset.dependencyChoice||"");if(!n)return;const s=e.appDependencies().find(i=>i.consumer_app_id===n.consumerAppId)?.dependencies.find(i=>i.alias===n.alias);if(!s)return;if(s.cardinality==="one"){e.saveDependencySelection(n.consumerAppId,n.alias,[n.providerAppId]).catch(e.showError);return}const a=new Set(s.selected_provider_app_ids);t.checked?a.add(n.providerAppId):a.delete(n.providerAppId),e.saveDependencySelection(n.consumerAppId,n.alias,Array.from(a)).catch(e.showError)})}),document.querySelectorAll("[data-dependency-save-default]").forEach(t=>{v(t,"click",()=>{const n=Wt(t.dataset.dependencySaveDefault||"");n&&e.saveDependencySelection(n.consumerAppId,n.alias,[n.providerAppId]).catch(e.showError)})})}function Wt(e){const[t,n,...s]=e.split(":"),a=s.join(":");return!t||!n||!a?null:{alias:n,consumerAppId:t,providerAppId:a}}function Zi(e){document.querySelectorAll("[data-app-toggle]").forEach(t=>{v(t,"change",()=>{const n=e.workspaceApps().find(s=>`${s.workspace_id}:${s.app_id}`===t.dataset.appToggle);n&&e.setWorkspaceAppStatus(n,t.checked).catch(e.showError)})}),document.querySelectorAll("[data-app-install]").forEach(t=>{v(t,"click",()=>{const n=e.workspaceApps().find(s=>`${s.workspace_id}:${s.app_id}`===t.dataset.appInstall);n&&e.installWorkspaceApp(n).catch(e.showError)})}),document.querySelectorAll("[data-app-uninstall]").forEach(t=>{v(t,"click",()=>{const n=e.workspaceApps().find(s=>`${s.workspace_id}:${s.app_id}`===t.dataset.appUninstall);n&&e.uninstallWorkspaceApp(n).catch(e.showError)})})}function Yi(e){document.querySelectorAll("[data-adapter-target]").forEach(t=>{v(t,"click",()=>{const n=t.dataset.adapterTarget;(n==="json"||n==="mongo")&&e.persistenceController.prepare(n).catch(e.showError)})}),v(document.getElementById("close-migration-modal"),"click",()=>{e.persistenceController.cancel()}),v(document.getElementById("cancel-migration"),"click",()=>{e.persistenceController.cancel()}),v(document.getElementById("validate-migration"),"click",()=>{e.persistenceController.validateDraft().catch(e.showError)}),document.querySelectorAll("[data-migration-field]").forEach(t=>{const n=s=>{const a=t.dataset.migrationField;if(a&&a in(e.persistenceController.viewState().targetDraft||{})){const i=!!e.persistenceController.viewState().migrationPlan;e.persistenceController.updateDraft(a,t.value,{render:s}),!s&&i&&Xi()}};v(t,"input",()=>n(!1)),v(t,"change",()=>n(!0))}),v(document.getElementById("settings-delete-source"),"change",t=>{e.persistenceController.setDeleteSource(t.currentTarget.checked)}),v(document.getElementById("confirm-migration"),"click",()=>{e.persistenceController.apply().catch(e.showError)})}function Xi(){const e=document.getElementById("confirm-migration");e&&(e.disabled=!0);const t=document.querySelector(".settings-migration-plan");if(!t)return;const n=t.querySelector(".material-symbols-rounded"),s=t.querySelector("strong"),a=t.querySelector("small");n&&(n.textContent="rule"),s&&(s.textContent="Dry run changed"),a&&(a.textContent="Validate the dry run again before applying migration."),t.querySelector(".settings-migration-collections")?.remove()}function xi(e){let t=null,n=null,s="",a=null,i=null,r=null,o=!1;function c(){return{deleteSourceAfterMigration:o,migrationPlan:a,migrationProgress:r,migrationResult:i,migrationTarget:t,persistence:e.getPersistence(),targetDraft:n}}async function l($){const b=e.getPersistence();if(!b||b.active_adapter.kind===$){m();return}t=$,n=er($,b),s="",a=null,o=!1,r=null,e.setNotice(null),e.render()}function p($,b,R={}){n&&(n={...n,[$]:b},a=null,s="",r=null,R.render!==!1&&e.render())}function u($){o=$,e.render()}function m(){t=null,n=null,a=null,s="",r=null,e.render()}async function S(){if(!(!n||!t)){r={target:t,phase:"validating",title:`Dry run to ${t.toUpperCase()}`,detail:"Validating target adapter and collection copy plan before applying changes."},e.setNotice(null),e.render();try{const $=pt(n);a=await Ts($),s=Vt($)}catch($){throw r=null,a=null,s="",$}r=null,a.same_adapter&&e.setNotice({tone:"info",message:"The selected persistence adapter is already active."}),e.render()}}async function g(){if(!n||!t)return;const $=pt(n),b=Vt($);if(!a||s!==b){await S();return}if(a.same_adapter)return;r={target:t,phase:"applying",title:`Migration to ${t.toUpperCase()}`,detail:"Copying the validated control-plane plan to the target adapter."},e.setNotice(null),e.render();try{i=await qs({...$,delete_source:o,restart_backend:!0})}catch(w){throw r={target:t,phase:"failed",title:"Migration failed",detail:w instanceof Error?w.message:"Unable to apply migration."},w}const R=t;t=null,n=null,a=null,s="",r={target:R,phase:"restarting",title:"Restart backend",detail:i.backend_restart?.detail||"Backend restart scheduled."},e.render(),await T(R)}async function T($){const b=Date.now(),R=9e4;for(;Date.now()-b<R;){r={target:$,phase:"polling",title:"Verifying cutover",detail:"Waiting for the backend to become healthy with the new adapter."},e.render();const w=await e.requestPersistenceStatusQuiet();if(w?.active_adapter.kind===$){e.setPersistence(w);const C=i?.source_cleanup?.scheduled===!0;r={target:$,phase:"complete",title:"Migration complete",detail:C?`Active adapter: ${$.toUpperCase()}. Source cleanup is scheduled after health check.`:`Active adapter: ${$.toUpperCase()}. Source storage was preserved.`},e.setNotice({tone:"success",message:`Migration to ${$.toUpperCase()} complete.`}),e.render();return}await new Promise(C=>window.setTimeout(C,1500))}r={target:$,phase:"failed",title:"Verification not completed",detail:"The backend did not confirm the new adapter before the timeout. Check service health and logs."},e.setNotice({tone:"error",message:"Migration not confirmed before the timeout."}),e.render()}return{apply:g,cancel:m,prepare:l,setDeleteSource:u,updateDraft:p,validateDraft:S,viewState:c}}function er(e,t){const n=t.active_adapter;return{kind:e,json_root:n.json_root||"data/control-plane/json",mongodb_uri:n.mongo_uri||"mongodb://127.0.0.1:27017/maverick",mongodb_database:n.mongo_database||"maverick",mongodb_username:n.mongo_username||"",mongodb_password_ref:n.mongo_password_ref||""}}function pt(e){return{kind:e.kind,json_root:e.json_root.trim()||"data/control-plane/json",mongodb_uri:e.mongodb_uri.trim(),mongodb_database:e.mongodb_database.trim()||"maverick",mongodb_username:e.mongodb_username?.trim()||void 0,mongodb_password_ref:e.mongodb_password_ref?.trim()||void 0}}function Vt(e){return JSON.stringify(pt(e))}async function tr(e){const t=e.settings?.workspace.workspace_id,n=e.state.hostedDraftModelId,s=nr(e.settings,e.state.hostedDraftModelId);if(!s||!e.state.hostedDraftModelId){e.state.hostedProviderErrorModelId=e.state.hostedDraftModelId,e.state.hostedProviderError="Hosted provider not loaded.",e.render();return}e.state.isSavingHostedProvider=!0,e.state.hostedProviderError="",e.state.hostedProviderErrorModelId=e.state.hostedDraftModelId,e.render();try{const a=await Es({provider_id:s,model_id:e.state.hostedDraftModelId,openrouter_provider_routing:pn(e.state,e.state.hostedDraftModelId)});if(e.getSettings()?.workspace.workspace_id!==t||!e.settings)return;const i={...e.getSettings(),provider:a};e.setSettings(i),oe(e.state,i,{hostedModelId:n}),document.querySelectorAll("[data-hosted-model-accordion]").forEach(r=>{r.dataset.hostedModelAccordion===n&&z(r)}),e.setNotice({tone:"success",message:"Hosted model settings updated."})}catch(a){e.state.hostedProviderErrorModelId=e.state.hostedDraftModelId,e.state.hostedProviderError=a instanceof Error?a.message:"Unable to update hosted model settings."}finally{e.state.isSavingHostedProvider=!1,e.render()}}function nr(e,t){const n=e?.provider.hosted_text||null;return[n?.active_provider,...n?.available_providers||[]].filter(Boolean).find(i=>!i||i.status!=="active"?!1:(i.model_options||[]).some(r=>r.model_id===t))?.provider_id||n?.active_provider?.provider_id||""}async function sr(e){const t=e.settings?.workspace.workspace_id,n=e.settings?.provider.speech_stt?.active_provider?.provider_id;if(!n||!e.state.speechAudioModelId||!e.state.speechConversationModelId){e.state.speechProviderError="Speech provider not loaded.",e.render();return}e.state.isSavingSpeechProvider=!0,e.state.speechProviderError="",e.render();try{const s=await As({provider_id:n,audio_transcription_model_id:e.state.speechAudioModelId,conversation_model_id:e.state.speechConversationModelId});if(e.getSettings()?.workspace.workspace_id!==t||!e.settings)return;const a={...e.getSettings(),provider:s};e.setSettings(a),oe(e.state,a,{speech:!0}),z(".settings-speech-model-accordion"),e.setNotice({tone:"success",message:"Speech model settings updated."})}catch(s){e.state.speechProviderError=s instanceof Error?s.message:"Unable to update speech model settings."}finally{e.state.isSavingSpeechProvider=!1,e.render()}}function ar(e){let t="",n=0,s=0;function a(){t="",n+=1,s+=1,e.state.providerUsageItems=[],e.state.providerUsageError="",e.state.isLoadingProviderUsage=!1,e.state.usageHistory=null,e.state.usageHistoryFilters=ot(),e.state.usageHistoryError="",e.state.isLoadingUsageHistory=!1}async function i(p=!1){const m=e.getSettings()?.workspace.workspace_id||"";if(!m){a();return}!p&&t===m||(t&&t!==m&&(e.state.usageHistoryFilters=ot()),t=m,await Promise.all([r(m),o(m)]))}async function r(p,u){const m=++n;e.state.providerUsageError="",e.state.isLoadingProviderUsage=!0,e.render();try{const S=await ks();l(p)&&m===n&&(e.state.providerUsageItems=S.items)}catch(S){l(p)&&m===n&&(e.state.providerUsageError=S instanceof Error?S.message:"Provider usage unavailable")}finally{l(p)&&m===n&&(e.state.isLoadingProviderUsage=!1,e.render())}}async function o(p,u=!1){const m=++s,S=e.state.usageHistoryFilters,g=dn(S.timeRange),T={providerId:S.providerId,modelId:S.modelId};e.state.isLoadingUsageHistory=!0,e.state.usageHistoryError="",u&&(e.state.usageHistory=null),e.render();try{const $=await Ss(g.resolution,g.periods,T);l(p)&&m===s&&(e.state.usageHistory=$)}catch($){l(p)&&m===s&&(e.state.usageHistoryError=$ instanceof Error?$.message:"Token usage history unavailable")}finally{l(p)&&m===s&&(e.state.isLoadingUsageHistory=!1,e.render())}}function c(p){const u=e.state.usageHistoryFilters,m=Gs(u,p);if(ir(u,m))return Promise.resolve();e.state.usageHistoryFilters=m;const S=u.providerId!==m.providerId||u.modelId!==m.modelId||u.timeRange!==m.timeRange,g=e.getSettings()?.workspace.workspace_id||"";return!S||!g?(e.render(),Promise.resolve()):o(g,!0)}function l(p){return e.getSettings()?.workspace.workspace_id===p}return{ensureLoaded:i,refresh:()=>i(!0),reset:a,updateUsageHistoryFilters:c}}function ir(e,t){return e.metric===t.metric&&e.providerId===t.providerId&&e.modelId===t.modelId&&e.timeRange===t.timeRange}function rr(e){return e?`<div class="settings-notice settings-notice-${e.tone}">
    <span class="material-symbols-rounded" aria-hidden="true">${e.tone==="error"?"error":e.tone==="success"?"task_alt":"info"}</span>
    <span>${d(e.message)}</span>
    <button type="button" class="settings-icon-button" id="dismiss-notice" aria-label="Close">
      <span class="material-symbols-rounded" aria-hidden="true">close</span>
    </button>
  </div>`:""}function or(e){let t=0;return{reset:()=>{t++,e.state.pendingAgenticEnabled={},e.state.savingAgenticBindings.clear(),e.state.activatingNativeProviders.clear(),e.state.agenticBindingErrors={},e.state.nativeProviderErrors={}},activateProvider:async n=>{const s=t,a=e.getSettings()?.workspace.workspace_id;if(!e.state.activatingNativeProviders.has(n)){e.state.activatingNativeProviders.add(n),e.state.nativeProviderErrors[n]="",e.render();try{await Is(n);const i=await $s("models");if(s!==t||e.getSettings()?.workspace.workspace_id!==a||i.workspace.workspace_id!==a)return;oe(e.state,i),e.setSettings(i,"Connection enabled. Selected models are available in Chat.")}catch(i){if(s!==t)return;e.state.nativeProviderErrors[n]=i instanceof Error?i.message:"Unable to enable connection."}finally{s===t&&(e.state.activatingNativeProviders.delete(n),e.render())}}},save:async(n,s={})=>{const a=t,i=e.getSettings()?.workspace.workspace_id,r=n;if(e.state.savingAgenticBindings.has(r))return;const o=e.getSettings()?.agentic_admin?.items.find(g=>g.definition_id===n),c=Array.from(document.querySelectorAll("[data-agentic-binding-form]")).find(g=>g.dataset.agenticDefinitionId===n);if(!o||!c){e.state.agenticBindingErrors[r]="Agentic binding form is no longer available.",e.render();return}const l=g=>c.querySelector(`[data-agentic-field="${g}"]`),p=g=>!!l(g)?.checked,u=s.enabled??p("enabled");if(o.containment_status==="NO-GO"&&u){e.state.agenticBindingErrors[r]=`Remote agentic release is NO-GO: ${o.containment_reason||"contained by operator policy"}.`,e.render();return}if(u&&(o.execution_family===null||o.runtime_status!=="complete"||o.enable_eligible!==!0)){e.state.agenticBindingErrors[r]=`This model is unavailable: ${o.enable_blocked_reason||o.runtime_status_reason||o.blocked_reason||"runtime unavailable"}.`,e.render();return}const m=l("max_estimated_cost_usd")?.value.trim()||"",S=Math.round(Number(m)*1e6);if(m&&(!Number.isFinite(S)||S<0)){e.state.agenticBindingErrors[r]="Maximum cost must be a non-negative amount.",e.render();return}e.state.savingAgenticBindings.add(r),s.enabled!==void 0&&(e.state.pendingAgenticEnabled[r]=u),e.state.agenticBindingErrors[r]="",e.render();try{const g=await Cs({definition_id:n,binding_id:o.binding?.binding_id||null,credential_binding_id:l("credential_binding_id")?.value||null,enabled:u,is_default:s.enabled===!1?!1:p("is_default"),actor_policy:{allow_workspace_admins:p("allow_workspace_admins"),allowed_user_ids:o.binding?.actor_policy.allowed_user_ids||[],allowed_workspace_role_ids:p("allow_workspace_members")?["member"]:[],allowed_agent_type_ids:o.binding?.actor_policy.allowed_agent_type_ids||[]},policy_patch:{max_estimated_cost_microusd:m?S:null,require_confirmation_for_mutating:p("require_confirmation_for_mutating"),require_confirmation_for_destructive:p("require_confirmation_for_destructive")}}),T=e.getSettings();if(a!==t||!T||T.workspace.workspace_id!==i||g.agentic_admin.workspace_id!==i)return;const $={...T,agentic_admin:g.agentic_admin};oe(e.state,$),z(c),e.setSettings($,`${o.display_name} binding updated for new sessions.`)}catch(g){if(a!==t)return;e.state.agenticBindingErrors[r]=g instanceof Error?g.message:"Unable to save agentic binding."}finally{a===t&&(delete e.state.pendingAgenticEnabled[r],e.state.savingAgenticBindings.delete(r),e.render())}}}}function lr(e){let t=null,n="",s=!1,a=!1,i=!1;async function r(l=!1){if(!(a||!l&&t)){a=!0,n="",e.render();try{if(t=await ns(),!t)throw new Error("Cache diagnostics are unavailable outside the Maverick shell.")}catch(p){n=Jt(p,"Unable to inspect this browser cache.")}finally{a=!1,e.render()}}}async function o(){if(s||i)return;i=!0;let l=!1;try{l=await bt({title:"Clear this browser cache?",detail:"Remove cached Maverick data and local file copies from this browser. Server files, conversations and settings are preserved.",confirmLabel:"Clear cache"})}finally{i=!1}if(l){s=!0,n="",e.render();try{const p=await ss();if(!p)throw new Error("Cache cleanup is unavailable outside the Maverick shell.");const{cleanup:u}=p;if(u.status!=="complete"||u.pendingCleanupCount>0)throw new Error("Cache cleanup is still pending. Persistent cache reads remain blocked; retry Clear cache.");t=p.dashboard,e.setNotice({tone:"success",message:u.removed===1?"1 cached entry removed.":`${u.removed} cached entries removed.`})}catch(p){n=Jt(p,"Unable to clear this browser cache."),e.setNotice({tone:"error",message:n})}finally{s=!1,e.render()}}}function c(){return{dashboard:t,error:n,isClearing:s,isLoading:a}}return{clear:o,ensureLoaded:r,viewState:c}}function Jt(e,t){return e instanceof Error&&e.message?e.message:t}let Le=null,Gt=null;const dr=Kn();let J=[],Me=[],ge="",He=[],le=[],Ue=null,A=null,gt=en()?.workspaceId||"",U=Aa();const An=Object.fromEntries(new URLSearchParams(window.location.search).entries());let V=Xt(An)||Dn,Y=In(An),x=!0,W=null,Kt="",Qt="";const G=on();let Xe="",Pe="",Zt=!1;const $t=Ds({state:U.speechSynthesis,render:D,notify:e=>{W={tone:"success",message:e}}}),cr=Os({state:U.computerUse,getSettings:()=>A,render:D,setSelection:e=>{A&&(A={...A,computer_use:e})},notify:e=>{W={tone:"success",message:e}}}),Te=xi({getPersistence:()=>Ue,render:()=>D(),requestPersistenceStatusQuiet:Ns,setNotice:e=>{W=e},setPersistence:e=>{Ue=e}}),ae=fi({publishChanged:Ar,render:()=>D(),setNotice:e=>{W=e}}),Fe=ar({getSettings:()=>A,render:()=>D(),state:U}),Oe=vi({render:D,updated:(e,t)=>{le=le.map(n=>n.workspace_id===e.workspace_id&&n.app_id===e.app_id?{...n,status:t?"enabled":"disabled"}:n),ae.invalidate(),N.ensure("apps",!0)}}),mt=or({getSettings:()=>A,render:D,state:U,setSettings:(e,t)=>{A={...A,...e,runtime:A?.runtime||e.runtime,computer_use:A?.computer_use},W={tone:"success",message:t}}}),kt=lr({render:D,setNotice:e=>{W=e}}),ce=la({render:D,workspaceId:()=>A?.workspace.workspace_id||""});function Cn(){return J.find(e=>e.user_id===Y)||J[0]}function In(e){const t=me(e.user_id)||me(e.selected_user_id)||me(e.id);if(t)return t;const n=me(e.app_page),s=/^users\/([^/?#]+)$/.exec(n);if(!s?.[1])return"";try{return decodeURIComponent(s[1])}catch{return s[1]}}function me(e){return typeof e=="string"?e.trim():""}function ur(e){const t=Xt(e),n=In(e),s=me(e.setting);Pe=["default-model","voice","password","cache","computer-use"].includes(s)?s:"",t&&(V=t),n&&n!==Y&&(Y=n),N.cancelExcept(_t(V)),D(),We()}function pr(e){e.id===Kt||window.parent===window||(Kt=e.id,window.parent.postMessage({type:"maverick.app.selection-changed",owner_app_id:"settings",selection:{page_id:e.id}},"*"))}function gr(e){!e||e.user_id===Qt||window.parent===window||(Qt=e.user_id,window.parent.postMessage({type:"maverick.app.selection-changed",owner_app_id:"settings",selection:{user_id:e.user_id}},"*"))}function ze(){window.parent!==window&&window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"settings",resource:"users"},"*")}const N=js({publish:(e,t)=>{if(e==="registry"){const n=t;Me=n.items,ge=n.workspace_id||A?.workspace.workspace_id||""}else if(e==="users")J=t.items,(!Y||!J.some(n=>n.user_id===Y))&&(Y=J[0]?.user_id||"");else if(e==="workspaces")He=t.items;else if(e==="apps")le=t.items;else if(e==="persistence")Ue=t;else if(e==="sessions")A?A=ct(A,t):Ce=t;else{const n=t,s=gt;s&&s!==n.workspace.workspace_id&&(Le?.unmountUsageVisualizations(),N.reset(),gs(),A=null,J=[],He=[],le=[],Ue=null,Ce=null,Me=[],ge="",U.savedDrafts=null,ae.reset(),ce.reset(),Fe.reset(),$t.reset(),mt.reset(),Oe.reset(),W=null,Object.assign(G,on()),queueMicrotask(()=>{D(),We()})),Me.length&&!ge&&(ge=n.workspace.workspace_id),gt=n.workspace.workspace_id;const a=e==="models"||e==="voice";A=Fs(A,n,e),Ce&&(A=ct(A,Ce)),(a||e==="computer-use")&&oe(U,A)}},changed:()=>D()});let Ce=null;async function We(e=!1){const t=V;t==="workspace-apps"&&N.ensure("registry",e),await Promise.all(_t(t).map(n=>N.ensure(n,e))),V===t&&(t==="app-links"&&N.state("apps").loaded&&N.state("context").loaded&&await Mn(e),t==="usage"&&A&&(Fe.ensureLoaded(e),Gt||=On(()=>import("./usageVisualizations-D_vPiW1S.js"),__vite__mapDeps([0,1])).then(n=>{Le=n,V==="usage"&&D()}).catch(n=>{Gt=null,V==="usage"&&Ne(n)})),t==="voice"&&A&&$t.load(A.workspace.workspace_id,e),t==="learning"&&A&&(ce.load(e),N.ensure("models")),t==="cache"&&kt.ensureLoaded(e))}async function mr(){await We(!0)}async function Mn(e=!1){await ae.ensureLoaded(A?.workspace.workspace_id||"",le,e)}async function fr(e){const t=new FormData(e),n=await ga({username:String(t.get("username")||""),password:String(t.get("password")||""),display_name:String(t.get("display_name")||""),email:String(t.get("email")||""),platform_role:String(t.get("platform_role")||"member")});J=[...J,n],Y=n.user_id,e.reset(),z(e),W={tone:"success",message:"User created."},D(),ze()}async function vr(e,t){const n=new FormData(e),s=await ma(t.user_id,{display_name:String(n.get("display_name")||""),email:String(n.get("email")||""),platform_role:String(n.get("platform_role")||"member"),account_type:String(n.get("account_type")||"standard"),is_active:n.get("is_active")==="on"});J=J.map(a=>a.user_id===s.user_id?s:a),z(e),W={tone:"success",message:"User updated."},D(),ze()}async function hr(e,t){const n=new FormData(e),s=String(n.get("password")||""),a=String(n.get("password_confirmation")||"");if(s!==a)throw new Error("Passwords do not match");await fa(t.user_id,s),e.reset(),z(e),W={tone:"success",message:"Password updated."},D()}async function _r(e){const t=e.display_name||e.username;await bt({title:`Delete ${t}?`,detail:"This permanently removes the user account and its workspace memberships. This action cannot be undone.",confirmLabel:"Delete user"})&&(await va(e.user_id),Y="",W={tone:"success",message:`${t} deleted.`},J=J.filter(n=>n.user_id!==e.user_id),Y=J[0]?.user_id||"",D(),ze())}async function br(e){const t=He.map(s=>{const a=document.querySelector(`[data-workspace-enabled="${s.workspace_id}"]`),i=document.querySelector(`[data-workspace-role="${s.workspace_id}"]`);return a?.checked?{workspace_id:s.workspace_id,role:i?.value||"member"}:null}).filter(s=>!!s),n=await ha(e.user_id,t);J=J.map(s=>s.user_id===n.user_id?n:s),z(".settings-memberships"),W={tone:"success",message:"Workspace access updated."},D(),ze()}async function yr(e){await _a(e),ae.invalidate(),await N.ensure("apps",!0)}async function wr(e,t){await Oe.setEnabled(e,t)}async function $r(e){await ya(e),ae.invalidate(),await N.ensure("apps",!0)}async function kr(e,t,n){await ae.saveDependencySelection(e,t,n)}async function Sr(e){if(!A)return;const t=A.workspace.workspace_id,n=yt(A,G),s=e?.length?n.filter(o=>e.includes(o.session_id)):n;if(!s.length)return;const a=G.scope==="server"?"the entire server":`workspace ${A.workspace.name}`,i=s.filter(o=>!["closed","completed","failed","terminated","stopped"].includes(o.status)).length;if(!await bt({title:`Delete ${s.length} runtime session${s.length===1?"":"s"}?`,detail:`Scope: ${a}. ${i} sessions may have active agents. Their agents will stop and their conversations, turns and runtime files will be permanently removed.`,confirmLabel:"Delete sessions"})||A.workspace.workspace_id!==t)return;const r=s.map(o=>o.session_id);U.cleanupError="",U.clearingAllRuntime=!e?.length,r.forEach(o=>U.cleaningSessionIds.add(o)),D();try{const o=await Ms(r);if(A.workspace.workspace_id!==t)return;Er(o),A=ct(A,o),W={tone:"success",message:`${o.cleared_sessions} runtime sessions deleted.`}}catch(o){U.cleanupError=o instanceof Error?o.message:"Unable to delete runtime sessions."}finally{r.forEach(o=>U.cleaningSessionIds.delete(o)),U.clearingAllRuntime=!1,D()}}function Er(e){e.deleted_threads<=0||window.parent===window||(window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"chat",resource:"threads"},"*"),e.deleted_thread_ids.forEach(t=>{window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"chat",resource:"threads",deleted_thread_id:t},"*")}))}function Ar(e,t){window.parent!==window&&window.parent.postMessage({type:"maverick.app.dependencies-changed",app_id:e,status:t.status},"*")}async function Cr(){if(window.parent&&window.parent!==window){window.parent.postMessage({type:"maverick.shell.logout"},"*");return}await Ps(),window.location.href="/"}function Ir(){return Za(A,U,V)}function D(){const e=document.getElementById("app");if(!e)return;Zt||(ms(e),Zt=!0);const t=performance.now(),n=Rn(V),s=_t(V);x=s.some(l=>!N.state(l).loaded&&!N.state(l).error);const a=s.filter(l=>N.state(l).error&&!N.state(l).loaded),i=s.filter(l=>N.state(l).error&&N.state(l).loaded),r=Cn();Xe==="usage"&&(V!=="usage"||x||a.length)&&Le?.unmountUsageVisualizations();const o=Xe!==V;Xe=V;const c=x?ni(n):a.length?a.map(l=>`<section class="settings-card"><h2>Unable to load ${d(l)}</h2><p role="alert">${d(N.state(l).error)}</p><button type="button" data-retry-resource="${l}">Retry</button></section>`).join(""):Vi({appLinksController:ae,cacheDiagnosticsController:kt,page:n,persistenceController:Te,platformSettingsHtml:Ir,sessionsHtml:()=>A?Vs(A,U,G):"",usageHtml:()=>ea(U),learningHtml:()=>ua(ce.viewState(),A?.provider.available_providers?.find(l=>l.provider_id==="codex")?.model_options||[]),selectedUser:r,users:J,workspaceApps:Oe.apps(le).map(l=>({...l,logo:l.workspace_id===ge&&Me.find(p=>p.app_id===l.app_id)?.logo||null})),savingAppKeys:Oe.savingKeys(),workspaces:He});if(fs(e,`<main class="settings-shell"><section class="settings-main"><div class="settings-content" data-render-key="${d(Ln(gt,n.id,r?.user_id))}">
    <header class="detail-header"><div class="detail-title-block"><h2>${d(n.title)}</h2><span class="detail-title-separator" aria-hidden="true"></span><p>${d(n.summary)}</p></div>
    ${A?`<div class="settings-context"><span>${d(A.workspace.name)}</span><span>${d(A.user.display_name||A.user.username)}</span><button type="button" id="settings-logout" class="settings-secondary">Logout</button></div>`:""}</header>
    ${rr(W)}${i.map(l=>`<p role="alert">${d(N.state(l).error)} <button type="button" data-retry-resource="${l}">Retry</button></p>`).join("")}${c}
    </div></section>${Di(Te.viewState())}</main>`),Mr(),dr.attach(V==="installation"?document.getElementById("installation-root"):null),zs(Te.cancel),ce.setVisible(V==="learning"&&dt()&&!x),V==="usage"&&!x&&!a.length&&Le?.mountUsageVisualizations({history:U.usageHistory,filters:U.usageHistoryFilters,isLoading:U.isLoadingUsageHistory,onFiltersChange:Fe.updateUsageHistoryFilters,settings:A}),o&&document.querySelector(".settings-main")?.scrollTo?.(0,0),pr(n),!x&&["users","workspace-access"].includes(V)&&gr(r),Pe&&!x){const l={"default-model":"[data-agentic-model-toggle]",voice:"#settings-tts-engine",password:"#reset-password input",cache:"#clear-pwa-cache","computer-use":"#settings-computer-use-mode"},p=document.querySelector(l[Pe]);p&&(p.closest("details")?.setAttribute("open",""),p.focus(),p.scrollIntoView?.({block:"center"}),Pe="")}performance.clearMeasures("settings.render"),performance.measure("settings.render",{start:t,end:performance.now()})}function Mr(){hs(),document.querySelectorAll("[data-user-discard]").forEach(e=>v(e,"click",()=>{const t=e.closest("form, #workspace-assignments");t&&(t instanceof HTMLFormElement&&t.reset(),z(t),D())})),document.querySelectorAll("[data-speech-discard]").forEach(e=>v(e,"click",()=>{oe(U,A,{speech:!0}),z(".settings-speech-model-accordion"),D()})),document.querySelectorAll("[data-hosted-discard]").forEach(e=>v(e,"click",()=>{oe(U,A,{hostedModelId:e.dataset.hostedDiscard}),z("[data-hosted-model-accordion]"),D()})),v(document.getElementById("settings-refresh-app-links"),"click",()=>{Mn(!0)}),document.querySelectorAll("[data-retry-resource]").forEach(e=>v(e,"click",()=>{N.ensure(e.dataset.retryResource,!0).then(()=>We())})),v(document.getElementById("settings-session-search"),"input",e=>{G.query=e.target.value,G.page=0,D()}),v(document.getElementById("settings-session-status"),"change",e=>{G.status=e.target.value,G.page=0,D()}),v(document.getElementById("settings-session-scope"),"change",e=>{G.scope=e.target.value==="server"?"server":"workspace",G.page=0,G.status="",z(".settings-session-filters"),D()}),v(document.getElementById("settings-sessions-prev"),"click",()=>{G.page-=1,D()}),v(document.getElementById("settings-sessions-next"),"click",()=>{G.page+=1,D()}),v(document.getElementById("create-workspace"),"submit",e=>{e.preventDefault();const t=e.target;L("/api/workspaces",{method:"POST",body:JSON.stringify(Object.fromEntries(new FormData(t)))}).then(async()=>{t.reset(),z("#create-workspace"),await N.ensure("workspaces",!0),await N.ensure("apps",!0),W={tone:"success",message:"Workspace created."},D()}).catch(Ne)}),$t.bind(),ce.bind(),cr.bind(),Gi({clearRuntimeSessionsFromPanel:Sr,cacheDiagnosticsController:kt,createUser:fr,deleteSelectedUser:_r,dismissNotice:()=>{W=null,D()},installWorkspaceApp:yr,logoutFromSettings:Cr,onHostedProviderRoutingChanged:(e,t,n)=>{Pa(U,A,e,t,n),D()},saveAgenticBindingFromPanel:mt.save,activateNativeProviderFromPanel:mt.activateProvider,onSpeechAudioModelChanged:e=>{Ia(U,e),D()},onSpeechConversationModelChanged:e=>{Ma(U,e),D()},persistenceController:Te,refreshProviderUsageFromPanel:Fe.refresh,render:D,resetSelectedUserPassword:hr,saveDependencySelection:kr,saveHostedProviderSettingsFromPanel:e=>(e&&Ca(U,A,e),tr(Yt())),saveSpeechProviderSettingsFromPanel:()=>sr(Yt()),selectedUser:Cn,selectUser:e=>{Y=e,D()},setWorkspaceAppStatus:wr,showError:Ne,uninstallWorkspaceApp:$r,updateMemberships:br,updateSelectedUser:vr,workspaceApps:()=>le,appDependencies:()=>ae.viewState().dependencies})}function Yt(){return{render:D,setNotice:e=>{W=e},setSettings:e=>{A=e},settings:A,getSettings:()=>A,state:U}}function Ne(e){W={tone:"error",message:e instanceof Error?e.message:"Unexpected error"},D()}pa({navigate:ur,visibilityChanged:e=>ce.setVisible(V==="learning"&&e&&!x)});mr().catch(Ne);export{ln as U,Dr as a,rt as b,qr as c,Tr as d,dn as u};
