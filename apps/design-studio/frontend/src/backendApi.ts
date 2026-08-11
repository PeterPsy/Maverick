export async function callDesignStudioBackend<T>(action: string, argumentsPayload: Record<string, unknown> = {}): Promise<T> {
  const response = await fetch("/api/apps/design-studio/backend", {
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
