export type SidebarSwipePoint = {
  x: number;
  y: number;
};

const MIN_HORIZONTAL_DISTANCE = 54;
const MAX_VERTICAL_DRIFT = 46;
const HORIZONTAL_INTENT_RATIO = 1.15;

export function isHorizontalIntent(start: SidebarSwipePoint, current: SidebarSwipePoint): boolean {
  const dx = Math.abs(current.x - start.x);
  const dy = Math.abs(current.y - start.y);
  return dx > 12 && dx > dy * HORIZONTAL_INTENT_RATIO;
}

export function isSidebarCloseSwipe(start: SidebarSwipePoint, current: SidebarSwipePoint): boolean {
  const dx = current.x - start.x;
  const dy = Math.abs(current.y - start.y);
  return dx < -MIN_HORIZONTAL_DISTANCE && dy <= MAX_VERTICAL_DRIFT;
}
