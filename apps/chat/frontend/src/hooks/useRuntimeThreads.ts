import { useEffect, useRef } from "react";
import type { Dispatch, SetStateAction } from "react";
import { ChatThread, orderChatThreads, RuntimeThreadWebSocketFrame, runtimeThreadWebSocketUrl } from "../api/client";

type RuntimeThreadSnapshotFrame = Extract<RuntimeThreadWebSocketFrame, { type: "runtime.thread.snapshot" }>;

type RuntimeThreadsArgs = {
  enabled?: boolean;
  onSnapshot?: ((frame: RuntimeThreadSnapshotFrame) => void) | null;
  setError: Dispatch<SetStateAction<string | null>>;
  setThreads: Dispatch<SetStateAction<ChatThread[]>>;
};

const INITIAL_RECONNECT_DELAY_MS = 500;
const MAX_RECONNECT_DELAY_MS = 10000;

export function useRuntimeThreads({ enabled = true, onSnapshot, setError, setThreads }: RuntimeThreadsArgs) {
  const onSnapshotRef = useRef<typeof onSnapshot>(onSnapshot);
  useEffect(() => {
    onSnapshotRef.current = onSnapshot;
  }, [onSnapshot]);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    if (typeof WebSocket === "undefined") {
      setError("Runtime thread WebSocket is unavailable.");
      return;
    }
    let cancelled = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: number | null = null;
    let heartbeatTimer: number | null = null;
    let lastFrameAt = Date.now();
    let reconnectDelayMs = INITIAL_RECONNECT_DELAY_MS;

    function applyThreads(threads: ChatThread[]) {
      setThreads(orderChatThreads(threads || []));
    }

    function connect() {
      let socketOpened = false;
      socket = new WebSocket(runtimeThreadWebSocketUrl());
      socket.onopen = () => {
        socketOpened = true;
        lastFrameAt = Date.now();
        reconnectDelayMs = INITIAL_RECONNECT_DELAY_MS;
        startHeartbeatWatchdog();
        setError(null);
      };
      socket.onmessage = (event) => {
        lastFrameAt = Date.now();
        try {
          const frame = JSON.parse(event.data) as RuntimeThreadWebSocketFrame;
          if (frame.type === "runtime.thread.snapshot") {
            applyThreads(frame.threads);
            onSnapshotRef.current?.(frame);
            return;
          }
          if (frame.type === "runtime.thread.changed") {
            applyThreads(frame.threads);
          }
        } catch (parseError) {
          setError(parseError instanceof Error ? parseError.message : "Unable to parse runtime thread WebSocket frame.");
        }
      };
      socket.onerror = () => {
        if (!socketOpened) {
          setError("Runtime thread WebSocket is unavailable.");
        }
      };
      socket.onclose = (event) => {
        stopHeartbeatWatchdog();
        if (cancelled) {
          return;
        }
        if (event.code === 4401 || event.code === 4404) {
          setError(event.code === 4401 ? "Runtime thread stream is not authorized." : "Runtime thread stream is unavailable.");
          return;
        }
        reconnectTimer = window.setTimeout(connect, reconnectDelayMs);
        reconnectDelayMs = Math.min(reconnectDelayMs * 2, MAX_RECONNECT_DELAY_MS);
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

    connect();
    return () => {
      cancelled = true;
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
      }
      stopHeartbeatWatchdog();
      socket?.close();
    };
  }, [enabled, setError, setThreads]);
}
