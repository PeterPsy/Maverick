# PWA cache — approved app completion candidate, 2026-09-05

> Historical checkpoint. The four subsequent review corrections, rebuilt
> candidate and current evidence are recorded in
> [the 2026-09-06 validation](pwa_cache_review_validation_2026-09-06.md).
> Do not reuse this older candidate's evidence for changed binaries.

## Verdict and candidate

**The approved M5 application code is implemented and the pertinent automated
checks pass. The release plan is not closed.** Physical PWA-098 and a controlled
rollout/rollback drill remain unexecuted. The shared backend deployment also
needs the authenticated restart described below; the smoke used a fresh,
disposable Core process. No production or shared-workspace cache flags changed.

Exact code/build candidate: **`1e09508744c96f2929d5015ec3d91bddd274dc3c`** on
`design`. Documentation-only commits after that candidate do not identify a new
binary. The nine complete manifest build identities are recorded in
[pwa_cache_completion_candidate_2026-09-05.json](pwa_cache_completion_candidate_2026-09-05.json).
All app sources, including CRM and Mail, resolve to root `apps/`, not the old
workspace-local forks. Other agents' work was preserved; the unrelated
`docs/architecture/core_architecture.md` working-tree change was not staged.

This implements the full decision in
[the product approval](../product/pwa_cache_completion_decision_2026-09-05.md)
(`a61b11d9`), not the rejected RAM-only or CRM/Mail-excluded proposal.

## Implementation checkpoints

| Commit | Work |
|---|---|
| `e729902b`, `b8311de7` | Earlier remaining reviewer fixes: durable primary publication authority across RAM→IndexedDB recovery; private read retry telemetry without loader replay |
| `18950fe1` | Fixed allowlisted conditional read requests, closed projection schemas, stable opaque parameter identity and shared read helper |
| `18f0f369` | Calendar bounded persistent display models and sanitized Fitness persistence |
| `4e06d831` | CRM/Mail approved projections and real UI integration |
| `1d324197` | Chat projects/threads/completed display history; provider-independent read path; no persistent sends; resource-scoped maintenance fences |
| `322bb2d8` | Revalidation/cancellation corrections and retirement of unscoped legacy seeds |
| `84abebe9` | Real isolated-app persistent browser smoke and populated CRM/Mail regressions |
| `d652356f` | Website Studio deletes every unscoped snapshot without reading/importing it; obsolete migration revision removed |
| `1e095087` | Nine official frontend builds, exact candidate |

## Per-app implementation and constraints

All approved persistent resources remain subordinate to host-scoped user,
workspace and app identity, policy/schema revision, access lease, quota, TTL,
budgets and feature gates. Stale-but-unexpired display does not grant authority.
The policy values and limits are normative in the
[resource inventory](../product/pwa_cache_resource_inventory.v2.json) and
[M5 runbook](../runbooks/pwa_data_cache_m5.md).

| App | Implemented state |
|---|---|
| Calendar | Persistent normalized overlapping event windows (at most 93 days), paginated reads and consulted details. Cached events do not await live connections/preferences/calendar authority. Date/detail cancellation and revalidation update the normal view. Operational access roles and OAuth state excluded. |
| Chat | Persistent paginated project display, recent thread metadata and completed user/assistant messages (50 turns, 5,000 source-event ceiling). Display history loads alongside the authoritative runtime connection, never restoring active session/turn or admission from cache. Provider/tool/active-stream state excluded. Old project/transcript/send namespaces are purged; queued sends are document RAM only, cleared on teardown, never replayed after reload. |
| CRM | Persistent recent lists, records, schema, pipelines and searched/consulted record projections. A closed app-owned JSON schema is shared by backend/frontend/host. Structured tags and actual search envelopes are covered by populated fixtures. Workflow proposals, admission and action authority are not persisted. |
| Mail | Persistent non-secret mailbox/folder display, recent headers/snippets, consulted thread/message plain-text bodies and attachment metadata. Thread reads do not wait for mailbox metadata. Active HTML, provider headers/locators, OAuth credentials, attachment bytes and send state are excluded; live rich rendering remains a separate enhancement. |
| Fitness Coach | Persistent closed sanitized bootstrap and bounded thumbnails. Old browser bootstrap/thumbnail storage is deleted without import. Only current scoped capture may seed thumbnail persistence; no parallel legacy writer. |
| Website Studio | Existing scoped conditional snapshot pilot retained. Old site/route-only snapshots cannot establish user/workspace provenance and are deleted without reading. Stable server SHA-256 only; RAM single-flight remains. |
| Storage | Existing scoped catalog pilot and exact file/version policy preserved. File bytes still require their own classification/approval and OPFS checks; app-level customer-data approval does not bypass them. |
| App Store | Existing revisioned catalog pilot retained. Cached catalog does not enable install, launch, assignment or publication authority. |

The fixed POST display reads explicitly request **no app secrets**. The SDK
retries only immutable reviewed reads, not arbitrary app loaders. The host's
private telemetry channel accounts for child retry waits, retries and duration
without accepting child-controlled identifiers/durations or payload content.

A browser-discovered publication issue was also fixed: unrelated resource
initialization no longer advances a global maintenance epoch and suppresses
another app's valid pending write. Resource maintenance epochs use opaque
SHA-256 scope keys; explicit cleanup retains its broad durable fence, including
writers admitted before RAM→IndexedDB recovery. Same-resource maintenance still
invalidates the old writer. Independent-context cleanup regressions stay green.

## Automated verification

Pertinent suites run during this completion pass (focused reruns are not added
again to these suite counts):

| Suite | Result |
|---|---|
| PWA SDK | 180 passed, 22 files; TypeScript passed |
| Base Shell | 204 passed, 36 files, including 22 real-broker tests |
| Chat frontend | 615 passed, 90 files |
| Calendar frontend | 35 passed, 5 files |
| Fitness frontend | 85 passed, 14 files |
| Storage frontend | 134 passed, 28 files |
| Settings cache diagnostics | 2 passed |
| Worker/build/cross-origin contract suite | 16 passed |
| App Store content-hash suite | 5 passed |
| Calendar Python | 66 passed |
| CRM Python | 67 passed |
| Mail Python | 107 passed |
| Website Studio Python | 114 passed |
| Chat Python | 35 run: 33 passed, 2 skipped |
| Focused PWA Python, including populated CRM/Mail and Chat API projection | 20 passed |
| Audit and physical-evidence-policy Python | 21 passed |

Operational PWA audit, unused-import checker and `git diff --check` passed.
Nine official `maverick app <id> frontend build --json` builds passed and emitted
scoped refresh events: Calendar, Chat, CRM, Mail, Fitness, Storage, Website
Studio, App Store and Base Shell. The eight TypeScript app build pipelines run
`tsc --noEmit`; App Store uses its JavaScript build/content-hash checks. Website
Studio retains its pre-existing revalidated-asset manifest policy (zero
immutable entries), rather than claiming every app has the same asset policy.

Representative reproducible commands, from the root repository:

```sh
npm --prefix packages/pwa-cache test -- --maxWorkers=2
npm --prefix packages/pwa-cache run typecheck
npm --prefix apps/base-shell test -- --maxWorkers=2
npm --prefix apps/base-shell run test:service-worker
# Same bounded Vitest invocation for chat/calendar/fitness-coach/storage/settings.
npm --prefix apps/app-store run test:content-hash
.venv/bin/python -m unittest discover -s tests/unit/pwa
.venv/bin/python -m unittest tests.unit.scripts.test_audit_pwa_cache tests.unit.scripts.test_pwa_device_regression
# App-owned Python discovery for calendar/chat/crm/mail/website-studio.
.venv/bin/python scripts/audit_pwa_cache.py
python3 scripts/check_unused_imports.py
.venv/bin/python scripts/pwa_shell_cache_smoke.py --app-read-models
```

The complete root pre-merge suite and every app's independent visual/E2E suite
were not run. The checks above are the pertinent completion suites, not a claim
of exhaustive cross-browser or all-product validation.

### Exact-candidate Chromium smoke

[Captured automated result](pwa_cache_completion_chromium_2026-09-05.json):
`2026-09-05T21:15:03.167Z`, shell build
`bf012577bbd4aca5b6a41e70ff166f43bd2189e1d538e2a7584a0d28e46a07c3`.

The runner uses a disposable Core root and persistent Chromium profile, enables
only its child-process test flags, and refuses app-persistence testing against
a supplied live base URL. It verifies an actual IndexedDB entry for each of
Calendar/Chat/CRM/Mail/Fitness, blocks that app's display HTTP requests, reopens
the isolated app, and observes initial broker delivery from cache with its
normal active frame mounted. It also verifies 16 shell precache assets,
transport-loss continuity, ordinary loading after a disconnected restart,
excluded dynamic requests, isolated Settings refresh/clear and recovery.

This is real browser storage and broker/UI wiring evidence, not a pixel-level
assertion of every populated screen. Populated CRM/Mail, sanitizer,
conditional unchanged/changed, pagination, expiry, cancellation, authorization,
cleanup and telemetry paths additionally have focused regressions. No physical
Safari, Home Screen, Dock or installed-device matrix run is inferred from it.

## Plan update and shared deployment handoff

The workspace plan was changed through Storage's guarded Markdown API: 18 exact
replacements, expected prior SHA-256
`8238056a4c17d40fafca8fd3c4c60e88fb7c285430590b89f56e260cef045205`, resulting SHA-256
`e8ce23ffe461f08bd696e1f0061c706412c7cb9c4079f848c787c5a21ec5e904`.
M5/M6 now distinguish implemented application code, automated checks, physical
validation and rollout. CRM/Mail are not left pending a generic privacy decision.

After the successful update, the official Storage reread and Core recovery
inspection returned `authentication_required`. A **read-only filesystem
fallback** verified the entire updated Markdown byte-for-byte against the
expected replacement result and SHA-256. No direct workspace document write was
used. The shared Core process still reports `/health` 200 but was started before
the new Chat display projection; health alone does not prove it loaded new code.

An authenticated operator must run the previously discovered official
`core.recovery.restart_backend` command, verify health and confirm the mounted
Chat display projection, without changing rollout flags. The fresh disposable
smoke host already exercised the new source. No authentication bypass or guessed
service-manager restart was attempted. This is a concrete deployment handoff,
not missing adapter code.

## Physical and controlled-rollout checklist — not executed

1. **Candidate binding:** deploy exactly the commit and manifest IDs above. If
   code or assets change, select a new candidate and regenerate its evidence;
   do not reuse this matrix for a different release tag/commit.
2. **Physical PWA-098:** fill
   [the candidate-bound matrix](pwa_cache_completion_device_matrix_2026-09-05.json)
   on all eight policy profiles (minimum/current macOS Safari, Dock,
   minimum/current iOS/iPadOS Safari, iPhone Home Screen, desktop Chrome/Edge and
   desktop installed Chrome). Record actual OS/browser versions, timestamp,
   redaction review and each scenario: cold/warm launch, worker update/recovery,
   quota pressure, intermittent network, logout/workspace cleanup, plus each
   profile's extra storage/lifecycle scenarios. Include changed-data refresh,
   two-context cleanup during a paused writer and bounded app display checks.
3. **Evidence validation:** run the command below only after physical execution.
   The supplied template is intentionally pending and the verifier currently
   **rejects** it (no timestamp, no redaction approval, non-passing scenarios).
   That expected rejection is not a physical pass.
4. **Baseline and safety:** release owner records an observation window and
   acceptance thresholds, verifies server-first behavior with gates off and
   captures aggregate hit/miss/stale/expired, quota/eviction, pending waits,
   retry counts and durations. Induce one validated transient app read: pending
   must rise, recovery must record retry and duration, cancellation must drain.
   Never collect user IDs, payloads, message subjects or request URLs as evidence.
5. **Controlled rollout:** after device/release gates, use the
   [M6 runbook](../runbooks/pwa_cache_operations_m6.md) for one resource at a time,
   with fixed salted cohort identity and explicit observation windows at
   1%, 5%, 25%, 50%, then 100%. No cohort was activated in this task. Storage file
   approval and file-cache flags remain independent.
6. **Rollback drill:** disable the affected per-app gate (or cohort percentage
   zero), restart through the official deployment surface if needed, reload,
   verify ordinary server-first loading/reads. For removal, use Settings Clear
   cache and require durable completion; verify no late cross-context writer
   republishes data. Record aggregate results and promote only after approval.

```sh
python3 scripts/pwa_device_regression.py verify \
  --input docs/development/pwa_cache_completion_device_matrix_2026-09-05.json \
  --expected-release-id 1e09508744c96f2929d5015ec3d91bddd274dc3c
```

**Remaining concrete gates:** authenticated shared-backend restart/deployment,
physical candidate-bound evidence, and controlled cohort/rollback execution.
The full release plan is not declared complete while these remain outstanding.
