# Chat

Workspace chat app that talks to the selected Maverick runtime provider.

## Contract Notes

- Frontend, backend, CLI, and MCP entrypoints are declared in `app_contract.json`.
- Chat's CLI and MCP inspect metadata lives in `cli/command_schemas.json` and `mcp/tool_schemas.json`; the no-argument CLI call and the `chat_operations_manifest` MCP tool return the compact `operations.manifest`.
- The contract declares the bundled `chat-ops` skill plus the `chat-sidebar`, `chat-sidebar-footer`, `chat-floating`, and Fleet-hosted `chat-runtime-text` widgets.
- Runtime threads, message sends, and turn interrupts are core-owned runtime operations. Chat does not expose placeholder MCP tools for those operations; the Chat app persists projects and view-filter UI state under `data/chat/state.json`.
- Chat references are project-owned; thread list, mutation, deletion, and runtime cleanup go through core runtime APIs.
- New runtime-thread titles are derived by the core from the first accepted user message as a compact contextual topic title of up to five words only while the thread still has the default placeholder title. The generator favors the concrete topic over opening filler or setup phrases. Chat no longer persists titles by trimming the first message text in the frontend, and non-placeholder titles, including user-renamed titles, are preserved.
- Draft chats remain frontend-only until the first send. On the first send, Chat creates the runtime session and queues the first turn in one runtime request before navigating to the thread route or doing extra catalog refresh work; title derivation follows from the queued message and must not block message persistence.
- Chat declares optional `agent-catalog`, `agent-prompt-materializer`, and `text-to-speech` dependencies on the `agent.catalog`, `agent.prompt-materializer`, and `speech.synthesis` interfaces. The shared composer uses a provider only when the same app satisfies both agent dependencies, then shows the agent selector for draft chats and materializes the selected agent prompt through that provider before creating the first runtime session. Existing runtime sessions keep their original agent metadata and cannot switch runner from the composer.
- The composer `@` picker uses the core app-reference API, so enabled reference providers such as Checklist and Storage can contribute app-owned records, files, and folders without Chat reading their storage directly. When Chat runs with an active shell app context, the picker requests that app's references first, then generic file and folder references, then the generic cross-app results; the picker keeps enough reference rows to show multiple entity types from a provider, such as Storage files and folders.
- The floating and full composer also accepts Storage's frontend drag payloads for files, folders, and multi-item selections. Dropped Storage items are inserted as normal `@` entity references, using the same `[ref:<app_id>/<entity_type>/<entity_id>]` markers and runtime `app_references` payload as picker-created citations.
- Project deletion is destructive: the Chat backend requests core cleanup for every runtime thread with the project id, then commits the app-owned project removal only after cleanup succeeds.
- Chat full app and widgets render initial and live thread catalogs from `WS /ws/runtime/threads`, ordered by each thread's latest accepted user message; transcripts render initial and live runtime events from `WS /ws/runtime/sessions/<session_id>`. Thread busyness is core runtime state derived from queued, active, terminal, and interrupted turn lifecycle events. Completed-response unread state is also core-owned: the runtime thread payload exposes `has_unread_completed_response`, and Chat marks a thread read through `POST /api/runtime/threads/<thread_id>/read` only when the user explicitly selects, opens, or clicks into that chat from the sidebar, floating-chat controls, or full chat surface.
- Chat full app thread selection publishes shell deep links as `/app/chat/threads/<thread_id>`; scoped widgets keep their own local selection state and do not rewrite the browser URL.
- Agent Markdown links that point at workspace Storage files under `storage/generated/` or `storage/uploaded/`, including absolute workspace filesystem paths, are normalized to workspace-relative Storage paths. Chat routes clicks through the shell to Storage, forwards embedded widget open-app requests back to the shell, and synthesizes the same `workspace.file.preview` widget for completed streamed output as for final output text.
- Agent response footers expose a speaker control beside the copy action only when Chat resolves an enabled `speech.synthesis` provider and that provider reports synthesis availability. Chat sends the same collapsed Markdown content visible in the transcript after lightweight Markdown-to-text normalization to the selected provider backend, then plays the returned bounded audio payload while keeping only one agent response active at a time.
- Structured widget iframes allow the browser `fullscreen` feature so embedded app previews such as Storage file previews can enter native fullscreen from a user action.
- `chat-floating` persists its open window list as browser UI state under `maverick.chat.floating-widget.state.v1:<workspace_id>`. It hydrates that workspace-scoped state before rendering or writing updates, migrates the older global fallback key only when the workspace key is empty, and never silently replaces a saved missing `threadId` with the first available thread.
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
