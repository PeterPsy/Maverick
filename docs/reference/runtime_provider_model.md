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

The provider adapter owns:

- provider process launch
- provider session or thread linking
- provider-specific protocol translation
- optional same-turn message admission when the provider declares `supports_same_turn_input`

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

Chat may create hidden `prepare_only` runtime sessions before the first message. The create response waits for provider prewarm for at most two seconds and reports `prewarm_status`, `prewarm_completed`, and `provider_thread_ready`. A client must treat the session as ready only when prewarm completed and the provider thread is ready; a session record existing is not sufficient. Plain hosted chat reports prewarm as `not_required` and ready because it has no local provider process or thread to warm.

Codex turn startup emits separate runtime events for `ensure_runtime`, generated-system-skill cleanup, `ensure_thread`, event-sink reset, and the `turn/start` write boundary. Each start/completed pair is persisted under `runtime.provider.*`, while `runtime.provider.turn_start_sent` remains the write-complete marker and provider acceptance carries `turn_start_request_ack_ms`. This keeps cold-process, cleanup, cold-thread, local reset, request-write, and provider-ack latency distinguishable. Generated `.system` skills are removed on runtime initialization/prewarm and only checked again when that runtime home may need cleanup; a warm turn does not recursively remove an already-clean tree.

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
pages the append-only event history through `RuntimeStore.list_event_page()`;
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
snapshot stable after later writes. Structured visible output applies
case/separator-insensitive sensitive-key filtering and one global node and JSON
byte budget. Its response
metadata states whether the structured payload is complete or truncated.
