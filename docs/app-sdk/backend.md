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

Most backend entrypoints should keep returning one JSON object on stdout. Mounted `GET` or `HEAD` media routes may opt in to binary streaming when the core payload includes:

```json
{"stream_response_protocol": "maverick.backend.stream.v1"}
```

In that mode the entrypoint emits one UTF-8 JSON header line followed by optional binary stdout bytes:

```json
{"status_code": 200, "stream_response": {"content_type": "video/mp4", "content_length": 123}}
```

After the newline, remaining stdout is streamed to the HTTP client. Use this only for backend-approved response bytes; keep secrets in entrypoint input and never put local host paths or bearer tokens in the stream header.

Mounted `GET` or `HEAD` media routes may also return an app-approved local file through `file_response`. The core validates the path against the app's allowed roots and serves it with range support. `file_response.headers` is optional and supports only a small safe allowlist for browser loading requirements, currently `Access-Control-Allow-Origin`, `Cross-Origin-Resource-Policy`, and `Timing-Allow-Origin`; arbitrary headers, cookies, and content overrides are ignored by the core.

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
