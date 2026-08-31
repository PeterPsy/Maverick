import type { FileCacheOpenResult } from "./fileCacheTypes";

export class MaverickFileHttpError extends Error {
  readonly retryAfterMs?: number;
  readonly status: number;

  constructor(response: Response) {
    super(`Storage file request failed with HTTP ${response.status}.`);
    this.name = "MaverickFileHttpError";
    this.status = response.status;
    this.retryAfterMs = retryAfterMilliseconds(response.headers.get("Retry-After"));
  }
}

export async function fetchFileResponse(
  fetchImpl: typeof fetch,
  url: string,
  signal: AbortSignal,
  headers?: Headers,
): Promise<Response> {
  try {
    return await fetchImpl(url, {
      credentials: "same-origin",
      headers,
      method: "GET",
      signal,
    });
  } catch (error) {
    if (isAbortError(error) || signal.aborted) throw error;
    throw transportError("Storage file transport failed.", error);
  }
}

export async function networkBlobResult(response: Response, etag: string): Promise<FileCacheOpenResult> {
  try {
    return { blob: await response.blob(), etag, source: "network" };
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw transportError("Storage file response stream failed.", error);
  }
}

export function validResumeResponse(
  response: Response,
  partial: { etag: string; writtenBytes: number },
  expectedSize: number,
): boolean {
  const etag = response.headers.get("ETag")?.trim() ?? "";
  const range = parseContentRange(response.headers.get("Content-Range"));
  return response.status === 206
    && etag === partial.etag
    && Boolean(range)
    && range?.start === partial.writtenBytes
    && range.total === expectedSize;
}

export function combinedSignal(external: AbortSignal | undefined, internal: AbortSignal): AbortSignal {
  if (!external) return internal;
  if (typeof AbortSignal.any === "function") return AbortSignal.any([external, internal]);
  const controller = new AbortController();
  const abort = (signal: AbortSignal) => controller.abort(signal.reason);
  if (external.aborted) abort(external);
  else external.addEventListener("abort", () => abort(external), { once: true });
  if (internal.aborted) abort(internal);
  else internal.addEventListener("abort", () => abort(internal), { once: true });
  return controller.signal;
}

export function typedBlob(blob: Blob, contentType: string): Blob {
  return blob.type === contentType ? blob : new Blob([blob], { type: contentType });
}

export function retryableFileStatus(status: number): boolean {
  return status === 429 || status === 502 || status === 503 || status === 504;
}

export function transportError(message: string, cause?: unknown): Error {
  const error = new Error(message, cause === undefined ? undefined : { cause });
  error.name = "MaverickTransportError";
  return error;
}

export function cacheErrorReason(error: unknown): string {
  if (isAbortError(error)) return "cancelled";
  return error instanceof Error && /digest/iu.test(error.message) ? "digest-mismatch" : "write-failed";
}

export function isAbortError(error: unknown): boolean {
  return Boolean(error) && typeof error === "object" && (error as { name?: unknown }).name === "AbortError";
}

function parseContentRange(value: string | null): { end: number; start: number; total: number } | null {
  const match = /^bytes (\d+)-(\d+)\/(\d+)$/u.exec(value?.trim() ?? "");
  if (!match) return null;
  const start = Number(match[1]);
  const end = Number(match[2]);
  const total = Number(match[3]);
  return Number.isSafeInteger(start) && Number.isSafeInteger(end) && Number.isSafeInteger(total)
    && start >= 0 && end >= start && end < total
    ? { end, start, total }
    : null;
}

function retryAfterMilliseconds(value: string | null): number | undefined {
  if (!value) return undefined;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) return Math.round(seconds * 1_000);
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? Math.max(0, timestamp - Date.now()) : undefined;
}
