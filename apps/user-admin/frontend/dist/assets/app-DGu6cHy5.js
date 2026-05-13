(function(){const a=document.createElement("link").relList;if(a&&a.supports&&a.supports("modulepreload"))return;for(const s of document.querySelectorAll('link[rel="modulepreload"]'))n(s);new MutationObserver(s=>{for(const o of s)if(o.type==="childList")for(const u of o.addedNodes)u.tagName==="LINK"&&u.rel==="modulepreload"&&n(u)}).observe(document,{childList:!0,subtree:!0});function t(s){const o={};return s.integrity&&(o.integrity=s.integrity),s.referrerPolicy&&(o.referrerPolicy=s.referrerPolicy),s.crossOrigin==="use-credentials"?o.credentials="include":s.crossOrigin==="anonymous"?o.credentials="omit":o.credentials="same-origin",o}function n(s){if(s.ep)return;s.ep=!0;const o=t(s);fetch(s.href,o)}})();let v=[],w=[],f=[],d=null,h=null,i=null,b="",_="",m=null,l=null;async function c(e,a={}){const t=await fetch(e,{credentials:"same-origin",headers:{"Content-Type":"application/json",...a.headers||{}},...a}),n=await t.json();if(!t.ok)throw new Error(n.detail||n.error||`Request failed ${t.status}`);return n}function k(){return v.find(e=>e.user_id===b)||v[0]}function E(e,a){return e.memberships.find(t=>t.workspace_id===a)}async function S(){try{return await c("/api/admin/persistence")}catch(e){return l={tone:"error",message:e instanceof Error?e.message:"Persistence API non disponibile"},null}}async function C(){try{return await c("/api/admin/persistence")}catch{return null}}async function g(){const[e,a,t,n]=await Promise.all([c("/api/admin/users"),c("/api/admin/workspaces"),c("/api/admin/workspace-apps"),S()]);v=e.items,w=a.items,f=t.items,d=n,(!b||!v.some(s=>s.user_id===b))&&(b=v[0]?.user_id||""),r()}async function A(e){const a=new FormData(e),t={username:String(a.get("username")||""),password:String(a.get("password")||""),display_name:String(a.get("display_name")||""),email:String(a.get("email")||""),platform_role:String(a.get("platform_role")||"member")};b=(await c("/api/admin/users",{method:"POST",body:JSON.stringify(t)})).user_id,e.reset(),await g()}async function P(e,a){const t=new FormData(e);await c(`/api/admin/users/${encodeURIComponent(a.user_id)}`,{method:"PATCH",body:JSON.stringify({display_name:String(t.get("display_name")||""),email:String(t.get("email")||""),platform_role:String(t.get("platform_role")||"member"),account_type:String(t.get("account_type")||"standard"),is_active:t.get("is_active")==="on"})}),await g()}async function I(e,a){const t=new FormData(e),n=String(t.get("password")||""),s=String(t.get("password_confirmation")||"");if(n!==s)throw new Error("Le password non coincidono");await c(`/api/admin/users/${encodeURIComponent(a.user_id)}/password`,{method:"POST",body:JSON.stringify({password:n})}),e.reset(),l={tone:"success",message:"Password aggiornata."},r()}async function U(e){const a=e.display_name||e.username;if(_!==e.user_id){_=e.user_id,l={tone:"info",message:`Premi di nuovo Elimina utente per confermare la rimozione definitiva di ${a}.`},r();return}await c(`/api/admin/users/${encodeURIComponent(e.user_id)}`,{method:"DELETE"}),b="",_="",l={tone:"success",message:`${a} eliminato.`},await g()}async function L(e){const a=w.map(t=>{const n=document.querySelector(`[data-workspace-enabled="${t.workspace_id}"]`),s=document.querySelector(`[data-workspace-role="${t.workspace_id}"]`);return n?.checked?{workspace_id:t.workspace_id,role:s?.value||"member"}:null}).filter(Boolean);await c(`/api/admin/users/${encodeURIComponent(e.user_id)}/workspaces`,{method:"PUT",body:JSON.stringify({memberships:a})}),await g()}async function M(e){await c(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"POST",body:JSON.stringify({source_id:e.source_id,enabled:!0})}),await g()}async function T(e,a){await c(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"PATCH",body:JSON.stringify({status:a?"enabled":"disabled"})}),await g()}async function O(e){await c(`/api/admin/workspace-apps/${encodeURIComponent(e.workspace_id)}/${encodeURIComponent(e.app_id)}`,{method:"DELETE",body:JSON.stringify({})}),await g()}function q(e){return{kind:e,json_root:"data/control-plane/json",mongodb_uri:d?.active_adapter.mongo_uri||"mongodb://127.0.0.1:27017/maverick",mongodb_database:d?.active_adapter.mongo_database||"maverick",delete_source:!0,restart_backend:!0}}async function z(e){if(!d||d.active_adapter.kind===e){m=null,r();return}i={target:e,phase:"applying",percent:18,title:`Migrazione verso ${e.toUpperCase()}`,detail:"Copia del control plane nel target adapter in corso."},l=null,r(),h=await c("/api/admin/persistence/migrations/apply",{method:"POST",body:JSON.stringify(q(e))}),m=null,i={target:e,phase:"restarting",percent:68,title:"Restart backend",detail:h.backend_restart?.detail||"Restart backend programmato."},r(),await N(e)}async function N(e){const a=Date.now(),t=9e4;for(;Date.now()-a<t;){i={target:e,phase:"polling",percent:84,title:"Verifica cutover",detail:"Attendo che il backend torni healthy con il nuovo adapter."},r();const n=await C();if(n?.active_adapter.kind===e){d=n,i={target:e,phase:"complete",percent:100,title:"Migrazione completata",detail:`Adapter attivo: ${e.toUpperCase()}. Cleanup del vecchio storage avviato dopo health check.`},l={tone:"success",message:`Migrazione verso ${e.toUpperCase()} completata.`},r();return}await new Promise(s=>window.setTimeout(s,1500))}i={target:e,phase:"failed",percent:100,title:"Verifica non conclusa",detail:"Il backend non ha confermato il nuovo adapter entro il timeout. Controlla health e log servizio."},l={tone:"error",message:"Migrazione non confermata entro il timeout."},r()}function R(){return v.map(e=>{const a=e.user_id===k()?.user_id?"is-active":"",t=e.platform_role==="admin"?"Admin":"Member";return`<button class="ua-user ${a}" data-user-id="${e.user_id}">
        <span class="ua-user-icon material-symbols-rounded" aria-hidden="true">account_circle</span>
        <span class="ua-user-copy">
          <strong>${e.display_name||e.username}</strong>
          <span>${t} · ${e.memberships.length} workspace</span>
        </span>
      </button>`}).join("")}function j(e){return w.map(a=>{const t=E(e,a.workspace_id);return`<label class="ua-membership">
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
      </label>`}).join("")}function D(){return w.map(e=>{const a=f.filter(s=>s.workspace_id===e.workspace_id),t=a.filter(s=>s.status==="enabled").length,n=a.filter(s=>s.installed).length;return`<details class="ua-app-workspace">
        <summary class="ua-app-workspace-heading">
          <span class="ua-summary-caret material-symbols-rounded" aria-hidden="true">chevron_right</span>
          <span class="ua-app-workspace-icon material-symbols-rounded" aria-hidden="true">deployed_code</span>
          <span>
            <strong>${e.name}</strong>
            <small>${e.workspace_id} · ${t}/${n} abilitate</small>
          </span>
        </summary>
        <div class="ua-apps">
          ${a.map(s=>{const o=s.status==="enabled",u=s.installed,y=u?s.status:"non installata";return`<div class="ua-app-row">
                <span class="ua-app-icon material-symbols-rounded" aria-hidden="true">${o?"apps":"hide_source"}</span>
                <span class="ua-app-copy">
                  <strong>${s.name}</strong>
                  <small>${s.app_id} · v${s.version} · ${y}</small>
                </span>
                ${u?`<label class="ua-switch">
                      <input type="checkbox" data-app-toggle="${e.workspace_id}:${s.app_id}" ${o?"checked":""} />
                      <span>Abilitata</span>
                    </label>
                    <button type="button" class="ua-secondary" data-app-uninstall="${e.workspace_id}:${s.app_id}">
                      <span class="material-symbols-rounded" aria-hidden="true">link_off</span>
                      Uninstall
                    </button>`:`<button type="button" class="ua-secondary" data-app-install="${e.workspace_id}:${s.app_id}">
                      <span class="material-symbols-rounded" aria-hidden="true">add_link</span>
                      Installa
                    </button>`}
              </div>`}).join("")}
        </div>
      </details>`}).join("")}function B(){if(!d)return`<section class="ua-card ua-persistence">
      <div class="ua-heading">
        <div>
          <p class="ua-kicker">Persistence</p>
          <h2>Control plane adapter</h2>
        </div>
        <span class="ua-pill ua-pill-muted">offline</span>
      </div>
      <p class="ua-card-copy">Le superfici core di persistence non sono disponibili nel backend attivo.</p>
    </section>`;const e=d.active_adapter,a=d.collections.reduce((y,$)=>y+$.count,0),t=i?`<div class="ua-migration-progress ${i.phase==="failed"?"is-failed":""} ${i.phase==="complete"?"is-complete":""}">
        <div class="ua-migration-progress-heading">
          <span class="material-symbols-rounded" aria-hidden="true">${i.phase==="complete"?"check_circle":i.phase==="failed"?"error":"sync"}</span>
          <span>
            <strong>${i.title}</strong>
            <small>${i.detail}</small>
          </span>
          <em>${i.percent}%</em>
        </div>
        <div class="ua-progress-track" aria-label="Progresso migrazione" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${i.percent}">
          <span style="width: ${i.percent}%"></span>
        </div>
      </div>`:"",n=h?`<div class="ua-migration-result">
        <span class="material-symbols-rounded" aria-hidden="true">task_alt</span>
        <span>
          <strong>Ultima migrazione</strong>
          <small>${h.collections.reduce((y,$)=>y+$.count,0)} documenti · target ${h.target_adapter.kind} · cleanup ${h.source_cleanup?.scheduled?"programmato":"non richiesto"}</small>
        </span>
      </div>`:"",s=e.kind==="json",o=e.kind==="mongo",u=i&&i.phase!=="complete"&&i.phase!=="failed";return`<section class="ua-card ua-persistence">
    <div class="ua-heading">
      <div>
        <p class="ua-kicker">Persistence</p>
        <h2>Control plane adapter</h2>
      </div>
      <span class="ua-pill">${a} documenti</span>
    </div>
    <div class="ua-adapter-cards">
      <button type="button" class="ua-adapter-card ${s?"is-active":""}" ${s||u?"disabled":'data-adapter-target="json"'}>
        <span class="ua-adapter-card-icon material-symbols-rounded" aria-hidden="true">${s?"check_circle":"database"}</span>
        <span>
          <strong>JSON</strong>
          <small>${s?e.json_root:"data/control-plane/json"}</small>
        </span>
        <em>${s?"Attuale":"Migra qui"}</em>
      </button>
      <button type="button" class="ua-adapter-card ${o?"is-active":""}" ${o||u?"disabled":'data-adapter-target="mongo"'}>
        <span class="ua-adapter-card-icon material-symbols-rounded" aria-hidden="true">${o?"check_circle":"database"}</span>
        <span>
          <strong>Mongo</strong>
          <small>${o?e.mongo_database:"mongodb://127.0.0.1:27017/maverick"}</small>
        </span>
        <em>${o?"Attuale":"Migra qui"}</em>
      </button>
    </div>
    ${t}
    ${n}
  </section>`}function J(){if(!m||!d)return"";const e=d.active_adapter.kind.toUpperCase(),a=m.toUpperCase();return`<div class="ua-modal-backdrop" role="presentation">
    <section class="ua-modal" role="dialog" aria-modal="true" aria-labelledby="adapter-migration-title">
      <div class="ua-heading">
        <div>
          <p class="ua-kicker">Conferma migrazione</p>
          <h2 id="adapter-migration-title">${e} → ${a}</h2>
        </div>
        <button type="button" class="ua-icon-button" id="close-migration-modal" aria-label="Chiudi">
          <span class="material-symbols-rounded" aria-hidden="true">close</span>
        </button>
      </div>
      <p class="ua-card-copy">La migrazione copia tutto il control plane nel nuovo adapter, aggiorna la configurazione del backend, riavvia il core e cancella il vecchio storage solo dopo che il nuovo backend risponde healthy.</p>
      <div class="ua-modal-actions">
        <button type="button" class="ua-secondary" id="cancel-migration">Annulla</button>
        <button type="button" class="ua-danger" id="confirm-migration" ${i&&i.phase!=="complete"&&i.phase!=="failed"?"disabled":""}>
          <span class="material-symbols-rounded" aria-hidden="true">sync_alt</span>
          Migra e cancella
        </button>
      </div>
    </section>
  </div>`}function r(){const e=document.getElementById("app"),a=k();e&&(e.innerHTML=`<section class="ua-shell">
    <aside class="ua-rail">
      <div>
        <p class="ua-kicker">Maverick</p>
        <h1>User Admin</h1>
        <p class="ua-copy">Gestione utenti, ruoli platform e accesso workspace.</p>
      </div>
      <div class="ua-users">${R()}</div>
    </aside>
    <section class="ua-main">
      <div class="ua-content">
        ${F()}
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
        ${B()}
        ${a?`<div class="ua-profile-row">
            <form class="ua-card ua-detail" id="edit-user">
            <div class="ua-heading">
              <div>
                <p class="ua-kicker">Utente selezionato</p>
                <h2>${a.display_name||a.username}</h2>
              </div>
              <span class="ua-pill">${a.is_active?"attivo":"disattivato"}</span>
            </div>
            <div class="ua-grid">
              <label>Nome<input name="display_name" value="${a.display_name||""}" /></label>
              <label>Email<input name="email" type="email" value="${a.email||""}" /></label>
              <label>Ruolo platform<select name="platform_role">
                <option value="member" ${a.platform_role==="member"?"selected":""}>Member</option>
                <option value="admin" ${a.platform_role==="admin"?"selected":""}>Admin</option>
              </select></label>
              <label>Tipo account<select name="account_type">
                <option value="standard" ${a.account_type==="standard"?"selected":""}>Standard</option>
                <option value="facilitated" ${a.account_type==="facilitated"?"selected":""}>Facilitated</option>
              </select></label>
            </div>
            <label class="ua-toggle"><input name="is_active" type="checkbox" ${a.is_active?"checked":""} /> Account attivo</label>
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
            <button type="button" class="ua-danger" id="delete-user">
              <span class="material-symbols-rounded" aria-hidden="true">person_remove</span>
              ${_===a.user_id?"Conferma elimina":"Elimina utente"}
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
            <div class="ua-memberships">${j(a)}</div>
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
            <div class="ua-app-workspaces">${D()}</div>
          </details>`:'<section class="ua-card"><h2>Nessun utente</h2></section>'}
      </div>
    </section>
    ${J()}
  </section>`,H())}function H(){document.getElementById("dismiss-notice")?.addEventListener("click",()=>{l=null,r()}),document.querySelectorAll("[data-user-id]").forEach(a=>{a.addEventListener("click",()=>{b=a.dataset.userId||"",_="",r()})}),document.getElementById("create-user")?.addEventListener("submit",a=>{a.preventDefault(),A(a.currentTarget).catch(p)});const e=k();document.getElementById("edit-user")?.addEventListener("submit",a=>{a.preventDefault(),e&&P(a.currentTarget,e).catch(p)}),document.getElementById("reset-password")?.addEventListener("submit",a=>{a.preventDefault(),e&&I(a.currentTarget,e).catch(p)}),document.getElementById("delete-user")?.addEventListener("click",()=>{e&&U(e).catch(p)}),document.getElementById("save-memberships")?.addEventListener("click",()=>{e&&L(e).catch(p)}),document.querySelectorAll("[data-app-toggle]").forEach(a=>{a.addEventListener("change",()=>{const t=f.find(n=>`${n.workspace_id}:${n.app_id}`===a.dataset.appToggle);t&&T(t,a.checked).catch(p)})}),document.querySelectorAll("[data-app-install]").forEach(a=>{a.addEventListener("click",()=>{const t=f.find(n=>`${n.workspace_id}:${n.app_id}`===a.dataset.appInstall);t&&M(t).catch(p)})}),document.querySelectorAll("[data-app-uninstall]").forEach(a=>{a.addEventListener("click",()=>{const t=f.find(n=>`${n.workspace_id}:${n.app_id}`===a.dataset.appUninstall);t&&O(t).catch(p)})}),document.querySelectorAll("[data-adapter-target]").forEach(a=>{a.addEventListener("click",()=>{const t=a.dataset.adapterTarget;(t==="json"||t==="mongo")&&(m=t,r())})}),document.getElementById("close-migration-modal")?.addEventListener("click",()=>{m=null,r()}),document.getElementById("cancel-migration")?.addEventListener("click",()=>{m=null,r()}),document.getElementById("confirm-migration")?.addEventListener("click",()=>{m&&z(m).catch(p)})}function p(e){l={tone:"error",message:e instanceof Error?e.message:"Errore inatteso"},r()}function F(){return l?`<div class="ua-notice ua-notice-${l.tone}">
    <span class="material-symbols-rounded" aria-hidden="true">${l.tone==="error"?"error":l.tone==="success"?"task_alt":"info"}</span>
    <span>${l.message}</span>
    <button type="button" class="ua-icon-button" id="dismiss-notice" aria-label="Chiudi">
      <span class="material-symbols-rounded" aria-hidden="true">close</span>
    </button>
  </div>`:""}g().catch(p);
