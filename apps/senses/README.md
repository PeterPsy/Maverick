# Senses

Senses is a root Maverick app for device and sensor inputs. Phase 2 implements
user-session pairing, the workspace-scoped device registry, and authenticated
frame ingestion through Storage-backed capture records without adding a public
bearer-token ingress.

## Phase 2 Surfaces

- frontend: `frontend/dist`
- backend: `manifest`, `health`, `overview`, `pairing.start`,
  `pairing.complete`, `pairing.status`, `devices.list`, `devices.revoke`,
  `settings.get`, `settings.update`, `ingest.frame`
- dependency callback: `storage_write.completed`
- CLI: `senses` for manifest, health, and reference discovery
- MCP: `senses_operations_manifest`, `senses_reference_manifest`
- hooks: `install`, `migrate`, `health_check`

The MVP auth mode is `user_session_mvp`. Mounted backend calls use the Maverick
user session supplied by `/api/apps/senses/backend`; Senses does not accept a raw
device token in Phase 2. Pairing, registry, settings, and ingestion operations
are backend/view-only because standard CLI/MCP app contexts do not carry a
Maverick user session.

## Data

Workspace data is owned by the app under:

```text
workspaces/<workspace_id>/data/senses/
```

The SQLite file is:

```text
workspaces/<workspace_id>/data/senses/senses.sqlite
```

Phase 2 creates these workspace-scoped tables:

- `schema_migrations`
- `settings`
- `devices`
- `pairing_sessions`
- `device_sessions`
- `ingestion_requests`
- `captures`
- `audit`

## Pairing

`pairing.start` creates a short code with a bounded TTL and returns a
machine-readable QR payload. `pairing.complete` requires a Maverick user session
and associates the completing iOS device with that user and workspace. The
server stores only registry/session metadata; device-token ingress is deferred.

Users can revoke their own devices. Workspace admins can list and revoke all
workspace devices and update Senses settings.

## Frame Ingestion

`ingest.frame` requires a Maverick user session, an active paired device, an
active `device_session_id`, `schema_version=senses.capture.v1`, `request_id`,
and `idempotency_key`. Senses generates the authoritative `capture_id` and
Storage path, validates MIME, base64, decoded size, timestamp skew and optional
client hash, strips JPEG EXIF APP1 metadata, then creates `ingestion_requests`
and `captures` records before returning a declared dependency request to
Storage `file.content.write`.

Storage writes use:

```text
storage/generated/senses/<device_id>/<yyyy-mm-dd>/<capture_id>.<jpg|png>
```

The `storage_write.completed` dependency callback updates the capture to
`stored` with Storage file id, workspace-relative path, sha256 and size. It does
not return runtime launch requests; routing remains a later phase through
`routing.dispatch_capture`.

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

## SDK Flow

```bash
maverick core cli run core.app-sdk.validate --app-root apps/senses --json
maverick app senses frontend build --json
maverick app senses cli list --json
maverick app senses mcp list --json
```

## Contract Notes

Senses is a sealed, sandbox-compatible root app. Its contract declares
frontend/backend/CLI/MCP surfaces, install/migrate/health hooks, app-owned
SQLite state under `data/senses`, required Storage dependency aliases for file
creation and catalog metadata, and data events for devices, pairing, settings,
and captures. Runtime session creation, device-token ingress, capture reference
entities, and routing are intentionally deferred beyond Phase 2.
