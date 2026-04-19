import { AppRegistryItem } from "./api";

export function shellVisibleApps(apps: AppRegistryItem[]): AppRegistryItem[] {
  return apps.filter((app) => app.app_id !== "base-shell" && Boolean(app.frontend_mount));
}

export function findRegistryApp(apps: AppRegistryItem[], appId: string | null): AppRegistryItem | null {
  if (!appId) {
    return null;
  }
  return apps.find((app) => app.app_id === appId && Boolean(app.frontend_mount)) ?? null;
}

export function preferredActiveApp(apps: AppRegistryItem[], requestedAppId: string | null): AppRegistryItem | null {
  return findRegistryApp(apps, requestedAppId) ?? findRegistryApp(apps, "chat") ?? shellVisibleApps(apps)[0] ?? null;
}

export function pinnedApps(apps: AppRegistryItem[], pinnedAppIds: string[]): AppRegistryItem[] {
  const visible = shellVisibleApps(apps);
  const pinned = pinnedAppIds.map((appId) => visible.find((app) => app.app_id === appId)).filter((app): app is AppRegistryItem => Boolean(app));
  return pinned.length ? pinned : visible.slice(0, 4);
}

export function nextPinnedAppIds(pinnedAppIds: string[], appId: string): string[] {
  const normalized = appId.trim();
  if (!normalized) {
    return pinnedAppIds;
  }
  if (pinnedAppIds.includes(normalized)) {
    return pinnedAppIds.filter((item) => item !== normalized);
  }
  return [...pinnedAppIds, normalized];
}

export function appStatusTone(status: string): "success" | "warning" | "danger" | "neutral" {
  const normalized = status.toLowerCase();
  if (normalized === "enabled" || normalized === "active" || normalized === "healthy") {
    return "success";
  }
  if (normalized === "disabled" || normalized === "degraded") {
    return "warning";
  }
  if (normalized === "failed" || normalized === "unhealthy") {
    return "danger";
  }
  return "neutral";
}
