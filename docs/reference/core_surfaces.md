# Core Surfaces Reference

This document summarizes the core-facing surfaces external reviewers should know first.

## HTTP / ASGI

Primary control-plane routes include:

- `/health`
- `/api/auth/login`
- `/api/auth/logout`
- `/api/session`
- `/api/workspaces`
- `/api/workspaces/active`
- `/api/apps`
- `/api/app-store/apps`
- `/api/app-store/server-apps`
- `/api/app-store/installations`
- `/api/app-store/install`
- `/api/app-store/install-server`
- `/api/app-store/install-local`
- `/api/app-store/uninstall`
- `/api/runtime/status`
- `/api/runtime/turns/<turn_id>/tool-confirmations/<invocation_id>`
- `/api/providers/hosted/active`
- `/api/inter-agent/runs`
- `/api/inter-agent/runs/<run_id>/events`
- `/api/inter-agent/runs/<run_id>/artifacts`
- `/api/inter-agent/runs/<run_id>/participants/<participant_id>/transcript`
- `/api/inter-agent/runs/<run_id>/interrupt`
- `/api/inter-agent/runs/<run_id>/resume`
- `/api/inter-agent/runs/<run_id>/close`
- `/api/providers/active`
- `/api/jobs`
- `/api/jobs/<job_id>`
- `/api/jobs/<job_id>/cancel`
- `/api/recovery/status`
- `/api/recovery/health`

These routes are generic platform surfaces, not app-owned business APIs.

Primary core WebSocket routes include:

- `/ws/runtime/threads`
- `/ws/runtime/sessions/<session_id>`
- `/ws/inter-agent/runs/<run_id>`
- `/api/jobs/events/ws`

Runtime turn submission is idempotent when callers provide `client_message_id`.
Retries with the same client message id return the already persisted turn instead
of creating a duplicate runtime session or turn. The async submission fast path
persists `runtime.turn.queued` before provider backend resolution. New-session
submission reserves the client message id with a workspace-scoped lease so a
crash before queue persistence can be retried after the lease expires instead of
leaving the id permanently pending. The queue persistence path verifies that the
reserved claim is still current before inserting the turn, so a late handler from
an expired/reclaimed claim cannot materialize a duplicate turn.

`POST /api/runtime/sessions` also accepts `prepare_only` for callers that need to
warm a new chat runtime before the first user message. Prepared sessions are
created with hidden thread visibility, do not appear in the runtime thread
catalog, and may be promoted only by their owner when the first turn is submitted
to `/api/runtime/sessions/<session_id>/turns`. Invalid first-turn submissions do
not promote the session or create a thread. Prepared-session metadata such as the
draft title, project id, agent type id, and agent role id is retained and used
when the visible thread is created. Callers must keep the existing
create-session-with-first-turn path as a fallback when no prepared session is
available.

The runtime records queue timing, worker start, and provider handoff through:

- `runtime.turn.worker_started`
- `runtime.turn.receive_to_queued`
- `runtime.turn.prewarm_waited`
- `runtime.prewarm.started`
- `runtime.prewarm.completed`
- `runtime.prewarm.failed`
- `runtime.provider.dispatching`
- `runtime.provider.turn_start_sent`
- `runtime.provider.accepted`

`runtime.provider.accepted` is the core-owned boundary for "work handed to the
runtime/model"; when `runtime.provider.turn_start_sent` is present, accepted
latency is measured from that handoff point. First model text remains
provider-dependent and is represented by later output events such as
`runtime.output.delta`.

Agentic tool calls use a Core-owned invocation ledger. CLI, MCP, selected app
interfaces, and Core filesystem/shell capabilities are materialized from their
authoritative registries into deterministic provider names. Unknown effect
classifications are not exposed. A mutating or destructive invocation that
requires confirmation moves its turn to `waiting_for_tool_confirmation` and
must be approved or denied through the authenticated confirmation route with
the exact arguments HMAC and invocation revision. Responses expose only the
tool handle, effect class, bounded argument summary, state, revision, and TTL;
they never expose raw arguments, private locators, idempotency keys, or grant
ids. Ambiguous side effects after a crash become `execution_unknown` and are
not replayed automatically.

The runtime thread WebSocket sends a full catalog in `runtime.thread.snapshot`.
Subsequent `runtime.thread.changed` frames may be deltas containing `thread`,
`deleted_thread_ids`, or `deleted_runtime_session_ids` without a full `threads`
array. Clients must upsert/remove deltas and keep full replacement support for
older frames that still include `threads`.

The inter-agent WebSocket serves graph snapshots, bounded replay, history pages,
live event frames, and heartbeats with server-side visibility filtering.

The durable-job WebSocket is authenticated and workspace-filtered. It sends a
bounded persisted `compute.job.snapshot`, live `compute.job.event` frames, and
transport `compute.job.heartbeat` frames. Clients can reconnect with a persisted
event cursor; replay is capped at 200 records.

## Core CLI

Discover core commands with:

```bash
./scripts/maverick core cli list --json
```

Important current core commands include:

- `core.workspaces.current`
- `core.runtime.status`
- `core.runtime.threads.list`
- `core.runtime.transcript.read`
- `core.runtime.transcript.message.read`
- `core.providers.list`
- `core.providers.route`
- `core.providers.hosted.activate`
- `developer-context.list`
- `developer-context.read`
- `core.jobs.submit`
- `core.jobs.list`
- `core.jobs.get`
- `core.jobs.cancel`

Core discovery also exposes dynamic per-app lifecycle commands when their
preconditions hold. In particular, `app.<app_id>.sidecars.restart` appears only
for an enabled workspace binding with declared HTTP sidecars. It is full-access,
revokes only that app/workspace's isolated-browser tickets and sessions,
restarts only the declared sidecars, waits for declared readiness, and emits
`maverick.app.runtime-changed` so Base Shell remounts only that app's iframe and
widgets.

## Core MCP

Discover core MCP tools with:

```bash
./scripts/maverick core mcp list --json
```

Important current tools include:

- `core.workspaces.list`
- `core.runtime.status`
- `core.runtime.threads.list`
- `core.runtime.transcript.read`
- `core.runtime.transcript.message.read`
- `core.providers.list`
- `core.providers.route`
- `core.providers.hosted.activate`
- `developer-context.list`
- `developer-context.read`
- `core.jobs.submit`
- `core.jobs.list`
- `core.jobs.get`
- `core.jobs.cancel`

`core.runtime.status` and `core.recovery.health` are operator-only diagnostic
surfaces. Recovery health requests must name `target_kind` (`runtime`,
`provider`, or `app`) and the matching `session_id`, `provider_id`, or `app_id`;
invalid or incomplete requests return a stable argument error instead of a raw
mapping exception.

The runtime transcript surfaces are owner/admin/grant-scoped and available to
sandboxed agents; full-access mode does not expand their data authority.
`threads.list` searches metadata only after unauthorized threads are removed.
`transcript.read` returns bounded newest-first pages presented in chronological
order, plus `has_more_before`, `next_before_cursor`, a
`snapshot_cursor`, and projection completeness warnings. The opaque cursor
captures physical append positions for both the event archive and eligible
turn-input fallbacks, including empty positions. Later events are excluded by
append position before chronological ordering. Missing queued events may use a
bounded turn input fallback, which is reported by warning and sets
`projection_complete: false`; mutable turn terminal state is never projected.
Long message previews advertise
`content_complete: false` and `next_offset`;
`transcript.message.read` continues the exact redacted text in windows of at
most 12,000 characters. Structured output is bounded by one global node and
16-KiB serialized-content ceiling; `structured_content_truncated`,
`structured_content_complete`, and `structured_content_serialized_bytes` make
any loss explicit. Conversation content is always marked
`untrusted_conversation_data` and must not be interpreted as current
instructions.

## App-Owned CLI And MCP

App `cli/command_schemas.json` and `mcp/tool_schemas.json` descriptors may add
`effect_class` (`read`, `mutating`, or `destructive`),
`supports_idempotency`, and `safe_to_retry`. The last flag is accepted only for
read surfaces. Missing or invalid metadata is `unclassified` and therefore
unavailable to the agentic tool catalog, while the ordinary CLI/MCP surface
remains backward compatible.

A mixed command or tool may add `effect_class_by_argument` with exactly these
fields:

- `argument_name`: one top-level string discriminator in the nested invocation
  arguments;
- `omitted_effect_class`: the class used only when that discriminator is
  absent; and
- `value_effect_classes`: a non-empty exact string-value-to-class map.

The surface-level `effect_class` must be the maximum severity represented by
the omitted and mapped classes. A non-string or unknown discriminator value, a
malformed nested argument object, or an incomplete map resolves to
`unclassified`; it never falls back to `read`.

For hosted execution, an app declaration is a claim rather than execution
authority. A built-in app read is admitted before effect only when the app id,
namespaced surface, platform source path, live descriptor bytes, and parsed
effect metadata match the exact Core-owned audit inventory. Workspace-local or
external app metadata cannot self-authorize. Mutating, destructive, and
unclassified app calls still require a separate certified Core pre-effect
contract. The inventory is versioned at
`core/runtime/hosted_builtin_app_effect_audit.json` and is part of the certified
runtime package/TCB. These hosted checks do not change ordinary human/operator
CLI or MCP invocation behavior.

Do not infer app capabilities from the filesystem alone.

Use:

```bash
./scripts/maverick apps list --json
./scripts/maverick app <app_id> cli list --json
./scripts/maverick app <app_id> mcp list --json
```

## Developer Context

Canonical coding guidance is intentionally exposed through read-only core developer-context surfaces so workspace-bounded agents can read the project rules without raw repository reads outside the workspace boundary.
