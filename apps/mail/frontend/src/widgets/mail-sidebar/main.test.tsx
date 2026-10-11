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

it.each(['gmail', 'imap_smtp'])('toggles sidebar filters without refetching and continues bounded %s sync', async (provider) => {
  vi.resetModules();
  vi.clearAllMocks();
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const accounts = [
    { id: 'a', provider, email_address: 'a@example.com', display_name: 'Same Name', status: 'connected' },
    { id: 'b', provider, email_address: 'b@example.com', display_name: 'Same Name', status: 'connected' },
  ];
  vi.mocked(readMailDisplay).mockResolvedValue({ items: accounts });
  vi.mocked(callBackend).mockImplementation(async (params) => {
    if (params.action === 'threads.sync') {
      if (provider === 'imap_smtp') {
        return params.continue_cursor
          ? { sync: { synced_messages: 0, checked_flag_messages: 15, has_more: false } }
          : { sync: { synced_messages: 1, checked_flag_messages: 24, has_more: true } };
      }
      return params.continue_cursor
        ? { sync: { synced_threads: 15, has_more: false } }
        : { sync: { synced_threads: 25, has_more: true } };
    }
    return { items: accounts, counts: {} };
  });
  const messages = vi.spyOn(window, 'postMessage').mockImplementation(() => undefined);
  const container = document.createElement('div');
  container.id = 'mail-sidebar-root';
  document.body.append(container);
  try {
    await act(async () => { await import('./main'); });
    expect([...container.querySelectorAll('.mail-account-label > span')].map(node => node.textContent)).toEqual(['a@example.com', 'b@example.com']);
    expect([...container.querySelectorAll('.mail-account-label > small')].map(node => node.textContent)).toEqual(['Same Name', 'Same Name']);
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

    await act(async () => container.querySelector<HTMLButtonElement>('[aria-label="Sync a@example.com"]')!.click());
    await vi.waitFor(() => expect(container.textContent).toContain('Account sync completed (40 messages checked).'));
    expect(vi.mocked(callBackend)).toHaveBeenCalledWith(expect.objectContaining({
      action: 'threads.sync', connection_id: 'a', max_threads: 25,
    }));
    expect(vi.mocked(callBackend)).toHaveBeenCalledWith(expect.objectContaining({
      action: 'threads.sync', connection_id: 'a', continue_cursor: true, max_threads: 15,
    }));
  } finally {
    await act(async () => vi.mocked(createRoot).mock.results[0]?.value.unmount());
    container.remove();
    messages.mockRestore();
    vi.unstubAllGlobals();
  }
});
