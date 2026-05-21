import { requestJson } from "./http";
import type { StructuredContent, WidgetContextPayload, WidgetRegistryPayload } from "./types";

export function listWidgets(host: string, contentKind: string): Promise<WidgetRegistryPayload> {
  const query = new URLSearchParams({ host, content_kind: contentKind });
  return requestJson<WidgetRegistryPayload>(`/api/apps/widgets?${query.toString()}`);
}

export function createWidgetContext(payload: {
  host_app_id: string;
  owner_app_id: string;
  widget_id: string;
  message_id: string;
  content: StructuredContent;
}): Promise<WidgetContextPayload> {
  return requestJson<WidgetContextPayload>("/api/apps/widgets/context", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function getWidgetContext(contextToken: string): Promise<{ context: Record<string, unknown> }> {
  return requestJson<{ context: Record<string, unknown> }>(`/api/apps/widgets/context/${encodeURIComponent(contextToken)}`);
}
