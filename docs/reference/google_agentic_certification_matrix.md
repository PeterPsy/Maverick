# Google Gemini agentic certification matrix

Status date: 2026-08-29
Matrix revision: `2026-08-29-r21-p4-composite-atomic-closure-tcb11`
Rollout: candidate preview, not certified
Runtime engine: `maverick-tool-loop`  
Adapter: `maverick-hosted-tool-loop==17`

## Candidate combination

| Field | Pinned value |
| --- | --- |
| Model provider | `google-ai-studio` |
| Model | `gemini-3.6-flash` |
| Immutable profile revision | `25` (revision `24` suspended) |
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
| Tool handles | complete `codex-baseline-v5` Full Workspace surface, including `artifact.read`, read-only-by-default shell/process isolation, and rollback-safe copy-on-write text effects |
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
| Semantic envelope | schema v1 and projection compiler `maverick-hosted-semantic-projection@5`; exact byte-bound classifications, restrictive attachment metadata/file joins, attachment-only admission without an empty prompt, exact `SKILL.md` projection, complete scoped `AGENTS.md` materialization, UTF-8/base64 attachment references, provider projection digest, and journal evidence | not certified |
| Harness recipe and context | exact recipe id/revision/digest plus fine-grained provider-capability catalog digest; independent context reserve, semantic stateless-history compaction, bounded tool-result artifacts, and explicit safe-next-turn steering fallback | not certified |
| Certified execution TCB | manifest v11 plus six static import-closure contracts cover every authority/content-changing Core, Chat, Settings, semantic compiler, recipe/context/live-preflight/artifact surface, full-workspace confinement/process/discovery/effect-overlay/batch surface, codec, transport, journal/recovery, store, policy, package initializer, and generalist-context dependency; drift rejects signing/verification/publication/binding/live status | not certified |
| SSE event ordering and model identity | strict stream decoder fixtures | not certified |
| Function call id/name/count | every call persisted before resolution, exact replay/divergence checks, malformed/unknown/denial accounting, ordered pairing, and full parallel-response denial | not certified |
| Filesystem discovery | descriptor-relative race-safe listing plus provider alias → shared loop → real `filesystem.list` handler → provider result round trip | not certified |
| Full Workspace contract implementation | atomic `codex-baseline-v5` claim validation; stable UTF-8/base64 reads, atomic direct mutations with mandatory instruction digests, networkless shell/process overlays, explicit scopes, rejection of unrepresentable directories, complete multi-file retained-preimage rollback, mutating non-retry-safe terminal process polling, official discovery-first CLI/MCP, bounded artifacts, and orphan cleanup | implementation fixture only; revision 25 makes the full claim but remains uncertified and unavailable |
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
| Live capability probe | operator-only Core-managed stateless history, two sequential real-filesystem-list calls, and one explicitly tool-less final response at the certificate-bound `high` effort (three requests total) | manifest step available; not run for r21 |

The table lists the required suite coverage; it is not evidence that the suite
ran. Bootstrap publishes only the candidate profile and never manufactures a
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

- Any model, protocol, API-version or adapter mismatch is rejected.
- A missing, expired or revoked certificate prevents authority creation.
- Missing or disabled credential bindings prevent session pinning.
- Unknown data classification is denied before transport.
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
