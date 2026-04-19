# App Contract Architecture

Date: 2026-04-17

## Purpose

Define the standard contract that every Maverick app must follow.

This contract does not impose the internal data model of an app.

It defines the minimum platform-facing structure needed so that apps remain:

- installable
- governable
- workspace-scoped
- isolated from each other
- compatible with a headless core

## Core Principle

Every app must have:

- a stable identity
- a workspace-owned data root
- a declared capability surface
- a declared lifecycle
- a clear boundary toward the core and toward other apps

The platform must not force all apps into the same internal schema.

The platform must require every app to describe how it behaves.

## Contract Versus Installation State

The app contract is not the same thing as app installation state.

Maverick v3 should distinguish clearly between:

- app source or project material
- app distribution artifact
- app contract metadata
- app installation state in the core
- app enablement state inside one workspace

Examples:

- a server-installed app store artifact may carry valid contract metadata before it is enabled in any workspace
- a workspace-local app project may exist under `workspaces/<workspace_id>/apps/` before it becomes an active capability
- an app may be installed but not enabled in a given workspace

The contract describes what the app is and how it behaves.

The core installation system decides where that app is known, installed, enabled, disabled, upgraded, uninstalled, or reattached.

## App Distribution Sources

Maverick v3 supports two canonical app source locations:

- installation-level app artifacts under `/apps`
- workspace-local app projects under `workspaces/<workspace_id>/apps`

The installation-level `/apps` directory is the server's app store, trusted bundle cache, and platform-installed app area.

It may contain:

- built-in platform apps such as `base-shell` and `chat`
- closed commercial apps distributed as sealed artifacts
- open-source or source-available apps distributed through the server app store
- versioned app bundles validated by the core

The workspace-level `workspaces/<workspace_id>/apps` directory is not the app store.

It contains:

- apps created directly inside that workspace
- app projects under development for that workspace
- workspace-local forks of store-installed apps
- agent-modified app source material scoped to that workspace

Installing an app from the server app store should create a workspace app binding.

It should not automatically copy the app's full source tree into the workspace.

Copying app source into `workspaces/<workspace_id>/apps/<app_id>/` should happen only when:

- the app is declared `source_available` with `source_access: forkable`
- the user or an authorized agent explicitly creates a workspace-local fork
- the app was born as a workspace-local project

Workspace app bindings and workspace-local projects are different concepts.

The binding says the workspace can use an app capability.

The workspace-local project says the workspace owns editable app source material.

## Distribution Mutability

An app contract should declare its distribution and mutability expectations.

The recommended distribution modes are:

- `sealed`
- `source_available`
- `workspace_local`

`sealed` apps are installed as non-editable artifacts.

They may expose frontend, backend, MCP, CLI, and skills surfaces, but their app source is not workspace-editable.

This is the correct mode for commercial closed-source apps, signed vendor bundles, and apps distributed only as runtime artifacts.

`source_available` apps are distributed by the server app store with source material available for inspection or forking.

They can still run from the installation-level artifact while remaining centrally governed.

If a workspace needs to customize the app, the core should create a workspace-local fork under `workspaces/<workspace_id>/apps/<app_id>/`.

`workspace_local` apps originate inside a workspace and are editable workspace material.

They may later be promoted into an installation-level distribution channel, but that promotion is an explicit packaging step, not an implicit side effect of local development.

The app contract should make source access explicit.

Source mutability is app-level distribution metadata, not actor-specific metadata.

The contract should not declare separate actor-scoped mutability fields.

If a source is editable, it is editable because its distribution mode and source access permit workspace-local editing under platform policy.

If a source is not editable, neither users nor agents should bypass that through a contract field.

For example:

```json
"distribution": {
  "mode": "source_available",
  "source_access": "forkable"
}
```

For a sealed commercial app:

```json
"distribution": {
  "mode": "sealed",
  "source_access": "none"
}
```

The core should enforce this at install, fork, upgrade, and workspace execution boundaries.

Upgrade and rebase are different operations.

Normal upgrade should preserve a workspace-local fork and upgrade only against the fork's own source unless the operator explicitly requests a rebase to a store source.

That rebase must still target the same `app_id`.

The core must reject any upgrade or rebase that attempts to move a workspace binding for one app onto a source artifact for a different app.

## Canonical Contract File

The platform should treat the app contract file as the source of truth for executable app metadata.

The recommended canonical file is:

```text
<app_root>/app_contract.json
```

Examples:

```text
/apps/checklists/app_contract.json
/apps/vendor-reporting/app_contract.json
/workspaces/acme/apps/notes/app_contract.json
```

The core may persist a normalized snapshot of this contract in control-plane records for listing, auditing, or operator inspection.

That snapshot is not the authoritative source for executable contract behavior.

Install, reinstall, upgrade, validate, repair, export, import, and health decisions should resolve from the contract file in the app source root so the platform does not drift away from the app artifact it is actually operating.

## Required App Identity

Every app must declare at least:

- `app_id`
- `name`
- `version`
- `description`
- `publisher`
- `capabilities`

This identity is required for:

- install flows
- update flows
- UI listing
- audit
- compatibility checks
- workspace governance

The canonical public format for `app_id` is lowercase kebab-case.

Examples:

- `restaurant-manager`
- `table-ops`
- `memory`

Do not use underscores or mixed-case forms in the public contract file.

## Workspace Data Ownership

Every app installed in a workspace owns its data under:

```text
/workspaces/<workspace_id>/data/<app_id>/
```

This path is the owned data namespace for the app inside that workspace.

The core should expose a canonical path helper for this namespace so apps and platform code resolve the same app-owned data root deterministically.

The app may choose its own internal storage shape within that root.

Examples:

- SQLite database
- DuckDB database
- JSON document layout
- JSONL append-only logs
- directory-per-record layout
- mixed storage models

## Storage Declaration

An app should declare its storage model in a minimal explicit way.

The declaration should include at least:

- `storage_kind`
- primary storage paths or directories
- index storage mode if indices are used
- whether migrations are supported
- whether export/import is supported

Example values for `storage_kind`:

- `sqlite`
- `duckdb`
- `json`
- `jsonl`
- `mixed`

This declaration exists for transparency and tooling support, not to constrain the app's internal schema.

If the app uses indices, it should also declare whether they are:

- `embedded`
- `file_based`

## Recommended Storage Choices

The platform should recommend:

- `SQLite` as the default embedded database for most stateful apps
- `DuckDB` for analytics-heavy local apps
- `JSON` or `JSONL` for simple config, manifest, snapshot, or log-oriented data

The app developer chooses the internal structure.

The platform only standardizes where the app owns that structure.

## Embedded App Databases

If an app uses a database, the preferred model is an embedded database inside the app's workspace-owned data root.

Examples:

```text
/workspaces/acme/data/checklists/app.db
/workspaces/acme/data/table_manager/app.db
/workspaces/acme/data/reports/analytics.duckdb
```

This database belongs to the app, not to the core platform.

## Core Database Versus App Database

The core platform database and app-owned storage must remain conceptually separate.

The core database is for platform concerns such as:

- auth
- users
- workspace registry
- memberships
- global audit
- platform installation state
- indexing and retrieval metadata
- operational and control-plane state

App-owned data should not be forced into the core database by default.

## Capability Surface

Every app should declare what it exposes to the platform and to the workspace.

Examples:

- MCP tools
- CLI commands
- skills
- views or widgets
- import/export hooks
- health or maintenance hooks

This declaration allows the platform to:

- render app UI correctly
- call app tools safely
- understand which app owns which kind of content
- understand which surface should be used for a given operation

The recommended mental model is:

- `mcp/` = structured tool surface
- `cli/` = command-oriented local surface
- `skills/` = procedural guidance for using the app's MCP and CLI correctly

Important distinction:

- `mcp/` and `cli/` are executable capability surfaces
- `skills/` is an instructional asset layer
- `skills/` is not a runtime interface, security boundary, or governance surface by itself

## Mounted App Model

In Maverick v3, everything above the core should be treated as an app.

This includes:

- end-user apps such as `chat`
- operator-facing apps
- agent-facing capability apps
- shell apps that host or frame other app frontends

The core does not become the UI product itself.

The core is the platform host that mounts app surfaces.

Each app may expose one or more of these surface families:

- `frontend/`
- `backend/`
- `mcp/`
- `cli/`
- `skills/`

The app contract should describe which of these surfaces exist and how the core should mount them.

This means an app is not limited to being:

- only a visual frontend
- only an API backend
- only an agent tool surface

One app may expose all of them at the same time.

It is not required that every app expose all of them.

The rule is:

- every app must declare its real surfaces explicitly
- the core mounts only the surfaces actually declared by that app

Examples:

- `chat` may expose a frontend for the user, a backend for app-specific server logic, MCP tools for agents, CLI commands for operators or agents, and skills for procedural guidance
- `base-shell` may expose a frontend shell that hosts the frontend of other apps while still being itself only another app mounted by the core

The core remains responsible for:

- installation
- enablement
- mounting
- auth and session context
- workspace context
- policy enforcement
- lifecycle orchestration

The app remains responsible for:

- its own domain model
- its own frontend behavior
- its own backend logic
- its own CLI and MCP behavior
- its own workspace-owned data under `data/<app_id>/`

## Frontend And Backend Surfaces

An app may ship a standalone frontend and a standalone backend while still being mounted by the core.

The intended model is:

- the core is the public platform host
- the core exposes mounted app routes
- the frontend of the app is served to the user through the platform host
- the backend of the app is routed through the platform host

The app backend is not the core.

The app frontend is not the core.

But both live under the governance and routing model of the core.

For the first v3 deployment model, the simplest canonical shape is:

- `/` for the platform host or shell entrypoint
- `/apps/<app_id>/...` for mounted app frontend routes
- `/api/apps/<app_id>/...` for mounted app backend routes
- `MCP` and `CLI` surfaces mounted by the core from the same app contract

The exact production routing layer may be implemented behind `nginx`, but the mount model should remain canonical at the platform level.

## Human Surface Versus Agent Surface

The same app may need to serve both humans and agents.

The intended split is:

- `frontend/` for human-facing visual interaction
- `backend/` for app-specific server logic
- `mcp/` and `cli/` for agent and operator execution surfaces
- `skills/` for agent guidance

This is a core design principle.

Apps in Maverick v3 are not just mini-sites.

They are platform extensions that can be:

- visual
- executable
- agent-usable
- operator-usable

at the same time.

## Frontend Hosting Apps

Some apps may primarily act as host shells for other app frontends.

This is still an app concern, not a core concern.

For example, a `base-shell` app may:

- expose the main frontend shell
- provide layout, app navigation, and visual composition
- mount or frame the frontend routes of other enabled apps

That does not make `base-shell` part of the core.

It remains an app mounted by the core like every other app.

This rule matters because the Maverick product shell should still be replaceable, versionable, and governable as an app.

## Secret references

If an app depends on external credentials or provider secrets, the app may declare secret references as part of its configuration model.

The app does not own the secret values themselves.

The app only owns the references it expects to use.

Secret values remain under platform control and must not be stored inside the app-owned workspace data root.

## Lifecycle Declaration

Every app should declare which lifecycle operations it supports.

Examples:

- install
- uninstall
- upgrade
- migrate
- export
- import
- validate after import
- repair after import
- rebuild
- health check

The goal is not to force every hook to exist.

The goal is to make lifecycle behavior explicit and automatable.

## Executable Contract Requirements

To be a real platform contract, the app contract should also declare executable integration details.

At minimum, the contract should support:

- `contract_version`
- `minimum_core_version`
- `entrypoints`
- `hook_timeouts`
- `failure_semantics`
- `compatibility`
- `health_contract`
- `rollback_support`

### Contract version

The app contract should declare its own contract schema version.

This allows the core to evolve contract handling safely over time.

### Minimum core version

The app contract should declare the minimum core version required to install or run the app.

This allows deterministic compatibility checks during install and upgrade.

### Entrypoints

The contract should declare the entrypoints for the executable app surfaces it actually supports.

Examples:

- MCP server entrypoint
- CLI entrypoint
- backend entrypoint
- frontend entrypoint or frontend asset root
- lifecycle hook entrypoints
- health check entrypoint

`skills/` does not need an execution entrypoint in the same sense.

It should instead declare where its instructional assets live.

For the first local v3 implementation, executable app entrypoints use a deterministic subprocess convention:

- the core resolves the declared entrypoint path inside the app root
- the core invokes that entrypoint as a local executable script with the current core interpreter
- the core passes a JSON payload on standard input
- the entrypoint returns a JSON object on standard output

This convention applies to app-owned MCP and CLI entrypoints in the initial implementation.

For mounted frontend and backend surfaces, the same principle applies:

- the contract must declare what the surface root or entrypoint is
- the core must mount it explicitly
- the app must not rely on implicit repo conventions unknown to the platform

For the first v3 implementation, it is acceptable for the frontend declaration to identify either:

- a frontend asset root
- a frontend build output root
- a frontend dev or preview entrypoint

and for the backend declaration to identify either:

- a callable entrypoint script
- or a backend surface root that the core knows how to host

The important rule is not the packaging style.

The important rule is that the mount contract is explicit and comes from the app contract.

### Frontend distribution artifacts

For apps that ship a frontend, the contract should distinguish between source and served artifact when that distinction matters.

Simple apps may point `entrypoints.frontend` directly at a static asset root.

Buildable apps such as React/Vite apps should declare the production build output as the mounted surface.

The source root may remain available for development, fork, audit, or agent customization only when the distribution mode allows it.

Recommended production shape:

```text
apps/<app_id>/
  app_contract.json
  frontend/
    src/
    dist/
```

In that shape, the platform host should mount `frontend/dist/`, not the TypeScript source tree.

For the first real `base-shell` port, `frontend/dist` is the canonical production mount target.

The `base-shell` source may use React, TypeScript, and Vite internally, but the core must only serve the declared static build output.

The v2 `base_shell` UI/UX is the visual and interaction reference for the v3 `base-shell`.

The port should preserve the shell experience, layout behavior, sidebar/topbar composition, workspace/app panels, and responsive behavior where those concepts are still valid.

The port must not preserve v2 runtime coupling, v2 API assumptions, v2 auth assumptions, or v2 manifest format.

The v3 shell attaches only to v3 platform protocols such as:

- `/api/apps` for enabled app registry data
- `/api/status` for platform status
- mounted app frontend routes under `/apps/<app_id>/`
- mounted app backend routes under `/api/apps/<app_id>/...`

The core remains responsible for routing, install state, enablement, policy, and app registry data.

The shell remains responsible only for visual composition and user interaction.

The contract may start with a simple path:

```json
"entrypoints": {
  "frontend": "frontend/dist"
}
```

As the contract matures, frontend declarations may become structured:

```json
"entrypoints": {
  "frontend": {
    "kind": "static_build",
    "source": "frontend",
    "mount": "frontend/dist",
    "spa_fallback": true
  }
}
```

The core must remain frontend-framework agnostic.

It should not know whether a build artifact came from React, Vue, Svelte, static HTML, or another frontend stack.

It should only know how to mount the declared frontend artifact.

### Backend distribution artifacts

Backend surfaces should follow the same principle.

The app contract declares the backend surface, but the core should not depend on the app's internal framework.

Examples of backend surface kinds that may be supported over time:

- local subprocess JSON entrypoint
- subprocess HTTP service
- packaged local service
- remote backend reference governed by platform policy

For the first implementation wave, app-owned backend entrypoints may remain local and platform-managed.

Sealed apps may provide only packaged backend artifacts.

Source-available or workspace-local apps may provide editable backend source that is built or launched according to a declared backend contract.

## Real Example: Base Shell And Chat

The following is a concrete example of the intended model.

```text
/apps/
  base-shell/
    app_contract.json
    frontend/
    backend/
    mcp/
    cli/
    skills/
  chat/
    app_contract.json
    frontend/
    backend/
    mcp/
    cli/
    skills/
```

In this example:

- `base-shell` is the mounted shell app
- `chat` is another mounted app
- both are apps
- neither is the core

The user may reach:

- `/apps/base-shell/` to load the shell frontend
- `/apps/chat/` to load the chat frontend directly
- `/api/apps/chat/...` for chat backend operations

Agents may use:

- chat MCP tools
- chat CLI commands
- chat skills

The core decides whether those surfaces are available in the current workspace.

The `base-shell` app may visually host the `chat` frontend.

That does not change ownership:

- shell composition belongs to `base-shell`
- chat functionality belongs to `chat`
- installation, policy, and mounting belong to the core

For the first hosted v3 wave, the minimal built-in set is:

- `base-shell` as the mounted frontend shell app
- `chat` as the first full app with frontend, backend, MCP, CLI, and skills

`memory` and `agents` remain later-wave apps even though the architecture is already shaped to host them the same way.

### Hook versioning

Lifecycle hooks should be versioned by the app contract and resolved explicitly by the core.

The core should not guess hook names or infer hook behavior from arbitrary files.

### Hook timeouts

The contract should allow explicit timeout declarations for operations such as:

- install
- upgrade
- migrate
- export
- import
- validate after import
- repair after import
- health check

This prevents non-deterministic hangs during platform lifecycle operations.

### Failure semantics

The contract should explicitly declare failure expectations for critical operations.

Examples:

- install failure blocks activation
- migrate failure leaves existing data intact and marks the app unhealthy
- import failure preserves imported payload until operator action
- health failure marks the app degraded rather than deleting data

### Compatibility

The contract should declare compatibility constraints such as:

- supported core versions
- supported workspace execution modes if relevant
- required provider or secret capabilities if relevant

### Health contract

The contract should define how the core checks whether the app is healthy.

This may include:

- a health command
- a health MCP route
- a validation hook
- a storage integrity check

### Rollback support

The contract should explicitly state whether the app supports:

- bundle rollback
- data rollback
- repair-only recovery

If rollback is unsupported, that should be declared rather than implied.

## Example Contract

The following example shows the kind of app contract Maverick should expect at platform level.

```json
{
  "app_id": "restaurant-manager",
  "contract_version": "1.0",
  "name": "Restaurant Manager",
  "version": "1.2.0",
  "description": "Manage rooms, tables, reservations, and service state inside a workspace.",
  "publisher": "third-party-dev",
  "minimum_core_version": "1.0.0",
  "distribution": {
    "mode": "source_available",
    "source_access": "forkable"
  },
  "capabilities": {
    "mcp_tools": [
      "tables.list",
      "tables.update",
      "reservations.create",
      "reservations.update"
    ],
    "cli_commands": [
      "tables",
      "reservations",
      "health"
    ],
    "skills": [
      "restaurant-operations",
      "reservation-repair"
    ],
    "views": [
      "floor_map",
      "reservation_board"
    ]
  },
  "entrypoints": {
    "mcp": "backend/mcp/server.py",
    "cli": "backend/cli/app_cli.py",
    "skills_root": "backend/skills/",
    "hooks": {
      "install": "backend/lifecycle/install.py",
      "migrate": "backend/lifecycle/migrate.py",
      "health_check": "backend/lifecycle/health.py"
    }
  },
  "storage": {
    "storage_kind": "sqlite",
    "primary_paths": [
      "data/restaurant-manager/app.db"
    ],
    "indices": {
      "kind": "embedded"
    },
    "supports_export": true,
    "supports_import": true,
    "supports_migrations": true
  },
  "compatibility": {
    "workspace_modes": ["sandbox", "full-access"]
  },
  "hook_timeouts": {
    "install_seconds": 60,
    "migrate_seconds": 300,
    "health_check_seconds": 30,
    "export_seconds": 120,
    "import_seconds": 120
  },
  "lifecycle": {
    "install": true,
    "upgrade": true,
    "uninstall": true,
    "migrate": true,
    "export": true,
    "import": true,
    "validate_after_import": true,
    "repair_after_import": false,
    "health_check": true
  },
  "health_contract": {
    "mode": "hook",
    "degraded_on_failure": true
  },
  "failure_semantics": {
    "install_failure": "block_activation",
    "migrate_failure": "preserve_data_mark_unhealthy",
    "import_failure": "preserve_payload_mark_failed"
  },
  "rollback_support": {
    "bundle": true,
    "data": false
  }
}
```

This example does not define the internal schema of the app database.

That remains the responsibility of the app developer.

The contract only defines what the platform needs to know in order to:

- install the app
- understand where the app owns its data
- understand what the app exposes
- manage lifecycle operations coherently
- resolve entrypoints deterministically
- enforce compatibility rules deterministically
- apply timeouts and failure semantics deterministically

An app may expose capabilities through more than one official surface:

- `mcp/`
- `cli/`
- `skills/`

Only `mcp/` and `cli/` are executable surfaces.

The contract declares which surfaces the app exposes, but the platform still decides how they are hosted:

- MCP and CLI are mounted through core-managed platform hosts
- skills are cataloged by the core as instructional assets
- provider-specific runtime installation of skill assets is handled by the selected provider adapter

When app-owned MCP tools and skills are surfaced through the platform, the host may apply namespacing to avoid collisions with core-owned assets or assets from other apps.

## Core Boundary Rule

Apps must not directly modify:

- core platform code
- other apps' data roots
- other workspaces
- platform database internals that are not part of the app contract

Apps interact with the core through declared MCP, CLI, or backend interfaces.

## Cross-App Boundary Rule

Apps do not read or write another app's internal data files or embedded databases directly.

Apps do not call or integrate with other apps directly.

Composition happens only through agents or runtime orchestration.

This preserves:

- modularity
- ownership clarity
- future portability
- app isolation inside the workspace

## Example Mental Model

The correct mental model is similar to an iPhone-style app container:

- the core is the platform
- the workspace is the tenant boundary
- `data/<app_id>/` is the app's owned data namespace inside that workspace

The app developer is free to choose how the app stores its own data inside that container.

## Decision Summary

The standard Maverick app contract should require:

- stable app identity
- workspace-owned storage under `data/<app_id>/`
- explicit storage declaration
- explicit capability declaration
- explicit lifecycle declaration
- no direct access to other apps' internal storage
- no direct coupling to core database internals as the default app data model
