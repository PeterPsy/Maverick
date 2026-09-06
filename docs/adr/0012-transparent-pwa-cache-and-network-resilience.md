# ADR-0012: Transparent PWA Cache And Network Resilience

## Status

Accepted on 2026-08-31 as the corrective M2R gate for the PWA cache rollout.

This ADR supersedes ADR-0011 wherever that record defines a product mode for
network absence, a global connectivity UI, an alternative shell, explicit
local-content availability, `offline_opt_in`, or a persistent mutation
outbox. ADR-0011 remains an immutable historical account of the M0-M2
implementation that preceded this correction.

## Context

Maverick is an online application whose browser caches are transparent
performance and resilience mechanisms. The M2 implementation correctly added
verified static artifacts, atomic service-worker installation, bounded cache
ownership, recovery, and a kill switch. It also made transport reachability a
product state: the shell replaced its normal tree, unmounted app frames,
blocked actions, exposed a global indicator and local-content dialog, and
served a dedicated fallback document.

That product model is rejected. A browser hint or failed request cannot prove
what every mounted feature can do, and a cache must not create a second
application experience. Some functions can render a valid cached derivative;
others require a fresh server response. Each function therefore keeps its
ordinary `loading`, `success`, or terminal `error` semantics while transport
recovery remains internal.

## Decision

### 1. There is one product UI

The Base Shell and mounted apps render the same normal component tree whether
the network is available, slow, intermittent, or absent. Maverick has no
network-absence mode, route, page, banner, badge, dialog, icon replacement, or
global Online/Offline copy.

A valid cached result may render through the same component used for an
equivalent network result. A cache miss or expired result remains in that
function's normal loading state during a transient transport failure. HTTP
authentication, authorization, validation, and conflict responses are
terminal outcomes and continue through their ordinary flows.

### 2. Cache and authority remain separate

Cache API, IndexedDB, OPFS, HTTP caches, and RAM contain rebuildable
derivatives only. They never grant workspace access, capabilities, provider or
model admission, tool authority, egress, confirmation, revocation state, or
mutation success. `401` and `403` take precedence over cached private data and
initiate the applicable cleanup.

The platform host owns generic HTTP semantics and verified frontend-artifact
metadata. Base Shell owns the root service worker and static-cache lifecycle.
Each app owns the schema, sanitization, revision, TTL, byte budget, and
invalidation of its read models. Storage owns stable file identity and its
automatic bounded file cache. Shared browser primitives must remain
app-agnostic and scope-isolated.

### 3. Local persistence policy v2 has three values

The policy revision is `maverick.local-persistence-policy.v2`. Its only values
are `deny`, `session`, and `cache`:

| Canonical `data_class` | Default | Maximum after a reviewed resource rule |
|---|---|---|
| `public` | `cache` | `cache` |
| `workspace_internal_fake` | `session` | `cache` |
| `workspace_internal` | `session` | `cache` |
| `personal_data` | `session` | `cache` after privacy approval |
| `regulated_or_customer_data` | `deny` | `cache` only on a reviewed allowlist |
| `credential_or_secret` | `deny` | `deny` |
| `host_operational_metadata` | `deny` | `deny` |
| `unclassified` or unknown | `deny` | `deny` |

`deny` wins. A missing classification, policy revision, approval, stable
resource revision, or bounded scope fails closed. A resource that would need a
new per-device consent product remains denied until a separate product and
security decision exists; this rollout does not manufacture an opt-in UI.

### 4. Transport recovery is internal and bounded

UI consumers receive only `loading`, `success`, or terminal `error`.
Transport failures and timeouts may move an idempotent read into an internal
waiting/retry substate while it continues to render as loading. Retry is
single-flight per request key, cancellable, rate-limited, and uses exponential
backoff with jitter. Browser `online`, focus, and visibility events are hints
that may advance a retry; only a Maverick response confirms useful transport.

`401`, `403`, `409`, and `422` are not transport failures. Mutation retry
requires a stable idempotency key and server deduplication. No pending request,
payload, or mutation queue introduced by this decision survives reload,
logout, user/workspace change, scope revision, or unmount.

### 5. The service worker caches the standard shell

The verified frontend manifest uses the explicit
`maverick.frontend-assets.v2` schema and a neutral `navigation_fallback` that
names the normal HTML entrypoint. The worker intercepts only `/`, `/app`, and
`/app/*` navigations for network-first loading with a bounded timeout and falls
back to that verified entrypoint. Other navigations retain normal browser and
network behavior.

There is no dedicated fallback document or synthetic product response. API,
SSE, WebSocket, backend, sidecar, range, non-GET, worker, and cross-origin
requests remain bypassed. Atomic install, digest and size verification,
candidate rollback, recovery, waiting-worker coordination, namespace
ownership, and the server-side kill switch are preserved.

App and widget documents use distinct browser origins, so they are not clients
of the shell-origin worker. Core makes initial HTML asset references absolute
on the public platform origin. Vite-generated JavaScript resolves lazy preload,
worker, and imported-media URLs relative to the already public module URL via
`import.meta.url`; it never uses the isolated document as their base. Safe
module, media, font, PDF, and WebAssembly build outputs are public cross-origin
artifacts, while immutable caching remains conditional on exact manifest
verification. All such responses retain CORS/CORP and compression. The former
`maverick-app-static-v2` Cache API path is retained only as an exact legacy name
for bounded deletion; it is not part of normal app loading.

### 6. Rollout configuration is cache-centric

The browser projection uses `maverick.pwa-config.v2`. It retains the service
worker and data-cache gates, exposes the automatic Storage file-cache gate,
and contains no mutation-outbox or network-absence capability. Invalid flag
values fail closed. Disabling the worker removes only known Maverick static
cache namespaces and never clears the whole origin, IndexedDB, or OPFS.

### 7. Evidence measures behavior, not a product mode

Automated and physical-device evidence records cache reuse, transferred bytes,
normal shell continuity, pending duration, recovery, lifecycle integrity, and
scope cleanup without content or sensitive identifiers. Safari, an installed
Home Screen/Dock app, and other browser containers are assessed separately.

The M2R release gate requires the standard shell to remain visually unchanged,
mounted frames not to be removed because of transport hints, cache misses to
remain in normal loading, and recovery to occur without connectivity copy. A
first visit with neither network nor a verified cache may show the browser's
ordinary navigation failure.

## Consequences

- The technically sound HTTP and static-cache work from M1-M2 is retained.
- Product components and contracts introduced solely for network-absence UX
  are deleted rather than hidden behind compatibility branches.
- Expired entries are always misses; network absence never extends their life.
- File caching is automatic, bounded, LRU-managed, and best-effort rather than
  pinned or promised to remain on the device.
- No persistent outbox is part of the PWA cache roadmap.
- Private cache rollout remains blocked on scoped cleanup, policy revision,
  app-owned resource contracts, privacy review, and physical-device evidence.

## M3 implementation profile

The shared `@maverick/pwa-cache` mechanics are implemented by M3 while the
data-cache rollout gate remains disabled by default. The browser database is
`maverick-pwa-data-v1`, currently at database and entry schema version 3. Entry
identity includes host-attested user, workspace and app identity plus resource,
entity, policy revision, app-owned resource schema revision, and entry schema
version. Metadata and payload records are committed atomically; schema upgrades
are transactional. Every hit re-runs the current sanitizer and validates exact
byte accounting and TTL timestamps before render.

Security-sensitive clear operations use an independent durable barrier plus
IndexedDB cleanup markers. They do not use the ordinary RAM performance
fallback: incomplete deletion is reported as pending and blocks persistent
cache access until the primary store confirms removal.

The conservative platform defaults are:

- policy revision `maverick.local-persistence-policy.v2`;
- a private access lease of at most 15 minutes after fresh server
  authentication; a later authoritative authentication may renew an existing
  entry without coupling the new lease to the entry's original cache time;
- 64 MiB global structured-cache budget, 32 MiB per app, and an explicit
  smaller resource budget;
- no persistent write when `navigator.storage.estimate()` cannot provide both
  usage and quota, and no call to `navigator.storage.persist()`;
- read retry starting at 1 second, capped at 30 seconds before server
  `Retry-After`, with 0.75–1.25 jitter and a 250 ms minimum hint interval;
- automatic HTTP retry only for transport failures, timeouts, `429`, `502`,
  `503`, and `504`; and
- at most three same-session mutation attempts, only when a stable
  `Idempotency-Key`, canonical `sha256:<64 lowercase hex>` request fingerprint,
  and declared server deduplication are all present.

M3 does not opt any app read model into persistent storage and does not add the
M4 OPFS file cache. Those rollouts remain separate reviewed gates.

The M3 SDK lets only the top-level host bind and mint an app-scoped client; an
embedded app cannot provide a replacement principal through client options.
The browser boundary is independently enforced: every app and widget document
is bootstrapped on an authenticated per-app, per-session isolated origin, while
direct non-shell app documents on the platform origin are rejected. Keeping
`allow-same-origin` therefore grants access only to that app's isolated origin,
not to shell-owned IndexedDB or OPFS. The default-off data gate remains
mandatory until app-owned resource, privacy, and physical-device rollout gates
are complete.

This is a fail-closed invariant rather than a deployment toggle. Maverick does
not provide a same-platform-origin launch fallback for executable app or widget
documents. Hosted app-frame and sidecar hosts require either the exact
`*.sidecars.<installation-domain>` TLS wildcard or the managed-exact HTTP-01
lifecycle. Managed-exact issuance is restricted to Core-derived names and must
complete before the corresponding one-shot ticket is returned; a manually
frozen certificate containing only currently observed opaque hosts cannot
satisfy the boundary.

## M4 implementation profile

M4 adds the automatic file-cache engine without changing the product UI or
enabling its rollout gate. `maverick-pwa-file-v1` is the separate IndexedDB
manifest at database version 1 and record schema 2;
`maverick-pwa-file-cache-v1` is the only owned OPFS directory. A ready identity
contains the host-attested user/workspace/storage
scope, stable file id, source version, current policy/schema revision, exact
size, strong ETag, SHA-256 digest, and private access-lease bound. OPFS names
are random UUID-derived, opaque, and never contain a principal or file id.

Base Shell owns a private-`MessageChannel` broker. The Storage frame supplies
only file id and source version; Base Shell re-resolves a server-owned
descriptor and media URL, enforces platform-origin identity binding and the
default 64 MiB entry bound, then applies local-persistence policy v2. Raw bytes
fail closed as `unclassified` unless a host-attested platform/workspace admin
has durably approved that exact current file/version. Such an approval projects
only that representation as `workspace_internal`; revocation or version change
returns it to network-only. A missing, malformed, stale, denied, oversized, or
unapproved descriptor produces an ordinary network fallback rather than a
cache error. `MAVERICK_FEATURE_PWA_STORAGE_FILE_CACHE` remains off by default;
the global flag is not a classification or privacy override.

Writes stream best-effort to a random opaque unpublished OPFS path. A shared
origin-budget lock reserves the full declared size, a file-identity generation
makes the newest started version authoritative, and publication rechecks the
cleanup epoch, identity generation, digest, size, and budgets before and after
committing `ready`. Same-session partial state alone may request `Range` with a
strong `If-Range`. Changed or weak validators, corruption, interrupted
publication, missing OPFS/quota information, and write failure cannot replace
or damage the network result.

A candidate hit re-hashes its physical OPFS bytes and performs a conditional
authoritative media `HEAD`; local files are live-hashed and Drive refreshes its
provider revision. Only an exact strong ETag and size confirm reuse, except for
the bounded same-session trusted-descriptor fallback already allowed during a
transient transport failure. Cleanup advances a durable epoch, cancels and
drains matching cross-tab writers, and keeps its tombstone until deletion and
writer acknowledgement complete. Budgets are 128 MiB per Storage scope and
256 MiB origin-wide with least-recent eviction. Lifecycle cleanup and Settings
aggregate clear include both the manifest and owned bytes, never server files
or unrelated origin storage. Storage migrates eligible raw
image/PDF/text/markdown previews through the broker while retaining direct
video/audio streaming and the same ordinary loading/viewer components.

## M5 implementation profile

M5 adds the first app-owned structured read models without exposing the M3
host capability to an embedded app. Base Shell owns a parent broker bound to
the authenticated user, active workspace, and access lease. It accepts a
private `MessageChannel` only from a registered app or widget frame window at
its exact isolated origin. Each registration records the real owner app id,
active workspace, and an opaque shell-session generation. The broker requires
that complete frame scope to match its current principal, the owner to match
the request app id, and a fixed
app/resource/schema declaration whose global and per-app rollout gates are
both enabled. The child performs the
app-specific conditional HTTP/backend read and applies its exact sanitizer;
the parent owns IndexedDB, policy derivation, TTL, quota, and lifecycle. A
missing or disabled broker produces one ordinary server read.

The first pilot declarations are Website Studio site snapshots, Storage file
catalog metadata, the App Store catalog, and Fitness Coach's sanitized
bootstrap and bounded thumbnail frames. Their complete policy, validator,
budget, migration, and invalidation contracts are recorded in
`docs/product/pwa_cache_resource_inventory.v2.json` and operated through
`docs/runbooks/pwa_data_cache_m5.md`. Fitness Coach remains `session` because
its canonical class is personal data; no feature flag promotes it to
persistent storage. Calendar and Chat remain a later reviewed tranche, and CRM
and Mail remain denied pending explicit privacy approval.

Legacy Website Studio snapshots and Fitness Coach bootstrap/thumbnail values
may be offered only as sanitized migration seeds. They never paint directly
and are removed only after the parent verifies the scoped commit. Fitness
Coach derives the legacy bootstrap workspace and mounted-app scope from the
immutable context injected by Core into the authenticated isolated document,
never from mutable URL query parameters. App Store
catalog rows remain read-only until fresh workspace, installation, pin, and
other authority inputs arrive. Across every pilot, expired data is a miss,
`maverick.app.data-changed` is accepted only from the shell or a frame whose
registered owner exactly matches the declared owner. A `401`/`403` triggers
scoped cleanup, notifies the shell to clear authenticated UI, and unmounts all
app/widget frames so previously rendered private data cannot survive; a later
authenticated session creates fresh frames. No cache result grants
mutation, provider, capability, publication, or launch authority. Both the
global and all per-app M5 gates remain off by default; implementation readiness
does not replace privacy or physical Safari/Home Screen release evidence.

Workspace or authenticated-session transitions rotate the shell generation
and synchronously remove frames from the previous generation before the new
broker becomes usable. A late old-frame request is answered unavailable
without consulting or exposing a warm entry from the new workspace. Shell
fan-out applies the same scoped owner check to app and widget recipients; only
an exact top-level shell message may intentionally cross owners.

AppShell enters an explicit transition barrier before requesting or applying a
replacement session: the published session, broker principal, frame scope, and
authenticated frame tree are removed in the same synchronous commit. Cache
lifecycle transition, logout, authorization failure, invalidation, and clear
operations execute through one serialized queue. A newly authenticated session
and its app registry are published only after its lifecycle transition has
completed and only if that load is still current. Logout enters the barrier
before its network request, completes local lifecycle cleanup even when the
request fails, and never depends on a follow-up session read to remove frames.

The barrier also precedes the actual Core request for a workspace switch or
creation. `WorkspaceSwitcher` is presentation-only; AppShell cancels the active
load, synchronously unmounts app/widget frames and both brokers (including the
Storage file broker through layout cleanup), then performs the mutation. It
transitions the lifecycle and loads the new registry before publishing the
resulting session.

Shell API requests, PWA-config reads, structured-data reads, Storage file
reads, and isolated-frame launch share one authorization-revocation channel.
Every invocation signals AppShell synchronously, including while another
revocation cleanup is pending; only the durable cleanup promise is coalesced
through the serialized lifecycle. That cleanup is not part of network timeout
classification: a received `401`/`403` remains a terminal HTTP response even
if cleanup is delayed behind another lifecycle operation.

## M6 implementation profile

M6 makes the existing cache boundary observable and operable without exposing
residency or identifiers. Base Shell aggregates a closed event vocabulary for
static/data/file hits, misses, stale/expired reads, revalidation, quota,
eviction, worker lifecycle, and request wait/retry/cancellation. Only aggregate
counters, quota gauges, and bounded duration summaries persist, for at most
seven days. Pending salted operation hashes stay in RAM. The isolated Settings
app obtains this dashboard through an exact registered-frame `MessageChannel`;
it cannot read shell storage and receives no cache entry, URL, file name,
principal, record id, payload, token, or content. Clear cancels RAM work,
executes the durable structured/file cleanup, and resets metrics only after a
complete deletion result.

The 2026-09-06 review fixes clarify two lifetime boundaries. Each structured
single-flight consumer owns only its own cancellation; the shared transport is
cancelled when no consumer remains. A broker transfers a departing loader
frame's read only to an already admitted reader of the same resource/entity.
Useful reconnection of the live app-event socket triggers scoped display
refresh because events have no replay cursor; it never remounts app frames or
changes product mode. Event aliases are reread triggers, not exhaustive change
sets: Website Studio retires resolved and pending derived previews whenever
the accepted site's snapshot revision changes, including revalidation without
another event. Same-site navigation does not invalidate the data-read lifetime:
initial and revalidated snapshots reconcile the latest selection directly,
without waiting for a prior preview build or issuing a replacement read. A
separate selection lifetime guards preview publication, errors and loader
cleanup for both navigation and recovery. Late builds cannot publish, report
errors over the current view or remove a replacement pending entry.
Pending-count/oldest-wait gauges belong solely to the
current shell document's RAM, while persisted shards aggregate historical
counters and completed durations. Expired diagnostics are automatically pruned
in throttled, bounded batches, not merely ignored at aggregation time.

Each existing boolean flag may be narrowed by stable 0–100 workspace and user
cohorts. Invalid values and missing identities in a partial cohort select
nobody; cohort inputs and buckets are not returned by the public config. The
operational policy is source-controlled and CI-audited against frontend asset
manifests, SDK budgets, the resource inventory, retryable methods/statuses, and
every RAM-retried mutation. Such a mutation now requires a registered audit id
in addition to its idempotency key, canonical request fingerprint, bounded
attempts, server deduplication, and replay regression test.

Quota, LRU pressure, corruption, and intermittent transport have an explicit
chaos matrix. Rollback and worker recovery remain namespace-bounded. A
redaction-safe evidence validator enforces the full physical Safari,
Home Screen/Dock, and Chrome matrix with a 90-day freshness limit. Tooling does
not convert emulation into physical evidence; a missing record keeps the
release gate open.

## Supersession boundary

When ADR-0011 and this record conflict, this record is normative. Historical
test results and checkpoint dates must not be rewritten, but current
architecture, product contracts, runbooks, security guidance, generated
artifacts, and tests must describe this decision.

## Normative product companion

- `docs/product/pwa_cache_product_contract.md`
- `docs/product/pwa_cache_resource_inventory.v2.json`
- `docs/product/pwa_cache_operational_policy.v1.json`
