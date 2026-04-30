# Surfaces and storage

## Surface checklist

| Surface | Contract entry | Verification |
| --- | --- | --- |
| Frontend | `entrypoints.frontend` | `maverick app <id> frontend build --json` |
| Backend | `entrypoints.backend` | mounted backend smoke action |
| CLI | `entrypoints.cli` | scoped CLI list and inspect |
| MCP | `entrypoints.mcp` | scoped MCP list and inspect |
| Skills | `entrypoints.skills_root` | template ids match directories |
| Hooks | `entrypoints.hooks` | install, migrate, health smoke |

## Storage declaration

Apps declare storage kind and primary paths, but app developers choose the internal schema.

```json
"storage": {
  "storage_kind": "json",
  "primary_paths": ["data/docs-studio/state.json"]
}
```


## Reference entities

Apps can expose referenceable entities so other apps can link without reading private storage. The common MCP convention is:

- `<app_id>_reference_manifest`
- `<app_id>_reference_search`
- `<app_id>_reference_resolve`
- `<app_id>_reference_summarize`

## View state

Apps with persisted view surfaces should expose state actions such as:

- `view_filter`
- `set_view_filter`
- `set_custom_view`
- `clear_custom_view`
