import type { Workspace, WorkspaceApp } from './adminApi';
import { escapeAttr, escapeHtml } from './html';
import { bouncyToggleHtml } from './bouncyToggle';

export function workspaceAppsPageHtml({
  workspaceApps,
  workspaces,
}: {
  workspaceApps: WorkspaceApp[];
  workspaces: Workspace[];
}) {
  return `<details class="settings-card"><summary>Create a workspace</summary><form id="create-workspace" class="settings-grid">
    <label>Name<input name="name" required /></label><label>Description<input name="description" /></label><button type="submit">Create workspace</button>
    </form></details><section class="settings-card">
      <div class="settings-heading">
        <div>
          <p class="settings-kicker">Workspace apps</p>
          <h2>Installation and visibility</h2>
        </div>
      </div>
      <p class="settings-card-copy">Installed means the app has a workspace binding. Only enabled apps are visible to users and served by the core.</p>
      <div class="settings-app-workspaces">${workspaceAppRowsHtml(workspaces, workspaceApps)}</div>
    </section>`;
}

function workspaceAppRowsHtml(workspaces: Workspace[], workspaceApps: WorkspaceApp[]) {
  return workspaces
    .map((workspace) => {
      const rows = workspaceApps.filter((app) => app.workspace_id === workspace.workspace_id);
      const enabledCount = rows.filter((app) => app.status === 'enabled').length;
      const installedCount = rows.filter((app) => app.installed).length;
      return `<details class="settings-app-workspace" data-workspace-row="${escapeAttr(workspace.workspace_id)}">
        <summary class="settings-app-workspace-heading">
          <span class="settings-summary-caret material-symbols-rounded" aria-hidden="true">chevron_right</span>
          <span class="settings-app-workspace-icon material-symbols-rounded" aria-hidden="true">deployed_code</span>
          <span>
            <strong>${escapeHtml(workspace.name)}</strong>
            <small>${escapeHtml(workspace.workspace_id)} · ${enabledCount}/${installedCount} enabled</small>
          </span>
        </summary>
        <div class="settings-apps">
          ${rows.map(workspaceAppRowHtml).join('')}
        </div>
      </details>`;
    })
    .join('');
}

function workspaceAppRowHtml(app: WorkspaceApp) {
  const enabled = app.status === 'enabled';
  const installed = app.installed;
  const statusLabel = installed ? app.status : 'not installed';
  const appKey = `${app.workspace_id}:${app.app_id}`;
  return `<div class="settings-app-row" data-app-row="${escapeAttr(appKey)}">
    ${app.logo?.kind === 'image' ? `<img class="settings-app-icon" src="${escapeAttr(app.logo.value)}" alt="" />` : `<span class="settings-app-icon material-symbols-rounded" aria-hidden="true">${escapeHtml(app.logo?.kind === 'glyph' ? app.logo.value : 'apps')}</span>`}
    <span class="settings-app-copy">
      <strong>${escapeHtml(app.name)}</strong>
      <small>${escapeHtml(app.app_id)} · v${escapeHtml(app.version)} · ${escapeHtml(statusLabel)}</small>
    </span>
    ${
      installed
        ? `${bouncyToggleHtml(`<input type="checkbox" role="switch" aria-label="Enable ${escapeAttr(app.name)} in ${escapeAttr(app.workspace_name)}" data-app-toggle="${escapeAttr(appKey)}" ${enabled ? 'checked' : ''} />`, 'Enabled', 'settings-switch')}
        <button type="button" class="settings-secondary" data-app-uninstall="${escapeAttr(appKey)}">
          <span class="material-symbols-rounded" aria-hidden="true">link_off</span>
          Uninstall
        </button>`
        : `<button type="button" class="settings-secondary" data-app-install="${escapeAttr(appKey)}">
          <span class="material-symbols-rounded" aria-hidden="true">add_link</span>
          Install
        </button>`
    }
  </div>`;
}
