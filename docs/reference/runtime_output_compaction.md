# Runtime Output Compaction

Date: 2026-06-15

Maverick compacts large `runtime.tool_call.*` payloads before the events are persisted, published to the runtime event bus, replayed through runtime history, or consumed by downstream app hooks. Runtime-token CLI calls can also request a provider-oriented compact response for large textual JSON fields. Maverick-managed Codex sessions additionally install a provider hook that can replace large shell tool results before Codex continues from the tool output.

Phase 1 reduces storage, websocket, replay, UI, and downstream event payload size. It does not guarantee provider-token reduction for generic shell commands because the provider may already have consumed the raw tool result before Maverick receives the runtime event. Phase 2 reduces provider context for controlled Maverick CLI calls. Phase 3 reduces provider context for Maverick-managed Codex `Bash` tool results intercepted by the managed `PostToolUse` hook.

| Phase | Pipeline point | Reduces storage/UI/event bus | Reduces provider tokens | Status |
| --- | --- | --- | --- | --- |
| 1 | `_RuntimeTurnOutputRecorder.record()` before `record_runtime_event` | Yes | Not guaranteed | Implemented |
| 2 | Controlled Maverick CLI through `/api/runtime/cli` with `output_profile` in the JSON body | Yes | Yes, only for that controlled CLI surface | Implemented |
| 3 | Maverick-owned Codex `PostToolUse` hook before `Bash` tool results enter provider history | Yes | Yes, for Maverick-managed Codex `Bash` tool results intercepted by the hook | Implemented |

Phase 1 deliberately does not compact `runtime.output.delta`, because those deltas are used to reconstruct assistant text through `final_text()` and `complete_text()`.

## Event Contract

For long tool-call output, Maverick redacts free-form text, applies a rule-based reducer, sanitizes duplicative provider `raw` fields such as `raw.item.aggregatedOutput`, and stores metadata under `payload.output_compaction`.

The metadata includes:

- `version: 1`
- `scope: runtime_event_payload`
- `applied`
- `rule_id` and `family`
- original, redacted, and compacted byte counts
- `savings_ratio`
- the required savings ratio used for the decision
- `digest_kind: redacted_sha256`
- `digest`
- affected fields and pass-through reason

The persisted digest is computed from redacted text. Maverick does not persist a default hash of the unredacted raw output.

If a reducer or compactor step fails unexpectedly, the event is still recorded with a redacted pass-through payload, sanitized `raw`, `pass_through_reason: compactor_failed`, and a non-sensitive `compaction_error` class name. If redaction itself fails for a large payload, Maverick records a bounded redaction-failure placeholder instead of persisting unredacted tool output.

## Runtime CLI Profile

`/api/runtime/cli` accepts an optional JSON body field:

```json
{
  "argv": ["core", "cli", "list", "--json"],
  "output_profile": "provider_compact"
}
```

Allowed values are `full` and `provider_compact`. Missing `output_profile` means `full`, preserving complete responses for external scripts and operator clients. `provider_compact` is accepted only on the runtime-token-authenticated CLI API; authority still comes from the token-bound runtime session, not from `effective_mode`, `workspace_id`, or other client-supplied body fields.

When `provider_compact` is requested, the API runs the CLI normally, preserves `status_code` and HTTP status behavior, and compacts large textual JSON fields before returning the response. Metadata is added under top-level `output_compaction` with `scope: runtime_cli_response`. The runtime-local `maverick` shim requests `provider_compact` by default because its stdout is normally destined for provider context; agents can set `MAVERICK_RUNTIME_CLI_OUTPUT_PROFILE=full` when they need the exact full JSON payload.

If the CLI response compactor fails unexpectedly for a large field, the API returns that field as redacted pass-through text and records `pass_through_reason: compactor_failed` plus a non-sensitive `compaction_error` class name in the compaction metadata.

This phase reduces provider tokens only for controlled Maverick CLI calls routed through `/api/runtime/cli`. It still does not compact arbitrary shell command output before the provider consumes it.

## Provider Hook Profile

Maverick-managed Codex runtime homes install `runtime/sessions/<runtime_session_id>/bin/maverick_codex_post_tool_use_hook.py` and write a managed `[[hooks.PostToolUse]]` entry into the session-scoped `CODEX_HOME/config.toml` with `matcher = "^Bash$"`. Inherited operator-home `hooks.*` sections are removed so runtime sessions use the Maverick-managed hook configuration.

The hook posts Codex's `PostToolUse` JSON payload to `/api/runtime/provider-hooks/codex/post-tool-use` with the session runtime token. The API validates token lifecycle, workspace, session id, and execution mode before compacting. When the payload should be replaced, the API returns Codex hook JSON with `decision: "block"`, `continue: false`, and `reason` set to the compacted/redacted text. Codex records that feedback in place of the original `Bash` result and continues the model from the replacement message.

Provider-hook compaction metadata uses `scope: provider_history_tool_result`. It reuses the same redaction and reducer pipeline as runtime event compaction, but with a provider-history policy: no original artifact is stored, raw provider payload sanitization is not needed, and size targets are lower because the text is about to enter model context.

If the core compactor raises unexpectedly, the API still returns a redacted pass-through hook response with `pass_through_reason: compactor_failed`. If the hook bridge cannot reach the API, the standalone runtime-local script falls back to bounded generic redaction and truncation with `pass_through_reason: hook_bridge_unavailable`. If `MAVERICK_RUNTIME_OUTPUT_COMPACTION=0`, both the API compactor and the standalone fallback stay disabled.

This phase does not claim provider-token reduction outside the currently hooked Codex `Bash` surface. It does not cover unhooked Codex tool mechanisms, web search, provider-internal tool calls, or future non-Codex providers until those providers expose and pass an equivalent pre-history proof point.

## Operations

Set `MAVERICK_RUNTIME_OUTPUT_COMPACTION=0` to disable runtime output compaction in an emergency, including provider-compact CLI response processing and Codex provider-hook fallback processing.

The first implementation keeps original artifacts out of Storage and Memory. It also avoids observability logs that include raw tool output.
