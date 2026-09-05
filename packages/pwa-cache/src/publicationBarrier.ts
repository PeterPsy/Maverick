import { nativeCrossClientLocksAvailable, withCrossClientLock } from "./cacheBus";

const generations = new Map<string, string>();
const PREFIX = "maverick-pwa-data-publication-v1:";

/** A completed cleanup must still fence readers waiting on network or quota. */
export function publicationGeneration(backendKey: string, shared = true): string | null {
  if (!shared || typeof window === "undefined") return generations.get(backendKey) ?? "initial";
  try {
    if (!nativeCrossClientLocksAvailable()) return null;
    return globalThis.localStorage.getItem(PREFIX + backendKey);
  } catch {
    // Without cross-document coordination, persistence is not safe.
    return null;
  }
}

export function withPublicationLock<T>(backendKey: string, operation: () => Promise<T>): Promise<T> {
  return withCrossClientLock(`data-publication:${backendKey}`, operation);
}

export function advancePublicationGeneration(backendKey: string, shared = true): void {
  const generation = globalThis.crypto.randomUUID();
  generations.set(backendKey, generation);
  if (shared && typeof window !== "undefined") {
    try {
      globalThis.localStorage.setItem(PREFIX + backendKey, generation);
    } catch (error) {
      // Never report cleanup complete if other documents cannot see its fence.
      throw new Error("Shared cache publication fence is unavailable.", { cause: error });
    }
  }
}
