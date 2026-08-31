# `@maverick/pwa-cache`

Framework-neutral browser primitives for Maverick's transparent PWA data
cache. The package owns mechanics only: mandatory scope keys, IndexedDB
migrations, TTL/LRU/accounting, quota checks, invalidation, lifecycle cleanup,
cross-client coordination, and bounded RAM retry.

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
non-idempotent mutation retries are rejected by construction.

Security-sensitive deletion never falls back to an empty RAM store and claims
success. A failed durable clear returns `status: "pending"`, leaves a durable
cleanup barrier, and blocks persistent reads and writes until the primary store
confirms deletion. Ordinary IndexedDB failures may still use the performance
fallback when no cleanup is pending.

The package never renders UI, reads `navigator.onLine`, calls
`navigator.storage.persist()`, stores pending requests, or turns cached data
into authority. See `docs/runbooks/pwa_data_cache_m3.md` for integration and
recovery details.

Conservative M3 defaults are a 64 MiB structured-cache budget, 32 MiB per app,
an app-declared resource budget, and a maximum 15-minute private access lease.
An unavailable quota estimate skips the cache write without affecting the
network result. The RAM retry coordinator pauses for document and Maverick
frame visibility, uses a 1–30 second jittered backoff, and never replays an
unsafe request without the explicit idempotency contract.

The current same-origin iframe sandbox is not a browser security boundary:
embedded app code could address origin storage directly outside this SDK. The
global data-cache rollout therefore remains disabled, and a private app cache
must not be enabled until that app runs on an isolated origin or uses a genuine
parent-owned storage broker from an opaque-origin frame.
