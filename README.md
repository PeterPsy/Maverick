# Loopinos Apps

Private workspace app monorepo for Loopinos/Maverick apps that are developed outside the platform core repository.

**Important:** this repository is not the Maverick `design` repository. For
core work, built-in apps, `base-shell`, `chat`, `storage`, app hosting, or any
task described as work on the `design` branch, use:

```text
/home/ubuntu/projects/maverick-v3
```

This repository is intentionally separate from the platform/core repository. It tracks app source only; the platform core continues to own hosting, contracts, registration, mounting, workspace policy, runtime execution, and app lifecycle orchestration.

## Layout

```text
apps/
  crm/
  mail/
  website-studio/
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

The active workspace paths for local app development are:

```text
apps/crm/
apps/mail/
apps/website-studio/
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

For Mail, use the same app-local test/build pattern from `apps/mail/`, and
validate the installed workspace surface with `maverick app mail ...` commands
when Mail is the changed app.

For Website Studio, use the same app-local test/build pattern from
`apps/website-studio/`, and validate the installed workspace surface with:

```bash
maverick core cli run core.app-sdk.validate --app-id website-studio --json
maverick app website-studio frontend build --json
maverick app website-studio cli list --json
maverick app website-studio mcp list --json
```

Commit app source changes here. Commit core/platform changes only in the separate Maverick/Loopinos core repository.

If `apps/chat`, `apps/base-shell`, or `apps/storage` appears to be missing, you
are in this workspace-local repository. Switch to
`/home/ubuntu/projects/maverick-v3` before continuing with built-in app or
platform work.

For app lookup, prefer root app source first:

```bash
test -d /home/ubuntu/projects/maverick-v3/apps/<app_id>
```

Then fall back to workspace-local source only when needed:

```bash
test -d /home/ubuntu/projects/maverick-v3/workspaces/default/apps/<app_id>
```
