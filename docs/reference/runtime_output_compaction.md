# Runtime Output Compaction

Date: 2026-06-19

Maverick compacts large `runtime.tool_call.*` payloads before the events are persisted, published to the runtime event bus, replayed through runtime history, or consumed by downstream app hooks. Runtime-token CLI calls can also request a provider-oriented compact response for large textual JSON fields. Maverick-managed Codex sessions additionally install a provider hook that can replace large shell tool results before Codex continues from the tool output when Codex actually runs the trusted hook.

Phase 1 reduces storage, websocket, replay, UI, and downstream event payload size. It does not guarantee provider-token reduction for generic shell commands because the provider may already have consumed the raw tool result before Maverick receives the runtime event. Phase 2 reduces provider context for controlled Maverick CLI calls. Phase 3 reduces provider context for Maverick-managed Codex `Bash` shell tool results when Codex runs the Maverick-owned `PostToolUse` hook.

| Phase | Pipeline point | Reduces storage/UI/event bus | Reduces provider tokens | Status |
| --- | --- | --- | --- | --- |
| 1 | `_RuntimeTurnOutputRecorder.record()` and the `record_runtime_event()` persistence guard | Yes | Not guaranteed | Implemented |
| 2 | Controlled Maverick CLI through `/api/runtime/cli` with `output_profile` in the JSON body | Yes | Yes, only for that controlled CLI surface | Implemented |
| 3 | Maverick-owned Codex `PostToolUse` hook before supported shell tool results enter provider history | Yes, when the hook runs | Only when Codex accepts and runs the trusted hook | Integrated; hard provider-token guarantee requires a trusted-hook end-to-end proof |

Phase 1 deliberately does not compact `runtime.output.delta`, because those deltas are used to reconstruct assistant text through `final_text()` and `complete_text()`. The turn output recorder performs compaction before normal turn persistence, and `record_runtime_event()` repeats the same idempotent guard for direct future callers that persist `runtime.tool_call.*` events. The persistence guard does not trust self-reported `output_compaction` metadata by itself; it only skips reprocessing when the payload is already bounded, redaction-clean, and its provider `raw` payload already matches the configured raw sanitization policy.

## Event Contract

For long tool-call output, Maverick redacts free-form text, applies a rule-based reducer, sanitizes duplicative provider `raw` fields such as `raw.item.aggregatedOutput`, and stores metadata under `payload.output_compaction`. Tool-call descriptor fields that are persisted outside the output body, including `command`, `summary`, `cwd`, `query`, and string `argv` entries, are redacted before normalization so secrets do not remain in compacted event metadata or websocket frames.

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

Redacted pass-through paths are also size-bounded when they would exceed the active target budget. This includes reducer failures, below-threshold outputs that are still larger than the UI/provider budget, and outputs whose semantic reducer did not meet the required savings ratio. Maverick keeps `applied: false` and the original `pass_through_reason`, writes a canonical `[tool output bounded]` field, empties omitted `stdout`/`stderr` strings, and records `bounded_pass_through: true` plus omission markers in metadata. Compactor-error fallback uses the same budget discipline with a `compactor_failed` marker.

Built-in match rules are declarative JSON files under `core/runtime/output_compaction/builtin_rules/`. A rule can match by command or by output text, which keeps command-family reducers effective for real outputs such as `git status --short --branch` and `git status --porcelain` that do not contain the long-form status headings. For failed commands, command-only selection is guarded by the rule's text patterns; if the output lacks a family-specific signal, Maverick falls back to the generic diagnostic reducer so fatal/error lines are preserved. The loader rejects unknown top-level or `match` fields, disables a single rule with diagnostics when one of its regexes is invalid, and never executes code from rule data. Reducers remain Maverick-owned Python functions selected by the validated rule id/reducer name.

## Runtime CLI Profile

`/api/runtime/cli` accepts an optional JSON body field:

```json
{
  "argv": ["core", "cli", "list", "--json"],
  "output_profile": "provider_compact"
}
```

Allowed values are `full` and `provider_compact`. Missing `output_profile` means `full`, preserving complete responses for external scripts and operator clients. `provider_compact` is accepted only on the runtime-token-authenticated CLI API; authority still comes from the token-bound runtime session, not from `effective_mode`, `workspace_id`, or other client-supplied body fields.

When `provider_compact` is requested, the API runs the CLI normally, preserves `status_code` and HTTP status behavior, and compacts large textual JSON fields before returning the response. It also redacts recognizable sensitive text and any value under a sensitive structured key, including non-string scalars, objects, and lists, even when the field is below the compaction size threshold, because the runtime-local shim normally sends this stdout into provider context. The same redaction and compaction policy is applied to `SystemExit` and unexpected exception `detail` fields raised while invoking the CLI. Metadata is added under top-level `output_compaction` with `scope: runtime_cli_response`. The runtime-local `maverick` shim requests `provider_compact` by default; agents can set `MAVERICK_RUNTIME_CLI_OUTPUT_PROFILE=full` when they need the exact full JSON payload.

`provider_compact` deliberately preserves explicit document-body fields from truncation for read surfaces where shortening would corrupt the requested source material. Redaction still runs on those fields, and redacted document bodies receive `output_compaction` metadata with `applied: false`. Current preserved top-level fields are developer-context `content`, Storage `file.text.read` `text`, and Storage preview or handoff `preview_text` when the response shape identifies Storage file metadata. Other large text fields remain eligible for compaction.

For large JSON payloads, the structured reducer first checks for app-style semantic result lists such as top-level `items` or `results` containing objects with retrieval markers like `kind`, `entity`, `locator`, or `node_id`. Those payloads are summarized as semantic items that preserve ids, titles, summaries, bounded body snippets, body length counts, compact citations, source chunk ids, provenance, Storage references, compiled summaries, and expansion-safe metadata before falling back to the generic top-level-key and array-sample reducer. This prevents provider-history compaction from turning app retrieval payloads into an unhelpful structural sample.

If the CLI response compactor fails unexpectedly for a large field, the API returns that field as redacted pass-through text and records `pass_through_reason: compactor_failed` plus a non-sensitive `compaction_error` class name in the compaction metadata.

This phase reduces provider tokens only for controlled Maverick CLI calls routed through `/api/runtime/cli`. It still does not compact arbitrary shell command output before the provider consumes it.

## Provider Hook Profile

Maverick-managed Codex runtime homes install `runtime/sessions/<runtime_session_id>/bin/maverick_codex_post_tool_use_hook.py` and write a Maverick-owned `[[hooks.PostToolUse]]` entry into the session-scoped `CODEX_HOME/config.toml` with a conservative shell-only matcher for `Bash`, `shell`, `shell_command`, `local_shell`, and `exec_command`. The same config writes a matching `hooks.state."<config-path>:post_tool_use:0:0".trusted_hash` entry for the generated command identity so Codex can treat the session-local hook as trusted. Inherited operator-home `hooks.*` sections are removed so runtime sessions use the Maverick-owned hook configuration.

Maverick also writes `experimental_use_unified_exec_tool = false` into the session `config.toml` and removes inherited values for that key from the operator home and profiles. Codex 0.130 surfaces rich shell calls as `exec_command` through its newer `unified_exec` mechanism, but Codex documents `PostToolUse` coverage for that path as incomplete. Until Codex exposes a trusted pre-history hook point for `unified_exec`, Maverick-managed runtime sessions force the simpler `Bash` tool path so `PostToolUse` can run before shell output enters provider history.

Codex still owns hook trust enforcement. Maverick generates the trusted hash using Codex's normalized command-hook identity shape for the installed hook. If a future Codex release changes that identity or refuses user-config hook state for runtime-local homes, the provider-hook diagnostics file will remain absent and Codex hook listing should be used to inspect the trust status.

When Codex runs the hook, it posts the `PostToolUse` JSON payload to `/api/runtime/provider-hooks/codex/post-tool-use` with the session runtime token. The API validates token lifecycle, workspace, session id, and execution mode before compacting. When the payload should be replaced, the API returns Codex hook JSON with `decision: "block"`, `continue: false`, and `reason` set to the compacted/redacted text. Codex records that feedback in place of the original shell result and continues the model from the replacement message.

Provider-hook compaction metadata uses `scope: provider_history_tool_result`. It reuses the same redaction and reducer pipeline as runtime event compaction, but with a provider-history policy: no original artifact is stored, raw provider payload sanitization is not needed, and size targets are lower because the text is about to enter model context.

If the core compactor raises unexpectedly, the API still returns a bounded redacted hook response with `pass_through_reason: compactor_failed`. If the hook bridge cannot reach the API, the standalone runtime-local script falls back to bounded generic redaction and truncation with `pass_through_reason: hook_bridge_unavailable`. The standalone fallback mirrors the core text-redaction coverage for common headers, key-like sensitive headers such as `X-API-Key`, cookies, query secrets with varied casing, signed-URL secret parameters, `.env`-style secrets, inline key assignments in exception text, URL credentials, JWTs, private keys, common provider/GitHub token prefixes, and the provider-hook E2E canary pattern. If `MAVERICK_RUNTIME_OUTPUT_COMPACTION=0`, both the API compactor and the standalone fallback stay disabled.

Current automated tests cover the Maverick-owned hook configuration, Codex trust-state rendering and hash identity, runtime-token API, response format, fallback redaction, diagnostics, replacement payload, E2E canary redaction, and a simulated runtime-local hook bridge that emits backend replacement output with `bridge_status: "returned_emit"`. They do not constitute a real Codex app-server trusted-hook proof. This phase does not claim provider-token reduction outside the currently hooked Codex shell surface, or for Codex sessions where the hook is installed but not run by Codex. It does not cover unhooked Codex tool mechanisms, web search, provider-internal tool calls, or future non-Codex providers until those providers expose and pass an equivalent pre-history proof point.

## Provider Hook Diagnostics

The runtime-local hook writes redaction-safe JSONL diagnostics to:

```text
workspaces/<workspace_id>/runtime/sessions/<runtime_session_id>/logs/provider-hook-events.jsonl
```

From inside the workspace root, the same file is under `runtime/sessions/<runtime_session_id>/logs/provider-hook-events.jsonl`. A typical check is:

```bash
tail -n 20 runtime/sessions/<runtime_session_id>/logs/provider-hook-events.jsonl
```

Each line contains only safe fields: timestamp, hook event name, tool name, whether the runtime token was present, whether `MAVERICK_API_BASE` was explicitly set, whether compaction was disabled, top-level payload keys, extracted text byte count, bridge status, and fallback status. It must not contain `tool_response`, stdout, stderr, full commands, bearer tokens, or raw output.

Interpret the file as follows:

- Hook not invoked: the file is absent, or no new line appears for the test window. Check `CODEX_HOME/config.toml`, the `PostToolUse` matcher, the generated `hooks.state` trusted hash, whether `experimental_use_unified_exec_tool` is still disabled, and Codex hook trust/review behavior.
- Hook invoked but bridge unreachable: a heartbeat line appears with `bridge_status: "called"`, followed by a final line with `bridge_status: "unavailable"`. `fallback_status: "emitted"` means the standalone fallback returned a compacted replacement without a backend POST; other fallback statuses explain why no fallback replacement was emitted.
- Hook invoked and API returned no emit: the final line has `bridge_status: "returned_no_emit"`. The POST reached `/api/runtime/provider-hooks/codex/post-tool-use`, but the API decided the provider-visible result should remain unchanged, usually because the payload had no supported shell text, was below threshold without redaction, or compaction was disabled.
- Hook invoked and replacement emitted: the final line has `bridge_status: "returned_emit"`. The POST reached the backend and the API returned a Codex hook response with compacted/redacted replacement text. The provider-visible tool result should contain `[tool output compacted]` and `scope: provider_history_tool_result`.

## Operations

Set `MAVERICK_RUNTIME_OUTPUT_COMPACTION=0` to disable runtime output compaction in an emergency, including provider-compact CLI response processing and Codex provider-hook fallback processing.

The first implementation keeps original artifacts out of Storage and Memory. It also avoids observability logs that include raw tool output.
