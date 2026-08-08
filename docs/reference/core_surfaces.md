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
- `core.providers.list`
- `core.providers.route`
- `core.providers.hosted.activate`
- `developer-context.list`
- `developer-context.read`
- `core.jobs.submit`
- `core.jobs.list`
- `core.jobs.get`
- `core.jobs.cancel`

## Core MCP

Discover core MCP tools with:

```bash
./scripts/maverick core mcp list --json
```

Important current tools include:

- `core.workspaces.list`
- `core.runtime.status`
- `core.providers.list`
- `core.providers.route`
- `core.providers.hosted.activate`
- `developer-context.list`
- `developer-context.read`
- `core.jobs.submit`
- `core.jobs.list`
- `core.jobs.get`
- `core.jobs.cancel`

## App-Owned CLI And MCP

Do not infer app capabilities from the filesystem alone.

Use:

```bash
./scripts/maverick apps list --json
./scripts/maverick app <app_id> cli list --json
./scripts/maverick app <app_id> mcp list --json
```

## Developer Context

Canonical coding guidance is intentionally exposed through read-only core developer-context surfaces so workspace-bounded agents can read the project rules without raw repository reads outside the workspace boundary.
