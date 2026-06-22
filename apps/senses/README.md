# Senses

Senses is a root Maverick app for device and sensor inputs. Phase 4 implements
user-session pairing, the workspace-scoped device registry, authenticated frame
ingestion through Storage-backed capture records, and explicit routing from
stored captures into Maverick Chat runtime threads without adding a public
bearer-token ingress.

## Phase 4 Surfaces

- frontend: `frontend/dist`
- backend: `manifest`, `health`, `overview`, `pairing.start`,
  `pairing.complete`, `pairing.status`, `devices.list`, `devices.revoke`,
  `settings.get`, `settings.update`, `captures.get`, `ingest.frame`,
  `routing.dispatch_capture`
- dependency callback: `storage_write.completed`
- runtime callback: `runtime_dispatch.completed`
- CLI: `senses` for manifest, health, and reference discovery
- MCP: `senses_operations_manifest`, `senses_reference_manifest`
- hooks: `install`, `migrate`, `health_check`

The MVP auth mode is `user_session_mvp`. Mounted backend calls use the Maverick
user session supplied by `/api/apps/senses/backend`; Senses does not accept a raw
device token in Phase 4. Pairing, registry, settings, ingestion, and routing
operations are backend/view-only because standard CLI/MCP app contexts do not
carry a Maverick user session.

## Data

Workspace data is owned by the app under:

```text
workspaces/<workspace_id>/data/senses/
```

The SQLite file is:

```text
workspaces/<workspace_id>/data/senses/senses.sqlite
```

Phase 4 creates these workspace-scoped tables:

- `schema_migrations`
- `settings`
- `devices`
- `pairing_sessions`
- `device_sessions`
- `ingestion_requests`
- `captures`
- `routing_sessions`
- `runtime_dispatch_attempts`
- `audit`

## Pairing

`pairing.start` creates a short code with a bounded TTL and returns a
machine-readable QR payload. `pairing.complete` requires a Maverick user session
and associates the completing iOS device with that user and workspace. When
member pairing is disabled, completion is limited to workspace admins or the
user who created the code. The server stores only registry/session metadata;
device-token ingress is deferred.

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

Idempotent retries return the existing capture. If that capture is still
`storage_pending` after the Storage write lease has expired, Senses reissues the
same Storage dependency request for the existing `capture_id` and path with
Storage `mode=upsert` and `confirm=true`. This lets a client retry recover when
Storage already wrote the file but the callback to Senses was lost; the callback
still has to match the persisted path, sha256 and size before the capture becomes
`stored`.

Storage writes use:

```text
storage/generated/senses/<device_id>/<yyyy-mm-dd>/<capture_id>.<jpg|png>
```

The `storage_write.completed` dependency callback updates the capture to
`stored` with Storage file id, workspace-relative path, sha256 and size. It does
not return runtime launch requests.

## Routing To Chat

`routing.dispatch_capture` requires a stored capture owned by the authenticated
user, or a workspace-admin session. It records a `runtime_dispatch_attempt`,
chooses the routing target from `routing_sessions`, and returns one
`runtime_launch_request` with the capture attached by Storage workspace-relative
path. When the request omits `agent_id` or `agent_type_id`, Senses targets the
`chat` agent type. Senses does not call Chat directly; the Maverick core owns
runtime session and thread creation.

MVP routing rules are:

- explicit `routing_hint=new_thread` or `force_new_thread=true` creates a new
  thread;
- close follow-up within `routing_followup_window_seconds` reuses the active
  thread;
- long task prompts or `routing_hint=task` use the active task thread, creating
  one when needed;
- otherwise short questions use the primary user/device thread.

Primary and active-task thread creation is serialized per routing session while
the matching attempt is pending, so two stored captures from the same user/device
cannot race to create separate shared threads before the first runtime callback
completes.

The `runtime_dispatch.completed` callback stores `runtime_session_id`, `turn_id`,
and the Chat thread mapping. For newly created sessions, Senses records
`thread_id = runtime_session_id`, matching the current core runtime thread
creation behavior. Runtime callbacks are accepted only for pending attempts;
duplicate or tardy callbacks for terminal attempts return the persisted terminal
state without rewriting the capture. `captures.get` returns the persisted capture
and Chat deep link after the callback has completed.

Live audio capture and bidirectional voice routing remain deferred. Senses must
not open raw device-token audio ingress, STT/TTS WebSockets, or remote speech
provider sessions until the core provider registry, router, audit trail, and
Core Secrets delivery path can supply an explicit governed decision for each
audio stream. Future audio dispatch should reference that decision rather than
choosing Deepgram, Cartesia, Kokoro-hosted, or any local engine inside Senses.

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

Runtime readiness is true only when the manifest reports
`available == true`, `dependency_resolution.status == "resolved"`, and the
contract runtime permission `create_sessions` is active.

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
creation and catalog metadata, runtime session creation for dispatch, and data
events for devices, pairing, settings, captures, and routing. The operations
manifest reports separate booleans for user-session `ingest.frame` support and
raw device auth support. Device-token
ingress and capture reference entities remain deferred beyond Phase 4.
