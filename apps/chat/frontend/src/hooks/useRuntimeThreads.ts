import { readChatDisplay, displayThread, invalidateChatDisplay } from '../pwaCache';
import { useEffect, useRef } from "react";
import type { Dispatch, SetStateAction } from "react";
import { orderChatThreads } from "../api/client";
import type { ChatThread, RuntimeThreadWebSocketFrame } from "../api/client";
import { getRuntimeThreadSource } from "./runtimeThreadSource";

type RuntimeThreadSnapshotFrame = Extract<RuntimeThreadWebSocketFrame, { type: "runtime.thread.snapshot" }>;

type RuntimeThreadsArgs = {
  enabled?: boolean;
  onDisplayReady?: (() => void) | null;
  onSnapshot?: ((frame: RuntimeThreadSnapshotFrame) => void) | null;
  setError: Dispatch<SetStateAction<string | null>>;
  setThreads: Dispatch<SetStateAction<ChatThread[]>>;
};

function isRuntimeThreadStreamError(message: string): boolean {
  return message.startsWith("Runtime thread ");
}

export function useRuntimeThreads({ enabled = true, onSnapshot, onDisplayReady, setError, setThreads }: RuntimeThreadsArgs) {
  const onDisplayReadyRef = useRef(onDisplayReady);
  onDisplayReadyRef.current = onDisplayReady;
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
    const displayController = new AbortController();
    const paintDisplay = (data: { threads: Record<string, unknown>[] }) => {
      if (displayController.signal.aborted || hasLoadedSnapshot) return;
      applyThreads(data.threads.map(displayThread));
      onDisplayReadyRef.current?.();
    };
    void readChatDisplay<{ threads: Record<string, unknown>[] }>({ kind: 'threads', limit: 100 }, {
      signal: displayController.signal, onRevalidated: paintDisplay,
    }).then(paintDisplay).catch(() => { /* The live stream owns terminal UI errors. */ });


    function applyThreadSnapshot(frame: RuntimeThreadSnapshotFrame) {
      if (hasLoadedSnapshot) invalidateChatDisplay('runtime-threads');
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
      invalidateChatDisplay('runtime-threads');
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
      displayController.abort();
      unsubscribe();
    };
  }, [enabled, setError, setThreads]);
}
