import { describe, expect, it, vi } from "vitest";
import {
  LOCAL_PERSISTENCE_POLICY_REVISION,
  PwaCacheClient,
  createPwaCacheHost,
  type ResourceCachePolicy,
  type StorageQuotaAdapter,
} from "../src";
import { CacheBus, MemoryCacheBackend, ResilientCacheBackend, validatedPayloadSize } from "../src/testing";

const quota: StorageQuotaAdapter = {
  canWrite: async () => true,
  estimate: async () => ({ quota: 1_000_000, supported: true, usage: 0 }),
};

function publicPolicy(overrides: Partial<ResourceCachePolicy<{ value: string }>> = {}): ResourceCachePolicy<{ value: string }> {
  return {
    allowStale: true,
    dataClass: "public",
    expiryTtlMs: 10_000,
    freshTtlMs: 1_000,
    maxEntryBytes: 1_024,
    maxScopeBytes: 8_192,
    policyRevision: LOCAL_PERSISTENCE_POLICY_REVISION,
    provenance: "app_reference",
    revalidateOnRead: "stale",
    schemaRevision: "records.v1",
    sanitize: (payload) => {
      const value = (payload as { value?: unknown })?.value;
      return typeof value === "string" ? { value } : null;
    },
    ...overrides,
  };
}

function client(options: {
  appId?: string;
  backend?: MemoryCacheBackend;
  enabled?: boolean;
  now?: () => number;
  userId?: string;
  workspaceId?: string;
} = {}): PwaCacheClient {
  return createPwaCacheHost({
    appId: options.appId ?? "docs",
    userId: options.userId ?? "user-a",
    workspaceId: options.workspaceId ?? "default",
  }).createClient({
    backend: options.backend ?? new MemoryCacheBackend(),
    enabled: options.enabled ?? true,
    now: options.now,
    quotaAdapter: quota,
  }, new CacheBus(null));
}

describe("PWA cache resource", () => {
  it("rejects clients whose scope was not attested by the top-level host", () => {
    expect(() => new PwaCacheClient({
      backend: new MemoryCacheBackend(),
      enabled: true,
      quotaAdapter: quota,
    } as never, {} as never, new CacheBus(null))).toThrow(/host-attested/i);
  });

  it("binds user, workspace, and app identity to the host capability", () => {
    const scoped = createPwaCacheHost({
      appId: "victim-app",
      userId: "victim-user",
      workspaceId: "victim-workspace",
    }).createClient({
      appId: "attacker-app",
      userId: "attacker-user",
      workspaceId: "attacker-workspace",
    } as never, new CacheBus(null));

    expect(scoped).toMatchObject({
      appId: "victim-app",
      userId: "victim-user",
      workspaceId: "victim-workspace",
    });
  });

  it("does not let an embedded app frame mint its own cache host", () => {
    vi.stubGlobal("window", { top: {} });
    try {
      expect(() => createPwaCacheHost({
        appId: "docs",
        userId: "user-a",
        workspaceId: "default",
      })).toThrow(/parent-mediated/i);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("reports client cleanup as pending instead of claiming fallback success", async () => {
    class FailingClearBackend extends MemoryCacheBackend {
      failClear = true;

      override async clear(...args: Parameters<MemoryCacheBackend["clear"]>): Promise<number> {
        if (this.failClear && args[1]?.durable) {
          throw new Error("injected durable cleanup failure");
        }
        return super.clear(...args);
      }
    }

    const primary = new FailingClearBackend();
    const scoped = createPwaCacheHost({
      appId: "docs",
      userId: "user-a",
      workspaceId: "default",
    }).createClient({ backend: new ResilientCacheBackend(primary), enabled: true }, new CacheBus(null));

    await expect(scoped.clear()).resolves.toMatchObject({
      pendingCleanupCount: expect.any(Number),
      status: "pending",
    });
    primary.failClear = false;
    await expect(scoped.clear()).resolves.toMatchObject({ pendingCleanupCount: 0, status: "complete" });
  });

  it("isolates identical entity ids across user, workspace, and app scopes", async () => {
    const backend = new MemoryCacheBackend();
    const variants = [
      client({ backend }),
      client({ backend, userId: "user-b" }),
      client({ backend, workspaceId: "other" }),
      client({ appId: "mail", backend }),
    ];
    await Promise.all(variants.map((item, index) => item.resource("records", publicPolicy()).readThrough(
      "same",
      async () => ({ kind: "value", payload: { value: `value-${index}` }, revision: `rev-${index}` }),
    )));

    const entries = await backend.list();
    expect(entries).toHaveLength(4);
    expect(new Set(entries.map((entry) => entry.key)).size).toBe(4);
  });

  it("serves a fresh cache hit without calling the loader", async () => {
    const resource = client().resource("records", publicPolicy());
    const loader = vi.fn(async () => ({ kind: "value" as const, payload: { value: "network" }, revision: "r1" }));
    await resource.readThrough("one", loader);
    const result = await resource.readThrough("one", loader);

    expect(result).toMatchObject({ freshness: "fresh", payload: { value: "network" }, source: "cache" });
    expect(loader).toHaveBeenCalledOnce();
  });

  it("returns an allowed stale value immediately and revalidates single-flight", async () => {
    let now = 1_000;
    const resource = client({ now: () => now }).resource("records", publicPolicy());
    await resource.readThrough("one", async () => ({ kind: "value", payload: { value: "old" }, revision: "r1" }));
    now = 2_500;
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const loader = vi.fn(async () => {
      await gate;
      return { kind: "value" as const, payload: { value: "new" }, revision: "r2" };
    });

    const [first, second] = await Promise.all([
      resource.readThrough("one", loader),
      resource.readThrough("one", loader),
    ]);
    expect(first.payload.value).toBe("old");
    expect(second.payload.value).toBe("old");
    release();
    await Promise.all([first.revalidation, second.revalidation]);
    expect(loader).toHaveBeenCalledOnce();
    expect((await resource.get("one"))?.payload.value).toBe("new");
  });

  it("does not expose stale data through get when the resource forbids stale rendering", async () => {
    let now = 1_000;
    const resource = client({ now: () => now }).resource("records", publicPolicy({ allowStale: false }));
    await resource.readThrough("one", async () => ({ kind: "value", payload: { value: "old" }, revision: "r1" }));
    now = 2_500;

    expect(await resource.get("one")).toBeNull();
  });

  it("revalidates cached payload shape and byte accounting before returning it", async () => {
    const backend = new MemoryCacheBackend();
    const resource = client({ backend, now: () => 1_000 }).resource("records", publicPolicy());
    await resource.readThrough("one", async () => ({ kind: "value", payload: { value: "safe" }, revision: "r1" }));
    const [metadata] = await backend.list();
    await backend.put({
      metadata: { ...metadata, sizeBytes: validatedPayloadSize({ unexpected: "<script>poison</script>" }) },
      payload: { unexpected: "<script>poison</script>" },
    });

    expect(await resource.get("one")).toBeNull();
    expect(await backend.list()).toEqual([]);
  });

  it("checks raw cached bytes before a sanitizer can discard injected fields", async () => {
    const backend = new MemoryCacheBackend();
    const resource = client({ backend, now: () => 1_000 }).resource("records", publicPolicy());
    await resource.readThrough("one", async () => ({ kind: "value", payload: { value: "safe" }, revision: "r1" }));
    const [metadata] = await backend.list();
    await backend.put({
      metadata,
      payload: { injected: "x".repeat(2_048), value: "safe" },
    });

    expect(await resource.get("one")).toBeNull();
    expect(await backend.list()).toEqual([]);
  });

  it("rejects a payload-size mismatch before rendering", async () => {
    const backend = new MemoryCacheBackend();
    const resource = client({ backend, now: () => 1_000 }).resource("records", publicPolicy());
    await resource.readThrough("one", async () => ({ kind: "value", payload: { value: "safe" }, revision: "r1" }));
    const [metadata] = await backend.list();
    await backend.put({
      metadata: { ...metadata, sizeBytes: metadata.sizeBytes + 1 },
      payload: { value: "safe" },
    });

    expect(await resource.get("one")).toBeNull();
  });

  it("rejects timestamps that exceed the resource TTL contract before rendering", async () => {
    const backend = new MemoryCacheBackend();
    const resource = client({ backend, now: () => 1_000 }).resource("records", publicPolicy());
    await resource.readThrough("one", async () => ({ kind: "value", payload: { value: "safe" }, revision: "r1" }));
    const [metadata] = await backend.list();
    await backend.put({
      metadata: { ...metadata, expiresAt: 1_000_000, staleAt: 999_000 },
      payload: { value: "safe" },
    });

    expect(await resource.get("one")).toBeNull();
  });

  it("invalidates entries from an older app-owned resource schema revision", async () => {
    const backend = new MemoryCacheBackend();
    const first = client({ backend }).resource("records", publicPolicy({ schemaRevision: "records.v1" }));
    await first.readThrough("one", async () => ({ kind: "value", payload: { value: "old-shape" }, revision: "r1" }));

    const upgraded = client({ backend }).resource("records", publicPolicy({ schemaRevision: "records.v2" }));
    expect(await upgraded.get("one")).toBeNull();
    expect(await backend.list()).toEqual([]);
  });

  it("treats expired data as a miss in every transport condition", async () => {
    let now = 1_000;
    const resource = client({ now: () => now }).resource("records", publicPolicy({ expiryTtlMs: 2_000 }));
    await resource.readThrough("one", async () => ({ kind: "value", payload: { value: "old" }, revision: "r1" }));
    now = 3_001;
    const transportError = Object.assign(new Error("no transport"), { name: "MaverickTransportError" });

    await expect(resource.readThrough("one", async () => { throw transportError; })).rejects.toBe(transportError);
    expect(await resource.get("one")).toBeNull();
  });

  it("updates metadata without rewriting a not-modified payload", async () => {
    class CountingBackend extends MemoryCacheBackend {
      puts = 0;
      touches = 0;
      override async put<T>(entry: Parameters<MemoryCacheBackend["put"]>[0]): Promise<void> {
        this.puts += 1;
        await super.put(entry as never);
      }
      override async touch(...args: Parameters<MemoryCacheBackend["touch"]>): Promise<boolean> {
        this.touches += 1;
        return super.touch(...args);
      }
    }
    let now = 1_000;
    const backend = new CountingBackend();
    const resource = client({ backend, now: () => now }).resource("records", publicPolicy());
    await resource.readThrough("one", async () => ({ kind: "value", payload: { value: "one" }, revision: "r1" }));
    now = 3_000;
    const cached = await resource.readThrough("one", async () => ({ kind: "not_modified", revision: "r1" }));
    await cached.revalidation;

    expect(backend.puts).toBe(1);
    expect(backend.touches).toBeGreaterThan(0);
    expect((await resource.get("one"))?.payload).toEqual({ value: "one" });
  });

  it("never lets quota or cache-write failure replace a valid network result", async () => {
    const deniedQuota: StorageQuotaAdapter = {
      canWrite: async () => { throw new Error("quota failed"); },
      estimate: quota.estimate,
    };
    const resource = createPwaCacheHost({
      appId: "docs",
      userId: "user-a",
      workspaceId: "default",
    }).createClient({
      backend: new MemoryCacheBackend(),
      enabled: true,
      quotaAdapter: deniedQuota,
    }, new CacheBus(null)).resource("records", publicPolicy());

    const result = await resource.readThrough("one", async () => ({ kind: "value", payload: { value: "network" }, revision: "r1" }));
    expect(result.payload.value).toBe("network");
    expect(await resource.get("one")).toBeNull();
  });

  it("keeps the server-first path when the rollout gate is disabled", async () => {
    const resource = client({ enabled: false }).resource("records", publicPolicy());
    const loader = vi.fn(async () => ({ kind: "value" as const, payload: { value: "network" }, revision: "r1" }));
    await resource.readThrough("one", loader);
    await resource.readThrough("one", loader);
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it("does not put session policy entries in the persistent backend", async () => {
    const backend = new MemoryCacheBackend();
    const resource = client({ backend }).resource("records", publicPolicy({
      cacheApproved: false,
      dataClass: "workspace_internal",
    }));
    await resource.readThrough("one", async () => ({ kind: "value", payload: { value: "session" }, revision: "r1" }));
    expect(resource.persistencePolicy).toBe("session");
    expect(await backend.list()).toHaveLength(0);
    expect((await resource.get("one"))?.payload.value).toBe("session");
  });

  it("durably removes prior persistent entries when a resource becomes session-only", async () => {
    const backend = new MemoryCacheBackend();
    const cachedClient = createPwaCacheHost({
      appId: "docs",
      userId: "user-a",
      workspaceId: "default",
    }).createClient({
      accessLease: { issuedAt: 1_000, expiresAt: 5_000 },
      backend,
      enabled: true,
      now: () => 1_000,
      quotaAdapter: quota,
    }, new CacheBus(null));
    await cachedClient.resource("records", publicPolicy({
      cacheApproved: true,
      dataClass: "workspace_internal",
    })).readThrough("one", async () => ({ kind: "value", payload: { value: "private" }, revision: "r1" }));
    expect(await backend.list()).toHaveLength(1);

    const sessionResource = client({ backend, now: () => 1_500 }).resource("records", publicPolicy({
      cacheApproved: false,
      dataClass: "workspace_internal",
    }));
    expect(await sessionResource.get("one")).toBeNull();
    expect(await backend.list()).toEqual([]);
  });

  it("requires a live access lease before persisting a private cache entry", async () => {
    const backend = new MemoryCacheBackend();
    const resource = client({ backend }).resource("records", publicPolicy({
      cacheApproved: true,
      dataClass: "workspace_internal",
    }));
    await resource.readThrough("one", async () => ({ kind: "value", payload: { value: "private" }, revision: "r1" }));
    expect(await backend.list()).toHaveLength(0);
  });

  it("invalidates persistent private data even after its access lease expires", async () => {
    let now = 1_000;
    const backend = new MemoryCacheBackend();
    const cachedClient = createPwaCacheHost({
      appId: "docs",
      userId: "user-a",
      workspaceId: "default",
    }).createClient({
      accessLease: { issuedAt: now, expiresAt: 2_000 },
      backend,
      enabled: true,
      now: () => now,
      quotaAdapter: quota,
    }, new CacheBus(null));
    const resource = cachedClient.resource("records", publicPolicy({
      cacheApproved: true,
      dataClass: "workspace_internal",
    }));
    await resource.readThrough("one", async () => ({ kind: "value", payload: { value: "private" }, revision: "r1" }));
    now = 2_001;

    expect(await resource.invalidate("one")).toBe(1);
    expect(await backend.list()).toEqual([]);
  });

  it("evicts least-recent entries to the resource byte budget", async () => {
    let now = 1_000;
    const backend = new MemoryCacheBackend();
    const resource = client({ backend, now: () => now }).resource("records", publicPolicy({
      maxEntryBytes: 32,
      maxScopeBytes: 45,
    }));
    for (const [entityId, value] of [["one", "111111"], ["two", "222222"], ["three", "333333"]] as const) {
      await resource.readThrough(entityId, async () => ({ kind: "value", payload: { value }, revision: `r-${entityId}` }));
      now += 100;
    }
    const entries = await backend.list();
    expect(entries.length).toBeLessThan(3);
    expect(entries.some((entry) => entry.entityId === "three")).toBe(true);
  });
});
