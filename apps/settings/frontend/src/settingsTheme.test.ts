// @vitest-environment happy-dom
import { expect, it } from 'vitest';
import { applySettingsTheme } from './settingsTheme';
it('accepts declared light/dark themes and rejects invalid values', () => {
  applySettingsTheme({ effective: 'light' });
  expect(document.documentElement.dataset.maverickTheme).toBe('light');
  expect(document.documentElement.style.colorScheme).toBe('light');
  applySettingsTheme({ effective: 'other' });
  expect(document.documentElement.dataset.maverickTheme).toBe('light');
  applySettingsTheme({ effective: 'dark' });
  expect(document.documentElement.dataset.maverickTheme).toBe('dark');
});
