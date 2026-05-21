import { type AppReference, searchAppReferences, type SearchAppReferencesOptions } from "../api/client";
import { referenceKey } from "./mentions";

export const APP_REFERENCE_SEARCH_LIMIT = 16;

const FILE_REFERENCE_ENTITY_TYPES = ["file", "folder"];
const CHECKLIST_REFERENCE_ENTITY_TYPES = ["checklist"];

type ReferenceSearchSpec = {
  options: SearchAppReferencesOptions;
};

export async function searchComposerReferences(query: string, signal: AbortSignal, activeAppId: string): Promise<AppReference[]> {
  const appId = activeAppId.trim();
  const trimmedQuery = query.trim();
  const targetedSearches = targetedSearchSpecs(trimmedQuery, appId);
  if (trimmedQuery && targetedSearches.length) {
    const targeted = await runReferenceSearches(query, signal, targetedSearches);
    if (targeted.length > 0) {
      return targeted;
    }
  }

  const searches = [
    ...(!trimmedQuery && appId ? [{ options: { appIds: [appId], limit: APP_REFERENCE_SEARCH_LIMIT } }] : []),
    { options: { entityTypes: FILE_REFERENCE_ENTITY_TYPES, limit: APP_REFERENCE_SEARCH_LIMIT } },
    { options: { limit: APP_REFERENCE_SEARCH_LIMIT } },
  ];
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

async function runReferenceSearches(query: string, signal: AbortSignal, searches: ReferenceSearchSpec[]): Promise<AppReference[]> {
  const results = await Promise.allSettled(searches.map((search) => searchAppReferences(query, signal, search.options)));
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
