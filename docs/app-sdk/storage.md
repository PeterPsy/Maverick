# Maverick App SDK Storage Guide

Date: 2026-04-21

App data belongs under:

```text
workspaces/<workspace_id>/data/<app_id>/
```

Use SDK helpers for simple JSON state:

```python
from core.app_sdk.storage import read_json_state, write_json_state, ensure_json_state
```

Use `entity-sqlite` when an app needs relational records, referenceable entities, and CRM-like workflows.

Never store app business data in core stores.
