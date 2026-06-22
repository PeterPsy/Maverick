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

## Hosted Model Providers And Plain Hosted Chat

Provider records distinguish `provider_role` from the lower-level provider `kind`.
Codex is a `runtime_engine` and remains the default agentic runtime. Groq and
DeepSeek are `model_provider` records for hosted text generation; they are not
runtime backends and must not be configured through the workspace runtime
provider selection path.

Hosted text providers are enabled through an operator-only hosted activation
path, not through `/api/providers/active`. The activation path stores an active
provider definition, binds a Core Secrets `secret_ref` as provider credential
metadata, and returns a redaction-safe routing preflight decision:

- HTTP: `POST /api/providers/hosted/active`
- CLI: `core.providers.hosted.activate`
- MCP: `core.providers.hosted.activate`

The activation responses expose provider ids, binding ids, model ids, and
reason codes. They do not expose raw secret values or secret refs.

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

The only supported Chat routing profile for this bridge is `fast_model`.
Runtime HTTP requests may omit `routing_profile` or pass `fast_model`; any other
provided value is rejected with `unsupported_routing_profile` instead of being
silently ignored.

The bridge is deliberately narrower than an agentic runtime. Before prompt
materialization it rejects skills, tool/MCP use, workspace filesystem access,
operative attachments, and operative app references. Hosted text requests must
not contain local workspace paths, `local path:` labels, or materialized
app-owned record blocks. Routing decisions, runtime events, logs, transcripts,
Storage artifacts, CLI/MCP payloads, and HTTP responses may expose provider ids,
model ids, binding ids, grants, and reason codes, but never raw secret values.

## Deferred Speech Provider Boundary

Deepgram, Cartesia, and Kokoro-hosted are metadata-only `speech_provider`
records until a later realtime audio slice implements governed STT/TTS
execution. They declare future remote capability and credential shape, but they
do not create a voice runtime path in this slice.

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
