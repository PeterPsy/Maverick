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
