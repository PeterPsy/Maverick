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

Use `frontend-backend` for a mounted React/Vite visual app that calls its backend at:

```text
/api/apps/<app_id>/backend
```

Use `agent-tool` for apps that expose CLI, MCP, and skill surfaces.

Use `data-app` for a stateful React/Vite app with lifecycle hooks and JSON app-owned data.

Use `widget` for an app that declares a React/Vite base-shell widget surface.

Use `react-vite` for a mounted frontend app with React/Vite source and official rebuild support.

Use `entity-sqlite` for record-centric apps with SQLite persistence, entities, reference metadata, view surfaces, CLI, MCP, hooks, generated entrypoint tests, and official rebuild support.

## Commands

Inside an agent runtime, use the workspace-local `maverick` command. It targets the current workspace through the runtime token issued by Maverick:

```bash
maverick core cli run core.app-sdk.create --app-id my-app --template-id data-app --json
maverick sdk docs
maverick core cli run core.app-sdk.validate --app-id my-app --workspace default --json
maverick core cli run core.app-sdk.register-local --app-id my-app --workspace default --json
maverick core cli run core.app-sdk.install-local --app-id my-app --workspace default --json
maverick core cli run core.app-sdk.status --app-id my-app --workspace default --json
maverick core cli run core.app-sdk.package --app-id my-app --workspace default --json
```

The repository also includes an operator/development wrapper for local source-tree work:

```bash
scripts/maverick core cli run core.app-sdk.create --app-id my-app --template-id entity-sqlite --entities '["account","contact"]' --json
scripts/maverick core cli run core.app-sdk.validate --app-id my-app --workspace default --json
scripts/maverick core cli run core.app-sdk.register-local --app-id my-app --workspace default --json
scripts/maverick core cli run core.app-sdk.install-local --app-id my-app --workspace default --json
scripts/maverick core cli run core.app-sdk.status --app-id my-app --workspace default --json
scripts/maverick core cli run core.app-sdk.package --app-id my-app --workspace default --json
```

If `maverick` is not available inside an agent runtime, the SDK runtime surface is missing and the app should not be created by manually copying another app.

## Surface Discipline

The SDK generates valid starting source trees and `maverick core cli run core.app-sdk.validate --app-id <app_id> --json` now blocks incomplete declared surfaces before SDK register, install, or package operations proceed. Developers still need to make the runtime behavior behind those surfaces real.

Rules:

- Do not leave `app_contract.json` ahead of the implementation.
- Keep declared CLI, MCP, frontend view, skills, reference-entity, view-state, and data-event surfaces aligned with the matching entrypoints.
- If you declare CLI commands, they must be discoverable through `maverick app <app_id> cli list --json`.
- If you declare MCP tools, they must be discoverable through `maverick app <app_id> mcp list --json`.
- If you declare `reference_entities`, implement matching reference behavior through manifest, search, resolve, and summarize actions.
- If you declare `view_surfaces`, implement real persisted or derived view state plus the standard view-state actions and `view-state` data event.
- If you declare a frontend entrypoint, ship a real `package.json` build script and use the official frontend rebuild operation.
- If app writes emit `app_events`, wire the frontend or widget to consume `maverick.app.data-changed` or `maverick.widget.data-changed` so mounted UI updates live.
- Put frontend behavior in React source under `frontend/src`; Vite HTML files should stay as thin mount documents.

The contract is an executable promise, not aspirational metadata.

## Completeness Baseline

In this repository, a valid app is not considered complete until:

- the app root has a `README.md`
- the test suite contains smoke coverage for the app contract
- `capabilities.skills` matches bundled skill template ids when `skills/` exists
- any intentional omission of backend, hooks, references, data events, or view surfaces is documented in the app README

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
- `package.json`
- `tsconfig.json`
- `vite.config.ts`
- `frontend/index.html`
- `frontend/src/main.tsx`
- `frontend/src/styles.css`
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

The contract points to `frontend/dist`, so the generated app is mountable immediately. When dependencies are installed, refresh production assets through the official core lifecycle path:

```text
maverick app <app_id> frontend build --json
```

That command runs the declared app frontend build and emits the mounted-frontend refresh event after success.

The same rebuild rule applies to every generated template that declares a frontend.

## Entity SQLite App

The `entity-sqlite` template is the recommended scaffold for record-centric apps:

```bash
scripts/maverick core cli run core.app-sdk.create --app-id mini-records --template-id entity-sqlite --entities '["account","contact","deal"]' --json
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
- Run `maverick app <app_id> frontend build --json` for apps that declare a frontend entrypoint.
- Keep SDK-generated frontend behavior in React source and let the generated `tsc --noEmit && vite build` script type-check before publishing assets.
- When the app emits data-change events, make mounted frontend and widget surfaces refresh from those events instead of requiring manual reloads.
- Keep app data under `data/<app_id>`.
- Keep app behavior inside the app.
- Use CLI/MCP/backend surfaces for operations.
- Use skills only as procedural instructions.
- Do not read another app's private data files.
