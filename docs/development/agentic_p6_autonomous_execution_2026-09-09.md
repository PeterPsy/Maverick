# P6 autonomous execution record — 2026-09-09

## Decision

Candidate 48 is **NO-GO**. The autonomous mandate removed organizational
approval dependencies but did not waive live protocol, natural evidence,
review, signing, canary, rollback, or zero-tolerance gates. Mandatory live
protocol collection failed, so the run stopped before promotion.

The Storage-owned normative plan now records this outcome in section 22. Its
SHA-256 is
`1ac15097561a06e19138167e12337a0f3772cbb025fc050d74659b2de4eea7a2`.

## Authorization and source identity

- autonomous authorization reference:
  `4293898a4d2e84e39874a28623ada259370d856ef5ece63772f631afc7a0bd92`;
- deployed and frozen certification source:
  `b5aa07dd1b83bf179ae8766c0f74293dfb087473`;
- suite 48, certified execution TCB manifest 38;
- TCB structure digest:
  `50ee47c3bf14ee097a6b7baf73c826f0496c70293a1ea7c8057215d5fd05ac50`;
- TCB live digest:
  `8ab58cfd3e263a7a666af9ae1f708b3f8352efae0bf7603ac4d4ce697d1479e5`.

Before this closeout documentation change, the checkout advanced after deploy
only through `docs/architecture/mac_local_runtime.md`. The certification ran
from a clean, detached worktree at the frozen source commit. This closeout also
changes documentation outside the TCB; no runtime or TCB source drift was
accepted.

## Live gate results

The fixture contract completed before each failed live step:

| Target | Fixture | Live step | Result |
| --- | ---: | --- | --- |
| Google AI Studio | 682 passed, zero skip | `live-synthetic-probe` | failed |
| OpenRouter | 692 passed, zero skip | `live-synthetic-probe` | failed |
| Antigravity CLI | 651 passed, zero skip | `live-native-smoke` | failed |

The successor ledger is durably halted with
`provider_transport_error` for both ledger providers. Google records three
requests/reservations in total, including one inherited, and a cumulative
list-price reservation of 134152 microusd under free-tier-only authority.
OpenRouter records four requests/reservations in total, including one
inherited, and 2529 microusd reserved. No request was retried after halt.

No complete signed collection was created. Consequently:

- the 14 natural scenarios were not eligible to run;
- `autonomous_post_evidence_review` was not eligible to run;
- no trusted signer was used and no certificate was published;
- no disposable canary or rollback rehearsal was started;
- no remote provider flag, Native provider, or workspace binding was enabled.

## Rollback and Codex preservation

There was no cutover to undo. The final containment check proves that all
remote agentic flags are false, enabled remote bindings are zero, and
Antigravity CLI remains `disabled`.

Codex remained usable throughout the backend restart and closeout:

- revision 15;
- active root certificate `native-connection:codex:codex:15`;
- eight active valid model projections;
- declared and observed artifact digest
  `8c3d7649dfc948d72602da7390915b2d64219bb229ca87122eef0b7803598b12`;
- focused rollout suite: 8/8 passed.

Codex was not migrated, reissued, disabled, or recertified.

## Operational cleanup and security finding

Diagnostic fixture subprocesses inherited production control-store variables.
The resulting records were limited to identifiers containing
`offline-continuation`, `operator-fixture`, or `fake-agentic-contract`.
Fourteen records were deleted through the persistent collection adapters; one
fixture provider definition later rewritten by a stale collection writer was
deleted again. The final inventory contains no matching marker and no enabled
remote binding.

A separate check confirmed that the persisted `admin` credential accepted the
weak value `maverick`. It was replaced with a random recovery credential through
the operator command dispatcher, all 116 existing admin sessions were revoked,
and the weak HTTP login now returns 401. The replacement plaintext is not in
the repository or evidence record.

Before any future live authorization, the collector must ensure that fixture
contract subprocesses cannot inherit production control-store or live-secret
variables. It should also retain a bounded, redaction-safe failed-step artifact;
the current collector preserves the durable ledger halt and failed stage but
not provider failure output.

## Authoritative evidence

The private final record is:

`/var/tmp/maverick/maverick-p6-autonomous-r48-68zsX93m/autonomous-execution-final.json`

SHA-256:

`24f38befc518f4097267eb3c8fd0d7f5665d37d64070e802aa182e203e4506d0`

It contains redaction-safe references to authorization, deployment, ledger,
cleanup, credential remediation, rollback, Codex certificate validation, and
test artifacts. It closes this autonomous mandate with NO-GO; it does not
close P6's Definition of Done and does not authorize reuse of halted ledgers.
