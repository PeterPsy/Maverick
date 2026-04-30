# Storage and packaging

## App data root

App data belongs under:

```text
data/<app_id>/
```

For JSON state, generated apps can use:

```python
from core.app_sdk.storage import read_json_state, write_json_state, ensure_json_state
```

## Packaging

```bash
maverick core cli run core.app-sdk.package --app-id <app_id> --json
```

Packaging validates the app contract and writes `<app_id>.tar.gz` plus `<app_id>.tar.gz.manifest.json` under `storage/generated/`. The agent CLI uses `app_id` and workspace context only; it does not accept host-local package output paths.

## Exclusions

Packages should exclude local junk:

- `node_modules`
- `__pycache__`
- runtime state
- logs
- temp files
- local databases when not intended as source
