import { afterEach, describe, expect, it, vi } from 'vitest';
import { callBackend, type MailDraft } from './api';
import { readMailDraftList } from './draftList';

vi.mock('./api', async (original) => ({ ...await original<object>(), callBackend: vi.fn() }));

describe('Live draft pagination', () => {
  afterEach(() => vi.resetAllMocks());
  it('loads all 205 drafts through both live pages with cancellation and timeouts', async () => {
    vi.mocked(callBackend).mockImplementation(async (params) => ({
      items: Array.from({ length: Number(params.offset) === 0 ? 200 : 5 }, (_, index) => ({ id: `draft-${Number(params.offset) + index}` } as MailDraft)),
      total_count: 205,
    }) as never);
    const signal = new AbortController().signal;
    const drafts = await readMailDraftList('', signal);
    expect(drafts).toHaveLength(205);
    expect(drafts.at(-1)?.id).toBe('draft-204');
    expect(vi.mocked(callBackend).mock.calls.map(([params]) => params.offset)).toEqual([0, 200]);
    expect(callBackend).toHaveBeenCalledWith(expect.any(Object), { signal, timeoutMs: 15_000 });
  });
  it('stops when the caller aborts before requesting another page', async () => {
    const controller = new AbortController();
    vi.mocked(callBackend).mockImplementation(async () => {
      controller.abort(new Error('Cancelled'));
      return { items: [], total_count: 205 } as never;
    });
    await expect(readMailDraftList('', controller.signal)).rejects.toThrow('Cancelled');
    expect(callBackend).toHaveBeenCalledTimes(1);
  });
});
