# App Store

Authenticated Maverick app catalog for inspecting remote catalog apps, server-registered app sources, and workspace installation state.

The default-off M5 adapter may reuse only the authorized public catalog through the Base Shell parent broker. `/api/app-store/apps` exposes a stable SHA-256/strong ETag after authentication and evaluates `If-None-Match` only after that check. Installations, workspace membership, pinned apps, publication state, and all actions remain fresh server state; cached rows stay read-only until those authority inputs load. See `docs/runbooks/pwa_data_cache_m5.md`.

## Contract Notes

- Frontend, backend, CLI, and MCP entrypoints are declared in `app_contract.json`.
- The contract declares the bundled `app-store-ops` skill and the `app-shortcuts` base-shell widget.
- The `app-shortcuts` widget is a dark sidebar app selector exposed for both the shell app selector slot and the App Store primary sidebar, with search, all/pinned scopes, pin controls, and registry logo image or glyph fallback rendering.
- Catalog, carousel, and shortcut surfaces distinguish `workspace`, `supporting`, and `none` frontend roles from app contract presentation metadata. Supporting frontends are shown as platform extensions with inverted glyph colors and cannot be opened or pinned as workspace apps.
- App-owned `pinned_apps` state is an ordered list. Pin mutations require
  workspace registry context, accept only launchable workspace frontends for
  new pins, and still allow stale entries to be removed. The POST `pinned_apps.list`
  action repairs the list against the launchable registry. The authenticated
  `pinned_apps.read` action on the same backend returns the stored
  ordered IDs without repairing, seeding business state, or emitting change events.
  This separate non-mutating read is safe for Base Shell's SDK-managed request
  recovery; the shell still filters every icon through the current authorized
  launchable registry. Its SDK-issued executor accepts no custom parameters,
  URLs, actions, or callbacks; it cannot be used to retry a pin mutation.
  `pinned_apps.set` preserves
  normalized order after filtering; Base Shell uses it for the desktop rail.
  Base Shell also supplies a stable idempotency key and exact SHA-256 request
  fingerprint. App Store atomically records a bounded deduplication result,
  returns the original response on replay, and suppresses duplicate data-change
  events without reverting later state.
- If a pinned shortcut no longer matches any catalog, server, local, or installed app, the App Store page exposes it in a cleanup section so the user can remove the orphaned shortcut through the same app-owned pin API.
- `installed_app` is the current reference entity exposed through app-owned surfaces.
- The app now declares persisted `view_surfaces` for catalog query/scope filters and curated installed-app selections.
- The frontend uses the animated type-folder catalog as the App Store page; the page keeps only the header and folders visible.
- Opening a folder app launches a carousel with app description, install/open controls, pinning, workspace assignment, server-source, workspace-local, promotion, deletion, and publication actions where applicable.
- Server app entries are included in the folder catalog from `/api/app-store/server-apps`, even when they are not installed in the active workspace.
- Server app carousel actions can install or uninstall selected workspace bindings through `/api/app-store/install-server` and `/api/app-store/uninstall`; this binds the workspace to the registered server source without copying source into the workspace.
- Public App Store publication is intentionally cross-repo: this app packages workspace-local app source into a ZIP, submits it with safe metadata, and reads submission status from the external public store service. The reviewer/admin approval panel lives in the external public store service, not in Maverick.
- Public identity is `public_store.public_app_uuid` in the app contract metadata. The App Store client generates and saves it before the first public submission when absent, then reuses it for updates; users do not type or edit this UUID.
- Public publication can be submitted as `sealed` or `forkable`. Sealed packages rewrite the submitted contract distribution to `sealed`/`none` and omit common editable frontend source files; forkable packages rewrite it to `source_available`/`forkable` and include source suitable for customization.
- The workspace-local promotion action is labeled "Promote to server app" to keep it distinct from public publication requests.

## SDK Flow

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-id app-store --workspace default --json
./scripts/maverick core cli run core.app-sdk.register-local --app-id app-store --workspace default --json
./scripts/maverick core cli run core.app-sdk.install-local --app-id app-store --workspace default --json
./scripts/maverick core cli run core.app-sdk.status --app-id app-store --workspace default --json
./scripts/maverick core cli run core.app-sdk.package --app-id app-store --workspace default --json
```
