import { nativeCrossClientLocksAvailable, withCrossClientLock } from "./cacheBus";

const generations = new Map<string, string>();
const PREFIX = "maverick-pwa-data-publication-v1:";

/** A completed cleanup must still fence readers waiting on network or quota. */
export function publicationGeneration(backendKey: string, shared = true, maintenance = false): string | null {
  const key = JSON.stringify([backendKey, maintenance ? "maintenance" : "cleanup"]);
  if (!shared || typeof window === "undefined") return generations.get(key) ?? "initial";
  try {
    if (!nativeCrossClientLocksAvailable()) return null;
    const stored = globalThis.localStorage.getItem(PREFIX + key);
    if (stored) return stored;
    // A fresh nonce avoids ABA if the browser removed an earlier marker.
    const initial = globalThis.crypto.randomUUID();
    globalThis.localStorage.setItem(PREFIX + key, initial);
    return initial;
  } catch {
    // Without cross-document coordination, persistence is not safe.
    return null;
  }
}

export function withPublicationLock<T>(backendKey: string, operation: () => Promise<T>): Promise<T> {
  return withCrossClientLock(`data-publication:${backendKey}`, operation);
}

export function advancePublicationGeneration(backendKey: string, shared = true, maintenance = false): void {
  const key = JSON.stringify([backendKey, maintenance ? "maintenance" : "cleanup"]);
  const generation = globalThis.crypto.randomUUID();
  generations.set(key, generation);
  if (shared && typeof window !== "undefined") {
    try {
      globalThis.localStorage.setItem(PREFIX + key, generation);
    } catch (error) {
      // Never report cleanup complete if other documents cannot see its fence.
      throw new Error("Shared cache publication fence is unavailable.", { cause: error });
    }
  }
}

/** Schema maintenance fences its resource, not unrelated app publications. Broad
 * maintenance retains the database-wide epoch checked by every resource. */
export async function maintenancePublicationKey(backendKey: string, scope: {
  userId?: string; workspaceId?: string; appId?: string; resource?: string;
}): Promise<string> {
  const identity = [scope.userId, scope.workspaceId, scope.appId, scope.resource];
  if (!identity.every((part) => typeof part === 'string' && part.length > 0)) return backendKey;
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(JSON.stringify(identity)));
  const opaque = [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
  return `${backendKey}:resource:${opaque}`;
}
