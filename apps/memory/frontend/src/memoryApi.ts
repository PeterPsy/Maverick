import type { ViewFilter } from "./types";

export async function callMemory<T>(body: Record<string, unknown>): Promise<T> {
  const response = await fetch("/api/apps/memory/backend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  return (payload.json || payload) as T;
}

export function normalizeViewFilter(raw?: Partial<ViewFilter>): ViewFilter {
  return {
    mode: raw?.mode === "custom" ? "custom" : "search",
    title: raw?.title || "",
    query: raw?.query || "",
    refs: Array.isArray(raw?.refs) ? raw.refs : [],
    updated_at: raw?.updated_at || "",
  };
}
