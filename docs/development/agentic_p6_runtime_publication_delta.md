# P6 runtime admission and publication delta

This delta implements review corrections, not P6-L/S/R approval. The prior
P6-D evidence describes commit `5a7ca45a`; it does not certify these new bytes.
No production availability constant is enabled, provider request made, trusted
operator key created, workspace reclassified, or production certificate issued
by this development work.

## Runtime and native boundary

Workspace stores are explicit server dependencies through profile resolution,
pinning, enablement, session/child creation, continuation, queueing, provider
start and hosted runtime composition. Every admission resolves current
attestation state again. A supplied earlier snapshot cannot override the store;
missing, revoked, changed-workspace and unreadable authority fail closed.
Queueing also fences persisted owner and exact pin, not only workspace/status.
Hosted full/cheap transport authority checks re-enter the same admission gate.

Gemini CLI uses the exact native connection identity (`gemini-cli`,
`gemini-cli-acp`, `google`, ACP), its own default-off flag and a separate closed
release barrier. `google` is not added to the API provider allowlist. Neither
Google API certification nor an API preview flag admits a native connection.

## Explicit Codex shared-source review

Codex revision 14 remains recorded with digest
`33b483337b160ba8281b3ad17176030905ee0b83f2067d5eee911ef6517eab55`.
The new revision 15 identifies the common coda/handoff delta; no path is removed
from `CodexProviderAdapter.artifact_components`. The source review scope is:

- handoff forwards a server-owned workspace store to the existing guards;
- exact local Codex still short-circuits remote admission;
- queueing rejects a stale owner or execution pin as well as a stale workspace;
- locks, provider-state checks, acceptance/release callbacks, transport, native
  sandbox, process control, model catalog and reasoning are not relaxed.

Revision 15's digest is
`a8d11f6cd051c39ab87b3453d6579c79ac8509c5e892018c4564abaac2bc4958`.
This is a development source review and explicit identity update, not an
independent operational release review. Old pins are not rewritten or assigned
this new identity. Required local regressions and independent final-candidate
review must be recorded separately; old deterministic/live receipts are stale.

## Retention and publisher trust

The collector retains actual stdout/stderr bytes in a bounded, private,
content-addressed archive. Attaching a natural report writes its canonical
bytes before returning its reference. Empty output streams have a legitimate
empty-content digest; missing/corrupt files and symlink blobs fail closed.

Publication requires the report and every prompt, trace, semantic source,
semantic projection and effect artifact, all read and verified by digest.
Worker signatures alone are insufficient. The publisher reloads its own public
trust policy, checks the collector key, and verifies a second independent review
signature binding the exact signed collection and complete artifact manifest.
The review identity must match the report; principal/key aliases cannot claim
independence. Both signed envelopes are retained with certificate evidence.

Private keys and publisher policy must be operator-owned and unavailable to
workers. File ownership/permissions reject unsafe policy files, but a process
with operator filesystem authority remains inside the operator trust boundary.
Neither cryptography nor artifact hashing proves that a human actually reviewed
the traces. That approval, deployment isolation, and P6-S remain operational
requirements, not automatically closed software tests.

The collection/signing runner rejects archive paths within its own source
checkout. The operator must also exclude other installation/tenant mounts and
keep the archive inaccessible to the worker's tools; a path check is not a
mount-isolation proof. No test fixture artifact or temporary test key
is accepted as operational evidence merely because unit tests exercise signing.

## Isolation and limits of this checkpoint

The plan's section 17 was updated during development. After reading that
addendum, this delta was moved off the active checkout to branch
`p6/admission-publication-20260906` in a separate worktree. Only this turn's
changes were reversed in the active checkout; unrelated concurrent changes
were preserved. Direct source verification then confirmed active Codex 14's
original digest and candidate Codex 15's different digest. No backend restart,
control-plane migration or cutover was performed.

The new API candidate identities are adapter 38, unchanged data-only recipe 24,
Google profile 47, OpenRouter profile 46, suite 42, TCB manifest 32. No recipe
payload changed, so its immutable revision is not artificially renewed.

Remaining operational/program work is explicit:

- a distinct experimental permission and isolated worker for the **real** hosted
  natural loop is not implemented by this delta; the release barrier remains
  closed, and no client/environment laboratory permit is accepted;
- the positive control-plane tests use fabricated certification observations
  and only set the release-availability constant as an offline test condition;
  they do not replace admission guards, certificate validators or stores, but
  they include the real API capability preflight, creation, queue and dispatch
  resolution, revocation between API preflight and persistence, and a new
  process rereading revoked authority from disk. They do not open a provider
  transport and do not prove P6-L or the complete API-to-provider canary;
- the API-positive test uses the existing `full-access` execution policy in a
  disposable installation. The existing sandbox policy removes shell and
  therefore cannot satisfy the atomic Full Workspace preflight; this delta
  neither weakens that check nor proves a sandbox-mode Full Workspace canary;
- live synthetic probes, all 14 natural scenarios per claimed configuration,
  provider billing/project verification, trusted operational signatures and
  independent source/leakage review remain required for each target;
- Gemini CLI needs a certified native artifact/connection and native live
  evidence; the separate gate here does not provide that certification;
- Full Workspace canary, actual process restart/cancellation, kill switch,
  rollback/cleanup and explicit Codex cutover still require operational proof.

These are remaining gates, not waived requirements or a declaration that the
multimodel program is complete. The source budget cap is now also enforced in
`CertificationBudgetLimit`, so direct policy creation cannot exceed OpenRouter
5 USD or reclassify Google's free-tier quota as paid credit.
