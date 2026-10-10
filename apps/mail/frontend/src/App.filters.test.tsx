// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import { callBackend, type MailDraft, type MailThread } from './api';
import { readMailDisplay } from './pwaCache';
import { threadScopeKey } from './threadUpdates';

vi.mock('./pwaCache', () => ({ readMailDisplay: vi.fn() }));
vi.mock('./api', async (original) => ({ ...await original<object>(), callBackend: vi.fn() }));

const accounts = ['a', 'b'].map((id) => ({
  id, provider: 'gmail', email_address: `${id}@example.com`, display_name: id, status: 'connected',
}));
function thread(id: string, labels: string[], account = 'a'): MailThread {
  return {
    id, labels, connection_id: account, subject: id, snippet: 'Cached snippet',
    participants: [{ email: 'sender@example.com' }], last_message_at: '2026-09-13T10:00:00Z',
    unread: false, starred: labels.includes('starred'), messages: [],
  };
}

describe('Live Mail sidebar filtering', () => {
  let container: HTMLDivElement;
  let root: Root;
  let data: MailThread[];
  let drafts: MailDraft[];
  beforeEach(() => {
    vi.resetAllMocks();
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
    window.history.replaceState({}, '', '/');
    container = document.createElement('div');
    document.body.append(container);
    root = createRoot(container);
    data = [thread('A inbox', ['inbox', 'starred']), thread('A sent', ['sent']),
      thread('B inbox', ['inbox'], 'b'), thread('B trash', ['trash'], 'b')];
    drafts = [];
    vi.mocked(readMailDisplay).mockImplementation(async (params) => {
      if (params.kind === 'mailboxes') return { items: accounts } as never;
      if (params.kind === 'thread') return { thread: data.find((item) => item.id === params.thread_id) } as never;
      const offset = Number(params.offset);
      const result = params.query ? data.filter((item) => item.id === 'A sent') : data;
      return { items: result.slice(offset, offset + 200), total_count: result.length, limit: 200, offset } as never;
    });
    vi.mocked(callBackend).mockImplementation(async (params) => {
      if (params.action === 'messages.mark_read' || params.action === 'labels.modify') {
        data = data.map((item) => item.id !== params.thread_id ? item : params.action === 'messages.mark_read'
          ? { ...item, unread: !params.read }
          : { ...item, labels: item.labels.filter((label) => !(params.remove as string[]).includes(label)).concat(params.add as string[]) });
        return { thread: data.find((item) => item.id === params.thread_id) } as never;
      }
      if (params.action === 'threads.get') return { thread: data.find((item) => item.id === params.thread_id) } as never;
      if (params.action === 'drafts.list') return { items: drafts.slice(Number(params.offset || 0), Number(params.offset || 0) + 200), total_count: drafts.length } as never;
      if (params.action === 'drafts.get') return { draft: drafts.find((item) => item.id === params.draft_id) } as never;
      return { items: accounts } as never;
    });
  });
  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });
  async function mount() { await act(async () => root.render(<App />)); }
  async function navigate(params: Record<string, unknown>) {
    await act(async () => window.dispatchEvent(new MessageEvent('message', {
      source: window, origin: window.location.origin,
      data: { type: 'maverick.app.navigate', params },
    })));
  }
  function rows() { return [...container.querySelectorAll('.thread-title')].map((row) => row.textContent); }
  function skeleton() { return container.querySelector('.mail-thread-skeleton'); }

  it('loads the next page from the header without rereading existing pages, accounts or drafts', async () => {
    data = Array.from({ length: 451 }, (_, index) => thread(`Mail ${index}`, ['inbox']));
    await mount();
    const firstRow = container.querySelector('.thread-row');
    const backendReads = vi.mocked(callBackend).mock.calls.length;
    const button = container.querySelector<HTMLButtonElement>('header.toolbar [aria-label="Load more mail"]')!;
    expect(button).not.toBeNull();
    await act(async () => button.click());
    expect(vi.mocked(readMailDisplay).mock.calls.filter(([params]) => params.kind === 'threads').map(([params]) => params.offset)).toEqual([0, 200]);
    expect(vi.mocked(callBackend)).toHaveBeenCalledTimes(backendReads);
    expect(container.querySelector('.thread-row')).toBe(firstRow);
    expect(skeleton()).toBeNull();
  });

  it('uses the same header icon for bounded provider sync and resumes pending work', async () => {
    await mount();
    vi.mocked(callBackend).mockImplementation(async (params) => params.action === 'threads.sync'
      ? { sync: { synced_messages: 2, has_more: true } } as never : { items: accounts } as never);
    const button = container.querySelector<HTMLButtonElement>('header.toolbar [aria-label="Load more mail"]')!;
    await act(async () => button.click());
    await act(async () => button.click());
    const calls = vi.mocked(callBackend).mock.calls.filter(([params]) => params.action === 'threads.sync');
    expect(calls).toHaveLength(2);
    expect(calls[0][0]).toMatchObject({ max_threads: 25, continue_cursor: false });
    expect(calls[1][0]).toMatchObject({ max_threads: 25, continue_cursor: true });
    expect(container.querySelectorAll('header.toolbar [aria-label="Load more mail"]')).toHaveLength(1);
    expect(container.querySelector('.mail-load-more')).toBeNull();
  });

  it('updates read state locally and refreshes only the affected thread for its data event', async () => {
    await mount();
    const reads = vi.mocked(readMailDisplay).mock.calls.length;
    const firstRow = container.querySelector('.thread-row')!;
    await act(async () => firstRow.querySelector<HTMLButtonElement>('.thread-read-button')!.click());
    expect(firstRow.querySelector('.thread-read-button')?.getAttribute('aria-label')).toBe('Mark read');
    const scopeKey = await threadScopeKey('A inbox');
    await act(async () => window.dispatchEvent(new MessageEvent('message', {
      source: window, origin: window.location.origin,
      data: { type: 'maverick.app.data-changed', owner_app_id: 'mail', resource: 'threads', scope_keys: [scopeKey] },
    })));
    await vi.waitFor(() => expect(vi.mocked(callBackend).mock.calls.filter(([params]) => params.action === 'threads.get')).toHaveLength(1));
    expect(vi.mocked(readMailDisplay)).toHaveBeenCalledTimes(reads);
    expect(container.querySelector('.thread-row')).toBe(firstRow);
    expect(skeleton()).toBeNull();
  });

  it('removes a trashed row without reloading the collection or replacing other rows', async () => {
    await mount();
    const otherRow = container.querySelectorAll('.thread-row')[1];
    const reads = vi.mocked(readMailDisplay).mock.calls.length;
    await act(async () => container.querySelector<HTMLButtonElement>('.thread-trash-button')!.click());
    expect(rows()).toEqual(['B inbox']);
    expect(container.querySelector('.thread-row')).toBe(otherRow);
    expect(vi.mocked(readMailDisplay)).toHaveBeenCalledTimes(reads);
    expect(skeleton()).toBeNull();
  });

  it('does not let an earlier data-event response undo a completed local read mutation', async () => {
    await mount();
    let resolve!: (value: unknown) => void;
    vi.mocked(callBackend).mockImplementationOnce(() => new Promise((done) => { resolve = done; }) as never);
    const stale = { ...data[0] };
    const scopeKey = await threadScopeKey(stale.id);
    await act(async () => window.dispatchEvent(new MessageEvent('message', {
      source: window, origin: window.location.origin,
      data: { type: 'maverick.app.data-changed', owner_app_id: 'mail', resource: 'threads', scope_keys: [scopeKey] },
    })));
    await vi.waitFor(() => expect(resolve).toBeDefined());
    const button = container.querySelector<HTMLButtonElement>('.thread-read-button')!;
    await act(async () => button.click());
    expect(button.getAttribute('aria-label')).toBe('Mark read');
    await act(async () => resolve({ thread: stale }));
    expect(button.getAttribute('aria-label')).toBe('Mark read');
  });

  it('does not fetch drafts until Drafts is selected and then reuses the loaded headers', async () => {
    await mount();
    expect(vi.mocked(callBackend).mock.calls.some(([params]) => params.action === 'drafts.list')).toBe(false);
    const reads = vi.mocked(readMailDisplay).mock.calls.length;
    await navigate({ mailbox_scopes: 'all:drafts' });
    await vi.waitFor(() => expect(vi.mocked(callBackend).mock.calls.some(([params]) => params.action === 'drafts.list')).toBe(true));
    expect(vi.mocked(readMailDisplay)).toHaveBeenCalledTimes(reads);
  });

  it('can still load Inbox pages after a failed Drafts read', async () => {
    data = Array.from({ length: 451 }, (_, index) => thread(`Mail ${index}`, ['inbox']));
    await mount();
    vi.mocked(callBackend).mockImplementationOnce(async () => { throw new Error('Drafts unavailable'); });
    await navigate({ mailbox_scopes: ['all:drafts'] });
    expect(container.textContent).toContain('Drafts unavailable');
    await navigate({ mailbox_scopes: ['all:inbox'] });
    await act(async () => container.querySelector<HTMLButtonElement>('header.toolbar [aria-label="Load more mail"]')!.click());
    expect(vi.mocked(readMailDisplay).mock.calls.filter(([params]) => params.kind === 'threads').map(([params]) => params.offset)).toEqual([0, 200]);
  });

  it('adds/removes only matching rows without another read or skeleton, including clearing all', async () => {
    await mount();
    const inboxRow = container.querySelector('.thread-row');
    const reads = vi.mocked(readMailDisplay).mock.calls.length;
    const backendReads = vi.mocked(callBackend).mock.calls.length;
    expect(rows()).toEqual(['A inbox', 'B inbox']);
    await navigate({ mailbox_scopes: 'all:inbox,connection:a:sent' });
    expect(rows()).toEqual(['A inbox', 'A sent', 'B inbox']);
    expect(container.querySelector('.thread-row')).toBe(inboxRow);
    expect(skeleton()).toBeNull();
    await navigate({ mailbox_scopes: 'connection:b:inbox' });
    expect(rows()).toEqual(['B inbox']);
    await navigate({ mailbox_scopes: '', mailbox: 'inbox' });
    expect(rows()).toEqual([]);
    expect(container.textContent).toContain('No threads match this view.');
    await navigate({ mailbox_scopes: 'all:inbox' });
    expect(rows()).toEqual(['A inbox', 'B inbox']);
    expect(vi.mocked(readMailDisplay)).toHaveBeenCalledTimes(reads);
    expect(vi.mocked(callBackend)).toHaveBeenCalledTimes(backendReads);
  });

  it('marks only the opened thread as selected', async () => {
    await mount();
    const threadRows = [...container.querySelectorAll<HTMLElement>('.thread-row')];
    expect(threadRows).toHaveLength(2);
    expect(threadRows.filter((row) => row.classList.contains('selected'))).toHaveLength(0);

    await act(async () => threadRows[0].querySelector<HTMLButtonElement>('.thread-row__body')!.click());

    const selectedRows = [...container.querySelectorAll<HTMLElement>('.thread-row.selected')];
    expect(selectedRows).toHaveLength(1);
    expect(selectedRows[0].textContent).toContain('A inbox');
  });

  it('filters the whole loaded collection, not only the first backend or UI page', async () => {
    data = Array.from({ length: 251 }, (_, index) => thread(`Mail ${index}`, [index < 200 ? 'inbox' : 'sent']));
    await mount();
    expect(vi.mocked(readMailDisplay).mock.calls.filter(([params]) => params.kind === 'threads')).toHaveLength(1);
    await act(async () => container.querySelector<HTMLButtonElement>('header.toolbar [aria-label="Load more mail"]')!.click());
    const reads = vi.mocked(readMailDisplay).mock.calls.length;
    await navigate({ mailbox_scopes: 'all:sent' });
    expect(rows()).toHaveLength(50);
    expect(rows()[0]).toBe('Mail 200');
    const pageTwo = [...container.querySelectorAll<HTMLButtonElement>('.sliding-pagination button')]
      .find((button) => button.textContent === '2')!;
    await act(async () => pageTwo.click());
    expect(rows()).toEqual(['Mail 250']);
    await navigate({ mailbox_scopes: 'all:starred' });
    expect(rows()).toEqual([]);
    expect(container.querySelector('.mail-page-range')?.textContent).toBe('0-0');
    expect(vi.mocked(readMailDisplay)).toHaveBeenCalledTimes(reads);
    expect(skeleton()).toBeNull();
  });

  it('loads local drafts live, filters them into Drafts, and opens a safe preview', async () => {
    drafts = [{
      id: 'draft-1', connection_id: 'a', subject: 'Candidate follow up', body_text: 'Prepared, not sent.',
      to: [{ email: 'candidate@example.com', name: 'Candidate' }], status: 'draft',
      updated_at: '2026-09-13T11:00:00Z', sent_at: null,
    }];
    window.history.replaceState({}, '', '/?mailbox_scopes=all:drafts');

    await mount();
    await vi.waitFor(() => expect(rows()).toEqual(['Candidate follow up']));
    await act(async () => container.querySelector<HTMLButtonElement>('.thread-row__body')!.click());

    expect(container.querySelector('.draft-reader')?.textContent).toContain('Draft · not sent');
    expect(container.querySelector('.draft-reader')?.textContent).toContain('Prepared, not sent.');
    expect(vi.mocked(callBackend)).toHaveBeenCalledWith(expect.objectContaining({ action: 'drafts.list' }), expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(vi.mocked(callBackend)).toHaveBeenCalledWith(expect.objectContaining({ action: 'drafts.get', draft_id: 'draft-1' }), expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(vi.mocked(readMailDisplay).mock.calls.some(([params]) => params.kind === 'draft')).toBe(false);
  });

  it('keeps server-side body/attachment search semantics while filtering its results locally', async () => {
    await mount();
    await navigate({ query: 'filename-not-in-the-header.pdf', mailbox_scopes: 'all:sent' });
    await vi.waitFor(() => expect(vi.mocked(readMailDisplay).mock.calls.some(([params]) => params.query === 'filename-not-in-the-header.pdf')).toBe(true));
    await vi.waitFor(() => expect(rows()).toEqual(['A sent']));
    const reads = vi.mocked(readMailDisplay).mock.calls.length;
    await navigate({ mailbox_scopes: 'all:inbox' });
    expect(rows()).toEqual([]);
    await navigate({ mailbox_scopes: 'all:sent' });
    expect(rows()).toEqual(['A sent']);
    expect(vi.mocked(readMailDisplay)).toHaveBeenCalledTimes(reads);
  });

  it('debounces rapid search changes and requests only the last query', async () => {
    await mount();
    vi.useFakeTimers();
    const reads = vi.mocked(readMailDisplay).mock.calls.length;
    await navigate({ query: 'first' });
    await act(async () => vi.advanceTimersByTimeAsync(100));
    await navigate({ query: 'final' });
    await act(async () => vi.advanceTimersByTimeAsync(249));
    expect(readMailDisplay).toHaveBeenCalledTimes(reads);
    await act(async () => vi.advanceTimersByTimeAsync(1));
    const queries = vi.mocked(readMailDisplay).mock.calls.map(([params]) => params.query).filter(Boolean);
    expect(queries).toEqual(['final']);
  });

  it('preserves a matching reader and prevents a hidden pending thread from reopening', async () => {
    await mount();
    await act(async () => container.querySelector<HTMLButtonElement>('.thread-row__body')!.click());
    expect(container.querySelector('.reader-column')).not.toBeNull();
    const reads = vi.mocked(readMailDisplay).mock.calls.length;
    await navigate({ mailbox_scopes: 'all:inbox,all:sent' });
    expect(container.querySelector('.reader-column')).not.toBeNull();
    expect(vi.mocked(readMailDisplay)).toHaveBeenCalledTimes(reads);
    await navigate({ mailbox_scopes: 'all:sent' });
    expect(container.querySelector('.reader-column')).toBeNull();
    let resolve!: (value: never) => void;
    vi.mocked(readMailDisplay).mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    await act(async () => container.querySelector<HTMLButtonElement>('.thread-row__body')!.click());
    await navigate({ mailbox_scopes: '' });
    expect(container.querySelector<HTMLButtonElement>('[aria-label="Load more mail"]')?.disabled).toBe(false);
    const backendReads = vi.mocked(callBackend).mock.calls.length;
    await act(async () => resolve({ thread: data[1] } as never));
    expect(container.querySelector('.reader-column')).toBeNull();
    expect(vi.mocked(callBackend)).toHaveBeenCalledTimes(backendReads);
  });

  it('keeps loaded rows visible during data-event refresh and preserves an empty selection', async () => {
    await mount();
    let resolve!: (value: never) => void;
    vi.mocked(readMailDisplay).mockImplementation(async (params) => {
      if (params.kind === 'mailboxes') return { items: accounts } as never;
      return new Promise((done) => { resolve = done; });
    });
    await act(async () => window.dispatchEvent(new MessageEvent('message', {
      source: window, origin: window.location.origin,
      data: { type: 'maverick.app.data-changed', owner_app_id: 'mail', resource: 'threads' },
    })));
    expect(rows()).toEqual(['A inbox', 'B inbox']);
    expect(skeleton()).toBeNull();
    await navigate({ mailbox_scopes: '' });
    await act(async () => resolve({ items: data, total_count: data.length, limit: 200, offset: 0 } as never));
    expect(rows()).toEqual([]);
  });

  it('does not display incoming-only threads backwards when Sent is the first of several filters', async () => {
    await mount();
    await navigate({ mailbox_scopes: 'all:sent,all:inbox' });
    const incoming = [...container.querySelectorAll('.thread-row')].find((row) => row.textContent?.includes('A inbox'))!;
    expect(incoming.querySelector('.thread-route')?.getAttribute('title')).toBe('sender@example.com to a');
  });

  it('honors a direct empty-scope URL instead of restoring the default Inbox', async () => {
    window.history.replaceState({}, '', '/?mailbox_scopes=&mailbox=inbox');
    await mount();
    expect(rows()).toEqual([]);
  });

  it('reapplies the active filters when cached labels are revalidated', async () => {
    await mount();
    const request = vi.mocked(readMailDisplay).mock.calls.find(([params]) => params.kind === 'threads')!;
    const changed = data.map((item) => item.id === 'A inbox' ? { ...item, labels: ['trash'] } : item);
    await act(async () => request[1]!.onRevalidated!({ items: changed, total_count: changed.length, limit: 200, offset: 0 }));
    expect(rows()).toEqual(['B inbox']);
    await navigate({ mailbox_scopes: 'all:trash' });
    expect(rows()).toEqual(['A inbox', 'B trash']);
  });

  it('ignores a late response belonging to a previous search', async () => {
    await mount();
    let resolve!: (value: never) => void;
    vi.mocked(readMailDisplay).mockImplementation(async (params) => {
      if (params.kind === 'mailboxes') return { items: accounts } as never;
      if (params.query === 'first') return new Promise((done) => { resolve = done; });
      return { items: [data[1]], total_count: 1, limit: 200, offset: 0 } as never;
    });
    await navigate({ query: 'first', mailbox_scopes: 'all:sent,all:inbox' });
    await vi.waitFor(() => expect(vi.mocked(readMailDisplay).mock.calls.some(([params]) => params.query === 'first')).toBe(true));
    await navigate({ query: 'second' });
    await vi.waitFor(() => expect(rows()).toEqual(['A sent']));
    await act(async () => resolve({ items: [data[0]], total_count: 1, limit: 200, offset: 0 } as never));
    expect(rows()).toEqual(['A sent']);
  });

  it('labels a failed partial collection instead of claiming there are no matches', async () => {
    vi.mocked(readMailDisplay).mockRejectedValue(new Error('Offline'));
    await mount();
    expect(container.textContent).toContain('Some cached mail could not be loaded.');
    expect(container.textContent).not.toContain('No threads match this view.');
    expect(skeleton()).toBeNull();
  });
});
