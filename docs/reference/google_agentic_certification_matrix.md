# Google Gemini agentic certification matrix

Status date: 2026-09-02
Matrix revision: `2026-09-02-r33-p4-snapshot-app-closure-collaboration-tcb23`
Rollout: Full Workspace preview, not certified
Runtime engine: `maverick-tool-loop`  
Adapter: `maverick-hosted-tool-loop==29`

## Preview combination

| Field | Pinned value |
| --- | --- |
| Model provider | `google-ai-studio` |
| Model | `gemini-3.6-flash` |
| Model revision policy | `exact`; authenticated catalog `version=stable-2026-07` |
| Immutable profile revision | `37` (revision `36` suspended) |
| Execution family | `maverick_agent`; atomically pinned to Full Workspace `codex-baseline-v16` |
| Lifecycle | stable / generally available |
| Protocol | `google-interactions` |
| API version | `v1` |
| Endpoint | `https://generativelanguage.googleapis.com/v1/interactions` |
| Continuation | exact Core-managed stateless history; deterministic bounded compaction |
| Tool calls | all calls retained in codec/journal; execution remains sequential, so a multi-call response is denied and paired in full |
| Private codec | `google-gemini-interactions@3`, schema `3`; no silent migration |
| Reasoning levels | `high`; deployed default `high` |
| Synthetic live probe output budget | 2,048 tokens per request, including thinking tokens |
| Finalization reserve | one 2,048-token / 550,000-micro-USD / 20-second final request plus one equal recovery |
| Turn cost ceiling | 3,500,000 micro-USD; 1,100,000 remains protected for the two terminal attempts |
| Final request | exact Core finalization instruction; `tools` omitted |
| Thought handling | summaries disabled; signatures kept provider-private |
| Remote data classes | `public` (Core-classified only; remote admission remains blocked) |
| Tool handles | Full Workspace `codex-baseline-v16` surface: all 21 result behaviors execute under exact source taint, an active operator-owned runtime-public policy, or a certified Core result projection; app reads require a Core-audited descriptor plus executable closure and are rechecked at dispatch, inter-agent CLI/MCP operations have exact effects and content-dropping projections, raw/base64/chunked reads retain complete-resource taint, provider transport revalidates live authority before every stream advance, and shell/process effects remain rollbackable over an immutable `.git`-excluding snapshot in read-only and overlay modes; `artifact.read`, app discovery, all-worker quiescence, and post-SIGTERM cleanup remain covered |
| Certificate lifetime after a successful signed run | 45 days |

Google documents Gemini 3.6 Flash as a stable model with a 1,048,576-token
input limit, 65,536-token output limit and function calling support. The
Interactions API supports both stateful continuation through
`previous_interaction_id` and stateless replay. In stateless mode Maverick
retains every model step, including the opaque thought signature, in encrypted
provider-private state and replays it exactly with the matching function
result.

Primary references:

- [Gemini 3.6 Flash model](https://ai.google.dev/gemini-api/docs/models/gemini-3.6-flash)
- [Latest Gemini models](https://ai.google.dev/gemini-api/docs/latest-model)
- [Interactions overview](https://ai.google.dev/gemini-api/docs/interactions-overview)
- [Interactions function calling](https://ai.google.dev/gemini-api/docs/function-calling)
- [Interactions streaming](https://ai.google.dev/gemini-api/docs/streaming)
- [Interactions API v1 reference](https://ai.google.dev/api/interactions-api-v1)

## Evidence matrix

| Contract | Required evidence | Current certification result |
| --- | --- | --- |
| Request translation | deterministic stateful/stateless fixtures | not certified |
| Semantic envelope | schema v1 and projection compiler `maverick-hosted-semantic-projection@8`; exact byte-bound classifications, lexical no-symlink skill identity, restrictive attachment metadata/file joins, production exact-resource app-reference classification, attachment-only admission without an empty prompt, complete scoped `AGENTS.md` materialization, UTF-8/base64 attachment references, provider projection digest, authority lineage revalidation, and journal evidence | not certified |
| Harness recipe and context | exact recipe id/revision/digest plus fine-grained provider-capability catalog digest; independent complete-request reserve, one forced below-trigger compaction, semantic stateless-history compaction, bounded byte-correct tool-result artifacts, and explicit safe-next-turn steering fallback | not certified |
| Certified execution TCB | manifest v23 plus six static import-closure contracts and the exact hosted built-in app execution roots cover every authority/content-changing Core, Chat, Settings, app entrypoint/dependency closure, semantic compiler, recipe/context/live-preflight/artifact surface, input/result admission, raw-resource classification, request/transport revalidation, full-workspace confinement/process/discovery/snapshot/effect-overlay/batch/metadata guard, codec, transport, journal/recovery, store/audit CAS, policy, package initializer, and generalist-context dependency; drift rejects dispatch/signing/verification/publication/binding/live status | not certified |
| SSE event ordering and model identity | strict stream decoder fixtures | not certified |
| Function call id/name/count | every call persisted before resolution, exact replay/divergence checks, malformed/unknown/denial accounting, ordered pairing, and full parallel-response denial | not certified |
| Filesystem discovery | descriptor-relative race-safe listing plus provider alias → shared loop → real `filesystem.list` handler → provider result round trip | not certified |
| Full Workspace behavioral gate | `codex-baseline-v16` executes 13 original positive result workflows, a production-composed inter-agent CLI-create/MCP-wait workflow, plus raw/base64/chunk marker narrowing, revoke-then-rebuild, delayed-egress-after-revocation, post-preflight transport revocation, revoke-between-provider-events, overlay-commit rollback, and concurrent shell/process `.git` snapshot probes instead of trusting declared mode strings or isolated helpers | repository gate complete: 21/21 behaviors; signed provider certification not run |
| Live endpoint/model preflight | official current Interactions OpenAPI operation plus authenticated exact model record prove streaming, usage, function tools, reasoning controls, model identity, and input/output limits before completion transport | not certified |
| Reasoning configuration | real tool round trips at every certificate-bound level, including immutable default `high` | not certified |
| Stateful continuation | previous interaction id round trip | not certified |
| Stateless continuation | exact user/thought/function history replay | not certified |
| Thought-signature isolation | provider-private envelope and public-event assertions | not certified |
| Usage and price estimate | token usage fixtures, integer micro-USD estimator, and active-request reservation reconciliation with missing-usage fallback | not certified |
| Failure propagation | terminal codec reasons survive the shared loop and `runtime.turn.failed`; quota, resource exhaustion, and rate limiting remain distinct redaction-safe categories | not certified |
| Shared tool loop | Google codec through the deterministic hosted-loop E2E | not certified |
| Cancel/recovery/confirmation | startup, pre-admission, pre-prepare, worker-loss and uncertain-cancellation recovery; crash after every journal/state/effect/pairing transition; repeated restart without duplicate effect | not certified |
| Turn lineage and terminal pairing | exact source journal/turn/request/input lineage; ordinary cross-turn input rejected before transport; limits, cancellation and revocation leave no ready pairing on a running session | not certified |
| Final-output delivery | private outbox before commit; crash before either terminal event replays one stable output with one provider request and no duplicate event across repeated restart | not certified |
| Governed finalization | separate durable step/tool budgets; full step/output/cost/time reserve covering a complete terminal request at the hosted input ceiling; request-specific staged preflight with tool-less fallback before egress commit; persisted execution lease whose live deadline is part of the terminal success CAS; final payload omits tools; exact final instruction; whitespace rollback; unexpected call gets journaled `budget_denied`, one recovery, then quarantine | not certified |
| Containment independence | diagnostic/private-payload failure, first journal CAS conflict, unavailable journal CAS, and runtime projection fault still preserve session quarantine whenever the session CAS succeeds | not certified |
| Revocation and egress drift | mid-step revocation, live-policy drift, workspace-path rewriting, tool-result host-path redaction, and non-tool denial fixtures | not certified |
| Private-state failure | explicit quota, integrity, and recovery-reason fixtures | not certified |
| Prompt-injection containment | untrusted tool output cannot expand materialized tools | not certified |
| Child-agent isolation | forked immutable binding and independent private state | not certified |
| Live capability probe | operator-only Core-managed stateless history, two sequential real-filesystem-list calls, and one explicitly tool-less final response at the certificate-bound `high` effort (three requests total) | manifest step available; not run for r33 |

The table lists the required suite coverage; it is not evidence that the suite
ran. Bootstrap publishes only the uncertified preview profile and never manufactures a
certificate. Certification requires deterministic fixture conformance, the
operator-only synthetic live probe, behavioral validation of the complete
ordered manifest and canonical command digests, and only then signing and
publication. Repository checks explicitly select `fixture_contract` and never
start the retained `live_probe`; a fixture-only result is rejected by signing,
verification, and publication. Even a valid candidate certificate cannot bypass
Phase-0 admission.
The executable signing and publication workflow is defined in
`docs/runbooks/agentic_certification_evidence.md`.

## Fail-closed conditions

- Any model, exact catalog revision, revision policy, protocol, API-version or
  adapter mismatch is rejected.
- A missing, expired or revoked certificate prevents authority creation.
- Missing or disabled credential bindings prevent session pinning.
- Unknown data classification is denied before transport.
- Unknown app CLI/MCP effect discriminators are `unclassified`; app mutations
  without a certified pre-effect result guarantee are denied.
- Function results with a different call id or function name are rejected
  before transport.
- A function name not present in the exact request catalog is still inserted in
  the preliminary ledger, then receives an `unknown_tool` denial and result.
- Multiple function calls are all retained in private codec state and the
  journal. Calls within the remaining tool budget receive `parallel_denied`;
  overflow receives `budget_denied`. None is executed or discarded.
- A final request with any tool definition, a missing/modified finalization
  instruction, or an incoherent phase is rejected before transport. Google
  finalization omits the `tools` member.
- Empty/whitespace final text is rolled back with
  `agent_final_output_empty`. A finalization tool call is journaled and
  `budget_denied`; only one paired tool-less recovery is allowed.
- A requested reasoning effort outside the immutable certificate tuple, or a
  certificate/binding reasoning-contract mismatch, is rejected before use.
- Provider terminal statuses keep their registered reason code through the
  shared hosted loop; unknown codes alone collapse to `provider_response_invalid`.
- Redirects, unexpected hosts, non-SSE responses, oversized requests/events and
  incomplete streams are rejected.
- Raw provider errors, thought signatures and credentials never enter public
  runtime events.

Revision 13 retained the exact `fake-data preview` warning label but removed fake
classification authority: its policy lists only Core-classified `public`, its
egress id is `remote-agentic-contained@2`, and central admission remains
NO-GO. It is now historical and suspended. A future policy could consider
`workspace_internal_fake` only with the
exact resource-derived classification and an active scoped workspace
attestation; neither declaration alone can create that class. It also carries
the revision-12 corrections exposed by a real multi-tool turn:
conservative per-request price reservations are reconciled with reported usage,
and Google private continuation state tracks already-consumed call ids so a
cumulative Core result ledger can send only the currently pending result. The
r9 fixture and retained live-probe contracts described the Phase-1 TCB,
resource-derived classification, certified schema, effective capability, and
descriptor-relative filesystem gates in addition to sequential tool calls
before the final response. The
shared egress contract also redacts residual host paths found inside untrusted
tool output while retaining fail-closed denial for every other provenance.

Revision 14 pinned adapter 6 and codec/schema 3 for the Phase-2 provider-step
journal, preliminary proposal ledger, staged-state promotion, complete
multi-call accounting, reconstructible pairing, effect ordering, and productive
recovery. Suite 10 and matrix `2026-08-27-r10-p2-tcb3` add the JSON/document
parity and Google/OpenRouter crash matrices to `fixture_contract` and bind TCB
manifest v3. Its retained `live_probe` was not selected or run, and revision 14
is historical and suspended.

Revision 15 pins adapter 7, suite 11, matrix
`2026-08-27-r11-p2-tcb4`, and TCB manifest v4 for the terminal Phase-2 closure:
same-turn pairing ownership and input lineage, containment-first quarantine,
and private final-output outbox delivery across commit/restart crashes. The
retained `live_probe` was not selected or run, no behavioral evidence was
created, and this revision is now suspended and uncertified.

Revision 16 pins adapter 8, suite 12, matrix
`2026-08-27-r12-p3-tcb5`, and TCB manifest v5 for the Phase-3 finalization
closure: restart-safe provider/tool budgets, protected final/recovery
step-output-cost-deadline capacity, an exact tool-less Google final payload,
whitespace rejection, journaled denial of unexpected final calls, and at most
one paired recovery. The retained `live_probe` was updated to exercise the
tool-less final request but was not selected or run. No behavioral evidence or
certificate was created; revision 16 is suspended and uncertified.

Revision 17 pins adapter 9, suite 13, matrix
`2026-08-28-r13-p3-review-tcb5`, and TCB manifest v5 for the Phase-3 review
closure. It stages candidate egress decisions until request-specific cost
eligibility succeeds, falls back from an unaffordable exploration request to a
tool-less final request, fences synchronous tool execution before protected
terminal time, and reserves enough cost for a maximum policy-admitted tool
result. No live or behavioral run was performed; revision 17 is suspended and
uncertified.

Revision 18 pins adapter 10, suite 14, matrix
`2026-08-28-r14-p3-review2-tcb5`, and TCB manifest v5 for the second Phase-3
review closure. Timeout publishes the deterministic terminal error by ledger
CAS before private result I/O, success rechecks its lease after that I/O, and
the per-attempt allocation covers a complete terminal request at the hosted
input ceiling. No live or behavioral run has been performed; revision 18
is suspended and uncertified.

Revision 19 pins adapter 11, suite 15, matrix
`2026-08-28-r15-p3-review3-tcb5`, and TCB manifest v5 for the third Phase-3
review closure. The `executing` ledger state persists a unique lease id and UTC
expiry; terminal success atomically requires the expected revision, the same
lease, and a future deadline. Local JSON rechecks immediately before atomic
replacement and Mongo uses server `$$NOW`. Deterministic coverage pauses the
worker after its final cooperative check while delaying the timeout CAS, and
proves that expired success cannot become authoritative. No live or behavioral
run has been performed; revision 19 remains a contained, uncertified preview.

Revision 20 pins adapter 12, suite 16, matrix
`2026-08-28-r16-p4a-semantic-envelope-tcb6`, and TCB manifest v6 for Phase 4A.
Every request is compiled from a Core-owned semantic envelope v1 with distinct
platform, runtime, workspace, agent, user, governed-context, attachment, app,
skill, tool, and provider-state blocks. Complete bounded `AGENTS.md` and
`SKILL.md` materialization is descriptor-confined and version-fenced; source
snapshot and exact egress projection evidence are persisted in provider-step
journal schema v4. No live or behavioral run has been performed; revision 20
remains a contained, uncertified preview.

Revision 21 pins adapter 13, suite 17, matrix
`2026-08-28-r17-p4b-full-workspace-tcb7`, and TCB manifest v7 for Phase 4B.
The adapter now contains the complete code-owned Full Workspace tool surface,
descriptor/race confinement, platform-runtime masking, managed-process
lifecycle, official discovery-first CLI/MCP registries, and shared result
compaction. This contained profile deliberately retains only list/read handles
and does not claim `full_workspace_contract_revision`; Phase 4D must create a
new full revision after exact endpoint and interaction closure. No live or
behavioral run has been performed; revision 21 remains an uncertified preview.

Revision 22 pins adapter 14, suite 18, matrix
`2026-08-28-r18-p4-context-provider-closure-tcb8`, and TCB manifest v8 for
Phase 4C-D. It is a new, uncertified full-workspace candidate rather than a
promotion of revision 21. The immutable recipe selects Core-managed stateless
Google history, compiler revision 2, `codex-baseline-v2`, independent context
reserve and deterministic compaction, bounded artifact-backed tool results,
explicit attachment references and safe-next-turn steering fallback. Every
request performs an exact local wire preflight before egress commit; final
requests omit `tools`. No live or behavioral run, certificate, binding,
provider request, canary, or remote activation has been performed.

Revision 23 pins adapter 15, recipe 2, suite 19, matrix
`2026-08-28-r19-p4-review-closure-tcb9`, and TCB manifest v9. It closes the P4
review findings with the production classifier/result-classifier composition,
mandatory commit-bound `AGENTS.md` guards, semantic compaction schema 2,
binary attachment reads, and an official live Interactions OpenAPI plus exact
model-catalog preflight. Compiler revision 3 and `codex-baseline-v3` bind those
behavior changes. This is still an uncertified, unbound, unavailable candidate;
no live probe, behavioral run, provider completion, certificate, canary, or
remote activation has been performed.

Revision 24 pins adapter 16, recipe 3, suite 20, matrix
`2026-08-29-r20-p4-adversarial-closure-tcb10`, and TCB manifest v10. Prompt,
governed-context, and instruction classes now require exact server-owned
admission observations; generic CLI, MCP, shell, and process results remain
`unclassified` unless their concrete source supplies a canonical class.
Shell and managed-process writes run in a private overlay and cross into the
workspace only after complete bounded diff validation, declared-scope
selection, nested `AGENTS.md` revalidation, and guarded per-file commit.
Compaction schema 3 preserves every semantic entry until the real byte limit,
marks any required middle truncation explicitly, and retains tool arguments.
Compiler revision 4 and `codex-baseline-v4` bind these changes. This candidate
is still uncertified, unbound, and unavailable; no live probe, behavioral run,
provider completion, certificate, canary, or remote activation has been
performed.

Revision 25 pins adapter 17, recipe 4, suite 21, matrix
`2026-08-29-r21-p4-composite-atomic-closure-tcb11`, and TCB manifest v11.
Compiler revision 5 binds semantic classes to exact projected bytes, joins
attachment metadata with the referenced resource, and projects exact skill
documents. `codex-baseline-v5` adds rollback-safe multi-file overlay commit,
explicit directory-effect rejection, and mutating/non-retry-safe terminal
process polling. This candidate remains uncertified, unbound, and unavailable;
no live probe, behavioral run, provider completion, certificate, canary, or
remote activation has been performed.

Revision 26 pins adapter 18, recipe 5, suite 22, matrix
`2026-08-29-r22-p4-metadata-appref-closure-tcb12`, and TCB manifest v12.
`codex-baseline-v6` preserves mode/ownership/ACL/xattrs for content-only
replacement, rejects unrepresented xattr/timestamp/overlay-root metadata, and
wires exact app-reference resource classification into production bootstrap.
This candidate remains uncertified, unbound, and unavailable; no live probe,
behavioral run, provider completion, certificate, canary, or remote activation
has been performed.

Revision 27 pins adapter 19, recipe 6, suite 23, matrix
`2026-08-29-r23-p4-cow-fidelity-closure-tcb13`, and TCB manifest v13.
`codex-baseline-v7` descriptor-pins every retained pre-image and compares its
complete metadata/xattr snapshot around exchange, applies exact file
atime/mtime for content effects, admits ordinary read-modify-write, and rejects
new or existing hardlinks plus non-representable directory/root metadata. This
candidate remains uncertified, unbound, and unavailable; no live probe,
behavioral run, provider completion, certificate, canary, or remote activation
has been performed.

Revision 28 pins adapter 20, recipe 7, suite 24, matrix
`2026-08-30-r24-p4-agentic-parity-closure-tcb14`, and TCB manifest v14.
`codex-baseline-v8` installs production transient-input admission, safe
action-result projection and pre-image taint, byte-correct artifact summaries,
cancellation-quiescent copy-on-write execution, adapter-owned process cleanup,
and a complete-request compaction retry. This candidate remains uncertified,
unbound, and unavailable; no live probe, behavioral run, provider completion,
certificate, canary, or remote activation has been performed.

Revision 30 pins adapter 22, governed recipe 9, suite 26, matrix
`2026-08-30-r26-p4-agentic-review-closure-tcb16`, and TCB manifest v16.
Production now atomically captures content-derived transient/governed-context
classification, preserves complete read-only variable results with public error
pairing on egress denial, denies unguaranteed mutations before effect, awaits all
synchronous workers on cancellation, and performs repeated post-SIGTERM process
sweeps. `codex-baseline-v10` reports the remaining mutating result scenarios as
incomplete, so this profile does not claim Full Workspace. It remains
uncertified, unbound, and unavailable; no live probe, behavioral run, provider
completion, certificate, canary, or remote activation has been performed.

Revision 31 pins adapter 23, governed recipe 10, suite 27, matrix
`2026-08-31-r27-p4-agentic-closure-tcb17`, and TCB manifest v17. Content
classification no longer promotes marker-free bytes to public; direct
replace/edit/patch preserves mode and ACL/xattrs and carries exact pre-image
taint through read-after-write; move rebinds it; failed parent creation is
rolled back; and skill aliases fail closed. `codex-baseline-v12` names and
executes every filesystem mutation workflow, while creation and variable
shell/process and CLI/MCP results remain incomplete without authoritative
classification. The definition is explicitly
`maverick_agent_candidate`, not `maverick_agent`, and does not claim Full
Workspace. It remains uncertified, unbound, and unavailable; no live probe,
behavioral run, provider completion, certificate, canary, or remote activation
has been performed.

Revision 33 pins adapter 25, governed recipe 12, suite 29, matrix
`2026-08-31-r29-p4-authority-revalidation-tcb19`, and TCB manifest v19. The
operator-owned runtime-public classification policy supplies explicit,
revocable server authority for exact prompt/result identities and canonical
digests; certified Core result contracts cover schema-owned results; and
shell/process mutations admit the exact private-overlay result before commit.
The executable `codex-baseline-v12` gate returns all 16 required behaviors,
including create/read-after-create across orchestrator rebuild, CLI/MCP
list/run/call, sensitive-marker narrowing, revoke-then-rebuild denial, and
delayed-egress denial after revocation. The immutable definition therefore atomically pins
`execution_family=maverick_agent` and the Full Workspace contract. It remains
uncertified, unbound, contained, and unavailable; no live probe, signed run,
provider completion, certificate, canary, or remote activation has been
performed.

Revision 34 pins adapter 26, governed recipe 13, suite 30, matrix
`2026-09-01-r30-p4-transport-effect-atomicity-tcb20`, and TCB manifest v20.
Prepared request authority is revalidated after endpoint preflight and in the
task that advances the lazy provider stream. Filesystem results scan bounded
complete raw bytes before base64 and retain their class across version-bound
chunks. Shell/process overlay batches revalidate exact-result authority before
and after materialization and restore every pre-image on drift. Runtime-public
issue/revoke uses pending audit, classification CAS, and terminal audit CAS, so
a losing concurrent mutation is recorded as failure rather than success. The
production-composed `codex-baseline-v13` gate returns all 18 required behaviors.
The immutable definition remains uncertified, unbound, contained, and
unavailable; no live probe, signed run, provider completion, certificate,
canary, or remote activation has been performed.

Revision 35 pins adapter 27, governed recipe 14, suite 31, matrix
`2026-09-01-r31-p4-review-closure-model-revision-tcb21`, and TCB manifest v21.
The exact Google catalog model version is now carried by the profile,
certificate, binding, recipe, request, and authority, and is compared with the
authenticated live record. Every built-in app CLI/MCP surface has conservative
effect metadata and real Storage read probes; shell and managed processes mask
`.git`; mutable authority is checked before every provider-stream advance; and
the oversized P4 tests are split and retained in the certification manifest.
The production-composed `codex-baseline-v14` gate returns all 20 required
behaviors. The immutable definition remains uncertified, unbound, contained,
and unavailable; no live probe, signed run, provider completion, certificate,
canary, or remote activation has been performed.

Revision 36 pins adapter 28, governed recipe 15, suite 32, matrix
`2026-09-02-r32-p4-git-effect-authority-tcb22`, and TCB manifest v22. Core now
recursively masks root and nested Git directories/worktree pointers in shell
and managed-process read-only and overlay mounts. Hosted built-in app reads
require the exact Core-owned descriptor audit; Website Studio preview creation
and document caching are mutating, while persistent pre/post tests cover every
remaining declared read. The strengthened `codex-baseline-v15` gate remains
20/20. The immutable definition remains uncertified, unbound, contained, and
unavailable; no live probe, signed run, provider completion, certificate,
canary, or remote activation has been performed.

Revision 37 pins adapter 29, governed recipe 16, suite 33, matrix
`2026-09-02-r33-p4-snapshot-app-closure-collaboration-tcb23`, and TCB manifest
v23. Shell and managed processes now use an immutable descriptor-confined
workspace snapshot that excludes `.git` and remains isolated from post-spawn
create/rename races. Hosted built-in app reads bind descriptor metadata and the
exact executable closure, with a second check at dispatch. Every inter-agent
CLI/MCP operation has an exact effect and reviewed content-dropping public
projection, and `codex-baseline-v16` adds a real CLI-create/MCP-wait workflow to
the 21/21 behavior gate. The immutable definition remains uncertified, unbound,
contained, and unavailable; no live probe, signed run, provider completion,
certificate, canary, or remote activation has been performed.
