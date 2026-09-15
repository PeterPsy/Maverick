---
name: agents-ops
description: Manage self-contained Maverick custom agent definitions through the Agents app.
---

# Agents Ops

Use `app.agents.agents_catalog_compact` to browse custom agents and
`app.agents.agents_get_agent_definition` to read one. Create or update exactly
one record with `app.agents.agents_upsert_agent_definition`; its behavior is
only `instructions` plus explicitly selected `skill_ids`. Use
`app.agents.agents_delete_agent_definition` to delete it.

Free Agent and Research are fixed Chat runners, not catalog records.
