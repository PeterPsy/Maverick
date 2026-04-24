# User Admin

Admin-only control panel for users, platform roles, and workspace assignments.

## Contract Notes

- The app currently declares frontend, CLI, and MCP entrypoints only.
- `user-admin` intentionally does not declare an app-owned backend or lifecycle hooks yet; authoritative admin state remains core-owned.
- The app stores only admin UI preferences under `data/user-admin/preferences.json`.
- `reference_entities`, `data_events`, and persisted `view_surfaces` remain intentionally empty until the app grows app-owned administrative state instead of acting as a shell over core-managed records.

## SDK Flow

```bash
./scripts/maverick app validate user-admin --workspace default
./scripts/maverick app register-local user-admin --workspace default
./scripts/maverick app install-local user-admin --workspace default
./scripts/maverick app status user-admin --workspace default
./scripts/maverick app package user-admin --workspace default
```
