# PWA cache M3 implementation validation — 2026-08-31

## Status

M3 shared cache mechanics, Base Shell lifecycle/retry integration, Settings
aggregate diagnostics, generated frontend artifacts, and focused automated
tests are implemented, including the post-review hardening below. The global
data-cache gate remains disabled and no M5 app read model or M4 Storage file
cache is enabled by this milestone.

No physical Safari, Home Screen, or Dock-container result is represented as
passed. M3 prepares the shared framework; physical evidence remains mandatory
before a private app resource is rolled out.

## Reviewed implementation checkpoints

- `7f1f2762` — scoped IndexedDB/cache policy, migrations, eviction, lifecycle,
  coordination, serialization guard, diagnostics, retry, and fault tests;
- `6448f19f` — Base Shell RAM retry, authentication/scope cleanup,
  invalidation, and official generated build;
- `31bd385e` — Settings Cache page, aggregate metrics, bounded clear action,
  source contract test, and official generated build.
- `e5b273e2` — host-bound scope, resource schema v3/read validation, canonical
  control-plane exclusion, durable cleanup barrier, structured cleanup status,
  retry terminal-error preservation, and rebuilt Settings artifact;
- `eca2eba2` — integrated Base Shell `401`/`403` preservation and real
  `pinned_apps.set` retry backed by atomic App Store deduplication, plus the
  rebuilt Base Shell artifact.
- `5030706e` — raw stored-byte validation before sanitizer normalization, with
  an injected-field regression test.

## Post-review remediation

1. A terminal `401` or `403` is classified before retry-scope cancellation, so
   lifecycle cleanup cannot replace `MaverickHttpError` with
   `RetryCancelledError`. The integration test uses the real request,
   lifecycle, and retry singletons.
2. The top-level host now binds user, workspace, and app identity; client
   options cannot choose another principal, and embedded frames/workers cannot
   mint a host. The same-origin iframe sandbox is explicitly **not** claimed as
   security isolation. Private app persistence stays blocked until isolated
   origins or an opaque-frame parent broker exist.
3. Database and entry schema 3 add an app-owned resource schema revision.
   Every hit re-runs the sanitizer and checks key, policy/schema, exact byte
   size, TTL timestamps, revision, expiry, and private lease before render.
4. Durable clear bypasses the ordinary RAM fallback. Failure records a barrier,
   returns `pending`, blocks persistent access, and Settings shows an error
   until primary deletion is confirmed.
5. Agentic exclusion is derived from canonical owning app and authoritative
   provenance, not resource-name terms; the review's four bypass examples and
   `tool_result` provenance are negative tests.
6. Public `get()` returns a miss for stale entries unless `allowStale` is
   explicit.
7. The generated development plan is synchronized through the Storage API.
   Its post-review SHA-256 is
   `13bf47e1247410a92a5db9fa505ee258077afe5846c581db0dc6fc010ba0b8c4`.
   PWA-053 now has a real Base Shell/App Store mutation proof rather than only
   an SDK contract test.

## Closed M3 tasks

| Task | Evidence |
|---|---|
| PWA-040 | IndexedDB v3; transactional v1 split and resource-schema cleanup |
| PWA-041 | host-bound principal; collision-safe complete scope/schema key |
| PWA-042 | read-through, explicit stale rendering, single-flight revalidation, metadata-only `not_modified` |
| PWA-043 | absolute expiry, least-recent eviction, exact serialized byte accounting, resource/app/global budgets |
| PWA-044 | `navigator.storage.estimate()` adapter; unknown estimate skips writes; no `persist()` call |
| PWA-045 | in-process promise coalescing, Web Locks when present, BroadcastChannel invalidation |
| PWA-046 | Base Shell and client handling for `maverick.app.data-changed` |
| PWA-047 | durable barrier for auth/scope/schema cleanup; pending blocks reuse |
| PWA-048 | automatic memory backend after IndexedDB absence or operation failure |
| PWA-049 | Settings aggregate bytes, entries, origin estimate, backend, cleanup markers, and two-click clear |
| PWA-050 | migration, cleanup, backend/quota, corruption, timestamp, and touch tests |
| PWA-051 | canonical app/provenance agentic control-plane exclusion plus bypass regression tests |
| PWA-052 | bounded RAM retry, visibility/cancellation, preserved terminal auth errors |
| PWA-053 | real `pinned_apps.set`; exact SHA-256, atomic dedup, no duplicate event |

## Security and failure semantics

The exact local policy revision is
`maverick.local-persistence-policy.v2`. Private entries need an access lease
issued after fresh server authentication and capped at 15 minutes. Structured
budgets default to 64 MiB global and 32 MiB per app; each resource must set
smaller entry/scope limits. Cache writes require a usable quota estimate below
85% projected origin usage.

Credential-like keys (including suffix variants such as `github_token`) and
values, credential/signed URL query parameters (including `access_token`),
`blob:` URLs, non-plain values, cycles, excessive nesting, invalid scope, and
non-finite numbers are rejected before persistence. `deny` never selects a
backend; `session` selects only the client RAM backend and durably removes a
former persistent resource. Canonical agentic apps and control-plane
provenance remain network-only even if an adapter falsely claims public/cache
approval.

An expired entry is deleted and returned as a miss. A cache, quota,
serialization, or IndexedDB failure cannot replace a valid network result.
`401`/`403` are terminal, remain observable as their original HTTP errors, and
trigger cleanup. Retry is RAM-only, never reads
`navigator.onLine` as authority, and automatically pauses while the document
or mounted Maverick frame is hidden.

## Automated evidence

| Surface | Result |
|---|---|
| PWA cache package typecheck | passed |
| PWA cache package | 5 files, 57 tests passed |
| Base Shell frontend | 27 files, 129 tests passed |
| Worker/build harness | 13 tests passed |
| App Store real idempotent mutation | 2 focused integration tests passed |
| Focused PWA/config/assets/Settings Python selection | 44 tests, 35 passed and 9 expected slow skips |
| Unused-import check | passed |
| Base Shell official build | `dc05b20ce076f5df1f140a8dc76e1e0997114859ef3b2ddc6c6b7b8023dfeb42` |
| Settings official build | `48a988763948a15ca8a58826d445f6ba8d1456c20ec86415381acbd620abaa1d` |

The default fast repository suite was also executed. Its main unit shard
(1,066 tests), API shard (305), app-hosting shard (62), runtime shard (31),
runtime-state shard (147), and M3-relevant Settings/Base/PWA selections were
green. The aggregate command remained non-green on unrelated shared-worktree
failures: one runtime-process environment assertion, two existing repository
line-budget assertions, two cross-app Base Shell fixture/source assertions,
and four Senses provider-selection setup errors. The runtime-process assertion
was rerun alone and reproduced. No failed assertion addressed M3 cache,
lifecycle, retry, diagnostics, manifest, or worker behavior.

## Built artifacts and live projection

The Base Shell manifest remains `maverick.frontend-assets.v2`, contains the
normal `index.html` navigation fallback and sixteen verified precache records,
and generated worker tests preserve M2R routing/ownership. Settings contains
the new Cache surface in both the primary app bundle and sidebar page catalog.

After the user's successful backend restart, live checks returned:

```json
{"service":"maverick-core","status":"ok"}
{"schema":"maverick.pwa-config.v2","service_worker":{"enabled":true,"generation":"v2"},"features":{"data_cache":false,"storage_file_cache":false}}
```

No further backend restart is required for these frontend/package/document
changes. Both official builds published `maverick.app.frontend-changed`.

## Rollout boundary

M3 is complete with data cache off. Enabling any resource still requires its
M5 adapter contract, stable revision, canonical inventory entry, privacy review
where applicable, app-specific rollout gate, and browser/device evidence. An
embedded private resource also requires an isolated origin or genuine
opaque-frame parent broker; logical SDK scope alone is not sufficient. OPFS
bytes, file streaming/partial recovery, and file-cache eviction remain M4.
