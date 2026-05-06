# Core Architecture

Date: 2026-04-17

## Purpose

Define the target architecture of the Maverick core as a standalone, headless platform layer.

This document exists separately from the workspace architecture because the core must be redesigned with a clean and scalable boundary.

The goal is to describe:

- what the core is responsible for
- what the core is not responsible for
- how the core should be structured
- how the core should relate to workspaces, apps, and the runtime
- which official capability surfaces the core exposes

This document is intentionally platform-oriented.

It does not describe the internal business models of apps.

## Core Definition

The core is the platform runtime and control layer of Maverick.

It is not a business application.

It is not a content domain.

It is not the storage owner of app-owned workspace data.

The core should remain:

- headless
- standalone
- minimal
- stable
- app-agnostic

The repository layout for the core must reflect this directly:

- `core/` is the package root of the core
- the core code lives directly under `/maverick/core/`
- the core must not be nested under technical wrapper folders such as `backend/`, `runtime_backend/`, or `app/`
- the repository must not contain an ambiguous `core/core/` subtree

If internal shared utilities are needed, they should live under an explicit name such as `shared/` or `foundation/`, or be placed inside the owning domain when possible.

The core may expose more than one official executable capability surface while remaining headless:

- `mcp/`
- `cli/`

In addition, the core may ship instructional assets under:

- `skills/`

`skills/` is not an execution surface or enforcement boundary.

It is a procedural layer that explains how to use the core's executable surfaces.

## Initial Repository Conventions

The initial repository conventions should stay minimal and explicit:

- Python `3.12`
- the package root is the repository `core/` directory
- tests live under `/maverick/tests/`
- early verification should rely on standard-library-friendly commands first

At this stage the repository should prefer:

- `python3 -m unittest discover -s tests -p 'test_*.py'`
- `python3 -m compileall core tests`

before introducing heavier toolchain assumptions.

The initial scaffold should also establish a small per-domain file pattern in the domains that become active first.

Preferred starter files, only when the domain has concrete implementation behind that boundary, are:

- `service.py`
- `models.py`
- `store.py`
- `errors.py` when a domain already owns explicit failure modes

Use `routes.py` only for real HTTP route wiring that is imported by the core host. Do not keep placeholder route modules that only describe future surfaces; domain intent belongs in architecture docs until executable wiring exists.

## Persistence Boundary

The Maverick domain model is storage-agnostic.

This applies in particular to:

- `models.py`
- `service.py`
- domain-level errors and contracts

`.maverick` is rebuildable installation-local operating material. Deleting `.maverick` must not delete the authoritative control-plane database, users, workspace links, OAuth/provider credential bindings, runtime token records, or secret values.

Hosted deployments use the configured durable control-plane store. The default adapter is JSON, selected with `MAVERICK_CONTROL_STORE=json` or by omitting `MAVERICK_CONTROL_STORE`. Its default root is `data/control-plane/json`, outside `.maverick`, so `.maverick` remains rebuildable installation-local operating material.

MongoDB is an optional adapter, selected with `MAVERICK_CONTROL_STORE=mongo` or by providing `MAVERICK_MONGODB_URI`. MongoDB is an implementation choice, not the architectural identity of the core.

Rules:

- domain records must not depend on Mongo driver types
- services should depend on store protocols or equivalent persistence contracts, not concrete Mongo adapters
- adapter-specific query shapes and update semantics must stay inside store adapters
- bootstrap wiring may choose JSON, MongoDB, or another explicit adapter for platform-owned control-plane collections
- the selected control-plane adapter must not become the storage owner for app-owned workspace data
- migrating between control-plane adapters must be an explicit operator action with dry-run and validation; backend startup must not silently move or delete control-plane state
- adapter migration must preserve the source adapter data during target preparation so rollback remains an operator configuration decision until cutover has been verified
- adapter migration surfaces belong to the core HTTP, CLI, and MCP layers; admin apps may call them but must not own adapter semantics or persistence code
- a prepared adapter migration must not hot-swap stores inside a live process; cutover happens on backend restart so exactly one control-plane adapter is mounted at a time
- deletion of old adapter storage must be post-cutover cleanup, scheduled only after target write and configuration update, and executed only after the restarted backend is healthy
- generated service environment files contain durable secrets and must not be stored under `.maverick`
- the control-plane database is not encrypted as a whole; sensitive values must use the core secret domain instead of raw database or environment fields
- database passwords, runtime signing secrets, widget signing secrets, provider API keys, and OAuth client secrets must be stored as core secret values or bootstrap secret refs, not as raw `.env` values
- the secret-store encryption key should be loaded from a local key file such as `MAVERICK_SECRET_KEY_FILE`; `MAVERICK_SECRET_STORE_KEY` is a development/backward-compatibility fallback

This keeps the core open to future adapters such as PostgreSQL, SQLite, or another control-plane store without reshaping the domain model.

### Secret Handling

The `core.secrets` domain is the platform-wide secret system. It owns encrypted secret value envelopes and authorization rules for delivering scoped values to apps, providers, runtime sessions, and platform infrastructure code.

The core must not introduce a separate product secret system for infrastructure credentials. Pre-adapter infrastructure secrets, such as a MongoDB password needed before a Mongo connection can be opened, may live in a local bootstrap secret store backed by the same `SecretDocumentStore` envelope format and the same secret key loader.

Workspace agents must not receive filesystem access to `.env.maverick`, secret key files, bootstrap secret files, or raw control-plane secret value storage. Full-access sessions are operator break-glass sessions and should be treated as capable of reading host-level secrets.

## Core Responsibilities

The core is responsible for the following domains.

### 1. Identity and access

The core owns:

- users
- authentication
- sessions
- workspace membership
- workspace governance

This includes who can enter the system and which workspaces they can access.

The control-plane persistence for these records may target JSON, MongoDB, or a future adapter, while keeping the domain records and service layer independent from HTTP, framework-specific exceptions, and database-driver-specific types.

### 2. Workspace registry and governance

The core owns:

- workspace existence
- workspace metadata
- workspace governance state
- workspace quotas and limits
- workspace policy enforcement

The core does not own the internal business data of a workspace.

The initial model should keep these records distinct:

- workspace registry record
- workspace membership record
- workspace governance record
- workspace quota record

The execution-policy domain may read these records, but it should still compute the effective runtime policy separately.

Only platform admins may create new workspaces through the hosted platform API.

Platform members may list and enter workspaces where they have active membership, but they must not create workspace records. Workspace assignment for members is an admin control-plane action.

### 3. App installation and hosting

The core owns:

- local installation state of apps
- app enablement state per workspace
- app lifecycle orchestration
- app hosting contracts
- app runtime hooks such as install, upgrade, migrate, uninstall

The core does not own app business data.

The app-hosting domain should keep at least these concepts distinct:

- app source or project material
- app distribution artifact
- app installation record
- workspace app enablement or binding state

These concepts are related, but they are not interchangeable.

Examples:

- a server app store artifact under `/apps` may be known to the installation without being enabled in every workspace
- a workspace-local app project may exist under `workspaces/<workspace_id>/apps/` without being installed yet
- an installed app may be disabled in one workspace while remaining enabled in another

This separation is required to keep lifecycle orchestration, compatibility checks, and uninstall or reinstall behavior deterministic.

The core also owns the generic resolver for app interface dependencies declared in app contracts.

This resolver is deliberately app-agnostic:

- provider apps advertise typed interfaces in `provides`
- consumer apps declare typed requirements in `requires`
- workspace users select concrete enabled provider apps per consumer alias
- the core validates interface id, version compatibility, provider visibility, and workspace enablement
- the core persists only workspace-scoped dependency selections, not app product data

The core must not special-case app ids such as `fleet`, `agents`, `gallery`, or a file provider app. A cross-app consumer depends on interface types such as `agent.catalog` or `file.preview`; the shell and the consumer app receive resolved provider ids after the workspace selection is made. If a provider app is disabled or uninstalled, the selection becomes stale until setup is corrected.

The app-hosting domain must also separate public app identity from workspace-local binding identity.

- `public_app_id` identifies the distributed app artifact or catalog entry declared by the app contract.
- `local_app_id` identifies one workspace binding, app-owned data namespace, and user-facing app instance inside that workspace.
- `mount_app_id` identifies the concrete route namespace used by mounted HTTP, WebSocket, CLI, MCP, and widget surfaces, normally equal to `local_app_id`.

Built-in apps may use the same value for all three, but the core must not require that equality. App Store install, fork, dependency selection, app registry responses, lifecycle hooks, and workspace data paths must preserve the distinction so one workspace can bind a public app, fork, or alternate provider under a distinct local id.

The installation-level `/apps` directory is the server-managed app store and trusted artifact cache.

It may contain built-in apps, commercial sealed apps, source-available store apps, and validated app bundles.

Remote catalog ingestion is still a core app-hosting responsibility. The official public catalog defaults to `https://maverick-app-store.versy.ai` and may be overridden per installation with `MAVERICK_APP_STORE_URL`. The app-store UI may request installation or uninstall for selected workspaces, but the core must own the authenticated operation that downloads a remote bundle, verifies its checksum, stages it under `apps/_bundles/<app_id>/<version>/`, registers the source as an `external_bundle`, creates workspace bindings for the authorized target workspaces, reports current workspace installation state, reports installation-level server app sources whether or not they are installed in the current workspace, installs already-registered server app sources into selected workspaces without copying source into the workspace, reports workspace-local app projects for the selected workspace context, and removes bindings during uninstall without deleting app-owned data.

The workspace-level `workspaces/<workspace_id>/apps/` directory is editable workspace material.

It should contain only workspace-created apps and explicit workspace-local forks of store apps.

Installing a store app into a workspace should create a binding to the store artifact by default.

It should not copy source into the workspace unless the distribution contract allows forking and the user or an authorized agent requests customization.

The core app-hosting domain should model at least these distribution modes:

- sealed
- source-available
- workspace-local

Promotion of a workspace-local app into an installation-level app is a core app-hosting operation, not an app-owned behavior. The initial promotion path is admin-only, copies the workspace-local source tree into `apps/<app_id>/`, rewrites only the copied contract's distribution declaration to `sealed` or `source_available/forkable`, registers the copied app as a `platform` source, and leaves the workspace-local project unchanged. The control plane must also persist ownership lineage: the workspace-local project creator becomes the promoted app owner for that `app_id`, later promotions of the same `app_id` are treated as owner-only updates, and a fork that wants to publish independently must use a different `app_id`.

This lets the core host closed commercial apps, open-source store apps, and fully local agent-created apps without changing the app surface model.

Implementation files in `core/apps/` should keep lifecycle responsibilities separate.

Recommended split:

- `registration.py` owns app source and workspace-local project registration
- `remote_store.py` owns remote catalog bundle staging and authenticated install orchestration
- `forks.py` owns workspace-local fork creation and provenance
- `installation.py` owns initial store and workspace-local app installation
- `status.py` owns enable, disable, uninstall, and purge transitions
- `reinstall.py` owns reattachment and import-recovery style reactivation
- `upgrades.py` owns upgrade, migration, rollback, and explicit rebase semantics
- `hook_payloads.py` owns canonical lifecycle hook context construction
- `health.py` owns app health probe execution
- `contracts.py` may remain a small public facade over contract builders, parser, serializer, records, and validation modules

`service.py` may remain as a public app-hosting facade, but it should not contain full lifecycle implementation.

### 4. Runtime orchestration

The core owns the generic runtime model for agent execution.

This includes:

- runtime lifecycle
- turn execution
- message delivery to runtime
- runtime status updates
- execution state transitions
- orchestration of tool execution
- process lifecycle
- runtime sessions that can carry an app-provided materialized `system_prompt`
- runtime sessions that can carry selected `skill_ids` when an agent type narrows the workspace default
- runtime sessions that can identify the app surface that created them with `source_app_id`
- runtime turns that can carry structured app references by stable `app_id` when an app UI parses human-facing mention text

These fields are generic runtime configuration. They are not an Agents app dependency.

An app such as `agents` may compose prompt text and pass it to the runtime session creation surface, but the core must not parse app-owned role files or know agent type semantics.

The core does not define workspace-specific agent personas as built-in runtime types.

### 5. Inter-agent communication

The core owns the infrastructure that allows multiple agents to coordinate.

This includes:

- delegation delivery
- inter-agent message transport
- status propagation between agents
- coordination queues and retries
- delivery reconciliation
- cross-agent operational routing

This is a core product capability, not an app concern.

### 6. AI provider management

The core owns the abstraction layer for model providers and model backends.

This includes:

- provider definitions
- provider credentials and secret bindings
- provider capability metadata
- model selection contracts
- runtime adapter selection

`Codex` is one supported runtime backend, not the architectural definition of the core itself.

The system must be designed so that other backends can be supported without changing the app model.

The core must also be installable and bootable with no AI provider configured or available.

No provider is a valid initial platform state, not an installation failure.

Provider selection is an explicit later setup or admin action. Once configured, the persisted provider selection is the authoritative runtime backend choice for runtime turns, provider status, and recovery automation.

Provider status APIs should represent this state directly:

- `active_provider: null` when no provider is configured or the configured provider is unavailable
- a stable `blocked_reason`, such as `no_provider_configured` or `provider_unavailable`
- enough available-provider metadata for an authorized setup flow to choose a provider later

Runtime creation, turn execution, and recovery work that need an AI backend should fail on use with a recoverable provider-status error when no provider is configured. They must not silently fall back to Codex or any other first registered adapter.

Runtime-style providers must preserve conversation continuity inside a runtime session.

For Codex specifically, the core must use the Codex app-server protocol, not one-off `codex exec` calls.

The Codex adapter should own the provider-specific protocol:

- start one local `codex app-server --listen stdio://` process for the runtime session
- initialize the app-server process
- prepare a session-local `CODEX_HOME` under the runtime root before launch
- populate that runtime home from a configurable operator Codex home, using `MAVERICK_CODEX_HOME`, `CODEX_HOME`, or the current user's default Codex home
- copy only required identity and configuration material into the runtime home, such as Codex auth, version, installation identity, sanitized config, and rules
- avoid hardcoded host paths for Codex identity or configuration
- keep runtime skills materialized separately through the workspace Skills app data rather than loading user-global or core-bundled skills into every runtime
- create a persistent Codex thread with `thread/start` when no provider thread exists
- resume the existing Codex thread with `thread/resume` when a runtime session already has a provider thread id
- submit each user turn with `turn/start` against the same provider thread id
- interrupt active work with the provider's turn interrupt method
- keep the provider thread id as provider-runtime state, not as chat-app state
- terminate the local provider process as soon as a runtime session has no queued or active turns, while keeping the provider thread id so the next turn can restart the backend and resume the same conversation

The core runtime session remains the Maverick-owned lifecycle container.

The provider thread is the selected backend's conversation container.

Those two ids are intentionally different but must be linked by the core runtime state so a chat can be reopened, a browser can refresh, and the next turn still reaches the same provider conversation.

The core also owns the workspace chat thread catalog that points at runtime sessions.

A chat thread is the user-visible runtime conversation record. It stores the thread id, linked `runtime_session_id`, title, availability, source app metadata, and optional project id. Apps such as `chat` may render or update that record through core runtime APIs, but they must not persist a second app-owned thread catalog or delete runtime sessions themselves.

### 7. Execution policy

The core owns:

- sandbox policy
- full-access policy
- runtime execution mode enforcement
- workspace execution boundary enforcement

The workspace domain may declare metadata and governance state, but the effective runtime mode must still be resolved by `execution_policy/`.

For the `default` workspace, the effective runtime mode is `full-access` by default when both platform policy and workspace governance allow it.

For non-default workspaces, the effective runtime mode remains sandbox-only regardless of runtime request.

### 8. Secret management

The core owns:

- secret storage
- secret resolution
- secret bindings
- secret delivery to runtime under controlled conditions

The core does not allow apps to own the secret values themselves.

### 9. Recovery and operational safety

The core owns:

- runtime recovery
- failed-start recovery
- migration failure visibility
- operational health checks
- platform-safe error handling

### 10. Runtime interface

The core exposes the generic runtime-facing interface for:

- sending an agent message
- accepting a client-generated message id for idempotent UI reconciliation
- reading current turn state
- receiving turn updates
- receiving runtime events

This is infrastructure.

It is not the same thing as the chat domain.

### 11. Capability surfaces

The core owns its official platform-facing and operator-facing capability surfaces.

These include:

- `mcp/` for structured tool access
- `cli/` for local command-oriented operations

The core may also own:

- `skills/` for procedural guidance on using core capabilities correctly

These are not separate products.

`mcp/` and `cli/` are executable surfaces of the same core platform.

`skills/` is a non-executable instructional layer attached to those surfaces.

The same platform host framework should also be able to expose app-contributed MCP, CLI, and skill surfaces once those apps are installed and enabled.

Apps may expose reference tools through their declared MCP and CLI surfaces so other apps can link to app-owned records without reading app-private storage. The core's responsibility is generic: validate contracts, register enabled app surfaces, enforce workspace policy, invoke the declared entrypoints, and expose discovery metadata. The core must not know how to search business records, chat threads, gallery files, memory nodes, or any other app-specific entity.

The common reference tool convention is:

- `<app_id>_reference_manifest`
- `<app_id>_reference_search`
- `<app_id>_reference_resolve`
- `<app_id>_reference_summarize`

CLI surfaces should mirror the same behavior with lightweight commands such as:

```text
<app_id> references manifest
<app_id> references search
<app_id> references resolve
<app_id> references summarize
```

Every app may expose at least a reference manifest. Apps with no referenceable entities should return an empty manifest rather than forcing the core or another app to infer that from missing app-specific behavior.

## What The Core Is Not

The core should not own:

- memory content
- chat content as a domain model
- business record content
- dynamic view content
- checklist content
- app-owned persisted records
- app-owned indices
- workspace-local app databases
- workspace-local app file structures
- agent persona definitions for a workspace

The core should also not force every operation through only one surface.

These belong to apps and workspaces, not to the core.

The core should also not be modeled as if it were a generic web app scaffold.

So the repository should not describe the core through names such as:

- `backend/`
- `runtime_backend/`
- `app/`

unless one of those names refers to a real product domain, which is not the case for the Maverick core.

Those names describe implementation posture, not product architecture.

## Core Versus Chat

The core should expose the runtime message and turn interface.

The chat app should own:

- persistent conversations
- thread model
- chat UI
- chat-specific organization
- chat-specific storage

So:

- runtime interaction = core
- chat domain = app

## Core As Platform Host

The public Maverick host should run the core, not one particular app.

In deployment terms, the intended model is:

- a public deployment hostname reaches the core platform host
- the core mounts enabled app surfaces
- the core enforces auth, workspace context, and policy before dispatching to app surfaces

This means the core is the host and orchestrator for apps, not the owner of the app domains themselves.

The core should be able to mount:

- app frontends
- app backends
- app MCP surfaces
- app CLI surfaces
- app skills
- app widget frontend surfaces

The platform should not force every app into the same UI or runtime style, but it should remain the owner of:

- routing
- policy
- mounting
- installation and enablement checks
- workspace-aware dispatch

Widget mounting follows the same platform-host rule.

An embeddable widget is not core UI and not direct app-to-app communication.

The core is responsible only for:

- validating widget declarations in app contracts
- exposing enabled widget metadata through the workspace app registry
- mounting widget frontend surfaces through controlled routes
- enforcing auth, workspace context, install state, and enablement before loading a widget
- providing deterministic routing metadata so host apps can find compatible widgets

The core must not:

- render chat widgets itself
- own widget business state
- let one app import another app's source tree
- special-case a specific widget owner inside the runtime or registry

For example, if chat embeds a checklist widget:

- chat owns the transcript host
- checklists owns the widget renderer and checklist data
- core owns registry, routing, auth, and workspace enablement

## Everything Above The Core Is An App

The Maverick product shell should also be modeled as an app.

That means the system may include apps such as:

- `base-shell`
- `chat`
- `agents`
- `skills`
- `app-store`
- `memory`

The `base-shell` app may host the frontend of other apps, but it is still only an app mounted by the core.

The `base-shell` app owns the product shell frontend and should preserve the current Maverick shell interaction model while using core protocols.

That means:

- preserve the user-facing shell design and interaction model where still relevant
- do not copy app-specific API contracts into the core
- do not move shell-specific composition logic into the core
- treat `base-shell` as a sealed server app store artifact under `/apps/base-shell`
- serve its production frontend from its declared build output, currently `frontend/dist`
- let the shell discover mountable apps through the registry instead of static app assumptions

The current `base-shell` implementation is a React/TypeScript app-owned frontend built with Vite.

The core serves only the declared `frontend/dist` artifact and exposes generic shell-facing control-plane APIs.

The first shell-facing API slice is intentionally core-generic, not `base-shell` specific:

- `/api/session`, `/api/auth/login`, and `/api/auth/logout` expose the current user session
- `/api/admin/users` and `/api/admin/workspaces` expose admin-only identity, password reset, role, and workspace assignment management
- `/api/admin/workspace-apps` exposes admin-only workspace app installation and enablement management
- `/api/workspaces` and `/api/workspaces/active` expose workspace list, creation, and active workspace selection
- `/api/apps` exposes enabled app registry records for the active workspace
- `/api/app-store/apps`, `/api/app-store/server-apps`, `/api/app-store/installations`, `/api/app-store/install`, `/api/app-store/install-server`, `/api/app-store/install-local`, and `/api/app-store/uninstall` expose authenticated remote catalog reads, installation-level server app source reads, workspace installation state, remote app installation, registered server source installation, workspace-local app installation, and workspace binding removal
- `/api/status` exposes platform status for the active workspace
- `/api/providers/active` and `/api/runtime/status` expose active runtime provider and runtime sessions
- `/api/settings/platform` exposes read-only platform/workspace/provider/runtime/recovery metadata for settings UI
- `/api/settings/runtime-sessions` and `/api/settings/runtime-sessions/clear` expose the runtime-session inventory in the cleanup scope of the active workspace and the cleanup action used by shell settings workflows
- when the active workspace is `default`, only a platform admin may use settings cleanup and the scope expands to every workspace on the server
- when the active workspace is not `default`, cleanup stays limited to that active workspace and is available to platform admins plus admins of that workspace
- cleanup is destructive by design: it terminates provider processes, cancels queued or active turns, removes runtime-session records, turns, events, core-owned state, and the runtime session filesystem root, then invokes app-declared cleanup hooks for app-owned data linked to that runtime session
- `/api/recovery/status` and `/api/recovery/health` expose operator recovery inspection, while `/api/recovery/restart-runtime` is the controlled runtime-restart action surfaced to trusted workspace callers through the core recovery flow

These APIs are platform capabilities that any suitable shell app may consume.

They do not make the core own shell UX, chat project organization, or app-specific settings panels.

When `/api/settings/platform` reports `active_provider: null`, `base-shell` may show an initial provider setup dialog backed by `/api/providers/active`. That dialog is shell UX over generic provider-selection governance; it must not silently select a provider in browser state or make Chat own the workspace-wide provider choice.

Admin-facing apps must still stay app-agnostic at the core boundary.

For example, a `user-admin` app may provide the UI for creating users, resetting a user's password, changing platform roles, and assigning users to workspaces, but the records remain owned by the core identity and workspace governance domains.

Admin app visibility is enforced through generic app contract visibility metadata, not through app-specific branches in the core.

The core filters `/api/apps`, mounted app routes, app-owned widgets, CLI discovery/invocation, MCP discovery/invocation, and compact app discovery according to `visibility.platform_roles`, `visibility.workspace_roles`, and declared capability requirements.
An app that declares `visibility.workspace_roles: ["admin"]` is not listed or mounted for ordinary workspace members, even when the workspace admin is not a platform admin.

The same visibility policy applies to App Store read surfaces.
`/api/app-store/apps` must hide catalog entries whose declared visibility excludes the current user.
`/api/app-store/server-apps` must hide registered server app sources whose resolved contract visibility excludes the current user, unless the user is a platform admin.
`/api/app-store/installations` must hide installed and workspace-local app rows whose resolved app contract excludes the current user, unless the user can manage apps for that workspace.
Workspace-local app projects without a workspace binding are management material and should be visible only to platform admins or workspace admins.

Runtime sessions carry ownership metadata such as `owner_user_id`, `created_by_user_id`, `creator_runtime_session_id`, source app id, and a small platform-minted structured grant list. Destructive runtime operations such as cleanup, interrupt, and restart must authorize against that record: the owner may operate their own session, a workspace admin may operate sessions in that workspace, platform admin authority is a separate explicit override, and any non-owner grant must identify the operation plus a concrete grantee principal. Workspace membership alone is not enough to delete or interrupt another user's runtime session, and client-submitted runtime creation payloads must not mint cleanup, interrupt, or restart grants. When an enabled app backend, CLI command, or MCP tool creates a runtime session while handling an authenticated user invocation, the core must stamp that human caller as both `owner_user_id` and `created_by_user_id`; trusted platform invocations without a user may leave those fields empty and rely on explicit admin or grant authority for later destructive operations.

Workspace-wide selections such as provider/model choice and app dependency bindings are governance state. They require workspace admin or platform admin authority; ordinary workspace members may read the resulting status needed to use the workspace, but they must not change the setting for everyone.

Workspace app installation and enablement are separate control-plane states.

An installed workspace app has a binding in the workspace and can be managed by an admin without deleting its data. A disabled installed app remains attached to the workspace, but it must not be listed in `/api/apps`, mounted through `/apps/<local_app_id>/`, exposed through `/api/apps/<local_app_id>/backend`, or exposed through app-owned widgets, CLI, MCP, or skills. Only enabled workspace app bindings are visible to normal workspace users and served by the platform host.

For hosted and local deployments, bootstrap credentials and signing/encryption material are installation configuration, not development defaults. The core must require the bootstrap admin credential plus refs or protected key-file paths for signing and encryption material before booting a hosted platform:

- `MAVERICK_ADMIN_USERNAME`
- `MAVERICK_SECRET_KEY_FILE`
- `MAVERICK_BOOTSTRAP_SECRET_STORE_ROOT`
- `MAVERICK_RUNTIME_API_SECRET_REF`
- `MAVERICK_WIDGET_CONTEXT_SECRET_REF`

The installer generates and preserves the secret-store key file and bootstrap secret values outside `.maverick`, defaulting the service env file to `.env.maverick` and the bootstrap secret files to `data/bootstrap-secrets/` for local installs. Systemd units load the env file through `EnvironmentFile=`.
Static known values for admin credentials, runtime tokens, widget context tokens, or secret-store encryption are permitted only in explicit test invocations that set `MAVERICK_ALLOW_INSECURE_TEST_DEFAULTS=1`. `MAVERICK_ENV=development`, `MAVERICK_ENV=dev`, and `MAVERICK_ENV=test` must not by themselves authorize static credentials or signing secrets. `MAVERICK_RUNTIME_API_SECRET`, `MAVERICK_WIDGET_CONTEXT_SECRET`, and `MAVERICK_SECRET_STORE_KEY` remain compatibility/dev fallbacks, not hosted-install defaults.
At hosted startup, `MAVERICK_ADMIN_PASSWORD` and `MAVERICK_ADMIN_PASSWORD_REF` are optional bootstrap inputs. If a bootstrap admin password or password ref is configured, startup creates or repairs the configured admin password credential. If no bootstrap password is configured, startup may create or preserve the configured admin user without a password credential and must not reset an existing admin password. This keeps normal boot independent from plaintext admin credentials.
Operator and developer CLI wrappers such as `scripts/maverick` must never apply bootstrap admin password repair while bootstrapping state for discovery, app frontend builds, CLI, or MCP calls. Those processes may inherit test or shell environment variables and can run against the live repository root; applying `MAVERICK_ADMIN_PASSWORD` there would silently rewrite the production admin credential outside the explicit identity recovery command.
Admin password recovery is an explicit operator-only core CLI action. It may create or reset the configured admin user's password directly in the durable identity store, revokes existing sessions for that user, and never persists the plaintext recovery password in `.env`, `.maverick`, or bootstrap secret files.

Cookie-authenticated unsafe HTTP methods must carry browser-controlled same-origin proof. If a request with session cookies uses POST, PUT, PATCH, or DELETE and lacks both `Origin` and `Referer`, the platform host must reject it unless a future explicit CSRF token mechanism replaces that proof. A client-controlled custom header is not a CSRF boundary.

The shell may visually frame mounted app frontends, but it must not hardcode optional product apps that are not installed in the current workspace.

This keeps the product shell replaceable and prevents product UI concerns from leaking into the core.

Local hosted bootstrap must rebuild enabled built-in app bindings for every active workspace in the workspace registry, not only for `default`. Workspace selection and `/api/apps` must remain consistent after a host restart because the workspace registry is durable control-plane state while the local app registry is reconstructed at process startup.

Mounted app frontends may request generic shell navigation by posting an explicit app-open message to their parent frame. The shell may honor that request only by opening another app from the workspace app registry; the message is not a filesystem, backend, or privilege boundary.

The completed `base-shell` implementation intentionally carries only shell-owned behavior:

- local browser session state such as active app and sidebar state
- reusable shell UI primitives used by the app itself
- registry-driven app catalog and mounted app iframe surfaces
- login/session UI backed by core identity/session APIs
- workspace selector backed by core workspace APIs
- provider/runtime indicators backed by core provider/runtime APIs
- Tutorial and Settings dialogs backed by currently available core metadata

It must not absorb chat project buttons, chat orchestration, retrieval settings, push notifications, or app-specific backend controls into `base-shell`.

Project organization belongs to the chat app because projects are chat-domain state, not shell or core platform state.

If a future product shell needs to show chat projects or conversations in its sidebar, it must do so by mounting a chat-owned widget through the generic widget registry. The default `base-shell` sidebar does not reserve space for that chat widget.

If the product shell needs to show app shortcuts in its sidebar, it must do so by mounting an App Store-owned widget through the same generic widget registry.

`base-shell` may keep a fixed `Apps` entry that opens the App Store, but it must not own or hardcode the shortcut list. Pinned app shortcut state belongs to `app-store` workspace data and is mutated through the App Store app's own backend surface.

The intended first shape is:

- `base-shell` owns the generic sidebar widget slot for app shortcuts, and that slot fills the available sidebar height between shell navigation and footer controls
- `app-store` owns an `app-shortcuts` widget compatible with `shell.sidebar.apps`
- `chat` may own a `chat-sidebar` widget for shells that choose to expose chat navigation, but default `base-shell` does not mount `shell.sidebar.primary`
- chat sidebar widgets, when mounted by a shell variant, load and mutate thread records through the core runtime thread surface and use chat-owned backend surfaces only for chat projects and view state
- `base-shell` keeps the iframe-mounted widget alive while the sidebar is hidden, so opening and closing the menu does not reload app-owned widget state
- `base-shell` may react to a generic browser message asking it to open an app with scalar navigation params, but it must not import chat code or call chat-private internals
- `base-shell` keeps mounted app iframe documents alive after first open and sends app navigation through a generic `postMessage` protocol instead of rebuilding iframe URLs for every internal app route
- `base-shell` listens to the core app-event WebSocket and may remount only the affected app iframe after a successful official frontend rebuild event
- `chat` owns project settings panels and "new chat" UI behavior; thread rename, move, delete, and delete-all operations call core runtime thread APIs

Mounted app navigation is intentionally message-driven.

The shell may activate an app frame and send:

```json
{
  "type": "maverick.app.navigate",
  "app_id": "chat",
  "params": {
    "thread_id": "thread_123"
  }
}
```

The shell must not append chat-specific query strings such as `thread_id` to the mounted iframe URL after the app is loaded.

This keeps iframe identity stable, prevents full app reloads during sidebar navigation, and preserves app-owned in-memory state.

The receiving app owns the meaning of the scalar params.

The core and shell only provide the generic delivery mechanism.

If an app asks the shell to open a workspace-local app from a workspace that is not currently active, the open request must include the target `workspace_id`.

The shell may switch the active workspace through the generic workspace API, reload the app registry, and then mount the requested app.

This does not make workspace-local apps cross-workspace capabilities: the app still mounts only after the shell enters the workspace that owns the app binding.

One-shot navigation commands must be idempotent at the receiving app boundary.

For example, `chat` may accept `{ "new_chat": true }` from a shell widget, but that request must include a unique app-owned request id such as `new_chat_request_id`, and the chat app must consume that id only once. This prevents repeated iframe ready/navigation handshakes from creating duplicate empty threads.

Creating a new empty chat thread must not preallocate or start a runtime session. A runtime session is created only when the first user message or an explicit runtime-session handoff requires execution.

When the `agents` app is installed and enabled in the active workspace, `chat` may use the Agents backend surface to initialize a new empty chat with the workspace common prompt. This is an app-to-app use of an official app backend surface, not a core dependency: the core must not read Agents data, parse role files, or special-case the Chat/Agents relationship.

For example, the Agents app may create a generic core runtime session and ask the shell to open Chat with:

```json
{
  "type": "maverick.app.open-app",
  "app_id": "chat",
  "params": {
    "runtime_session_id": "runtime_session_123",
    "agent_label": "Backend Systems Engineer",
    "agent_type_id": "backend-systems-engineer",
    "thread_title": "Backend Systems Engineer"
  }
}
```

The shell should only activate Chat and deliver the scalar params.

Chat asks the core runtime thread API to create or reuse the thread record for that runtime session because thread state is core runtime data.

If that creates or changes thread data that is also represented by an embedded widget, the widget receives the new thread catalog through `WS /ws/runtime/threads`. The app may emit an app-owned UI message only to mirror active selection:

```json
{
  "type": "maverick.chat.active-thread-changed",
  "owner_app_id": "chat",
  "active_thread_id": "<thread_id>"
}
```

The shell may forward that selection message to mounted widgets owned by the same app.

The shell must not inspect, mutate, or reconstruct the app data.

The receiving widget owns the refresh behavior.

Mounted apps should also emit:

```json
{
  "type": "maverick.app.ready",
  "app_id": "chat"
}
```

The shell should treat this as a lifecycle acknowledgement and resend the latest pending navigation params for that mounted app.

This keeps navigation reliable after login/logout cycles and cold iframe mounts without switching back to query-string driven iframe reloads.

### Current Product Assumptions To Remove

The current code keeps the core/app boundary clean at the import level: `core/` does not import app frontend code, and `base-shell` does not import `chat`.

There is still a product assumption that should be removed before calling the core and apps fully standalone:

- `base-shell` currently prefers/pins `chat` as the initial app in local browser state instead of deriving the first-open app from workspace preference or registry metadata

Built-in app bootstrap is contract-driven and scans installation-level app roots that contain `app_contract.json`.
Future production packaging may still narrow the default installed set through installation configuration or app-store metadata, but the core bootstrap no longer names individual app ids for discovery.

The root `/` platform route is configured through the hosted platform state.
The local hosted default is `base-shell`, and operators may override it with `MAVERICK_ROOT_SHELL_APP_ID`.
That default is a bootstrap configuration value, not a core dependency on the shell app's internals.

These assumptions are not direct code-contamination problems because they do not import app internals into core.

They are product defaults encoded in code, and they should become configuration or registry-driven policy.

The rule is:

- the core is the platform host
- every product extension above the core is an app

## Human And Agent Interfaces

Apps in Maverick are not only visual applications.

An app may need to serve:

- a human user through `frontend/`
- app-specific backend logic through `backend/`
- agents through `mcp/`
- operators or agents through `cli/`
- agent guidance through `skills/`

This is the intended target model.

The real value of an app is not only that it renders a screen.

The real value is that it extends the platform for both:

- humans
- agents

under one mounted app contract.

## Deployment Surfaces

For the first real hosted deployment, the intended shape is:

- `nginx` as the public ingress
- one main core service behind the deployment hostname
- one independent rescue service that does not depend on the main backend staying alive

The default assumption should not be one `systemd` service per app.

At least in the first implementation wave, apps should be mounted by the core rather than deployed as independent public services by default.

This keeps the architecture aligned with the platform-host model.

The rescue path is different.

It should remain independently deployable so the user can still reach recovery tooling even if the main platform service is unhealthy.

For the first hosted wave, this means:

- one main core host mounted at the deployment hostname
- one separate rescue host
- one backend watchdog timer that probes the main core host from outside the main backend process
- a minimal app set mounted by the core:
  - `base-shell`
  - `chat`
  - `agents`
  - `skills`
  - `app-store`

The main core host should run through the ASGI platform host so HTTP and WebSocket traffic share the same `PlatformState` and persistence adapters.

The ASGI host must implement `lifespan` shutdown so active mounted app backend subprocess trees are terminated cooperatively during service restarts instead of relying on `systemd` timeout kills.

The WSGI host may remain useful for isolated local smoke checks, but it is not the production runtime host once WebSocket is part of the agent communication surface.

`nginx` must forward `/ws/` and WebSocket-capable API routes such as `/api/apps/events/ws` with `Upgrade` and `Connection: upgrade` headers to the main core host.

The backend watchdog is deployment infrastructure, not app runtime behavior.

It should run as a small `systemd` timer that probes the main backend health endpoint once per minute and persists downtime state under installation-local recovery state. If the backend is continuously unhealthy for at least 300 seconds, it may launch one autonomous rescue agent from the independent rescue path with full host access, using the authoritative provider configured for platform recovery. The rescue prompt must require a forward minimal fix against the current tree, must forbid git rollback operations such as `git reset`, `git checkout`, or `git restore`, and must preserve unrelated user changes.

If no provider is configured or the configured provider is unavailable, the watchdog must not assume Codex. It should persist and expose a clear blocked state, such as `blocked: no_provider_configured`, without preventing the core from being installed or booted.

The watchdog resolves the recovery provider from durable installation-local provider selection state, not from an independent raw shell command. Provider adapter configuration may still supply provider-specific command details for the selected provider, but that command is not a separate source of recovery authority when no provider is configured.

The rescue agent should diagnose the current code and deployment state, apply the smallest fix that restores the backend, run targeted verification, restart `maverick-core.service` when systemd is available, and verify the health endpoint. It must not manually recreate product runtime agents. Runtime session spin-back remains the backend startup recovery responsibility described in the runtime recovery section.

## Target Core Tree

The target core tree should look like this:

```text
/maverick/
  core/
    api/
    main.py
    identity/
    workspaces/
    apps/
    runtime/
    inter_agent/
    providers/
    execution_policy/
    secrets/
    recovery/
    observability/
    mcp/
    cli/
    skills/
```

Notes:

- `api/` is the application bootstrap surface for backend or HTTP process wiring
- `mcp/` and `cli/` are executable capability surfaces of the same core
- `skills/` is instructional only
- every other top-level directory under `core/` should represent a real Maverick core domain

## Core Versus Agents App

The core owns the runtime and provider layers.

One supported runtime backend today is:

- `Codex`

The core should not encode "Codex" as the product-wide definition of an agent type.

The architectural distinction is:

- runtime abstraction = core
- backend provider implementation = core
- workspace agent definition = app

The app `agents` owns:

- workspace-specific agent definitions
- prompt compositions
- role-specific system prompts
- shared prompt templates
- catalog of agents visible in a workspace

So:

- runtime execution and provider selection = core
- workspace agent definitions = app

## Core Versus Memory

Memory is entirely an app concern.

The core should not own:

- memory notes
- memory links
- memory indexing semantics
- memory retrieval semantics

If a memory app exists, it owns those concepts inside the workspace.

## Architectural Boundary

The core should interact with workspaces and apps through stable contracts.

That means:

- the core hosts and orchestrates
- the app owns its data and domain model
- the workspace contains app-owned persisted state

The core must not depend on:

- app-specific schema internals
- app-specific embedded database layout
- app-specific indexing internals

This boundary must remain true across:

- `mcp/`
- `cli/`

and must not be weakened by instructional assets under `skills/`.

## Filesystem Position

The core lives at installation level under:

```text
/maverick/core/
```

It is outside:

- workspace data
- workspace app data
- workspace storage

The core must never become a general-purpose dumping ground for workspace-derived content.

## Core Structure Direction

The target structure of the core should separate the following concerns.

The structure should optimize for:

- small files
- narrow responsibilities
- obvious folder ownership
- naming that reads well in long file trees
- minimal need to open a file to guess what it does

The core should prefer many small explicit modules over a few generic buckets.

### `identity/`

Owns:

- users
- auth
- sessions
- membership logic

### `workspaces/`

Owns:

- workspace registry
- governance
- quotas
- workspace policy

### `apps/`

Owns:

- app hosting
- install state
- lifecycle orchestration
- compatibility checks

This does not mean app business logic lives here.

It means the platform side of app management lives here.

### `runtime/`

Owns:

- runtime session lifecycle
- turn management
- runtime event flow
- process lifecycle
- execution orchestration
- runtime state transitions

This package should be provider-agnostic.

The HTTP runtime API is a host surface over this domain, not the domain itself.

The ASGI platform host is the canonical interactive host because it serves both:

- REST-style HTTP APIs used by apps and operators
- WebSocket runtime streams used by apps that need realtime agent communication

Current first-use endpoints include:

- `POST /api/runtime/sessions`
- `GET /api/runtime/sessions`
- `GET /api/runtime/sessions/<session_id>`
- `GET /api/runtime/sessions/<session_id>/events`
- `GET /api/runtime/sessions/<session_id>/turns`
- `POST /api/runtime/sessions/<session_id>/turns`
- `POST /api/runtime/sessions/<session_id>/cleanup`
- `GET /api/runtime/turns/<turn_id>`
- `POST /api/runtime/turns/<turn_id>/interrupt`
- `WS /ws/runtime/sessions/<session_id>`
- `WS /ws/runtime/threads`

Runtime session creation must include an explicit `agent_id`.
The core must not default missing runtime ownership metadata to a product app such as Chat.

Turn submission is implemented through a dedicated runtime service so future CLI, MCP, WebSocket, or automation surfaces can reuse the same orchestration without embedding execution logic in HTTP route handlers.

The runtime WebSocket endpoints are the official realtime transports for mounted apps and other interactive clients.

`WS /ws/runtime/sessions/<session_id>` sends a `runtime.snapshot` frame containing session metadata and persisted events, then live `runtime.event` frames from the runtime event bus. `WS /ws/runtime/threads` sends a `runtime.thread.snapshot` frame containing the workspace thread catalog, then live `runtime.thread.changed` frames from the runtime thread event bus.

The HTTP event and thread endpoints remain command, diagnostics, and operator surfaces. Product chat rendering must not bootstrap transcripts or thread lists by replaying runtime data over HTTP.

Apps that want realtime agent updates should connect to the WebSocket surface directly.

They should not implement app-specific WebSocket routes for core runtime events.

### Runtime model decomposition

The runtime domain should separate at least these concepts:

- runtime session
- runtime turn
- runtime event
- runtime process
- runtime state

Those are related, but they are not the same thing.

The first implementation should keep those boundaries explicit instead of collapsing them into one generic session manager.

#### Runtime session

A runtime session is the lifecycle container for one running agent runtime.

It should carry:

- authoritative runtime ownership such as `workspace_id` and agent or instance identity
- effective execution mode
- lifecycle timestamps
- current session status

The first local implementation should use explicit canonical statuses such as:

- `created`
- `running`
- `stopping`
- `stopped`
- `failed`

#### Runtime turn

A runtime turn is one unit of execution inside a runtime session.

It is not the same thing as chat-thread persistence.

The runtime turn model should support at least:

- queued
- active
- completed
- failed
- cancelled
- timed out

The first local implementation may represent `timed out` as an explicit terminal turn status rather than as an inferred transport-side error.

#### Runtime event

A runtime event is a structured state or progress signal emitted by the runtime domain.

Examples:

- turn started
- tool invocation started
- tool invocation completed
- runtime stalled
- process exited

Runtime events should be modeled independently from WebSocket framing or any other transport protocol.

The transport may carry runtime events, but it must not define the domain model.

When a runtime turn is submitted with a client-generated message id, the core should carry that id through the queued-turn event payload.

That id is not a chat-specific concept.

It is a generic correlation value that lets mounted apps reconcile optimistic UI state with authoritative runtime events without duplicating user messages.

The queued-turn event may also carry runtime input attachment metadata.

Attachment metadata is not file storage.

The core file upload surface persists file bytes under workspace storage and returns stable metadata. Uploads and JSON HTTP/ASGI request bodies must be bounded before decoding or dispatching so malformed, non-object, or oversized bodies return stable 4xx errors instead of becoming unbounded memory pressure or generic 500s. WSGI and ASGI hosts must resolve the body-size limit through the same configuration path, and the default body ceiling must account for the workspace upload API's decoded-file limit plus base64/JSON expansion. Runtime turns should carry references such as `file_id`, `relative_path`, content type, size, and checksum, not inline file bytes.

Before dispatching a turn to a text-oriented provider backend, the runtime should materialize uploaded attachment references into the provider input as workspace-relative links and local workspace paths. The queued runtime event should still preserve the original user text and structured attachment metadata for transcript rendering.

Provider lifecycle prompts such as waiting for stdin, turn start, turn completion, turn diff update, turn plan update, and item start or completion are internal runtime noise.

The provider normalization layer should drop those lines before they become persisted runtime events or frontend transport frames.
Chat-facing runtime views may still defensively ignore such labels, but the core runtime must not publish them as user-visible progress.

The first HTTP implementation supports async turn submission through an explicit request flag.

In async mode:

- the route queues the turn
- the route returns immediately with `202 Accepted`
- the provider execution runs in a background worker
- ordered runtime events record start, step updates, tool calls, output deltas, final output, completion, failure, or cancellation

Interactive runtime turns must not have a fixed wall-clock timeout.

An agent may work for minutes or hours inside one turn. The core may keep short protocol handshakes bounded, and users may explicitly stop a turn, but the runtime must not interrupt active provider work solely because a static turn-duration timer expired.

Provider adapters may emit provider-specific raw output, but the runtime domain must normalize it before persistence.

For Codex, the local provider runs a persistent `codex app-server --listen stdio://` process and maps app-server JSON events into generic runtime events such as:

- `runtime.step.updated`
- `runtime.tool_call.started`
- `runtime.tool_call.updated`
- `runtime.tool_call.completed`
- `runtime.tool_call.failed`
- `runtime.output.delta`
- `runtime.output.structured`

The Codex adapter must not silently drop app-server notifications just because their method name is not yet known by Maverick.

Known methods should be mapped intentionally. Codex app-server item types such as `commandExecution`, `fileChange`, and `webSearch` must be normalized as first-class generic tool calls with stable `tool_kind`, `tool_call_id`, status, summary, and structured detail fields such as command output, file changes, web-search query, and web-search results.

If an app-owned CLI, MCP, or backend surface returns a generic `chat_render` object, the runtime/provider bridge should normalize it into structured runtime output instead of treating the whole JSON response as assistant prose. The same normalization rule applies when an agent-message completion intentionally returns a JSON envelope with `structured_content` or `chat_render`. The normalized event shape is provider-agnostic: `runtime.output.structured` carries `structured_content` with a stable `kind` and `payload`. Chat and other host apps must resolve that kind through the widget registry; they must not hardcode a specific app such as Dynamic Views.

Provider output that belongs to a tool item must remain tool output. For example, Codex `item.fileChange.outputDelta` notifications are file-change tool updates and must not be emitted as assistant `runtime.output.delta` text.

Provider output deltas that are only low-level command stream fragments are not chat-facing runtime history. For Codex, `item.commandExecution.outputDelta` records represent partial stdout/stderr fragments for an already tracked command execution item, and `item.commandExecution.terminalInteraction` records represent terminal protocol interaction rather than a separate user-visible tool call. They should be filtered before runtime-event persistence and transport; the chat-facing history should retain the command lifecycle and final aggregate result instead of storing every intermediate fragment or terminal handshake.

Codex agent-message output may arrive both as streamed `item/agentMessage/delta` fragments and as a later completed item snapshot. The adapter must emit the text once per provider item: completion snapshots should fill gaps when no delta was streamed, but must not be re-emitted as duplicate transcript output for an item already streamed.

Unknown methods should still become generic runtime events with `provider_event_type` and compact raw payload preserved. If the method or payload looks like a tool, search, browser, fetch, command, or execution operation, it should be emitted as a generic `runtime.tool_call.*` event so the chat UI can show that a tool was used while the exact provider schema is still being learned.

Tool-like provider notifications without an explicit lifecycle state are point-in-time observations. They should be normalized as completed tool calls instead of active updates, otherwise generic notifications such as provider progress activity can leave stale spinners in transcript views.

Provider lifecycle and telemetry notifications that do not represent user-visible work should be filtered before persistence and transport. Examples include account rate-limit refreshes, token-usage updates, and generic thread status changes.

The Codex adapter must not use stateless `codex exec` for interactive chat or agent sessions.

Before launching the Codex process, the adapter must prepare a runtime-scoped `CODEX_HOME`.

This home is operational provider state for one Maverick runtime session.

It must live below the session runtime root, not in the workspace data plane and not inside the source repository.
The session runtime root is `workspaces/<workspace_id>/runtime/sessions/<runtime_session_id>/`, so concurrent agents in the same workspace receive separate provider homes, temporary directories, copied runtime skills, and transient provider binaries.
Runtime history and operational records for that agent session must also be partitioned there. The core stores per-session runtime records under the session root, including:

- `session.json` for the runtime session lifecycle record
- `events.json` for the persisted runtime event stream and chat transcript projection
- `turns.json` for turn lifecycle records
- `processes.json` for local process metadata
- `state.json` for the mutable runtime state snapshot

Workspace-scoped runtime thread records are persisted under `workspaces/<workspace_id>/runtime/threads.json`.

The core must not append every agent's session metadata, thread metadata, history, or operational records into installation-level shared JSON files because replay, cleanup, and restart recovery would degrade as total server history grows and would mix workspace-owned runtime state with platform control-plane state. Installation-level runtime persistence is reserved for platform security records such as runtime API token lifecycle state.

Runtime API tokens issued into provider launch environments must have store-backed lifecycle records keyed by token id. Runtime CLI and SDK APIs must reject tokens that are unregistered, expired, revoked, or mismatched against the session workspace and effective mode. This lets the platform revoke one runtime token without trusting bearer-token signature validity alone for the rest of the token TTL.

The source of Codex identity/configuration is configurable and path-agnostic:

1. `MAVERICK_CODEX_HOME`
2. `CODEX_HOME`
3. the current operating-system user's default Codex home

The adapter may copy required files such as auth, version, installation identity, sanitized config, and rules.

The sanitized runtime config must remove inherited MCP server and plugin sections from the operator Codex home. Maverick runtime sessions should not automatically expose user-global Codex connector apps such as GitHub, Gmail, Photoshop, AllTrails, or Notion unless Maverick explicitly materializes an allowed tool surface for that runtime.

The Codex adapter owns Maverick's managed Codex model selection for runtime agents. It should discover the visible Codex model catalog through the configured Codex binary, expose the viable model and reasoning-effort options through generic provider settings, and write the workspace-selected `model` and `model_reasoning_effort` into each runtime-scoped Codex config instead of inheriting those values from the operator home. The initial preferred fallback is `gpt-5.5` with high reasoning, but the persisted workspace selection must not require code changes when Codex adds or removes visible models.

The Codex app-server command for Maverick-managed runtimes must also disable Codex's built-in `apps` and `plugins` features. Runtime config preparation must write a managed Codex `[features]` section with `apps`, `plugins`, and `skill_mcp_dependency_install` disabled, instead of inheriting those feature switches from the operator home. Runtime-home preparation must remove plugin/app connector residue such as `plugins/`, `cache/codex_apps_tools/`, `.tmp/plugins/`, `.tmp/plugins.sha`, and `.tmp/app-server-remote-plugin-sync-v1` before launch so Codex does not attempt to start the `codex_apps` MCP bridge.

Codex may also generate provider-bundled system skills under `CODEX_HOME/skills/.system` when app-server starts. Maverick-managed Codex runtimes must remove that provider-generated `.system` tree during runtime-home preparation and again after app-server initialization before starting or resuming a provider thread. The only runtime skills visible to Maverick agents are workspace Skills app copies materialized by Maverick.

For sandboxed Codex sessions, sanitized runtime config must also drop inherited Codex `[projects.*]` trust entries that point outside the workspace root. This is provider-specific defense in depth: the generic Maverick runtime policy remains provider-agnostic, while the Codex adapter prevents Codex-specific trust configuration from weakening a Maverick sandbox.

For sandbox execution, the provider launch spec must carry both `readable_roots` and `writable_roots`.

For non-default workspace runtimes, both lists are exactly the workspace root.

The Codex provider must enforce that boundary before the app-server starts. It must launch the backend inside an operating-system workspace sandbox that mounts the workspace read/write, mounts only required runtime dependencies read-only, and does not mount the repository root, installation-level `core/`, installation-level `apps/`, another workspace, or operator home material.

The workspace operating-system sandbox may mount host resolver, host-name, NSS, and CA metadata as explicit read-only file binds when they are required for DNS or TLS. These file-level runtime dependencies do not broaden write access or expose workspace material outside the boundary. The sandbox must not mount broad host operating-system roots such as `/etc`, `/usr`, `/bin`, `/lib`, or `/lib64` by default. If a provider adapter explicitly supplies a dependency root for a concrete runtime binary, broad system document roots such as `/usr/share` and `/usr/local/share` must be masked so sandboxed agents cannot inventory host package documentation as user-accessible material outside the workspace.

When the configured Codex command is the NPM/NVM wrapper, the provider adapter should launch the packaged standalone Codex binary through a read-only bind at `runtime/bin/codex`. It must not mount the whole NVM installation, the whole Node version tree, or other operator-home package trees into sandboxed runtime sessions.

The same narrow binding rule applies to provider-bundled helper binaries that are required for normal workspace development. For Codex, `rg` must be exposed as a read-only file bind at `runtime/bin/rg` when the packaged ripgrep binary is available. The adapter should prefer the packaged standalone ripgrep binary over the `bin/rg` dotslash script, because sandboxed sessions must not require operator-home `dotslash` or package-manager trees. The runtime should also expose a minimal static shell as `runtime/bin/sh` and bind it to `/bin/sh` inside the workspace sandbox, so provider command execution can run ordinary shell commands without mounting broad host roots such as `/bin`, `/usr`, `/lib`, or `/lib64`. Exposing these tools this way makes workspace-local work possible without granting read access to the Codex package root, NVM installation, operator home, repository root, installation-level `core/`, installation-level `apps/`, or other workspaces. Inside the sandbox, Codex must see the workspace as `/workspace`, not as its host path.

Codex turn permissions must keep writable roots and read-only roots constrained to the workspace while allowing provider network access. For sandboxed turns, Maverick must enforce filesystem confinement with its own workspace sandbox and send a Codex app-server `sandboxPolicy` with `type: externalSandbox` and network enabled, so Codex does not construct a second managed filesystem sandbox inside the already-confined process. The legacy `workspaceWrite.readOnlyAccess` shape is no longer valid in Codex app-server and must not be sent. The network permission is required for Codex app-server sampling, streaming, and explicit web-research tasks; it is not permission to broaden raw filesystem access beyond the workspace boundary.

If the host cannot create that read/write confinement, sandbox runtime launch must fail closed. It must not fall back to Codex `workspace-write`, legacy Landlock flags, or any mode that still permits raw reads outside the workspace.

It must not copy user-global, plugin-provided, or repository-local skills into the runtime home by default.

Maverick core has no preinstalled runtime skills. Skills are extension data owned by the workspace Skills app. The Skills app seeds bundled skill templates from `apps/*/skills/` into `workspaces/<workspace_id>/data/skills/skills/` during install and migration. Operators enable or disable workspace skill copies from that editable workspace data.

At turn launch, the runtime materializes skills from the workspace-owned Skills app catalog. A base session with no explicit `skill_ids` receives every enabled workspace skill. A session created from an agent type may pass `skill_ids` to narrow that set to the agent type's selected skills.

Materialized runtime skills and rules must be copied into the session-local runtime home for sandbox sessions, not symlinked to source repository or operator home paths outside the workspace boundary.

Codex app-server retry notifications must be streamed as runtime step updates without prematurely closing the Maverick turn.

Only terminal app-server failures should transition the runtime turn to failed.

`codex exec` can be useful for isolated operator commands, tests, or one-shot automation, but it is not the product chat runtime because it does not preserve the provider conversation.

The canonical Codex runtime flow is:

1. runtime session starts
2. provider adapter launches `codex app-server --listen stdio://`
3. adapter sends `initialize`
4. adapter sends `thread/start` or `thread/resume`
5. runtime turn submission sends `turn/start` with the provider thread id
6. provider app-server emits structured turn, item, tool, and output events
7. runtime normalization persists provider events as Maverick runtime events
8. WebSocket transport streams the persisted Maverick runtime events

Conversation memory for the active provider session comes from the provider thread.

Chat thread records and runtime event history are still persisted by Maverick for UI replay, audit, recovery, and app-owned metadata, but the Codex model context must be preserved through `thread/start` and `thread/resume`.

WebSocket delivery is the canonical realtime transport for active runtime turns.

The runtime WebSocket stream must deliver the same persisted event records that `GET /api/runtime/sessions/<session_id>/events` returns, but live delivery must not poll the persistence adapter.

Runtime event recording has two distinct responsibilities:

- persist the event for replay, history, audit, and recovery
- publish the saved event to the in-memory runtime event bus for live subscribers

Provider output deltas may arrive as very small fragments. The runtime execution layer should coalesce adjacent output deltas before they reach runtime event persistence and live transport. Coalescing should be content-threshold based, not a tiny time-slice flush that turns slow provider tokens into one-character or one-syllable UI updates. Tool events, step updates, terminal events, and other non-output events must flush any pending output first so transcript chronology remains correct. Non-chat-facing command stream and terminal-interaction telemetry, such as Codex `item.commandExecution.outputDelta` and `item.commandExecution.terminalInteraction`, must be filtered rather than coalesced into persisted runtime history.

The WebSocket transport should subscribe to that bus before performing its initial replay so events recorded during replay are not lost. After replay, the WebSocket waits on the bus and sends events as they are published.

The local JSON persistence adapter is suitable for bootstrap control-plane state and runtime history replay. It is not a live token-streaming mechanism and must not sit in the active-turn hot path as a polling source.

For bootstrap deployments that persist runtime events in local JSON, event writes must be append-oriented. Saving one new runtime event must not require rereading and rewriting the full event history file, because active provider turns can produce many events while the HTTP host is also serving shell and app traffic.

The local JSON adapter must treat malformed collection files as storage errors, not as empty collections. A corrupt runtime history file may require recovery, but it must not be silently overwritten in a way that makes existing chat threads appear empty.

Runtime session, turn, event, process, and state records must survive auth logout/login cycles and local host restarts.

For the local hosted bootstrap, workspace-scoped runtime-domain collections are persisted under the owning workspace root. Installation-local `.maverick/local-state/runtime/` is not the storage home for runtime sessions, runtime threads, turns, events, processes, or state.

This is a bootstrap adapter detail, not the domain model. Production deployments may replace it with MongoDB or another store adapter without changing runtime service interfaces.

Backend process restart is a runtime recovery event.

On real backend host startup, the platform must inspect persisted running runtime sessions. Generic platform-state bootstrap used by CLI wrappers, MCP wrappers, tests, app tooling, or other sidecar processes must not run backend-restart recovery, because those processes can coexist with live runtime workers owned by the backend host. The hosted backend must start this recovery from the backend host lifecycle without blocking the HTTP socket from opening; large runtime histories must not make the service unavailable while deterministic recovery work is still running. Recovery must scope bounded event reads to the running sessions being inspected instead of scanning every persisted runtime event partition or loading full legacy histories. Oversized valid event partitions may be skipped by the startup recovery scan, but they must remain in place for normal runtime history reads and WebSocket snapshot replay; malformed event partitions may be quarantined out of the startup path rather than parsed unboundedly. If a running session has a queued or active turn during true backend startup, the in-memory worker that owned that turn died with the previous backend process. The startup recovery pass must first reconcile the turn store with persisted terminal events: if the event log already contains a terminal event such as `runtime.output.final`, `runtime.turn.completed`, `runtime.turn.failed`, or `runtime.turn.cancelled`, the non-terminal turn record must be closed to match that evidence, source-app runtime event hooks must be dispatched for the terminal state, and no resume turn should be queued for it. Remaining stale non-terminal user turns must be closed with explicit backend-restart evidence and source-app hooks must be dispatched for those terminal transitions. The platform may then enqueue one new asynchronous turn with the fixed input `resume` on the same runtime session and dispatch a source-app `runtime.turn.queued` hook for that resume turn so app-owned projections can track the active turn id. If a recovery-created `resume` turn is itself interrupted by a later backend restart, recovery may retry it only up to a bounded attempt limit; it must never create an unbounded restart/resume loop.

After runtime turn reconciliation, backend restart recovery may invoke generic background hooks declared by enabled workspace apps. The hosted backend may also run a periodic app-agnostic `background_tick` hook scheduler for active workspaces. The core must not know what those apps are recovering or scheduling. It only invokes the declared hook, publishes declared app events, and applies any permitted generic runtime session or interrupt requests returned by the app. App-specific recovery decisions, such as whether a queued Fleet workflow node should launch after a browser was closed, remain app-owned backend behavior.

Runtime JSON partitions may be touched by the backend host and sidecar runtime processes. Session-partitioned collection reads and writes must use a filesystem-level lock, not only an in-process mutex, so append-only event writes, pruning rewrites, and recovery reads cannot interleave into malformed JSON.

This behavior is deterministic platform recovery. It must not depend on frontend reconnect timing, agent-specific logic, or a user manually sending another message.

Runtime session persistence must include enough provider binding state to resume a provider conversation when the provider supports it.

For Codex this means storing the app-server thread id returned by `thread/start` and reusing it with `thread/resume`.

If a provider cannot resume native conversation state, its adapter must make that limitation explicit and choose a documented fallback such as reconstructing bounded conversation context from runtime events.

Chat thread records may reference runtime session ids, but chat history rendering must load authoritative runtime events from the runtime surface.

For chat UI state, `runtime.output.final` is terminal evidence for the active turn even if `runtime.turn.completed` is delayed, dropped by the active WebSocket, or replayed out of order.

The runtime store should still record explicit terminal turn events, but the chat frontend must clear its busy/stop state once final output for that turn is present.

Terminal turn evidence must also dominate earlier or late-arriving `queued` or `started` events for the same turn so replay ordering cannot reactivate a finished turn.

If a provider emits session-level terminal evidence without a `turn_id`, chat replay must close the latest active turn for that session rather than leaving the transcript in a permanent loading state.

Live loading labels must be derived only from runtime step events for the active turn. Historical step labels from earlier turns, including failure text, must not be reused as the current `Thinking` label for a later or idle turn.

Transcript rendering must also close active tool indicators when later output, final output, failure, or cancellation proves the turn has moved past that tool. A tool may be shown as actively running only while it is the latest evidence for an active turn.

Chat transcript rendering must preserve the runtime event ordering for visible tool usage.

Streamed assistant output is part of that same event timeline. When a later `runtime.output.final` arrives, the chat renderer must use it as terminal evidence and as a source for any missing suffix or structured link previews, but it must not replace already-rendered output segments in a way that moves tool groups above or below the text updates that originally separated them.

The runtime must not persist the same assistant text twice as both streamed output and final output. `runtime.output.delta` carries progressive assistant text. `runtime.output.final` is terminal evidence and may carry only text that was not already emitted through deltas. If the provider's final text is exactly the concatenation of streamed deltas, the final event must use an empty `text` field.

Consecutive runtime tool-call invocations within one turn may be rendered as a single `Tool Used` group, with start/update/completion events for the same invocation merged inside that group only when the provider supplies a stable call id such as `tool_call_id`, `call_id`, or `item_id`.

The renderer must not merge separate invocations merely because they use the same tool name or command.

A visible runtime update, output, failure, cancellation, or other non-tool transcript event must close the current tool group.

If more tool calls arrive after that update, chat must render a new `Tool Used` group rather than appending those later tools to an earlier group.

Provider notifications that describe a concrete runtime capability change may also be projected into the `Tool Used` affordance when that gives the user a better audit trail than a plain step label.

For example, a `skills changed` runtime update may be rendered as a synthetic `skill_change` tool item while preserving the original runtime event payload in the tool detail panel.

Deleting a chat thread is also a runtime ownership operation when the thread references a runtime session.

The chat product model is a strict one-to-one runtime invariant: one chat is one core runtime thread, one runtime session, one selected-provider app-server context, and one canonical session root under `workspaces/<workspace_id>/runtime/sessions/<runtime_session_id>/`. A chat thread must not exist without a runtime session, and every runtime session in the active workspace must be represented by exactly one runtime thread before the chat list is returned. The runtime thread id should use the runtime session id for core-created chat/session entries so user-facing chat deletion can target the same conceptual object without a second identifier mapping.

The core owns the delete operation. `DELETE /api/runtime/threads/<thread_id>` removes the core thread record and performs full cleanup of the linked runtime session. `POST /api/runtime/threads/clear` applies the same operation to every runtime thread in the active workspace.

The chat app must not implement a parallel thread delete path, return cleanup requests, or rely on hidden app-specific side effects in the platform app mount.

The runtime cleanup endpoint must remove the runtime session completely.
That includes terminating any live provider subprocesses registered for that runtime session, cancelling queued or active turns, deleting runtime-session records, deleting linked core runtime thread records, removing canonical runtime files, and invoking app-declared cleanup hooks for app-owned data linked to that runtime session.
Process termination remains a core runtime responsibility, but app-owned cleanup must be exposed through generic lifecycle orchestration rather than through app-specific platform-host behavior.

Apps that own runtime-linked metadata or files must declare a lifecycle or capability hook such as `runtime_session_cleanup`.
The core invokes every enabled app that declares that hook with a generic context containing `workspace_id`, `local_app_id`, `public_app_id`, `runtime_session_id`, and canonical runtime paths.
The app decides how to clean its own records under `data/<local_app_id>/`, and the hook must be idempotent, bounded by hook timeout, and governed by the same app contract and workspace authorization rules as other lifecycle hooks.

Therefore a persisted core chat thread must not outlive its runtime event history in a way that silently appears as an empty new chat.

Runtime turn state must remain consistent across the turn store and runtime event log. If startup recovery finds a non-terminal turn event without a corresponding turn record, it must append a terminal recovery event for that turn id so event-based transcript rendering and turn-based availability checks do not disagree indefinitely.

The WebSocket transport must support:

- workspace/session authorization during handshake
- ordered initial replay from persisted runtime events
- push delivery for newly recorded runtime events through the runtime event bus
- replay from a client-provided last seen event id
- heartbeat or keepalive messages that are transport-level, not runtime-domain events
- clean terminal delivery for completed, failed, cancelled, or timed-out turns

HTTP event replay is a recovery and history surface, not the active-turn transport. Polling the event store during a live WebSocket session is not an acceptable implementation of realtime streaming. SSE is not the target first-class transport unless a future deployment environment makes WebSocket impossible.

#### Runtime process

A runtime process is the execution handle that a runtime session currently controls.

For the first implementation, the runtime process model should support local process execution cleanly.

The model should not assume that every runtime must always be a local subprocess forever.

That said, remote-node or distributed-runtime orchestration is not required to complete the first local Phase 6 implementation.

The first local implementation should still model process lifecycle states explicitly, for example:

- `created`
- `running`
- `exited`
- `failed`
- `terminated`
- `timed-out`

#### Runtime state

Runtime state is the mutable execution snapshot of one runtime session.

Examples:

- current turn pointer
- last known progress
- watchdog state
- forced stop reason
- last runtime error detail

This state belongs to the runtime domain, not to chat persistence and not to app-owned storage.

### `inter_agent/`

Owns:

- delegation
- inter-agent message transport
- queueing
- retries
- delivery reconciliation
- coordination state

This package should be explicitly separate from `runtime/` even when the two collaborate closely.

### `providers/`

Owns:

- provider definitions
- provider adapters
- provider selection
- model capability metadata
- provider credential resolution

This package should make it possible to support:

- Codex
- Claude Code
- Kimi
- local open-source runtimes
- API-key based hosted models

without changing workspace or app architecture.

### Provider boundary rules

The provider domain should stay separate from:

- runtime session lifecycle
- workspace filesystem routing
- HTTP settings routes
- UI-specific forms or settings payloads

Provider modules should answer questions such as:

- what provider definitions exist
- what capabilities each provider offers
- what secret bindings or credential references are required
- how one runtime backend is constructed or selected

They should not become a generic dumping ground for runtime control logic.

### Provider definitions versus credentials

Maverick should distinguish clearly between:

- provider definition
- provider capability metadata
- provider credential binding
- runtime backend selection

Those are related, but they are not the same record.

The definition says what the provider is.

The capability metadata says what it can do.

The credential binding says which secret or operator-managed credential is attached.

The runtime backend selection flow decides which backend the runtime should use for one execution context.

Generic runtime turn submission, execution, user interrupts, app-requested interrupts, and cleanup must depend on the selected runtime backend adapter, not on Codex-specific branches. The runtime domain may coalesce and persist provider-neutral events, but backend launch specs, subprocess/protocol execution, provider thread binding, turn interruption, and provider runtime cleanup belong to the adapter registered for the selected provider.

Raw secret values must not appear in domain models or ordinary runtime records.

### Provider kinds

The provider abstraction should support at least two architectural kinds:

1. runtime-style backends
2. hosted API-style providers

Examples:

- `Codex`, `Claude Code`, `Kimi`, and local OSS runtimes behave like runtime-style backends
- hosted model APIs behave like API-style providers

The first implementation may ship only one real backend, but the core model should not collapse those categories into a single provider shape.

The current implementation ships:

- a provider registry owned by `core/providers`
- provider definition records separated from credential bindings and workspace selection records
- a workspace-aware provider selection flow in the core
- a runtime backend adapter contract that owns launch-spec construction, skill materialization, turn execution, turn interruption, and provider runtime cleanup
- one concrete runtime backend adapter: `Codex`

`Codex` is therefore the first installed backend, not the architectural identity of the provider layer.

### `execution_policy/`

Owns:

- sandbox policy
- full-access policy
- boundary validation

### `secrets/`

Owns:

- secret storage interfaces
- secret resolution
- binding logic

The secrets layer should distinguish clearly between:

- secret metadata and bindings
- raw secret values

The domain and service layers should work primarily with references, bindings, aliases, and resolution results, not with persistent raw secret payloads.

Raw secret values must stay confined to controlled secret-store adapters and short-lived runtime delivery paths.

The first implementation should therefore support:

- platform-owned secret records and aliases
- workspace-scoped, app-scoped, or provider-scoped secret bindings
- controlled resolution for runtime use
- app-scoped secret write and rotation requests from mounted app backend entrypoints, with raw values stripped before frontend responses
- ephemeral secret delivery into provider launch paths under platform authority
- operator inspection of metadata without exposing raw values
- operator-facing CLI and policy-gated MCP hooks for create, inspection, rotation, disable, and revoke operations without ever returning raw secret values

#### Recommended first file layout

```text
secrets/
  models.py
  errors.py
  store.py
  secret_store.py
  secret_bindings.py
  secret_resolution.py
  service.py
  routes.py  # only when real route wiring exists
```

Suggested responsibilities:

- `models.py`
  - `SecretRecord`
  - `SecretBindingRecord`
  - `ResolvedSecretLease` or equivalent short-lived resolution result
- `store.py`
  - storage-agnostic store contracts
- `secret_store.py`
  - concrete secret persistence and encryption adapter wiring
- `secret_bindings.py`
  - binding and alias logic separate from raw value persistence
- `secret_resolution.py`
  - controlled runtime resolution and delivery logic
- `service.py`
  - orchestration across store, bindings, and resolution
- `routes.py`
  - operator-facing or policy-gated surface wiring only

### `recovery/`

Owns:

- restart logic
- failed state handling
- repair orchestration at platform level

Recovery is not just "restart the process".

The platform should distinguish between:

- restartable failures
- repair-first failures
- non-recoverable failures that require operator action

So the recovery layer should coordinate:

- runtime restart intents
- backend-startup recovery for interrupted runtime turns
- failed-start diagnosis
- health-driven recovery decisions
- backend downtime watchdog escalation into an autonomous full-access rescue agent after sustained outage
- operator-facing repair and recovery workflows exposed through controlled CLI or MCP surfaces

The recovery surface should be designed so that operators can still reach it even when the main backend surface is unhealthy or unavailable.

In practice, this means the recovery domain should stay separable from the primary application host lifecycle.

The first implementation does not need a fully separate deployment, but it should preserve a clean boundary so that a dedicated recovery service or recovery-only host can be introduced without redesigning the domain.

The first implementation should also expose recovery through controlled CLI and MCP hooks so operators can:

- inspect recovery state
- record failed-start diagnoses
- execute runtime restart through the runtime lifecycle when the platform can reach the runtime store
- run on-demand runtime, provider, and app health probes
- plan restart or repair-first recovery intents

The explicit backend host restart surface is narrower than the rest of the recovery domain. `core.recovery.restart_backend` is governed by a dedicated admin recovery capability, such as `recovery.restart_backend`, and must be authorized from trusted platform or workspace governance records. `full-access` execution in the `default` workspace is only the filesystem/process mode needed to perform the restart; it is not itself proof of authority. Runtime callers without that admin capability must be denied, including full-access default-workspace agents that are not explicitly granted the capability.

App health probes should execute through the installed app's declared health contract or health hook when one exists, without relying on caller-supplied booleans, app-owned shortcuts, or direct access to primary backend runtime internals as the source of truth.

Backend downtime escalation is intentionally outside the main backend process. The watchdog owns only health probing, persisted downtime state, cooldown, and launch control for a single rescue agent. The rescue agent owns diagnosis and the minimal forward code or deployment fix. The backend startup recovery pass owns runtime session spin-back after the main service is healthy again.

Automatic backend downtime escalation is separate from manual restart authority. The watchdog is a full-server infrastructure service and may launch a rescue runtime only through the configured recovery provider. Manual restart remains an admin-governed operation and must not use `full-access/default` as a shortcut around capability checks.

#### Recommended first file layout

```text
recovery/
  models.py
  errors.py
  store.py
  runtime_recovery.py
  failed_start_recovery.py
  backend_watchdog.py
  health_checks.py
  service.py
  routes.py
```

Suggested responsibilities:

- `models.py`
  - failure classifications
  - recovery intent records
  - health result summaries
- `store.py`
  - persistence contracts for recovery markers and health snapshots when needed
- `runtime_recovery.py`
  - restart or resume orchestration for runtime sessions
- `failed_start_recovery.py`
  - diagnosis and recovery planning for startup failures
- `health_checks.py`
  - runtime, provider, and app health probe orchestration
- `service.py`
  - platform-level recovery coordination
- `routes.py`
  - CLI or MCP surface wiring for controlled recovery operations

### `observability/`

Owns:

- structured platform events
- runtime observability
- platform logging and audit hooks

The observability layer should keep these concerns distinct:

- raw log streams
- structured platform and runtime events
- audit records for operator-relevant control-plane actions
- metrics suitable for health and supportability workflows

Every operation that changes control-plane state or crosses a trust boundary should emit structured observability.

The audit record is the governance trail.

The structured event is the operational timeline.

Runtime and app logs are supporting debug streams, not the source of truth for governance.

The first implementation should wire audit and structured event emission into the real core flows, especially:

- app source registration, install, enable, disable, fork, rebase, upgrade, rollback, uninstall, purge, and reinstall
- frontend, backend, CLI, MCP, and skill mounting or unmounting
- app-owned CLI and MCP invocation failures, policy denials, and entrypoint execution failures
- provider binding, selection, launch-spec construction, credential binding, and provider health probes
- secret create, rotate, resolve attempts, denied resolution, disable, and revoke surfaces
- runtime session creation, lifecycle transitions, provider launch, process failure, and execution policy decisions
- workspace export, app export hook execution, manifest generation, import, and restore
- recovery health probes, recovery intents, actions executed, and actions failed

Observability data must be attributed consistently across planes, for example with:

- `workspace_id`
- `app_id`
- `runtime_session_id`
- `turn_id`
- `provider_id` when relevant
- source domain or component

Observability must also enforce redaction rules so that logs, audit trails, and structured events do not leak:

- raw secret values
- raw provider credentials
- sensitive runtime environment payloads unless explicitly allowed by operator policy

The first implementation should create and manage:

- installation-level log roots under `logs/platform/` and `logs/runtime/`
- workspace log roots under `workspaces/<workspace_id>/logs/workspace/`
- app-local log roots under `workspaces/<workspace_id>/logs/apps/<app_id>/`

It should also exclude workspace logs from default workspace export manifests.

#### Recommended first file layout

```text
observability/
  models.py
  errors.py
  store.py
  event_log.py
  audit_log.py
  runtime_log.py
  metrics.py
  service.py
  routes.py
```

Suggested responsibilities:

- `models.py`
  - structured event records
  - audit records
  - metrics envelopes or counters when modeled in code
- `store.py`
  - storage contracts for event, audit, and metric persistence
- `event_log.py`
  - structured event emission and attribution helpers
- `audit_log.py`
  - operator-relevant control-plane audit recording
- `runtime_log.py`
  - runtime-engine and process log handling
- `metrics.py`
  - metrics collection and aggregation surfaces
- `service.py`
  - redaction-aware orchestration across observability planes
- `routes.py`
  - operator inspection surfaces where intentionally exposed

### `mcp/`

Owns:

- MCP host surface
- tool registry
- platform MCP wiring
- app-facing runtime MCP boundaries

The core MCP layer should keep tool registration separate from transport bootstrap.

The registry of available tools, their schemas, and their discovery metadata should not be entangled with HTTP mounting, stdio startup, or application entrypoint wiring.

This keeps MCP bootstrap logic out of the main application startup path.

The core MCP layer is a platform-managed host for both:

- core-owned tools
- app-contributed tools from enabled workspace apps

The app contract may declare MCP capability surfaces, but the core still owns whether and how those surfaces are mounted.

MCP invocation policy should be enforced by the platform host in the same spirit as controlled CLI entrypoints.

So a tool being visible in discovery metadata is not, by itself, sufficient authority to execute it.

In the first local implementation, app-owned MCP entrypoints are invoked by the platform through a deterministic subprocess contract:

- the core resolves the declared entrypoint path
- the core passes a JSON payload on standard input
- the entrypoint returns a JSON object on standard output
- the entrypoint runs with the same Python interpreter as the core process unless a future runtime-specific interpreter strategy is introduced

This keeps mounting and policy centralized in the core while still allowing app-owned MCP logic to execute for enabled apps.

App-owned MCP tools should be namespaced in the platform host, for example:

- `app.<app_id>.<declared_tool_name>`

This prevents collisions between app-owned tools and core-owned tools in the shared host surface.

### `cli/`

Owns:

- platform CLI commands
- workspace and app administration commands
- operational maintenance commands
- batch and scriptable control surfaces

The core CLI is an official runtime and workspace automation surface.

CLI commands are agent-invokable by default when the trusted workspace context, execution mode, and command-specific policy allow the operation. The CLI layer must not use an `operator-only` category; privileged operations are expressed with workspace context, full-access mode, platform/workspace role checks, or domain-specific authorization inside the handler.

That means the CLI layer must distinguish clearly between:

- workspace-context commands
- full-access commands
- commands that may be surfaced through both CLI and MCP with separate policy models

CLI command registration should stay separate from invocation policy.

Whether a sandboxed agent may invoke a command is a core policy decision, not something inferred only from raw command-line arguments.
When an enabled app needs a per-command policy override, the core may read an app-owned `cli/command_policies.json` manifest beside the declared CLI entrypoint. That manifest can tighten visibility for declared app commands, for example by requiring a platform role, without adding app-id-specific branches to the core CLI registry. The manifest is not a replacement for core enforcement: the core still owns policy parsing, validation, discovery filtering, and invocation denial.

The same CLI framework should be able to host both:

- core-owned commands
- app-contributed commands for enabled workspace apps
- core-owned per-app lifecycle commands for app installation, uninstallation, and complete workspace-local removal when those operations are available

The core remains responsible for command registration, workspace authority checks, and exposure policy.

The user-facing Maverick wrapper must keep discovery scoped by authority and owner. `maverick apps list --json` is the compact app-discovery command. Core-owned CLI commands are discovered and invoked through `maverick core cli list --json`, `maverick core cli inspect <command_id> --json`, and `maverick core cli run <command_id> ...`. App-owned CLI commands are discovered and invoked through `maverick app <app_id> cli list --json`, `maverick app <app_id> cli inspect <command_name> --json`, and `maverick app <app_id> cli run <command_name> ...`. Official app frontend rebuilds use `maverick app <app_id> frontend build --json`, which runs the core app-hosting frontend build operation and emits the mounted-frontend refresh event after success. The wrapper must not provide a default global command dump that merges all core and app commands, because agents should pull only the command surface relevant to the task.

Canonical coding guidance for workspace agents must also be exposed through read-only core developer-context surfaces. `maverick core cli run developer-context.list --json` returns the canonical developer document catalog, and `maverick core cli run developer-context.read --doc-id <doc_id> --json` returns one canonical document body at a time. This lets sandboxed workspace agents read `AGENTS.md` and selected architecture documents without direct filesystem reads outside the workspace boundary.

MCP follows the same scoped discovery rule. Core tools use `maverick core mcp list --json`, `maverick core mcp inspect <tool_name> --json`, and `maverick core mcp call <tool_name> ...`. App tools use `maverick app <app_id> mcp list --json`, `maverick app <app_id> mcp inspect <tool_name> --json`, and `maverick app <app_id> mcp call <tool_name> ...`. The core developer-context tools `developer-context.list` and `developer-context.read` expose the same canonical document catalog and one-document read contract over MCP. `--help` remains human-oriented parser help; `list` and `inspect` are the machine-readable discovery contract for agents.

Per-app lifecycle CLI commands use the app namespace but remain core-owned operations. They do not require each app to implement its own install or uninstall script. `app.<app_id>.install` is available when a platform app source or workspace-local project exists. `app.<app_id>.uninstall` is available when the app has a workspace binding. `app.<app_id>.frontend.build` is available when the enabled app declares a frontend entrypoint and has a real frontend build script. `app.<app_id>.remove` is available only for workspace-local app projects, because complete removal deletes workspace-owned source and data rather than merely detaching a binding.

In the first local implementation, app-owned CLI entrypoints follow the same deterministic subprocess contract:

- the core resolves the declared CLI entrypoint path
- the core passes trusted invocation context, including `workspace_id`, `agent_id`, `effective_mode`, and `runtime_session_id` when available, plus app arguments as JSON on standard input
- the command returns a JSON object on standard output

Implementation files should keep command ownership explicit.

Recommended CLI split:

- `core_commands.py` composes core-owned command groups
- `workspace_commands.py` owns workspace inspection commands
- `runtime_provider_commands.py` owns runtime and provider commands
- `secret_commands.py` owns secret management commands
- `recovery_commands.py` owns recovery commands
- `app_lifecycle_commands.py` owns core-managed per-app lifecycle commands
- `app_commands.py` owns enabled-app command mounting
- `registry_builder.py` builds the visible command registry and runs commands

`service.py` may remain as a small public facade, but it should not accumulate registry, policy, and execution logic.

Recommended MCP split follows the same shape:

- `core_tools.py` composes core-owned tool groups
- `workspace_tools.py` owns workspace registry tools
- `runtime_provider_tools.py` owns runtime and provider tools
- `secret_tools.py` owns secret management tools
- `recovery_tools.py` owns recovery tools
- `app_tools.py` owns enabled-app tool mounting
- `registry_builder.py` builds the visible tool registry and invokes tools

This prevents the core surfaces from becoming mixed registry/spec/execution monoliths.

### `skills/`

Owns:

- core-owned procedural skills
- guidance for using the core's MCP and CLI correctly
- reusable operational workflows for orchestration, inspection, recovery, and provider setup

This does not refer to the separate app named `Skills`.

It refers to instruction assets owned by the core itself.

Core skills may be loaded, indexed, or synchronized into runtime-adjacent locations when necessary, but they remain instructional assets.

They do not become executable capability surfaces merely because they are materialized for runtime use.

Runtime authority and policy enforcement must continue to live in MCP, CLI, provider, runtime, and backend service layers rather than in `skills/`.

The skill catalog is platform-managed and may include:

Enabled workspace-owned skills from the Skills app catalog, optionally narrowed by explicit session `skill_ids`.

How those skill assets are installed into a runtime home is provider-specific.

That installation strategy belongs to the selected provider adapter, because different backends such as Codex, Claude Code, or Gemini CLI may require different runtime-home layouts or sync behavior.

Visible runtime skill ids are plain workspace skill ids, for example `maverick-code-skill` or `chat-ops`. They are intentionally not namespaced by core or source app, because the workspace Skills app is the single owner of the editable runtime catalog and must prevent or resolve name collisions before saving a skill.

The workspace app named `Skills` is the authoritative operator view for runtime skills.

It owns editable workspace skills under `workspaces/<workspace_id>/data/skills/skills/`.

It does not discover `~/.codex/skills`, plugin skills, system skills, or any other host Codex skill directories.

Bundled product skill templates may live under app source directories such as `apps/skills/skills/` and `apps/chat/skills/`, but runtime agents never read those source paths directly. Install and migration hooks copy missing templates into workspace data, and all subsequent edits happen on the workspace copy.

## Naming Conventions

The new core should use naming that keeps the file tree readable.

### Folder naming

Use short singular domain names:

- `identity/`
- `workspaces/`
- `apps/`
- `runtime/`
- `inter_agent/`
- `providers/`
- `execution_policy/`
- `secrets/`
- `recovery/`
- `observability/`
- `mcp/`
- `cli/`
- `skills/`

Avoid vague folders such as:

- `platform/`
- `support/`
- `utils/`
- `misc/`

unless the contents are truly cross-cutting and cannot belong to a domain.

### File naming

Prefer noun or action-specific filenames over overloaded generic names.

Good examples:

- `service.py`
- `routes.py`
- `models.py`
- `store.py`
- `policy.py`
- `runtime_session.py`
- `runtime_turns.py`
- `runtime_events.py`
- `delegation_service.py`
- `message_delivery.py`
- `provider_registry.py`
- `provider_openai.py`
- `provider_anthropic.py`
- `secret_bindings.py`
- `workspace_limits.py`
- `runtime_cli.py`
- `providers_cli.py`
- `recovery_cli.py`

Avoid names like:

- `helpers.py`
- `common.py`
- `manager.py`
- `base.py`

unless the file is truly the canonical implementation of that concept.

### Size rule

Files should stay small enough that one file usually contains one responsibility.

As a practical rule:

- if a file starts mixing routes, persistence, domain logic, and serialization, split it
- if a file has multiple unrelated public entrypoints, split it
- if a filename stops explaining the contents clearly, split it

### Recommended per-domain file pattern

Not every domain needs every file, but this should be the default pattern:

```text
<domain>/
  routes.py
  service.py
  models.py
  store.py
  errors.py
```

When a domain grows, split further by concept instead of creating monoliths:

```text
runtime/
  runtime_session.py
  runtime_turns.py
  runtime_events.py
  runtime_process.py
  routes.py
```

```text
inter_agent/
  delegation_service.py
  message_delivery.py
  delivery_reconcile.py
  models.py
  routes.py
```

```text
providers/
  provider_registry.py
  provider_models.py
  provider_credentials.py
  provider_openai.py
  provider_anthropic.py
  provider_codex.py
  provider_local.py
```

```text
cli/
  workspace_cli.py
  apps_cli.py
  runtime_cli.py
  inter_agent_cli.py
  providers_cli.py
  recovery_cli.py
```

```text
skills/
  runtime-orchestration/
    SKILL.md
  inter-agent-operations/
    SKILL.md
  provider-configuration/
    SKILL.md
```

## Illustrative File Layout

The target folder structure should move toward something like this:

```text
core/
  main.py
  api/
    application.py
    lifecycle.py
  identity/
    routes.py
    service.py
    models.py
    store.py
  workspaces/
    routes.py
    service.py
    models.py
    store.py
    governance.py
    limits.py
  apps/
    routes.py
    service.py
    models.py
    install_store.py
    lifecycle.py
    compatibility.py
  runtime/
    routes.py
    runtime_session.py
    runtime_turns.py
    runtime_events.py
    runtime_process.py
    runtime_state.py
  inter_agent/
    routes.py
    models.py
    delegation_service.py
    message_delivery.py
    delivery_queue.py
    delivery_reconcile.py
  providers/
    routes.py
    provider_registry.py
    provider_models.py
    provider_credentials.py
    provider_selection.py
    provider_codex.py
    provider_openai.py
    provider_anthropic.py
    provider_local.py
  execution_policy/
    policy.py
    sandbox_policy.py
    full_access_policy.py
    workspace_boundary.py
  secrets/
    models.py
    errors.py
    store.py
    routes.py
    secret_store.py
    secret_bindings.py
    secret_resolution.py
    service.py
  recovery/
    models.py
    errors.py
    store.py
    routes.py
    runtime_recovery.py
    failed_start_recovery.py
    health_checks.py
    service.py
  observability/
    models.py
    errors.py
    store.py
    event_log.py
    audit_log.py
    runtime_log.py
    metrics.py
    service.py
  mcp/
    server.py
    tool_registry.py
    platform_tools.py
  cli/
    workspace_cli.py
    apps_cli.py
    runtime_cli.py
    inter_agent_cli.py
    providers_cli.py
    recovery_cli.py
  skills/
    runtime-orchestration/
      SKILL.md
    inter-agent-operations/
      SKILL.md
    provider-configuration/
      SKILL.md
  shared/
```

This tree is intentionally explicit.

It is better to have more files with obvious names than fewer files with mixed responsibilities.

## Database Ownership In The Core

The core database should remain limited to platform-level records such as:

- users
- auth sessions
- workspaces
- workspace memberships
- app installation metadata
- runtime operational state
- secret metadata
- audit and platform logs
- quotas and governance state

The core database should not become the default storage engine for app business data.

Password resets and user deactivation are auth-session lifecycle events. When a user's password credential changes or the user is deactivated, the core identity service must revoke that user's existing auth sessions. Request session resolution must also reject inactive users even if an old active session record still exists.

## Design Summary

The target Maverick core should be:

- headless
- standalone
- platform-scoped
- app-agnostic
- workspace-aware
- operationally safe

It should own:

- identity
- governance
- app hosting
- runtime orchestration
- inter-agent communication
- AI provider management
- orchestration
- execution policy
- secret management
- recovery
- MCP surface
- CLI surface
- workspace Skills app catalog resolution

It should not own:

- app domain models
- app data schemas
- app business content
- workspace business content

This is the foundation required to rebuild the core in a clean and scalable way.
