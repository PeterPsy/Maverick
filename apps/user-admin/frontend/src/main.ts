import './styles.css';

type Membership = {
  workspace_id: string;
  role: 'admin' | 'member';
  status: string;
};

type User = {
  user_id: string;
  username: string;
  email: string | null;
  display_name: string | null;
  platform_role: 'admin' | 'member';
  account_type: string;
  is_active: boolean;
  memberships: Membership[];
};

type Workspace = {
  workspace_id: string;
  name: string;
  status: string;
};

type WorkspaceApp = {
  workspace_id: string;
  workspace_name: string;
  app_id: string;
  name: string;
  description: string;
  version: string;
  source_id: string;
  installed: boolean;
  status: 'uninstalled' | 'installed' | 'enabled' | 'disabled' | 'failed' | 'updating' | 'rolled_back';
};

let users: User[] = [];
let workspaces: Workspace[] = [];
let workspaceApps: WorkspaceApp[] = [];
let selectedUserId = '';

async function requestJson<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || payload.error || `Request failed ${response.status}`);
  }
  return payload as T;
}

function selectedUser(): User | undefined {
  return users.find((user) => user.user_id === selectedUserId) || users[0];
}

function membershipFor(user: User, workspaceId: string): Membership | undefined {
  return user.memberships.find((membership) => membership.workspace_id === workspaceId);
}

async function refresh() {
  const [usersPayload, workspacesPayload, workspaceAppsPayload] = await Promise.all([
    requestJson<{ items: User[] }>('/api/admin/users'),
    requestJson<{ items: Workspace[] }>('/api/admin/workspaces'),
    requestJson<{ items: WorkspaceApp[] }>('/api/admin/workspace-apps')
  ]);
  users = usersPayload.items;
  workspaces = workspacesPayload.items;
  workspaceApps = workspaceAppsPayload.items;
  if (!selectedUserId || !users.some((user) => user.user_id === selectedUserId)) {
    selectedUserId = users[0]?.user_id || '';
  }
  render();
}

async function createUser(form: HTMLFormElement) {
  const data = new FormData(form);
  const payload = {
    username: String(data.get('username') || ''),
    password: String(data.get('password') || ''),
    display_name: String(data.get('display_name') || ''),
    email: String(data.get('email') || ''),
    platform_role: String(data.get('platform_role') || 'member')
  };
  const created = await requestJson<User>('/api/admin/users', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
  selectedUserId = created.user_id;
  form.reset();
  await refresh();
}

async function updateSelectedUser(form: HTMLFormElement, user: User) {
  const data = new FormData(form);
  await requestJson<User>(`/api/admin/users/${encodeURIComponent(user.user_id)}`, {
    method: 'PATCH',
    body: JSON.stringify({
      display_name: String(data.get('display_name') || ''),
      email: String(data.get('email') || ''),
      platform_role: String(data.get('platform_role') || 'member'),
      account_type: String(data.get('account_type') || 'standard'),
      is_active: data.get('is_active') === 'on'
    })
  });
  await refresh();
}

async function updateMemberships(user: User) {
  const memberships = workspaces
    .map((workspace) => {
      const checkbox = document.querySelector<HTMLInputElement>(`[data-workspace-enabled="${workspace.workspace_id}"]`);
      const role = document.querySelector<HTMLSelectElement>(`[data-workspace-role="${workspace.workspace_id}"]`);
      return checkbox?.checked ? { workspace_id: workspace.workspace_id, role: role?.value || 'member' } : null;
    })
    .filter(Boolean);
  await requestJson<User>(`/api/admin/users/${encodeURIComponent(user.user_id)}/workspaces`, {
    method: 'PUT',
    body: JSON.stringify({ memberships })
  });
  await refresh();
}

async function installWorkspaceApp(app: WorkspaceApp) {
  await requestJson(`/api/admin/workspace-apps/${encodeURIComponent(app.workspace_id)}/${encodeURIComponent(app.app_id)}`, {
    method: 'POST',
    body: JSON.stringify({ source_id: app.source_id, enabled: true })
  });
  await refresh();
}

async function setWorkspaceAppStatus(app: WorkspaceApp, enabled: boolean) {
  await requestJson(`/api/admin/workspace-apps/${encodeURIComponent(app.workspace_id)}/${encodeURIComponent(app.app_id)}`, {
    method: 'PATCH',
    body: JSON.stringify({ status: enabled ? 'enabled' : 'disabled' })
  });
  await refresh();
}

async function uninstallWorkspaceApp(app: WorkspaceApp) {
  await requestJson(`/api/admin/workspace-apps/${encodeURIComponent(app.workspace_id)}/${encodeURIComponent(app.app_id)}`, {
    method: 'DELETE',
    body: JSON.stringify({})
  });
  await refresh();
}

function userListHtml() {
  return users
    .map((user) => {
      const active = user.user_id === selectedUser()?.user_id ? 'is-active' : '';
      const role = user.platform_role === 'admin' ? 'Admin' : 'Member';
      return `<button class="ua-user ${active}" data-user-id="${user.user_id}">
        <span class="ua-user-icon material-symbols-rounded" aria-hidden="true">account_circle</span>
        <span class="ua-user-copy">
          <strong>${user.display_name || user.username}</strong>
          <span>${role} · ${user.memberships.length} workspace</span>
        </span>
      </button>`;
    })
    .join('');
}

function membershipHtml(user: User) {
  return workspaces
    .map((workspace) => {
      const membership = membershipFor(user, workspace.workspace_id);
      return `<label class="ua-membership">
        <input type="checkbox" data-workspace-enabled="${workspace.workspace_id}" ${membership ? 'checked' : ''} />
        <span class="ua-membership-icon material-symbols-rounded" aria-hidden="true">workspaces</span>
        <span>
          <strong>${workspace.name}</strong>
          <small>${workspace.workspace_id}</small>
        </span>
        <select data-workspace-role="${workspace.workspace_id}">
          <option value="member" ${membership?.role !== 'admin' ? 'selected' : ''}>Member</option>
          <option value="admin" ${membership?.role === 'admin' ? 'selected' : ''}>Workspace admin</option>
        </select>
      </label>`;
    })
    .join('');
}

function workspaceAppHtml() {
  return workspaces
    .map((workspace) => {
      const rows = workspaceApps.filter((app) => app.workspace_id === workspace.workspace_id);
      return `<article class="ua-app-workspace">
        <div class="ua-app-workspace-heading">
          <span class="material-symbols-rounded" aria-hidden="true">deployed_code</span>
          <div>
            <strong>${workspace.name}</strong>
            <small>${workspace.workspace_id}</small>
          </div>
        </div>
        <div class="ua-apps">
          ${rows
            .map((app) => {
              const enabled = app.status === 'enabled';
              const installed = app.installed;
              const statusLabel = installed ? app.status : 'non installata';
              return `<div class="ua-app-row">
                <span class="ua-app-icon material-symbols-rounded" aria-hidden="true">${enabled ? 'apps' : 'hide_source'}</span>
                <span class="ua-app-copy">
                  <strong>${app.name}</strong>
                  <small>${app.app_id} · v${app.version} · ${statusLabel}</small>
                </span>
                ${
                  installed
                    ? `<label class="ua-switch">
                      <input type="checkbox" data-app-toggle="${workspace.workspace_id}:${app.app_id}" ${enabled ? 'checked' : ''} />
                      <span>Abilitata</span>
                    </label>
                    <button type="button" class="ua-secondary" data-app-uninstall="${workspace.workspace_id}:${app.app_id}">
                      <span class="material-symbols-rounded" aria-hidden="true">link_off</span>
                      Uninstall
                    </button>`
                    : `<button type="button" class="ua-secondary" data-app-install="${workspace.workspace_id}:${app.app_id}">
                      <span class="material-symbols-rounded" aria-hidden="true">add_link</span>
                      Installa
                    </button>`
                }
              </div>`;
            })
            .join('')}
        </div>
      </article>`;
    })
    .join('');
}

function render() {
  const root = document.getElementById('app');
  const user = selectedUser();
  if (!root) return;
  root.innerHTML = `<section class="ua-shell">
    <aside class="ua-rail">
      <div>
        <p class="ua-kicker">Maverick</p>
        <h1>User Admin</h1>
        <p class="ua-copy">Gestione utenti, ruoli platform e accesso workspace.</p>
      </div>
      <div class="ua-users">${userListHtml()}</div>
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
      ${
        user
          ? `<form class="ua-card ua-detail" id="edit-user">
            <div class="ua-heading">
              <div>
                <p class="ua-kicker">Utente selezionato</p>
                <h2>${user.display_name || user.username}</h2>
              </div>
              <span class="ua-pill">${user.is_active ? 'attivo' : 'disattivato'}</span>
            </div>
            <div class="ua-grid">
              <label>Nome<input name="display_name" value="${user.display_name || ''}" /></label>
              <label>Email<input name="email" type="email" value="${user.email || ''}" /></label>
              <label>Ruolo platform<select name="platform_role">
                <option value="member" ${user.platform_role === 'member' ? 'selected' : ''}>Member</option>
                <option value="admin" ${user.platform_role === 'admin' ? 'selected' : ''}>Admin</option>
              </select></label>
              <label>Tipo account<select name="account_type">
                <option value="standard" ${user.account_type === 'standard' ? 'selected' : ''}>Standard</option>
                <option value="facilitated" ${user.account_type === 'facilitated' ? 'selected' : ''}>Facilitated</option>
              </select></label>
            </div>
            <label class="ua-toggle"><input name="is_active" type="checkbox" ${user.is_active ? 'checked' : ''} /> Account attivo</label>
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
            <div class="ua-memberships">${membershipHtml(user)}</div>
          </section>
          <section class="ua-card">
            <div class="ua-heading">
              <div>
                <p class="ua-kicker">App per workspace</p>
                <h2>Installazione e visibilità</h2>
              </div>
            </div>
            <p class="ua-card-copy">Installata significa montata nel workspace. Solo le app abilitate sono visibili agli utenti e servite dal core.</p>
            <div class="ua-app-workspaces">${workspaceAppHtml()}</div>
          </section>`
          : '<section class="ua-card"><h2>Nessun utente</h2></section>'
      }
    </section>
  </section>`;
  bindEvents();
}

function bindEvents() {
  document.querySelectorAll<HTMLButtonElement>('[data-user-id]').forEach((button) => {
    button.addEventListener('click', () => {
      selectedUserId = button.dataset.userId || '';
      render();
    });
  });
  document.getElementById('create-user')?.addEventListener('submit', (event) => {
    event.preventDefault();
    createUser(event.currentTarget as HTMLFormElement).catch(showError);
  });
  const user = selectedUser();
  document.getElementById('edit-user')?.addEventListener('submit', (event) => {
    event.preventDefault();
    if (user) updateSelectedUser(event.currentTarget as HTMLFormElement, user).catch(showError);
  });
  document.getElementById('save-memberships')?.addEventListener('click', () => {
    if (user) updateMemberships(user).catch(showError);
  });
  document.querySelectorAll<HTMLInputElement>('[data-app-toggle]').forEach((input) => {
    input.addEventListener('change', () => {
      const app = workspaceApps.find((item) => `${item.workspace_id}:${item.app_id}` === input.dataset.appToggle);
      if (app) setWorkspaceAppStatus(app, input.checked).catch(showError);
    });
  });
  document.querySelectorAll<HTMLButtonElement>('[data-app-install]').forEach((button) => {
    button.addEventListener('click', () => {
      const app = workspaceApps.find((item) => `${item.workspace_id}:${item.app_id}` === button.dataset.appInstall);
      if (app) installWorkspaceApp(app).catch(showError);
    });
  });
  document.querySelectorAll<HTMLButtonElement>('[data-app-uninstall]').forEach((button) => {
    button.addEventListener('click', () => {
      const app = workspaceApps.find((item) => `${item.workspace_id}:${item.app_id}` === button.dataset.appUninstall);
      if (app) uninstallWorkspaceApp(app).catch(showError);
    });
  });
}

function showError(error: unknown) {
  const message = error instanceof Error ? error.message : 'Errore inatteso';
  window.alert(message);
}

refresh().catch(showError);
