import { useCallback, useEffect, useRef, useState, type Dispatch, type MutableRefObject, type SetStateAction } from 'react';
import type { RuntimeEvent, RuntimeTurn, RuntimeWebSocketFrame } from '../api/client';
import { firstPersistedRuntimeEventId, isSyntheticRuntimeEvent, mergeRuntimeEvents, hydrateMissingTurnAnchors } from '../lib/runtimeEvents';
import { boundRuntimeEventWindow } from '../lib/runtimeEventWindow';

type Setter<T> = Dispatch<SetStateAction<T>>;
type Page = Extract<RuntimeWebSocketFrame, { type: 'runtime.history.page' }>;
type Source = 'live' | 'snapshot' | 'before' | 'after' | 'latest' | 'around';
export type HistoryRestoreRequest = { id: number; sessionId: string; eventId: string };
export type RuntimeHistoryArgs = {
  runtimeSessionId: string | null;
  hasMoreHistory?: boolean;
  hasNewerHistory?: boolean;
  olderHistoryRequestId?: number;
  newerHistoryRequestId?: number;
  latestHistoryRequestId?: number;
  historyRestoreRequest?: HistoryRestoreRequest | null;
  setRestoredHistoryRequestId?: Setter<number>;
  followLatestRef?: MutableRefObject<boolean>;
  setHasMoreHistory?: Setter<boolean>;
  setHasNewerHistory?: Setter<boolean>;
  setIsOlderHistoryLoading?: Setter<boolean>;
  setIsNewerHistoryLoading?: Setter<boolean>;
};

/** The view's paging cursor is separate from the stream's live replay cursor. */
export function useRuntimeHistoryWindow(args: RuntimeHistoryArgs & {
  setEvents: Setter<RuntimeEvent[]>;
  activeTurnRef: MutableRefObject<RuntimeTurn | null>;
  socketRef: MutableRefObject<WebSocket | null>;
}) {
  const latest = useRef(args);
  latest.current = args;
  const [appliedRestore, setAppliedRestore] = useState(0);
  const appliedRestoreRef = useRef(0);
  useEffect(() => {
    if (appliedRestore) latest.current.setRestoredHistoryRequestId?.(appliedRestore);
  }, [appliedRestore]);
  const state = useRef({ session: args.runtimeSessionId, before: args.hasMoreHistory === true,
    after: args.hasNewerHistory === true, oldest: null as string | null, newest: null as string | null,
    request: null as string | null, direction: null as Source | null, sequence: 0 });
  if (state.current.session !== args.runtimeSessionId) {
    state.current = { session: args.runtimeSessionId, before: args.hasMoreHistory === true,
      after: args.hasNewerHistory === true, oldest: null, newest: null, request: null, direction: null, sequence: 0 };
  }

  const apply = useCallback((incoming: RuntimeEvent[], source: Source, page?: { has_more_before?: boolean; has_more_after?: boolean }) => {
    const options = latest.current;
    const window = state.current;
    options.setEvents(current => {
      if (window !== state.current) return current;
      const scoped = current.filter(event => event.session_id === window.session);
      const existing = scoped.length === current.length ? current : scoped;
      const historical = window.after && (source === 'live' || source === 'snapshot');
      // Updates to retained events are safe; distant live data must not join two
      // disconnected history ranges. Live control/usage still run in the owner.
      const ids = historical ? new Set(existing.map(event => event.event_id)) : null;
      const accepted = incoming.filter(event => event.session_id === window.session && (!ids || ids.has(event.event_id)));
      let base = existing;
      if (source === 'latest' || source === 'around') base = [];
      if (source === 'snapshot' && !historical && incoming.length && existing.length) {
        const incomingIds = new Set(incoming.map(event => event.event_id));
        if (!existing.some(event => incomingIds.has(event.event_id))) base = [];
      }
      const merged = mergeRuntimeEvents(base, accepted);
      const keepEarlier = source === 'before' || (source === 'live' && options.followLatestRef?.current === false);
      const activeTurn = options.activeTurnRef.current;
      const bounded = boundRuntimeEventWindow(merged, {
        previous: base, keep: keepEarlier ? 'earliest' : 'latest',
        activeTurnId: !keepEarlier && !historical && (source === 'live' || source === 'snapshot' || source === 'latest')
          && activeTurn?.session_id === window.session ? activeTurn.turn_id : null,
      });
      if (source === 'before' || source === 'latest' || source === 'around' || (source === 'snapshot' && !historical && !base.length)) {
        window.before = page?.has_more_before === true;
      }
      if (source === 'after' || source === 'latest' || source === 'around') window.after = page?.has_more_after === true;
      window.before ||= bounded.removedBefore;
      window.after ||= bounded.removedAfter;
      window.oldest = firstPersistedRuntimeEventId(bounded.events);
      window.newest = null;
      for (let index = bounded.events.length - 1; index >= 0; index--) {
        if (!isSyntheticRuntimeEvent(bounded.events[index])) {
          window.newest = bounded.events[index].event_id;
          break;
        }
      }
      options.setHasMoreHistory?.(window.before);
      options.setHasNewerHistory?.(window.after);
      return bounded.events;
    });
  }, []);

  const receive = useCallback((page: Page) => {
    const window = state.current;
    if (page.request_id && page.request_id !== window.request) return;
    if (window.direction && page.direction && window.direction !== page.direction) return;
    window.request = null;
    window.direction = null;
    apply(hydrateMissingTurnAnchors(page.events || [], page.turns), page.direction || 'before', page);
    if (page.direction === 'around' && latest.current.historyRestoreRequest) {
      appliedRestoreRef.current = latest.current.historyRestoreRequest.id;
      setAppliedRestore(appliedRestoreRef.current);
    }
    latest.current.setIsOlderHistoryLoading?.(false);
    latest.current.setIsNewerHistoryLoading?.(false);
  }, [apply]);

  const resetRequest = useCallback(() => {
    state.current.request = null;
    state.current.direction = null;
    latest.current.setIsOlderHistoryLoading?.(false);
    latest.current.setIsNewerHistoryLoading?.(false);
  }, []);

  const request = useCallback((direction: 'before' | 'after' | 'latest' | 'around', eventId?: string) => {
    const options = latest.current;
    const window = state.current;
    const socket = options.socketRef.current;
    const cursor = eventId || (direction === 'before' ? window.oldest : window.newest);
    if (!socket || socket.readyState !== WebSocket.OPEN || (direction !== 'latest' && !cursor)) {
      resetRequest();
      return;
    }
    const requestId = `${window.session}:${++window.sequence}`;
    window.request = requestId;
    window.direction = direction;
    socket.send(JSON.stringify({ type: `runtime.history.${direction}`, request_id: requestId,
      ...(direction !== 'latest' ? { [`${direction}_event_id`]: cursor } : {}), limit: 250 }));
  }, [resetRequest]);

  const resumeRestore = useCallback(() => {
    const restore = latest.current.historyRestoreRequest;
    if (state.current.direction === 'around' && state.current.request) return;
    if (restore && restore.sessionId === state.current.session && restore.id !== appliedRestoreRef.current) {
      request('around', restore.eventId);
    }
  }, [request]);
  useEffect(resumeRestore, [args.historyRestoreRequest, args.runtimeSessionId, resumeRestore]);

  const { olderHistoryRequestId = 0, newerHistoryRequestId = 0, latestHistoryRequestId = 0, runtimeSessionId } = args;
  // Counter changes are explicit UI intents. A thread change must not replay a
  // counter left over from the previous conversation.
  const requested = useRef({ olderHistoryRequestId, newerHistoryRequestId, latestHistoryRequestId });
  useEffect(() => {
    const previous = requested.current;
    requested.current = { olderHistoryRequestId, newerHistoryRequestId, latestHistoryRequestId };
    if (!runtimeSessionId) return;
    if (latestHistoryRequestId !== previous.latestHistoryRequestId) request('latest');
    else if (newerHistoryRequestId !== previous.newerHistoryRequestId) request('after');
    else if (olderHistoryRequestId !== previous.olderHistoryRequestId) request('before');
  }, [olderHistoryRequestId, newerHistoryRequestId, latestHistoryRequestId, runtimeSessionId, request]);

  return { apply, receive, resetRequest, resumeRestore };
}
