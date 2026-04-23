# App SDK Architecture

Date: 2026-04-21

## Purpose

Define the official Maverick App SDK as a developer surface for creating Maverick apps without weakening the v3 platform boundary.

The SDK helps humans and agents create, validate, register, install, and inspect app source trees. It does not replace the app contract, app-hosting lifecycle, workspace boundary, or app-owned data rules.

## Boundary

The SDK is a core-owned developer tool because it operates on platform contracts and app-hosting flows. It must remain generic and app-agnostic.

The SDK may:

- generate app source trees from official templates
- validate app source trees through the canonical app contract parser
- register workspace-local app projects through generic app-hosting registration
- install workspace-local app projects through generic app-hosting installation
- report source, registration, installation, and validation state
- package valid app source trees into deterministic artifacts
- expose a thin terminal wrapper over the workspace-scoped SDK API
- provide a Developer Kit app UI for app source creation and validation
- provide small runtime helpers for generated backend, hook, CLI, and MCP entrypoints

The SDK must not:

- add app-specific conditionals to the core
- write app business data outside `workspaces/<workspace_id>/data/<app_id>/`
- make one app depend on another app's private files
- bypass App Store, CLI, MCP, or backend APIs for platform-owned state
- create compatibility shims for Maverick v2

## Source Roots

The SDK supports two target source roots:

```text
apps/<app_id>/
workspaces/<workspace_id>/apps/<app_id>/
```

Workspace-local creation is the default developer workflow. Generated workspace-local apps must declare:

```json
{
  "distribution": {
    "mode": "workspace_local",
    "source_access": "editable"
  }
}
```

Installation-level app creation is reserved for explicit platform or store-app work. It must not be the default for workspace agents.

## Contract-First Flow

Every generated app starts with a valid `app_contract.json`.

The SDK validation path calls the same parser used by the app-hosting domain. The SDK must not maintain a second contract schema or duplicate validation rules.

The canonical flow is:

1. create app source under the correct root
2. validate `app_contract.json`
3. register workspace-local app project when applicable
4. install workspace-local app when requested
5. inspect app status and mounted surfaces

## Workspace SDK API And CLI Surface

The official SDK surface for agents is the workspace-scoped hosted API:

```text
POST /api/app-sdk
```

The API accepts a normal authenticated browser session or a workspace runtime bearer token issued by the core when launching an agent runtime. Runtime tokens are scoped to one `workspace_id`; SDK actions never infer or fall back to `default` when a non-default workspace token is used.

The workspace-local `maverick` command installed into `workspaces/<workspace_id>/runtime/sessions/<runtime_session_id>/bin/` is a thin HTTP client for this API. It does not import `core`, read installation-level source, or require repo-global paths inside the sandbox.

The command shape is:

```text
maverick app create
maverick app validate
maverick app register-local
maverick app install-local
maverick app status
maverick app package
maverick sdk templates
maverick sdk docs
```

Registration and installation remain governed by workspace policy. `create`, `validate`, `status`, `package`, and `templates` require `allow_custom_apps`; `register-local` and `install-local` also require `allow_app_installation`.

`maverick sdk docs` returns the SDK documentation content through the hosted SDK API. Workspace runtimes must use this command instead of reading SDK documentation files from disk.

The repository also provides an operator/development wrapper:

```text
scripts/maverick
```

Packaging metadata may expose this as the `maverick` console script.

## Templates

The first SDK templates are:

- `minimal`: contract, README, and contract test only
- `frontend-backend`: mounted frontend and JSON stdin/stdout backend
- `agent-tool`: CLI, MCP, and bundled skill template
- `data-app`: frontend, backend, CLI, MCP, lifecycle hooks, and JSON state
- `widget`: mounted frontend, backend, and a base-shell widget declaration
- `react-vite`: mounted frontend app with React/Vite source, committed `frontend/dist` smoke output, and `lifecycle.rebuild` support through the official core frontend build operation
- `entity-sqlite`: CRM-inspired SQLite entity app with backend, frontend, CLI, MCP, skill, lifecycle hooks, reference metadata, and generated entrypoint tests

Templates are generated source, not runtime magic. A generated app should be understandable and editable without the SDK.

The `entity-sqlite` template is the recommended starting point for CRM-like apps. It supports a caller-provided entity list and generates one SQLite table per entity, reference metadata, list/create/get/search actions, and CLI/MCP surfaces.

## Runtime Helpers

The SDK exposes small Python helpers under `core.app_sdk` for generated apps:

- `runtime.py` reads JSON stdin payloads and emits JSON responses
- `storage.py` resolves app data paths under the app-owned data root and rejects traversal

App entrypoints run in app source roots. The generic entrypoint and lifecycle runners prepend the repository root to `PYTHONPATH` so generated apps can import official SDK helpers without copying them into every app.

## Developer Kit App

`apps/developer-kit` is a sealed workspace-visible app that exposes a frontend for SDK workflows. It is intentionally not admin-only because the official SDK must be usable by every workspace developer. Permission checks for creating, registering, installing, and packaging apps belong to the authenticated SDK API and generic app-hosting policy layer, not to SDK discoverability.

The Developer Kit UI calls `/api/app-sdk` to:

- list templates
- create workspace-local app source through the SDK
- validate generated source
- register workspace-local app projects
- install workspace-local app projects
- inspect SDK status
- package generated source

Developer Kit must not write app-hosting control-plane records directly and must not carry a parallel app-owned backend for SDK control-plane mutations.

## Packaging Artifacts

`maverick app package <app_id>` creates a tarball and a sidecar manifest under `workspaces/<workspace_id>/storage/generated/`:

```text
<app_id>-<version>.tar.gz
<app_id>-<version>.tar.gz.manifest.json
```

The manifest includes app identity, contract version, distribution mode, source access, file list, checksum, and packager provenance. The package excludes local junk such as `node_modules`, `__pycache__`, runtime state, logs, temp files, and local databases.

## Testing

SDK work must include focused tests for:

- generated contracts parsing through `parse_app_contract_file`
- path traversal rejection
- workspace-local registration
- workspace-local installation
- installed app data root creation
- generated CLI/MCP/backend/hook entrypoints when declared
- SDK CLI command registration
- package exclusion rules
- package manifest and checksum tests
- workspace runtime CLI wrapper tests
- authenticated workspace SDK API tests
- Developer Kit contract/frontend smoke tests

## Current Implementation

The initial implementation lives under:

```text
core/app_sdk/
core/api/app_sdk_api.py
core/runtime/workspace_api_token.py
core/cli/app_sdk_commands.py
scripts/maverick
apps/developer-kit/
tests/test_app_sdk.py
docs/app-sdk/getting_started.md
```

It includes contract-first app generation, React/Vite and SQLite entity templates, packaging metadata, a workspace runtime CLI wrapper, a workspace-visible Developer Kit app, and an authenticated SDK API while preserving the core/app boundary.
