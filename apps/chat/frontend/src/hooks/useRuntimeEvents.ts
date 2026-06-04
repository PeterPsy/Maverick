import { useEffect, useRef } from "react";
import type { Dispatch, SetStateAction } from "react";
import {
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
} from "../lib/runtimeEvents";

type RuntimeEventsArgs = {
  runtimeSessionId: string | null;
  activeTurn: RuntimeTurn | null;
  hasMoreHistory?: boolean;
  onRuntimeSessionUnavailable?: ((runtimeSessionId: string) => void) | null;
  onRuntimeSnapshot?: (() => void) | null;
  olderHistoryRequestId?: number;
  setActiveSession: Dispatch<SetStateAction<RuntimeSession | null>>;
  setActiveTurn: Dispatch<SetStateAction<RuntimeTurn | null>>;
  setEvents: Dispatch<SetStateAction<RuntimeEvent[]>>;
  setError: Dispatch<SetStateAction<string | null>>;
  setHasMoreHistory?: Dispatch<SetStateAction<boolean>>;
  setIsOlderHistoryLoading?: Dispatch<SetStateAction<boolean>>;
  setPendingUserMessages: Dispatch<SetStateAction<PendingMessage[]>>;
};

function terminalStatus(eventType: string): RuntimeTurn["status"] | null {
  if (eventType === "runtime.output.final") {
    return "completed";
  }
  if (eventType === "runtime.turn.completed") {
    return "completed";
  }
  if (eventType === "runtime.turn.failed") {
    return "failed";
  }
  if (eventType === "runtime.turn.cancelled") {
    return "cancelled";
  }
  return null;
}

export function applyRuntimeEventEffects(
  events: RuntimeEvent[],
  activeTurn: RuntimeTurn,
  setActiveTurn: Dispatch<SetStateAction<RuntimeTurn | null>>,
  setPendingUserMessages: Dispatch<SetStateAction<PendingMessage[]>>,
) {
  const terminalEvent = events.find((event) => event.turn_id === activeTurn.turn_id && terminalStatus(event.event_type));
  if (!terminalEvent) {
    return;
  }
  const status = terminalStatus(terminalEvent.event_type);
  const completedClientMessageIds = new Set(
    events
      .filter((event) => event.turn_id === activeTurn.turn_id && event.event_type === "runtime.turn.queued" && typeof event.payload.client_message_id === "string")
      .map((event) => event.payload.client_message_id as string),
  );
  setActiveTurn((current) => (current?.turn_id === activeTurn.turn_id && status ? { ...current, status } : current));
  setPendingUserMessages((current) => current.filter((item) => !completedClientMessageIds.has(item.clientMessageId)));
}

export function useRuntimeEvents({
  activeTurn,
  hasMoreHistory = false,
  onRuntimeSessionUnavailable,
  onRuntimeSnapshot,
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

    function applyIncomingEvents(incoming: RuntimeEvent[], oldestEventId?: string | null) {
      if (!incoming.length) {
        return;
      }
      const persistedIncoming = incoming.filter((event) => !isSyntheticRuntimeEvent(event));
      lastEventId = (persistedIncoming.at(-1) || incoming[incoming.length - 1]).event_id;
      setEvents((current) => {
        const merged = mergeRuntimeEvents(current, incoming);
        setOldestEventCursor(merged, oldestEventId);
        const currentTurn = activeTurnRef.current;
        if (currentTurn) {
          applyRuntimeEventEffects(merged, currentTurn, setActiveTurn, setPendingUserMessages);
        }
        setActiveTurn(inferActiveRuntimeTurn(merged, currentSessionId));
        return merged;
      });
    }

    function applyHistoryPage(incoming: RuntimeEvent[], oldestEventId?: string | null) {
      setEvents((current) => {
        const merged = mergeRuntimeEvents(current, incoming);
        setOldestEventCursor(merged, oldestEventId);
        setActiveTurn(inferActiveRuntimeTurn(merged, currentSessionId));
        return merged;
      });
    }

    if (typeof WebSocket === "undefined") {
      setError("Runtime WebSocket is unavailable.");
      return;
    }

    setEvents((current) => {
      lastEventId = lastRuntimeEventId(current);
      setOldestEventCursor(current);
      setActiveTurn(inferActiveRuntimeTurn(current, currentSessionId));
      return current;
    });

    function connectWebSocket() {
      let socketOpened = false;
      const replayCursor = receivedInitialSnapshot ? lastEventId : null;
      socket = new WebSocket(runtimeWebSocketUrl(currentSessionId, replayCursor));
      socketRef.current = socket;
      socket.onopen = () => {
        socketOpened = true;
        lastFrameAt = Date.now();
        startHeartbeatWatchdog();
        setError(null);
      };
      socket.onmessage = (event) => {
        lastFrameAt = Date.now();
        try {
          const frame = JSON.parse(event.data) as RuntimeWebSocketFrame;
          if (frame.type === "runtime.snapshot") {
            receivedInitialSnapshot = true;
            setActiveSession(frame.session);
            lastEventId = frame.last_event_id || lastEventId;
            if (typeof frame.has_more_before === "boolean") {
              setHasMoreHistory?.(frame.has_more_before === true);
            }
            applyIncomingEvents(hydrateMissingTurnAnchors(frame.events || [], frame.turns), frame.oldest_event_id);
            if (!frame.events?.length) {
              oldestEventIdRef.current = frame.oldest_event_id || oldestEventIdRef.current;
            }
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
          setError(parseError instanceof Error ? parseError.message : "Unable to parse runtime WebSocket frame.");
        }
      };
      socket.onerror = () => {
        if (!socketOpened) {
          setError("Runtime WebSocket is unavailable.");
        }
      };
      socket.onclose = (event) => {
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
