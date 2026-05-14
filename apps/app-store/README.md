# App Store

Authenticated Maverick app catalog for inspecting remote catalog apps, server-registered app sources, and workspace installation state.

## Contract Notes

- Frontend, backend, CLI, and MCP entrypoints are declared in `app_contract.json`.
- The contract declares the bundled `app-store-ops` skill and the `app-shortcuts` base-shell widget.
- The `app-shortcuts` widget is a dark sidebar app selector exposed for both the shell app selector slot and the App Store primary sidebar, with search, all/pinned scopes, pin controls, and registry logo image or glyph fallback rendering.
- App-owned `pinned_apps` state is an ordered list. `pinned_apps.set` preserves the normalized order it receives, and the Base Shell uses that order for the desktop app rail while keeping App Store itself outside the movable pinned list.
- `installed_app` is the current reference entity exposed through app-owned surfaces.
- The app now declares persisted `view_surfaces` for catalog query/scope filters and curated installed-app selections.
- The frontend uses the public Maverick App Store browsing experience as the primary page and keeps Maverick management controls on the same page.
- The primary catalog view groups apps into animated type folders; opening a folder app launches a carousel with app description, install/open controls, pinning, and workspace assignment options.
- The management area includes Server Apps backed by `/api/app-store/server-apps`; it lists installation-level app sources even when they are not installed in the active workspace.
- Server app rows can install or uninstall selected workspace bindings through `/api/app-store/install-server` and `/api/app-store/uninstall`; this binds the workspace to the registered server source without copying source into the workspace.
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
