---
name: agents-ops
description: Manage Maverick agent roles, agent types, prompt previews, and agent catalog data through the Agents app.
---

# Agents Ops

Use the Agents app surfaces to inspect and manage workspace agent definitions.

Prefer the `app.agents.maverick_agents_app` MCP tool for automated catalog work. Keep role and agent type changes scoped to workspace-owned agents data, and do not edit core runtime internals to change agent behavior.

Agent execution requires the generic Maverick runtime launch contract. Until that contract is available, treat runtime start and delegation actions as unavailable instead of faking live execution.
