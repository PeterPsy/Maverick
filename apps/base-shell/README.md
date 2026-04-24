# Base Shell

Maverick v3 product shell app that hosts enabled app frontends through the platform registry.

## Contract Notes

- The shell frontend is app-owned, but shell composition, app hosting, and workspace navigation remain core/platform concerns.
- Browser-facing workspace navigation uses `/app/<app_id>/<app_page>` routes owned by the shell. Internal app iframe assets still mount under `/apps/<app_id>/`.
- `base-shell` intentionally does not declare an app-owned backend, lifecycle hooks, reference entities, or persisted `view_surfaces`.
- CLI and MCP entrypoints are limited to shell-facing reference and operator support behavior.
- The app stores shell preferences under `data/base-shell/preferences.json`.

## SDK Flow

```bash
./scripts/maverick app validate base-shell --workspace default
./scripts/maverick app register-local base-shell --workspace default
./scripts/maverick app install-local base-shell --workspace default
./scripts/maverick app status base-shell --workspace default
./scripts/maverick app package base-shell --workspace default
```
