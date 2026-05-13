export type ScreenPoint = {
  clientX: number;
  clientY: number;
};

export type Viewport = {
  scale: number;
  offsetX: number;
  offsetY: number;
};

export type ViewportRect = {
  height: number;
  left: number;
  top: number;
  width: number;
};

export type WorldPoint = {
  x: number;
  y: number;
};

const MIN_GRAPH_SCALE = 0.45;
const MAX_GRAPH_SCALE = 2.2;

export function clampGraphScale(scale: number): number {
  return Math.max(MIN_GRAPH_SCALE, Math.min(MAX_GRAPH_SCALE, scale));
}

export function distanceBetweenPoints(a: ScreenPoint, b: ScreenPoint): number {
  return Math.hypot(b.clientX - a.clientX, b.clientY - a.clientY);
}

export function midpointBetweenPoints(a: ScreenPoint, b: ScreenPoint): ScreenPoint {
  return {
    clientX: (a.clientX + b.clientX) / 2,
    clientY: (a.clientY + b.clientY) / 2,
  };
}

export function panViewport(current: Viewport, deltaX: number, deltaY: number): Viewport {
  return {
    ...current,
    offsetX: current.offsetX + deltaX,
    offsetY: current.offsetY + deltaY,
  };
}

export function screenToWorld(point: ScreenPoint, rect: ViewportRect, viewport: Viewport): WorldPoint {
  return {
    x: (point.clientX - rect.left - viewport.offsetX) / viewport.scale,
    y: (point.clientY - rect.top - viewport.offsetY) / viewport.scale,
  };
}

export function viewportForWorldPointAtScreen(
  worldPoint: WorldPoint,
  point: ScreenPoint,
  rect: ViewportRect,
  scale: number,
): Viewport {
  return {
    scale,
    offsetX: point.clientX - rect.left - worldPoint.x * scale,
    offsetY: point.clientY - rect.top - worldPoint.y * scale,
  };
}

export function zoomViewportAtPoint(
  current: Viewport,
  rect: ViewportRect,
  point: ScreenPoint,
  factor: number,
): Viewport {
  const worldPoint = screenToWorld(point, rect, current);
  return viewportForWorldPointAtScreen(worldPoint, point, rect, clampGraphScale(current.scale * factor));
}

export function pinchViewport(
  startViewport: Viewport,
  startWorldMidpoint: WorldPoint,
  startDistance: number,
  rect: ViewportRect,
  currentMidpoint: ScreenPoint,
  currentDistance: number,
): Viewport {
  const distanceRatio = currentDistance / Math.max(1, startDistance);
  return viewportForWorldPointAtScreen(
    startWorldMidpoint,
    currentMidpoint,
    rect,
    clampGraphScale(startViewport.scale * distanceRatio),
  );
}
