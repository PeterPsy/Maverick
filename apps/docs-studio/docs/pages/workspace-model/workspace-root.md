# Workspace root

## Canonical layout

```text
workspaces/<workspace_id>/
  apps/
  data/
  logs/
  runtime/
  storage/
    uploaded/
    generated/
  tests/
  tmp/
```

## What belongs where

| Path | Purpose |
| --- | --- |
| `apps/` | Workspace-local app source and forks |
| `data/<app_id>/` | Durable app-owned structured data |
| `storage/uploaded/` | User uploads |
| `storage/generated/` | Generated artifacts visible to Storage |
| `runtime/` | Ephemeral runtime/session state |
| `tmp/` | Scratch material |

> **Simple rule:** app-owned content lives in `data/<app_id>`, file artifacts live in `storage`.


## Data versus storage

Use `data/` for structured app state and `storage/` for file-like artifacts. This keeps the workspace understandable and lets Storage derive file inventory from actual files.

## Workspace-local apps

Workspace-created apps live under:

```text
apps/<app_id>/
```

Their durable data still lives separately under:

```text
data/<app_id>/
```

Source and data must not be conflated.
