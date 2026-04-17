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
- app contract metadata
- app installation state in the core
- app enablement state inside one workspace

Examples:

- an external app bundle may carry valid contract metadata before it is installed anywhere
- a workspace-local app project may exist under `workspaces/<workspace_id>/apps/` before it becomes an active capability
- an app may be installed but not enabled in a given workspace

The contract describes what the app is and how it behaves.

The core installation system decides where that app is known, installed, enabled, disabled, upgraded, uninstalled, or reattached.

## Canonical Contract File

The platform should treat the app contract file as the source of truth for executable app metadata.

The recommended canonical file is:

```text
<app_root>/app_contract.json
```

Examples:

```text
/apps/checklists/app_contract.json
/apps/_bundles/vendor-reporting/app_contract.json
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
- lifecycle hook entrypoints
- health check entrypoint

`skills/` does not need an execution entrypoint in the same sense.

It should instead declare where its instructional assets live.

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
  "app_id": "restaurant_manager",
  "contract_version": "1.0",
  "name": "Restaurant Manager",
  "version": "1.2.0",
  "description": "Manage rooms, tables, reservations, and service state inside a workspace.",
  "publisher": "third-party-dev",
  "minimum_core_version": "1.0.0",
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
      "data/restaurant_manager/app.db"
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
