# P6 Settings and isolated laboratory delta

Branch: `p6/settings-lab-20260906`, based on reviewer candidate `dfbf045f`.
This work is in an independent candidate checkout, not the running installation.
Active Codex 14, active stores, credentials, backend and unrelated user changes
are not deployed, migrated, restarted or reclassified. No real provider call is
made. **P6-L/S/R are not declared closed by this development checkpoint.**

## Settings first

`c93ba8ed` completes the pre-existing Settings draft, copied coherently into this
candidate. Groups use normalized family + definition + runtime engine + model
provider, never model ID/name. Primary selection returns an original item:
enabled default, otherwise enabled, otherwise highest natural revision. Numeric
runs are compared without floating-point conversion, including 500-digit values.
Each summary identifies the exact `definition_id@revision`; remaining original
cards live in a closed `Other revisions · N` details element which is deliberately
not a model accordion. Other enabled revisions remain indicated and visible.
The original controller keeps exact binding ID/revision/CAS/gates. Rendering
neither mutates the list nor writes configuration. The API's projection of one
binding ID per definition/revision remains an explicit, separate limitation.

Settings verification: 19 frontend tests, TypeScript check and candidate build;
Python 14 passed / 9 intentionally slow-gated skips. Candidate assets were built
and their canonical conservative asset manifest generated; nothing was deployed
to the running Settings app.

## Distinct laboratory, common runtime

`e567f643` adds typed signed API/native targets, installation-owned issuer trust,
operator authorization references, exact source/adapter/TCB/root/attestation,
actor/session/scenario/effort/capability/policy/route/credential/budget grants,
expiry, CAS revocation and durable non-renewable ownership. No certificate object
or fabricated certificate ID/evidence is used for laboratory admission.

The subsequent composition uses one shared monotonic lattice and one hosted
factory. Both production and lab artifacts always include the new components.
The private bootstrap opens the real stores/vault/tool ledger/provider WAL
through the extracted side-effect-free store composition; production-only app,
repository, migration and recovery bootstrap side effects remain separate.
The clean allowlisted process environment cannot inherit insecure test defaults,
HOME, provider keys, Mongo or active endpoints. Source, stores, vault and operator
material must be disjoint from explicitly inventoried active roots; aliases,
hardlinks, shared Git administration and dirty/different source fail closed.
Inventory completeness and OS mount isolation remain operator responsibilities.

The natural worker captures the real semantic input and executes
`execute_agentic_runtime_turn` through the actual adapter and `HostedAgenticLoop`.
It retains captured input/sources, translated provider payloads, runtime events,
observed workspace versions/content, actual result/usage and cleanup errors in
the content-addressed archive. It does **not** synthesize semantic check booleans
or issue/sign/publish certification. Mandatory mutation confirmations are still
mandatory: the offline human peer uses the real confirmation API with the exact
observed arguments and CAS, separately from the worker/model actor.

Each real generation uses a reusable global ledger fence independent of probe
round limits. The shared request guard propagates task-locally to this fence and
revalidates after pacing/reservation, before HTTPS, and while streaming; a silent
stream also polls the cheap revocation fence. Reservations survive cancel/crash.
OpenRouter operational permits are capped at 4.50 USD within the ledger's 5 USD
ceiling. Google has finite free-tier quota only; actual provider billing-tier
verification remains required before live work.

## Explicit candidate identity revision

- Hosted adapter **42**, Google profile **51**, OpenRouter profile **50**.
- Data-only recipes unchanged: Google **24**, OpenRouter **25**.
- Suite **46**, TCB manifest **36**, matrix
  `2026-09-06-r46-p6-isolated-lab-tcb36`.
- Codex candidate **16**:
  `0297245b4a9c234614ada790fb05d18a0429e9d2d3378b8fa2cf8e087b9b0b19`.

Shared queue source remains in the Codex artifact, with explicit typed laboratory
admission before the unchanged handoff/ownership/status/WAL checks. Revisions
14 and 15 retain their original artifact hashes; neither is silently rewritten,
certified for these new bytes or operationally cut over. Existing production
pins may omit the new domain extension using the documented production-only
historical digest contract. Lab pins cannot use that fallback or be imported.

## Review and release gates still required

1. Independent source/isolation/last-mile review before the first live cost.
2. Operator-prepared private installation/trust/credentials, source freeze and
   billing/quota checks; one bounded live vertical, then the full natural corpus
   for each exact API target/effort. Offline HTTP fixtures are **not** live proof.
3. Native Gemini needs its own binary/distribution/connection/effects worker and
   corpus. The typed native permit is deliberately rejected by the API worker;
   Google API authorization and the production allowlist are not repurposed.
4. Natural semantic reports need independent review and real retained evidence;
   existing publisher verification rejects missing/corrupt blobs, mismatched
   receipts and unauthorized/reviewer-alias signers. No operational review keys
   or certificates are generated by this delta.
5. The certified production API → enable → create → queue → dispatch canary,
   restart/cancel/kill-switch/cleanup/rollback and any explicit Codex cutover
   remain release evidence, distinct from the laboratory vertical.

Restart currently refuses reclaiming a named lab session rather than inventing
a renewed ownership lease. Descendants are not executable even if named until a
parent-liveness/recovery protocol exists. The worker is a library entrypoint, not
an operator live-launch CLI or a general multi-worker scheduler. These limitations
are fail-closed and must not be presented as completed natural/release scenarios.

## Recorded offline verification

Exact full-suite source: `cc1e2d5f4745a9d11051f88e4e25de7d5355093e`, with a clean
checkout before and after both sequential fixture commands and unchanged TCB.
`MAVERICK_CERTIFICATION_ALLOW_LIVE=0`; only `fixture_contract` steps were run.

| Check | Tests | Failures / errors / skips |
| --- | ---: | --- |
| Exact Google suite-46 fixture command | 699 | 0 / 0 / 0 |
| Exact OpenRouter suite-46 fixture command | 710 | 0 / 0 / 0 |
| Additional native rollout, queue, API, cleanup and historical pin regressions | 95 | 0 / 0 / 0 |
| Settings frontend (plus separate TypeScript check) | 19 | 0 / 0 / 0 |

Counts overlap between commands; they are not a repository-wide unique total.
The strict fixture parser accepted both complete retained stderr streams and
the extra regressions, including its uncaught-background-failure checks.
Expanded commands, timings, output hashes and verified receipts are retained at
`/var/tmp/maverick/maverick-p6-lab-verified-uiry0pld/summary.json`, SHA-256
`619a9f5cf20f2ce19c0bc374dc1875e9d634546c581a44ba1387ef23197dfde8`.
The adjacent `extra-summary.json` has SHA-256
`e08903cb1c7f36109052cc3638016a5e22f39b63f4e313898d44265b23b3c607`.

A subsequent **test-only** strengthening revokes the permit from another process
during pacing, after reservation and during streaming; all six job-budget tests
pass. Its retained `cross-process-budget.stderr` SHA-256 is
`fcd935949acd05d0565c171ebd84025f8b7b30df26b3180e31952c7905e737c3`.
The matrix tables were also corrected to manifest 36 / seven dependency
contracts. These final test/documentation changes do not alter runtime bytes or
served assets. The full-suite receipts above name the exact earlier source,
not certification evidence for a later commit or the live laboratory.

TCB structure: `149f897cc921d7abbfbf96b5cb9684a17aaf1933a3d4923292a7cb2c4fb4549e`.
TCB live: `00ad85af941e1ea16ca88cbb06d7988fc932040863428485814e232f22e29a30`.
Unused-import and whitespace checks passed. Final read-only verification
confirmed the active Settings draft's original hashes and active Codex revision
14/digest `33b483337b160ba8281b3ad17176030905ee0b83f2067d5eee911ef6517eab55`
were unchanged. The full repository fast/pre-merge suite was not run.
