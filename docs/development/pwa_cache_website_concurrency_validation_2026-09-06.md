# PWA cache — Website Studio concurrent recovery, 2026-09-06

## Verdict and candidate

**Both reported concurrency findings are corrected and regression-tested.**
M6 remains open: physical PWA-098, controlled rollout and the operational
rollback drill have not been executed. No shared/live flags changed and no
shared backend restart was needed. Other agents' changes were not staged.

- Fix and regression checkpoint: **`e4e05aa3`**.
- Official code/assets candidate: **`724c93e50c8e55585b88246ab489ca918185be00`**.
- Website Studio build:
  `910ef054f0a0cf15dc775457405aee5b94797a033471ae29a8501bf8d1bd6517`.
- [Exact ten-manifest binding](pwa_cache_website_concurrency_candidate_2026-09-06.json):
  the other nine manifests are unchanged from `e2466671` and `fb6e7145`.
  All ten match both this Git candidate and the installed build files byte-for-byte.
- [Authenticated Chromium smoke](pwa_cache_website_concurrency_chromium_2026-09-06.json):
  `2026-09-06T11:23:58.855Z`, SHA-256
  `27e28a498e793e0f6d10b2e4902dca22b38d5cfba803f9480bf13216169ee2e9`.

The [previous Website Studio report](pwa_cache_website_recovery_validation_2026-09-06.md)
and its 632 passing tests are historical evidence for `e2466671`; its original
fix did not cover these two interleavings. Earlier reports and their counts
remain historical, not claims of full-suite reruns on this candidate.

## Corrections

### Navigation cannot invalidate data recovery

The snapshot read's validity is now owned by its abort-controller identity,
independently of the view-selection generation. Same-site navigation updates
the synchronous current selection, but does not cancel or discard the read.
Initial and revalidated snapshots reconcile that latest route/asset/target and
retire derived caches when their site/revision changes. Revalidation applies
its delivered snapshot directly, without another read or waiting for a previous
preview build. A snapshot-supplied preview also warms its route when another
route is selected, so returning Home cannot resurrect A.

Superseding reads, site switches, new-website requests and unmounts retire the
appropriate old lifetimes. Revalidation rejection is observed even before the
initial phase settles; current data-read errors remain reportable after navigation.

### Old navigation builds cannot report late errors

Both cached navigation and snapshot-driven rendering finish through one
selection-guarded path. Preview publication, error notices and asynchronous
loader cleanup check the current selection at the point of publication, rather
than rethrowing into an unguarded outer navigation catch. Obsolete completions
cannot publish, clear a newer loader or remove a replacement pending promise.
Current navigation failures still follow the ordinary error path.

Additional info-panel tests exposed a selection fallback to Home: opening
details alone now preserves the current route/target, while an explicit route
does not inherit a conflicting old page id. The panel's current visibility is
updated synchronously and both navigation paths share the same guarded renderer.
No Shell alias changes, new event type, mutation replay or connectivity UI was added.

## Verification

| Suite | Result |
|---|---|
| Website Studio component | **39 passed**, including both reviewer reproductions and initial/revalidated recovery during multiple warm selections, target preservation, slow initial builds, obsolete/current failures, newer loaders, info-panel navigation, supersession, site switches and teardown |
| Website Studio Chromium visual/runtime | **15 passed**, including four real-App/API/nested-runtime concurrency cases with unchanged/changed build identity and no outer-iframe replacement |
| Website Studio Python | **130 passed, 2 skipped** (132 discovered; existing opt-in live GitHub/Storage integration skips) |
| Base Shell | **216 passed** |
| PWA SDK | **195 passed** |
| Worker/build/browser contracts | **17 passed** |
| Python PWA | **20 passed** |
| Python audit/device-evidence policy | **21 passed** |

**653 passed, 2 skipped**, excluding focused repeats and the separate
authenticated smoke. Website Studio and SDK typechecks, the operational PWA
audit, unused-import checker and whitespace checks passed. The official
frontend build emitted its scoped refresh event. No Node-suite retry was needed.

The two reviewer reproductions first failed against the preceding implementation.
The expanded component suite then reproduced three info-panel cases before
their fix. Existing assertions were retained: the pending-promise ownership
test now explicitly navigates Home rather than relying on recovery incorrectly
forcing that selection. A shared component harness avoids duplicated setup.

The four Chromium recovery tests render the actual App, API/SDK and nested
preview runtime, mocking HTTP responses only. They hold recovery HTTP pending
while selecting a warmed route, verify B in that route and on return Home with
one recovery read, and reject an old build after B is visible. Both same-build
warm navigation and changed-build runtime replacement are covered. The existing
PWA hardening CI job already runs both the component suite and this browser file;
no CI filter changes were necessary.

### Immutable-candidate smoke

To exclude concurrent repository edits, the smoke ran from a **full Git archive
of `724c93e5`**, not the shared source tree. All **3,559 tracked files** in that
archive were compared with their Git blob identities before and after execution.
The Python Core import was verified inside the archive; existing Python and
locked Chat Playwright dependencies were reused. The official smoke runner
created its own disposable Core root, test identity and browser profile.

The smoke passed all 16 Shell precache assets, five approved IndexedDB display
adapters with display transport blocked, mounted-tree continuity, standard
restart/loading, isolated Settings refresh/clear and transparent recovery.
It is separate from the Website Studio UI concurrency tests and is not a
physical-device or rollout/rollback result.

The first archive setup omitted root metadata and stopped at missing
`pyproject.toml`, before browser execution. Exporting the complete candidate
fixed the harness setup; no product code was changed or assertion bypassed.
The prior provider identity startup blocker did not recur. Later concurrent
commits or dirty files are not recertified by this immutable-candidate evidence.

Representative commands (Maverick root unless stated otherwise):

```sh
npm --prefix apps/website-studio test -- --maxWorkers=1
(cd apps/website-studio && ./node_modules/.bin/tsc --noEmit)
PLAYWRIGHT_BROWSERS_PATH=/home/ubuntu/.cache/ms-playwright \
  npm --prefix apps/website-studio run test:visual -- --workers=1
.venv/bin/python -m unittest discover -s apps/website-studio/tests -p 'test_*.py'
npm --prefix apps/base-shell test -- --maxWorkers=1
npm --prefix packages/pwa-cache test -- --maxWorkers=1
npm --prefix packages/pwa-cache run typecheck
npm --prefix apps/base-shell run test:service-worker
.venv/bin/python -m unittest discover -s tests/unit/pwa
.venv/bin/python -m unittest tests.unit.scripts.test_audit_pwa_cache tests.unit.scripts.test_pwa_device_regression
maverick app website-studio frontend build --json
.venv/bin/python scripts/audit_pwa_cache.py
python3 scripts/check_unused_imports.py
```

For the isolated smoke, export the **whole** candidate with `git archive`, link
only the existing Chat `node_modules`, set `PYTHONPATH` to that archive, and run
its `scripts/pwa_shell_cache_smoke.py --app-read-models` from the archive root
using the existing repository Python venv and Chromium installation. Verify the
export's tracked file hashes and ten manifests against the candidate again
after the run. The hosted GitHub job and repository-wide pre-merge suite were
not executed here; this change does not upgrade the existing dev toolchain.

## Open gates and plan synchronization

1. **PWA-098 physical evidence:** all eight profiles in the
   [candidate-bound matrix](pwa_cache_website_concurrency_device_matrix_2026-09-06.json)
   remain pending. The verifier correctly returned **exit 1**; capture and
   redaction review are absent, not simulated or inferred from Chromium.
2. **Controlled rollout:** release-owner approval, prerequisite gates and cohort
   observation windows still need execution on the selected release.
3. **Operational rollback drill:** actual flag/config disable, server-first
   reload and any required durable clear must be exercised and recorded.
   Automated kill-switch coverage does not close this gate.

The Storage-owned plan
`storage/generated/development/maverick-pwa-cache-development-plan.md` was
updated using six guarded exact replacements through
`storage_update_markdown_file`, followed by a full eight-page official reread.
Sections 5.8 and 7.8 now describe the independent lifetimes and identify this
candidate, the new tests and all three unchecked operational gates.

- Previous SHA-256: `8bcfae90ee699fa839af98d4699456d99f1db5db46a6388ff24f43aef6fa092f`.
- New SHA-256: `7af042a2e0fcf116dec63d7a88f8032a0a028a5e36f9a2a9fd8cfec9a66837d6`.
- Verified size: **95,978 UTF-8 bytes**.

New binary changes require a new candidate and fresh evidence. This report does
not mark M6 or the development plan complete.
