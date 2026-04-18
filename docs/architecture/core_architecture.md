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
- the core code lives directly under `/maverick-v3/core/`
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

The initial repository conventions for v3 should stay minimal and explicit:

- Python `3.12`
- the package root is the repository `core/` directory
- tests live under `/maverick-v3/tests/`
- early verification should rely on standard-library-friendly commands first

At this stage the repository should prefer:

- `python3 -m unittest discover -s tests -p 'test_*.py'`
- `python3 -m compileall core tests`

before introducing heavier toolchain assumptions.

The initial scaffold should also establish a small per-domain file pattern in the domains that become active first.

Preferred starter files are:

- `routes.py`
- `service.py`
- `models.py`
- `store.py`
- `errors.py` when a domain already owns explicit failure modes

This pattern is meant to keep ownership obvious early, not to justify large empty scaffolding trees.

## Persistence Boundary

The Maverick v3 domain model is storage-agnostic.

This applies in particular to:

- `models.py`
- `service.py`
- domain-level errors and contracts

The first control-plane persistence adapter may target MongoDB, but MongoDB is an implementation choice, not the architectural identity of the core.

Rules:

- domain records must not depend on Mongo driver types
- services should depend on store protocols or equivalent persistence contracts, not concrete Mongo adapters
- Mongo-specific query shapes and update semantics must stay inside store adapters
- bootstrap wiring may choose MongoDB as the initial persistence backend

This keeps the core open to future adapters such as PostgreSQL, SQLite, or another control-plane store without reshaping the domain model.

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

The initial control-plane persistence for these records may target MongoDB, while keeping the domain records and service layer independent from HTTP, framework-specific exceptions, and database-driver-specific types.

### 2. Workspace registry and governance

The core owns:

- workspace existence
- workspace metadata
- workspace governance state
- workspace quotas and limits
- workspace policy enforcement

The core does not own the internal business data of a workspace.

The initial v3 model should keep these records distinct:

- workspace registry record
- workspace membership record
- workspace governance record
- workspace quota record

The execution-policy domain may read these records, but it should still compute the effective runtime policy separately.

### 3. App installation and hosting

The core owns:

- local installation state of apps
- app enablement state per workspace
- app lifecycle orchestration
- app hosting contracts
- app runtime hooks such as install, upgrade, migrate, uninstall

The core does not own app business data.

For v3, the app-hosting domain should keep at least these concepts distinct:

- app source or project material
- app installation record
- workspace app enablement or binding state

These concepts are related, but they are not interchangeable.

Examples:

- an external app bundle may be known to the installation without being enabled in every workspace
- a workspace-local app project may exist under `workspaces/<workspace_id>/apps/` without being installed yet
- an installed app may be disabled in one workspace while remaining enabled in another

This separation is required to keep lifecycle orchestration, compatibility checks, and uninstall or reinstall behavior deterministic.

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

### 7. Execution policy

The core owns:

- sandbox policy
- full-access policy
- runtime execution mode enforcement
- workspace execution boundary enforcement

The workspace domain may declare metadata and governance state, but the effective runtime mode must still be resolved by `execution_policy/`.

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

## What The Core Is Not

The core should not own:

- memory content
- chat content as a domain model
- CRM content
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

## Target Core Tree

The target core tree should look like this:

```text
/maverick-v3/
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

### Runtime model decomposition

The runtime domain should separate at least these concepts:

- runtime session
- runtime turn
- runtime event
- runtime process
- runtime state

Those are related, but they are not the same thing.

The first v3 implementation should keep those boundaries explicit instead of collapsing them into one generic session manager.

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

Runtime events should be modeled independently from websocket framing or any other transport protocol.

The transport may carry runtime events, but it must not define the domain model.

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

Maverick v3 should distinguish clearly between:

- provider definition
- provider capability metadata
- provider credential binding
- runtime backend selection

Those are related, but they are not the same record.

The definition says what the provider is.

The capability metadata says what it can do.

The credential binding says which secret or operator-managed credential is attached.

The runtime backend selection flow decides which backend the runtime should use for one execution context.

Raw secret values must not appear in domain models or ordinary runtime records.

### Provider kinds

The provider abstraction should support at least two architectural kinds:

1. runtime-style backends
2. hosted API-style providers

Examples:

- `Codex`, `Claude Code`, `Kimi`, and local OSS runtimes behave like runtime-style backends
- hosted model APIs behave like API-style providers

The first implementation may ship only one real backend, but the core model should not collapse those categories into a single provider shape.

The current v3 implementation ships:

- a provider registry owned by `core/providers`
- provider definition records separated from credential bindings and workspace selection records
- a workspace-aware provider selection flow in the core
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

The first v3 implementation should therefore support:

- platform-owned secret records and aliases
- workspace-scoped or provider-scoped secret bindings
- controlled resolution for runtime use
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
  routes.py
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
- failed-start diagnosis
- health-driven recovery decisions
- operator-facing repair and recovery workflows exposed through controlled CLI or MCP surfaces

The recovery surface should be designed so that operators can still reach it even when the main backend surface is unhealthy or unavailable.

In practice, this means the recovery domain should stay separable from the primary application host lifecycle.

The first v3 implementation does not need a fully separate deployment, but it should preserve a clean boundary so that a dedicated recovery service or recovery-only host can be introduced without redesigning the domain.

The first v3 implementation should also expose recovery through controlled CLI and MCP hooks so operators can:

- inspect recovery state
- record failed-start diagnoses
- execute runtime restart through the runtime lifecycle when the platform can reach the runtime store
- run on-demand runtime, provider, and app health probes
- plan restart or repair-first recovery intents

App health probes should execute through the installed app's declared health contract or health hook when one exists. They should not depend on caller-supplied booleans as the source of truth for app health.

without relying on app-owned surfaces or on direct access to the primary backend runtime internals.

#### Recommended first file layout

```text
recovery/
  models.py
  errors.py
  store.py
  runtime_recovery.py
  failed_start_recovery.py
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

The first v3 implementation should wire audit and structured event emission into the real core flows, especially:

- app install, enable, disable, uninstall, and reinstall
- provider binding, selection, and launch-spec construction
- secret create, rotate, disable, and revoke surfaces
- runtime session creation and lifecycle transitions
- recovery intents and health probes

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

The first v3 implementation should create and manage:

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

This avoids rebuilding the v2 pattern where too much MCP bootstrap logic accumulated inside the main application startup path.

The core MCP layer is a platform-managed host for both:

- core-owned tools
- app-contributed tools from enabled workspace apps

The app contract may declare MCP capability surfaces, but the core still owns whether and how those surfaces are mounted.

MCP invocation policy should be enforced by the platform host in the same spirit as controlled CLI entrypoints.

So a tool being visible in discovery metadata is not, by itself, sufficient authority to execute it.

In the first local v3 implementation, app-owned MCP entrypoints are invoked by the platform through a deterministic subprocess contract:

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

The core CLI is primarily an operator and runtime surface.

It may also expose controlled workspace-safe commands to sandboxed agents when the platform explicitly allows that invocation path.

That means the CLI layer must distinguish clearly between:

- operator-only commands
- workspace-safe commands
- commands that may be surfaced through both CLI and MCP

CLI command registration should stay separate from invocation policy.

Whether a sandboxed agent may invoke a command is a core policy decision, not something inferred only from raw command-line arguments.

The same CLI framework should be able to host both:

- core-owned commands
- app-contributed commands for enabled workspace apps

The core remains responsible for command registration, workspace authority checks, and exposure policy.

In the first local v3 implementation, app-owned CLI entrypoints follow the same deterministic subprocess contract:

- the core resolves the declared CLI entrypoint path
- the core passes trusted invocation context and arguments as JSON on standard input
- the command returns a JSON object on standard output

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

- core-owned skills
- app-contributed skills from enabled workspace apps

How those skill assets are installed into a runtime home is provider-specific.

That installation strategy belongs to the selected provider adapter, because different backends such as Codex, Claude Code, or Gemini CLI may require different runtime-home layouts or sync behavior.

Visible skill ids should be namespaced in the platform catalog, for example:

- `core.<skill_id>`
- `app.<app_id>.<skill_id>`

This avoids collisions between core-owned and app-contributed skill assets.

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
- core-owned skills

It should not own:

- app domain models
- app data schemas
- app business content
- workspace business content

This is the foundation required to rebuild the core in a clean and scalable way.
