# PWA Cache M6 Validation — 2026-09-05

Status: M6 review findings remediated and M6 automated gates green;
physical-device and resource-specific rollout gates remain pending.

## Implemented scope

| Plan item | Evidence |
|---|---|
| PWA-090/091 | Closed aggregate metric schema, per-tab writer shards, generation-linearized reset, single-recipient worker events, Base Shell operations broker, and Settings cache/space dashboard |
| PWA-092 | `docs/security/pwa_cache_m6_review.md` plus exact-frame, redaction, corruption, multi-tab, and cleanup tests |
| PWA-093 | `packages/pwa-cache/tests/hardeningChaos.test.ts` covers quota failure, LRU pressure, corrupt payload, and intermittent single-flight transport |
| PWA-094 | Deterministic, monotonic workspace/user cohort gates in `core/pwa/rollout.py` |
| PWA-095 | Rollback and namespace-bounded worker recovery in `docs/runbooks/pwa_cache_operations_m6.md` |
| PWA-096 | Cache/space-only user guidance in `docs/product/pwa_cache_user_guide.md` |
| PWA-097 | CI audit of every frontend build plus canonical class rules and exact inventory/runtime declaration parity |
| PWA-098 | Policy-derived physical matrix/verifier and a dispatchable CI release-gate workflow; no physical evidence is claimed here |
| PWA-099 | Non-overridable runtime mutation registry and repository-wide production JS/TS/component source/policy/client/server/replay audit |

No data-cache, file-cache, or per-app rollout flag was enabled by this work.
The existing service-worker default is unchanged.

## Review remediation

- Metrics no longer use a last-writer-wins shared document. Each tab writes an
  opaque shard; snapshots merge current shards and ignore stale generations.
  Reset uses one shared generation marker and preserves events ordered after
  that marker, including a tested reset/write interleaving.
- The service worker sends each metric to one window client, preventing one
  worker operation from being counted once per open tab.
- `pwa_revalidate_error` is emitted only when the conditional loader fails.
  Local persistence failures use `pwa_data_cache_error` and quota metrics.
- Base Shell builds `RESOURCE_DECLARATIONS` directly from
  `pwaDataCacheResourceDeclarations.v1.json`. The audit compares that manifest
  bidirectionally with the product inventory and validates the complete
  `RuntimeDataClass` set and every class-specific approval gate.
- Mutation discovery covers JavaScript, TypeScript, Vue, and Svelte production
  sources under apps (including Storage), shared packages, Core, and scripts.
  Operational evidence and the JSON registry imported by the runtime must
  match exactly; callers cannot replace the approved registry.
- CI explicitly runs the PWA SDK typecheck and complete suite (including chaos,
  metrics, and protocols), Base Shell worker/broker tests, Settings DOM
  interactions, and the authenticated isolated-frame shell smoke. A separate
  workflow directly invokes the physical-evidence verifier.

## Automated results

- `packages/pwa-cache`: TypeScript check passed; **15 files / 128 tests** passed.
- Base Shell: **34 files / 185 tests** passed.
- Service-worker/build/broker suite: **16 tests** passed.
- Settings frontend: TypeScript/build passed; **1 file / 2 DOM tests** passed.
- Focused PWA API, rollout, audit, inventory, and device-policy Python suite:
  **30 tests** passed.
- `python3 scripts/audit_pwa_cache.py`: passed against the generated assets.
- JavaScript/Python syntax checks and `git diff --check`: passed.
- Authenticated Chromium shell/Settings smoke: passed with **16** verified
  precache records, isolated-origin refresh/clear, transport loss, restart, and
  recovery.
- Official frontend build ids:
  - Base Shell: `41c05100ee3cbeb274460548bad57f2d30bb0208934a10747e503c66b081213b`
  - Settings: `cd88915b042c82cbe578c3dc08f4d30ae6985823d54c10e631d632133bcf23c4`

The repository-wide unused-import checker still reports only the unrelated
pre-existing import in `core/runtime/lifecycle_service_sessions.py`; that
concurrently owned file is not changed by this remediation.

The authenticated Settings → Cache smoke is now a required CI command and
fails rather than skipping when Chromium is unavailable. It verifies the real
login, isolated Settings frame, dashboard refresh, two-step clear, shell
precache, transport loss, restart, and recovery. The DOM-level test separately
forces a durable `pending` cleanup result and proves that confirmation remains
available with an error rather than reporting success.

## Open release gates

No physical Safari, iPhone Home Screen, macOS Dock, or Chrome/Edge device run
was available in this environment, so none is claimed. A release owner must run
the complete generated matrix and dispatch **PWA Physical Device Release Gate**
with the current redaction-reviewed evidence. Emulation and the authenticated
Chromium CI smoke cannot satisfy this gate.

M5 is also intentionally not relabeled complete: Calendar and Chat remain the
second tranche, and CRM/Mail remain denied pending their explicit privacy
approvals. Those product/privacy decisions are not inferred by this M6
hardening change. All related flags therefore remain fail-closed.
