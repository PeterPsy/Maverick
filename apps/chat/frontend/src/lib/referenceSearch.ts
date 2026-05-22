import { type AppReference, searchAppReferences, type SearchAppReferencesOptions } from "../api/client";
import { referenceKey } from "./mentions";

export const APP_REFERENCE_SEARCH_LIMIT = 16;

const FILE_REFERENCE_ENTITY_TYPES = ["file", "folder"];
const CHECKLIST_REFERENCE_ENTITY_TYPES = ["checklist"];
const REFERENCE_SEARCH_CACHE_TTL_MS = 5000;
const REFERENCE_SEARCH_CACHE_MAX_ENTRIES = 24;

type ReferenceSearchSpec = {
  options: SearchAppReferencesOptions;
};

type ReferenceSearchCacheEntry = {
  expiresAt: number;
  references: AppReference[];
};

const recentSearchCache = new Map<string, ReferenceSearchCacheEntry>();

export async function searchComposerReferences(
  query: string,
  signal: AbortSignal,
  activeAppId: string,
  workspaceId = "",
): Promise<AppReference[]> {
  const appId = activeAppId.trim();
  const workspace = workspaceId.trim();
  const trimmedQuery = query.trim();
  const cacheKey = composerSearchCacheKey(trimmedQuery, appId, workspace);
  const cached = readComposerSearchCache(cacheKey);
  if (cached) {
    return cached;
  }
  const references = await searchComposerReferencesUncached(query, signal, appId, trimmedQuery);
  if (!signal.aborted) {
    writeComposerSearchCache(cacheKey, references);
  }
  return references;
}

async function searchComposerReferencesUncached(
  query: string,
  signal: AbortSignal,
  appId: string,
  trimmedQuery: string,
): Promise<AppReference[]> {
  const targetedSearches = targetedSearchSpecs(trimmedQuery, appId);
  if (trimmedQuery && targetedSearches.length) {
    const targeted = await runReferenceSearches(query, signal, targetedSearches);
    if (targeted.length > 0) {
      return targeted;
    }
  }

  const searches = fallbackSearchSpecs(trimmedQuery, appId);
  return runReferenceSearches(query, signal, searches);
}

function targetedSearchSpecs(query: string, appId: string): ReferenceSearchSpec[] {
  const specs: ReferenceSearchSpec[] = [];
  if (appId) {
    specs.push({ options: { appIds: [appId], limit: APP_REFERENCE_SEARCH_LIMIT } });
  }
  if (isChecklistReferenceQuery(query) && appId !== "checklist") {
    specs.push({ options: { entityTypes: CHECKLIST_REFERENCE_ENTITY_TYPES, limit: APP_REFERENCE_SEARCH_LIMIT } });
  }
  if (isFileReferenceQuery(query)) {
    specs.push({ options: { entityTypes: FILE_REFERENCE_ENTITY_TYPES, limit: APP_REFERENCE_SEARCH_LIMIT } });
  }
  return specs;
}

function fallbackSearchSpecs(query: string, appId: string): ReferenceSearchSpec[] {
  if (query) {
    return [{ options: { limit: APP_REFERENCE_SEARCH_LIMIT } }];
  }
  if (appId) {
    return [{ options: { appIds: [appId], limit: APP_REFERENCE_SEARCH_LIMIT } }];
  }
  return [{ options: { entityTypes: FILE_REFERENCE_ENTITY_TYPES, limit: APP_REFERENCE_SEARCH_LIMIT } }];
}

async function runReferenceSearches(query: string, signal: AbortSignal, searches: ReferenceSearchSpec[]): Promise<AppReference[]> {
  const uniqueSearches = dedupeSearches(searches);
  if (!uniqueSearches.length) {
    return [];
  }
  const results = await Promise.allSettled(uniqueSearches.map((search) => searchAppReferences(query, signal, search.options)));
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

function dedupeSearches(searches: ReferenceSearchSpec[]): ReferenceSearchSpec[] {
  const seen = new Set<string>();
  return searches.filter((search) => {
    const key = JSON.stringify({
      appIds: [...(search.options.appIds || [])].sort(),
      entityTypes: [...(search.options.entityTypes || [])].sort(),
      limit: search.options.limit || APP_REFERENCE_SEARCH_LIMIT,
    });
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function composerSearchCacheKey(query: string, appId: string, workspaceId: string): string {
  return `${workspaceId}\n${appId}\n${query}`;
}

function readComposerSearchCache(key: string): AppReference[] | null {
  const cached = recentSearchCache.get(key);
  if (!cached) {
    return null;
  }
  if (cached.expiresAt <= Date.now()) {
    recentSearchCache.delete(key);
    return null;
  }
  return [...cached.references];
}

function writeComposerSearchCache(key: string, references: AppReference[]): void {
  recentSearchCache.set(key, {
    expiresAt: Date.now() + REFERENCE_SEARCH_CACHE_TTL_MS,
    references: [...references],
  });
  while (recentSearchCache.size > REFERENCE_SEARCH_CACHE_MAX_ENTRIES) {
    const oldestKey = recentSearchCache.keys().next().value;
    if (!oldestKey) {
      break;
    }
    recentSearchCache.delete(oldestKey);
  }
}

function isChecklistReferenceQuery(query: string): boolean {
  return queryTokens(query).some((token) => token === "checklist" || token === "checklists");
}

function isFileReferenceQuery(query: string): boolean {
  return queryTokens(query).some((token) => ["file", "files", "folder", "folders", "storage"].includes(token));
}

function queryTokens(query: string): string[] {
  return query
    .toLowerCase()
    .split(/\s+/)
    .map((token) => token.trim())
    .filter(Boolean);
}
