# Control plane versus data plane

Maverick separates platform state from workspace content so app behavior can evolve without turning the core into a business database.

## The three planes

| Plane | Scope | Examples |
| --- | --- | --- |
| Global control plane | installation-wide | users, sessions, platform roles, workspace registry |
| Workspace governance plane | one workspace | app enablement, workspace permissions, quotas |
| Workspace data plane | one workspace's content | `data/<app_id>`, generated files, uploads, app databases |

## Why the distinction matters

- Governance decides whether a capability is allowed.
- The owning app decides what its records mean.
- The workspace root contains the operational content.
- The core indexes, mounts, and enforces policy without reading app-private schemas.

## Example

The Agents app owns agent definitions under `data/agents`. The core owns runtime sessions that execute a selected agent definition. The provider adapter owns backend-specific launch and thread protocol.

> **Source:** `docs/architecture/workspace_root_architecture.md`
