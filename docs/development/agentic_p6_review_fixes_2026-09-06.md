# P6 reviewer corrections — 2026-09-06

The two P1 findings are corrected and covered by offline regressions. Overall
P6 certification and release remain **NO-GO**: the full deterministic manifests
still have the inherited continuation/app-audit failures described below, and
no operational certification or release approval was performed.

This is development verification, not trusted provider evidence, a signature,
a certificate, a security approval, or a rollout authorization.

## Checkpoints

| Commit | Correction |
| --- | --- |
| `a594864f` | Persist exact API targets in certificate/evidence; enforce projection, admission, full validation and fast refresh |
| `926658f7` | Google preflight before every transport; observed catalog/revision-bound receipts |
| `36d34a6b` | Bring the isolated reasoning fixture up to the certificate shape, without weakening validation |
| `728c33e0` | Unique session ownership for concurrent cold shell/process behavior probes |
| `42dfe298` | Preserve one detached hosted launcher/child termination group and terminal isolation |
| `68ea1d72` | Complete group escalation after launcher exit; keep stale/reaped handles out of PID-based signal authority |

### P1: certification cannot move to a new API tuple

Certificate schema 7 persists `certification_target_digest` in both certificate
and digest-bound evidence. Status projection and admission compare the full
immutable profile (except publication time). Full binding validation and fast
authority refresh load the exact pinned definition and check its target and
actual policy/context/config snapshots. New revisions, enlarged step/tool/cost
ceilings, context changes, and provider/model changes cannot reuse a certificate.
Workspace governance may still narrow the certified ceiling.

The regression matrix covers both Google and OpenRouter, including actual
publisher fixtures followed by publication of an uncertified revised profile.
Targetless historical API certificates fail closed; no target is backfilled.
The API-only extension omits empty targets from the native evidence hash domain,
preserving Codex evidence and connection attestations without rewriting them.

### P1: Google must observe the live catalog before transport

The operator runner delegates to the probe's mandatory production preflight.
Each of the two tool rounds and finalization first verifies the exact request
against the official OpenAPI and authenticated model record. Receipts contain
three catalog snapshots with observed API/model revision, capacity and
capability metadata, endpoint/model digests and canonical snapshot digests.
The observations bind the result summary and the derived exact target.
Missing/incompatible catalogs and mid-run drift fail before the next transport.

The real-codec/simulated-transport regression observes six catalog fetches before
three requests. Negative cases observe zero completion requests; last-round
preflight failures cannot be hidden by previous successful rounds. Rehashed
catalog-free, relabelled, partial or mixed-snapshot receipts remain ineligible.
All provider responses/catalogs in these tests are fixtures, not live evidence.

### Investigation of intermittent Full Workspace failures

Cold diagnostics exposed missing `core-capability:process.interrupt` evidence.
Two defect families were reproduced rather than hidden by retries:

1. **Shared probe session ID.** A deterministic two-thread regression pauses one
   real probe before interrupt, lets another complete its session cleanup, then
   resumes the first. Previously that cleanup killed the other probe's worker.
   Every invocation now owns a unique session ID.
2. **Incomplete Bubblewrap group termination.** Stress still found an undrained pipe
   after the first correction. Diagnostics observed a terminated launcher and
   a live marked Bubblewrap/shell subtree in a different process group. Both
   hosted launch sites already detach via `Popen(start_new_session=True)`;
   removing their redundant inner `--new-session` keeps descendants in that
   termination group. New real-process tests assert one detached session/group,
   no controlling terminal, and no marked worker surviving interrupt.
   That scope correction alone was insufficient: a subsequent 300-iteration
   stress still found 15 missing interrupt observations. A TERM-ignoring child
   reproduces the remaining problem: launcher exit was incorrectly treated as
   group quiescence. `68ea1d72` shares a hosted-only bounded termination helper
   across cancellation, output timeout and managed-process interruption; it
   escalates the active owned group even after SIGTERM exits the leader. Reaped
   handles at entry cannot signal potentially reused numeric IDs. The native
   process-control artifact and session-scoped orphan fallback are unchanged.

Neither fix relaxes result admission, caches failed evidence, retries failed
proofs, or changes the native Codex sandbox/shared process-control artifact.
The exact reviewer 45-test command was not supplied; the reproductions and
order checks below are explicitly separate from that original run.

## Exact-source verification

Frozen code: `68ea1d72e785b0c9ae7fdf9d276f1defd486ed27` in a clean detached checkout,
not the concurrently edited primary working tree. Both complete code-owned
`fixture_contract` commands ran sequentially, without removing failed modules,
selecting live steps, or signing their outputs. Source, clean status and TCB
identity remained unchanged before/after both runs.

| Check | Result |
| --- | --- |
| Focused mixed group, forward order | 96/96 passed; no incomplete-contract observation |
| Same group, reversed module order | 96/96 passed; no incomplete-contract observation |
| Google profile module alone | 3/3 passed |
| Entire behavior gate, cold caches | 50/50 complete |
| Shell/process behavior, uncached | 300/300 complete |
| Complete Google suite 40 | 620 tests; 12 failures, 5 errors |
| Complete OpenRouter suite 40 | 629 tests; 12 failures, 5 errors |
| Repository unused-import check | Passed |

All final full-suite failure cases exactly match the prior frozen baseline
`c58a38f5eb17e8fed6aafb6cae653ca44790c01b`. They are confined to:

- `tests.unit.recovery.test_continuation_fork`: the historical fixture changes
  Codex adapter/evidence identity while retaining the current native connection
  reference; the P5 validator correctly rejects the inconsistent pair.
- `tests.integration.cli_mcp.test_builtin_surface_effects`: the existing App Store
  descriptor audit mismatch; executable app-effect audit renewal remains a
  separate reviewed operation, not an automatic hash refresh.

No additional failing test case appears in the final reruns. The first review
checkout (`926658f7`) additionally exposed a reasoning-only `SimpleNamespace` fixture
missing the certificate's family/target defaults; `36d34a6b` corrected it and
its full module passed 12/12 before the final complete reruns.

The adjacent JSON records exact commands, manifest/TCB/source identities,
diagnostic module order, failure cases, timestamps and log hashes. Metadata
SHA-256: `e42e598226267960e32621fe81f2be7e8be7ea63d74678f3f5a32f1842a73462`. Retained development logs are in
`/tmp/maverick-p6-review-final.ARp9R8/`; the initial review logs are in
`/tmp/maverick-p6-review.PaI6dA/`. Neither directory is operational evidence.

## Codex and operational boundary

- Codex baseline revision observed during this review is **14**; source artifact
  remains
  `33b483337b160ba8281b3ad17176030905ee0b83f2067d5eee911ef6517eab55`.
- The authenticated provider-list surface reported Codex **active** during this
  review. The final read returned `authentication_required`, so current live
  readiness could not be reconfirmed. No credential was replaced or auth
  boundary bypassed; this is not a reported Codex certificate revocation.
- No live certificate/evidence/profile/binding writes, artifact approvals,
  workspace classification, backend restart, provider certification run,
  remote activation, canary, rollback apply, or push was performed. Other agents'
  changes were preserved and not included in the checkpoints.
- `REMOTE_AGENTIC_ATTESTATION_AVAILABLE` remains false. Fixing the two P1s does
  not close the inherited deterministic failures, natural/live evidence,
  trusted-signer, independent security review, canary and explicit release gates.
- Before any live schema-7 control-plane write, deploy/restart the backend on
  the reviewed source and verify health, as required by the working agreement.
