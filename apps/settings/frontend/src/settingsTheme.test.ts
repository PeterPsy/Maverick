// @vitest-environment happy-dom
import { expect, it } from 'vitest';
import { applySettingsTheme } from './settingsTheme';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
it('accepts declared light/dark themes and rejects invalid values', () => {
  applySettingsTheme({ effective: 'light' });
  expect(document.documentElement.dataset.maverickTheme).toBe('light');
  expect(document.documentElement.style.colorScheme).toBe('light');
  applySettingsTheme({ effective: 'other' });
  expect(document.documentElement.dataset.maverickTheme).toBe('light');
  applySettingsTheme({ effective: 'dark' });
  expect(document.documentElement.dataset.maverickTheme).toBe('dark');
});

it.each(['light', 'dark'])('uses the current %s theme in native select menus', theme => {
  const style = document.createElement('style');
  style.textContent = ['styles/tokens.css', 'styles/layout.css', 'styles.css']
    .map(name => readFileSync(join(dirname(fileURLToPath(import.meta.url)), name), 'utf8').replace(/^@import.*;$/gm, '')).join('\n');
  document.head.append(style);
  document.body.innerHTML = '<select><optgroup label="Group"><option>Option</option></optgroup></select><button>Save</button>';
  applySettingsTheme({ effective: theme });
  // Happy DOM does not compute color-scheme inheritance; inspect the native CSS rule.
  const selectRule = Array.from(style.sheet!.cssRules).find(rule => (rule as CSSStyleRule).selectorText === 'select') as CSSStyleRule;
  expect(selectRule.style.getPropertyValue('color-scheme')).toBe('inherit');
  expect(document.documentElement.style.colorScheme).toBe(theme);
  const background = theme === 'light' ? '#ffffff' : '#171717';
  const color = theme === 'light' ? '#111827' : '#ececec';
  for (const element of document.querySelectorAll('option, optgroup')) {
    expect(getComputedStyle(element).backgroundColor).toBe(background);
    expect(getComputedStyle(element).color).toBe(color);
  }
  expect(getComputedStyle(document.querySelector('button')!).color).toBe(theme === 'light' ? '#ffffff' : '#0a0a0b');
  expect(getComputedStyle(document.querySelector('button')!).backgroundColor).toBe(theme === 'light' ? '#111827' : '#ffffff');
  style.remove();
});
