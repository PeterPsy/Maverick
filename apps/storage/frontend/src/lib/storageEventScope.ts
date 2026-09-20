import { IncrementalSha256 } from '@maverick/pwa-cache';

export function storageScopeKey(role: string, parent: string | null): string {
  return new IncrementalSha256().update(new TextEncoder().encode(JSON.stringify([role, parent]))).hexDigest();
}

/** Unknown or provider-wide events always reload; proven unrelated scopes do not. */
export function storageEventAffectsView(keys: unknown, view: {
  role: string; folder: string; query: string; custom: boolean; drive: boolean;
}): boolean {
  if (view.drive || view.role === 'all' || !Array.isArray(keys) || !keys.length || keys.length > 128
      || keys.some(key => typeof key !== 'string' || !/^[0-9a-f]{64}$/.test(key))) return true;
  const folder = view.folder.replace(/^\/+|\/+$/g, '');
  return keys.includes(storageScopeKey(view.role, view.custom || view.query.trim() ? null : folder));
}
