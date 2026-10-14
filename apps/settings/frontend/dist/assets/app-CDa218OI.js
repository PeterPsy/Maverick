const __vite__mapDeps=(i,m=__vite__mapDeps,d=(m.f||(m.f=["assets/usageVisualizations-DmZ4oN5T.js","assets/pages-D4vzaPOW.js"])))=>i.map(i=>d[i]);
import{i as ft,P as Tn,a as qn,b as Ln,s as Xt,D as Dn,c as Rn,d as Hn}from"./pages-D4vzaPOW.js";const Un="modulepreload",On=function(e){return"/apps/settings/"+e},St={},Nn=function(t,n,s){let a=Promise.resolve();if(n&&n.length>0){let c=function(l){return Promise.all(l.map(u=>Promise.resolve(u).then(p=>({status:"fulfilled",value:p}),p=>({status:"rejected",reason:p}))))};document.getElementsByTagName("link");const o=document.querySelector("meta[property=csp-nonce]"),r=o?.nonce||o?.getAttribute("nonce");a=c(n.map(l=>{if(l=On(l),l in St)return;St[l]=!0;const u=l.endsWith(".css"),p=u?'[rel="stylesheet"]':"";if(document.querySelector(`link[href="${l}"]${p}`))return;const m=document.createElement("link");if(m.rel=u?"stylesheet":Un,u||(m.as="script"),m.crossOrigin="",m.href=l,r&&m.setAttribute("nonce",r),document.head.appendChild(m),u)return new Promise((S,g)=>{m.addEventListener("load",S),m.addEventListener("error",()=>g(new Error(`Unable to preload CSS for ${l}`)))})}))}function i(o){const r=new Event("vite:preloadError",{cancelable:!0});if(r.payload=o,window.dispatchEvent(r),!r.defaultPrevented)throw o}return a.then(o=>{for(const r of o||[])r.status==="rejected"&&i(r.reason);return t().catch(i)})},Bn=e=>["ready","rolled_back","failed","rollback_requested"].includes(e.status);class qe extends Error{constructor(t,n){super(t),this.code=t,this.status=n}}async function ie(e,t,n){const s=await fetch("/api/admin/installation"+(e==="inspect"?"":"/"+e),{method:t===void 0?"GET":"POST",credentials:"same-origin",signal:n,headers:{Accept:"application/json",...t===void 0?{}:{"Content-Type":"application/json"}},...t===void 0?{}:{body:JSON.stringify(t)}}),a=await s.json();if(!s.ok)throw new qe(a.error||"installation_operation_failed",s.status);return a}async function jn(e,t){if(!window.isSecureContext)throw new qe("secure_connection_required",400);const n=await fetch("/api/secrets",{method:"POST",credentials:"same-origin",signal:t,headers:{"Content-Type":"application/json"},body:JSON.stringify({label:"Cloudflare DNS",kind:"api_key",alias:"cloudflare-dns-"+crypto.randomUUID().slice(0,8),raw_value:e})}),s=await n.json();if(!n.ok)throw new qe(s.error||"credential_save_failed",n.status);return"platform:secrets/"+s.secret.secret_id}const et=e=>String(e??"").replace(/[&<>"']/g,t=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[t]),O=et,he=(e,t)=>e.startsWith("https://")?`<a href="${O(e)}" target="_blank" rel="noopener noreferrer">${O(t)} ↗</a>`:"",Fn={queued:"Queued",preparing:"Preparing DNS & certificates",waiting_dns:"Waiting for DNS",waiting_ca:"Waiting for certificate authority",waiting_external_actions:"Provider update needed",activating:"Activating address",verifying:"Checking the new connection",rolling_back:"Restoring previous setup",rolled_back:"Previous setup restored",ready:"Ready",failed:"Needs attention",rollback_requested:"Restoration requested"},Wn=e=>Fn[e]||e,zn={dns_zone_not_authorized:"This token cannot access the domain. Add Zone · DNS · Edit and Zone · Zone · Read for this domain.",dns_access_denied:"Cloudflare rejected this connection. Check the token permissions in Vault.",dns_automation_connection_required:"Connect Cloudflare to automate wildcard certificates and renewal. Other providers can delegate DNS to Cloudflare while keeping the domain at the same registrar.",invalid_hostname:"Enter a public domain such as loopino.example.com, without a path or port.",invalid_server_ip:"Enter the public IP address of this server.",public_server_ip_required:"Use the public server IP.",stale_installation_plan:"The setup changed. Review a fresh plan before applying.",installation_change_in_progress:"An installation change is already running. Follow its progress below.",wrong_server_at_target_address:"The address reaches another server. Check the public IP before retrying.",secure_connection_required:"Open setup over HTTPS or a local connection before saving a credential.",admin_required:"Sign in with a platform administrator account to configure this installation.",plan_integrity_failed:"This plan changed after review. Create a fresh plan.",renewal_verification_failed:"The automatic renewal test failed. Check DNS access before retrying."},vt=e=>zn[e]||"The operation could not complete. Diagnostic: "+e.replaceAll("_"," ");function Vn(e){const t=e.configuration,n=e.worker?.checked_at&&Date.now()-Date.parse(e.worker.checked_at)<1200*1e3;return`<section class="installation-card"><div class="installation-card-heading"><div><p class="installation-eyebrow">This installation</p><h2>${O(t.hostname||"Choose your address")}</h2></div><span class="installation-badge">${t.managed?"Managed":"Setup available"}</span></div>
    <div class="installation-facts"><div><span>Public address</span><strong>${t.public_url?he(t.public_url,t.public_url):"Not configured"}</strong></div><div><span>Automation</span><strong>${n?"Worker online":"Worker unavailable"}</strong></div><div><span>Certificate renewal</span><strong>${O(e.worker?.renewal_state||(t.managed?"Scheduled":"Complete setup to manage"))}</strong></div></div>
    ${e.worker?.verification?.healthy===!1?'<p role="alert">The secure connection needs attention. Check the connection for current diagnostics.</p>':""}
    ${n?"":'<p class="installation-muted">The server administrator can enable automation with <code>sudo /usr/bin/python3 scripts/deploy/install_installation_worker.py</code>.</p>'}
    ${e.requirements.length?`<details><summary>Service connections</summary>${e.requirements.map(s=>`<div class="installation-notice"><strong>${O(s.label)}</strong><p>${s.configured?"Provider configured · check registration when changing address":"Connection required · web setup can continue"}</p><code>${O(s.url)}</code>${s.provider_url?`<p>${he(s.provider_url,"Open provider")}</p>`:""}</div>`).join("")}</details>`:""}
    <div class="installation-actions"><button type="button" data-installation-action="verify">Check connection</button><a href="${O(t.public_url+"/setup")}" target="_blank" rel="noopener">Open recovery setup ↗</a></div></section>`}function Jn(e,t){const n=e.blocking_issues.some(s=>s.code==="dns_automation_connection_required");return`<section class="installation-card"><p class="installation-eyebrow">Review your setup</p><h2>${O(e.hostname)}</h2><p class="installation-muted">Server ${O(e.target_ip)} · DNS only · ${n?"Connect DNS automation to enable renewal":"HTTPS with automatic renewal"}</p>
    <ul class="installation-records">${e.dns_changes.map(s=>`<li><code>${O(s.name)}</code><span>${s.action==="keep"?"Already correct":O(s.after?.type+" → "+s.after?.content)}</span></li>`).join("")}</ul>
    <p class="installation-muted">Certificates: ${e.certificate_names.map(O).join(", ")}</p>
    ${e.blocking_issues.map(s=>`<div class="installation-notice">${s.code==="dns_delegation_pending"?`Set these nameservers at your registrar once, then Loopino will continue automatically: <ul>${(s.nameservers||[]).map(a=>`<li><code>${O(a)}</code></li>`).join("")}</ul>`:O(vt(s.code))}</div>`).join("")}
    ${e.external_actions.length?"<p>Keep the current provider callback registered until the new connection is ready. Loopino will pause for your confirmation.</p>":""}
    <div class="installation-actions"><button class="installation-primary" type="button" data-installation-action="apply" ${n||t?"disabled":""}>Apply setup</button>${e.token_template_url?he(e.token_template_url,"Scoped token template"):""}</div></section>`}function Gn(e,t){const n=!["ready","rolled_back","failed","rollback_requested"].includes(e.status);return`<section class="installation-card" aria-label="Installation progress"><div class="installation-card-heading"><h2>${O(Wn(e.status))}</h2><span class="installation-badge">${n?"In progress":"Completed check"}</span></div>
    <ol class="installation-steps"><li>DNS & delegation</li><li>Certificates & renewal test</li><li>Provider connections</li><li>Activate & verify</li></ol>
    <p class="installation-muted" role="status">${n?"This operation continues on the server if you close this page.":""}${e.retry_at?" Next check: "+O(new Date(e.retry_at).toLocaleString()):""}</p>
    ${e.error_code?`<p role="alert">${O(vt(e.error_code))}</p>`:""}
    ${e.status==="waiting_external_actions"&&t?`<form data-installation-confirm="${O(e.job_id)}"><p>Add each new address in its provider console, then confirm.</p>${t.external_actions.map(s=>`<label class="installation-confirm-row"><input type="checkbox" name="action_id" value="${O(s.id)}" ${e.confirmed_actions?.includes(s.id)?"checked":""}><span><strong>${O(s.label)}</strong><code>${O(s.url)}</code>${s.provider_url?he(s.provider_url,"Open provider"):""}</span></label>`).join("")}<button class="installation-primary" type="submit">Confirm provider updates</button></form>`:""}
    ${e.verification?xt(e.verification):""}
    ${e.status==="ready"&&t?.change_kind==="address_change"?'<p class="installation-muted">Use the new address for saved server connections and installed apps. Saved web links on this server will forward to the new address.</p>':""}
    <div class="installation-actions">${e.status==="failed"?'<button type="button" data-installation-action="retry">Retry</button>':""}${e.status!=="rolled_back"&&e.status!=="rollback_requested"?'<button type="button" data-installation-action="rollback-review">Restore previous setup</button>':""}${e.status==="ready"&&t?he(t.public_url,"Open Loopino"):""}</div>
    <div data-installation-rollback hidden><p>Restore the DNS and address settings saved before this change. Provider registrations remain under your control.</p><button type="button" data-installation-action="rollback">Confirm restoration</button></div></section>`}function xt(e){const t=n=>n.startsWith("af-")?"Secure app pages":n.startsWith("sc-")?"Secure app services":"Loopino address";return`<div class="installation-verification" role="status"><strong>${e.healthy?"Connection verified":"Some connections need attention"}</strong><ul>${e.checks.map(n=>`<li><span>${t(n.host)}</span><span>${n.healthy?"HTTPS ready":O(n.error||"Unavailable")}</span></li>`).join("")}</ul><details><summary>Technical details</summary>${e.checks.map(n=>`<p><code>${O(n.host)}</code></p>`).join("")}</details></div>`}function Kn(e){let t,n,s,a,i=!1,o=0;const r=new Map;let c=!1,l;const u=new Set;e.classList.add("installation-view"),e.innerHTML=`<div data-installation-overview><p role="status">Loading installation…</p></div><div data-installation-message role="status" aria-live="polite"></div>
    <form class="installation-card" data-installation-form><p class="installation-eyebrow">Address & connection</p><h2>Give Loopino a home</h2><p class="installation-muted">Use a domain you own. Loopino connects DNS, secures the address and checks its apps.</p>
    <label class="installation-field">Public address<input data-settings-controlled name="address" placeholder="loopino.example.com" required autocomplete="url" spellcheck="false"></label>
    <div class="installation-columns"><label class="installation-field">DNS provider<select data-settings-controlled name="dns_provider"><option value="cloudflare">Cloudflare · automatic</option><option value="manual">Another provider · guided</option></select></label>
    <label class="installation-field">Vault connection<select data-settings-controlled name="dns_secret_ref" aria-label="Vault connection"><option value="">Choose a connection</option></select></label></div>
    <details data-installation-credential><summary>Add a Cloudflare connection</summary><p class="installation-muted">Create a token with Zone · DNS · Edit and Zone · Zone · Read, restricted to your domain. The token is saved in Vault.</p><a href="https://dash.cloudflare.com/profile/api-tokens" target="_blank" rel="noopener noreferrer">Create a token ↗</a>
    <label class="installation-field">API token<input data-settings-controlled data-installation-token type="password" autocomplete="new-password" spellcheck="false"></label><button type="button" data-installation-action="save-token">Save in Vault</button></details>
    <details data-installation-server><summary>Server settings</summary><label class="installation-field">Public server IP<input data-settings-controlled name="target_ip" placeholder="Detected automatically" required spellcheck="false"></label><p class="installation-muted">Check this value if the server uses NAT or a separate public IP.</p></details>
    <div class="installation-actions"><button class="installation-primary" type="submit">Review setup</button></div></form><div data-installation-plan></div><div data-installation-job></div><div data-installation-verification></div>`;const p=M=>e.querySelector(M),m=p("[data-installation-form]"),S=p("[data-installation-token]"),g=(M,P=!1)=>{if(c)return;const E=p("[data-installation-message]");E.textContent=M,E.setAttribute("role",P?"alert":"status")};function T(){if(c)return;const M=e.querySelector("[data-installation-confirm]");M&&r.set(M.dataset.installationConfirm,new FormData(M).getAll("action_id").map(String)),p("[data-installation-plan]").innerHTML=n?Jn(n,i):"",p("[data-installation-job]").innerHTML=a?Gn(a,s):"",a&&r.has(a.job_id)&&e.querySelectorAll("[data-installation-confirm] input").forEach(P=>{P.checked=r.get(a.job_id).includes(P.value)}),e.querySelectorAll("[data-installation-job] button").forEach(P=>{P.disabled=i}),m.querySelectorAll("button").forEach(P=>{P.disabled=i})}async function $(M,P=!0){const E=new AbortController;u.add(E),P&&(o+=1,i=!0,T(),g("Working…"));try{const _=await M(E.signal);return c?void 0:(P&&g(""),_)}catch(_){!c&&!E.signal.aborted&&g(_ instanceof qe?vt(_.code):"Reconnecting to the server. Progress will resume automatically.",!0);return}finally{u.delete(E),P&&(i=!1,T())}}async function b(M=!1){const P=o,E=await $(_=>ie("inspect",void 0,_),!1);if(!c){if(E&&P===o){t=E,p("[data-installation-overview]").innerHTML=Vn(t);const _=p("[name=dns_secret_ref]"),h=_.value;if(_.innerHTML='<option value="">Choose a connection</option>'+t.dns_credentials.map(f=>`<option value="${et(f.ref)}">${et(f.label)}</option>`).join(""),_.value=t.dns_credentials.some(f=>f.ref===h)?h:t.dns_credentials[0]?.ref||"",M){p("[name=address]").value=t.configuration.hostname;const f=(t.configuration.managed?t.configuration.target_ip:t.worker?.public_ip)||t.configuration.target_ip||"";p("[name=target_ip]").value=f,p("[data-installation-server]").open=!f}if(a=t.latest_job||a,a){const f=await $(y=>ie("status",{job_id:a.job_id},y),!1);f&&P===o&&(a=f.job,s=f.plan)}T()}c||(l=setTimeout(()=>{b()},a&&!Bn(a)?5e3:3e4))}}const D=async M=>{const P=M.target;if(P===m){if(M.preventDefault(),i)return;const E=new FormData(m),_=await $(h=>ie("plan",Object.fromEntries(E.entries()),h));_&&(n=_,T(),p("[data-installation-plan]").scrollIntoView?.({block:"nearest",behavior:"smooth"}))}else if(P.matches("[data-installation-confirm]")){if(M.preventDefault(),i||!a)return;const E=await $(_=>ie("confirm",{job_id:a.job_id,action_ids:new FormData(P).getAll("action_id")},_));E&&(a=E,T())}},w=async M=>{const P=M.target.closest("[data-installation-action]")?.dataset.installationAction;if(!(!P||i)){if(P==="rollback-review"){p("[data-installation-rollback]").removeAttribute("hidden");return}if(P==="save-token"){if(!S.value.trim()){g("Enter the Cloudflare API token.",!0);return}const E=await $(_=>jn(S.value.trim(),_));S.value="",E&&(p("[data-installation-credential]").open=!1,l&&clearTimeout(l),await b(),c||(p("[name=dns_secret_ref]").value=E))}else if(P==="verify"){const E=await $(_=>ie("verify",void 0,_));E&&(p("[data-installation-verification]").innerHTML=xt(E.verification))}else if(P==="apply"&&n){const E=await $(_=>ie("apply",{plan_id:n.plan_id},_));E&&(a=E,s=n,n=void 0,T(),l&&clearTimeout(l),b())}else if(["retry","rollback"].includes(P)&&a){const E=await $(_=>ie(P,{job_id:a.job_id},_));E&&(a=E,T(),l&&clearTimeout(l),b())}}},A=M=>{M.target.closest("[data-installation-form]")&&(n=void 0,T())},B=M=>A(M);return e.addEventListener("change",B),e.addEventListener("submit",D),e.addEventListener("click",w),e.addEventListener("input",A),b(!0),{destroy(){c=!0,l&&clearTimeout(l),u.forEach(M=>M.abort()),S.value="",e.replaceChildren(),e.removeEventListener("submit",D),e.removeEventListener("click",w),e.removeEventListener("input",A),e.removeEventListener("change",B)}}}function Qn(){let e=null,t;return{attach(n){e!==n&&(t?.destroy(),e=n,t=n?Kn(n):void 0)}}}let tt=!0;const $e=new Set;let ke=null;function nt(e={}){return tt&&!globalThis.document?.hidden&&(e.requireOnline===!1||globalThis.navigator?.onLine!==!1)}function Zn(e,t={}){if(typeof window>"u")return e(!0),()=>{};const n={notify:e,options:t,previous:nt(t)};if($e.add(n),!ke){const s=()=>{for(const i of $e){const o=nt(i.options);o!==i.previous&&(i.previous=o,i.notify(o))}},a=i=>{!ft(i)||i.data?.type!=="loopino.app.visibility-changed"||typeof i.data.visible!="boolean"||(tt=i.data.visible,s())};window.addEventListener?.("message",a),window.addEventListener?.("online",s),window.addEventListener?.("offline",s),globalThis.document?.addEventListener("visibilitychange",s),ke=()=>{window.removeEventListener?.("message",a),window.removeEventListener?.("online",s),window.removeEventListener?.("offline",s),globalThis.document?.removeEventListener("visibilitychange",s)}}return e(n.previous),()=>{$e.delete(n),$e.size||(ke?.(),ke=null,tt=!0)}}const Yn=256;function en(){if(typeof window>"u")return null;const e=window.__LOOPINO_APP_FRAME_CONTEXT__;if(!e||typeof e!="object"||Array.isArray(e))return null;const t=e;return!Et(t.app_id)||!Et(t.workspace_id)?null:{appId:t.app_id,workspaceId:t.workspace_id}}function Et(e){return typeof e=="string"&&e.trim()===e&&e.length>0&&e.length<=Yn&&!/[\u0000-\u001f\u007f]/u.test(e)}const Xn="loopino.pwa.cache-operations.request.v1",xn="loopino.pwa.cache-operations.accepted.v1",es="loopino.pwa.cache-operations.result.v1",ts=750,ns=1e4;function ss(e={}){return tn("diagnostics",e).then(t=>t?.dashboard??null)}function as(e={}){return tn("clear",e).then(t=>t?.cleanup?{cleanup:t.cleanup,dashboard:t.dashboard}:null)}async function tn(e,t){const n=t.parentWindow??ds();if(!n)return null;const s=t.parentOrigin===void 0?cs():st(t.parentOrigin);if(!s)return null;const a=(t.createMessageChannel??(()=>new MessageChannel))(),i=ps(),o={action:e,app_id:"settings",request_id:i,type:Xn};return new Promise((r,c)=>{let l=!1,u=!1,p=globalThis.setTimeout(()=>S(null),Ct(t.acceptanceTimeoutMs,ts));function m(){globalThis.clearTimeout(p),a.port1.close()}function S(T){u||(u=!0,m(),r(T))}function g(){u||(u=!0,m(),c(new Error("Loopino cache diagnostics are unavailable.")))}a.port1.addEventListener("message",T=>{const $=ne(T.data);if(!$||$.app_id!=="settings"||$.request_id!==i)return;if($.type===xn){if(l)return;l=!0,globalThis.clearTimeout(p),p=globalThis.setTimeout(g,Ct(t.resultTimeoutMs,ns));return}if(!l||$.type!==es)return;if($.status==="unavailable"){S(null);return}if($.status!=="ok"){g();return}const b=is($.dashboard),D=$.cleanup===void 0?void 0:ls($.cleanup);if(!b||e==="clear"&&!D){g();return}S({...D?{cleanup:D}:{},dashboard:b})}),a.port1.start();try{n.postMessage(o,s,[a.port2])}catch{S(null)}})}function is(e){const t=ne(e),n=os(t?.diagnostics),s=rs(t?.metrics);return n&&s?{diagnostics:n,metrics:s}:null}function os(e){const t=ne(e);return!t||t.backend!=="indexeddb"&&t.backend!=="memory"||typeof t.fileCacheAvailable!="boolean"||["cacheBytes","entryCount","fileCacheBytes","fileCacheEntryCount","pendingCleanupCount","structuredCacheBytes","structuredEntryCount"].some(s=>!_e(t[s]))||!de(t.originQuotaBytes)||!de(t.originUsageBytes)?null:t}function rs(e){const t=ne(e),n=ne(t?.counters),s=ne(t?.quota),a=ne(t?.requestWait);if(!t||t.schema!==Tn||!n||!s||!a||!at(t.updatedAt)||!at(t.windowStartedAt)||qn.some(i=>!_e(n[i]))||!de(s.lastEstimatedAt)||!de(s.quotaBytes)||!de(s.usageBytes)||s.supported!==null&&typeof s.supported!="boolean")return null;for(const i of["averageDurationMs","durationObservations","maxDurationMs","pendingCount","totalDurationMs"])if(!_e(a[i]))return null;return de(a.oldestPendingMs)?t:null}function ls(e){const t=ne(e);return!t||t.status!=="complete"&&t.status!=="pending"||!_e(t.pendingCleanupCount)||!_e(t.removed)?null:t}function ds(){return typeof window<"u"&&window.parent!==window?window.parent:null}function cs(){if(typeof window>"u")return null;const e=st(window.__LOOPINO_PLATFORM_ORIGIN__),t=st(window.location.origin);return e&&t&&e!==t?e:null}function st(e){if(typeof e!="string"||!e)return null;try{const t=new URL(e);return t.origin===e&&(t.protocol==="http:"||t.protocol==="https:")?t.origin:null}catch{return null}}function ps(){return globalThis.crypto?.randomUUID?.()??`${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`}function Ct(e,t){return typeof e=="number"&&Number.isFinite(e)&&e>0?Math.min(Math.floor(e),3e4):t}function _e(e){return typeof e=="number"&&Number.isSafeInteger(e)&&e>=0}function at(e){return typeof e=="number"&&Number.isFinite(e)&&e>=0}function de(e){return e===null||at(e)}function ne(e){return e&&typeof e=="object"&&!Array.isArray(e)?e:null}const fe=new Set;let Se=null;function us(e,t){if(typeof window>"u")return()=>{};const n={event:e,refresh:t};return fe.add(n),Se||(Se=gs()),()=>{fe.delete(n),fe.size||(Se?.(),Se=null)}}function gs(){const e=en(),t=!!(e&&window.parent&&window.parent!==window),n=()=>!!(globalThis.document?.hidden||globalThis.navigator?.onLine===!1);let s=t&&n(),a=null,i,o=!1,r=!1,c=0;const l=nt;let u=l();r=!u;const p=()=>{for(const w of fe)w.refresh()},m=w=>{for(const A of fe)A.event(w)};function S(){if(r=!0,o||!l()||i!==void 0)return;const w=Math.min(3e4,1e3*2**Math.min(c++,5)*(.8+Math.random()*.4));i=setTimeout(()=>{i=void 0,g()},w)}function g(){if(o||t||!l()||a||typeof WebSocket>"u")return;const w=window.location.protocol==="https:"?"wss:":"ws:";let A;try{A=new WebSocket(`${w}//${window.location.host}/api/apps/events/ws`)}catch{S();return}a=A;let B=!1;const M=()=>!o&&a===A;A.onopen=()=>{!M()||B||(B=!0,c=0,r&&(r=!1,p()))},A.onmessage=P=>{if(!M()||!l())return;let E;try{E=JSON.parse(P.data)}catch{return}m(E)},A.onclose=()=>{M()&&(a=null,S())},A.onerror=()=>{M()&&A.close()}}function T(){const w=l();if(w!==u)if(u=w,w)t?r&&!s&&(r=!1,p()):g();else{t&&n()&&(s=!0),r=!0,clearTimeout(i),i=void 0;const A=a;a=null,A?.close()}}function $(){t&&n()&&(s=!0)}function b(w){if(!t||!ft(w)||!w.data||typeof w.data!="object")return;const A=w.data;if(A.type==="loopino.app.events-resync")s=!1,l()?(r=!1,p()):r=!0;else if(A.type==="loopino.app.event"&&A.event&&typeof A.event=="object"){if(A.event.workspace_id&&A.event.workspace_id!==e.workspaceId)return;l()?m(A.event):r=!0}}const D=Zn(T);return window.addEventListener?.("offline",$),globalThis.document?.addEventListener("visibilitychange",$),window.addEventListener?.("message",b),g(),()=>{o=!0,clearTimeout(i);const w=a;a=null,w?.close(),D(),window.removeEventListener?.("offline",$),globalThis.document?.removeEventListener("visibilitychange",$),window.removeEventListener?.("message",b)}}let be=new WeakSet;const ee=new Map;function ms(e=document.getElementById("app")){ee.clear(),be=new WeakSet,e?.replaceChildren()}function fs(e){const t=n=>{if(n.target instanceof Element&&!n.target.hasAttribute("data-settings-controlled")){be.add(n.target);const s=n.target.closest("form, #workspace-assignments")?.querySelector("[data-action-status]");s&&(s.textContent="Unsaved changes")}};e.addEventListener("input",t,!0),e.addEventListener("change",t,!0)}function W(e){(typeof e=="string"?[...document.querySelectorAll(e),...Array.from(ee.values()).flatMap(n=>[...n.matches(e)?[n]:[],...n.querySelectorAll(e)])]:[e]).forEach(n=>{be.delete(n),n.querySelectorAll("[data-action-status]").forEach(s=>{s.textContent="",s.setAttribute("role","status")}),n.querySelectorAll("input, select, textarea").forEach(s=>be.delete(s))})}function vs(e,t){const n=document.activeElement,s=n instanceof HTMLInputElement||n instanceof HTMLTextAreaElement?[n.selectionStart,n.selectionEnd]:null,a=document.createElement("template");a.innerHTML=t,nn(e,a.content),n?.isConnected&&document.activeElement!==n&&(n.focus({preventScroll:!0}),s&&s[0]!==null&&s[1]!==null&&n.setSelectionRange(s[0],s[1]))}function te(e){return e instanceof Element?e.getAttribute("data-render-key")||e.id||["data-settings-model-accordion","data-hosted-model-accordion","data-runtime-row","data-workspace-row","data-app-row","data-dependency-row","data-agentic-provider-group","data-hosted-provider-group","data-execution-family"].map(t=>{const n=e.getAttribute(t);return n===null?"":`${t}:${n}`}).find(Boolean)||(e.classList.length?`${e.tagName}:${Array.from(e.classList).filter(t=>!t.startsWith("is-")).join(" ")}`:""):""}function Je(e,t){return e.nodeType===t.nodeType&&e.nodeName===t.nodeName&&te(e)===te(t)}function nn(e,t){let n=e.firstChild;for(const s of Array.from(t.childNodes)){if(n&&!Je(n,s)&&te(s)){const a=Array.from(e.childNodes).find(i=>Je(i,s))||ee.get(te(s));a&&(ee.delete(te(s)),e.insertBefore(a,n),n=a)}if(!n||!Je(n,s)){const a=s.cloneNode(!0);if(e.insertBefore(a,n),n&&!te(n)){const i=n;n=n.nextSibling,i.remove()}continue}hs(n,s),n=n.nextSibling}for(;n;){const s=n;n=n.nextSibling,s instanceof Element&&te(s).startsWith("page:")&&(ee.set(te(s),s),ee.size>12&&ee.delete(ee.keys().next().value)),e.removeChild(s)}}function hs(e,t){if(!(e instanceof Element)||!(t instanceof Element)){e.nodeValue!==t.nodeValue&&(e.nodeValue=t.nodeValue);return}const n=be.has(e)&&!t.hasAttribute("data-settings-controlled"),s=e instanceof HTMLDetailsElement?e.open:void 0,a=n&&"value"in e?String(e.value):void 0,i=n&&e instanceof HTMLInputElement?e.checked:void 0;if(!e.matches("[data-action-status]")&&!(e.hasAttribute("data-settings-owned-view")&&e.getAttribute("data-settings-owned-view")===t.getAttribute("data-settings-owned-view"))){for(const o of Array.from(e.attributes))e.hasAttribute("data-pending-action")&&["data-pending-action","aria-busy"].includes(o.name)||t.hasAttribute(o.name)||e.removeAttribute(o.name);for(const o of Array.from(t.attributes))e.getAttribute(o.name)!==o.value&&e.setAttribute(o.name,o.value);e.closest("[data-pending-action]")&&e.matches("input, button, select")&&e.setAttribute("disabled",""),!e.matches("[data-usage-history-chart], [data-usage-history-filters]")&&(nn(e,t),e instanceof HTMLDetailsElement&&s!==void 0&&(e.open=s),e instanceof HTMLInputElement&&(e.value=a??t.value,e.checked=i??t.checked),(e instanceof HTMLSelectElement||e instanceof HTMLTextAreaElement)&&(e.value=a??t.value))}}let it=new AbortController;function _s(){it.abort(),it=new AbortController}function v(e,t,n){e?.addEventListener(t,n,{signal:it.signal})}async function R(e,t={}){const n=await fetch(e,{credentials:"same-origin",headers:{"Content-Type":"application/json",...t.headers||{}},...t}),s=await n.json();if(!n.ok)throw new Error(s.detail||s.error||`Request failed ${n.status}`);return s}function At(e,t=""){return typeof e=="string"?e:t}function bs(e){return Array.isArray(e)?e.filter(t=>typeof t=="string"):[]}function ys(e){if(!e||typeof e!="object"||Array.isArray(e))return null;const t=e,n=t.kind==="image"||t.kind==="glyph"?t.kind:null;return n&&typeof t.value=="string"?{kind:n,value:t.value}:null}function ws(e){const t=e&&typeof e=="object"&&!Array.isArray(e)?e:{},n=At(t.app_id);return{app_id:n,name:At(t.name,n||"Unnamed app"),views:bs(t.views),logo:ys(t.logo)}}async function $s(){return((await R("/api/apps")).items||[]).map(ws).filter(t=>t.app_id)}function ht(e){const t=new URLSearchParams({consumer_app_id:e});return R(`/api/apps/dependencies?${t.toString()}`)}function sn(e,t,n){return R("/api/apps/dependencies",{method:"POST",body:JSON.stringify({consumer_app_id:e,alias:t,provider_app_ids:n})})}function ks(e="all"){return R(e==="all"?"/api/settings/platform":`/api/settings/platform?section=${e}`)}function Ss(){return R("/api/providers/usage")}function Es(e,t,n={}){const s=new URLSearchParams({resolution:e,periods:String(t)});return n.providerId&&s.set("provider_id",n.providerId),n.modelId&&s.set("model_id",n.modelId),R(`/api/usage/timeseries?${s.toString()}`)}function Cs(e){return R("/api/providers/hosted/selection",{method:"POST",body:JSON.stringify(e)})}function As(e){return R("/api/providers/speech/selection",{method:"POST",body:JSON.stringify(e)})}function Is(e){return R("/api/providers/agentic/workspace-bindings",{method:"POST",body:JSON.stringify(e)})}function Ps(e){return R("/api/providers/native/activate",{method:"POST",body:JSON.stringify({provider_id:e,confirmation:"native-runtime-reviewed"})})}function Ms(e,t="settings_runtime_sessions_cleared"){return R("/api/settings/runtime-sessions/clear",{method:"POST",body:JSON.stringify({session_ids:e,reason:t})})}function Ts(){return R("/api/auth/logout",{method:"POST"})}function qs(e){return R("/api/admin/persistence/migrations/dry-run",{method:"POST",body:JSON.stringify(e)})}function Ls(e){return R("/api/admin/persistence/migrations/apply",{method:"POST",body:JSON.stringify(e)})}function d(e){return e.replace(/[&<>"']/g,t=>t==="&"?"&amp;":t==="<"?"&lt;":t===">"?"&gt;":t==='"'?"&quot;":"&#39;")}function k(e){return d(e)}function an(){return{workspaceId:"",providerAppId:"",engines:[],engine:"",language:"auto",savedEngine:"",savedLanguage:"auto",loading:!1,saving:!1,loaded:!1,error:""}}const It={logical_names:["openrouter-api-key","deepinfra-api-key","google-ai-studio-api-key"],required:!1};function Ds(e){const t=e.state;let n=0;function s(){n+=1,Object.assign(t,an())}async function a(c,l=!1){if(!c||(t.workspaceId!==c&&s(),t.loading||t.saving||t.loaded&&!l))return;t.workspaceId=c;const u=++n;t.loading=!0,t.error="",e.render();try{const p=await ht("settings");if(u!==n)return;if(p.workspace_id!==c)throw new Error("The active workspace changed. Reload voice settings.");const S=p.dependencies.find(T=>T.alias==="text-to-speech")?.selected_provider_app_ids[0]||"";if(!S)throw new Error("Select a text-to-speech provider for Settings in App links.");const g=await R(`/api/apps/${encodeURIComponent(S)}/backend`,{method:"POST",body:JSON.stringify({action:"engine_health",include_voices:!1,_app_secret_request:It})});if(u!==n)return;t.providerAppId=S,i(g),t.loaded=!0}catch(p){u===n&&(t.error=p instanceof Error?p.message:"Unable to load text-to-speech settings.")}finally{u===n&&(t.loading=!1,e.render())}}function i(c,l=!1){t.engines=c.synthesis,(!t.loaded||l||t.engine===t.savedEngine)&&(t.engine=c.settings.synthesis_engine),(!t.loaded||l||t.language===t.savedLanguage)&&(t.language=c.settings.synthesis_language),t.savedEngine=c.settings.synthesis_engine,t.savedLanguage=c.settings.synthesis_language}async function o(){if(!t.providerAppId||t.saving||t.loading)return;const c=n;t.saving=!0,t.error="",e.render();try{const l=await R(`/api/apps/${encodeURIComponent(t.providerAppId)}/backend`,{method:"POST",body:JSON.stringify({action:"set_engine",synthesis_engine:t.engine,synthesis_language:t.language,_app_secret_request:It})});if(c!==n)return;i(l.engines,!0),W(".settings-tts-group"),e.notify("Text-to-speech settings updated.")}catch(l){c===n&&(t.error=l instanceof Error?l.message:"Unable to save text-to-speech settings.")}finally{c===n&&(t.saving=!1,e.render())}}function r(){v(document.getElementById("settings-tts-discard"),"click",()=>{t.engine=t.savedEngine,t.language=t.savedLanguage,W(".settings-tts-group"),e.render()}),v(document.getElementById("settings-tts-engine"),"change",c=>{t.engine=c.currentTarget.value,t.error="",e.render()}),v(document.getElementById("settings-tts-language"),"input",c=>{t.language=c.currentTarget.value;const l=document.getElementById("settings-tts-discard");l&&(l.disabled=t.engine===t.savedEngine&&t.language===t.savedLanguage)}),v(document.getElementById("settings-tts-save"),"click",()=>{o()}),v(document.getElementById("settings-tts-retry"),"click",()=>{a(t.workspaceId,!0)})}return{load:a,save:o,reset:s,bind:r}}const Rs={auto:"Automatic local voice",piper:"Piper","espeak-ng":"eSpeak NG",espeak:"eSpeak","kokoro-openrouter":"Kokoro · OpenRouter","kokoro-deepinfra":"Kokoro · DeepInfra",gemini:"Gemini 3.8 Flash-Lite TTS"};function Hs(e){const t=e.engines.find(a=>a.engine===e.engine),n=e.loading||e.saving,s=[{engine:"auto",available:!0},...e.engines];return`<section class="settings-hosted-provider-group settings-tts-group" aria-labelledby="settings-tts-title">
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
  </section>`}function Us(){return{workspaceId:"",providerId:"",modelId:"",effort:"",executionMode:"delegated",fallbackModelId:"",fallbackEffort:"",saving:!1,error:"",generation:0,savedSelection:""}}function ot(e,t,n=!1){const s=t?.computer_use,a=t?.workspace.workspace_id||"",i=e.workspaceId!==a,o=JSON.stringify([s?.provider_id,s?.model_id,s?.reasoning_effort,s?.execution_mode,s?.fallback_model_id,s?.fallback_reasoning_effort]);if(i&&(e.generation+=1,e.saving=!1,e.error=""),!i&&!n){if(e.savedSelection===o)return;const r=JSON.stringify([e.providerId||void 0,e.modelId||void 0,e.effort||void 0,e.executionMode,e.fallbackModelId||void 0,e.fallbackEffort||void 0]);if(e.savedSelection&&r!==e.savedSelection){e.savedSelection=o;return}}Object.assign(e,{workspaceId:a,providerId:s?.provider_id||"",modelId:s?.model_id||"",effort:s?.reasoning_effort||"",executionMode:s?.execution_mode||"delegated",fallbackModelId:s?.fallback_model_id||"",fallbackEffort:s?.fallback_reasoning_effort||"",savedSelection:o})}function on(e,t){return e?.computer_use?.providers.find(n=>n.provider_id===t.providerId)?.models.find(n=>n.model_id===t.modelId)}function Os(e,t){const n=e.computer_use;if(!n)return"";const s=on(e,t),a=s?.supported_reasoning_efforts||[],i=a.length?a.some(c=>c.effort===t.effort):!t.effort,o=t.providerId!==n.provider_id||t.modelId!==n.model_id||t.effort!==(n.reasoning_effort||"")||t.executionMode!==(n.execution_mode||"delegated")||t.fallbackModelId!==(n.fallback_model_id||"")||t.fallbackEffort!==(n.fallback_reasoning_effort||""),r=!n.can_configure||t.saving;return`<section class="settings-card settings-platform" aria-labelledby="settings-computer-use-title">
    <div class="settings-heading settings-platform-heading settings-model-card-heading">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">desktop_windows</span>
      <div><p class="settings-kicker">Models</p><h2 id="settings-computer-use-title">PC use decision model</h2></div>
    </div>
    <p class="settings-card-copy">Use the chat model directly or a separate interface operator. Reconnect PC use after changing execution mode. Operator model changes apply to the next UI task.</p>
    ${t.modelId==="gpt-6-luna"&&t.effort==="low"&&t.executionMode==="delegated"?'<p class="settings-card-copy">Luna Low uses planned UI steps. Choose a recovery model for tasks that need broader navigation.</p>':""}
    <div class="settings-platform-provider-forms">
      <label class="settings-platform-field settings-platform-field-wide"><span>UI execution</span>
        <select id="settings-computer-use-mode" ${r?"disabled":""}>
          <option value="direct" ${t.executionMode==="direct"?"selected":""}>Chat model directly</option>
          <option value="delegated" ${t.executionMode==="delegated"?"selected":""}>Separate interface operator</option>
        </select>
      </label>
      ${t.executionMode==="delegated"||!s||!i?`<label class="settings-platform-field settings-platform-field-wide"><span>Decision model</span>
        <select id="settings-computer-use-model" ${r?"disabled":""}>
          ${s?"":`<option selected disabled value="">Unavailable: ${d(t.modelId)}</option>`}
          ${n.providers.map(c=>`<optgroup label="${d(c.label)}">${c.models.map(l=>`<option value="${d(JSON.stringify([c.provider_id,l.model_id]))}" ${c.provider_id===t.providerId&&l.model_id===t.modelId?"selected":""}>${d(l.label)}</option>`).join("")}</optgroup>`).join("")}
        </select>
      </label>
      <label class="settings-platform-field settings-platform-field-wide"><span>Reasoning effort</span>
        <select id="settings-computer-use-effort" ${r||!s?"disabled":""}>
          ${i?"":`<option selected disabled value="${d(t.effort)}">Unavailable: ${d(t.effort)}</option>`}
          ${a.length?a.map(c=>`<option value="${d(c.effort)}" ${c.effort===t.effort?"selected":""}>${d(c.label)}</option>`).join(""):'<option value="">Default</option>'}
        </select>
      </label>
      ${t.executionMode==="delegated"?`<label class="settings-platform-field settings-platform-field-wide"><span>Recovery model</span>
        <select id="settings-computer-use-fallback" ${r?"disabled":""}>
          <option value="" ${t.fallbackModelId?"":"selected"}>Return to chat</option>
          ${t.fallbackModelId&&!n.providers.flatMap(c=>c.models).some(c=>c.model_id===t.fallbackModelId)?`<option selected disabled value="${d(t.fallbackModelId)}">Unavailable: ${d(t.fallbackModelId)}</option>`:""}
          ${n.providers.flatMap(c=>c.models).filter(c=>c.model_id!==t.modelId&&c.supported_reasoning_efforts.some(l=>l.effort==="medium")).map(c=>`<option value="${d(c.model_id)}" ${c.model_id===t.fallbackModelId?"selected":""}>${d(c.label)} · Mid</option>`).join("")}
        </select>
      </label>
      `:""}
      `:'<p class="settings-card-copy">The selected chat model controls the interface directly.</p>'}
      ${n.available?"":'<p class="settings-inline-error" role="alert">The saved model is unavailable. Choose an available model to continue PC use.</p>'}
      ${t.error?`<p class="settings-inline-error" role="alert">${d(t.error)}</p>`:""}
      <button type="button" id="settings-computer-use-discard" class="settings-secondary" ${o&&!r?"":"disabled"}>Discard edits</button>
      <button type="button" id="settings-computer-use-save" ${r||!s||!i||!o?"disabled":""}>
        <span class="material-symbols-rounded" aria-hidden="true">${t.saving?"sync":"save"}</span>
        ${t.saving?"Saving":"Save decision model"}
      </button>
    </div>
  </section>`}function Ns(e){const{state:t,getSettings:n,render:s}=e;let a=0;async function i(){const r=n();if(!r?.computer_use?.can_configure||t.saving)return;const c=r.workspace.workspace_id;if(c!==t.workspaceId)return;const l=t.generation,u=++a,p=()=>t.generation===l&&u===a&&n()?.workspace.workspace_id===c;t.saving=!0,t.error="";const m={workspace_id:c,provider_id:t.providerId,model_id:t.modelId,reasoning_effort:t.effort||null,execution_mode:t.executionMode,fallback_model_id:t.fallbackModelId||null,fallback_reasoning_effort:t.fallbackEffort||null};s();try{const S=await R("/api/settings/computer-use",{method:"POST",body:JSON.stringify(m)});if(!p()||S.workspace_id!==c)return;e.setSelection(S),ot(t,n(),!0),W('[aria-labelledby="settings-computer-use-title"]'),e.notify("PC use decision model updated.")}catch(S){p()&&(t.error=S instanceof Error?S.message:"Unable to update the decision model.")}finally{p()&&(t.saving=!1,s())}}function o(){v(document.getElementById("settings-computer-use-discard"),"click",()=>{ot(t,n(),!0),W('[aria-labelledby="settings-computer-use-title"]'),s()}),v(document.getElementById("settings-computer-use-mode"),"change",r=>{t.executionMode=r.currentTarget.value,t.executionMode==="direct"&&(t.fallbackModelId="",t.fallbackEffort=""),t.error="",s()}),v(document.getElementById("settings-computer-use-fallback"),"change",r=>{t.fallbackModelId=r.currentTarget.value,t.fallbackEffort=t.fallbackModelId?"medium":"",t.error="",s()}),v(document.getElementById("settings-computer-use-model"),"change",r=>{const[c,l]=JSON.parse(r.currentTarget.value);t.providerId=c,t.modelId=l,t.fallbackModelId===l&&(t.fallbackModelId="",t.fallbackEffort="");const u=on(n(),t);t.effort=u?.supported_reasoning_efforts.some(p=>p.effort==="low")?"low":u?.default_reasoning_effort||"",t.error="",s()}),v(document.getElementById("settings-computer-use-effort"),"change",r=>{t.effort=r.currentTarget.value,t.error="",s()}),v(document.getElementById("settings-computer-use-save"),"click",()=>{i()})}return{bind:o,save:i}}async function Bs(){try{return await R("/api/admin/persistence")}catch{return null}}const js={registry:"/api/apps",context:"/api/settings/platform?section=context",models:"/api/settings/platform?section=models",voice:"/api/settings/platform?section=voice","computer-use":"/api/settings/platform?section=computer-use",users:"/api/admin/users",workspaces:"/api/admin/workspaces",apps:"/api/admin/workspace-apps",persistence:"/api/admin/persistence",sessions:"/api/settings/runtime-sessions"};function _t(e){return e==="users"||e==="workspace-access"?["users","workspaces"]:e==="workspace-apps"?["context","workspaces","apps"]:e==="app-links"?["context","apps"]:e==="sessions"?["context","sessions"]:e==="usage"||e==="learning"?["context"]:e==="cache"||e==="installation"?[]:[e]}function Fs(e){const t=new Map,n=new Map;function s(r){return t.has(r)||t.set(r,{loaded:!1,loading:!1,error:""}),t.get(r)}function a(r,c=!1){if(!c&&n.has(r))return n.get(r).promise;if(!c&&s(r).loaded)return Promise.resolve();n.get(r)?.controller.abort();const l=new AbortController;Object.assign(s(r),{loading:!0,error:""});const u=performance.now(),p=R(js[r],{signal:l.signal}).then(m=>{l.signal.aborted||(e.publish(r,m),s(r).loaded=!0)}).catch(m=>{l.signal.aborted||(s(r).error=m instanceof Error?m.message:"Unable to load settings.")}).finally(()=>{n.get(r)?.controller===l&&(n.delete(r),s(r).loading=!1,performance.clearMeasures(`settings.load.${r}`),performance.measure(`settings.load.${r}`,{start:u,end:performance.now()}),e.changed(r))});return n.set(r,{controller:l,promise:p}),e.changed(r),p}function i(){n.forEach(({controller:r})=>r.abort()),n.clear(),t.clear()}function o(r){n.forEach(({controller:c},l)=>{r.includes(l)||(c.abort(),n.delete(l),s(l).loading=!1)})}return{state:s,ensure:a,reset:i,cancelExcept:o}}function Ws(e,t,n){e?.workspace.workspace_id!==t.workspace.workspace_id&&(e=null);const s=n==="models"?t.provider:n==="voice"?{...e?.provider||t.provider,hosted_text:t.provider.hosted_text,speech_stt:t.provider.speech_stt}:e?.provider||t.provider;return{...e,...t,provider:s,runtime:{...e?.runtime,...t.runtime,all_sessions:e?.runtime.all_sessions},computer_use:t.computer_use||e?.computer_use,agentic_admin:n==="models"?t.agentic_admin:e?.agentic_admin}}function bt(e){const t=document.activeElement,n=document.createElement("dialog");return n.className="settings-modal settings-confirm-dialog",n.setAttribute("aria-labelledby","settings-confirm-title"),n.setAttribute("aria-describedby","settings-confirm-detail"),n.innerHTML=`<h2 id="settings-confirm-title">${d(e.title)}</h2>
    <p id="settings-confirm-detail" class="settings-card-copy">${d(e.detail)}</p>
    <form method="dialog" class="settings-modal-actions">
      <button value="cancel" class="settings-secondary" autofocus>Cancel</button>
      <button value="confirm" class="settings-danger">${d(e.confirmLabel)}</button>
    </form>`,document.body.append(n),new Promise(s=>{n.addEventListener("close",()=>{const a=n.returnValue==="confirm";n.remove(),t?.isConnected&&t.focus(),s(a)},{once:!0}),n.showModal()})}let Ge=null,Ee=null;function zs(e){const t=document.querySelector('.settings-modal[role="dialog"]');if(!t){Ee&&Ge?.isConnected&&Ge.focus(),Ee=null;return}const n=()=>Array.from(t.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex="0"]'));Ee!==t&&(Ge=document.activeElement,Ee=t,n()[0]?.focus()),t.onkeydown=s=>{if(s.key==="Escape"&&!t.querySelector("button#close-migration-modal:disabled")&&(s.preventDefault(),e()),s.key!=="Tab")return;const a=n(),i=a[0],o=a.at(-1);s.shiftKey&&document.activeElement===i&&(s.preventDefault(),o?.focus()),!s.shiftKey&&document.activeElement===o&&(s.preventDefault(),i?.focus())}}const Ke=20,rn=()=>({scope:"workspace",query:"",status:"",page:0});function yt(e,t){const n=e.runtime.all_sessions||e.runtime.sessions||[];return t.scope==="server"&&e.runtime.cleanup_scope==="server"?n:n.filter(s=>s.workspace_id===e.workspace.workspace_id)}function Vs(e,t){const n=t.query.trim().toLowerCase();return yt(e,t).filter(s=>(!t.status||s.status===t.status)&&`${s.session_id} ${s.agent_id} ${s.workspace_name||s.workspace_id} ${s.provider_id}`.toLowerCase().includes(n))}function Js(e,t,n){const s=yt(e,n),a=Vs(e,n),i=Math.max(1,Math.ceil(a.length/Ke));n.page=Math.min(n.page,i-1);const o=a.slice(n.page*Ke,(n.page+1)*Ke),r=e.runtime.cleanup_allowed===!0,c=n.scope==="server"?"All workspaces on this server":e.workspace.name;return`<section class="settings-card settings-runtime-settings-card">
    <div class="settings-heading"><div><p class="settings-kicker">${d(c)}</p><h2>Runtime sessions</h2></div>
      <button type="button" id="settings-clear-all-runtime" class="settings-danger" ${!r||!s.length||t.clearingAllRuntime?"disabled":""}>${t.clearingAllRuntime?"Deleting…":`Delete ${s.length} sessions`}</button>
    </div>
    <p class="settings-card-copy">Deletion stops active agents and removes their conversations, turns and runtime files. Review the confirmation before continuing.</p>
    <div class="settings-grid settings-session-filters">
      <label>Search sessions<input id="settings-session-search" type="search" value="${k(n.query)}" placeholder="Agent, workspace or session" /></label>
      <label>Status<select id="settings-session-status"><option value="">All statuses</option>${Array.from(new Set(s.map(l=>l.status))).sort().map(l=>`<option value="${k(l)}" ${n.status===l?"selected":""}>${d(l)}</option>`).join("")}</select></label>
      ${e.runtime.cleanup_scope==="server"?`<label>View scope<select id="settings-session-scope"><option value="workspace" ${n.scope==="workspace"?"selected":""}>Current workspace</option><option value="server" ${n.scope==="server"?"selected":""}>Entire server</option></select></label>`:""}
    </div>
    ${r?"":'<p role="status">You do not have permission to delete sessions in this workspace.</p>'}
    <div class="settings-platform-runtime-list">${o.map(l=>Gs(l,r,t)).join("")||'<p role="status">No sessions match this view.</p>'}</div>
    <div class="settings-pagination"><span role="status">${a.length} sessions · Page ${n.page+1} of ${i}</span>
      <button type="button" id="settings-sessions-prev" class="settings-secondary" ${n.page===0?"disabled":""}>Previous</button>
      <button type="button" id="settings-sessions-next" class="settings-secondary" ${n.page+1>=i?"disabled":""}>Next</button>
    </div>
    ${t.cleanupError?`<p class="settings-inline-error" role="alert">${d(t.cleanupError)}</p>`:""}
  </section>`}function Gs(e,t,n){const s=n.cleaningSessionIds.has(e.session_id)||n.clearingAllRuntime;return`<article class="settings-platform-runtime-row" data-runtime-row="${k(e.session_id)}">
    <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">terminal</span>
    <span class="settings-platform-runtime-copy"><span class="settings-platform-runtime-title"><strong>${d(e.agent_id||e.session_id)}</strong>
      <button type="button" class="settings-secondary" data-runtime-clear="${k(e.session_id)}" aria-label="Delete session ${k(e.agent_id||e.session_id)}" ${!t||s?"disabled":""}>${s?"Deleting…":"Delete"}</button></span>
      <small>${d(e.workspace_name||e.workspace_id)} · ${d(e.status)} · ${d(e.effective_mode)}</small>
      ${e.recovery_reason_code?`<small class="settings-inline-error">${d(e.recovery_reason_code)}</small>`:""}
      ${e.agentic_containment?.status==="NO-GO"?`<small class="settings-inline-error">Contained: ${d(e.agentic_containment.reason_code||"Unavailable")}</small>`:""}
      <code>${d(e.session_id)}</code></span>
  </article>`}const rt=[{value:"6h",label:"6 hours",resolution:"hour",periods:6},{value:"12h",label:"12 hours",resolution:"hour",periods:12},{value:"24h",label:"24 hours",resolution:"hour",periods:24},{value:"3d",label:"3 days",resolution:"hour",periods:72},{value:"7d",label:"7 days",resolution:"day",periods:7},{value:"30d",label:"30 days",resolution:"day",periods:30},{value:"90d",label:"90 days",resolution:"day",periods:90},{value:"180d",label:"180 days",resolution:"day",periods:180},{value:"1y",label:"1 year",resolution:"day",periods:365}],ln=[{value:"non_cached_tokens",label:"Non-cached"},{value:"total_tokens",label:"Processed total"},{value:"cached_input_tokens",label:"Cached input"},{value:"input_tokens",label:"Uncached input"},{value:"output_tokens",label:"Output"},{value:"reasoning_output_tokens",label:"Reasoning output"},{value:"cache_write_input_tokens",label:"Cache write"}];function lt(){return{metric:"non_cached_tokens",providerId:"",modelId:"",timeRange:"24h"}}function Ks(e,t){const n=ln.some(a=>a.value===t.metric)?t.metric:e.metric,s=rt.some(a=>a.value===t.timeRange)?t.timeRange:e.timeRange;return{metric:n,providerId:Pt(t.providerId,e.providerId),modelId:Pt(t.modelId,e.modelId),timeRange:s}}function dn(e){return rt.find(t=>t.value===e)||rt[2]}function qo(e,t){return t==="non_cached_tokens"?Math.max(0,Qe(e.total_tokens)-Qe(e.cached_input_tokens)):Math.max(0,Qe(e[t]))}function Lo(e){return ln.find(t=>t.value===e)?.label||"Non-cached"}function Do(e){const t=new Map,n=(i,o=[])=>{if(!i?.provider_id)return;const r=t.get(i.provider_id)||new Set;i.model_options.forEach(c=>c.model_id&&r.add(c.model_id)),o.forEach(c=>c&&r.add(c)),t.set(i.provider_id,r)},s=e?.provider;n(s?.active_provider,[s?.model_settings?.selected_model_id||"",...(s?.model_settings?.available_models||[]).map(i=>i.model_id)]),s?.available_providers?.forEach(i=>n(i));const a=s?.hosted_text;return n(a?.active_provider,[a?.model_settings?.selected_model_id||"",...(a?.model_settings?.available_models||[]).map(i=>i.model_id)]),a?.available_providers.forEach(i=>n(i)),e?.agentic_admin?.items.forEach(i=>{const o=t.get(i.model_provider_id)||new Set;i.model_id&&o.add(i.model_id),t.set(i.model_provider_id,o)}),Array.from(t,([i,o])=>({provider_id:i,model_ids:Array.from(o).sort((r,c)=>r.localeCompare(c))})).sort((i,o)=>i.provider_id.localeCompare(o.provider_id))}function Qe(e){return Number.isFinite(e)?e:0}function Pt(e,t){return typeof e=="string"?e.trim():t}function Qs(e,t,n=Date.now()){const s=t.providerUsageItems.find(o=>o.provider_id===e);if(!s)return t.isLoadingProviderUsage?"Loading usage…":t.providerUsageError?"Usage unavailable":"Usage limit not reported";if(!s.available)return"Usage unavailable";const a=s.limits.map(o=>({limit:o,windows:[o.primary_window,o.secondary_window].filter(r=>r!==null)})).filter(({windows:o})=>o.length>0);if(!a.length)return"Usage limit not reported";const i=a.length>1;return a.map(({limit:o,windows:r})=>`${i?`${o.label} — `:""}${r.map(l=>Zs(l,n)).join("; ")}`).join(" · ")}function Zs(e,t){const n=Math.min(100,Math.max(0,e.used_percent)),s=Math.max(0,100-n),a=Xs(e,t);return`${Ys(e.limit_window_seconds)}: ${Mt(n)} used · ${Mt(s)} remaining before limit${a?` · ${a}`:""}`}function Mt(e){return`${Number.isInteger(e)?e.toFixed(0):e.toFixed(1)}%`}function Ys(e){return!e||e<=0?"Rolling window":e%604800===0?`${e/604800}w window`:e%86400===0?`${e/86400}d window`:e%3600===0?`${e/3600}h window`:e%60===0?`${e/60}m window`:"Rolling window"}function Xs(e,t){let n=null;return e.reset_at_epoch_seconds!==null?n=Math.max(0,Math.ceil(e.reset_at_epoch_seconds-t/1e3)):n=e.reset_after_seconds,n===null?"":`resets ${xs(n)}`}function xs(e){if(e<=0)return"now";const t=Math.max(1,Math.ceil(e/60)),n=Math.floor(t/1440),s=Math.floor(t%1440/60),a=t%60;return n>0?`in ${n}d${s>0?` ${s}h`:""}`:s>0?`in ${s}h${a>0?` ${a}m`:""}`:`in ${a}m`}function ea(e){const t=e.isLoadingUsageHistory?"sync":"refresh",n=dn(e.usageHistoryFilters.timeRange),s=n.resolution==="hour"?"Hourly consumption":"Daily consumption";return`<section class="settings-card settings-platform settings-usage-history-card" aria-labelledby="settings-usage-history-title">
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
  </section>`}function ta(e){return`<section class="settings-card"><div class="settings-heading"><h2>Provider subscriptions</h2></div>
    ${e.providerUsageError?`<p role="alert">${d(e.providerUsageError)}</p>`:""}
    ${e.isLoadingProviderUsage?'<p role="status">Loading subscription usage…</p>':""}
    ${e.providerUsageItems.map(t=>`<article class="settings-subscription-row"><strong>${d(t.provider_id)}</strong><p>${d(Qs(t.provider_id,e))}</p></article>`).join("")}
    ${!e.isLoadingProviderUsage&&!e.providerUsageItems.length&&!e.providerUsageError?"<p>No subscription limits reported.</p>":""}
  </section>${ea(e)}`}const we=e=>["rejected","undone","undoing"].includes(e.status)?e.status:e.implementation?.status||e.status,na=[{id:"proposed",label:"Proposed",states:["pending"],hint:"Accept to start a Chat agent"},{id:"queued",label:"Queued",states:["accepted","queued","launching"],hint:"Starts when an agent slot is available"},{id:"running",label:"In progress",states:["running","stopping"],hint:"Follow the agent in Chat"},{id:"review",label:"To verify",states:["awaiting_review"],hint:"Check the result before completing"},{id:"attention",label:"Needs attention",states:["failed","cancelled"],hint:"Inspect the chat and retry when ready"},{id:"done",label:"Done",states:["implemented"],hint:"Implementation confirmed"},{id:"closed",label:"Dismissed",states:["rejected"],hint:"Proposals you chose to dismiss"}],sa=[{id:"proposed",label:"Proposed",states:["pending","checking"],hint:"Accept to start a Memory agent"},{id:"queued",label:"Queued",states:["accepted","queued","launching"],hint:"One Memory chat at a time"},{id:"running",label:"In progress",states:["running","saving","stopping","undoing"],hint:"Verifies sources and saves the approved fact"},{id:"attention",label:"Needs attention",states:["failed","cancelled"],hint:"Read the chat before retrying"},{id:"done",label:"Saved",states:["saved"],hint:"Confirmed by the Memory provider"},{id:"undone",label:"Undone",states:["undone"],hint:"Saves you chose to undo"},{id:"closed",label:"Dismissed",states:["rejected"],hint:"Facts you chose to dismiss"}],aa={pending:"Proposed",checking:"Checking Memory",saving:"Saving",saved:"Saved",undoing:"Undoing",undone:"Undone",accepted:"Accepted · not started",queued:"Queued",launching:"Starting chat",running:"In progress",stopping:"Stopping",awaiting_review:"To verify",failed:"Failed",cancelled:"Stopped",implemented:"Done",rejected:"Dismissed"},dt=e=>["implemented","rejected","saved","undone"].includes(we(e));function ia(e){const t=we(e);return t==="pending"?[[e.kind==="memory"?"approve":"accept",e.kind==="memory"?"Accept & save":"Accept & start"],["reject","Dismiss"]]:t==="saved"?e.details.node_created?[["undo","Undo save"]]:[]:t==="accepted"?[["start","Start implementation"],["reject","Dismiss"]]:["queued","launching","running"].includes(t)?[["stop",t==="queued"?"Remove from queue":"Stop implementation"]]:t==="awaiting_review"?[["implemented","Confirm implemented"],["retry","Continue fixing"]]:["failed","cancelled"].includes(t)?[["retry","Retry in same chat"],["reject","Dismiss"]]:[]}function oa(e,t){const n=we(e);if(t==="queued")return n==="pending"?e.kind==="memory"?"approve":"accept":n==="accepted"?"start":["failed","cancelled","awaiting_review"].includes(n)?"retry":void 0;if(t==="done"&&n==="awaiting_review")return"implemented";if(t==="closed"&&["pending","accepted","failed","cancelled"].includes(n))return"reject"}function Tt(e,t,n=!0){const s=we(e),a=ia(e),i=(l,u)=>`<button class="settings-secondary ${l==="accept"?"ticket-primary":""}" data-learning-item="${d(e.id)}" data-learning-command="${l}" ${t?"disabled":""}>${u}</button>`,o=[...new Set(e.evidence.map(l=>l.session_id))],r=e.details.memory_matches||[],c=`${n?`<p>${d(e.body)}</p>`:""}<dl class="learning-proposal-details">${["generalization","expected_impact","verification"].filter(l=>e.details[l]).map(l=>`<dt>${{generalization:"Why this helps other tasks",verification:"Verification",expected_impact:"Expected impact"}[l]}</dt><dd>${d(e.details[l])}</dd>`).join("")}</dl>
    ${e.evidence.map(l=>`<blockquote><p>${d(l.quote)}</p><small>${d(l.role)} · ${d(l.turn_id)} · <a href="/app/chat/threads/${encodeURIComponent(l.session_id)}">Source chat</a></small></blockquote>`).join("")}
    ${e.implementation?.summary?`<details data-learning-disclosure="${d(e.id)}-summary"><summary>Agent result</summary><p class="ticket-summary">${d(e.implementation.summary)}</p></details>`:""}
    ${e.status==="pending"?`<details data-learning-disclosure="${d(e.id)}-edit"><summary>Edit proposal</summary><label>Title<input data-learning-title="${d(e.id)}" value="${d(e.title)}" maxlength="240"></label><label>Description<textarea data-learning-body="${d(e.id)}" rows="3" maxlength="4000">${d(e.body)}</textarea></label>${i("edit","Save edit")}</details>`:""}`;return`<article class="learning-ticket ${n?"":"ticket-list-row"}" data-ticket-id="${d(e.id)}" data-ticket-state="${d(s)}">
    <div class="ticket-top"><span>${d(e.details.category||"Improvement")}</span>${a.length?`<button class="ticket-grip" draggable="${!t}" data-learning-drag="${d(e.id)}" aria-label="Move ${d(e.title)} between columns" title="Drag to Queued, Done or Dismissed; actions below also work with keyboard" ${t?"disabled":""}><span class="material-symbols-rounded" aria-hidden="true">drag_indicator</span></button>`:""}</div>
    <h4>${d(e.title)}</h4><p class="ticket-description">${d(e.body)}</p>
    <div class="ticket-meta"><span>${d(aa[s]||s)}</span>${e.details.effort?`<span>${d(e.details.effort)} effort</span>`:""}<span>${o.length} source chat${o.length===1?"":"s"}${e.occurrences>1?` · ${e.occurrences} observations`:""}</span></div>
    ${e.implementation?.error?`<p class="learning-error" role="status">${d(e.implementation.error)}</p>`:""}
    ${e.details.review_stale&&!dt(e)?'<p class="ticket-note">The source chat changed. Accepted tickets wait for reassessment before an agent starts.</p>':""}
    ${e.details.review_reason?`<p class="ticket-note">${d(e.details.review_reason)}</p>`:""}
    ${s==="awaiting_review"?'<p class="ticket-note">The agent finished its turn. Review the changes and checks in Chat.</p>':""}
    ${s==="pending"&&e.kind==="memory"&&r.length?`<label>Memory destination<select data-learning-target="${d(e.id)}" aria-label="Memory destination"><option value="">Choose destination</option>${r.map(l=>`<option value="${d(l.id)}">Attach to ${d(l.title)}</option>`).join("")}<option value="new">Create separate fact</option></select></label>`:""}
    ${e.details.memory_check_error||e.details.save_error?`<p class="learning-error">${d(e.details.save_error||e.details.memory_check_error)}</p>`:""}
    <div class="learning-actions">${e.kind==="memory"&&e.status==="saved"?`<a class="settings-secondary" href="/app/${encodeURIComponent(e.provider_id||"memory")}/nodes/${encodeURIComponent(e.node_id)}">Open Memory</a>`:""}${e.implementation?.session_id?`<a class="settings-secondary" href="/app/chat/threads/${encodeURIComponent(e.implementation.session_id)}">Open work chat <span aria-hidden="true">↗</span></a>`:""}${a.slice(0,1).map(([l,u])=>i(l,u)).join("")}</div>
    <details class="ticket-details" data-learning-disclosure="${d(e.id)}-ticket"><summary>Details &amp; evidence</summary>${c}${a.slice(1).map(([l,u])=>i(l,u)).join("")}</details>
  </article>`}function ra(e){const t=e.tab==="memory",n=t?"memory":"improvement",s=e.data.items.filter(p=>p.kind===n),a=e.ticketFilter||"open",i=e.ticketView||"board",o=(e.ticketSearch||"").trim().toLocaleLowerCase(),r=[...new Set(s.map(p=>p.details.category).filter(Boolean))].sort(),c=s.filter(p=>(a==="all"||(a==="closed"?dt(p):!dt(p)))&&(!e.ticketCategory||p.details.category===e.ticketCategory)&&(!o||`${p.title} ${p.body}`.toLocaleLowerCase().includes(o))),l=(t?sa:na).filter(p=>a==="all"||(a==="closed"?["done","closed","undone"].includes(p.id):!["done","closed","undone"].includes(p.id))),u=e.data.projects?.[n];return`${e.error?`<p class="learning-error" role="alert">${d(e.error)}</p>`:""}${e.notice?`<p class="ticket-queue-note" role="status" aria-live="polite">${d(e.notice)}</p>`:""}<div class="ticket-toolbar"><div class="ticket-toolbar-title"><strong>${t?"Memory":"Improvement"} tickets <span>${s.length}</span></strong><small>${t?"Accept a fact to start a Chat agent that verifies its sources and saves it to Memory.":"Accept a proposal to start a Chat agent with its source context."}${u?` <a href="/app/chat/projects/${encodeURIComponent(u)}">Open ${t?"Memory":"Improvements"} project ↗</a>`:""}</small></div>
    <div class="ticket-toolbar-controls"><div class="ticket-segment" role="group" aria-label="Ticket status filter">${["open","all","closed"].map(p=>`<button data-ticket-filter="${p}" aria-pressed="${a===p}">${{open:"Open",all:"All",closed:"Closed"}[p]}</button>`).join("")}</div>
    <div class="ticket-segment" role="group" aria-label="Ticket view">${["board","list"].map(p=>`<button data-ticket-view="${p}" aria-pressed="${i===p}" aria-label="${p==="board"?"Kanban board":"Ticket list"}"><span class="material-symbols-rounded" aria-hidden="true">${p==="board"?"view_kanban":"view_list"}</span></button>`).join("")}</div></div>
    <input id="ticket-search" data-settings-controlled type="search" aria-label="Search improvement tickets" placeholder="Search tickets…" value="${d(e.ticketSearch||"")}"><select id="ticket-category" data-settings-controlled aria-label="Ticket category"><option value="">All categories</option>${r.map(p=>`<option value="${d(p)}" ${p===e.ticketCategory?"selected":""}>${d(p)}</option>`).join("")}</select></div>
    <p class="ticket-queue-note">${t?"One Memory work chat runs at a time. Saved means the provider confirmed the write.":`Up to ${e.data.settings.improvement_concurrency??4} improvement chats run in parallel. Configure the limit in Usage & retention.`} Accepted tickets use normal Chat usage; analysis pause and allowance apply to analysis.${e.data.items.length>=200?" Showing the first 200 learning results.":""}</p>
    ${e.data.runtime_ready===!1?'<p class="learning-notice" role="status">Work chats are waiting for the backend update. Accepted tickets stay queued until launching is available.</p>':""}
    ${i==="board"?`<div class="learning-kanban" role="region" aria-label="Improvement ticket board" tabindex="0">${l.map(p=>{const m=c.filter(S=>p.states.includes(we(S)));return`<section class="ticket-column" data-ticket-column="${p.id}" aria-label="${p.label}"><header><h4><i aria-hidden="true"></i>${p.label}<span>${m.length}</span></h4><small>${p.hint}</small></header><div class="ticket-dropzone">${m.map(S=>Tt(S,e.saving)).join("")||'<div class="ticket-column-empty">No tickets</div>'}</div></section>`}).join("")}</div>`:`<div class="learning-list">${c.map(p=>Tt(p,e.saving,!1)).join("")||'<div class="learning-empty"><strong>No matching tickets</strong><p>Change the filters or wait for new proposals.</p></div>'}</div>`}`}function la(e,t,n){document.querySelectorAll("[data-ticket-filter]").forEach(a=>v(a,"click",()=>n({ticketFilter:a.dataset.ticketFilter}))),document.querySelectorAll("[data-ticket-view]").forEach(a=>v(a,"click",()=>n({ticketView:a.dataset.ticketView}))),v(document.querySelector("#ticket-search"),"input",a=>n({ticketSearch:a.target.value})),v(document.querySelector("#ticket-category"),"change",a=>n({ticketCategory:a.target.value}));let s="";document.querySelectorAll("[data-learning-drag]").forEach(a=>{v(a,"dragstart",i=>{if(e.saving){i.preventDefault();return}s=a.dataset.learningDrag,i.dataTransfer?.setData("text/plain",s),i.dataTransfer&&(i.dataTransfer.effectAllowed="move")}),v(a,"dragend",()=>{s="",document.querySelectorAll(".ticket-column.is-over").forEach(i=>i.classList.remove("is-over"))})}),document.querySelectorAll("[data-ticket-column]").forEach(a=>{const i=()=>{const o=e.data?.items.find(r=>r.id===s);return o&&oa(o,a.dataset.ticketColumn)};v(a,"dragover",o=>{!e.saving&&i()&&(o.preventDefault(),a.classList.add("is-over"))}),v(a,"dragleave",o=>{a.contains(o.relatedTarget)||a.classList.remove("is-over")}),v(a,"drop",o=>{o.preventDefault();const r=i();a.classList.remove("is-over"),r&&!e.saving&&t(s,r),s=""})})}function da(e){let t={data:null,error:"",loading:!1,saving:!1,tab:"memory",detail:null,dependency:null,dirty:!1},n="",s=0,a=0,i=0,o=null,r=!1,c=!1;const l=new Map,u=new Map,p=new Map,m=E=>R("/api/apps/chat/backend",{method:"POST",body:JSON.stringify(E)});function S(){o?.(),o=null}function g(){const E=document.querySelector(".learning-kanban")?.scrollLeft||0,_=document.activeElement,h=_?.id?`#${_.id}`:_?.getAttribute("name")?`[name="${_.getAttribute("name")}"]`:["data-learning-title","data-learning-body","data-learning-target"].map(Z=>_?.hasAttribute(Z)?`[${Z}="${_.getAttribute(Z)}"]`:"").find(Boolean),f=_ instanceof HTMLTextAreaElement||_ instanceof HTMLInputElement?[_.selectionStart,_.selectionEnd]:null,y=new Set(t.openSections);document.querySelectorAll("[data-learning-disclosure]").forEach(Z=>{Z.open?y.add(Z.dataset.learningDisclosure):y.delete(Z.dataset.learningDisclosure)}),t.openSections=[...y],e.render();const I=document.querySelector(".learning-kanban");I&&(I.scrollLeft=E);const j=h?document.querySelector(h):null;j?.focus({preventScroll:!0}),f?.[0]!=null&&(j instanceof HTMLTextAreaElement||j instanceof HTMLInputElement&&["text","search"].includes(j.type))&&j.setSelectionRange(f[0],f[1])}function T(){s++,n="",c=!1,l.clear(),u.clear(),p.clear(),S(),t={data:null,error:"",loading:!1,saving:!1,tab:"memory",detail:null,dependency:null,dirty:!1}}function $(){if(!r||o)return;const E=s,_=()=>{E===s&&(c=!0,t.saving||b(!0))};o=us(h=>{h.workspace_id===n&&h.owner_app_id==="chat"&&h.resource==="learning"&&_()},_)}async function b(E=!1){const _=e.workspaceId();if(!_||(n!==_&&(T(),n=_),t.loading||!E&&t.data))return;const h=s,f=++a;c=!1,t.loading=!0,t.data||g();try{const[y,I]=await Promise.all([m({action:"learning.read"}),ht("chat")]);if(h!==s||f!==a||_!==e.workspaceId())return;t.data=y,t.dependency=I,t.error=""}catch(y){h===s&&f===a&&(t.error=Ze(y))}finally{h===s&&f===a&&(t.loading=!1,g(),c&&!t.saving&&r&&b(!0))}}async function D(E,_){if(t.saving)return;const h=s;a++,t.loading=!1,t.saving=!0,t.error="",t.notice="",g();try{if(_&&await _(),h!==s||(await m(E),h!==s))return;const f=E;if(f.action==="learning.configure"&&f.settings&&"enabled"in f.settings&&(l.clear(),W("#learning-settings")),t.notice=f.action==="learning.configure"?"Settings saved":["accept","approve","start","retry"].includes(f.command||"")?"Ticket queued. Its work chat appears when the agent starts.":f.command==="implemented"?"Implementation confirmed.":f.command==="stop"?"Stop requested. This chat keeps its slot until the turn ends.":"Action completed",f.item_id){const y=f.item_id;for(const I of u.keys())I.endsWith(":"+y)&&u.delete(I);W(["data-learning-title","data-learning-body","data-learning-target"].map(I=>`[${I}="${CSS.escape(y)}"]`).join(", "))}t.dirty=l.size>0||u.size>0,await b(!0)}catch(f){h===s&&(t.error=Ze(f))}finally{h===s&&(t.saving=!1,g(),c&&r&&b(!0))}}async function w(E){const _=new FormData(E),h={};h.paused=t.data.settings.paused;for(const I of["enabled","memory_enabled","improvements_enabled"])h[I]=_.get(I)==="on";for(const I of["idle_seconds","max_context_chars","max_output_tokens","timeout_seconds","daily_token_budget","retention_days"])h[I]=Number(_.get(I));_.has("improvement_concurrency")&&(h.improvement_concurrency=Number(_.get("improvement_concurrency")));for(const I of["memory_mode","model_source","model_id","reasoning_effort","instructions"])h[I]=String(_.get(I)||"");for(const I of["excluded_thread_ids","excluded_project_ids"])h[I]=String(_.get(I)||"").split(/[\s,]+/).filter(Boolean);const f=String(_.get("memory_provider")||""),y=t.dependency?.dependencies.find(I=>I.alias==="learning-memory")?.selected_provider_app_ids[0]||"";await D({action:"learning.configure",settings:h},f!==y?()=>sn("chat","learning-memory",f?[f]:[]):void 0)}function A(){const E=(h,f)=>{const y=document.querySelector(`[data-learning-target="${h}"]`)?.value||"",I=document.querySelector(`[data-learning-title="${h}"]`)?.value,j=document.querySelector(`[data-learning-body="${h}"]`)?.value;D({action:"learning.review",item_id:h,command:f,target_node_id:y==="new"?"":y,confirm_new:y==="new",title:I,body:j})};la(t,E,h=>{Object.assign(t,h),g()});const _=document.querySelector("#learning-settings");if(_){for(const f of _.elements){if(!(f instanceof HTMLInputElement||f instanceof HTMLSelectElement||f instanceof HTMLTextAreaElement)||!f.name||!l.has(f.name))continue;const y=l.get(f.name);f instanceof HTMLInputElement&&f.type==="checkbox"?f.checked=y===!0:f.value=String(y)}const h=()=>{t.dirty=!0;for(const f of _.elements)(f instanceof HTMLInputElement||f instanceof HTMLSelectElement||f instanceof HTMLTextAreaElement)&&f.name&&l.set(f.name,f instanceof HTMLInputElement&&f.type==="checkbox"?f.checked:f.value);M()};v(_,"input",h),v(_,"change",h),M()}v(_,"submit",h=>{h.preventDefault(),w(_)}),v(document.querySelector("#learning-refresh"),"click",()=>{b(!0)}),v(document.querySelector("#learning-discard"),"click",()=>{t.dirty=!1,l.clear(),u.clear(),t.notice="",W("#learning-settings, .learning-results"),g()}),v(document.querySelector("#learning-pause"),"click",()=>{D({action:"learning.configure",settings:{paused:!t.data.settings.paused}})}),v(document.querySelector("#learning-session"),"change",h=>{t.selectedSession=h.target.value,g()}),document.querySelectorAll("[data-learning-disclosure]").forEach(h=>{h.open=!!t.openSections?.includes(h.dataset.learningDisclosure),v(h,"toggle",()=>{if(!h.isConnected)return;const f=new Set(t.openSections);h.open?f.add(h.dataset.learningDisclosure):f.delete(h.dataset.learningDisclosure),t.openSections=[...f]})}),v(document.querySelector("#learning-analyze"),"click",()=>{const h=document.querySelector("#learning-session")?.value;h&&D({action:"learning.analyze_now",session_id:h})});for(const h of["data-learning-title","data-learning-body","data-learning-target"])document.querySelectorAll(`[${h}]`).forEach(f=>{const y=h+":"+f.getAttribute(h);u.has(y)&&(f.value=u.get(y)),v(f,"input",()=>{u.set(y,f.value),t.dirty=!0,M()})});document.querySelectorAll('.learning-results a[href^="/app/"]').forEach(h=>v(h,"click",f=>{if(window.parent===window||f.ctrlKey||f.metaKey)return;f.preventDefault();const y=new URL(h.href).pathname.split("/").filter(Boolean),I=window.__LOOPINO_PLATFORM_ORIGIN__||"*";window.parent.postMessage({type:"loopino.app.open-app",app_id:decodeURIComponent(y[1]),params:{app_page:y.slice(2).map(decodeURIComponent).join("/")}},I)})),document.querySelectorAll("[data-learning-tab]").forEach(h=>v(h,"click",()=>{p.set(t.tab,{ticketView:t.ticketView,ticketFilter:t.ticketFilter,ticketSearch:t.ticketSearch,ticketCategory:t.ticketCategory}),i++,t.tab=h.dataset.learningTab,t.detail=null,Object.assign(t,{ticketView:void 0,ticketFilter:void 0,ticketSearch:void 0,ticketCategory:void 0},p.get(t.tab)),g()})),document.querySelectorAll("[data-learning-tab]").forEach((h,f,y)=>v(h,"keydown",I=>{const j={ArrowRight:(f+1)%y.length,ArrowLeft:(f+y.length-1)%y.length,Home:0,End:y.length-1}[I.key];j!==void 0&&(I.preventDefault(),y[j].click(),document.querySelector(`#${y[j].id}`)?.focus())})),document.querySelectorAll("[data-learning-job]").forEach(h=>v(h,"click",async()=>{const f=h.dataset.learningJob,y=h.dataset.learningCommand;if(y!=="inspect"){await D({action:"learning.job",job_id:f,command:y});return}const I=s,j=++i;try{const Z=await m({action:"learning.job",job_id:f,command:y});I===s&&j===i&&(t.detail=Z.job,g())}catch(Z){I===s&&j===i&&(t.error=Ze(Z),g())}})),document.querySelectorAll("[data-learning-item]").forEach(h=>v(h,"click",()=>{const f=h.dataset.learningItem;E(f,h.dataset.learningCommand)}))}function B(E){if(r=E,!E){S();return}n&&$(),c&&!t.saving&&b(!0)}function M(){const E=document.querySelector("#learning-draft-status");E&&(E.textContent=t.dirty?"Unsaved changes":t.notice||"Settings are up to date");const _=document.querySelector("#learning-discard");_&&(_.disabled=!t.dirty||t.saving);const h=document.querySelector("[name=memory_enabled]"),f=document.querySelector("#learning-memory-options");f&&h&&(f.hidden=!h.checked);const y=document.querySelector("[name=model_source]")?.value;document.querySelectorAll("[data-learning-native]").forEach(j=>{j.hidden=y!=="workspace"});const I=document.querySelector("#learning-mode-hint");I&&(I.textContent=document.querySelector("[name=memory_mode]")?.value==="automatic"?"Only explicit user facts with verified quotes and no Memory matches are saved automatically.":"You approve each fact before it enters Memory.")}function P(){const E={};for(const[_,h]of l){if(_==="memory_provider"||!t.data)continue;const f=t.data.settings[_];E[_]=typeof f=="number"?Number(h):Array.isArray(f)?String(h).split(/[\s,]+/).filter(Boolean):h}return{...t,draftSettings:E}}return{load:b,reset:T,bind:A,setVisible:B,viewState:P}}function Ze(e){return e instanceof Error?e.message:"Learning operation failed"}function ca(e,t){const n={...e.data.settings,...e.draftSettings},s=e.saving?"disabled":"",a=e.dependency?.dependencies.find(c=>c.alias==="learning-memory"),i=a?.selected_provider_app_ids[0]||"",o=(c,l,u,p)=>`<label class="learning-toggle ${p?"learning-channel":""}">
    ${p?`<span class="material-symbols-rounded learning-channel-icon" aria-hidden="true">${p}</span>`:""}
    <span class="learning-toggle-copy"><strong>${l}</strong><small>${u}</small></span>
    <input type="checkbox" role="switch" name="${c}" ${n[c]?"checked":""} ${s}><span class="learning-toggle-track" aria-hidden="true"></span></label>`,r=(c,l,u,p,m)=>`<label>${l}<input type="number" name="${c}" min="${u}" max="${p}" value="${n[c]}" required ${s}><small>${m}</small></label>`;return`<form id="learning-settings" class="settings-card learning-controls" aria-busy="${e.saving}">
    <div class="learning-section-heading"><div><h3>Automatic learning</h3><p>Learn lasting knowledge and new Loopino improvements from completed work.</p></div><span class="settings-pill">One analysis at a time</span></div>
    ${o("enabled","Enable learning","Review conversations after a quiet period. Unfinished work stays under observation.")}
    <div class="learning-channel-grid">
      ${o("memory_enabled","Memory","Keep sourced discoveries, people, events and lasting knowledge.","neurology")}
      ${o("improvements_enabled","Improvements","Find general limits of Loopino; skip work already requested or underway.","lightbulb")}
    </div>
    <div class="learning-form-grid" id="learning-memory-options" ${n.memory_enabled?"":"hidden"}>
      <label>Save to<select name="memory_provider" ${s}><option value="">Choose a Memory provider</option>${a?.candidates.map(c=>`<option value="${d(c.app_id)}" ${c.app_id===i?"selected":""}>${d(c.name)}</option>`).join("")||""}</select><small id="learning-provider-hint">${i?"Facts and their chat evidence are saved to this app.":"Choose a provider to check existing knowledge and save facts."}</small></label>
      <label>Saving mode<select name="memory_mode" ${s}><option value="review" ${n.memory_mode==="review"?"selected":""}>Review before saving</option><option value="automatic" ${n.memory_mode==="automatic"?"selected":""}>Save supported explicit facts automatically</option></select><small id="learning-mode-hint">${n.memory_mode==="automatic"?"Only explicit user facts with verified quotes and no Memory matches are saved automatically.":"You approve each fact before it enters Memory."}</small></label>
    </div>
    <p class="learning-note">A quiet chat is not necessarily finished. Proposals require a completed work episode; development instructions do not become Memory.</p>
    <details class="learning-advanced" data-learning-disclosure="timing" ${e.openSections?.includes("timing")?"open":""}>
      <summary><span><strong>Timing &amp; model</strong><small>${n.idle_seconds} seconds after the last response · ${n.model_source==="workspace"?"Workspace Codex":"Fast API model"}</small></span><span class="material-symbols-rounded" aria-hidden="true">expand_more</span></summary>
      <div class="learning-form-grid">
        ${r("idle_seconds","Quiet period (seconds)",0,3600,"Delay before review. New messages postpone it; this delay does not certify that work is finished.")}
        <label>Analysis model<select name="model_source" ${s}><option value="workspace" ${n.model_source==="workspace"?"selected":""}>Workspace Codex</option><option value="fast_model" ${n.model_source==="fast_model"?"selected":""}>Configured fast API model</option></select><small>API mode uses the fast model configured in platform settings.</small></label>
        <label data-learning-native ${n.model_source==="workspace"?"":"hidden"}>Codex model<select name="model_id" ${s}><option value="">Workspace default</option>${t.map(c=>`<option value="${d(c.model_id)}" ${c.model_id===n.model_id?"selected":""}>${d(c.label||c.model_id)}</option>`).join("")}${n.model_id&&!t.some(c=>c.model_id===n.model_id)?`<option selected value="${d(n.model_id)}">${d(n.model_id)} (unavailable)</option>`:""}</select></label>
        <label data-learning-native ${n.model_source==="workspace"?"":"hidden"}>Reasoning<select name="reasoning_effort" ${s}>${["low","medium","high"].map(c=>`<option value="${c}" ${n.reasoning_effort===c?"selected":""}>${{low:"Low · faster",medium:"Medium",high:"High · more thorough"}[c]}</option>`).join("")}</select></label>
      </div>
    </details>
    <details class="learning-advanced" data-learning-disclosure="limits" ${e.openSections?.includes("limits")?"open":""}>
      <summary><span><strong>Usage &amp; retention</strong><small>${n.daily_token_budget.toLocaleString()} tokens per day · ${n.retention_days} days of transcripts</small></span><span class="material-symbols-rounded" aria-hidden="true">expand_more</span></summary>
      <div class="learning-form-grid">
        ${r("daily_token_budget","Daily token allowance",1e3,1e7,"UTC day. Each analysis reserves tokens before it starts.")}
        ${r("max_context_chars","Context limit (characters)",4e3,6e4,"Maximum conversation evidence per analysis.")}
        ${r("max_output_tokens","Output limit (tokens)",128,8192,"Maximum size of the generated suggestions.")}
        ${r("timeout_seconds","Timeout (seconds)",10,300,"Stop an analysis if it takes too long.")}
        ${r("retention_days","Transcript retention (days)",1,365,"Saved Memory facts and review decisions remain available.")}
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
  </form>`}const pa=e=>({pending:"To review",checking:"Checking Memory",saving:"Saving",saved:"Saved",undoing:"Undoing",undone:"Undone",rejected:"Rejected",accepted:"Accepted",implemented:"Implemented",queued:"Waiting",running:"Analyzing",completed:"Completed",failed:"Failed",cancelled:"Cancelled"})[e]||e;function qt(e){return d(new Date(e*1e3).toLocaleString())}function ua(e,t=[]){const{data:n,error:s,saving:a}=e;if(!n)return`<section class="settings-card learning-empty"><strong>${e.loading?"Loading learning settings…":"Learning is unavailable"}</strong>${s?`<p role="alert">${d(s)}</p>`:""}<button class="settings-secondary" id="learning-refresh">Retry</button></section>`;const i=n.settings,o=n.counts||{pending_memory:n.items.filter(g=>g.kind==="memory"&&g.status==="pending").length,pending_improvements:n.items.filter(g=>g.kind==="improvement"&&g.status==="pending").length,queued:n.jobs.filter(g=>g.status==="queued").length,running:n.jobs.filter(g=>g.status==="running").length,failed:n.jobs.filter(g=>g.status==="failed").length,budget_waiting:0},r=i.enabled?i.paused?"Paused":!i.memory_enabled&&!i.improvements_enabled?"No outputs selected":o.running?"Analyzing":"On":"Off",c=i.enabled?i.paused?"Chats are still captured. Resume when you are ready.":!i.memory_enabled&&!i.improvements_enabled?"Choose Memory or Improvements to start analysis.":o.running?"One conversation is being reviewed. The others wait in the queue.":"Quiet periods trigger review. Only completed work can produce proposals.":"Enable learning to capture future conversations.",l=n.daily_tokens_reserved_or_used,u=Math.min(100,Math.round(l/i.daily_token_budget*100)),p=a?"disabled":"",m=g=>n.conversations.find(T=>T.session_id===g)?.label||`Chat ${g.slice(0,8)}`,S={memory:o.open_memory??o.pending_memory,improvements:o.open_improvement??o.pending_improvements,analyses:o.queued+o.running,audit:0};return`<section class="settings-card learning-overview">
    <div class="learning-status-row"><div class="learning-status-copy"><span class="learning-status-dot ${i.enabled&&!i.paused?"is-on":""}" aria-hidden="true"></span><div><h3>Learning is ${r.toLowerCase()}</h3><p>${c}</p></div></div><div class="learning-actions">${i.enabled?`<button id="learning-pause" class="settings-secondary" ${p}>${i.paused?"Resume analysis":"Pause analysis"}</button>`:""}<button id="learning-refresh" class="learning-icon-button" aria-label="Refresh learning status" ${p}><span class="material-symbols-rounded" aria-hidden="true">refresh</span></button></div></div>
    <div class="learning-stats"><div><strong>${o.pending_memory+o.pending_improvements}</strong><span>To review</span></div><div><strong>${o.queued}</strong><span>In queue</span></div><div class="learning-usage"><div><span>Today’s token allowance</span><strong>${u}%</strong></div><progress value="${Math.min(l,i.daily_token_budget)}" max="${i.daily_token_budget}" aria-label="Daily learning token allowance"></progress><small>${l.toLocaleString()} / ${i.daily_token_budget.toLocaleString()} reserved or observed · resets at 00:00 UTC</small></div></div>
    ${l>=i.daily_token_budget?'<p class="learning-notice">Today’s allowance is reached. New analyses wait until the next UTC day or a higher saved allowance.</p>':""}
    ${o.budget_waiting&&l<i.daily_token_budget?'<p class="learning-notice">The remaining allowance cannot cover the next analysis. Increase it in Usage &amp; retention or wait for the UTC reset. Codex reserves extra tokens for its instructions.</p>':""}
    ${o.failed?`<p class="learning-notice">${o.failed} failed ${o.failed===1?"analysis":"analyses"}. Open the Analyses tab to inspect or retry.</p>`:""}
    ${s?`<p class="learning-error" role="alert">${d(s)}</p>`:""}
  </section>
  ${ca(e,t)}
  <section class="settings-card learning-results">
    <div class="learning-section-heading"><div><h3>Results &amp; history</h3><p>Review suggestions and see what the agent has done.</p></div></div>
    <div class="learning-manual"><label for="learning-session">Analyze a captured chat</label><div class="learning-actions"><select id="learning-session" data-settings-controlled ${!n.conversations.length||a?"disabled":""}><option value="">${n.conversations.length?"Choose a conversation…":"No captured conversations yet"}</option>${n.conversations.map(g=>`<option value="${d(g.session_id)}" ${e.selectedSession===g.session_id?"selected":""}>${d(m(g.session_id))}</option>`).join("")}</select><button id="learning-analyze" class="settings-secondary" ${a||!i.enabled||i.paused||!e.selectedSession||!i.memory_enabled&&!i.improvements_enabled?"disabled":""}>Analyze now</button></div><p class="learning-note">${i.enabled?i.paused?"Resume analysis to use the queue.":"Adds new captured messages to the same serial queue; active chats wait until ready.":"Enable learning first. Only conversations captured after activation are available."}</p></div>
    <div class="learning-tabs" role="tablist" aria-label="Learning results">${["memory","improvements","analyses","audit"].map(g=>`<button id="learning-tab-${g}" role="tab" aria-controls="learning-panel" aria-selected="${e.tab===g}" tabindex="${e.tab===g?"0":"-1"}" class="${e.tab===g?"is-active":""}" data-learning-tab="${g}">${{memory:"Memory",improvements:"Improvements",analyses:"Analyses",audit:"Activity"}[g]}${S[g]?`<span>${S[g]}</span>`:""}</button>`).join("")}</div>
    <div id="learning-panel" role="tabpanel" aria-labelledby="learning-tab-${e.tab}" tabindex="0">
    ${e.tab==="improvements"||e.tab==="memory"?ra(e):""}
    ${e.tab==="analyses"?`<div class="learning-list">${n.jobs.map(g=>`<article class="learning-row"><div><div class="learning-item-heading"><strong>${d(m(g.session_id))}</strong><span class="settings-pill">${d(pa(g.status))}</span></div><p>${qt(g.created_at)} · ${g.attempts} attempt(s) · ${g.usage||g.reserved} tokens${g.model?` · ${d(g.model)}`:""}</p>${g.error?`<p class="learning-error">${d(g.error)}</p>`:""}</div><div class="learning-actions"><button class="settings-secondary" data-learning-job="${d(g.id)}" data-learning-command="inspect">Details</button>${["queued","running"].includes(g.status)?`<button class="settings-secondary" data-learning-job="${d(g.id)}" data-learning-command="cancel" ${p}>Cancel</button>`:["failed","cancelled"].includes(g.status)?`<button class="settings-secondary" data-learning-job="${d(g.id)}" data-learning-command="retry" ${p}>Retry</button>`:""}</div></article>`).join("")||'<div class="learning-empty"><strong>No analyses yet</strong><p>After activation, finish a chat and wait for the quiet period. Its analysis will appear here.</p></div>'}</div>`:""}
    ${e.tab==="audit"?`<div class="learning-list">${n.audit.map(g=>`<div class="learning-row"><span>${d(g.action.replaceAll("."," · ").replaceAll("_"," "))}</span><small>${qt(g.created_at)} · ${d(g.actor)}</small></div>`).join("")||'<div class="learning-empty"><strong>No activity yet</strong><p>Settings changes and review decisions will appear here.</p></div>'}</div>`:""}
    ${e.detail?`<details class="learning-transcript" open><summary>Analysis details · ${d(e.detail.id)}</summary><h4>Conversation evidence</h4><pre>${d(JSON.stringify(e.detail.input,null,2))}</pre><h4>Agent result</h4><pre>${d(e.detail.output_text||"No output available. The run may be pending or its transcript retention period has ended.")}</pre></details>`:""}
    </div>
  </section>`}let cn=!0;const Le=()=>cn&&!document.hidden;function ga(e){window.addEventListener("message",t=>{if(!ft(t)||!t.data||typeof t.data!="object")return;const n=t.data;(n.type==="loopino.shell.theme-changed"||n.type==="loopino.app.navigate"&&(!n.app_id||n.app_id==="settings"))&&Ln(n.theme),n.type==="loopino.app.visibility-changed"&&n.app_id==="settings"&&(cn=n.visible===!0,e.visibilityChanged(Le())),n.type==="loopino.app.navigate"&&(!n.app_id||n.app_id==="settings")&&e.navigate(n.params||{})}),document.addEventListener("visibilitychange",()=>e.visibilityChanged(Le())),window.parent?.postMessage({type:"loopino.app.ready",app_id:"settings"},"*")}function ma(e){return R("/api/admin/users",{method:"POST",body:JSON.stringify(e)})}function fa(e,t){return R(`/api/admin/users/${encodeURIComponent(e)}`,{method:"PATCH",body:JSON.stringify(t)})}function va(e,t){return R(`/api/admin/users/${encodeURIComponent(e)}/password`,{method:"POST",body:JSON.stringify({password:t})})}function ha(e){return R(`/api/admin/users/${encodeURIComponent(e)}`,{method:"DELETE"})}function _a(e,t){return R(`/api/admin/users/${encodeURIComponent(e)}/workspaces`,{method:"PUT",body:JSON.stringify({memberships:t})})}function ba(e){return R(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"POST",body:JSON.stringify({source_id:e.source_id,enabled:!0})})}function ya(e,t){return R(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"PATCH",body:JSON.stringify({status:t?"enabled":"disabled"})})}function wa(e){return R(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"DELETE",body:JSON.stringify({})})}function ct(e,t){if(!t)return e;const n="items"in t?t.items:t.sessions,s="cleanup_allowed"in t?t.cleanup_allowed:e.runtime.cleanup_allowed,a="cleanup_scope"in t?t.cleanup_scope:e.runtime.cleanup_scope;return{...e,runtime:{...e.runtime,all_sessions:n||[],cleanup_allowed:s,cleanup_scope:a}}}function $a(e){const t=e?.provider.hosted_text?.active_provider||null,n=e?.provider.hosted_text?.model_settings||null;return ka(t,n)}function pn(e){const t=e?.provider.hosted_text||null,n=t?.active_provider||null;return(t?.available_providers?.length?t.available_providers:n?[n]:[]).flatMap(a=>{const i=a.provider_id===n?.provider_id&&t?.model_settings||null;return Sa(a,i).map(o=>({...o,hosted_text_profile:t?.profiles?.find(r=>r.profile.provider_id===a.provider_id&&r.profile.model_id===o.model_id)||null,metadata:{...o.metadata||{},hosted_provider_id:a.provider_id,hosted_provider_label:a.label||a.provider_id,hosted_provider_status:a.status}}))})}function ka(e,t){return{modelId:t?.selected_model_id||e?.default_model_family||""}}function Sa(e,t){const n=t?.selected_model_id||e?.default_model_family||"",s=Ye(t?.available_models).length?Ye(t?.available_models):Ye(e?.model_options);return(s.length?s:n?[Ca(n,t?.selected_reasoning_effort||"")]:[]).map(Ea)}function Ye(e){return(e||[]).filter(t=>t.model_id)}function Ea(e){return e.supported_reasoning_efforts.length||!e.default_reasoning_effort?e:{...e,supported_reasoning_efforts:[{effort:e.default_reasoning_effort,label:e.default_reasoning_effort,description:null}]}}function Ca(e,t){return{model_id:e,label:e,description:null,default_reasoning_effort:t||null,supported_reasoning_efforts:t?[{effort:t,label:t,description:null}]:[]}}function Aa(){return{computerUse:Us(),savedDrafts:null,speechSynthesis:an(),activatingNativeProviders:new Set,nativeProviderErrors:{},agenticBindingErrors:{},cleanupError:"",clearingAllRuntime:!1,cleaningSessionIds:new Set,hostedDraftModelId:"",hostedProviderError:"",hostedProviderErrorModelId:"",hostedRoutingDraftsByModel:{},isSavingHostedProvider:!1,isSavingSpeechProvider:!1,isLoadingProviderUsage:!1,isLoadingUsageHistory:!1,savingAgenticBindings:new Set,pendingAgenticEnabled:{},providerUsageError:"",providerUsageItems:[],usageHistory:null,usageHistoryFilters:lt(),usageHistoryError:"",speechAudioModelId:"",speechConversationModelId:"",speechProviderError:""}}function re(e,t,n={}){t?.computer_use&&ot(e.computerUse,t);const s=t?.workspace.workspace_id||"",a=e.savedDrafts?.workspaceId===s?e.savedDrafts:null,{modelId:i}=$a(t),o=qa(t),r=new Set([...pn(t).map(l=>l.model_id),i,...Object.keys(a?e.hostedRoutingDraftsByModel:{})].filter(Boolean)),c=Object.fromEntries(Array.from(r).map(l=>[l,Fe(je(t,l))]));(!a||e.hostedDraftModelId===a.hostedModelId||n.hostedModelId)&&(e.hostedDraftModelId=i),(!a||e.speechAudioModelId===a.audioModelId||n.speech)&&(e.speechAudioModelId=o.audioModelId),(!a||e.speechConversationModelId===a.conversationModelId||n.speech)&&(e.speechConversationModelId=o.conversationModelId),e.hostedRoutingDraftsByModel=Object.fromEntries(Array.from(r).map(l=>{const u=e.hostedRoutingDraftsByModel[l],p=a&&u&&JSON.stringify(u)!==JSON.stringify(a.routing[l]);return[l,p&&n.hostedModelId!==l?u:c[l]]})),e.savedDrafts={workspaceId:s,hostedModelId:i,audioModelId:o.audioModelId,conversationModelId:o.conversationModelId,routing:Object.fromEntries(Object.entries(c).map(([l,u])=>[l,{...u}]))}}function Ia(e,t,n){e.hostedDraftModelId=n,mn(e,t,n),e.hostedProviderError="",e.hostedProviderErrorModelId=""}function Pa(e,t){e.speechAudioModelId=t,e.speechProviderError=""}function Ma(e,t){e.speechConversationModelId=t,e.speechProviderError=""}function Ta(e,t,n,s,a){if(!n)return;const i=mn(e,t,n);e.hostedDraftModelId=n,s==="mode"&&typeof a=="string"&&["auto","prefer","only","ignore"].includes(a)?i.mode=a:s==="provider_id"&&typeof a=="string"?i.providerId=a:s==="allow_fallbacks"&&typeof a=="boolean"?i.allowFallbacks=a:s==="require_parameters"&&typeof a=="boolean"?i.requireParameters=a:s==="zdr"&&typeof a=="boolean"?i.zdr=a:s==="sort"&&typeof a=="string"&&["","price","throughput","latency"].includes(a)?i.sort=a:s==="data_collection"&&typeof a=="string"&&["","allow","deny"].includes(a)?i.dataCollection=a:s==="quantization"&&typeof a=="string"&&(i.quantization=a),e.hostedProviderError="",e.hostedProviderErrorModelId=""}function un(e,t=e.hostedDraftModelId){const n=e.hostedRoutingDraftsByModel[t]||Ra();return{mode:n.mode,provider_id:n.providerId||void 0,allow_fallbacks:n.allowFallbacks,require_parameters:n.requireParameters,zdr:n.zdr,sort:n.sort,data_collection:n.dataCollection,quantizations:n.quantization?[n.quantization]:[]}}function qa(e){const t=e?.provider.speech_stt||null,n=t?.active_provider||t?.available_providers?.find(i=>i.provider_id==="deepgram")||null,s=De(t,n,"prerecorded_transcription"),a=De(t,n,"conversational_streaming");return{audioModelId:t?.model_settings?.audio_transcription_model_id||s.find(i=>i.model_id==="nova-3")?.model_id||s[0]?.model_id||"nova-3",conversationModelId:t?.model_settings?.conversation_model_id||a.find(i=>i.model_id==="flux-general-multi")?.model_id||a[0]?.model_id||"flux-general-multi"}}function De(e,t,n){const s=n==="prerecorded_transcription"?e?.model_settings?.available_audio_transcription_models:e?.model_settings?.available_conversation_models;return s?.length?s:(e?.model_settings?.available_models?.length?e.model_settings.available_models:t?.model_options||[]).filter(i=>i.metadata?.purpose===n)}function je(e,t){const n=e?.provider.hosted_text?.selection?.openrouter_provider_routing_by_model?.[t];return{mode:n?.mode||"auto",provider_id:n?.provider_id||"",allow_fallbacks:n?.allow_fallbacks!==!1,require_parameters:n?.require_parameters===!0,zdr:n?.zdr===!0,sort:n?.sort||"",data_collection:n?.data_collection||"",quantizations:n?.quantizations||[]}}function gn(e,t,n){const s=je(t,n),a=un(e,n);return s.mode!==a.mode||(s.provider_id||"")!==(a.provider_id||"")||s.allow_fallbacks!==!1!=(a.allow_fallbacks!==!1)||s.require_parameters===!0!=(a.require_parameters===!0)||s.zdr===!0!=(a.zdr===!0)||(s.sort||"")!==(a.sort||"")||(s.data_collection||"")!==(a.data_collection||"")||(s.quantizations?.[0]||"")!==(a.quantizations?.[0]||"")}function La(e,t){return t.hostedProviderErrorModelId?t.hostedProviderErrorModelId:!t.hostedDraftModelId||!gn(t,e,t.hostedDraftModelId)?"":t.hostedDraftModelId}function Da(e,t,n){return e.hostedRoutingDraftsByModel[n]||Fe(je(t,n))}function mn(e,t,n){return e.hostedRoutingDraftsByModel[n]||(e.hostedRoutingDraftsByModel[n]=Fe(je(t,n))),e.hostedRoutingDraftsByModel[n]}function Fe(e){return{allowFallbacks:e.allow_fallbacks!==!1,dataCollection:e.data_collection||"",mode:e.mode||"auto",providerId:e.provider_id||"",quantization:e.quantizations?.[0]||"",requireParameters:e.require_parameters===!0,sort:e.sort||"",zdr:e.zdr===!0}}function Ra(){return Fe({mode:"auto",allow_fallbacks:!0,require_parameters:!1,zdr:!1,sort:"",data_collection:"",quantizations:[]})}function oe(e,t,n=""){return`<label class="settings-toggle settings-bouncy-toggle ${n}">
    ${e}
    <span class="settings-bouncy-toggle__label">${t}</span>
    <span class="settings-bouncy-toggle__track" aria-hidden="true">
      <span class="settings-bouncy-toggle__inner"></span>
      <span class="settings-bouncy-toggle__thumb"><span class="settings-bouncy-toggle__dot"></span></span>
    </span>
  </label>`}function Ha(e=document){e.querySelectorAll(".settings-bouncy-toggle").forEach(t=>{const n=s=>t.classList.toggle("is-pressed",s);v(t,"pointerdown",()=>n(!0)),v(t,"pointerup",()=>n(!1)),v(t,"pointerleave",()=>n(!1))})}const Ua=[{family_id:"native_agent",label:"CLI models",description:"Models running through an installed CLI.",workspace_actions:!0},{family_id:"loopino_agent",label:"API models",description:"Models running through a provider API.",workspace_actions:!0}];function Lt(e,t){return t?.find(n=>n.family_id===e)||Ua.find(n=>n.family_id===e)}function fn(e,t){return`<div class="settings-heading settings-platform-heading settings-model-card-heading">
    <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">${d(e)}</span>
      <div>
        <p class="settings-kicker">Models</p>
        <h2>${d(t)}</h2>
      </div>
    </div>`}function Oa(e,t,n,s,a){const i=new Set(s.filter(b=>a&&b.runtime_engine_id!=="codex"&&b.unavailable_reason==="native_agent_disabled"&&b.models.length>0).map(b=>b.runtime_engine_id)),o=e?.items||[],r=o,c=e?.release_decision||"GO",l=Lt("native_agent",n||e?.execution_families),u=Lt("loopino_agent",n||e?.execution_families),p=r.filter(b=>b.execution_family==="native_agent"||!b.execution_family&&b.runtime_engine_id==="codex"),m=r.filter(b=>b.execution_family==="loopino_agent"),S=new Set(o.filter(b=>b.execution_family==="native_agent"||!b.execution_family&&b.runtime_engine_id==="codex").map(b=>b.runtime_engine_id)),g=s.filter(b=>!S.has(b.runtime_engine_id)),T=[...ja(p).map(b=>({html:Ht(b,t),providerId:b.runtime_engine_id,canActivate:i.has(b.runtime_engine_id),providerLabel:Ie(b.runtime_engine_id)})),...g.map(b=>({html:Fa(b),providerId:b.runtime_engine_id,canActivate:i.has(b.runtime_engine_id),providerLabel:b.label||Ie(b.runtime_engine_id)}))],$=m.map(b=>({html:Ht(b,t),providerId:b.model_provider_id,providerLabel:Ie(b.model_provider_id)}));return`<section class="settings-card settings-platform settings-agentic-runtimes-card">
    ${fn("account_tree","Models")}
    ${c==="NO-GO"?'<p class="settings-platform-error settings-agentic-no-go"><strong>Remote agentic release: NO-GO</strong><br>Remote profiles remain visible for containment review but cannot be enabled or selected.</p>':""}
    ${Dt(l,T,t,"No native-agent runtime is registered by this installation.")}
    ${Dt(u,$,t,"No complete Loopino Agent profile is currently available.")}
  </section>`}function Dt(e,t,n,s){const a=Na(t);return`<section class="settings-runtime-family" data-execution-family="${k(e.family_id)}">
    <header class="settings-runtime-family-heading">
      <h3>${d(e.label)}</h3>
    </header>
    <div class="settings-runtime-provider-list">
      ${a.length?a.map(i=>Ba(i,n)).join(""):`<div class="settings-provider-usage-unavailable">
        <span class="material-symbols-rounded" aria-hidden="true">info</span>
        <span><strong>No available profiles</strong><small>${d(s)}</small></span>
      </div>`}
    </div>
  </section>`}function Na(e){const t=new Map;e.forEach(s=>{const a=t.get(s.providerId)||[];a.push(s),t.set(s.providerId,a)});const n=new Map([["codex",0],["antigravity-cli",1],["openrouter",2],["google-ai-studio",3]]);return Array.from(t.entries()).map(([s,a])=>({providerId:s,providerLabel:a[0]?.providerLabel||Ie(s),items:a})).sort((s,a)=>(n.get(s.providerId)??100)-(n.get(a.providerId)??100)||s.providerLabel.localeCompare(a.providerLabel))}function Ba(e,t){const n=e.items.some(i=>i.canActivate),s=t.activatingNativeProviders.has(e.providerId),a=t.nativeProviderErrors[e.providerId];return`<section class="settings-runtime-provider" data-agentic-provider-group="${k(e.providerId)}">
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
  </section>`}function Ie(e){return{"antigravity-cli":"Antigravity",codex:"Codex","google-ai-studio":"Google AI Studio",openrouter:"OpenRouter"}[e]||ye(e)}function ja(e){const t=new Map,n=[];return e.forEach(s=>{const a=s.runtime_engine_id==="antigravity-cli"?s.model_id.replace(/-(high|medium|low)$/i,""):s.model_id,i=`${s.runtime_engine_id}\0${a}`;t.has(i)||n.push(i);const o=t.get(i);(!o||Rt(s.model_id)>Rt(o.model_id))&&t.set(i,s)}),n.map(s=>t.get(s)).filter(s=>!!s)}function Rt(e){const t=e.match(/-(high|medium|low)$/i)?.[1]?.toLowerCase();return t==="high"?3:t==="medium"?2:t==="low"?1:0}function Fa(e){const t=e.models[0],n=e.unavailable_reason||"native_agent_unavailable",s=e.selectable===!0;return`<article class="settings-agentic-runtime settings-native-runtime-installation settings-agentic-runtime-static">
    <div class="settings-agentic-runtime-static__content">
      <span class="settings-model-summary-copy">
        <strong>${d(t?.model_id||e.label)}</strong>
        <small>${d(vn(t?.model_id,null))}</small>
      </span>
      <span class="settings-agentic-summary-badges">
        <span class="settings-pill ${s?"is-healthy":"is-warning"}">${s?"Available":d(ye(n))}</span>
      </span>
    </div>
  </article>`}function Ht(e,t){const n=e.definition_id,s=e.binding,a=s?.workspace_policy_ceiling||e.profile_policy_ceiling,i=s?.actor_policy||{allow_workspace_admins:!0,allowed_workspace_role_ids:["admin","member"]},o=e.execution_family==="loopino_agent",r=e.effective_capabilities,c=e.containment_status==="NO-GO",l=t.savingAgenticBindings.has(n),u=t.agenticBindingErrors[n]||"",p=a.max_estimated_cost_microusd===null?"":String(a.max_estimated_cost_microusd/1e6),m=e.credential_bindings,S=s?.credential_binding_id||m[0]?.binding_id||"",g=t.pendingAgenticEnabled[n]??!!s?.enabled,T=e.selectable===!0||!g&&e.enable_eligible===!0,$=e.enable_blocked_reason||e.blocked_reason||(o&&r?.status!=="active"?r?.reason_code||"effective capabilities unavailable":"")||"Unavailable";return`<details class="settings-model-accordion settings-agentic-runtime" data-settings-model-accordion="agentic-${k(n)}">
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
        ${o?`<label class="settings-platform-field">
          <span>Credential binding</span>
          <select data-agentic-field="credential_binding_id" ${l||c?"disabled":""}>
            <option value="">${m.length?"No credential":"No active credential available"}</option>
            ${m.map(b=>`<option value="${k(b.binding_id)}" ${b.binding_id===S?"selected":""}>${d(b.label||b.binding_id)} · ${b.workspace_id?"workspace":"platform"}</option>`).join("")}
          </select>
        </label>`:'<input data-agentic-field="credential_binding_id" type="hidden" value="">'}
        <label class="settings-platform-field">
          <span>Maximum cost per turn (USD)</span>
          <input data-agentic-field="max_estimated_cost_usd" type="number" min="0" step="0.01" value="${k(p)}" placeholder="No explicit ceiling" ${l||c?"disabled":""}>
        </label>
        <div class="settings-platform-checks settings-agentic-checks">
          <input data-agentic-field="enabled" type="checkbox" ${g?"checked":""} hidden>
          ${ue("is_default","Use as workspace default",!!s?.is_default,l||c)}
          <details class="settings-agentic-advanced">
            <summary>Advanced controls</summary>
            ${ue("allow_workspace_admins","Workspace administrators",i.allow_workspace_admins,l||c)}
            ${ue("allow_workspace_members","Workspace members",i.allowed_workspace_role_ids.includes("member"),l||c)}
            ${ue("require_confirmation_for_mutating","Confirm mutating tools",a.require_confirmation_for_mutating,l||c,e.profile_policy_ceiling.require_confirmation_for_mutating)}
            ${ue("require_confirmation_for_destructive","Confirm destructive tools",a.require_confirmation_for_destructive,l||c,e.profile_policy_ceiling.require_confirmation_for_destructive)}
          </details>
        </div>
      </div>
      <button type="button" data-agentic-binding-save data-agentic-definition-id="${k(e.definition_id)}" ${l||c?"disabled":""}>
        <span class="material-symbols-rounded" aria-hidden="true">${l?"progress_activity":"verified_user"}</span>
        ${l?"Saving binding":s?"Save binding":"Create binding"}
      </button>
      ${u?`<p class="settings-platform-error" role="alert">${d(u)}</p>`:""}
    </div>
  </details>`}function ue(e,t,n,s,a=!1){return oe(`<input data-agentic-field="${k(e)}" type="checkbox" role="switch" ${n?"checked":""} ${s||a?"disabled":""}>`,d(t))}function Ut(e){return e.runtime_engine_id==="codex"||e.runtime_engine_id==="antigravity-cli"?e.model_id:e.display_name.replace(/^OpenRouter\s+/i,"").replace(/^Google\s+/i,"").replace(/\s+·\s+Relace$/i,"")}function vn(e,t){const n=e?.match(/-(max|xhigh|high|medium|low)$/i)?.[1]||"",s=t||n;return`Reasoning · ${s?ye(s):"Preset"}`}function ye(e){return e.replace(/[._-]+/g," ").replace(/\b\w/g,t=>t.toUpperCase())}function Wa({modelOptions:e,openHostedModel:t,hostedProvider:n,settings:s,state:a,emptyMessage:i,inactiveMessage:o}){const r=!!n,c=Ja(e,n);return`<div class="settings-hosted-models">
    ${e.length?c.map(l=>za(l,t,n,s,a)).join(""):`<p class="settings-card-copy settings-platform-note">${d(i)}</p>`}
    ${r?"":`<p class="settings-card-copy settings-platform-note">${d(o)}</p>`}
  </div>`}function za(e,t,n,s,a){const i=e.providerStatus==="active"?"Active provider":"Inactive provider";return`<section class="settings-hosted-provider-group" data-hosted-provider-group="${k(e.providerId)}">
    <div class="settings-hosted-provider-heading">
      <span>
        <strong>${d(e.providerLabel)}</strong>
        <small>${e.models.length} ${e.models.length===1?"model":"models"}</small>
      </span>
      <span class="settings-pill">${d(i)}</span>
    </div>
    ${e.models.map(o=>Va(o,t,n,s,a)).join("")}
  </section>`}function Va(e,t,n,s,a){const i=e.model_id,o=Da(a,s,i),r=e.upstream_provider_options||[],c=r.length>0,l=Array.from(new Set(r.map(w=>w.quantization||"").filter(Boolean))),u=hn(e,n),p=bn(e,n),m=!!u,S=a.isSavingHostedProvider&&a.hostedDraftModelId===i,g=s.provider.hosted_text?.selection?.provider_id||n?.provider_id||"",T=u===g&&(s.provider.hosted_text?.model_settings?.selected_model_id||n?.default_model_family)||"",$=!!(m&&p==="active"&&i&&!a.isSavingHostedProvider&&(u!==g||i!==T||gn(a,s,i))),b=i===t,D=_n(e,n);return`<details class="settings-model-accordion settings-hosted-model-accordion" data-settings-model-accordion="hosted:${k(i)}" data-hosted-model-accordion="${k(i)}" id="settings-hosted-${k(encodeURIComponent(i))}" ${b?"open":""}>
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
      <select data-openrouter-routing="mode" data-hosted-model-id="${k(i)}" ${!m||!r.length||a.isSavingHostedProvider?"disabled":""}>
        ${[["auto","Auto"],["prefer","Prefer selected"],["only","Only selected"],["ignore","Ignore selected"]].map(([w,A])=>`<option value="${k(w)}" ${w===o.mode?"selected":""}>${d(A)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Upstream provider</span>
      <select data-openrouter-routing="provider_id" data-hosted-model-id="${k(i)}" ${!m||!r.length||o.mode==="auto"||a.isSavingHostedProvider?"disabled":""}>
        <option value="">Select provider</option>
        ${r.map(w=>`<option value="${k(String(w.provider_id||w.tag||""))}" ${(w.provider_id||w.tag)===o.providerId?"selected":""}>${d(w.label||w.provider_id||w.tag||"Provider")}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Sort</span>
      <select data-openrouter-routing="sort" data-hosted-model-id="${k(i)}" ${!m||a.isSavingHostedProvider?"disabled":""}>
        ${[["","OpenRouter default"],["price","Price"],["throughput","Throughput"],["latency","Latency"]].map(([w,A])=>`<option value="${k(w)}" ${w===o.sort?"selected":""}>${d(A)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Data collection</span>
      <select data-openrouter-routing="data_collection" data-hosted-model-id="${k(i)}" ${!m||a.isSavingHostedProvider?"disabled":""}>
        ${[["","OpenRouter default"],["allow","Allow"],["deny","Deny"]].map(([w,A])=>`<option value="${k(w)}" ${w===o.dataCollection?"selected":""}>${d(A)}</option>`).join("")}
      </select>
    </label>
    <label class="settings-platform-field">
      <span>Quantization</span>
      <select data-openrouter-routing="quantization" data-hosted-model-id="${k(i)}" ${!m||!l.length||a.isSavingHostedProvider?"disabled":""}>
        <option value="">Any</option>
        ${l.map(w=>`<option value="${k(w)}" ${w===o.quantization?"selected":""}>${d(w)}</option>`).join("")}
      </select>
    </label>
    <div class="settings-platform-checks">
      ${oe(`<input type="checkbox" role="switch" data-openrouter-routing="allow_fallbacks" data-hosted-model-id="${k(i)}" ${o.allowFallbacks?"checked":""} ${!m||a.isSavingHostedProvider?"disabled":""}>`,"Allow OpenRouter fallback")}
      ${oe(`<input type="checkbox" role="switch" data-openrouter-routing="require_parameters" data-hosted-model-id="${k(i)}" ${o.requireParameters?"checked":""} ${!m||a.isSavingHostedProvider?"disabled":""}>`,"Require supported parameters")}
      ${oe(`<input type="checkbox" role="switch" data-openrouter-routing="zdr" data-hosted-model-id="${k(i)}" ${o.zdr?"checked":""} ${!m||a.isSavingHostedProvider?"disabled":""}>`,"Require zero data retention")}
    </div>
    `:""}
    <button type="button" data-hosted-provider-save="${k(i)}" ${$?"":"disabled"}>
      <span class="material-symbols-rounded" aria-hidden="true">${S?"sync":"save"}</span>
      ${S?"Saving":"Save hosted model"}
    </button>
    ${a.hostedProviderError&&a.hostedProviderErrorModelId===i?`<p class="settings-platform-error">${d(a.hostedProviderError)}</p>`:""}
    </div>
  </details>`}function Ja(e,t){const n=new Map;for(const s of e){const a=hn(s,t)||"hosted-provider",i=n.get(a);if(i){i.models.push(s);continue}n.set(a,{providerId:a,providerLabel:_n(s,t),providerStatus:bn(s,t),models:[s]})}return Array.from(n.values()).sort((s,a)=>s.providerStatus==="active"&&a.providerStatus!=="active"?-1:a.providerStatus==="active"&&s.providerStatus!=="active"?1:s.providerLabel.localeCompare(a.providerLabel))}function hn(e,t){const n=e.metadata?.hosted_provider_id;return typeof n=="string"&&n?n:t?.provider_id||""}function _n(e,t){const n=e.metadata?.hosted_provider_label;return typeof n=="string"&&n?n:t?.label||t?.provider_id||"Hosted provider"}function bn(e,t){const n=e.metadata?.hosted_provider_status;return typeof n=="string"&&n?n:t?.status||""}function Ga(e,t){const n=e?.active_provider||e?.available_providers?.find(D=>D.provider_id==="deepgram")||null,s=De(e,n,"prerecorded_transcription"),a=De(e,n,"conversational_streaming"),i=e?.model_settings?.audio_transcription_model_id||s[0]?.model_id||"nova-3",o=e?.model_settings?.conversation_model_id||a[0]?.model_id||"flux-general-multi",r=t.speechAudioModelId||i,c=t.speechConversationModelId||o,l=s.find(D=>D.model_id===r)||s[0]||null,u=a.find(D=>D.model_id===c)||a[0]||null,p=Nt(l,e?.model_settings?.endpoints?.audio_transcription||`https://api.deepgram.com/v1/listen?model=${r}`),m=Nt(u,e?.model_settings?.endpoints?.conversation||`wss://api.deepgram.com/v2/listen?model=${c}`),S=!!(e?.active_provider&&e?.credential_binding),g=!!(S&&r&&c&&!t.isSavingSpeechProvider&&(r!==i||c!==o)),T=n?.label||n?.provider_id||"Deepgram",$=n?.provider_id||"deepgram",b=S?"Active provider":"Inactive provider";return`<div class="settings-hosted-models settings-speech-models">
    <section class="settings-hosted-provider-group" data-speech-provider-group="${k($)}">
      <div class="settings-hosted-provider-heading">
        <span>
          <strong>${d(T)}</strong>
          <small>2 settings</small>
        </span>
        <span class="settings-pill">${d(b)}</span>
      </div>
      ${Ot({id:"settings-speech-audio-model",label:"Audio transcription model",icon:"hearing",value:r,options:s,endpoint:p,description:l?.description||"Deepgram model for prerecorded audio, files, and one-shot microphone transcription.",disabled:!S||t.isSavingSpeechProvider,canSave:g,isSaving:t.isSavingSpeechProvider})}
      ${Ot({id:"settings-speech-conversation-model",label:"Conversation model",icon:"forum",value:c,options:a,endpoint:m,description:u?.description||"Deepgram Flux model for realtime voice conversation and turn detection.",disabled:!S||t.isSavingSpeechProvider,canSave:g,isSaving:t.isSavingSpeechProvider})}
    </section>
    ${t.speechProviderError?`<p class="settings-platform-error">${d(t.speechProviderError)}</p>`:""}
    ${S?"":'<p class="settings-card-copy settings-platform-note">Activate Deepgram with a Core Secrets binding before using speech-to-text.</p>'}
  </div>`}function Ot({id:e,label:t,icon:n,value:s,options:a,endpoint:i,description:o,disabled:r,canSave:c,isSaving:l}){return a.length?`<details class="settings-model-accordion settings-speech-model-accordion">
    <summary class="settings-model-trigger">
      <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">${d(n)}</span>
      <span class="settings-model-copy">
        <span class="settings-model-kicker">
          <span class="settings-kicker">${d(t)}</span>
        </span>
        <strong>${d(a.find(u=>u.model_id===s)?.label||s)}</strong>
        <small>${d(s)} · ${d(i)}</small>
      </span>
      <span class="settings-model-chevron material-symbols-rounded" aria-hidden="true">expand_more</span>
    </summary>
    <div class="settings-model-content settings-hosted-model-content">
      <label class="settings-platform-field settings-platform-field-wide">
        <span>${d(t)}</span>
        <select id="${k(e)}" ${r?"disabled":""}>
          ${a.map(u=>`<option value="${k(u.model_id)}" ${u.model_id===s?"selected":""}>${d(u.label||u.model_id)}</option>`).join("")}
        </select>
      </label>
      <div class="settings-platform-field settings-platform-field-wide">
        <span>Endpoint</span>
        <code class="settings-model-code">${d(i)}</code>
      </div>
      <p class="settings-card-copy">${d(o)}</p>
      <button type="button" data-speech-discard class="settings-secondary" ${c&&!l?"":"disabled"}>Discard edits</button>
      <button type="button" data-speech-save="${k(e)}" ${c?"":"disabled"}>
        <span class="material-symbols-rounded" aria-hidden="true">${l?"sync":"save"}</span>
        ${l?"Saving":"Save speech model"}
      </button>
    </div>
  </details>`:`<p class="settings-card-copy settings-platform-note">No ${d(t.toLowerCase())} options are available.</p>`}function Nt(e,t){const n=e?.metadata?.endpoint;return typeof n=="string"&&n?n:t}function Ka(e,t){const n=pn(e).filter(Za);return Qa(n,La(e,t),e.provider.hosted_text?.active_provider||null,e.provider.speech_stt||null,e,t)}function Qa(e,t,n,s,a,i){return`<section class="settings-card settings-platform settings-speech-model-settings-card">
    ${fn("record_voice_over","Speech model settings")}
    <div class="settings-platform-provider-forms">
      ${Hs(i.speechSynthesis)}
      ${Wa({modelOptions:e,openHostedModel:t,hostedProvider:n,settings:a,state:i,emptyMessage:"No hosted speech models are available from the active hosted providers.",inactiveMessage:"Activate the hosted provider before saving speech model routing."})}
      ${Ga(s,i)}
    </div>
  </section>`}function Za(e){return(e.output_modalities||[]).includes("speech")}function Ya(e,t,n="models"){return e?n==="computer-use"?Os(e,t.computerUse):n==="voice"?Ka(e,t):Oa(e.agentic_admin||null,t,e.provider.execution_families,e.provider.native_agents?.items||[],e.user.platform_role==="admin"):'<section class="settings-card"><p role="alert">Settings unavailable.</p></section>'}const Xa=5,xa=4,ei=4,ti=3,ni=4;function si(e){return`<section class="settings-loading-skeleton" role="status" aria-label="Settings content is loading">
    <header class="detail-header settings-loading-skeleton__header" aria-hidden="true">
      <div class="detail-title-block">
        ${H("title")}
        <span class="detail-title-separator" aria-hidden="true"></span>
        ${H("subtitle")}
      </div>
    </header>
    ${ai(e)}
  </section>`}function ai(e){return e.id==="workspace-access"?ri():e.id==="workspace-apps"?li():["models","voice","computer-use","usage","sessions"].includes(e.id)?di():e.id==="persistence"?ci():e.id==="cache"?ii():e.id==="learning"?`<section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">${se(!0)}<div class="settings-loading-skeleton__field-grid">${Q(3,()=>H("copy"))}</div></section>
      <section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">${se(!0)}${Q(2,()=>F("toggle"))}${Q(3,()=>H("copy-wide"))}${F("button")}</section>`:oi()}function ii(){return`<section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
    ${se(!0)}
    ${H("copy-wide")}
    <div class="settings-loading-skeleton__rows">
      ${Q(4,()=>wn())}
    </div>
    ${F("button")}
  </section>`}function oi(){return`<section class="settings-card settings-loading-skeleton__create" aria-hidden="true">
      ${pi("short-title")}
      ${Q(Xa,()=>F("field"))}
      ${F("button")}
    </section>
    ${yn()}
    <div class="settings-loading-skeleton__profile-row" aria-hidden="true">
      <section class="settings-card settings-loading-skeleton__detail-card">
        ${se(!0)}
        <div class="settings-loading-skeleton__field-grid">
          ${Q(xa,()=>Re())}
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
        ${Q(ei,()=>ui())}
      </div>
    </section>`}function li(){return`<section class="settings-card" aria-hidden="true">
      ${se(!1)}
      ${H("copy-wide")}
      <div class="settings-loading-skeleton__rows">
        ${Q(ti,()=>gi())}
      </div>
    </section>`}function di(){return`<section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
      ${Xe()}
    </section>
    <section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
      ${Xe()}
      <div class="settings-loading-skeleton__provider-form">
        ${Q(2,()=>Re())}
        ${F("button")}
      </div>
      ${Xe()}
    </section>
    <section class="settings-card settings-loading-skeleton__settings" aria-hidden="true">
      <div class="settings-loading-skeleton__runtime-toolbar">
        ${H("copy-wide")}
        ${F("button")}
      </div>
      <div class="settings-loading-skeleton__runtime-list">
        ${Q(ni,()=>mi())}
      </div>
    </section>`}function ci(){return`<section class="settings-card settings-loading-skeleton__persistence" aria-hidden="true">
      ${se(!0)}
      <div class="settings-loading-skeleton__adapter-cards">
        ${Q(2,()=>fi())}
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
  </div>`}function pi(e){return`<div class="settings-loading-skeleton__copy-stack">
    ${H("kicker")}
    ${H(e)}
  </div>`}function Re(){return`<span class="settings-loading-skeleton__field-wrap">
    ${H("label")}
    ${F("field")}
  </span>`}function ui(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--membership">
    ${F("checkbox")}
    ${pe("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${H("row-title")}
      ${H("row-copy")}
    </span>
    ${F("select")}
  </span>`}function gi(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--app">
    ${pe("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${H("row-title")}
      ${H("row-copy")}
    </span>
    ${F("toggle-pill")}
    ${F("button")}
  </span>`}function Xe(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--tile">
    ${pe("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${H("row-title")}
      ${H("row-copy")}
    </span>
  </span>`}function mi(){return`<span class="settings-loading-skeleton__row settings-loading-skeleton__row--runtime">
    ${pe("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${H("row-title")}
      ${H("row-copy")}
    </span>
    ${F("button")}
  </span>`}function fi(){return`<span class="settings-loading-skeleton__adapter-card">
    ${pe("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${H("row-title")}
      ${H("row-copy-wide")}
    </span>
    ${F("pill")}
  </span>`}function wn(){return`<span class="settings-loading-skeleton__result">
    ${pe("row")}
    <span class="settings-loading-skeleton__copy-stack">
      ${H("row-title")}
      ${H("row-copy-wide")}
    </span>
  </span>`}function H(e){return`<span class="settings-loading-skeleton__line settings-loading-skeleton__line--${e}"></span>`}function F(e){return`<span class="settings-loading-skeleton__block settings-loading-skeleton__block--${e}"></span>`}function pe(e){return`<span class="settings-loading-skeleton__icon settings-loading-skeleton__icon--${e}"></span>`}function Q(e,t){return Array.from({length:e},t).join("")}function vi({publishChanged:e,render:t,setNotice:n}){let s=[],a=[],i="",o=[],r="",c=!1,l=0,u=0,p="";const m=new Map;function S(){return{appRegistry:s,error:i,isLoading:c,loadErrors:o,savingKeys:new Set(m.keys()),dependencies:a.map(w=>({...w,dependencies:w.dependencies.map(A=>{const B=m.get(Bt(w.consumer_app_id,A.alias));return B?{...A,selected_provider_app_ids:B.providerAppIds}:A})}))}}function g(){l+=1,u+=1,c=!1,p="",m.clear(),s=[],a=[],i="",o=[],r=""}function T(){r=""}async function $(w,A,B=!1){if(!w||(p!==w&&(g(),p=w),c)||!B&&r===p)return;const M=++u;c=!0,i="",o=[],t();try{const[P,E]=await Promise.all([$s(),D(p,A)]);if(M!==u)return;s=P,a=E.dependencies,o=E.errors,r=p}catch(P){if(M!==u)return;r="",i=P instanceof Error?P.message:"Unable to load app links."}finally{M===u&&(c=!1,t())}}async function b(w,A,B){const M=l,P=Bt(w,A);if(m.has(P))return;const E={providerAppIds:[...B]};m.set(P,E),t();try{const _=await sn(w,A,B);if(M!==l||_.workspace_id!==p)return;u+=1,c=!1;const h=a.find(y=>y.consumer_app_id===w),f={..._,dependencies:_.dependencies.map(y=>y.alias===A?y:h?.dependencies.find(I=>I.alias===y.alias)||y)};a=[...a.filter(y=>y.consumer_app_id!==w),f].sort((y,I)=>y.consumer_app_id.localeCompare(I.consumer_app_id)),e(w,f),n({tone:"success",message:"App link updated."})}catch(_){if(M===l)throw _}finally{m.get(P)===E&&(m.delete(P),t())}}async function D(w,A){const B=A.filter(y=>y.workspace_id===w&&y.status==="enabled"),M=new Array(B.length);let P=0;const E=u;await Promise.all(Array.from({length:Math.min(4,B.length)},async()=>{for(;P<B.length&&E===u;){const y=P++,I=B[y];try{M[y]={app:I,payload:await ht(I.app_id)}}catch(j){M[y]={app:I,error:j instanceof Error?j.message:"Unable to load app links."}}}}));const _=M.filter(Boolean),h=_.filter(y=>"error"in y).map(y=>({app_id:y.app.app_id,message:y.error,name:y.app.name||y.app.app_id}));return{dependencies:_.filter(y=>"payload"in y&&y.payload.dependencies.length>0).map(y=>y.payload).sort((y,I)=>y.consumer_app_id.localeCompare(I.consumer_app_id)),errors:h}}return{ensureLoaded:$,invalidate:T,reset:g,saveDependencySelection:b,viewState:S}}function Bt(e,t){return`${e}:${t}`}function hi(e){let t=0;const n=new Map,s=a=>`${a.workspace_id}:${a.app_id}`;return{reset:()=>{t++,n.clear()},savingKeys:()=>new Set(n.keys()),apps:a=>a.map(i=>n.has(s(i))?{...i,status:n.get(s(i))?"enabled":"disabled"}:i),setEnabled:async(a,i)=>{const o=t,r=s(a);if(!n.has(r)){n.set(r,i),e.render();try{await ya(a,i),o===t&&e.updated(a,i)}catch(c){if(o===t)throw c}finally{o===t&&(n.delete(r),e.render())}}}}}function _i({appRegistry:e,dependencies:t,error:n,isLoading:s,loadErrors:a,savingKeys:i,workspaceApps:o}){return`<section class="settings-card settings-app-links">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">App links</p>
          <h2>Provider app links</h2>
          <button type="button" id="settings-refresh-app-links" class="settings-secondary" ${s?"disabled":""}>Refresh links</button>
        </div>
      </div>
      <p class="settings-card-copy">Provider links are workspace-scoped. A selected provider is reused until it becomes unavailable; otherwise one-provider interface links use the first available candidate as their automatic default.</p>
      ${n?`<p class="settings-platform-error">${d(n)}</p>`:""}
      ${a.length?`<div class="settings-app-link-errors">${a.map(Ci).join("")}</div>`:""}
      ${t.length>1?bi(t,e,o):""}
      <div class="settings-app-link-list">
        ${t.length?t.map(r=>yi(r,e,o,i)).join(""):$i(n,s)}
      </div>
    </section>`}function bi(e,t,n){return`<nav class="settings-app-link-consumer-nav" aria-label="Provider link apps">
    ${e.map(s=>{const a=n.find(r=>r.workspace_id===s.workspace_id&&r.app_id===s.consumer_app_id),i=wt(t,s.consumer_app_id),o=a?.name||i?.name||s.consumer_app_id;return`<a class="settings-app-link-consumer-nav__item" href="#${k($n(s.consumer_app_id))}">
        <strong>${d(o)}</strong>
        <small>${d(String(s.dependencies.length))}</small>
      </a>`}).join("")}
  </nav>`}function yi(e,t,n,s){const a=n.find(o=>o.workspace_id===e.workspace_id&&o.app_id===e.consumer_app_id),i=wt(t,e.consumer_app_id);return`<article class="settings-app-link-consumer" id="${k($n(e.consumer_app_id))}">
    <header class="settings-app-link-consumer__header">
      ${Sn(i)}
      <span class="settings-app-copy">
        <strong>${d(a?.name||e.consumer_app_id)}</strong>
        <small>${d(e.consumer_app_id)} - ${d(e.status)}</small>
      </span>
    </header>
    <div class="settings-app-link-dependencies">
      ${e.dependencies.map(o=>wi(e.consumer_app_id,o,t,s)).join("")}
    </div>
  </article>`}function wi(e,t,n,s){const a=s.has(ki(e,t.alias)),i=Si(t),o=kn(t);return`<section class="settings-app-link-row" data-dependency-row="${k(e)}:${k(t.alias)}">
    <header class="settings-app-link-row__header">
      <span class="settings-app-link-row__copy">
        <strong>${d(t.alias)}</strong>
        <small>${d(t.interface)} ${d(t.version)}</small>
      </span>
      <span class="settings-pill ${t.status==="resolved"||o?"":"settings-pill-muted"}">${d(Ei(t,o))}</span>
    </header>
    <p class="settings-card-copy">${d(t.description||"No description.")}</p>
    ${t.blocked_reason?`<p class="settings-platform-error">${d(t.blocked_reason)}</p>`:""}
    ${t.stale_provider_app_ids.length?`<p class="settings-platform-error">Unavailable selection: ${d(t.stale_provider_app_ids.join(", "))}</p>`:""}
    ${t.candidates.length?`<div class="settings-app-link-candidates">
            ${t.candidates.map(r=>{const c=i.includes(r.app_id),l=t.cardinality==="many"?"checkbox":"radio",u=`dependency:${e}:${t.alias}`,p=wt(n,r.app_id);return`<label class="settings-app-link-candidate ${c?"is-selected":""}">
                <input
                  data-settings-controlled
                  ${c?"checked":""}
                  ${a?"disabled":""}
                  data-dependency-choice="${k(jt(e,t.alias,r.app_id))}"
                  name="${k(u)}"
                  type="${l}"
                />
                ${Sn(p)}
                <span>
                  <strong>${d(r.name||r.app_id)}</strong>
                  <small>${d(r.app_id)} - ${d(r.interface_version)}${r.app_id===o?" - automatic default":""}</small>
                </span>
              </label>`}).join("")}
          </div>`:'<p class="settings-card-copy">No enabled provider app is available for this interface.</p>'}
    ${o?`<button type="button" class="settings-secondary" data-dependency-save-default="${k(jt(e,t.alias,o))}" ${a?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">${a?"sync":"save"}</span>
          ${a?"Saving":"Save default"}
        </button>`:""}
  </section>`}function $i(e,t){return e?"":t?'<p class="settings-card-copy">Loading app links...</p>':'<p class="settings-card-copy">No enabled app in the active workspace declares provider links.</p>'}function ki(e,t){return`${e}:${t}`}function jt(e,t,n){return`${e}:${t}:${n}`}function $n(e){return`settings-app-link-consumer-${e}`}function Si(e){if(e.selected_provider_app_ids.length)return e.selected_provider_app_ids;const t=kn(e);return t?[t]:[]}function kn(e){return e.selected_provider_app_ids.length||e.status!=="optional_unset"||e.cardinality!=="one"||e.stale_provider_app_ids.length||e.blocked_reason?"":e.candidates[0]?.app_id||""}function Ei(e,t){return t?"auto default":e.status==="optional_unset"?"unset":e.status}function wt(e,t){return e.find(n=>n.app_id===t)||null}function Ci(e){return`<p class="settings-platform-error">${d(e.name||e.app_id)}: ${d(e.message)}</p>`}function Sn(e){if(e?.logo?.kind==="image"&&e.logo.value)return`<span class="settings-app-link-logo is-image"><img alt="" loading="lazy" src="${k(e.logo.value)}" /></span>`;const t=e?.logo?.value||"apps";return`<span class="settings-app-link-logo is-glyph"><span class="material-symbols-rounded" aria-hidden="true">${d(t)}</span></span>`}function Ai(e){const{dashboard:t,error:n,isClearing:s,isLoading:a}=e,i=s?"Clearing…":"Clear cache";return`<section class="settings-card settings-cache-diagnostics" aria-busy="${a||s}">
    <div class="settings-heading">
      <div>
        <span class="settings-kicker">This browser</span>
        <h3>Loopino cache</h3>
      </div>
      <span class="settings-pill settings-pill-muted">Disposable</span>
    </div>
    <p class="settings-card-copy">Inspect aggregate cache usage for this browser container. Cached entries and file copies are rebuildable and never authorize server actions.</p>
    ${n?`<div class="settings-cache-diagnostics__error" role="alert">${d(n)}</div>`:""}
    ${Ii(t,a)}
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
    <p class="settings-cache-diagnostics__note">Clear cache removes only Loopino's structured data and versioned file cache from this browser container. It does not delete server files, static app assets, or unrelated origin storage.</p>
  </section>`}function Ii(e,t){if(!e||t)return`<div class="settings-cache-diagnostics__grid" aria-label="Loading cache diagnostics">
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
  ${Pi(s)}
  ${Mi(s)}`}function Pi(e){const t=e.counters;return`<div class="settings-cache-diagnostics__section">
    <h4>Cache activity</h4>
    <p>Aggregate events in this browser since ${d(qi(e.windowStartedAt))}.</p>
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
      ${q("Oldest pending (this window)",Ti(n.oldestPendingMs))}
      ${q("Average wait",pt(n.averageDurationMs))}
      ${q("Longest wait",pt(n.maxDurationMs))}
      ${q("Resolved / cancelled",X(t.pwa_request_wait_resolved,t.pwa_request_wait_cancelled))}
      ${q("Retry attempts",K(t.pwa_request_retry_attempt))}
      ${q("Worker installs / updates",X(t.pwa_sw_install,t.pwa_sw_update))}
      ${q("Worker recoveries / errors",X(t.pwa_sw_recovery,t.pwa_sw_error))}
      ${q("Static cache errors",K(t.pwa_static_cache_error))}
    </div>
  </div>`}function q(e,t){return`<div class="settings-cache-diagnostics__metric">
    <span>${d(e)}</span>
    <strong>${d(t)}</strong>
  </div>`}function Ft(e){return e===null?"Unavailable":ve(e)}function ve(e){if(!Number.isFinite(e)||e<=0)return"0 B";const t=["B","KB","MB","GB"],n=Math.min(t.length-1,Math.floor(Math.log(e)/Math.log(1024))),s=e/1024**n;return`${s>=10||n===0?s.toFixed(0):s.toFixed(1)} ${t[n]}`}function K(e){return e.toLocaleString()}function X(e,t){return`${K(e)} / ${K(t)}`}function Ti(e){return e===null?"None":pt(e)}function pt(e){return!Number.isFinite(e)||e<=0?"0 ms":e<1e3?`${Math.round(e)} ms`:`${(e/1e3).toFixed(e<1e4?1:0)} s`}function qi(e){const t=new Date(e);return Number.isFinite(t.getTime())?t.toLocaleString():"this session"}function Li(e){return Hi(e)}function Di(e){const{deleteSourceAfterMigration:t,migrationPlan:n,migrationProgress:s,migrationTarget:a,persistence:i}=e;if(!a||!i)return"";const o=i.active_adapter.kind.toUpperCase(),r=a.toUpperCase(),c=!!(s&&!["complete","failed"].includes(s.phase)),l=!!(n&&!n.same_adapter&&!c);return`<div class="settings-modal-backdrop" role="presentation">
    <section class="settings-modal" role="dialog" aria-modal="true" aria-labelledby="adapter-migration-title">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Confirm migration</p>
          <h2 id="adapter-migration-title">${o} → ${r}</h2>
        </div>
        <button type="button" class="settings-icon-button" id="close-migration-modal" aria-label="Close" ${c?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">close</span>
        </button>
      </div>
      ${n?Bi(n):Ni(s)}
      ${Ri(e)}
      ${oe(`<input id="settings-delete-source" type="checkbox" role="switch" ${t?"checked":""} ${c?"disabled":""} />`,"Schedule source cleanup after restart health check","settings-migration-delete-source")}
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
  </div>`}function Hi(e){const{migrationProgress:t,migrationResult:n,persistence:s}=e;if(!s)return`<section class="settings-card settings-persistence">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Persistence</p>
          <h2>Control plane adapter</h2>
        </div>
        <span class="settings-pill settings-pill-muted">offline</span>
      </div>
      <p class="settings-card-copy">The core persistence surfaces are not available in the active backend.</p>
    </section>`;const a=s.active_adapter,i=s.collections.reduce((l,u)=>l+u.count,0),o=a.kind==="json",r=a.kind==="mongo",c=t&&!["complete","failed"].includes(t.phase);return`<section class="settings-card settings-persistence">
    <div class="settings-heading">
      <div>
        <p class="settings-kicker">Persistence</p>
        <h2>Control plane adapter</h2>
      </div>
      <span class="settings-pill">${i} documents</span>
    </div>
    <div class="settings-adapter-cards">
      <button type="button" class="settings-adapter-card ${o?"is-active":""}" ${o||c?"disabled":'data-adapter-target="json"'}>
        <span class="settings-adapter-card-icon material-symbols-rounded" aria-hidden="true">${o?"check_circle":"database"}</span>
        <span>
          <strong>JSON</strong>
          <small>${d(o?a.json_root:"data/control-plane/json")}</small>
        </span>
        <em>${o?"Current":"Review migration"}</em>
      </button>
      <button type="button" class="settings-adapter-card ${r?"is-active":""}" ${r||c?"disabled":'data-adapter-target="mongo"'}>
        <span class="settings-adapter-card-icon material-symbols-rounded" aria-hidden="true">${r?"check_circle":"database"}</span>
        <span>
          <strong>Mongo</strong>
          <small>${d(r?a.mongo_database:"mongodb://127.0.0.1:27017/loopino")}</small>
        </span>
        <em>${r?"Current":"Review migration"}</em>
      </button>
    </div>
    ${Ui(t)}
    ${Oi(n)}
  </section>`}function Ui(e){return e?`<div role="status" aria-live="polite" class="settings-migration-progress ${e.phase==="failed"?"is-failed":""} ${e.phase==="complete"?"is-complete":""}">
    <div class="settings-migration-progress-heading">
      <span class="material-symbols-rounded" aria-hidden="true">${e.phase==="complete"?"check_circle":e.phase==="failed"?"error":"sync"}</span>
      <span>
        <strong>${d(e.title)}</strong>
        <small>${d(e.detail)}</small>
      </span>

    </div>
  </div>`:""}function Oi(e){return e?`<div class="settings-migration-result">
    <span class="material-symbols-rounded" aria-hidden="true">task_alt</span>
    <span>
      <strong>Last migration</strong>
      <small>${e.collections.reduce((n,s)=>n+s.count,0)} documents · target ${d(e.target_adapter.kind)} · cleanup ${e.source_cleanup?.scheduled?"scheduled":"not requested"}</small>
    </span>
  </div>`:""}function Ni(e){return`<div class="settings-migration-plan">
    <span class="material-symbols-rounded" aria-hidden="true">rule</span>
    <span>
      <strong>${d(e?.title||"Dry run not validated")}</strong>
      <small>${d(e?.detail||"Adjust the target fields, then validate the dry run before applying migration.")}</small>
    </span>
  </div>`}function Bi(e){const t=e.collections.reduce((s,a)=>s+a.count,0),n=e.target_collections.reduce((s,a)=>s+a.count,0);return`<div class="settings-migration-plan">
    <span class="material-symbols-rounded" aria-hidden="true">${e.same_adapter?"block":"rule"}</span>
    <span>
      <strong>${e.same_adapter?"Target already active":"Dry run complete"}</strong>
      <small>${t} source documents · ${n} target documents before copy · env ${d(e.env_file)}</small>
    </span>
    <div class="settings-migration-collections">
      ${e.collections.map(s=>`<span><strong>${d(s.name)}</strong><small>${s.count}</small></span>`).join("")}
    </div>
  </div>`}function ji({selectedUser:e,users:t}){return`<details class="settings-card settings-user-create"><summary>Create a user</summary><form class="settings-create" id="create-user">
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
            ${oe(`<input name="is_active" type="checkbox" role="switch" ${e.is_active?"checked":""} />`,"Account active")}
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
        </div>`:'<section class="settings-card"><h2>No users</h2></section>'}`}function Wt({selectedUser:e,users:t,workspaces:n,showPicker:s=!0}){return`${s?En(t,e):""}
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
          <div class="settings-memberships">${Fi(e,n)}</div>
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
    </section>`}function Fi(e,t){return t.map(n=>{const s=e.memberships.find(a=>a.workspace_id===n.workspace_id);return`<label class="settings-membership">
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
      </label>`}).join("")}function Wi({workspaceApps:e,workspaces:t,savingKeys:n=new Set}){return`<details class="settings-card"><summary>Create a workspace</summary><form id="create-workspace" class="settings-grid">
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
    </section>`}function zi(e,t,n){return e.map(s=>{const a=t.filter(r=>r.workspace_id===s.workspace_id),i=a.filter(r=>r.status==="enabled").length,o=a.filter(r=>r.installed).length;return`<details class="settings-app-workspace" data-workspace-row="${k(s.workspace_id)}">
        <summary class="settings-app-workspace-heading">
          <span class="settings-summary-caret material-symbols-rounded" aria-hidden="true">chevron_right</span>
          <span class="settings-app-workspace-icon material-symbols-rounded" aria-hidden="true">deployed_code</span>
          <span>
            <strong>${d(s.name)}</strong>
            <small>${d(s.workspace_id)} · ${i}/${o} enabled</small>
          </span>
        </summary>
        <div class="settings-apps">
          ${a.map(r=>Vi(r,n)).join("")}
        </div>
      </details>`}).join("")}function Vi(e,t){const n=e.status==="enabled",s=e.installed,a=s?e.status:"not installed",i=`${e.workspace_id}:${e.app_id}`,o=t.has(i);return`<div class="settings-app-row" data-app-row="${k(i)}">
    ${e.logo?.kind==="image"?`<img class="settings-app-icon" src="${k(e.logo.value)}" alt="" />`:`<span class="settings-app-icon material-symbols-rounded" aria-hidden="true">${d(e.logo?.kind==="glyph"?e.logo.value:"apps")}</span>`}
    <span class="settings-app-copy">
      <strong>${d(e.name)}</strong>
      <small>${d(e.app_id)} · v${d(e.version)} · ${d(a)}</small>
    </span>
    ${s?`${oe(`<input type="checkbox" role="switch" data-settings-controlled aria-label="Enable ${k(e.name)} in ${k(e.workspace_name)}" data-app-toggle="${k(i)}" ${n?"checked":""} ${o?"disabled":""} />`,"Enabled","settings-switch")}
        <button type="button" class="settings-secondary" data-app-uninstall="${k(i)}" ${o?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">link_off</span>
          Uninstall
        </button>`:`<button type="button" class="settings-secondary" data-app-install="${k(i)}">
          <span class="material-symbols-rounded" aria-hidden="true">add_link</span>
          Install
        </button>`}
  </div>`}function Ji(e){const{page:t,selectedUser:n}=e;if(t.id==="installation")return'<div id="installation-root" data-settings-owned-view="installation"></div>';if(t.id==="users")return ji({selectedUser:n,users:e.users})+Wt({selectedUser:n,users:e.users,workspaces:e.workspaces,showPicker:!1});if(t.id==="workspace-access")return Wt({selectedUser:n,users:e.users,workspaces:e.workspaces});if(t.id==="workspace-apps")return Wi({workspaceApps:e.workspaceApps,workspaces:e.workspaces,savingKeys:e.savingAppKeys});if(t.id==="app-links"){const s=e.appLinksController.viewState();return _i({appRegistry:s.appRegistry,dependencies:s.dependencies,error:s.error,isLoading:s.isLoading,loadErrors:s.loadErrors,savingKeys:s.savingKeys,workspaceApps:e.workspaceApps})}return["models","voice","computer-use"].includes(t.id)?e.platformSettingsHtml():t.id==="usage"?e.usageHtml():t.id==="sessions"?e.sessionsHtml():t.id==="learning"?e.learningHtml():t.id==="cache"?Ai(e.cacheDiagnosticsController.viewState()):Li(e.persistenceController.viewState())}async function Ce(e,t,n){if(!e||e.hasAttribute("data-pending-action"))return;const s=Array.from(e.querySelectorAll("input, button, select")),a=s.map(o=>o.disabled);e.setAttribute("data-pending-action",""),e.setAttribute("aria-busy","true");const i=e.querySelector("[data-action-status]");i&&(i.setAttribute("role","status"),i.textContent="Saving…");try{const o=t();s.forEach(r=>{r.disabled=!0}),await o,i&&(i.textContent="Saved.")}catch(o){i&&(i.setAttribute("role","alert"),i.textContent=o instanceof Error?o.message:"Unable to save."),n(o)}finally{e.removeAttribute("data-pending-action"),e.removeAttribute("aria-busy"),s.forEach((o,r)=>{o.disabled=a[r]})}}function Gi(e){document.querySelectorAll("[data-native-provider-activate]").forEach(t=>{v(t,"click",()=>{e.onActivateNativeProvider(t.dataset.nativeProviderActivate||"")})}),document.querySelectorAll("[data-agentic-binding-save]").forEach(t=>{v(t,"click",()=>{e.onSaveAgenticBinding(t.dataset.agenticDefinitionId||"")})}),document.querySelectorAll("[data-agentic-model-toggle]").forEach(t=>{v(t,"click",n=>n.stopPropagation()),v(t.closest("label"),"click",n=>n.stopPropagation()),v(t,"change",()=>{const n=t.checked;e.onSaveAgenticBinding(t.dataset.agenticDefinitionId||"",{enabled:n})})}),v(document.getElementById("settings-speech-audio-model"),"change",t=>{e.onSpeechAudioModelChanged(t.currentTarget.value)}),v(document.getElementById("settings-speech-conversation-model"),"change",t=>{e.onSpeechConversationModelChanged(t.currentTarget.value)}),document.querySelectorAll("[data-speech-save]").forEach(t=>{v(t,"click",()=>{e.onSaveSpeechProviderSettings()})}),v(document.getElementById("settings-speech-save"),"click",()=>{e.onSaveSpeechProviderSettings()}),document.querySelectorAll("[data-settings-model-accordion]").forEach(t=>{v(t,"toggle",()=>{t.open&&document.querySelectorAll("[data-settings-model-accordion]").forEach(n=>{n!==t&&(n.open=!1)})})}),document.querySelectorAll("[data-openrouter-routing]").forEach(t=>{v(t,"change",n=>{const s=n.currentTarget,a=s.dataset.hostedModelId||s.closest("[data-hosted-model-accordion]")?.dataset.hostedModelAccordion||"";e.onHostedProviderRoutingChanged(a,s.dataset.openrouterRouting||"",s instanceof HTMLInputElement&&s.type==="checkbox"?s.checked:s.value)})}),v(document.getElementById("settings-refresh-usage-history"),"click",e.onRefreshProviderUsage),document.querySelectorAll("[data-hosted-provider-save]").forEach(t=>{v(t,"click",()=>e.onSaveHostedProviderSettings(t.dataset.hostedProviderSave||""))}),v(document.getElementById("settings-logout"),"click",e.onLogout),v(document.getElementById("settings-clear-all-runtime"),"click",e.onClearAllRuntimeSessions),document.querySelectorAll("[data-runtime-clear]").forEach(t=>{v(t,"click",()=>e.onClearRuntimeSession(t.dataset.runtimeClear||""))})}function Ki(e){Ha(),v(document.getElementById("dismiss-notice"),"click",e.dismissNotice),v(document.getElementById("create-user"),"submit",n=>{n.preventDefault();const s=n.currentTarget;Ce(s,()=>e.createUser(s),e.showError)});const t=e.selectedUser();v(document.getElementById("selected-user"),"change",n=>{e.selectUser(n.currentTarget.value)}),v(document.getElementById("edit-user"),"submit",n=>{n.preventDefault();const s=n.currentTarget;t&&Ce(s,()=>e.updateSelectedUser(s,t),e.showError)}),v(document.getElementById("reset-password"),"submit",n=>{n.preventDefault();const s=n.currentTarget;t&&Ce(s,()=>e.resetSelectedUserPassword(s,t),e.showError)}),v(document.getElementById("delete-user"),"click",()=>{t&&e.deleteSelectedUser(t).catch(e.showError)}),v(document.getElementById("save-memberships"),"click",()=>{t&&Ce(document.getElementById("workspace-assignments"),()=>e.updateMemberships(t),e.showError)}),Yi(e),Zi(e),Xi(e),Qi(e),Gi({onClearAllRuntimeSessions:()=>{e.clearRuntimeSessionsFromPanel().catch(e.showError)},onClearRuntimeSession:n=>{n&&e.clearRuntimeSessionsFromPanel([n]).catch(e.showError)},onLogout:()=>{e.logoutFromSettings().catch(e.showError)},onHostedProviderRoutingChanged:e.onHostedProviderRoutingChanged,onActivateNativeProvider:n=>{e.activateNativeProviderFromPanel(n).catch(e.showError)},onSaveAgenticBinding:(n,s)=>{e.saveAgenticBindingFromPanel(n,s).catch(e.showError)},onRefreshProviderUsage:()=>{e.refreshProviderUsageFromPanel().catch(e.showError)},onSpeechAudioModelChanged:e.onSpeechAudioModelChanged,onSpeechConversationModelChanged:e.onSpeechConversationModelChanged,onSaveHostedProviderSettings:n=>{e.saveHostedProviderSettingsFromPanel(n).catch(e.showError)},onSaveSpeechProviderSettings:()=>{e.saveSpeechProviderSettingsFromPanel().catch(e.showError)}})}function Qi(e){v(document.getElementById("refresh-pwa-cache"),"click",()=>{e.cacheDiagnosticsController.ensureLoaded(!0).catch(e.showError)}),v(document.getElementById("clear-pwa-cache"),"click",()=>{e.cacheDiagnosticsController.clear().catch(e.showError)})}function Zi(e){document.querySelectorAll("[data-dependency-choice]").forEach(t=>{v(t,"change",()=>{const n=zt(t.dataset.dependencyChoice||"");if(!n)return;const s=e.appDependencies().find(i=>i.consumer_app_id===n.consumerAppId)?.dependencies.find(i=>i.alias===n.alias);if(!s)return;if(s.cardinality==="one"){e.saveDependencySelection(n.consumerAppId,n.alias,[n.providerAppId]).catch(e.showError);return}const a=new Set(s.selected_provider_app_ids);t.checked?a.add(n.providerAppId):a.delete(n.providerAppId),e.saveDependencySelection(n.consumerAppId,n.alias,Array.from(a)).catch(e.showError)})}),document.querySelectorAll("[data-dependency-save-default]").forEach(t=>{v(t,"click",()=>{const n=zt(t.dataset.dependencySaveDefault||"");n&&e.saveDependencySelection(n.consumerAppId,n.alias,[n.providerAppId]).catch(e.showError)})})}function zt(e){const[t,n,...s]=e.split(":"),a=s.join(":");return!t||!n||!a?null:{alias:n,consumerAppId:t,providerAppId:a}}function Yi(e){document.querySelectorAll("[data-app-toggle]").forEach(t=>{v(t,"change",()=>{const n=e.workspaceApps().find(s=>`${s.workspace_id}:${s.app_id}`===t.dataset.appToggle);n&&e.setWorkspaceAppStatus(n,t.checked).catch(e.showError)})}),document.querySelectorAll("[data-app-install]").forEach(t=>{v(t,"click",()=>{const n=e.workspaceApps().find(s=>`${s.workspace_id}:${s.app_id}`===t.dataset.appInstall);n&&e.installWorkspaceApp(n).catch(e.showError)})}),document.querySelectorAll("[data-app-uninstall]").forEach(t=>{v(t,"click",()=>{const n=e.workspaceApps().find(s=>`${s.workspace_id}:${s.app_id}`===t.dataset.appUninstall);n&&e.uninstallWorkspaceApp(n).catch(e.showError)})})}function Xi(e){document.querySelectorAll("[data-adapter-target]").forEach(t=>{v(t,"click",()=>{const n=t.dataset.adapterTarget;(n==="json"||n==="mongo")&&e.persistenceController.prepare(n).catch(e.showError)})}),v(document.getElementById("close-migration-modal"),"click",()=>{e.persistenceController.cancel()}),v(document.getElementById("cancel-migration"),"click",()=>{e.persistenceController.cancel()}),v(document.getElementById("validate-migration"),"click",()=>{e.persistenceController.validateDraft().catch(e.showError)}),document.querySelectorAll("[data-migration-field]").forEach(t=>{const n=s=>{const a=t.dataset.migrationField;if(a&&a in(e.persistenceController.viewState().targetDraft||{})){const i=!!e.persistenceController.viewState().migrationPlan;e.persistenceController.updateDraft(a,t.value,{render:s}),!s&&i&&xi()}};v(t,"input",()=>n(!1)),v(t,"change",()=>n(!0))}),v(document.getElementById("settings-delete-source"),"change",t=>{e.persistenceController.setDeleteSource(t.currentTarget.checked)}),v(document.getElementById("confirm-migration"),"click",()=>{e.persistenceController.apply().catch(e.showError)})}function xi(){const e=document.getElementById("confirm-migration");e&&(e.disabled=!0);const t=document.querySelector(".settings-migration-plan");if(!t)return;const n=t.querySelector(".material-symbols-rounded"),s=t.querySelector("strong"),a=t.querySelector("small");n&&(n.textContent="rule"),s&&(s.textContent="Dry run changed"),a&&(a.textContent="Validate the dry run again before applying migration."),t.querySelector(".settings-migration-collections")?.remove()}function eo(e){let t=null,n=null,s="",a=null,i=null,o=null,r=!1;function c(){return{deleteSourceAfterMigration:r,migrationPlan:a,migrationProgress:o,migrationResult:i,migrationTarget:t,persistence:e.getPersistence(),targetDraft:n}}async function l($){const b=e.getPersistence();if(!b||b.active_adapter.kind===$){m();return}t=$,n=to($,b),s="",a=null,r=!1,o=null,e.setNotice(null),e.render()}function u($,b,D={}){n&&(n={...n,[$]:b},a=null,s="",o=null,D.render!==!1&&e.render())}function p($){r=$,e.render()}function m(){t=null,n=null,a=null,s="",o=null,e.render()}async function S(){if(!(!n||!t)){o={target:t,phase:"validating",title:`Dry run to ${t.toUpperCase()}`,detail:"Validating target adapter and collection copy plan before applying changes."},e.setNotice(null),e.render();try{const $=ut(n);a=await qs($),s=Vt($)}catch($){throw o=null,a=null,s="",$}o=null,a.same_adapter&&e.setNotice({tone:"info",message:"The selected persistence adapter is already active."}),e.render()}}async function g(){if(!n||!t)return;const $=ut(n),b=Vt($);if(!a||s!==b){await S();return}if(a.same_adapter)return;o={target:t,phase:"applying",title:`Migration to ${t.toUpperCase()}`,detail:"Copying the validated control-plane plan to the target adapter."},e.setNotice(null),e.render();try{i=await Ls({...$,delete_source:r,restart_backend:!0})}catch(w){throw o={target:t,phase:"failed",title:"Migration failed",detail:w instanceof Error?w.message:"Unable to apply migration."},w}const D=t;t=null,n=null,a=null,s="",o={target:D,phase:"restarting",title:"Restart backend",detail:i.backend_restart?.detail||"Backend restart scheduled."},e.render(),await T(D)}async function T($){const b=Date.now(),D=9e4;for(;Date.now()-b<D;){o={target:$,phase:"polling",title:"Verifying cutover",detail:"Waiting for the backend to become healthy with the new adapter."},e.render();const w=await e.requestPersistenceStatusQuiet();if(w?.active_adapter.kind===$){e.setPersistence(w);const A=i?.source_cleanup?.scheduled===!0;o={target:$,phase:"complete",title:"Migration complete",detail:A?`Active adapter: ${$.toUpperCase()}. Source cleanup is scheduled after health check.`:`Active adapter: ${$.toUpperCase()}. Source storage was preserved.`},e.setNotice({tone:"success",message:`Migration to ${$.toUpperCase()} complete.`}),e.render();return}await new Promise(A=>window.setTimeout(A,1500))}o={target:$,phase:"failed",title:"Verification not completed",detail:"The backend did not confirm the new adapter before the timeout. Check service health and logs."},e.setNotice({tone:"error",message:"Migration not confirmed before the timeout."}),e.render()}return{apply:g,cancel:m,prepare:l,setDeleteSource:p,updateDraft:u,validateDraft:S,viewState:c}}function to(e,t){const n=t.active_adapter;return{kind:e,json_root:n.json_root||"data/control-plane/json",mongodb_uri:n.mongo_uri||"mongodb://127.0.0.1:27017/loopino",mongodb_database:n.mongo_database||"loopino",mongodb_username:n.mongo_username||"",mongodb_password_ref:n.mongo_password_ref||""}}function ut(e){return{kind:e.kind,json_root:e.json_root.trim()||"data/control-plane/json",mongodb_uri:e.mongodb_uri.trim(),mongodb_database:e.mongodb_database.trim()||"loopino",mongodb_username:e.mongodb_username?.trim()||void 0,mongodb_password_ref:e.mongodb_password_ref?.trim()||void 0}}function Vt(e){return JSON.stringify(ut(e))}async function no(e){const t=e.settings?.workspace.workspace_id,n=e.state.hostedDraftModelId,s=so(e.settings,e.state.hostedDraftModelId);if(!s||!e.state.hostedDraftModelId){e.state.hostedProviderErrorModelId=e.state.hostedDraftModelId,e.state.hostedProviderError="Hosted provider not loaded.",e.render();return}e.state.isSavingHostedProvider=!0,e.state.hostedProviderError="",e.state.hostedProviderErrorModelId=e.state.hostedDraftModelId,e.render();try{const a=await Cs({provider_id:s,model_id:e.state.hostedDraftModelId,openrouter_provider_routing:un(e.state,e.state.hostedDraftModelId)});if(e.getSettings()?.workspace.workspace_id!==t||!e.settings)return;const i={...e.getSettings(),provider:a};e.setSettings(i),re(e.state,i,{hostedModelId:n}),document.querySelectorAll("[data-hosted-model-accordion]").forEach(o=>{o.dataset.hostedModelAccordion===n&&W(o)}),e.setNotice({tone:"success",message:"Hosted model settings updated."})}catch(a){e.state.hostedProviderErrorModelId=e.state.hostedDraftModelId,e.state.hostedProviderError=a instanceof Error?a.message:"Unable to update hosted model settings."}finally{e.state.isSavingHostedProvider=!1,e.render()}}function so(e,t){const n=e?.provider.hosted_text||null;return[n?.active_provider,...n?.available_providers||[]].filter(Boolean).find(i=>!i||i.status!=="active"?!1:(i.model_options||[]).some(o=>o.model_id===t))?.provider_id||n?.active_provider?.provider_id||""}async function ao(e){const t=e.settings?.workspace.workspace_id,n=e.settings?.provider.speech_stt?.active_provider?.provider_id;if(!n||!e.state.speechAudioModelId||!e.state.speechConversationModelId){e.state.speechProviderError="Speech provider not loaded.",e.render();return}e.state.isSavingSpeechProvider=!0,e.state.speechProviderError="",e.render();try{const s=await As({provider_id:n,audio_transcription_model_id:e.state.speechAudioModelId,conversation_model_id:e.state.speechConversationModelId});if(e.getSettings()?.workspace.workspace_id!==t||!e.settings)return;const a={...e.getSettings(),provider:s};e.setSettings(a),re(e.state,a,{speech:!0}),W(".settings-speech-model-accordion"),e.setNotice({tone:"success",message:"Speech model settings updated."})}catch(s){e.state.speechProviderError=s instanceof Error?s.message:"Unable to update speech model settings."}finally{e.state.isSavingSpeechProvider=!1,e.render()}}function io(e){let t="",n=0,s=0;function a(){t="",n+=1,s+=1,e.state.providerUsageItems=[],e.state.providerUsageError="",e.state.isLoadingProviderUsage=!1,e.state.usageHistory=null,e.state.usageHistoryFilters=lt(),e.state.usageHistoryError="",e.state.isLoadingUsageHistory=!1}async function i(u=!1){const m=e.getSettings()?.workspace.workspace_id||"";if(!m){a();return}!u&&t===m||(t&&t!==m&&(e.state.usageHistoryFilters=lt()),t=m,await Promise.all([o(m),r(m)]))}async function o(u,p){const m=++n;e.state.providerUsageError="",e.state.isLoadingProviderUsage=!0,e.render();try{const S=await Ss();l(u)&&m===n&&(e.state.providerUsageItems=S.items)}catch(S){l(u)&&m===n&&(e.state.providerUsageError=S instanceof Error?S.message:"Provider usage unavailable")}finally{l(u)&&m===n&&(e.state.isLoadingProviderUsage=!1,e.render())}}async function r(u,p=!1){const m=++s,S=e.state.usageHistoryFilters,g=dn(S.timeRange),T={providerId:S.providerId,modelId:S.modelId};e.state.isLoadingUsageHistory=!0,e.state.usageHistoryError="",p&&(e.state.usageHistory=null),e.render();try{const $=await Es(g.resolution,g.periods,T);l(u)&&m===s&&(e.state.usageHistory=$)}catch($){l(u)&&m===s&&(e.state.usageHistoryError=$ instanceof Error?$.message:"Token usage history unavailable")}finally{l(u)&&m===s&&(e.state.isLoadingUsageHistory=!1,e.render())}}function c(u){const p=e.state.usageHistoryFilters,m=Ks(p,u);if(oo(p,m))return Promise.resolve();e.state.usageHistoryFilters=m;const S=p.providerId!==m.providerId||p.modelId!==m.modelId||p.timeRange!==m.timeRange,g=e.getSettings()?.workspace.workspace_id||"";return!S||!g?(e.render(),Promise.resolve()):r(g,!0)}function l(u){return e.getSettings()?.workspace.workspace_id===u}return{ensureLoaded:i,refresh:()=>i(!0),reset:a,updateUsageHistoryFilters:c}}function oo(e,t){return e.metric===t.metric&&e.providerId===t.providerId&&e.modelId===t.modelId&&e.timeRange===t.timeRange}function ro(e){return e?`<div class="settings-notice settings-notice-${e.tone}">
    <span class="material-symbols-rounded" aria-hidden="true">${e.tone==="error"?"error":e.tone==="success"?"task_alt":"info"}</span>
    <span>${d(e.message)}</span>
    <button type="button" class="settings-icon-button" id="dismiss-notice" aria-label="Close">
      <span class="material-symbols-rounded" aria-hidden="true">close</span>
    </button>
  </div>`:""}function lo(e){let t=0;return{reset:()=>{t++,e.state.pendingAgenticEnabled={},e.state.savingAgenticBindings.clear(),e.state.activatingNativeProviders.clear(),e.state.agenticBindingErrors={},e.state.nativeProviderErrors={}},activateProvider:async n=>{const s=t,a=e.getSettings()?.workspace.workspace_id;if(!e.state.activatingNativeProviders.has(n)){e.state.activatingNativeProviders.add(n),e.state.nativeProviderErrors[n]="",e.render();try{await Ps(n);const i=await ks("models");if(s!==t||e.getSettings()?.workspace.workspace_id!==a||i.workspace.workspace_id!==a)return;re(e.state,i),e.setSettings(i,"Connection enabled. Selected models are available in Chat.")}catch(i){if(s!==t)return;e.state.nativeProviderErrors[n]=i instanceof Error?i.message:"Unable to enable connection."}finally{s===t&&(e.state.activatingNativeProviders.delete(n),e.render())}}},save:async(n,s={})=>{const a=t,i=e.getSettings()?.workspace.workspace_id,o=n;if(e.state.savingAgenticBindings.has(o))return;const r=e.getSettings()?.agentic_admin?.items.find(g=>g.definition_id===n),c=Array.from(document.querySelectorAll("[data-agentic-binding-form]")).find(g=>g.dataset.agenticDefinitionId===n);if(!r||!c){e.state.agenticBindingErrors[o]="Agentic binding form is no longer available.",e.render();return}const l=g=>c.querySelector(`[data-agentic-field="${g}"]`),u=g=>!!l(g)?.checked,p=s.enabled??u("enabled");if(r.containment_status==="NO-GO"&&p){e.state.agenticBindingErrors[o]=`Remote agentic release is NO-GO: ${r.containment_reason||"contained by operator policy"}.`,e.render();return}if(p&&(r.execution_family===null||r.runtime_status!=="complete"||r.enable_eligible!==!0)){e.state.agenticBindingErrors[o]=`This model is unavailable: ${r.enable_blocked_reason||r.runtime_status_reason||r.blocked_reason||"runtime unavailable"}.`,e.render();return}const m=l("max_estimated_cost_usd")?.value.trim()||"",S=Math.round(Number(m)*1e6);if(m&&(!Number.isFinite(S)||S<0)){e.state.agenticBindingErrors[o]="Maximum cost must be a non-negative amount.",e.render();return}e.state.savingAgenticBindings.add(o),s.enabled!==void 0&&(e.state.pendingAgenticEnabled[o]=p),e.state.agenticBindingErrors[o]="",e.render();try{const g=await Is({definition_id:n,binding_id:r.binding?.binding_id||null,credential_binding_id:l("credential_binding_id")?.value||null,enabled:p,is_default:s.enabled===!1?!1:u("is_default"),actor_policy:{allow_workspace_admins:u("allow_workspace_admins"),allowed_user_ids:r.binding?.actor_policy.allowed_user_ids||[],allowed_workspace_role_ids:u("allow_workspace_members")?["member"]:[],allowed_agent_type_ids:r.binding?.actor_policy.allowed_agent_type_ids||[]},policy_patch:{max_estimated_cost_microusd:m?S:null,require_confirmation_for_mutating:u("require_confirmation_for_mutating"),require_confirmation_for_destructive:u("require_confirmation_for_destructive")}}),T=e.getSettings();if(a!==t||!T||T.workspace.workspace_id!==i||g.agentic_admin.workspace_id!==i)return;const $={...T,agentic_admin:g.agentic_admin};re(e.state,$),W(c),e.setSettings($,`${r.display_name} binding updated for new sessions.`)}catch(g){if(a!==t)return;e.state.agenticBindingErrors[o]=g instanceof Error?g.message:"Unable to save agentic binding."}finally{a===t&&(delete e.state.pendingAgenticEnabled[o],e.state.savingAgenticBindings.delete(o),e.render())}}}}function co(e){let t=null,n="",s=!1,a=!1,i=!1;async function o(l=!1){if(!(a||!l&&t)){a=!0,n="",e.render();try{if(t=await ss(),!t)throw new Error("Cache diagnostics are unavailable outside the Loopino shell.")}catch(u){n=Jt(u,"Unable to inspect this browser cache.")}finally{a=!1,e.render()}}}async function r(){if(s||i)return;i=!0;let l=!1;try{l=await bt({title:"Clear this browser cache?",detail:"Remove cached Loopino data and local file copies from this browser. Server files, conversations and settings are preserved.",confirmLabel:"Clear cache"})}finally{i=!1}if(l){s=!0,n="",e.render();try{const u=await as();if(!u)throw new Error("Cache cleanup is unavailable outside the Loopino shell.");const{cleanup:p}=u;if(p.status!=="complete"||p.pendingCleanupCount>0)throw new Error("Cache cleanup is still pending. Persistent cache reads remain blocked; retry Clear cache.");t=u.dashboard,e.setNotice({tone:"success",message:p.removed===1?"1 cached entry removed.":`${p.removed} cached entries removed.`})}catch(u){n=Jt(u,"Unable to clear this browser cache."),e.setNotice({tone:"error",message:n})}finally{s=!1,e.render()}}}function c(){return{dashboard:t,error:n,isClearing:s,isLoading:a}}return{clear:r,ensureLoaded:o,viewState:c}}function Jt(e,t){return e instanceof Error&&e.message?e.message:t}let He=null,Gt=null;const Cn=Qn();let J=[],Pe=[],ge="",Ue=[],le=[],Oe=null,C=null,gt=en()?.workspaceId||"",U=Aa();const An=Object.fromEntries(new URLSearchParams(window.location.search).entries());let z=Xt(An)||Dn,Y=Pn(An),x=!0,V=null,Kt="",Qt="";const G=rn();let xe="",Me="",Zt=!1;const $t=Ds({state:U.speechSynthesis,render:L,notify:e=>{V={tone:"success",message:e}}}),po=Ns({state:U.computerUse,getSettings:()=>C,render:L,setSelection:e=>{C&&(C={...C,computer_use:e})},notify:e=>{V={tone:"success",message:e}}}),Te=eo({getPersistence:()=>Oe,render:()=>L(),requestPersistenceStatusQuiet:Bs,setNotice:e=>{V=e},setPersistence:e=>{Oe=e}}),ae=vi({publishChanged:Ao,render:()=>L(),setNotice:e=>{V=e}}),We=io({getSettings:()=>C,render:()=>L(),state:U}),Ne=hi({render:L,updated:(e,t)=>{le=le.map(n=>n.workspace_id===e.workspace_id&&n.app_id===e.app_id?{...n,status:t?"enabled":"disabled"}:n),ae.invalidate(),N.ensure("apps",!0)}}),mt=lo({getSettings:()=>C,render:L,state:U,setSettings:(e,t)=>{C={...C,...e,runtime:C?.runtime||e.runtime,computer_use:C?.computer_use},V={tone:"success",message:t}}}),kt=co({render:L,setNotice:e=>{V=e}}),ce=da({render:L,workspaceId:()=>C?.workspace.workspace_id||""});function In(){return J.find(e=>e.user_id===Y)||J[0]}function Pn(e){const t=me(e.user_id)||me(e.selected_user_id)||me(e.id);if(t)return t;const n=me(e.app_page),s=/^users\/([^/?#]+)$/.exec(n);if(!s?.[1])return"";try{return decodeURIComponent(s[1])}catch{return s[1]}}function me(e){return typeof e=="string"?e.trim():""}function uo(e){const t=Xt(e),n=Pn(e),s=me(e.setting);Me=["default-model","voice","password","cache","computer-use"].includes(s)?s:"",t&&(z=t),n&&n!==Y&&(Y=n),N.cancelExcept(_t(z)),L(),Ve()}function go(e){e.id===Kt||window.parent===window||(Kt=e.id,window.parent.postMessage({type:"loopino.app.selection-changed",owner_app_id:"settings",selection:{page_id:e.id}},"*"))}function mo(e){!e||e.user_id===Qt||window.parent===window||(Qt=e.user_id,window.parent.postMessage({type:"loopino.app.selection-changed",owner_app_id:"settings",selection:{user_id:e.user_id}},"*"))}function ze(){window.parent!==window&&window.parent.postMessage({type:"loopino.app.data-changed",owner_app_id:"settings",resource:"users"},"*")}const N=Fs({publish:(e,t)=>{if(e==="registry"){const n=t;Pe=n.items,ge=n.workspace_id||C?.workspace.workspace_id||""}else if(e==="users")J=t.items,(!Y||!J.some(n=>n.user_id===Y))&&(Y=J[0]?.user_id||"");else if(e==="workspaces")Ue=t.items;else if(e==="apps")le=t.items;else if(e==="persistence")Oe=t;else if(e==="sessions")C?C=ct(C,t):Ae=t;else{const n=t,s=gt;s&&s!==n.workspace.workspace_id&&(He?.unmountUsageVisualizations(),N.reset(),ms(),C=null,J=[],Ue=[],le=[],Oe=null,Ae=null,Pe=[],ge="",U.savedDrafts=null,ae.reset(),ce.reset(),We.reset(),$t.reset(),mt.reset(),Ne.reset(),V=null,Object.assign(G,rn()),queueMicrotask(()=>{L(),Ve()})),Pe.length&&!ge&&(ge=n.workspace.workspace_id),gt=n.workspace.workspace_id;const a=e==="models"||e==="voice";C=Ws(C,n,e),Ae&&(C=ct(C,Ae)),(a||e==="computer-use")&&re(U,C)}},changed:()=>L()});let Ae=null;async function Ve(e=!1){const t=z;t==="workspace-apps"&&N.ensure("registry",e),await Promise.all(_t(t).map(n=>N.ensure(n,e))),z===t&&(t==="app-links"&&N.state("apps").loaded&&N.state("context").loaded&&await Mn(e),t==="usage"&&C&&(We.ensureLoaded(e),Gt||=Nn(()=>import("./usageVisualizations-DmZ4oN5T.js"),__vite__mapDeps([0,1])).then(n=>{He=n,z==="usage"&&L()}).catch(n=>{Gt=null,z==="usage"&&Be(n)})),t==="voice"&&C&&$t.load(C.workspace.workspace_id,e),t==="learning"&&C&&(ce.load(e),N.ensure("models")),t==="cache"&&kt.ensureLoaded(e))}async function fo(){await Ve(!0)}async function Mn(e=!1){await ae.ensureLoaded(C?.workspace.workspace_id||"",le,e)}async function vo(e){const t=new FormData(e),n=await ma({username:String(t.get("username")||""),password:String(t.get("password")||""),display_name:String(t.get("display_name")||""),email:String(t.get("email")||""),platform_role:String(t.get("platform_role")||"member")});J=[...J,n],Y=n.user_id,e.reset(),W(e),V={tone:"success",message:"User created."},L(),ze()}async function ho(e,t){const n=new FormData(e),s=await fa(t.user_id,{display_name:String(n.get("display_name")||""),email:String(n.get("email")||""),platform_role:String(n.get("platform_role")||"member"),account_type:String(n.get("account_type")||"standard"),is_active:n.get("is_active")==="on"});J=J.map(a=>a.user_id===s.user_id?s:a),W(e),V={tone:"success",message:"User updated."},L(),ze()}async function _o(e,t){const n=new FormData(e),s=String(n.get("password")||""),a=String(n.get("password_confirmation")||"");if(s!==a)throw new Error("Passwords do not match");await va(t.user_id,s),e.reset(),W(e),V={tone:"success",message:"Password updated."},L()}async function bo(e){const t=e.display_name||e.username;await bt({title:`Delete ${t}?`,detail:"This permanently removes the user account and its workspace memberships. This action cannot be undone.",confirmLabel:"Delete user"})&&(await ha(e.user_id),Y="",V={tone:"success",message:`${t} deleted.`},J=J.filter(n=>n.user_id!==e.user_id),Y=J[0]?.user_id||"",L(),ze())}async function yo(e){const t=Ue.map(s=>{const a=document.querySelector(`[data-workspace-enabled="${s.workspace_id}"]`),i=document.querySelector(`[data-workspace-role="${s.workspace_id}"]`);return a?.checked?{workspace_id:s.workspace_id,role:i?.value||"member"}:null}).filter(s=>!!s),n=await _a(e.user_id,t);J=J.map(s=>s.user_id===n.user_id?n:s),W(".settings-memberships"),V={tone:"success",message:"Workspace access updated."},L(),ze()}async function wo(e){await ba(e),ae.invalidate(),await N.ensure("apps",!0)}async function $o(e,t){await Ne.setEnabled(e,t)}async function ko(e){await wa(e),ae.invalidate(),await N.ensure("apps",!0)}async function So(e,t,n){await ae.saveDependencySelection(e,t,n)}async function Eo(e){if(!C)return;const t=C.workspace.workspace_id,n=yt(C,G),s=e?.length?n.filter(r=>e.includes(r.session_id)):n;if(!s.length)return;const a=G.scope==="server"?"the entire server":`workspace ${C.workspace.name}`,i=s.filter(r=>!["closed","completed","failed","terminated","stopped"].includes(r.status)).length;if(!await bt({title:`Delete ${s.length} runtime session${s.length===1?"":"s"}?`,detail:`Scope: ${a}. ${i} sessions may have active agents. Their agents will stop and their conversations, turns and runtime files will be permanently removed.`,confirmLabel:"Delete sessions"})||C.workspace.workspace_id!==t)return;const o=s.map(r=>r.session_id);U.cleanupError="",U.clearingAllRuntime=!e?.length,o.forEach(r=>U.cleaningSessionIds.add(r)),L();try{const r=await Ms(o);if(C.workspace.workspace_id!==t)return;Co(r),C=ct(C,r),V={tone:"success",message:`${r.cleared_sessions} runtime sessions deleted.`}}catch(r){U.cleanupError=r instanceof Error?r.message:"Unable to delete runtime sessions."}finally{o.forEach(r=>U.cleaningSessionIds.delete(r)),U.clearingAllRuntime=!1,L()}}function Co(e){e.deleted_threads<=0||window.parent===window||(window.parent.postMessage({type:"loopino.app.data-changed",owner_app_id:"chat",resource:"threads"},"*"),e.deleted_thread_ids.forEach(t=>{window.parent.postMessage({type:"loopino.app.data-changed",owner_app_id:"chat",resource:"threads",deleted_thread_id:t},"*")}))}function Ao(e,t){window.parent!==window&&window.parent.postMessage({type:"loopino.app.dependencies-changed",app_id:e,status:t.status},"*")}async function Io(){if(window.parent&&window.parent!==window){window.parent.postMessage({type:"loopino.shell.logout"},"*");return}await Ts(),window.location.href="/"}function Po(){return Ya(C,U,z)}function L(){const e=document.getElementById("app");if(!e)return;Zt||(fs(e),Zt=!0);const t=performance.now(),n=Rn(z),s=_t(z);x=s.some(l=>!N.state(l).loaded&&!N.state(l).error);const a=s.filter(l=>N.state(l).error&&!N.state(l).loaded),i=s.filter(l=>N.state(l).error&&N.state(l).loaded),o=In();xe==="usage"&&(z!=="usage"||x||a.length)&&He?.unmountUsageVisualizations();const r=xe!==z;xe=z;const c=x?si(n):a.length?a.map(l=>`<section class="settings-card"><h2>Unable to load ${d(l)}</h2><p role="alert">${d(N.state(l).error)}</p><button type="button" data-retry-resource="${l}">Retry</button></section>`).join(""):Ji({appLinksController:ae,cacheDiagnosticsController:kt,page:n,persistenceController:Te,platformSettingsHtml:Po,sessionsHtml:()=>C?Js(C,U,G):"",usageHtml:()=>ta(U),learningHtml:()=>ua(ce.viewState(),C?.provider.available_providers?.find(l=>l.provider_id==="codex")?.model_options||[]),selectedUser:o,users:J,workspaceApps:Ne.apps(le).map(l=>({...l,logo:l.workspace_id===ge&&Pe.find(u=>u.app_id===l.app_id)?.logo||null})),savingAppKeys:Ne.savingKeys(),workspaces:Ue});if(vs(e,`<main class="settings-shell"><section class="settings-main"><div class="settings-content" data-render-key="${d(Hn(gt,n.id,o?.user_id))}">
    <header class="detail-header"><div class="detail-title-block"><h2>${d(n.title)}</h2><span class="detail-title-separator" aria-hidden="true"></span><p>${d(n.summary)}</p></div>
    ${C?`<div class="settings-context"><span>${d(C.workspace.name)}</span><span>${d(C.user.display_name||C.user.username)}</span><button type="button" id="settings-logout" class="settings-secondary">Logout</button></div>`:""}</header>
    ${ro(V)}${i.map(l=>`<p role="alert">${d(N.state(l).error)} <button type="button" data-retry-resource="${l}">Retry</button></p>`).join("")}${c}
    </div></section>${Di(Te.viewState())}</main>`),Mo(),Cn.attach(z==="installation"&&Le()?document.getElementById("installation-root"):null),zs(Te.cancel),ce.setVisible(z==="learning"&&Le()&&!x),z==="usage"&&!x&&!a.length&&He?.mountUsageVisualizations({history:U.usageHistory,filters:U.usageHistoryFilters,isLoading:U.isLoadingUsageHistory,onFiltersChange:We.updateUsageHistoryFilters,settings:C}),r&&document.querySelector(".settings-main")?.scrollTo?.(0,0),go(n),!x&&["users","workspace-access"].includes(z)&&mo(o),Me&&!x){const l={"default-model":"[data-agentic-model-toggle]",voice:"#settings-tts-engine",password:"#reset-password input",cache:"#clear-pwa-cache","computer-use":"#settings-computer-use-mode"},u=document.querySelector(l[Me]);u&&(u.closest("details")?.setAttribute("open",""),u.focus(),u.scrollIntoView?.({block:"center"}),Me="")}performance.clearMeasures("settings.render"),performance.measure("settings.render",{start:t,end:performance.now()})}function Mo(){_s(),document.querySelectorAll("[data-user-discard]").forEach(e=>v(e,"click",()=>{const t=e.closest("form, #workspace-assignments");t&&(t instanceof HTMLFormElement&&t.reset(),W(t),L())})),document.querySelectorAll("[data-speech-discard]").forEach(e=>v(e,"click",()=>{re(U,C,{speech:!0}),W(".settings-speech-model-accordion"),L()})),document.querySelectorAll("[data-hosted-discard]").forEach(e=>v(e,"click",()=>{re(U,C,{hostedModelId:e.dataset.hostedDiscard}),W("[data-hosted-model-accordion]"),L()})),v(document.getElementById("settings-refresh-app-links"),"click",()=>{Mn(!0)}),document.querySelectorAll("[data-retry-resource]").forEach(e=>v(e,"click",()=>{N.ensure(e.dataset.retryResource,!0).then(()=>Ve())})),v(document.getElementById("settings-session-search"),"input",e=>{G.query=e.target.value,G.page=0,L()}),v(document.getElementById("settings-session-status"),"change",e=>{G.status=e.target.value,G.page=0,L()}),v(document.getElementById("settings-session-scope"),"change",e=>{G.scope=e.target.value==="server"?"server":"workspace",G.page=0,G.status="",W(".settings-session-filters"),L()}),v(document.getElementById("settings-sessions-prev"),"click",()=>{G.page-=1,L()}),v(document.getElementById("settings-sessions-next"),"click",()=>{G.page+=1,L()}),v(document.getElementById("create-workspace"),"submit",e=>{e.preventDefault();const t=e.target;R("/api/workspaces",{method:"POST",body:JSON.stringify(Object.fromEntries(new FormData(t)))}).then(async()=>{t.reset(),W("#create-workspace"),await N.ensure("workspaces",!0),await N.ensure("apps",!0),V={tone:"success",message:"Workspace created."},L()}).catch(Be)}),$t.bind(),ce.bind(),po.bind(),Ki({clearRuntimeSessionsFromPanel:Eo,cacheDiagnosticsController:kt,createUser:vo,deleteSelectedUser:bo,dismissNotice:()=>{V=null,L()},installWorkspaceApp:wo,logoutFromSettings:Io,onHostedProviderRoutingChanged:(e,t,n)=>{Ta(U,C,e,t,n),L()},saveAgenticBindingFromPanel:mt.save,activateNativeProviderFromPanel:mt.activateProvider,onSpeechAudioModelChanged:e=>{Pa(U,e),L()},onSpeechConversationModelChanged:e=>{Ma(U,e),L()},persistenceController:Te,refreshProviderUsageFromPanel:We.refresh,render:L,resetSelectedUserPassword:_o,saveDependencySelection:So,saveHostedProviderSettingsFromPanel:e=>(e&&Ia(U,C,e),no(Yt())),saveSpeechProviderSettingsFromPanel:()=>ao(Yt()),selectedUser:In,selectUser:e=>{Y=e,L()},setWorkspaceAppStatus:$o,showError:Be,uninstallWorkspaceApp:ko,updateMemberships:yo,updateSelectedUser:ho,workspaceApps:()=>le,appDependencies:()=>ae.viewState().dependencies})}function Yt(){return{render:L,setNotice:e=>{V=e},setSettings:e=>{C=e},settings:C,getSettings:()=>C,state:U}}function Be(e){V={tone:"error",message:e instanceof Error?e.message:"Unexpected error"},L()}ga({navigate:uo,visibilityChanged:e=>{ce.setVisible(z==="learning"&&e&&!x),Cn.attach(e&&z==="installation"?document.getElementById("installation-root"):null)}});fo().catch(Be);export{ln as U,Do as a,rt as b,Lo as c,qo as d,dn as u};
