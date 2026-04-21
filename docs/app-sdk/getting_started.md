# Maverick App SDK Getting Started

Date: 2026-04-21

## What The SDK Does

The Maverick App SDK creates valid Maverick app source trees and moves workspace-local apps through the official lifecycle:

1. create source
2. validate contract
3. register local project
4. install into workspace
5. inspect status

The SDK does not bypass the core. It uses the same app contract parser and app-hosting flows used by Maverick itself.

## Templates

Available initial templates:

- `minimal`
- `frontend-backend`
- `agent-tool`
- `data-app`
- `widget`

Use `minimal` when defining a contract-first skeleton.

Use `frontend-backend` for a mounted visual app that calls its backend at:

```text
/api/apps/<app_id>/backend
```

Use `agent-tool` for apps that expose CLI, MCP, and skill surfaces.

Use `data-app` for a stateful app with lifecycle hooks and JSON app-owned data.

Use `widget` for an app that declares a base-shell widget surface.

## Commands

The core command ids are:

```text
core.app-sdk.create
core.app-sdk.validate
core.app-sdk.register-local
core.app-sdk.install-local
core.app-sdk.status
core.app-sdk.package
```

The intended human command shape is:

```bash
maverick app create my-app --template data-app --workspace default
maverick app validate my-app --workspace default
maverick app register-local my-app --workspace default
maverick app install-local my-app --workspace default
maverick app status my-app --workspace default
maverick app package --app-root workspaces/default/apps/my-app
```

Until a shell executable wraps the core CLI registry, tests and platform surfaces invoke these commands by command id.

## Workspace-Local App Flow

Generated workspace-local apps live under:

```text
workspaces/<workspace_id>/apps/<app_id>/
```

They store their data under:

```text
workspaces/<workspace_id>/data/<app_id>/
```

Creating source files is not enough. A workspace-local app becomes visible only after registration and installation.

## Generated Data App

A `data-app` includes:

- `app_contract.json`
- `backend/app_backend.py`
- `cli/app_cli.py`
- `mcp/server.py`
- `hooks/install.py`
- `hooks/migrate.py`
- `hooks/health_check.py`
- `frontend/dist/index.html`
- `skills/<app_id>-ops/SKILL.md`
- `tests/test_contract.py`

## Packaging

The SDK can package a valid app source tree into a deterministic `tar.gz` artifact. Packaging validates the contract first and excludes local junk such as `node_modules`, `__pycache__`, runtime state, temp files, logs, and local databases.

The install hook creates:

```text
data/<app_id>/state.json
```

The hook is idempotent and can be run more than once.

## Development Rules

- Keep `app_contract.json` honest.
- Declare only surfaces that exist.
- Keep app data under `data/<app_id>`.
- Keep app behavior inside the app.
- Use CLI/MCP/backend surfaces for operations.
- Use skills only as procedural instructions.
- Do not read another app's private data files.
