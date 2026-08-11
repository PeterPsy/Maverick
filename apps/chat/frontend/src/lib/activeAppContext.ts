import { AppReference, getWidgetContext } from "../api/client";
import { MentionItem, referenceKey } from "./mentions";

export type ActiveAppContext = {
  app_id: string;
  description: string;
  name: string;
  params?: Record<string, string | boolean | null>;
  views: string[];
};

export async function loadWidgetActiveAppContext(): Promise<ActiveAppContext | null> {
  const token = widgetContextToken();
  if (!token) {
    return null;
  }
  try {
    const payload = await getWidgetContext(token);
    return activeAppContextFromWidgetContext(payload.context);
  } catch {
    return null;
  }
}

export function widgetContextToken(): string {
  const hash = window.location.hash.startsWith("#") ? window.location.hash.slice(1) : window.location.hash;
  return new URLSearchParams(hash).get("context") || new URLSearchParams(window.location.search).get("context") || "";
}

export async function loadDefaultSystemPrompt(activeApp: ActiveAppContext | null): Promise<string> {
  return promptWithActiveAppContext("", activeApp);
}

export function activeAppContextFromWidgetContext(context: Record<string, unknown>): ActiveAppContext | null {
  const content = context.content;
  if (!content || typeof content !== "object") {
    return null;
  }
  const payload = (content as { payload?: unknown }).payload;
  if (!payload || typeof payload !== "object") {
    return null;
  }
  const activeApp = (payload as { active_app?: unknown }).active_app;
  if (!activeApp || typeof activeApp !== "object") {
    return null;
  }
  const record = activeApp as Record<string, unknown>;
  const appId = typeof record.app_id === "string" ? record.app_id.trim() : "";
  if (!appId || appId === "chat") {
    return null;
  }
  const params = scalarParams(record.params);
  return {
    app_id: appId,
    description: typeof record.description === "string" ? record.description : "",
    name: typeof record.name === "string" && record.name.trim() ? record.name.trim() : appId,
    ...(Object.keys(params).length ? { params } : {}),
    views: Array.isArray(record.views) ? record.views.filter((item): item is string => typeof item === "string") : [],
  };
}

function scalarParams(value: unknown): Record<string, string | boolean | null> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  return Object.fromEntries(
    Object.entries(value).filter((entry): entry is [string, string | boolean | null] => {
      const item = entry[1];
      return typeof item === "string" || typeof item === "boolean" || item === null;
    }),
  );
}

export function promptWithActiveAppContext(basePrompt: string, activeApp: ActiveAppContext | null): string {
  if (!activeApp) {
    return basePrompt;
  }
  if (basePrompt.includes(`active_app_id: ${activeApp.app_id}`)) {
    return basePrompt;
  }
  const lines = [
    "Current shell context:",
    `- active_app_id: ${activeApp.app_id}`,
    `- active_app_name: ${activeApp.name}`,
  ];
  if (activeApp.description) {
    lines.push(`- active_app_description: ${activeApp.description}`);
  }
  return [basePrompt.trim(), lines.join("\n")].filter(Boolean).join("\n\n");
}

export function mergeAppReferences(references: AppReference[], activeApp: ActiveAppContext | null): AppReference[] {
  if (!activeApp || references.some((reference) => reference.app_id === activeApp.app_id)) {
    return references;
  }
  return [...references, { type: "app", app_id: activeApp.app_id, label: activeApp.name }];
}

export function referenceMentionItem(reference: AppReference): MentionItem {
  if (reference.type === "entity") {
    return {
      id: referenceKey(reference),
      label: reference.label || reference.entity_id,
      description: [reference.app_id, reference.entity_type, reference.summary].filter(Boolean).join(" · "),
      kind: "entity",
      reference,
    };
  }
  return {
    id: reference.app_id,
    label: reference.label || reference.app_id,
    description: "",
    kind: "app",
    reference,
  };
}

export function mergeSelectedReferenceMentionItems(items: MentionItem[], selectedReferences: AppReference[]): MentionItem[] {
  const byKey = new Map<string, MentionItem>();
  for (const item of items) {
    byKey.set(item.reference ? referenceKey(item.reference) : `${item.kind}:${item.id}`, item);
  }
  for (const reference of selectedReferences) {
    byKey.set(referenceKey(reference), referenceMentionItem(reference));
  }
  return [...byKey.values()];
}
