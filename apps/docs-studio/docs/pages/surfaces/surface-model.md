# Surface model

An app surface is a declared way the core can mount, invoke, or expose app-owned behavior. The contract is the source of truth.

## Surface taxonomy

| Surface | Executable? | Owner | Purpose |
| --- | --- | --- | --- |
| Frontend | no direct mutation authority | app | user interface mounted by the core |
| Backend | yes | app | JSON actions behind `/api/apps/<app_id>/backend` |
| CLI | yes | app or core | command-oriented automation |
| MCP | yes | app or core | structured tool invocation |
| Skills | no | app template, Skills app copy | procedural instructions for runtime agents |
| Hooks | yes | app | install, migrate, health, import/export lifecycle |
| Widgets | visual, action-limited | app | embeddable iframe visual surface |
| Data events | notification | app/core transport | tell mounted clients what changed |

## Contract discipline

- Declared surfaces must exist.
- Discoverable surfaces must be scoped by owner.
- Mutating surfaces should emit `app_events` when mounted views need refresh.
- Skills are not security boundaries or executable APIs.

> **Source:** `docs/reference/core_surfaces.md`, `docs/app-sdk/getting_started.md`
