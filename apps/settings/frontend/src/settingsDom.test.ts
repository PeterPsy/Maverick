// @vitest-environment happy-dom
import { beforeEach, expect, it, vi } from 'vitest';
import { clearSettingsDomCache, clearSettingsDrafts, patchSettingsDom, rememberSettingsDrafts } from './settingsDom';
import { beginSettingsBindings, bindControl } from './controlBindings';
import { usersPageHtml } from './userPages';
import type { User } from './adminApi';
import { settingsPageDomKey } from './pages';
import { escapeAttr } from './html';

let root: HTMLElement;
beforeEach(() => { clearSettingsDomCache(); document.body.innerHTML = '<div id="app"></div>'; root = document.getElementById('app')!; rememberSettingsDrafts(root); });

it('retains input, selection, disclosures and chart islands during unrelated updates', () => {
  const html = (notice: string) => `<div class="settings-content" data-render-key="page:users"><header>${notice}</header><form id="edit-user"><input name="email" value="saved" /></form><details id="advanced"><summary>Advanced</summary></details><div data-usage-history-chart></div></div>`;
  patchSettingsDom(root, html('Before'));
  const input = root.querySelector('input')!;
  input.focus(); input.value = 'unsaved'; input.setSelectionRange(2, 5); input.dispatchEvent(new Event('input', { bubbles: true }));
  root.querySelector('details')!.open = true;
  const chart = root.querySelector('[data-usage-history-chart]')!; chart.innerHTML = '<svg></svg>';
  patchSettingsDom(root, html('After'));
  expect(root.querySelector('input')).toBe(input);
  expect(document.activeElement).toBe(input);
  expect(input.value).toBe('unsaved');
  expect(input.selectionStart).toBe(2);
  expect(root.querySelector('details')!.open).toBe(true);
  expect(chart.querySelector('svg')).not.toBeNull();
});

it('keeps page drafts when navigating away and back, and clears them on a workspace reset', () => {
  const html = (page: string) => `<div data-render-key="page:${page}"><input id="draft-${page}" value="saved" /></div>`;
  patchSettingsDom(root, html('voice'));
  const input = root.querySelector('input')!; input.value = 'draft'; input.dispatchEvent(new Event('input', { bubbles: true }));
  patchSettingsDom(root, html('users')); patchSettingsDom(root, html('voice'));
  expect(root.querySelector('input')).toBe(input);
  expect(input.value).toBe('draft');
  patchSettingsDom(root, html('users')); clearSettingsDomCache(); patchSettingsDom(root, html('voice'));
  expect(root.querySelector('input')).not.toBe(input);
});

it('replaces event handlers when controls are retained', () => {
  patchSettingsDom(root, '<button id="save">Save</button>');
  const handler = vi.fn();
  for (let i = 0; i < 3; i++) { beginSettingsBindings(); bindControl(root.querySelector('button'), 'click', handler); }
  root.querySelector('button')!.click();
  expect(handler).toHaveBeenCalledOnce();
});

it('keeps the user picker aligned with the active account after A → B → A', () => {
  const users: User[] = ['a', 'b'].map(user_id => ({ user_id, username: user_id, display_name: user_id, email: `${user_id}@example.test`, memberships: [], platform_role: 'member', account_type: 'standard', is_active: true }));
  const render = (id: string) => patchSettingsDom(root, `<div data-render-key="${escapeAttr(settingsPageDomKey('default', 'users', id))}">${usersPageHtml({ users, selectedUser: users.find(user => user.user_id === id) })}</div>`);
  const select = (id: string) => {
    const picker = root.querySelector<HTMLSelectElement>('#selected-user')!;
    picker.value = id; picker.dispatchEvent(new Event('change', { bubbles: true })); render(id);
  };
  render('a'); select('b'); select('a');
  expect(root.querySelector<HTMLSelectElement>('#selected-user')!.value).toBe('a');
  expect(root.querySelector<HTMLInputElement>('#edit-user [name=email]')!.value).toBe('a@example.test');
});

it('scopes cached page drafts by workspace identity', () => {
  const html = (workspace: string) => `<div data-render-key="${escapeAttr(settingsPageDomKey(workspace, 'voice'))}"><input value="saved" /></div>`;
  patchSettingsDom(root, html('first'));
  const field = root.querySelector('input')!;
  field.value = 'draft'; field.dispatchEvent(new Event('input', { bubbles: true }));
  patchSettingsDom(root, html('second'));
  expect(root.querySelector<HTMLInputElement>('input')!.value).toBe('saved');
  expect(root.querySelector('input')).not.toBe(field);
});

it('invalidates a mounted draft when the workspace resets', () => {
  const html = (value: number) => `<div data-render-key="page:settings"><input id="limit" value="${value}" /></div>`;
  patchSettingsDom(root, html(120));
  const field = root.querySelector<HTMLInputElement>('#limit')!;
  field.value = '123'; field.dispatchEvent(new Event('input', { bubbles: true }));
  clearSettingsDomCache(); patchSettingsDom(root, html(5));
  expect(root.querySelector<HTMLInputElement>('#limit')!.value).toBe('5');
  expect(root.querySelector('#limit')).not.toBe(field);
});

it('clears the owning draft after an acknowledgement while its page is detached', () => {
  const html = (value: string) => `<div data-render-key="page:learning"><form id="learning-settings"><input value="${value}" /></form></div>`;
  patchSettingsDom(root, html('120'));
  const field = root.querySelector('input')!;
  field.value = '300'; field.dispatchEvent(new Event('input', { bubbles: true }));
  patchSettingsDom(root, '<div data-render-key="page:users"></div>');
  clearSettingsDrafts('#learning-settings');
  patchSettingsDom(root, html('250'));
  expect(root.querySelector('input')).toBe(field);
  expect(field.value).toBe('250');
});

it('keeps a model draft when a provider refresh reorders groups', () => {
  const group = (provider: string) => `<section data-agentic-provider-group="${provider}"><input id="model-${provider}" value="saved" /></section>`;
  patchSettingsDom(root, group('a') + group('b'));
  const input = root.querySelector<HTMLInputElement>('#model-b')!;
  input.focus(); input.value = 'draft'; input.dispatchEvent(new Event('input', { bubbles: true }));
  patchSettingsDom(root, group('b') + group('a'));
  expect(root.querySelector('#model-b')).toBe(input);
  expect(input.value).toBe('draft');
  expect(document.activeElement).toBe(input);
});
