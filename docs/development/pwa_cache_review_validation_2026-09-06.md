# PWA cache — review corrections and release handoff, 2026-09-06

> Historical candidate `fb6e7145`: the four corrections below were independently
> confirmed, but a later review reproduced stale Website Studio previews after
> recovery. That follow-up is corrected and the replacement candidate/evidence
> is recorded in [Website Studio recovery validation](pwa_cache_website_recovery_validation_2026-09-06.md).
> This checkpoint does not certify the replacement Website Studio bundle.

## Verdict and exact candidate

**All four reported code findings are corrected and regression-tested. M6's
release gate is still open:** physical PWA-098 and controlled rollout/rollback
execution cannot be inferred from code or Chromium smoke. No shared/live cache
flags were changed and no physical result has been fabricated.

- Implementation: `2aacaddd` — independent read cancellation, broker handoff,
  reconnect refresh, live-only pending gauges and bounded physical retention.
- Code/asset candidate: **`fb6e71453a3ae080d90315491ea2339c29f69cc6`** on `design`.
- [Ten exact manifest identities](pwa_cache_review_candidate_2026-09-06.json),
  including Shell, Chat and Settings; the record also binds the captured smoke
  file's SHA-256. The old `1e095087` candidate and its evidence are historical,
  not authorization to release these changed assets.
- [Captured Chromium smoke](pwa_cache_review_chromium_2026-09-06.json),
  `2026-09-06T09:31:14.902Z`, shell build
  `84699ab3435c079dbb87461c448bb3f805c2d1edec5245780ccc05246cf8cf4b`.

The PWA code, Core source, smoke scripts and generated frontend files used for
the final smoke were compared with the candidate and had no differences. The
concurrent architecture/provider-test changes were not staged. Documentation
commits following this candidate do not change the tested binaries.

## Corrections

| Review finding | Implementation and regression |
|---|---|
| P1: first reader cancels peers | Every consumer has its own cancellable promise; only departure of the last reader aborts the shared signal. Abandoned loaders cannot publish, even if they ignore abort. Native queued locks receive that signal. The real broker hands a departed loader frame's conditional read to another admitted same-resource/entity frame. Cold and warm two-frame tests verify surviving delivery and cache publication, not only an isolated helper. |
| P2: reconnect misses updates | A shared event-socket connector triggers refresh only after a useful connection opens following interruption, including failed initial connection. It bounds reconnect backoff and cancels timers/old callbacks at teardown. Shell uses the existing scoped owner refresh routes without remounting frames; Calendar coalesces recovery with live events into a fresh read. App Store now accepts exact-parent catalog refreshes without rerunning or granting installation/workspace authority. |
| P2: ghost pending after reload | Persisted shards contain history, not live pending gauges. Snapshot pending/oldest values come only from the current shell document's RAM and are explicitly labelled “this window”. Old-format pending fields are ignored; real pending survives a historical retention-window rollover. Historical counters still merge across tabs. |
| P2: expired shards retain storage | Collector startup and ongoing writes/reads sweep at most 64 keys per pass, throttled to once per minute per collector. A rolling cursor removes obsolete owned shards without a dashboard or manual reset. Tests cover multiple batches, refreshed shards, winning reset generations, denied storage and unrelated-key preservation. |

Existing cleanup/publication generations, leases, authorization revocation,
same-origin/frame validation and mutation retry restrictions remain in force.
Reader handoff does not retry an arbitrary loader error or create an outbox.

## Verification

Focused repeats are not counted twice in this table.

| Suite | Result |
|---|---|
| PWA SDK | 195 passed, 25 files; TypeScript passed |
| Base Shell | 215 passed, 37 files, including real broker and shell/App Store recovery integration |
| Worker/build/browser contracts | 17 passed, including actual Chromium metrics reload and localStorage pruning |
| Calendar frontend | 36 passed, 6 files, including component-level changed-data recovery |
| Chat frontend | 631 passed, 92 files |
| Storage frontend | 134 passed, 28 files |
| Fitness Coach frontend | 85 passed, 14 files |
| Settings cache DOM | 2 passed |
| App Store content-hash contracts | 5 passed |
| Python PWA | 20 passed |
| Python audit/device-evidence policy | 21 passed |

**1,361 tests passed.** PWA operational audit, SDK typecheck, unused-import
checker and final diff whitespace checks passed. Ten official
`maverick app <id> frontend build --json` operations completed and published
scoped frontend refresh events. CRM, Mail and Website Studio were rebuilt and
covered by SDK/broker/smoke checks; their separate full visual/E2E suites and the
repository-wide pre-merge suite were not run.

The final authenticated smoke used a fresh disposable Core root and a persistent
Chromium profile. It verified all five approved display adapters in IndexedDB,
warm broker delivery with each display transport blocked, 16 shell precache
entries, unchanged mounted UI on transport loss, ordinary loading on restart,
dynamic-request exclusion, and isolated Settings refresh/clear/recovery. The
earlier review's provider identity startup failure did **not** recur. An initial
pre-build smoke was diagnostic only; it is not the evidence linked above.

Representative commands from the Maverick root:

```sh
npm --prefix packages/pwa-cache test -- --maxWorkers=1
npm --prefix packages/pwa-cache run typecheck
npm --prefix apps/base-shell test -- --maxWorkers=1
npm --prefix apps/base-shell run test:service-worker
npm --prefix apps/calendar test -- --maxWorkers=1
# Same bounded Vitest invocation for Chat, Storage, Fitness and Settings.
npm --prefix apps/app-store run test:content-hash
.venv/bin/python -m unittest discover -s tests/unit/pwa
.venv/bin/python -m unittest tests.unit.scripts.test_audit_pwa_cache tests.unit.scripts.test_pwa_device_regression
.venv/bin/python scripts/audit_pwa_cache.py
python3 scripts/check_unused_imports.py
.venv/bin/python scripts/pwa_shell_cache_smoke.py --app-read-models
```

## Remaining operational gates — not executed

1. **Physical PWA-098:** execute all eight profiles in
   [the new candidate-bound matrix](pwa_cache_review_device_matrix_2026-09-06.json)
   on real Safari/iOS/iPadOS/Home Screen/macOS Dock and Chrome/Edge devices. It
   intentionally has pending scenarios, no capture timestamp and no redaction
   approval. The verifier was run and correctly returned **exit 1**. This is
   negative-gate verification, not a physical pass.
2. **Release owner approval and controlled rollout:** after physical acceptance,
   set observation windows and acceptance thresholds, record a gates-off
   baseline, and follow the M6 runbook's 1%, 5%, 25%, 50%, 100% progression for
   one approved resource at a time. No live cohort was selected or activated.
3. **Operational rollback drill:** record the affected app/cohort disable,
   authenticated config confirmation, shell reload and ordinary server-first
   reads. If removal is required, require durable Settings clear with no late
   writer republication. Automated kill-switch/cleanup tests are not this drill.

```sh
python3 scripts/pwa_device_regression.py verify \
  --input docs/development/pwa_cache_review_device_matrix_2026-09-06.json \
  --expected-release-id fb6e71453a3ae080d90315491ea2339c29f69cc6
```

No shared backend restart was necessary for these frontend/SDK fixes; official
builds publish refreshed assets. The disposable host exercised current backend
source without disturbing other agents. Any later deployment or Core changes
must be verified by the release owner against this exact candidate, or require
a newly selected candidate and fresh evidence. The full plan must not be marked
complete until the three operational steps above are actually recorded.

## Workspace plan synchronization

The Storage-owned
`storage/generated/development/maverick-pwa-cache-development-plan.md` was
updated through `storage_update_markdown_file` with six guarded exact
replacements. Prior SHA-256:
`e8ce23ffe461f08bd696e1f0061c706412c7cb9c4079f848c787c5a21ec5e904`;
new SHA-256:
`9f15092ab50418891e022de0500707bda2f68331072eb2fd0507dfb48a1d11e2`.
An official Storage reread followed all eight pages and verified the complete
92,412 bytes against the expected update. The status and M6 section now name
this candidate and distinguish the corrected findings from the three still
unexecuted operational gates. No direct workspace-document write was used.
