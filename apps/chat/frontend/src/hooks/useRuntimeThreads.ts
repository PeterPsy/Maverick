import { useEffect, useRef } from "react";
import type { Dispatch, SetStateAction } from "react";
import { orderChatThreads } from "../api/client";
import type { ChatThread, RuntimeThreadWebSocketFrame } from "../api/client";
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

    let hasLoadedSnapshot = false;

    function applyThreadSnapshot(frame: RuntimeThreadSnapshotFrame) {
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
          applyThreadSnapshot(frame);
          return;
        }
        if (frame.type === "runtime.thread.changed") {
          applyThreadDelta(frame);
        }
      },
    });
    return () => {
      unsubscribe();
    };
  }, [enabled, setError, setThreads]);
}
