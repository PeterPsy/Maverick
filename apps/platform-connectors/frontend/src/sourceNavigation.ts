export const ownerAppId = "platform-connectors";
export const sidebarWidgetId = "connectors-sidebar";
export type ConnectorsTab = "explore" | "collections" | "history";

export function sourceFromParams(params: unknown): string {
  if (!params || typeof params !== "object" || Array.isArray(params)) return "";
  const source = (params as Record<string, unknown>).source;
  return typeof source === "string" && /^[a-z_]{1,32}$/.test(source) ? source : "";
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export function tabFromParams(params: unknown): ConnectorsTab | null {
  const tab = record(params).tab;
  return tab === "explore" || tab === "collections" || tab === "history" ? tab : null;
}

export function sidebarContext(message: Record<string, unknown>) {
  if (message.type !== "maverick.widget.context-changed" ||
      message.owner_app_id !== ownerAppId || message.widget_id !== sidebarWidgetId)
    return null;
  const content = record(record(message.context).content);
  if (content.kind !== "shell.sidebar.primary" || typeof content.workspace_id !== "string" || !content.workspace_id)
    return null;
  const payload = record(content.payload);
  if (payload.active_app_id !== ownerAppId) return null;
  return {
    workspaceId: content.workspace_id,
    source: sourceFromParams(payload.active_app_params) || "instagram",
    isMobile: payload.is_mobile_layout === true,
  };
}

export function sourceSelection(message: Record<string, unknown>): string {
  if (message.type !== "maverick.app.selection-changed" || message.owner_app_id !== ownerAppId)
    return "";
  return sourceFromParams(message.selection);
}

export function postToShell(message: Record<string, unknown>) {
  if (window.parent === window) return;
  const supplied = (window as Window & { __MAVERICK_PLATFORM_ORIGIN__?: string }).__MAVERICK_PLATFORM_ORIGIN__;
  window.parent.postMessage(message, supplied || window.location.origin);
}
