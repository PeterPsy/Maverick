# Agentic certification evidence procedure

Status date: 2026-08-30

Scope: trusted CI or operator-controlled certification worker

Production status: **not approved; no complete two-step certificate evidence recorded**

Phase-4 repository closure executes only the explicitly selected deterministic
`fixture_contract` steps for Google and OpenRouter. It does not execute
`live_probe`, produce behavioral evidence, sign/publish a remote certificate,
or make any provider HTTP/SSE request.

Suite 25 retains the P2 crash/pairing/outbox matrix and P3 finalization
coverage, including durable step/tool/output/cost/time reservation, complete
terminal-request cost projections, tool-less provider payloads, staged
request-specific preflight, and request-scoped instructions. It also verifies
that a terminal success requires a persisted live execution lease in the same
CAS, including the race where a worker pauses after its last cooperative check,
and adds semantic-envelope source/projection, scoped instruction, full-skill,
journal-evidence, atomic Full Workspace contract, descriptor-confined mutation,
fixed-path shell, managed-process, discovery-first CLI/MCP, compaction, and
orphan-cleanup fixtures.
It additionally binds recipe/catalog identity, compiler revision 5,
`codex-baseline-v9`, mandatory commit-bound instruction digests and governed
rollback-safe shell/process effect transactions, semantic compaction schema 3, artifact-backed
large results, UTF-8/base64 attachment
workspace references, explicit steering fallback, production-composed
server-admitted classification/resource-taint continuation, fail-closed generic
tool results, preflight-before-egress ordering, Google stateless
continuation and live OpenAPI/model preflight, and OpenRouter request-scoped
authority plus `tool_choice:none`/context-capacity catalog evidence.
Composite attachment classification, exact skill-byte binding, attachment-only
admission, unsupported-directory rejection, full multi-file rollback, and
mutating terminal process-poll semantics are part of the deterministic corpus.
It also proves exact production app-reference resource classification,
mode/owner/xattr preservation, complete retained-pre-image metadata race
rollback, exact file timestamp materialization for read-modify-write, and
rejection of metadata-only root/directory and hardlink effects.
The corpus additionally proves source-derived transient-input classification,
restrictive governed-context joins, complete-or-egress-denied shell/process and
CLI/MCP results, byte-correct artifact summary digests, a shared
cancel-vs-COW-commit linearization gate, requested turn quiescence,
adapter-owned explicit-session managed-process cleanup, and
full-request-triggered compaction.
These fixtures are conformance checks only: `live_probe_selected=false` remains
mandatory for this repository closure and cannot yield certificate evidence.

This procedure is the only supported path from an executed provider suite to a
Google or OpenRouter capability certificate. Bootstrap publishes candidate
profile definitions only. Test source files, fixture names, matrix rows, or a
locally fabricated run id are not evidence.

## Trust and input gate

Run from a clean checkout of the exact commit to certify. The worker must have:

- an Ed25519 private key held by trusted CI and a stable `signer_key_id` whose
  public key is installed in the certificate publisher trust set;
- a synthetic-only provider credential delivered only to the operator-controlled
  live-probe worker;
- the dated suite-v25 matrix revision
  `2026-08-30-r25-p4-agentic-review-closure-tcb15` declared by the provider
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

## Execute and sign

Create an output directory outside the repository. The runner opens its output
with create-only semantics and emits nothing when the command exits non-zero.
The runner selects a code-owned, versioned manifest from `suite-id` and
`suite-version`. It accepts no command, matrix path/revision, artifact list, or
probe entrypoint from the CLI. Every current remote manifest contains one
deterministic `fixture_contract` step and one distinct operator-only
`live_probe` step; both must pass in canonical order before the run can be
signed, verified, or published.

Normal repository tests may call `execute_certification_suite` with
`step_kinds=("fixture_contract",)` to exercise deterministic conformance without
provider traffic. That explicit selection does not remove or rewrite the live
step in the manifest. The resulting incomplete run is deliberately rejected by
completed-run validation and can never be certificate evidence.

```bash
python3 scripts/run_agentic_certification.py \
  --suite-id maverick-google-interactions-agentic-contract \
  --suite-version 25 \
  --adapter-artifact-digest "$ADAPTER_ARTIFACT_SHA256" \
  --evidence-ref "$PLATFORM_EVIDENCE_REF" \
  --signer-key-id "$CERTIFICATION_SIGNER_KEY_ID" \
  --private-key-file "$CERTIFICATION_PRIVATE_KEY_FILE" \
  --output "$CERTIFICATION_OUTPUT/google-run.json"
```

For OpenRouter use suite id `maverick-openrouter-agentic-contract`, suite
version `25`, matrix revision
`2026-08-30-r25-p4-agentic-review-closure-tcb15`, and the OpenRouter manifest.
The Google suite uses version `25` and the same matrix revision. The
canonical matrices, artifact bundles, commands, and live-probe entrypoints live
in `core/providers/certification_manifests.py`. Do not reuse a Google artifact
bundle, result, live probe, or evidence reference.

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
3. behavioral conformance validation of both successful results, their order,
   manifest digest, and canonical command digests;
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
