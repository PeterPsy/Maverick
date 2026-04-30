# Core domain map

The Maverick core is the headless platform layer. It should be understandable as a set of small platform domains, not as a generic web backend.

## Domain responsibilities

| Core domain | Owns | Typical files |
| --- | --- | --- |
| `identity/` | users, auth, sessions, membership | `models.py`, `service.py`, HTTP route modules only when wired |
| `workspaces/` | registry, governance, quotas, active workspace | `governance.py`, `limits.py`, `store.py` |
| `apps/` | app sources, contracts, install, enablement, lifecycle | `registration.py`, `installation.py`, `status.py` |
| `runtime/` | sessions, turns, events, processes, state | `runtime_session.py`, `runtime_turns.py` |
| `providers/` | provider definitions, adapters, model metadata, credential binding | `provider_registry.py`, `provider_codex.py` |
| `execution_policy/` | sandbox/full-access policy and workspace boundaries | `policy.py`, `workspace_boundary.py` |
| `secrets/` | secret metadata, bindings, short-lived resolution | `secret_bindings.py`, `secret_resolution.py` |
| `recovery/` | health probes, restart intent, failed-start diagnosis | `health_checks.py`, `runtime_recovery.py` |
| `observability/` | audit, structured events, runtime logs, metrics | `event_log.py`, `audit_log.py` |

## File boundary rule

Core files should be named after the platform behavior they own. Avoid vague buckets such as `helpers.py`, `misc.py`, or app-specific branches in shared code.

## Storage boundary rule

Domain models and services stay storage-agnostic. Mongo, JSON, SQLite, or another adapter can exist, but driver payloads and persistence-only shapes should stay inside store adapters.

> **Source:** `docs/architecture/core_architecture.md`
