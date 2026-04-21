---
name: maverick-v3-app-creator
description: "Use when planning or implementing a brand-new Maverick v3 app in /home/ubuntu/maverick-v3, not when porting from Maverick v2. Enforces clean-slate app design, app-agnostic core boundaries, contract-first implementation, workspace-owned data under data/<app_id>, declared frontend/backend/MCP/CLI/skills/hooks surfaces, tests, docs, tasklist updates, final review, and checkpoint commits."
---

# Maverick v3 App Creator

Use this skill when creating a new Maverick v3 app from scratch.

Do not use this skill for ports from Maverick v2 or any legacy app. For porting work, use `maverick-v3-app-porting`.

## Mandatory Pairing

Also use `maverick3-code-skill` for any task that touches `/home/ubuntu/maverick-v3`.

## Required Read Order

Before proposing a plan or changing files, read:

1. `/home/ubuntu/maverick-v3/AGENTS.md`
2. `/home/ubuntu/maverick-v3/apps/skills/skills/maverick3-code-skill/SKILL.md`
3. `/home/ubuntu/maverick-v3/IMPLEMENTATION_TASKLIST.md`
4. `/home/ubuntu/maverick-v3/docs/architecture/core_architecture.md`
5. `/home/ubuntu/maverick-v3/docs/architecture/app_contract_architecture.md`
6. `/home/ubuntu/maverick-v3/docs/architecture/workspace_root_architecture.md`
7. `/home/ubuntu/maverick-v3/docs/architecture/app_sdk_architecture.md`
8. `/home/ubuntu/maverick-v3/docs/app-sdk/getting_started.md`
9. Current examples under `/home/ubuntu/maverick-v3/apps`, especially apps with similar declared surfaces.
10. Relevant core mounting code for the chosen surfaces, usually `core/apps`, `core/app_sdk`, `core/api/app_mounts.py`, `core/api/app_registry.py`, `core/cli`, `core/mcp`, `core/skills`, `core/runtime`, `core/secrets`, and `core/observability`.

## Required Inputs

Clarify or infer these before implementation. If any requirement is still product-ambiguous, ask before coding.

- app id, using canonical lowercase kebab-case
- app purpose and user workflow
- app kind: `frontend-only`, `backend-only`, `frontend+backend`, `mcp/cli-only`, `shell/host app`, or mixed
- distribution mode: `sealed`, `source_available`, or `workspace_local`
- source access: `none`, `read_only`, `forkable`, or `editable`
- declared surfaces: frontend, backend, MCP, CLI, skills, lifecycle hooks, widgets, secrets, storage, export/import
- workspace data needs and schema version
- runtime/provider needs, if any
- permissions or execution policy expectations
- expected verification: unit tests, frontend build, smoke tests, CLI/MCP invocation, runtime checks
- whether the official App SDK template should be used: `minimal`, `frontend-backend`, `agent-tool`, `data-app`, or `widget`

## Core Boundary Rules

- The app owns its domain data, UI, app-specific backend actions, MCP tool behavior, CLI commands, lifecycle hooks, and skills.
- The core owns app registration, app mounting, workspace binding, identity, governance, runtime, provider, secrets, recovery, and observability.
- App-owned workspace data must live under `workspaces/<workspace_id>/data/<app_id>/`.
- App source for server-installed apps lives under installation-level `/apps/<app_id>/`.
- Workspace-local app projects live under `workspaces/<workspace_id>/apps/<app_id>/`.
- The core must not import app source or contain app-specific conditionals.
- Do not add branches like `if app_id == "<new-app>"` in core.
- If the app needs a missing generic capability, add a generic core surface or document the gap in `IMPLEMENTATION_TASKLIST.md`.
- If behavior is app-specific, implement it inside the app.

## Official App SDK First

For brand-new workspace-local apps, prefer the official Maverick App SDK unless the requested app requires a surface or structure the SDK does not yet support.

Use the SDK to create the initial source tree, validate the contract, register/install workspace-local apps, inspect status, and package valid app source:

```text
core.app-sdk.create
core.app-sdk.validate
core.app-sdk.register-local
core.app-sdk.install-local
core.app-sdk.status
core.app-sdk.package
```

Initial SDK templates:

- `minimal`
- `frontend-backend`
- `agent-tool`
- `data-app`
- `widget`

Recommended flow for an immediately usable workspace-local app:

1. Generate the app with `core.app-sdk.create`.
2. Replace scaffold behavior with real product behavior.
3. Keep `app_contract.json` aligned with the real implemented surfaces.
4. Validate with `core.app-sdk.validate`.
5. Register with `core.app-sdk.register-local`.
6. Install with `core.app-sdk.install-local`.
7. Verify with `core.app-sdk.status`, `/api/status`, `/api/apps`, mounted frontend/backend checks, and CLI/MCP listings when declared.
8. Package with `core.app-sdk.package` when a generated artifact is useful.

Do not leave SDK scaffold behavior in place when the user asked for a real app. The SDK gives the correct v3 shape; the app still needs real domain behavior, UI, storage, tests, and smoke verification.

## Installation Is Required

Creating an app source tree is not enough for Maverick to use the app.

Every new app must finish with the correct generic app-hosting flow for its distribution mode:

- built-in or installation-level apps under `/home/ubuntu/maverick-v3/apps/<app_id>` must be registered from `app_contract.json`, installed/enabled into the target workspace, and verified through the same generic bootstrap/app-hosting state that the App Store reports
- workspace-local apps under `workspaces/<workspace_id>/apps/<app_id>` must be registered as workspace-local projects, installed/enabled into their owning workspace, and verified through App Store local-app and installation surfaces
- source-available forks must be installed from the correct source record or workspace-local fork record; do not rely on copied files alone

Do not say an app is complete just because files, tests, or `app_contract.json` exist. The final summary must explicitly state the app's source state, registration state, installation/binding state, and whether the app is enabled for the intended workspace.

Use only generic platform operations for this:

- built-in/server app registration and install through contract-driven app-hosting bootstrap or `register_app_source_from_contract(...)` plus `install_store_app(...)`
- workspace-local registration and install through App Store APIs or `register_workspace_local_app_project_from_contract(...)` plus `install_workspace_local_app(...)`
- verification through `/api/app-store/installations`, `/api/apps`, app bindings, CLI/MCP listings, mounted frontend checks, or equivalent generic core service calls

Do not add app-specific registration scripts, hardcoded core lists, or branches such as `if app_id == "<new-app>"`.

## Workspace-Local App Registration

Creating files under `workspaces/<workspace_id>/apps/<app_id>/` does not make the app visible to Maverick.

For every `distribution.mode = "workspace_local"` app, the agent must complete the app-hosting registration flow after writing the files.

Required flow:

1. Create the app source tree under `workspaces/<workspace_id>/apps/<app_id>/`.
2. Write a valid `app_contract.json` with:
   - `app_id` matching the folder name
   - `distribution.mode = "workspace_local"`
   - `distribution.source_access = "editable"`
   - every declared entrypoint pointing to a real file or directory
3. Validate the contract with the core contract parser.
4. Register the project in the core app-hosting control plane with `register_workspace_local_app_project_from_contract(...)` or the official core CLI/API equivalent when available.
5. If the user wants to use the app immediately, install it into the owning workspace with `install_workspace_local_app(...)` or the official core CLI/API equivalent when available.
6. Verify `/api/app-store/installations` includes the app in `local_apps`.
7. If installed, verify the workspace app binding appears in the installation list and the app is mountable/enabled according to the core app-hosting state.

Do not say an app has been created for Maverick just because the directory exists.

A workspace-local app has three distinct states:

- source exists on disk under `workspaces/<workspace_id>/apps/<app_id>/`
- project is registered in app-hosting control-plane records
- app is installed/enabled for the workspace

Keep these states explicit in the implementation summary.

Use the official SDK CLI registry commands when available:

```text
core.app-sdk.validate
core.app-sdk.register-local
core.app-sdk.install-local
core.app-sdk.status
```

Use the core service functions directly in tests or focused repository scripts only when the hosted CLI/API surface is not available for the current environment.

Do not implement app-specific registration shortcuts.

Registration and installation must remain generic core app-hosting operations.

When running inside a workspace-only sandbox, use the hosted core API rather than reading or writing control-plane files directly:

```text
POST /api/app-store/register-local
POST /api/app-store/install-local
GET /api/app-store/installations
GET /api/apps
```

The local project root is always resolved by the core from `workspace_id` and `app_id` as:

```text
workspaces/<workspace_id>/apps/<app_id>
```

Do not invent endpoints, desktop launchers, file links, or standalone static servers as substitutes for a Maverick local app. If `GET /api/app-store/installations` reports a local app with `status: "invalid"`, read `validation_error`, fix `app_contract.json`, then call `register-local` again.

Minimum valid frontend-only workspace-local contract:

```json
{
  "app_id": "example-local",
  "contract_version": "1.0",
  "name": "Example Local",
  "version": "0.1.0",
  "description": "Workspace-local app.",
  "publisher": "workspace",
  "minimum_core_version": "0.1.0",
  "distribution": {
    "mode": "workspace_local",
    "source_access": "editable"
  },
  "capabilities": {
    "mcp_tools": [],
    "cli_commands": [],
    "skills": [],
    "views": ["main"]
  },
  "entrypoints": {
    "frontend": "frontend/dist",
    "hooks": {}
  },
  "storage": {
    "storage_kind": "json",
    "data_schema_version": "1",
    "primary_paths": ["data/example-local/state.json"],
    "indices": null,
    "supports_export": false,
    "supports_import": false,
    "supports_migrations": false
  },
  "compatibility": {
    "workspace_modes": ["sandbox", "full-access"]
  },
  "hook_timeouts": {
    "install_seconds": 60,
    "upgrade_seconds": 120,
    "migrate_seconds": 300,
    "export_seconds": 120,
    "import_seconds": 120,
    "validate_after_import_seconds": 60,
    "repair_after_import_seconds": 180,
    "health_check_seconds": 30
  },
  "lifecycle": {
    "install": false,
    "upgrade": false,
    "uninstall": false,
    "migrate": false,
    "export": false,
    "import": false,
    "validate_after_import": false,
    "repair_after_import": false,
    "rebuild": false,
    "health_check": false
  },
  "health_contract": {
    "mode": "none",
    "degraded_on_failure": true
  },
  "failure_semantics": {
    "install_failure": "block_activation",
    "migrate_failure": "preserve_data_mark_unhealthy",
    "import_failure": "preserve_payload_mark_failed"
  },
  "rollback_support": {
    "bundle": false,
    "data": false,
    "repair_only": false
  }
}
```

Replace every `example-local` occurrence with the real `app_id`, keep it lowercase kebab-case, and make every declared entrypoint resolve to a real path under the app root.

## Planning Workflow

For non-trivial apps, produce a short plan before coding.

1. Define the app's product scope in one paragraph.
2. Decide declared surfaces and explicitly exclude surfaces that are not needed.
3. Select the closest SDK template or explain why the SDK is not appropriate.
4. Design `app_contract.json` before implementation.
5. Define the workspace data layout and schema version.
6. Identify generic core gaps separately from app work.
7. Choose the smallest useful app structure.
8. Define tests and smoke checks before or alongside implementation.
9. Define the generic registration/install/enable verification for the app's distribution mode.
10. Include docs and `IMPLEMENTATION_TASKLIST.md` updates in the same change.

## Target App Structure

Create only directories for real surfaces.

Mixed full app:

```text
apps/<app_id>/
  app_contract.json
  backend/
    app_backend.py
    models.py
    service.py
    store.py
    errors.py
  cli/
    app_cli.py
  frontend/
    index.html
    src/
      main.tsx
      styles/
        main.css
  hooks/
    install.py
    migrate.py
    health_check.py
  mcp/
    server.py
  skills/
    <skill-id>/
      SKILL.md
  package.json
  package-lock.json
  tsconfig.json
  vite.config.ts
```

For smaller apps, omit unused surfaces. Do not create empty ceremony.

When using an SDK-generated workspace-local app, the generated starter tree is acceptable as the initial structure. Remove unused generated surfaces if the final app does not actually implement them.

## Contract-First Rules

`app_contract.json` is the source of truth for executable app metadata.

Before coding an entrypoint:

- declare the surface in `capabilities`
- declare the path in `entrypoints`
- ensure the path exists before contract parser tests run
- ensure production frontend contracts point to `frontend/dist`
- include build output for built-in mounted frontend apps when the contract points to `frontend/dist`
- keep `storage.primary_paths` aligned with the real workspace data layout
- set lifecycle booleans honestly
- after SDK generation, re-run validation whenever `app_contract.json` or declared entrypoints change

Do not declare MCP, CLI, skills, hooks, widgets, export/import, or frontend if the app does not actually implement them.

## Backend Pattern

App backend entrypoints are JSON stdin/stdout scripts executed by the core.

For SDK-generated apps, prefer `core.app_sdk.runtime` for JSON payload parsing and response emission, and `core.app_sdk.storage` for safe app data paths.

Use this shape:

- read JSON payload from stdin
- read app request body from `payload["body"]`
- read workspace data root from `payload["data_root"]`
- dispatch by `body["action"]`
- return `{"status_code": <int>, "json": <object>}`
- keep persistence in `store.py`
- keep behavior in `service.py`
- keep entrypoint code thin

Do not copy FastAPI route patterns into v3 apps unless the v3 app host explicitly supports that surface.

## Frontend Pattern

For React/Vite app frontends:

- use `frontend/src/main.tsx`
- use `frontend/dist` as the contract mount target
- call app backend through `/api/apps/<app_id>/backend`
- call generic core APIs only for platform-owned behavior
- keep UI controls feature-complete for the app's real workflow
- avoid landing pages when the app is an operator tool
- run `npm run build` and commit `frontend/dist` for built-in mounted apps
- do not commit `node_modules`

Keep files small. If `main.tsx` grows beyond roughly 250 to 300 lines, split components and hooks.

## MCP And CLI Pattern

MCP and CLI entrypoints should reuse the same service layer as the backend.

MCP entrypoint:

- read `payload["tool_name"]`
- read `payload["arguments"]`
- return a JSON object
- avoid duplicating store logic

CLI entrypoint:

- read `payload["command_id"]`
- read `payload["arguments"]`
- return a JSON object
- keep it useful for smoke checks, export/import, validation, or local inspection

## Lifecycle Hooks

Implement lifecycle hooks when the app has data.

Minimum useful hooks:

- `install.py`: create app data root and seed initial data
- `migrate.py`: idempotently upgrade data schema
- `health_check.py`: verify required files or storage are readable

Hooks must be idempotent. Running install or migrate twice must not duplicate records or corrupt data.

## Skills

If the app exposes skills:

- place them under `apps/<app_id>/skills/<skill-id>/SKILL.md`
- keep the skill focused on using that app's official surfaces
- do not treat skills as an enforcement or execution boundary
- prefer MCP/CLI/backend surfaces for real operations

## Storage

For first implementations, prefer simple JSON or markdown where it is enough.

For SDK-generated apps, use `core.app_sdk.storage.safe_app_data_path`, `read_json_state`, `write_json_state`, or `ensure_json_state` instead of ad hoc path concatenation.

Recommended layout:

```text
workspaces/<workspace_id>/data/<app_id>/
  state.json
```

Use more files when the domain benefits from reviewable separation, such as markdown content or append-only logs.

Rules:

- validate ids and relative paths
- reject path traversal
- keep app data out of core stores
- keep database-specific details inside store adapters if the app later needs one
- update `storage.data_schema_version` when changing persistent schema

## Testing Workflow

Default to focused tests for contracts, path rules, store behavior, and entrypoints.

Useful test categories:

- contract parses under `parse_app_contract_file`
- SDK-generated source validates with `core.app-sdk.validate` when the SDK is used
- built-in or store app registers from its contract and creates an enabled workspace binding when intended for immediate use
- workspace-local app is registered with `register_workspace_local_app_project_from_contract`
- workspace-local app registers with `core.app-sdk.register-local` when using the SDK flow
- `/api/app-store/installations` reports registered workspace-local app in `local_apps`
- workspace-local app can be installed with `install_workspace_local_app` when requested
- workspace-local app installs with `core.app-sdk.install-local` when using the SDK flow
- `/api/app-store/installations` and/or `/api/apps` reports the app as installed/enabled for the target workspace
- install hook creates expected data under `data/<app_id>`
- seed is idempotent
- backend actions return expected status and payloads
- invalid ids or paths are rejected
- MCP and CLI surfaces are visible when the app is enabled
- MCP and CLI entrypoints call the same service behavior as backend
- frontend build output exists when declared
- mounted frontend is served by `PlatformHost`
- generic core gaps are covered by core tests, not app-specific tests

## Documentation And Tasklist

Update docs in the same change when any of these move:

- app contract pattern
- runtime behavior
- app-hosting behavior
- workspace data layout
- package boundaries
- lifecycle behavior

Use:

- `docs/architecture/` for architecture changes
- `docs/porting/` only for porting plans, not new app creation plans
- `IMPLEMENTATION_TASKLIST.md` for progress and open gaps

Mark tasklist items complete only when implementation and verification are real.

## Verification Checklist

Run the smallest relevant set, then broaden if core surfaces changed.

Common checks:

```bash
python3 -m unittest tests/test_<app_id>_app.py
python3 scripts/check_unused_imports.py
npm --prefix apps/<app_id> run build
python3 -m unittest discover -s tests -p 'test_*.py'
```

SDK-flow checks:

```text
core.app-sdk.validate
core.app-sdk.status
core.app-sdk.package
```

If a command cannot run, state why in the final summary.

## Anti-Patterns

- creating app-specific shortcuts in core
- adding an app to a hardcoded core list when contract-driven discovery is available
- assuming a built-in app is usable because its folder exists under `/apps`
- assuming a workspace-local app is visible because its folder exists
- forgetting to run or verify the generic registration/install/enable flow after creating an app
- forgetting to register a `workspace_local` app after creating its `app_contract.json`
- installing a workspace-local app into a workspace other than its owning workspace
- declaring surfaces that are not implemented
- storing app business data in core stores
- writing app data outside `data/<app_id>`
- committing `node_modules`, caches, temporary files, or local secrets
- copying an existing app without re-evaluating product scope
- leaving placeholder UI where a real workflow was requested
- leaving SDK starter behavior in place after the user requested domain-specific app behavior
- marking an app complete when only the contract or scaffold exists

## Definition Of Done

A new Maverick v3 app is done when:

- `app_contract.json` is valid
- if the SDK was used, the final app source validates after all domain edits
- installation-level apps are registered from their contract and installed/enabled in the intended workspace when they should be immediately usable
- workspace-local apps are registered in app-hosting control-plane records
- apps that should be usable immediately are installed/enabled in their target workspace
- App Store visibility is verified through `local_apps` for workspace-local apps
- App Store installation state, `/api/apps`, app bindings, or equivalent generic service calls verify the installed/enabled state
- every declared surface exists and works
- app-owned data is under `data/<app_id>`
- install and health behavior are idempotent
- frontend builds if declared
- backend/MCP/CLI use shared service logic where applicable
- tests cover stable contract and storage behavior
- docs and `IMPLEMENTATION_TASKLIST.md` are updated
- final review removes stale files, dead code, and generated junk
- SDK package output is produced when the user asked for a distributable artifact
- a focused commit is created and pushed when implementation changes are made
