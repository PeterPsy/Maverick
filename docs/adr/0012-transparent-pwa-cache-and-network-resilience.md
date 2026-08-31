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
  authentication;
- 64 MiB global structured-cache budget, 32 MiB per app, and an explicit
  smaller resource budget;
- no persistent write when `navigator.storage.estimate()` cannot provide both
  usage and quota, and no call to `navigator.storage.persist()`;
- read retry starting at 1 second, capped at 30 seconds before server
  `Retry-After`, with 0.75–1.25 jitter and a 250 ms minimum hint interval;
- automatic HTTP retry only for transport failures, timeouts, `429`, `502`,
  `503`, and `504`; and
- at most three same-session mutation attempts, only when a stable
  `Idempotency-Key`, request fingerprint, and declared server deduplication are
  all present.

M3 does not opt any app read model into persistent storage and does not add the
M4 OPFS file cache. Those rollouts remain separate reviewed gates.

The M3 SDK lets only the top-level host bind and mint an app-scoped client; an
embedded app cannot provide a replacement principal through client options.
This is capability discipline, not origin isolation. Current same-origin app
frames can still address the origin's browser storage outside the SDK, so a
private app rollout additionally requires an isolated app origin or a genuine
parent-mediated broker used from an opaque-origin frame. The default-off data
gate is mandatory until that browser boundary exists.

## Supersession boundary

When ADR-0011 and this record conflict, this record is normative. Historical
test results and checkpoint dates must not be rewritten, but current
architecture, product contracts, runbooks, security guidance, generated
artifacts, and tests must describe this decision.

## Normative product companion

- `docs/product/pwa_cache_product_contract.md`
- `docs/product/pwa_cache_resource_inventory.v2.json`
