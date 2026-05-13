# Chat

Workspace chat app that talks to the selected Maverick runtime provider.

## Contract Notes

- Frontend, backend, CLI, and MCP entrypoints are declared in `app_contract.json`.
- The contract declares the bundled `chat-ops` skill plus the `chat-sidebar`, `chat-sidebar-footer`, `chat-floating`, and Fleet-hosted `chat-runtime-text` widgets.
- Runtime threads are core-owned. The Chat app persists projects and view-filter UI state under `data/chat/state.json`.
- Chat references are project-owned; thread list, mutation, deletion, and runtime cleanup go through core runtime APIs.
- Project deletion is destructive: the Chat backend requests core cleanup for every runtime thread with the project id, then commits the app-owned project removal only after cleanup succeeds.
- Chat full app and widgets render initial and live thread catalogs from `WS /ws/runtime/threads`, ordered by each thread's latest accepted user message; transcripts render initial and live runtime events from `WS /ws/runtime/sessions/<session_id>`. Thread busyness is core runtime state derived from queued, active, terminal, and interrupted turn lifecycle events. Completed-response unread state is also core-owned: the runtime thread payload exposes `has_unread_completed_response`, and the sidebar marks a thread read through `POST /api/runtime/threads/<thread_id>/read` only when the user explicitly selects that chat from the sidebar.
- Chat full app thread selection publishes shell deep links as `/app/chat/threads/<thread_id>`; scoped widgets keep their own local selection state and do not rewrite the browser URL.
- `chat-sidebar` owns only the shell sidebar's central chat/project list; `chat-sidebar-footer` owns the fixed shell footer action for starting a new chat.
- HTTP runtime event and thread reads are not used as frontend bootstrap or realtime fallbacks.
- The Fleet runtime text widget is read-only and renders compact transcript text for one `runtime_session_id`; it uses the same runtime-session websocket path as the full Chat app and does not create sessions or submit turns.
- Persisted `view_surfaces` cover runtime-thread/project browse filters and curated transcript selections; the widgets remain first-class embedded shell surfaces.

## SDK Flow

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-id chat --workspace default --json
./scripts/maverick core cli run core.app-sdk.register-local --app-id chat --workspace default --json
./scripts/maverick core cli run core.app-sdk.install-local --app-id chat --workspace default --json
./scripts/maverick core cli run core.app-sdk.status --app-id chat --workspace default --json
./scripts/maverick core cli run core.app-sdk.package --app-id chat --workspace default --json
```
