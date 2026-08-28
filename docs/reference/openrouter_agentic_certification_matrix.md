# OpenRouter DeepSeek agentic certification matrix

Status date: 2026-08-28
Matrix revision: `2026-08-28-r15-p3-review3-tcb5`
Rollout: candidate preview, not certified
Runtime engine: `maverick-tool-loop`  
Adapter: `maverick-hosted-tool-loop==11`

## Candidate combination

| Field | Pinned value |
| --- | --- |
| Model provider | `openrouter` |
| Model | `deepseek/deepseek-v4-flash` |
| Immutable profile revision | `18` (revision `17` suspended) |
| Protocol | OpenAI-compatible streaming Chat Completions |
| API version | `v1` |
| Endpoint | `https://openrouter.ai/api/v1/chat/completions` |
| Upstream endpoint tag | `deepinfra/fp8` |
| Effective provider identity | `DeepInfra` |
| Quantization | `fp8` |
| Context / endpoint completion limit | 1,048,576 / 65,536 tokens |
| Tool calls | every indexed call is retained; execution remains sequential, so a multi-call response is denied and paired in full |
| Parallel request control | parameter omitted because the certified endpoint catalog does not declare it; Core journals every returned call before `parallel_denied` |
| Private codec | `openrouter-chat-completions@2`, schema `2`; ordered plural pending calls and no silent migration |
| Mixed response handling | provisional text plus one tool call is retained privately and continued |
| Reasoning levels | `minimal`, `low`, `medium`, `high`; deployed default `high` |
| Router controls | fallback off, parameters required, collection denied, ZDR required |
| Finalization reserve | one 2,048-token / 35,000-micro-USD / 20-second final request plus one equal recovery |
| Turn cost ceiling | 80,000 micro-USD; 70,000 remains protected for the two terminal attempts |
| Final request | exact Core finalization instruction; `tools: []`; `tool_choice: none` |
| Remote data classes | `public` (Core-classified only; remote admission remains blocked) |
| Tool handles | `core-capability:filesystem.list`, `core-capability:filesystem.read` |
| Certificate lifetime after a successful signed run | 30 days |

The dated OpenRouter model and ZDR endpoint catalogs listed `deepinfra/fp8` as
active for DeepSeek V4 Flash, with `tools`, `tool_choice`, `reasoning`,
`max_tokens`, and `reasoning_effort` support. Neither catalog declared
`parallel_tool_calls`. The endpoint exposed FP8 quantization; the recorded list
price was $0.09 per million input tokens and $0.18 per million output tokens.
The certification probe fetches both official catalogs immediately before any
completion request and fails unless this exact record is active, ZDR-listed,
large enough for the requested completion budget, and supports every parameter
the translated payload sends that participates in endpoint parameter routing.

Every agentic request sends this router object without a permissive default.
It intentionally omits `parallel_tool_calls`, because `require_parameters=true`
would otherwise make every currently catalogued endpoint ineligible:

```json
{
  "provider": {
    "only": ["deepinfra/fp8"],
    "allow_fallbacks": false,
    "require_parameters": true,
    "data_collection": "deny",
    "zdr": true,
    "quantizations": ["fp8"]
  }
}
```

The transport opts into OpenRouter router metadata. The codec requires the
response provider to be `DeepInfra`, then requires terminal metadata to show
the requested model, one successful attempt, and `DeepInfra` as the selected
provider. Only after those checks can the exact requested endpoint tag be
normalized as the certified upstream. Missing metadata, a different provider,
an extra attempt, or an unavailable endpoint fails closed.

Primary references:

- [DeepSeek V4 Flash model](https://openrouter.ai/deepseek/deepseek-v4-flash/api)
- [Model endpoint catalog](https://openrouter.ai/api/v1/models/deepseek/deepseek-v4-flash/endpoints)
- [ZDR endpoint catalog](https://openrouter.ai/api/v1/endpoints/zdr)
- [Provider selection](https://openrouter.ai/docs/guides/routing/provider-selection)
- [Zero data retention](https://openrouter.ai/docs/guides/features/zdr)
- [Router metadata](https://openrouter.ai/docs/guides/features/router-metadata)
- [Reasoning preservation](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens)
- [Tool calling](https://openrouter.ai/docs/guides/features/tool-calling)

## Evidence matrix

| Contract | Required evidence | Current certification result |
| --- | --- | --- |
| Exact request translation | deterministic payload, omission of unsupported `parallel_tool_calls`, and relaxed-router-control rejection fixtures | not certified |
| Certified execution TCB | manifest v5 plus six static import-closure contracts cover every authority/content-changing Core, Chat, Settings, codec, transport, journal/recovery, store, policy, package initializer, and generalist-context dependency; drift rejects signing/verification/publication/binding/live status | not certified |
| Endpoint catalog preflight | exact model and ZDR records must both support every endpoint-gated translated parameter, DeepInfra FP8 identity, active status, and completion budget | not certified |
| SSE ordering and bounds | shared bounded SSE plus OpenRouter transport fixtures | not certified |
| Effective upstream | response identity and terminal router-metadata mismatch fixtures | not certified |
| No eligible endpoint | HTTP and streamed 404 normalization fixtures | not certified |
| Tool call id/name/count | fragmented/malformed arguments, all contiguous indices, preliminary persistence, exact replay/divergence, duplicate-id rejection, full parallel denial, and ordered plural pairing | not certified |
| Mixed text then tool | provisional narration is not finalized or duplicated; one call continues to the next step | not certified |
| Multi-step continuation | deterministic fixtures for three sequential tool rounds followed by a final response at every reasoning effort | not certified |
| Filesystem discovery | descriptor-relative race-safe listing plus provider alias → shared loop → real `filesystem.list` handler → provider result round trip | not certified |
| Reasoning configuration | real tool round trips at every certificate-bound level, including immutable default `high` | not certified |
| Reasoning isolation | exact private `reasoning_details` replay and public-event leakage assertions | not certified |
| Usage, generation id and price | success and decode-failure fixtures retain telemetry; active request reservations reconcile to reported micro-USD while missing usage remains worst-case | not certified |
| Failure propagation | distinct mixed/parallel/index codes, safe public message, diagnostic reference, and nonnumeric Chat UX | not certified |
| Shared tool loop | real OpenRouter codec through deterministic hosted-loop E2E | not certified |
| Cancel/recovery/confirmation | startup, pre-admission, pre-prepare, worker-loss and uncertain-cancellation recovery; crash after every journal/state/effect/pairing transition; repeated restart without duplicate effect | not certified |
| Turn lineage and terminal pairing | exact source journal/turn/request/input lineage; ordinary cross-turn input rejected before transport; limits, cancellation and revocation leave no ready pairing on a running session | not certified |
| Final-output delivery | private outbox before commit; crash before either terminal event replays one stable output with one provider request and no duplicate event across repeated restart | not certified |
| Governed finalization | separate durable step/tool budgets; full step/output/cost/time reserve covering a complete terminal request at the hosted input ceiling; request-specific staged preflight with tool-less fallback before egress commit; persisted execution lease whose live deadline is part of the terminal success CAS; `tools: []` plus `tool_choice: none`; exact request-scoped final instruction after paired results; whitespace rollback; unexpected call gets journaled `budget_denied`, one recovery, then quarantine | not certified |
| Containment independence | diagnostic/private-payload failure, first journal CAS conflict, unavailable journal CAS, and runtime projection fault still preserve session quarantine whenever the session CAS succeeds | not certified |
| Outage after acceptance | terminal normalized failure with no blind retry | not certified |
| Revocation and egress drift | mid-step revocation, live-policy drift, workspace-path rewriting, tool-result host-path redaction, and non-tool denial fixtures | not certified |
| Private-state failure | explicit quota, integrity, and recovery-reason fixtures | not certified |
| Prompt-injection containment | untrusted tool output cannot expand materialized tools | not certified |
| Child-agent isolation | forked immutable binding and independent private state | not certified |
| Live capability probe | operator-only catalog/ZDR preflight, then three sequential real-filesystem-list rounds plus one explicitly tool-less final response at every certificate-bound reasoning effort | manifest step available; not run for r15 |

The table defines required coverage and does not report a completed run.
Bootstrap publishes only the candidate profile and never manufactures a
certificate. Certification requires deterministic fixture conformance, the
operator-only synthetic live probe with fresh catalog/ZDR reconfirmation,
behavioral validation of the complete ordered manifest and canonical command
digests, and only then an immutable signed result and publication. Repository
checks explicitly select `fixture_contract` and never start the retained
`live_probe`; fixture-only output is rejected by signing, verification, and
publication.
The executable signing and publication workflow is defined in
`docs/runbooks/agentic_certification_evidence.md`.

The operator probe on 2026-08-19 exposed the revision-8 contract defect: it sent
`parallel_tool_calls:false` while `require_parameters:true` excluded every
endpoint that did not declare that parameter, producing the expected
`provider_no_eligible_endpoint`. Revision 9 removes only the unsupported
parameter, retains strict routing, and keeps sequential execution fail-closed
in the decoder.

A real revision-9 canary on 2026-08-20 exposed a second interoperability edge:
DeepInfra occasionally streamed an additional tool proposal as a later array
index even though the shared runtime permits only one sequential execution per
step. Revision 10 retains only the fully validated index-0 call in private
continuation state. Later indexed proposals are neither emitted nor executed;
after the primary result is replayed, the model can request remaining work in a
new sequential step. A missing index-0 call or a conflicting second index-0
identity still fails closed. Revision 10 is historical and suspended.

Revision 11 carries the corrected shared hosted-loop budget accounting and
egress transformation contract. A provider request keeps a conservative
reservation until priced usage replaces it; missing usage remains charged at
the worst case. Absolute host paths found inside untrusted tool output are
redacted after exact workspace-root rewriting, while host paths from every
other provenance remain denied. Revision 11 is historical and suspended.

Revision 12 retained the exact `fake-data preview` warning label but removed fake
classification authority: its policy lists only Core-classified `public`, its
egress id is `remote-agentic-contained@2`, and central admission remains
NO-GO. It is now historical and suspended. A future policy could consider
`workspace_internal_fake` only with the
exact resource-derived classification and an active scoped workspace
attestation; neither declaration alone can create that class. Its suite-v9
manifest retained both `fixture_contract` and `live_probe`; the live step was
not run.

Revision 13 pinned adapter 6 and codec/schema 2 for the Phase-2 provider-step
journal, preliminary proposal ledger, staged-state promotion, complete indexed
call accounting, reconstructible plural pairing, effect ordering, and
productive recovery. Suite 10 and matrix `2026-08-27-r10-p2-tcb3` add the
JSON/document parity and Google/OpenRouter crash matrices to
`fixture_contract` and bind TCB manifest v3. Its retained `live_probe` was not
selected or run, and revision 13 is historical and suspended.

Revision 14 pins adapter 7, suite 11, matrix
`2026-08-27-r11-p2-tcb4`, and TCB manifest v4 for the terminal Phase-2 closure:
same-turn pairing ownership and input lineage, containment-first quarantine,
and private final-output outbox delivery across commit/restart crashes. The
retained `live_probe` was not selected or run, no behavioral evidence was
created, and this revision is now suspended and uncertified.

Revision 15 pins adapter 8, suite 12, matrix
`2026-08-27-r12-p3-tcb5`, and TCB manifest v5 for the Phase-3 finalization
closure: restart-safe provider/tool budgets, protected final/recovery
step-output-cost-deadline capacity, exact `tools: []` plus
`tool_choice: none`, whitespace rejection, journaled denial of unexpected final
calls, and at most one paired recovery. The retained `live_probe` was updated
to exercise the tool-less final request but was not selected or run. No
behavioral evidence or certificate was created; revision 15 is suspended and
uncertified.

Revision 16 pins adapter 9, suite 13, matrix
`2026-08-28-r13-p3-review-tcb5`, and TCB manifest v5 for the Phase-3 review
closure. The finalization instruction is wire-only and cannot contaminate a
later turn's private history; candidate egress decisions remain staged until
request-specific cost eligibility succeeds; unaffordable exploration falls
back to tool-less finalization; synchronous tools are deadline-fenced; and the
cost reserve covers a maximum policy-admitted result. No live or behavioral
run was performed; revision 16 is suspended and uncertified.

Revision 17 pins adapter 10, suite 14, matrix
`2026-08-28-r14-p3-review2-tcb5`, and TCB manifest v5 for the second Phase-3
review closure. Timeout publishes the deterministic terminal error by ledger
CAS before private result I/O, success rechecks its lease after that I/O, and
the per-attempt allocation covers a complete terminal request at the hosted
input ceiling. No live or behavioral run has been performed; revision 17
is suspended and uncertified.

Revision 18 pins adapter 11, suite 15, matrix
`2026-08-28-r15-p3-review3-tcb5`, and TCB manifest v5 for the third Phase-3
review closure. The `executing` ledger state persists a unique lease id and UTC
expiry; terminal success atomically requires the expected revision, the same
lease, and a future deadline. Local JSON rechecks immediately before atomic
replacement and Mongo uses server `$$NOW`. Deterministic coverage pauses the
worker after its final cooperative check while delaying the timeout CAS, and
proves that expired success cannot become authoritative. No live or behavioral
run has been performed; revision 18 remains a contained, uncertified preview.

## Fail-closed conditions

- Any model, protocol, API-version, adapter, endpoint, quantization, or upstream
  mismatch is rejected.
- `allow_fallbacks=true`, missing parameter enforcement, collection other than
  `deny`, or missing ZDR enforcement is rejected before transport.
- Sending `parallel_tool_calls` while the pinned endpoint does not declare it is
  a request-contract and catalog-preflight failure.
- A 404/no-eligible-provider result is terminal and never falls back.
- Missing, expired, revoked, or digest-mismatched certificates prevent authority.
- Missing or disabled credential bindings prevent session pinning.
- Unknown data classification is denied before transport.
- Function results with a different id or name are rejected before transport.
- Every contiguous indexed tool call is persisted. Duplicate ids, missing
  indices, or conflicting fragments fail closed. A multi-call response is
  completely dispositioned: calls inside the remaining budget receive
  `parallel_denied`, overflow receives `budget_denied`, and no call executes.
- Finalization must carry no tool definitions, the exact Core instruction, an
  empty `tools` array, and `tool_choice: none`; any mismatch fails before
  transport. Empty/whitespace output is rolled back, and only one paired
  recovery follows an unexpected journaled finalization call.
- A requested reasoning effort outside the immutable certificate tuple, or a
  certificate/binding reasoning-contract mismatch, is rejected before use.
- A single tool call preceded by text is accepted; that text remains
  provisional, is stored with the assistant tool call in private continuation
  state, and is not duplicated in the final answer.
- Redirects, unexpected paths, non-SSE responses, oversized data, incomplete
  streams, and missing terminal routing metadata are rejected.
- Credentials, raw errors, router payloads, and reasoning details never enter
  public runtime events.
