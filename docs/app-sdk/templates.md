# Maverick App SDK Templates

Date: 2026-04-21

## Template Summary

- `minimal`: contract-first skeleton.
- `frontend-backend`: mounted static frontend plus JSON backend.
- `agent-tool`: CLI, MCP, and skill template.
- `data-app`: JSON state app with lifecycle hooks.
- `widget`: mounted widget declaration for `base-shell`.
- `react-vite`: React/Vite frontend source with committed `frontend/dist` smoke output and `lifecycle.rebuild` enabled.
- `entity-sqlite`: CRM-inspired SQLite entity app with reference entities, view surfaces, and `lifecycle.rebuild` enabled.

## Choosing A Template

Use `entity-sqlite` for business records, CRM-like workflows, referenceable entities, and apps that need durable structured state.

Use `react-vite` when the main need is an app frontend and the domain model is not yet stable.

Use `data-app` for small stateful tools that do not need relational storage.

Use `agent-tool` for agent/operator capability apps without a human UI.

Use `widget` when the app primarily contributes an embeddable shell widget.

## Template Rule

Generated files are starting source. Replace placeholder behavior with real product behavior before marking an app complete.

## Surface Expectations By Template

`minimal`

- Contract-first only.
- No executable app surfaces.

`frontend-backend`

- Mounted frontend plus app backend.
- No CLI or MCP by default.
- No official rebuild support by default because the template ships only static `frontend/dist`.

`agent-tool`

- CLI, MCP, and skill surfaces.
- Good for operator or agent capability apps with no human UI.

`data-app`

- Frontend, backend, CLI, MCP, and lifecycle hooks.
- Good for simple JSON-state tools.
- Frontend is static by default, so rebuild remains off until you add a real build pipeline.
- If you add mutating actions that emit `maverick.app.data-changed`, also add frontend live-update wiring instead of relying on startup-only loads.

`widget`

- Frontend, backend, and widget declaration.
- Use when the app primarily contributes an embeddable mounted widget.
- If widget state depends on app writes, consume `maverick.widget.data-changed` in the widget frontend.

`react-vite`

- Mounted React/Vite frontend plus backend.
- `package.json` build script present.
- `lifecycle.rebuild: true` enabled.
- Use `maverick app <app_id> frontend build --json` after frontend edits.
- When app writes emit live change events, wire the frontend to `/api/apps/events/ws` or shell-forwarded `postMessage` updates.

`entity-sqlite`

- Full-stack app with React/Vite frontend, backend, CLI, MCP, lifecycle hooks, reference entities, and view surfaces.
- `package.json` build script present.
- `lifecycle.rebuild: true` enabled.
- Best starting point when developers need to learn how to expose a complete app surface area cleanly.
- Treat emitted `maverick.app.data-changed` events as part of the template completion bar for mounted views.
