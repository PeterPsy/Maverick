# Maverick App SDK Templates

Date: 2026-04-21

## Template Summary

- `minimal`: contract-first skeleton.
- `frontend-backend`: mounted React/Vite frontend plus JSON backend and official frontend build support.
- `agent-tool`: CLI, MCP, and skill template.
- `data-app`: JSON state app with React/Vite frontend, lifecycle hooks, and official frontend build support.
- `widget`: mounted React/Vite widget declaration for `base-shell` and official frontend build support.
- `react-vite`: React/Vite frontend source with committed `frontend/dist` smoke output and official frontend build support.
- `entity-sqlite`: record-centric SQLite entity app with reference entities, view surfaces, and official frontend build support.

## Choosing A Template

Use `entity-sqlite` for business records, record-centric workflows, referenceable entities, and apps that need durable structured state.

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
- `package.json` build script present.
- React/Vite source under `frontend/src`.
- Official frontend build support.

`agent-tool`

- CLI, MCP, and skill surfaces.
- Good for operator or agent capability apps with no human UI.

`data-app`

- Frontend, backend, CLI, MCP, and lifecycle hooks.
- Good for simple JSON-state tools.
- `package.json` build script present.
- React/Vite source under `frontend/src`.
- Official frontend build support.
- If you add mutating actions that emit `maverick.app.data-changed`, also add frontend live-update wiring instead of relying on startup-only loads.

`widget`

- React/Vite frontend, backend, and widget declaration.
- Use when the app primarily contributes an embeddable mounted widget.
- `package.json` build script present.
- Widget React source under `frontend/src/widgets/main`.
- Official frontend build support.
- If widget state depends on app writes, consume `maverick.widget.data-changed` in the widget frontend.

`react-vite`

- Mounted React/Vite frontend plus backend.
- `package.json` build script present.
- Official frontend build support.
- Use `maverick app <app_id> frontend build --json` after frontend edits.
- When app writes emit live change events, wire the frontend to `/api/apps/events/ws` or shell-forwarded `postMessage` updates.

`entity-sqlite`

- Full-stack app with React/Vite frontend, backend, CLI, MCP, lifecycle hooks, reference entities, and view surfaces.
- `package.json` build script present.
- Official frontend build support.
- Best starting point when developers need to learn how to expose a complete app surface area cleanly.
- Treat emitted `maverick.app.data-changed` events as part of the template completion bar for mounted views.
