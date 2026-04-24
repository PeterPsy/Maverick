import { AppRegistryItem } from "./api";

export type AppRouteParams = Record<string, string | boolean | null>;

export type ShellAppRoute = {
  appId: string | null;
  params: AppRouteParams;
};

const APP_ROUTE_PREFIX = "/app";
const NON_URL_APP_PARAMS = new Set(["app_page", "workspace_id", "new_chat", "new_chat_request_id"]);

export function shellVisibleApps(apps: AppRegistryItem[]): AppRegistryItem[] {
  return apps.filter((app) => app.app_id !== "base-shell" && Boolean(app.frontend_mount));
}

export function findRegistryApp(apps: AppRegistryItem[], appId: string | null): AppRegistryItem | null {
  if (!appId) {
    return null;
  }
  const normalizedAppId = appId.toLowerCase();
  return apps.find((app) => app.app_id.toLowerCase() === normalizedAppId && Boolean(app.frontend_mount)) ?? null;
}

export function preferredActiveApp(apps: AppRegistryItem[], requestedAppId: string | null): AppRegistryItem | null {
  return findRegistryApp(apps, requestedAppId) ?? findRegistryApp(apps, "chat") ?? shellVisibleApps(apps)[0] ?? null;
}

export function parseShellAppRoute(pathname: string, search = ""): ShellAppRoute {
  if (pathname !== APP_ROUTE_PREFIX && !pathname.startsWith(`${APP_ROUTE_PREFIX}/`)) {
    return { appId: null, params: {} };
  }
  const segments = pathname
    .slice(APP_ROUTE_PREFIX.length)
    .split("/")
    .filter(Boolean)
    .map(decodePathSegment);
  const [appId = null, ...pageSegments] = segments;
  const queryParams = Object.fromEntries(new URLSearchParams(search).entries());
  const appPage = pageSegments.join("/");
  return {
    appId,
    params: {
      ...queryParams,
      ...(appPage ? { app_page: appPage } : {}),
    },
  };
}

export function currentShellAppRoute(): ShellAppRoute {
  return parseShellAppRoute(window.location.pathname, window.location.search);
}

export function shellAppPath(appId: string | null, params: AppRouteParams = {}): string {
  if (!appId) {
    return "/";
  }
  const page = typeof params.app_page === "string" ? normalizeAppPage(params.app_page) : "";
  const pagePath = page
    ? `/${page
        .split("/")
        .filter(Boolean)
        .map(encodeURIComponent)
        .join("/")}`
    : "";
  const query = new URLSearchParams();
  Object.entries(params).forEach(([name, value]) => {
    if (NON_URL_APP_PARAMS.has(name) || value === null || value === undefined || value === false) {
      return;
    }
    query.set(name, String(value));
  });
  const queryString = query.toString();
  return `${APP_ROUTE_PREFIX}/${encodeURIComponent(appId)}${pagePath}${queryString ? `?${queryString}` : ""}`;
}

export function replaceShellAppRoute(appId: string | null, params: AppRouteParams = {}) {
  const nextPath = shellAppPath(appId, params);
  if (`${window.location.pathname}${window.location.search}` !== nextPath) {
    window.history.replaceState({ appId, params }, "", nextPath);
  }
}

export function pushShellAppRoute(appId: string | null, params: AppRouteParams = {}) {
  const nextPath = shellAppPath(appId, params);
  if (`${window.location.pathname}${window.location.search}` !== nextPath) {
    window.history.pushState({ appId, params }, "", nextPath);
  }
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

function normalizeAppPage(value: string): string {
  return value
    .split("/")
    .map((segment) => segment.trim())
    .filter(Boolean)
    .join("/");
}

function decodePathSegment(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment;
  }
}
