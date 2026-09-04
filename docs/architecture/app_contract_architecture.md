# App Contract Architecture

Date: 2026-04-17

## Purpose

Define the standard contract that every Maverick app must follow.

This contract does not impose the internal data model of an app.

The official App SDK is documented separately in `docs/architecture/app_sdk_architecture.md`.
The SDK may generate and validate app contracts, but `app_contract.json` remains the source of truth and the core contract parser remains the enforcement point.

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

Frontend rebuildability is derived from the frontend entrypoint and source tree, not a lifecycle flag.
Apps with a declared frontend must provide a real source build that can regenerate the declared frontend artifact.
Apps without a frontend do not expose the frontend rebuild operation.

## Contract Versus Installation State

The app contract is not the same thing as app installation state.

Maverick should distinguish clearly between:

- app source or project material
- app distribution artifact
- app contract metadata
- app installation state in the core
- app enablement state inside one workspace

Examples:

- a server-installed app store artifact may carry valid contract metadata before it is enabled in any workspace
- a workspace-local app project may exist under `workspaces/<workspace_id>/apps/` before it becomes an active capability
- an app may be installed but not enabled in a given workspace

In workspace-facing surfaces, "installed" means the workspace has a binding to an app source and app-owned data may exist under `data/<local_app_id>/`. "Enabled" means that binding is actively mounted by the core. Disabled installed apps remain manageable by admins but are not shown to workspace users and are not mounted.

The contract describes what the app is and how it behaves.

The core installation system decides where that app is known, installed, enabled, disabled, upgraded, uninstalled, or reattached.

## User-Facing App Routes

Mounted app frontends have a canonical user-facing shell route:

```text
/app/<local_app_id>/<app_page>
```

This route belongs to the base shell and is served by the configured root shell app. It selects an enabled workspace app binding by its local app id and forwards the optional app-owned page segment to the mounted iframe as `params.app_page` in the `maverick.app.navigate` message.

The frontend mount namespace remains:

```text
/apps/<mount_app_id>/
```

Core uses that namespace as the upstream route behind an authenticated isolated
app-frame proxy. Direct non-shell HTML/SPA documents at the platform origin are
rejected; the only callback exception is a Core-owned no-store OAuth relay that
immediately bootstraps the isolated callback document. App and widget documents
are otherwise available only after a one-shot launch ticket establishes the
per-app, per-login-session isolated origin. Public immutable/static
subresources remain available at the platform namespace, but
are sandboxed and `nosniff` when interpreted as documents. The namespace is not
the canonical browser URL for workspace navigation.

The public app id declared by the app artifact and the local app id used for one workspace binding are separate identities:

- `public_app_id` is the catalog or source identity declared by the app contract and used for distribution, upgrade lineage, compatibility, and publisher ownership.
- `local_app_id` is the workspace binding and app-owned data namespace chosen for one installation of that app in a workspace.
- `mount_app_id` is the concrete HTTP/widget route namespace exposed by the core host, normally equal to `local_app_id`.

For built-in apps these values may be equal, but the architecture must not rely on that. A workspace may install two compatible forks or versions of the same public app under different local ids, and app contracts must not hardcode the local id they will be mounted under.

Apps own the structure and meaning of `<app_page>`. The platform must not hardcode every app's internal route tree. An app that exposes deep links should translate its own page segments, such as `threads/<thread_id>` or `runtime-sessions/<runtime_session_id>`, into its internal state after receiving `maverick.app.navigate`.

## Shell Theme Protocol

The root shell owns the user's shell theme preference, and mounted app iframes remain responsible for rendering their own dark and light tokens.

For every mounted app iframe and shell-hosted widget iframe, the shell must
include these URL parameters in the isolated launch path before the frontend
bundle executes:

- `maverick_theme`: the effective visual theme, `dark` or `light`
- `maverick_theme_mode`: the user's preference, `dark`, `light`, or `system`
- `maverick_color_scheme`: the CSS color scheme to apply, `dark` or `light`

App and widget frontends that support shell theming should run a tiny pre-paint bootstrap in their HTML entrypoint. That bootstrap reads the URL parameters, sets `data-maverick-theme`, `data-theme`, and `colorScheme` on the document root, and then lets the normal frontend code attach listeners. This prevents persisted or shell-provided light mode from flashing through the default dark CSS before module execution.

The shell also posts live theme updates without remounting iframe documents:

```json
{
  "type": "maverick.shell.theme-changed",
  "theme": {
    "mode": "system",
    "effective": "light",
    "color_scheme": "light"
  }
}
```

Mounted apps may also receive the same `theme` object on `maverick.app.navigate`. Widgets may receive it in `context.content.shell_theme` on `maverick.widget.context-changed`.
Apps and widgets must ignore `theme` fields on unrelated messages so app-owned
UI state messages cannot accidentally change document theme. Shell-to-frame
messages are accepted only through the exact-parent relay bound to the platform
origin; the relay re-emits them inside the app's isolated origin for existing
app listeners.

## App Distribution Sources

Maverick supports two canonical app source locations:

- installation-level app artifacts under `/apps`
- workspace-local app projects under `workspaces/<workspace_id>/apps`

The installation-level `/apps` directory is the server's app store, trusted bundle cache, and platform-installed app area.

It may contain:

- built-in platform apps such as `base-shell` and `chat`
- closed commercial apps distributed as sealed artifacts
- open-source or source-available apps distributed through the server app store
- versioned app bundles validated by the core

The Maverick App Store itself is also an app. Its UI, backend, CLI, MCP, skills, and workspace-owned state live under `apps/app-store` and `workspaces/<workspace_id>/data/app-store/`. It may present the remote catalog only through core-owned App Store APIs such as `/api/app-store/apps`; the app backend must not fetch the public catalog or submission transport directly. It may show installation-level server app sources that are not necessarily installed in the active workspace, show whether catalog apps are already installed in selected workspaces, show workspace-local app projects for the selected workspace context, open installed app frontends through generic shell navigation, and collect install, uninstall, complete workspace-local deletion, workspace assignment, and shortcut pinning choices, but it does not bypass platform boundaries: remote catalog retrieval, public submission transport, authenticated server source reads, authenticated installation state reads, checksum verification, source registration, workspace-local project registration, workspace binding, workspace-local project deletion, and uninstall binding removal remain generic core app-hosting operations.

The App Store's app shortcut sidebar may list every visible workspace app in its "all apps" scope, including apps without a workspace frontend and apps whose frontend role is only supporting. Only launchable workspace frontends may be opened or pinned from that sidebar. Non-launchable apps are shown as app records, not shortcuts: they must not expose pin controls or send shell open requests.

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

CLI and MCP registry discovery, app-scoped CLI/MCP discovery, and periodic or recovery background-hook dispatch are aggregate surfaces under the same rule. A missing or invalid app surface must be excluded before command/tool registration or hook invocation, without blocking core surfaces or healthy apps in the workspace.

Hosted app isolation must treat unexpected app-hosting faults the same way operationally. If one app surface raises an unclassified exception during contract resolution, registry serialization, or frontend serving, the core must log it, exclude only that app from aggregate workspace surfaces, and keep the rest of the shell responsive. A direct shell mount failure for the configured root shell should degrade to `503 shell_unavailable`; a direct mount for any other app should degrade to `404 app_unavailable`. An unexpected exception must not bubble out of the hosted platform request path and take down the backend process.

Built-in app bootstrap follows the same workspace-local isolation rule for declared compatibility. When a built-in app contract supports only a subset of workspace execution modes, the core must register the installation-level source but skip that app only for incompatible workspace bindings. A full-access workspace may still host sandbox-compatible apps; `full-access` in `compatibility.workspace_modes` is reserved for apps that require host/operator access and makes those apps ineligible for sandbox workspaces. A full-access-only operator app must not prevent sandbox workspaces from bootstrapping compatible shell and workspace apps.

Built-in app bootstrap must also be idempotent. When a workspace already has an enabled binding for the same built-in source id, source kind, app version, and local id, bootstrap must not rerun install or health hooks. It should only repair missing platform-owned installation metadata such as the app data root marker. Install and health hooks run when a binding is missing, incompatible, stale, or being intentionally reinstalled/upgraded through an app-hosting operation.

Complete deletion is intentionally narrower than uninstall.

Uninstall removes only the workspace binding and preserves app-owned data by default. Complete deletion is valid for workspace-local app projects, where the workspace owns the app source. It must remove the workspace binding if present, delete `workspaces/<workspace_id>/data/<app_id>/`, delete the project directory under `workspaces/<workspace_id>/apps/<app_id>/`, and remove the workspace-local project record so the app no longer appears in the workspace-local catalog. Platform store apps and remote catalog entries are not deleted through a workspace-local delete action because their source is installation-level or external catalog state rather than workspace-owned material.

Workspace-local discovery must be diagnosable. When the core scans `workspaces/<workspace_id>/apps/<app_id>/` and finds an `app_contract.json` that fails contract validation, the project must be reported to App Store management surfaces as an invalid local project with the validation error. Invalid projects must not silently disappear from the local app list because workspace-only agents need the parser error in order to repair the app contract.

The core exposes a generic workspace-local registration surface for app projects born inside a workspace:

```text
POST /api/app-store/register-local
```

The request identifies an `app_id` and one owning workspace. The core resolves the project root as `workspaces/<workspace_id>/apps/<app_id>`, validates the canonical `app_contract.json`, and persists the workspace-local project record. This is distinct from installation:

- registration makes the local project known to the app-hosting control plane
- `POST /api/app-store/install-local` creates the workspace binding and enables the app
- complete deletion removes the binding, app-owned data, project source, and project registration

Workspace members may use workspace-local registration and installation when workspace governance allows custom apps and app installation. Platform admins and workspace admins may manage local projects when app installation is allowed. Remote catalog app installation and complete deletion of workspace-local project source remain app-management operations and must not be broadened by this workspace-local policy.

## Distribution Mutability

An app contract should declare its distribution and mutability expectations.

The recommended distribution modes are:

- `sealed`
- `source_available`
- `workspace_local`

`sealed` apps are installed as non-editable artifacts.

They may expose frontend, backend, MCP, and CLI surfaces, plus bundled skill templates, but their app source is not workspace-editable.

This is the correct mode for commercial closed-source apps, signed vendor bundles, and apps distributed only as runtime artifacts.

`source_available` apps are distributed by the server app store with source material available for inspection or forking.

They can still run from the installation-level artifact while remaining centrally governed.

If a workspace needs to customize the app, the core should create a workspace-local fork under `workspaces/<workspace_id>/apps/<app_id>/`.

`workspace_local` apps originate inside a workspace and are editable workspace material.

They may later be promoted into an installation-level distribution channel, but that promotion is an explicit packaging step, not an implicit side effect of local development.

The first promotion flow is admin-only and control-plane owned:

- source project stays in `workspaces/<workspace_id>/apps/<app_id>/`
- promotion copies the full app directory into installation-level `apps/<app_id>/`
- the copied contract is rewritten for the selected installation distribution:
  - `sealed` -> `distribution.mode: sealed`, `source_access: none`
  - `forkable` -> `distribution.mode: source_available`, `source_access: forkable`
- the copied app is then registered as an installation-level `platform` source

Promotion ownership is separate from contract distribution metadata:

- the workspace-local project record persists its creator as the project owner
- the first successful promotion claims that installation-level `app_id` for that owner
- later promotions of the same `app_id` are treated as server-wide updates, not as a second independent app
- only the original promoted-app owner may publish updates for that `app_id`
- if another workspace forks and customizes the app, it must change the `app_id` before promotion so the result is a separate installation-level app
- promotion must report a clear blocked reason when an existing installation-level `app_id` belongs to a different owner

Promotion must never mutate the original workspace-local project in place.

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

## Completeness Baseline

Contract validity is necessary but not sufficient.

Every app tracked as a real Maverick product surface must also meet a repository completeness baseline:

- a `README.md` in the app root describing the app purpose, declared surfaces, storage ownership, and SDK validation flow
- at least one automated contract smoke check in the repository test suite
- truthful `capabilities.skills` entries that match bundled skill template ids under `skills/` when `entrypoints.skills_root` is declared
- documentation of intentional omissions when an app does not expose a backend, hooks, reference entities, data events, or persisted view surfaces

This baseline keeps `app_contract.json`, the SDK, and human-facing documentation aligned.

Host or control-plane-adjacent apps may intentionally expose fewer app-owned surfaces than stateful workspace apps, but the omission must be documented explicitly in the app README rather than left implicit.

The SDK validation flow enforces the machine-checkable part of this baseline for source trees it creates, registers, installs, or packages. In addition to parsing the contract shape, SDK validation rejects app sources where declared CLI, MCP, frontend view, skills, reference-entity, view-state, or data-event capabilities do not line up with the corresponding entrypoints and standard contract conventions. Repository tests still cover the human-facing baseline items that cannot be inferred from the contract alone, such as README explanation quality and first-party smoke-test coverage.

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

The contract parser is strict for the declared contract version. Unknown root fields and unknown fields inside modeled sections such as `capabilities`, `entrypoints`, `storage`, `permissions`, lifecycle metadata, health metadata, rollback metadata, and widget declarations are validation errors rather than ignored extensions. Future extensions must be added to the versioned schema intentionally so app authors cannot declare apparently enforceable fields that the core silently drops during normalization.

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

Every app artifact must declare at least:

- `app_id`
- `name`
- `version`
- `description`
- `publisher`
- `provides`
- `requires`
- `capabilities`

In the public contract file, `app_id` is the artifact's public app id. The normalized contract snapshot may also expose this as `public_app_id` to avoid confusing it with workspace-local binding ids.

Workspace installation records must carry the local identities separately:

- `public_app_id` from the source contract
- `local_app_id` for the workspace binding and app-owned data namespace
- `mount_app_id` for mounted HTTP, WebSocket, and widget route namespaces when it differs from `local_app_id`. CLI command ids and MCP tool ids use `local_app_id`; entrypoint payloads also receive `public_app_id`.
- source or binding metadata that links the local install to the installation-level artifact, workspace-local project, fork, or external bundle

This identity separation is required for:

- install flows
- update flows
- UI listing
- audit
- compatibility checks
- workspace governance
- multiple local installations or forks of the same public app

The canonical public format for contract `app_id` and for local binding ids is lowercase kebab-case.

Examples:

- `restaurant-manager`
- `table-ops`
- `memory`

Do not use underscores or mixed-case forms in the public contract file.

When docs or examples use `data/<app_id>/` in a workspace context, `app_id` means the local workspace app id unless the text explicitly says `public_app_id`.

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
  "platform_roles": ["admin"],
  "workspace_roles": ["admin"],
  "capabilities": ["manage_runtime_sessions"]
}
```

Rules:

- omitted `visibility`, or visibility with no role or capability restrictions, means the app is visible to every authenticated workspace member
- `platform_roles` is a list of global platform roles, initially `admin` or `member`, and is reserved for platform-wide authority
- `workspace_roles` is a list of active workspace membership roles, initially `admin` or `member`, and is the normal way to expose workspace-admin surfaces to a user who is not a platform admin
- `capabilities` is a list of named workspace or platform capabilities enforced by the core visibility policy; unsupported capability names fail closed for non-platform callers
- visibility affects app registry responses, mounted frontend/backend access, widgets, CLI discovery/invocation, MCP discovery/invocation, and compact app discovery
- visibility also affects user-facing App Store catalog, installed-app, and workspace-local app listings
- visibility does not move business logic into the core
- visibility must not be implemented as app-specific conditionals such as `if app_id == "internal-admin-tool"`

App Store management views may show restricted apps to users who can manage apps for the relevant workspace, such as platform admins or workspace admins.

Users without app-management authority should see only apps they can actually mount or use. Workspace-local projects that are not installed are management material and should not be listed to ordinary members.

An admin tool app can therefore be a normal sealed app under installation-level `/apps/<public_app_id>/` while user records, platform roles, sessions, memberships, and workspace governance remain core-owned control-plane state.

### Presentation Declaration

App presentation is contract metadata that tells shell-facing surfaces whether a frontend is a user-openable workspace app or only a supporting asset surface.

Canonical shape:

```json
"presentation": {
  "frontend_role": "workspace"
}
```

Allowed `frontend_role` values:

- `workspace`: the app declares `entrypoints.frontend` and exposes a meaningful user-facing workspace app view. Shell app navigation, App Store open actions, and pinned shortcuts may target it.
- `supporting`: the app declares `entrypoints.frontend`, but the frontend is a supporting platform or plugin surface rather than a primary workspace app view. The core may still serve its assets, but shell navigation and pinning must not treat it as launchable.
- `none`: the app has no frontend entrypoint.

Rules:

- `workspace` and `supporting` require `entrypoints.frontend`
- an app with `entrypoints.frontend` must use either `workspace` or `supporting`
- App Store catalog and installed-app payloads expose both the declared role and a derived `frontend_launchable` boolean
- Remote catalog entries are normalized by the core before they reach the App Store UI so `presentation`, `frontend_role`, `frontend_launchable`, and `surfaces` have the same meaning as server, local, and installation payloads.
- user-facing grouping and icon styling must be derived from the contract role, not from hardcoded app ids
- direct `/apps/<mount_app_id>/` asset serving remains available for declared frontends even when the role is `supporting`

The recommended mental model is:

- `mcp/` = structured tool surface
- `cli/` = command-oriented local surface
- `skills/` = procedural skill templates that a skill catalog app, canonically the built-in Skills app, can copy into workspace data

Important distinction:

- `mcp/` and `cli/` are executable capability surfaces
- `skills/` is an instructional asset layer
- `skills/` is not a runtime interface, security boundary, or governance surface by itself
- runtime agents may use only workspace-owned skill copies from the runtime session's selected `skill.catalog` provider; the canonical built-in provider stores them under `data/skills/skills/`

### Referenceable Entity Declaration

Some apps own business objects that other apps may need to reference without taking ownership of their data.

Examples:

- Storage owns uploaded files and generated artifacts.
- Chat owns projects and chat-specific UI state; core runtime owns chat thread records and transcript events.
- Agents owns agent types, agent instances, and prompt material.
- A record-centric app may own accounts, contacts, deals, activities, and relationships.
- Memory may link these records into a workspace knowledge graph.

The app contract may declare referenceable entity metadata under `capabilities`. The supported optional shape is:

```json
"capabilities": {
  "mcp_tools": [
    "records_reference_manifest",
    "records_reference_search",
    "records_reference_resolve",
    "records_reference_summarize"
  ],
  "cli_commands": [
    "records"
  ],
  "reference_entities": [
    {
      "entity_type": "contact",
      "display_name": "Contact",
      "searchable": true,
      "resolvable": true,
      "summarizable": true,
      "deep_link_supported": true,
      "cache_scope": "session"
    }
  ]
}
```

This declaration is metadata, not data access.

Rules:

- the owning app remains the source of truth for the entity
- the referencing app stores only stable references and derived context it owns
- the core must not read app-private data to resolve references
- the core must not implement app-specific reference logic
- referenceable entities must have stable `app_id`, `entity_type`, and `entity_id` identity
- safe summaries must omit private fields the owning app does not intend to expose
- authorization remains governed by the core and by the owning app surface being called
- `cache_scope` defaults to `session`; an entity provider may declare `workspace_user` only when its redaction-safe resolve/materialize result is independent of the runtime session for the same workspace user and effective authorization context
- the runtime reference cache may reuse `workspace_user` results across sessions, but it must retain workspace, user, role, effective-mode, provider-binding, entity identity, and safe version metadata in the fingerprint

Mounted app frontends should use the platform host's generic `/api/app-references/manifest`, `/api/app-references/search`, `/api/app-references/resolve`, and `/api/app-references/summarize` routes when building interactive reference pickers. The routes are app-agnostic: they discover enabled providers from `capabilities.reference_entities`, invoke the owning app's reference MCP tools, and return normalized `type: "entity"` references that can be stored or sent as runtime `app_references`.

When a mounted frontend sends runtime `app_references`, the client payload is only an identity hint. The runtime submit path must re-check the local workspace app id, entity type, and entity id against enabled visible providers, then refresh labels, summaries, and deep links by calling the owner app's reference tools. Apps should return local-route-neutral `app_page` values when possible; the core maps those pages onto the binding's `local_app_id` route namespace.

Apps that declare `permissions.runtime.create_sessions` may return Storage-backed `attachments` in generic runtime launch requests. Attachments are platform-owned runtime input, not app-private file access: each item must point to an existing workspace Storage file using `workspace_relative_path` or `relative_path` under `storage/uploaded/` or `storage/generated/`. The core rejects malformed lists, non-object items, absolute or escaping paths, paths outside Storage, excessive attachment counts, and non-numeric sizes before creating the runtime turn.

Reference lookup behavior belongs to the owning app's CLI and MCP surfaces. A common convention should be used so apps such as Memory can consume references without app-specific integrations:

```text
<app_id>_reference_manifest
<app_id>_reference_search
<app_id>_reference_resolve
<app_id>_reference_summarize
```

CLI commands should mirror the same behavior for lightweight, low-context local access:

```text
<app_id> references manifest
<app_id> references search --type <entity_type> --query "..."
<app_id> references resolve --type <entity_type> --id <entity_id>
<app_id> references summarize --type <entity_type> --id <entity_id> --purpose memory_retrieval
```

The CLI surface is useful for runtime agents because it can be faster and avoids loading large MCP tool descriptions into context. MCP remains the structured tool surface and should expose equivalent behavior when the app supports references.

Every app should expose at least a reference manifest through CLI and MCP. Apps with no referenceable entities should return an empty `entity_types` list. Search, resolve, and summarize may return a structured unsupported response when the manifest is empty. Apps with real workspace objects should implement all four reference operations.

Apps that declare `reference_entities` must expose matching CLI or MCP reference behavior through the manifest, search, resolve, and summarize convention. A record-centric app may let Memory store a durable reference to a contact or deal while the owning app remains the source of truth for the structured business record.

### Live Data Event Declaration

Apps with mutable workspace data should declare the app-owned resources that emit live UI invalidation events under `capabilities.data_events`:

```json
"capabilities": {
  "data_events": [
    {
      "resource": "records",
      "description": "Emitted when the app's business records change through official app surfaces."
    }
  ]
}
```

This declaration tells agents and host surfaces which app resources may publish the standard `maverick.app.data-changed` event. It is not a data subscription implementation by itself.

Rules:

- app data changes must go through official app backend, MCP, CLI, or lifecycle surfaces
- direct writes into `data/<app_id>` are repair operations, not normal product behavior, because they bypass live events
- write actions that mutate a declared resource may return `maverick.app.data-changed` with `resource`; the core stamps the current app as `owner_app_id`
- the core must ignore app-returned events whose type is not allowed for that surface or whose `resource` is not declared in `capabilities.data_events`
- mounted app frontends should listen on the core app-event WebSocket and refresh only the affected app/resource
- frontends must not use periodic polling as their default live-update mechanism
- app frontends that render generic runtime sessions for user-visible UI state must use the core runtime WebSocket snapshot and live frames; HTTP runtime reads are diagnostics or explicit operator refresh surfaces, not product bootstrap or realtime fallback paths
- chat-style runtime frontends must treat the core runtime thread as the user-visible conversation record and maintain a strict one-thread-per-user-visible-runtime-session invariant; they must not create app-owned placeholder conversations without a runtime session, must not expose `thread_visibility=hidden` sessions as chat conversations, and must delete conversations through the core runtime thread cleanup surface so the provider process and session root are removed with the thread
- `resource` values are lowercase slugs owned by the app contract
- apps may declare multiple resources when different UI regions can update independently

A record-centric app may declare `records` because accounts, contacts, deals, activities, relationships, and view state all affect the visible record surfaces.

### Runtime Event Hooks

Apps that create runtime sessions and need app-owned state to follow terminal runtime turns may opt in with an entrypoint hook:

```json
"entrypoints": {
  "hooks": {
    "runtime_event": "backend/app_backend.py"
  }
}
```

The core invokes this hook only for runtime sessions whose `source_app_id` matches the enabled workspace app binding. The hook receives terminal runtime events such as `runtime.turn.completed` and `runtime.turn.failed`, plus the `runtime_session_id`, `turn_id`, terminal status, final output text when available, and a redaction-safe failure reason when available. The persisted `runtime.turn.failed` event also carries the stable `failure_reason_code` and may carry a bounded `diagnostic_reference`; an exit code is never the sole public failure description. Terminal callbacks receive the persisted `runtime_event_id`; cancellation delivery is at least once, and apps must persist that id as the idempotency key before acknowledging the callback so a replay returns before external calls or app-state mutations. Direct runtime turn submissions against a source-app session and backend restart recovery both dispatch a non-terminal `runtime.turn.queued` event when the core queues a new turn, so the source app can keep its app-owned projection pointing at the active turn before a later terminal event arrives.

This hook is for app-owned projection state, not for changing the core runtime source of truth. For example, a future orchestration app can use it to mark the matching workflow node complete and perform the same downstream handoff it would perform through its own backend action, even when no frontend is open. If a loop exit has already stopped the run, the app must not queue downstream work from the terminal event.

Runtime event hooks are opt-in. The core must not call every source app backend for every turn, and apps must not read runtime persistence files directly to discover terminal status.

### App Runtime Requests

Apps that declare `permissions.runtime.create_sessions: true` may ask the platform host to create or reuse runtime sessions and submit asynchronous turns by returning a generic `runtime_session_requests` list from an app backend or hook result. The core applies these requests as platform runtime operations; it does not interpret app-owned workflow concepts such as orchestration nodes, edges, handoff text, loop goals, or queue state.

Each request may include `agent_id`, optional `runtime_session_id`, `system_prompt` or a generic dependency-backed `system_prompt_request`, `skill_ids`, `skill_activation_mode`, turn-local `invoked_skill_ids`, `input_text`, `app_references`, and a callback action. If the requesting app has a selected `runtime-skills` dependency for `skill.catalog`, the platform persists that selected provider app id on the runtime session so session allowlists and turn-local invocations resolve from the same catalog. `implicit` activation exposes the session catalog to the runtime prompt; `explicit` activation requires stable skill IDs on the turn and never accepts a client filesystem path. `app_references` is a generic union: `type: "app"` carries a stable `app_id`, while `type: "entity"` carries `app_id`, `entity_type`, `entity_id`, and optional safe label, summary, existence, and deep-link metadata. The platform stamps the created session with the requesting app as `source_app_id`, submits the turn through the core runtime, and invokes the app callback with the created `runtime_session_id` and `turn_id` or an error. The callback lets the app persist its own projection state without the core writing app-owned data. Apps may reuse only user-visible runtime sessions through `runtime_session_id`; hidden inter-agent participant sessions are operable only through the core inter-agent service.

Before reserving an app runtime stream or publishing a new agentic app session, Core resolves the workspace profile permitted for the authenticated actor, runs the central remote-agentic admission gate, and mints the immutable execution binding itself. An app may request a stable `workspace_profile_binding_id` and reasoning effort, but it cannot classify session data or supply provider authority, a capability certificate, an egress attestation, or an execution-binding snapshot. Core rechecks that the minted pin matches the exact authorized binding id and revision; any intervening governance change fails closed.

Apps may also return `runtime_turn_interrupt_requests` for turns that belong to a user-visible runtime session sourced by that same app. The core validates workspace, visibility, and source-app ownership, performs the generic interrupt operation, records the runtime terminal event, and dispatches the same source-app runtime event hook. The durable cancellation-intent CAS is the sole public ownership decision, so exactly one concurrent request reports `interrupted=true`. Terminal-outbox ownership is technical only: a worker or another caller may drain it without creating another successful interrupt result. The app still owns any product-level decision to mark its own node, job, or workflow as stopped or failed.

Apps that need to translate a long-running runtime turn into an app-owned streaming protocol require an app-agnostic durable runtime stream rather than direct access to runtime persistence. The generic boundary owns submission, a durable `stream_id`, monotonically sequenced runtime events, reads after an acknowledged sequence, inspection, recovery, and idempotent interrupt. Every operation is scoped to the current workspace and the session's `source_app_id`; the authenticated actor and ownership fields are stamped by core. App-specific route names, event schemas, correlation records, SSE encoding, and terminal packages remain in the app backend. A sidecar or browser must not receive provider credentials, core cookies, arbitrary host paths, or a reusable runtime capability through this surface.

A streamed request sets `create_stream: true` and supplies a bounded
`idempotency_key`. It may request an existing app-data-relative project
directory with `project_root: {"scope":"app_data","relative_path":"..."}`.
Core resolves that directory through a short one-shot capability bound to the
workspace, source app, and actor; the raw capability is neither persisted nor
returned to the app. Stream events expose only queued/started state, bounded
assistant text, project-relative file changes, and terminal status. Provider
payloads, chain-of-thought, prompts, host paths, credentials, and provider homes
are not part of the projection. The ASGI host asks the app backend to translate
each bounded ordered batch and advances only after an exact acknowledgement;
the WSGI path fails with `426` instead of buffering a stream.

Apps that declare `permissions.runtime.cleanup_sessions: true` may return `runtime_cleanup_requests` from a backend result. Requests may identify a `runtime_session_id`, `thread_id`, or app-owned grouping key such as `project_id`; the core resolves those identifiers inside the active workspace and performs runtime thread/session cleanup through the same platform cleanup path used by the runtime thread delete API. The contract permission only enables the app to request cleanup; it does not register that app to receive cleanup callbacks. Every existing runtime session is still authorized against the caller, workspace governance, and visibility policy with the normal runtime cleanup policy. Hidden inter-agent participant sessions are excluded from app-requested cleanup and are removed only by inter-agent close/root cleanup cascade. When an app-owned record must be removed only after cleanup succeeds, the result may include `runtime_cleanup_commit` with a backend action and payload; the host runs that commit action after all cleanup requests complete, and the commit remains responsible for mutating app-owned data and publishing declared app events.

Apps that own runtime-linked metadata opt in separately with `permissions.runtime.receive_cleanup_callbacks: true`. The core invokes each enabled opted-in app once per cleanup batch and supplies the complete deduplicated `runtime_session_ids` list, including active inter-agent child sessions expanded from selected roots. An app that only requests cleanup, such as Chat when deleting a project, must leave this receiver permission false and is not started for an empty callback.

Apps may return `dependency_backend_requests` from backend, CLI, MCP, or hook results when they need to call the backend surface of a selected provider for one declared dependency alias. Each request includes a `dependency_alias`, optional `request_id`, app-owned `body`, and optional backend `callback`. The core resolves the consumer's selected provider for that alias, verifies that the selected candidate declares the required interface with the `backend` surface, invokes the provider-owned `surface=secret_selector` preflight with no delivered secrets, resolves only the grant-authorized secret requests declared by that preflight or by an explicit `_app_secret_request`, and then calls the provider backend with `surface=dependency_backend`. Public `dependency_backend_request_results` contain only status metadata and callback status; the provider payload is delivered only to the consumer's backend callback with `surface=dependency_backend_request_callback`. This is the generic app-to-app backend surface for cases such as a processing app resolving a Storage local path through the selected `file.local.path` provider; it is not limited to runtime system prompt materialization.

This is the correct boundary for headless app-owned orchestration. For example, a future orchestration app can decide which workflow node is ready and return a runtime request for that node; the core only creates the runtime session/turn and calls that app back with the runtime identifiers. If the app later receives a terminal runtime event, the app decides whether to hand off, stop for a loop exit, or request the next runtime turn.

Backend recovery may invoke a declared app hook such as `backend_recovery` on enabled apps. A hosted backend may also invoke a declared `background_tick` hook periodically for active workspaces. These hooks follow the same rule: they may return generic runtime requests, but all app-specific recovery, scheduling, and orchestration decisions remain inside the app backend.

### View Composition Surface Declaration

Referenceable entities let apps such as Memory understand and link app-owned records. Some apps also need to render a curated set of their own records in UI after an agent or another app has selected relevant references.

This is a separate app-owned surface. The core must not decide which business records, message threads, Memory nodes, or Storage files belong in a view. The selecting agent or app composes stable references by using reference surfaces, then asks the owning app UI to render that set through a declared view composition surface.

Apps that support externally composed views may declare view surfaces under `capabilities.view_surfaces`:

```json
"capabilities": {
  "views": ["storage"],
  "reference_entities": [
    {
      "entity_type": "file",
      "display_name": "Workspace File",
      "searchable": true,
      "resolvable": true,
      "summarizable": true,
      "deep_link_supported": true
    }
  ],
  "view_surfaces": [
    {
      "view_id": "storage",
      "display_name": "Storage",
      "entity_types": ["file"],
      "state_actions": [
        {
          "action": "view_filter",
          "standard": true,
          "description": "Read the current Storage view state without scanning workspace storage."
        },
        {
          "action": "set_view_filter",
          "standard": true,
          "description": "Set keyword, role, and kind filters for the Storage view."
        },
        {
          "action": "set_custom_view",
          "standard": true,
          "description": "Show a curated set of Storage file references."
        },
        {
          "action": "clear_custom_view",
          "standard": true,
          "description": "Return Storage to normal search mode."
        },
        {
          "action": "toggle_preview_density",
          "standard": false,
          "description": "Example of an app-specific Storage view enhancement."
        }
      ],
      "supports_custom_view": true,
      "supports_filter_refinement": true
    }
  ]
}
```

Rules:

- `view_id` must identify a mounted app view declared in `capabilities.views`
- `entity_types` must reference entity types declared in `capabilities.reference_entities`
- each `state_actions` entry must declare an `action`, a boolean `standard`, and a human-readable `description`
- `standard: true` means the action follows a Maverick-wide view-composition semantic contract and agents may call it consistently across apps that declare it
- `standard: false` means the action is app-specific; agents may use it only after reading that app's declaration and should not assume other apps expose the same behavior
- the owning app stores and interprets its own view state under `data/<app_id>/`
- `set_custom_view` should accept a title plus stable references for the declared entity types
- `set_view_filter` may refine the current custom view when the app supports filter refinement
- `clear_custom_view` should return the app to its normal view mode
- the core validates only the contract shape and invokes declared app entrypoints; it does not inspect app-owned view state or app business records

The shared standard action names mirror the reference convention:

```text
view_filter
set_view_filter
set_custom_view
clear_custom_view
```

Concrete CLI and MCP command syntax may remain app-specific while `standard: true` action names and payload semantics stay common. Apps can add richer UI operations by declaring additional `standard: false` actions. Apps such as Storage and Memory implement these standard view surfaces: agents can build a custom Storage file view, record-centric view, or Memory graph view from topic search, Memory context, record references, message references, or any other app-owned evidence without the rendering app needing to know why those records were selected.

A record-centric app can declare the same standard view actions for `account`, `contact`, `deal`, and `activity` references. Its custom view payload stores typed refs such as:

```json
{
  "action": "set_custom_view",
  "title": "Acme pursuit",
  "refs": [
    {"app_id": "records", "entity_type": "account", "entity_id": "account_123"},
    {"app_id": "records", "entity_type": "deal", "entity_id": "deal_456"}
  ]
}
```

## Mounted App Model

In Maverick, everything above the core should be treated as an app.

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

- `chat` may expose a frontend for the user, a backend for app-specific server logic, MCP tools for agents, CLI commands for operators or agents, and bundled skill templates that a skill catalog app can copy into workspace data
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

Mounted app backend requests are app-domain calls, not runtime turns.

Mounted app backend entrypoints are still host-managed subprocess work. During ASGI host shutdown, the core must terminate any live mounted backend subprocess trees cooperatively so restarts do not depend on forced `systemd` kills.

The platform host may provide workspace, data-root, request, and active-provider context to the backend entrypoint, but ordinary backend polling, CRUD, settings, and widget actions must not create runtime sessions, runtime turns, or runtime events. Runtime records are reserved for explicit runtime execution through the generic runtime APIs.

Mounted backends may opt into a progressive binary response for a `POST /api/apps/<mount_app_id>/backend` call by receiving a JSON body with `response_mode: "stream"`. The core still owns authentication, workspace authorization, CSRF enforcement, request limits, app-secret delivery, entrypoint timeout, and cancellation. It invokes the backend with `stream_response_protocol: "maverick.backend.stream.v1"`; a cooperating entrypoint writes one newline-terminated JSON header containing `status_code` and `stream_response`, flushes it, and then writes raw response bytes to stdout. The platform HTTP host must forward each available following chunk without using a fill-to-size buffered read or waiting for process completion, and progressive responses must disable reverse-proxy buffering through a core-owned response header. While opening or forwarding a mounted backend stream, an HTTP client disconnect must terminate that request's entrypoint subprocess without cancelling unrelated app requests; host shutdown must still terminate the same process through the parent shutdown controller. An entrypoint that returns an ordinary JSON result remains an ordinary backend response even when the caller requested streaming.

Mounted backend secret selection supports the same bounded `_app_secret_request` object in a JSON body or as compact JSON in the `_app_secret_request` query parameter when a binary request body cannot carry app metadata. Both forms remain contract-checked and grant-checked by Core; the query form does not expose values, only logical names and whether the request is required.

Progressive response metadata is deliberately narrow. The core owns HTTP status and safety headers, permits inline media only for existing safe content types, and may expose an allowlisted generation id, PCM description, and phase timings through `X-Generation-Id`, `X-Audio-*`, and `Server-Timing`. Apps must not use the stream header to inject arbitrary browser response headers or expose provider credentials. This subprocess stream protocol is distinct from HTTP sidecar streaming: it preserves governed per-request secret delivery and is appropriate for provider pipelines such as Speech where a raw credential must remain out of the browser and sidecar environment.

For the first deployment model, the simplest canonical shape is:

- `/` for the platform host or shell entrypoint
- `/apps/<mount_app_id>/...` for mounted app frontend routes
- `/api/apps/<mount_app_id>/...` for mounted app backend routes
- `MCP` and `CLI` surfaces mounted by the core from the same app contract

The exact production routing layer may be implemented behind `nginx`, but the mount model should remain canonical at the platform level.

## App-Owned HTTP Sidecars

Some source-available apps need to run an app-owned local HTTP process while still staying behind the Maverick host boundary.

The contract may declare those processes under `services.http_sidecars`. This section is strict contract metadata, not an escape hatch to arbitrary host services. A sidecar declaration names the runtime, working directory, command, environment substitutions, loopback bind target, readiness check, workspace log files, and an optional governed proxy.

Sandbox-compatible sidecars must bind only to loopback. Apps that expose sidecar routes to a mounted frontend must provide a `proxy.route_policy`; routes are denied by default unless explicitly declared as:

- `pass_through` for bounded HTTP forwarding to the sidecar
- `handled_by_core` for routes the app protocol needs but the Maverick host must own, such as provider proxying or Storage import/export
- `blocked` for upstream features that are intentionally unavailable in sandbox mode

Rules use `path_template`, not a prefix. Literal segments match exactly and a
named segment such as `{project_id}` consumes one non-empty segment. Authorized
pass-through and handled-by-core rules must declare a method; HEAD may use a GET
rule. One named splat such as `{*project_path}` may consume one or more
canonical segments while preserving the declared literal prefix and suffix;
this supports file APIs without granting a regex or global prefix. Regex,
colon syntax, partial or repeated splats, percent encoding in templates, and
ambiguous/traversal forms are invalid. The only
tree match is `static_tree: true`, restricted to GET/HEAD roots outside `/api`
for web assets such as `/_next`. Incoming paths are canonicalized once and
encoded slash/backslash/dot traversal or double encoding fails before policy
selection. `blocked` takes precedence over `handled_by_core`, which takes
precedence over `pass_through`; every unknown method/template is denied.

An app that installs a complete official runtime may select a protected
artifact subtree with `root_filesystem`. Core assembles its verified top-level
trees as the sidecar's read-only execution root while retaining the same outer
network namespace, Unix relay, app-data mount, source read-only mount, and
resource limits. The declaration must reference an existing `artifact_mounts`
id and a canonical relative `subpath`; symlinked or escaping roots fail closed.
This capability mounts an artifact unchanged and does not permit an app overlay
or a host-root fallback.

A sidecar that needs only one product-owned subtree may narrow its writable
data capability explicitly:

```json
"data_mount": {
  "subpath": "native-product-data"
}
```

Core resolves the canonical subpath beneath the binding's app-data root and
mounts that directory, rather than the binding root, as `/data`. The same
resolved directory scopes any sidecar model-access lease. Sibling control
metadata, update journals, immutable backups, and other app-owned products are
therefore absent from both the sidecar filesystem and a delegated CLI sandbox.
Absolute, parent, symlinked, or escaping selections fail closed.

An app whose launch selection is host-owned may declare one bounded
`host_prepare` entrypoint. Core runs it only for a fresh managed launch, after
there is no live managed writer and before creating the sidecar or model-access
capabilities. The declaration allowlists exact `MAVERICK_APP_*` output keys;
the hook must return exactly those string values and cannot replace static or
Core-owned environment fields. This is a control-plane projection, not a
general secret channel: values are size-bounded, raw provider credentials are
forbidden, and only trusted app source may declare the hook. The pattern lets a
host transaction recover journals and project a digest-validated product
selection without exposing the transaction root to the product process.
Because this hook runs before sandbox preparation and process spawn, it may
make a transaction launchable but must not persist process readiness. Only
post-spawn evidence from the live manager may transition durable state to
ready.

When a narrowed sidecar also declares `diagnostics.status_file`, that path
remains relative to the binding's app-data root but does not widen `/data`.
Core creates and validates exactly that owner-only regular file, clears stale
content before launch, and bind-mounts only its inode at the fixed
`/run/maverick/sidecar-status.json` capability path. The surrounding directory,
release controls, journals, and backups remain absent. Core injects the fixed
path itself; app static environment and `host_prepare` output cannot choose a
host path. A launcher must update the bound file in place rather than replacing
the mount inode. Readers that request a bounded live handshake must tolerate
empty or incomplete reads while that in-place rewrite is in progress. This
surface is redaction-safe operational evidence, never an authorization or
release-selection input.

A sidecar with `permissions.providers.model_proxy: true` may additionally
request an optional private model transport:

```json
"model_access": {
  "api": true,
  "cli": ["codex"],
  "required": false
}
```

`model_access` is sidecar-specific and is rejected without the app-level
provider permission. `required` must be false: model access is an optional
bridge and its absence cannot prevent the native sidecar product from
starting. Core mounts one owner-only Unix socket at a fixed sandbox path and
injects a short-lived, scope-bound technical capability. API credentials are
resolved only inside Core. A requested CLI is launched by Core under a second
filesystem/process boundary over the same selected `data_mount` root. Its
working directory remains confined to that writable root. An approved native
adapter `--add-dir` may also select an existing canonical directory beneath a
read-only `artifact_mounts` namespace already declared for that sidecar. Core
resolves the host path from the lease rather than from sidecar input and mounts
only the exact requested directory read-only; undeclared namespaces, missing
paths, traversal, symlink escapes, and arbitrary host paths fail closed. Neither
transport creates a Maverick runtime
session or grants access to Maverick memory, Chat history, prompts, personas,
skills, or tools. The sidecar may receive the technical socket and capability,
but never a raw provider credential.

The CLI transport validates the complete native-adapter argv before process
creation. Provider configuration overrides are denied by default; a supported
native runtime's fixed shell-environment policy may be admitted only as exact
certified values with a closed `include_only` key list. Any changed value or
additional key fails closed. Accepting those argv values does not forward the
sidecar process environment: Core still constructs the bounded executor
environment and credential mount itself.

Every authorized model request receives a Core-owned cancellation fence. The
fence linearizes revocation against the external API submission or CLI spawn:
if revocation wins, the provider transport is never opened and the process is
never started; if submission wins, Core registers the connection or process
group for cancellation before it can remain live. Revocation then shuts down
the connection or signals the process immediately rather than waiting for a
response-read loop. Transport adapters may not defer the first cancellation
check until response streaming.

If a provider requires serialized access to a shared technical home, lock
acquisition is part of the same cancellation boundary. Preparation and full
invocation locks must use bounded non-blocking acquisition attempts and check
the request cancellation signal between attempts; a revoked queued request may
not wait for the preceding invocation to finish.

CLI execution authorization belongs to the Core broker, not to configuration
under the sidecar-writable app data root. Every non-diagnostic invocation must
select exactly one model explicitly, and Core must match that model and
provider against the current catalog resolved for the lease's workspace/app
scope before invoking the executor. A bounded closed set of metadata-only
diagnostics may omit `--model`.

The core owns process lifecycle, technical token injection, app data-root substitution, route-policy enforcement, auth, workspace membership, app visibility, and error translation. The sidecar owns only its app protocol behind the loopback boundary. A frontend must call a sidecar through the generic core route:

```text
/api/apps/<mount_app_id>/sidecars/<sidecar_id>/<sidecar_path>
```

For `handled_by_core` routes, the core must not start or forward to the sidecar. It invokes the owning app backend with `surface: "sidecar_core_handler"`, the sidecar id, normalized route path, method, query, safe request headers, app data root, workspace Storage roots, and the app dependency resolution payload. The app backend may then return an ordinary mounted-backend response and may emit `dependency_backend_requests`, so routes such as Storage import/export can still use provider apps through the same governed dependency mechanism as `/api/apps/<app_id>/backend`. Provider or business secrets are not delivered to this surface unless the app contract and secret-delivery policy explicitly support that future target.

When a sidecar proxy declares `streaming: true`, the hosted ASGI path must forward request bodies and response bodies in chunks rather than through the JSON app-backend request limit. When it also declares `sse: true`, `text/event-stream` responses must remain streamed and unbuffered. The core injects service credentials only on the server-side upstream request; generated technical tokens must not be forwarded back to browser clients in response headers.

The mounted path above is the legacy browser shape and is insufficient for an
upstream web application that owns root-relative routes. A sidecar may instead
declare the generic isolated-browser-origin capability defined by
[`sidecar_browser_origin.md`](sidecar_browser_origin.md). That capability uses
an opaque host beneath `sidecars.<installation-domain>`, a body-only one-shot
bootstrap ticket, and a separate host-only session cookie. The isolated host
routes only the declared sidecar roots and never falls through to Maverick API
routes. App contracts do not choose the opaque host, ticket, cookie, workspace,
technical port, or generation, and the capability fails closed when local or
hosted origin prerequisites are unavailable.

The declaration is intentionally a closed profile rather than arbitrary CSP or
host configuration:

```json
{
  "browser_origin": {
    "mode": "isolated",
    "csp_profile": "self_hosted_web_app",
    "frame_ancestors": ["platform"],
    "connect_src": ["self"],
    "immutable_asset_prefixes": ["/_next/static/"],
    "sandboxed_frame_resource_prefixes": ["/api/plugins/", "/api/asset-cache"]
  }
}
```

Core rejects weakened or unknown values. An authenticated mounted app obtains a
body-only launch ticket with `POST /api/app-sidecars/browser-launch`, providing
only its app id, declared sidecar id, and a clean root-relative landing path.
Core resolves actor/workspace/install generation from the Maverick session,
starts the already-authorized sidecar, and returns an origin plus form bootstrap
instructions and a separate confirmation token that grants no sidecar access.
The mounted app polls that launch's authenticated platform-origin confirmation
endpoint. It may expose the sidecar frame only after Core has confirmed that
the one-shot ticket became a validated host-bound session and the target frame
has loaded; `iframe.onload` alone is never readiness because a browser error
document can emit it. Reusing a live process is not itself a readiness result:
before issuing every new ticket, Core rechecks the declaration's health endpoint and
evicts the process if that check fails. A process that is alive but no longer
ready therefore receives no new browser authority. The browser submits the
ticket to `/.well-known/maverick-sidecar-bootstrap` on that origin; it never selects a
workspace, binding, technical listener, or host. Logout, workspace switch,
disable/uninstall, sidecar restart, generation change, and core restart revoke
the corresponding in-memory authority.

`immutable_asset_prefixes` is optional and limited to canonical absolute
directory prefixes outside `/api` and `/.well-known`. Successful GET/HEAD
responses under a declared prefix receive a private immutable browser-cache
policy. The app is responsible for using content-addressed filenames there;
all other responses, including errors under that tree, remain `no-store`.

`sandboxed_frame_resource_prefixes` is optional and limited to eight canonical
literal absolute paths or directory prefixes. It exists only for native apps
whose upstream UI intentionally omits `allow-same-origin` from an iframe
sandbox: resources loaded by that opaque-origin document otherwise fail the
default `Cross-Origin-Resource-Policy: same-origin` check. Core emits
`Cross-Origin-Resource-Policy: cross-origin` only for a matching authenticated
response. A trailing slash declares a directory tree; a value without one is
an exact path. The reserved bootstrap namespace, a blanket `/api` declaration,
escaping, dynamic segments, and duplicates are rejected. This does not add a
route or enable CORS. Because an opaque sandbox withholds `SameSite=Strict`,
the declaration also issues a separate host-only, `HttpOnly`, `SameSite=None`,
`Secure` resource cookie while preserving the main `SameSite=Strict` cookie.
Core accepts the resource cookie only for `GET`/`HEAD` on a matching declared
path. Actor, workspace, app, sidecar, generation, TTL, and revocation checks
remain mandatory, and CORS remains disabled. A cross-site page can cause those
explicitly embeddable requests while the resource session is live, so contracts
must never declare user-private APIs or media under this capability.

The core-owned lifecycle command `app.<local_app_id>.sidecars.restart` is the
only general hot-restart surface. It resolves the enabled binding and declared
services rather than accepting process ids or ports. Before stopping anything,
it revokes only the isolated-origin launch tickets and sessions bound to the
current workspace/app. It then stops only those declared sidecars, starts them,
waits for each declared readiness contract, emits redaction-safe audit records,
and publishes `maverick.app.runtime-changed` with the owner app and workspace.
The owner-authenticated local control channel preserves typed startup codes and
phases (for example `runtime_binding_invalid/sidecar_contract_resolve` or a
typed daemon startup failure); it must not collapse contract, spawn, or health
failures into an unphased generic launch error. Host paths and underlying
exception messages are never returned across that channel.
Apps may orchestrate this capability after changing app-owned selection state,
but cannot expand its process or browser-session scope. The core must remain
unaware of app-specific runtime artifacts, data migrations, or rollback rules.

The same owner-authenticated channel exposes an internal fail-closed stop used
by governed maintenance: Core revokes the workspace/app browser authority before
terminating the process group. It is not an app-facing process-control API. If a
declared automatic repair succeeds but the following transactional startup
fails, that startup is part of the same repair attempt; Core records a bounded
backoff and cannot run the hook again on the next request. Concurrent callers
join the in-flight repair/startup rather than creating another process or repair.

When maintenance cannot prove that a writer stopped, the channel also exposes
a generic quarantine operation. Core first persists a workspace/app fence in
the control-plane adapter, then revokes browser sessions, model-access leases
and active broker requests, and live relay/proxy authority before attempting
process termination. Proxy resolution, browser launch, prewarm, restart, and
model capability issue/authorization remain denied across Core restart until
an explicit release clears both the durable and in-process gates. Quarantine
attempts browser, model, and relay/process revocation independently after the
durable write, so one cleanup failure cannot skip another boundary. Its public
evidence reports each observed result separately; proxy revocation is true
only when every affected relay path is confirmed absent. Quarantine does not
infer app migration state and release does not prewarm automatically. An
app-owned maintenance preflight must require an explicit `quarantined: false`
status before making an irreversible writer transition; a missing quarantine
result is not evidence that activation is safe.

App-owned backend, CLI, MCP, and reference entrypoints do not receive the
sidecar listener, technical token, or sidecar filesystem. A sidecar may declare
a separate synchronous `entrypoint_access` profile. The declaration names an
explicit TTL from 1 through 30 seconds, request budget, request/response body
limits, `streaming: false`, and per-surface exact route lists for `backend`,
`cli`, `mcp`, and/or `reference`. Every entrypoint route must be an exact
non-static subset of `proxy.route_policy.pass_through`; reference routes are
limited to GET/HEAD. Browser policy never implies entrypoint authority.

For one matching entrypoint invocation, core creates a private mode-`0600` Unix
broker socket, issues a random capability bound to invocation, workspace,
local app id, service id, surface, actor, route list, expiry, and budget, and
adds only the broker descriptor to the JSON payload. The app uses
`core.app_sdk.app_sidecar.app_sidecar(payload, service_id)` to make an HTTP-like
request. It cannot select another workspace or service, and it never learns the
internal TCP port, `${service.token}`, relay capability, or `OD_API_TOKEN`-style
technical credential. Core canonicalizes and authorizes the path, strips host,
cookie, authorization and hop-by-hop request headers, injects the technical
credential only upstream, filters unsafe response headers, bounds the complete
response, and records redaction-safe issue/request/deny/revoke audit events
under one invocation correlation id.

Capabilities are stored only by digest and revoked when the entrypoint exits,
times out, is cancelled, or the host shuts down. A stale SDK client fails at the
broker and has no loopback or direct-filesystem fallback. Long-lived streams or
jobs require a distinct contract and capability; the synchronous profile does
not gain a longer TTL implicitly. Reference invocation is distinguished from
ordinary MCP invocation by trusted core context, so a reference tool cannot
reuse the app's broader MCP policy.

Sandbox compatibility also requires the generic process boundary defined by
[`app_sidecar_execution.md`](app_sidecar_execution.md). A sandbox-required
sidecar starts with an allowlisted environment, a verified read-only artifact,
only its active app-data generation and bounded temp/relay roots writable, an
isolated network namespace with no egress, and a core-owned Unix relay. Contract
authors cannot provide raw sandbox flags, host mount sources, socket paths,
network destinations, identities, or fallback commands. Missing mandatory
namespace, mount, relay, or limit support prevents the sidecar from starting;
host-loopback or unsandboxed fallback is invalid.

Every HTTP sidecar declaration includes `process_policy`. The supported
sandbox contract is deliberately singular: `inherit_host_env: false`,
`sandbox: required`, read-only bundle, writable validated app data root,
`network: isolated`, `transport: unix_relay`, and an empty `outbound` list. Its
`limits` object declares positive `memory_bytes`, `open_files`, and
`request_concurrency` bounds. Missing or weakened fields are contract errors.
Sandbox environment values may use only `${service.port}`, `${service.token}`,
`${app.data_dir}`, and `${app.source_dir}`; `${workspace.root}`, unresolved
host substitutions, `HOME`, provider keys, platform bootstrap/runtime tokens,
and secret-store material are rejected. Core overrides Maverick identity fields
and never derives the sidecar environment from `os.environ`.

The internal TCP listener exists only in the sidecar network namespace. Health,
WSGI, and streaming ASGI requests all open the workspace-bound Unix socket and
present a per-launch relay preamble before sending HTTP with the separate
technical token. The host does not connect to, publish, or fall back to the
internal TCP port. Relay directories use mode `0700`, sockets use `0600`, and
shutdown or failed health terminates the bubblewrap process group and removes
the relay identity.

The proxy must not expose terminal access, host-folder import, wildcard passthrough, arbitrary network binding, or undeclared websocket/streaming semantics for sandbox apps. If an app needs those features, the contract must mark them outside sandbox compatibility or route them through a future generic core policy surface.

## Human Surface Versus Agent Surface

The same app may need to serve both humans and agents.

The intended split is:

- `frontend/` for human-facing visual interaction
- `backend/` for app-specific server logic
- `mcp/` and `cli/` for agent and operator execution surfaces
- `skills/` for skill templates owned by the app source but copied into workspace skill catalog data before runtime use

This is a core design principle.

Apps in Maverick are not just mini-sites.

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

Mounted app backends may request app-scoped secret writes through the generic entrypoint result contract. The core persists or rotates the raw value in the platform secret store, creates or reuses an app backend grant for the current `(workspace_id, app_id, logical_name)`, strips the raw write from the HTTP response, and returns only non-sensitive metadata. Automatic secret create, rotate, and grant creation steps emit explicit audit/event records attributed to the app and actor when available. Legacy app bindings are migration input only; app-entrypoint delivery consumes grants. On later mounted backend, CLI, or MCP calls, the core delivers `app_secrets` only from active, non-expired app grants whose logical names are declared by the app contract, whose action allowlist includes `app.backend`, whose target patterns match the synthetic delivery target, and whose resource scope matches the request. Non-resource grants are delivered only to non-resource requests. Resource-scoped grants are delivered only when `resource_type` and `resource_id` match exactly. Backend delivery uses `maverick://app.backend/backend`. CLI and MCP delivery uses per-entrypoint targets such as `maverick://app.backend/cli/<command>` and `maverick://app.backend/mcp/<tool>`, and each command or tool receives only the declared logical names listed in its descriptor `required_secrets` array or derived by its descriptor `secret_selectors` array. A grant may use `maverick://app.backend/*` to cover all app entrypoint delivery targets, but descriptor-level secret declarations still limit which values are delivered to each backend call, CLI command, or MCP tool. Delivery fails closed and records audit/event data when a required logical name has no current compatible grant. App CLI and MCP entrypoints must consume that delivered `app_secrets` payload; they must not import core secret-store internals, read configured control-plane secret collections directly, or reconstruct secret values from control-plane files.

A platform-owned grant binds a secret reference to a workspace, enabled and surface-resolvable app id, logical name, allowed action set, optional structured HTTP/HTTPS or platform delivery target patterns, expiry, and revocation state. Apps store or receive the grant reference and ask the platform to use the secret for a concrete action and target. The core validates the grant before decrypting the value, rejects `app.backend` grants whose logical name is not declared by the target app under `permissions.secrets.read`, rejects manual and app-written grants whose resource scope does not match the app's descriptor-declared consumer mode, rejects resource-specific platform delivery target patterns that point at a different resource than the grant scope, returns only redacted metadata to browser clients, strips query strings from audit targets, stores only allowlisted bounded request context, and records allow or deny audit events without raw values. Secret permission logical names are sensitive contract metadata for grant administration: Vault-style UI discovery must use an admin-only Core Secrets endpoint, while generic registry surfaces such as `/api/apps` must omit them. That admin endpoint may expose redaction-safe consumer metadata such as whether a logical name is consumed only through resource-scoped selectors and which `resource_type` values those selectors declare, so governance UI does not suggest workspace-wide grants for per-resource credentials. It may also expose redaction-safe issue-oriented needs with recommended grant specs, value state, grant state, user action, and credential-match confidence metadata; those recommendations must be derived from contracts and descriptors and should prefer specific `maverick://app.backend/backend`, `maverick://app.backend/cli/<command>`, or `maverick://app.backend/mcp/<tool>` targets over `maverick://app.backend/*` whenever the narrower target covers the declared consumer. Expired grants are reported as expired derived state, ignored during app-entrypoint delivery selection, and no longer block replacement of the same logical name. Empty targets are accepted only for internal `app.backend` defaults; user-directed actions require explicit targets. `*` target patterns are rejected for mixed-action grants because targets are grant-wide, not per-action.

Vault is a built-in sealed app that provides the user-facing Credential Inbox, Connection Issues, and Advanced details UI for this model. Its normal workflows call admin-gated Core Secrets APIs for redaction-safe inventory, issue recommendations, controlled credential input, rotation, CSV import, and audit/diagnostic review; direct grant mechanics stay in advanced diagnostics and core-owned agent operations rather than the primary user workflow. Vault does not own a secret-value data model and must not persist raw values under `data/vault`.

This capability is provider-agnostic. OAuth providers, token shapes, refresh semantics, and account metadata remain app-owned behavior.

## Operational Permissions

Capabilities describe what an app can expose. Permissions describe what the platform may allow that app surface to do.

Every app that needs privileged operational behavior should declare those needs explicitly instead of relying on hidden code paths or broad backend trust.

The contract supports a required, strict `permissions` section for platform-governed operations such as:

- app-scoped secret read or write requests
- outbound network access classes or allowed hosts
- host telemetry, process, or filesystem inspection outside the workspace data root
- runtime session creation, interrupt, cleanup, or recovery actions
- workspace file read/write outside the app-owned data root
- app backend subprocess execution requirements
- lifecycle hooks that mutate app data, workspace storage, or platform state

Permissions are requests, not authority by themselves. The core must combine declared permissions with workspace governance, user/session authority, source trust level, and execution mode before mounting or invoking the surface.

Apps that do not declare a permission in that section must be treated as not needing it. The core fails closed for unknown permission fields and for privileged operations attempted without a matching declaration.

Example shape:

```json
"permissions": {
  "secrets": {
    "read": ["oauth_account"],
    "write": ["oauth_account"]
  },
  "network": {
    "outbound": ["api.vendor.example"]
  },
  "runtime": {
    "create_sessions": false,
    "cleanup_sessions": true,
    "receive_cleanup_callbacks": false
  },
  "host": {
    "telemetry": false
  },
  "providers": {
    "model_proxy": false,
    "credential_source": "none",
    "deliver_secrets_to_app": false
  }
}
```

`permissions.providers` is for core-governed workspace model provider access, not app-owned secret delivery. `model_proxy: true` allows redaction-safe provider status/model metadata through a governed `handled_by_core` route or the explicit sidecar `model_access` transport above. `credential_source: "core-vault"` declares that raw provider credentials remain under Maverick/Vault control. `deliver_secrets_to_app: false` is the sandbox default and means provider keys must not be included in browser payloads, app backend `app_secrets`, sidecar environment, media config files, or sidecar-forwarded requests. The model-access socket carries only a scoped technical handle; Core resolves the raw credential at execution time and forwards provider protocol bytes without cognitive enrichment.

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
- health check
- runtime session cleanup
- data cleanup

The goal is not to force every hook to exist.

The goal is to make lifecycle behavior explicit and automatable.

Lifecycle and cleanup hooks are app-owned behavior declared in the contract and invoked by the core only through generic lifecycle orchestration.

The core must not hardcode one app, such as Chat, into runtime cleanup. If app-owned metadata or files need cleanup when a runtime session is deleted, the app sets `permissions.runtime.receive_cleanup_callbacks: true`, and the core invokes every enabled opted-in app with a generic context containing `workspace_id`, `local_app_id`, `public_app_id`, deduplicated `runtime_session_ids`, and canonical runtime paths. The app decides how to clean its own records under `data/<local_app_id>/`.

Cleanup hooks must be idempotent, bounded by hook timeout, and authorized by the same app contract and workspace governance rules as other lifecycle hooks.

## Executable Contract Requirements

To be a real platform contract, the app contract should also declare executable integration details.

At minimum, the contract should support:

- `contract_version`
- `minimum_core_version`
- `entrypoints`
- `permissions`
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

### App interfaces and cross-app dependencies

Apps may declare platform-visible interfaces with top-level `provides` and `requires` arrays.

`provides` describes interface types the app can satisfy. It is not a dependency on a specific consumer app.

```json
"provides": [
  {
    "interface": "file.catalog",
    "version": "1",
    "description": "Lists workspace files exposed by this app.",
    "surfaces": ["backend", "reference"]
  }
]
```

`requires` describes interface types the app needs from whichever enabled provider app the workspace selects.

```json
"requires": [
  {
    "alias": "file-providers",
    "interface": "file.catalog",
    "version": "^1",
    "required": true,
    "cardinality": "many",
    "description": "File catalog providers available to this workflow app."
  }
]
```

Rules:

- interface identifiers use dotted lowercase names such as `agent.catalog`, `file.preview`, or `file.content.write`
- version requirements support exact versions and compatible major ranges such as `^1`
- `cardinality: "one"` requires exactly one selected provider; `cardinality: "many"` allows multiple selected providers
- optional requirements may be left unset without blocking app launch
- `surfaces` must reference surfaces the provider contract actually exposes
- consumers must refer to dependency selections by alias, not by hardcoded app id

The core resolves these declarations against enabled workspace app bindings and stores only workspace-scoped provider selections. It does not know the product semantics of `agents`, `storage`, `drive`, or any other app.

The base shell owns the human setup flow for unresolved dependencies. It can show candidate provider apps filtered by interface type and persist the selected provider app ids through the generic core dependency API. Mounted apps receive the resolved dependency payload through shell messages and may also read it from the generic dependency API.

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

For the first local implementation, executable app entrypoints use a deterministic subprocess convention:

- the core resolves the declared entrypoint path inside the app root
- the core invokes that entrypoint as a local executable script with the current core interpreter
- the core passes a JSON payload on standard input
- the entrypoint returns a JSON object on standard output

This convention applies to app-owned MCP and CLI entrypoints in the initial implementation.
The core-provided payload is the authority for `workspace_id`, `app_id`, runtime context, data roots, generated/uploaded storage roots, and delivered app-scoped secrets. App entrypoints must reject missing required context instead of falling back to a workspace such as `default`, and they must not trust caller arguments or HTTP bodies for platform-owned context fields.

For mounted frontend and backend surfaces, the same principle applies:

- the contract must declare what the surface root or entrypoint is
- the core must mount it explicitly
- the app must not rely on implicit repo conventions unknown to the platform

For the first implementation, it is acceptable for the frontend declaration to identify either:

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

For the first frontend build operation, the core supports app sources that declare a frontend entrypoint and contain a `package.json` with a real `build` script either at the app root or at the frontend source root. The core runs the build from that package root only through an authenticated full-access or operator-authorized host path. If `node_modules` is absent, the package root must contain `package-lock.json`; the official build operation runs `npm ci` before `npm run build` so a clean checkout can reproduce the build deterministically. Every successful build must produce `maverick-frontend-assets.json` using schema `maverick.frontend-assets.v2`. A build-aware bundler plugin may classify generated content-hashed outputs as `immutable`; a conservative post-build fallback classifies every artifact as `revalidated`. The optional `navigation_fallback` field names a verified normal HTML entrypoint and is valid only when that same path is selected by a verified precache record; it never declares an alternative product shell. The build-aware plugin rejects local static resource references in emitted HTML when the referenced file is absent from the built artifact; navigation links and external or embedded URLs are not artifact references. Core verifies safe relative paths, file presence, byte size, and SHA-256 before publishing `maverick.app.frontend-changed`. A hash-looking filename without a matching verified manifest record is never evidence of immutability.

Mounted app registry, frontend documents, and backend routes are authenticated
workspace surfaces. Anonymous requests may load the root shell, the configured
root-shell app document, and session endpoints, but `/api/status`, `/api/apps`,
and `/api/apps/<app_id>/backend` require a valid user session. A direct non-shell
app or widget document at the platform origin is rejected even with a session;
the Core-owned OAuth callback relay is no-store and contains no app bundle.
Core serves the actual app document only through a host-bound app-frame session
on the app's isolated origin. That session carries the canonical local and mount
app ids into the internal HTTP and WebSocket scope. Core compares every app and
widget frontend owner with that binding before routing, and a bare internal
proxy marker is never sufficient document authority. App and widget frontend
HTML documents use
`Cache-Control: no-store` because they point at the current built asset hashes
and must not pin clients
to obsolete bundles after an official frontend rebuild. Static built frontend
assets under `/apps/<app_id>/assets/...` and non-HTML static files emitted into
the frontend artifact root are public artifacts and must not contain user,
workspace, secret, or app-data payloads. Only bytes matching an `immutable`
record in the generated manifest receive
`public, max-age=31536000, immutable`; other public static files remain
revalidated. Any public app artifact is served with a restrictive document CSP
(`sandbox`) and `X-Content-Type-Options: nosniff`, preventing script-capable SVG
or mislabeled bytes from becoming app-controlled platform-origin documents.
Gzip or Brotli content encoding and cross-origin headers allow isolated app and
widget frames plus Vite-generated `crossorigin` module/style tags to load
bundles without platform session cookies on every asset request. When Core
serves an isolated HTML document, it converts quoted `src` and `href` references
below `/apps/<app_id>/assets/` into absolute URLs on the exact platform origin;
API and navigation references remain on the isolated proxy. Vite app builds
that create URLs from JavaScript must use the shared isolated-frame asset URL
plugin. It leaves HTML/CSS on the declared `/apps/<app_id>/` mount and emits
lazy module-preload dependencies, worker URLs, and imported media relative to
the platform-origin module through `import.meta.url`, never relative to the
isolated document. Public build outputs include safe script/module, style,
image, audio/video, font, PDF, and WebAssembly types; one-year immutability still
requires an exact manifest record. This is the normative browser-cache path for
app bundles. The shell service worker cannot control a document on another
origin, so app artifacts use their verified HTTP cache policy rather than a
shell-owned runtime Cache API entry. Source maps and source-like extensions such
as `.ts`, `.tsx`, `.jsx`, `.vue`, `.svelte`, `.py`, and `.env` must not be
treated as public static assets or SPA fallback routes.
Workspace-local editable backend entrypoints are additionally workspace-admin
gated until a dedicated app backend sandbox/governance model is available.

Browser persistence does not change app ownership. An app that later opts a
read model into the shared PWA SDK must declare a canonical Maverick
`data_class` source, resource provenance, stable revision, bounded TTL and byte
budget, invalidation event, and sanitization rule. The local persistence policy
is derived from that canonical classification under ADR-0012 and has only
`deny`, `session`, and `cache` values; it is not an app-defined sensitivity
taxonomy. Missing classification or revision remains network-only. Only the
top-level host creates a client capability whose user/workspace/app principal
it binds; embedded app frontends reach it through the constrained parent broker
and cannot select another scope. Every app and widget document now runs on an authenticated
per-app, per-login-session isolated origin. Direct non-shell documents on the
platform origin are blocked, and retaining iframe `allow-same-origin` grants an
app access only to its own isolated-origin storage. It cannot inspect Base
Shell IndexedDB/OPFS or another app's origin. Private app persistence remains
disabled by default until its resource, privacy, lifecycle, and physical
rollout gates are approved; isolation is necessary but does not itself grant
cache policy.

Core injects a frozen, non-configurable `__MAVERICK_APP_FRAME_CONTEXT__` into
each authenticated isolated app and widget HTML document. It contains only the
canonical workspace id and public mounted app id from the browser-session
binding. Apps may use this host-attested context to reject a legacy cache value
from another scope; URL query parameters are not workspace attestation and the
context itself does not authorize an app action.

There is no same-platform-origin compatibility mode for executable app or
widget documents. If the isolated browser origin cannot be created or reached,
Core fails launch closed and keeps direct platform-origin documents blocked.
Hosted installations must provision either the exact
`*.sidecars.<installation-domain>` TLS wildcard or the managed-exact HTTP-01
mode used by both dynamically derived `sc-*` sidecar hosts and `af-*`
app-frame hosts. Managed-exact mode authorizes only Core-derived names, obtains
the certificate before issuing a browser ticket, and atomically publishes it
to the restricted Nginx key directory. A manually maintained finite SAN list
is not a substitute for either supported lifecycle.

Cached platform control-plane state never authorizes an app action. An app
renders a valid cached result through its normal component and keeps a cache
miss in its normal loading state during a transient transport failure. App
contracts must not add a network-absence mode, availability badge, pin action,
or persistent mutation queue as an implicit consequence of cache support.

M5 app frontends use the Base Shell parent broker rather than constructing the
host capability themselves. A child request names only its own mounted app,
opaque entity, fixed resource, and exact resource schema revision. Base Shell
registers every app and widget frame together with its real owner app id,
active workspace, and opaque authenticated shell-session generation. It
accepts a request only when that complete scope matches the current broker
principal, the owner matches the request, the frame window and exact isolated
origin match, and both global and per-app gates are open.
The app performs
its conditional backend read when requested over the private channel and
returns an app-sanitized model; it never receives the host principal, access
lease, IndexedDB backend, or another resource namespace. A rejected or absent
broker invokes the same server read directly. Sanitized legacy state is a
migration seed, never an independently renderable value, and may be removed
only after the parent verifies the scoped commit.

Structured invalidation messages follow that same owner registration:
neither an app nor one of its widgets may claim another app's owner id. Declared
resource aliases and shell fan-out recipients are resolved only after scoped
owner verification; only an exact top-level shell message may intentionally
cross owners. Workspace and authenticated-session transitions rotate the
generation and synchronously remove frames from the previous scope, so a late
old frame is rejected before a warm new-workspace value can be read. If a warm
read has already rendered and its revalidation returns `401` or `403`, the broker starts
durable cleanup and AppShell clears authenticated UI and unmounts every app and
widget frame. Reauthentication creates new frame documents, so private data
from the revoked scope cannot remain in the DOM.

The session handoff is an AppShell publication barrier, not an eventual effect.
Before a replacement session is fetched, a workspace mutation is sent, or a
logout request is awaited, the shell synchronously withdraws its broker
principal and frame scope, removes the authenticated frame tree, and disposes
the Storage file broker in a layout cleanup. `WorkspaceSwitcher` only requests
the action; AppShell owns the boundary and calls Core after that synchronous
commit. Lifecycle transition, end-session,
authorization-failure, invalidation, and clear operations are serialized. The
candidate session and its registry become renderable only after the applicable
lifecycle transition completes and only while that load remains current; a
concurrent authorization failure cancels publication. Logout finishes in the
anonymous shell after local cleanup regardless of a failed network response and
does not remount frames through a follow-up session read.

Every parent-owned path that can observe `401` or `403`—shell APIs, PWA config,
structured data, Storage file bytes, and isolated-frame launch—uses one
idempotent authorization-revocation channel. Each observed authorization
failure synchronously signals AppShell, cancels the active shell load, and
removes authenticated UI even when a prior cleanup is pending. Only the durable
cleanup promise is coalesced and serialized. Cleanup latency is outside request
timeout classification: once an HTTP authorization response exists, it remains
the terminal HTTP result and cannot be rewritten as a transport timeout.

The initial declarations are Website Studio site snapshots, Storage catalog
metadata, the App Store catalog, and Fitness Coach bootstrap/thumbnail data.
Their schemas, classifications, validators, TTLs, byte budgets, event aliases,
and persistence outcomes are normative in
`docs/product/pwa_cache_resource_inventory.v2.json`. App Store catalog data
cannot enable an install, launch, workspace assignment, pin, or publication
control before fresh server authority loads. Fitness Coach obtains the exact
workspace/app scope for legacy bootstrap migration from Core's immutable frame
context and never from the launch URL query. Its personal data is session-only
until a separate privacy decision changes the resource policy;
feature flags cannot make that promotion. Calendar, Chat, CRM, and Mail are not
implicitly enabled by the existence of the broker.

The M3 shared implementation is `packages/pwa-cache/`. The top-level host must
create an app-bound capability with explicit non-empty user id, workspace id,
and owning app id; an adapter receives a client from that capability and
registers each resource exactly once with policy revision
`maverick.local-persistence-policy.v2` and an app-owned resource schema
revision. The resource declaration supplies its canonical data class and
provenance, sanitizer, stable server revision or ETag, fresh and absolute
expiry TTLs, maximum entry bytes, maximum resource bytes, stale-render
permission, and required privacy approvals. The framework derives `deny`,
`session`, or `cache`; an app cannot directly promote its own classification.
Persistent private reads additionally require a fresh bounded access lease
issued after successful server authentication.

`readThrough` returns an ordinary network result on a miss, an ordinary cached
result on a valid hit, and an optional single-flight revalidation promise for
an explicitly renderable stale value. Expired, malformed, sanitizer-rejected,
wrong-scope, wrong-policy, wrong-resource-schema, wrong-entry-schema,
impossible-timestamp, size-mismatched, and lease-expired entries are misses. An
adapter must use `not_modified` only when it already has the matching cached
value, and must emit `maverick.app.data-changed` with the owning app and
resource after a confirmed server mutation. Quota, IndexedDB, migration,
serialization, or cache-write failure must never replace a successful server
response.
Security-sensitive deletion cannot use the RAM performance fallback as
success: an incomplete durable clear is pending and blocks persistent cache
access until the primary store confirms deletion.

The SDK's retry coordinator is RAM-only. It automatically pauses for document
visibility and `maverick.app.visibility-changed`, treats browser `online`,
focus, and successful Maverick responses only as early retry hints, and
cancels work at unmount or principal/scope change. Unsafe requests are not
replayed without a stable `Idempotency-Key`, a request fingerprint, and an
explicit server-deduplication contract. Even then they re-enter current server
authorization/admission and have a bounded attempt count; no app may interpret
the local pending state as mutation success. A terminal `401` or `403` remains
the original HTTP result even when cleanup cancels its retry scope. The M3
end-to-end mutation proof is Base Shell's `pinned_apps.set`, whose exact
SHA-256 fingerprint and stable key are deduplicated atomically by App Store.

The `base-shell` UI/UX is the visual and interaction reference for the mounted shell.

The shell should preserve the intended shell experience, layout behavior, sidebar composition, workspace/app panels, and responsive behavior where those concepts are still valid.

The `base-shell` intentionally does not include a topbar. Provider, runtime, workspace, and status metadata must be exposed through generic settings or app-owned surfaces instead of leaving a hidden topbar component behind.

The shell must not preserve obsolete runtime coupling, app-specific API assumptions, auth shortcuts, or non-contract manifest formats.

The shell attaches only to platform protocols such as:

- `/api/session`, `/api/auth/login`, and `/api/auth/logout` for session state
- `/api/workspaces` and `/api/workspaces/active` for workspace selection
- `/api/apps` for enabled app registry data
- `/api/status` for platform status
- `/api/providers/active` and `/api/runtime/status` for runtime provider indicators
- `/api/settings/provider-setup` for shell provider setup metadata
- `/api/settings/platform` for generic settings metadata
- `/api/settings/runtime-sessions` for cleanup-scope runtime inventory
- `/api/recovery/status` and related recovery routes for operator status where appropriate
- mounted app frontend routes under `/apps/<mount_app_id>/`
- mounted app backend routes under `/api/apps/<mount_app_id>/...`

The shell must derive app navigation from registry records such as `local_app_id`, `public_app_id`, `name`, `description`, `views`, `frontend_mount`, `frontend_role`, `frontend_launchable`, `backend_mount`, and optional icon or logo metadata.

The shell and App Store pinning APIs must treat `frontend_launchable` as the app-open and pinning gate. `frontend_mount` alone means the platform can serve frontend assets; it does not imply the app should appear as a user-openable workspace app.

The `base-shell` port may retain shell-owned local preferences in the browser, such as the last active app and sidebar state.

Those preferences are shell UI state only. They are not core workspace records, app installation state, provider configuration, or app-owned backend data.

If the active workspace has no configured runtime provider, `base-shell` may open a startup provider setup dialog and persist the selected provider/model through the generic core provider API. This is workspace governance state, not shell-local preference and not chat-app state.

Pinned app shortcuts are not shell-owned browser preferences. They are App Store app data, exposed through an App Store-owned sidebar widget that `base-shell` mounts through the generic widget registry. Pin mutations require current workspace app registry context so non-launchable supporting apps cannot be newly pinned; stale uninstalled, non-launchable, or orphaned entries may still be removed. If an orphaned pinned app id no longer appears in catalog, server, local, or installed app listings, App Store UI should expose a cleanup row instead of requiring direct API use.

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

The readiness message means the mounted frontend has reached its first useful render, which may still be an app-owned loading skeleton while app data is loading. The host should reveal a cold-mounted target iframe and resend the latest pending navigation params for that app when it receives `maverick.app.ready`, but repeated readiness messages for the same app, frame, and navigation signature must not fan out duplicate navigation deliveries.

This avoids losing navigation requests when an app iframe is freshly mounted after login, logout, refresh, or recovery and the host message arrives before the app has installed its listener.
- the host may know the target `app_id`, but must not know app-private storage or route internals
- the receiving app owns interpretation of `params`
- the receiving app must ignore messages that do not come through the
  exact-parent relay bound to the platform origin

The physical iframe starts at `about:blank`. Base Shell posts the registry
`frontend_mount` (including frozen initial theme and mobile-layout parameters)
to `/api/app-frames/browser-launch`, validates the returned distinct exact
origin, and submits the body-only one-shot ticket to that origin in a hidden
form targeted at the iframe. The ticket is never placed in a URL. Core binds
the resulting host-only `HttpOnly`, `SameSite=Strict` cookie to actor,
workspace, app generation, platform login session, and exact host; logout or a
stale binding revokes it. HTTP and WebSocket forwarding preserve the bound app
identity, and any app/widget frontend path naming another owner fails with an
authorization denial before its document can be served.

During shell app switches, a host may keep the previously visible app frame on screen while the newly requested iframe loads hidden. If a third-party app does not yet emit `maverick.app.ready`, the host may use a bounded post-load fallback to reveal the frame, but it should avoid exposing the browser's initial blank iframe canvas during normal cold mounts.

Shell-mounted app and widget iframes preserve access to their own mounted
frontend and API routes through the isolated proxy. The sandbox includes
`allow-same-origin`, but "same origin" now means the exact per-app isolated
host, never the platform or another app origin. Core isolates that host into an
origin agent cluster and permits only the platform/self frame ancestor. Unsafe
proxied HTTP methods require the exact isolated `Origin` and browser
`Sec-Fetch-Site: same-origin`; WebSockets require the exact isolated origin.
Mounted app and widget iframes also allow the browser `fullscreen` feature so
app-owned preview surfaces can request real fullscreen from a user gesture
while still falling back to in-frame fullscreen when the browser denies it.
Base Shell delegates `clipboard-write` only to app and widget frames whose
public app owner is Chat, preserving user-initiated message copying across the
isolated-origin boundary without granting clipboard access to unrelated apps.
Chat retains a selection-backed document-copy fallback because browsers may
still deny asynchronous clipboard writes after exposing the API in a delegated
cross-origin frame; copied feedback is shown only after either path succeeds.
Full app frames retain microphone delegation, while Chat-owned widget frames
receive it for composer dictation.
Public static assets remain cross-origin readable and must never carry
user-specific data, but their document interpretation is sandboxed and
`nosniff`.

On mobile, the shell may render transparent chrome above mounted app iframes.
To let app content scroll visually underneath that chrome while keeping the
first app content below it, the isolated document bootstrap applies the initial
layout from `maverick_mobile_layout` and then accepts exact-parent
`maverick.shell.layout-changed` messages. It sets
`--maverick-shell-mobile-content-top-offset` and the related status/header
variables inside the isolated document; the shell never reaches through the
cross-origin DOM. The shell must not crop the mounted iframe below its mobile
header, because that prevents app content from appearing behind the transparent
mobile header chrome.

The shell must notify mounted app and widget iframes when their host surface becomes visible or hidden by sending `maverick.app.visibility-changed`. App frontends must treat hidden as a signal to suspend nonessential intervals, runtime replay, and background refresh. Hidden iframes may keep state in memory, but they must not continue live polling as if they were the active work surface.

Apps that declare a frontend entrypoint may be rebuilt through the official core app-hosting frontend build operation when they provide a real build script. After a successful rebuild, the core publishes `maverick.app.frontend-changed` on the app event WebSocket. The shell should react to that event by remounting only the affected app iframe and shell-hosted widget iframes owned by that app with a shell-owned cache-busting query parameter. This refresh path is for updated frontend artifacts after rebuilds. It must not be used for app-owned internal navigation, must not poll mounted frontend documents, and must not require a full shell page reload for already-mounted app or widget iframes.

This avoids unnecessary reloads, keeps app state alive, and preserves a clean core/app boundary.

Shell panels that configure users, retrieval, notifications, backend restarts, or chat internals should live behind their own app contracts or generic core surfaces, not hardcoded inside `base-shell`.

When capabilities become available, they should be exposed through their own app contracts or generic core surfaces, then discovered or mounted by `base-shell` through the same registry-driven mechanism.

The initial shell may include login, workspace selection, provider/runtime indicators, and generic settings only because those are backed by generic core APIs rather than shell-private backend assumptions.

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

App-owned surfaces may return a generic `chat_render` object when they create or recall content meant for chat. The runtime bridge treats that as structured output by copying `chat_render.kind` and `chat_render.payload` into provider-agnostic structured content. Agent-message completions may also return the same envelope, or a direct `structured_content` envelope with the same `kind` and `payload`, and the runtime bridge must normalize both forms identically. Host apps still discover renderers through the widget registry; `chat_render` is not permission for Chat to special-case the producing app.

This is an app surface model, not app-to-app communication.

The embedding app does not import source code from the widget owner.

The embedded widget does not call private APIs of the embedding app.

The core remains responsible for:

- validating the widget declaration in the app contract
- publishing enabled widget metadata through the app registry
- mounting or routing the widget surface according to workspace enablement
- enforcing auth, workspace context, and install state before a widget can load

Host apps may forward generic app data invalidation messages to widgets when the invalidation belongs to the widget owner.

Core-owned runtime data should use core realtime transports instead of app invalidation messages. For example, Chat full app and widgets subscribe to `WS /ws/runtime/threads` for initial and live thread catalog state; active thread selection can be mirrored with an app-owned UI message such as `maverick.chat.active-thread-changed`, but the thread records themselves must not be refreshed through `maverick.app.data-changed`. Runtime thread snapshots are bounded initial pages with `threads_page` metadata, and REST mutations return changed-thread or removed-id deltas rather than a full catalog replacement.

A shell-hosted floating widget follows the same rule. The shell may reserve a visual overlay slot, such as a bottom-right holder, but the embedded app still owns the widget declaration, renderer, backend actions, and persisted state. The shell selects the widget through the registry by `host` and `content_kind`; it must not import the widget owner's source or call private app APIs.

When a shell overlay widget needs awareness of the user's current work surface, the shell may pass the currently mounted app as explicit widget context. That context should include registry-level metadata only, such as app id, name, description, and views. The shell should suppress a widget whose owner app is already the mounted app, because embedding an app's helper inside that same app usually duplicates the active experience.

A floating widget may be only a thin app-owned frame around the owning app's normal frontend. For example, a chat-owned floating assistant can render the normal Chat app inside a collapsible widget frame. Frame-level controls such as choosing the active core runtime thread or creating a new empty chat may live in that widget frame, while composer behavior, Markdown rendering, attachments, and transcript rendering stay in the Chat app instead of being copied into a separate mini-chat implementation. Runtime ownership stays in the core.

If a shell-hosted widget needs to attach a screenshot of the currently visible work surface, the widget may request a shell-mediated area capture. The shell owns the drag-selection overlay and returns a generic image file to the requesting widget. This capture path must not inspect the mounted app iframe DOM; it is a visual fallback that works across apps without app-specific selection protocols.

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

For chat, this means compile-time imports such as:

```text
../../*/chat/*widget.tsx
```

must not be introduced.

That pattern makes the chat app aware of other apps' source trees and breaks the standalone app boundary.

The model should be registry-driven.

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

The initial core implementation uses:

- `GET /api/apps/widgets?host=<host>&content_kind=<kind>` for workspace-scoped widget discovery
- `GET /api/apps/widgets/<owner_app_id>/<widget_id>/frontend/...` for controlled iframe frontend mounting
- `POST /api/apps/widgets/context` to create a signed context token after validating workspace, authenticated user, requested host surface, widget owner, widget id, and content kind
- `GET /api/apps/widgets/context/<token>` to read the explicit context from the widget iframe without exposing source paths or registry internals

Widgets are reusable app-owned surfaces. Any authenticated app frontend may discover a compatible widget and request a context token for the widget's declared host surface and content kind. The signed context token is not proof of the requester app's identity: it must not include or imply `requester_app_id`, and widget owners must treat `host_app_id` as the requested compatible surface, not as an attested caller. The registry endpoint must not mint reusable requester capabilities, and mounted app backend responses must not cause the core to sign widget contexts as a side effect.

The widget frontend document route is a controlled authenticated mount. Static non-HTML files below that widget frontend mount, such as `styles.css`, `main.js`, fonts, or images, follow the same public-cacheable rule as app frontend assets: they must not contain user-specific data and may be served with cross-origin headers so sandboxed widget iframes can load their own bundle without per-asset session cookies.

Iframe widgets that need host-driven sizing may post `maverick.widget.resize` to their parent with the declaring `owner_app_id`, `widget_id`, and a pixel height such as `320px`.
The embedded widget must measure its content, not the current iframe viewport, so parent resizing does not create a feedback loop.
The host must validate the message origin and frame source, match `owner_app_id` and `widget_id` to the mounted widget, accept only bounded pixel values, and ignore invalid or excessive resize strings.
Long widget content should be capped by the host surface and scroll inside the mounted iframe rather than stretching the host transcript or shell area indefinitely.

Shell sidebar footer widgets may expose a mobile header primary action through the `maverick.widget.primary-action` protocol.
This is a shell-to-widget contract, not a shell-owned app command.
The shell may query only the mounted `shell.sidebar.footer` widget selected for the active app:

```json
{
  "type": "maverick.widget.primary-action.query",
  "owner_app_id": "agents",
  "widget_id": "agents-sidebar-footer"
}
```

The widget answers with its current availability:

```json
{
  "type": "maverick.widget.primary-action.state",
  "owner_app_id": "agents",
  "widget_id": "agents-sidebar-footer",
  "available": true,
  "label": "New Agent",
  "preferred_surface": "app"
}
```

`preferred_surface` is optional and defaults to `app`.
When a footer action needs UI that lives inside the shell sidebar, it may return `"preferred_surface": "sidebar"`.
The host may then open the currently selected sidebar surface immediately before sending `maverick.widget.primary-action.invoke`.
This is a narrow primary-action affordance and must not reintroduce a generic iframe command that opens the shell sidebar.

When the user activates the shell header button, the shell sends:

```json
{
  "type": "maverick.widget.primary-action.invoke",
  "owner_app_id": "agents",
  "widget_id": "agents-sidebar-footer"
}
```

The host must validate message origin and frame source for widget responses, and must match `owner_app_id` and `widget_id` to the mounted widget before accepting state.
State from a different frame, owner, or widget id must be ignored.
The shell treats missing state, widget remount, app switch, load failure, or `available: false` as unavailable.
The `label` is host chrome text for accessible labels and titles; the widget still owns the actual action behavior.
The widget must derive or receive the effective mounted owner id, such as the local `owner_app_id` in `/api/apps/widgets/<owner_app_id>/<widget_id>/frontend/`, instead of hardcoding its source package id.

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

- remove compile-time widget import models
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

The same widget mechanism is also the correct way for the shell to host app-specific sidebar content. The default `base-shell` owns only the fixed sidebar frame and mounts standard app-owned slots for the active app.

The shell must not import app sidebar components or own app-domain sidebar state such as chat projects.

For apps that expose content in the `base-shell` sidebar:

- the shell renders `shell.sidebar.primary` as the central modular sidebar body
- the shell renders `shell.sidebar.footer` as a compact app-owned action area inside the shell's fixed footer
- on desktop, the shell's app rail is always layout-reserved; overlay sidebar mode may overlay only the sidebar body/footer details area beyond the rail, while mobile may keep the full sidebar as an overlay surface
- sidebar slots discover widgets with `host=base-shell` and the requested shell sidebar content kind
- sidebar slots prefer the widget whose `owner_app_id` matches the active app id and remain empty when the active app does not declare a matching widget
- the shell does not render a generic loading skeleton inside app-owned sidebar slots; each owning app must render the skeleton or loading state for its own sidebar widget
- `chat` declares `chat-sidebar` for `shell.sidebar.primary`
- `chat` declares `chat-sidebar-footer` for `shell.sidebar.footer`, so "new chat" remains Chat-owned instead of becoming shell logic
- each widget frontend is served from the owning app's own declared widget mount, such as Chat's `frontend/dist/widgets/chat-sidebar` or `frontend/dist/widgets/chat-sidebar-footer`
- project actions go through the chat app backend, while thread create, rename, move, delete, and delete-all actions go through core runtime thread APIs; deleting a chat project must request core runtime cleanup for every thread with that `project_id` and commit the app-owned project deletion only after cleanup succeeds
- project and thread settings panels are rendered by the chat widget, not by the shell
- optional shell navigation uses browser messaging from the iframe to ask the host to open the `chat` app with explicit scalar params such as a thread id or a new-chat request
- the shell forwards those scalar params to the mounted chat app through `maverick.app.navigate` without reloading the chat iframe
- shell-hosted widget slots must include the active workspace id in the signed widget context and remount the widget iframe when the active workspace changes
- a widget must never keep showing app-owned data loaded under a previous workspace after the host has switched workspace context
- host apps should hide iframe widget slots without unmounting them when a temporary shell panel closes, unless a widget explicitly asks to be reset
- `maverick.app.runtime-changed` and `maverick.app.frontend-changed` remount
  only the mounted app iframe and shell-hosted widget iframes whose owner id
  matches the event; unrelated app and widget frames retain their state

This preserves the visual layout while moving ownership to the app boundary:

- shell layout and app mounting belong to `base-shell`
- sidebar body and footer contents belong to the active app that declares those widgets
- chat projects, chat list state, and "new chat" behavior belong to `chat`
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

The hosted platform route `/` may be configured to serve a root shell app.
The local hosted default is `base-shell`, but that is a platform configuration value, not a special app identity in the app contract model.
Root-level browser assets required by that shell, such as `/manifest.webmanifest` and `/sw.js`, may be served from the configured root shell app's frontend artifact without making that app a core dependency.

The user may reach:

- `/apps/base-shell/` to load the shell frontend
- `/apps/chat/` to load the chat frontend directly
- `/api/apps/chat/...` for chat backend operations

Agents may use:

- chat MCP tools
- chat CLI commands
- workspace-owned skill copies seeded from chat skill templates

The core decides whether executable MCP and CLI surfaces are available in the current workspace. Runtime skills are selected from the runtime session's workspace skill catalog. The canonical default provider is the built-in Skills app, while apps may select another `skill.catalog` provider through a declared dependency such as `runtime-skills`.

The `base-shell` app may visually host the `chat` frontend.

That does not change ownership:

- shell composition belongs to `base-shell`
- chat functionality belongs to `chat`
- installation, policy, and mounting belong to the core

For the first hosted wave, the minimal built-in set is:

- `base-shell` as the mounted frontend shell app
- `chat` as the first full app with frontend, backend, MCP, CLI, and skills

`memory` and `agents` remain later-wave apps even though the architecture is already shaped to host them the same way.

### Hook versioning

Lifecycle hooks should be versioned by the app contract and resolved explicitly by the core.

The core should not guess hook names or infer hook behavior from arbitrary files.

### Hook timeouts

The contract should allow explicit timeout declarations for operations such as:

- mounted backend entrypoint execution
- install
- upgrade
- migrate
- export
- import
- validate after import
- repair after import
- health check

This prevents non-deterministic hangs during platform lifecycle operations and lets long-running provider apps declare backend request budgets without changing the core's default timeout for ordinary apps.

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

A hook that exits unsuccessfully is unhealthy. When a successful hook emits a
JSON object, Core must also honor explicit health indicators instead of treating
exit code zero as sufficient: `ok` and `operational` must be true, a
`status_code` must be successful, and a declared `status` must be one of the
healthy states. Malformed or contradictory output fails closed. Exit-only hooks
that emit no payload remain valid.

For declared HTTP sidecars, platform health combines the app hook with the live
sidecar manager state and the declared readiness result. A launcher heartbeat
cannot substitute for live manager ownership, and a process-presence check
cannot substitute for the readiness endpoint.

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
  "public_app_id": "restaurant-manager",
  "contract_version": "1.0",
  "name": "Restaurant Manager",
  "version": "1.2.0",
  "description": "Manage rooms, tables, reservations, and service state inside a workspace.",
  "publisher": "third-party-dev",
  "minimum_core_version": "1.0.0",
  "provides": [
    {
      "interface": "restaurant.records",
      "version": "1",
      "description": "Restaurant records and references.",
      "surfaces": ["backend", "mcp", "cli", "reference"]
    }
  ],
  "requires": [],
  "distribution": {
    "mode": "source_available",
    "source_access": "forkable"
  },
  "presentation": {
    "frontend_role": "workspace"
  },
  "capabilities": {
    "mcp_tools": [
      "tables.list",
      "tables.update",
      "reservations.create",
      "reservations.update",
      "restaurant_manager_reference_manifest",
      "restaurant_manager_reference_search",
      "restaurant_manager_reference_resolve",
      "restaurant_manager_reference_summarize"
    ],
    "cli_commands": [
      "tables",
      "reservations",
      "health",
      "restaurant-manager"
    ],
    "skills": [],
    "views": [
      "floor_map",
      "reservation_board"
    ],
    "reference_entities": [
      {
        "entity_type": "reservation",
        "display_name": "Reservation",
        "searchable": true,
        "resolvable": true,
        "summarizable": true,
        "deep_link_supported": true
      }
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
  "permissions": {
    "secrets": {
      "read": [],
      "write": []
    },
    "network": {
      "outbound": []
    },
    "runtime": {
      "create_sessions": false,
      "cleanup_sessions": false,
      "receive_cleanup_callbacks": false
    },
    "host": {
      "telemetry": false
    }
  },
  "compatibility": {
    "workspace_modes": ["sandbox"]
  },
  "hook_timeouts": {
    "backend_seconds": 30,
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
    "runtime_session_cleanup": false,
    "data_cleanup": true,
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
- app source skills are templates, not directly visible runtime skills
- a skill catalog app copies bundled skill templates into workspace-owned editable skill data; the built-in Skills app is the canonical provider
- provider-specific runtime installation of enabled workspace skill assets, optionally narrowed by explicit session skill ids, is handled by the selected provider adapter

Workspace agents and users must invoke core-owned and app-owned CLI and MCP capabilities through scoped core-managed workspace surfaces, not by discovering or executing files under installation-level `apps/<public_app_id>/`.
Discovery must be narrow by default so agents do not pull every command from every installed app into context.

The compact installed-app discovery shape is:

```text
maverick apps list --json
```

Core CLI discovery and invocation use:

```text
maverick core cli list --json
maverick core cli inspect <command_id> --json
maverick core cli run <command_id> ...
```

App CLI discovery and invocation use:

```text
maverick app <app_id> cli list --json
maverick app <app_id> cli inspect <command_name> --json
maverick app <app_id> cli run <command_name> ...
```

Core MCP discovery and invocation use:

```text
maverick core mcp list --json
maverick core mcp inspect <tool_name> --json
maverick core mcp call <tool_name> ...
```

App MCP discovery and invocation use:

```text
maverick app <app_id> mcp list --json
maverick app <app_id> mcp inspect <tool_name> --json
maverick app <app_id> mcp call <tool_name> ...
```

The wrapper resolves the current workspace, checks the enabled app registry, applies CLI or MCP invocation policy, resolves the app-owned data root when applicable, and then executes the declared entrypoint through the platform host.
Sandboxed workspace agents therefore do not need to know where an app source artifact lives outside the workspace.

App-owned CLI and MCP invocation policy starts from the app contract. Apps whose `compatibility.workspace_modes` exclude `sandbox` and include only `full-access` are discovered with `sandbox_agent_allowed: false` and `requires_full_access: true` for executable app surfaces. App-owned policy sidecars may tighten that floor for individual CLI commands, but they must not make a full-access-only app surface appear sandbox-safe.

When app-owned MCP tools are surfaced through the platform, the host may apply namespacing to avoid collisions with core-owned assets or assets from other apps.

Apps may also provide app-owned discovery descriptor sidecars beside their executable entrypoints:

```text
apps/<app_id>/cli/command_schemas.json
apps/<app_id>/mcp/tool_schemas.json
```

These sidecars are optional metadata for the generic core hosts. They do not add commands or tools; the executable surface still comes from `app_contract.json`. When present, the core reads them generically to populate app command/tool descriptions and JSON schemas in `list` and `inspect` responses. If absent or invalid, the core falls back to the generic app-owned description and `{"type": "object"}` schema for that command or tool instead of breaking workspace discovery.

The descriptor files must stay app-owned and declarative:

- CLI descriptors use a top-level `commands` object keyed by declared command name, with optional `description`, `argument_schema`, `required_secrets`, `secret_selectors`, execution timeout/retry metadata, and effect metadata.
- MCP descriptors use a top-level `tools` object keyed by declared tool name, with optional `description`, `input_schema`, `output_schema`, `required_secrets`, `secret_selectors`, retry metadata, and effect metadata.
- Executable app surfaces declare a conservative `effect_class` of `read`,
  `mutating`, or `destructive`. A mixed surface may additionally declare
  `effect_class_by_argument` with one top-level `argument_name`, an explicit
  `omitted_effect_class`, and an exact `value_effect_classes` map. The static
  class must equal the maximum mapped severity. Invalid metadata, an unknown
  discriminator value, or a malformed argument payload resolves to
  `unclassified`; it never inherits a read classification.
- `required_secrets` is a list of non-resource logical names declared in `permissions.secrets.read`; the core ignores undeclared names and delivers no CLI/MCP secrets when a command or tool omits both `required_secrets` and `secret_selectors`.
- `secret_selectors` is a list of declarative selector objects with `required_secrets`, optional `when` argument matches, optional `resource_type`, optional `resource_id_argument`, and optional app-mediated `resource_lookup`. The core may call the same app entrypoint with `surface=secret_selector` and no delivered secrets so the app can map opaque app-owned ids such as thread, draft, message, or attachment ids to a platform resource id before the core resolves a resource-scoped grant. A lookup result gates whether a selector is needed, but it scopes delivery only when that selector explicitly declares `resource_type`; workspace-wide logical names remain non-resource requests even when the same lookup returns a resource id for another selector.
- Apps with resource-scoped secret needs may also opt in to a read-only `surface=secret_resource_inventory` entrypoint call by setting `secret_resource_inventory: true` on one declared CLI command descriptor. The platform sends no secrets and expects only redaction-safe resources such as `logical_name`, `resource_type`, `resource_id`, optional label, provider, and status. Core Secrets recommendation surfaces use this inventory to show concrete grant issues before a grant exists; if an app does not opt in or does not implement the surface, the core falls back to existing grants and descriptor resource types.
- Descriptor metadata must not replace app-owned validation inside the entrypoint.
- Descriptor metadata must not grant policy or expose undeclared surfaces.

## Core Boundary Rule

Apps must not directly modify:

- core platform code
- other apps' data roots
- other workspaces
- platform database internals that are not part of the app contract

Apps interact with the core through declared MCP, CLI, or backend interfaces.

## Cross-App Boundary Rule

Apps do not read or write another app's internal data files or embedded databases directly.

Apps do not depend on a specific app id when they need another app capability.

Cross-app composition is allowed only through declared app interfaces and official platform-hosted surfaces:

- the provider app declares an interface in `provides`
- the consumer app declares an interface requirement in `requires`
- the workspace selects the concrete enabled provider app or apps through shell-managed setup
- the consumer calls the selected provider through official dependency backend, backend, CLI, MCP, reference, view, or widget surfaces

Composition may also happen through agents or runtime orchestration when that is the product behavior, but the same rule applies: agents and apps use official surfaces rather than another app's private files.

### Agentic runtime tool resolution

The hosted agentic runtime is a consumer of these same contracts, not a new app
host or a second tool registry. It builds a provider-safe tool catalog from the
Core CLI registry, Core MCP registry, enabled workspace app mounts, declared
app interfaces and dependency selections, grants, and the current invocation
policy. Canonical handles remain typed (`cli:`, `mcp:`, `app-interface:`, or
`core-capability:`); model-facing names are only deterministic aliases for those
handles.

Discovery never grants execution authority. Immediately before every tool call,
the Core resolves the canonical handle again against the current workspace app
binding and selected interface provider, then reapplies actor/session grants,
runtime execution mode, tool invocation policy, and the pinned execution
binding ceiling. A disabled or missing app, changed dependency selection,
revoked grant, unknown handle, or policy mismatch fails closed. Live state may
remove tools from a session but cannot add authority above its pinned ceiling.

Full-workspace hosted profiles reach CLI and MCP through discovery-first Core
wrappers rather than embedding every enabled app schema in the provider's base
catalog. Discovery filters the authoritative registry by the current actor,
workspace, execution mode, and app binding and returns a session- and registry-
bound invocation token. Invocation without that token fails; invocation with
it still re-enters the official CLI/MCP runner and rechecks policy. The same
path exposes Core collaboration/inter-agent commands and tools when authorized,
without granting them merely because their schema was discovered.

Before executing an app-owned wrapper call, the hosted runtime resolves its
exact declared effect against the nested invocation arguments. The declaration
is not authority by itself. Read-only calls may proceed only for a platform
built-in whose app id, namespaced surface, source path, exact live descriptor
digest, reparsed execution metadata, and exact executable-closure digest match
the Core-owned effect audit. The closure covers the app contract, descriptor,
entrypoint, app-local backend, and reviewed extra executable dependencies; its
paths are also part of the certified-execution TCB. Core recalculates this
authority at dispatch after validation/confirmation, so a descriptor or code
change between discovery/preflight and entrypoint execution fails before the
effect boundary. Workspace-local and external bundles fail closed at this
hosted preflight.
Admitted reads remain subject to exact-result classification and egress policy.
Mutating, destructive, or unclassified app calls are denied unless a future
Core-certified pre-effect contract explicitly governs them; an app descriptor
cannot self-promote a result to public or mint mutation authority. An operation
that persists a preview record, runtime session, cache, lazy default, or read
model is mutating even when its response resembles a read.

The runtime must invoke the selected app through its declared, platform-hosted
CLI, MCP, backend, or app-interface surface. It must not import an app module,
read `data/<app_id>/`, inspect an app-private database, infer a provider from a
well-known app id, or retain a direct entrypoint after resolution. Tool
arguments and results pass through the persistent invocation/confirmation
ledger and egress policy; protocol-private copies remain in the Core private
state service, not in app-owned storage. This preserves the same app isolation,
visibility, secret-delivery, and per-app degradation semantics used by ordinary
CLI and MCP callers.

Core-owned collaboration definitions use a separate reviewed contract rather
than app metadata: each inter-agent CLI/MCP operation declares its conservative
effect and an exact safe-result projector. Hosted projection exposes only
bounded lifecycle status, safe platform-generated ids or hashed opaque
references, counts, and booleans; prompts, messages, events, output, final
answers, labels, and cleanup details are never forwarded. If a handler returns
an invalid shape, Core emits a fixed public failure projection and never falls
back to the original bytes.

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
