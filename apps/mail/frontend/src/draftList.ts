import { callBackend, MAIL_BACKEND_ACTIONS, type MailDraft } from './api';

/** Drafts are live-only and are never written to the display cache. */
export async function readMailDraftList(query: string, signal: AbortSignal): Promise<MailDraft[]> {
  const drafts = new Map<string, MailDraft>();
  for (let offset = 0; offset <= 100_000; offset += 200) {
    const page = await callBackend<{ items: MailDraft[]; total_count: number }>({
      action: MAIL_BACKEND_ACTIONS.draftsList, ...(query ? { query } : {}),
      limit: 200, offset, _app_secret_request: { logical_names: [], required: false },
    }, { signal, timeoutMs: 15_000 });
    if (signal.aborted) throw signal.reason;
    for (const draft of page.items) drafts.set(draft.id, draft);
    if (offset + page.items.length >= page.total_count) return [...drafts.values()];
    if (!page.items.length) throw new Error('Draft pagination returned an incomplete page. Refresh Mail.');
  }
  throw new Error('Too many drafts. Narrow the Mail search.');
}
