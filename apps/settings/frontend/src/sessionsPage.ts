import type { PlatformSettings, RuntimeSessionItem } from './adminApi';
import type { SettingsPanelState } from './settingsDrafts';
import { escapeHtml, escapeAttr } from './html';

export type SessionsView = { scope: 'workspace' | 'server'; query: string; status: string; page: number };
export const SESSION_PAGE_SIZE = 20;
export const createSessionsView = (): SessionsView => ({ scope: 'workspace', query: '', status: '', page: 0 });

export function scopedSessions(settings: PlatformSettings, view: SessionsView): RuntimeSessionItem[] {
  const sessions = settings.runtime.all_sessions || settings.runtime.sessions || [];
  return view.scope === 'server' && settings.runtime.cleanup_scope === 'server'
    ? sessions : sessions.filter(session => session.workspace_id === settings.workspace.workspace_id);
}

export function filteredSessions(settings: PlatformSettings, view: SessionsView) {
  const query = view.query.trim().toLowerCase();
  return scopedSessions(settings, view).filter(session => (!view.status || session.status === view.status)
    && `${session.session_id} ${session.agent_id} ${session.workspace_name || session.workspace_id} ${session.provider_id}`.toLowerCase().includes(query));
}

export function sessionsPageHtml(settings: PlatformSettings, state: SettingsPanelState, view: SessionsView) {
  const scoped = scopedSessions(settings, view);
  const filtered = filteredSessions(settings, view);
  const pages = Math.max(1, Math.ceil(filtered.length / SESSION_PAGE_SIZE));
  view.page = Math.min(view.page, pages - 1);
  const visible = filtered.slice(view.page * SESSION_PAGE_SIZE, (view.page + 1) * SESSION_PAGE_SIZE);
  const allowed = settings.runtime.cleanup_allowed === true;
  const scopeLabel = view.scope === 'server' ? 'All workspaces on this server' : settings.workspace.name;
  return `<section class="settings-card settings-runtime-settings-card">
    <div class="settings-heading"><div><p class="settings-kicker">${escapeHtml(scopeLabel)}</p><h2>Runtime sessions</h2></div>
      <button type="button" id="settings-clear-all-runtime" class="settings-danger" ${!allowed || !scoped.length || state.clearingAllRuntime ? 'disabled' : ''}>${state.clearingAllRuntime ? 'Deleting…' : `Delete ${scoped.length} sessions`}</button>
    </div>
    <p class="settings-card-copy">Deletion stops active agents and removes their conversations, turns and runtime files. Review the confirmation before continuing.</p>
    <div class="settings-grid settings-session-filters">
      <label>Search sessions<input id="settings-session-search" type="search" value="${escapeAttr(view.query)}" placeholder="Agent, workspace or session" /></label>
      <label>Status<select id="settings-session-status"><option value="">All statuses</option>${Array.from(new Set(scoped.map(session => session.status))).sort().map(status => `<option value="${escapeAttr(status)}" ${view.status === status ? 'selected' : ''}>${escapeHtml(status)}</option>`).join('')}</select></label>
      ${settings.runtime.cleanup_scope === 'server' ? `<label>View scope<select id="settings-session-scope"><option value="workspace" ${view.scope === 'workspace' ? 'selected' : ''}>Current workspace</option><option value="server" ${view.scope === 'server' ? 'selected' : ''}>Entire server</option></select></label>` : ''}
    </div>
    ${!allowed ? '<p role="status">You do not have permission to delete sessions in this workspace.</p>' : ''}
    <div class="settings-platform-runtime-list">${visible.map(session => sessionRowHtml(session, allowed, state)).join('') || '<p role="status">No sessions match this view.</p>'}</div>
    <div class="settings-pagination"><span role="status">${filtered.length} sessions · Page ${view.page + 1} of ${pages}</span>
      <button type="button" id="settings-sessions-prev" class="settings-secondary" ${view.page === 0 ? 'disabled' : ''}>Previous</button>
      <button type="button" id="settings-sessions-next" class="settings-secondary" ${view.page + 1 >= pages ? 'disabled' : ''}>Next</button>
    </div>
    ${state.cleanupError ? `<p class="settings-inline-error" role="alert">${escapeHtml(state.cleanupError)}</p>` : ''}
  </section>`;
}

function sessionRowHtml(session: RuntimeSessionItem, allowed: boolean, state: SettingsPanelState) {
  const busy = state.cleaningSessionIds.has(session.session_id) || state.clearingAllRuntime;
  return `<article class="settings-platform-runtime-row" data-runtime-row="${escapeAttr(session.session_id)}">
    <span class="settings-platform-icon material-symbols-rounded" aria-hidden="true">terminal</span>
    <span class="settings-platform-runtime-copy"><span class="settings-platform-runtime-title"><strong>${escapeHtml(session.agent_id || session.session_id)}</strong>
      <button type="button" class="settings-secondary" data-runtime-clear="${escapeAttr(session.session_id)}" aria-label="Delete session ${escapeAttr(session.agent_id || session.session_id)}" ${!allowed || busy ? 'disabled' : ''}>${busy ? 'Deleting…' : 'Delete'}</button></span>
      <small>${escapeHtml(session.workspace_name || session.workspace_id)} · ${escapeHtml(session.status)} · ${escapeHtml(session.effective_mode)}</small>
      ${session.recovery_reason_code ? `<small class="settings-inline-error">${escapeHtml(session.recovery_reason_code)}</small>` : ''}
      ${session.agentic_containment?.status === 'NO-GO' ? `<small class="settings-inline-error">Contained: ${escapeHtml(session.agentic_containment.reason_code || 'Unavailable')}</small>` : ''}
      <code>${escapeHtml(session.session_id)}</code></span>
  </article>`;
}
