# Runtime Output Compaction

Date: 2026-06-15

Maverick compacts large `runtime.tool_call.*` payloads before the events are persisted, published to the runtime event bus, replayed through runtime history, or consumed by downstream app hooks.

This is Phase 1: runtime event payload compaction. It reduces storage, websocket, replay, UI, and downstream event payload size. It does not guarantee provider-token reduction for generic shell commands because the provider may already have consumed the raw tool result before Maverick receives the runtime event.

| Phase | Pipeline point | Reduces storage/UI/event bus | Reduces provider tokens | Status |
| --- | --- | --- | --- | --- |
| 1 | `_RuntimeTurnOutputRecorder.record()` before `record_runtime_event` | Yes | Not guaranteed | Implemented |
| 2 | Controlled Maverick CLI through `/api/runtime/cli` with `output_profile` in the JSON body | Yes | Yes, only for that controlled CLI surface | Future |
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

## Operations

Set `MAVERICK_RUNTIME_OUTPUT_COMPACTION=0` to disable Phase 1 compaction in an emergency.

The first implementation keeps original artifacts out of Storage and Memory. It also avoids observability logs that include raw tool output.
