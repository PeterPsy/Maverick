import type { AppRegistryItem } from "../api";

export const STATIC_DESKTOP_RAIL_APP_IDS = ["app-store"];

export type RailItemRect = {
  top: number;
  bottom: number;
};

export type DropTargetDirection = "up" | "down" | "nearest";

export function sanitizePinnedOrder(
  pinnedAppIds: string[],
  visibleAppIds: string[],
  staticAppIds: string[] = STATIC_DESKTOP_RAIL_APP_IDS,
): string[] {
  const visibleByNormalizedId = new Map(visibleAppIds.map((appId) => [normalizeAppId(appId), appId]));
  const staticIds = new Set(staticAppIds.map(normalizeAppId));
  const seen = new Set<string>();
  const sanitized: string[] = [];

  for (const rawAppId of pinnedAppIds) {
    const normalizedAppId = normalizeAppId(rawAppId);
    const visibleAppId = visibleByNormalizedId.get(normalizedAppId);
    if (!visibleAppId || staticIds.has(normalizedAppId) || seen.has(normalizedAppId)) {
      continue;
    }
    seen.add(normalizedAppId);
    sanitized.push(visibleAppId);
  }

  return sanitized;
}

export function orderedDesktopRailApps(
  registryApps: AppRegistryItem[],
  pinnedAppIds: string[],
  staticAppIds: string[] = STATIC_DESKTOP_RAIL_APP_IDS,
): AppRegistryItem[] {
  const visibleApps = registryApps.filter((app) => app.app_id !== "base-shell" && Boolean(app.frontend_mount));
  const visibleAppsById = new Map(visibleApps.map((app) => [app.app_id, app]));
  const orderedPinnedApps = sanitizePinnedOrder(
    pinnedAppIds,
    visibleApps.map((app) => app.app_id),
    staticAppIds,
  )
    .map((appId) => visibleAppsById.get(appId))
    .filter((app): app is AppRegistryItem => Boolean(app));
  const staticApps = staticAppIds
    .map((appId) => visibleApps.find((app) => normalizeAppId(app.app_id) === normalizeAppId(appId)))
    .filter((app): app is AppRegistryItem => Boolean(app));

  return [...orderedPinnedApps, ...staticApps];
}

export function reorderByTargetIndex<T>(items: T[], sourceIndex: number, targetIndex: number): T[] {
  if (!items.length || sourceIndex < 0 || sourceIndex >= items.length) {
    return [...items];
  }
  const clampedTargetIndex = clamp(targetIndex, 0, items.length - 1);
  if (sourceIndex === clampedTargetIndex) {
    return [...items];
  }
  const nextItems = [...items];
  const [movedItem] = nextItems.splice(sourceIndex, 1);
  nextItems.splice(clampedTargetIndex, 0, movedItem);
  return nextItems;
}

export function dropTargetIndexFromPointerY(
  rects: RailItemRect[],
  pointerY: number,
  direction: DropTargetDirection = "nearest",
): number {
  if (!rects.length) {
    return 0;
  }
  const orderedRects = [...rects].sort((left, right) => left.top - right.top);
  for (let index = 0; index < orderedRects.length; index += 1) {
    const rect = orderedRects[index];
    if (pointerY < rect.top) {
      return index;
    }
    if (pointerY <= rect.bottom) {
      if (direction === "down") {
        return index + 1;
      }
      if (direction === "up") {
        return index;
      }
      return pointerY > (rect.top + rect.bottom) / 2 ? index + 1 : index;
    }
  }
  return rects.length;
}

function normalizeAppId(appId: string): string {
  return appId.trim().toLowerCase();
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
