export async function callDesignStudioBackend<T>(
  action: string,
  argumentsPayload: Record<string, unknown> = {},
  appId = mountedAppId(),
): Promise<T> {
  const response = await fetch(`/api/apps/${encodeURIComponent(appId)}/backend`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ action, arguments: argumentsPayload }),
  });
  const payload = await response.json() as { detail?: string; error?: string } & T;
  if (!response.ok || payload.error) {
    throw new Error(payload.detail || payload.error || "Design Studio request failed.");
  }
  return payload;
}

export function mountedAppId(pathname = window.location.pathname): string {
  const match = /^\/apps\/([^/?#]+)/.exec(pathname);
  return match?.[1] || "design-studio";
}

export function projectCreatedAt(project: Record<string, unknown>): number {
  const value = project.createdAt ?? project.created_at ?? 0;
  if (typeof value === "number" && Number.isFinite(value)) {
    return Math.abs(value) < 100_000_000_000 ? value * 1000 : value;
  }
  if (typeof value !== "string") {
    return 0;
  }
  const numeric = Number(value);
  if (Number.isFinite(numeric) && value.trim()) {
    return Math.abs(numeric) < 100_000_000_000 ? numeric * 1000 : numeric;
  }
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

export function projectIdFromWidgetMessage(value: unknown): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return "";
  }
  const message = value as Record<string, unknown>;
  if (message.type === "maverick.app.selection-changed") {
    return scalarProjectId((message.selection as Record<string, unknown> | undefined)?.od_project_id);
  }
  if (message.type !== "maverick.widget.context-changed") {
    return "";
  }
  const context = message.context as Record<string, unknown> | undefined;
  const content = context?.content as Record<string, unknown> | undefined;
  const payload = content?.payload as Record<string, unknown> | undefined;
  const params = payload?.active_app_params as Record<string, unknown> | undefined;
  return scalarProjectId(params?.od_project_id || params?.project_id);
}

export function mobileLayoutFromWidgetMessage(value: unknown): boolean | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return undefined;
  }
  const message = value as Record<string, unknown>;
  if (message.type !== "maverick.widget.context-changed") {
    return undefined;
  }
  const context = message.context as Record<string, unknown> | undefined;
  const content = context?.content as Record<string, unknown> | undefined;
  const payload = content?.payload as Record<string, unknown> | undefined;
  return typeof payload?.is_mobile_layout === "boolean" ? payload.is_mobile_layout : undefined;
}

function scalarProjectId(value: unknown): string {
  const text = typeof value === "string" ? value.trim() : "";
  return /^[A-Za-z0-9_][A-Za-z0-9._~-]{0,127}$/.test(text) ? text : "";
}
