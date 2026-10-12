// @vitest-environment happy-dom
import { expect, it, vi } from 'vitest';
import { runSettingsAction } from './settingsActions';
import { patchSettingsDom } from './settingsDom';

it('captures form values before locking controls and keeps them locked during a late render', async () => {
  document.body.innerHTML = '<div id="app"></div>';
  const root = document.getElementById('app')!;
  const html = '<form id="edit-user"><input name="email" value="person@example.test"><button>Save</button><p data-action-status role="status"></p></form>';
  patchSettingsDom(root, html);
  const form = document.querySelector('form')!;
  let email: unknown; let finish!: () => void;
  const pending = runSettingsAction(form, async () => {
    email = new FormData(form).get('email'); await new Promise<void>(resolve => { finish = resolve; });
  }, vi.fn());
  expect(email).toBe('person@example.test');
  patchSettingsDom(root, html);
  expect(form.querySelector('input')!.disabled).toBe(true);
  expect(form.querySelector('[data-action-status]')!.textContent).toBe('Saving…');
  finish(); await pending;
  expect(form.querySelector('input')!.disabled).toBe(false);
  expect(form.querySelector('[data-action-status]')!.textContent).toBe('Saved.');
});
