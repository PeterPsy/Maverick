(function(){const e=document.createElement("link").relList;if(e&&e.supports&&e.supports("modulepreload"))return;for(const t of document.querySelectorAll('link[rel="modulepreload"]'))n(t);new MutationObserver(t=>{for(const i of t)if(i.type==="childList")for(const l of i.addedNodes)l.tagName==="LINK"&&l.rel==="modulepreload"&&n(l)}).observe(document,{childList:!0,subtree:!0});function s(t){const i={};return t.integrity&&(i.integrity=t.integrity),t.referrerPolicy&&(i.referrerPolicy=t.referrerPolicy),t.crossOrigin==="use-credentials"?i.credentials="include":t.crossOrigin==="anonymous"?i.credentials="omit":i.credentials="same-origin",i}function n(t){if(t.ep)return;t.ep=!0;const i=s(t);fetch(t.href,i)}})();let c=[],m=[],u=[],p="";async function o(a,e={}){const s=await fetch(a,{credentials:"same-origin",headers:{"Content-Type":"application/json",...e.headers||{}},...e}),n=await s.json();if(!s.ok)throw new Error(n.detail||n.error||`Request failed ${s.status}`);return n}function y(){return c.find(a=>a.user_id===p)||c[0]}function h(a,e){return a.memberships.find(s=>s.workspace_id===e)}async function d(){const[a,e,s]=await Promise.all([o("/api/admin/users"),o("/api/admin/workspaces"),o("/api/admin/workspace-apps")]);c=a.items,m=e.items,u=s.items,(!p||!c.some(n=>n.user_id===p))&&(p=c[0]?.user_id||""),b()}async function w(a){const e=new FormData(a),s={username:String(e.get("username")||""),password:String(e.get("password")||""),display_name:String(e.get("display_name")||""),email:String(e.get("email")||""),platform_role:String(e.get("platform_role")||"member")};p=(await o("/api/admin/users",{method:"POST",body:JSON.stringify(s)})).user_id,a.reset(),await d()}async function g(a,e){const s=new FormData(a);await o(`/api/admin/users/${encodeURIComponent(e.user_id)}`,{method:"PATCH",body:JSON.stringify({display_name:String(s.get("display_name")||""),email:String(s.get("email")||""),platform_role:String(s.get("platform_role")||"member"),account_type:String(s.get("account_type")||"standard"),is_active:s.get("is_active")==="on"})}),await d()}async function v(a,e){const s=new FormData(a),n=String(s.get("password")||""),t=String(s.get("password_confirmation")||"");if(n!==t)throw new Error("Le password non coincidono");await o(`/api/admin/users/${encodeURIComponent(e.user_id)}/password`,{method:"POST",body:JSON.stringify({password:n})}),a.reset(),window.alert("Password aggiornata")}async function _(a){const e=m.map(s=>{const n=document.querySelector(`[data-workspace-enabled="${s.workspace_id}"]`),t=document.querySelector(`[data-workspace-role="${s.workspace_id}"]`);return n?.checked?{workspace_id:s.workspace_id,role:t?.value||"member"}:null}).filter(Boolean);await o(`/api/admin/users/${encodeURIComponent(a.user_id)}/workspaces`,{method:"PUT",body:JSON.stringify({memberships:e})}),await d()}async function k(a){await o(`/api/admin/workspace-apps/${encodeURIComponent(a.workspace_id)}/${encodeURIComponent(a.app_id)}`,{method:"POST",body:JSON.stringify({source_id:a.source_id,enabled:!0})}),await d()}async function $(a,e){await o(`/api/admin/workspace-apps/${encodeURIComponent(a.workspace_id)}/${encodeURIComponent(a.app_id)}`,{method:"PATCH",body:JSON.stringify({status:e?"enabled":"disabled"})}),await d()}async function S(a){await o(`/api/admin/workspace-apps/${encodeURIComponent(a.workspace_id)}/${encodeURIComponent(a.app_id)}`,{method:"DELETE",body:JSON.stringify({})}),await d()}function E(){return c.map(a=>{const e=a.user_id===y()?.user_id?"is-active":"",s=a.platform_role==="admin"?"Admin":"Member";return`<button class="ua-user ${e}" data-user-id="${a.user_id}">
        <span class="ua-user-icon material-symbols-rounded" aria-hidden="true">account_circle</span>
        <span class="ua-user-copy">
          <strong>${a.display_name||a.username}</strong>
          <span>${s} · ${a.memberships.length} workspace</span>
        </span>
      </button>`}).join("")}function A(a){return m.map(e=>{const s=h(a,e.workspace_id);return`<label class="ua-membership">
        <input type="checkbox" data-workspace-enabled="${e.workspace_id}" ${s?"checked":""} />
        <span class="ua-membership-icon material-symbols-rounded" aria-hidden="true">workspaces</span>
        <span>
          <strong>${e.name}</strong>
          <small>${e.workspace_id}</small>
        </span>
        <select data-workspace-role="${e.workspace_id}">
          <option value="member" ${s?.role!=="admin"?"selected":""}>Member</option>
          <option value="admin" ${s?.role==="admin"?"selected":""}>Workspace admin</option>
        </select>
      </label>`}).join("")}function I(){return m.map(a=>{const e=u.filter(t=>t.workspace_id===a.workspace_id),s=e.filter(t=>t.status==="enabled").length,n=e.filter(t=>t.installed).length;return`<details class="ua-app-workspace">
        <summary class="ua-app-workspace-heading">
          <span class="ua-summary-caret material-symbols-rounded" aria-hidden="true">chevron_right</span>
          <span class="ua-app-workspace-icon material-symbols-rounded" aria-hidden="true">deployed_code</span>
          <span>
            <strong>${a.name}</strong>
            <small>${a.workspace_id} · ${s}/${n} abilitate</small>
          </span>
        </summary>
        <div class="ua-apps">
          ${e.map(t=>{const i=t.status==="enabled",l=t.installed,f=l?t.status:"non installata";return`<div class="ua-app-row">
                <span class="ua-app-icon material-symbols-rounded" aria-hidden="true">${i?"apps":"hide_source"}</span>
                <span class="ua-app-copy">
                  <strong>${t.name}</strong>
                  <small>${t.app_id} · v${t.version} · ${f}</small>
                </span>
                ${l?`<label class="ua-switch">
                      <input type="checkbox" data-app-toggle="${a.workspace_id}:${t.app_id}" ${i?"checked":""} />
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
      </details>`}).join("")}function b(){const a=document.getElementById("app"),e=y();a&&(a.innerHTML=`<section class="ua-shell">
    <aside class="ua-rail">
      <div>
        <p class="ua-kicker">Maverick</p>
        <h1>User Admin</h1>
        <p class="ua-copy">Gestione utenti, ruoli platform e accesso workspace.</p>
      </div>
      <div class="ua-users">${E()}</div>
    </aside>
    <section class="ua-main">
      <div class="ua-content">
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
        ${e?`<div class="ua-profile-row">
            <form class="ua-card ua-detail" id="edit-user">
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
          <form class="ua-card ua-password" id="reset-password">
            <div class="ua-heading">
              <div>
                <p class="ua-kicker">Password</p>
                <h2>Reset accesso</h2>
              </div>
              <span class="ua-password-icon material-symbols-rounded" aria-hidden="true">key</span>
            </div>
            <p class="ua-card-copy">Imposta una nuova password temporanea per l'utente selezionato.</p>
            <div class="ua-password-grid">
              <label>Nuova password<input name="password" type="password" minlength="8" autocomplete="new-password" required /></label>
              <label>Conferma password<input name="password_confirmation" type="password" minlength="8" autocomplete="new-password" required /></label>
            </div>
            <button type="submit" class="ua-secondary">
              <span class="material-symbols-rounded" aria-hidden="true">password</span>
              Aggiorna password
            </button>
          </form>
          </div>
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
            <div class="ua-memberships">${A(e)}</div>
          </section>
          <details class="ua-card ua-collapsible" open>
            <summary class="ua-heading ua-collapsible-heading">
              <div>
                <p class="ua-kicker">App per workspace</p>
                <h2>Installazione e visibilità</h2>
              </div>
              <span class="ua-summary-caret material-symbols-rounded" aria-hidden="true">chevron_right</span>
            </summary>
            <p class="ua-card-copy">Installata significa montata nel workspace. Solo le app abilitate sono visibili agli utenti e servite dal core.</p>
            <div class="ua-app-workspaces">${I()}</div>
          </details>`:'<section class="ua-card"><h2>Nessun utente</h2></section>'}
      </div>
    </section>
  </section>`,U())}function U(){document.querySelectorAll("[data-user-id]").forEach(e=>{e.addEventListener("click",()=>{p=e.dataset.userId||"",b()})}),document.getElementById("create-user")?.addEventListener("submit",e=>{e.preventDefault(),w(e.currentTarget).catch(r)});const a=y();document.getElementById("edit-user")?.addEventListener("submit",e=>{e.preventDefault(),a&&g(e.currentTarget,a).catch(r)}),document.getElementById("reset-password")?.addEventListener("submit",e=>{e.preventDefault(),a&&v(e.currentTarget,a).catch(r)}),document.getElementById("save-memberships")?.addEventListener("click",()=>{a&&_(a).catch(r)}),document.querySelectorAll("[data-app-toggle]").forEach(e=>{e.addEventListener("change",()=>{const s=u.find(n=>`${n.workspace_id}:${n.app_id}`===e.dataset.appToggle);s&&$(s,e.checked).catch(r)})}),document.querySelectorAll("[data-app-install]").forEach(e=>{e.addEventListener("click",()=>{const s=u.find(n=>`${n.workspace_id}:${n.app_id}`===e.dataset.appInstall);s&&k(s).catch(r)})}),document.querySelectorAll("[data-app-uninstall]").forEach(e=>{e.addEventListener("click",()=>{const s=u.find(n=>`${n.workspace_id}:${n.app_id}`===e.dataset.appUninstall);s&&S(s).catch(r)})})}function r(a){const e=a instanceof Error?a.message:"Errore inatteso";window.alert(e)}d().catch(r);
