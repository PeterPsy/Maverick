# P6 deterministic closeout — 2026-09-06

**P6-D: PASS on `5a7ca45af4c10879e7f95c89d31fba6fa0eaea1d`.**
**Overall P6 and remote release: NO-GO.** Live/natural evidence, trusted
signing and independent approval, scoped canary, rollback and cleanup have
not been completed. This report does not certify or enable a provider.

The complete unsigned machine record is
[`agentic_p6_deterministic_closeout_2026-09-06.json`](agentic_p6_deterministic_closeout_2026-09-06.json).
Raw stdout/stderr are retained under `evidence/agentic_p6_2026-09-06/`, with
SHA-256 hashes and full manifest commands in that record. They are development
evidence, not an immutable platform evidence allocation or a signed run.

## Checkpoints

| Commit | Change |
| --- | --- |
| `f29d5114` | Exact-target offline API continuation fixtures; dedicated rejection of reused native connection authority; no native validator changes |
| `a09e22dd` | Source-reviewed effect audit renewal for ten app/surface pairs, with executable regressions |
| `5a7ca45a` | Frozen candidate: hosted adapter 37, recipes 24, Google/OpenRouter profiles 46/45, suite 41, TCB 31 |

The user-authorized plan addendum was written through Storage using an exact
SHA fence, not a direct workspace-file write. Plan SHA-256:
`0c8796ded071189b315982cd17596f001e02062c550c3be3f57b203f920069e9`.
Its section 16 separates D/L/S/R without waiving the original release gates.

## Verification

Both canonical fixture manifests ran sequentially in a clean detached checkout
of the frozen commit, outside the shared working tree. Their exact commands
are retained; the live step was not selected, explicit live opt-in was `0`
and the probe budget was `0`. No provider generation credential was supplied
by this task and no live probe or signing command was run.

| Suite | Executed | Failures | Errors | Skips | Exit |
| --- | ---: | ---: | ---: | ---: | ---: |
| Google suite 41 | 635 | 0 | 0 | 0 | 0 |
| OpenRouter suite 41 | 644 | 0 | 0 | 0 | 0 |

The production fixture-receipt validator accepted both unittest footers.
Expected argparse errors printed by negative runner tests are not suite
failures. Source commit, clean-checkout status and live TCB identity were
checked again after each manifest and remained unchanged.
OpenRouter stdout includes a mocked probe receipt printed by its runner test
(synthetic catalog digests and an empty nonce). It is not an observed live
receipt and is not eligible for certification.

The previous 12 failures and 5 errors per provider are resolved, not waived.
No module was removed from the suite-40 manifests. Four modules were added:
continuation repair, multi-hop, native identity rejection and the effect-audit
delta. This adds 15 tests to each previous complete manifest (620/629).

Focused development checks also passed: 31 recovery/target tests, one
subsequent non-default-binding fixture check, 14 effect-audit/TCB tests, and
the version/manifest assertions after updating their explicit identity pins.
The full runs above supersede those focused checks. `check_unused_imports.py`
and scoped `git diff --check` passed. The fixer's earlier 300-iteration stress
run was not repeated and is not relabelled as evidence for this commit.

## Identity and Codex preservation

- TCB structure: `1c39b86bc8791b7075f2353657e2c8048cbee616f2eb93ac279e21bcd781dc11`.
- TCB live bytes: `f3b98048eb8c7a1a1a419156cd1052271108fd2c272c6026bc604217add896e6`.
- Codex revision 14 artifact: `33b483337b160ba8281b3ad17176030905ee0b83f2067d5eee911ef6517eab55`, unchanged from the reviewed baseline.

Official read-only `core.providers.list` observations are recorded separately
in the JSON record. They are provider-status observations, not a new native
certificate or a production-safety attestation. No backend restart, certificate
publication/revocation, binding enablement, workspace attestation/classification
issue, or live runtime migration was performed. Other agents' commits and the
pre-existing unrelated Core architecture edit were preserved.

The report/documentation commits following the frozen source are not claimed
to have run these suites themselves. Certification must use the exact clean
source it actually executes, not substitute a later branch tip.

## Remaining operational work — not waived

1. **Trusted laboratory execution boundary.** Normal remote creation, queue
   and dispatch are still contained. The offline fixture's stub is not a live
   worker, and flipping `REMOTE_AGENTIC_ATTESTATION_AVAILABLE` alone is not an
   approved canary path. Approve and verify the scoped certification/admission
   path in an isolated deployment before natural execution; do not borrow the
   current workspace or manufacture release authority from fixture records.
2. **Operator inputs.** Select authorized synthetic credential/connection
   references, per-provider and overall cost ceilings, an already-trusted
   signer, independent reviewer(s) and the platform evidence destination.
   No key should be pasted into chat or auto-added to the trust set.
3. **P6-L.** On the exact source/target, execute the operator synthetic probe
   and all 14 natural scenarios at every claimed reasoning effort. Retain the
   actual private traces, semantic/effect evidence and resource accounting.
   Mock/fixture receipts cannot fill missing observations.
4. **P6-S.** Review the retained traces and relevant security boundary
   independently, sign the complete evidence, and publish only the matching
   tuple. Gemini CLI remains an uncertified candidate; native release also
   requires an approved runtime artifact and connection-scoped evidence.
5. **P6-R.** In a new disposable synthetic workspace, scope one profile to one
   actor, execute Full Workspace canary and actual kill-switch/rollback/cleanup
   rehearsals, then decide promotion from observations. General production
   security blockers remain independent and binding.

If code, TCB, recipe, profile, catalog or deployable source changes while these
steps are prepared, re-freeze and rerun the affected gates. A NO-GO decision or
this deterministic checkpoint alone does not complete P6.
