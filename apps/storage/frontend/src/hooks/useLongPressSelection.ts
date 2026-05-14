import { useRef, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent } from 'react';

const DEFAULT_LONG_PRESS_MS = 520;
const DEFAULT_MOVE_TOLERANCE_PX = 10;

type LongPressState = {
  pointerId: number;
  startX: number;
  startY: number;
  timerId: number;
};

type UseLongPressSelectionOptions<T> = {
  delayMs?: number;
  disabled?: boolean;
  item: T;
  moveTolerancePx?: number;
  onLongPress: (item: T) => void;
  shouldIgnoreTarget?: (target: EventTarget | null) => boolean;
};

export function useLongPressSelection<T, E extends HTMLElement = HTMLElement>({
  delayMs = DEFAULT_LONG_PRESS_MS,
  disabled = false,
  item,
  moveTolerancePx = DEFAULT_MOVE_TOLERANCE_PX,
  onLongPress,
  shouldIgnoreTarget,
}: UseLongPressSelectionOptions<T>) {
  const longPressRef = useRef<LongPressState | null>(null);
  const suppressClickRef = useRef(false);

  function clearLongPress() {
    const current = longPressRef.current;
    if (current) {
      window.clearTimeout(current.timerId);
      longPressRef.current = null;
    }
  }

  function handlePointerDown(event: ReactPointerEvent<E>) {
    if (disabled || event.button !== 0 || shouldIgnoreTarget?.(event.target)) {
      return;
    }
    clearLongPress();
    const pointerId = event.pointerId;
    const startX = event.clientX;
    const startY = event.clientY;
    const timerId = window.setTimeout(() => {
      const current = longPressRef.current;
      if (!current || current.pointerId !== pointerId) {
        return;
      }
      longPressRef.current = null;
      suppressClickRef.current = true;
      onLongPress(item);
    }, delayMs);
    longPressRef.current = { pointerId, startX, startY, timerId };
  }

  function handlePointerMove(event: ReactPointerEvent<E>) {
    const current = longPressRef.current;
    if (!current || current.pointerId !== event.pointerId) {
      return;
    }
    const deltaX = event.clientX - current.startX;
    const deltaY = event.clientY - current.startY;
    if (Math.hypot(deltaX, deltaY) > moveTolerancePx) {
      clearLongPress();
    }
  }

  function handlePointerEnd() {
    clearLongPress();
  }

  function handleClickCapture(event: ReactMouseEvent<E>) {
    if (!suppressClickRef.current) {
      return;
    }
    suppressClickRef.current = false;
    event.preventDefault();
    event.stopPropagation();
  }

  return {
    cancelLongPress: clearLongPress,
    longPressHandlers: {
      onClickCapture: handleClickCapture,
      onPointerCancel: handlePointerEnd,
      onPointerDown: handlePointerDown,
      onPointerLeave: handlePointerEnd,
      onPointerMove: handlePointerMove,
      onPointerUp: handlePointerEnd,
    },
  };
}
