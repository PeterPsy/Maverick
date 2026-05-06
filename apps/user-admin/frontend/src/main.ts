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

type PersistenceAdapter = {
  kind: 'json' | 'mongo';
  json_root: string;
  mongo_uri: string | null;
  mongo_database: string;
};

type PersistenceStatus = {
  active_adapter: PersistenceAdapter;
  collections: { name: string; count: number }[];
  restart_required_for_cutover: boolean;
};

type MigrationResult = {
  status: string;
  source_adapter: PersistenceAdapter;
  target_adapter: PersistenceAdapter;
  collections: { name: string; count: number }[];
  restart_required_for_cutover: boolean;
  active_adapter_changed?: boolean;
  env_file?: { path: string; updated: boolean; missing: boolean };
  backend_restart?: { restarted: boolean; scheduled: boolean; detail: string; method: string; healthy: boolean };
  source_cleanup?: { scheduled: boolean; mode: string };
};

type MigrationProgress = {
  target: 'json' | 'mongo';
  phase: 'applying' | 'restarting' | 'polling' | 'complete' | 'failed';
  percent: number;
  title: string;
  detail: string;
};

let users: User[] = [];
let workspaces: Workspace[] = [];
let workspaceApps: WorkspaceApp[] = [];
let persistence: PersistenceStatus | null = null;
let persistenceMigration: MigrationResult | null = null;
let migrationProgress: MigrationProgress | null = null;
let selectedUserId = '';
let pendingDeleteUserId = '';
let migrationTarget: 'json' | 'mongo' | null = null;
let notice: { tone: 'info' | 'success' | 'error'; message: string } | null = null;

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

async function requestPersistenceStatus(): Promise<PersistenceStatus | null> {
  try {
    return await requestJson<PersistenceStatus>('/api/admin/persistence');
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Persistence API unavailable';
    notice = { tone: 'error', message };
    return null;
  }
}

async function requestPersistenceStatusQuiet(): Promise<PersistenceStatus | null> {
  try {
    return await requestJson<PersistenceStatus>('/api/admin/persistence');
  } catch {
    return null;
  }
}

async function refresh() {
  const [usersPayload, workspacesPayload, workspaceAppsPayload, persistencePayload] = await Promise.all([
    requestJson<{ items: User[] }>('/api/admin/users'),
    requestJson<{ items: Workspace[] }>('/api/admin/workspaces'),
    requestJson<{ items: WorkspaceApp[] }>('/api/admin/workspace-apps'),
    requestPersistenceStatus()
  ]);
  users = usersPayload.items;
  workspaces = workspacesPayload.items;
  workspaceApps = workspaceAppsPayload.items;
  persistence = persistencePayload;
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

async function resetSelectedUserPassword(form: HTMLFormElement, user: User) {
  const data = new FormData(form);
  const password = String(data.get('password') || '');
  const confirmation = String(data.get('password_confirmation') || '');
  if (password !== confirmation) {
    throw new Error('Passwords do not match');
  }
  await requestJson<{ status: string }>(`/api/admin/users/${encodeURIComponent(user.user_id)}/password`, {
    method: 'POST',
    body: JSON.stringify({ password })
  });
  form.reset();
  notice = { tone: 'success', message: 'Password updated.' };
  render();
}

async function deleteSelectedUser(user: User) {
  const label = user.display_name || user.username;
  if (pendingDeleteUserId !== user.user_id) {
    pendingDeleteUserId = user.user_id;
    notice = {
      tone: 'info',
      message: `Press Delete user again to confirm permanent removal of ${label}.`
    };
    render();
    return;
  }
  await requestJson<{ status: string }>(`/api/admin/users/${encodeURIComponent(user.user_id)}`, {
    method: 'DELETE'
  });
  selectedUserId = '';
  pendingDeleteUserId = '';
  notice = { tone: 'success', message: `${label} deleted.` };
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

function persistencePayloadForTarget(kind: 'json' | 'mongo') {
  return {
    kind,
    json_root: 'data/control-plane/json',
    mongodb_uri: persistence?.active_adapter.mongo_uri || 'mongodb://127.0.0.1:27017/maverick',
    mongodb_database: persistence?.active_adapter.mongo_database || 'maverick',
    delete_source: true,
    restart_backend: true
  };
}

async function applyPersistenceMigration(kind: 'json' | 'mongo') {
  if (!persistence || persistence.active_adapter.kind === kind) {
    migrationTarget = null;
    render();
    return;
  }
  migrationProgress = {
    target: kind,
    phase: 'applying',
    percent: 18,
    title: `Migration to ${kind.toUpperCase()}`,
    detail: 'Copying the control plane to the target adapter.'
  };
  notice = null;
  render();
  persistenceMigration = await requestJson<MigrationResult>('/api/admin/persistence/migrations/apply', {
    method: 'POST',
    body: JSON.stringify(persistencePayloadForTarget(kind))
  });
  migrationTarget = null;
  migrationProgress = {
    target: kind,
    phase: 'restarting',
    percent: 68,
    title: 'Restart backend',
    detail: persistenceMigration.backend_restart?.detail || 'Backend restart scheduled.'
  };
  render();
  await waitForPersistenceCutover(kind);
}

async function waitForPersistenceCutover(kind: 'json' | 'mongo') {
  const startedAt = Date.now();
  const timeoutMs = 90_000;
  while (Date.now() - startedAt < timeoutMs) {
    migrationProgress = {
      target: kind,
      phase: 'polling',
      percent: 84,
      title: 'Verifying cutover',
      detail: 'Waiting for the backend to become healthy with the new adapter.'
    };
    render();
    const status = await requestPersistenceStatusQuiet();
    if (status?.active_adapter.kind === kind) {
      persistence = status;
      migrationProgress = {
        target: kind,
        phase: 'complete',
        percent: 100,
        title: 'Migration complete',
        detail: `Active adapter: ${kind.toUpperCase()}. Old storage cleanup started after health check.`
      };
      notice = {
        tone: 'success',
        message: `Migration to ${kind.toUpperCase()} complete.`
      };
      render();
      return;
    }
    await new Promise((resolve) => window.setTimeout(resolve, 1500));
  }
  migrationProgress = {
    target: kind,
    phase: 'failed',
    percent: 100,
    title: 'Verification not completed',
    detail: 'The backend did not confirm the new adapter before the timeout. Check service health and logs.'
  };
  notice = {
    tone: 'error',
    message: 'Migration not confirmed before the timeout.'
  };
  render();
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
      const enabledCount = rows.filter((app) => app.status === 'enabled').length;
      const installedCount = rows.filter((app) => app.installed).length;
      return `<details class="ua-app-workspace">
        <summary class="ua-app-workspace-heading">
          <span class="ua-summary-caret material-symbols-rounded" aria-hidden="true">chevron_right</span>
          <span class="ua-app-workspace-icon material-symbols-rounded" aria-hidden="true">deployed_code</span>
          <span>
            <strong>${workspace.name}</strong>
            <small>${workspace.workspace_id} · ${enabledCount}/${installedCount} enabled</small>
          </span>
        </summary>
        <div class="ua-apps">
          ${rows
            .map((app) => {
              const enabled = app.status === 'enabled';
              const installed = app.installed;
              const statusLabel = installed ? app.status : 'not installed';
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
                      <span>Enabled</span>
                    </label>
                    <button type="button" class="ua-secondary" data-app-uninstall="${workspace.workspace_id}:${app.app_id}">
                      <span class="material-symbols-rounded" aria-hidden="true">link_off</span>
                      Uninstall
                    </button>`
                    : `<button type="button" class="ua-secondary" data-app-install="${workspace.workspace_id}:${app.app_id}">
                      <span class="material-symbols-rounded" aria-hidden="true">add_link</span>
                      Install
                    </button>`
                }
              </div>`;
            })
            .join('')}
        </div>
      </details>`;
    })
    .join('');
}

function persistenceHtml() {
  if (!persistence) {
    return `<section class="ua-card ua-persistence">
      <div class="ua-heading">
        <div>
          <p class="ua-kicker">Persistence</p>
          <h2>Control plane adapter</h2>
        </div>
        <span class="ua-pill ua-pill-muted">offline</span>
      </div>
      <p class="ua-card-copy">The core persistence surfaces are not available in the active backend.</p>
    </section>`;
  }
  const active = persistence.active_adapter;
  const totalDocuments = persistence.collections.reduce((total, item) => total + item.count, 0);
  const progress = migrationProgress
    ? `<div class="ua-migration-progress ${migrationProgress.phase === 'failed' ? 'is-failed' : ''} ${migrationProgress.phase === 'complete' ? 'is-complete' : ''}">
        <div class="ua-migration-progress-heading">
          <span class="material-symbols-rounded" aria-hidden="true">${migrationProgress.phase === 'complete' ? 'check_circle' : migrationProgress.phase === 'failed' ? 'error' : 'sync'}</span>
          <span>
            <strong>${migrationProgress.title}</strong>
            <small>${migrationProgress.detail}</small>
          </span>
          <em>${migrationProgress.percent}%</em>
        </div>
        <div class="ua-progress-track" aria-label="Progresso migrazione" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${migrationProgress.percent}">
          <span style="width: ${migrationProgress.percent}%"></span>
        </div>
      </div>`
    : '';
  const result = persistenceMigration
    ? `<div class="ua-migration-result">
        <span class="material-symbols-rounded" aria-hidden="true">task_alt</span>
        <span>
          <strong>Ultima migrazione</strong>
          <small>${persistenceMigration.collections.reduce((total, item) => total + item.count, 0)} documents · target ${persistenceMigration.target_adapter.kind} · cleanup ${persistenceMigration.source_cleanup?.scheduled ? 'scheduled' : 'not requested'}</small>
        </span>
      </div>`
    : '';
  const jsonActive = active.kind === 'json';
  const mongoActive = active.kind === 'mongo';
  const locked = migrationProgress && migrationProgress.phase !== 'complete' && migrationProgress.phase !== 'failed';
  return `<section class="ua-card ua-persistence">
    <div class="ua-heading">
      <div>
        <p class="ua-kicker">Persistence</p>
        <h2>Control plane adapter</h2>
      </div>
      <span class="ua-pill">${totalDocuments} documents</span>
    </div>
    <div class="ua-adapter-cards">
      <button type="button" class="ua-adapter-card ${jsonActive ? 'is-active' : ''}" ${jsonActive || locked ? 'disabled' : 'data-adapter-target="json"'}>
        <span class="ua-adapter-card-icon material-symbols-rounded" aria-hidden="true">${jsonActive ? 'check_circle' : 'database'}</span>
        <span>
          <strong>JSON</strong>
          <small>${jsonActive ? active.json_root : 'data/control-plane/json'}</small>
        </span>
        <em>${jsonActive ? 'Current' : 'Migrate here'}</em>
      </button>
      <button type="button" class="ua-adapter-card ${mongoActive ? 'is-active' : ''}" ${mongoActive || locked ? 'disabled' : 'data-adapter-target="mongo"'}>
        <span class="ua-adapter-card-icon material-symbols-rounded" aria-hidden="true">${mongoActive ? 'check_circle' : 'database'}</span>
        <span>
          <strong>Mongo</strong>
          <small>${mongoActive ? active.mongo_database : 'mongodb://127.0.0.1:27017/maverick'}</small>
        </span>
        <em>${mongoActive ? 'Current' : 'Migrate here'}</em>
      </button>
    </div>
    ${progress}
    ${result}
  </section>`;
}

function persistenceMigrationModalHtml() {
  if (!migrationTarget || !persistence) return '';
  const source = persistence.active_adapter.kind.toUpperCase();
  const target = migrationTarget.toUpperCase();
  return `<div class="ua-modal-backdrop" role="presentation">
    <section class="ua-modal" role="dialog" aria-modal="true" aria-labelledby="adapter-migration-title">
      <div class="ua-heading">
        <div>
          <p class="ua-kicker">Confirm migration</p>
          <h2 id="adapter-migration-title">${source} → ${target}</h2>
        </div>
        <button type="button" class="ua-icon-button" id="close-migration-modal" aria-label="Close">
          <span class="material-symbols-rounded" aria-hidden="true">close</span>
        </button>
      </div>
      <p class="ua-card-copy">The migration copies the entire control plane to the new adapter, updates the backend configuration, restarts the core, and deletes the old storage only after the new backend responds healthy.</p>
      <div class="ua-modal-actions">
        <button type="button" class="ua-secondary" id="cancel-migration">Cancel</button>
        <button type="button" class="ua-danger" id="confirm-migration" ${migrationProgress && migrationProgress.phase !== 'complete' && migrationProgress.phase !== 'failed' ? 'disabled' : ''}>
          <span class="material-symbols-rounded" aria-hidden="true">sync_alt</span>
          Migrate and delete
        </button>
      </div>
    </section>
  </div>`;
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
        <p class="ua-copy">Manage users, platform roles, and workspace access.</p>
      </div>
      <div class="ua-users">${userListHtml()}</div>
    </aside>
    <section class="ua-main">
      <div class="ua-content">
        ${noticeHtml()}
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
        ${persistenceHtml()}
        ${
          user
            ? `<div class="ua-profile-row">
            <form class="ua-card ua-detail" id="edit-user">
            <div class="ua-heading">
              <div>
                <p class="ua-kicker">Selected user</p>
                <h2>${user.display_name || user.username}</h2>
              </div>
              <span class="ua-pill">${user.is_active ? 'active' : 'disabled'}</span>
            </div>
            <div class="ua-grid">
              <label>Name<input name="display_name" value="${user.display_name || ''}" /></label>
              <label>Email<input name="email" type="email" value="${user.email || ''}" /></label>
              <label>Platform role<select name="platform_role">
                <option value="member" ${user.platform_role === 'member' ? 'selected' : ''}>Member</option>
                <option value="admin" ${user.platform_role === 'admin' ? 'selected' : ''}>Admin</option>
              </select></label>
              <label>Account type<select name="account_type">
                <option value="standard" ${user.account_type === 'standard' ? 'selected' : ''}>Standard</option>
                <option value="facilitated" ${user.account_type === 'facilitated' ? 'selected' : ''}>Facilitated</option>
              </select></label>
            </div>
            <label class="ua-toggle"><input name="is_active" type="checkbox" ${user.is_active ? 'checked' : ''} /> Account active</label>
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
              ${pendingDeleteUserId === user.user_id ? 'Confirm delete' : 'Delete user'}
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
            <div class="ua-memberships">${membershipHtml(user)}</div>
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
            <div class="ua-app-workspaces">${workspaceAppHtml()}</div>
          </details>`
            : '<section class="ua-card"><h2>No users</h2></section>'
        }
      </div>
    </section>
    ${persistenceMigrationModalHtml()}
  </section>`;
  bindEvents();
}

function bindEvents() {
  document.getElementById('dismiss-notice')?.addEventListener('click', () => {
    notice = null;
    render();
  });
  document.querySelectorAll<HTMLButtonElement>('[data-user-id]').forEach((button) => {
    button.addEventListener('click', () => {
      selectedUserId = button.dataset.userId || '';
      pendingDeleteUserId = '';
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
  document.getElementById('reset-password')?.addEventListener('submit', (event) => {
    event.preventDefault();
    if (user) resetSelectedUserPassword(event.currentTarget as HTMLFormElement, user).catch(showError);
  });
  document.getElementById('delete-user')?.addEventListener('click', () => {
    if (user) deleteSelectedUser(user).catch(showError);
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
  document.querySelectorAll<HTMLButtonElement>('[data-adapter-target]').forEach((button) => {
    button.addEventListener('click', () => {
      const target = button.dataset.adapterTarget;
      if (target === 'json' || target === 'mongo') {
        migrationTarget = target;
        render();
      }
    });
  });
  document.getElementById('close-migration-modal')?.addEventListener('click', () => {
    migrationTarget = null;
    render();
  });
  document.getElementById('cancel-migration')?.addEventListener('click', () => {
    migrationTarget = null;
    render();
  });
  document.getElementById('confirm-migration')?.addEventListener('click', () => {
    if (migrationTarget) {
      applyPersistenceMigration(migrationTarget).catch(showError);
    }
  });
}

function showError(error: unknown) {
  const message = error instanceof Error ? error.message : 'Unexpected error';
  notice = { tone: 'error', message };
  render();
}

function noticeHtml() {
  if (!notice) return '';
  return `<div class="ua-notice ua-notice-${notice.tone}">
    <span class="material-symbols-rounded" aria-hidden="true">${notice.tone === 'error' ? 'error' : notice.tone === 'success' ? 'task_alt' : 'info'}</span>
    <span>${notice.message}</span>
    <button type="button" class="ua-icon-button" id="dismiss-notice" aria-label="Close">
      <span class="material-symbols-rounded" aria-hidden="true">close</span>
    </button>
  </div>`;
}

refresh().catch(showError);
