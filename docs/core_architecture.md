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

### 2. Workspace registry and governance

The core owns:

- workspace existence
- workspace metadata
- workspace governance state
- workspace quotas and limits
- workspace policy enforcement

The core does not own the internal business data of a workspace.

### 3. App installation and hosting

The core owns:

- local installation state of apps
- app enablement state per workspace
- app lifecycle orchestration
- app hosting contracts
- app runtime hooks such as install, upgrade, migrate, uninstall

The core does not own app business data.

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

### `recovery/`

Owns:

- restart logic
- failed state handling
- repair orchestration at platform level

### `observability/`

Owns:

- structured platform events
- runtime observability
- platform logging and audit hooks

### `mcp/`

Owns:

- MCP host surface
- tool registry
- platform MCP wiring
- app-facing runtime MCP boundaries

### `cli/`

Owns:

- platform CLI commands
- workspace and app administration commands
- operational maintenance commands
- batch and scriptable control surfaces

The core CLI is primarily an operator and runtime surface.

It may also expose controlled workspace-safe commands to sandboxed agents when the platform explicitly allows that invocation path.

### `skills/`

Owns:

- core-owned procedural skills
- guidance for using the core's MCP and CLI correctly
- reusable operational workflows for orchestration, inspection, recovery, and provider setup

This does not refer to the separate app named `Skills`.

It refers to instruction assets owned by the core itself.

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
    routes.py
    secret_store.py
    secret_bindings.py
    secret_resolution.py
  recovery/
    routes.py
    runtime_recovery.py
    failed_start_recovery.py
    health_checks.py
  observability/
    event_log.py
    audit_log.py
    runtime_log.py
    metrics.py
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
