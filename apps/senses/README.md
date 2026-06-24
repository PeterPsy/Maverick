# Senses

Senses is a root Maverick app for device and sensor inputs. Phase 7 keeps the
Phase 4 backend contract for user-session pairing, the workspace-scoped device
registry, authenticated frame ingestion through Storage-backed capture records,
and explicit routing from stored captures into Maverick Chat runtime threads
without adding a public bearer-token ingress. It keeps the existing workspace UI
as the primary device surface and adds Chat mapping visibility, Chat status
filters, and clearer visual-origin thread titles for the Senses MVP.

## Phase 7 Surfaces

- frontend: `frontend/dist`
- backend: `manifest`, `health`, `overview`, `pairing.start`,
  `pairing.complete`, `pairing.status`, `devices.list`, `devices.revoke`,
  `settings.get`, `settings.update`, `captures.get`, `ingest.frame`,
  `routing.dispatch_capture`, `routing.reset`
- dependency callback: `storage_write.completed`
- runtime callback: `runtime_dispatch.completed`
- CLI: `senses` for manifest, health, and reference discovery
- MCP: `senses_operations_manifest`, `senses_reference_manifest`,
  `senses_view_filter`, `senses_set_view_filter`,
  `senses_set_custom_view`, `senses_clear_custom_view`
- hooks: `install`, `migrate`, `health_check`

The MVP auth mode is `user_session_mvp`. Mounted backend calls use the Maverick
user session supplied by `/api/apps/senses/backend`; Senses does not accept a raw
device token in Phase 7. Pairing, registry, settings, ingestion, and routing
operations are backend/view-only because standard CLI/MCP app contexts do not
carry a Maverick user session.

The standard view-state tools read and write a workspace-shared UI state file.
`view_filter` requires an authenticated Maverick actor. `set_view_filter`,
`set_custom_view`, and `clear_custom_view` additionally require workspace-admin
or platform-admin authority, including when invoked through MCP.

## Data

Workspace data is owned by the app under:

```text
workspaces/<workspace_id>/data/senses/
```

The SQLite file is:

```text
workspaces/<workspace_id>/data/senses/senses.sqlite
```

The current schema creates these workspace-scoped tables:

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
and a Chat deep link after the callback has completed only when the optional
`chat-communication` dependency resolves a `communication.chat` provider.

Phase 7 keeps Chat/Core ownership unchanged and does not add core thread
metadata. Runtime requests created by Senses still produce runtime threads with
`source_app_id=senses` through the generic app-hosting runtime request path.
Senses stores the device/thread mapping in `routing_sessions`, exposes pending,
unavailable, or linked Chat state in capture and dispatch payloads, and titles
Meta glasses visual threads as `Occhiali - domanda visiva` or the matching task
variant. The frontend Captures and Routing tabs publish shell selection events
for stored captures, Chat-linked captures, Chat-pending captures, mapped routing
sessions, pending mapping sessions, and task threads. When the actor has
workspace-admin or platform-admin authority, the frontend also persists those
filters through the standard Senses `set_view_filter` backend action; non-admin
sessions keep the filters local to the shell event stream.

Live audio capture and bidirectional voice routing remain deferred. Senses must
not open raw device-token audio ingress, STT/TTS WebSockets, or remote speech
provider sessions until the core provider registry, router, audit trail, and
Core Secrets delivery path can supply an explicit governed decision for each
audio stream. Future audio dispatch should reference that decision rather than
choosing Deepgram, Cartesia, Kokoro-hosted, or any local engine inside Senses.

## Frontend And iOS Host Bridge

The Senses frontend is the primary visual surface for Maverick status, iOS host
status, glasses connection, capture state, local Senses queue, last frame/error,
pairing, captures, routing, settings, and diagnostics. When the app is opened
inside Maverick iOS, the WebView exposes a minimal `sensesHost` message handler
only while the main WebView is on the same-origin `/app/senses` route. The
handler accepts controlled commands:

- `refreshNativeStatus`
- `pairGlasses`
- `ask`
- `openLogin`

The native app pushes sanitized status into the page with the
`maverick.senses.native-status` browser event. No cookies, bearer tokens, raw
DAT handles, or Meta DAT logic are exposed to the frontend. When Senses runs in
a normal browser or PWA without the iOS host, backend-owned device, pairing,
capture, routing, and settings views still work, while physical glasses actions
show as unavailable.

Maverick iOS remains responsible for Meta DAT SDK configuration, iOS
permissions, Meta glasses pairing, physical snapshot capture, local retry queue,
user-session HTTPS submission to Senses, and opening Maverick login when the
session expires. Senses remains responsible for the registry, pairing sessions,
capture records, Storage write requests, routing state, settings, audit, and the
user-facing diagnostic UI.

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
maverick core cli run app.senses.dependencies.set \
  --arguments-json '{"alias":"chat-communication","provider_app_ids":["chat"]}' \
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
creation and catalog metadata, optional `chat-communication` for verified Chat
deep links, runtime session creation for dispatch, and data events for devices,
pairing, settings, captures, routing, and frontend view-state. The operations
manifest reports separate booleans for user-session `ingest.frame` support and
raw device auth support. Device-token ingress and capture reference entities
remain deferred beyond Phase 7.
