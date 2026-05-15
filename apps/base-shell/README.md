# Base Shell

Maverick product shell app that hosts enabled app frontends through the platform registry.

## Contract Notes

- The shell frontend is app-owned, but shell composition, app hosting, and workspace navigation remain core/platform concerns.
- `base-shell` declares `presentation.frontend_role: supporting`; the platform can mount it as the root shell, but it is not a normal workspace app target for App Store opening or shortcut pinning.
- Browser-facing workspace navigation uses `/app/<app_id>/<app_page>` routes owned by the shell. Internal app iframe assets still mount under `/apps/<app_id>/`.
- The empty shell route and empty `/app/chat` route open Chat on a transient new-chat screen with the sidebar closed; deep links such as `/app/chat/threads/<thread_id>` remain explicit navigation.
- Mounted app and widget iframes allow the browser `fullscreen` feature so user-triggered app preview surfaces can request native fullscreen while retaining their in-frame fallback behavior.
- On desktop, the app rail renders the App Store app as a static trailing shortcut and lets users reorder only pinned workspace apps. A long press starts pointer reordering, `Alt+ArrowUp` and `Alt+ArrowDown` provide keyboard reordering, and the resulting ordered app id list is saved through the App Store app-owned `pinned_apps.set` backend action.
- The Settings rail shortcut opens the app-owned `settings` frontend when that app is visible in the active workspace; `base-shell` does not render settings UI itself.
- Mobile layout uses a shell-owned header above mounted app iframes and reserves the header height so app content starts below it. The active app icon opens the sidebar, the centered logo opens a new Chat launch, and the right-side plus invokes the active app's `shell.sidebar.footer` primary action through the generic widget message protocol. Mobile entry starts with the sidebar closed even when a desktop session had it open or fixed.
- During app switches, `base-shell` keeps the previously visible app frame on screen while the requested target frame mounts hidden. The target frame is revealed after `maverick.app.ready`, or after a short post-load fallback for apps that do not yet emit readiness, so users see the target app's first rendered loading state instead of the browser's blank iframe canvas.
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
