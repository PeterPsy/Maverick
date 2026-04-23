# Maverick App SDK Frontend Guide

Date: 2026-04-21

SDK-generated frontends are mounted by the core through the app contract.

The contract entrypoint must point to:

```text
frontend/dist
```

React/Vite templates include source under:

```text
frontend/src/
```

Mounted frontends call their app backend through:

```text
/api/apps/<app_id>/backend
```

Do not call another app's private backend or private files directly. Use the owning app's official backend, CLI, or MCP surfaces.

## Rebuild Rule

If the app declares `lifecycle.rebuild: true`, frontend updates should be published through:

```text
maverick app <app_id> frontend build --json
```

That is the official path that:

- runs the declared frontend build
- verifies the declared frontend artifact root
- emits `maverick.app.frontend-changed`
- lets mounted clients refresh without a manual full-page reload

Do not rely on ad hoc static servers or undocumented rebuild shortcuts.

For static HTML apps with inline `<script>` blocks, add a syntax gate before closing the task:

```text
python3 scripts/check_inline_script_syntax.py apps/<app_id>/frontend/dist/index.html
```

Include widget HTML mounts when they also contain inline scripts.

## Live Update Rule

If app writes emit `app_events` such as `maverick.app.data-changed`, the mounted frontend should react to them without manual refresh.

Recommended pattern:

- listen for same-origin `postMessage` events such as `maverick.app.data-changed` when the app is mounted inside `base-shell`
- connect to the official app-event WebSocket at `/api/apps/events/ws` when the app also needs to refresh outside shell forwarding
- filter by `owner_app_id` and `resource`
- reload the affected view state through the app's own backend surface

Do not rely on stale startup-only fetches for stateful apps. If the app emits live change events, the frontend implementation should consume them.
