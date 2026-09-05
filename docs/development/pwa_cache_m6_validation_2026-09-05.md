# PWA Cache M6 Validation — 2026-09-05

Status: automated M6 gate complete; physical-device release evidence pending.

## Implemented scope

| Plan item | Evidence |
|---|---|
| PWA-090/091 | Closed aggregate metric schema, seven-day bounded persistence, Base Shell operations broker, and Settings cache/space dashboard |
| PWA-092 | `docs/security/pwa_cache_m6_review.md` plus exact-frame, redaction, corruption, and cleanup tests |
| PWA-093 | `packages/pwa-cache/tests/hardeningChaos.test.ts` covers quota failure, LRU pressure, corrupt payload, and intermittent single-flight transport |
| PWA-094 | Deterministic, monotonic workspace/user cohort gates in `core/pwa/rollout.py` |
| PWA-095 | Rollback and namespace-bounded worker recovery in `docs/runbooks/pwa_cache_operations_m6.md` |
| PWA-096 | Cache/space-only user guidance in `docs/product/pwa_cache_user_guide.md` |
| PWA-097 | CI audit of every frontend build's asset/total budget and every declared manifest digest/output |
| PWA-098 | Policy-derived physical matrix template/verifier with a 90-day freshness and redaction gate |
| PWA-099 | Runtime-required mutation `auditId` and source/policy/client/server/replay audit |

No data-cache, file-cache, or per-app rollout flag was enabled by this work.
The existing service-worker default is unchanged.

## Final automated results

- `packages/pwa-cache`: TypeScript check passed; **15 files / 122 tests** passed.
- Base Shell: **34 files / 185 tests** passed.
- Service-worker/build/broker suite: **16 tests** passed.
- Focused Python M6/API/rollout suite: **17 tests** passed.
- Settings app shard in the repository fast suite: **23 tests**, **9 skipped**, no failure.
- `python3 scripts/audit_pwa_cache.py`: passed against the final generated assets.
- Targeted Python compilation and `git diff --check`: passed.
- Final manifest ids:
  - Base Shell: `80df47c6e487a26435c86d678035bdcd1d2f0a67da7c068d883db080afa25bb0`
  - Settings: `58f785c9fdeec337e96f80fd4109ae16b7af5fe9e3b76e6b24ae7ee143eb6787`

The final Settings artifact was produced through the official app frontend
build. The official Base Shell build succeeded earlier in the validation, but
the final refresh attempt was rejected with `authentication_required` after
the shared CLI session changed. The final Base Shell artifact was therefore
rebuilt with its app-owned `npm run build`; TypeScript, manifest digest, asset
budget, worker, and full frontend tests all passed afterward.

## Repository-wide baseline findings

`python3 scripts/test_suite.py --level fast` ran all configured shards. M6 and
the app shards passed, while the aggregate command remained non-zero for
unrelated repository/environment findings already present at `HEAD`:

- the Codex artifact-history test invoked plain Git, which rejected repository
  ownership; the test passed when rerun with the repository supplied as Git's
  safe directory;
- one runtime process-control assertion was transient and passed immediately
  when rerun alone;
- repository convention checks report
  `tests/unit/api/test_app_mounts.py:1451>1436` and
  `core/runtime/lifecycle_service_sessions.py:332>300`; both files and line
  counts are unchanged from `HEAD`; and
- `scripts/check_unused_imports.py` reports the pre-existing unused
  `fork_hosted_text_execution_binding` import in the same unchanged lifecycle
  module.

These unrelated files were not modified.

## Open physical gate

No physical Safari, iPhone Home Screen, macOS Dock, or Chrome/Edge device run
was available in this environment, so none is claimed. Before a private cache
rollout or the policy freshness deadline, generate the matrix with
`scripts/pwa_device_regression.py template`, execute it on the required
physical containers, and require `verify` to pass. Emulation cannot satisfy
this gate.

Core was not restarted because no live rollout was activated and a restart
would disrupt concurrent repository work. A deployment must restart its Core
process after installing this code or changing environment-backed cohort
values, then verify health and the authenticated `/api/pwa/config` projection.
