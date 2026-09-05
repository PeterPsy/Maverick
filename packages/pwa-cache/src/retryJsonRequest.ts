const RETRY_REQUEST_TIMEOUT_MS = 15_000;

type HttpErrorConstructor = new (response: Response) => Error;
type TransportErrorConstructor = new (message: string, options?: ErrorOptions) => Error;

export type RetryJsonRequest = Readonly<{
  body?: string;
  endpoint: string;
  etag?: string;
  headers: Readonly<Record<string, string>>;
  httpError: HttpErrorConstructor;
  label: string;
  method: string;
  transportError: TransportErrorConstructor;
}>;

/** Issue and decode one SDK-described request; consumers cannot supply this operation. */
export async function executeRetryJsonRequest(
  request: RetryJsonRequest,
  signal: AbortSignal,
): Promise<unknown> {
  const requestController = new AbortController();
  const relayAbort = () => requestController.abort(signal.reason);
  if (signal.aborted) {
    relayAbort();
  } else {
    signal.addEventListener("abort", relayAbort, { once: true });
  }
  let didTimeout = false;
  const timeoutId = globalThis.setTimeout(() => {
    didTimeout = true;
    requestController.abort();
  }, RETRY_REQUEST_TIMEOUT_MS);
  const cleanup = () => {
    globalThis.clearTimeout(timeoutId);
    signal.removeEventListener("abort", relayAbort);
  };
  let response: Response;
  try {
    response = await globalThis.fetch(request.endpoint, {
      ...(request.body === undefined ? {} : { body: request.body }),
      credentials: "same-origin",
      headers: request.headers,
      method: request.method,
      redirect: "error",
      signal: requestController.signal,
    });
  } catch (error) {
    cleanup();
    if (signal.aborted) throw error;
    const message = didTimeout
      ? `${request.label} request timed out after ${RETRY_REQUEST_TIMEOUT_MS} ms.`
      : `${request.label} request transport failed.`;
    throw new request.transportError(message, { cause: error });
  }
  if (response.status === 304 && request.etag) {
    cleanup();
    const etag = response.headers.get("etag") || request.etag;
    if (etag !== request.etag) throw new TypeError("Read-model validator mismatch.");
    return { not_modified: true, etag };
  }
  if (!response.ok) {
    cleanup();
    throw new request.httpError(response);
  }
  if (response.status === 204 || request.method === "HEAD") {
    cleanup();
    return null;
  }
  try {
    return await response.json() as unknown;
  } catch (error) {
    if (!signal.aborted && (didTimeout || error instanceof TypeError)) {
      throw new request.transportError(
        didTimeout
          ? `${request.label} response timed out after ${RETRY_REQUEST_TIMEOUT_MS} ms.`
          : `${request.label} response transport failed.`,
        { cause: error },
      );
    }
    throw error;
  } finally {
    cleanup();
  }
}

export function retryAfterMilliseconds(value: string | null): number | undefined {
  if (!value) return undefined;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) {
    return Math.min(seconds * 1_000, Number.MAX_SAFE_INTEGER);
  }
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp)
    ? Math.max(0, timestamp - Date.now())
    : undefined;
}
