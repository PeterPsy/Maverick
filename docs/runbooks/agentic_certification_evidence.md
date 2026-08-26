# Agentic certification evidence procedure

Status date: 2026-08-26

Scope: trusted CI or operator-controlled certification worker

Production status: **not approved; fixture-contract evidence only**

This procedure is the only supported path from an executed provider suite to a
Google or OpenRouter capability certificate. Bootstrap publishes candidate
profile definitions only. Test source files, fixture names, matrix rows, or a
locally fabricated run id are not evidence.

## Trust and input gate

Run from a clean checkout of the exact commit to certify. The worker must have:

- an Ed25519 private key held by trusted CI and a stable `signer_key_id` whose
  public key is installed in the certificate publisher trust set;
- the dated matrix revision declared by the provider certificate module;
- the exact adapter artifact digest and a reviewed explicit list of the adapter,
  codec, transport, hosted-loop, policy, and focused-test artifacts in the
  certification bundle;
- the exact certificate-bound reasoning-effort tuple and default represented by
  the profile under test;
- a platform evidence reference allocated by the authoritative evidence store.

Abort if `git status --short` is non-empty or the matrix no longer matches the
manifest. The certification runner must not receive a provider credential,
send provider traffic, or execute a live probe.

## Execute and sign

Create an output directory outside the repository. The runner opens its output
with create-only semantics and emits nothing when the command exits non-zero.
The runner selects a code-owned, versioned manifest from `suite-id` and
`suite-version`. It accepts no command, matrix path/revision, artifact list, or
probe entrypoint from the CLI. Every current remote manifest contains
`fixture_contract` steps only. A live diagnostic is not a certification step,
is not started by repository checks, and cannot be folded into the signed run.

```bash
python3 scripts/run_agentic_certification.py \
  --suite-id maverick-google-interactions-agentic-contract \
  --suite-version 8 \
  --adapter-artifact-digest "$ADAPTER_ARTIFACT_SHA256" \
  --evidence-ref "$PLATFORM_EVIDENCE_REF" \
  --signer-key-id "$CERTIFICATION_SIGNER_KEY_ID" \
  --private-key-file "$CERTIFICATION_PRIVATE_KEY_FILE" \
  --output "$CERTIFICATION_OUTPUT/google-run.json"
```

For OpenRouter use suite id `maverick-openrouter-agentic-contract`, suite
version `8`, matrix revision `2026-08-26-r8`, and the OpenRouter manifest. The
Google suite uses version `8` and matrix revision `2026-08-26-r8`. The
canonical matrices, artifact bundles, and fixture commands live in
`core/providers/certification_manifests.py`.
Do not reuse a Google artifact bundle, result, or evidence reference.

Fixture contracts exercise the generated filesystem alias, real Core handler,
multi-step tool/result/final sequencing, routing/catalog validation, reasoning
levels, and failure normalization without provider traffic. Any future
operator-only provider diagnostic and catalog reconfirmation belong to the
separate release gate in `agentic_provider_preview.md`; their output is not
certificate evidence and cannot bypass Phase-0 admission.

The runner records and signs the source commit, suite identity/version, matrix
revision and digest, adapter digest, complete artifact-bundle digest, command
result digest, evidence references, timestamps, and `passed` outcome. Raw
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
command digests, matrix bytes, complete artifact bundle, and deployed adapter
digest before publishing immutable evidence and certificate records through
the provider store. There is deliberately no bootstrap
fallback. A mismatch, untrusted signer, duplicate conflicting identity,
invalid evidence reference, or publisher failure leaves the candidate
uncertified; a binding must not be enabled until both records and active status
read back consistently.

The deployed adapter digest includes each declared operational module and
function directly. A source change in the shared stream consumer,
filesystem-list traversal, tool orchestration, request translation, provider
codec, or transport must change that digest and invalidate older certificates;
digesting the built-in `function` type is never acceptable.

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
