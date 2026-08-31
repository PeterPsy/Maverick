# PWA cache M3 implementation validation — 2026-08-31

## Status

M3 shared cache mechanics, Base Shell lifecycle/retry integration, Settings
aggregate diagnostics, generated frontend artifacts, and focused automated
tests are implemented. The global data-cache gate remains disabled and no M5
app read model or M4 Storage file cache is enabled by this milestone.

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

## Closed M3 tasks

| Task | Evidence |
|---|---|
| PWA-040 | `@maverick/pwa-cache`; IndexedDB database v2 with transactional v1 payload split |
| PWA-041 | collision-safe mandatory user/workspace/app/resource/entity/policy/schema key |
| PWA-042 | read-through, explicit stale rendering, single-flight revalidation, metadata-only `not_modified` |
| PWA-043 | absolute expiry, least-recent eviction, exact serialized byte accounting, resource/app/global budgets |
| PWA-044 | `navigator.storage.estimate()` adapter; unknown estimate skips writes; no `persist()` call |
| PWA-045 | in-process promise coalescing, Web Locks when present, BroadcastChannel invalidation |
| PWA-046 | Base Shell and client handling for `maverick.app.data-changed` |
| PWA-047 | durable cleanup for logout, unknown/cold authorization failure, user/workspace and policy changes |
| PWA-048 | automatic memory backend after IndexedDB absence or operation failure |
| PWA-049 | Settings aggregate bytes, entries, origin estimate, backend, cleanup markers, and two-click clear |
| PWA-050 | successful/aborted migration, cleanup-resume, backend fault, quota fault, and payload-touch tests |
| PWA-051 | non-overridable agentic control-plane resource denylist plus negative policy tests |
| PWA-052 | RAM retry with capped exponential delay, jitter, hints, cancellation, scope and frame visibility |
| PWA-053 | idempotency header/fingerprint/server-dedup contract, coalescing, reuse rejection, three-attempt cap |

## Security and failure semantics

The exact local policy revision is
`maverick.local-persistence-policy.v2`. Private entries need an access lease
issued after fresh server authentication and capped at 15 minutes. Structured
budgets default to 64 MiB global and 32 MiB per app; each resource must set
smaller entry/scope limits. Cache writes require a usable quota estimate below
85% projected origin usage.

Credential-like keys and values, signed URLs, `blob:` URLs, non-plain values,
cycles, excessive nesting, invalid scope, and non-finite numbers are rejected
before persistence. `deny` never selects a backend; `session` selects only the
client RAM backend and durably removes a former persistent resource. Agentic
capabilities, certificates, provider state/bindings, admission, egress,
authority, confirmation, proposals, revocations, and secret grants remain
network-only even if an adapter falsely claims public/cache approval.

An expired entry is deleted and returned as a miss. A cache, quota,
serialization, or IndexedDB failure cannot replace a valid network result.
`401`/`403` are terminal and trigger cleanup. Retry is RAM-only, never reads
`navigator.onLine` as authority, and automatically pauses while the document
or mounted Maverick frame is hidden.

## Automated evidence

| Surface | Result |
|---|---|
| PWA cache package typecheck | passed |
| PWA cache package | 5 files, 42 tests passed |
| Base Shell frontend | 27 files, 126 tests passed |
| Worker/build harness | 13 tests passed |
| Focused PWA/config/assets/Settings Python selection | 44 tests, 35 passed and 9 expected slow skips |
| Unused-import check | passed |
| Base Shell official build | `da532c1773c933f824c9b1829a386a0f3311173b0e5658264ffe593ec6e4024e` |
| Settings official build | `99a70035322d0984da809a568a55ad4465003c582e0a906a9a405445440d18e3` |

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
where applicable, app-specific rollout gate, and browser/device evidence.
OPFS bytes, file streaming/partial recovery, and file-cache eviction remain M4.
