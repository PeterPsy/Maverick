# Senses

Senses is a root Maverick app for device and sensor inputs. Phase 1 implements
user-session pairing and the workspace-scoped device registry without adding a
public bearer-token ingress.

## Phase 1 Surfaces

- frontend: `frontend/dist`
- backend: `manifest`, `health`, `overview`, `pairing.start`,
  `pairing.complete`, `pairing.status`, `devices.list`, `devices.revoke`,
  `settings.get`, `settings.update`
- CLI: `senses` for manifest, health, and reference discovery
- MCP: `senses_operations_manifest`, `senses_reference_manifest`
- hooks: `install`, `migrate`, `health_check`

The MVP auth mode is `user_session_mvp`. Mounted backend calls use the Maverick
user session supplied by `/api/apps/senses/backend`; Senses does not accept a raw
device token in Phase 1. Pairing, registry, and settings operations are
backend/view-only in Phase 1 because standard CLI/MCP app contexts do not carry
a Maverick user session.

## Data

Workspace data is owned by the app under:

```text
workspaces/<workspace_id>/data/senses/
```

The SQLite file is:

```text
workspaces/<workspace_id>/data/senses/senses.sqlite
```

Phase 1 creates these workspace-scoped tables:

- `schema_migrations`
- `settings`
- `devices`
- `pairing_sessions`
- `device_sessions`
- `audit`

## Pairing

`pairing.start` creates a short code with a bounded TTL and returns a
machine-readable QR payload. `pairing.complete` requires a Maverick user session
and associates the completing iOS device with that user and workspace. The
server stores only registry/session metadata; device-token ingress is deferred.

Users can revoke their own devices. Workspace admins can list and revoke all
workspace devices and update Senses settings.

## Verify

```bash
maverick core cli run core.app-sdk.validate --app-root apps/senses --json
maverick app senses frontend build --json
python3 -m unittest discover -s apps/senses/tests -p 'test_*.py'
python3 -m compileall apps/senses/backend apps/senses/cli apps/senses/mcp apps/senses/hooks
```

After Senses and Storage are installed and enabled in the workspace, configure
the required Storage providers from an authorized workspace-admin context:

```bash
maverick core cli run app.senses.dependencies.set \
  --arguments-json '{"alias":"storage-file-content-write","provider_app_ids":["storage"]}' \
  --json
maverick core cli run app.senses.dependencies.set \
  --arguments-json '{"alias":"storage-file-catalog","provider_app_ids":["storage"]}' \
  --json
maverick core cli run app.senses.dependencies --json
maverick app senses cli run senses --action health --json
```

Runtime readiness is true only when `ok` is `true` and
`dependencies.status == "resolved"`.
