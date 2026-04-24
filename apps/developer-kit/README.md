# Developer Kit

Official Maverick app SDK developer UI for creating, validating, and managing workspace-local apps.

## Contract Notes

- `developer-kit` is intentionally frontend-centric.
- The UI calls the core-owned `/api/app-sdk` surface documented by the SDK architecture instead of declaring app-owned backend, CLI, MCP, or lifecycle hooks.
- The app keeps only lightweight UI state under `data/developer-kit/state.json`.
- Because the control plane is core-owned, the contract intentionally leaves `reference_entities`, `data_events`, and persisted `view_surfaces` empty for now.

## SDK Flow

```bash
./scripts/maverick app validate developer-kit --workspace default
./scripts/maverick app register-local developer-kit --workspace default
./scripts/maverick app install-local developer-kit --workspace default
./scripts/maverick app status developer-kit --workspace default
./scripts/maverick app package developer-kit --workspace default
```
