export type SidebarSwipePoint = {
  x: number;
  y: number;
};

export type SidebarSwipeViewport = {
  width: number;
  height: number;
};

const LEFT_SWIPE_X_MIN = 0.04;
const LEFT_SWIPE_X_MAX = 0.55;
const SWIPE_Y_MIN = 0.2;
const SWIPE_Y_MAX = 0.8;
const MIN_HORIZONTAL_DISTANCE = 72;
const MAX_VERTICAL_DRIFT = 48;

export function startsInSidebarSwipeZone(point: SidebarSwipePoint, viewport: SidebarSwipeViewport): boolean {
  if (viewport.width <= 0 || viewport.height <= 0) {
    return false;
  }
  const minX = viewport.width * LEFT_SWIPE_X_MIN;
  const maxX = viewport.width * LEFT_SWIPE_X_MAX;
  const minY = viewport.height * SWIPE_Y_MIN;
  const maxY = viewport.height * SWIPE_Y_MAX;
  return point.x >= minX && point.x <= maxX && point.y >= minY && point.y <= maxY;
}

export function isSidebarOpenSwipe(start: SidebarSwipePoint, end: SidebarSwipePoint, viewport: SidebarSwipeViewport): boolean {
  if (!startsInSidebarSwipeZone(start, viewport)) {
    return false;
  }
  const deltaX = end.x - start.x;
  const deltaY = Math.abs(end.y - start.y);
  return deltaX >= MIN_HORIZONTAL_DISTANCE && deltaY <= MAX_VERTICAL_DRIFT;
}

export function isSidebarCloseSwipe(start: SidebarSwipePoint, end: SidebarSwipePoint, _viewport?: SidebarSwipeViewport): boolean {
  const deltaX = end.x - start.x;
  const deltaY = Math.abs(end.y - start.y);
  return deltaX <= -MIN_HORIZONTAL_DISTANCE && deltaY <= MAX_VERTICAL_DRIFT;
}
