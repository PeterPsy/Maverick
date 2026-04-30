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
import { inferActiveRuntimeTurn, lastRuntimeEventId, mergeRuntimeEvents } from "../lib/runtimeEvents";
import { eventsToMessages } from "../lib/transcript";

type RuntimeEventsArgs = {
  runtimeSessionId: string | null;
  activeTurn: RuntimeTurn | null;
  onRuntimeSessionUnavailable?: ((runtimeSessionId: string) => void) | null;
  onRuntimeSnapshot?: (() => void) | null;
  setActiveSession: Dispatch<SetStateAction<RuntimeSession | null>>;
  setActiveTurn: Dispatch<SetStateAction<RuntimeTurn | null>>;
  setEvents: Dispatch<SetStateAction<RuntimeEvent[]>>;
  setError: Dispatch<SetStateAction<string | null>>;
  setPendingUserMessages: Dispatch<SetStateAction<PendingMessage[]>>;
};

function terminalStatus(eventType: string): RuntimeTurn["status"] | null {
  if (eventType === "runtime.turn.completed") {
    return "completed";
  }
  if (eventType === "runtime.output.final") {
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
  const matchingMessages = eventsToMessages(events);
  const terminalEvent = events.find((event) => event.turn_id === activeTurn.turn_id && terminalStatus(event.event_type));
  if (!terminalEvent) {
    return;
  }
  const status = terminalStatus(terminalEvent.event_type);
  setActiveTurn((current) => (current?.turn_id === activeTurn.turn_id && status ? { ...current, status } : current));
  setPendingUserMessages((current) => current.filter((item) => !matchingMessages.some((message) => message.id === item.clientMessageId)));
}

export function useRuntimeEvents({
  activeTurn,
  onRuntimeSessionUnavailable,
  onRuntimeSnapshot,
  runtimeSessionId,
  setActiveSession,
  setActiveTurn,
  setError,
  setEvents,
  setPendingUserMessages,
}: RuntimeEventsArgs) {
  const activeTurnRef = useRef<RuntimeTurn | null>(activeTurn);
  const onRuntimeSnapshotRef = useRef<typeof onRuntimeSnapshot>(onRuntimeSnapshot);
  const onRuntimeSessionUnavailableRef = useRef<typeof onRuntimeSessionUnavailable>(onRuntimeSessionUnavailable);
  useEffect(() => {
    activeTurnRef.current = activeTurn;
  }, [activeTurn]);
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

    function applyIncomingEvents(incoming: RuntimeEvent[]) {
      if (!incoming.length) {
        return;
      }
      lastEventId = incoming[incoming.length - 1].event_id;
      setEvents((current) => {
        const merged = mergeRuntimeEvents(current, incoming);
        const currentTurn = activeTurnRef.current;
        if (currentTurn) {
          applyRuntimeEventEffects(merged, currentTurn, setActiveTurn, setPendingUserMessages);
        }
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
      setActiveTurn(inferActiveRuntimeTurn(current, currentSessionId));
      return current;
    });

    function connectWebSocket() {
      let socketOpened = false;
      socket = new WebSocket(runtimeWebSocketUrl(currentSessionId, lastEventId));
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
            setActiveSession(frame.session);
            lastEventId = frame.last_event_id || lastEventId;
            applyIncomingEvents(frame.events || []);
            onRuntimeSnapshotRef.current?.();
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
    };
  }, [runtimeSessionId, setActiveSession, setActiveTurn, setError, setEvents, setPendingUserMessages]);
}
