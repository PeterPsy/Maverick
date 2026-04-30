# Core boundaries

## Core responsibilities

| Domain | Responsibility |
| --- | --- |
| Identity | Users, auth, sessions, workspace membership |
| Workspaces | Registry, governance, quotas, policy state |
| Apps | Source registration, installation, enablement, lifecycle |
| Runtime | Sessions, turns, events, provider process orchestration |
| Providers | Model backend registry, credentials, selection |
| Execution policy | Sandbox/full-access decisions and workspace boundaries |
| Secrets | Secret metadata, bindings, resolution, ephemeral delivery |
| Recovery | Health checks, restart intent, failure diagnosis |

## Non-goals

- Business records, memory notes, chat threads, or docs.
- App-specific conditions in core code.
- Direct reads from app-private stores.

> **Boundary test:** if a behavior is specific to one product experience, it belongs in that app.


## File organization principle

Core domains should stay explicit. Prefer names like `workspace_registry.py`, `provider_selection.py`, or `runtime_turns.py` over broad utility buckets.

## Storage principle

The core domain model is storage-agnostic. Mongo, SQLite, or another adapter can exist, but raw driver shapes must stay inside store adapters and bootstrap wiring.

## App-agnostic test

If deleting one app would make a core branch meaningless, that branch probably belongs somewhere else.
