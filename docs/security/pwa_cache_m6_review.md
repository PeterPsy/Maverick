# PWA Cache M6 Security Review: XSS And Data Remanence

Status: implementation review completed 2026-09-05. This review covers the M6
cache boundary only. It does not change Maverick's experimental pre-release
posture, approve production data, or satisfy a resource-specific privacy or
physical-device release gate.

## Scope and invariants

Reviewed surfaces are the Base Shell-owned Cache API, IndexedDB and OPFS stores;
the M3/M4/M5 parent brokers; aggregate M6 metrics and Settings dashboard; RAM
retry; lifecycle cleanup; and progressive rollout projection. The server stays
authoritative. Credentials, signed/object URLs, unclassified data, Speech audio,
temporary archives, and agentic control-plane state remain denied.

## XSS analysis

- App and widget documents have per-app/per-session origins distinct from Base
  Shell. They cannot directly open shell IndexedDB, OPFS, localStorage, or the
  root worker's Cache API namespace.
- Data/file brokers accept transferred ports only from a registered frame's
  exact window, isolated origin, owner, workspace, and shell-session generation.
  The M6 operations broker additionally accepts only the Settings owner. A
  guessed request id or protocol message from another frame is insufficient.
- Settings receives aggregate numbers and fixed enum values only. It receives
  no cache key or payload. Dynamic copy continues through HTML escaping, and
  the shell caps concurrent diagnostics from the trusted Settings frame.
- Every structured cache hit revalidates schema, scope, policy revision, TTL,
  exact serialized byte count, and the current app sanitizer before render.
  Corrupt or injected payloads are deleted and become misses.
- File hits are re-hashed and matched to exact size/version/strong validator.
  Opaque OPFS paths contain no file or principal identifier.

A compromise of trusted Base Shell JavaScript is inside the authority that owns
these browser stores; browser-side encryption with a key available to that same
JavaScript is not an XSS boundary. Residual risk is limited through strict CSP,
origin isolation, data minimization, TTL/budgets, server reauthorization,
default-off private gates, and by keeping authority and secrets out of cache.
No M6 metric, cohort decision, or cached derivative may become authorization.

## Data-remanence analysis

- Logout, `401/403`, user/workspace transition, scope revision, and explicit
  clear synchronously withdraw old frames and cancel RAM work before durable
  scoped cleanup completes.
- The lifecycle queue serializes transition and cleanup. IndexedDB cleanup
  markers and OPFS epochs/tombstones block old reads/publication until deletion
  and cross-tab writer drain are confirmed. Failure returns `pending`.
- Explicit Settings clear now cancels the retry coordinator before removing
  structured/file data. It resets aggregate M6 metrics only after cleanup is
  complete, preserving incident evidence when deletion remains pending.
- Metrics make only fixed aggregate counters/gauges eligible for aggregation
  for at most seven days; expired generations are ignored and winning-reset
  cleanup prunes captured obsolete shards best-effort.
  Each tab owns an opaque generation-qualified writer shard; reads merge
  current-generation shards, and a reset marker prevents stale writers from
  republishing earlier values. Cleanup rereads the winning marker and cannot
  remove a new-generation key created by a concurrent winning reset. Worker
  metrics go to one window client rather than every tab. Pending hashed
  operation keys stay in RAM and are not serialized; only pending count and
  oldest-time aggregates cross a reload. Reasons, URLs, names, ids, payloads,
  and content are discarded
  at collection time.
- The worker stores public, manifest-verified static bytes in named namespaces.
  Its kill switch deletes only those known names. Settings clear intentionally
  does not claim to remove static assets or unrelated origin storage.

Browser deletion and eviction are best-effort platform operations rather than a
secure-erasure guarantee for physical media. For this reason sensitive classes
remain denied/default-off and user documentation describes cache as disposable,
not as durable or securely encrypted storage.

## Verification and findings

Automated tests cover exact-frame protocol rejection, multi-tab merge/reset
interleavings, single-recipient worker metrics, metric redaction, revalidation
error taxonomy, cleanup-cancels-retry, cross-scope lifecycle, corrupt payload
removal, quota denial, eviction, intermittent-network single-flight,
OPFS/IndexedDB failure, and worker namespace recovery. The operational audit
compares the canonical data-class policy, product inventory (including exact
invalidation aliases), runtime resource manifest, SDK mutation-executor
sources, and the non-overridable full-target retry registry. Runtime rejects
non-factory executors and any method/endpoint/action or JSON-action mismatch.
The executor owns the concrete `fetch`; the mutation retry API exposes no
application callback or custom classifier that could issue a different
request. Arbitrary callbacks are one-shot and cannot claim a safe method;
retryable GET/HEAD/OPTIONS reads also use a factory-issued SDK request executor.
CI runs the
complete SDK/chaos and protocol suites plus a DOM test and authenticated
isolated-frame smoke for Settings → Cache.

The subsequent M6 review reproduced two P1 regressions (late structured writes
and lost broker-read retry) plus body-disconnect, Retry-After hint, and warm
config-latency defects. The corrective implementation adds a retained
publication generation and publication/cleanup lock, SDK-owned reviewed read
transport and file executors, body-transport classification, server-deadline
fencing, and non-blocking confirmed-session config refresh. Regression tests
cover these interleavings; arbitrary broker loaders themselves are not retried.
The new structured generation marker contains only an opaque nonce, not a
principal, payload, URL, or resource id. A missing/unwritable marker or missing
Web Locks fails closed for browser persistence. This corrective verification
does not constitute physical-device evidence or privacy approval. Remaining
release conditions are explicit rather than waived: private per-resource
privacy approval, current physical Safari/Home Screen/Dock evidence, and
Maverick's wider production-readiness blockers. The implementation must be
reviewed again if a new data class, storage namespace, broker action, retrying
mutation, or persistent telemetry dimension is introduced.
