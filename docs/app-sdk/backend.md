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

## Surface Mapping

Backend, CLI, and MCP should share the same service logic whenever possible.

Recommended pattern:

- backend translates mounted HTTP requests into app actions
- CLI translates command invocations into the same app actions
- MCP translates tool invocations into the same app actions

If the app declares:

- `reference_entities`, implement manifest, search, resolve, and summarize behavior through CLI or MCP
- `view_surfaces`, implement real view-state actions such as `view_filter`, `set_view_filter`, `set_custom_view`, and `clear_custom_view`

Do not declare these surfaces unless the behavior exists in the app service layer.
