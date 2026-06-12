import { useEffect, useRef, useState } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';

const REORDER_LONG_PRESS_MS = 420;
const REORDER_MOVE_TOLERANCE_PX = 10;
const REORDER_AUTO_SCROLL_EDGE_PX = 72;
const REORDER_AUTO_SCROLL_STEP_PX = 14;

type ReorderableItem = {
  id: string;
};

export type ReorderItemProps = {
  onPointerDown: (event: ReactPointerEvent<HTMLElement>) => void;
};

export function useWorkoutBlockReorder<T extends ReorderableItem>(items: T[], onReorder: (items: T[]) => void) {
  const [draggingItemId, setDraggingItemId] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const itemElementsRef = useRef<Map<string, HTMLElement>>(new Map());
  const itemsRef = useRef(items);
  const onReorderRef = useRef(onReorder);
  const dragListenersRef = useRef<{
    move: (event: globalThis.PointerEvent) => void;
    up: (event: globalThis.PointerEvent) => void;
  } | null>(null);
  const touchMoveListenerRef = useRef<((event: TouchEvent) => void) | null>(null);
  const dragRef = useRef<{
    itemId: string;
    pointerId: number;
    pointerType: string;
    startX: number;
    startY: number;
    started: boolean;
    longPressTimer: number | null;
  } | null>(null);

  useEffect(() => {
    itemsRef.current = items;
    onReorderRef.current = onReorder;
  }, [items, onReorder]);

  useEffect(() => {
    return () => {
      removeDragListeners();
      removeTouchMoveListener();
      const drag = dragRef.current;
      if (drag?.longPressTimer) window.clearTimeout(drag.longPressTimer);
      dragRef.current = null;
      document.body.classList.remove('is-workout-block-dragging');
    };
  }, []);

  function setItemElement(itemId: string, element: HTMLElement | null) {
    if (element) {
      itemElementsRef.current.set(itemId, element);
    } else {
      itemElementsRef.current.delete(itemId);
    }
  }

  function updateItems(nextItems: T[]) {
    itemsRef.current = nextItems;
    onReorderRef.current(nextItems);
  }

  function reorderDraggedItem(itemId: string, pointerY: number) {
    const fromIndex = itemsRef.current.findIndex((item) => item.id === itemId);
    if (fromIndex < 0) return;
    const remainingItems = itemsRef.current.filter((item) => item.id !== itemId);
    let insertIndex = remainingItems.length;

    for (let index = 0; index < remainingItems.length; index += 1) {
      const element = itemElementsRef.current.get(remainingItems[index].id);
      if (!element) continue;
      const rect = element.getBoundingClientRect();
      if (pointerY < rect.top + rect.height / 2) {
        insertIndex = index;
        break;
      }
    }

    if (insertIndex === fromIndex) return;
    const draggedItem = itemsRef.current[fromIndex];
    updateItems([...remainingItems.slice(0, insertIndex), draggedItem, ...remainingItems.slice(insertIndex)]);
  }

  function startDrag(itemId: string) {
    const drag = dragRef.current;
    if (!drag || drag.itemId !== itemId || drag.started) return;
    drag.started = true;
    setDraggingItemId(itemId);
    document.body.classList.add('is-workout-block-dragging');
    addTouchMoveListener();
  }

  function removeDragListeners() {
    const listeners = dragListenersRef.current;
    if (!listeners) return;
    window.removeEventListener('pointermove', listeners.move);
    window.removeEventListener('pointerup', listeners.up);
    window.removeEventListener('pointercancel', listeners.up);
    dragListenersRef.current = null;
  }

  function addTouchMoveListener() {
    if (touchMoveListenerRef.current) return;
    const listener = (event: TouchEvent) => {
      if (dragRef.current?.started) event.preventDefault();
    };
    touchMoveListenerRef.current = listener;
    window.addEventListener('touchmove', listener, { passive: false });
  }

  function removeTouchMoveListener() {
    const listener = touchMoveListenerRef.current;
    if (!listener) return;
    window.removeEventListener('touchmove', listener);
    touchMoveListenerRef.current = null;
  }

  function finishDrag() {
    const drag = dragRef.current;
    if (drag?.longPressTimer) window.clearTimeout(drag.longPressTimer);
    dragRef.current = null;
    setDraggingItemId(null);
    document.body.classList.remove('is-workout-block-dragging');
    removeDragListeners();
    removeTouchMoveListener();
  }

  function autoScrollDuringDrag(pointerY: number) {
    const scrollContainer = listRef.current?.closest('.editor') as HTMLElement | null;
    if (!scrollContainer) return;
    const rect = scrollContainer.getBoundingClientRect();
    if (pointerY < rect.top + REORDER_AUTO_SCROLL_EDGE_PX) {
      scrollContainer.scrollBy({ top: -REORDER_AUTO_SCROLL_STEP_PX });
    } else if (pointerY > rect.bottom - REORDER_AUTO_SCROLL_EDGE_PX) {
      scrollContainer.scrollBy({ top: REORDER_AUTO_SCROLL_STEP_PX });
    }
  }

  function handleWindowPointerMove(event: globalThis.PointerEvent) {
    const drag = dragRef.current;
    if (!drag || event.pointerId !== drag.pointerId) return;
    const distance = Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY);

    if (!drag.started) {
      if (distance > REORDER_MOVE_TOLERANCE_PX) {
        finishDrag();
      }
      return;
    }

    event.preventDefault();
    autoScrollDuringDrag(event.clientY);
    reorderDraggedItem(drag.itemId, event.clientY);
  }

  function handleWindowPointerUp(event: globalThis.PointerEvent) {
    const drag = dragRef.current;
    if (!drag || event.pointerId !== drag.pointerId) return;
    finishDrag();
  }

  function handlePointerDown(itemId: string, event: ReactPointerEvent<HTMLElement>) {
    if (event.pointerType === 'mouse' && event.button !== 0) return;
    finishDrag();
    const pointerType = event.pointerType || 'mouse';
    event.currentTarget.setPointerCapture?.(event.pointerId);
    dragRef.current = {
      itemId,
      pointerId: event.pointerId,
      pointerType,
      startX: event.clientX,
      startY: event.clientY,
      started: false,
      longPressTimer: window.setTimeout(() => startDrag(itemId), REORDER_LONG_PRESS_MS)
    };
    const moveListener = (nativeEvent: globalThis.PointerEvent) => handleWindowPointerMove(nativeEvent);
    const upListener = (nativeEvent: globalThis.PointerEvent) => handleWindowPointerUp(nativeEvent);
    dragListenersRef.current = { move: moveListener, up: upListener };
    window.addEventListener('pointermove', moveListener, { passive: false });
    window.addEventListener('pointerup', upListener);
    window.addEventListener('pointercancel', upListener);
  }

  function handleItemPointerDown(itemId: string, event: ReactPointerEvent<HTMLElement>) {
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest('button, input, select, textarea, a, [data-no-reorder-drag]')) return;
    handlePointerDown(itemId, event);
  }

  function getItemProps(itemId: string): ReorderItemProps {
    return {
      onPointerDown: (event) => handleItemPointerDown(itemId, event)
    };
  }

  return {
    draggingItemId,
    listRef,
    setItemElement,
    getItemProps
  };
}

export function moveItemToIndex<T>(items: T[], fromIndex: number, toIndex: number) {
  if (fromIndex === toIndex || fromIndex < 0 || fromIndex >= items.length) return items;
  const next = [...items];
  const [item] = next.splice(fromIndex, 1);
  next.splice(Math.max(0, Math.min(toIndex, next.length)), 0, item);
  return next;
}
