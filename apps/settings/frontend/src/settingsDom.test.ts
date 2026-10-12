// @vitest-environment happy-dom
import { beforeEach, expect, it, vi } from 'vitest';
import { clearSettingsDomCache, patchSettingsDom, rememberSettingsDrafts } from './settingsDom';
import { beginSettingsBindings, bindControl } from './controlBindings';

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
