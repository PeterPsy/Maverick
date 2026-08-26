# ADR-0011: PWA Cache And Offline-Aware Boundaries

## Status

Accepted on 2026-08-26 as the M0 gate for the PWA cache rollout.

This decision authorizes an offline shell and verified static-asset caching. It
does **not** authorize persistent private read models, offline files, or an
outbox until their later milestone gates and feature flags are complete.

## Context

Maverick is online-first. Browser HTTP caching already helps some hashed
bundles, while the current service worker caches only selected Base Shell
assets and cannot reopen a navigation offline. App data remains server-owned,
and existing browser caches are app-specific and lack a shared scope, quota,
classification, or logout contract.

The browser stores controlled by one origin share quota and may be evicted.
Cache API, IndexedDB, and OPFS therefore hold derived copies only. They are not
an authority boundary and cannot authorize an agent, provider, capability,
egress decision, confirmation, or mutation.

## Decision

### 1. Ownership stays explicit

| Surface | Owner | Responsibility |
|---|---|---|
| HTTP validators and frontend artifact verification | Core app hosting | Generic HTTP semantics; no app read models |
| Root service worker, offline shell, connectivity UI, cleanup coordination | Base Shell | One platform shell lifecycle |
| Record schema, revision, sanitization, TTL, and invalidation | Owning app | No cross-app cache reads |
| File pin UX and stable Storage references | Storage | Opt-in file availability only |
| Shared browser primitives | `@maverick/pwa-cache` | Technical scoped stores, quota, LRU, OPFS, cleanup |

The shared SDK will live at `packages/pwa-cache/` beginning in M3. It will be a
framework-neutral ESM package built and versioned independently, consumed by
apps through an explicit package dependency. It may import platform-owned
types and policy artifacts, but it may not import any app source or model. An
app adapter may never address another app's cache namespace.

### 2. Browser storage has specialized roles

- Cache API stores verified shell and static HTTP responses.
- IndexedDB stores bounded structured derivatives and file indices.
- OPFS stores large pinned file bytes behind opaque scoped names.
- RAM stores hot data and in-flight deduplication.
- `localStorage` stores only small UI preferences, non-sensitive timestamps,
  and cleanup signals.
- `sessionStorage` is limited to bounded session-only state and migration
  compatibility.

HTML remains `no-store` over HTTP. A verified service worker may explicitly
retain the exact shell fallback corresponding to its build.

### 3. Local persistence policy v1 derives from canonical classification

The policy revision is `maverick.local-persistence-policy.v1`. It consumes the
existing canonical `RuntimeDataClass` value; it does not rename or replace that
classification.

| Canonical `data_class` | Default | Maximum after an explicit resource rule |
|---|---|---|
| `public` | `cache` | `offline_opt_in` |
| `workspace_internal_fake` | `session` | `cache` |
| `workspace_internal` | `session` | `offline_opt_in` |
| `personal_data` | `session` | `offline_opt_in` after app privacy approval |
| `regulated_or_customer_data` | `deny` | `offline_opt_in` only on a reviewed resource allowlist |
| `credential_or_secret` | `deny` | `deny` |
| `host_operational_metadata` | `deny` | `deny` |
| `unclassified` or unknown | `deny` | `deny` |

The effective result is the most restrictive intersection of canonical class,
provenance, resource/app rule, current egress/authority constraints, rollout
flag, and user choice. A resource rule may narrow the result. It cannot exceed
the table's maximum. `deny` always wins, and a missing or stale classification
fails closed.

The normative resource inventory stores `local_persistence_policy` only as one
of `deny`, `session`, `cache`, or `offline_opt_in`. Unmet approval, revision,
classification, allowlist, or opt-in conditions belong in the optional
`policy_prerequisites` list instead of being embedded in that enum value. A
missing canonical class is recorded as `unclassified`, and an effective `deny`
row has zero local TTL and byte budget until its policy is explicitly revised.

The agentic control plane has an invariant resource override of `deny`,
including effective capabilities, certificates, provider profiles/bindings,
provider state, admission/preflight, recovery state, revocations, egress
authorization, authority/confirmation, proposals, pending tool calls, and
secret grants. Cached metadata is never evidence for a later decision.

### 4. Fully offline private access is denied by default

M2 stores no private app read model. A cold offline reopen may show branding,
connectivity state, static shell UI, and the local-content management surface,
but not a cached Mail, CRM, Chat, Calendar, or Storage payload.

Later milestones may expose a private derivative after restart only when all of
the following are true:

1. the resource policy is `offline_opt_in`;
2. the user made an explicit choice on that device;
3. the copy has the full user/workspace/app/resource scope;
4. a bounded local access lease, minted after fresh server authentication, has
   not passed the earlier of session expiry, resource expiry, or policy expiry;
5. no pending logout, user change, workspace removal, schema reset, `401`, or
   `403` cleanup marker exists;
6. the UI labels source, freshness, and last successful verification.

Mail, CRM, and Chat require a separate privacy approval before such a resource
allowlist exists. Being offline cannot extend a server session or suppress a
revocation once the server is reachable.

### 5. Supported browser floor is explicit and feature-detected

The release test floor is Safari 17.4 on macOS 14.4 and iOS/iPadOS 17.4,
including Home Screen and Dock-installed web apps. Current Safari on the newest
supported macOS/iOS is also tested. Current Chrome and Edge are control
browsers, not substitutes for WebKit acceptance.

Every storage primitive remains feature-detected. Missing service workers,
Cache API, IndexedDB, OPFS, `estimate()`, or `persist()` produce a server-first
fallback rather than an app failure. Private browsing and ephemeral contexts
are not described as persistent offline storage.

### 6. Rollout switches are independent and fail closed

| Environment variable | Default | Purpose |
|---|---:|---|
| `MAVERICK_FEATURE_PWA_SERVICE_WORKER_V2` | on | Offline shell/static cache; immediate kill switch |
| `MAVERICK_FEATURE_PWA_DATA_CACHE` | off | Global private read-model gate |
| `MAVERICK_FEATURE_PWA_APP_CACHE_<APP_ID>` | off | Per-app gate, subordinate to the global gate |
| `MAVERICK_FEATURE_PWA_STORAGE_OFFLINE_FILES` | off | Storage opt-in file gate |
| `MAVERICK_FEATURE_PWA_OFFLINE_OUTBOX` | off | Future write gate |

Accepted true values are `1`, `true`, `yes`, and `on`; accepted false values
are `0`, `false`, `no`, and `off`. Invalid values disable the surface. The
public, `no-store` `/api/pwa/config` response exposes only browser-safe effective
state. Disabling worker v2 makes clients unregister it and clean only known
Maverick static caches; it cannot erase unrelated Cache API entries or any
future IndexedDB/OPFS data.

### 7. Product and connectivity contracts are narrow

Approved description:

> Maverick è offline-aware e supporta consultazione e preparazione locale
> selettiva; l'esecuzione agentica richiede la rete.

M2 must not use an unqualified “offline capable” claim. One global Offline
indicator replaces the current-app icon in the top-left sidebar slot. The same
slot is used in expanded and rail-only layouts; no duplicate main-area banner
or persistent toast is allowed. The control exposes last successful sync and
opens local-content management. `navigator.onLine` may report loss, but a
successful fresh Maverick request is required to restore Online state.

Remote mutations, prompts, models, agents, and tools are not actionable while
offline. App-specific inline explanations are allowed and do not become a
second global status banner.

### 8. Baseline and release evidence are redaction-safe

The repeatable probe records request count, transferred response bytes, shell
time, immutable responses, `304` responses, service-worker responses, file
revalidation, and offline reopen. It records neither content nor credentials,
file names, signed URLs, subjects, record ids, or app payloads.

Playwright WebKit emulation is a development signal only. Release acceptance
requires the same capture sheet on one physical supported Mac and iPhone for
cold online, warm online, slow/intermittent network, offline reopen, and file
open/revalidation. Measured p75/p95 values become budgets only after that
physical-device baseline; this ADR does not invent absolute time thresholds.

### 9. Rollback precedes rollout

The worker update is atomic: a failed install leaves the active worker and
cache usable. Activation deletes only obsolete cache names owned by the static
PWA implementation. Rollback may disable registration, serve a cleanup worker,
or disable SDK reads while preserving the server-first path. It must never
depend on clearing the entire origin.

No offline writes are authorized in M0-M5. A future outbox needs a separate
gate, idempotency, revision conflicts, visible state, and fresh server-side
admission/authorization/confirmation after reconnect.

## Consequences

- Static and shell caching can ship before private browser persistence.
- Mail/CRM/Chat cold-offline access remains unavailable until explicitly
  reviewed instead of emerging accidentally from implementation details.
- Apps must provide canonical classification and stable revision metadata
  before their read model can opt in.
- The same-origin XSS boundary remains important; browser-side encryption with
  a key available to the same JavaScript is not treated as an XSS solution.
- Browser eviction is recoverable because all cached content is derivative.

## Normative companions

- `docs/product/pwa_offline_capabilities.md`
- `docs/product/pwa_cache_resource_inventory.v1.json`
- `docs/runbooks/pwa_cache_baseline.md`
- `docs/runbooks/pwa_shell_v2.md`
- `SECURITY.md`
