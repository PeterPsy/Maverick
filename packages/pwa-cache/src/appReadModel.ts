import { readThroughParentDataCache, type ParentDataCacheReadResult } from "./dataCacheBrokerProtocol";
import { readCacheModelJson } from "./readModelRetry";

export type AppReadModelOptions<T> = {
  signal?: AbortSignal;
  onRevalidated?: (payload: T) => void;
  onRevalidationError?: (error: unknown) => void;
};

/** App-owned display projection; the only replayable operation is the SDK's HTTP read. */
export async function readAppCacheModel<T>(
  request: { appId: string; resource: string; schemaRevision: string; parameters: Readonly<Record<string, unknown>> },
  sanitize: (value: unknown) => T | null,
  options: AppReadModelOptions<T> = {},
): Promise<ParentDataCacheReadResult<T>> {
  const parameters = JSON.parse(JSON.stringify(request.parameters)) as Record<string, unknown>;
  // Hash the full query: no user data in broker entity ids; canonical order avoids
  // duplicate entries for equivalent query objects. Scope still belongs to host.
  const bytes = new TextEncoder().encode(JSON.stringify(parameters, (_key, value: unknown) => value && typeof value === "object" && !Array.isArray(value)
    ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b))) : value));
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  const entityId = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
  const result = await readThroughParentDataCache<T>({ ...request, entityId }, async ({ knownRevision, signal }) => {
    const response = await readCacheModelJson<{ revision: string; not_modified?: boolean; payload?: unknown }>({
      appId: request.appId, resource: request.resource, parameters: { ...parameters, known_revision: knownRevision },
    }, signal);
    if (response.not_modified) {
      if (!knownRevision || response.revision !== knownRevision) throw new TypeError("Invalid conditional read-model response.");
      return { kind: "not_modified", revision: knownRevision };
    }
    const payload = sanitize(response.payload);
    if (payload === null) throw new TypeError("Invalid app display read model.");
    return { kind: "value", payload, revision: response.revision };
  }, { sanitize, signal: options.signal });
  void result.revalidation?.then((next) => {
    if (next.changed && !options.signal?.aborted) options.onRevalidated?.(next.payload);
  }).catch((error: unknown) => {
    if (!options.signal?.aborted) options.onRevalidationError?.(error);
  });
  return result;
}
