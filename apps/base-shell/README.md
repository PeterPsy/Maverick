# Base Shell

Maverick product shell app that hosts enabled app frontends through the platform registry.

## Contract Notes

- The shell frontend is app-owned, but shell composition, app hosting, and workspace navigation remain core/platform concerns.
- Browser-facing workspace navigation uses `/app/<app_id>/<app_page>` routes owned by the shell. Internal app iframe assets still mount under `/apps/<app_id>/`.
- The empty shell route and empty `/app/chat` route open Chat on a transient new-chat screen with the sidebar closed; deep links such as `/app/chat/threads/<thread_id>` remain explicit navigation.
- Mobile layout uses a shell-owned header above mounted app iframes and reserves the header height so app content starts below it. The active app icon opens the sidebar, the centered logo opens a new Chat launch, and the right-side plus invokes the active app's `shell.sidebar.footer` primary action through the generic widget message protocol. Mobile entry starts with the sidebar closed even when a desktop session had it open or fixed.
- `base-shell` intentionally does not declare an app-owned backend, lifecycle hooks, reference entities, or persisted `view_surfaces`.
- CLI and MCP entrypoints are limited to shell-facing reference and operator support behavior.
- The app stores shell preferences under `data/base-shell/preferences.json`.

## SDK Flow

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-id base-shell --workspace default --json
./scripts/maverick core cli run core.app-sdk.register-local --app-id base-shell --workspace default --json
./scripts/maverick core cli run core.app-sdk.install-local --app-id base-shell --workspace default --json
./scripts/maverick core cli run core.app-sdk.status --app-id base-shell --workspace default --json
./scripts/maverick core cli run core.app-sdk.package --app-id base-shell --workspace default --json
```
