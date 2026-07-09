import { useEffect, useRef } from "react";
import type { Dispatch, SetStateAction } from "react";
import { listRuntimeThreads, orderChatThreads } from "../api/client";
import type { ChatThread, RuntimeThreadWebSocketFrame, RuntimeThreadsPayload } from "../api/client";
import { getRuntimeThreadSource } from "./runtimeThreadSource";

type RuntimeThreadSnapshotFrame = Extract<RuntimeThreadWebSocketFrame, { type: "runtime.thread.snapshot" }>;

type RuntimeThreadsArgs = {
  enabled?: boolean;
  onSnapshot?: ((frame: RuntimeThreadSnapshotFrame) => void) | null;
  setError: Dispatch<SetStateAction<string | null>>;
  setThreads: Dispatch<SetStateAction<ChatThread[]>>;
};

function isRuntimeThreadStreamError(message: string): boolean {
  return message.startsWith("Runtime thread ");
}

export function useRuntimeThreads({ enabled = true, onSnapshot, setError, setThreads }: RuntimeThreadsArgs) {
  const onSnapshotRef = useRef<typeof onSnapshot>(onSnapshot);
  useEffect(() => {
    onSnapshotRef.current = onSnapshot;
  }, [onSnapshot]);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    function applyThreads(threads: ChatThread[]) {
      setThreads(orderChatThreads(threads || []));
    }

    function snapshotFrameFromPayload(payload: RuntimeThreadsPayload): RuntimeThreadSnapshotFrame {
      return {
        type: "runtime.thread.snapshot",
        workspace_id: payload.workspace_id || "",
        threads: payload.threads || [],
        threads_page: payload.threads_page,
        at: new Date().toISOString(),
      };
    }

    let disposed = false;
    let hasLoadedSnapshot = false;
    let hasWebSocketSnapshot = false;
    const fallbackController = new AbortController();

    function applyThreadSnapshot(frame: RuntimeThreadSnapshotFrame, source: "rest" | "websocket") {
      if (source === "websocket") {
        hasWebSocketSnapshot = true;
      }
      hasLoadedSnapshot = true;
      applyThreads(frame.threads);
      onSnapshotRef.current?.(frame);
    }

    function handleStreamError(message: string | null) {
      if (message && hasLoadedSnapshot && isRuntimeThreadStreamError(message)) {
        setError(null);
        return;
      }
      setError(message);
    }

    function applyThreadDelta(frame: Extract<RuntimeThreadWebSocketFrame, { type: "runtime.thread.changed" }>) {
      if (Array.isArray(frame.threads)) {
        applyThreads(frame.threads);
        return;
      }
      setThreads((current) => {
        const deletedThreadIds = new Set(frame.deleted_thread_ids || []);
        const deletedRuntimeSessionIds = new Set(frame.deleted_runtime_session_ids || []);
        const retained = current.filter(
          (thread) => !deletedThreadIds.has(thread.thread_id) && !deletedRuntimeSessionIds.has(thread.runtime_session_id),
        );
        if (!frame.thread) {
          return orderChatThreads(retained);
        }
        const next = retained.filter((thread) => thread.thread_id !== frame.thread?.thread_id);
        next.push(frame.thread);
        return orderChatThreads(next);
      });
    }

    const unsubscribe = getRuntimeThreadSource().subscribe({
      onError: handleStreamError,
      onFrame: (frame) => {
        if (frame.type === "runtime.thread.snapshot") {
          applyThreadSnapshot(frame, "websocket");
          return;
        }
        if (frame.type === "runtime.thread.changed") {
          applyThreadDelta(frame);
        }
      },
    });
    listRuntimeThreads({ signal: fallbackController.signal })
      .then((payload) => {
        if (disposed || hasWebSocketSnapshot) {
          return;
        }
        applyThreadSnapshot(snapshotFrameFromPayload(payload), "rest");
        setError(null);
      })
      .catch((loadError: Error) => {
        if (!disposed && loadError.name !== "AbortError") {
          setError(loadError.message);
        }
      });
    return () => {
      disposed = true;
      fallbackController.abort();
      unsubscribe();
    };
  }, [enabled, setError, setThreads]);
}
