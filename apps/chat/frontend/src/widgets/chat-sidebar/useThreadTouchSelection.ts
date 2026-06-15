import type { PointerEvent as ReactPointerEvent } from "react";
import { useEffect, useRef, useState } from "react";
import type { ChatThread } from "../../api/client";

type UseThreadTouchSelectionParams = {
  isShellMobileLayout: boolean;
  selectThread: (thread: ChatThread) => void;
};

const LONG_PRESS_MS = 520;
const TOUCH_MOVE_TOLERANCE_PX = 10;
const TOUCH_ACTIONS_VISIBLE_MS = 5200;

export function useThreadTouchSelection({ isShellMobileLayout, selectThread }: UseThreadTouchSelectionParams) {
  const [areThreadActionsRevealed, setAreThreadActionsRevealed] = useState(false);
  const touchThreadPointerStartRef = useRef<{
    longPressTriggered: boolean;
    pointerId: number;
    threadId: string;
    timerId: number;
    x: number;
    y: number;
  } | null>(null);
  const touchSelectedThreadIdRef = useRef<string | null>(null);
  const touchSelectedThreadResetRef = useRef<number | null>(null);
  const threadActionsRevealResetRef = useRef<number | null>(null);

  useEffect(
    () => () => {
      clearTrackedTouch();
      if (touchSelectedThreadResetRef.current !== null) {
        window.clearTimeout(touchSelectedThreadResetRef.current);
      }
      if (threadActionsRevealResetRef.current !== null) {
        window.clearTimeout(threadActionsRevealResetRef.current);
      }
    },
    [],
  );

  useEffect(() => {
    if (!isShellMobileLayout) {
      clearTrackedTouch();
      setAreThreadActionsRevealed(false);
    }
  }, [isShellMobileLayout]);

  function revealThreadActions() {
    setAreThreadActionsRevealed(true);
    if (threadActionsRevealResetRef.current !== null) {
      window.clearTimeout(threadActionsRevealResetRef.current);
    }
    threadActionsRevealResetRef.current = window.setTimeout(() => {
      setAreThreadActionsRevealed(false);
      threadActionsRevealResetRef.current = null;
    }, TOUCH_ACTIONS_VISIBLE_MS);
  }

  function clearTrackedTouch() {
    const start = touchThreadPointerStartRef.current;
    if (start) {
      window.clearTimeout(start.timerId);
    }
    touchThreadPointerStartRef.current = null;
  }

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
    clearTrackedTouch();
    const pointerId = event.pointerId;
    const timerId = window.setTimeout(() => {
      const start = touchThreadPointerStartRef.current;
      if (!start || start.pointerId !== pointerId || start.threadId !== thread.thread_id) {
        return;
      }
      start.longPressTriggered = true;
      revealThreadActions();
    }, LONG_PRESS_MS);
    touchThreadPointerStartRef.current = {
      longPressTriggered: false,
      pointerId,
      threadId: thread.thread_id,
      timerId,
      x: event.clientX,
      y: event.clientY,
    };
  }

  function trackThreadTouchMove(event: ReactPointerEvent<HTMLButtonElement>, thread: ChatThread) {
    if (!isShellMobileLayout || event.pointerType !== "touch") {
      return;
    }
    const start = touchThreadPointerStartRef.current;
    if (!start || start.threadId !== thread.thread_id || start.pointerId !== event.pointerId) {
      return;
    }
    const movedX = Math.abs(event.clientX - start.x);
    const movedY = Math.abs(event.clientY - start.y);
    if (movedX > TOUCH_MOVE_TOLERANCE_PX || movedY > TOUCH_MOVE_TOLERANCE_PX) {
      clearTrackedTouch();
    }
  }

  function cancelThreadTouch(event: ReactPointerEvent<HTMLButtonElement>, thread: ChatThread) {
    if (!isShellMobileLayout || event.pointerType !== "touch") {
      return;
    }
    const start = touchThreadPointerStartRef.current;
    if (!start || start.threadId !== thread.thread_id || start.pointerId !== event.pointerId) {
      return;
    }
    clearTrackedTouch();
  }

  function selectThreadFromPointer(event: ReactPointerEvent<HTMLButtonElement>, thread: ChatThread) {
    if (!isShellMobileLayout || event.pointerType !== "touch") {
      return;
    }
    const start = touchThreadPointerStartRef.current;
    clearTrackedTouch();
    if (start?.threadId === thread.thread_id) {
      if (start.longPressTriggered) {
        event.preventDefault();
        event.stopPropagation();
        markTouchThreadSelection(thread.thread_id);
        return;
      }
      const movedX = Math.abs(event.clientX - start.x);
      const movedY = Math.abs(event.clientY - start.y);
      if (movedX > TOUCH_MOVE_TOLERANCE_PX || movedY > TOUCH_MOVE_TOLERANCE_PX) {
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
    areThreadActionsRevealed,
    cancelThreadTouch,
    selectThreadFromClick,
    selectThreadFromPointer,
    trackThreadTouchMove,
    trackThreadTouchStart,
  };
}
