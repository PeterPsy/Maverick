# User Admin

Admin-only control panel for users, platform roles, workspace assignments, app visibility, and core persistence adapter operations.

## Contract Notes

- The app currently declares frontend, CLI, and MCP entrypoints only.
- `user-admin` intentionally does not declare an app-owned backend or lifecycle hooks yet; authoritative admin state remains core-owned.
- Persistence adapter status, dry-runs, migrations, and backend restarts are core-owned admin surfaces. User Admin only presents those surfaces in the UI.
- The app stores only admin UI preferences under `data/user-admin/preferences.json`.
- `reference_entities`, `data_events`, and persisted `view_surfaces` remain intentionally empty until the app grows app-owned administrative state instead of acting as a shell over core-managed records.

## SDK Flow

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-id user-admin --workspace default --json
./scripts/maverick core cli run core.app-sdk.register-local --app-id user-admin --workspace default --json
./scripts/maverick core cli run core.app-sdk.install-local --app-id user-admin --workspace default --json
./scripts/maverick core cli run core.app-sdk.status --app-id user-admin --workspace default --json
./scripts/maverick core cli run core.app-sdk.package --app-id user-admin --workspace default --json
```
