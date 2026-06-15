# Runtime Output Compaction

Date: 2026-06-15

Maverick compacts large `runtime.tool_call.*` payloads before the events are persisted, published to the runtime event bus, replayed through runtime history, or consumed by downstream app hooks. Runtime-token CLI calls can also request a provider-oriented compact response for large textual JSON fields.

This is Phase 1: runtime event payload compaction. It reduces storage, websocket, replay, UI, and downstream event payload size. It does not guarantee provider-token reduction for generic shell commands because the provider may already have consumed the raw tool result before Maverick receives the runtime event.

| Phase | Pipeline point | Reduces storage/UI/event bus | Reduces provider tokens | Status |
| --- | --- | --- | --- | --- |
| 1 | `_RuntimeTurnOutputRecorder.record()` before `record_runtime_event` | Yes | Not guaranteed | Implemented |
| 2 | Controlled Maverick CLI through `/api/runtime/cli` with `output_profile` in the JSON body | Yes | Yes, only for that controlled CLI surface | Implemented |
| 3 | Maverick-owned provider hook or tool broker before generic shell/tool results enter provider history | Yes | Yes, only after end-to-end proof | Future |

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

This phase reduces provider tokens only for controlled Maverick CLI calls routed through `/api/runtime/cli`. It still does not compact arbitrary shell command output before the provider consumes it.

## Operations

Set `MAVERICK_RUNTIME_OUTPUT_COMPACTION=0` to disable runtime output compaction in an emergency, including provider-compact CLI response processing.

The first implementation keeps original artifacts out of Storage and Memory. It also avoids observability logs that include raw tool output.
