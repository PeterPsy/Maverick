import { useEffect, useRef } from "react";
import { isHorizontalIntent, isSidebarCloseSwipe, type SidebarSwipePoint } from "../lib/sidebarSwipe";

const MOBILE_SIDEBAR_SWIPE_QUERY = "(max-width: 979px)";
const CLOSE_SIDEBAR_MESSAGE = { type: "maverick.shell.sidebar.close" };

type TouchTarget = EventTarget | null;

export function useShellSidebarCloseSwipe(enabled: boolean) {
  const startPointRef = useRef<SidebarSwipePoint | null>(null);
  const trackingTouchIdRef = useRef<number | null>(null);

  useEffect(() => {
    if (!enabled || typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return undefined;
    }

    const mediaQuery = window.matchMedia(MOBILE_SIDEBAR_SWIPE_QUERY);

    function resetSwipe() {
      startPointRef.current = null;
      trackingTouchIdRef.current = null;
    }

    function handleTouchStart(event: TouchEvent) {
      if (!mediaQuery.matches || event.touches.length !== 1 || isTextInputTarget(event.target)) {
        resetSwipe();
        return;
      }
      const touch = event.touches[0];
      startPointRef.current = { x: touch.clientX, y: touch.clientY };
      trackingTouchIdRef.current = touch.identifier;
    }

    function handleTouchMove(event: TouchEvent) {
      const start = startPointRef.current;
      const touch = trackedTouch(event.changedTouches, trackingTouchIdRef.current);
      if (!mediaQuery.matches || !start || !touch) {
        return;
      }
      const current = { x: touch.clientX, y: touch.clientY };
      if (isHorizontalIntent(start, current)) {
        event.preventDefault();
        event.stopPropagation();
      }
      if (isSidebarCloseSwipe(start, current)) {
        event.preventDefault();
        event.stopPropagation();
        window.parent?.postMessage(CLOSE_SIDEBAR_MESSAGE, "*");
        resetSwipe();
      }
    }

    document.addEventListener("touchstart", handleTouchStart, { passive: true });
    document.addEventListener("touchmove", handleTouchMove, { passive: false });
    document.addEventListener("touchcancel", resetSwipe, { passive: true });
    document.addEventListener("touchend", resetSwipe, { passive: true });
    return () => {
      document.removeEventListener("touchstart", handleTouchStart);
      document.removeEventListener("touchmove", handleTouchMove);
      document.removeEventListener("touchcancel", resetSwipe);
      document.removeEventListener("touchend", resetSwipe);
    };
  }, [enabled]);
}

function trackedTouch(touches: TouchList, identifier: number | null): Touch | null {
  if (identifier === null) {
    return null;
  }
  for (const touch of Array.from(touches)) {
    if (touch.identifier === identifier) {
      return touch;
    }
  }
  return null;
}

function isTextInputTarget(target: TouchTarget): boolean {
  if (!(target instanceof Element)) {
    return false;
  }
  return Boolean(target.closest("input, textarea, select, [contenteditable='true'], [data-no-sidebar-swipe]"));
}
