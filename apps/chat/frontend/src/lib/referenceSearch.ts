import { type AppReference, searchAppReferences } from "../api/client";
import { referenceKey } from "./mentions";

export const APP_REFERENCE_SEARCH_LIMIT = 16;

const FILE_REFERENCE_ENTITY_TYPES = ["file", "folder"];

export async function searchComposerReferences(query: string, signal: AbortSignal, activeAppId: string): Promise<AppReference[]> {
  const appId = activeAppId.trim();
  const searches = [
    ...(appId ? [searchAppReferences(query, signal, { appIds: [appId], limit: APP_REFERENCE_SEARCH_LIMIT })] : []),
    searchAppReferences(query, signal, { entityTypes: FILE_REFERENCE_ENTITY_TYPES, limit: APP_REFERENCE_SEARCH_LIMIT }),
    searchAppReferences(query, signal, { limit: APP_REFERENCE_SEARCH_LIMIT }),
  ];
  const results = await Promise.allSettled(searches);
  const rejected = results.find((result) => result.status === "rejected");
  if (results.every((result) => result.status === "rejected")) {
    throw rejected?.reason;
  }
  const byKey = new Map<string, AppReference>();
  for (const result of results) {
    if (result.status !== "fulfilled") {
      continue;
    }
    for (const reference of result.value) {
      byKey.set(referenceKey(reference), reference);
    }
  }
  const references = [...byKey.values()].slice(0, APP_REFERENCE_SEARCH_LIMIT);
  if (references.length === 0 && rejected?.status === "rejected") {
    throw rejected.reason;
  }
  return references;
}
