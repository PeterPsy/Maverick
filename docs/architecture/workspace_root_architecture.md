# Workspace Root Architecture

Date: 2026-04-17

## Purpose

Define the target Maverick architecture where each workspace is a first-class isolated working environment.

This document establishes the intended end state:

- a top-level `workspaces/` directory exists alongside `core/` and `apps/`
- each workspace owns its own filesystem root
- sandboxed agents can work freely inside their workspace root
- sandboxed agents cannot directly write to `core/`, installation-level `apps/`, or other workspaces
- interactions with platform capabilities outside the workspace root happen only through official platform interfaces such as MCP, CLI, and backend APIs
- workspace memory, files, apps, and execution context remain confined to that workspace

This is a core feature, even though the workspace directories live physically outside the core code tree.

## Core Principle

Each non-default workspace is both:

1. a tenant boundary
2. a filesystem boundary
3. an agent runtime boundary
4. an app-data boundary

The workspace must behave like a complete local operating environment for the agent that runs inside it.

The platform should stop thinking in terms of:

- one shared repository plus many partial guards
- separate concepts for runtime root, storage root, and memory root

The platform should instead think in terms of:

- one canonical root per workspace
- everything the agent is allowed to touch lives inside that root
- everything outside that root is platform infrastructure and is only reachable through controlled interfaces

## Platform Plane Separation

Maverick should distinguish three different planes:

1. global control plane
2. workspace governance plane
3. workspace data plane

This separation is required to avoid mixing:

- platform identity and security
- workspace permissions and enablement state
- app-owned operational content

### Global control plane

The global control plane is platform-wide.

It governs:

- users
- authentication and sessions
- global roles
- workspace registry
- workspace memberships
- platform audit
- billing or licensing
- minimal installation-level platform state

This plane answers questions such as:

- who is this user
- which workspaces can this user access
- what platform-level privileges exist

### Workspace governance plane

The workspace governance plane is scoped to a workspace, but it is still platform state rather than app-owned operational data.

It governs:

- who can enter the workspace
- which users can create, install, update, or remove apps in that workspace
- which users can create, modify, or operate specific capabilities in that workspace
- which apps or capabilities are enabled or disabled in that workspace
- workspace-scoped policy and permission rules

This plane answers questions such as:

- can this user install apps in this workspace
- can this user create or manage agents in this workspace
- is this capability enabled in this workspace

The governance plane does not define the internal content of an app.

The initial control-plane persistence for workspace registry, membership, governance, quota, and active workspace selection may target MongoDB, but their semantics must not depend on Mongo documents or driver APIs.

Rules:

- workspace records keep domain meaning regardless of persistence backend
- service-layer contracts should depend on store interfaces or equivalent abstractions
- Mongo-specific queries and update operators stay inside store adapters only

The hosted shell may expose workspace selection through generic core APIs.

The current active workspace is session state for a user, not a property of the shell app.

That means:

- `/api/session` may report the active workspace id for the current user
- `/api/workspaces` may list workspace records the user is a member of
- `/api/workspaces/active` may switch the active workspace for that user session
- `/api/apps` and `/api/status` should resolve against the active workspace
- chat projects are not workspace selection; project organization remains app-domain state owned by the chat app

### Workspace data plane

The workspace data plane contains the actual operational content owned by the workspace and by the apps installed inside it.

It includes:

- workspace files
- `data/<app_id>/`
- workspace-local app databases
- workspace-local app state
- memory content
- chat content
- generated outputs
- saved views, saved widgets, and app-owned persisted artifacts

This plane answers questions such as:

- which agent definitions exist in this workspace
- which dynamic views exist in this workspace
- which CRM records exist in this workspace
- which notes, chats, files, and outputs exist in this workspace

App-owned content belongs here, not in governance.

For example:

- the app `agents` defines which agent records exist in the workspace
- workspace governance decides who may create, modify, or operate those agents

## Target Filesystem Layout

At installation level, Maverick should have:

```text
/maverick/
  apps/
  core/
  workspaces/
    default/
      apps/
      data/
      logs/
      storage/
        uploaded/
        generated/
      tests/
      tmp/
      runtime/
    acme/
      apps/
      data/
      logs/
      storage/
        uploaded/
        generated/
      tests/
      tmp/
      runtime/
```

The workspace root remains the writable tenant boundary for sandboxed agents.

Runtime-owned temporary state remains inside:

```text
/workspaces/<workspace_id>/runtime/
```

This runtime directory is for ephemeral provider state, logs, process metadata, and temporary files.

So the distinction is:

- `workspace_root` = the writable sandbox boundary for the workspace
- `runtime/` = runtime-local temporary and operational state, not the provider process cwd

Provider processes that operate on workspace files should start in the workspace root.

Notes:

- `default/` is the installation-level workspace created automatically by Maverick.
- Every additional company or tenant workspace gets its own sibling root under `workspaces/`.
- `core/` and the installation-level app store/cache under `apps/` stay outside the workspace roots.
- A sandboxed agent assigned to a non-default workspace may not write outside `/workspaces/<workspace_id>/`.
- `core/` is itself the package root of the platform core and should not contain wrapper layers such as `backend/`, `runtime_backend/`, or `app/`.

The initial implementation should expose canonical path helpers and workspace bootstrap services for this layout before building higher-level runtime behavior on top of it.

## Workspace Contents

Each workspace root is the canonical home for everything that belongs to that tenant's operating environment.

### `apps/`

`apps/` contains workspace-local app source trees, app bundles under development, and workspace-specific app material.

This is where users and workspace agents can develop app projects that belong only to that workspace.

This workspace-local `apps/` directory must not be confused with the installation-level `/apps` directory.

The installation-level `/apps` directory is the server-managed app store, trusted artifact cache, and built-in app area.

The workspace-local `workspaces/<workspace_id>/apps/` directory is editable tenant material.

Installing an app from the server app store creates a workspace binding to the installation-level artifact unless the app is explicitly forked into the workspace.

A workspace-local fork or app project should live under:

```text
workspaces/<workspace_id>/apps/<app_id>/
```

The app's workspace-owned data still lives separately under:

```text
workspaces/<workspace_id>/data/<app_id>/
```

Important trust rule:

- code under `workspaces/<workspace_id>/apps/` is editable workspace material
- it is not automatically trusted or executable just because it exists there
- a workspace-local app must still be explicitly installed or mounted for that workspace before it becomes an active capability
- code under installation-level `/apps` is not workspace-editable unless a fork is explicitly created under the workspace root

This means:

- workspace-created apps can be developed locally and installed only into their own workspace
- they are invisible to other workspaces unless later promoted into a platform-level distribution channel
- store-installed apps can be enabled in many workspaces without duplicating source into every workspace
- installation state and enablement are still governed by the core

The agent must not directly edit platform apps under the installation-level `apps/` directory.

### `data/`

Workspace-saved content produced through global app capabilities lives here.

This directory is for persisted workspace-owned content that is created or managed by app features but does not belong inside the global app code or platform-level app storage.

Examples:

- saved dynamic views
- saved checklists
- saved widget payloads
- app-local persisted state
- workspace-owned app outputs that are not just gallery files

Recommended shape:

```text
/workspaces/<workspace_id>/data/
  dynamic_views/
  checklists/
  crm/
  chat/
  memory/
  widgets/
  custom_app_x/
```

The exact subdirectories can evolve, but the ownership rule must remain stable:

- the app is a global capability
- the saved content belongs to the workspace

The initial canonical workspace bootstrap should materialize at least:

- `apps/`
- `data/`
- `logs/`
- `runtime/`
- `storage/uploaded/`
- `storage/generated/`
- `tests/`
- `tmp/`

Apps in a workspace may expose more than one official executable capability surface:

- `mcp/`
- `cli/`

An app may also ship:

- `skills/`

`skills/` is not an executable interface in the same sense as MCP or CLI.

It is an instructional layer that helps an agent or operator use the app correctly.

If skill content is synchronized into a runtime home or other runtime-adjacent location, that synchronization does not make `skills/` an executable boundary.

The executable surfaces remain MCP, CLI, and backend-controlled service interfaces.

The platform host should be able to expose app-contributed MCP, CLI, and skills surfaces once the app is installed and enabled for that workspace.

The app declares those surfaces through its contract and source layout, but the core remains responsible for validating them, mounting them, and enforcing workspace boundaries.

That includes:

- enforcing invocation policy for shared MCP and CLI hosts
- applying platform-level namespacing where needed to avoid collisions between app-owned and core-owned surfaces

Apps may also declare embeddable frontend widgets.

Widgets are visual surfaces owned by the app that declares them.

They may be rendered inside another app's UI, but they do not create app-to-app communication.

For example:

- the `chat` app may render a structured message
- the structured message may contain a content kind such as `checklist.design`
- the installed `checklists` app may declare a widget that can render `checklist.design`
- the platform registry exposes that widget as available in the workspace
- chat embeds the widget through the core-mounted widget surface

The ownership remains separate:

- `chat` owns the chat transcript and message container
- `checklists` owns the widget renderer and checklist data
- the core owns registry, mounting, auth, workspace context, and enablement checks

The embedding app must not import source files from the widget owner.

The widget owner must not write into the embedding app's data root.

Widget state must be stored under the widget owner's app data namespace:

```text
/workspaces/<workspace_id>/data/<widget_owner_app_id>/
```

If no enabled widget can render a structured payload, the embedding app must show a safe generic fallback instead of failing the transcript or hiding the content.

Each app should own its own namespace under:

```text
/workspaces/<workspace_id>/data/<app_id>/
```

This is the Maverick equivalent of an app sandbox data container.

If an app named `dynamic_views` produces a saved artifact for workspace `acme`, it should persist under:

```text
/workspaces/acme/data/dynamic_views/
```

not under a platform-global app-owned storage area.

### App-owned storage model

Each app in a workspace should be free to store its own data in the way the app developer considers most appropriate, as long as it stays inside the app's workspace-owned data root.

That means the platform should support this principle:

- the workspace is the tenant boundary
- `data/<app_id>/` is the app storage boundary inside that workspace
- the app developer chooses the internal storage structure

The standard contract for Maverick apps is defined in:

- [app_contract_architecture.md](/home/ubuntu/maverick-v3/docs/architecture/app_contract_architecture.md)

Examples of valid app-local storage choices:

- SQLite
- DuckDB
- JSON or JSONL files
- directory-per-record layouts
- append-only logs
- caches and manifests

Each app may also ship its own operational surfaces alongside its data model:

- `mcp/` for structured tool access
- `cli/` for command-oriented local operations
- `skills/` for procedural guidance on how to use the app correctly

### App lifecycle in workspaces

The platform must distinguish clearly between:

- app bundle, package, or executable capability source
- app installation state in a workspace
- app enabled or disabled state in a workspace
- app-owned data in `data/<app_id>/`

These are related, but they are not the same thing.

#### Install

When an app is installed in a workspace, Maverick should:

1. register the app as installed for that workspace
2. create `data/<app_id>/` if it does not already exist
3. make the declared app capability available to that workspace
4. execute the app install hook if one exists
5. initialize app-local storage only as needed

Bundle source may differ:

- server app store artifacts under installation-level `/apps` remain outside the workspace and are enabled for the workspace through core-managed installation state
- sealed app artifacts are not copied into the workspace for modification
- source-available store apps may be forked into `workspaces/<workspace_id>/apps/<app_id>/` only through an explicit fork/customize operation
- workspace-local app projects under `workspaces/<workspace_id>/apps/` may be installed only into that same workspace unless later promoted through a platform-level distribution channel

Install should create the minimum required structure, not arbitrary seeded content unless the app explicitly defines it.

#### Uninstall

Uninstall should remove the app as an active capability from the workspace, but should not automatically delete the app's persisted data.

That means:

- the app is no longer active in the workspace
- the app may be hidden or disabled in operator-facing surfaces
- the app's data root may remain on disk

This keeps uninstall safe and reversible.

#### Purge app data

Purging app data is a separate operation from uninstall.

Purging should:

- explicitly delete `data/<app_id>/`
- explicitly remove app-owned persisted local state
- require clear operator intent

This avoids conflating:

- removing access to an app
- destroying the app's data

#### Reinstall

If an app is reinstalled in a workspace and `data/<app_id>/` still exists, Maverick should allow the app to reattach to that existing data.

This may require:

- validation
- repair
- migration

but it should not require a fresh data root by default.

### App-owned indices

Indices belong to the app that creates them.

They are not owned by the core and they are not part of a shared platform indexing layer.

Indices are optional and app-specific.

If an app stores indices as files, they should live under:

```text
/workspaces/<workspace_id>/data/<app_id>/indices/
```

If an app uses an embedded database, indices may live inside that database instead.

Examples:

```text
/workspaces/acme/data/memory/indices/
/workspaces/acme/data/crm/indices/
/workspaces/acme/data/chat/app.db
```

where the SQLite or DuckDB file may already contain the app's internal indexes.

The platform does not define the semantic structure of those indices.

The only platform rule is that app-owned indices remain inside the app's own workspace data boundary.

### Isolation between apps inside a workspace

Apps inside the same workspace must remain isolated from each other.

This is an app-runtime and app-contract boundary.

It is not a filesystem security boundary against the workspace's own agent.

That means:

- apps do not communicate directly with other apps
- apps do not know about other apps as internal dependencies
- apps do not read `data/<other_app_id>/`
- apps do not open another app's embedded database
- apps do not write into another app's storage area

The only component that may compose multiple apps in one workflow is the agent runtime.

The workspace agent itself may still edit any workspace files, including app-owned files, because the workspace root is the sandbox perimeter.

That is intentional.

The rule here is narrower:

- installed app capabilities do not call each other
- installed app capabilities do not depend on direct access to each other's internal stores
- app isolation is enforced at capability/runtime level, not by pretending the workspace agent cannot edit workspace files

In other words:

- apps expose capabilities
- agents decide when to use them
- orchestration happens at the agent or runtime level, not at the app-to-app level

This rule preserves:

- modularity
- ownership clarity
- storage isolation
- the standalone nature of the core and the apps

### Agents app versus core runtime backend

The core runtime exposes a provider-agnostic runtime abstraction.

One supported runtime backend today is:

- `Codex`

`Codex` is not the architectural definition of the runtime.

It is one backend that can satisfy the runtime contract.

What Maverick calls "agents" at workspace level are not separate core runtime types.

They are app-owned configurations that instruct the selected runtime backend through prompts and related metadata.

That means:

- the core owns runtime execution and backend selection
- the app `agents` owns workspace-specific agent definitions
- those definitions may include a shared base prompt plus a role-specific prompt

The first provider implementation should not blur these concerns:

- runtime session and turn lifecycle remain in the runtime domain
- backend env-building and provider-specific launch configuration belong in the provider adapter
- workspace agent definitions remain app-owned configuration, not provider records

Provider credentials are also not app-owned workspace data.

They remain under platform control even when one workspace selects which provider binding it wants to use.

The current v3 implementation resolves provider selection in the core and currently ships only one concrete runtime backend adapter:

- `Codex`

That is an implementation starting point, not a narrowing of the architecture. The workspace/runtime boundary remains provider-agnostic.

Examples of app-owned agent definition content:

- common system prompt fragments
- role-specific prompt instructions
- naming and description
- optional app-owned configuration metadata

These definitions belong to the workspace data plane under the `agents` app.

They do not redefine the core runtime model.

### Agent catalog and agent runtime

The app `agents` defines the workspace catalog of agent configurations.

Those definitions live in:

```text
/workspaces/<workspace_id>/data/agents/
```

and are persisted as app-owned data.

The runtime state of a running agent is separate.

Running state is operational and ephemeral.

It belongs to the runtime perimeter of the workspace, not to the persisted catalog of agent definitions.

This separation must remain explicit:

- `Codex` runtime in the core
- agent definitions in the `agents` app
- runtime execution state in workspace runtime state
- governance deciding who may create or use those agent definitions

### Recommended storage choices for app developers

The platform should recommend:

- `SQLite` as the default embedded database for most stateful applications
- `DuckDB` for analytics-heavy local applications
- `JSON` or `JSONL` for simple config, manifest, snapshot, or log-oriented cases

The platform should not assume that every app uses the same internal data model.

Different apps may legitimately choose different shapes:

- a checklist app may use one SQLite file or a small set of JSON documents
- a restaurant table manager may use a more transactional SQLite layout
- a reporting app may use DuckDB
- a widget app may store small saved payload files

### Embedded app databases

If an app developer wants a database for the app, the preferred model is an embedded database inside the app's workspace-owned data root.

Examples:

```text
/workspaces/acme/data/checklists/app.db
/workspaces/acme/data/table_manager/app.db
/workspaces/acme/data/reports/analytics.duckdb
```

This app-level database is separate from the platform database.

The platform database is not the default storage engine for app-owned data.

### Platform database versus app database

Maverick should distinguish clearly between:

- the core platform database
- app-owned embedded storage inside the workspace

The core platform database exists for platform-level concerns such as:

- auth
- users
- workspace registry
- memberships
- platform app installation state
- indexing
- retrieval metadata
- analytics
- control-plane and operational state

App-owned data should not be forced into the core database by default.

If an app needs persistent structured local state, it should normally persist that state under:

```text
/workspaces/<workspace_id>/data/<app_id>/
```

using the embedded or file-based storage model that best fits the app.

### MongoDB policy for app-owned data

The core MongoDB database should not be treated as the default private database for each app.

Using the core MongoDB as the app's primary private store would blur the line between:

- platform data
- app data

and would reintroduce unnecessary coupling between app internals and the platform storage model.

The intended default is:

- core MongoDB for platform concerns
- embedded app storage for app-owned workspace data

An app can still expose or synchronize selected derived state through MCP or platform indexing layers when needed, but the app's own data ownership remains inside its workspace root.

### App lifecycle in workspaces

The platform must distinguish clearly between:

- app bundle or executable capability
- app installation state in a workspace
- app-owned data in `data/<app_id>/`

These are related, but they are not the same thing.

#### Install

When an app is installed in a workspace, Maverick should:

1. register the app as installed in that workspace
2. make the app bundle or capability available to that workspace
3. create the app data root at `data/<app_id>/` if it does not already exist
4. execute the app's install hook if one exists
5. initialize the app's local storage only as needed

Bundle source may differ:

- server app store artifacts under installation-level `/apps` remain outside the workspace and are only bound or enabled for that workspace
- sealed app artifacts remain non-editable and should not be copied into workspace app source directories
- source-available store apps may be forked into `workspaces/<workspace_id>/apps/<app_id>/` when the user or an authorized agent requests customization
- workspace-local app projects under `workspaces/<workspace_id>/apps/` may be installed only into that same workspace

Install should create the minimum required structure, not arbitrary seeded content unless the app explicitly defines it.

#### Upgrade

When an app is upgraded in a workspace, Maverick should:

1. activate the new version for that workspace
2. preserve the existing `data/<app_id>/`
3. execute the app's migration hook if one exists
4. update the local installation metadata

Upgrade must not silently discard app-owned data.

Upgrade must also preserve the source boundary.

If the workspace binding points to a workspace-local fork, normal upgrade should continue using that workspace-local project.

Moving a workspace-local fork back onto an installation-level store artifact is a rebase operation, not a normal upgrade, and must be requested explicitly.

Both upgrade and rebase must verify that the target source has the same `app_id` as the current workspace binding.

#### Uninstall

Uninstall should remove the app as an active capability from the workspace, but should not automatically delete the app's persisted data.

That means:

- the app is no longer active in the workspace
- the app may be hidden or disabled in the UI
- the app's data root may remain on disk

This keeps uninstall safe and reversible.

#### Purge app data

Purging app data is a separate operation from uninstall.

Purging should:

- explicitly delete `data/<app_id>/`
- explicitly remove app-owned persisted local state
- require clear operator intent

This avoids conflating:

- removing access to an app
- destroying the app's data

#### Reinstall

If an app is reinstalled in a workspace and `data/<app_id>/` still exists, Maverick should allow the app to reattach to that existing data.

This may require:

- validation
- repair
- migration

but it should not require a fresh data root by default.

#### Workspace duplication

If a workspace is duplicated, the duplicated workspace should carry over app-owned persisted data under `data/<app_id>/`.

By default, duplication should preserve:

- persistent app data
- local app databases
- saved app content

By default, duplication should not preserve unless explicitly requested:

- temporary files
- runtime state
- caches

#### Export and import

Workspace export and import should include app-owned persisted data under `data/<app_id>/`, together with the metadata required to understand which apps were installed and which versions those data were associated with.

If app data is imported before the corresponding app is available locally, Maverick may keep that data as dormant app-owned workspace content until the app is installed again.

### App data migrations

Every app is responsible for its own data schema and for migrating its own persisted data.

The core platform should not know the internal schema of an app's database or file model.

The core should only provide:

- a lifecycle contract
- a migration invocation point
- clear success or failure handling

This preserves the standalone and headless nature of the core.

#### Migration ownership

The platform orchestrates migrations.

The app performs migrations.

That means:

- the core decides when migration should be invoked
- the app decides how its own data should be transformed

#### Data schema version

Every app should maintain its own `data_schema_version`.

This may live:

- in a local metadata file under `data/<app_id>/`
- inside the app's embedded database
- in another app-owned local metadata structure

The important rule is that the app must be able to determine:

- which data schema version currently exists
- which schema version the current app version expects

In the first v3 implementation, a small app-owned metadata file under `data/<app_id>/` is an acceptable default place to persist the current data schema version and installed app version.

#### Upgrade migration flow

When an app is upgraded in a workspace:

1. Maverick activates or prepares the new app version
2. Maverick invokes the app migration hook if required
3. the app reads the current data schema version
4. the app performs the required migration steps
5. the app updates its local schema version metadata

#### Migration failure behavior

If a migration fails:

- app-owned data must not be deleted
- the app should not be treated as healthy in that workspace
- the workspace should retain the existing data in place
- the failure should remain visible as operational state

This allows:

- retry
- repair
- reinstall
- rollback of the app bundle if supported

without silently destroying data.

#### Rollback responsibility

The core may support rollback of the installed app version.

The core should not assume it can rollback the app's data automatically.

Rollback of app data remains the responsibility of the app itself unless the app explicitly supports a safe rollback strategy.

#### Migration design expectations

App migrations should be:

- explicit
- deterministic
- ordered
- idempotent when reasonably possible

The core should not depend on the internal migration mechanism.

An app may use:

- SQL migration scripts
- embedded migration runners
- file transformation scripts
- app-specific repair routines

as long as the migration remains owned by the app.

### Workspace backup, restore, export, and import

The platform must distinguish clearly between:

- workspace backup or export
- platform backup

These are related, but they are not the same operation.

#### Workspace export scope

A workspace export should include the persistent workspace data plane.

That includes:

- workspace-local app data under `data/<app_id>/`
- workspace-owned files under `storage/uploaded/`
- workspace-owned generated outputs under `storage/generated/`
- workspace-local memory artifacts
- workspace-local app-owned content and databases
- workspace-local app metadata needed to understand the content
- installation metadata required to resolve local app data deterministically

#### What should be excluded by default

Workspace export should not include by default:

- `tmp/`
- `runtime/`
- caches
- `logs/`
- live process state
- other ephemeral or regenerable artifacts

These are not part of the persistent workspace data plane.

For the default export implementation, cache exclusion should apply at least to paths named:

- `cache/`
- `caches/`
- `.cache/`
- `__pycache__/`

#### Workspace manifest

Every workspace export should include a minimal manifest describing the exported workspace.

The manifest should include at least:

- `workspace_id`
- export timestamp
- installed or known app references
- app version metadata
- app source kind metadata
- workspace-local fork provenance when applicable
- app-level data schema version metadata
- schema version metadata
- inventory or checksum information as needed

These fields are required for deterministic restore, reinstall, migration, and dormant-app-data handling.

They should not be treated as optional nice-to-have metadata.

This keeps workspace export understandable and portable.

#### Workspace import

When a workspace is imported, Maverick should:

1. create or attach the target workspace
2. restore the workspace data plane
3. retain app-owned data even if a corresponding app is not yet available locally
4. preserve the imported app data as dormant workspace content until the app is installed or restored

Import must not silently discard app-owned data just because an app is missing at import time.

#### Snapshot consistency

Workspace export must be a coordinated snapshot, not a best-effort copy of unrelated sources.

Because app-owned data may include:

- embedded databases
- file trees
- derived indices
- manifests

the platform should either:

- quiesce the relevant app before export, or
- invoke the app's export hook to produce a consistent snapshot

When the platform invokes an app export hook, it should pass a structured context that includes at least:

- `workspace_id`
- `workspace_root`
- `export_root`
- `app_id`
- `data_root`
- uploaded and generated storage roots
- source record metadata sufficient to identify the installed app bundle or project

The export process must not assume that copying live files blindly is always sufficient.

#### Restore

Restore is different from import.

- import moves workspace content into a platform instance
- restore returns a workspace to a prior known state

Restore should operate on the workspace data plane without requiring a rebuild of the full control plane.

#### Relationship to the control plane

Workspace export is not the same thing as control-plane backup.

Workspace export should not include:

- global users
- auth sessions
- workspace memberships
- global roles
- billing or licensing state
- complete platform registry state

Those belong to the platform control plane and should be backed up separately.

#### Platform backup

The platform should also support a separate backup of the control and governance planes.

That platform backup covers:

- users
- auth and session state
- workspace registry
- memberships
- workspace governance metadata
- installation metadata
- other platform-level records

This backup is distinct from workspace export.

## Observability And Logs

Observability must distinguish clearly between:

- platform-level events
- runtime-level events
- workspace-level events
- app-level events

This separation prevents operational debugging from collapsing into one undifferentiated log stream.

### Installation-level logs

At installation level, Maverick should have:

```text
/maverick/logs/
  platform/
  runtime/
```

#### `logs/platform/`

This area is for platform and control-plane logs such as:

- auth
- users
- memberships
- workspace registry operations
- app installation metadata operations
- secret resolution and related control-plane events
- global audit and core failures

#### `logs/runtime/`

This area is for runtime engine and orchestration logs such as:

- agent host lifecycle
- process management
- sandbox or full-access runtime behavior
- runtime crashes and infrastructure-level execution failures

### Workspace-level logs

Each workspace should have its own log root:

```text
/workspaces/<workspace_id>/logs/
  workspace/
  apps/
```

#### `logs/workspace/`

This area is for workspace-scoped operational events such as:

- workspace export
- workspace import
- workspace restore
- workspace-level operational transitions

Runtime-domain records are authoritative execution state, not debug logs.

The local bootstrap host may persist runtime collections under installation-local `.maverick/local-state/runtime/` until the production store adapter is wired.

That persistence must preserve runtime sessions, turns, events, processes, and state across host restarts so app-owned references such as chat thread `runtime_session_id` remain resolvable.

#### `logs/apps/<app_id>/`

This area is for app-local logs within that workspace.

Examples:

- migration logs
- validation logs
- repair logs
- app-local import or export logs
- app-local debug or failure logs

### Observability rule

App-local logs may exist in the workspace, but they must not be treated as the only reliable observability surface.

The platform should still provide structured event attribution so that operators can understand:

- which workspace an event belongs to
- which app caused it
- whether it came from core, runtime, workspace, or app scope

The platform should also distinguish clearly between:

- workspace or app logs
- installation-level platform or runtime logs
- structured audit records
- metrics and health telemetry

These surfaces may describe the same incident, but they do not have the same retention, export, or access semantics.

### Redaction rule

Logs and audit surfaces must not leak:

- raw secret values
- raw provider credentials
- sensitive runtime environment snapshots unless an operator-level policy explicitly permits them

Debugging support should therefore prefer:

- stable identifiers
- secret binding ids or aliases
- runtime session ids
- app ids and workspace ids

instead of embedding sensitive payloads directly in logs.

## Resource Limits And Quotas

Resource control is required to keep the platform stable once workspaces can host:

- app-owned databases
- generated files
- uploaded files
- logs
- temporary artifacts
- runtime state
- multiple agents

Without explicit limits, one workspace or one app can degrade the whole installation.

### Resource control planes

Resource limits must exist at two levels:

1. workspace level
2. app level inside a workspace

The workspace remains the primary tenant boundary.

App-level limits exist as a second layer to prevent one app from consuming the entire workspace allocation.

### Workspace-level limits

The platform should support workspace-scoped limits such as:

- maximum disk usage for the workspace
- maximum size of `storage/uploaded/`
- maximum size of `storage/generated/`
- maximum size of `logs/`
- maximum size of `tmp/`
- maximum size of `runtime/`
- maximum number of installed apps
- maximum number of configured agent definitions
- maximum number of concurrently active agent runtimes

These limits belong to workspace governance, not to app-owned data.

### App-level limits

Within a workspace, the platform should support limits for a single app such as:

- maximum size of `data/<app_id>/`
- maximum size of `logs/apps/<app_id>/`
- maximum temporary storage used by the app
- maximum number of app-owned runtime processes, if the app launches any
- maximum generated output owned by the app when that distinction exists

These limits are still governance policy, but they apply inside one workspace to one app namespace.

### Soft limits and hard limits

The platform should distinguish between:

- soft limits
- hard limits

#### Soft limits

Soft limits should:

- emit warnings
- produce observable events
- surface degraded status where useful
- notify operators before the workspace or app is blocked

#### Hard limits

Hard limits should:

- block new writes when required
- block new app installs when required
- block new runtime starts when required
- reject new generated outputs when required
- reject other expensive operations once the limit is truly exceeded

This distinction allows safe operation before catastrophic exhaustion.

### Cleanup policy

Resource limits only work well when paired with cleanup policy.

The platform should treat different workspace paths differently.

#### Safe to clean automatically

The platform may automatically clean or rotate:

- `tmp/`
- stale runtime state under `runtime/`
- app caches that are explicitly marked regenerable
- old log files beyond configured retention

#### Not safe to clean automatically

The platform must not treat the following as disposable by default:

- `data/<app_id>/`
- `storage/uploaded/`
- `storage/generated/`
- app-owned embedded databases
- persisted workspace content

Quota enforcement should not silently destroy durable app or workspace data.

### Enforcement points

The platform should enforce limits at the operational points where resource growth occurs.

Examples:

- app install
- app upgrade that requires temporary extra space
- file upload
- generated output write
- creation of large app databases
- export operations
- runtime start
- log growth
- cache creation

Limits are not just metadata. They must be enforceable at these boundaries.

### Governance ownership of limits

All limits and quotas belong to the workspace governance plane.

They are not app-owned content.

That means:

- apps do not define their own final quotas as source of truth
- the platform or workspace governance decides the effective limits
- the app may declare its needs, but governance decides what is allowed

### Failure behavior

When a limit is exceeded, the platform should prefer:

- explicit failure
- observable warning
- actionable operator feedback

instead of:

- silent truncation
- silent deletion of durable data
- hidden cleanup of app-owned content

### Design summary

The architecture should support:

- workspace-level quotas
- app-level quotas inside a workspace
- explicit cleanup policy
- soft and hard limit thresholds
- enforcement at operational write points

This preserves both:

- workspace isolation
- app ownership of durable data

### `storage/uploaded/`

Files uploaded by users into the workspace.

These should automatically appear in the workspace file inventory and gallery as uploaded files.

### `storage/generated/`

Files generated by agents or workspace-local tools.

These should automatically appear in the workspace gallery as generated assets without requiring a separate persistence ritual.

### `storage/` versus `data/`

The workspace should distinguish between file artifacts and saved app content.

Use `storage/` for file-like artifacts:

- uploaded files
- generated documents
- generated media
- binary assets intended for gallery or file inventory

Use `data/` for saved structured content owned by the workspace and produced by app capabilities:

- saved dynamic views
- saved checklist state
- saved custom widget configurations
- app-specific persisted content that is not primarily a gallery file

This separation keeps the workspace understandable:

- `storage/` is file inventory
- `data/` is workspace saved content

### `tests/`

Workspace-local tests, fixtures, sandboxes, evaluation scripts, and validation outputs.

### `tmp/`

Temporary files produced during agent execution inside the workspace.

### `runtime/`

Ephemeral runtime state can live here if needed, but it is still part of the workspace root and not a separate storage domain.

This directory exists for implementation convenience, not as a separate conceptual filesystem.

Typical examples of valid content here are:

- runtime session state
- active turn state
- watchdog or recovery markers
- local runtime process artifacts that are not app-owned data

This directory is not the canonical home for:

- uploaded files
- generated artifacts
- app-owned structured business data
- persistent chat-thread history

## Runtime Model

### Sandbox rule

A sandboxed agent must have write access to its entire workspace root and nowhere else.

That means:

- readable and writable: `/workspaces/<workspace_id>/...`
- not writable: `/core/...`
- not writable: `/apps/...`
- not writable: `/workspaces/<other_workspace_id>/...`

This is the key behavior change from the current model.

Today, the runtime primarily writes to a narrow workdir and persists files elsewhere through backend code paths.

The target model is simpler:

- the workspace root is the workdir perimeter
- the sandbox perimeter matches the workspace perimeter
- the agent can organize files directly inside the workspace

For the first local runtime implementation, this should also mean:

- the runtime resolves `workspace_id` from trusted runtime ownership, not from arbitrary client-provided path selection
- child runtime sessions inherit the same workspace root unless a trusted control-plane action explicitly changes scope
- runtime-local ephemeral state stays under `workspaces/<workspace_id>/runtime/`
- `storage/` and `data/` remain separate from runtime process state

### Default workspace exception

The installation-level `default` workspace is a special operational workspace.

It still has its own dedicated workspace root under:

```text
/workspaces/default/
```

but agents created there are not required to be sandboxed.

In the `default` workspace, agents may run with `full-access` and may operate on the server outside the workspace root when explicitly allowed by the platform.

Examples:

- editing platform files
- operating on `core/`
- operating on installation-level `apps/`
- interacting with system services such as nginx

This makes the `default` workspace the privileged operator workspace of the installation.

The first implementation of this mode does not need distributed runtime nodes or remote execution infrastructure.

It only needs a clear local full-access mode that is explicitly policy-gated and correctly bounded.

### Non-default workspace rule

Every workspace other than `default` is an isolated workspace.

For those workspaces:

- agents are always created sandboxed
- the workspace root is the absolute filesystem boundary
- agents must not access files outside the workspace in any way
- agents must not operate on platform files, services, or other workspaces

So the model is intentionally asymmetric:

- `default` workspace: privileged operator workspace, may use `full-access`
- non-default workspaces: isolated tenant workspaces, sandbox-only

## Secret Management

Secret handling must preserve both:

- platform-level control and security
- separation between app-owned workspace data and platform-managed sensitive state

### Core rule

Secret values must not be stored inside:

- `data/<app_id>/`
- app-owned embedded databases
- workspace-exported files
- workspace-local config files in cleartext

### Secret values versus secret references

The architecture should distinguish clearly between:

- secret values
- secret references

Secret values belong to the platform control and governance planes.

Workspace apps may store only references to secrets, not the secret values themselves.

Examples of valid workspace-side content:

- secret alias
- secret binding id
- logical reference name

Examples of invalid workspace-side content:

- raw API token
- raw private key
- raw provider secret

### Access model

Apps and agents do not read secret values from workspace files.

They access secrets through controlled runtime or backend interfaces.

That means:

- the workspace may declare which secret reference it needs
- the runtime resolves that reference through the platform
- the platform decides whether the secret may be used

If the runtime receives a resolved secret value, that delivery should be treated as ephemeral runtime input, not as workspace-owned persisted state.

So resolved values must not be written back into:

- `runtime/state/`
- `data/<app_id>/`
- workspace-local config files
- exported workspace artifacts

### Export and import behavior

Workspace export and import must never include secret values.

At most, workspace data may include:

- secret references
- unresolved bindings
- placeholders indicating that secrets must be reconfigured

If a workspace is imported elsewhere, secret values must be re-established in the local platform control plane.

### Working directory

The runtime may choose a default working directory inside the workspace, for example:

```text
/workspaces/<workspace_id>/
```

or:

```text
/workspaces/<workspace_id>/runtime/<user_id>/<instance_id>/
```

but this choice must not reduce the sandbox's writable scope to only that subdirectory.

The writable scope must still be the whole workspace root.

### Platform interaction rule

If a sandboxed agent wants to:

- query company memory outside local files
- create or manage Maverick app records
- access operating system records
- inspect platform status
- interact with external providers
- create child agents
- invoke platform CLI functionality that is not workspace-local

it must do so through MCP tools, controlled CLI entrypoints, or backend APIs.

It must not do so by directly editing platform code or reaching into global storage.

Sandboxed agents never access the database directly.

Workspace-scoped records such as app records, operating records, and other structured platform state must be created and updated only through MCP tools, controlled CLI entrypoints, or backend interfaces that enforce workspace isolation.

For sandboxed workspace agents, controlled CLI entrypoints must be explicitly allowed by platform policy.

The platform must not treat arbitrary CLI argument passing as sufficient proof of workspace authority.

Workspace authority has to be derived from trusted runtime ownership and policy resolution, then enforced by the command surface.

When skill assets are synchronized into provider-specific runtime homes, that synchronization must still happen through platform-controlled provider adapters rather than through direct app-managed runtime mutation.

The same rule applies to persisted content produced through global app capabilities:

- global apps may render, validate, or manage content
- saved content produced through those apps must be written into the current workspace under `data/<app_name>/` or another workspace-owned path

No global app should be treated as the long-term owner of tenant content created inside a workspace.

## Gallery and File Inventory Model

The workspace filesystem should be the source of truth for workspace files.

That means:

- files in `storage/uploaded/` are uploaded files
- files in `storage/generated/` are generated files

The gallery and file inventory should derive from the workspace storage tree, not from a separate persistence ceremony.

The backend may still maintain metadata and indexes, but those are derived system layers, not the authoritative existence check.

### Stable file identity

The filesystem is the source of truth for file bytes.

However, application references and memory references need a stable file identity that survives ordinary path changes.

For that reason, every file that enters workspace inventory should receive a stable `file_id`.

That `file_id` should remain the canonical reference target even if the file is:

- renamed
- moved inside the workspace
- re-indexed
- restored from backup

The inventory layer should therefore maintain at least:

- `file_id`
- current workspace-relative path
- content hash when available
- file role such as uploaded or generated
- timestamps

Rules:

- references from apps and notes should prefer `file_id`
- paths remain useful for navigation and debugging
- overwrite semantics must produce either an explicit version update or a new `file_id`, but never a silent identity collision

### Required behavior

If an agent writes:

```text
/workspaces/acme/storage/generated/report.md
```

then:

- the file exists immediately as a workspace artifact
- the gallery sees it as a generated asset
- preview/index metadata may be created asynchronously
- no extra manual persistence dance is required

## Workspace Memory Model

Memory is an app.

It is not a core-owned domain and it does not live in a special top-level `memory/` directory.

The memory app owns its data under:

```text
/workspaces/<workspace_id>/data/memory/
```

Everything related to memory must be modeled as app-owned workspace data.

This includes:

- note records
- link records
- file references
- app-owned indices
- app-owned retrieval caches
- exports and snapshots produced by the memory app

### Memory isolation

Memory remains tenant-confined because the memory app belongs to one workspace.

An agent operating in workspace `acme` must not be able to read workspace `globex` memory unless a deliberate cross-workspace sharing feature exists.

No silent cross-tenant fallback should exist.

### Memory domain model

For the current Maverick target, the memory app should model:

- notes
- links between notes
- references from notes to workspace files

This is enough to support the desired use case:

- company X
- known at event Y
- linked to contract Z
- linked to email thread A

without forcing a rigid global schema for every memory item.

### Memory storage rule

The memory app chooses its own internal storage model inside `data/memory/`.

Recommended shape:

- embedded database for notes and links
- optional markdown inside note bodies for readability
- file references to workspace storage by stable `file_id`

The important architectural rule is not "memory must use the core database".

The important rule is:

- memory is app-owned
- memory data lives under `data/memory/`
- the memory app can use an embedded database or another app-local storage model

### Notes

Each note should use a small common structure plus a flexible payload.

Recommended base fields:

- `id`
- `title`
- `note_type`
- `summary`
- `body_markdown`
- `payload`
- `tags`
- `source_refs`
- `file_refs`
- `entity_keys`
- `created_at`
- `updated_at`

### Links between notes

Links between notes should be first-class records, not implicit text-only references.

Recommended base fields:

- `id`
- `from_note_id`
- `to_note_id`
- `relation_type`
- `status`
- `confidence`
- `reason`
- `evidence_refs`
- `created_at`
- `updated_at`

### Memory file references

Notes should reference workspace files by stable `file_id`, with path retained only as a secondary navigation aid.

The note can store:

- file id
- current workspace-relative path
- reference role such as `attachment`, `source`, `evidence`, or `output`

### Access pattern

Memory retrieval should prefer:

1. direct lookup by note id or entity key
2. linked note traversal
3. linked file fetch
4. search expansion only when direct graph traversal is insufficient

## Database Model

### Recommended default

Use one platform database with strict workspace scoping, not one database per workspace.

This is the recommended default architecture for Maverick.

Why:

- simpler operations
- simpler migrations
- lower infrastructure cost
- easier analytics and admin workflows
- easier tenant provisioning

This recommendation applies to the platform database, not to app-owned embedded databases inside workspaces.

### Required database rule

All workspace-owned records must carry `workspace_id`.

This includes:

- file index records
- app records
- operating records
- task/checklist state
- agent instances
- event log entries
- retrieval metadata

The global database still needs a separate control-plane area for:

- accounts
- auth
- workspace memberships
- billing
- platform admin state

### Future exception

Per-workspace databases should be an optional enterprise-grade deployment mode, not the default architecture.

Use that only when required by:

- regulatory isolation
- customer-managed infrastructure
- data residency requirements
- very large dedicated tenants

## Provisioning Model

When Maverick is installed on a machine:

1. create installation-level `apps/`
2. create installation-level `core/`
3. create installation-level `workspaces/`
4. create default workspace at `workspaces/default/`
5. register the default workspace in the control plane

When a new tenant workspace is created:

1. create `/workspaces/<workspace_id>/`
2. create standard subdirectories
3. attach users and memberships
4. ensure runtime and MCP flows resolve that workspace as authoritative

## Security and Isolation Invariants

The platform should enforce all of the following:

1. A sandboxed workspace agent cannot write outside its workspace root.
2. A sandboxed workspace agent cannot directly write to installation-level `core/`.
3. A sandboxed workspace agent cannot directly write to installation-level `apps/`.
4. A sandboxed workspace agent cannot directly access another workspace root.
5. Workspace files, memory, and retrieval artifacts remain scoped to the same `workspace_id`.
6. Gallery, file APIs, and retrieval must never return artifacts from another workspace.
7. Child agents inherit the same workspace root unless an explicit trusted control-plane action says otherwise.
8. Cross-workspace operations happen only through explicit product features, never by path traversal or raw runtime access.

## Why the Current Model Feels Wrong

The current system remains too fragmented:

- runtime workdir and file storage are separate concepts
- generated files need special persistence paths
- gallery visibility depends on backend records more than on actual file placement
- the sandbox perimeter does not match the natural workspace perimeter

This creates operator confusion and agent confusion.

The architecture described here removes that mismatch.

## Migration Direction

The migration should move toward these concrete changes:

1. Introduce top-level `workspaces/` as a first-class install path.
2. Create a canonical helper module for workspace root path resolution.
3. Change sandbox writable roots from `workdir-only` to `workspace-root`.
4. Move uploaded and generated files under `workspaces/<workspace_id>/storage/...`.
5. Make gallery and file inventory read from workspace storage as the source of truth.
6. Treat DB metadata as an index over workspace files rather than the sole persistence mechanism.
7. Move workspace-local memory data under `workspaces/<workspace_id>/data/memory/...`.
8. Keep installation-level `core/` and `apps/` writable only to trusted full-access platform runtimes, never to sandboxed tenant agents.

## Non-Goals

This document does not require:

- one VM per workspace
- one database per workspace
- one Git repository per workspace

Those can remain optional deployment choices.

The key requirement is that the workspace root is the canonical isolated operating environment for the sandboxed agent.

## Decision Summary

The target Maverick architecture should be:

- top-level `workspaces/` directory alongside `core/` and `apps/`
- one canonical filesystem root per workspace
- sandbox write scope equals workspace root
- gallery derives automatically from `storage/uploaded/` and `storage/generated/`
- workspace-local memory remains inside the workspace boundary
- global platform code is outside the workspace and accessible only through MCP/backend interfaces
- one platform database by default, with strict `workspace_id` isolation for platform-scoped tenant records

This is the model that best matches the product expectation:

each workspace is a private operating environment where the agent can work freely, but only inside that workspace.
