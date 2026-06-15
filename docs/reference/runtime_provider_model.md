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
- Maverick-managed Codex agents install a Maverick-owned `PostToolUse` hook for `Bash` so large shell outputs can be compacted before Codex continues from the tool result when Codex accepts and runs that hook under its hook-trust policy
- non-default workspaces are intended to remain sandbox-first
- provider adapters may need helper binaries such as `rg`
- network access for providers is not equivalent to unconstrained filesystem access
- shell settings can list runtime sessions across workspaces visible to the authenticated user, terminate individual sessions, and clear visible session records in batch through controlled settings runtime-session endpoints

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

Runtime-token CLI responses can request provider-oriented compaction for controlled Maverick CLI calls, and Maverick-managed Codex sessions install a Maverick-owned `PostToolUse` hook to replace large `Bash` tool results before those results enter Codex provider history when the hook is trusted or delivered through a Codex-supported managed configuration path.

See `docs/reference/runtime_output_compaction.md` for the event contract, provider hook contract, operational flag, and Phase 1/2/3 status.
