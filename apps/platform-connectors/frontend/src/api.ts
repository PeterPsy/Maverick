export type Source = {
  id: string;
  name: string;
  category: string;
  backend: string;
  operations: string[];
  description: string;
  home: string | null;
};
export type Connection = {
  session_id: string;
  display_name: string;
  platform: string;
  status: string;
  url?: string;
  expires_at?: number;
};
export type Evidence = {
  file_id: string;
  workspace_relative_path: string;
  deep_link: string;
};
export type Transcript = {
  status?: string;
  text?: string;
  language?: string;
  engine?: string;
  automatic?: boolean;
  segments?: { start: number; end: number; text: string }[];
};
export type Item = {
  source: string;
  url: string;
  title?: string;
  text?: string;
  content_observed?: boolean;
  observed_at?: string;
  truncated?: boolean;
  author?: string;
  images?: { url: string; alt?: string }[];
  transcript?: Transcript;
  media?: {
    frames?: { time_seconds: number; storage?: Evidence }[];
    transcription?: Transcript;
    covered_seconds?: number;
    duration_seconds?: number;
  };
};
export type Run = {
  id: string;
  source: string;
  operation: string;
  status: string;
  phase: string;
  error: string;
  created_at: string;
  parameters: Record<string, unknown>;
  result: {
    context_items?: Item[];
    items?: Item[];
    text?: string;
    coverage?: string;
    stop_reason?: string;
    file?: Evidence;
  };
};
export type CollectionSummary = {
  id: string;
  title: string;
  source: string;
  total: number;
  updated_at: string;
};
export type Collection = CollectionSummary & {
  items: Item[];
  has_more: boolean;
  next_offset: number;
  parameters: Record<string, unknown>;
};
export type State = {
  sources: Source[];
  connections: Connection[];
  runs: Run[];
  collections: CollectionSummary[];
  connections_checked_at?: string;
  media_runtime_available: boolean;
  view_state?: {
    mode: string;
    query: string;
    source: string;
    ids: string[];
    title?: string;
  };
};

export async function callBackend<T>(
  body: Record<string, unknown>,
): Promise<T> {
  const response = await fetch("/api/apps/platform-connectors/backend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok || data.error)
    throw new Error(
      data.detail || data.error || `Request failed (${response.status}).`,
    );
  return data as T;
}

export const active = (run: Run) =>
  ["pending", "running", "waiting"].includes(run.status);
export const externalUrl = (url?: string) =>
  /^https?:\/\//i.test(url || "") ? url : undefined;
export const dateLabel = (value?: string) =>
  value
    ? new Date(value).toLocaleString("en-US", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "";

export type Perform = <T>(
  body: Record<string, unknown>,
) => Promise<T | undefined>;

export function shellHref(path: string): string {
  const supplied = (
    window as Window & { __MAVERICK_PLATFORM_ORIGIN__?: string }
  ).__MAVERICK_PLATFORM_ORIGIN__;
  let origin = window.location.origin;
  try {
    const url = new URL(supplied || "");
    if (["http:", "https:"].includes(url.protocol) && url.origin === supplied)
      origin = url.origin;
  } catch {
    /* Standalone app. */
  }
  return new URL(path, origin).href;
}
