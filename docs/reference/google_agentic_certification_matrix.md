# Google Gemini agentic certification matrix

Status date: 2026-08-27
Matrix revision: `2026-08-27-r10-p2-tcb3`
Rollout: candidate preview, not certified
Runtime engine: `maverick-tool-loop`  
Adapter: `maverick-hosted-tool-loop==6`

## Candidate combination

| Field | Pinned value |
| --- | --- |
| Model provider | `google-ai-studio` |
| Model | `gemini-3.6-flash` |
| Immutable profile revision | `14` (revision `13` suspended) |
| Lifecycle | stable / generally available |
| Protocol | `google-interactions` |
| API version | `v1` |
| Endpoint | `https://generativelanguage.googleapis.com/v1/interactions` |
| Continuation | stateful in production; stateless exact-history codec tested |
| Tool calls | all calls retained in codec/journal; execution remains sequential, so a multi-call response is denied and paired in full |
| Private codec | `google-gemini-interactions@3`, schema `3`; no silent migration |
| Reasoning levels | `high`; deployed default `high` |
| Synthetic live probe output budget | 2,048 tokens per request, including thinking tokens |
| Thought handling | summaries disabled; signatures kept provider-private |
| Remote data classes | `public` (Core-classified only; remote admission remains blocked) |
| Tool handles | `core-capability:filesystem.list`, `core-capability:filesystem.read` |
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
| Certified execution TCB | manifest v3 plus six static import-closure contracts cover every authority/content-changing Core, Chat, Settings, codec, transport, journal/recovery, store, policy, package initializer, and generalist-context dependency; drift rejects signing/verification/publication/binding/live status | not certified |
| SSE event ordering and model identity | strict stream decoder fixtures | not certified |
| Function call id/name/count | every call persisted before resolution, exact replay/divergence checks, malformed/unknown/denial accounting, ordered pairing, and full parallel-response denial | not certified |
| Filesystem discovery | descriptor-relative race-safe listing plus provider alias → shared loop → real `filesystem.list` handler → provider result round trip | not certified |
| Reasoning configuration | real tool round trips at every certificate-bound level, including immutable default `high` | not certified |
| Stateful continuation | previous interaction id round trip | not certified |
| Stateless continuation | exact user/thought/function history replay | not certified |
| Thought-signature isolation | provider-private envelope and public-event assertions | not certified |
| Usage and price estimate | token usage fixtures, integer micro-USD estimator, and active-request reservation reconciliation with missing-usage fallback | not certified |
| Failure propagation | terminal codec reasons survive the shared loop and `runtime.turn.failed`; quota, resource exhaustion, and rate limiting remain distinct redaction-safe categories | not certified |
| Shared tool loop | Google codec through the deterministic hosted-loop E2E | not certified |
| Cancel/recovery/confirmation | startup, pre-admission, pre-prepare, worker-loss and uncertain-cancellation recovery; crash after every journal/state/effect/pairing transition; repeated restart without duplicate effect | not certified |
| Revocation and egress drift | mid-step revocation, live-policy drift, workspace-path rewriting, tool-result host-path redaction, and non-tool denial fixtures | not certified |
| Private-state failure | explicit quota, integrity, and recovery-reason fixtures | not certified |
| Prompt-injection containment | untrusted tool output cannot expand materialized tools | not certified |
| Child-agent isolation | forked immutable binding and independent private state | not certified |
| Live capability probe | operator-only two sequential real-filesystem-list calls plus final response at the certificate-bound `high` effort (three requests total) | manifest step available; not run for r10 |

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
  journal, then each receives `parallel_denied`; none is executed or discarded.
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

Revision 14 pins adapter 6 and codec/schema 3 for the Phase-2 provider-step
journal, preliminary proposal ledger, staged-state promotion, complete
multi-call accounting, reconstructible pairing, effect ordering, and productive
recovery. Suite 10 and matrix `2026-08-27-r10-p2-tcb3` add the JSON/document
parity and Google/OpenRouter crash matrices to `fixture_contract` and bind TCB
manifest v3. The retained `live_probe` was not selected or run, no behavioral
evidence was created, and this candidate remains suspended and uncertified.
