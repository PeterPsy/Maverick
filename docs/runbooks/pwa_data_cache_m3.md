# PWA data cache M3 operations and integration

This runbook covers the shared structured-data cache and RAM retry primitives
implemented in `packages/pwa-cache/`. It does not enable an app read model,
authorize the M4 Storage file cache, or create a network-absence product mode.
The global data-cache feature remains off until an app completes its own M5
resource, privacy, and device gates.

## Owned browser state

- package: `@maverick/pwa-cache`;
- IndexedDB database: `maverick-pwa-data-v1`;
- current database version: `3`;
- current entry schema: `3`;
- current policy revision: `maverick.local-persistence-policy.v2`;
- metadata stores: `entries` and `metadata`;
- payload store: `payloads`;
- coordination channel: `maverick-pwa-cache-v1`;
- durable cleanup barrier: `maverick-pwa-cache-cleanup-barrier-v1` plus
  IndexedDB cleanup markers;
- retry state: RAM only.

The package does not own Cache API static assets, OPFS file bytes, app data on
the server, or unrelated origin storage. **Clear cache** may clear only the
known structured cache. It must never call a whole-origin clear operation.

## Fail-closed policy

Every resource needs a non-empty host-attested user, workspace, app, resource,
entity, policy revision, and app-owned resource schema revision. The entry key
also includes resource schema and entry schema versions. The app declares
canonical data class and provenance, but the SDK derives the only allowed local
results: `deny`, `session`, or `cache`.

Persistent writes require all applicable conditions:

1. exact policy revision v2;
2. owning app and authoritative provenance are outside the canonical agentic
   control-plane exclusion;
3. valid TTL and byte bounds;
4. successful app-owned sanitization to bounded plain JSON;
5. no credential-like key/value, signed URL, or `blob:` URL;
6. reviewed cache/privacy approvals for the canonical data class;
7. a live access lease for non-public data; and
8. a browser estimate containing both origin usage and quota with sufficient
   headroom.

An unknown quota skips the write. The package never calls
`navigator.storage.persist()`. Any policy, storage, serialization, quota, or
migration failure leaves the successful network result intact.

Default structured-data budgets are 64 MiB across the known database and
32 MiB per user/workspace/app scope. Every resource declares a smaller bound
and a maximum entry size. Cleanup removes expired entries first, then uses
least-recent access order at resource, app, and global levels.

## Resource adapter checklist

An app adapter must:

1. keep `enabled` false unless both the global and app rollout gates allow it;
2. let the top-level platform host bind the freshly authenticated principal;
3. cap a private access lease with `clampPrivateAccessLease`;
4. register one resource name once per client;
5. provide stable server revision or ETag semantics;
6. declare fresh and absolute expiry TTLs separately;
7. set `allowStale` only after the resource owner accepts rendering stale data;
8. sanitize an unknown payload into its exact cache read-model shape;
9. publish `maverick.app.data-changed` only after server-confirmed mutation;
10. dispose the client and cancel retry state on unmount; and
11. use the same ordinary loading/success/error components for cache and
    network results.

A minimal host-owned public adapter has this shape:

```ts
const host = createPwaCacheHost({
  appId: "example",
  userId: session.user.user_id,
  workspaceId: session.workspace_id,
});
const client = host.createClient({
  enabled: dataCacheEnabled && exampleCacheEnabled,
});

const records = client.resource("records", {
  allowStale: true,
  dataClass: "public",
  expiryTtlMs: 15 * 60_000,
  freshTtlMs: 60_000,
  maxEntryBytes: 128 * 1024,
  maxScopeBytes: 4 * 1024 * 1024,
  policyRevision: LOCAL_PERSISTENCE_POLICY_REVISION,
  provenance: "app_reference",
  revalidateOnRead: "stale",
  schemaRevision: "example.records.v1",
  sanitize: sanitizeRecord,
});
```

The host capability is app-bound and must not be exposed to an embedded app.
`createPwaCacheHost` rejects embedded browser frames and browser workers.
Because current Maverick app iframes still use `allow-same-origin`, this SDK
boundary does not prevent hostile frame code from opening origin IndexedDB
directly. No app read model, especially no private read model, may be enabled
until the app has an isolated origin or an opaque-origin frame with a real
parent-owned cache broker. `features.data_cache` remains `false` meanwhile.

Do not copy those TTLs or budgets into a private adapter without a resource
review. `session` data stays in the client RAM backend. `deny` data bypasses all
cache reads and writes. A transition from persistent policy to `session` or
`deny` durably removes prior persistent entries for that resource.

## Read and revalidation semantics

`readThrough(entityId, loader, signal)` behaves as follows:

- fresh hit: return the cached ordinary result; optionally revalidate when the
  resource explicitly selects `always`;
- allowed stale hit: return it immediately with one single-flight revalidation;
- disallowed stale hit: call the loader and keep the feature's normal loading;
- expired, malformed, wrong-schema, or sanitizer-rejected entry: delete it and
  treat it as a miss;
- public `get`: return a miss for stale data unless `allowStale` is explicit;
- `not_modified`: refresh only metadata and retain the payload record;
- new stable revision: atomically replace metadata and payload;
- cache failure: continue with the loader result;
- loader failure on a miss: leave transport handling to the RAM retry
  coordinator; never invent cached success.

Web Locks coordinate the revalidation critical section when available,
in-process calls share a single promise, and BroadcastChannel propagates
invalidation and cleanup across clients. Correctness does not depend on a
coordination hint being delivered.

## Authentication and cleanup lifecycle

Base Shell initializes one `CacheLifecycleController` and one
`RetryCoordinator`. After a successful `/api/session`, it transitions with the
authenticated user/workspace/app principal and a private access lease of no
more than 15 minutes. Transitioning user or workspace clears the previous
private scope before it becomes inactive.

Logout, a session response with `authenticated: false`, and every `401` or
`403` cancel RAM retries and durably clear the applicable structured-data
scope. If the current principal is unknown after a cold start, authorization
failure clears the known M3 database rather than guessing an owner. Cleanup
markers and the independent durable barrier are written before
security-sensitive deletion and resumed on the next successful bootstrap if
the browser interrupts the operation. A persistent-store deletion failure is
reported as `status: "pending"`; it never becomes RAM-fallback success. While
any cleanup is pending, the resilient backend blocks persistent reads, writes,
touches, and listings until deletion succeeds.

`maverick.app.data-changed` requires `owner_app_id` and `resource`; optional
`entity_id` narrows deletion. Base Shell forwards the invalidation to the
lifecycle controller. The event is an acceleration hint, not the only
correctness mechanism, so resource revisions and expiry remain mandatory.

## RAM retry contract

The coordinator uses:

- one flight per scoped read key;
- 1 second exponential base delay;
- 30 second exponential cap;
- jitter from 0.75 to 1.25;
- a 250 ms minimum interval for early hints;
- server `Retry-After` when longer than the computed delay;
- pause while the document or Maverick frame is hidden; and
- cancellation on abort, unmount, logout, or scope change.

Browser `online`, focus, document visibility,
`maverick.app.visibility-changed`, and a successful Maverick response are only
hints. The coordinator never reads `navigator.onLine` as authority. `401`,
`403`, `409`, `422`, and other terminal HTTP responses are not retried.
Automatic HTTP retries are limited to transport/timeouts and
`429/502/503/504`.

If a `401` or `403` triggers lifecycle cleanup while its request is still the
active retry flight, the original `MaverickHttpError` remains the terminal
result. Scope cancellation must not replace it with `RetryCancelledError`, so
Base Shell can always enter its normal authentication teardown.

Unsafe requests are attempted once unless the caller supplies all of:

- a stable `Idempotency-Key` sent to the server;
- a stable fingerprint of the exact request body/semantics; and
- `serverDeduplicates: true` backed by a real server contract.

Eligible mutations have at most three attempts in the current RAM session.
Concurrent callers with the same idempotency key and fingerprint share one
flight. Reusing the key with a different fingerprint is rejected. The request
still crosses current server authorization and no pending state survives a
reload.

The Base Shell `pinned_apps.set` path is the M3 end-to-end mutation proof. It
hashes the exact canonical request semantics with SHA-256, sends one stable key
and body across attempts, and the App Store atomically stores a bounded
workspace idempotency ledger with the state mutation. A replay returns the
original response, does not reapply or revert later state, and emits no second
`maverick.app.data-changed` event.

## Settings diagnostics

Settings → Cache displays only aggregate values:

- structured-cache bytes;
- entry count;
- total origin usage and quota when available;
- active backend (`IndexedDB` or memory fallback); and
- pending cleanup marker count.

It never lists record ids, content, users, workspaces, file names, or supposed
locally available items. **Clear cache** uses a second-click confirmation and
removes only M3 structured cache entries. It does not delete server data,
static service-worker caches, OPFS, or unrelated origin storage. Settings shows
success only for a complete durable result; a pending result is an error and
explicitly states that persistent reads remain blocked.

## Fault and recovery drills

### IndexedDB unavailable

1. Deny or inject failure into IndexedDB before client initialization.
2. Load a resource through a successful server response.
3. Confirm the normal result renders and diagnostics report `Memory fallback`.
4. Reload and confirm no durable availability is claimed.

### Interrupted migration

1. Create a v1 fixture with payload inline in `entries`.
2. Abort the v2 payload-split step or v3 resource-schema cleanup.
3. Confirm IndexedDB remains at v1 and the original record is intact.
4. Reopen without fault injection and confirm the atomic upgrade to v3
   succeeds and entries without the required resource schema are removed.

### Interrupted cleanup

1. Inject a primary clear failure before or after its IndexedDB marker write.
2. Confirm cleanup returns pending, backend mode may become memory, and the
   old primary entry is not readable through the resilient backend.
3. Reinitialize or retry after restoring the primary.
4. Confirm matching entries are removed before reads and every marker/barrier
   disappears.

### Quota pressure

1. Return an estimate above the 85% headroom threshold, or no usable estimate.
2. Load a valid server response.
3. Confirm the response renders, no cache entry is added, and no persistence
   prompt or product UI appears.

## Automated preflight

```bash
npm --prefix packages/pwa-cache run typecheck
npm --prefix packages/pwa-cache test
npm --prefix apps/base-shell test
npm --prefix apps/base-shell run test:service-worker
maverick app base-shell frontend build --json
maverick app settings frontend build --json
python3 -m unittest apps.settings.tests.test_settings_app
```

Also run the focused Core PWA/config/asset suites and the repository's default
fast validation required by `AGENTS.md`. Record aggregate counts and build ids,
not cache contents or principal identifiers.

## Rollback

Disable `MAVERICK_FEATURE_PWA_DATA_CACHE` and app-specific rollout gates. A
disabled client performs server-first reads and does not immediately destroy
the database, allowing a separate bounded cleanup release. The RAM retry
coordinator in Base Shell may remain active because it persists no request or
payload. Do not disable or clear the M2R static worker cache as a substitute for
rolling back structured data.

M3 does not waive the physical Safari/Home Screen evidence required before a
private app read model is enabled. Safari, browser tabs, private browsing, and
installed Home Screen/Dock containers remain distinct storage containers.
