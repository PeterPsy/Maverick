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
- `react-vite`
- `entity-sqlite`

Use `minimal` when defining a contract-first skeleton.

Use `frontend-backend` for a mounted visual app that calls its backend at:

```text
/api/apps/<app_id>/backend
```

Use `agent-tool` for apps that expose CLI, MCP, and skill surfaces.

Use `data-app` for a stateful app with lifecycle hooks and JSON app-owned data.

Use `widget` for an app that declares a base-shell widget surface.

Use `react-vite` for a mounted frontend app with React/Vite source and official rebuild support.

Use `entity-sqlite` for CRM-like apps with SQLite persistence, entities, reference metadata, view surfaces, CLI, MCP, hooks, generated entrypoint tests, and official rebuild support.

## Commands

Inside an agent runtime, use the workspace-local `maverick` command. It targets the current workspace through the runtime token issued by Maverick:

```bash
maverick app create my-app --template data-app
maverick sdk docs
maverick app validate my-app
maverick app register-local my-app
maverick app install-local my-app
maverick app status my-app
maverick app package my-app
```

The repository also includes an operator/development wrapper for local source-tree work:

```bash
scripts/maverick app create my-app --template entity-sqlite --entity account --entity contact
scripts/maverick app validate my-app --workspace default
scripts/maverick app register-local my-app --workspace default
scripts/maverick app install-local my-app --workspace default
scripts/maverick app status my-app --workspace default
scripts/maverick app package --app-root workspaces/default/apps/my-app
```

If `maverick` is not available inside an agent runtime, the SDK runtime surface is missing and the app should not be created by manually copying another app.

## Surface Discipline

The SDK generates valid starting source trees, but developers still need to make the declared surfaces real.

Rules:

- Do not leave `app_contract.json` ahead of the implementation.
- If you declare CLI commands, they must be discoverable through `maverick app <app_id> cli list --json`.
- If you declare MCP tools, they must be discoverable through `maverick app <app_id> mcp list --json`.
- If you declare `reference_entities`, implement matching reference behavior through manifest, search, resolve, and summarize actions.
- If you declare `view_surfaces`, implement real persisted or derived view state plus the declared state actions.
- If you declare `lifecycle.rebuild: true`, ship a real `package.json` build script and use the official frontend rebuild operation.

The contract is an executable promise, not aspirational metadata.

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

## React/Vite App

The `react-vite` template includes:

- `package.json`
- `tsconfig.json`
- `vite.config.ts`
- `frontend/index.html`
- `frontend/src/main.tsx`
- `frontend/src/styles.css`
- `frontend/dist/index.html`

The contract points to `frontend/dist`, so the generated app is mountable immediately. The generated contract also declares `lifecycle.rebuild: true`. When dependencies are installed, refresh production assets through the official core lifecycle path:

```text
maverick app <app_id> frontend build --json
```

That command runs the declared app frontend build and emits the mounted-frontend refresh event after success.

The same rebuild rule applies to buildable frontend templates such as `entity-sqlite`.

## Entity SQLite App

The `entity-sqlite` template is the recommended scaffold for CRM-like apps:

```bash
scripts/maverick app create mini-crm --template entity-sqlite --entity account --entity contact --entity deal
```

It generates:

- SQLite schema and store under `backend/`
- list/create/get/search actions
- backend, CLI, and MCP entrypoints
- reference entity metadata
- view surface contract metadata
- lifecycle hooks
- skill template
- React/Vite source
- generated entrypoint tests

`entity-sqlite` is the canonical SDK example when an app needs all of these together:

- frontend
- backend
- CLI
- MCP
- reference entities
- view surfaces
- official frontend rebuild support

## Developer Kit

The `developer-kit` app provides a browser UI for SDK workflows. It is workspace-visible rather than admin-only, so any workspace user can learn the SDK and create, validate, register, install, inspect, and package workspace-local app source through the authenticated SDK API.

## Development Rules

- Keep `app_contract.json` honest.
- Declare only surfaces that exist.
- Verify every declared surface with scoped `list` and `inspect` commands.
- Treat `reference_entities` and `view_surfaces` as real implementation work, not contract decoration.
- Run `maverick app <app_id> frontend build --json` for apps that declare `lifecycle.rebuild: true`.
- Keep app data under `data/<app_id>`.
- Keep app behavior inside the app.
- Use CLI/MCP/backend surfaces for operations.
- Use skills only as procedural instructions.
- Do not read another app's private data files.
