(function(){const a=document.createElement("link").relList;if(a&&a.supports&&a.supports("modulepreload"))return;for(const s of document.querySelectorAll('link[rel="modulepreload"]'))n(s);new MutationObserver(s=>{for(const i of s)if(i.type==="childList")for(const u of i.addedNodes)u.tagName==="LINK"&&u.rel==="modulepreload"&&n(u)}).observe(document,{childList:!0,subtree:!0});function t(s){const i={};return s.integrity&&(i.integrity=s.integrity),s.referrerPolicy&&(i.referrerPolicy=s.referrerPolicy),s.crossOrigin==="use-credentials"?i.credentials="include":s.crossOrigin==="anonymous"?i.credentials="omit":i.credentials="same-origin",i}function n(s){if(s.ep)return;s.ep=!0;const i=t(s);fetch(s.href,i)}})();let y=[],_=[],v=[],l=null,b=null,r=null,h="",w="",m=null,d=null;async function c(e,a={}){const t=await fetch(e,{credentials:"same-origin",headers:{"Content-Type":"application/json",...a.headers||{}},...a}),n=await t.json();if(!t.ok)throw new Error(n.detail||n.error||`Request failed ${t.status}`);return n}function k(){return y.find(e=>e.user_id===h)||y[0]}function E(e,a){return e.memberships.find(t=>t.workspace_id===a)}async function S(){try{return await c("/api/admin/persistence")}catch(e){return d={tone:"error",message:e instanceof Error?e.message:"Persistence API unavailable"},null}}async function C(){try{return await c("/api/admin/persistence")}catch{return null}}async function g(){const[e,a,t,n]=await Promise.all([c("/api/admin/users"),c("/api/admin/workspaces"),c("/api/admin/workspace-apps"),S()]);y=e.items,_=a.items,v=t.items,l=n,(!h||!y.some(s=>s.user_id===h))&&(h=y[0]?.user_id||""),o()}async function P(e){const a=new FormData(e),t={username:String(a.get("username")||""),password:String(a.get("password")||""),display_name:String(a.get("display_name")||""),email:String(a.get("email")||""),platform_role:String(a.get("platform_role")||"member")};h=(await c("/api/admin/users",{method:"POST",body:JSON.stringify(t)})).user_id,e.reset(),await g()}async function I(e,a){const t=new FormData(e);await c(`/api/admin/users/${encodeURIComponent(a.user_id)}`,{method:"PATCH",body:JSON.stringify({display_name:String(t.get("display_name")||""),email:String(t.get("email")||""),platform_role:String(t.get("platform_role")||"member"),account_type:String(t.get("account_type")||"standard"),is_active:t.get("is_active")==="on"})}),await g()}async function U(e,a){const t=new FormData(e),n=String(t.get("password")||""),s=String(t.get("password_confirmation")||"");if(n!==s)throw new Error("Passwords do not match");await c(`/api/admin/users/${encodeURIComponent(a.user_id)}/password`,{method:"POST",body:JSON.stringify({password:n})}),e.reset(),d={tone:"success",message:"Password updated."},o()}async function A(e){const a=e.display_name||e.username;if(w!==e.user_id){w=e.user_id,d={tone:"info",message:`Press Delete user again to confirm permanent removal of ${a}.`},o();return}await c(`/api/admin/users/${encodeURIComponent(e.user_id)}`,{method:"DELETE"}),h="",w="",d={tone:"success",message:`${a} deleted.`},await g()}async function L(e){const a=_.map(t=>{const n=document.querySelector(`[data-workspace-enabled="${t.workspace_id}"]`),s=document.querySelector(`[data-workspace-role="${t.workspace_id}"]`);return n?.checked?{workspace_id:t.workspace_id,role:s?.value||"member"}:null}).filter(Boolean);await c(`/api/admin/users/${encodeURIComponent(e.user_id)}/workspaces`,{method:"PUT",body:JSON.stringify({memberships:a})}),await g()}async function M(e){await c(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"POST",body:JSON.stringify({source_id:e.source_id,enabled:!0})}),await g()}async function T(e,a){await c(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"PATCH",body:JSON.stringify({status:a?"enabled":"disabled"})}),await g()}async function O(e){await c(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"DELETE",body:JSON.stringify({})}),await g()}function q(e){return{kind:e,json_root:"data/control-plane/json",mongodb_uri:l?.active_adapter.mongo_uri||"mongodb://127.0.0.1:27017/maverick",mongodb_database:l?.active_adapter.mongo_database||"maverick",delete_source:!0,restart_backend:!0}}async function N(e){if(!l||l.active_adapter.kind===e){m=null,o();return}r={target:e,phase:"applying",percent:18,title:`Migration to ${e.toUpperCase()}`,detail:"Copying the control plane to the target adapter."},d=null,o(),b=await c("/api/admin/persistence/migrations/apply",{method:"POST",body:JSON.stringify(q(e))}),m=null,r={target:e,phase:"restarting",percent:68,title:"Restart backend",detail:b.backend_restart?.detail||"Backend restart scheduled."},o(),await j(e)}async function j(e){const a=Date.now(),t=9e4;for(;Date.now()-a<t;){r={target:e,phase:"polling",percent:84,title:"Verifying cutover",detail:"Waiting for the backend to become healthy with the new adapter."},o();const n=await C();if(n?.active_adapter.kind===e){l=n,r={target:e,phase:"complete",percent:100,title:"Migration complete",detail:`Active adapter: ${e.toUpperCase()}. Old storage cleanup started after health check.`},d={tone:"success",message:`Migration to ${e.toUpperCase()} complete.`},o();return}await new Promise(s=>window.setTimeout(s,1500))}r={target:e,phase:"failed",percent:100,title:"Verification not completed",detail:"The backend did not confirm the new adapter before the timeout. Check service health and logs."},d={tone:"error",message:"Migration not confirmed before the timeout."},o()}function D(){return y.map(e=>{const a=e.user_id===k()?.user_id?"is-active":"",t=e.platform_role==="admin"?"Admin":"Member";return`<button class="ua-user ${a}" data-user-id="${e.user_id}">
        <span class="ua-user-icon material-symbols-rounded" aria-hidden="true">account_circle</span>
        <span class="ua-user-copy">
          <strong>${e.display_name||e.username}</strong>
          <span>${t} · ${e.memberships.length} workspace</span>
        </span>
      </button>`}).join("")}function R(e){return _.map(a=>{const t=E(e,a.workspace_id);return`<label class="ua-membership">
        <input type="checkbox" data-workspace-enabled="${a.workspace_id}" ${t?"checked":""} />
        <span class="ua-membership-icon material-symbols-rounded" aria-hidden="true">workspaces</span>
        <span>
          <strong>${a.name}</strong>
          <small>${a.workspace_id}</small>
        </span>
        <select data-workspace-role="${a.workspace_id}">
          <option value="member" ${t?.role!=="admin"?"selected":""}>Member</option>
          <option value="admin" ${t?.role==="admin"?"selected":""}>Workspace admin</option>
        </select>
      </label>`}).join("")}function B(){return _.map(e=>{const a=v.filter(s=>s.workspace_id===e.workspace_id),t=a.filter(s=>s.status==="enabled").length,n=a.filter(s=>s.installed).length;return`<details class="ua-app-workspace">
        <summary class="ua-app-workspace-heading">
          <span class="ua-summary-caret material-symbols-rounded" aria-hidden="true">chevron_right</span>
          <span class="ua-app-workspace-icon material-symbols-rounded" aria-hidden="true">deployed_code</span>
          <span>
            <strong>${e.name}</strong>
            <small>${e.workspace_id} · ${t}/${n} enabled</small>
          </span>
        </summary>
        <div class="ua-apps">
          ${a.map(s=>{const i=s.status==="enabled",u=s.installed,f=u?s.status:"not installed";return`<div class="ua-app-row">
                <span class="ua-app-icon material-symbols-rounded" aria-hidden="true">${i?"apps":"hide_source"}</span>
                <span class="ua-app-copy">
                  <strong>${s.name}</strong>
                  <small>${s.app_id} · v${s.version} · ${f}</small>
                </span>
                ${u?`<label class="ua-switch">
                      <input type="checkbox" data-app-toggle="${e.workspace_id}:${s.app_id}" ${i?"checked":""} />
                      <span>Enabled</span>
                    </label>
                    <button type="button" class="ua-secondary" data-app-uninstall="${e.workspace_id}:${s.app_id}">
                      <span class="material-symbols-rounded" aria-hidden="true">link_off</span>
                      Uninstall
                    </button>`:`<button type="button" class="ua-secondary" data-app-install="${e.workspace_id}:${s.app_id}">
                      <span class="material-symbols-rounded" aria-hidden="true">add_link</span>
                      Install
                    </button>`}
              </div>`}).join("")}
        </div>
      </details>`}).join("")}function J(){if(!l)return`<section class="ua-card ua-persistence">
      <div class="ua-heading">
        <div>
          <p class="ua-kicker">Persistence</p>
          <h2>Control plane adapter</h2>
        </div>
        <span class="ua-pill ua-pill-muted">offline</span>
      </div>
      <p class="ua-card-copy">The core persistence surfaces are not available in the active backend.</p>
    </section>`;const e=l.active_adapter,a=l.collections.reduce((f,$)=>f+$.count,0),t=r?`<div class="ua-migration-progress ${r.phase==="failed"?"is-failed":""} ${r.phase==="complete"?"is-complete":""}">
        <div class="ua-migration-progress-heading">
          <span class="material-symbols-rounded" aria-hidden="true">${r.phase==="complete"?"check_circle":r.phase==="failed"?"error":"sync"}</span>
          <span>
            <strong>${r.title}</strong>
            <small>${r.detail}</small>
          </span>
          <em>${r.percent}%</em>
        </div>
        <div class="ua-progress-track" aria-label="Progresso migrazione" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${r.percent}">
          <span style="width: ${r.percent}%"></span>
        </div>
      </div>`:"",n=b?`<div class="ua-migration-result">
        <span class="material-symbols-rounded" aria-hidden="true">task_alt</span>
        <span>
          <strong>Ultima migrazione</strong>
          <small>${b.collections.reduce((f,$)=>f+$.count,0)} documents · target ${b.target_adapter.kind} · cleanup ${b.source_cleanup?.scheduled?"scheduled":"not requested"}</small>
        </span>
      </div>`:"",s=e.kind==="json",i=e.kind==="mongo",u=r&&r.phase!=="complete"&&r.phase!=="failed";return`<section class="ua-card ua-persistence">
    <div class="ua-heading">
      <div>
        <p class="ua-kicker">Persistence</p>
        <h2>Control plane adapter</h2>
      </div>
      <span class="ua-pill">${a} documents</span>
    </div>
    <div class="ua-adapter-cards">
      <button type="button" class="ua-adapter-card ${s?"is-active":""}" ${s||u?"disabled":'data-adapter-target="json"'}>
        <span class="ua-adapter-card-icon material-symbols-rounded" aria-hidden="true">${s?"check_circle":"database"}</span>
        <span>
          <strong>JSON</strong>
          <small>${s?e.json_root:"data/control-plane/json"}</small>
        </span>
        <em>${s?"Current":"Migrate here"}</em>
      </button>
      <button type="button" class="ua-adapter-card ${i?"is-active":""}" ${i||u?"disabled":'data-adapter-target="mongo"'}>
        <span class="ua-adapter-card-icon material-symbols-rounded" aria-hidden="true">${i?"check_circle":"database"}</span>
        <span>
          <strong>Mongo</strong>
          <small>${i?e.mongo_database:"mongodb://127.0.0.1:27017/maverick"}</small>
        </span>
        <em>${i?"Current":"Migrate here"}</em>
      </button>
    </div>
    ${t}
    ${n}
  </section>`}function H(){if(!m||!l)return"";const e=l.active_adapter.kind.toUpperCase(),a=m.toUpperCase();return`<div class="ua-modal-backdrop" role="presentation">
    <section class="ua-modal" role="dialog" aria-modal="true" aria-labelledby="adapter-migration-title">
      <div class="ua-heading">
        <div>
          <p class="ua-kicker">Confirm migration</p>
          <h2 id="adapter-migration-title">${e} → ${a}</h2>
        </div>
        <button type="button" class="ua-icon-button" id="close-migration-modal" aria-label="Close">
          <span class="material-symbols-rounded" aria-hidden="true">close</span>
        </button>
      </div>
      <p class="ua-card-copy">The migration copies the entire control plane to the new adapter, updates the backend configuration, restarts the core, and deletes the old storage only after the new backend responds healthy.</p>
      <div class="ua-modal-actions">
        <button type="button" class="ua-secondary" id="cancel-migration">Cancel</button>
        <button type="button" class="ua-danger" id="confirm-migration" ${r&&r.phase!=="complete"&&r.phase!=="failed"?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">sync_alt</span>
          Migrate and delete
        </button>
      </div>
    </section>
  </div>`}function o(){const e=document.getElementById("app"),a=k();e&&(e.innerHTML=`<section class="ua-shell">
    <aside class="ua-rail">
      <div>
        <p class="ua-kicker">Maverick</p>
        <h1>User Admin</h1>
        <p class="ua-copy">Manage users, platform roles, and workspace access.</p>
      </div>
      <div class="ua-users">${D()}</div>
    </aside>
    <section class="ua-main">
      <div class="ua-content">
        ${W()}
        <form class="ua-card ua-create" id="create-user">
          <div>
            <p class="ua-kicker">New user</p>
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
        ${J()}
        ${a?`<div class="ua-profile-row">
            <form class="ua-card ua-detail" id="edit-user">
            <div class="ua-heading">
              <div>
                <p class="ua-kicker">Selected user</p>
                <h2>${a.display_name||a.username}</h2>
              </div>
              <span class="ua-pill">${a.is_active?"active":"disabled"}</span>
            </div>
            <div class="ua-grid">
              <label>Name<input name="display_name" value="${a.display_name||""}" /></label>
              <label>Email<input name="email" type="email" value="${a.email||""}" /></label>
              <label>Platform role<select name="platform_role">
                <option value="member" ${a.platform_role==="member"?"selected":""}>Member</option>
                <option value="admin" ${a.platform_role==="admin"?"selected":""}>Admin</option>
              </select></label>
              <label>Account type<select name="account_type">
                <option value="standard" ${a.account_type==="standard"?"selected":""}>Standard</option>
                <option value="facilitated" ${a.account_type==="facilitated"?"selected":""}>Facilitated</option>
              </select></label>
            </div>
            <label class="ua-toggle"><input name="is_active" type="checkbox" ${a.is_active?"checked":""} /> Account active</label>
            <button type="submit">
              <span class="material-symbols-rounded" aria-hidden="true">save</span>
              Save user
            </button>
          </form>
          <form class="ua-card ua-password" id="reset-password">
            <div class="ua-heading">
              <div>
                <p class="ua-kicker">Password</p>
                <h2>Reset access</h2>
              </div>
              <span class="ua-password-icon material-symbols-rounded" aria-hidden="true">key</span>
            </div>
            <p class="ua-card-copy">Imposta una nuova temporary password per l'utente selezionato.</p>
            <div class="ua-password-grid">
              <label>New password<input name="password" type="password" minlength="8" autocomplete="new-password" required /></label>
              <label>Confirm password<input name="password_confirmation" type="password" minlength="8" autocomplete="new-password" required /></label>
            </div>
            <button type="submit" class="ua-secondary">
              <span class="material-symbols-rounded" aria-hidden="true">password</span>
              Update password
            </button>
            <button type="button" class="ua-danger" id="delete-user">
              <span class="material-symbols-rounded" aria-hidden="true">person_remove</span>
              ${w===a.user_id?"Confirm delete":"Delete user"}
            </button>
          </form>
          </div>
          <section class="ua-card">
            <div class="ua-heading">
              <div>
                <p class="ua-kicker">Workspace</p>
                <h2>Assignments</h2>
              </div>
              <button type="button" id="save-memberships">
                <span class="material-symbols-rounded" aria-hidden="true">admin_panel_settings</span>
                Save access
              </button>
            </div>
            <div class="ua-memberships">${R(a)}</div>
          </section>
          <details class="ua-card ua-collapsible" open>
            <summary class="ua-heading ua-collapsible-heading">
              <div>
                <p class="ua-kicker">Workspace apps</p>
                <h2>Installation and visibility</h2>
              </div>
              <span class="ua-summary-caret material-symbols-rounded" aria-hidden="true">chevron_right</span>
            </summary>
            <p class="ua-card-copy">Installta significa montata nel workspace. Solo le app enabled sono visibili agli utenti e servite dal core.</p>
            <div class="ua-app-workspaces">${B()}</div>
          </details>`:'<section class="ua-card"><h2>No users</h2></section>'}
      </div>
    </section>
    ${H()}
  </section>`,F())}function F(){document.getElementById("dismiss-notice")?.addEventListener("click",()=>{d=null,o()}),document.querySelectorAll("[data-user-id]").forEach(a=>{a.addEventListener("click",()=>{h=a.dataset.userId||"",w="",o()})}),document.getElementById("create-user")?.addEventListener("submit",a=>{a.preventDefault(),P(a.currentTarget).catch(p)});const e=k();document.getElementById("edit-user")?.addEventListener("submit",a=>{a.preventDefault(),e&&I(a.currentTarget,e).catch(p)}),document.getElementById("reset-password")?.addEventListener("submit",a=>{a.preventDefault(),e&&U(a.currentTarget,e).catch(p)}),document.getElementById("delete-user")?.addEventListener("click",()=>{e&&A(e).catch(p)}),document.getElementById("save-memberships")?.addEventListener("click",()=>{e&&L(e).catch(p)}),document.querySelectorAll("[data-app-toggle]").forEach(a=>{a.addEventListener("change",()=>{const t=v.find(n=>`${n.workspace_id}:${n.app_id}`===a.dataset.appToggle);t&&T(t,a.checked).catch(p)})}),document.querySelectorAll("[data-app-install]").forEach(a=>{a.addEventListener("click",()=>{const t=v.find(n=>`${n.workspace_id}:${n.app_id}`===a.dataset.appInstall);t&&M(t).catch(p)})}),document.querySelectorAll("[data-app-uninstall]").forEach(a=>{a.addEventListener("click",()=>{const t=v.find(n=>`${n.workspace_id}:${n.app_id}`===a.dataset.appUninstall);t&&O(t).catch(p)})}),document.querySelectorAll("[data-adapter-target]").forEach(a=>{a.addEventListener("click",()=>{const t=a.dataset.adapterTarget;(t==="json"||t==="mongo")&&(m=t,o())})}),document.getElementById("close-migration-modal")?.addEventListener("click",()=>{m=null,o()}),document.getElementById("cancel-migration")?.addEventListener("click",()=>{m=null,o()}),document.getElementById("confirm-migration")?.addEventListener("click",()=>{m&&N(m).catch(p)})}function p(e){d={tone:"error",message:e instanceof Error?e.message:"Unexpected error"},o()}function W(){return d?`<div class="ua-notice ua-notice-${d.tone}">
    <span class="material-symbols-rounded" aria-hidden="true">${d.tone==="error"?"error":d.tone==="success"?"task_alt":"info"}</span>
    <span>${d.message}</span>
    <button type="button" class="ua-icon-button" id="dismiss-notice" aria-label="Close">
      <span class="material-symbols-rounded" aria-hidden="true">close</span>
    </button>
  </div>`:""}g().catch(p);
