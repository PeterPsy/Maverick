import type { PointerEvent as ReactPointerEvent } from "react";
import { useEffect, useRef } from "react";
import type { ChatThread } from "../../api/client";

type UseThreadTouchSelectionParams = {
  isShellMobileLayout: boolean;
  selectThread: (thread: ChatThread) => void;
};

export function useThreadTouchSelection({ isShellMobileLayout, selectThread }: UseThreadTouchSelectionParams) {
  const touchThreadPointerStartRef = useRef<{ threadId: string; x: number; y: number } | null>(null);
  const touchSelectedThreadIdRef = useRef<string | null>(null);
  const touchSelectedThreadResetRef = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (touchSelectedThreadResetRef.current !== null) {
        window.clearTimeout(touchSelectedThreadResetRef.current);
      }
    },
    [],
  );

  function markTouchThreadSelection(threadId: string) {
    touchSelectedThreadIdRef.current = threadId;
    if (touchSelectedThreadResetRef.current !== null) {
      window.clearTimeout(touchSelectedThreadResetRef.current);
    }
    touchSelectedThreadResetRef.current = window.setTimeout(() => {
      touchSelectedThreadIdRef.current = null;
      touchSelectedThreadResetRef.current = null;
    }, 450);
  }

  function trackThreadTouchStart(event: ReactPointerEvent<HTMLButtonElement>, thread: ChatThread) {
    if (!isShellMobileLayout || event.pointerType !== "touch") {
      return;
    }
    touchThreadPointerStartRef.current = { threadId: thread.thread_id, x: event.clientX, y: event.clientY };
  }

  function selectThreadFromPointer(event: ReactPointerEvent<HTMLButtonElement>, thread: ChatThread) {
    if (!isShellMobileLayout || event.pointerType !== "touch") {
      return;
    }
    const start = touchThreadPointerStartRef.current;
    touchThreadPointerStartRef.current = null;
    if (start?.threadId === thread.thread_id) {
      const movedX = Math.abs(event.clientX - start.x);
      const movedY = Math.abs(event.clientY - start.y);
      if (movedX > 10 || movedY > 10) {
        return;
      }
    }
    event.preventDefault();
    event.stopPropagation();
    markTouchThreadSelection(thread.thread_id);
    selectThread(thread);
  }

  function selectThreadFromClick(thread: ChatThread) {
    if (touchSelectedThreadIdRef.current === thread.thread_id) {
      touchSelectedThreadIdRef.current = null;
      if (touchSelectedThreadResetRef.current !== null) {
        window.clearTimeout(touchSelectedThreadResetRef.current);
        touchSelectedThreadResetRef.current = null;
      }
      return;
    }
    selectThread(thread);
  }

  return {
    selectThreadFromClick,
    selectThreadFromPointer,
    trackThreadTouchStart,
  };
}
