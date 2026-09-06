# Agentic certification evidence procedure

Status date: 2026-09-06

Scope: trusted CI or operator-controlled certification worker

Production status: **NO-GO; no P6 live/natural evidence or release approval recorded**

The following coverage inventory is historical P4 evidence, not a P6 run.
P6 collection/signing below supersedes its former two-step signing procedure.

Phase-4 repository closure executes only the explicitly selected deterministic
`fixture_contract` steps for Google and OpenRouter. It does not execute
`live_probe`, produce behavioral evidence, sign/publish a remote certificate,
or make any provider HTTP/SSE request.

Suite 38 retains the P2 crash/pairing/outbox matrix and P3 finalization
coverage, including durable step/tool/output/cost/time reservation, complete
terminal-request cost projections, tool-less provider payloads, staged
request-specific preflight, and request-scoped instructions. It also verifies
that a terminal success requires a persisted live execution lease in the same
CAS, including the race where a worker pauses after its last cooperative check,
and adds semantic-envelope source/projection, scoped instruction, full-skill,
journal-evidence, atomic Full Workspace contract, descriptor-confined mutation,
fixed-path shell, managed-process, discovery-first CLI/MCP, compaction, and
orphan-cleanup fixtures.
It additionally binds recipe/catalog identity, compiler revision 10,
the `codex-baseline-v20` behavioral Full Workspace gate, the hosted governed
result contract, mandatory commit-bound instruction digests and governed
rollback-safe shell/process effect transactions, semantic compaction schema 3,
artifact-backed large results, and UTF-8/base64 attachment workspace references
whose server-observed identity/revision/digest fences are injected into the
first and every later read. It also covers explicit steering fallback, production-composed
server-admitted classification/resource-taint continuation, fail-closed generic
tool results, preflight-before-egress ordering, Google stateless
continuation and live OpenAPI/model preflight, and OpenRouter request-scoped
authority plus `tool_choice:none`/context-capacity catalog evidence.
The last-mile fixtures narrow nonnumeric policy immediately after the lazy-open
authority refresh and require zero provider requests. They cover app-reference
and skill blocks on requests with and without tools, verify the complete public
resolver against profile policies that retain `cli`, `mcp`, `app-interface`,
and `core-capability`, and require a tool-less rebuild when live tool-call or
cumulative result-byte ceilings are exhausted. Behavior-probe
fixtures prove that only complete evidence is cached and transient or partial
results are retried. Classification fixtures also prove that a Luhn-valid
numeric run stays sensitive inside arbitrary hexadecimal text while exact
Core-owned result digests are removed only by payload-bound typed projections.
Composite attachment classification, exact skill-byte binding, attachment-only
admission, unsupported-directory rejection, full multi-file rollback, and
mutating terminal process-poll semantics are part of the deterministic corpus.
It also proves exact production app-reference resource classification,
mode/owner/xattr preservation, complete retained-pre-image metadata race
rollback, exact file timestamp materialization for read-modify-write, and
rejection of metadata-only root/directory and hardlink effects.
The corpus additionally proves atomic conservative transient-input capture,
restrictive governed-context joins, and public promotion only through an active
operator-owned runtime-public policy whose self-digest, revision, workspace,
and revocation state are revalidated against each exact-byte classification.
It proves narrowing and public error pairing for denied shell/process and
CLI/MCP results, certified Core result contracts, pre-commit exact-result
admission for private-overlay mutations, byte-correct artifact summary digests,
a shared cancel-vs-COW-commit linearization gate, all-worker requested turn
quiescence, post-SIGTERM explicit-session managed-process sweeping, and
full-request-triggered compaction. It also covers lexical skill symlink
rejection, direct edit metadata fidelity, rollback of created parents, and
public-preimage post-image taint through read-after-write. The executable Full
Workspace behavior probe now returns all 24 required workflows: 16 concrete
filesystem, shell/process, and CLI/MCP capability paths, a production-composed
inter-agent CLI-create/MCP-wait workflow with reviewed public projections, and
seven security probes. Those probes require raw/base64/chunked
filesystem markers to narrow a public result, require an
issue-write-revoke-rebuild-read sequence to fail closed, require a delayed
persisted tool result to pair only a public error after revocation, deny a
prepared request when full authority or credential authorization changes during
endpoint preflight or before lazy transport, deny a
second provider event after revocation, roll back real shell/process overlays
when authority changes after their first batch write, and prove that immutable
workspace snapshots exclude root/nested `.git` entries plus post-spawn create
and rename races for shell and managed processes in both read-only and
mutation-overlay modes. The suite also verifies exact authority
lineage across provider-state generations and pending/CAS/terminal audit
coherence for runtime-public issue/revoke under failure and concurrency.
It parses every installed built-in app CLI/MCP surface, requires a conservative
effect declaration (plus a fail-closed argument discriminator for mixed
runners), verifies the exact Core-owned descriptor and executable-closure audit
revision `2026-09-03-p4-builtin-effects-execution-v3` against the certified
TCB, exercises drift between initial preflight and
dispatch, executes real Storage
catalog reads through both registries, and checks Website Studio read actions
against persistent SQLite/file pre/post state.
Google certificates bind the exact live catalog model version; OpenRouter
certificates bind the explicit provider-alias revision policy and existing
endpoint/upstream catalog identity.
These fixtures are conformance checks only: `live_probe_selected=false` remains
mandatory for this repository closure and cannot yield certificate evidence.

This procedure is the only supported path from an executed provider suite to a
Google or OpenRouter capability certificate. Bootstrap publishes uncertified,
unbound Full Workspace preview definitions only. Test source files, fixture
names, matrix rows, or a locally fabricated run id are not evidence.

## Trust and input gate

Run from a clean checkout of the exact commit to certify. The worker must have:

- an Ed25519 private key held by trusted CI and a stable `signer_key_id` whose
  public key is installed in the certificate publisher trust set;
- a synthetic-only provider credential delivered only to the operator-controlled
  live-probe worker;
- the dated suite-v39 matrix revision
  `2026-09-04-r39-p4-typed-result-classification-tcb29` declared by the provider
  certificate module;
- the exact adapter artifact digest and the code-owned certified-execution TCB
  manifest in `core/providers/certified_execution_tcb.py`; callers do not
  provide or narrow its component list or digest;
- the exact certificate-bound reasoning-effort tuple and default represented by
  the profile under test;
- a platform evidence reference allocated by the authoritative evidence store.

Abort if `git status --short` is non-empty, the matrix/catalog has not been
reconfirmed, the live step is omitted, or the credential/workspace contains
non-synthetic data. Ordinary repository-test workers must not receive a provider
credential or send provider traffic; the complete certification worker is a
separate trusted environment.

## Collect, observe, review, then sign

Use a clean, isolated checkout at the exact deployable commit. Outputs must be
new files outside that checkout. Collection and signing are separate commands;
collection does not create a certificate, and signing never invokes a provider.

The default is fixture-only, even if ambient environment enables live probes:

```bash
python3 scripts/run_agentic_certification.py collect \
  --suite-id maverick-google-interactions-agentic-contract \
  --suite-version 40 \
  --adapter-artifact-digest "$ADAPTER_ARTIFACT_SHA256" \
  --evidence-ref "$PLATFORM_EVIDENCE_REF" \
  --output "$CERTIFICATION_OUTPUT/google-fixtures.json"
```

Only an authorized operator with explicitly scoped test credentials and a cost
budget may add `--live-probe --max-cost-microusd <approved-ceiling>` to a **new**
collection. The subprocess receives explicit opt-in and the budget; standalone
probe entrypoints also require `MAVERICK_CERTIFICATION_ALLOW_LIVE=1` and
`MAVERICK_CERTIFICATION_MAX_COST_MICROUSD`. Merely setting a credential does
not authorize a paid request. The actual translated payload is bounded before
HTTPS: model identity, conservative input-byte ceiling, output limit, request
count and non-refundable price reservation are checked. Failed/ambiguous
requests are never refunded or retried automatically.

Both suite-40 manifests bind matrix revision
`2026-09-06-r40-p6-exact-target-tcb30`. OpenRouter uses suite id
`maverick-openrouter-agentic-contract`. The live step must return a bounded,
strict JSON receipt with the exact API-profile target digest and the
collector-generated nonce. Duplicate fields, arbitrary text, extra payload
fields, missing observations, stale receipts and false counters fail closed,
even when the subprocess exits zero.

After successful fixture and live collection, an independent trusted operator
must actually execute and review the plan's 14 natural behavioral scenarios at
every claimed reasoning effort, on the same source/TCB and exact target. The
report schema and required checks are code-owned in
`core/providers/certification_behavior.py`; scenario proof contains only
prompt/trace/source/projection/effect digests, exact booleans and bounded
resource counters. Each absolute failure counter must be the integer zero.
Record native observations per approved runtime/provider connection, not per
model slug. This API signing runner does **not** implement or approve a new
native connection.

The report must be later than the protocol collection. It is an operator
observation record, not an executable behavioral runner or a self-authenticating
certificate. Do not fill checkboxes without executing the real scenarios.
Retain the reviewed private traces in the platform-owned evidence store and
store the canonical report under its `platform-evidence:sha256:<digest>` ref.
The signer must verify those traces and their provenance independently.
No production code generates passing natural observations; fabricated data in
`tests/support/certification_evidence.py` is only a unit-test fixture.

```bash
python3 scripts/run_agentic_certification.py sign \
  --collection-file "$CERTIFICATION_OUTPUT/google-live-collection.json" \
  --behavioral-evidence-file "$CERTIFICATION_OUTPUT/google-natural-observations.json" \
  --confirmation natural-traces-reviewed \
  --signer-key-id "$CERTIFICATION_SIGNER_KEY_ID" \
  --private-key-file "$CERTIFICATION_PRIVATE_KEY_FILE" \
  --output "$CERTIFICATION_OUTPUT/google-signed-run.json"
```

Only a previously trusted operator/CI signer may be used; generating a new key
and declaring it trusted does not satisfy the independent trust gate. Signing,
verification and publication reject fixture-only, protocol-only, incomplete,
wrong-target, resource-exceeding or drifted reports. The certificate publisher
also compares the full immutable definition to the signed target, so a run for
one model/recipe/policy cannot certify a different profile sharing its adapter.
The collection id retains the fixture/live run identity; the signature and
result-summary digest additionally bind the natural report and its evidence
reference. Certificate issuance/expiry use the natural completion timestamp.

Both live probes must make the provider call the exact generated alias for
`core-capability:filesystem.list`, execute the real Core handler over an
isolated synthetic directory, and return its marker-bearing result to the
provider at every certified reasoning effort. The OpenRouter probe requires
three sequential tool rounds plus a final response at every effort. The Google
probe requires two sequential tool rounds plus a final response at its single
certified effort, for exactly three provider requests. For both providers the
last request must carry the exact Core finalization instruction and an empty
tool catalog: OpenRouter sends `tools: []` with `tool_choice: none`, while
Google omits `tools`. A whitespace-only final fails the probe. Requests are
paced (one second by default) so the probe itself does not justify diagnosing a
quota incident. A Google failure must preserve the redaction-safe distinction
among `quota_exceeded`, `resource_exhausted`, and `rate_limit_exceeded`; do not
infer a
project-quota cause from the broader family alone.

Before its first completion request, the Google probe must fetch the official
current Interactions OpenAPI operation and the authenticated exact model record;
streaming, usage, function tools, reasoning controls, model identity, and both
token limits must match. Before its first completion request, the OpenRouter probe must fetch both the
official model endpoint catalog and ZDR endpoint catalog. It fails closed unless
the exact `deepinfra/fp8` record is active, FP8, ZDR-listed, has enough completion
capacity, total input-plus-output context capacity, explicit support for
`tool_choice:none`, and every endpoint-gated translated parameter. In
particular, the request must not reintroduce `parallel_tool_calls` while the
endpoint does not declare it. The required set is derived from the translated
completion payload rather than maintained as a second hard-coded parameter
list. OpenRouter may stream more than one indexed proposal despite that
omission. The certified decoder must retain every contiguous indexed call.
Because parallel execution remains unsupported, the shared loop must persist
every preliminary proposal and then return a denial result for each call; it
must not discard or execute a secondary call. A missing index, duplicate call
id, or conflicting fragment remains terminal.

The trust sequence is indivisible:

1. deterministic conformance through `fixture_contract`;
2. synthetic provider behavior through `live_probe`;
3. independently executed natural behavioral conformance, with exact target,
   source/projection/effect/trace evidence, resource bounds and absolute gates;
4. signing, independent verification, and immutable certificate publication.

The server-owned availability boundary still blocks remote admission after a
valid certificate; certification evidence cannot substitute for later
recovery, preview, canary, security-review, or production gates.

The runner records and signs the source commit, suite identity/version, matrix
revision and digest, adapter digest, certified TCB manifest id/version/digest,
complete artifact-bundle digest, command result digest, evidence references,
timestamps, and `passed` outcome. Raw
credentials, provider payloads, prompts, tool arguments/results, and private
continuation state must not appear in the signed JSON or evidence reference.

## Verify and publish

Transfer the signed JSON and referenced evidence to the isolated certificate
publisher. The publisher must parse it with
`core.providers.certification_pipeline.signed_run_from_json`, verify the
signature against its configured trusted public keys, and call exactly one of:

- `publish_google_preview_certificate` in
  `core/providers/google_agentic_certification.py`;
- `publish_openrouter_preview_certificate` in
  `core/providers/openrouter_agentic_certification.py`.

Those functions recheck the deployed source commit, suite manifest and step
command digests, matrix bytes, complete artifact bundle, deployed adapter
digest, and the current certified-execution TCB manifest/digest before
publishing immutable evidence and certificate records through the provider
store. The publisher computes the digest from deployed files and never trusts
a caller-supplied digest. Signing, verification, issuance, execution binding,
continuation/authority refresh, and live status use the same identity. There is
deliberately no bootstrap
fallback. A mismatch, untrusted signer, duplicate conflicting identity,
invalid evidence reference, or publisher failure leaves the candidate
uncertified; a binding must not be enabled until both records and active status
read back consistently.

The TCB includes every component able to change attestation/classification/
egress, runtime API/app admission, input composition/request building, tool
schema/catalog, ledger/store/private state, lifecycle/recovery boundary,
capability projection, Chat/Settings governance, and provider codec/transport/
live policy. Drift in any component invalidates an older remote certificate
before creation, continuation, refresh, or dispatch. A legacy remote
certificate without a valid TCB identity is ineligible; exact Codex remains its
separate local identity. Manifest v9 makes the transitive inventory executable:
six code-owned contracts statically walk local imports for admission, input,
egress, tools, state/lifecycle, and served governance, including package
initializers and the exact `core/inter_agent/generalist_context.py` closure.
Every reached path must already be in the canonical artifact set. Signing,
verification, publication validation, binding, and live status all reject an
older digest when any such path drifts.

After publication, read the certificate and evidence back through the
platform-authority provider surface and verify that all signed identities match
the deployed commit and profile definition. Then run the pre-activation gate in
`docs/runbooks/agentic_provider_preview.md`. Store any human-readable report in
Storage only as a redaction-safe copy linked to the opaque authoritative
evidence id.

## Revocation and rerun

Revoke the exact certificate immediately if adapter bytes, codec, transport,
matrix, routing catalog, provider behavior, signer trust, or evidence integrity
is in doubt. Never edit or reactivate the immutable certificate. A corrected
build requires a new run, evidence id, signed artifact, certificate identity,
expiry, and canary. Preserve the old redaction-safe metadata for audit and
follow the rollback sequence in the preview runbook.
