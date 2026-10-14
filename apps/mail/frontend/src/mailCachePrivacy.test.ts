import { describe, expect, it } from 'vitest';
import { CacheLifecycleController, LOCAL_PERSISTENCE_POLICY_REVISION, PWA_CACHE_ENTRY_SCHEMA_VERSION, type CacheEntryMetadata } from '@loopino/pwa-cache';
import { CacheBus, MemoryCacheBackend, cacheEntryKey } from '../../../../packages/pwa-cache/src/testing';

function metadata(userId: string, workspaceId = 'default'): CacheEntryMetadata {
  const scope = { userId, workspaceId, appId: 'mail', resource: 'thread-headers-snippets-and-bodies', policyRevision: LOCAL_PERSISTENCE_POLICY_REVISION, schemaRevision: 'mail.thread-headers-snippets-and-bodies.v1' };
  return {
    ...scope, key: cacheEntryKey(scope, 'thread'), entityId: 'thread', schemaVersion: PWA_CACHE_ENTRY_SCHEMA_VERSION,
    dataClass: 'personal_data', provenance: 'app_reference', policy: 'cache', revision: 'one',
    sizeBytes: 100, cachedAt: 1_000, lastAccessedAt: 1_000, staleAt: 20_000, expiresAt: 20_000,
  };
}

describe('Mail display-cache privacy', () => {
  it('isolates user and workspace keys and purges Mail on logout', async () => {
    const backend = new MemoryCacheBackend();
    const entry = metadata('user-a');
    await backend.put({ metadata: entry, payload: { subject: 'Private test mail' } });
    expect(await backend.get(metadata('user-b').key)).toBeNull();
    expect(await backend.get(metadata('user-a', 'other').key)).toBeNull();
    const controller = new CacheLifecycleController({ backend, bus: new CacheBus(null), now: () => 1_000 });
    await controller.transition({ appId: 'base-shell', userId: 'user-a', workspaceId: 'default' });
    await controller.endSession();
    expect(await backend.list({ appId: 'mail' })).toEqual([]);
  });

  it('clears previous-user Mail during an identity change', async () => {
    const backend = new MemoryCacheBackend();
    await backend.put({ metadata: metadata('user-a'), payload: { subject: 'Private test mail' } });
    const controller = new CacheLifecycleController({ backend, bus: new CacheBus(null), now: () => 1_000 });
    await controller.transition({ appId: 'base-shell', userId: 'user-a', workspaceId: 'default' });
    await controller.transition({ appId: 'base-shell', userId: 'user-b', workspaceId: 'default' });
    expect(await backend.list({ userId: 'user-a', appId: 'mail' })).toEqual([]);
  });
});
