import { readChatDisplay, displayMessageEvents, invalidateChatDisplay, type CompletedDisplayMessage } from '../pwaCache';
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
import { runtimeFrameBatch } from '../lib/runtimeFrameBatch';
import { socketReconnectDelay } from '../lib/socketReconnectDelay';
import { useRuntimeHistoryWindow, type RuntimeHistoryArgs } from './useRuntimeHistoryWindow';
import { useChatVisibility } from './useChatVisibility';
import {
  hydrateMissingTurnAnchors,
  inferActiveRuntimeTurn,
  isSyntheticRuntimeEvent,
  lastRuntimeEventId,
  liveRuntimeTurnAfterEvents,
  runtimeTurnStatusFromEvent,
} from "../lib/runtimeEvents";

type RuntimeEventsArgs = RuntimeHistoryArgs & {
  activeTurn: RuntimeTurn | null;
  onRuntimeSessionUnavailable?: ((runtimeSessionId: string) => void) | null;
  onRuntimeSnapshot?: (() => void) | null;
  onUsageSnapshot?: ((usage: ChatUsageSummary | null) => void) | null;
  setActiveSession: Dispatch<SetStateAction<RuntimeSession | null>>;
  setActiveTurn: Dispatch<SetStateAction<RuntimeTurn | null>>;
  setEvents: Dispatch<SetStateAction<RuntimeEvent[]>>;
  setError: Dispatch<SetStateAction<string | null>>;
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
  if (activeTurn.client_message_id) {
    setPendingUserMessages(current => current.filter(item => item.clientMessageId !== activeTurn.client_message_id));
  }
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
  onRuntimeSessionUnavailable,
  onRuntimeSnapshot,
  onUsageSnapshot,
  runtimeSessionId,
  setActiveSession,
  setActiveTurn,
  setError,
  setEvents,
  setHasMoreHistory,
  setPendingUserMessages,
  ...historyArgs
}: RuntimeEventsArgs) {
  const visible = useChatVisibility();
  const activeTurnRef = useRef<RuntimeTurn | null>(activeTurn);
  const onRuntimeSnapshotRef = useRef<typeof onRuntimeSnapshot>(onRuntimeSnapshot);
  const onUsageSnapshotRef = useRef<typeof onUsageSnapshot>(onUsageSnapshot);
  const onRuntimeSessionUnavailableRef = useRef<typeof onRuntimeSessionUnavailable>(onRuntimeSessionUnavailable);
  const socketRef = useRef<WebSocket | null>(null);
  const { apply: applyWindow, receive: receiveHistoryPage, resetRequest: resetHistoryRequest, resumeRestore } = useRuntimeHistoryWindow({
    ...historyArgs, runtimeSessionId, setHasMoreHistory, setEvents, activeTurnRef, socketRef,
  });
  useEffect(() => {
    activeTurnRef.current = activeTurn;
  }, [activeTurn]);
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
    if (!runtimeSessionId || !visible) {
      return;
    }
    const currentSessionId = runtimeSessionId;
    let cancelled = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: number | null = null;
    let reconnectAttempt = 0;
    let heartbeatTimer: number | null = null;
    let lastEventId: string | null = null;
    let receivedInitialSnapshot = false;
    const displayController = new AbortController();
    let paintedDisplay = false;
    const paintDisplay = (data: { messages: CompletedDisplayMessage[] }) => {
      if (cancelled || receivedInitialSnapshot) return;
      setEvents(current => {
        if (current.some(event => event.session_id === currentSessionId)) return current;
        paintedDisplay = true;
        setHasMoreHistory?.(data.messages.length > 0);
        onRuntimeSnapshotRef.current?.();
        return displayMessageEvents(currentSessionId, data.messages);
      });
    };
    void readChatDisplay<{ messages: CompletedDisplayMessage[] }>({ kind: 'messages', session_id: currentSessionId }, {
      signal: displayController.signal, onRevalidated: paintDisplay,
    }).then(paintDisplay).catch(() => { /* The authenticated stream still determines availability. */ });

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

    function socketIsCurrent(candidate: WebSocket | null): candidate is WebSocket {
      return Boolean(candidate && !cancelled && socketRef.current === candidate);
    }

    function eventsForCurrentSession(incoming: RuntimeEvent[]): RuntimeEvent[] {
      return incoming.every((event) => event.session_id === currentSessionId) ? incoming
        : incoming.filter((event) => event.session_id === currentSessionId);
    }

    function applyIncomingEvents(incoming: RuntimeEvent[], source: "live" | "snapshot" = "live", page?: { has_more_before?: boolean }) {
      let scopedIncoming = eventsForCurrentSession(incoming);
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
      // Coalesced usage snapshots have no durable replay cursor.
      scopedIncoming = scopedIncoming.filter((event) => event.event_type !== 'runtime.usage.updated');
      if (!scopedIncoming.length) return;
      const persistedIncoming = scopedIncoming.filter((event) => !isSyntheticRuntimeEvent(event));
      lastEventId = (persistedIncoming.at(-1) || scopedIncoming[scopedIncoming.length - 1]).event_id;
      const previousTurn = activeTurnRef.current;
      const currentTurn = previousTurn?.session_id === currentSessionId ? previousTurn : null;
      applyRuntimeEventEffects(scopedIncoming, currentTurn, setActiveTurn, setPendingUserMessages);
      const nextTurn = source === 'snapshot' ? inferActiveRuntimeTurn(scopedIncoming, currentSessionId)
        : liveRuntimeTurnAfterEvents(scopedIncoming, currentTurn, currentSessionId);
      activeTurnRef.current = nextTurn;
      setActiveTurn(nextTurn);
      applyWindow(scopedIncoming, source, page);
    }

    const frameBatch = runtimeFrameBatch(applyIncomingEvents);

    if (typeof WebSocket === "undefined") {
      setError("Runtime WebSocket is unavailable.");
      return () => { cancelled = true; displayController.abort(); };
    }

    setEvents((current) => {
      const scopedCurrent = eventsForCurrentSession(current);
      lastEventId = lastRuntimeEventId(scopedCurrent);
      return scopedCurrent;
    });

    function scheduleReconnect() {
      if (cancelled || unavailableReported || reconnectTimer !== null) return;
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        connectWebSocket();
      }, socketReconnectDelay(reconnectAttempt++));
    }

    function connectWebSocket() {
      if (cancelled || unavailableReported) return;
      let socketOpened = false;
      const replayCursor = receivedInitialSnapshot ? lastEventId : null;
      let current: WebSocket;
      try {
        current = new WebSocket(runtimeWebSocketUrl(currentSessionId, replayCursor));
      } catch {
        setError("Runtime WebSocket is unavailable.");
        scheduleReconnect();
        return;
      }
      socket = current;
      socketRef.current = current;
      current.onopen = () => {
        if (!socketIsCurrent(current)) {
          return;
        }
        socketOpened = true;
        lastFrameAt = Date.now();
        startHeartbeatWatchdog();
        setError(null);
      };
      current.onmessage = (event) => {
        if (!socketIsCurrent(current)) {
          return;
        }
        try {
          const frame = JSON.parse(event.data) as RuntimeWebSocketFrame;
          if ("session_id" in frame && frame.session_id !== currentSessionId) {
            return;
          }
          lastFrameAt = Date.now();
          if (frame.type === "runtime.snapshot") {
            frameBatch.flush();
            if (frame.session.session_id !== currentSessionId) {
              return;
            }
            reconnectAttempt = 0;
            if (receivedInitialSnapshot) invalidateChatDisplay('messages');
            receivedInitialSnapshot = true;
            if (paintedDisplay) { setEvents([]); paintedDisplay = false; }

            setActiveSession({
              ...frame.session,
              runtime_admission: frame.runtime_admission ?? frame.session.runtime_admission ?? null,
            });
            lastEventId = frame.last_event_id || lastEventId;
            applyIncomingEvents(hydrateMissingTurnAnchors(frame.events || [], frame.turns), 'snapshot', frame);
            if (!frame.events?.length) {
              activeTurnRef.current = null;
              setActiveTurn(null);
              applyWindow([], 'snapshot', frame);
            }
            onUsageSnapshotRef.current?.(chatUsageSummaryFromPayload(frame.usage));
            onRuntimeSnapshotRef.current?.();
            resumeRestore();
            return;
          }
          if (frame.type === "runtime.history.page") {
            frameBatch.flush();
            receiveHistoryPage(frame);
            return;
          }
          const runtimeEvent = runtimeEventFromWebSocketFrame(frame);
          if (runtimeEvent) {
            if (terminalStatus(runtimeEvent)) {
              invalidateChatDisplay('messages');
              // Refill only through the fixed authenticated read, never replay a
              // WebSocket loader or persist its operational payload.
              void readChatDisplay({ kind: 'messages', session_id: currentSessionId }, { signal: displayController.signal }).catch(() => undefined);
            }
            frameBatch.push(runtimeEvent);
          }
        } catch (parseError) {
          if (!socketIsCurrent(current)) {
            return;
          }
          setError(parseError instanceof Error ? parseError.message : "Unable to parse runtime WebSocket frame.");
        }
      };
      current.onerror = () => {
        if (!socketIsCurrent(current)) {
          return;
        }
        if (!socketOpened) {
          setError("Runtime WebSocket is unavailable.");
        }
      };
      current.onclose = (event) => {
        if (!socketIsCurrent(current)) {
          return;
        }
        stopHeartbeatWatchdog();
        resetHistoryRequest();
        frameBatch.flush();
        socketRef.current = null;
        socket = null;
        if (cancelled || unavailableReported) {
          return;
        }
        if (event.code === 4401 || event.code === 4404) {
          reportUnavailableSession();
          return;
        }
        scheduleReconnect();
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
      resetHistoryRequest();
      frameBatch.dispose();
      displayController.abort();
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
      }
      stopHeartbeatWatchdog();
      socket?.close();
      if (socketRef.current === socket) {
        socketRef.current = null;
      }
    };
  }, [runtimeSessionId, visible, setActiveSession, setActiveTurn, setError, setEvents, setHasMoreHistory, setPendingUserMessages, applyWindow, receiveHistoryPage, resetHistoryRequest, resumeRestore]);
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
