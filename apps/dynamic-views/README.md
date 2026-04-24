# Dynamic Views

Persisted custom visual views rendered in chat and reopened from a workspace library.

## Contract Notes

- Frontend, backend, CLI, and MCP entrypoints are declared in `app_contract.json`.
- The contract now declares the bundled `dynamic-views` skill and the `dynamic-view` chat widget surface.
- The app exposes `view` as its current reference entity and stores view state under `data/dynamic-views/`.
- Persisted `view_surfaces` cover library filters and curated dynamic-view selections; the dynamic-view widget remains the embedded chat surface.

## SDK Flow

```bash
./scripts/maverick app validate dynamic-views --workspace default
./scripts/maverick app register-local dynamic-views --workspace default
./scripts/maverick app install-local dynamic-views --workspace default
./scripts/maverick app status dynamic-views --workspace default
./scripts/maverick app package dynamic-views --workspace default
```
