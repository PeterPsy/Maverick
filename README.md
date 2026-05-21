# Loopinos Apps

Private workspace app monorepo for Loopinos/Maverick apps that are developed outside the platform core repository.

This repository is intentionally separate from the platform/core repository. It tracks app source only; the platform core continues to own hosting, contracts, registration, mounting, workspace policy, runtime execution, and app lifecycle orchestration.

## Layout

```text
apps/
  crm/
```

Each app remains a normal Maverick app root with its own `app_contract.json`, README, tests, app-owned surfaces, and frontend build artifacts when they are intentionally committed.

Workspace runtime state, app data, uploaded files, logs, and temporary files are not tracked in this repository.

## Repository Boundary

Track:

- app source under `apps/<app_id>/`
- `app_contract.json`
- app README and tests
- app-owned backend, CLI, MCP, hook, skill, and frontend source files
- frontend `dist/` artifacts when the app contract expects committed mounted assets

Do not track:

- workspace data such as `data/<app_id>/`
- SQLite databases, exported customer records, or runtime state
- `node_modules/`, Python bytecode, caches, logs, and temporary files
- platform core files from the Maverick/Loopinos repository

## Local Development

The active workspace path for CRM is:

```text
apps/crm/
```

From the CRM app root:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
npm run build
```

From the workspace root, validate the app through the platform surface:

```bash
maverick core cli run core.app-sdk.validate --app-id crm --json
maverick app crm cli list --json
maverick app crm mcp list --json
```

Commit app source changes here. Commit core/platform changes only in the separate Maverick/Loopinos core repository.
