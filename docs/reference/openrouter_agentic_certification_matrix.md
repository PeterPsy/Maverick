# OpenRouter DeepSeek agentic certification matrix

Status date: 2026-09-06
Matrix revision: `2026-09-06-r46-p6-isolated-lab-tcb36`
Rollout: Full Workspace preview, not certified
Runtime engine: `maverick-tool-loop`  
Adapter: `maverick-hosted-tool-loop==42`

## P6 candidate checkpoint

This delta additionally binds the isolated typed laboratory, shared authority
lattice/store composition, Settings exact-revision grouping, and post-pacing
job fence. Lab observations are not certification or production-release evidence.
See `docs/architecture/certification_lab.md`. Recipes remain unchanged: the
new adapter/profile/suite/TCB identities bind the authorization-composition change.


Suite 46 / TCB manifest 36 / hosted adapter 42 / recipe 25 bind
fresh-attestation admission, production-composed API-to-final submission,
retained evidence with reparsed step receipts, independent publisher trust and the durable aggregate budget
to the existing P0–P5 corpus. The new profile is immutable, unbound and uncertified.
The prior suite-41/42/43/44/45 deterministic receipts
are historical, not evidence for this delta. Codex's shared queue/handoff change
has its own explicit revision 16; no source is excluded from its artifact.
See `docs/development/agentic_p6_runtime_publication_delta.md` for the scope and
remaining live, laboratory, independent review and release requirements.

## Tools-omitted protocol follow-up (not yet recertified)

The isolated protocol follow-up replaces explicit-none finalization with the
contract in `docs/architecture/openrouter_finalization_contract.md`. Numeric
identities above name the combined new candidate, **not approval for it**;
full exact-source verification and all remaining P6 gates are required before
publication or operational deployment. Observed `supports_tool_choice.none=false` stays false. The new
method offers no tools and sends neither tool parameter. Unsolicited final
calls remain pairable for core denial/recovery; they cannot authorize tool
execution or successful user-turn finalization.

## Preview combination

| Field | Pinned value |
| --- | --- |
| Model provider | `openrouter` |
| Model | `deepseek/deepseek-v4-flash` |
| Model revision policy | `provider_alias`; identity `openrouter-catalog-2026-08-17`, with exact endpoint/upstream catalog constraints |
| Immutable profile revision | `50` (revision `49` suspended) |
| Execution family | `maverick_agent`; atomically pinned to Full Workspace `codex-baseline-v20` |
| Protocol | OpenAI-compatible streaming Chat Completions |
| API version | `v1` |
| Protocol adapter | `openrouter-chat-completions-protocol@3` |
| Provider config | `openrouter-deepinfra-fp8@2`; digest `5ed02612baa9f19b1af3f361ff7fbf4d9f943fe1d03a32a23c210935dc92c66e` |
| Endpoint | `https://openrouter.ai/api/v1/chat/completions` |
| Upstream endpoint tag | `deepinfra/fp8` |
| Effective provider identity | `DeepInfra` |
| Quantization | `fp8` |
| Context / endpoint completion limit | 1,048,576 / 65,536 tokens |
| Tool calls | every indexed call is retained; execution remains sequential, so a multi-call response is denied and paired in full |
| Parallel request control | parameter omitted because the certified endpoint catalog does not declare it; Core journals every returned call before `parallel_denied` |
| Private codec | `openrouter-chat-completions@3`, schema `2`; ordered plural pending calls and no silent migration |
| Mixed response handling | provisional text plus one tool call is retained privately and continued |
| Reasoning levels | `minimal`, `low`, `medium`, `high`; deployed default `high` |
| Router controls | fallback off, parameters required, collection denied, ZDR required |
| Accounting policy | `openrouter-deepinfra-deepseek-v4-flash-public-list-price@1`; 90,000 / 180,000 micro-USD per million input/output tokens |
| Finalization reserve | one 2,048-token / 35,000-micro-USD / 20-second final request plus one equal recovery |
| Turn cost ceiling | 250,000 micro-USD; 70,000 remains protected for the two terminal attempts |
| Final request | exact Core finalization instruction; omit both `tools` and `tool_choice`; unsolicited tool-bearing terminal fails closed |
| Remote data classes | `public` (Core-classified only; remote admission remains blocked) |
| Policy surfaces | exact `cli`, `mcp`, `app-interface`, and `core-capability` set plus every Full Workspace wrapper handle; the public resolver must produce complete live authority |
| Tool handles | Full Workspace `codex-baseline-v20` surface: all 24 result behaviors execute under exact source taint, an active operator-owned runtime-public policy, or a certified Core result projection; only complete probe evidence is cached, while transient/partial results remain retryable; app reads require a Core-audited descriptor plus executable closure and are rechecked at dispatch, inter-agent CLI/MCP operations have exact effects and content-dropping projections, raw/base64/chunked reads retain complete-resource taint, provider transport revalidates authority plus the freshly read nonnumeric policy before every stream advance, and shell/process effects remain rollbackable over an immutable `.git`-excluding snapshot in read-only and overlay modes; `artifact.read`, app discovery, all-worker quiescence, and post-SIGTERM cleanup remain covered |
| Certificate lifetime after a successful signed run | 30 days |

Historical P5: revision 43 and provider-config revision 2 add the exact executable
config/protocol-adapter identity and config-owned endpoint, upstream/provider/
resolved-model, quantization, and accounting data. They have no signed suite-39
result; the unchanged matrix revision describes the required rerun, not
certification evidence. The preview remains contained and unavailable.

The current OpenRouter model catalog lists `deepinfra/fp8` as active for
DeepSeek V4 Flash, with `tools`, `tool_choice`, `reasoning`, `max_tokens`, and
`reasoning_effort` support, but reports `supports_tool_choice.none=false`.
Neither catalog declares `parallel_tool_calls`. The endpoint exposes FP8
quantization; the recorded list price is $0.09 per million input tokens and
$0.18 per million output tokens.
The certification probe fetches both official catalogs immediately before any
completion request and fails unless this exact record is active, ZDR-listed,
large enough for the requested completion budget, and supports every parameter
the translated payload sends that participates in endpoint parameter routing.
Historically, suite 39 and the suite-41 freeze required
`supports_tool_choice.none=true` in both exact records, so the current record
correctly blocks that explicit-none contract. The tools-omitted follow-up changes
the method rather than relabeling this capability; it still requires new live
evidence and certification. A changed endpoint or
upstream requires a new recipe/catalog digest and immutable profile revision.

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
| Semantic envelope | schema v1 and projection compiler `maverick-hosted-semantic-projection@10`; exact byte-bound classifications, conservative Luhn detection inside hexadecimal text/JSON, payload-bound typed projection of authenticated server-owned attachment and Core tool-result identity metadata, lexical no-symlink skill identity, restrictive attachment metadata/file joins, immutable server-observed attachment read fences, production exact-resource app-reference classification, attachment-only admission without an empty prompt, complete scoped `AGENTS.md` materialization, UTF-8/base64 attachment references, provider projection digest, authority lineage revalidation, policy-narrowed live semantic revalidation for skill/app-reference blocks on tool-less requests, and journal evidence | not certified |
| Certified execution TCB | manifest v35 plus six static import-closure contracts and the exact hosted built-in app execution roots, validated by effect audit `2026-09-06-p6-builtin-effects-reviewed-v4`, cover every authority/content-changing Core, Chat, Settings, app entrypoint/dependency closure, semantic compiler, recipe/context/preflight/artifact surface, input/result admission, raw-resource classification, typed tool-result classification projection, request/transport revalidation, success-only behavior-probe caching, full-workspace confinement/process/discovery/snapshot/effect-overlay/batch/metadata guard, codec, transport, journal/recovery, store/audit CAS, policy, package initializer, and generalist-context dependency; a content-bound filesystem fence invalidates the lightweight per-event check without rehashing source bytes | not certified |
| Endpoint catalog preflight | exact model and ZDR records must both support every endpoint-gated translated parameter, automatic tool selection, DeepInfra FP8 identity, active status, total input-plus-output context, and completion budget | not certified |
| SSE ordering and bounds | shared bounded SSE plus OpenRouter transport fixtures | not certified |
| Effective upstream | response identity and terminal router-metadata mismatch fixtures | not certified |
| No eligible endpoint | HTTP and streamed 404 normalization fixtures | not certified |
| Tool call id/name/count | fragmented/malformed arguments, all contiguous indices, preliminary persistence, exact replay/divergence, duplicate-id rejection, full parallel denial, and ordered plural pairing | not certified |
| Mixed text then tool | provisional narration is not finalized or duplicated; one call continues to the next step | not certified |
| Multi-step continuation | deterministic fixtures for three sequential tool rounds followed by a final response at every reasoning effort | not certified |
| Filesystem discovery | descriptor-relative race-safe listing plus provider alias → shared loop → real `filesystem.list` handler → provider result round trip | not certified |
| Harness recipe and context | exact recipe id/revision/digest plus fine-grained provider-capability catalog digest; independent complete-request reserve, one forced below-trigger compaction, pairing-safe semantic history compaction, request-scoped authority replacement, bounded byte-correct tool-result artifacts, explicit attachment workspace references, and safe-next-turn steering fallback | not certified |
| Full Workspace behavioral gate | `codex-baseline-v20` executes 16 concrete filesystem, shell/process, and CLI/MCP capability paths, one production-composed inter-agent CLI-create/MCP-wait workflow, plus seven security probes covering raw/base64/chunk marker narrowing, revoke-then-rebuild, delayed-egress-after-revocation, full-authority/credential/policy revocation at the transport boundary, revoke-between-provider-events, overlay-commit rollback, and concurrent shell/process `.git` snapshots; incomplete or transient probe evidence is never cached | repository gate complete: 24/24 behaviors; signed provider certification not run |
| Reasoning configuration | real tool round trips at every certificate-bound level, including immutable default `high` | not certified |
| Reasoning isolation | exact private `reasoning_details` replay and public-event leakage assertions | not certified |
| Usage, generation id and price | success and decode-failure fixtures retain telemetry; active request reservations reconcile to reported micro-USD while missing usage remains worst-case | not certified |
| Failure propagation | distinct mixed/parallel/index codes, safe public message, diagnostic reference, and nonnumeric Chat UX | not certified |
| Shared tool loop | real OpenRouter codec through deterministic hosted-loop E2E | not certified |
| Cancel/recovery/confirmation | startup, pre-admission, pre-prepare, worker-loss and uncertain-cancellation recovery; crash after every journal/state/effect/pairing transition; repeated restart without duplicate effect | not certified |
| Turn lineage and terminal pairing | exact source journal/turn/request/input lineage; ordinary cross-turn input rejected before transport; limits, cancellation and revocation leave no ready pairing on a running session | not certified |
| Final-output delivery | private outbox before commit; crash before either terminal event replays one stable output with one provider request and no duplicate event across repeated restart | not certified |
| Governed finalization | separate durable step/tool budgets; full step/output/cost/time reserve covering a complete terminal request at the hosted input ceiling; request-specific staged preflight with tool-less fallback before egress commit; tool-call and cumulative result-byte exhaustion, including live tightening after preparation, rebuild finalization without exposing tools; persisted execution lease whose live deadline is part of the terminal success CAS; both tool parameters omitted; exact request-scoped final instruction after paired results; whitespace rollback; unexpected call gets journaled `budget_denied`, one recovery, then quarantine | not certified |
| Containment independence | diagnostic/private-payload failure, first journal CAS conflict, unavailable journal CAS, and runtime projection fault still preserve session quarantine whenever the session CAS succeeds | not certified |
| Outage after acceptance | terminal normalized failure with no blind retry | not certified |
| Revocation and egress drift | complete authority refresh after endpoint preflight and before lazy transport open; the request's data classes, catalog handles, surfaces, filesystem/shell flags, and complete semantic capability projection are then revalidated against the freshly policy-narrowed live authority, including skill/app-reference blocks without tools; the endpoint snapshot and transport share one process-local redaction-safe credential fingerprint; live policy tightens the active reservation and checks its finalization deadline at every boundary; later SSE advances use a lightweight certificate/binding/actor/feature/health/TCB/classification/credential revocation fence instead of rerunning the full TCB and behavior gates | not certified |
| Private-state failure | explicit quota, integrity, and recovery-reason fixtures | not certified |
| Prompt-injection containment | untrusted tool output cannot expand materialized tools | not certified |
| Child-agent isolation | forked immutable binding and independent private state | not certified |
| Live capability probe | operator-only catalog/ZDR preflight of actual translated parameters and total context capacity, then three sequential real-filesystem-list rounds plus one explicitly tool-less final response at every certificate-bound reasoning effort | manifest step available; not run for r40 |

The table defines required coverage and does not report a completed run.
Bootstrap publishes only the uncertified preview profile and never manufactures a
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

Revision 19 pins adapter 12, suite 16, matrix
`2026-08-28-r16-p4a-semantic-envelope-tcb6`, and TCB manifest v6 for Phase 4A.
Every request is compiled from a Core-owned semantic envelope v1 with distinct
platform, runtime, workspace, agent, user, governed-context, attachment, app,
skill, tool, and provider-state blocks. Complete bounded `AGENTS.md` and
`SKILL.md` materialization is descriptor-confined and version-fenced; source
snapshot and exact egress projection evidence are persisted in provider-step
journal schema v4. No live or behavioral run has been performed; revision 19
remains a contained, uncertified preview.

Revision 20 pins adapter 13, suite 17, matrix
`2026-08-28-r17-p4b-full-workspace-tcb7`, and TCB manifest v7 for Phase 4B.
The adapter now contains the complete code-owned Full Workspace tool surface,
descriptor/race confinement, platform-runtime masking, managed-process
lifecycle, official discovery-first CLI/MCP registries, and shared result
compaction. This contained profile deliberately retains only list/read handles
and does not claim `full_workspace_contract_revision`; Phase 4D must create a
new full revision after exact endpoint and interaction closure. No live or
behavioral run has been performed; revision 20 remains an uncertified preview.

Revision 21 pins adapter 14, suite 18, matrix
`2026-08-28-r18-p4-context-provider-closure-tcb8`, and TCB manifest v8 for
Phase 4C-D. It is a new, uncertified full-workspace candidate rather than a
promotion of revision 20. The immutable recipe selects the exact OpenRouter
Chat/DeepInfra FP8 composition, compiler revision 2, `codex-baseline-v2`, an
independent context reserve and pairing-safe compaction, bounded
artifact-backed tool results, explicit attachment references and
safe-next-turn steering fallback. Every request performs the exact live
catalog/ZDR and wire preflight before egress commit; final requests require
`tools: []` and `tool_choice: none`. No live or behavioral run, certificate,
binding, provider request, canary, or remote activation has been performed.

Revision 22 pins adapter 15, recipe 2, suite 19, matrix
`2026-08-28-r19-p4-review-closure-tcb9`, and TCB manifest v9. It closes the P4
review findings with production request/result classification, mandatory
commit-bound `AGENTS.md` guards, request-scoped system/developer reinjection,
truthful persisted projection evidence, semantic compaction schema 2, and
binary attachment reads. Compiler revision 3 and `codex-baseline-v3` bind the
behavior changes. This remains an uncertified, unbound, unavailable candidate;
no live probe, behavioral run, provider completion, certificate, canary, or
remote activation has been performed.

Revision 23 pins adapter 16, recipe 3, suite 20, matrix
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

Revision 24 pins adapter 17, recipe 4, suite 21, matrix
`2026-08-29-r21-p4-composite-atomic-closure-tcb11`, and TCB manifest v11.
Compiler revision 5 binds semantic classes to exact projected bytes, joins
attachment metadata with the referenced resource, and projects exact skill
documents. `codex-baseline-v5` adds rollback-safe multi-file overlay commit,
explicit directory-effect rejection, and mutating/non-retry-safe terminal
process polling. This candidate remains uncertified, unbound, and unavailable;
no live probe, behavioral run, provider completion, certificate, canary, or
remote activation has been performed.

Revision 25 pins adapter 18, recipe 5, suite 22, matrix
`2026-08-29-r22-p4-metadata-appref-closure-tcb12`, and TCB manifest v12.
`codex-baseline-v6` preserves mode/ownership/ACL/xattrs for content-only
replacement, rejects unrepresented xattr/timestamp/overlay-root metadata, and
wires exact app-reference resource classification into production bootstrap.
This candidate remains uncertified, unbound, and unavailable; no live probe,
behavioral run, provider completion, certificate, canary, or remote activation
has been performed.

Revision 26 pins adapter 19, recipe 6, suite 23, matrix
`2026-08-29-r23-p4-cow-fidelity-closure-tcb13`, and TCB manifest v13.
`codex-baseline-v7` descriptor-pins every retained pre-image and compares its
complete metadata/xattr snapshot around exchange, applies exact file
atime/mtime for content effects, admits ordinary read-modify-write, and rejects
new or existing hardlinks plus non-representable directory/root metadata. This
candidate remains uncertified, unbound, and unavailable; no live probe,
behavioral run, provider completion, certificate, canary, or remote activation
has been performed.

Revision 27 pins adapter 20, recipe 7, suite 24, matrix
`2026-08-30-r24-p4-agentic-parity-closure-tcb14`, and TCB manifest v14.
`codex-baseline-v8` installs production transient-input admission, safe
action-result projection and pre-image taint, byte-correct artifact summaries,
cancellation-quiescent copy-on-write execution, adapter-owned process cleanup,
and a complete-request compaction retry. This candidate remains uncertified,
unbound, and unavailable; no live probe, behavioral run, provider completion,
certificate, canary, or remote activation has been performed.

Revision 29 pins adapter 22, governed recipe 9, suite 26, matrix
`2026-08-30-r26-p4-agentic-review-closure-tcb16`, and TCB manifest v16.
Production now atomically captures content-derived transient/governed-context
classification, preserves complete read-only variable results with public error
pairing on egress denial, denies unguaranteed mutations before effect, awaits all
synchronous workers on cancellation, and performs repeated post-SIGTERM process
sweeps. `codex-baseline-v10` reports the remaining mutating result scenarios as
incomplete, so this profile does not claim Full Workspace. It remains
uncertified, unbound, and unavailable; no live probe, behavioral run, provider
completion, certificate, canary, or remote activation has been performed.

Revision 30 pins adapter 23, governed recipe 10, suite 27, matrix
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

Revision 32 pins adapter 25, governed recipe 12, suite 29, matrix
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

Revision 33 pins adapter 26, governed recipe 13, suite 30, matrix
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

Revision 34 pins adapter 27, governed recipe 14, suite 31, matrix
`2026-09-01-r31-p4-review-closure-model-revision-tcb21`, and TCB manifest v21.
The explicit OpenRouter provider-alias model revision policy is now carried by
the profile, certificate, binding, recipe, request, and authority while exact
endpoint/upstream catalog constraints remain mandatory. Every built-in app
CLI/MCP surface has conservative effect metadata and real Storage read probes;
shell and managed processes mask `.git`; mutable authority is checked before
every provider-stream advance; and the oversized P4 tests are split and
retained in the certification manifest. The production-composed
`codex-baseline-v14` gate returns all 20 required behaviors. The immutable
definition remains uncertified, unbound, contained, and unavailable; no live
probe, signed run, provider completion, certificate, canary, or remote
activation has been performed.

Revision 35 pins adapter 28, governed recipe 15, suite 32, matrix
`2026-09-02-r32-p4-git-effect-authority-tcb22`, and TCB manifest v22. Core now
recursively masks root and nested Git directories/worktree pointers in shell
and managed-process read-only and overlay mounts. Hosted built-in app reads
require the exact Core-owned descriptor audit; Website Studio preview creation
and document caching are mutating, while persistent pre/post tests cover every
remaining declared read. The strengthened `codex-baseline-v15` gate remains
20/20. The immutable definition remains uncertified, unbound, contained, and
unavailable; no live probe, signed run, provider completion, certificate,
canary, or remote activation has been performed.

Revision 36 pins adapter 29, governed recipe 16, suite 33, matrix
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

Revision 37 pinned adapter 30, governed recipe 17, semantic compiler 9, suite
34, matrix `2026-09-03-r34-p4-last-mile-attachment-process-tcb24`, and TCB
manifest v24. Attachment reads received immutable server-observed fences, and
`codex-baseline-v17` replaced synthetic shell/process/CLI/MCP claims with 16
concrete capability paths, one inter-agent workflow, and seven security probes
for a 24/24 repository gate.

Revision 38 pinned adapter 31, governed recipe 18, semantic compiler 10, suite
35, matrix `2026-09-03-r35-p4-policy-credential-stream-fence-tcb25`, and TCB
manifest v25. The last-mile guard tightened live policy and active deadlines,
bound endpoint discovery to the transport credential fingerprint, and separated
full request/open checks from the cheaper per-event revocation fence.

Revision 39 pins adapter 32, governed recipe 19, semantic compiler 10, suite
36, matrix `2026-09-03-r36-p4-policy-egress-probe-cache-tcb26`, and TCB
manifest v26. The last-mile guard validates request data classes and the exact
catalog/surface capability set against the policy read after each authority
refresh, including the refresh inside lazy transport opening. Full Workspace
behavior probes cache only complete successful evidence; transient, empty, or
partial results remain retryable. The immutable definition remains uncertified,
unbound, contained, and unavailable; no live probe, signed run, provider
completion, certificate, canary, or remote activation has been performed.

Revision 40 pins adapter 33, governed recipe 20, semantic compiler 10, suite
37, matrix `2026-09-03-r37-p4-semantic-budget-authority-tcb27`, and TCB
manifest v27. Live policy is projected over every semantic capability, including
app references and skills on tool-less requests; tool-call and cumulative
result-byte exhaustion rebuild an uncommitted request as finalization; and the
profile plus Full Workspace contract require the distinct CLI, MCP,
app-interface, and Core-capability surfaces. Built-in effect audit
`2026-09-06-p6-builtin-effects-reviewed-v4` binds the reviewed Fitness Coach,
Storage, and Website Studio read-model closure updates. The immutable definition
remains uncertified, unbound, contained, and unavailable; no live probe, signed
run, provider completion, certificate, canary, or remote activation has been
performed.

Revision 41 pins adapter 34, governed recipe 21, semantic compiler 10, suite
38, matrix `2026-09-04-r38-p4-pan-classification-determinism-tcb28`, and TCB
manifest v28. The generic scanner no longer exempts long hexadecimal tokens,
and regression coverage keeps embedded PANs sensitive for raw text, JSON,
runtime-public input, and declared-public tool output. Only exact typed
attachment-fence identity is removed from the scan surface. Runtime-public
policy v3 invalidates older mutable-authority lineage, while the hosted
finalization deadline fixture now uses controlled time and leaves no delayed
worker behind. The immutable definition remains uncertified, unbound,
contained, and unavailable; no live probe, signed run, provider completion,
certificate, canary, or remote activation has been performed.

Revision 42 pins adapter 35, governed recipe 22, semantic compiler 10, suite
39, matrix `2026-09-04-r39-p4-typed-result-classification-tcb29`, and TCB
manifest v29. Exact Core filesystem, instruction, process, discovery, artifact,
certified inter-agent, and compactor metadata now use typed classification
projections bound to the complete unmodified result. This removes accidental
Luhn matches from server-owned digests without restoring a lexical hex bypass;
paths, content, shell output, discovery descriptions, and arbitrary tool values
remain conservatively scanned. The immutable definition remains uncertified,
unbound, contained, and unavailable; no live probe, signed run, provider
completion, certificate, canary, or remote activation has been performed.

Revision 43 retains adapter 35, governed recipe 22, semantic compiler 10, suite
39, matrix `2026-09-04-r39-p4-typed-result-classification-tcb29`, and TCB
manifest v29. It additionally binds provider config
`openrouter-deepinfra-fp8@2` and protocol adapter
`openrouter-chat-completions-protocol@3` in the profile, future certificate,
execution binding, actual transport route, upstream/provider/resolved-model
checks, and config-owned price policy. The immutable definition remains
uncertified, unbound, contained, and unavailable; no live probe, signed run,
provider completion, certificate, canary, or remote activation has been
performed.

## Fail-closed conditions

- Any model, provider-alias revision policy, protocol, API-version,
  protocol-adapter, provider-config, endpoint, accounting policy, effective
  provider/resolved model, quantization, or upstream mismatch is rejected.
- `allow_fallbacks=true`, missing parameter enforcement, collection other than
  `deny`, or missing ZDR enforcement is rejected before transport.
- Sending `parallel_tool_calls` while the pinned endpoint does not declare it is
  a request-contract and catalog-preflight failure.
- A 404/no-eligible-provider result is terminal and never falls back.
- Missing, expired, revoked, or digest-mismatched certificates prevent authority.
- Missing or disabled credential bindings prevent session pinning.
- Unknown data classification is denied before transport.
- Unknown app CLI/MCP effect discriminators are `unclassified`; app mutations
  without a certified pre-effect result guarantee are denied.
- Function results with a different id or name are rejected before transport.
- Every contiguous indexed tool call is persisted. Duplicate ids, missing
  indices, or conflicting fragments fail closed. A multi-call response is
  completely dispositioned: calls inside the remaining budget receive
  `parallel_denied`, overflow receives `budget_denied`, and no call executes.
- Finalization must carry no tool definitions and the exact Core instruction;
  both `tools` and `tool_choice` must be absent. Any mismatch fails before
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
