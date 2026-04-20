(function(){const e=document.createElement("link").relList;if(e&&e.supports&&e.supports("modulepreload"))return;for(const n of document.querySelectorAll('link[rel="modulepreload"]'))s(n);new MutationObserver(n=>{for(const i of n)if(i.type==="childList")for(const m of i.addedNodes)m.tagName==="LINK"&&m.rel==="modulepreload"&&s(m)}).observe(document,{childList:!0,subtree:!0});function t(n){const i={};return n.integrity&&(i.integrity=n.integrity),n.referrerPolicy&&(i.referrerPolicy=n.referrerPolicy),n.crossOrigin==="use-credentials"?i.credentials="include":n.crossOrigin==="anonymous"?i.credentials="omit":i.credentials="same-origin",i}function s(n){if(n.ep)return;n.ep=!0;const i=t(n);fetch(n.href,i)}})();let d=[],u=[],p=[],l="";async function o(a,e={}){const t=await fetch(a,{credentials:"same-origin",headers:{"Content-Type":"application/json",...e.headers||{}},...e}),s=await t.json();if(!t.ok)throw new Error(s.detail||s.error||`Request failed ${t.status}`);return s}function f(){return d.find(a=>a.user_id===l)||d[0]}function y(a,e){return a.memberships.find(t=>t.workspace_id===e)}async function c(){const[a,e,t]=await Promise.all([o("/api/admin/users"),o("/api/admin/workspaces"),o("/api/admin/workspace-apps")]);d=a.items,u=e.items,p=t.items,(!l||!d.some(s=>s.user_id===l))&&(l=d[0]?.user_id||""),b()}async function h(a){const e=new FormData(a),t={username:String(e.get("username")||""),password:String(e.get("password")||""),display_name:String(e.get("display_name")||""),email:String(e.get("email")||""),platform_role:String(e.get("platform_role")||"member")};l=(await o("/api/admin/users",{method:"POST",body:JSON.stringify(t)})).user_id,a.reset(),await c()}async function _(a,e){const t=new FormData(a);await o(`/api/admin/users/${encodeURIComponent(e.user_id)}`,{method:"PATCH",body:JSON.stringify({display_name:String(t.get("display_name")||""),email:String(t.get("email")||""),platform_role:String(t.get("platform_role")||"member"),account_type:String(t.get("account_type")||"standard"),is_active:t.get("is_active")==="on"})}),await c()}async function v(a){const e=u.map(t=>{const s=document.querySelector(`[data-workspace-enabled="${t.workspace_id}"]`),n=document.querySelector(`[data-workspace-role="${t.workspace_id}"]`);return s?.checked?{workspace_id:t.workspace_id,role:n?.value||"member"}:null}).filter(Boolean);await o(`/api/admin/users/${encodeURIComponent(a.user_id)}/workspaces`,{method:"PUT",body:JSON.stringify({memberships:e})}),await c()}async function g(a){await o(`/api/admin/workspace-apps/${encodeURIComponent(a.workspace_id)}/${encodeURIComponent(a.app_id)}`,{method:"POST",body:JSON.stringify({source_id:a.source_id,enabled:!0})}),await c()}async function w(a,e){await o(`/api/admin/workspace-apps/${encodeURIComponent(a.workspace_id)}/${encodeURIComponent(a.app_id)}`,{method:"PATCH",body:JSON.stringify({status:e?"enabled":"disabled"})}),await c()}async function k(a){await o(`/api/admin/workspace-apps/${encodeURIComponent(a.workspace_id)}/${encodeURIComponent(a.app_id)}`,{method:"DELETE",body:JSON.stringify({})}),await c()}function $(){return d.map(a=>{const e=a.user_id===f()?.user_id?"is-active":"",t=a.platform_role==="admin"?"Admin":"Member";return`<button class="ua-user ${e}" data-user-id="${a.user_id}">
        <span class="ua-user-icon material-symbols-rounded" aria-hidden="true">account_circle</span>
        <span class="ua-user-copy">
          <strong>${a.display_name||a.username}</strong>
          <span>${t} · ${a.memberships.length} workspace</span>
        </span>
      </button>`}).join("")}function S(a){return u.map(e=>{const t=y(a,e.workspace_id);return`<label class="ua-membership">
        <input type="checkbox" data-workspace-enabled="${e.workspace_id}" ${t?"checked":""} />
        <span class="ua-membership-icon material-symbols-rounded" aria-hidden="true">workspaces</span>
        <span>
          <strong>${e.name}</strong>
          <small>${e.workspace_id}</small>
        </span>
        <select data-workspace-role="${e.workspace_id}">
          <option value="member" ${t?.role!=="admin"?"selected":""}>Member</option>
          <option value="admin" ${t?.role==="admin"?"selected":""}>Workspace admin</option>
        </select>
      </label>`}).join("")}function E(){return u.map(a=>{const e=p.filter(t=>t.workspace_id===a.workspace_id);return`<article class="ua-app-workspace">
        <div class="ua-app-workspace-heading">
          <span class="material-symbols-rounded" aria-hidden="true">deployed_code</span>
          <div>
            <strong>${a.name}</strong>
            <small>${a.workspace_id}</small>
          </div>
        </div>
        <div class="ua-apps">
          ${e.map(t=>{const s=t.status==="enabled",n=t.installed,i=n?t.status:"non installata";return`<div class="ua-app-row">
                <span class="ua-app-icon material-symbols-rounded" aria-hidden="true">${s?"apps":"hide_source"}</span>
                <span class="ua-app-copy">
                  <strong>${t.name}</strong>
                  <small>${t.app_id} · v${t.version} · ${i}</small>
                </span>
                ${n?`<label class="ua-switch">
                      <input type="checkbox" data-app-toggle="${a.workspace_id}:${t.app_id}" ${s?"checked":""} />
                      <span>Abilitata</span>
                    </label>
                    <button type="button" class="ua-secondary" data-app-uninstall="${a.workspace_id}:${t.app_id}">
                      <span class="material-symbols-rounded" aria-hidden="true">link_off</span>
                      Uninstall
                    </button>`:`<button type="button" class="ua-secondary" data-app-install="${a.workspace_id}:${t.app_id}">
                      <span class="material-symbols-rounded" aria-hidden="true">add_link</span>
                      Installa
                    </button>`}
              </div>`}).join("")}
        </div>
      </article>`}).join("")}function b(){const a=document.getElementById("app"),e=f();a&&(a.innerHTML=`<section class="ua-shell">
    <aside class="ua-rail">
      <div>
        <p class="ua-kicker">Maverick</p>
        <h1>User Admin</h1>
        <p class="ua-copy">Gestione utenti, ruoli platform e accesso workspace.</p>
      </div>
      <div class="ua-users">${$()}</div>
    </aside>
    <section class="ua-main">
      <form class="ua-card ua-create" id="create-user">
        <div>
          <p class="ua-kicker">Nuovo utente</p>
          <h2>Crea accesso</h2>
        </div>
        <input name="username" placeholder="username" required />
        <input name="password" type="password" placeholder="password temporanea" required />
        <input name="display_name" placeholder="nome visualizzato" />
        <input name="email" type="email" placeholder="email" />
        <select name="platform_role">
          <option value="member">Member</option>
          <option value="admin">Admin</option>
        </select>
        <button type="submit">
          <span class="material-symbols-rounded" aria-hidden="true">person_add</span>
          Crea utente
        </button>
      </form>
      ${e?`<form class="ua-card ua-detail" id="edit-user">
            <div class="ua-heading">
              <div>
                <p class="ua-kicker">Utente selezionato</p>
                <h2>${e.display_name||e.username}</h2>
              </div>
              <span class="ua-pill">${e.is_active?"attivo":"disattivato"}</span>
            </div>
            <div class="ua-grid">
              <label>Nome<input name="display_name" value="${e.display_name||""}" /></label>
              <label>Email<input name="email" type="email" value="${e.email||""}" /></label>
              <label>Ruolo platform<select name="platform_role">
                <option value="member" ${e.platform_role==="member"?"selected":""}>Member</option>
                <option value="admin" ${e.platform_role==="admin"?"selected":""}>Admin</option>
              </select></label>
              <label>Tipo account<select name="account_type">
                <option value="standard" ${e.account_type==="standard"?"selected":""}>Standard</option>
                <option value="facilitated" ${e.account_type==="facilitated"?"selected":""}>Facilitated</option>
              </select></label>
            </div>
            <label class="ua-toggle"><input name="is_active" type="checkbox" ${e.is_active?"checked":""} /> Account attivo</label>
            <button type="submit">
              <span class="material-symbols-rounded" aria-hidden="true">save</span>
              Salva utente
            </button>
          </form>
          <section class="ua-card">
            <div class="ua-heading">
              <div>
                <p class="ua-kicker">Workspace</p>
                <h2>Assegnazioni</h2>
              </div>
              <button type="button" id="save-memberships">
                <span class="material-symbols-rounded" aria-hidden="true">admin_panel_settings</span>
                Salva accessi
              </button>
            </div>
            <div class="ua-memberships">${S(e)}</div>
          </section>
          <section class="ua-card">
            <div class="ua-heading">
              <div>
                <p class="ua-kicker">App per workspace</p>
                <h2>Installazione e visibilità</h2>
              </div>
            </div>
            <p class="ua-card-copy">Installata significa montata nel workspace. Solo le app abilitate sono visibili agli utenti e servite dal core.</p>
            <div class="ua-app-workspaces">${E()}</div>
          </section>`:'<section class="ua-card"><h2>Nessun utente</h2></section>'}
    </section>
  </section>`,A())}function A(){document.querySelectorAll("[data-user-id]").forEach(e=>{e.addEventListener("click",()=>{l=e.dataset.userId||"",b()})}),document.getElementById("create-user")?.addEventListener("submit",e=>{e.preventDefault(),h(e.currentTarget).catch(r)});const a=f();document.getElementById("edit-user")?.addEventListener("submit",e=>{e.preventDefault(),a&&_(e.currentTarget,a).catch(r)}),document.getElementById("save-memberships")?.addEventListener("click",()=>{a&&v(a).catch(r)}),document.querySelectorAll("[data-app-toggle]").forEach(e=>{e.addEventListener("change",()=>{const t=p.find(s=>`${s.workspace_id}:${s.app_id}`===e.dataset.appToggle);t&&w(t,e.checked).catch(r)})}),document.querySelectorAll("[data-app-install]").forEach(e=>{e.addEventListener("click",()=>{const t=p.find(s=>`${s.workspace_id}:${s.app_id}`===e.dataset.appInstall);t&&g(t).catch(r)})}),document.querySelectorAll("[data-app-uninstall]").forEach(e=>{e.addEventListener("click",()=>{const t=p.find(s=>`${s.workspace_id}:${s.app_id}`===e.dataset.appUninstall);t&&k(t).catch(r)})})}function r(a){const e=a instanceof Error?a.message:"Errore inatteso";window.alert(e)}c().catch(r);
