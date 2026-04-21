# Maverick App SDK Templates

Date: 2026-04-21

## Template Summary

- `minimal`: contract-first skeleton.
- `frontend-backend`: mounted static frontend plus JSON backend.
- `agent-tool`: CLI, MCP, and skill template.
- `data-app`: JSON state app with lifecycle hooks.
- `widget`: mounted widget declaration for `base-shell`.
- `react-vite`: React/Vite frontend source with committed `frontend/dist` smoke output.
- `entity-sqlite`: CRM-inspired SQLite entity app.

## Choosing A Template

Use `entity-sqlite` for business records, CRM-like workflows, referenceable entities, and apps that need durable structured state.

Use `react-vite` when the main need is an app frontend and the domain model is not yet stable.

Use `data-app` for small stateful tools that do not need relational storage.

Use `agent-tool` for agent/operator capability apps without a human UI.

Use `widget` when the app primarily contributes an embeddable shell widget.

## Template Rule

Generated files are starting source. Replace placeholder behavior with real product behavior before marking an app complete.
