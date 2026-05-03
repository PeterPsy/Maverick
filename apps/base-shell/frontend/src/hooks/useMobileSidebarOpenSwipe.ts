import { useEffect, useRef } from "react";
import {
  isHorizontalIntent,
  isSidebarOpenSwipe,
  startsInSidebarOpenSwipeZone,
  type SidebarSwipePoint,
  type SidebarSwipeViewport,
} from "../lib/sidebarSwipe";

type TrackedTouch = SidebarSwipePoint & {
  id: number;
};

export function useMobileSidebarOpenSwipe({ enabled, onOpen }: { enabled: boolean; onOpen: () => void }) {
  const onOpenRef = useRef(onOpen);
  const swipeStartRef = useRef<TrackedTouch | null>(null);

  useEffect(() => {
    onOpenRef.current = onOpen;
  }, [onOpen]);

  useEffect(() => {
    if (!enabled) {
      swipeStartRef.current = null;
      return undefined;
    }

    function viewport(): SidebarSwipeViewport {
      return {
        width: window.innerWidth,
        height: window.innerHeight,
      };
    }

    function resetSwipe() {
      swipeStartRef.current = null;
    }

    function handleTouchStart(event: TouchEvent) {
      if (event.touches.length !== 1 || isSidebarSwipeIgnoredTarget(event.target)) {
        resetSwipe();
        return;
      }
      const touch = event.touches[0];
      const start = { x: touch.clientX, y: touch.clientY };
      if (!startsInSidebarOpenSwipeZone(start, viewport())) {
        resetSwipe();
        return;
      }
      swipeStartRef.current = { ...start, id: touch.identifier };
    }

    function handleTouchMove(event: TouchEvent) {
      const start = swipeStartRef.current;
      if (!start) {
        return;
      }
      const touch = Array.from(event.changedTouches).find((item) => item.identifier === start.id);
      if (!touch) {
        return;
      }
      const current = { x: touch.clientX, y: touch.clientY };
      if (isHorizontalIntent(start, current)) {
        event.preventDefault();
        event.stopPropagation();
      }
      if (isSidebarOpenSwipe(start, current, viewport())) {
        event.preventDefault();
        event.stopPropagation();
        onOpenRef.current();
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

function isSidebarSwipeIgnoredTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) {
    return false;
  }
  return Boolean(target.closest("a, button, input, textarea, select, [contenteditable='true'], [role='button'], [data-no-sidebar-swipe]"));
}
