# PWA Cache M6 Validation — 2026-09-05

Status: M6 review findings remediated and M6 automated gates green;
physical-device and resource-specific rollout gates remain pending.

## Implemented scope

| Plan item | Evidence |
|---|---|
| PWA-090/091 | Closed aggregate metric schema, generation-qualified per-tab writer shards, winning-marker reset linearization, single-recipient worker events, Base Shell operations broker, and Settings cache/space dashboard |
| PWA-092 | `docs/security/pwa_cache_m6_review.md` plus exact-frame, redaction, corruption, multi-tab, and cleanup tests |
| PWA-093 | `packages/pwa-cache/tests/hardeningChaos.test.ts` covers quota failure, LRU pressure, corrupt payload, and intermittent single-flight transport |
| PWA-094 | Deterministic, monotonic workspace/user cohort gates in `core/pwa/rollout.py` |
| PWA-095 | Rollback and namespace-bounded worker recovery in `docs/runbooks/pwa_cache_operations_m6.md` |
| PWA-096 | Cache/space-only user guidance in `docs/product/pwa_cache_user_guide.md` |
| PWA-097 | CI audit of every frontend build plus canonical class rules and exact inventory/runtime declaration parity, including invalidation aliases |
| PWA-098 | Policy-derived physical matrix/verifier plus monthly, release-triggered, reusable, and manually dispatchable fail-closed workflow; no physical evidence is claimed here |
| PWA-099 | Factory-only nominal mutation contracts bound to audit id/method/endpoint/action, plus repository-wide production JS/TS/component source/policy/client/server/replay audit |

No data-cache, file-cache, or per-app rollout flag was enabled by this work.
The existing service-worker default is unchanged.

## Review remediation

- Metrics no longer use a last-writer-wins shared document. Each tab writes an
  opaque shard; snapshots merge current shards and ignore stale generations.
  Reset uses one shared generation marker, generation-qualified writer keys,
  and a winning-marker reread. It preserves events ordered after one reset and
  after the winning reset in a tested two-clear interleaving.
- The service worker sends each metric to one window client, preventing one
  worker operation from being counted once per open tab.
- `pwa_revalidate_error` is emitted only when the conditional loader fails.
  Local persistence failures use `pwa_data_cache_error` and quota metrics.
- Base Shell builds `RESOURCE_DECLARATIONS` directly from
  `pwaDataCacheResourceDeclarations.v1.json`. The audit compares that manifest
  bidirectionally with the product inventory and validates exact invalidation
  aliases, the complete `RuntimeDataClass` set, and every class-specific
  approval gate.
- Mutation discovery covers JavaScript, TypeScript, Vue, and Svelte production
  sources under apps (including Storage), shared packages, Core, and scripts.
  Raw/computed contract declarations are rejected. A nominal contract can only
  be issued by the SDK factory when audit id, method, endpoint, and action match
  the v2 runtime registry; the coordinator validates the same tuple at use time.
- CI explicitly runs the PWA SDK typecheck and complete suite (including chaos,
  metrics, and protocols), Base Shell worker/broker tests, Settings DOM
  interactions, and the authenticated isolated-frame shell smoke. A separate
  workflow directly invokes the physical-evidence verifier. That workflow now
  runs monthly, on release events, by dispatch, and through `workflow_call`,
  using explicit input or the `PWA_DEVICE_EVIDENCE_JSON` repository variable.

## Automated results

- `packages/pwa-cache`: TypeScript check passed; **15 files / 132 tests** passed.
- Base Shell: **34 files / 185 tests** passed.
- Service-worker/build/broker suite: **16 tests** passed.
- Settings frontend: TypeScript/build passed; **1 file / 2 DOM tests** passed.
- Focused PWA API, rollout, audit, inventory, and device-policy Python suite:
  **33 tests** passed.
- `python3 scripts/audit_pwa_cache.py`: passed against the generated assets.
- JavaScript/Python syntax checks and `git diff --check`: passed.
- Authenticated Chromium shell/Settings smoke: passed with **16** verified
  precache records, isolated-origin refresh/clear, transport loss, restart, and
  recovery.
- Official frontend build ids:
  - Base Shell: `2bae45fdbec4c672b0d57e5c540b166e8e93a2ec18b85d3c15c656d7e58f528b`
  - Settings: `a0acff84cdc0658b24343ddbb296e0655bab8b40b9a41a81786f1a3fc8512e84`

The repository-wide unused-import checker passed. Concurrently owned Core and
provider work present in the shared tree was not changed by this remediation.

The authenticated Settings → Cache smoke is now a required CI command and
fails rather than skipping when Chromium is unavailable. It verifies the real
login, isolated Settings frame, dashboard refresh, two-step clear, shell
precache, transport loss, restart, and recovery. The DOM-level test separately
forces a durable `pending` cleanup result and proves that confirmation remains
available with an error rather than reporting success.

## Open release gates

No physical Safari, iPhone Home Screen, macOS Dock, or Chrome/Edge device run
was available in this environment, so none is claimed. A release owner must run
the complete generated matrix, store the current redaction-reviewed evidence,
and require the reusable **PWA Physical Device Release Gate** before artifact
promotion. The scheduled and release-event executions continuously detect
missing/stale evidence; emulation and the authenticated Chromium CI smoke
cannot satisfy this gate.

M5 is also intentionally not relabeled complete: Calendar and Chat remain the
second tranche, and CRM/Mail remain denied pending their explicit privacy
approvals. Those product/privacy decisions are not inferred by this M6
hardening change. All related flags therefore remain fail-closed.
