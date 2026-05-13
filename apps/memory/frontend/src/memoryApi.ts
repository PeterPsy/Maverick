import type { ViewFilter } from "./types";

const DEFAULT_APP_ID = "memory";
const DEFAULT_TIMEOUT_MS = 15000;

export type MemoryApiOptions = {
  appId?: string;
  endpoint?: string;
  fetchImpl?: typeof fetch;
  signal?: AbortSignal;
  timeoutMs?: number;
};

export class MemoryApiError extends Error {
  code: string;
  detail: string;
  status: number;
  payload: unknown;

  constructor(message: string, options: { code?: string; detail?: string; status?: number; payload?: unknown } = {}) {
    super(message);
    this.name = "MemoryApiError";
    this.code = options.code || "memory_request_failed";
    this.detail = options.detail || message;
    this.status = options.status || 0;
    this.payload = options.payload;
  }
}

export async function callMemory<T>(body: Record<string, unknown>, options: MemoryApiOptions = {}): Promise<T> {
  const timeoutMs = Math.max(1, options.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  const timeoutController = new AbortController();
  const timeoutId = globalThis.setTimeout(() => timeoutController.abort("timeout"), timeoutMs);
  const signal = combineSignals(options.signal, timeoutController.signal);
  const fetchImpl = options.fetchImpl || fetch;
  try {
    const response = await fetchImpl(options.endpoint || memoryBackendEndpoint(options.appId), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
    const payload = await parseJsonResponse(response);
    const appPayload = unwrapAppPayload(payload);
    const statusCode = appStatusCode(payload);
    if (!response.ok || statusCode >= 400) {
      throw apiErrorFromPayload(appPayload, statusCode >= 400 ? statusCode : response.status);
    }
    return appPayload as T;
  } catch (error) {
    if (error instanceof MemoryApiError) {
      throw error;
    }
    if (timeoutController.signal.aborted && timeoutController.signal.reason === "timeout") {
      throw new MemoryApiError("Memory request timed out.", { code: "request_timeout", status: 408 });
    }
    if (options.signal?.aborted || isAbortError(error)) {
      throw new MemoryApiError("Memory request was cancelled.", { code: "request_cancelled" });
    }
    throw new MemoryApiError(error instanceof Error ? error.message : "Memory request failed.", { payload: error });
  } finally {
    globalThis.clearTimeout(timeoutId);
  }
}

export function memoryBackendEndpoint(appId = currentMemoryAppId()): string {
  return `/api/apps/${encodeURIComponent(appId || DEFAULT_APP_ID)}/backend`;
}

export function currentMemoryAppId(pathname = typeof window === "undefined" ? "" : window.location.pathname): string {
  const match = /^\/api\/apps\/widgets\/([^/?#]+)/.exec(pathname) || /^\/apps\/([^/?#]+)/.exec(pathname);
  if (!match?.[1]) {
    return DEFAULT_APP_ID;
  }
  try {
    return decodeURIComponent(match[1]) || DEFAULT_APP_ID;
  } catch {
    return match[1] || DEFAULT_APP_ID;
  }
}

function combineSignals(externalSignal: AbortSignal | undefined, timeoutSignal: AbortSignal): AbortSignal {
  if (!externalSignal) {
    return timeoutSignal;
  }
  const controller = new AbortController();
  const abort = (signal: AbortSignal) => {
    if (!controller.signal.aborted) {
      controller.abort(signal.reason);
    }
  };
  if (externalSignal.aborted) {
    abort(externalSignal);
  } else {
    externalSignal.addEventListener("abort", () => abort(externalSignal), { once: true });
  }
  if (timeoutSignal.aborted) {
    abort(timeoutSignal);
  } else {
    timeoutSignal.addEventListener("abort", () => abort(timeoutSignal), { once: true });
  }
  return controller.signal;
}

async function parseJsonResponse(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    if (!response.ok) {
      return { error: "http_error", detail: response.statusText || "Memory request failed." };
    }
    return {};
  }
}

function unwrapAppPayload(payload: unknown): unknown {
  if (payload && typeof payload === "object" && "json" in payload) {
    return (payload as { json?: unknown }).json ?? {};
  }
  return payload ?? {};
}

function appStatusCode(payload: unknown): number {
  if (!payload || typeof payload !== "object") {
    return 0;
  }
  const value = (payload as { status_code?: unknown }).status_code;
  return typeof value === "number" ? value : 0;
}

function apiErrorFromPayload(payload: unknown, status: number): MemoryApiError {
  if (payload && typeof payload === "object") {
    const record = payload as { error?: unknown; detail?: unknown; message?: unknown };
    const detail = stringValue(record.detail) || stringValue(record.message) || stringValue(record.error);
    return new MemoryApiError(detail || "Memory request failed.", {
      code: stringValue(record.error) || "memory_request_failed",
      detail: detail || "",
      status,
      payload,
    });
  }
  return new MemoryApiError("Memory request failed.", { status, payload });
}

function isAbortError(error: unknown): boolean {
  return typeof DOMException !== "undefined" && error instanceof DOMException && error.name === "AbortError";
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
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
