# Base Shell

Maverick product shell app that hosts enabled app frontends through the platform registry.

## Contract Notes

- The shell frontend is app-owned, but shell composition, app hosting, and workspace navigation remain core/platform concerns.
- `base-shell` declares `presentation.frontend_role: supporting`; the platform can mount it as the root shell, but it is not a normal workspace app target for App Store opening or shortcut pinning.
- Browser-facing workspace navigation uses `/app/<app_id>/<app_page>` routes owned by the shell. Internal app iframe assets still mount under `/apps/<app_id>/`.
- The empty shell route and empty `/app/chat` route open Chat on a transient new-chat screen with the sidebar closed; deep links such as `/app/chat/threads/<thread_id>` remain explicit navigation.
- Mounted app iframes allow browser `fullscreen` and `microphone` features so user-triggered app surfaces such as Chat dictation can request native browser permission prompts. Chat-owned widget iframes also allow `microphone` for composer dictation; other widget iframes allow `fullscreen` for preview surfaces while retaining their in-frame fallback behavior.
- On desktop, the app rail renders the App Store app as a static trailing shortcut and lets users reorder only pinned workspace apps. A long press starts pointer reordering, `Alt+ArrowUp` and `Alt+ArrowDown` provide keyboard reordering, and the resulting ordered app id list is saved through the App Store app-owned `pinned_apps.set` backend action.
- The Settings rail shortcut opens the app-owned `settings` frontend when that app is visible in the active workspace; `base-shell` does not render settings UI itself.
- Mobile layout uses a shell-owned header above mounted app iframes and reserves the header height so app content starts below it. The active app icon opens the sidebar, the centered logo opens a new Chat launch, the right-side plus invokes the active app's `shell.sidebar.footer` primary action through the generic widget message protocol, and the adjacent Chat app icon opens Chat's `shell.overlay.mobile.fullscreen` widget as a contextual panel below the persistent shell header. While the panel is open, that header action becomes a close control; it is hidden when the active app is Chat because the contextual floating chat is disabled there. Mobile entry starts with the sidebar closed even when a desktop session had it open or fixed, and the bottom-right floating overlay launcher is not mounted on mobile.
- Desktop layout mounts Chat's fixed right dock through the generic `shell.dock.right` widget slot. Chat requests it with `maverick.widget.dock.open`; the shell persists the chat dock mode, selected thread/navigation scope, and dock width, then shrinks the workspace frame while the dock is fixed.
- The shell persists a `dark`, `light`, or `system` theme preference in browser session state. Its HTML entry applies the saved effective theme before the frontend bundle runs. Runtime code then applies `data-maverick-theme` and `data-theme` to the root document, bootstraps mounted app and widget iframe URLs with `maverick_theme`, `maverick_theme_mode`, and `maverick_color_scheme`, and sends live `{ type: "maverick.shell.theme-changed", theme }` messages so iframe surfaces can update without remounting.
- During app switches, `base-shell` keeps the previously visible app frame on screen while the requested target frame mounts hidden. The target frame is revealed after `maverick.app.ready`, or after a short post-load fallback for apps that do not yet emit readiness, so users see the target app's first rendered loading state instead of the browser's blank iframe canvas.
- Primary and footer sidebar widget frames follow the same visited-app lifecycle: switching apps hides the inactive widget iframe without unmounting it, and returning reveals its preserved DOM and in-memory state. Context and theme changes continue through `postMessage`; workspace/authenticated-session generation changes or app-scoped frontend/runtime refresh events remount the affected widget.
- `base-shell` intentionally does not declare an app-owned backend, lifecycle hooks, reference entities, or persisted `view_surfaces`.
- CLI and MCP entrypoints are limited to shell-facing reference and operator support behavior.
- The app stores shell preferences under `data/base-shell/preferences.json`.
- M4 keeps Storage file bytes parent-mediated. The shell binds a private broker to the authenticated user, active workspace, and fixed `storage` scope; it accepts stable identity only from the mounted Storage frame over a transferred `MessagePort`, re-resolves the server-owned cache descriptor, and never exposes OPFS or IndexedDB handles to the frame. The default-off feature, unclassified-resource denial, and opaque/isolated-frame release gate are documented in `docs/runbooks/pwa_file_cache_m4.md`.
- M5 structured read models remain parent-mediated and default-off. Every app and widget iframe registration binds exact source/origin to its real owner, workspace, and opaque authenticated shell-session generation. Workspace/session transitions synchronously drop old-generation frames; late requests are unavailable before cache lookup. App/widget fan-out requires the sender's registered owner to match `owner_app_id`, while exact top-level shell messages may intentionally cross owners. See `docs/runbooks/pwa_data_cache_m5.md`.

## SDK Flow

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-id base-shell --workspace default --json
./scripts/maverick core cli run core.app-sdk.register-local --app-id base-shell --workspace default --json
./scripts/maverick core cli run core.app-sdk.install-local --app-id base-shell --workspace default --json
./scripts/maverick core cli run core.app-sdk.status --app-id base-shell --workspace default --json
./scripts/maverick core cli run core.app-sdk.package --app-id base-shell --workspace default --json
```
