# Loopinos Apps

Private workspace app monorepo for Loopinos/Maverick apps that are developed outside the platform core repository.

## Layout

```text
apps/
  crm/
```

Each app remains a normal Maverick app root with its own `app_contract.json`, README, tests, app-owned surfaces, and frontend build artifacts when they are intentionally committed.

Workspace runtime state, app data, uploaded files, logs, and temporary files are not tracked in this repository.
