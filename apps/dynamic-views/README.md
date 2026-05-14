# Dynamic Views

Persisted custom visual views rendered in chat and reopened from a workspace library.

## Contract Notes

- Frontend, backend, CLI, and MCP entrypoints are declared in `app_contract.json`.
- The contract now declares the bundled `dynamic-views` skill, the `dynamic-views-sidebar` base-shell widget, and the `dynamic-view` chat widget surface.
- The app exposes `view` as its current reference entity and stores view state under `data/dynamic-views/`.
- Persisted `view_surfaces` cover library filters and curated dynamic-view selections; the dynamic-view widget remains the embedded chat surface.
- The workspace frontend is a viewer for persisted dynamic view instances created through app-owned backend, CLI, MCP, or agent skill surfaces. It does not expose manual HTML/CSS/JavaScript authoring controls.
- Saved view search and selection live in the base-shell sidebar iframe for `shell.sidebar.primary`; curated `view_filter.refs` selections are respected until the user types in the searchbar, and typed sidebar search switches back to normal library search across view titles, metadata, tags, and sources.
- The main viewer listens for `maverick.app.navigate` with `view_id`, `instance_id`, or `app_page: "views/<id>"`, emits `maverick.app.selection-changed`, and opens view metadata from the viewer header details icon on desktop or from the header pill row on mobile rather than a persistent side inspector. The rendered dynamic view grows to its measured content height so overflow belongs to the page, not to the sandbox iframe. On mobile, the page header remains visible while the rendered dynamic view uses the full lateral width.

## SDK Flow

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-id dynamic-views --workspace default --json
./scripts/maverick core cli run core.app-sdk.register-local --app-id dynamic-views --workspace default --json
./scripts/maverick core cli run core.app-sdk.install-local --app-id dynamic-views --workspace default --json
./scripts/maverick core cli run core.app-sdk.status --app-id dynamic-views --workspace default --json
./scripts/maverick core cli run core.app-sdk.package --app-id dynamic-views --workspace default --json
```
