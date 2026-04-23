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
