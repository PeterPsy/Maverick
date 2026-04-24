# Gallery

Workspace file gallery for uploaded files and generated artifacts.

## Contract Notes

- Frontend, backend, CLI, and MCP entrypoints are declared in `app_contract.json`.
- The contract now declares the bundled `gallery-ops` skill, persisted gallery view-state actions, and the `file-preview` chat widget.
- `file` is the primary reference entity and app-owned state lives under `data/gallery/state.json`.
- Gallery is one of the repository reference apps for file-centric references and embedded widget surfaces.

## SDK Flow

```bash
./scripts/maverick app validate gallery --workspace default
./scripts/maverick app register-local gallery --workspace default
./scripts/maverick app install-local gallery --workspace default
./scripts/maverick app status gallery --workspace default
./scripts/maverick app package gallery --workspace default
```
