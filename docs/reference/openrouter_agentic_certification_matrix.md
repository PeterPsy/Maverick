# OpenRouter DeepSeek agentic certification matrix

Status date: 2026-08-27
Matrix revision: `2026-08-27-r11-p2-tcb4`
Rollout: candidate preview, not certified
Runtime engine: `maverick-tool-loop`  
Adapter: `maverick-hosted-tool-loop==7`

## Candidate combination

| Field | Pinned value |
| --- | --- |
| Model provider | `openrouter` |
| Model | `deepseek/deepseek-v4-flash` |
| Immutable profile revision | `14` (revision `13` suspended) |
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
| Certified execution TCB | manifest v4 plus six static import-closure contracts cover every authority/content-changing Core, Chat, Settings, codec, transport, journal/recovery, store, policy, package initializer, and generalist-context dependency; drift rejects signing/verification/publication/binding/live status | not certified |
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
| Containment independence | diagnostic/private-payload failure, first journal CAS conflict, unavailable journal CAS, and runtime projection fault still preserve session quarantine whenever the session CAS succeeds | not certified |
| Outage after acceptance | terminal normalized failure with no blind retry | not certified |
| Revocation and egress drift | mid-step revocation, live-policy drift, workspace-path rewriting, tool-result host-path redaction, and non-tool denial fixtures | not certified |
| Private-state failure | explicit quota, integrity, and recovery-reason fixtures | not certified |
| Prompt-injection containment | untrusted tool output cannot expand materialized tools | not certified |
| Child-agent isolation | forked immutable binding and independent private state | not certified |
| Live capability probe | operator-only catalog/ZDR preflight, then three sequential real-filesystem-list rounds plus final response at every certificate-bound reasoning effort | manifest step available; not run for r11 |

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
created, and this candidate remains suspended and uncertified.

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
  indices, or conflicting fragments fail closed; a multi-call response receives
  complete `parallel_denied` dispositions and no call executes.
- A requested reasoning effort outside the immutable certificate tuple, or a
  certificate/binding reasoning-contract mismatch, is rejected before use.
- A single tool call preceded by text is accepted; that text remains
  provisional, is stored with the assistant tool call in private continuation
  state, and is not duplicated in the final answer.
- Redirects, unexpected paths, non-SSE responses, oversized data, incomplete
  streams, and missing terminal routing metadata are rejected.
- Credentials, raw errors, router payloads, and reasoning details never enter
  public runtime events.
