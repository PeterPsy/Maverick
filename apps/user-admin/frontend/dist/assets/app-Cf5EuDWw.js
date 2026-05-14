import{l as C,a as I,b as A,r as l}from"./adminApi-BbgnavI7.js";let m=[],_=[],w=[],d=null,b=null,r=null,h=U(Object.fromEntries(new URLSearchParams(window.location.search).entries())),f="",p=null,o=null,E="";function P(){return m.find(e=>e.user_id===h)||m[0]}function M(e,a){return e.memberships.find(t=>t.workspace_id===a)}function U(e){const a=k(e.user_id)||k(e.selected_user_id)||k(e.id);if(a)return a;const t=k(e.app_page),s=/^users\/([^/?#]+)$/.exec(t);if(!s?.[1])return"";try{return decodeURIComponent(s[1])}catch{return s[1]}}function k(e){return typeof e=="string"?e.trim():""}function T(e){const a=U(e);a&&(h=a,f="",m.length&&i())}function L(e){!e||e.user_id===E||window.parent===window||(E=e.user_id,window.parent.postMessage({type:"maverick.app.selection-changed",owner_app_id:"user-admin",selection:{user_id:e.user_id}},window.location.origin))}function $(){window.parent!==window&&window.parent.postMessage({type:"maverick.app.data-changed",owner_app_id:"user-admin",resource:"users"},window.location.origin)}async function D(){try{return await l("/api/admin/persistence")}catch(e){return o={tone:"error",message:e instanceof Error?e.message:"Persistence API unavailable"},null}}async function N(){try{return await l("/api/admin/persistence")}catch{return null}}async function g(){const[e,a,t,s]=await Promise.all([C(),I(),A(),D()]);m=e,_=a,w=t,d=s,(!h||!m.some(n=>n.user_id===h))&&(h=m[0]?.user_id||""),i()}async function O(e){const a=new FormData(e),t={username:String(a.get("username")||""),password:String(a.get("password")||""),display_name:String(a.get("display_name")||""),email:String(a.get("email")||""),platform_role:String(a.get("platform_role")||"member")};h=(await l("/api/admin/users",{method:"POST",body:JSON.stringify(t)})).user_id,e.reset(),await g(),$()}async function q(e,a){const t=new FormData(e);await l(`/api/admin/users/${encodeURIComponent(a.user_id)}`,{method:"PATCH",body:JSON.stringify({display_name:String(t.get("display_name")||""),email:String(t.get("email")||""),platform_role:String(t.get("platform_role")||"member"),account_type:String(t.get("account_type")||"standard"),is_active:t.get("is_active")==="on"})}),await g(),$()}async function R(e,a){const t=new FormData(e),s=String(t.get("password")||""),n=String(t.get("password_confirmation")||"");if(s!==n)throw new Error("Passwords do not match");await l(`/api/admin/users/${encodeURIComponent(a.user_id)}/password`,{method:"POST",body:JSON.stringify({password:s})}),e.reset(),o={tone:"success",message:"Password updated."},i()}async function j(e){const a=e.display_name||e.username;if(f!==e.user_id){f=e.user_id,o={tone:"info",message:`Press Delete user again to confirm permanent removal of ${a}.`},i();return}await l(`/api/admin/users/${encodeURIComponent(e.user_id)}`,{method:"DELETE"}),h="",f="",o={tone:"success",message:`${a} deleted.`},await g(),$()}async function B(e){const a=_.map(t=>{const s=document.querySelector(`[data-workspace-enabled="${t.workspace_id}"]`),n=document.querySelector(`[data-workspace-role="${t.workspace_id}"]`);return s?.checked?{workspace_id:t.workspace_id,role:n?.value||"member"}:null}).filter(Boolean);await l(`/api/admin/users/${encodeURIComponent(e.user_id)}/workspaces`,{method:"PUT",body:JSON.stringify({memberships:a})}),await g(),$()}async function J(e){await l(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"POST",body:JSON.stringify({source_id:e.source_id,enabled:!0})}),await g()}async function W(e,a){await l(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"PATCH",body:JSON.stringify({status:a?"enabled":"disabled"})}),await g()}async function F(e){await l(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"DELETE",body:JSON.stringify({})}),await g()}function H(e){return{kind:e,json_root:"data/control-plane/json",mongodb_uri:d?.active_adapter.mongo_uri||"mongodb://127.0.0.1:27017/maverick",mongodb_database:d?.active_adapter.mongo_database||"maverick",delete_source:!0,restart_backend:!0}}async function x(e){if(!d||d.active_adapter.kind===e){p=null,i();return}r={target:e,phase:"applying",percent:18,title:`Migration to ${e.toUpperCase()}`,detail:"Copying the control plane to the target adapter."},o=null,i(),b=await l("/api/admin/persistence/migrations/apply",{method:"POST",body:JSON.stringify(H(e))}),p=null,r={target:e,phase:"restarting",percent:68,title:"Restart backend",detail:b.backend_restart?.detail||"Backend restart scheduled."},i(),await z(e)}async function z(e){const a=Date.now(),t=9e4;for(;Date.now()-a<t;){r={target:e,phase:"polling",percent:84,title:"Verifying cutover",detail:"Waiting for the backend to become healthy with the new adapter."},i();const s=await N();if(s?.active_adapter.kind===e){d=s,r={target:e,phase:"complete",percent:100,title:"Migration complete",detail:`Active adapter: ${e.toUpperCase()}. Old storage cleanup started after health check.`},o={tone:"success",message:`Migration to ${e.toUpperCase()} complete.`},i();return}await new Promise(n=>window.setTimeout(n,1500))}r={target:e,phase:"failed",percent:100,title:"Verification not completed",detail:"The backend did not confirm the new adapter before the timeout. Check service health and logs."},o={tone:"error",message:"Migration not confirmed before the timeout."},i()}function V(e){return _.map(a=>{const t=M(e,a.workspace_id);return`<label class="ua-membership">
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
      </label>`}).join("")}function Q(){return _.map(e=>{const a=w.filter(n=>n.workspace_id===e.workspace_id),t=a.filter(n=>n.status==="enabled").length,s=a.filter(n=>n.installed).length;return`<details class="ua-app-workspace">
        <summary class="ua-app-workspace-heading">
          <span class="ua-summary-caret material-symbols-rounded" aria-hidden="true">chevron_right</span>
          <span class="ua-app-workspace-icon material-symbols-rounded" aria-hidden="true">deployed_code</span>
          <span>
            <strong>${e.name}</strong>
            <small>${e.workspace_id} · ${t}/${s} enabled</small>
          </span>
        </summary>
        <div class="ua-apps">
          ${a.map(n=>{const u=n.status==="enabled",y=n.installed,v=y?n.status:"not installed";return`<div class="ua-app-row">
                <span class="ua-app-icon material-symbols-rounded" aria-hidden="true">${u?"apps":"hide_source"}</span>
                <span class="ua-app-copy">
                  <strong>${n.name}</strong>
                  <small>${n.app_id} · v${n.version} · ${v}</small>
                </span>
                ${y?`<label class="ua-switch">
                      <input type="checkbox" data-app-toggle="${e.workspace_id}:${n.app_id}" ${u?"checked":""} />
                      <span>Enabled</span>
                    </label>
                    <button type="button" class="ua-secondary" data-app-uninstall="${e.workspace_id}:${n.app_id}">
                      <span class="material-symbols-rounded" aria-hidden="true">link_off</span>
                      Uninstall
                    </button>`:`<button type="button" class="ua-secondary" data-app-install="${e.workspace_id}:${n.app_id}">
                      <span class="material-symbols-rounded" aria-hidden="true">add_link</span>
                      Install
                    </button>`}
              </div>`}).join("")}
        </div>
      </details>`}).join("")}function G(){if(!d)return`<section class="ua-card ua-persistence">
      <div class="ua-heading">
        <div>
          <p class="ua-kicker">Persistence</p>
          <h2>Control plane adapter</h2>
        </div>
        <span class="ua-pill ua-pill-muted">offline</span>
      </div>
      <p class="ua-card-copy">The core persistence surfaces are not available in the active backend.</p>
    </section>`;const e=d.active_adapter,a=d.collections.reduce((v,S)=>v+S.count,0),t=r?`<div class="ua-migration-progress ${r.phase==="failed"?"is-failed":""} ${r.phase==="complete"?"is-complete":""}">
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
      </div>`:"",s=b?`<div class="ua-migration-result">
        <span class="material-symbols-rounded" aria-hidden="true">task_alt</span>
        <span>
          <strong>Ultima migrazione</strong>
          <small>${b.collections.reduce((v,S)=>v+S.count,0)} documents · target ${b.target_adapter.kind} · cleanup ${b.source_cleanup?.scheduled?"scheduled":"not requested"}</small>
        </span>
      </div>`:"",n=e.kind==="json",u=e.kind==="mongo",y=r&&r.phase!=="complete"&&r.phase!=="failed";return`<section class="ua-card ua-persistence">
    <div class="ua-heading">
      <div>
        <p class="ua-kicker">Persistence</p>
        <h2>Control plane adapter</h2>
      </div>
      <span class="ua-pill">${a} documents</span>
    </div>
    <div class="ua-adapter-cards">
      <button type="button" class="ua-adapter-card ${n?"is-active":""}" ${n||y?"disabled":'data-adapter-target="json"'}>
        <span class="ua-adapter-card-icon material-symbols-rounded" aria-hidden="true">${n?"check_circle":"database"}</span>
        <span>
          <strong>JSON</strong>
          <small>${n?e.json_root:"data/control-plane/json"}</small>
        </span>
        <em>${n?"Current":"Migrate here"}</em>
      </button>
      <button type="button" class="ua-adapter-card ${u?"is-active":""}" ${u||y?"disabled":'data-adapter-target="mongo"'}>
        <span class="ua-adapter-card-icon material-symbols-rounded" aria-hidden="true">${u?"check_circle":"database"}</span>
        <span>
          <strong>Mongo</strong>
          <small>${u?e.mongo_database:"mongodb://127.0.0.1:27017/maverick"}</small>
        </span>
        <em>${u?"Current":"Migrate here"}</em>
      </button>
    </div>
    ${t}
    ${s}
  </section>`}function K(){if(!p||!d)return"";const e=d.active_adapter.kind.toUpperCase(),a=p.toUpperCase();return`<div class="ua-modal-backdrop" role="presentation">
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
  </div>`}function i(){const e=document.getElementById("app"),a=P();if(!e)return;const t=m.filter(s=>s.is_active).length;e.innerHTML=`<main class="ua-shell">
    <section class="ua-main">
      <div class="ua-content">
        <header class="ua-page-header">
          <div>
            <p class="ua-kicker">Maverick</p>
            <h1>User Admin</h1>
            <p class="ua-copy">Manage users, platform roles, workspace access, app visibility, and control-plane persistence.</p>
          </div>
          <div class="ua-page-stats" aria-label="Admin summary">
            <span class="ua-stat"><strong>${m.length}</strong><small>users</small></span>
            <span class="ua-stat"><strong>${t}</strong><small>active</small></span>
            <span class="ua-stat"><strong>${_.length}</strong><small>workspaces</small></span>
          </div>
        </header>
        ${Y()}
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
        ${G()}
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
              ${f===a.user_id?"Confirm delete":"Delete user"}
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
            <div class="ua-memberships">${V(a)}</div>
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
            <div class="ua-app-workspaces">${Q()}</div>
          </details>`:'<section class="ua-card"><h2>No users</h2></section>'}
      </div>
    </section>
    ${K()}
  </main>`,X(),L(a)}function X(){document.getElementById("dismiss-notice")?.addEventListener("click",()=>{o=null,i()}),document.getElementById("create-user")?.addEventListener("submit",a=>{a.preventDefault(),O(a.currentTarget).catch(c)});const e=P();document.getElementById("edit-user")?.addEventListener("submit",a=>{a.preventDefault(),e&&q(a.currentTarget,e).catch(c)}),document.getElementById("reset-password")?.addEventListener("submit",a=>{a.preventDefault(),e&&R(a.currentTarget,e).catch(c)}),document.getElementById("delete-user")?.addEventListener("click",()=>{e&&j(e).catch(c)}),document.getElementById("save-memberships")?.addEventListener("click",()=>{e&&B(e).catch(c)}),document.querySelectorAll("[data-app-toggle]").forEach(a=>{a.addEventListener("change",()=>{const t=w.find(s=>`${s.workspace_id}:${s.app_id}`===a.dataset.appToggle);t&&W(t,a.checked).catch(c)})}),document.querySelectorAll("[data-app-install]").forEach(a=>{a.addEventListener("click",()=>{const t=w.find(s=>`${s.workspace_id}:${s.app_id}`===a.dataset.appInstall);t&&J(t).catch(c)})}),document.querySelectorAll("[data-app-uninstall]").forEach(a=>{a.addEventListener("click",()=>{const t=w.find(s=>`${s.workspace_id}:${s.app_id}`===a.dataset.appUninstall);t&&F(t).catch(c)})}),document.querySelectorAll("[data-adapter-target]").forEach(a=>{a.addEventListener("click",()=>{const t=a.dataset.adapterTarget;(t==="json"||t==="mongo")&&(p=t,i())})}),document.getElementById("close-migration-modal")?.addEventListener("click",()=>{p=null,i()}),document.getElementById("cancel-migration")?.addEventListener("click",()=>{p=null,i()}),document.getElementById("confirm-migration")?.addEventListener("click",()=>{p&&x(p).catch(c)})}function c(e){o={tone:"error",message:e instanceof Error?e.message:"Unexpected error"},i()}function Y(){return o?`<div class="ua-notice ua-notice-${o.tone}">
    <span class="material-symbols-rounded" aria-hidden="true">${o.tone==="error"?"error":o.tone==="success"?"task_alt":"info"}</span>
    <span>${o.message}</span>
    <button type="button" class="ua-icon-button" id="dismiss-notice" aria-label="Close">
      <span class="material-symbols-rounded" aria-hidden="true">close</span>
    </button>
  </div>`:""}window.addEventListener("message",e=>{if(e.origin!==window.location.origin||!e.data||typeof e.data!="object")return;const a=e.data;a.type==="maverick.app.navigate"&&(!a.app_id||a.app_id==="user-admin")&&T(a.params||{})});window.parent?.postMessage({type:"maverick.app.ready",app_id:"user-admin"},window.location.origin);g().catch(c);
