# Settings

Admin-only platform settings app for provider/runtime settings, users, workspace roles, workspace assignments, app visibility, and core persistence adapter operations.

## Contract Notes

- The app currently declares frontend, CLI, MCP, and base-shell sidebar widget surfaces.
- `settings` intentionally does not declare an app-owned backend or lifecycle hooks yet; authoritative admin state remains core-owned.
- Persistence adapter status, platform settings, provider/model selection, runtime-session cleanup, and backend restarts are core-owned admin surfaces. Settings presents those surfaces in the UI.
- The platform settings panel shows Codex runtime model selection separately from hosted text model selection. Codex remains the agentic provider for tools, filesystem, MCP, and skills; hosted text providers such as OpenRouter govern only `plain_hosted_chat` and `fast_model`.
- Persistence migration UI must call the core dry-run endpoint before apply. The confirmation dialog exposes target JSON/Mongo connection fields, including Mongo username and password secret ref, and source cleanup is an explicit operator opt-in rather than the default migration behavior.
- The main app iframe owns the settings work surface and renders one page at a time: platform settings, users, workspace access, workspace apps, app links, or persistence.
- The app links page presents generic core app dependency selections for the active workspace, including intra-app provider catalogs such as `agent.catalog`. It calls `/api/apps/dependencies` and does not read another app's private storage.
- The `settings-sidebar` iframe declared for `shell.sidebar.primary` is a page navigator, matching the page-list pattern used by Docs Studio. Selected-user controls live inside the relevant Settings pages.
- The platform settings panel is rendered inside the main app work surface rather than as a shell modal or app-local overlay. It calls generic core settings/provider/runtime APIs and keeps the shell boundary app-agnostic.
- The app stores only admin UI preferences under `data/settings/preferences.json`.
- `reference_entities`, `data_events`, and persisted `view_surfaces` remain intentionally empty until the app grows app-owned administrative state instead of acting as a shell over core-managed records.

## SDK Flow

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-id settings --app-root apps/settings --workspace default --json
./scripts/maverick app settings frontend build --operator --json
python3 -m unittest discover -s apps/settings/tests -p 'test_*.py'
```

`settings` is an installation-level sealed app under `apps/settings`; it is not a workspace-local app project. Do not use `core.app-sdk.register-local` or `core.app-sdk.install-local` for this app unless it is intentionally copied into a workspace-local development project.
