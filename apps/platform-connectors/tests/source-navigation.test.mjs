import assert from 'node:assert/strict';
import { test } from 'node:test';
import { ownerAppId, sidebarWidgetId, sidebarContext, sourceFromParams, sourceSelection, tabFromParams } from '../frontend/src/sourceNavigation.ts';

test('source routes accept bounded identifiers and reject malformed params', () => {
  assert.equal(sourceFromParams({ source: 'instagram' }), 'instagram');
  for (const params of [null, [], { source: 1 }, { source: '../github' }, { source: 'x'.repeat(33) }])
    assert.equal(sourceFromParams(params), '');
});

test('tab routes retain explicit workspace selection without accepting other views', () => {
  for (const tab of ['explore', 'collections', 'history']) assert.equal(tabFromParams({ tab }), tab);
  assert.equal(tabFromParams({ tab: 'settings' }), null);
  assert.equal(tabFromParams(null), null);
});

test('sidebar context is tied to the declared owner, widget, slot and active app', () => {
  const context = { content: { kind: 'shell.sidebar.primary', workspace_id: 'default',
    payload: { active_app_id: ownerAppId, active_app_params: { source: 'github' }, is_mobile_layout: true } } };
  const message = { type: 'maverick.widget.context-changed', owner_app_id: ownerAppId, widget_id: sidebarWidgetId, context };
  assert.deepEqual(sidebarContext(message), { workspaceId: 'default', source: 'github', isMobile: true });
  for (const override of [{ type: 'other' }, { owner_app_id: 'browser' }, { widget_id: 'other' },
    { context: {} }, { context: { content: { ...context.content, kind: 'chat.attachment' } } },
    { context: { content: { ...context.content, payload: { active_app_id: 'storage' } } } }])
    assert.equal(sidebarContext({ ...message, ...override }), null);
});

test('selection relay rejects other apps and malformed source identifiers', () => {
  const message = { type: 'maverick.app.selection-changed', owner_app_id: ownerAppId, selection: { source: 'rss' } };
  assert.equal(sourceSelection(message), 'rss');
  assert.equal(sourceSelection({ ...message, owner_app_id: 'storage' }), '');
  assert.equal(sourceSelection({ ...message, selection: { source: '//github' } }), '');
});
