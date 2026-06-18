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
- `/api/inter-agent/runs`
- `/api/inter-agent/runs/<run_id>/events`
- `/api/inter-agent/runs/<run_id>/artifacts`
- `/api/inter-agent/runs/<run_id>/interrupt`
- `/api/inter-agent/runs/<run_id>/resume`
- `/api/inter-agent/runs/<run_id>/close`
- `/api/providers/active`
- `/api/recovery/status`
- `/api/recovery/health`

These routes are generic platform surfaces, not app-owned business APIs.

Primary core WebSocket routes include:

- `/ws/runtime/threads`
- `/ws/runtime/sessions/<session_id>`
- `/ws/inter-agent/runs/<run_id>`

The inter-agent WebSocket serves graph snapshots, bounded replay, history pages,
live event frames, and heartbeats with server-side visibility filtering.

## Core CLI

Discover core commands with:

```bash
./scripts/maverick core cli list --json
```

Important current core commands include:

- `core.workspaces.current`
- `core.runtime.status`
- `core.providers.list`
- `developer-context.list`
- `developer-context.read`

## Core MCP

Discover core MCP tools with:

```bash
./scripts/maverick core mcp list --json
```

Important current tools include:

- `core.workspaces.list`
- `core.runtime.status`
- `core.providers.list`
- `developer-context.list`
- `developer-context.read`

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
