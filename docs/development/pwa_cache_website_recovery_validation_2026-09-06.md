# PWA cache — Website Studio recovery follow-up, 2026-09-06

> Historical report for `e2466671`. A subsequent review reproduced navigation
> during recovery and late navigation-build errors that this checkpoint did not
> cover. The [concurrency follow-up](pwa_cache_website_concurrency_validation_2026-09-06.md)
> records their corrections and the new `724c93e5` candidate; the evidence and
> counts below are retained for their original candidate, not the current release.

## Verdict and candidate

**The reported Website Studio P2 is corrected and regression-tested. M6 remains
open:** physical PWA-098, controlled rollout and an operational rollback drill
are still unexecuted. No shared/live flags changed; no shared backend restart
was necessary. Other agents' source and architecture work was not staged.

- Implementation: `3ac1baa2` — snapshot-bound derived previews, pending-request
  ownership, visible details refresh and obsolete-error isolation.
- Code/assets candidate: **`e24666714aee83ec50753711f1a17b959702d391`** (`design`).
- CI checkpoint: `df5eafeb` adds the component and real-preview Chromium
  regressions to the PWA hardening job. CI/documentation commits after the
  candidate do not change its app/Core/SDK/smoke implementation or binaries.
- [Ten exact manifest identities](pwa_cache_website_recovery_candidate_2026-09-06.json)
  bind the captured smoke's SHA-256. Website Studio was officially rebuilt:
  `52dffe0a914ae986c56ab4a030d0dbb02e31fa418b4ade58a384710ae973d82e`.
  The other nine manifests, including Shell and Chat, are unchanged from
  `fb6e7145`; all ten match the selected Git candidate byte-for-byte.
- [Fresh authenticated Chromium smoke](pwa_cache_website_recovery_chromium_2026-09-06.json):
  `2026-09-06T10:30:48.203Z`, actual Shell build
  `84699ab3435c079dbb87461c448bb3f805c2d1edec5245780ccc05246cf8cf4b`.

The [previous review report](pwa_cache_review_validation_2026-09-06.md) and its
1,361 tests remain historical evidence for `fb6e7145`, not a claim that those
entire suites were all rerun on this follow-up. The original `1e095087`
candidate is historical too.

## Recovery correction

Shell's alias order is unchanged. Aliases trigger rereads; they cannot describe
all changes missed during disconnection. Website Studio now binds both its
resolved-preview map and pending-build map to the accepted snapshot's site and
content revision. A changed snapshot retires both maps before rendering,
including a snapshot reread after background revalidation with no new event.
Unchanged revisions retain warm route reuse. A compatible snapshot-supplied
preview takes precedence over RAM even in the same cache generation.

The existing refresh-generation guard runs before invalidation and publication.
A late build removes only its own pending promise, never a replacement request.
Two nearby recovery defects exposed by the broader component/browser checks
were also corrected: the open info panel now rereads status/history using its
current visibility, and obsolete refresh errors/teardown cancellations cannot
leave an error notice over the recovered UI. Current-read errors still surface.
No mutation replay, new event type, alias workaround or connectivity UI was added.

## Verification

| Suite | Result |
|---|---|
| Website Studio component | **20 passed**: every declared alias, changed/unchanged revisions, snapshot precedence, warmed routes, revalidation, late reads/builds, visible details, errors and sender rejection |
| Website Studio Chromium visual/runtime | **13 passed**, including two new real-App/API/nested-runtime A→B recoveries with unchanged/changed build identity and no outer-iframe replacement |
| Website Studio Python | **130 passed, 2 skipped** (132 discovered; existing environment-dependent skips) |
| Base Shell | **216 passed**, including actual socket reconnection producing Website Studio `records` without app-frame remount |
| PWA SDK | **195 passed**, typecheck passed |
| Worker/build/browser contracts | **17 passed**, including real metrics reload and physical localStorage pruning |
| Python PWA | **20 passed** |
| Python audit/device-evidence policy | **21 passed** |

**632 passed, 2 skipped**, excluding focused repeats and the separate
authenticated smoke. Website Studio TypeScript, the operational PWA audit,
unused-import checker and whitespace checks passed. The official frontend
build completed and emitted the scoped frontend-refresh event.

The new component tests first reproduced stale A (including `records` and
background revalidation), retired-request reuse and stale error/info state.
The two new browser tests render actual app/SDK/runtime code with simulated
HTTP snapshots/documents. The unmodified runtime HTML is served at Core's
directory URL because Vite's development SPA fallback does not resolve that
directory to its public `index.html`. They assert visible nested document B,
recovered warmed routes and the unchanged outer iframe, not just an API count.
The existing visual harness was aligned with the document-ready contract,
single event delivery and a missing mock-state binding; navigation timing now
starts after the initial document is ready. No production assertion was relaxed.

The fresh authenticated smoke uses a disposable Core root and persistent
Chromium profile. It verifies 16 precache assets, all five approved display
adapters in IndexedDB with warm paint under blocked display transport,
preserved mounted UI during transport loss, and isolated Settings refresh,
clear and recovery. This smoke does not replace the separate Website Studio
component/runtime regressions or physical-device evidence. At the post-smoke
check, App/Core/SDK/smoke files had no working-tree differences from the
candidate. The prior provider startup blocker did not recur. Subsequent
concurrent provider/runtime edits are not included in this candidate or
recertified by this evidence; the current dirty working tree is not a release.

Representative commands (root unless specified):

```sh
npm --prefix apps/website-studio test -- --maxWorkers=1
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
.venv/bin/python scripts/pwa_shell_cache_smoke.py --app-read-models
```

Limitations: the hosted GitHub job and repository-wide pre-merge suite were not
executed here. Installing the app-owned test runner reported four pre-existing
development-toolchain advisories (browserslist, esbuild, nanoid, postcss); their
locked versions are unchanged. No unrelated dependency upgrades were applied.

## Open release gates

1. **PWA-098:** all eight profiles in the
   [candidate-bound physical matrix](pwa_cache_website_recovery_device_matrix_2026-09-06.json)
   remain pending, without capture/redaction approval. The verifier correctly
   returned **exit 1**, not a physical pass.
2. **Controlled rollout:** release owner approval, gates-off baseline and
   cohort observation windows must still be executed against this candidate.
3. **Operational rollback drill:** record actual flag/config disable, reload
   and server-first reads; if removal is required, verify durable clear and no
   late republication. Automated kill-switch tests do not satisfy this gate.

Any later binary change requires a new candidate and fresh evidence. The plan
must not be marked complete until all three operational gates are recorded.

## Storage-owned plan synchronization

`storage/generated/development/maverick-pwa-cache-development-plan.md` was
updated through `storage_update_markdown_file` with six guarded exact
replacements. Previous SHA-256:
`9f15092ab50418891e022de0500707bda2f68331072eb2fd0507dfb48a1d11e2`.
New SHA-256:
`8bcfae90ee699fa839af98d4699456d99f1db5db46a6388ff24f43aef6fa092f`.
An official reread followed all eight pages and verified the complete
**94,249 UTF-8 bytes** against that hash. Sections 5.8 and 7.8 now cover derived
cache recovery, identify this candidate and preserve all three unchecked
operational gates. Earlier evidence remains explicitly historical.
