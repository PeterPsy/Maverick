# Chat

Workspace chat app that talks to the selected Maverick runtime provider.

## Contract Notes

- Frontend, backend, CLI, and MCP entrypoints are declared in `app_contract.json`.
- The contract declares the bundled `chat-ops` skill plus the `chat-sidebar` and `chat-floating` widgets.
- Reference entities are `thread` and `project`; data events cover thread and project mutations.
- Persisted `view_surfaces` cover thread/project browse filters and curated transcript selections; the widgets remain first-class embedded shell surfaces.

## SDK Flow

```bash
./scripts/maverick app validate chat --workspace default
./scripts/maverick app register-local chat --workspace default
./scripts/maverick app install-local chat --workspace default
./scripts/maverick app status chat --workspace default
./scripts/maverick app package chat --workspace default
```
