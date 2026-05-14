# Developer Kit

Official Maverick app SDK developer UI for creating, validating, and managing workspace-local apps.

## Contract Notes

- `developer-kit` is a supporting SDK surface, not a primary workspace app view; its contract uses `presentation.frontend_role: supporting`.
- The UI calls the core-owned `/api/app-sdk` surface documented by the SDK architecture instead of declaring app-owned backend, CLI, MCP, or lifecycle hooks.
- The app keeps only lightweight UI state under `data/developer-kit/state.json`.
- Because the control plane is core-owned, the contract intentionally leaves `reference_entities`, `data_events`, and persisted `view_surfaces` empty for now.

## SDK Flow

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-id developer-kit --workspace default --json
./scripts/maverick core cli run core.app-sdk.register-local --app-id developer-kit --workspace default --json
./scripts/maverick core cli run core.app-sdk.install-local --app-id developer-kit --workspace default --json
./scripts/maverick core cli run core.app-sdk.status --app-id developer-kit --workspace default --json
./scripts/maverick core cli run core.app-sdk.package --app-id developer-kit --workspace default --json
```
