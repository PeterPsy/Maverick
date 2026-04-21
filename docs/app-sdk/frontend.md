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
