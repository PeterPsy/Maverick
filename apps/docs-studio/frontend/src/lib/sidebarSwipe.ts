export type SwipePoint = {
  x: number;
  y: number;
};

export function shouldCloseSidebarFromSwipe(start: SwipePoint | null, end: SwipePoint | null): boolean {
  if (!start || !end) {
    return false;
  }
  const deltaX = end.x - start.x;
  const deltaY = end.y - start.y;
  return deltaX < -64 && Math.abs(deltaY) < 42;
}
