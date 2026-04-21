import { useEffect, useRef } from "react";
import type { Dispatch, SetStateAction } from "react";
import {
  listRuntimeEvents,
  RuntimeEvent,
  runtimeEventFromWebSocketFrame,
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
  setActiveTurn: Dispatch<SetStateAction<RuntimeTurn | null>>;
  setEvents: Dispatch<SetStateAction<RuntimeEvent[]>>;
  setError: Dispatch<SetStateAction<string | null>>;
  setPendingUserMessages: Dispatch<SetStateAction<PendingMessage[]>>;
};

const RUNTIME_EVENT_REPLAY_LIMIT = 1000;

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
  runtimeSessionId,
  setActiveTurn,
  setError,
  setEvents,
  setPendingUserMessages,
}: RuntimeEventsArgs) {
  const activeTurnRef = useRef<RuntimeTurn | null>(activeTurn);
  useEffect(() => {
    activeTurnRef.current = activeTurn;
  }, [activeTurn]);

  useEffect(() => {
    if (!runtimeSessionId) {
      return;
    }
    const currentSessionId = runtimeSessionId;
    let cancelled = false;
    let socket: WebSocket | null = null;
    let fallbackInterval: number | null = null;
    let reconnectTimer: number | null = null;
    let lastEventId: string | null = null;
    let socketOpened = false;

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

    async function refreshFromHttpReplay() {
      try {
        const runtimeEvents = await listRuntimeEvents(currentSessionId, { limit: RUNTIME_EVENT_REPLAY_LIMIT });
        applyIncomingEvents(runtimeEvents.items);
        setError(null);
      } catch (pollError) {
        if (!isTransientReplayError(pollError)) {
          setError(pollError instanceof Error ? pollError.message : "Unable to refresh runtime events.");
        }
      }
    }

    function startHttpFallback() {
      if (cancelled || fallbackInterval !== null) {
        return;
      }
      void refreshFromHttpReplay();
      fallbackInterval = window.setInterval(refreshFromHttpReplay, 900);
    }

    function stopHttpFallback() {
      if (fallbackInterval === null) {
        return;
      }
      window.clearInterval(fallbackInterval);
      fallbackInterval = null;
    }

    if (typeof WebSocket === "undefined") {
      startHttpFallback();
      return () => {
        cancelled = true;
        if (fallbackInterval !== null) {
          window.clearInterval(fallbackInterval);
        }
      };
    }

    setEvents((current) => {
      lastEventId = lastRuntimeEventId(current);
      setActiveTurn(inferActiveRuntimeTurn(current, currentSessionId));
      return current;
    });

    function connectWebSocket() {
      socket = new WebSocket(runtimeWebSocketUrl(currentSessionId, lastEventId));
      socket.onopen = () => {
        socketOpened = true;
        stopHttpFallback();
        setError(null);
      };
      socket.onmessage = (event) => {
        try {
          const frame = JSON.parse(event.data) as RuntimeWebSocketFrame;
          const runtimeEvent = runtimeEventFromWebSocketFrame(frame);
          if (runtimeEvent) {
            applyIncomingEvents([runtimeEvent]);
          }
          if (frame.type === "runtime.replay_complete") {
            lastEventId = frame.last_event_id;
          }
        } catch (parseError) {
          setError(parseError instanceof Error ? parseError.message : "Unable to parse runtime WebSocket frame.");
        }
      };
      socket.onerror = () => {
        if (!socketOpened) {
          setError("Runtime WebSocket is unavailable; using HTTP event replay.");
        }
      };
      socket.onclose = () => {
        if (cancelled) {
          return;
        }
        if (!socketOpened) {
          startHttpFallback();
          return;
        }
        reconnectTimer = window.setTimeout(connectWebSocket, 500);
      };
    }

    connectWebSocket();

    return () => {
      cancelled = true;
      if (fallbackInterval !== null) {
        window.clearInterval(fallbackInterval);
      }
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
      }
      socket?.close();
    };
  }, [runtimeSessionId, setActiveTurn, setError, setEvents, setPendingUserMessages]);
}

export function isTransientReplayError(error: unknown): boolean {
  if (!(error instanceof Error)) {
    return false;
  }
  return /\b(502|503|504)\b|failed to fetch|networkerror|load failed/i.test(error.message);
}
