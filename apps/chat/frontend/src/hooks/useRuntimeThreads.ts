import { useEffect, useRef } from "react";
import type { Dispatch, SetStateAction } from "react";
import { ChatThread, RuntimeThreadWebSocketFrame, runtimeThreadWebSocketUrl } from "../api/client";

type RuntimeThreadsArgs = {
  onSnapshot?: (() => void) | null;
  setError: Dispatch<SetStateAction<string | null>>;
  setThreads: Dispatch<SetStateAction<ChatThread[]>>;
};

export function useRuntimeThreads({ onSnapshot, setError, setThreads }: RuntimeThreadsArgs) {
  const onSnapshotRef = useRef<typeof onSnapshot>(onSnapshot);
  useEffect(() => {
    onSnapshotRef.current = onSnapshot;
  }, [onSnapshot]);

  useEffect(() => {
    if (typeof WebSocket === "undefined") {
      setError("Runtime thread WebSocket is unavailable.");
      return;
    }
    let cancelled = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: number | null = null;
    let heartbeatTimer: number | null = null;
    let lastFrameAt = Date.now();

    function applyThreads(threads: ChatThread[]) {
      setThreads(threads || []);
    }

    function connect() {
      socket = new WebSocket(runtimeThreadWebSocketUrl());
      socket.onopen = () => {
        lastFrameAt = Date.now();
        startHeartbeatWatchdog();
        setError(null);
      };
      socket.onmessage = (event) => {
        lastFrameAt = Date.now();
        try {
          const frame = JSON.parse(event.data) as RuntimeThreadWebSocketFrame;
          if (frame.type === "runtime.thread.snapshot") {
            applyThreads(frame.threads);
            onSnapshotRef.current?.();
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
        setError("Runtime thread WebSocket is unavailable.");
      };
      socket.onclose = () => {
        stopHeartbeatWatchdog();
        if (!cancelled) {
          reconnectTimer = window.setTimeout(connect, 500);
        }
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
  }, [setError, setThreads]);
}
