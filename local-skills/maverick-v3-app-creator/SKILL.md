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
2. `/home/ubuntu/maverick-v3/local-skills/maverick3-code-skill/SKILL.md`
3. `/home/ubuntu/maverick-v3/IMPLEMENTATION_TASKLIST.md`
4. `/home/ubuntu/maverick-v3/docs/architecture/core_architecture.md`
5. `/home/ubuntu/maverick-v3/docs/architecture/app_contract_architecture.md`
6. `/home/ubuntu/maverick-v3/docs/architecture/workspace_root_architecture.md`
7. Current examples under `/home/ubuntu/maverick-v3/apps`, especially apps with similar declared surfaces.
8. Relevant core mounting code for the chosen surfaces, usually `core/apps`, `core/api/app_mounts.py`, `core/api/app_registry.py`, `core/cli`, `core/mcp`, `core/skills`, `core/runtime`, `core/secrets`, and `core/observability`.

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

Until a stable core CLI exists, use the core service functions directly in tests or a focused repository script only when necessary.

Preferred future CLI shape:

```bash
maverick apps register-local --workspace <workspace_id> --path workspaces/<workspace_id>/apps/<app_id>
maverick apps install-local --workspace <workspace_id> --app <app_id>
```

Do not implement app-specific registration shortcuts.

Registration and installation must remain generic core app-hosting operations.

## Planning Workflow

For non-trivial apps, produce a short plan before coding.

1. Define the app's product scope in one paragraph.
2. Decide declared surfaces and explicitly exclude surfaces that are not needed.
3. Design `app_contract.json` before implementation.
4. Define the workspace data layout and schema version.
5. Identify generic core gaps separately from app work.
6. Choose the smallest useful app structure.
7. Define tests and smoke checks before or alongside implementation.
8. Include docs and `IMPLEMENTATION_TASKLIST.md` updates in the same change.

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

Do not declare MCP, CLI, skills, hooks, widgets, export/import, or frontend if the app does not actually implement them.

## Backend Pattern

App backend entrypoints are JSON stdin/stdout scripts executed by the core.

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
- workspace-local app is registered with `register_workspace_local_app_project_from_contract`
- `/api/app-store/installations` reports registered workspace-local app in `local_apps`
- workspace-local app can be installed with `install_workspace_local_app` when requested
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

If a command cannot run, state why in the final summary.

## Anti-Patterns

- creating app-specific shortcuts in core
- adding an app to a hardcoded core list when contract-driven discovery is available
- assuming a workspace-local app is visible because its folder exists
- forgetting to register a `workspace_local` app after creating its `app_contract.json`
- installing a workspace-local app into a workspace other than its owning workspace
- declaring surfaces that are not implemented
- storing app business data in core stores
- writing app data outside `data/<app_id>`
- committing `node_modules`, caches, temporary files, or local secrets
- copying an existing app without re-evaluating product scope
- leaving placeholder UI where a real workflow was requested
- marking an app complete when only the contract or scaffold exists

## Definition Of Done

A new Maverick v3 app is done when:

- `app_contract.json` is valid
- workspace-local apps are registered in app-hosting control-plane records
- apps that should be usable immediately are installed/enabled in their owning workspace
- App Store visibility is verified through `local_apps` for workspace-local apps
- every declared surface exists and works
- app-owned data is under `data/<app_id>`
- install and health behavior are idempotent
- frontend builds if declared
- backend/MCP/CLI use shared service logic where applicable
- tests cover stable contract and storage behavior
- docs and `IMPLEMENTATION_TASKLIST.md` are updated
- final review removes stale files, dead code, and generated junk
- a focused commit is created and pushed when implementation changes are made
