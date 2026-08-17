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
id/version/source digest, model provider, model, protocol, routing digest,
certified upstream set, capability set, evidence suite, and expiry. Evidence
metadata and optional content-addressed blobs are installation-owned; neither
workspace Storage nor an adapter controls their locators. Revocation lives in a
separate revisioned status record and therefore takes effect without rewriting
the certificate or a session binding.

Before session binding, prewarm, and every pinned turn, Core verifies certificate
identity, expiry/revocation, live adapter artifact, credential reference, profile
status, workspace binding, and upstream constraint. It then intersects certified
capability with the pinned profile/workspace ceilings and current live
restrictions. The resulting `EffectiveRuntimeAuthority` is ephemeral and is not
a bearer grant. Runtime events persist only its SHA-256 digest, revision set,
capability names, and counts; tool handles and content are omitted.

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

Every invocation is journaled before validation and before an effect boundary.
Mutating/destructive confirmations are one-shot and consumed with CAS;
idempotency keys are passed only to surfaces that declare support. After a
worker crash, only a declared safe read may return to `authorized` for retry.
An executing mutation, destructive operation, or other ambiguous outcome moves
to `execution_unknown` and requires reconciliation instead of automatic replay.

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

Codex declares same-turn text input and maps the generic adapter operation to app-server `turn/steer`. Maverick supplies `threadId`, the provider turn id persisted by `runtime.provider.accepted`, a text input item, and the stable `clientUserMessageId`. The adapter serializes steering writes, retries only explicit app-server backpressure rejections with a small bound, and refuses a changed provider-turn correlation. Explicit no-active-turn, non-steerable-turn, mismatch, overload, or other rejection is safe for the Core to queue as the next runtime turn. A transport write failure or acknowledgement timeout is delivery-uncertain and is never retried or queued automatically.

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
controls; it only selects the model. During OpenRouter execution, Maverick
translates the saved per-model preference into the OpenRouter `provider`
request object.

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

Large tool-call event payloads are compacted in the runtime recorder before persistence and live event fanout. This Phase 1 behavior protects storage, websocket delivery, runtime replay, UI rendering, and downstream app consumers, but it does not guarantee provider-token reduction for generic shell/tool output.

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
plaintext size, timestamp, and the opaque locator.

Writes are bounded to 2 MiB per blob and 8 MiB per session, serialized under a
namespace file lock, and attached through provider-state revision CAS. A losing
writer deletes its new blob; a winning replacement deletes the prior blob.
Wrong adapter or codec identities, missing keys, ciphertext tamper, digest/size
mismatch, and quota failures produce explicit provider-private recovery reasons.
The ordinary provider-state patch path rejects private envelopes and raw thought
fields. Tool arguments use the same restart-safe encrypted store with a separate
namespace and integrity binding.

## Hosted Agentic Egress Records

`AgenticEgressEvaluator` evaluates every classified content block against its
exact provider/upstream and policy revision before returning bytes to a request
builder. Unknown data class, provenance, trust, provider, or upstream fails
closed. The preview policy exports only `public` and
`workspace_internal_fake`; secret, host-operational, and unclassified content
is always denied. Workspace paths are rewritten to `workspace://` references,
other host paths are denied, and recognizable sensitive text must be redacted.

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

The loop journals a deterministic request id in provider state before transport
acceptance. It performs no blind retry after acceptance. Each model step,
tool call, tool-result byte, input/output token, estimated micro-USD cost, and
wall-clock interval is checked against a policy that may tighten but never
loosen during the turn. Decoded streamed output also has a conservative byte
ceiling, so a provider cannot bypass the limit by delaying usage events. Tool
parallelism remains disabled. Result content stays
in encrypted tool storage and is re-evaluated against the current egress policy
when included in every subsequent request.

Confirmation waiting is represented by the persisted invocation and
`waiting_for_tool_confirmation` turn state. Approval consumes the exact one-shot
grant and refreshes authority before the side effect. Cancellation makes a
still-waiting invocation terminal. Recovery never automatically replays an
ambiguous `executing` mutation; it becomes `execution_unknown`. Public provider
events are bounded JSON and recursively reject private-state field names.

The deterministic fake provider certification covers a two-request streamed
loop, official read and confirmed mutating tools, restart deduplication,
provider-private round-trip, egress records, budgets, cancellation transport
closure, normalized provider failures, and conservative recovery.
