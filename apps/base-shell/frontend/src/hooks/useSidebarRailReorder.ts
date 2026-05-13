import { useEffect, useRef, useState } from "react";
import type {
  KeyboardEvent as ReactKeyboardEvent,
  MouseEvent as ReactMouseEvent,
  PointerEvent as ReactPointerEvent,
} from "react";
import { dropTargetIndexFromPointerY, reorderByTargetIndex } from "../lib/sidebarRailReorder";

const RAIL_REORDER_LONG_PRESS_MS = 350;
const RAIL_REORDER_MOVE_CANCEL_PX = 8;
const RAIL_REORDER_SCROLL_EDGE_PX = 42;
const RAIL_REORDER_MAX_SCROLL_STEP = 12;

type PendingRailReorder = {
  appId: string;
  appIds: string[];
  pointerId: number;
  sourceIndex: number;
  startX: number;
  startY: number;
  timerId: number;
};

export type ActiveRailReorder = Omit<PendingRailReorder, "timerId"> & {
  currentX: number;
  currentY: number;
  targetIndex: number;
};

export function useSidebarRailReorder({
  canReorder,
  getAppName,
  onReorderPinnedApps,
  reorderableAppIds,
}: {
  canReorder: boolean;
  getAppName: (appId: string) => string;
  onReorderPinnedApps: (appIds: string[]) => void;
  reorderableAppIds: string[];
}) {
  const railAppsContainerRef = useRef<HTMLDivElement | null>(null);
  const railItemRefs = useRef(new Map<string, HTMLDivElement>());
  const pendingRailReorderRef = useRef<PendingRailReorder | null>(null);
  const activeRailReorderRef = useRef<ActiveRailReorder | null>(null);
  const autoScrollFrameRef = useRef<number | null>(null);
  const autoScrollVelocityRef = useRef(0);
  const suppressRailClickAppIdRef = useRef<string | null>(null);
  const [activeRailReorder, setActiveRailReorderState] = useState<ActiveRailReorder | null>(null);
  const [keyboardReorderStatus, setKeyboardReorderStatus] = useState("");

  function setActiveRailReorder(nextReorder: ActiveRailReorder | null) {
    activeRailReorderRef.current = nextReorder;
    setActiveRailReorderState(nextReorder);
  }

  function clearPendingRailReorder() {
    const pendingReorder = pendingRailReorderRef.current;
    if (pendingReorder) {
      window.clearTimeout(pendingReorder.timerId);
      pendingRailReorderRef.current = null;
    }
  }

  function stopRailAutoScroll() {
    autoScrollVelocityRef.current = 0;
    if (autoScrollFrameRef.current !== null) {
      window.cancelAnimationFrame(autoScrollFrameRef.current);
      autoScrollFrameRef.current = null;
    }
  }

  function cancelRailReorder() {
    clearPendingRailReorder();
    stopRailAutoScroll();
    setActiveRailReorder(null);
  }

  function isRailReorderInProgress(): boolean {
    return Boolean(pendingRailReorderRef.current || activeRailReorderRef.current);
  }

  function setRailItemRef(appId: string, element: HTMLDivElement | null) {
    if (element) {
      railItemRefs.current.set(appId, element);
      return;
    }
    railItemRefs.current.delete(appId);
  }

  function suppressClickIfNeeded(appId: string, event?: ReactMouseEvent<HTMLButtonElement>): boolean {
    if (suppressRailClickAppIdRef.current !== appId) {
      return false;
    }
    suppressRailClickAppIdRef.current = null;
    event?.preventDefault();
    event?.stopPropagation();
    return true;
  }

  function handleRailPointerDown(appId: string, event: ReactPointerEvent<HTMLButtonElement>) {
    if (!canReorder || event.button !== 0 || event.ctrlKey || event.metaKey) {
      return;
    }
    const sourceIndex = reorderableAppIds.indexOf(appId);
    if (sourceIndex < 0) {
      return;
    }
    clearPendingRailReorder();
    const appIds = [...reorderableAppIds];
    const startX = event.clientX;
    const startY = event.clientY;
    const pointerId = event.pointerId;
    const pendingReorder: PendingRailReorder = {
      appId,
      appIds,
      pointerId,
      sourceIndex,
      startX,
      startY,
      timerId: window.setTimeout(() => {
        pendingRailReorderRef.current = null;
        suppressRailClickAppIdRef.current = appId;
        setActiveRailReorder({
          appId,
          appIds,
          currentX: startX,
          currentY: startY,
          pointerId,
          sourceIndex,
          startX,
          startY,
          targetIndex: sourceIndex,
        });
      }, RAIL_REORDER_LONG_PRESS_MS),
    };
    pendingRailReorderRef.current = pendingReorder;
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  function handleRailPointerMove(event: ReactPointerEvent<HTMLButtonElement>) {
    const pendingReorder = pendingRailReorderRef.current;
    if (pendingReorder?.pointerId === event.pointerId) {
      const distance = Math.hypot(event.clientX - pendingReorder.startX, event.clientY - pendingReorder.startY);
      if (distance > RAIL_REORDER_MOVE_CANCEL_PX) {
        clearPendingRailReorder();
      }
      return;
    }

    const currentReorder = activeRailReorderRef.current;
    if (!currentReorder || currentReorder.pointerId !== event.pointerId) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const hitTestIds = currentReorder.appIds.filter((appId) => appId !== currentReorder.appId);
    const rects = hitTestIds
      .map((appId) => railItemRefs.current.get(appId)?.getBoundingClientRect())
      .filter((rect): rect is DOMRect => Boolean(rect));
    const targetIndex = rects.length ? dropTargetIndexFromPointerY(rects, event.clientY) : currentReorder.targetIndex;
    setActiveRailReorder({
      ...currentReorder,
      currentX: event.clientX,
      currentY: event.clientY,
      targetIndex,
    });
    scheduleRailAutoScroll(event.clientY);
  }

  function handleRailPointerUp(event: ReactPointerEvent<HTMLButtonElement>) {
    const pendingReorder = pendingRailReorderRef.current;
    if (pendingReorder?.pointerId === event.pointerId) {
      clearPendingRailReorder();
      return;
    }
    const currentReorder = activeRailReorderRef.current;
    if (!currentReorder || currentReorder.pointerId !== event.pointerId) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const nextAppIds = reorderByTargetIndex(currentReorder.appIds, currentReorder.sourceIndex, currentReorder.targetIndex);
    const didMove = nextAppIds.join("\u0000") !== currentReorder.appIds.join("\u0000");
    const movedAppId = currentReorder.appId;
    suppressRailClickAppIdRef.current = movedAppId;
    cancelRailReorder();
    if (didMove) {
      onReorderPinnedApps(nextAppIds);
    }
    window.setTimeout(() => {
      if (suppressRailClickAppIdRef.current === movedAppId) {
        suppressRailClickAppIdRef.current = null;
      }
    }, 0);
  }

  function handleRailPointerCancel(event: ReactPointerEvent<HTMLButtonElement>) {
    const pendingReorder = pendingRailReorderRef.current;
    const currentReorder = activeRailReorderRef.current;
    if (pendingReorder?.pointerId === event.pointerId || currentReorder?.pointerId === event.pointerId) {
      cancelRailReorder();
    }
  }

  function handleRailKeyDown(appId: string, event: ReactKeyboardEvent<HTMLButtonElement>) {
    if (event.key === "Escape" && isRailReorderInProgress()) {
      event.preventDefault();
      cancelRailReorder();
      return;
    }
    if (!canReorder || !event.altKey) {
      return;
    }
    const direction = event.key === "ArrowUp" ? -1 : event.key === "ArrowDown" ? 1 : 0;
    if (direction === 0) {
      return;
    }
    const sourceIndex = reorderableAppIds.indexOf(appId);
    const targetIndex = sourceIndex + direction;
    if (sourceIndex < 0 || targetIndex < 0 || targetIndex >= reorderableAppIds.length) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    const nextAppIds = reorderByTargetIndex(reorderableAppIds, sourceIndex, targetIndex);
    onReorderPinnedApps(nextAppIds);
    setKeyboardReorderStatus(`${getAppName(appId)} moved to position ${targetIndex + 1} of ${nextAppIds.length}.`);
    window.requestAnimationFrame(() => {
      const button = railItemRefs.current.get(appId)?.querySelector("button");
      button?.focus();
    });
  }

  function scheduleRailAutoScroll(pointerY: number) {
    const container = railAppsContainerRef.current;
    if (!container) {
      stopRailAutoScroll();
      return;
    }
    const rect = container.getBoundingClientRect();
    if (pointerY < rect.top + RAIL_REORDER_SCROLL_EDGE_PX) {
      autoScrollVelocityRef.current = -RAIL_REORDER_MAX_SCROLL_STEP;
    } else if (pointerY > rect.bottom - RAIL_REORDER_SCROLL_EDGE_PX) {
      autoScrollVelocityRef.current = RAIL_REORDER_MAX_SCROLL_STEP;
    } else {
      autoScrollVelocityRef.current = 0;
    }
    if (autoScrollFrameRef.current === null && autoScrollVelocityRef.current !== 0) {
      autoScrollFrameRef.current = window.requestAnimationFrame(tickRailAutoScroll);
    }
  }

  function tickRailAutoScroll() {
    const container = railAppsContainerRef.current;
    const velocity = autoScrollVelocityRef.current;
    if (!container || !activeRailReorderRef.current || velocity === 0) {
      autoScrollFrameRef.current = null;
      return;
    }
    container.scrollTop += velocity;
    autoScrollFrameRef.current = window.requestAnimationFrame(tickRailAutoScroll);
  }

  useEffect(() => {
    function handleWindowKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && isRailReorderInProgress()) {
        event.preventDefault();
        cancelRailReorder();
      }
    }
    window.addEventListener("keydown", handleWindowKeyDown);
    window.addEventListener("blur", cancelRailReorder);
    return () => {
      window.removeEventListener("keydown", handleWindowKeyDown);
      window.removeEventListener("blur", cancelRailReorder);
      cancelRailReorder();
    };
  }, []);

  useEffect(() => {
    if (!canReorder) {
      cancelRailReorder();
    }
  }, [canReorder]);

  return {
    activeRailReorder,
    cancelRailReorder,
    handleRailKeyDown,
    handleRailPointerCancel,
    handleRailPointerDown,
    handleRailPointerMove,
    handleRailPointerUp,
    isRailReorderInProgress,
    keyboardReorderStatus,
    railAppsContainerRef,
    setRailItemRef,
    suppressClickIfNeeded,
  };
}
