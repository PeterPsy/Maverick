# `@maverick/pwa-cache`

Framework-neutral browser primitives for Maverick's transparent PWA data
cache. The package owns mechanics only: mandatory scope keys, IndexedDB
migrations, TTL/LRU/accounting, quota checks, invalidation, lifecycle cleanup,
cross-client coordination, OPFS file-cache publication, and bounded RAM retry.

The API mints a client only through a capability constructed in a top-level
window; Base Shell owns that capability by contract. The host binds the
complete authenticated user/workspace/app principal once, and client options
cannot replace that identity. Every resource also declares an app-owned
`schemaRevision`, and each cache hit is re-sanitized and checked against its
exact serialized size, TTL timestamps, policy revision, and resource schema
before it can render.

Apps continue to own their read-model schema, canonical classification,
sanitizer, stable revision, TTL, and byte budget. Persistent writes fail closed
unless policy revision `maverick.local-persistence-policy.v2` derives `cache`.
Control-plane resources, secrets, incomplete scopes, expired entries, and
non-idempotent mutation retries are rejected by construction. String payloads
are normalized before rejecting object URLs, credential-bearing URLs,
credential assignments, and recognizable token formats even when their object
field name is generic.

Security-sensitive deletion never falls back to an empty RAM store and claims
success. A failed durable clear returns `status: "pending"`, leaves a durable
cleanup barrier, and blocks persistent reads and writes until the primary store
confirms deletion. Ordinary IndexedDB failures may still use the performance
fallback when no cleanup is pending.

Lifecycle operations that depend on the active principal are serialized:
scope transition, logout, authorization failure, invalidation, and aggregate
clear cannot race updates to the controller's current principal. A terminating
operation queued during a delayed transition observes and clears the resulting
principal rather than capturing the preceding one.

The package never renders UI, reads `navigator.onLine`, calls
`navigator.storage.persist()`, stores pending requests, or turns cached data
into authority. See `docs/runbooks/pwa_data_cache_m3.md` for integration and
recovery details and `docs/runbooks/pwa_file_cache_m4.md` for the file-cache
broker, failure drills, and rollout boundary.

M4 adds a separate `maverick-pwa-file-v1` IndexedDB manifest and the owned
`maverick-pwa-file-cache-v1` OPFS directory. File names are opaque, writes are
streamed into a temporary path, and only a final manifest transaction publishes
a `ready` record after exact size, strong ETag, source-version, and incremental
SHA-256 verification. An interrupted same-session transfer may resume with
`Range` plus strong `If-Range`; abandoned partials, orphans, superseded versions,
and LRU victims are removed without touching server files. Missing OPFS, an
unknown quota estimate, quota pressure, or any local write error keeps the
ordinary network result authoritative.

The exported M4 frame protocol transfers a private `MessagePort`: an embedded
Storage client submits only stable file id and source version, while Base Shell
independently resolves classification, media URL, size, digest, and policy.
The port supports RAM-only cancellation and returns either an ordinary Blob or
an unavailable result that preserves the app's existing network path. It never
exposes a cache host or browser-storage handle to the frame. The isolated
document must receive Core's exact `__MAVERICK_PLATFORM_ORIGIN__`; the client
validates that it is a distinct canonical HTTP(S) origin and otherwise declines
the broker immediately instead of using a wildcard or waiting for a handshake
that cannot arrive.

M5 adds a separate parent-mediated read-model protocol for isolated app
documents. An app declares only its resource, canonical entity id, schema
revision, and optional sanitized migration seed; Base Shell binds the request
to the authenticated principal and an exact registered app/widget frame whose
recorded owner matches the requested app, owns IndexedDB, and asks the
same frame to perform conditional network reads over a private `MessagePort`.
The child revalidates every payload with its app-owned sanitizer before render,
never receives a storage capability, and falls back to the ordinary server path
when the broker or rollout is unavailable. Exact parent-origin checks, request
cancellation, auth-failure cleanup, per-resource budgets, and global/per-app
kill switches remain fail-closed. See `docs/runbooks/pwa_data_cache_m5.md` for
the pilot inventory, rollout, recovery, and verification commands.

Core exposes the authenticated isolated-document scope as the frozen,
non-configurable `__MAVERICK_APP_FRAME_CONTEXT__` value. The exported
`readMaverickAppFrameContext()` validates and returns its mounted app and
workspace ids so app-owned legacy migration code can fail closed without
treating mutable URL parameters as attestation. The value is scope evidence,
not an authorization capability.

Conservative M3 defaults are a 64 MiB structured-cache budget, 32 MiB per app,
an app-declared resource budget, and a maximum 15-minute private access lease
that fresh server authentication may renew independently of the original cache
timestamp. An unavailable quota estimate skips the cache write without
affecting the network result. The RAM retry coordinator pauses for document and
Maverick frame visibility and uses a 1–30 second jittered backoff. Application
callbacks enter only `runOpaque()` and are one-shot. Safe API reads use a
factory-issued `createSafeRequestRetryExecutor()` whose GET/HEAD/OPTIONS request
is issued by the SDK through `runRequest()`; retrying mutations use the separate
audited executor and a canonical `sha256:<64 lowercase hex>` fingerprint.

Conservative M4 file-cache defaults are 64 MiB per entry, 128 MiB per
authenticated Storage scope, and 256 MiB across the origin, all subordinate to
the existing 85% quota-headroom check. Settings diagnostics and lifecycle clear
aggregate the structured and file caches but never enumerate cached content.

Every app and widget document, including Storage, now runs on a per-app,
per-login-session origin distinct from Base Shell. This closes direct access to
shell-owned IndexedDB and OPFS while preserving the parent-owned broker. Both
global cache rollouts remain disabled until their separate resource/privacy and
physical-device release gates are complete; origin isolation alone never grants
local-persistence policy.

M6 adds a closed, redaction-safe metrics collector and the cross-origin Settings
operations protocol. The collector stores only aggregate counters, quota
gauges, and wait-duration summaries; pending salted keys remain in RAM and event
reasons are discarded. Tabs persist separate opaque, generation-qualified
writer shards and merge them on read. A shared reset generation prevents a
stale tab from resurrecting pre-clear counters. Reset cleanup rereads the
winning marker and can only prune keys captured from an older generation, so
two concurrent clears cannot delete an event committed to the winning one. The
service worker delivers each metric to one window client, avoiding broadcast
multiplication. Conditional loader failures explicitly carry the revalidation
marker; initial-load and local structured-cache failures use
`pwa_data_cache_error` instead. Base Shell
accepts the operations protocol only from the exact registered Settings frame
and wires data, file, quota, retry, and worker telemetry. An explicit clear
cancels pending retry before the durable structured/file cleanup.

Unsafe retry executors now require a versioned `auditId` bound to one exact
HTTP method, API endpoint, and backend action. Production executors and their
client/server/replay evidence are registered in
`docs/product/pwa_cache_operational_policy.v1.json`; the exact runtime allowlist
is loaded from `src/mutationRetryRegistry.v2.json` and cannot be replaced by a
consumer. `createMutationRetryExecutor()` validates and snapshots the exact JSON
semantics, derives their SHA-256 fingerprint, and owns the target, method,
headers, body, timeout, redirect policy, `fetch`, and JSON decoding for every
attempt. `RetryCoordinator.runMutation()` accepts only that nominal executor;
it has no application callback or custom classifier, so reviewed metadata
cannot be paired with a different request. `scripts/audit_pwa_cache.py` scans
production JavaScript, TypeScript, Vue, and Svelte sources across apps and
shared packages, rejects legacy/raw/computed declarations and mutation
callbacks, and requires factory source, policy, runtime registry, server
deduplication, and replay evidence to agree. The runtime also enforces the
three-attempt cap.
