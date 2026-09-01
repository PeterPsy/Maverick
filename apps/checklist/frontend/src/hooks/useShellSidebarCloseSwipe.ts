import { useEffect, useRef } from 'react';
import { isHorizontalIntent, isSidebarCloseSwipe, type SidebarSwipePoint } from '../lib/sidebarSwipe';

const CLOSE_SIDEBAR_MESSAGE = { type: 'maverick.shell.sidebar.close' };

export function useShellSidebarCloseSwipe(enabled: boolean) {
  const startPointRef = useRef<SidebarSwipePoint | null>(null);
  const trackingTouchIdRef = useRef<number | null>(null);

  useEffect(() => {
    if (!enabled || typeof window === 'undefined') {
      return undefined;
    }

    function resetSwipe() {
      startPointRef.current = null;
      trackingTouchIdRef.current = null;
    }

    function handleTouchStart(event: TouchEvent) {
      if (event.touches.length !== 1 || isTextInputTarget(event.target)) {
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
      if (!start || !touch) {
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

    document.addEventListener('touchstart', handleTouchStart, { passive: true });
    document.addEventListener('touchmove', handleTouchMove, { passive: false });
    document.addEventListener('touchcancel', resetSwipe, { passive: true });
    document.addEventListener('touchend', resetSwipe, { passive: true });
    return () => {
      document.removeEventListener('touchstart', handleTouchStart);
      document.removeEventListener('touchmove', handleTouchMove);
      document.removeEventListener('touchcancel', resetSwipe);
      document.removeEventListener('touchend', resetSwipe);
    };
  }, [enabled]);
}

function trackedTouch(touches: TouchList, identifier: number | null): Touch | null {
  if (identifier === null) {
    return null;
  }
  return Array.from(touches).find((touch) => touch.identifier === identifier) || null;
}

function isTextInputTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) {
    return false;
  }
  return Boolean(target.closest('input, textarea, select, [contenteditable="true"], [data-no-sidebar-swipe]'));
}

