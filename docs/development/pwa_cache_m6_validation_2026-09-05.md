# PWA Cache M6 Validation — 2026-09-05

Status: five follow-up review findings corrected in `233f5f85` and `2efa105d`;
automated corrective validation is recorded below. M5 completion, physical-device
evidence and private rollout remain open. This is not closure of the whole plan.

## Follow-up review: corrective validation

| Finding | Correction and regression evidence |
|---|---|
| P1 late structured writer | Retained cleanup and maintenance generations; the admission ticket spans initialization, cache lookup, loader and quota waits. Publication and cleanup share a cross-client lock. Cancellation/dispose and lease are rechecked before publishing; cleanup drains an already-entered put. Tests cover clear through a separate lifecycle wrapper, no cancellation, deferred initialization, quota, active put, invalidation, dispose and lease expiry. |
| P1 lost broker retry | Structured pilot adapters replay only SDK-owned, allowlisted, immutable HTTP reads; their arbitrary loader and sanitizer run once. The shell retains the one-shot cancellation envelope, including Settings clear. File reads use a nominal host-issued SDK file executor. Real broker tests prove pending → transport recovery and cleanup cancellation, with no loader replay. |
| P2 body disconnect | JSON-body transport TypeError is retryable; malformed JSON SyntaxError, terminal HTTP and external abort remain terminal/cancelled. |
| P2 Retry-After hints | Hints and visibility resume cannot precede the server deadline. Numeric and HTTP-date delays, including delays beyond the backoff cap, are covered. Long timers are chunked without overflowing browser timer limits. |
| P2 warm config wait | After a positive session decision, config refresh is background work. A deferred-config test receives the warm value before resolving config; explicit denial cancels revalidation and remains latched. |

Corrective automated checks:

- SDK: **16 files / 161 tests**, TypeScript check passed.
- Base Shell: **34 files / 191 tests** passed.
- Storage: **28 files / 134 tests** passed.
- Fitness Coach: **14 files / 85 tests** passed.
- Worker/build/cross-origin broker suite: **16 tests** passed.
- App Store catalog/content-hash suite: **5 tests** passed.
- Focused PWA API, flags/cohorts, inventory, audit and physical-evidence-policy
  Python suite: **37 tests** passed.
- Total: **629 automated tests**; PWA operational audit and unused-import
  checker passed. The full suite also caught a clock-capture issue in the
  deadline guard; the default coordinator clock now resolves Date.now at use
  time, with its own regression test.
- Final official builds for **all five apps** passed and published scoped
  refresh events. An unrelated shared-tree `localRuntimeBroker.test.ts:31`
  TS4104 error temporarily blocked the shell build. Its owning agent corrected
  and committed that work; no Mac runtime source was changed here. During the
  blocker, the exact committed PWA shell source at `2efa105d` was also built and
  tested in a temporary tree: TypeScript, Vite and **34 files / 191 tests**
  passed. The final shared-tree suite passed **35 files / 194 tests** including
  three concurrent tests not counted in the 629 above. The final shell assets
  include the separately committed Mac bridge integration and are already
  versioned by that owner's frontend build commit.
- Authenticated Chromium smoke on final shell build
  `e03421fd2ec0491c0d4cec64323133b77b4056b975906b94626b363be6af7ed4`
  passed with **16 verified precache assets**, isolated Settings refresh/clear,
  normal mounted UI during transport loss, standard-shell restart and recovery.
  It ran with `.venv/bin/python scripts/pwa_shell_cache_smoke.py`; the system
  interpreter lacks uvicorn. This is automated Chromium evidence, not PWA-098.
- No shared backend restart or feature-flag change was needed.

### Corrective build identities

| App | Build id |
|---|---|
| base-shell | `e03421fd2ec0491c0d4cec64323133b77b4056b975906b94626b363be6af7ed4` |
| storage | `94f2ce84ee803581e9692a2a50c6414dce4b204d922846cba000444c27bd5814` |
| fitness-coach | `ae3959b8f4a4605c4c1efbda5da50e18fbae89e7b7578f60c0dcc5f0ae2d8ccc` |
| website-studio | `336a49a8749d58a82268a5428bded523733390dcd3e43c678fd9bb17cd7f8e35` |
| app-store | `7c398b6953347ed76401d27400e9e65e98a3d65d55748d5d5f2cf9158c6f2dc7` |

The plan at `storage/generated/development/maverick-pwa-cache-development-plan.md`
was updated and reread through Storage's guarded Markdown surface. Its current
SHA-256 is `a58a397488a371da8913f28f0f54518d746ac609981c522c6ee44b68cf73f9e0`.
Section 7.8 distinguishes implemented code from validation and actual rollout;
PWA-098, M5 Calendar/Chat, CRM/Mail privacy approval and release-owner cohort
activation are explicitly assigned as open gates, not silently marked done.

Concurrent Core/provider/local-runtime work was left untouched. The browser
publication fence is deliberately conservative (backend-wide generation,
filter-scoped physical deletion) and stores only opaque nonces. Schema
maintenance has a separate epoch so it cannot overwrite an explicit cleanup's
admission boundary. Browser persistence fails closed without shared generation
storage/Web Locks; local memory caching keeps a local fence.

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
| PWA-098 | Candidate-bound physical matrix/verifier plus monthly, release-triggered, reusable, manually dispatchable, and preventive prerelease-promotion workflows; no physical evidence is claimed here |
| PWA-099 | SDK-owned nominal mutation executors bound to audit id/method/endpoint/action and the concrete JSON request, plus repository-wide production JS/TS/component source/policy/client/server/replay audit |

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
  Raw/computed contract declarations and callback-bearing mutation runs are
  rejected. A nominal executor can only be issued by the SDK factory when audit
  id, method, endpoint, JSON action, and action match the v2 runtime registry.
  The SDK snapshots and fingerprints the JSON semantics and owns the exact
  `fetch`; the coordinator mutation path accepts no consumer callback or custom
  classifier. Arbitrary callbacks are restricted to the one-shot `runOpaque()`
  path; retryable GET/HEAD/OPTIONS reads likewise use an SDK-owned executor, so
  no application callback enters an automatic retry loop.
- CI explicitly runs the PWA SDK typecheck and complete suite (including chaos,
  metrics, and protocols), Base Shell worker/broker tests, Settings DOM
  interactions, and the authenticated isolated-frame shell smoke. A separate
  workflow directly invokes the physical-evidence verifier. That workflow runs
  monthly, on release events, by dispatch, and through `workflow_call`, and
  requires evidence to match the expected tag/build exactly. A separate
  promotion workflow gates an existing prerelease before publishing the same
  tag.

## Earlier M6 automated results (historical checkpoint)

- `packages/pwa-cache`: TypeScript check passed; **15 files / 136 tests** passed.
- Base Shell: **34 files / 187 tests** passed.
- Service-worker/build/broker suite: **16 tests** passed.
- Settings frontend: TypeScript/build passed; **1 file / 2 DOM tests** passed.
- Focused PWA API, rollout, audit, inventory, and device-policy Python suite:
  **37 tests** passed.
- `python3 scripts/audit_pwa_cache.py`: passed against the generated assets.
- JavaScript/Python syntax checks and `git diff --check`: passed.
- Authenticated Chromium shell/Settings smoke: passed with **16** verified
  precache records, isolated-origin refresh/clear, transport loss, restart, and
  recovery.
- Official frontend build ids:
  - Base Shell: `be04273db7317161b424c6bc755fb3a62672dbce119c86097a9bac34fc67e419`
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
and use **Promote PWA Release Candidate** with matching evidence. Its reusable
physical gate must pass for the exact prerelease tag before promotion. The
scheduled and release-event executions continuously detect missing/stale or
candidate-mismatched evidence; emulation and the authenticated Chromium CI
smoke cannot satisfy this gate.

M5 is also intentionally not relabeled complete: Calendar and Chat remain the
second tranche, and CRM/Mail remain denied pending their explicit privacy
approvals. Those product/privacy decisions are not inferred by this M6
hardening change. All related flags therefore remain fail-closed.
