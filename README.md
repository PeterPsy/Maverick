# Maverick v3

Maverick v3 is a clean rebuild of Maverick with:

- a standalone headless core
- standalone apps
- workspace-first isolation
- provider-agnostic runtime architecture
- explicit inter-agent communication as a core capability

This repository is intentionally separate from `maverick-v2`.

It is not a backward-compatible continuation of the v2 codebase.

## Initial Layout

```text
/home/ubuntu/maverick-v3/
  apps/
  core/
  docs/
  scripts/
  workspaces/
```

## Core Layout Rule

`core/` is the package root of the Maverick core.

This means:

- the core code lives directly under `core/`
- the core must not be wrapped in extra technical folders such as `backend/`, `runtime_backend/`, or `app/`
- the core is organized by Maverick domains such as `runtime/`, `identity/`, `workspaces/`, `providers/`, `mcp/`, and `cli/`
- the repository must not introduce an ambiguous `core/core/` subtree

If shared internal code is needed inside the core, it should live under an explicit domain-oriented name such as `shared/` or `foundation/`, not under `core/core/`

## Documentation

The initial architecture documents live in `docs/`:

- `workspace_root_architecture.md`
- `app_contract_architecture.md`
- `core_architecture.md`
- `IMPLEMENTATION_TASKLIST.md`

## Build Principle

v3 starts from a clean structure and only reintroduces concepts that still fit the new architecture.
