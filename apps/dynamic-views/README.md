# Dynamic Views

Persisted custom visual views rendered in chat and reopened from a workspace library.

## Contract Notes

- Frontend, backend, CLI, and MCP entrypoints are declared in `app_contract.json`.
- The contract now declares the bundled `dynamic-views` skill, the `dynamic-views-sidebar` base-shell widget, and the `dynamic-view` chat widget surface.
- The app exposes `view` as its current reference entity and stores view state under `data/dynamic-views/`.
- Persisted `view_surfaces` cover library filters and curated dynamic-view selections; the dynamic-view widget remains the embedded chat surface.
- The main Dynamic Views iframe no longer renders the saved-views column. Saved view search and selection live in the base-shell sidebar iframe for `shell.sidebar.primary`, while the main iframe listens for `maverick.app.navigate` with `view_id`, `instance_id`, or `app_page: "views/<id>"` and emits `maverick.app.selection-changed` to keep the sidebar active row synchronized.

## SDK Flow

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-id dynamic-views --workspace default --json
./scripts/maverick core cli run core.app-sdk.register-local --app-id dynamic-views --workspace default --json
./scripts/maverick core cli run core.app-sdk.install-local --app-id dynamic-views --workspace default --json
./scripts/maverick core cli run core.app-sdk.status --app-id dynamic-views --workspace default --json
./scripts/maverick core cli run core.app-sdk.package --app-id dynamic-views --workspace default --json
```
