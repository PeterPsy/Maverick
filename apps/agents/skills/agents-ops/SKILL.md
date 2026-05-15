---
name: agents-ops
description: Manage Maverick agent roles, agent types, prompt previews, and agent catalog data through the Agents app.
---

# Agents Ops

Use the Agents app surfaces to inspect and manage workspace agent definitions.

Prefer `app.agents.maverick_agents_app` with no arguments for the compact operation manifest, `app.agents.agents_catalog_compact` for catalog reads, and `app.agents.agents_upsert_agent_definition` for create/update work. Keep role and agent type changes scoped to workspace-owned agents data, and do not edit core runtime internals to change agent behavior.

Agent execution requires the generic Maverick runtime launch contract. Until that contract is available, treat runtime start and delegation actions as unavailable instead of faking live execution.
