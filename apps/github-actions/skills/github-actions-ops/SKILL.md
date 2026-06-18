---
name: github-actions-ops
description: Use the `github-actions` Maverick app to dispatch GitHub Actions workflows and inspect run status/logs through a GitHub App installation.
---

# GitHub Actions Operations

Use the app's official CLI or MCP surfaces. Do not read or write another app's
private data, and do not ask users to paste GitHub App secrets in chat.

Default CameraAccess install run:

```bash
maverick app github-actions cli run github-actions --json --arguments-json '{"action":"dispatch_and_wait","timeout_seconds":900}'
```

Useful actions:

- `manifest`
- `dispatch`
- `dispatch_and_wait`
- `list_runs`
- `run_status`
- `run_logs`
- `wait`
