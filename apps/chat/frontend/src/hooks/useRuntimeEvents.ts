import { useEffect, useRef } from "react";
import type { Dispatch, SetStateAction } from "react";
import {
  ChatUsageSummary,
  RuntimeEvent,
  runtimeEventFromWebSocketFrame,
  RuntimeSession,
  RuntimeTurn,
  RuntimeWebSocketFrame,
  runtimeWebSocketUrl,
} from "../api/client";
import { PendingMessage } from "../lib/messageState";
import {
  firstPersistedRuntimeEventId,
  firstRuntimeEventId,
  hydrateMissingTurnAnchors,
  inferActiveRuntimeTurn,
  isSyntheticRuntimeEvent,
  lastRuntimeEventId,
  mergeRuntimeEvents,
  runtimeTurnStatusFromEvent,
} from "../lib/runtimeEvents";

type RuntimeEventsArgs = {
  runtimeSessionId: string | null;
  activeTurn: RuntimeTurn | null;
  hasMoreHistory?: boolean;
  onRuntimeSessionUnavailable?: ((runtimeSessionId: string) => void) | null;
  onRuntimeSnapshot?: (() => void) | null;
  onUsageSnapshot?: ((usage: ChatUsageSummary | null) => void) | null;
  olderHistoryRequestId?: number;
  setActiveSession: Dispatch<SetStateAction<RuntimeSession | null>>;
  setActiveTurn: Dispatch<SetStateAction<RuntimeTurn | null>>;
  setEvents: Dispatch<SetStateAction<RuntimeEvent[]>>;
  setError: Dispatch<SetStateAction<string | null>>;
  setHasMoreHistory?: Dispatch<SetStateAction<boolean>>;
  setIsOlderHistoryLoading?: Dispatch<SetStateAction<boolean>>;
  setPendingUserMessages: Dispatch<SetStateAction<PendingMessage[]>>;
};

function terminalStatus(event: RuntimeEvent): RuntimeTurn["status"] | null {
  const status = runtimeTurnStatusFromEvent(event);
  return status && status !== "queued" && status !== "active" ? status : null;
}

export function applyRuntimeEventEffects(
  events: RuntimeEvent[],
  activeTurn: RuntimeTurn | null,
  setActiveTurn: Dispatch<SetStateAction<RuntimeTurn | null>>,
  setPendingUserMessages: Dispatch<SetStateAction<PendingMessage[]>>,
) {
  const completedClientMessageIds = completedClientMessageIdsForEvents(events);
  if (completedClientMessageIds.size) {
    setPendingUserMessages((current) => current.filter((item) => !completedClientMessageIds.has(item.clientMessageId)));
  }
  if (!activeTurn) {
    return;
  }
  const terminalEvent = events.find((event) => event.turn_id === activeTurn.turn_id && terminalStatus(event));
  if (!terminalEvent) {
    return;
  }
  const status = terminalStatus(terminalEvent);
  setActiveTurn((current) => (current?.turn_id === activeTurn.turn_id && status ? { ...current, status } : current));
}

function completedClientMessageIdsForEvents(events: RuntimeEvent[]): Set<string> {
  const terminalTurnIds = new Set(
    events
      .filter((event) => event.turn_id && terminalStatus(event))
      .map((event) => event.turn_id as string),
  );
  return new Set(
    events
      .filter(
        (event) =>
          event.turn_id &&
          terminalTurnIds.has(event.turn_id) &&
          event.event_type === "runtime.turn.queued" &&
          typeof event.payload.client_message_id === "string",
      )
      .map((event) => event.payload.client_message_id as string),
  );
}

export function useRuntimeEvents({
  activeTurn,
  hasMoreHistory = false,
  onRuntimeSessionUnavailable,
  onRuntimeSnapshot,
  onUsageSnapshot,
  olderHistoryRequestId = 0,
  runtimeSessionId,
  setActiveSession,
  setActiveTurn,
  setError,
  setEvents,
  setHasMoreHistory,
  setIsOlderHistoryLoading,
  setPendingUserMessages,
}: RuntimeEventsArgs) {
  const activeTurnRef = useRef<RuntimeTurn | null>(activeTurn);
  const hasMoreHistoryRef = useRef(hasMoreHistory);
  const oldestEventIdRef = useRef<string | null>(null);
  const onRuntimeSnapshotRef = useRef<typeof onRuntimeSnapshot>(onRuntimeSnapshot);
  const onUsageSnapshotRef = useRef<typeof onUsageSnapshot>(onUsageSnapshot);
  const onRuntimeSessionUnavailableRef = useRef<typeof onRuntimeSessionUnavailable>(onRuntimeSessionUnavailable);
  const socketRef = useRef<WebSocket | null>(null);
  useEffect(() => {
    activeTurnRef.current = activeTurn;
  }, [activeTurn]);
  useEffect(() => {
    hasMoreHistoryRef.current = hasMoreHistory;
  }, [hasMoreHistory]);
  useEffect(() => {
    onRuntimeSnapshotRef.current = onRuntimeSnapshot;
  }, [onRuntimeSnapshot]);
  useEffect(() => {
    onUsageSnapshotRef.current = onUsageSnapshot;
  }, [onUsageSnapshot]);
  useEffect(() => {
    onRuntimeSessionUnavailableRef.current = onRuntimeSessionUnavailable;
  }, [onRuntimeSessionUnavailable]);

  useEffect(() => {
    if (!runtimeSessionId) {
      return;
    }
    const currentSessionId = runtimeSessionId;
    let cancelled = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: number | null = null;
    let heartbeatTimer: number | null = null;
    let lastEventId: string | null = null;
    let receivedInitialSnapshot = false;
    let unavailableReported = false;
    let lastFrameAt = Date.now();
    let activeRuntimeSessionId = currentSessionId;
    const lineageSessionIds = new Set([currentSessionId]);

    function reportUnavailableSession() {
      if (cancelled || unavailableReported) {
        return;
      }
      unavailableReported = true;
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      stopHeartbeatWatchdog();
      setError(null);
      onRuntimeSessionUnavailableRef.current?.(currentSessionId);
    }

    function setOldestEventCursor(events: RuntimeEvent[], oldestEventId?: string | null) {
      oldestEventIdRef.current = oldestEventId || firstPersistedRuntimeEventId(events) || firstRuntimeEventId(events);
    }

    function socketIsCurrent(candidate: WebSocket | null): candidate is WebSocket {
      return Boolean(candidate && !cancelled && socketRef.current === candidate);
    }

    function eventsForCurrentSession(incoming: RuntimeEvent[]): RuntimeEvent[] {
      return incoming.filter((event) => lineageSessionIds.has(event.session_id));
    }

    function extendRuntimeLineage(incoming: RuntimeEvent[]) {
      for (const runtimeEvent of incoming) {
        if (
          runtimeEvent.event_type === "runtime.continuation.forked"
          && lineageSessionIds.has(runtimeEvent.session_id)
          && typeof runtimeEvent.payload.successor_session_id === "string"
        ) {
          activeRuntimeSessionId = runtimeEvent.payload.successor_session_id;
          lineageSessionIds.add(activeRuntimeSessionId);
        }
        if (
          runtimeEvent.event_type === "runtime.continuation.accepted"
          && typeof runtimeEvent.payload.predecessor_session_id === "string"
          && lineageSessionIds.has(runtimeEvent.payload.predecessor_session_id)
        ) {
          activeRuntimeSessionId = runtimeEvent.session_id;
          lineageSessionIds.add(runtimeEvent.session_id);
        }
      }
    }

    function applyIncomingEvents(incoming: RuntimeEvent[], oldestEventId?: string | null) {
      extendRuntimeLineage(incoming);
      const scopedIncoming = eventsForCurrentSession(incoming);
      if (!scopedIncoming.length) {
        return;
      }
      const usageEvent = [...scopedIncoming].reverse().find((event) => event.event_type === "runtime.usage.updated");
      if (usageEvent) {
        const usage = chatUsageSummaryFromPayload(usageEvent.payload);
        if (usage) {
          onUsageSnapshotRef.current?.(usage);
        }
      }
      const persistedIncoming = scopedIncoming.filter((event) => !isSyntheticRuntimeEvent(event));
      lastEventId = (persistedIncoming.at(-1) || scopedIncoming[scopedIncoming.length - 1]).event_id;
      setEvents((current) => {
        const merged = mergeRuntimeEvents(eventsForCurrentSession(current), scopedIncoming);
        setOldestEventCursor(merged, oldestEventId);
        const currentTurn = activeTurnRef.current;
        applyRuntimeEventEffects(merged, currentTurn && lineageSessionIds.has(currentTurn.session_id) ? currentTurn : null, setActiveTurn, setPendingUserMessages);
        setActiveTurn(inferActiveRuntimeTurn(merged, activeRuntimeSessionId));
        return merged;
      });
    }

    function applyHistoryPage(incoming: RuntimeEvent[], oldestEventId?: string | null) {
      extendRuntimeLineage(incoming);
      const scopedIncoming = eventsForCurrentSession(incoming);
      setEvents((current) => {
        const merged = mergeRuntimeEvents(eventsForCurrentSession(current), scopedIncoming);
        setOldestEventCursor(merged, oldestEventId);
        setActiveTurn(inferActiveRuntimeTurn(merged, activeRuntimeSessionId));
        return merged;
      });
    }

    if (typeof WebSocket === "undefined") {
      setError("Runtime WebSocket is unavailable.");
      return;
    }

    setEvents((current) => {
      const scopedCurrent = eventsForCurrentSession(current);
      lastEventId = lastRuntimeEventId(scopedCurrent);
      setOldestEventCursor(scopedCurrent);
      const currentTurn = activeTurnRef.current;
      applyRuntimeEventEffects(scopedCurrent, currentTurn?.session_id === currentSessionId ? currentTurn : null, setActiveTurn, setPendingUserMessages);
      setActiveTurn(inferActiveRuntimeTurn(scopedCurrent, activeRuntimeSessionId));
      return scopedCurrent;
    });

    function connectWebSocket() {
      let socketOpened = false;
      const replayCursor = receivedInitialSnapshot ? lastEventId : null;
      socket = new WebSocket(runtimeWebSocketUrl(currentSessionId, replayCursor));
      socketRef.current = socket;
      socket.onopen = () => {
        if (!socketIsCurrent(socket)) {
          return;
        }
        socketOpened = true;
        lastFrameAt = Date.now();
        startHeartbeatWatchdog();
        setError(null);
      };
      socket.onmessage = (event) => {
        if (!socketIsCurrent(socket)) {
          return;
        }
        try {
          const frame = JSON.parse(event.data) as RuntimeWebSocketFrame;
          if ("session_id" in frame && !lineageSessionIds.has(frame.session_id)) {
            return;
          }
          lastFrameAt = Date.now();
          if (frame.type === "runtime.snapshot") {
            const declaredLineage = frame.lineage_session_ids || [frame.session.session_id];
            if (
              frame.requested_session_id
              && frame.requested_session_id !== currentSessionId
            ) {
              return;
            }
            if (
              !frame.requested_session_id
              && !declaredLineage.includes(currentSessionId)
            ) {
              return;
            }
            declaredLineage.forEach((sessionId) => lineageSessionIds.add(sessionId));
            activeRuntimeSessionId = frame.session.session_id;
            receivedInitialSnapshot = true;
            setActiveSession({
              ...frame.session,
              runtime_admission: frame.runtime_admission ?? frame.session.runtime_admission ?? null,
            });
            lastEventId = frame.last_event_id || lastEventId;
            if (typeof frame.has_more_before === "boolean") {
              setHasMoreHistory?.(frame.has_more_before === true);
            }
            applyIncomingEvents(hydrateMissingTurnAnchors(frame.events || [], frame.turns), frame.oldest_event_id);
            if (!frame.events?.length) {
              oldestEventIdRef.current = frame.oldest_event_id || oldestEventIdRef.current;
            }
            onUsageSnapshotRef.current?.(chatUsageSummaryFromPayload(frame.usage));
            onRuntimeSnapshotRef.current?.();
            return;
          }
          if (frame.type === "runtime.history.page") {
            setHasMoreHistory?.(frame.has_more_before === true);
            applyHistoryPage(hydrateMissingTurnAnchors(frame.events || [], frame.turns), frame.oldest_event_id);
            setIsOlderHistoryLoading?.(false);
            return;
          }
          const runtimeEvent = runtimeEventFromWebSocketFrame(frame);
          if (runtimeEvent) {
            applyIncomingEvents([runtimeEvent]);
          }
        } catch (parseError) {
          if (!socketIsCurrent(socket)) {
            return;
          }
          setError(parseError instanceof Error ? parseError.message : "Unable to parse runtime WebSocket frame.");
        }
      };
      socket.onerror = () => {
        if (!socketIsCurrent(socket)) {
          return;
        }
        if (!socketOpened) {
          setError("Runtime WebSocket is unavailable.");
        }
      };
      socket.onclose = (event) => {
        if (!socketIsCurrent(socket)) {
          return;
        }
        stopHeartbeatWatchdog();
        if (socketRef.current === socket) {
          socketRef.current = null;
        }
        if (cancelled || unavailableReported) {
          return;
        }
        if (event.code === 4401 || event.code === 4404) {
          reportUnavailableSession();
          return;
        }
        reconnectTimer = window.setTimeout(connectWebSocket, 500);
      };
    }

    function startHeartbeatWatchdog() {
      stopHeartbeatWatchdog();
      heartbeatTimer = window.setInterval(() => {
        if (Date.now() - lastFrameAt > 60000) {
          socket?.close();
        }
      }, 10000);
    }

    function stopHeartbeatWatchdog() {
      if (heartbeatTimer !== null) {
        window.clearInterval(heartbeatTimer);
        heartbeatTimer = null;
      }
    }

    connectWebSocket();

    return () => {
      cancelled = true;
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
      }
      stopHeartbeatWatchdog();
      socket?.close();
      if (socketRef.current === socket) {
        socketRef.current = null;
      }
    };
  }, [runtimeSessionId, setActiveSession, setActiveTurn, setError, setEvents, setHasMoreHistory, setIsOlderHistoryLoading, setPendingUserMessages]);

  useEffect(() => {
    if (!runtimeSessionId || olderHistoryRequestId <= 0) {
      return;
    }
    if (!hasMoreHistoryRef.current) {
      setIsOlderHistoryLoading?.(false);
      return;
    }
    const beforeEventId = oldestEventIdRef.current;
    const socket = socketRef.current;
    if (!beforeEventId || !socket || socket.readyState !== WebSocket.OPEN) {
      setIsOlderHistoryLoading?.(false);
      return;
    }
    socket.send(
      JSON.stringify({
        type: "runtime.history.before",
        before_event_id: beforeEventId,
        limit: 250,
      }),
    );
  }, [olderHistoryRequestId, runtimeSessionId, setIsOlderHistoryLoading]);
}

export function chatUsageSummaryFromPayload(value: unknown): ChatUsageSummary | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const payload = value as Record<string, unknown>;
  const tokens = payload.tokens;
  if (
    typeof payload.root_session_id !== "string"
    || !tokens
    || typeof tokens !== "object"
    || Array.isArray(tokens)
    || typeof (tokens as Record<string, unknown>).total_tokens !== "number"
  ) {
    return null;
  }
  return payload as unknown as ChatUsageSummary;
}
