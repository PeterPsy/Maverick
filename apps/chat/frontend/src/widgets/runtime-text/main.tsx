import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import type { PendingMessage } from "../../lib/messageState";
import type { RuntimeEvent, RuntimeSession, RuntimeTurn } from "../../api/client";
import { getWidgetContext } from "../../api/client";
import { useRuntimeEvents } from "../../hooks/useRuntimeEvents";
import { applyInitialMaverickTheme, listenForMaverickThemeMessages } from "../../lib/shellTheme";
import { eventsToMessages } from "../../lib/transcript";
import "./styles.css";

applyInitialMaverickTheme();
listenForMaverickThemeMessages();

const CONTENT_KIND = "chat.runtime.text.preview";
const MAX_VISIBLE_MESSAGES = 12;

type RuntimeTextPayload = {
  node_id?: string;
  runtime_session_id?: string;
};

function widgetContextToken(): string {
  const hash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : window.location.hash;
  return new URLSearchParams(hash).get("context") || new URLSearchParams(window.location.search).get("context") || "";
}

function runtimePayloadFromContext(context: Record<string, unknown>): RuntimeTextPayload {
  const content = context.content && typeof context.content === "object" ? (context.content as Record<string, unknown>) : {};
  if (content.kind !== CONTENT_KIND) {
    return {};
  }
  const payload = content.payload && typeof content.payload === "object" ? (content.payload as Record<string, unknown>) : content;
  return {
    node_id: stringValue(payload.node_id),
    runtime_session_id: stringValue(payload.runtime_session_id),
  };
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function RuntimeTextWidget() {
  const rootRef = useRef<HTMLElement | null>(null);
  const [payload, setPayload] = useState<RuntimeTextPayload>({});
  const [contextError, setContextError] = useState<string | null>(null);
  const [runtimeError, setRuntimeError] = useState<string | null>(null);
  const [snapshotLoaded, setSnapshotLoaded] = useState(false);
  const [activeSession, setActiveSession] = useState<RuntimeSession | null>(null);
  const [activeTurn, setActiveTurn] = useState<RuntimeTurn | null>(null);
  const [events, setEvents] = useState<RuntimeEvent[]>([]);
  const [, setPendingMessages] = useState<PendingMessage[]>([]);
  const runtimeSessionId = payload.runtime_session_id || null;

  useRuntimeEvents({
    activeTurn,
    onRuntimeSessionUnavailable: () => {
      setRuntimeError("Runtime session unavailable.");
      setSnapshotLoaded(true);
    },
    onRuntimeSnapshot: () => setSnapshotLoaded(true),
    runtimeSessionId,
    setActiveSession,
    setActiveTurn,
    setError: setRuntimeError,
    setEvents,
    setPendingUserMessages: setPendingMessages,
  });

  const messages = useMemo(
    () =>
      eventsToMessages(events)
        .filter((message) => message.content.trim() && ["human", "agent", "system"].includes(message.role))
        .slice(-MAX_VISIBLE_MESSAGES),
    [events],
  );

  useEffect(() => {
    let cancelled = false;
    async function loadContext() {
      const token = widgetContextToken();
      if (!token) {
        setContextError("Missing widget context.");
        return;
      }
      try {
        const nextContext = await getWidgetContext(token);
        if (!cancelled) {
          setPayload(runtimePayloadFromContext(nextContext.context));
          setContextError(null);
          setRuntimeError(null);
          setSnapshotLoaded(false);
          setEvents([]);
          setActiveTurn(null);
          setActiveSession(null);
        }
      } catch (error) {
        if (!cancelled) {
          setContextError(error instanceof Error ? error.message : "Widget context unavailable.");
        }
      }
    }

    void loadContext();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin || !event.data || typeof event.data !== "object") {
        return;
      }
      const message = event.data as { context?: Record<string, unknown>; type?: string };
      if (message.type !== "maverick.widget.context-changed" || !message.context) {
        return;
      }
      setPayload(runtimePayloadFromContext(message.context));
      setContextError(null);
      setRuntimeError(null);
      setSnapshotLoaded(false);
      setEvents([]);
      setActiveTurn(null);
      setActiveSession(null);
    }

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, []);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) {
      return;
    }
    const height = `${Math.min(280, Math.max(112, root.scrollHeight))}px`;
    window.parent?.postMessage(
      {
        type: "maverick.widget.resize",
        owner_app_id: "chat",
        widget_id: "chat-runtime-text",
        height,
        width: "100%",
      },
      "*",
    );
  }, [contextError, runtimeError, messages.length, snapshotLoaded]);

  const isLoading = Boolean(runtimeSessionId) && !snapshotLoaded && !runtimeError;
  const emptyLabel = activeSession ? "No text yet." : "Waiting for runtime session.";

  return (
    <main className="chat-runtime-text" ref={rootRef}>
      {contextError || runtimeError ? <p className="chat-runtime-text__state is-error">{contextError || runtimeError}</p> : null}
      {!contextError && !runtimeError && !runtimeSessionId ? <p className="chat-runtime-text__state">{emptyLabel}</p> : null}
      {!contextError && !runtimeError && runtimeSessionId ? (
        <>
          {messages.length ? (
            <div className="chat-runtime-text__messages" aria-live="polite">
              {messages.map((message) => (
                <article className={`chat-runtime-text__message is-${message.role}`} key={message.id}>
                  <span className="chat-runtime-text__role">{message.role === "human" ? "You" : message.role === "system" ? "System" : "Agent"}</span>
                  <p>{message.content}</p>
                </article>
              ))}
            </div>
          ) : null}
          {!messages.length && isLoading ? <p className="chat-runtime-text__state">Loading transcript</p> : null}
          {!messages.length && !isLoading ? <p className="chat-runtime-text__state">{emptyLabel}</p> : null}
        </>
      ) : null}
    </main>
  );
}

createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <RuntimeTextWidget />
  </React.StrictMode>,
);
