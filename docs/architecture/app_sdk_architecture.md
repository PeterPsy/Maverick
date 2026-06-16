# App SDK Architecture

Date: 2026-04-21

## Purpose

Define the official Maverick App SDK as a developer surface for creating Maverick apps without weakening the platform boundary.

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
- create compatibility shims for obsolete implementations

## Source Roots

The SDK supports two target source roots:

```text
apps/<app_id>/
workspaces/<workspace_id>/apps/<app_id>/
```

Workspace-local creation is the default developer workflow. Generated workspace-local apps must declare workspace-local distribution:

```json
{
  "distribution": {
    "mode": "workspace_local",
    "source_access": "editable"
  }
}
```

Templates with a user-openable frontend also declare `presentation.frontend_role: "workspace"`.
Templates without a frontend declare `presentation.frontend_role: "none"`.
Templates that ship frontend assets only for a platform or plugin workflow declare `presentation.frontend_role: "supporting"` and must not be treated as shell-launchable apps.

Installation-level app creation is reserved for explicit platform or store-app work. It must not be the default for workspace agents.

## Contract-First Flow

Every generated app starts with a valid `app_contract.json`.

The SDK validation path calls the same parser used by the app-hosting domain. The SDK must not maintain a second contract schema or duplicate parser rules.

After parsing, SDK validation also enforces source-level surface completeness for the official app contract. These checks make sure declared capabilities are backed by the corresponding source tree surfaces before an app can be registered, installed, or packaged through the SDK:

- MCP tools require an MCP entrypoint, and an MCP entrypoint must declare the tools it exposes.
- CLI commands require a CLI entrypoint, and a CLI entrypoint must declare the commands it exposes.
- Declared views require a mounted frontend entrypoint.
- Declared bundled skills must match direct `SKILL.md` templates under `entrypoints.skills_root`.
- Apps with MCP support must expose the common `<app_id>_reference_manifest` tool, using underscores in the tool prefix.
- Apps with `reference_entities` must expose reference manifest, search, resolve, and summarize tools through MCP, plus an equivalent CLI surface.
- Apps with `reference_entities` must declare view surfaces for those entities.
- Apps with `view_surfaces` must declare the shared `view-state` data event, the standard view-state actions, and matching MCP tools when MCP is exposed.
- Declared data events require at least one executable backend, CLI, or MCP surface capable of emitting or acting on those events.
- Declared `provides` surfaces must be backed by matching app entrypoints or capability declarations.
- Apps with a declared frontend entrypoint must have a real `package.json` build script for the declared frontend artifact root. No-op scripts that only check `frontend/dist` existence or call `process.exit(0)` do not satisfy the frontend build contract.
- Generated contracts include explicit top-level `provides` and `requires` arrays, even when they are empty, so cross-app capability declarations stay contract-first rather than inferred from app ids.

The canonical flow is:

1. create app source under the correct root
2. validate `app_contract.json`
3. register workspace-local app project when applicable
4. install workspace-local app when requested
5. inspect app status and mounted surfaces

Generated source is only the starting point. Before an app is considered complete in this repository, it must keep the contract, README, bundled skill declarations, official surface behavior, and automated smoke coverage aligned.

## Workspace SDK API And CLI Surface

The official SDK mutation surface for agents is the canonical core CLI, invoked with the runtime workspace context:

```text
maverick core cli run core.app-sdk.create --app-id <app_id> --template-id <template_id> --json
maverick core cli run core.app-sdk.validate --app-id <app_id> --json
maverick core cli run core.app-sdk.register-local --app-id <app_id> --json
maverick core cli run core.app-sdk.install-local --app-id <app_id> --json
maverick core cli run core.app-sdk.status --app-id <app_id> --json
maverick core cli run core.app-sdk.package --app-id <app_id> --json
```

The runtime CLI API accepts a workspace runtime bearer token issued by the core when launching an agent runtime. Runtime tokens are scoped to one active runtime session and one `workspace_id`; SDK CLI actions never infer or fall back to `default` when a non-default workspace token is used.

The workspace-local `maverick` command installed into `workspaces/<workspace_id>/runtime/sessions/<runtime_session_id>/bin/` is a thin HTTP client for `/api/runtime/cli`. It does not import `core`, read installation-level source, or require repo-global paths inside the sandbox. Runtime CLI requests may include `output_profile` in the JSON body. The default API profile is `full`; the runtime-local shim requests `provider_compact` by default so large textual response fields are redacted and compacted before they enter provider context, while preserving explicit document-body fields for developer-context and Storage read surfaces from truncation. Agents can set `MAVERICK_RUNTIME_CLI_OUTPUT_PROFILE=full` for exact full JSON output.

The supported command shape is:

```text
maverick core cli run core.app-sdk.create
maverick core cli run core.app-sdk.validate
maverick core cli run core.app-sdk.register-local
maverick core cli run core.app-sdk.install-local
maverick core cli run core.app-sdk.status
maverick core cli run core.app-sdk.package
maverick sdk templates
maverick sdk docs
```

The older app-domain SDK shortcut form is not a supported surface. Registration and installation remain governed by workspace policy and actor authority, but the canonical SDK CLI commands are agent-invokable through the trusted runtime CLI context available to the workspace today. Secret values or other privileged inputs may be accepted as command arguments only when the result stays redaction-safe.

`maverick sdk docs` returns the SDK documentation content through the hosted SDK API. Workspace runtimes must use this command instead of reading SDK documentation files from disk.

The repository also provides an operator/development wrapper:

```text
scripts/maverick
```

Packaging metadata may expose this as the `maverick` console script.

## Templates

The first SDK templates are:

- `minimal`: contract, README, and contract test only
- `frontend-backend`: mounted React/Vite frontend, JSON stdin/stdout backend, and official frontend build support
- `agent-tool`: CLI, MCP, and bundled skill template
- `data-app`: React/Vite frontend, backend, CLI, MCP, lifecycle hooks, JSON state, and official frontend build support
- `widget`: mounted React/Vite frontend, backend, base-shell widget declaration, and official frontend build support
- `react-vite`: mounted frontend app with React/Vite source, committed `frontend/dist` smoke output, and support through the official core frontend build operation
- `entity-sqlite`: record-centric SQLite entity app with backend, frontend, CLI, MCP, skill, lifecycle hooks, reference metadata, and generated entrypoint tests

All first-party templates are expected to generate:

- `README.md` with SDK flow commands
- `tests/test_contract.py` or equivalent automated smoke coverage
- React/Vite source under `frontend/src` for every template that declares a frontend
- honest contract metadata for bundled skills and declared surfaces
- complete reference, CLI, MCP, view-surface, and `view-state` declarations when the template owns referenceable workspace records
- explicit documentation when a template intentionally omits app-owned backend, hooks, or persisted view-state surfaces

Templates are generated source, not runtime magic. A generated app should be understandable and editable without the SDK.

The `entity-sqlite` template is the recommended starting point for record-centric apps. It supports a caller-provided entity list and generates one SQLite table per entity, reference metadata, list/create/get/search actions, and CLI/MCP surfaces.

## Runtime Helpers

The SDK exposes small Python helpers under `core.app_sdk` for generated apps:

- `runtime.py` reads JSON stdin payloads and emits JSON responses
- `storage.py` resolves app data paths under the app-owned data root and rejects traversal

App entrypoints run in app source roots. The generic entrypoint and lifecycle runners prepend the repository root to `PYTHONPATH` so generated apps can import official SDK helpers without copying them into every app.

## Developer Kit App

`apps/developer-kit` is a sealed workspace-visible SDK support app. It may ship frontend assets for SDK workflows, but its contract marks that frontend as `presentation.frontend_role: supporting` because it is a platform/plugin surface rather than a primary workspace app to pin or open from the normal shell app rail. Permission checks for creating, registering, installing, and packaging apps belong to the authenticated SDK API and generic app-hosting policy layer, not to SDK discoverability.

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

`maverick core cli run core.app-sdk.package --app-id <app_id> --json` creates a tarball and a sidecar manifest under `workspaces/<workspace_id>/storage/generated/`:

```text
<app_id>.tar.gz
<app_id>.tar.gz.manifest.json
```

The official agent CLI accepts `app_id` and workspace context, not arbitrary local `app_root` or `output_path` values. The manifest includes app identity, contract version, distribution mode, source access, file list, checksum, and packager provenance using workspace-safe source descriptors instead of absolute host paths. The package excludes local junk such as `node_modules`, `__pycache__`, runtime state, logs, temp files, and local databases.

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
