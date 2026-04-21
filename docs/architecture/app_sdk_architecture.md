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

## CLI Surface

The first official SDK surface is core CLI commands:

```text
core.app-sdk.create
core.app-sdk.validate
core.app-sdk.register-local
core.app-sdk.install-local
core.app-sdk.status
core.app-sdk.package
```

The user-facing path segments are:

```text
maverick app create
maverick app validate
maverick app register-local
maverick app install-local
maverick app status
maverick app package
```

These commands are operator-only because they create and install app capabilities. Workspace agent access should go through authorized hosted APIs or future governance-aware surfaces.

## Templates

The first SDK templates are:

- `minimal`: contract, README, and contract test only
- `frontend-backend`: mounted frontend and JSON stdin/stdout backend
- `agent-tool`: CLI, MCP, and bundled skill template
- `data-app`: frontend, backend, CLI, MCP, lifecycle hooks, and JSON state
- `widget`: mounted frontend, backend, and a base-shell widget declaration

Templates are generated source, not runtime magic. A generated app should be understandable and editable without the SDK.

## Runtime Helpers

The SDK exposes small Python helpers under `core.app_sdk` for generated apps:

- `runtime.py` reads JSON stdin payloads and emits JSON responses
- `storage.py` resolves app data paths under the app-owned data root and rejects traversal

App entrypoints run in app source roots. The generic entrypoint and lifecycle runners prepend the repository root to `PYTHONPATH` so generated apps can import official SDK helpers without copying them into every app.

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

## Current Implementation

The initial implementation lives under:

```text
core/app_sdk/
core/cli/app_sdk_commands.py
tests/test_app_sdk.py
docs/app-sdk/getting_started.md
```

It intentionally starts with a small set of robust templates and command flows. Future SDK work should add packaging, widget templates, richer frontend templates, and a developer UI without changing the core/app boundary.
