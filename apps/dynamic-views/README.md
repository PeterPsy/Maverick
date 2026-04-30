# Dynamic Views

Persisted custom visual views rendered in chat and reopened from a workspace library.

## Contract Notes

- Frontend, backend, CLI, and MCP entrypoints are declared in `app_contract.json`.
- The contract now declares the bundled `dynamic-views` skill and the `dynamic-view` chat widget surface.
- The app exposes `view` as its current reference entity and stores view state under `data/dynamic-views/`.
- Persisted `view_surfaces` cover library filters and curated dynamic-view selections; the dynamic-view widget remains the embedded chat surface.

## SDK Flow

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-id dynamic-views --workspace default --json
./scripts/maverick core cli run core.app-sdk.register-local --app-id dynamic-views --workspace default --json
./scripts/maverick core cli run core.app-sdk.install-local --app-id dynamic-views --workspace default --json
./scripts/maverick core cli run core.app-sdk.status --app-id dynamic-views --workspace default --json
./scripts/maverick core cli run core.app-sdk.package --app-id dynamic-views --workspace default --json
```
