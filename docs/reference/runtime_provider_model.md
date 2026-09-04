# Runtime Provider Model

## Overview

The runtime layer is provider-backed.

Maverick owns:

- runtime session lifecycle
- turn lifecycle
- execution policy
- workspace context
- streaming and persistence of runtime events
- compaction of large persisted `runtime.tool_call.*` event payloads

The runtime engine adapter owns:

- provider preparation and recovery
- provider session or thread linking
- provider-specific protocol translation
- cancellation and resource closure
- optional same-turn message admission when the provider declares `supports_same_turn_input`

Local process launch is an optional lifecycle capability, not a requirement of
an agentic runtime.

## Pinned Agentic Session Identity

Agentic sessions no longer resolve their runtime from the mutable workspace
`ProviderSelection` after creation. The Core resolves a selectable
`WorkspaceAgenticProfileBinding`, snapshots its immutable installation-level
`AgenticProfileDefinition`, adapter artifact, exact model, routing constraint,
credential reference, execution mode, and policy ceilings into the nested
`RuntimeExecutionBinding`, and inserts that binding with the session aggregate.
Changing the Settings default therefore affects only later sessions.

Session creation uses that aggregate as a persisted publication barrier. A new
record is inserted with `preparation_status=unprepared`; Core then initializes
provider state (when bound) and the runtime-state snapshot idempotently, and
publishes `prepared` with a one-way compare-and-set. An exact retry repairs any
missing initialization writes, while a retry with different aggregate identity
is rejected. Neither the `running` transition nor the provider-start handoff
accepts an unprepared session. Records predating this barrier hydrate as
prepared because the former creation API returned only after initialization.

Mutable continuation metadata is stored separately in
`RuntimeProviderState`. Provider thread updates use exact-revision
compare-and-set and are projected onto the legacy session response only for
read compatibility. Chat sends `workspace_profile_binding_id` with a new
session choice and never mutates the Settings default. Child sessions receive a
new immutable binding derived from the parent but start with independent
provider state.

The schema migration publishes preview Codex definitions and workspace
bindings from legacy selections, pins unambiguous existing agentic sessions,
and moves their provider thread into revision-zero provider state. Ambiguous
legacy sessions remain readable but are not continued without a proven
execution binding. Runtime resolution no longer falls back to the legacy
workspace provider selection: every executable agentic session resolves only
from its immutable binding, while `/api/providers/active` is a projection of
the workspace-default agentic binding for remaining status consumers.

## Provider-Neutral Async Engine Contract

Pinned agentic sessions execute through `AgenticRuntimeEngineAdapter`. Its
validation, preparation, cancellation, recovery, close, and health operations
are asynchronous; execution produces an ordered async stream of typed runtime
events carrying a correlation id, ordinal, schema version, and bounded payload.
Core validates stream ordering and correlation before translating events into
the durable runtime event model.

`LocalProcessRuntimeLifecycle` is present only for engines that actually need a
host process. Hosted engines prepare, execute, cancel, recover, and close with
no launch specification. The Codex backend currently runs behind the same
contract through a compatibility bridge while retaining its local lifecycle.
The common turn, prewarm, cancellation, and idle-close paths select behavior by
adapter capability and contain no Codex-specific dispatch branches.

The adapter may propose allowlisted updates to `RuntimeProviderState`; Core is
the only writer and applies them with revision fencing. Session APIs expose the
provider-neutral `runtime_ready` prewarm result separately from the legacy
`provider_thread_ready` projection, because a hosted engine can be ready
without creating a provider thread.

## Capability Certificates And Effective Authority

Agentic execution is fail-closed behind an immutable
`CapabilityCertificate`. The certificate identifies the exact engine, adapter
id/version/source digest, model provider, model, model revision and revision
policy, protocol, routing digest,
certified upstream set, capability set, evidence suite, certified-execution TCB
manifest/digest, and expiry. Evidence
metadata and optional content-addressed blobs are installation-owned; neither
workspace Storage nor an adapter controls their locators. Revocation lives in a
separate revisioned status record and therefore takes effect without rewriting
the certificate or a session binding.

Before session binding, prewarm, continuation, authority refresh, and every
pinned turn, Core verifies certificate identity, expiry/revocation, the current
code-owned TCB digest, live adapter artifact, credential reference, profile
status, workspace binding, and upstream constraint. TCB manifest v29 also
executes six static local-import audits across admission, input composition,
classification/egress, tool execution, provider state/lifecycle, and served
governance, and hashes the exact executable roots of every built-in app surface
admitted as a hosted read. Package initializers, the exact generalist
orchestration-context closure, and audited app-local execution bytes are
artifacts; any newly reached, uncovered dependency or app-code drift fails
identity/authority calculation. Core then computes one
`EffectiveRuntimeAuthority` by intersecting certificate capability, profile
policy ceiling, workspace binding, actor policy, live authority/catalog,
feature flags, and provider health. The snapshot distinguishes filesystem
read/write, shell, CLI, MCP, skill catalog, attachment modalities, app
references, confirmations, recovery, provider/upstream/data policy,
certificate/suite/expiry, and TCB posture. It is ephemeral and not a bearer
grant. Runtime events persist only its SHA-256 digest, revision set, capability
names, and counts; tool handles, credentials, and content are omitted. API,
Chat, and Settings use the same server-owned projection.

Session and turn preflight validate invoked skills, every attachment modality,
app references, CLI/MCP/shell requests, and filesystem write intent against
that snapshot before claims, prepared locks, sessions, turns, queues, or
provider work are persisted. Unsupported context yields one public allowlisted
reason code; it is never ignored or merely omitted from the provider request.

Hosted provider input is first compiled as Core semantic-envelope schema v1.
Platform, runtime, capability, workspace `AGENTS.md`, agent, user,
governed-context, attachment, app-reference, complete invoked-skill, tool, and
provider-state sources remain separate typed blocks. Complete instruction files
are read through the confined filesystem with identity/revision fencing and the
applicable root-to-workdir instruction chain is recomputed for every provider
step. The source snapshot digest is distinct from the versioned provider
projection digest; both and the compiler identity are journaled without source
content. A mandatory block that cannot be classified, materialized, or
projected aborts before provider transport.

Each block classification is bound to its exact canonical byte digest.
Composite attachment metadata is independently admitted and restrictively
joined with the referenced file classification. The model-visible workspace
reference includes the exact server-observed resource identity, revision,
digest, and MIME-derived UTF-8/base64 encoding. Core injects that immutable
fence into every matching `filesystem.read`, including the first chunk and
filesystem-equivalent path spellings; client metadata is not runtime authority.
Skills project exact
`SKILL.md` content instead of unbound catalog metadata. Attachment-only input
omits an empty prompt. Hosted shell/process text effects use a rollback-safe
multi-file transaction, preserve existing mode/owner/ACL/xattrs, carry exact
file atime/mtime for content effects, and retain a descriptor-pinned complete
pre-image metadata snapshot across exchange. Metadata-only directory/root
timestamps and xattrs are rejected, as are upper or existing hardlinks that the
text transaction cannot reproduce. Terminal process polling is
mutating/non-retry-safe because it commits the overlay. App references use an
exact server-materialized resource
observation resolved by production `PlatformState` against the workspace
classification store; metadata classification alone cannot make them public.

Hosted full-workspace bindings additionally pin the execution family, harness
recipe and digest, fine-grained provider-capability catalog digest, semantic
compiler, tool contract, and context policy. The generic runtime registry must
resolve that exact model/protocol/API/endpoint/upstream/reasoning composition.
Context admission preserves an independent reserve; deterministic compaction
retains authority/provenance evidence and current-turn tool pairing. Reserve
validation covers the complete request and may force one recipe-bound
compaction/rebuild below the ordinary private-state trigger. Large
results become session-owned artifact references, attachments become explicit
authorized workspace references, and hosted steering reports a safe-next-turn
fallback when same-turn delivery is not certified. Recipe-specific endpoint
preflight runs before staged egress is committed or the completion transport is
opened. After that potentially slow preflight, one last-mile guard refreshes
full certificate, binding, feature, actor, health, policy, Full Workspace, and
credential authorization, then validates the prepared request's remote classes,
catalog handles, surfaces, and filesystem/shell flags against the freshly read
policy. It also rebuilds the semantic capability projection from that
policy-narrowed authority, so app-reference, skill, and runtime-capability
blocks are fenced even when the request is tool-less. The full guard runs in
the task that opens and first advances the lazy transport. Every subsequent
provider event uses the cheap mutable-authority/TCB
metadata, classification, credential, policy, and deadline fence.

The product execution-family catalog is Core-owned and ordered as
`native_agent`, `maverick_agent`, then `hosted_text`. Native installations bind
five independent records: a structured adapter manifest, an immutable harness
recipe, one or more model selections, a sandbox/effect-observation contract,
and a certificate reference. `ProviderRegistry` validates this composition and
exposes a structured controller for discovery/version/health/update status,
launch, connect, resume, event streaming/final output, steering, interrupt,
recovery, cleanup, and close. A candidate cannot acquire an executable
controller or become active merely from provider capability metadata. Exact
legacy Codex identity is the sole safe family inference for profiles created
before the family field; arbitrary vendor labels and flags are never used for
that inference. The discovery-only Gemini CLI candidate demonstrates a second
native registration while remaining hard-disabled until full certification.

For the Maverick-owned API loop, onboarding records are data rather than Core
loop branches. `MaverickProtocolAdapterManifest` identifies the trusted
transport/codecs/private-state/usage/cancellation/recovery implementation;
`MaverickProviderConfig` pins endpoint, upstream, routing, credential, retention,
and destination policy; `HostedHarnessRecipeManifest` owns the semantic/tool and
context recipe; and `AgenticProfileDefinition` is the exact immutable model
profile. The onboarding catalog can build the existing provider runtime registry
from trusted factories and these records. Candidate discovery records vendor
metadata only as an observation digest with no family or authority. Immutable
publication rejects in-place tuple drift and refuses `maverick_agent`
classification until the Full Workspace revision, complete tool set, context
contract, streaming, usage accounting, tool calling, and cancellation contract
all match.

`hosted_text` is not an incomplete agent profile. Its immutable
`HostedTextProfileDefinition`, separate `HostedTextProfileStatus`, and
`HostedTextCapabilityCertificate` use their own ids and schemas. The text
certificate always records `workspace_tools=false`, `action_loop=false`, and
`workspace_actions=false`; it is never accepted where an agentic capability
certificate is required. A new text session pins these records, provider/model,
and provider-routing snapshot in `HostedTextExecutionBinding` before
persistence. The session initializer receives no agentic execution binding, so
it creates neither provider-private agent state nor a provider-step journal.
Dispatch supplies the exact pinned provider/model and routing snapshot and
fails on drift instead of falling back. A continuation only forks the binding's
session identity. Legacy stored text sessions remain byte-for-byte unmigrated;
hydration does not synthesize authority for them.

## Provider status and product taxonomy

`GET /api/providers` is the authoritative redaction-safe projection used by
both Settings and Chat. It returns the exact ordered family catalog:

1. `Native Agents (CLI)` — external coding-agent runtimes supervised by
   Maverick;
2. `Maverick Agents (API)` — API models running the Maverick execution loop;
3. `Text-only Models (API)` — hosted generation without tools or an action
   loop.

The response also includes `native_agents.items`, agentic profile
`family_contract_status`/`full_workspace_status`, independent
`hosted_text.profiles`, and `selection_migration`. Native status contains only
safe executable-name/version and contract metadata, never an absolute host path
or authentication secret. Agent profile selection requires the server to
report a complete recognized family, certified Full Workspace revision, active
certificate and effective authority, enabled binding, selectable rollout, no
containment, and healthy native installation where applicable. Missing or
narrowed state is `unavailable`; it is never silently offered as a lesser
agent.

Settings renders family and Full Workspace state as derived information. It
does not expose capability tiers, a `Full/Read-only` switch, per-agent controls
that remove required filesystem/shell/CLI/MCP/skill surfaces, or a way to
promote text-only models. Administrative binding enable/disable, credentials,
default selection, approvals, rollout, and kill-switch authority remain
server-governed. Chat uses the same family order and copy, shows agent
destination/profile/recipe before a new session, and displays `No workspace
tools or actions.` for every text-only option.

`selection_migration` uses schema
`maverick.execution-family-selection.v1` and mode `projection_only`. It maps
legacy runtime and `fast_model` selection records to canonical picker ids but
reports both `persisted_records_mutated=false` and
`pinned_sessions_rewritten=false`. The browser applies that projection only to
the default for a new chat. A loaded agentic or text-only session continues to
resolve its immutable binding/provider/model, so migration cannot change its
family or cause an implicit fallback. If a persisted new-chat target is no
longer selectable, Chat requires an explicit replacement selection rather than
choosing the first model from another family.

The single deterministic manifest in
`core/providers/certified_execution_tcb.py` owns every component that can alter
attestation/classification/egress, API/app admission, input composition/request
building, tool schema/catalog, ledger/store/private state, lifecycle/recovery
boundary, capability projection, Chat/Settings governance, and provider
codec/transport/live policy. Suite artifacts, signing, publication, execution
bindings, and live status all derive from its digest. The publisher recomputes
the deployed digest. Drift—or a legacy remote certificate with no valid TCB
identity—makes the certificate ineligible before work. Exact Codex follows its
existing local identity path rather than being treated as hosted remote.

The migrated Codex profile is `preview` and receives an expiring certificate
backed by the packaged adapter contract suite. A code change that changes the
adapter source digest invalidates older session bindings; those sessions require
a new chat rather than silently adopting the new artifact.

## Runtime Tool Orchestration

`RuntimeToolOrchestrator` is a facade over the existing CLI and MCP registries,
workspace-selected app-interface providers, and separately governed Core
filesystem/shell capabilities. It does not import app backends or maintain a
shadow registry. Internal handles map deterministically to provider-safe names,
while returned arguments are validated against the original bounded JSON
schema. App-interface handles include the declared interface, selected local
provider app, and official underlying surface.

Every decoded invocation is inserted as a preliminary proposal before catalog
resolution, schema checks, policy/budget disposition, or an effect boundary.
The persisted handle is nullable; provider safe name, call id, request id,
ordinal/index, private argument reference and HMAC, policy revision, and
authority digest are immutable. Exact replay deduplicates, while the same call
id with a different name or arguments fails closed. Unknown, revoked,
not-authorized, schema, budget, malformed, and parallel denials remain durable
and pairable. Full arguments exist only in encrypted private storage.
The row is inserted before its deterministic encrypted-argument WAL half, so a
restart can repair an exact replay without losing the preliminary proposal or
accepting divergent bytes.

Mutating/destructive confirmations are one-shot and consumed with CAS;
idempotency keys are passed only to surfaces that declare support. The event and
effect order is proposal persisted → proposed → validation/disposition →
started → effect boundary → result persisted → completed/failed. After a worker
crash, only a declared safe read may return to `authorized` for retry. An
executing mutation, destructive operation, or other ambiguous outcome moves to
`execution_unknown` and requires reconciliation instead of automatic replay.

Discovery also does not make a schema provider-public. Only an explicitly
public Core-owned surface covered by the exact TCB can be materialized into a
remote request. App-owned and dynamic CLI/MCP schemas, uncertified surfaces,
and requested surfaces omitted by authorization produce bounded structured
rejections such as `tool_schema_not_certified`; the request builder never
silently drops them.

Core filesystem capabilities are implemented by
`ConfinedWorkspaceFilesystem`. It pins the workspace-root descriptor, opens
every path component relative to a verified descriptor with no-follow and
directory flags where available, never reopens a verified resource by path,
and rejects root/parent/final symlink or rename/swap races. Reads and list
cursors return exact resource identity/revision/digest and reject mutations;
UTF-8 chunking does not split code points. Writes commit through the verified
parent descriptor and roll back when confinement changes. Listing does not
descend into `.git`, and shell cwd is entered through a verified descriptor.
The resulting exact observation is also the source of filesystem/tool-result
classification.

## Current Provider Reality

The current practical backend is Codex.

Important implications:

- local evaluation expects the Codex CLI to be available when testing Codex-backed runtime paths
- Maverick-managed Codex agents use the workspace-selected Codex model and reasoning effort; the provider adapter discovers visible model options from `codex debug models` and writes the selected `model` and `model_reasoning_effort` into each runtime-scoped `CODEX_HOME/config.toml` instead of inheriting operator-home values
- Maverick-managed Codex agents install a Maverick-owned `PostToolUse` hook, write the matching Codex `hooks.state` trusted hash, and disable Codex `unified_exec` so large `Bash` shell outputs can be compacted before Codex continues from the tool result when Codex accepts and runs that hook under its hook-trust policy; this integration is not a hard provider-token guarantee until a trusted Codex hook run is verified end to end
- non-default workspaces are intended to remain sandbox-first
- provider adapters may need helper binaries such as `rg`
- network access for providers is not equivalent to unconstrained filesystem access
- shell settings can list runtime sessions across workspaces visible to the authenticated user, terminate individual sessions, and clear visible session records in batch through controlled settings runtime-session endpoints

Chat may create hidden `prepare_only` runtime sessions before the first message. The create response waits for provider prewarm for at most two seconds and reports `prewarm_status`, `prewarm_completed`, `runtime_ready`, and the legacy `provider_thread_ready`. A client treats the session as ready when prewarm completed and `runtime_ready` is true; older servers fall back to `provider_thread_ready`. A session record existing is not sufficient. Plain hosted chat reports prewarm as `not_required` and ready because it has no local provider process or thread to warm.

Codex turn startup emits separate runtime events for `ensure_runtime`, generated-system-skill cleanup, `ensure_thread`, event-sink reset, and the `turn/start` write boundary. Each start/completed pair is persisted under `runtime.provider.*`, while `runtime.provider.turn_start_sent` remains the write-complete marker and provider acceptance carries `turn_start_request_ack_ms`. This keeps cold-process, cleanup, cold-thread, local reset, request-write, and provider-ack latency distinguishable. Generated `.system` skills are removed on runtime initialization/prewarm and only checked again when that runtime home may need cleanup; a warm turn does not recursively remove an already-clean tree. Maverick owns Codex's `[skills] include_instructions` setting per runtime session: `implicit` writes `true`, while `explicit` writes `false` and supplies validated `type=skill` user-input items only on the invoking `turn/start` or `turn/steer` request.

Explicit Codex threads also use Maverick's `maverick-explicit-lean-v1`
`baseInstructions` profile instead of the general coding-agent baseline. It
keeps the workspace, tool, destructive-action, and structured-skill rules but
does not carry a static skill catalog or generic multi-agent operating manual.
The automatic project-document excerpt is capped at 2 KiB; before repository
edits the profile requires the agent to read each applicable `AGENTS.md` in
full on demand. Implicit sessions retain Codex's legacy baseline and automatic
project-document behavior. The explicit profile has an 8,000 non-cached input
token budget for its first turn. Exact Codex usage snapshots add
`prompt_profile`, `first_turn_input_token_budget`,
`latest_non_cached_input_tokens`, `first_turn_within_input_budget`, and
`prompt_budget_final` to `runtime.usage.reported`. At `turn/completed`, Core
also emits the durable `runtime.prompt_budget.evaluated` event from the latest
exact usage snapshot, including the final non-cached count and pass/fail result
even when Codex reports usage separately from the completion notification. The
acceptance smoke against Codex 0.144.4, with an empty system prompt, no invoked
skills, the repository
workspace, and a two-word reply request, measured 7,691 non-cached input tokens.
This is a versioned acceptance datum rather than a claim that later Codex
releases or larger app prompts will have identical tokenization.

For an `explicit` session, the persisted user input remains unchanged, but the Codex-only text item neutralizes every `$` sequence that Codex could parse as a skill mention. The validated `invoked_skill_ids` are therefore authoritative. After each acknowledged same-turn steer, Maverick atomically appends the validated IDs to the persisted active-turn receipt. The live runtime retains the same union; when Codex completes a `contextCompaction` item, Maverick serializes a `turn/steer` reinjection of the runtime-local `type=skill` items and emits a bounded success or failure event. Backend-restart recovery likewise copies the interrupted active turn's complete persisted invocation receipt into its continuation turn. It never reconstructs provider paths from persisted data.

Codex declares same-turn text input and maps the generic adapter operation to app-server `turn/steer`. Maverick supplies `threadId`, the provider turn id persisted by `runtime.provider.accepted`, a text input item, and the stable `clientUserMessageId`. The adapter serializes steering writes, retries only explicit app-server backpressure rejections with a small bound, and refuses a changed provider-turn correlation. Explicit no-active-turn, non-steerable-turn, mismatch, overload, or other rejection is safe for the Core to queue as the next runtime turn. A local `ProviderLaunchError` while validating provider input is also known not to have crossed the write boundary, so Core releases the message claim and queues normally. A transport write failure or acknowledgement timeout is delivery-uncertain and is never retried or queued automatically.

Same-turn admission is distinct from realtime media input and barge-in. Providers that do not declare `supports_same_turn_input`, including the current plain hosted chat bridge, use the same Core API but receive the normal server-side queued-turn fallback.

The latency report also exposes an overlapping `prepared_ready` cohort for turns whose client observed a fully prewarmed prepared session before submit. Session-scoped prewarm and app-reference preparation events are associated with a turn only when they precede its queue marker by at most 30 seconds, preventing stale session history from inflating a later turn's metrics. Legacy turn-scoped `prewarm_total_ms` values above that window are discarded unless the event marks the value as the corrected completion duration, so genuinely slow prewarms remain visible.

## Hosted Model Providers And Plain Hosted Chat

Provider records distinguish `provider_role` from the lower-level provider `kind`.
Codex is a `runtime_engine` and remains the default agentic runtime. Groq,
DeepSeek, and OpenRouter are `model_provider` records for hosted text
generation; they are not runtime backends and must not be configured through
the workspace runtime provider selection path.

OpenRouter is the hosted provider used for selectable `fast_model` and
`plain_hosted_chat` text routing when activated by an operator. It uses the
Core Secrets alias `openrouter_api_key`, the public secret reference
`platform:secret-alias/openrouter_api_key`, and the OpenAI-compatible chat
completions endpoint `https://openrouter.ai/api/v1/chat/completions`.
Maverick exposes these OpenRouter model options:

- `google/gemma-4-31b-it:free` as `Gemma 4 31B (free)`, with text, image, video, and PDF input metadata
- `nvidia/nemotron-3-ultra-550b-a55b:free` as `Nemotron 3 Ultra (free)`, with text and PDF input metadata
- `deepseek/deepseek-v4-flash` as `DeepSeek V4 Flash`, with text and PDF input metadata and paid OpenRouter pricing
- `hexgrad/kokoro-82m` as `Kokoro 82M`, with text-to-speech metadata and paid OpenRouter pricing

Hosted text providers are enabled through an operator-only hosted activation
path, not through `/api/providers/active`. The activation path stores an active
provider definition, binds a Core Secrets `secret_ref` as provider credential
metadata, and returns a redaction-safe routing preflight decision:

- HTTP: `POST /api/providers/hosted/active`
- CLI: `core.providers.hosted.activate`
- MCP: `core.providers.hosted.activate`

The activation responses expose provider ids, binding ids, model ids, and
reason codes. They do not expose raw secret values or secret refs.

The hosted provider/model choice is persisted separately from the Codex runtime
`ProviderSelection`. Settings saves it through `/api/providers/hosted/selection`
so a workspace can choose an OpenRouter hosted model for `fast_model` while
leaving Codex as the agentic runtime for tools, filesystem, MCP, and skills.
Chat treats that Settings selection as a default/fallback. When a user chooses a
hosted model in the Chat provider picker, each provider model option is exposed
as a separate selectable runtime option and the runtime session persists
`hosted_provider_id` plus `hosted_model_id`. The provider router honors those
session fields as an explicit override without mutating the workspace Settings
selection.

Settings owns OpenRouter upstream-provider preferences. Each OpenRouter model
can store its own routing preference, such as automatic routing, preferring one
upstream provider, allowing only one upstream provider, ignoring one upstream
provider, fallback behavior, sorting preference, parameter requirements, data
collection preference, and quantization filter. Chat does not expose these
controls; Settings also exposes an explicit zero-data-retention filter. Chat
only selects the model. During OpenRouter execution, Maverick
translates the saved per-model preference into the OpenRouter `provider`
request object.

OpenRouter also has one separate contained, uncertified Full Workspace agentic
preview. It pins
`deepseek/deepseek-v4-flash` to `deepinfra/fp8` through
`openrouter-chat-completions` v1 and the shared `maverick-tool-loop`. Unlike
plain hosted chat, this profile does not inherit workspace OpenRouter routing
preferences: its immutable routing constraint always disables fallback,
requires parameter support, denies data collection, requires ZDR, and requires
FP8. It preserves tool-call and reasoning continuation only in encrypted
provider-private state. The exact dated evidence and promotion requirements
are in `docs/reference/openrouter_agentic_certification_matrix.md`.

Speech-output OpenRouter models such as `hexgrad/kokoro-82m` are cataloged in
Settings for provider routing metadata, but the current `plain_hosted_chat`
bridge only executes models whose output modality includes `text`. Kokoro uses
OpenRouter's `/api/v1/audio/speech` TTS endpoint and is intentionally not routed
through the text chat completions bridge until Maverick has a speech synthesis
runtime path.

`plain_hosted_chat` is the current non-agentic text bridge. A Chat/runtime
session using that mode routes the `fast_model` profile through the provider
router, resolves credentials only through Core Secrets/provider bindings, calls
the hosted text adapter, and maps output back into normal runtime events:

- `provider.routing.decision`
- `runtime.output.delta`
- `runtime.output.final`
- `runtime.turn.completed` or `runtime.turn.failed`

The same effective provider registry is used for route preview and real
`plain_hosted_chat` execution: builtin metadata is overlaid by persisted
provider-store definitions. Runtime failure payloads keep bounded router reason
codes so missing credentials, disabled providers, model/policy failures, and
provider transport failures remain distinguishable.

Hosted providers do not own Maverick conversation state. Before each
`plain_hosted_chat` request, the runtime rebuilds a bounded message history
from completed turns in the same runtime session and sends complete
`user`/`assistant` pairs before the current user message. Failed, cancelled,
active, current, and incomplete turns are excluded; historical attachments are
not replayed. The builder orders turns by creation time and turn id, chooses the
latest `runtime.output.final` event per turn by event creation time and event
id, trims only whole historical pairs, and always keeps the current user
message. Because hosted text request validation scans the whole generated
request, an operational reference in an older retained turn fails closed just
like one in the current prompt.

The only supported Chat routing profile for this bridge is `fast_model`.
Runtime HTTP requests may omit `routing_profile` or pass `fast_model`; any other
provided value is rejected with `unsupported_routing_profile` instead of being
silently ignored.

Runtime thread-title generation also uses `fast_model` as a bounded hosted
micro-task. The title worker asks the routed hosted text model for a short JSON
title from the first user message, attachment labels, and app-reference labels.
If hosted routing or hosted generation is unavailable, the worker falls back to
the configured Codex runtime model and then to the deterministic title fallback.
This keeps title generation independent from the active chat runtime while using
the low-cost hosted model path when it is configured. Completed thread-title
jobs persist the redaction-safe provider id and model id used for the title on
the runtime thread record.

The bridge is deliberately narrower than an agentic runtime. Before prompt
materialization it rejects skills, tool/MCP use, workspace filesystem access,
and operative app references. Storage-backed attachments are read by the
platform and sent only when the selected hosted model advertises the matching
input modality and the hosted provider bridge can serialize that modality.
OpenRouter uses `image_url`, `input_audio`, `video_url`, and `file` content
parts for local base64 data; Gemini uses `inlineData` parts. Attachments whose
type is not declared by the selected hosted model fail closed. Hosted text
requests must not contain local
workspace paths, `local path:` labels, or materialized app-owned record blocks.
Routing decisions, runtime events, logs, transcripts, Storage artifacts,
CLI/MCP payloads, and HTTP responses may expose provider ids, model ids, binding
ids, grants, and reason codes, but never raw secret values.

## Speech Provider Boundary

Deepgram is exposed as a governed `speech_provider` for speech-to-text settings
and credential binding. The built-in Deepgram model catalog starts with
`nova-2`, using the public Deepgram listen endpoints:

- prerecorded HTTPS: `https://api.deepgram.com/v1/listen?model=nova-2`
- streaming WebSocket: `wss://api.deepgram.com/v1/listen?model=nova-2`

Settings surfaces these under `Deepgram models` and reads only redaction-safe
provider and binding metadata. The API key remains in Core Secrets/Vault and is
referenced through a provider credential binding such as
`platform:secrets/deepgram-api-key`; raw secret values are never returned.

Cartesia and Kokoro-hosted remain metadata-only `speech_provider` records until
a later realtime audio slice implements governed STT/TTS execution. OpenRouter
Kokoro (`hexgrad/kokoro-82m`) is cataloged under OpenRouter model metadata, but
is not a `plain_hosted_chat` text model.

The next speech integration must reuse the same registry, policy, routing, and
Core Secrets boundary proven by hosted text:

- Speech consumes routed provider decisions through official core/app surfaces.
- Speech must not import core internals or read raw provider secrets from app
  data.
- Chat asks the provider/router layer for speech capability instead of silently
  choosing a remote provider.
- Senses may open live audio sessions only after STT/TTS provider routing and
  audit decisions exist.
- Any future audio WebSocket must carry an already-audited router decision and
  must not expose secret values.

Kokoro-local, `local_process`, Piper/espeak provider governance, local STT/TTS
provider execution, and bidirectional voice realtime are explicitly outside this
hosted text slice. Existing local Speech app engines remain app-local behavior,
not governed remote provider execution.

## What External Reviewers Should Know

- provider abstraction is a real architectural boundary, not only an internal naming trick
- Codex app-server is the current implementation choice, not the permanent platform identity
- setup docs must separate "Maverick runs" from "Codex-backed agents run"

## Local Evaluation Guidance

Use the local host and core verification even without provider setup when evaluating:

- architecture
- built-in app hosting
- workspace layout
- app contracts
- CLI and MCP discovery

Provider setup is required only for end-to-end agent execution paths that depend on Codex.

## Runtime Event Payload Compaction

Large tool-call event payloads are compacted before persistence and live event
fanout. The Codex compatibility bridge applies the same compaction before it
yields legacy tool-call events into the bounded public agentic stream, and the
runtime recorder repeats an idempotent guard at the persistence boundary. This
Phase 1 behavior protects the agentic adapter boundary, storage, websocket
delivery, runtime replay, UI rendering, and downstream app consumers, but it
does not guarantee provider-token reduction for generic shell/tool output.

Runtime-token CLI responses can request provider-oriented compaction for controlled Maverick CLI calls, and Maverick-managed Codex sessions install a Maverick-owned `PostToolUse` hook plus matching Codex `hooks.state` trusted hash to replace large `Bash` shell tool results before those results enter Codex provider history when Codex runs the hook. Maverick disables Codex `unified_exec` in these managed sessions because Codex hook coverage for that richer shell path is currently incomplete. Automated Maverick tests cover the bridge/config/trust-state/fallback/diagnostic behavior; deployments that need a hard provider-token guarantee must verify an actual trusted Codex hook execution.

See `docs/reference/runtime_output_compaction.md` for the event contract, provider hook contract, operational flag, and Phase 1/2/3 status.

## Agent-Facing Transcript Reads

The runtime owns the official read-only conversation projection exposed as
`core.runtime.threads.list`, `core.runtime.transcript.read`, and
`core.runtime.transcript.message.read` over both CLI and MCP. The projection
pages the append-only event history through
`RuntimeStore.list_event_archive_page()`;
it never reconstructs a complete chat from the 500-event recent tail.

The `messages` profile includes queued and steered user messages, canonical
final assistant output (falling back to deltas when necessary), visible
structured output, and failed/cancelled/timed-out states. It omits prompts,
provider-private payloads and ids, runtime filesystem/environment values, and
raw technical tool output. Long text is exposed through explicit character
windows, and provider-oriented CLI compaction recognizes those already-bounded
message windows so it does not silently summarize them.

Historical transcript reads apply the opaque snapshot's physical append
position before sorting events by timestamp and id. The same cursor bounds the
set of eligible turn records, allowing durable user input to be recovered when
its queued event is missing without admitting later turns. Turn submission
fields are immutable after insertion. Turn fallbacks never
project mutable terminal state, are reported by warning, and make projection
completeness false. Explicit empty positions keep an earlier empty event or turn
snapshot stable after later writes. Streamed output status in historical reads
is derived only from terminal events inside that event snapshot, never from the
mutable current turn status. Structured visible output applies
case/separator-insensitive sensitive-key filtering and one global node and JSON
byte budget. Its response
metadata states whether the structured payload is complete or truncated.

## Agentic Provider-Private State

Hosted agentic adapters do not place thought signatures, opaque continuation
steps, or raw vendor protocol state in runtime events. They use the Core-owned
`ProviderPrivateStateService`, which issues a non-path `provider-private:v1:*`
locator and stores the exact bytes under authenticated AES-256-GCM encryption.
Associated data binds the blob to workspace, session, runtime engine, pinned
adapter id/version, codec id/version, and schema version. The envelope persisted
in `provider_state.json` contains only codec/encryption metadata, SHA-256,
plaintext size, timestamp, and the opaque locator. Its adjacent redaction-safe
taint metadata records source-block digests, source data classes, source trust
levels, their restrictive effective data class/trust join, codec identity,
provider request id, and turn generation. It never stores source content or
credentials, and the effective class is not implicitly fake/public or
trusted-platform. Persist/load/continuation validates the metadata before use.

Writes are bounded to 2 MiB per blob and 8 MiB per session and serialized under
a namespace file lock. Streamed response state is first staged at a
deterministic request-scoped private locator and attached to the provider-step
journal; this does not mutate authoritative provider state. Promotion uses the
step's base provider-state revision only after final-output validation or full
proposal/disposition/result pairing, and journal commit follows that CAS. A
losing writer cannot overwrite newer state; a winning replacement deletes the
prior committed blob. Recovery can reattach a blob written immediately before
its WAL update without treating it as committed.

Validated final text uses a separate deterministic
`provider-final-output:v1:*` encrypted namespace. The journal retains only its
opaque locator, digest, byte count, stable delivery id, and output/completion
acknowledgements. Content is durable before stream completion and commit,
readable only through the exact bound adapter/codec recovery context, and never
projected through journal APIs.

Wrong adapter or codec identities, missing keys, ciphertext tamper, digest/size
mismatch, and quota failures produce explicit provider-private recovery reasons.
No continuation reader sees an uncommitted staged envelope and no codec is
silently migrated. The ordinary provider-state patch path rejects private
envelopes and raw thought fields. Tool arguments use the same restart-safe
encrypted store with a separate namespace and integrity binding.

## Hosted Agentic Egress Records

`AgenticEgressEvaluator` evaluates every Core-classified content block against its
exact provider/upstream and policy revision before returning bytes to a request
builder. Attestation/declaration, effective resource classification, and this
decision are separate records. The workspace attestation is an actor-attributed,
timestamped, scoped, revocable CAS record exposed for mutation only through
governed Core operator/admin surfaces; Settings may show its read-only safe
projection. It can narrow policy but cannot promote real, secret,
workspace-internal, or unclassified content. Browser fields, labels, flags,
egress-policy ids, `workspace_internal_fake`, and legacy
`declared_remote_data_class` are non-authoritative.

Every platform/finalization instruction, prompt, orchestration block, skill,
attachment, app reference, tool schema/result, and private-state source retains
distinct canonical provenance,
trust, and data class. Filesystem and tool-result sources inherit the exact
resource identity, revision, digest, and matching classification record. A
missing/incoherent match becomes `unclassified`, and the restrictive source
join cannot be weakened by an attestation or a less-sensitive sibling.
Unknown data class, provenance, trust, provider, or upstream fails closed.
`workspace_internal_fake` can pass this stage only when the exact observed
resource/version carries that Core-owned classification, an active scoped
attestation matches the workspace and covers the resource, and the policy
allows the class and destination. Attestation does not supply classification.
Current contained revisions list only `public`, remain disabled and NO-GO, and
no client or egress-policy id is attestation. Secret, host-operational, and
unclassified content is always denied. Workspace paths are rewritten to
`workspace://` references, other host paths are denied, and recognizable
sensitive text must be redacted.

For app references, Core hashes the complete server-materialized payload into
the observed revision/digest and hashes its stable app/entity key into the
resource identity. The production resolver reads the same revisioned workspace
classification store used by other resource observations. Absent evidence or
any identity/version mismatch stays `unclassified`.

Production bootstrap also installs the closed transient-input admission
resolver and its Core-owned production writer. Before dispatch, one turn CAS
persists a revisioned content-derived manifest for the exact prompt, agent
instruction, reference metadata, and each governed orchestration control,
summary, task/result, and artifact chunk. Integrity-bound source ids never imply
`public`; marker absence remains `unclassified` unless a current operator-owned
runtime-public classification policy explicitly authorizes Core to classify
the exact source identity/revision/digest. Admission revalidates the policy's
self-digest, CAS revision, workspace identity, and revocation state against the
immutable manifest. Governed
context restrictively joins its entries while retaining untrusted provenance.

Tool results do not receive a generic public fallback. Exact resource
observations and edit pre-images retain their taint; shell/process streams and
CLI/MCP discovery/read results are classified from exact bytes under an active
runtime-public policy or an explicit certified Core result contract and remain
complete through the common compactor. A denied private result becomes only a
public call-paired error on the next request. Workspace-mutating shell/process
runs classify their exact private-overlay result before commit and discard the
overlay on denial. Mutating/destructive app CLI/MCP calls without the same
pre-effect guarantee remain rejected; app definitions cannot self-promote.
Built-in app definitions carry conservative effect metadata, and mixed runners
resolve one declared argument discriminator; unknown values fail closed. A
hosted app read additionally needs an exact platform source, descriptor digest,
and executable-closure digest from the Core-owned audit and TCB, recalculated at
dispatch, so workspace/external metadata and drifted code are never its sole
authority. Real Storage catalog reads execute through both app registries;
Website Studio preview creation/cache operations are mutating and persistent
pre/post tests cover all of its remaining reads. Core inter-agent CLI/MCP
definitions declare exact effects and reviewed public projectors that omit
conversation/result content; the behavior gate runs an actual
CLI-create/MCP-wait workflow. Hosted bwrap consumes a descriptor-confined
immutable workspace snapshot that omits every `.git` component, so post-spawn
live create/rename races remain invisible to shell and managed processes, with
or without a mutation overlay.
Current Google/OpenRouter definitions use `maverick_agent` and pin
`codex-baseline-v20` only because the executable 24-behavior gate runs 16 real
filesystem, shell/process, and CLI/MCP capability paths, one concrete
inter-agent workflow, and seven security probes; only a complete successful
result is cached, while transient, empty, and partial probe evidence is retried;
their policy ceilings retain `cli`, `mcp`, `app-interface`, and
`core-capability`, and the public resolver proves the complete live authority
from each exact profile. They are still uncertified, unbound, contained
previews. Direct replacement
and move propagate exact version-bound pre-image taint for read-after-write
through authenticated same-session mutation records, even when the next tool
step rebuilds its orchestrator, while creation remains unclassified without
authoritative source taint. Mutable classification authority is stored as the
exact id, kind, ref, revision, digest, and policy revision on tool and
provider-state lineage, then checked against the current audit-backed authority
before result reuse, continuation, request commit, and every actual lazy-stream
advance. Attachment references additionally inject their server-captured
identity/revision/digest and required encoding into every matching read, so a
replacement at the same path or an alias cannot evade the first-chunk fence.
Filesystem reads classify the bounded complete raw resource before
base64 projection and retain that class on every version-bound chunk. Mutating
shell/process overlays revalidate exact result authority around the batch and
roll back on drift. Sensitive markers can only narrow the class. Large artifact
summaries carry a digest of their exact provider-visible bytes while retaining
the original result class/trust/identity separately.
Payment-card detection treats every 13–19 digit Luhn-valid candidate as
sensitive even when hexadecimal characters surround it. The scanner has no
global digest exception: arbitrary prompts, JSON values, runtime-public input,
and declared-public tool results all remain on the conservative surface.
Only a typed attachment read fence or an owning Core tool-result boundary may
project out exact server-observed identity/revision/digest fields. Tool-result
projections are bound to the complete canonical payload; discovery tokens and
certified result projections are revalidated against their HMAC/schema
authority before use, and only Core-generated compactor metadata is added on a
derived payload. User-controlled attachment metadata, filesystem paths/content,
shell output, discovery text, and arbitrary result fields remain scanned, while
classification evidence still binds the complete unmodified bytes. Classifier
revision 4, hosted result-admission revision 10, and runtime-public policy v3
invalidate older vulnerable manifests and mutable-authority lineage.

Google profile/binding/certificate/request identity uses the `exact` revision
policy and must match the authenticated catalog `version`. OpenRouter uses the
explicit `provider_alias` policy while separately pinning the endpoint,
upstream, routing controls, and catalog digest. Revision or policy drift rejects
binding or transport rather than silently following a different model.

The complete decision metadata is inserted first into the session-owned
`egress_decisions.json`; only then may transformed bytes be used. Its audit
projection contains domain-separated HMAC digests and decision metadata, never
the original or transformed content.

## Shared Hosted Agentic Loop

Hosted model vendors implement `AgenticModelProviderClient`, which accepts one
normalized `AgenticModelRequest` and emits decoded `AgenticModelEvent` values.
Vendor payloads, retry behavior, and credentials remain behind that boundary.
`HostedAgenticEngineAdapter` delegates every provider to the same Core loop for
request journaling, live authority refresh, tool catalog materialization,
per-request egress, sequential tool execution, confirmation pause/resume,
provider-private codec access, usage, cancellation, and recovery.

Before transport, the loop writes `REQUEST_READY` then `REQUEST_JOURNALED` to a
schema-versioned provider-step saga. Acceptance records response/upstream ids;
stream state is staged; ordered proposal, disposition, result, pairing, and
commit fields advance by revision CAS. A continuation must also name its source
journal, turn, and provider request and reproduce the source's exact non-tool
input lineage digest and current private-state generation. The JSON
`provider_step_journal.json` collection and document-store implementation have
the same semantics and no cross-collection transaction is claimed. The loop
performs no blind retry after acceptance.

Provider-step and provider tool-call budgets are distinct. Journal schema v3
persists the request phase, max-output/input/cost reservation, separate
request-control digest, tool-call charges, paired-result byte count, and the
sole provider usage report. Restart therefore restores consumed steps, tool
proposals, result bytes, input/output and micro-USD accounting; missing usage
keeps the conservative request reservation. The controller exposes remaining
provider steps, tool calls, output tokens, cost, wall time, and whether the
terminal reserve is intact. Proposal and accepted tool-budget charge share one
journal CAS, and usage is journaled before its public usage event. Live policy may
tighten but never loosen it. Tool-call and cumulative tool-result-byte
exhaustion each close the catalog; if a last-mile tightening crosses either
boundary after preparation, Core releases the uncommitted reservation and
rebuilds finalization without tools before any provider request.

Each hosted adapter pins one normal finalization attempt and at most one
recovery, including per-attempt output, cost, and deadline capacity. Google and
OpenRouter currently use 2,048 output tokens and 20 seconds per attempt, with
550,000 and 35,000 micro-USD respectively. Those values cover the conservative
request estimator for every complete terminal projection inside the hosted
262,144-token input ceiling, including retained context, provider-private state,
and a maximum-size result. Exploration stops before consuming those protected
resources. A final request whose conservative cost estimate is larger than its
per-attempt allocation is rejected before transport. Decoded streamed output also has a
conservative byte ceiling, so a provider cannot bypass the request limit by
delaying usage events.

Core checks coarse phase eligibility and credentials before catalog projection.
It then evaluates a request candidate with egress decisions staged in memory,
runs the provider-specific cost preflight, and commits those decisions only for
the eligible request. If an exploration candidate would cross the protected
cost reserve, Core discards it and evaluates one tool-less finalization
candidate instead; no exploration egress decision or request journal is left
behind. Synchronous tool dispatch runs behind a deadline fence before the
protected terminal window. A timeout CAS-persists a deterministic failed read
result in the invocation ledger without waiting for private result storage;
the `executing` record contains a unique lease id and UTC expiry, and success
atomically requires the expected revision, the same lease, and a deadline still
in the future. JSON evaluates this under its collection lock and rechecks just
before atomic replacement; Mongo evaluates it with server `$$NOW`. A worker
paused after its last cooperative check therefore cannot become authoritative
after expiry, and the paired final request can proceed. A non-read effect
remains `execution_unknown` and fails closed.

For synchronous shell and managed-process work, execution control terminates
the complete process group, discards the COW overlay, and waits for worker
quiescence before cancellation returns. `HostedAgenticEngineAdapter` owns the
managed-process registry, so close and idle reap clear live handles, capture
FDs, overlays,
global registrations, and durable process status before the orphan fallback.

Google and OpenRouter preserve every call, including later OpenRouter indices
and calls decoded before a terminal stream error. Parallel execution remains
disabled, so every call in a multi-call response is first journaled. Calls
inside the remaining tool budget are charged and `parallel_denied`; overflow is
`budget_denied`. No call is discarded. Result content stays in encrypted tool
storage and is re-evaluated against the current egress policy when included in
every subsequent request.

Confirmation waiting is represented by the persisted invocation and
`waiting_for_tool_confirmation` turn state. Approval consumes the exact one-shot
grant and refreshes authority before the side effect. Cancellation makes a
still-waiting invocation terminal. Recovery is invoked by backend
startup/worker-loss, continuation pre-admission, hosted pre-prepare, execution
failure, uncertain cancellation, and the explicit adapter operation. It
validates the exact pinned binding and codec, repairs only provable
WAL/pairing/provider-state transitions, and is idempotent across restarts.
Recovery never automatically replays an ambiguous `executing` mutation; it
becomes `execution_unknown`. Anything else unprovable becomes a session
status-CAS transition to `recovery_required` with allowlisted public cause.
Session containment uses bounded reread/retry before independent journal CAS;
encrypted Core-private detail is best-effort and cannot block containment.
Queue, continuation, prepare/dispatch, and token authority read the persisted
journal and reject unresolved state. A ready pairing is resumable only by its
active original turn; terminal limits, cancellation, revocation, egress denial,
or execution failure must complete same-turn recovery or quarantine it.

Final output is staged in the private outbox before stream completion and
journal commit. Stable `runtime.output.final` and
`provider.execution.completed` delivery identities are persisted once and
acknowledged independently. Startup and same-turn retry drain the exact bytes
after a crash without another provider request; missing or conflicting identity
enters quarantine. Public provider events are bounded JSON and recursively
reject private-state field names.

When the tool-call or cumulative tool-result-byte budget reaches zero—or
another protected resource reaches its reserve—the next request has phase
`finalization`, no Core tools, and one exact
trusted finalization instruction placed last. Google omits the `tools` member;
OpenRouter sends `tools: []` with `tool_choice: none`; its instruction is
request-scoped wire content and is excluded from durable chat history. Both
codecs reject a phase/catalog/instruction mismatch before transport. Empty or whitespace final
text is durably rejected and its staged state rolled back, never committed as a
healthy output. A tool proposed despite the closed catalog is still journaled,
gets a paired `budget_denied` result, and permits exactly one tool-less
`finalization_recovery`. Another proposal is denied without a fourth request
and its ready pairing is quarantined. Every terminal failure produces a
structured runtime error and non-zero completion rather than a silent turn.

The deterministic fake provider certification covers multi-request streaming,
official read and confirmed mutating tools, restart deduplication,
provider-private round-trip, egress records, budgets, cancellation transport
closure, terminal outages without blind retry, mid-step certificate revocation,
policy drift, explicit private-state quota/integrity failures, prompt-injection
containment, child-agent binding isolation, JSON/document-store parity,
Google/OpenRouter multi-call accounting, journal fault injection, event/effect
ordering, productive lifecycle recovery, durable budget restoration, tool-less
provider payloads, whitespace rejection, and the one-recovery finalization
controller.
The terminal-gap matrix additionally covers cross-turn Google/OpenRouter
pairing rejection, step/cost/cancellation/revocation containment, diagnostic
and CAS/projection faults, final-commit crashes, and repeated restart with one
provider request and one event per terminal identity.
