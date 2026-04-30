# Verification checklist

## Core and Python checks

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall core tests scripts
python3 scripts/check_unused_imports.py
```

## Workspace-local app checks

```bash
maverick core cli run core.app-sdk.validate --app-id <app_id> --json
maverick core cli run core.app-sdk.register-local --app-id <app_id> --json
maverick core cli run core.app-sdk.install-local --app-id <app_id> --json
maverick core cli run core.app-sdk.status --app-id <app_id> --json
```

## Frontend checks

```bash
npm run build
maverick app <app_id> frontend build --json
```

## Smoke checks

- [ ] App is listed by `maverick apps list --json`.
- [ ] Declared CLI commands appear in scoped CLI discovery.
- [ ] Declared MCP tools appear in scoped MCP discovery.
- [ ] App data exists under `data/<app_id>`.
- [ ] Mounted frontend loads from `frontend/dist`.


## What each check proves

| Check | Proves |
| --- | --- |
| Contract validation | Declared app surfaces and entrypoints line up |
| CLI/MCP discovery | The core can expose app-owned executable surfaces |
| Frontend build | Source can regenerate mounted assets |
| App status | Source, registration, installation, enablement, and validation are coherent |
| Smoke invocation | The declared surface actually runs |

## Release-ready app checklist

- [ ] Source exists under the expected app root.
- [ ] Contract validates with no issues.
- [ ] Workspace-local project is registered.
- [ ] App is installed and enabled for the workspace.
- [ ] App data root exists under `data/<app_id>`.
- [ ] Package artifact has been regenerated if useful.
