export type SidebarSwipePoint = {
  x: number;
  y: number;
};

const MIN_HORIZONTAL_DISTANCE = 72;
const MAX_VERTICAL_DRIFT = 48;
const HORIZONTAL_INTENT_MIN_DISTANCE = 12;

export function isSidebarCloseSwipe(start: SidebarSwipePoint, end: SidebarSwipePoint): boolean {
  const deltaX = end.x - start.x;
  const deltaY = Math.abs(end.y - start.y);
  return deltaX <= -MIN_HORIZONTAL_DISTANCE && deltaY <= MAX_VERTICAL_DRIFT;
}

export function isHorizontalIntent(start: SidebarSwipePoint, current: SidebarSwipePoint): boolean {
  const deltaX = Math.abs(current.x - start.x);
  const deltaY = Math.abs(current.y - start.y);
  return deltaX > HORIZONTAL_INTENT_MIN_DISTANCE && deltaX > deltaY;
}
