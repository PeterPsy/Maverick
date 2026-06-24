import type { Workspace, WorkspaceApp } from './adminApi';
import { escapeAttr, escapeHtml } from './html';

export function workspaceAppsPageHtml({
  workspaceApps,
  workspaces,
}: {
  workspaceApps: WorkspaceApp[];
  workspaces: Workspace[];
}) {
  return `<section class="settings-card">
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
      return `<details class="settings-app-workspace">
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
  return `<div class="settings-app-row">
    <span class="settings-app-icon material-symbols-rounded" aria-hidden="true">${escapeHtml(appIcon(app))}</span>
    <span class="settings-app-copy">
      <strong>${escapeHtml(app.name)}</strong>
      <small>${escapeHtml(app.app_id)} · v${escapeHtml(app.version)} · ${escapeHtml(statusLabel)}</small>
    </span>
    ${
      installed
        ? `<label class="settings-switch">
          <input type="checkbox" data-app-toggle="${escapeAttr(appKey)}" ${enabled ? 'checked' : ''} />
          <span>Enabled</span>
        </label>
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

function appIcon(app: WorkspaceApp): string {
  if (app.status !== 'enabled') {
    return 'hide_source';
  }
  const iconByAppId: Record<string, string> = {
    agents: 'smart_toy',
    'app-store': 'storefront',
    'base-shell': 'dashboard',
    browser: 'language',
    calendar: 'calendar_month',
    chat: 'forum',
    checklist: 'checklist',
    crm: 'contacts',
    'developer-kit': 'developer_board',
    'docs-studio': 'description',
    'document-generator': 'description',
    'dynamic-views': 'dashboard_customize',
    'gmail-app': 'mail',
    mail: 'mail',
    memory: 'database',
    'maverick-monitor': 'monitor_heart',
    settings: 'admin_panel_settings',
    senses: 'sensors',
    skills: 'school',
    speech: 'record_voice_over',
    storage: 'cloud',
    vault: 'key',
    'website-studio': 'web_asset'
  };
  return iconByAppId[app.app_id] || 'apps';
}
