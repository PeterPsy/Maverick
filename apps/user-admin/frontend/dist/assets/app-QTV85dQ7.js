(function(){const e=document.createElement("link").relList;if(e&&e.supports&&e.supports("modulepreload"))return;for(const s of document.querySelectorAll('link[rel="modulepreload"]'))n(s);new MutationObserver(s=>{for(const i of s)if(i.type==="childList")for(const u of i.addedNodes)u.tagName==="LINK"&&u.rel==="modulepreload"&&n(u)}).observe(document,{childList:!0,subtree:!0});function a(s){const i={};return s.integrity&&(i.integrity=s.integrity),s.referrerPolicy&&(i.referrerPolicy=s.referrerPolicy),s.crossOrigin==="use-credentials"?i.credentials="include":s.crossOrigin==="anonymous"?i.credentials="omit":i.credentials="same-origin",i}function n(s){if(s.ep)return;s.ep=!0;const i=a(s);fetch(s.href,i)}})();let r=[],m=[],o="";async function c(t,e={}){const a=await fetch(t,{credentials:"same-origin",headers:{"Content-Type":"application/json",...e.headers||{}},...e}),n=await a.json();if(!a.ok)throw new Error(n.detail||n.error||`Request failed ${a.status}`);return n}function p(){return r.find(t=>t.user_id===o)||r[0]}function b(t,e){return t.memberships.find(a=>a.workspace_id===e)}async function d(){const[t,e]=await Promise.all([c("/api/admin/users"),c("/api/admin/workspaces")]);r=t.items,m=e.items,(!o||!r.some(a=>a.user_id===o))&&(o=r[0]?.user_id||""),f()}async function y(t){const e=new FormData(t),a={username:String(e.get("username")||""),password:String(e.get("password")||""),display_name:String(e.get("display_name")||""),email:String(e.get("email")||""),platform_role:String(e.get("platform_role")||"member")};o=(await c("/api/admin/users",{method:"POST",body:JSON.stringify(a)})).user_id,t.reset(),await d()}async function h(t,e){const a=new FormData(t);await c(`/api/admin/users/${encodeURIComponent(e.user_id)}`,{method:"PATCH",body:JSON.stringify({display_name:String(a.get("display_name")||""),email:String(a.get("email")||""),platform_role:String(a.get("platform_role")||"member"),account_type:String(a.get("account_type")||"standard"),is_active:a.get("is_active")==="on"})}),await d()}async function v(t){const e=m.map(a=>{const n=document.querySelector(`[data-workspace-enabled="${a.workspace_id}"]`),s=document.querySelector(`[data-workspace-role="${a.workspace_id}"]`);return n?.checked?{workspace_id:a.workspace_id,role:s?.value||"member"}:null}).filter(Boolean);await c(`/api/admin/users/${encodeURIComponent(t.user_id)}/workspaces`,{method:"PUT",body:JSON.stringify({memberships:e})}),await d()}function g(){return r.map(t=>{const e=t.user_id===p()?.user_id?"is-active":"",a=t.platform_role==="admin"?"Admin":"Member";return`<button class="ua-user ${e}" data-user-id="${t.user_id}">
        <strong>${t.display_name||t.username}</strong>
        <span>${a} · ${t.memberships.length} workspace</span>
      </button>`}).join("")}function _(t){return m.map(e=>{const a=b(t,e.workspace_id);return`<label class="ua-membership">
        <input type="checkbox" data-workspace-enabled="${e.workspace_id}" ${a?"checked":""} />
        <span>
          <strong>${e.name}</strong>
          <small>${e.workspace_id}</small>
        </span>
        <select data-workspace-role="${e.workspace_id}">
          <option value="member" ${a?.role!=="admin"?"selected":""}>Member</option>
          <option value="admin" ${a?.role==="admin"?"selected":""}>Workspace admin</option>
        </select>
      </label>`}).join("")}function f(){const t=document.getElementById("app"),e=p();t&&(t.innerHTML=`<section class="ua-shell">
    <aside class="ua-rail">
      <div>
        <p class="ua-kicker">Identity</p>
        <h1>User Admin</h1>
        <p class="ua-copy">Gestione utenti, ruoli platform e accesso workspace.</p>
      </div>
      <div class="ua-users">${g()}</div>
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
        <button type="submit">Crea utente</button>
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
            <button type="submit">Salva utente</button>
          </form>
          <section class="ua-card">
            <div class="ua-heading">
              <div>
                <p class="ua-kicker">Workspace</p>
                <h2>Assegnazioni</h2>
              </div>
              <button type="button" id="save-memberships">Salva accessi</button>
            </div>
            <div class="ua-memberships">${_(e)}</div>
          </section>`:'<section class="ua-card"><h2>Nessun utente</h2></section>'}
    </section>
  </section>`,w())}function w(){document.querySelectorAll("[data-user-id]").forEach(e=>{e.addEventListener("click",()=>{o=e.dataset.userId||"",f()})}),document.getElementById("create-user")?.addEventListener("submit",e=>{e.preventDefault(),y(e.currentTarget).catch(l)});const t=p();document.getElementById("edit-user")?.addEventListener("submit",e=>{e.preventDefault(),t&&h(e.currentTarget,t).catch(l)}),document.getElementById("save-memberships")?.addEventListener("click",()=>{t&&v(t).catch(l)})}function l(t){const e=t instanceof Error?t.message:"Errore inatteso";window.alert(e)}d().catch(l);
