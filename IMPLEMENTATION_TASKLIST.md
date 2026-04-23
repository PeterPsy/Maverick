# Maverick v3 Implementation Tasklist

Date: 2026-04-17

## Goal

Build Maverick v3 from a clean codebase under:

```text
Repository root
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


## Phase 12: File Inventory, Export, Import, Restore

- [x] Implement file inventory layer with stable `file_id`
- [x] Implement uploaded/generated file discovery from filesystem
- [x] Implement export manifest generation
- [x] Implement coordinated workspace export for the Phase 13 unblocker slice
  - [x] plan app participation during export
  - [x] run declared app export hooks before manifest generation
  - [x] pass workspace and app data-plane context into export hooks
  - [x] include per-app data schema metadata in the manifest
  - [x] include workspace-local fork provenance in exported app references
  - [x] exclude runtime, tmp, logs, and inventory metadata from default workspace export snapshots
  - [x] exclude caches from default workspace export snapshots
- [ ] Implement import flow with dormant app data support
- [ ] Implement restore flow
- [ ] Expand snapshot consistency strategy beyond the minimal export-hook-first slice:
  - [ ] app quiesce
  - [ ] richer coordinated export for dormant app data restore


## Phase 14: Acceptance Criteria for First Usable v3

- [ ] Fresh install creates `default` workspace correctly
- [ ] New non-default workspace can be created
- [x] Non-admin members cannot create workspaces through `/api/workspaces`
- [x] Core exposes admin-only user CRUD and workspace assignment APIs
- [x] Core exposes admin-only user password reset and User Admin surfaces it for forgotten passwords
- [x] Core exposes admin-only workspace app installation and enablement APIs
- [x] Core enforces admin-only access for identity and workspace membership management
- [x] Disabled installed workspace apps are hidden from `/api/apps` and denied by app mount routes
- [x] App contract visibility can hide and deny app mounts by platform role
- [x] User Admin is installed as a sealed Maverick app for admin-only identity/workspace access management
- [x] User Admin can manage workspace app installed/enabled state through generic core APIs
- [x] User Admin frontend uses the same dark visual language as the shell and first-wave apps
- [x] Local hosted bootstrap persists identity and workspace control-plane state under `.maverick/local-state/`
- [x] Persisted non-default workspaces receive built-in app bindings again after host restart
- [x] Backend restart automatically resumes interrupted running runtime sessions
- [x] Non-default workspace agent is sandboxed to workspace root
- [x] Sandboxed non-default workspace agents can use `rg` inside the workspace without host filesystem reads
- [x] Default workspace agent can run `full-access`
- [ ] External app can be installed into one workspace only
- [x] App Store is installed as a Maverick app and can install a remote app into selected authorized workspaces
- [ ] Workspace-local app can be created, installed, enabled, disabled, uninstalled
- [x] Core can route runtime turns
- [ ] Core can delegate between agents
- [ ] Core can switch runtime backend via provider abstraction
- [x] Chat app works on top of core runtime interfaces
- [x] Hosted v3 can be served behind a deployment hostname.
- [x] Base shell app discovers and mounts enabled app frontends through the core host
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
