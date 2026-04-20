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

In workspace-facing surfaces, "installed" means the workspace has a binding to an app source and app-owned data may exist under `data/<app_id>/`. "Enabled" means that binding is actively mounted by the core. Disabled installed apps remain manageable by admins but are not shown to workspace users and are not mounted.

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

The Maverick App Store itself is also an app. Its UI, backend, CLI, MCP, skills, and workspace-owned state live under `apps/app-store` and `workspaces/<workspace_id>/data/app-store/`. It may present the remote catalog, show whether catalog apps are already installed in selected workspaces, show workspace-local app projects for the selected workspace context, open installed app frontends through generic shell navigation, and collect install, uninstall, complete workspace-local deletion, workspace assignment, and shortcut pinning choices, but it does not bypass platform boundaries: authenticated installation state reads, checksum verification, source registration, workspace-local project registration, workspace binding, workspace-local project deletion, and uninstall binding removal remain generic core app-hosting operations.

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

Workspace-facing aggregate surfaces must degrade per app when a binding points to source material that is no longer available.

For example, `/api/apps`, `/api/status`, and widget discovery must skip an unavailable enabled app and continue returning the remaining workspace capabilities. Direct mounts for that unavailable app should return an app-unavailable response instead of leaking a filesystem exception or failing the whole shell.

Complete deletion is intentionally narrower than uninstall.

Uninstall removes only the workspace binding and preserves app-owned data by default. Complete deletion is valid for workspace-local app projects, where the workspace owns the app source. It must remove the workspace binding if present, delete `workspaces/<workspace_id>/data/<app_id>/`, delete the project directory under `workspaces/<workspace_id>/apps/<app_id>/`, and remove the workspace-local project record so the app no longer appears in the workspace-local catalog. Platform store apps and remote catalog entries are not deleted through a workspace-local delete action because their source is installation-level or external catalog state rather than workspace-owned material.

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

Installation-level built-in app discovery should be contract-driven.

The platform may scan the installation-level `/apps` directory for app roots that contain a valid `app_contract.json`. This keeps first-boot app registration independent from hardcoded app id lists while still requiring every executable app to pass the same contract validation.

Discovering an app contract does not make the app's business data part of the core. It only makes the app source eligible for registration, installation, and workspace binding through generic app-hosting flows.

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
- views
- embeddable widgets
- import/export hooks
- health or maintenance hooks

This declaration allows the platform to:

- render app UI correctly
- call app tools safely
- understand which app owns which kind of content
- understand which surface should be used for a given operation

### Visibility Declaration

App visibility is a platform policy hint declared in the app contract and enforced by the core host.

The canonical optional shape is:

```json
"visibility": {
  "platform_roles": ["admin"]
}
```

Rules:

- omitted `visibility` or `platform_roles: null` means the app is visible to every authenticated workspace member
- `platform_roles` is a list of global platform roles, initially `admin` or `member`
- visibility affects app registry responses and mounted frontend/backend access
- visibility does not move business logic into the core
- visibility must not be implemented as app-specific conditionals such as `if app_id == "user-admin"`

An admin tool app can therefore be a normal sealed app under `/apps/<app_id>/` while user records, platform roles, sessions, memberships, and workspace governance remain core-owned control-plane state.

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

For sealed built-in apps, the repository may keep both the app source needed to rebuild the artifact and the generated `frontend/dist` artifact used by the hosted core.

The generated artifact is part of the app store payload, not part of the core package.

The build source remains app-owned and must not introduce framework-specific assumptions into the core host.

The v2 `base_shell` UI/UX is the visual and interaction reference for the v3 `base-shell`.

The port should preserve the shell experience, layout behavior, sidebar composition, workspace/app panels, and responsive behavior where those concepts are still valid.

The v3 `base-shell` intentionally does not include a topbar. Provider, runtime, workspace, and status metadata must be exposed through generic settings or app-owned surfaces instead of leaving a hidden topbar component behind.

The port must not preserve v2 runtime coupling, v2 API assumptions, v2 auth assumptions, or v2 manifest format.

The v3 shell attaches only to v3 platform protocols such as:

- `/api/session`, `/api/auth/login`, and `/api/auth/logout` for session state
- `/api/workspaces` and `/api/workspaces/active` for workspace selection
- `/api/apps` for enabled app registry data
- `/api/status` for platform status
- `/api/providers/active` and `/api/runtime/status` for runtime provider indicators
- `/api/settings/platform` for generic settings metadata
- `/api/recovery/status` and related recovery routes for operator status where appropriate
- mounted app frontend routes under `/apps/<app_id>/`
- mounted app backend routes under `/api/apps/<app_id>/...`

The shell must derive app navigation from registry records such as `app_id`, `name`, `description`, `views`, `frontend_mount`, `backend_mount`, and optional icon or logo metadata.

The `base-shell` port may retain shell-owned local preferences in the browser, such as the last active app and sidebar state.

Those preferences are shell UI state only. They are not core workspace records, app installation state, provider configuration, or app-owned backend data.

Pinned app shortcuts are not shell-owned browser preferences. They are App Store app data, exposed through an App Store-owned sidebar widget that `base-shell` mounts through the generic widget registry.

Mounted app frontends should be treated as stable app documents after first open.

The shell should not force internal app navigation by mutating iframe `src` with app-owned query parameters.

Instead, host apps should keep the iframe mounted and send a generic browser message:

```json
{
  "type": "maverick.app.navigate",
  "app_id": "chat",
  "params": {
    "thread_id": "thread_123"
  }
}
```

Rules:

- `type` identifies the generic host-to-app lifecycle message
- `app_id` must match the target mounted app
- `params` contains only explicit scalar navigation data

Mounted app frontends should acknowledge readiness with the matching app-owned lifecycle message:

```json
{
  "type": "maverick.app.ready",
  "app_id": "chat"
}
```

The host should resend the latest pending navigation params for that app when it receives `maverick.app.ready`.

This avoids losing navigation requests when an app iframe is freshly mounted after login, logout, refresh, or recovery and the host message arrives before the app has installed its listener.
- the host may know the target `app_id`, but must not know app-private storage or route internals
- the receiving app owns interpretation of `params`
- the receiving app must ignore messages from unexpected origins

The initial iframe URL remains the registry-provided `frontend_mount`.

This avoids unnecessary reloads, keeps app state alive, and preserves a clean core/app boundary.

V2 shell panels that configured users, retrieval, notifications, backend restarts, or chat internals should not be copied into `base-shell`.

When capabilities become available in v3, they should be exposed through their own app contracts or generic core surfaces, then discovered or mounted by `base-shell` through the same registry-driven mechanism.

The initial v3 shell may include login, workspace selection, provider/runtime indicators, and generic settings only because those are backed by generic core APIs rather than shell-private backend assumptions.

Chat projects and project action buttons must not be implemented in `base-shell`; they belong to the chat app.

It must not create fake installed state for product apps that are not present in the registry.

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

## Embeddable Widget Surfaces

Some apps may expose small visual surfaces intended to be embedded inside another app's UI.

The first known case is chat structured content:

- the runtime emits or stores a structured message payload
- the payload has a stable `kind`
- an installed app declares that it can render that `kind`
- the chat app renders the matching app-owned widget surface

This is an app surface model, not app-to-app communication.

The embedding app does not import source code from the widget owner.

The embedded widget does not call private APIs of the embedding app.

The core remains responsible for:

- validating the widget declaration in the app contract
- publishing enabled widget metadata through the app registry
- mounting or routing the widget surface according to workspace enablement
- enforcing auth, workspace context, and install state before a widget can load

Host apps may forward generic app data invalidation messages to widgets when the invalidation belongs to the widget owner.

For example, if the chat app creates a thread in its own backend, it may emit `maverick.app.data-changed` with `owner_app_id: "chat"` and `resource: "threads"`.

A shell-hosted chat sidebar widget may receive that as `maverick.widget.data-changed` and refresh through the chat app's own backend.

This is not direct app-to-app communication: the shell only relays a generic invalidation event and does not read or write app data.

The app that owns the widget remains responsible for:

- rendering the widget frontend
- interpreting the structured payload it supports
- calling its own backend, MCP, or CLI surfaces for widget actions
- storing widget-owned state under `data/<widget_app_id>/`

The embedding app remains responsible for:

- deciding where the widget appears in its own UI
- passing the structured payload and host context to the widget
- providing a safe fallback if no matching widget exists
- avoiding direct imports from the widget app

For chat, this means the v2 model based on compile-time imports such as:

```text
../../*/chat/*widget.tsx
```

must not be preserved in v3.

That pattern makes the chat app aware of other apps' source trees and breaks the standalone app boundary.

The v3 model should be registry-driven.

An app contract may declare widgets with a structure like:

```json
"widgets": [
  {
    "widget_id": "design-checklist",
    "host": "chat",
    "content_kinds": ["checklist.design"],
    "frontend": {
      "kind": "iframe",
      "mount": "frontend/dist/widgets/design-checklist",
      "spa_fallback": true
    },
    "actions": {
      "backend": true,
      "mcp": false,
      "cli": false
    }
  }
]
```

The exact schema can evolve, but the stable concepts are:

- `widget_id` identifies the widget inside its owning app
- `host` identifies the host UI family it is designed for, such as `chat`
- `content_kinds` declares which structured payload kinds it can render
- `frontend` declares how the core can mount it
- `actions` declares which official surfaces the widget may use for mutations

Initial contract validation rules:

- `widget_id` must be unique within the owning app contract
- `widget_id` must be a stable slug and must not contain path traversal
- `host` must be a stable slug such as `chat`
- every `content_kind` must be a non-empty dotted string such as `checklist.design`
- `frontend.kind` initially supports only `iframe`
- `frontend.mount` must be a relative path under the app source root and should normally point under `frontend/dist`
- `frontend.spa_fallback` controls whether missing widget frontend paths fall back to the widget `index.html`
- `actions.backend`, `actions.mcp`, and `actions.cli` may only be true when the owning app declares the corresponding surface
- widget declarations must not name files, routes, or storage locations owned by the embedding app
- widget declarations are ignored unless the owning app is installed and enabled in the current workspace

If multiple installed apps declare widgets for the same `host` and `content_kind`, the host must use deterministic registry ordering or a workspace preference.

The default fallback must always exist.

For chat, the fallback is a generic structured message card that shows the payload in a readable form.

### Widget Runtime Contract

An embedded widget should receive only explicit host context.

Recommended initial context:

```json
{
  "workspace_id": "acme",
  "host_app_id": "chat",
  "owner_app_id": "checklists",
  "widget_id": "design-checklist",
  "message_id": "msg_123",
  "content": {
    "kind": "checklist.design",
    "payload": {}
  }
}
```

For iframe-based widgets, the context may be passed by:

- signed context token returned by the core widget context endpoint
- initial `postMessage`
- backend bootstrap endpoint scoped to the mounted widget

The widget must not receive broad app registry data unless it needs it and the core explicitly exposes it.

The initial v3 core implementation uses:

- `GET /api/apps/widgets?host=<host>&content_kind=<kind>` for workspace-scoped widget discovery
- `GET /api/apps/widgets/<owner_app_id>/<widget_id>/frontend/...` for controlled iframe frontend mounting
- `POST /api/apps/widgets/context` to create a signed context token after validating workspace, host, widget owner, widget id, and content kind
- `GET /api/apps/widgets/context/<token>` to read the explicit context from the widget iframe without exposing source paths or registry internals

Widget actions should go to the widget owner's own backend or tool surface.

For example, a checklist widget embedded in chat should persist checklist edits through the `checklists` app, not through the `chat` app.

This preserves app ownership:

- chat owns the message container
- checklists owns checklist data and checklist widget behavior
- core owns registry, routing, auth, and workspace context

### Widget Core Implementation Plan

The core implementation should be generic and not reference `chat`, `checklists`, or any specific widget owner.

Required core pieces:

- extend app contract models with `WidgetDeclaration`, `WidgetFrontendDeclaration`, and `WidgetActionDeclaration`
- extend the contract parser, serializer, and validator to round-trip and reject invalid widget declarations
- expose widget declarations through app source records and parsed workspace app surfaces
- add a workspace-scoped widget registry service that indexes only enabled app bindings
- add collision and ordering rules for same `host` and `content_kind`
- add `GET /api/apps/widgets?host=<host>&content_kind=<kind>` for registry discovery
- add a widget frontend mount route that serves the owning app's declared widget mount, not the embedding app's source
- add a widget bootstrap/context route or signed context token so iframe widgets receive only explicit host context
- enforce auth, active workspace, app installation state, and app enabled state on all widget routes
- include widget metadata in app registry responses only where useful and without leaking unrelated app internals
- add observability events for widget registry lookup, widget mount success, and policy denial

Required tests:

- contract parser accepts a valid widget declaration
- contract parser rejects duplicate widget ids
- contract parser rejects path traversal in widget mounts
- registry lists only widgets from enabled apps in the active workspace
- registry filters by `host` and `content_kind`
- disabled/uninstalled apps do not expose widgets
- widget mount serves the owner app's frontend artifact
- host apps cannot import or resolve widget owner source paths through the registry payload
- policy denial returns a clear error for unavailable widgets

Required chat-side work after the core is ready:

- remove the v2 compile-time widget import model
- keep generic structured-message fallback rendering
- call the widget registry by `host=chat` and message `content.kind`
- embed compatible widgets through iframe-mounted widget routes
- pass only explicit widget context, never app source paths
- route widget actions to the widget owner's official surfaces

The chat app must treat widget hosting as a generic host responsibility.

It must not maintain a built-in list of widget owners or known structured content kinds.
For every structured message, chat resolves widgets by `host=chat` and the message's `content.kind`, selects the deterministic first registry match, creates an explicit widget context token, and mounts the owner app's declared iframe route.

If no enabled app declares a compatible widget, chat renders the same generic structured-content fallback card for every kind.

Agents are not required to emit widget JSON for common file preview flows.

When an agent answer contains a normal Markdown link, URL, or plain text reference to workspace storage under `storage/generated/` or `storage/uploaded/`, the chat transcript layer may synthesize an internal structured content item with `kind: "workspace.file.preview"` and a payload containing the normalized `workspace_relative_path`.

That synthesized item follows the same widget registry path as any other structured message:

- chat asks the core for `host=chat` and `content_kind=workspace.file.preview`
- the enabled widget owner renders the preview
- the original agent text remains ordinary Markdown
- local filesystem paths are not exposed to iframe widgets

The same widget mechanism is also the correct way for `base-shell` to host chat-owned navigation.

The shell must not import chat sidebar components or own chat projects.

Instead:

- `base-shell` renders a generic sidebar widget slot
- the slot discovers widgets with `host=base-shell` and a shell sidebar content kind
- `chat` declares a widget such as `chat-sidebar`
- the widget frontend is served from the chat app's own `frontend/dist/widgets/chat-sidebar`
- project, thread, rename, move, and creation actions go through the chat app backend
- project and thread settings panels are rendered by the chat widget, not by the shell
- optional shell navigation uses browser messaging from the iframe to ask the host to open the `chat` app with explicit scalar params such as a thread id or a new-chat request
- the shell forwards those scalar params to the mounted chat app through `maverick.app.navigate` without reloading the chat iframe
- shell-hosted widget slots must include the active workspace id in the signed widget context and remount the widget iframe when the active workspace changes
- a widget must never keep showing app-owned data loaded under a previous workspace after the host has switched workspace context
- host apps should hide iframe widget slots without unmounting them when a temporary shell panel closes, unless a widget explicitly asks to be reset

This preserves the v2 visual layout while moving ownership to the v3 app boundary:

- shell layout and app mounting belong to `base-shell`
- chat projects and chat list state belong to `chat`
- widget discovery, auth, workspace context, and controlled frontend mount belong to the core

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
  "widgets": [
    {
      "widget_id": "reservation-summary",
      "host": "chat",
      "content_kinds": ["restaurant.reservation_summary"],
      "frontend": {
        "kind": "iframe",
        "mount": "frontend/dist/widgets/reservation-summary"
      },
      "actions": {
        "backend": true,
        "mcp": false,
        "cli": false
      }
    }
  ],
  "entrypoints": {
    "frontend": "frontend/dist",
    "backend": "backend/app_backend.py",
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
