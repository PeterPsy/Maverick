# App Store

Authenticated Maverick app catalog for inspecting remote catalog apps, server-registered app sources, and workspace installation state.

## Contract Notes

- Frontend, backend, CLI, and MCP entrypoints are declared in `app_contract.json`.
- The contract declares the bundled `app-store-ops` skill and the `app-shortcuts` base-shell widget.
- `installed_app` is the current reference entity exposed through app-owned surfaces.
- The app now declares persisted `view_surfaces` for catalog query/scope filters and curated installed-app selections.
- The frontend includes a Server Apps tab backed by `/api/app-store/server-apps`; it lists installation-level app sources even when they are not installed in the active workspace.

## SDK Flow

```bash
./scripts/maverick app validate app-store --workspace default
./scripts/maverick app register-local app-store --workspace default
./scripts/maverick app install-local app-store --workspace default
./scripts/maverick app status app-store --workspace default
./scripts/maverick app package app-store --workspace default
```
