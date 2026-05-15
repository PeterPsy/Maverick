export const STRUCTURED_WIDGET_MIN_HEIGHT_PX = 140;
export const STRUCTURED_WIDGET_MAX_HEIGHT_PX = 520;

export function boundedWidgetHeightPx(value: unknown): number | null {
  if (typeof value !== "string") {
    return null;
  }
  const match = value.trim().match(/^(\d+(?:\.\d+)?)px$/);
  if (!match) {
    return null;
  }
  const parsed = Number(match[1]);
  if (!Number.isFinite(parsed)) {
    return null;
  }
  return Math.min(STRUCTURED_WIDGET_MAX_HEIGHT_PX, Math.max(STRUCTURED_WIDGET_MIN_HEIGHT_PX, Math.ceil(parsed)));
}
