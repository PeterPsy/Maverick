import { type AppReference, searchAppReferences, type SearchAppReferencesOptions } from "../api/client";
import { referenceKey } from "./mentions";

export const APP_REFERENCE_SEARCH_LIMIT = 16;

const FILE_REFERENCE_ENTITY_TYPES = ["file", "folder"];
const CHECKLIST_REFERENCE_ENTITY_TYPES = ["checklist"];
const STORAGE_APP_ID = "storage";
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
      if (shouldFillFromGlobalFallback(trimmedQuery, appId, targeted)) {
        const fallback = await runReferenceSearches(query, signal, fallbackSearchSpecs(trimmedQuery, appId));
        return mergeReferenceResults(query, targeted, fallback);
      }
      return targeted;
    }
  }

  const searches = fallbackSearchSpecs(trimmedQuery, appId);
  return runReferenceSearches(query, signal, searches);
}

function shouldFillFromGlobalFallback(query: string, appId: string, targeted: AppReference[]): boolean {
  return (
    !appId
    && targeted.length < APP_REFERENCE_SEARCH_LIMIT
    && !isChecklistReferenceQuery(query)
    && !isFileReferenceQuery(query)
  );
}

function targetedSearchSpecs(query: string, appId: string): ReferenceSearchSpec[] {
  const specs: ReferenceSearchSpec[] = [];
  if (appId) {
    specs.push({ options: { appIds: [appId], limit: APP_REFERENCE_SEARCH_LIMIT } });
  }
  if (appId !== STORAGE_APP_ID) {
    specs.push({
      options: {
        appIds: [STORAGE_APP_ID],
        entityTypes: FILE_REFERENCE_ENTITY_TYPES,
        limit: APP_REFERENCE_SEARCH_LIMIT,
      },
    });
  }
  if (isChecklistReferenceQuery(query) && appId !== "checklist") {
    specs.push({ options: { entityTypes: CHECKLIST_REFERENCE_ENTITY_TYPES, limit: APP_REFERENCE_SEARCH_LIMIT } });
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
  const byKey = new Map<string, { reference: AppReference; firstIndex: number }>();
  for (const [resultIndex, result] of results.entries()) {
    if (result.status !== "fulfilled") {
      continue;
    }
    for (const [itemIndex, reference] of result.value.entries()) {
      const key = referenceKey(reference);
      if (!byKey.has(key)) {
        byKey.set(key, {
          reference,
          firstIndex: resultIndex * APP_REFERENCE_SEARCH_LIMIT + itemIndex,
        });
      }
    }
  }
  const references = orderReferenceResults([...byKey.values()], query).slice(0, APP_REFERENCE_SEARCH_LIMIT);
  if (references.length === 0 && rejected?.status === "rejected") {
    throw rejected.reason;
  }
  return references;
}

function orderReferenceResults(
  entries: Array<{ reference: AppReference; firstIndex: number }>,
  query: string,
): AppReference[] {
  const normalizedQuery = normalizeReferenceSearchText(query);
  if (!normalizedQuery) {
    return entries.sort((first, second) => first.firstIndex - second.firstIndex).map((entry) => entry.reference);
  }
  return entries
    .map((entry) => ({
      ...entry,
      score: referenceSearchScore(entry.reference, normalizedQuery),
    }))
    .sort((first, second) => second.score - first.score || first.firstIndex - second.firstIndex)
    .map((entry) => entry.reference);
}

function mergeReferenceResults(query: string, ...lists: AppReference[][]): AppReference[] {
  const byKey = new Map<string, { reference: AppReference; firstIndex: number }>();
  let index = 0;
  for (const list of lists) {
    for (const reference of list) {
      const key = referenceKey(reference);
      if (!byKey.has(key)) {
        byKey.set(key, { reference, firstIndex: index });
      }
      index += 1;
    }
  }
  return orderReferenceResults([...byKey.values()], query).slice(0, APP_REFERENCE_SEARCH_LIMIT);
}

function referenceSearchScore(reference: AppReference, normalizedQuery: string): number {
  const tokens = normalizedQuery.split(/\s+/).filter(Boolean);
  const label = normalizeReferenceSearchText(reference.label || "");
  const identity = normalizeReferenceSearchText(referenceIdentityText(reference));
  const summary = normalizeReferenceSearchText(reference.type === "entity" ? reference.summary || "" : "");
  let score = 0;
  score += textMatchScore(label, normalizedQuery, 1000, 700, 450);
  score += textMatchScore(identity, normalizedQuery, 180, 120, 80);
  score += textMatchScore(summary, normalizedQuery, 120, 80, 50);
  for (const token of tokens) {
    if (label.includes(token)) {
      score += 50;
    }
    if (identity.includes(token)) {
      score += 10;
    }
    if (summary.includes(token)) {
      score += 15;
    }
  }
  if (reference.type === "entity" && reference.app_id === STORAGE_APP_ID && FILE_REFERENCE_ENTITY_TYPES.includes(reference.entity_type)) {
    score += 8;
  }
  return score;
}

function textMatchScore(text: string, query: string, exact: number, prefix: number, contains: number): number {
  if (!text || !query) {
    return 0;
  }
  if (text === query) {
    return exact;
  }
  if (text.startsWith(query)) {
    return prefix;
  }
  if (text.includes(query)) {
    return contains;
  }
  return 0;
}

function referenceIdentityText(reference: AppReference): string {
  if (reference.type === "entity") {
    return [reference.app_id, reference.entity_type, reference.entity_id, reference.deep_link].filter(Boolean).join(" ");
  }
  return reference.app_id;
}

function normalizeReferenceSearchText(value: string): string {
  return value.toLowerCase().replace(/[._/-]+/g, " ").replace(/\s+/g, " ").trim();
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
  return (
    queryTokens(query).some((token) => ["file", "files", "folder", "folders", "storage", "uploaded", "generated"].includes(token))
    || /\.[a-z0-9]{1,12}(?:\s|$)/i.test(query)
    || /(?:^|\/)storage\/(?:uploaded|generated)(?:\/|$)/i.test(query)
  );
}

function queryTokens(query: string): string[] {
  return query
    .toLowerCase()
    .split(/\s+/)
    .map((token) => token.trim())
    .filter(Boolean);
}
