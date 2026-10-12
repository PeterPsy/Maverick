import { expect, it } from 'vitest';
import { createSessionsView, filteredSessions, sessionsPageHtml } from './sessionsPage';
import { createSettingsPanelState } from './settingsDrafts';
import type { PlatformSettings } from './adminApi';

it('starts with the current workspace in Default, bounds rows and exposes server scope explicitly', () => {
  const settings = { workspace: { workspace_id: 'default', name: 'Default' }, runtime: {
    cleanup_allowed: true, cleanup_scope: 'server', all_sessions: Array.from({ length: 60 }, (_, index) => ({
      session_id: `session-${index}`, workspace_id: index < 40 ? 'default' : 'other', agent_id: `agent-${index}`, status: index % 2 ? 'active' : 'closed', effective_mode: 'sandbox',
    })),
  } } as PlatformSettings;
  const view = createSessionsView();
  expect(filteredSessions(settings, view)).toHaveLength(40);
  const html = sessionsPageHtml(settings, createSettingsPanelState(), view);
  expect(html.match(/data-runtime-row=/g)).toHaveLength(20);
  expect(html).toContain('Current workspace');
  view.scope = 'server'; view.query = 'other';
  expect(filteredSessions(settings, view)).toHaveLength(20);
});
