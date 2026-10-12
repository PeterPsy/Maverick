// @vitest-environment happy-dom
import { beforeAll, expect, it, vi } from 'vitest';

let post: ReturnType<typeof vi.spyOn>;
beforeAll(async () => {
  document.body.innerHTML = '<div id="settings-sidebar-root"></div>';
  post = vi.spyOn(window, 'postMessage');
  await import('./widgets/settings-sidebar/main');
}, 30000);

it('accepts continuous search without replacing the focused input and opens the matching control', () => {
  const input = document.querySelector<HTMLInputElement>('.settings-sidebar-search')!;
  input.focus();
  for (const character of 'password') {
    input.value += character; input.dispatchEvent(new Event('input', { bubbles: true }));
    expect(document.activeElement).toBe(input);
    expect(document.querySelector('.settings-sidebar-search')).toBe(input);
  }
  expect(input.value).toBe('password');
  document.querySelector<HTMLButtonElement>('[data-page-id="users"]')!.click();
  expect(post).toHaveBeenCalledWith(expect.objectContaining({ params: expect.objectContaining({ page_id: 'users', setting: 'password' }) }), '*');
});
