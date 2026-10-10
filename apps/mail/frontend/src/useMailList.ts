import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { callBackend, MAIL_BACKEND_ACTIONS, type MailConnection, type MailDraft, type MailThread } from './api';
import { readMailDisplay } from './pwaCache';
import { readMailThreadList, type ThreadListPayload } from './threadList';
import { readMailDraftList } from './draftList';

type Snapshot = { query: string; items: MailThread[]; complete: boolean };
type ConnectionPayload = { items: MailConnection[] };
const PAGE_SIZE = 200;

function draftListItem(draft: MailDraft): MailThread {
  return {
    id: draft.id, item_kind: 'draft', draft_id: draft.id, connection_id: draft.connection_id,
    subject: draft.subject, participants: draft.to || [], last_message_at: draft.updated_at || draft.created_at || '',
    snippet: draft.body_text.slice(0, 180), unread: false, starred: false, labels: ['drafts'],
  };
}
function newestFirst(left: MailThread, right: MailThread) {
  return right.last_message_at.localeCompare(left.last_message_at) || left.id.localeCompare(right.id);
}

export function useMailList(query: string, onError: (message: string) => void, includeDrafts = true) {
  const [connections, setConnections] = useState<MailConnection[]>([]);
  const [liveConnections, setLiveConnections] = useState<MailConnection[] | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [draftSnapshot, setDraftSnapshot] = useState<Snapshot | null>(null);
  const [refreshing, setRefreshing] = useState(true);
  const [draftRefreshing, setDraftRefreshing] = useState(false);
  const [failed, setFailed] = useState(false);
  const [draftFailed, setDraftFailed] = useState(false);
  const [searchQuery, setSearchQuery] = useState(query);
  const controllerRef = useRef<AbortController | null>(null);
  const draftController = useRef<AbortController | null>(null);
  const connectionController = useRef<AbortController | null>(null);
  const loadedPages = useRef({ query, count: 1 });
  const pagesRef = useRef({ query, pages: new Map<number, ThreadListPayload>() });
  const currentSnapshot = useRef(snapshot);
  currentSnapshot.current = snapshot;
  const readingMore = useRef(false);

  useEffect(() => {
    if (query !== searchQuery) controllerRef.current?.abort();
    const timer = setTimeout(() => setSearchQuery(query), 250);
    return () => clearTimeout(timer);
  }, [query, searchQuery]);
  const report = useCallback((error: unknown, signal: AbortSignal, resource: 'threads' | 'drafts' = 'threads') => {
    if (!signal.aborted) {
      if (resource === 'drafts') setDraftFailed(true);
      else setFailed(true);
      onError(error instanceof Error ? error.message : 'Unable to load mail.');
    }
  }, [onError]);

  const acceptPages = useCallback((next: ThreadListPayload[]) => {
    if (pagesRef.current.query !== searchQuery) pagesRef.current = { query: searchQuery, pages: new Map() };
    const pages = pagesRef.current.pages;
    for (const page of next) {
      if (page.offset && (!pages.has(page.offset - PAGE_SIZE)
        || pages.get(page.offset - PAGE_SIZE)!.offset + pages.get(page.offset - PAGE_SIZE)!.items.length >= pages.get(page.offset - PAGE_SIZE)!.total_count)) continue;
      pages.set(page.offset, page);
      if (page.offset + page.items.length >= page.total_count) {
        for (const offset of pages.keys()) if (offset > page.offset) pages.delete(offset);
      }
    }
    const items = new Map<string, MailThread>();
    let complete = false;
    let count = 0;
    for (let offset = 0; pages.has(offset); offset += PAGE_SIZE) {
      const page = pages.get(offset)!;
      for (const item of page.items) if (!items.has(item.id)) items.set(item.id, item);
      count += 1;
      complete = page.offset + page.items.length >= page.total_count;
      if (complete) break;
    }
    loadedPages.current = { query: searchQuery, count: Math.max(1, count) };
    setSnapshot({ query: searchQuery, items: [...items.values()], complete });
  }, [searchQuery]);

  const refreshConnections = useCallback(async () => {
    connectionController.current?.abort();
    const controller = new AbortController();
    connectionController.current = controller;
    const { signal } = controller;
    let receivedLive = false;
    const display = (next: ConnectionPayload) => {
      if (!signal.aborted && !receivedLive) setConnections((current) => next.items.map((item) => ({
        ...current.find((connection) => connection.id === item.id), ...item,
      })));
    };
    void readMailDisplay<ConnectionPayload>({ kind: 'mailboxes' }, { signal, onRevalidated: display })
      .then(display).catch(() => undefined);
    await callBackend<ConnectionPayload>({ action: MAIL_BACKEND_ACTIONS.connectionsList,
      _app_secret_request: { logical_names: [], required: false },
    }, { signal, timeoutMs: 15_000 }).then((next) => {
      if (!signal.aborted) {
        receivedLive = true;
        setConnections(next.items);
        setLiveConnections(next.items);
      }
    }).catch(() => undefined);
  }, []);

  const refreshDrafts = useCallback(async () => {
    draftController.current?.abort();
    const controller = new AbortController();
    draftController.current = controller;
    setDraftRefreshing(true);
    setDraftFailed(false);
    try {
      const items = await readMailDraftList(searchQuery, controller.signal);
      if (!controller.signal.aborted) setDraftSnapshot({ query: searchQuery, items: items.map(draftListItem), complete: true });
    } catch (error) { report(error, controller.signal, 'drafts'); }
    finally { if (!controller.signal.aborted) setDraftRefreshing(false); }
  }, [searchQuery, report]);

  const refreshThreads = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    readingMore.current = false;
    setRefreshing(true);
    setFailed(false);
    if (loadedPages.current.query !== searchQuery) loadedPages.current = { query: searchQuery, count: 1 };
    try {
      await readMailThreadList(searchQuery, controller.signal, (_items, _complete, pages) => {
        if (!controller.signal.aborted) acceptPages(pages);
      }, (error) => report(error, controller.signal), loadedPages.current.count);
    } catch (error) {
      if (!controller.signal.aborted) setSnapshot((current) => current?.query === searchQuery ? current
        : { query: searchQuery, items: [], complete: false });
      report(error, controller.signal);
    } finally { if (!controller.signal.aborted) setRefreshing(false); }
  }, [searchQuery, report, acceptPages]);

  useEffect(() => { void refreshConnections(); return () => connectionController.current?.abort(); }, [refreshConnections]);
  useEffect(() => { void refreshThreads(); return () => controllerRef.current?.abort(); }, [refreshThreads]);
  useEffect(() => {
    if (includeDrafts) void refreshDrafts();
    else setDraftRefreshing(false);
    return () => draftController.current?.abort();
  }, [includeDrafts, refreshDrafts]);
  const refresh = useCallback(async (resource = 'all') => {
    await Promise.all([
      ...(['all', 'threads'].includes(resource) ? [refreshThreads()] : []),
      ...(['all', 'connections'].includes(resource) ? [refreshConnections()] : []),
      ...(includeDrafts && ['all', 'drafts'].includes(resource) ? [refreshDrafts()] : []),
    ]);
  }, [includeDrafts, refreshConnections, refreshDrafts, refreshThreads]);

  const updateThread = useCallback((thread: MailThread) => {
    // Fence older list/revalidation responses before applying the live result.
    controllerRef.current?.abort();
    readingMore.current = false;
    setRefreshing(false);
    const { messages: _messages, ...header } = thread;
    for (const page of pagesRef.current.pages.values()) page.items = page.items.map((item) => item.id === header.id ? header : item);
    setSnapshot((current) => current && ({ ...current,
      items: current.items.map((item) => item.id === header.id ? header : item),
    }));
  }, []);

  const loadMore = useCallback(async () => {
    if (readingMore.current || query !== searchQuery) return;
    const prefix = currentSnapshot.current;
    if (!prefix || prefix.query !== searchQuery || prefix.complete) return;
    if (!controllerRef.current || controllerRef.current.signal.aborted) controllerRef.current = new AbortController();
    const { signal } = controllerRef.current;
    const offset = loadedPages.current.count * PAGE_SIZE;
    if (offset > 100_000) { report(new Error('Too many cached threads. Narrow the Mail search.'), signal); return; }
    readingMore.current = true;
    setRefreshing(true);
    let revalidated = false;
    const accept = (page: ThreadListPayload) => {
      if (signal.aborted) return;
      acceptPages([page]);
    };
    try {
      const page = await readMailDisplay<ThreadListPayload>({ kind: 'threads', max_threads: PAGE_SIZE, offset,
        ...(searchQuery ? { query: searchQuery } : {}),
      }, { signal, onRevalidated: (next) => { revalidated = true; accept(next); }, onRevalidationError: (error) => report(error, signal) });
      if (!revalidated) accept(page);
    } catch (error) { report(error, signal); }
    finally { if (!signal.aborted) { readingMore.current = false; setRefreshing(false); } }
  }, [query, searchQuery, report, acceptPages]);

  const threads = useMemo(() => [
    ...(snapshot?.query === searchQuery ? snapshot.items : []),
    ...(includeDrafts && draftSnapshot?.query === searchQuery ? draftSnapshot.items : []),
  ].sort(newestFirst), [snapshot, draftSnapshot, searchQuery, includeDrafts]);
  return {
    connections, liveConnections, refresh, updateThread, threads, loadMore,
    refreshing: refreshing || draftRefreshing, loading: snapshot?.query !== searchQuery,
    searching: query !== searchQuery, incomplete: (failed || (includeDrafts && draftFailed)) && !refreshing && !draftRefreshing,
    hasMore: snapshot?.query === searchQuery && !snapshot.complete && !failed,
  };
}
