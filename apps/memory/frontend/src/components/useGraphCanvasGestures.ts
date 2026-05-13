import { useCallback, useRef, type MutableRefObject, type PointerEvent as ReactPointerEvent } from "react";
import {
  distanceBetweenPoints,
  midpointBetweenPoints,
  panViewport,
  pinchViewport,
  screenToWorld,
  type ScreenPoint,
  type Viewport,
  type ViewportRect,
  type WorldPoint,
} from "../lib/graphViewport";

type GestureNode = {
  id: string;
  vx: number;
  vy: number;
  x: number;
  y: number;
};

type CanvasPointer = ScreenPoint & {
  pointerId: number;
};

export type GraphCanvasDragState = {
  mode: "node" | "pan";
  pointerId: number;
  id?: string;
  lastX: number;
  lastY: number;
};

type PinchState = {
  distance: number;
  viewport: Viewport;
  worldMidpoint: WorldPoint;
};

type GestureOptions<TNode extends GestureNode> = {
  clientToWorld: (clientX: number, clientY: number) => WorldPoint;
  dragRef: MutableRefObject<GraphCanvasDragState | null>;
  hoverIdRef: MutableRefObject<string | null>;
  nodeAt: (clientX: number, clientY: number) => TNode | null;
  nodeByIdRef: MutableRefObject<Map<string, TNode>>;
  onSelectNode: (id: string) => void;
  rectRef: MutableRefObject<ViewportRect>;
  requestFrame: () => void;
  setViewport: (updater: (current: Viewport) => Viewport) => void;
  updateCanvasRect: () => void;
  viewportRef: MutableRefObject<Viewport>;
};

export function useGraphCanvasGestures<TNode extends GestureNode>({
  clientToWorld,
  dragRef,
  hoverIdRef,
  nodeAt,
  nodeByIdRef,
  onSelectNode,
  rectRef,
  requestFrame,
  setViewport,
  updateCanvasRect,
  viewportRef,
}: GestureOptions<TNode>) {
  const activePointersRef = useRef<Map<number, CanvasPointer>>(new Map());
  const pinchRef = useRef<PinchState | null>(null);

  const trackedPointerPair = useCallback(() => {
    const pointers = Array.from(activePointersRef.current.values());
    return pointers.length >= 2 ? [pointers[0], pointers[1]] : null;
  }, []);

  const beginPinch = useCallback(() => {
    const pair = trackedPointerPair();
    if (!pair) {
      pinchRef.current = null;
      return;
    }
    const midpoint = midpointBetweenPoints(pair[0], pair[1]);
    pinchRef.current = {
      distance: Math.max(1, distanceBetweenPoints(pair[0], pair[1])),
      viewport: { ...viewportRef.current },
      worldMidpoint: screenToWorld(midpoint, rectRef.current, viewportRef.current),
    };
  }, [rectRef, trackedPointerPair, viewportRef]);

  const handlePinchMove = useCallback(() => {
    const pair = trackedPointerPair();
    if (!pair) return;
    if (!pinchRef.current) beginPinch();
    const pinch = pinchRef.current;
    if (!pinch) return;
    setViewport(() => pinchViewport(
      pinch.viewport,
      pinch.worldMidpoint,
      pinch.distance,
      rectRef.current,
      midpointBetweenPoints(pair[0], pair[1]),
      Math.max(1, distanceBetweenPoints(pair[0], pair[1])),
    ));
  }, [beginPinch, rectRef, setViewport, trackedPointerPair]);

  const handlePointerDown = useCallback((event: ReactPointerEvent<HTMLCanvasElement>) => {
    event.preventDefault();
    updateCanvasRect();
    capturePointer(event.currentTarget, event.pointerId);
    activePointersRef.current.set(event.pointerId, pointerFromEvent(event));
    if (activePointersRef.current.size >= 2) {
      dragRef.current = null;
      beginPinch();
      requestFrame();
      return;
    }

    pinchRef.current = null;
    const node = nodeAt(event.clientX, event.clientY);
    if (node) {
      dragRef.current = { mode: "node", id: node.id, pointerId: event.pointerId, lastX: event.clientX, lastY: event.clientY };
      onSelectNode(node.id);
    } else {
      dragRef.current = { mode: "pan", pointerId: event.pointerId, lastX: event.clientX, lastY: event.clientY };
    }
    requestFrame();
  }, [beginPinch, dragRef, nodeAt, onSelectNode, requestFrame, updateCanvasRect]);

  const handlePointerMove = useCallback((event: ReactPointerEvent<HTMLCanvasElement>) => {
    const pointerIsActive = activePointersRef.current.has(event.pointerId);
    if (pointerIsActive) activePointersRef.current.set(event.pointerId, pointerFromEvent(event));
    updateCanvasRect();

    if (activePointersRef.current.size >= 2) {
      event.preventDefault();
      handlePinchMove();
      return;
    }

    if (event.pointerType === "mouse") {
      const node = nodeAt(event.clientX, event.clientY);
      const nextHoverId = node?.id || null;
      if (hoverIdRef.current !== nextHoverId) {
        hoverIdRef.current = nextHoverId;
        requestFrame();
      }
    }

    const drag = dragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    event.preventDefault();
    if (drag.mode === "node" && drag.id) {
      const draggedNode = nodeByIdRef.current.get(drag.id);
      if (!draggedNode) return;
      const point = clientToWorld(event.clientX, event.clientY);
      draggedNode.x = point.x;
      draggedNode.y = point.y;
      draggedNode.vx = 0;
      draggedNode.vy = 0;
      requestFrame();
      return;
    }
    setViewport((current) => panViewport(current, event.clientX - drag.lastX, event.clientY - drag.lastY));
    dragRef.current = { ...drag, lastX: event.clientX, lastY: event.clientY };
  }, [clientToWorld, dragRef, handlePinchMove, hoverIdRef, nodeAt, nodeByIdRef, requestFrame, setViewport, updateCanvasRect]);

  const handlePointerEnd = useCallback((event: ReactPointerEvent<HTMLCanvasElement>) => {
    const endedDrag = dragRef.current?.pointerId === event.pointerId;
    activePointersRef.current.delete(event.pointerId);
    releasePointer(event.currentTarget, event.pointerId);

    if (activePointersRef.current.size >= 2) {
      beginPinch();
    } else if (activePointersRef.current.size === 1 && pinchRef.current) {
      const remaining = Array.from(activePointersRef.current.values())[0];
      pinchRef.current = null;
      dragRef.current = { mode: "pan", pointerId: remaining.pointerId, lastX: remaining.clientX, lastY: remaining.clientY };
    } else {
      pinchRef.current = null;
      if (endedDrag || activePointersRef.current.size === 0) {
        dragRef.current = null;
      }
    }
    requestFrame();
  }, [beginPinch, dragRef, requestFrame]);

  const handlePointerLeave = useCallback((event: ReactPointerEvent<HTMLCanvasElement>) => {
    if (event.pointerType !== "mouse" || activePointersRef.current.has(event.pointerId)) return;
    hoverIdRef.current = null;
    requestFrame();
  }, [hoverIdRef, requestFrame]);

  return {
    handlePointerCancel: handlePointerEnd,
    handlePointerDown,
    handlePointerLeave,
    handlePointerMove,
    handlePointerUp: handlePointerEnd,
  };
}

function pointerFromEvent(event: ReactPointerEvent<HTMLCanvasElement>): CanvasPointer {
  return { clientX: event.clientX, clientY: event.clientY, pointerId: event.pointerId };
}

function capturePointer(canvas: HTMLCanvasElement, pointerId: number) {
  try {
    canvas.setPointerCapture(pointerId);
  } catch {
    // Pointer capture can fail if the browser cancels the pointer before React handles it.
  }
}

function releasePointer(canvas: HTMLCanvasElement, pointerId: number) {
  try {
    if (canvas.hasPointerCapture(pointerId)) canvas.releasePointerCapture(pointerId);
  } catch {
    // The browser may already have released capture after touch cancellation.
  }
}
