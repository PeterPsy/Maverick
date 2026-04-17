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
- [x] Copy or move the approved architecture documents into `maverick-v3/docs/`
- [ ] Initialize git in `maverick-v3` or connect it to the intended remote strategy
- [x] Create a root `.gitignore` for:
  - [x] runtime state
  - [x] app-local DB files
  - [x] logs
  - [x] tmp
  - [x] generated build output
- [ ] Define repository conventions:
  - Python version
  - package layout
  - lint/test commands
  - environment bootstrap

## Phase 1: Define the v3 Filesystem Contract

- [x] Implement the canonical installation layout:
  - [x] `/maverick-v3/core/`
  - [x] `/maverick-v3/apps/`
  - [x] `/maverick-v3/workspaces/`
- [ ] Define canonical workspace path helpers
- [ ] Define canonical app path helpers
- [ ] Define canonical storage path helpers
- [ ] Define canonical logs path helpers
- [ ] Define canonical runtime path helpers
- [ ] Define canonical file identity rules:
  - `file_id`
  - relative path
  - hash
  - timestamps
- [ ] Define canonical export manifest structure

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
- [ ] Add a small per-domain file pattern:
  - `routes.py`
  - `service.py`
  - `models.py`
  - `store.py`
  - `errors.py` when needed
- [x] Ensure the core tree lives directly under `/maverick-v3/core/` with no wrapper layers such as `backend/`, `runtime_backend/`, or `app/`

## Phase 3: Identity and Workspace Governance

- [ ] Implement users model
- [ ] Implement auth/session model
- [ ] Implement workspace registry model
- [ ] Implement workspace membership model
- [ ] Implement workspace governance model
- [ ] Implement workspace quota/limit model
- [ ] Implement workspace creation flow
- [ ] Implement automatic creation of `default` workspace
- [ ] Implement workspace execution profile:
  - `default` can allow `full-access`
  - non-default workspaces are sandbox-only

## Phase 4: App Hosting and Installation System

- [ ] Implement app installation records in the core
- [ ] Implement distinction between:
  - external installed app
  - workspace-local app project
  - app enabled state
- [ ] Implement install flow for external app bundles
- [ ] Implement install flow for workspace-local apps under `workspaces/<id>/apps/`
- [ ] Implement uninstall flow
- [ ] Implement purge-data flow
- [ ] Implement reinstall flow
- [ ] Implement compatibility checks:
  - minimum core version
  - contract version
  - supported workspace modes if declared

## Phase 5: App Contract Execution Layer

- [ ] Implement parser/validator for app contract files
- [ ] Implement support for:
  - `contract_version`
  - `minimum_core_version`
  - `entrypoints`
  - `storage`
  - `capabilities`
  - `lifecycle`
  - `compatibility`
  - `hook_timeouts`
  - `failure_semantics`
  - `health_contract`
  - `rollback_support`
- [ ] Implement deterministic resolution of:
  - MCP entrypoint
  - CLI entrypoint
  - skills root
  - lifecycle hooks
- [ ] Implement health contract execution
- [ ] Implement install/upgrade timeout enforcement

## Phase 6: Workspace Runtime Model

- [ ] Implement runtime session abstraction
- [ ] Implement turn abstraction
- [ ] Implement runtime event abstraction
- [ ] Implement runtime process abstraction
- [ ] Implement runtime state model
- [ ] Implement workspace-aware runtime routing
- [ ] Implement `sandbox` execution mode
- [ ] Implement `full-access` execution mode
- [ ] Ensure non-default workspace runtime cannot escape workspace root
- [ ] Ensure `default` runtime can operate beyond workspace root only when explicitly configured

## Phase 7: AI Provider Abstraction

- [ ] Implement provider registry
- [ ] Implement provider model and capability metadata
- [ ] Implement provider credential store and binding logic
- [ ] Implement runtime backend selection flow
- [ ] Define the provider/runtime distinction clearly in code:
  - runtime abstraction
  - provider/backend adapter
- [ ] Implement first provider backend:
  - `Codex`
- [ ] Define extension points for future backends:
  - Claude Code
  - Kimi
  - local OSS runtime
  - API-key based hosted models

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

## Phase 9: MCP, CLI, and Skills Surfaces

- [ ] Implement core MCP host surface
- [ ] Implement core CLI surface
- [ ] Implement core skills loading model
- [ ] Define which core operations are exposed:
  - MCP only
  - CLI only
  - both
- [ ] Clarify CLI invocation policy for sandboxed workspace agents
- [ ] Ensure `skills/` is treated as instructional, not as executable runtime boundary

## Phase 10: Secrets and Recovery

- [ ] Implement platform secret store
- [ ] Implement workspace/app secret references
- [ ] Implement secret resolution at runtime
- [ ] Ensure secret values never land in app-owned data
- [ ] Implement runtime recovery primitives
- [ ] Implement failed-start recovery
- [ ] Implement health-check framework
- [ ] Implement recovery-oriented CLI and MCP hooks

## Phase 11: Observability and Logs

- [ ] Implement installation-level log roots:
  - `logs/platform/`
  - `logs/runtime/`
- [ ] Implement workspace log roots:
  - `logs/workspace/`
  - `logs/apps/<app_id>/`
- [ ] Implement structured event attribution:
  - `workspace_id`
  - `app_id`
  - `run_id` or equivalent
  - event plane
- [ ] Implement retention and rotation policy
- [ ] Ensure logs are excluded from workspace export by default

## Phase 12: File Inventory, Export, Import, Restore

- [ ] Implement file inventory layer with stable `file_id`
- [ ] Implement uploaded/generated file discovery from filesystem
- [ ] Implement export manifest generation
- [ ] Implement coordinated workspace export
- [ ] Implement import flow with dormant app data support
- [ ] Implement restore flow
- [ ] Implement snapshot consistency strategy:
  - app quiesce, or
  - app export hook

## Phase 13: First Built-In Apps for v3

- [ ] Decide the minimal built-in app set for first boot
- [ ] Implement `chat` as an app on top of core runtime interfaces
- [ ] Implement `agents` as an app on top of core runtime/provider system
- [ ] Decide whether `memory` is in the first wave or the second wave
- [ ] For each built-in app, enforce:
  - `mcp/`
  - `cli/`
  - `skills/`
  - app contract
  - storage under `data/<app_id>/`

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
- [ ] Chat app works on top of core runtime interfaces
- [ ] Export/import works for one workspace without legacy assumptions

## Recommended Build Order

1. Phase 0
2. Phase 1
3. Phase 2
4. Phase 3
5. Phase 4
6. Phase 5
7. Phase 6
8. Phase 7
9. Phase 8
10. Phase 9
11. Phase 10
12. Phase 11
13. Phase 12
14. Phase 13
15. Phase 14

## Immediate Next Step

Start with a concrete bootstrap commit in `maverick-v3` containing:

- root folder structure
- docs copied in
- empty core tree scaffold
- naming conventions enforced from day one

Do not start by porting code from `v2`.

Start by making the target structure real on disk first.
