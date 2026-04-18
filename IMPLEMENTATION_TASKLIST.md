# Maverick v3 Implementation Tasklist

Date: 2026-04-17

## Goal

Build Maverick v3 from a clean codebase under:

```text
/home/ubuntu/maverick-v3
```

without carrying forward legacy structure or backward-compatibility constraints from v2.

## Global Rules

- v3 is a clean rebuild, not a compatibility layer on top of v2
- do not preserve legacy folder names just because they exist in v2
- do not preserve legacy APIs unless they still fit the new architecture
- optimize for clean boundaries, small files, and obvious ownership
- keep the core headless and app-agnostic
- treat `default` as a special workspace only at execution-policy level, not as a different storage model
- treat `core/` as the direct package root of the platform core, not as a container for extra wrapper layers
- do not introduce wrapper folders such as `core/backend/`, `core/backend/runtime_backend/`, or `core/.../app/`
- do not introduce an ambiguous `core/core/`; use a clearer name such as `shared/` or `foundation/` if a shared internal package is truly needed

## Non-Goals

- no migration bridge from v2 in the first implementation phase
- no backward-compatible database schema
- no compatibility shim for old runtime routes unless explicitly reintroduced later
- no reuse of legacy monolithic folders such as generic `platform/` buckets unless a concept truly belongs there

## Phase 0: Bootstrap v3 Repository

- [x] Create the base repository structure in `/home/ubuntu/maverick-v3`
- [x] Create a minimal root README describing v3 as a clean rebuild
- [x] Create top-level folders:
  - [x] `core/`
  - [x] `apps/`
  - [x] `workspaces/`
  - [x] `scripts/`
  - [x] `docs/`
- [x] Copy or move the approved architecture documents into `maverick-v3/docs/architecture/`
- [x] Initialize git in `maverick-v3` or connect it to the intended remote strategy
- [x] Create a root `.gitignore` for:
  - [x] runtime state
  - [x] app-local DB files
  - [x] logs
  - [x] tmp
  - [x] generated build output
- [x] Define repository conventions:
  - [x] Python version
  - [x] package layout
  - [x] lint/test commands
  - [x] environment bootstrap

## Phase 1: Define the v3 Filesystem Contract

- [x] Implement the canonical installation layout:
  - [x] `/maverick-v3/core/`
  - [x] `/maverick-v3/apps/`
  - [x] `/maverick-v3/workspaces/`
- [x] Define canonical workspace path helpers
- [x] Define canonical app path helpers
- [x] Define canonical storage path helpers
- [x] Define canonical logs path helpers
- [x] Define canonical runtime path helpers
- [x] Define canonical file identity rules:
  - [x] `file_id`
  - [x] relative path
  - [x] hash
  - [x] timestamps
- [x] Define canonical export manifest structure

## Phase 2: Scaffold the New Core Tree

- [x] Create the new core package layout exactly around the approved target structure:
  - [x] `api/`
  - [x] `main.py`
  - [x] `identity/`
  - [x] `workspaces/`
  - [x] `apps/`
  - [x] `runtime/`
  - [x] `inter_agent/`
  - [x] `providers/`
  - [x] `execution_policy/`
  - [x] `secrets/`
  - [x] `recovery/`
  - [x] `observability/`
  - [x] `mcp/`
  - [x] `cli/`
  - [x] `skills/`
- [x] Add empty but real modules with clean names instead of generic placeholders
- [x] Add a minimal `main.py`
- [x] Add a minimal application bootstrap in `api/application.py`
- [x] Add a small per-domain file pattern:
  - [x] `routes.py`
  - [x] `service.py`
  - [x] `models.py`
  - [x] `store.py`
  - [x] `errors.py` when needed
- [x] Ensure the core tree lives directly under `/maverick-v3/core/` with no wrapper layers such as `backend/`, `runtime_backend/`, or `app/`

## Phase 3: Identity and Workspace Governance

- [x] Implement users model
- [x] Implement auth/session model
- [x] Implement workspace registry model
- [x] Implement workspace membership model
- [x] Implement workspace governance model
- [x] Implement workspace quota/limit model
- [x] Implement workspace creation flow
- [x] Implement automatic creation of `default` workspace
- [x] Implement workspace execution profile:
  - [x] `default` can allow `full-access`
  - [x] non-default workspaces are sandbox-only

## Phase 4: App Hosting and Installation System

- [x] Implement app installation records in the core:
  - [x] installation-level app source record for external bundles or known platform app artifacts
  - [x] workspace-local app project record for code living under `workspaces/<id>/apps/`
  - [x] workspace app binding or enablement record
- [x] Implement distinction between:
  - [x] external installed app
  - [x] workspace-local app project
  - [x] app enabled state
- [x] Define canonical app lifecycle states and transitions:
  - [x] `installed`
  - [x] `enabled`
  - [x] `disabled`
  - [x] `failed`
  - [x] `updating`
  - [x] `rolled_back`
  - [x] enforce that an app cannot be enabled before it is installed
- [x] Implement install flow for external app bundles
- [x] Implement install flow for workspace-local apps under `workspaces/<id>/apps/`
- [x] Implement deterministic creation of `workspaces/<id>/data/<app_id>/` during install
- [x] Implement uninstall flow:
  - [x] remove active capability from the workspace
  - [x] preserve app-owned data by default
- [x] Implement purge-data flow
- [x] Implement reinstall flow:
  - [x] reattach to existing `data/<app_id>/` when present
  - [x] support validation, repair, or migration before reactivation when needed
- [x] Implement upgrade flow
  - [x] stage the target app version through an explicit updating state
  - [x] run upgrade and migrate hooks where declared
  - [x] persist app-owned data schema metadata under `data/<app_id>/`
  - [x] support bundle rollback when declared by the app contract
- [x] Implement compatibility checks:
  - [x] minimum core version
  - [x] contract version
  - [x] supported workspace modes if declared
- [x] Keep app business data out of the core control-plane database
- [x] Keep app source or project material separate from installation state and workspace enablement state

## Phase 5: App Contract Execution Layer

- [x] Make the app contract file the source of truth for executable app metadata
- [x] Implement parser/validator for canonical app contract files
- [x] Implement support for:
  - [x] `contract_version`
  - [x] `minimum_core_version`
  - [x] `entrypoints`
  - [x] `storage`
  - [x] `capabilities`
  - [x] `lifecycle`
  - [x] `compatibility`
  - [x] `hook_timeouts`
  - [x] `failure_semantics`
  - [x] `health_contract`
  - [x] `rollback_support`
- [x] Implement lifecycle import-recovery support declarations:
  - [x] `validate_after_import`
  - [x] `repair_after_import`
- [x] Implement deterministic resolution of:
  - [x] MCP entrypoint
  - [x] CLI entrypoint
  - [x] skills root
  - [x] lifecycle hooks
- [x] Implement health contract execution
- [x] Implement lifecycle timeout enforcement for:
  - [x] install
  - [x] upgrade
  - [x] migrate
  - [x] export
  - [x] import
  - [x] validate_after_import
  - [x] repair_after_import
  - [x] health_check

## Phase 6: Workspace Runtime Model

- [x] Implement runtime session abstraction
  - [x] define canonical runtime session statuses
  - [x] store authoritative `workspace_id`, `agent_id` or equivalent runtime owner, and execution mode
  - [x] track `started_at`, `updated_at`, `ended_at`, and last progress timestamp
- [x] Implement turn abstraction
  - [x] define canonical turn statuses
  - [x] model queued, active, completed, failed, cancelled, and timed-out turns explicitly
  - [x] keep turn runtime state separate from chat-thread persistence
- [x] Implement runtime event abstraction
  - [x] define structured event types instead of raw transport messages
  - [x] attribute runtime events to `workspace_id`, runtime session, turn, and process when present
  - [x] distinguish runtime-domain events from websocket or transport framing
- [x] Implement runtime process abstraction
  - [x] define a local process handle model
  - [x] track stdin or stdout lifecycle, exit code, and crash or timeout outcomes
  - [x] keep room for future non-local execution targets without making remote runtime a Phase 6 requirement
- [x] Implement runtime state model
  - [x] track current turn pointer, current runtime status, last known progress, and watchdog or error detail
  - [x] keep runtime state under workspace-scoped runtime state, not in chat persistence
- [x] Implement workspace-aware runtime routing
  - [x] resolve workspace authority from runtime ownership, not from untrusted client input alone
  - [x] ensure child runtime sessions inherit the same workspace boundary unless a trusted control-plane action says otherwise
- [x] Implement `sandbox` execution mode
  - [x] make the workspace root the writable runtime perimeter
  - [x] keep `runtime/` ephemeral and separate from `storage/` and `data/`
- [x] Implement `full-access` execution mode
  - [x] keep it operator-only and policy-gated
  - [x] do not require remote-node or distributed-runtime support for the first local implementation
- [x] Ensure non-default workspace runtime cannot escape workspace root
- [x] Ensure `default` runtime can operate beyond workspace root only when explicitly configured

## Phase 7: AI Provider Abstraction

- [x] Implement provider registry
  - [x] separate provider definition records from runtime session records
  - [x] make provider registry independent from HTTP settings routes or UI forms
- [x] Implement provider model and capability metadata
  - [x] define canonical provider ids, labels, and descriptions
  - [x] define capability metadata separately from secret material
  - [x] distinguish runtime-style backends from API-key-based hosted providers
- [x] Implement provider credential store and binding logic
  - [x] keep raw secret values out of domain models
  - [x] model secret references or bindings separately from provider definitions
  - [x] support workspace-scoped provider selection without making secrets app-owned data
- [x] Implement runtime backend selection flow
  - [x] make backend selection a core decision based on provider capability metadata and policy
  - [x] do not hardcode `Codex` as the only architectural runtime
- [x] Define the provider/runtime distinction clearly in code:
  - [x] runtime abstraction
  - [x] provider/backend adapter
  - [x] keep runtime session lifecycle out of provider modules
- [x] Implement first provider backend:
  - [x] `Codex`
    - [x] isolate Codex subprocess env building in the provider adapter, not in the runtime domain
- [x] Define extension points for future backends:
  - [x] Claude Code
  - [x] Kimi
  - [x] local OSS runtime
  - [x] API-key based hosted models

## Phase 9: MCP, CLI, and Skills Surfaces

- [x] Implement core MCP host surface
  - [x] separate core tool registry from HTTP, stdio, or other transport wiring
  - [x] expose a deterministic tool discovery manifest or index
  - [x] keep MCP host bootstrap out of monolithic application entrypoints
  - [x] execute app-owned MCP entrypoints through a platform-managed host
  - [x] enforce invocation policy for MCP calls, not only for CLI
  - [x] namespace app-owned MCP tools in the platform host to avoid collisions
- [x] Implement core CLI surface
  - [x] separate command registration from invocation policy and transport concerns
  - [x] define operator-facing commands separately from agent-safe commands
  - [x] support scriptable and batch-safe platform operations
  - [x] execute app-owned CLI entrypoints through a platform-managed host
  - [x] return operational core data when the relevant control-plane stores are available
- [x] Implement core skills loading model
  - [x] load and index core-owned skills as instructional assets
  - [x] allow controlled runtime materialization or synchronization of skill content when needed
  - [x] keep skill loading separate from runtime session lifecycle
  - [x] delegate runtime skill installation strategy to the selected provider adapter
  - [x] namespace visible skill ids to avoid core-app and app-app collisions
- [x] Define which core operations are exposed:
  - [x] MCP only
  - [x] CLI only
  - [x] both
  - [x] document why each operation belongs to that surface
- [x] Clarify CLI invocation policy for sandboxed workspace agents
  - [x] define a controlled allowlist or policy gate for sandbox-safe commands
  - [x] ensure sandboxed agents cannot invoke operator-only CLI paths
  - [x] keep workspace authority enforcement outside raw CLI argument trust
- [x] Ensure `skills/` is treated as instructional, not as executable runtime boundary
  - [x] keep runtime and policy enforcement anchored in MCP, CLI, and backend services
  - [x] ensure synchronized skill artifacts do not become an implicit capability surface
- [x] Ensure the core host framework can expose:
  - [x] core-owned MCP, CLI, and skills surfaces
  - [x] app-contributed MCP, CLI, and skills surfaces for enabled workspace apps
  - [x] unmount app-contributed surfaces when an app is disabled

## Phase 10: Secrets and Recovery

- [x] Implement platform secret store
  - [x] create `core/secrets/models.py`
  - [x] create `core/secrets/store.py`
  - [x] create `core/secrets/secret_store.py`
  - [x] define secret metadata model separate from raw secret values
  - [x] define canonical secret ids, aliases, and provider-independent labels
  - [x] keep persistence and encryption details confined to secret-store adapters
- [x] Implement workspace/app secret references
  - [x] create `core/secrets/secret_bindings.py`
  - [x] model app-owned secret references separately from platform-owned secret values
  - [x] support workspace-scoped secret bindings without making secrets app-owned data
  - [x] support provider credential bindings through the same secret-reference model where appropriate
- [x] Implement secret resolution at runtime
  - [x] create `core/secrets/secret_resolution.py`
  - [x] resolve secret references through a controlled platform path
  - [x] deliver secrets to runtime only under explicit policy and only for the current session scope
  - [x] resolve provider credentials into ephemeral runtime launch input through the platform path, not from workspace-owned files
  - [x] avoid persisting resolved secret values in runtime state snapshots, app data roots, or workspace files
- [x] Implement secrets orchestration surface
  - [x] create `core/secrets/service.py`
  - [x] create `core/secrets/errors.py`
- [x] Ensure secret values never land in app-owned data
  - [x] keep secret values out of `data/<app_id>/`
  - [x] keep secret values out of workspace export artifacts
  - [x] keep secret values out of app-owned embedded databases and cleartext config files
- [x] Implement secret management surfaces
  - [x] create `core/secrets/routes.py`
  - [x] operator-oriented CLI hooks for create, rotate, inspect metadata, disable, and revoke
  - [x] MCP hooks only where the operation is intentionally safe and policy-gated
  - [x] ensure secret inspection surfaces never return raw secret values
- [x] Implement runtime recovery primitives
  - [x] create `core/recovery/models.py`
  - [x] create `core/recovery/store.py`
  - [x] create `core/recovery/runtime_recovery.py`
  - [x] model recoverable vs non-recoverable runtime failures explicitly
  - [x] define restart intents and recovery markers separately from normal runtime state
  - [x] keep recovery orchestration in `recovery/`, not inside runtime session models
- [x] Implement failed-start recovery
  - [x] create `core/recovery/failed_start_recovery.py`
  - [x] classify failed start causes such as missing secret, invalid provider setup, contract failure, and process crash
  - [x] support repair-first recovery paths before restart where the architecture allows them
  - [x] persist operator-meaningful recovery status without leaking sensitive values
- [x] Implement health-check framework
  - [x] create `core/recovery/health_checks.py`
  - [x] distinguish runtime health, provider health, and app health
  - [x] support scheduled or on-demand health probes without coupling them to transport routes
  - [x] make health results available to recovery decisions and operator inspection surfaces
- [x] Implement recovery-oriented CLI and MCP hooks
  - [x] create `core/recovery/service.py`
  - [x] create `core/recovery/errors.py`
  - [x] create `core/recovery/routes.py`
  - [x] restart runtime through the runtime lifecycle when the runtime store is available
  - [x] inspect recovery state
  - [x] run on-demand runtime, provider, and app health probes
  - [x] trigger repair or recovery workflows where allowed
  - [x] expose recovery status without exposing secret values

## Phase 11: Observability and Logs

- [x] Implement installation-level log roots:
  - `logs/platform/`
  - `logs/runtime/`
- [x] Implement workspace log roots:
  - `logs/workspace/`
  - `logs/apps/<app_id>/`
- [x] Implement observability model and store contracts
  - [x] create `core/observability/models.py`
  - [x] create `core/observability/store.py`
  - [x] create `core/observability/errors.py`
- [x] Implement platform audit surface separate from raw logs
  - [x] create `core/observability/audit_log.py`
  - [x] record control-plane operations such as workspace governance changes, app installation, provider binding, and secret resolution attempts
  - [x] wire audit emission into real app, provider, runtime, secrets, and recovery flows
  - [x] keep audit records structured and queryable
  - [x] ensure audit entries never include raw secret values
- [x] Implement structured event attribution:
  - [x] create `core/observability/event_log.py`
  - [x] `workspace_id`
  - [x] `app_id`
  - [x] `run_id` or equivalent
  - [x] event plane
  - [x] emit structured events from real core flows, not only from tests
- [x] Implement correlation and source attribution fields:
  - [x] `runtime_session_id`
  - [x] `turn_id`
  - [x] `provider_id` when relevant
  - [x] source component or domain
- [x] Implement metrics surface
  - [x] create `core/observability/metrics.py`
  - [x] runtime metrics
  - [x] recovery and health metrics
  - [x] app lifecycle and platform operation counters where meaningful
- [x] Implement runtime log handling
  - [x] create `core/observability/runtime_log.py`
- [x] Implement observability orchestration surface
  - [x] create `core/observability/service.py`
  - [x] create `core/observability/routes.py`
- [x] Implement retention and rotation policy
- [x] Implement redaction rules for observability payloads
  - [x] avoid raw secrets in logs
  - [x] avoid raw provider credentials in audit trails
  - [x] avoid leaking sensitive runtime env values into structured event payloads
- [x] Ensure logs are excluded from workspace export by default

## Phase 12: File Inventory, Export, Import, Restore

- [x] Implement file inventory layer with stable `file_id`
- [x] Implement uploaded/generated file discovery from filesystem
- [x] Implement export manifest generation
- [x] Implement coordinated workspace export for the Phase 13 unblocker slice
  - [x] plan app participation during export
  - [x] run declared app export hooks before manifest generation
  - [x] pass workspace and app data-plane context into export hooks
  - [x] include per-app data schema metadata in the manifest
  - [x] exclude runtime, tmp, logs, and inventory metadata from default workspace export snapshots
  - [x] exclude caches from default workspace export snapshots
- [ ] Implement import flow with dormant app data support
- [ ] Implement restore flow
- [ ] Expand snapshot consistency strategy beyond the minimal export-hook-first slice:
  - [ ] app quiesce
  - [ ] richer coordinated export for dormant app data restore

## Phase 13: First Built-In Apps for v3

- [x] Decide the minimal built-in app set for first boot
  - [x] `base-shell`
  - [x] `chat`
- [x] Define the mounted app model for first hosted deployment:
  - [x] core runs behind `maverick3.versy.ai` as the platform host
  - [x] apps are mounted by the core, not deployed by default as separate public services
  - [x] each app may expose `frontend/`, `backend/`, `mcp/`, `cli/`, and `skills/`
  - [x] the product shell is also an app, not part of the core
- [x] Implement `chat` as an app on top of core runtime interfaces
- [x] Implement `base-shell` as the minimal mounted frontend shell app
- [ ] Implement `agents` as an app on top of core runtime/provider system
- [x] Decide whether `memory` is in the first wave or the second wave
  - [x] second wave
- [x] For each built-in app, enforce:
  - [x] explicit app contract
  - [x] explicit declared surfaces chosen from `frontend/`, `backend/`, `mcp/`, `cli/`, and `skills/`
  - [x] storage under `data/<app_id>/` when the app is stateful
- [x] Define first-wave deployment wiring for hosted v3:
  - [x] main core `systemd` service
  - [x] independent `rescue` `systemd` service
  - [x] `nginx` routing for mounted app frontend/backend paths

## Phase 14: Acceptance Criteria for First Usable v3

- [ ] Fresh install creates `default` workspace correctly
- [ ] New non-default workspace can be created
- [ ] Non-default workspace agent is sandboxed to workspace root
- [ ] Default workspace agent can run `full-access`
- [ ] External app can be installed into one workspace only
- [ ] Workspace-local app can be created, installed, enabled, disabled, uninstalled
- [ ] Core can route runtime turns
- [ ] Core can delegate between agents
- [ ] Core can switch runtime backend via provider abstraction
- [x] Chat app works on top of core runtime interfaces
- [x] Hosted v3 is reachable at `maverick3.versy.ai`
- [x] Base shell app mounts chat frontend through the core host
- [ ] Export/import works for one workspace without legacy assumptions

## Phase 8: Inter-Agent Communication

- [ ] Implement inter-agent message model
- [ ] Implement delegation model
- [ ] Implement queueing model
- [ ] Implement delivery retry model
- [ ] Implement reconciliation model
- [ ] Implement status propagation model
- [ ] Implement cross-agent orchestration rules scoped to one workspace
- [ ] Implement observability for inter-agent delivery lifecycle
- [ ] Make inter-agent communication a first-class core capability, not an incidental runtime helper

## Recommended Build Order

1. Phase 0
2. Phase 1
3. Phase 2
4. Phase 3
5. Phase 4
6. Phase 5
7. Phase 6
8. Phase 7
9. Phase 9
10. Phase 10
11. Phase 11
12. Phase 12
13. Phase 13
14. Phase 14
15. Phase 8

## Immediate Next Step

Start with a concrete bootstrap commit in `maverick-v3` containing:

- root folder structure
- docs copied in
- empty core tree scaffold
- naming conventions enforced from day one

Do not start by porting code from `v2`.

Start by making the target structure real on disk first.
