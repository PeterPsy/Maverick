// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import { callBackend } from '../../api';
import { readMailDisplay } from '../../pwaCache';

vi.mock('../../pwaCache', () => ({ readMailDisplay: vi.fn() }));
vi.mock('../../api', async (original) => ({ ...await original<object>(), callBackend: vi.fn() }));
vi.mock('react-dom/client', async (original) => {
  const actual = await original<typeof import('react-dom/client')>();
  return { ...actual, createRoot: vi.fn(actual.createRoot) };
});

it('toggles real sidebar checkboxes cumulatively, including rapid clicks, without refetching', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const accounts = [{ id: 'a', provider: 'gmail', email_address: 'a@example.com', display_name: 'Account A', status: 'connected' }];
  vi.mocked(readMailDisplay).mockResolvedValue({ items: accounts });
  vi.mocked(callBackend).mockResolvedValue({ items: accounts, counts: {} });
  const messages = vi.spyOn(window, 'postMessage').mockImplementation(() => undefined);
  const container = document.createElement('div');
  container.id = 'mail-sidebar-root';
  document.body.append(container);
  try {
    await act(async () => { await import('./main'); });
    const checkboxes = [...container.querySelectorAll<HTMLElement>('[role="checkbox"]')];
    const inbox = checkboxes.find((node) => node.textContent?.includes('All inbox'))!;
    const sent = checkboxes.find((node) => node.textContent?.includes('All sent'))!;
    expect(inbox.getAttribute('aria-checked')).toBe('true');
    const backendReads = vi.mocked(callBackend).mock.calls.length;
    const displayReads = vi.mocked(readMailDisplay).mock.calls.length;

    // Both handlers execute before React gets a chance to commit another render.
    await act(async () => { inbox.click(); sent.click(); });
    expect(inbox.getAttribute('aria-checked')).toBe('false');
    expect(sent.getAttribute('aria-checked')).toBe('true');
    expect(messages.mock.calls.at(-1)?.[0]).toMatchObject({
      type: 'maverick.widget.open-app', app_id: 'mail', params: { mailbox_scopes: 'all:sent', thread: null },
    });
    await act(async () => sent.click());
    expect(messages.mock.calls.at(-1)?.[0].params.mailbox_scopes).toBe('');
    expect(vi.mocked(callBackend)).toHaveBeenCalledTimes(backendReads);
    expect(vi.mocked(readMailDisplay)).toHaveBeenCalledTimes(displayReads);
    expect(container.querySelector('.mail-sidebar-skeleton')).toBeNull();
  } finally {
    await act(async () => vi.mocked(createRoot).mock.results[0]?.value.unmount());
    container.remove();
    messages.mockRestore();
    vi.unstubAllGlobals();
  }
});
