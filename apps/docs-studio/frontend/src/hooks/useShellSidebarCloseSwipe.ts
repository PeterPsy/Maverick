import { useEffect } from 'react';
import { shouldCloseSidebarFromSwipe, type SwipePoint } from '../lib/sidebarSwipe';

export function useShellSidebarCloseSwipe(enabled: boolean) {
  useEffect(() => {
    if (!enabled || typeof window === 'undefined') {
      return undefined;
    }
    let startPoint: SwipePoint | null = null;
    let currentPoint: SwipePoint | null = null;

    function pointFromTouch(event: TouchEvent): SwipePoint | null {
      const touch = event.touches[0] || event.changedTouches[0];
      if (!touch) {
        return null;
      }
      return { x: touch.clientX, y: touch.clientY };
    }

    function handleTouchStart(event: TouchEvent) {
      startPoint = pointFromTouch(event);
      currentPoint = startPoint;
    }

    function handleTouchMove(event: TouchEvent) {
      currentPoint = pointFromTouch(event);
    }

    function reset() {
      startPoint = null;
      currentPoint = null;
    }

    function handleTouchEnd(event: TouchEvent) {
      currentPoint = pointFromTouch(event) || currentPoint;
      if (shouldCloseSidebarFromSwipe(startPoint, currentPoint)) {
        window.parent?.postMessage({ type: 'maverick.shell.sidebar.close' }, window.location.origin);
      }
      reset();
    }

    window.addEventListener('touchstart', handleTouchStart, { passive: true });
    window.addEventListener('touchmove', handleTouchMove, { passive: true });
    window.addEventListener('touchend', handleTouchEnd, { passive: true });
    window.addEventListener('touchcancel', reset, { passive: true });
    return () => {
      window.removeEventListener('touchstart', handleTouchStart);
      window.removeEventListener('touchmove', handleTouchMove);
      window.removeEventListener('touchend', handleTouchEnd);
      window.removeEventListener('touchcancel', reset);
    };
  }, [enabled]);
}
