# Senses

Senses is a root Maverick app for future device and sensor inputs. Phase 0 only
creates the app skeleton, data root, SQLite schema, and availability surfaces.

It intentionally does not implement pairing, `ingest.frame`,
`routing.dispatch_capture`, device-token ingress, or frontend/reference views.

## Phase 0 Surfaces

- backend: `manifest`, `health`
- CLI: `senses`
- MCP: `senses_operations_manifest`, `senses_reference_manifest`
- hooks: `install`, `migrate`, `health_check`

The contract requires Storage interfaces:

- `storage-file-content-write` -> `file.content.write`
- `storage-file-catalog` -> `file.catalog`

## Data

Workspace data is owned by the app under:

```text
workspaces/default/data/senses/
```

The Phase 0 SQLite file is:

```text
workspaces/default/data/senses/senses.sqlite
```

The initial schema creates `schema_migrations` and `settings`, both scoped by
`workspace_id`.

## Verify

```bash
maverick sdk templates
maverick sdk docs
maverick core cli run core.app-sdk.validate --app-root apps/senses --json
maverick apps list --json
maverick app senses cli list --json
maverick app senses cli inspect senses --json
maverick app senses cli run senses --action health --json
maverick app senses mcp list --json
maverick app senses mcp inspect senses_operations_manifest --json
maverick app senses mcp call senses_operations_manifest --json
python3 -m unittest discover -s apps/senses/tests -p 'test_*.py'
```

Configure the required Storage providers after the app is installed through the
generic app-hosting dependency service. In the current CLI runtime the generated
`app.senses.dependencies` commands are discoverable from the core list but are
not invokable from either the core runner or the app-scoped runner unless the
command is explicitly present in the Senses contract, so Phase 0 uses the
generic service directly instead of declaring extra CLI commands.

```python
from pathlib import Path
from core.api.platform_state import bootstrap_platform_state
from core.apps.service import resolve_app_dependencies, save_app_dependency_selection

root = Path.cwd()
state = bootstrap_platform_state(
    start_path=root,
    install_builtin_apps=False,
    register_builtin_provider_definitions=False,
    bootstrap_admin=False,
)
for alias in ("storage-file-content-write", "storage-file-catalog"):
    save_app_dependency_selection(
        state.app_store,
        workspace_id="default",
        consumer_app_id="senses",
        alias=alias,
        provider_app_ids=["storage"],
        workspace_store=state.workspace_store,
        start_path=root,
    )
print(resolve_app_dependencies(
    state.app_store,
    workspace_id="default",
    consumer_app_id="senses",
    workspace_store=state.workspace_store,
    start_path=root,
))
```
