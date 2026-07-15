# Maverick App SDK Backend Guide

Date: 2026-04-21

App backend entrypoints are JSON stdin/stdout scripts executed by the core.

SDK-generated backends should use:

```python
from core.app_sdk.runtime import backend_response, emit_json, read_entrypoint_payload
```

Use `payload.body` for request data and `payload.data_root` for app-owned workspace data.

Keep entrypoints thin:

- parse payload
- dispatch by action
- call `service.py`
- return `{"status_code": <int>, "json": <object>}`

Keep persistence in `store.py` or `database.py`.

## Binary Streaming Responses

Mounted backend entrypoints receive a bounded `headers` object in their payload for browser context that may affect generated URLs or range handling. The core includes only safe request metadata such as `content-type`, `range`, `origin`, `host`, and forwarded host/proto fields; cookies, authorization headers, and arbitrary request headers are not passed through.

Most backend entrypoints should keep returning one JSON object on stdout. Mounted `GET` or `HEAD` media routes and explicit progressive `POST` operations may opt in to binary streaming when the core payload includes:

```json
{"stream_response_protocol": "maverick.backend.stream.v1"}
```

In that mode the entrypoint emits one UTF-8 JSON header line followed by optional binary stdout bytes:

```json
{"status_code": 200, "stream_response": {"content_type": "video/mp4", "content_length": 123}}
```

After the newline, remaining stdout is streamed to the HTTP client. Use this only for backend-approved response bytes; keep secrets in entrypoint input and never put local host paths or bearer tokens in the stream header.

The core forwards each available stdout pipe chunk immediately, adds `X-Accel-Buffering: no`, and closes the request entrypoint when the HTTP client disconnects. Entrypoints should flush after the header and after latency-sensitive chunks, stop upstream work when their stdout consumer closes, and must not rely on the platform accumulating a requested chunk size before delivery.

Mounted backend callers may request a bounded subset of the app's declared secrets with `_app_secret_request`. JSON operations put that object in the request body. Binary-body operations and other calls that cannot add JSON fields may send its compact JSON encoding in the `_app_secret_request` query parameter. The core validates both forms against the app contract and active grants before it delivers any secret; callers should mark alternative provider credentials optional when only one configured route is required.

Mounted `GET` or `HEAD` media routes may also return an app-approved local file through `file_response`. The core validates the path against the app's allowed roots and serves it with range support. `file_response.headers` is optional and supports only a small safe allowlist for browser loading requirements, currently `Access-Control-Allow-Origin`, `Cross-Origin-Resource-Policy`, and `Timing-Allow-Origin`; arbitrary headers, cookies, and content overrides are ignored by the core.

Apps that need repeated browser loads for the same approved file can avoid launching their backend for every asset request by writing a manifest under their data root at `run/file-gateway/<token>.json` and linking to `/api/apps/<app_id>/backend/file/<token>`. The manifest schema is `maverick.app.file_gateway.v1` and contains the same `file_response` object plus optional `app_id`, `expires_at`, `access`, and `allowed_paths` fields. By default the core validates the user's authenticated session, membership, app visibility, manifest app ownership, expiry, allowed roots, ETag, and range semantics before serving the file directly.

For opaque sandbox iframes or other browser contexts that cannot send useful cookies, apps may opt in to bearer capability mode with `"access": "public_capability"`. Public capability manifests must use unguessable random tokens, set a short `expires_at`, and include exact absolute file paths in `allowed_paths`; the core rejects expired capabilities, capabilities longer than 24 hours, missing exact-path scopes, path scopes outside the app's allowed roots, and responses whose `file_response.path` is not explicitly listed. Public capability URLs must be treated as temporary read-only asset grants and should only be emitted for already-approved preview/build artifacts.

## Surface Mapping

Backend, CLI, and MCP should share the same service logic whenever possible.

Recommended pattern:

- backend translates mounted HTTP requests into app actions
- CLI translates command invocations into the same app actions
- MCP translates tool invocations into the same app actions
- mutating actions emit `app_events` such as `maverick.app.data-changed` when mounted UI should refresh live

If the app declares:

- `reference_entities`, implement manifest, search, resolve, and summarize behavior through CLI or MCP
- `view_surfaces`, implement real view-state actions such as `view_filter`, `set_view_filter`, `set_custom_view`, and `clear_custom_view`

Do not declare these surfaces unless the behavior exists in the app service layer.
