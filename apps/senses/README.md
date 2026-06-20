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
maverick app senses mcp list --json
maverick app senses mcp inspect senses_operations_manifest --json
maverick app senses mcp call senses_operations_manifest --json
python3 -m unittest discover -s apps/senses/tests -p 'test_*.py'
```

After Senses and Storage are installed and enabled in the workspace, configure
the required Storage providers from an authorized workspace-admin context
through the core-owned app dependency commands:

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

The health payload is only ready when `ok` is `true` and
`dependencies.status` is `resolved`. If the host does not provide dependency
resolution, or either required Storage provider is unset, Senses reports
`ok: false` with `status: "dependency_resolution_pending"`.
