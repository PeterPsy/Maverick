import { useEffect, useRef } from "react";
import { isSidebarCloseSwipe, isSidebarOpenSwipe, startsInSidebarSwipeZone, type SidebarSwipePoint, type SidebarSwipeViewport } from "../lib/sidebarSwipe";

const MOBILE_SIDEBAR_SWIPE_QUERY = "(max-width: 979px)";
const OPEN_SIDEBAR_MESSAGE = { app_id: "chat", type: "maverick.shell.sidebar.open" };
const CLOSE_SIDEBAR_MESSAGE = { type: "maverick.shell.sidebar.close" };

type TouchTarget = EventTarget | null;
type SwipeMatcher = (start: SidebarSwipePoint, end: SidebarSwipePoint, viewport: SidebarSwipeViewport) => boolean;
type SwipeTargetFilter = (target: TouchTarget) => boolean;

export function useShellSidebarSwipe() {
  useShellSidebarGesture({
    ignoreTarget: isInteractiveTarget,
    isSwipe: isSidebarOpenSwipe,
    message: OPEN_SIDEBAR_MESSAGE,
    preventHorizontalDefault: true,
  });
}

export function useShellSidebarCloseSwipe(enabled: boolean) {
  useShellSidebarGesture({
    enabled,
    ignoreTarget: isTextInputTarget,
    isSwipe: isSidebarCloseSwipe,
    message: CLOSE_SIDEBAR_MESSAGE,
    preventHorizontalDefault: true,
    requireStartZone: false,
  });
}

function useShellSidebarGesture({
  enabled = true,
  ignoreTarget,
  isSwipe,
  message,
  preventHorizontalDefault = false,
  requireStartZone = true,
}: {
  enabled?: boolean;
  ignoreTarget: SwipeTargetFilter;
  isSwipe: SwipeMatcher;
  message: Record<string, string>;
  preventHorizontalDefault?: boolean;
  requireStartZone?: boolean;
}) {
  const startPointRef = useRef<SidebarSwipePoint | null>(null);
  const trackingTouchIdRef = useRef<number | null>(null);

  useEffect(() => {
    if (!enabled || typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return undefined;
    }

    const mediaQuery = window.matchMedia(MOBILE_SIDEBAR_SWIPE_QUERY);

    function viewport() {
      return {
        width: window.innerWidth,
        height: window.innerHeight,
      };
    }

    function resetSwipe() {
      startPointRef.current = null;
      trackingTouchIdRef.current = null;
    }

    function handleTouchStart(event: TouchEvent) {
      if (!mediaQuery.matches || event.touches.length !== 1 || ignoreTarget(event.target)) {
        resetSwipe();
        return;
      }
      const touch = event.touches[0];
      const start = { x: touch.clientX, y: touch.clientY };
      if (requireStartZone && !startsInSidebarSwipeZone(start, viewport())) {
        resetSwipe();
        return;
      }
      startPointRef.current = start;
      trackingTouchIdRef.current = touch.identifier;
    }

    function handleTouchMove(event: TouchEvent) {
      const start = startPointRef.current;
      const touch = trackedTouch(event.changedTouches, trackingTouchIdRef.current);
      if (!mediaQuery.matches || !start || !touch) {
        return;
      }
      if (preventHorizontalDefault && isHorizontalIntent(start, { x: touch.clientX, y: touch.clientY })) {
        event.preventDefault();
        event.stopPropagation();
      }
      if (isSwipe(start, { x: touch.clientX, y: touch.clientY }, viewport())) {
        if (preventHorizontalDefault) {
          event.preventDefault();
          event.stopPropagation();
        }
        window.parent?.postMessage(message, window.location.origin);
        resetSwipe();
      }
    }

    document.addEventListener("touchstart", handleTouchStart, { passive: true });
    document.addEventListener("touchmove", handleTouchMove, { passive: !preventHorizontalDefault });
    document.addEventListener("touchcancel", resetSwipe, { passive: true });
    document.addEventListener("touchend", resetSwipe, { passive: true });
    return () => {
      document.removeEventListener("touchstart", handleTouchStart);
      document.removeEventListener("touchmove", handleTouchMove);
      document.removeEventListener("touchcancel", resetSwipe);
      document.removeEventListener("touchend", resetSwipe);
    };
  }, [enabled, ignoreTarget, isSwipe, message, preventHorizontalDefault, requireStartZone]);
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

function isInteractiveTarget(target: TouchTarget): boolean {
  if (!(target instanceof Element)) {
    return false;
  }
  return Boolean(target.closest("a, button, input, textarea, select, [contenteditable='true'], [role='button'], [data-no-sidebar-swipe]"));
}

function isTextInputTarget(target: TouchTarget): boolean {
  if (!(target instanceof Element)) {
    return false;
  }
  return Boolean(target.closest("input, textarea, select, [contenteditable='true'], [data-no-sidebar-swipe]"));
}

function isHorizontalIntent(start: SidebarSwipePoint, current: SidebarSwipePoint): boolean {
  const deltaX = Math.abs(current.x - start.x);
  const deltaY = Math.abs(current.y - start.y);
  return deltaX > 12 && deltaX > deltaY;
}
