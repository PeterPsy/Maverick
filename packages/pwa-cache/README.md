# `@maverick/pwa-cache`

Framework-neutral browser primitives for Maverick's transparent PWA data
cache. The package owns mechanics only: mandatory scope keys, IndexedDB
migrations, TTL/LRU/accounting, quota checks, invalidation, lifecycle cleanup,
cross-client coordination, and bounded RAM retry.

Apps continue to own their read-model schema, canonical classification,
sanitizer, stable revision, TTL, and byte budget. Persistent writes fail closed
unless policy revision `maverick.local-persistence-policy.v2` derives `cache`.
Control-plane resources, secrets, incomplete scopes, expired entries, and
non-idempotent mutation retries are rejected by construction.

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
