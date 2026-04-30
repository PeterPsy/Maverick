# References and view state

Referenceable entities let one app point to another app's records without reading its private data files.

## Reference tool convention

| Tool | Purpose |
| --- | --- |
| `<app_id>_reference_manifest` | list entity types |
| `<app_id>_reference_search` | find entities by query |
| `<app_id>_reference_resolve` | resolve a stable id |
| `<app_id>_reference_summarize` | return safe context |

## View surface actions

Apps with persistent browse or board state should expose:

- `view_filter`
- `set_view_filter`
- `set_custom_view`
- `clear_custom_view`

## Example

Docs Studio declares `doc_page` as a reference entity. Another app can store:

```json
{
  "app_id": "docs-studio",
  "entity_type": "doc_page",
  "entity_id": "surface-model"
}
```

It should not open `data/docs-studio/state.json` directly.
