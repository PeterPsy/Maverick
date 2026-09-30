import type { ViewId } from "../types";
import {
  isExactMaverickParentMessage,
  readMaverickAppFrameContext,
} from "@maverick/pwa-cache";

export const DEFAULT_APP_ID = "marta-ops";

const VIEW_IDS = new Set<ViewId>([
  "today",
  "work",
  "contacts",
  "tasks",
  "ideas",
]);

export function viewFromAppPage(value: unknown): ViewId | null {
  return typeof value === "string" && VIEW_IDS.has(value as ViewId)
    ? (value as ViewId)
    : null;
}

export function mountedAppIdFromPath(
  pathname = typeof window === "undefined" ? "" : window.location.pathname,
  fallback = DEFAULT_APP_ID,
): string {
  const context = readMaverickAppFrameContext();
  if (context) return context.appId;
  const match =
    /^\/api\/apps\/widgets\/([^/?#]+)/.exec(pathname) ||
    /^\/apps\/([^/?#]+)/.exec(pathname);
  if (!match?.[1]) return fallback;
  try {
    return decodeURIComponent(match[1]) || fallback;
  } catch {
    return match[1] || fallback;
  }
}

export function postToShell(message: Record<string, unknown>) {
  const origin = (window as Window & { __MAVERICK_PLATFORM_ORIGIN__?: string })
    .__MAVERICK_PLATFORM_ORIGIN__;
  if (origin) window.parent?.postMessage(message, origin);
  else if (window.parent === window)
    window.postMessage(message, window.location.origin);
}

export function openApp(appId: string, params: Record<string, unknown>) {
  postToShell({ type: "maverick.app.open-app", app_id: appId, params });
}

export function isMaverickParentMessage(event: MessageEvent) {
  return (
    isExactMaverickParentMessage(event) &&
    Boolean(event.data) &&
    typeof event.data === "object"
  );
}
