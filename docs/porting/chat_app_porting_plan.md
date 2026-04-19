# Chat App Porting Plan

This document defines the complete porting plan for the Maverick v2 `chat_app` into Maverick v3.

The goal is not to copy the v2 backend shape. The goal is to keep the chat as a standalone v3 app while exposing the generic core runtime surfaces that any future chat-like or agent-facing app can use.

## Source And Target

Source app:

- `/home/ubuntu/maverick-v2/apps/chat_app`

Target app:

- `/home/ubuntu/maverick-v3/apps/chat`

Current v3 state:

- `apps/chat` already exists as a smoke app.
- It proves frontend/backend/CLI/MCP/skills/hooks/storage mounting, but it is not the real product chat.
- The real v2 chat is coupled to legacy FastAPI routes, WebSocket runtime updates, Mongo user/workspace lookup, `session_manager`, attachment app services, prompt preview routes, schedules, and chat widget discovery.

Porting principle:

- Chat owns chat UX, composer, transcript rendering, thread metadata, UI drafts, message normalization, app-local storage, app MCP/CLI/skills, and app health.
- Chat owns chat projects, thread lists, new-chat actions, chat navigation, and chat-specific AI usage/status indicators.
- Core owns users, workspaces, app hosting, runtime providers, runtime sessions, runtime turns, runtime events/updates, process lifecycle, sandbox/full-access policy, secrets, recovery, and runtime orchestration.
- Base shell owns only visual app hosting, workspace selection, login/session UI, generic settings, and app registry navigation.
- Other apps own their own domain integrations. Attachments, dynamic views, checklists, memory, and skills must not be folded into chat.

## Non-Negotiable Boundaries

- Do not move chat code into core.
- Do not make core depend on `apps/chat`.
- Do not reintroduce v2 `session_manager` as an app-private dependency.
- Do not expose v2 routes such as `/api/agent-instances/...` as the final v3 contract.
- Do not let chat import source files from other apps.
- Do not let chat discover other apps with compile-time glob imports.
- Do not implement inter-agent communication as part of this port unless the core runtime surface is already available and intentionally enabled.
- Do not move chat project state, chat thread lists, or "new chat" controls into `base-shell`.
- Do not make `base-shell` inspect chat internals to show project/thread navigation.

## Boundary With Core And Base-Shell

The intended architecture is:

- `core/` is standalone and app-agnostic.
- `apps/base-shell` is standalone and app-owned.
- `apps/chat` is standalone and app-owned.
- Core exposes generic endpoints and mounted app routes.
- Apps attach to those endpoints through their own contracts.

There must be no direct contamination between `core` and `base-shell`:

- core must not import React, base-shell source files, shell components, or shell-specific state
- core may expose generic APIs such as session, workspace, provider, runtime, settings, recovery, app registry, and app backend dispatch
- base-shell may call generic core APIs, but it must not own runtime execution, provider configuration, chat project data, or chat thread data
- base-shell may mount chat as an app iframe, but it must not know chat storage, chat route internals, or chat UI state
- chat may call generic core runtime APIs, but it must not reach into provider adapters or workspace policy internals

This boundary is the reason several v2 base-shell features are deliberately delegated to `apps/chat`.

## Features Delegated From Base-Shell To Chat

The following v2 shell behaviors are not core features and should not live in `base-shell`.

They are part of the chat app port.

### Projects

Projects are chat-domain organization state.

They belong in `apps/chat`, not in core and not in `apps/base-shell`.

The chat app should own:

- project list
- project create/rename/archive/delete
- project ordering and selection
- mapping threads to projects
- "no project" grouping
- project-level local UI state

Recommended storage:

```json
{
  "projects": [
    {
      "project_id": "project_id",
      "name": "Project name",
      "archived": false,
      "created_at": "iso",
      "updated_at": "iso",
      "metadata": {}
    }
  ],
  "thread_project_links": [
    {
      "thread_id": "thread_id",
      "project_id": "project_id"
    }
  ]
}
```

### Chat List And New Chat

The left-side chat list and `New chat` action should be implemented by the chat app.

Base-shell should only show installed apps and workspace/session controls.

The chat app should own:

- thread list
- active thread selection
- new chat button
- empty thread creation
- thread rename/archive/delete
- recent thread ordering
- per-thread unread/running/error indicators if useful

These controls should appear inside the mounted chat app UI, not in base-shell's global sidebar.

### AI Usage And Codex Indicators

Provider/runtime indicators shown inside chat should be chat-contextual.

Base-shell may show a generic active provider badge, but chat should show the operational AI status relevant to the active thread.

For the first v3 chat port, Codex is the default provider.

The chat app should show:

- active provider label, initially `Codex`
- runtime session status for the active thread
- active turn status: queued, running, streaming, completed, failed, interrupted
- tool-call activity if events expose it
- execution mode: sandbox or full-access
- last activity timestamp
- token/usage metrics only after the provider/runtime layer exposes a generic usage event or metric

Chat must derive these from generic core runtime/provider APIs and runtime events, not from Codex-specific process internals.

If a required usage field is missing from core, add it to the generic runtime/provider tasklist rather than hardcoding it in chat.

### Chat Settings

Chat-specific settings belong in `apps/chat`.

Examples:

- default thread behavior
- composer preferences
- transcript density
- project display preferences
- per-thread runtime binding preferences, if allowed

Base-shell settings should remain platform-level: user/session, active workspace, provider status, runtime status, recovery summary, and generic governance metadata.

## Target App Structure

Recommended target layout:

```text
apps/chat/
  app_contract.json
  package.json
  package-lock.json
  tsconfig.json
  vite.config.ts
  backend/
    app_backend.py
    schemas.py
    storage.py
    threads.py
  cli/
    app_cli.py
  frontend/
    index.html
    src/
      main.tsx
      App.tsx
      api/
        appBackend.ts
        coreRuntime.ts
        schemas.ts
      components/
        AiUsageIndicator.tsx
        ChatBubble.tsx
        ChatComposer.tsx
        ChatHeader.tsx
        ChatSidebar.tsx
        ChatTranscript.tsx
        EmptyState.tsx
        PendingTurn.tsx
        ProjectList.tsx
        ThreadList.tsx
        StructuredMessage.tsx
      hooks/
        useChatActions.ts
        useChatProjects.ts
        useChatRuntime.ts
        useChatSession.ts
        useChatViewport.ts
        useComposerDrafts.ts
      lib/
        chatAttachments.ts
        chatPerformance.ts
        chatRuntimeView.ts
        chatSession.ts
        chatStream.ts
        chatToolCallStatus.ts
        chatTranscriptEntries.ts
        chatTypes.ts
      styles/
        main.css
        tokens.css
        chat/
          layout.css
          transcript.css
          tool-calls.css
          pending-diff.css
          prompt-preview.css
      tests/
        chat-performance.test.ts
        chat-session.test.ts
        chat-stream.test.ts
        chat-transcript.test.ts
  hooks/
    install.py
    health_check.py
    migrate.py
  mcp/
    server.py
  skills/
    chat-ops/
      SKILL.md
```

The app should build like `apps/base-shell`: React + Vite, with the mounted frontend pointing to `frontend/dist`.

## App Contract Target

`apps/chat/app_contract.json` should become a real contract, not a smoke contract.

Required contract decisions:

- `app_id`: `chat`
- `contract_version`: `1.0`
- `distribution.mode`: `sealed` for the built-in app initially.
- `distribution.source_access`: `none` for the built-in app initially.
- `entrypoints.frontend`: `frontend/dist`
- `entrypoints.backend`: `backend/app_backend.py`
- `entrypoints.mcp`: `mcp/server.py`
- `entrypoints.cli`: `cli/app_cli.py`
- `entrypoints.skills_root`: `skills`
- `entrypoints.hooks.install`: `hooks/install.py`
- `entrypoints.hooks.health_check`: `hooks/health_check.py`
- `entrypoints.hooks.migrate`: `hooks/migrate.py` once schema migration exists.

Recommended capabilities:

- View: `chat`
- MCP tools: `threads.list`, `threads.get`, `message.send`, `turn.stop`
- CLI command: `chat`
- Skill: `chat-ops`

Recommended storage:

```json
{
  "storage_kind": "json",
  "data_schema_version": "1",
  "primary_paths": [
    "data/chat/threads.json",
    "data/chat/preferences.json"
  ],
  "indices": null,
  "supports_export": true,
  "supports_import": true,
  "supports_migrations": true
}
```

If message volume becomes high, replace `threads.json` with:

```text
data/chat/threads/<thread_id>.json
data/chat/messages/<thread_id>.jsonl
```

Do not use `data/memory`, `data/agents`, or other app-owned folders.

## V2 File Classification

Port and adapt:

- `frontend/chat-workspace-entry.tsx`
- `frontend/chat-workspace.tsx`
- `frontend/chat-transcript.tsx`
- `frontend/chat-bubble.tsx`
- `frontend/chat-composer.tsx`
- `frontend/chat-header.tsx`
- `frontend/structured-message.tsx`
- `frontend/periodic-task-panel.tsx`, only if runtime schedules are already exposed by core.
- `frontend/prompt-preview-dialog.tsx`, only after prompt preview has a v3 core/app surface.
- `frontend/primitives.tsx`
- `frontend/styles/**`
- `chat/*.tsx`, if still useful as compatibility re-exports or after deduplication.
- `hooks/use-chat-actions.ts`
- `hooks/use-agent-runtime.ts`, but rewrite API and socket assumptions.
- `hooks/use-chat-instance-mutations.ts`, but rewrite around v3 runtime/session APIs.
- `hooks/use-chat-viewport.ts`
- `hooks/use-chat-workspace-state.ts`
- `hooks/use-composer-attachments.ts`, only after the attachment app has a v3 surface.
- `hooks/use-mobile-layout.ts`
- `lib/chat-session.ts`
- `lib/chat-stream.ts`
- `lib/chat-runtime-view.ts`
- `lib/chat-tool-call-status.ts`
- `lib/chat-tools.ts`
- `lib/chat-transcript-entries.ts`
- `lib/chat-types.ts`
- `lib/chat-performance.ts`
- `lib/workspace-session.ts`
- `tests/chat-performance.test.ts`
- `tests/chat-session.test.ts`
- `tests/chat-sync.test.ts`
- `tests/chat-transcript.test.ts`
- `tests/pending-turn.test.ts`

Rewrite instead of porting directly:

- `backend/routes.py`
- `backend/mount.py`
- `lib/api.ts`
- `lib/api-core.ts`

Partially port as pure logic:

- `backend/input_support.py`
- `lib/chat-attachments.ts`

Do not port in phase 1:

- `frontend/widget-surface-registry.tsx`
- `tests/widget-registry.test.tsx`

Reason: the v2 registry uses compile-time cross-app imports such as `../../*/chat/*widget.tsx`. In v3, apps do not import other apps. Widget rendering must be redesigned through a generic app registry/runtime surface, not through chat-owned source imports.

## Required Core Work

The chat port depends on generic core work. This work must be implemented in core without referencing the chat app.

### 1. Runtime HTTP API

Core must expose stable HTTP endpoints for runtime sessions, turns, and events.

Recommended endpoints:

```text
GET    /api/runtime/sessions
POST   /api/runtime/sessions
GET    /api/runtime/sessions/{session_id}
PATCH  /api/runtime/sessions/{session_id}
DELETE /api/runtime/sessions/{session_id}

GET    /api/runtime/sessions/{session_id}/turns
POST   /api/runtime/sessions/{session_id}/turns
GET    /api/runtime/turns/{turn_id}
POST   /api/runtime/turns/{turn_id}/interrupt

GET    /api/runtime/sessions/{session_id}/events
GET    /api/runtime/turns/{turn_id}/events
```

Minimum response contracts:

- Session includes `session_id`, `workspace_id`, `provider_id`, `runtime_backend`, `status`, `execution_mode`, `created_at`, `updated_at`, and optional `metadata`.
- Turn includes `turn_id`, `session_id`, `workspace_id`, `status`, `input_text`, timestamps, and failure reason.
- Event includes `event_id`, `session_id`, `turn_id`, `event_type`, `plane`, `payload`, and `created_at`.

The current `core/runtime/routes.py` is only a placeholder. It must become a real API layer using the runtime service/store already present in v3.

### 2. Runtime Realtime Updates

Core must expose a realtime update channel owned by runtime, not chat.

Recommended options:

- SSE first: `GET /api/runtime/sessions/{session_id}/events/stream`
- WebSocket later: `/ws/runtime/sessions/{session_id}`

For the first working online version, SSE is enough if it streams ordered runtime events and reconnects cleanly from `last_event_id`.

Required event types:

- `runtime.session.started`
- `runtime.session.updated`
- `runtime.turn.queued`
- `runtime.turn.started`
- `runtime.output.delta`
- `runtime.tool_call.started`
- `runtime.tool_call.updated`
- `runtime.tool_call.completed`
- `runtime.turn.completed`
- `runtime.turn.failed`
- `runtime.turn.cancelled`
- `runtime.error`

Chat should render these events. It should not own the transport.

### 3. Runtime Message Submission

Core must provide a generic way to submit user input to a runtime session.

Required request:

```json
{
  "input_text": "message",
  "client_message_id": "optional-client-id",
  "attachments": [],
  "metadata": {}
}
```

Required behavior:

- Validate workspace/session ownership.
- Create or reuse a runtime session.
- Queue a runtime turn.
- Start execution according to provider/runtime routing.
- Persist turn and event records.
- Return `session_id`, `turn_id`, and initial status.

The app should never call provider-specific code directly.

### 4. Runtime History Projection

Core must expose runtime history as event/turn records. Chat may transform these records into chat transcript items.

Core should not store chat transcript bubbles as its canonical model.

Core canonical model:

- Sessions
- Turns
- Events
- Processes
- Runtime state

Chat derived model:

- UI transcript entries
- Local scroll/session state
- Composer drafts
- Thread display metadata

### 5. Interrupt/Stop API

Core must expose turn interruption.

Recommended endpoint:

```text
POST /api/runtime/turns/{turn_id}/interrupt
```

Required behavior:

- Mark the turn as cancelling/cancelled.
- Signal the runtime process if active.
- Emit an ordered event.
- Return the updated turn.

This replaces v2 `session_manager.interrupt_current_turn`.

### 6. Runtime Provider Selection

Core must expose provider/runtime routing enough for chat to show what runtime is active.

Chat needs read-only fields:

- `provider_id`
- `runtime_backend`
- `model_label` if available
- `execution_mode`
- `workspace_mode`

Chat should not own provider configuration or API keys.

### 7. Prompt Preview Surface

The v2 chat can preview and edit composed agent prompts. In v3, this belongs to the Agents app plus core runtime composition.

Core/app work required before porting this feature:

- Define who owns base prompt and role-specific prompt.
- Expose a generic read endpoint for resolved runtime prompt preview.
- Expose mutation only through the owning app, probably Agents, not Chat.

Until this exists, port the dialog component but feature-gate it off.

### 8. Schedule Surface

The v2 chat includes periodic task controls. In v3, scheduling is core/runtime or an app-owned automation feature, not chat-owned.

Core work required before enabling:

- Runtime session scheduling model.
- Schedule CRUD API.
- Trigger-now API.
- Pause/resume API.
- Schedule event records.

Until this exists, port the UI only if hidden behind feature flags.

### 9. Attachments Surface

The v2 chat uploads files through `/api/files` and resolves runtime attachment blocks through legacy app services.

In v3 this must not be a hidden chat dependency.

Required design:

- Either core exposes generic workspace file storage.
- Or an Attachments app exposes an official app backend/MCP/CLI surface.
- Chat calls only the official surface.

Do not port `get_app_service("file_store...")`.

### 10. App Backend Routing

Current v3 `platform_host` supports `POST /api/apps/{app_id}/backend` with an action-style payload.

For chat, two options are valid:

- Keep one backend endpoint and use action envelopes such as `{ "action": "threads.list" }`.
- Add generic app backend subpath dispatch in core, for example `/api/apps/{app_id}/backend/{path:path}`.

Recommendation:

- Use action envelopes for the first port to avoid expanding core hosting too early.
- Add subpath dispatch only if multiple apps need REST-like backend routes.

### 11. Frontend App Mounting

Base shell currently hosts app frontends in an iframe using `frontend_mount`.

Chat must therefore:

- Build to `frontend/dist`.
- Use relative API paths.
- Avoid assuming it is mounted at root.
- Avoid importing base-shell internals.
- Receive workspace/session context through URL params, bootstrap endpoint, or platform status API.

If chat needs richer shell-to-app communication later, define a generic postMessage contract. Do not special-case chat in base-shell.

## Chat Widget Runtime Model

The v2 chat supports structured message widgets through `frontend/widget-surface-registry.tsx`.

That v2 mechanism works by:

- reading enabled app records
- finding `ui_surfaces` with `kind: "chat_widget"`
- matching the structured message `content.kind` against `content_kinds`
- dynamically loading widget source with `import.meta.glob("../../*/chat/*widget.tsx")`
- rendering the widget component inside the chat transcript
- falling back to a generic structured message card when no widget exists

This behavior is useful, but the v2 implementation must not be copied as-is.

The problem is the compile-time cross-app import.

In v3, chat is a standalone app. It must not know the source tree of `checklists`, `dynamic_views`, `attachments`, `editorial_memory`, or any other app.

The v3 model must be registry-driven and mounted by the core.

### Desired v3 flow

1. A runtime event or chat message contains structured content:

```json
{
  "kind": "checklist.design",
  "payload": {}
}
```

2. The chat app sees `structuredContent.kind`.

3. The chat app asks the workspace app registry for enabled widgets compatible with:

```json
{
  "host": "chat",
  "content_kind": "checklist.design"
}
```

4. The core registry returns widget metadata only for apps enabled in the current workspace.

5. Chat embeds the widget through a core-mounted frontend surface.

6. The widget receives only explicit host context: workspace id, message id, content payload, owner app id, and widget id.

7. Widget actions go to the widget owner's own backend, MCP, or CLI surface.

8. If no widget is available, chat renders a generic structured content card.

### Widget ownership rule

The embedding app owns the container.

The widget owner owns the renderer and widget state.

The core owns registry, mounting, auth, workspace context, and enablement checks.

For example:

- `chat` owns the transcript row and structured message fallback
- `checklists` owns the checklist widget renderer and checklist persistence
- `dynamic_views` owns dynamic view rendering and saved dynamic view state
- `attachments` owns attachment preview widgets and attachment data
- core owns whether those app surfaces are installed and enabled

Chat must not write into `data/checklists`, `data/dynamic_views`, or `data/attachments`.

Those apps must not write into `data/chat`.

### Contract shape

The app that owns the widget should declare it in its own `app_contract.json`.

Example:

```json
{
  "app_id": "checklists",
  "widgets": [
    {
      "widget_id": "design-checklist",
      "host": "chat",
      "content_kinds": ["checklist.design"],
      "frontend": {
        "kind": "iframe",
        "mount": "frontend/dist/widgets/design-checklist"
      },
      "actions": {
        "backend": true,
        "mcp": false,
        "cli": false
      }
    }
  ]
}
```

The chat app contract should not list widgets owned by other apps.

The chat app may declare that it supports widget hosting for structured messages, but ownership of concrete widgets remains with each producing app.

### Required core work for widgets

Core app hosting must eventually expose widget registry data.

Recommended endpoint:

```text
GET /api/apps/widgets?host=chat&content_kind=checklist.design
```

Recommended response:

```json
{
  "items": [
    {
      "owner_app_id": "checklists",
      "widget_id": "design-checklist",
      "host": "chat",
      "content_kinds": ["checklist.design"],
      "frontend_mount": "/api/apps/checklists/widgets/design-checklist",
      "actions": {
        "backend": true,
        "mcp": false,
        "cli": false
      }
    }
  ]
}
```

Core must filter this response by:

- current workspace
- app installation state
- app enablement state
- user/session access
- app contract validity

Core must not load or execute widget source inside chat.

### Widget embedding options

Initial recommended option:

- iframe-mounted widget frontend

Why:

- preserves app isolation
- avoids bundling other app code into chat
- works with sealed apps
- works with workspace-local apps after they are built/mounted
- keeps framework choice app-owned

Possible later option:

- signed module federation or remote component loading

Do not start there. It is more complex and weakens the isolation model unless carefully governed.

### Chat porting implication

For the first chat port:

- port `StructuredMessage`
- keep generic fallback rendering
- remove compile-time `import.meta.glob("../../*/chat/*widget.tsx")`
- do not port `widget-surface-registry.tsx` as-is
- add a small registry client abstraction, but keep it disabled until core widget registry exists
- add tests for fallback rendering
- later add tests for registry-driven widget discovery

## Chat App Backend Responsibilities

The chat backend should be small and app-owned.

Allowed responsibilities:

- Thread metadata.
- Chat preferences.
- Optional server-side composer drafts.
- Mapping a chat thread to a core runtime session.
- Import/export/migration of app-owned chat data.
- App health checks.

Not allowed:

- Provider execution.
- Runtime process lifecycle.
- Workspace policy.
- User auth.
- Other app data access.
- Direct attachment storage unless attachments are explicitly part of the chat app contract.

Recommended backend actions:

```text
projects.list
projects.create
projects.rename
projects.archive
projects.delete
threads.list
threads.get
threads.create
threads.rename
threads.archive
threads.delete
threads.move_to_project
threads.bind_runtime_session
preferences.get
preferences.update
health.check
```

Recommended storage model:

```json
{
  "schema_version": "1",
  "threads": [
    {
      "thread_id": "chat_thread_id",
      "workspace_id": "workspace_id",
      "project_id": null,
      "runtime_session_id": "core_runtime_session_id",
      "title": "Thread title",
      "created_at": "iso",
      "updated_at": "iso",
      "archived": false,
      "metadata": {}
    }
  ],
  "projects": [],
  "preferences": {
    "active_thread_id": null
  }
}
```

Messages should generally come from core runtime events, not from chat storage. If chat needs UI-only persisted transcript snapshots for performance, store them as derived cache and make them rebuildable.

## Frontend Porting Plan

Phase 1: standalone app shell

- Create React/Vite setup under `apps/chat`.
- Mount inside base-shell iframe.
- Load `GET /api/status` and `GET /api/apps` only as generic platform reads.
- Render the v2 chat workspace visual system inside the app.
- Include app-owned chat navigation: project list, thread list, and new-chat action.
- Do not put chat project/thread controls in base-shell.

Phase 2: core runtime client

- Replace v2 `lib/api.ts` with `frontend/src/api/coreRuntime.ts`.
- Replace `/agent-instances/{id}/history` with `/api/runtime/sessions/{session_id}/events`.
- Replace `/ws/agents/{id}` with core SSE/WebSocket runtime stream.
- Replace start/stop/restart calls with v3 runtime session/turn APIs.
- Read provider/runtime status from generic core APIs for chat-contextual AI indicators.

Phase 3: transcript rendering

- Port stream merge logic.
- Port pending turn rendering.
- Port tool-call rendering.
- Port structured message rendering, but without cross-app widget imports.
- Keep inter-agent message rendering passive/read-only if events contain it, but do not expose active delegation controls yet.

Phase 4: composer

- Port composer text/draft logic.
- Submit user message through core runtime turn API.
- Queue local messages only as UI state until core confirms `turn_id`.
- Handle reconnect and duplicate `client_message_id`.
- Implement `New chat` as chat-owned thread creation.

Phase 4.5: projects and thread navigation

- Implement project CRUD in the chat backend.
- Implement thread list and active-thread selection in the chat frontend.
- Implement thread-to-project movement.
- Persist active thread/project preferences in `data/chat`.
- Keep global workspace selection in base-shell; keep project selection inside chat.
- Add tests for project CRUD and thread/project mapping.

Phase 5: optional features behind gates

- Attachments.
- Prompt preview.
- Periodic schedules.
- Widget rendering.
- Multi-agent controls.

## UI/UX Parity Tasklist

This tasklist tracks the remaining chat UI/UX parity work after the first mounted v3 chat implementation.

The base-shell sidebar is handled through the chat-owned `chat-sidebar` widget, not through compile-time shell imports.

All tasks must be implemented in v3-owned code only. It is acceptable to copy and adapt visual code, but v3 source must not import from or reference legacy paths.

### Priority 1: Message Rendering And Active Turn Controls

- [x] Restore Markdown and GFM rendering for assistant/provider messages, including links, code blocks, inline code, lists, tables, blockquotes, and safe line breaks.
- [x] Add only the frontend dependencies needed for Markdown rendering and sanitization.
- [x] Make assistant/provider message styling match the ported chat visual system exactly: spacing, typography, bubble/card boundaries, code styling, and empty paragraph behavior.
- [x] Replace hardcoded pending labels such as `Codex sta lavorando` with labels derived from the active provider/runtime state.
- [x] Implement stop-turn control when a runtime turn is active.
- [x] Persist the active `turn_id` in frontend state while the turn is running, failed, completed, interrupted, or cancelling.
- [x] Disable or hide stop-turn controls when no cancellable turn exists.
- [x] Render cancelled, failed, and interrupted turns as first-class transcript states.

Note: stop-turn is wired to the generic core interrupt endpoint. The current runtime HTTP path still executes turns synchronously, so interrupting an actively running provider will become practically useful once runtime turns are async/streaming.

### Chat-Owned Shell Sidebar Widget

- [x] Keep project and thread navigation owned by the chat app.
- [x] Mount the sidebar widget through the generic v3 widget registry.
- [x] Keep the iframe-mounted widget alive when the base-shell sidebar is hidden.
- [x] Route selected chats to the chat app view through explicit navigation params.
- [x] Route new-chat actions to a newly created chat in the chat app view.
- [x] Receive `maverick.app.navigate` messages from the persistent shell app frame instead of relying on iframe query-string reloads.
- [x] Add floating settings panels for projects and individual chats.
- [x] Support rename, move, delete, and project creation through the chat backend.
- [ ] Add browser-level regression coverage for open/close sidebar without iframe reload.

### Composer And Attachments

- [x] Implement local attachment state in the composer.
- [x] Show a selected-attachment preview strip before sending.
- [x] Support attachment removal before send.
- [x] Validate attachment count, size, and accepted file types before submit.
- [x] Support paste-from-clipboard attachment insertion where the browser allows it.
- [x] Support drag-and-drop attachment insertion into the composer area.
- [x] Make the attachment floating panel close on outside click and Escape.
- [x] Keep attachment panel positioning, icons, spacing, and hover states aligned with the ported v2 visual system.
- [ ] Wire attachment metadata into the runtime submit payload only through the official v3 attachment surface.
- [x] If the official attachment surface is not ready, feature-gate sending attachments and keep the picker UI non-destructive.
- [ ] Render sent human-message attachments once the message is confirmed.
- [x] Avoid storing attachment data inside chat unless the chat contract explicitly owns that storage.

### Turn UX And Message Queue

- [x] Keep the user's optimistic message visible immediately after submit.
- [x] Avoid temporary disappearance of the user message while the provider/runtime is working.
- [x] Use `client_message_id` to reconcile optimistic messages with confirmed runtime events.
- [x] Prevent duplicate human messages when the runtime history catches up.
- [x] Implement a local outgoing-message queue when the user sends while a turn is busy.
- [x] Show queued messages clearly in the transcript or composer status area.
- [x] Drain queued messages in order after the active turn completes, fails, or is interrupted, if policy allows consecutive turns.
- [ ] Separate `isBootstrapping`, `isSending`, `isRunningTurn`, and `isStreaming` state.
- [x] Do not show provider-working indicators during initial history loading unless a real active turn exists.
- [x] Preserve composer draft text if submit fails before runtime acceptance.

### Transcript Scroll Behavior

- [x] Keep the chat viewport height fixed inside the mounted app instead of pushing content outside the page.
- [x] Ensure the transcript, not the whole page, owns vertical scrolling.
- [x] Auto-scroll only when the user is already near the bottom.
- [x] Do not force-scroll when the user has intentionally scrolled upward.
- [x] Add a floating scroll-to-bottom affordance when new content arrives while the user is away from the bottom.
- [ ] Verify long conversations, large code blocks, and streamed output do not break the layout.
- [ ] Verify desktop, narrow iframe, and mobile viewport scrolling.
- [x] Keep composer pinned and usable while the transcript scrolls.

### Transcript Message States

- [x] Render system/runtime update cards with the correct visual hierarchy.
- [x] Render runtime errors distinctly from assistant/provider messages.
- [ ] Render pending human messages, confirmed human messages, and failed-send human messages distinctly.
- [ ] Render assistant/provider streaming text without layout jumps.
- [x] Render empty assistant/provider output without producing broken blank bubbles.
- [ ] Add heavy-message collapse/expand for very long outputs.
- [x] Preserve readable code-block wrapping and horizontal scrolling.
- [x] Add timestamp rendering consistent with the ported visual system.
- [ ] Add copy affordances for assistant text and code blocks if present in the visual source.

### Runtime And Provider Status

- [x] Replace static `connected` and `sandbox` badges with values from generic core runtime/provider surfaces.
- [x] Show active provider from the provider selector and runtime session state.
- [x] Show execution mode from runtime/workspace policy: sandbox or full-access.
- [x] Show runtime status: ready, queued, running, streaming, failed, interrupted, cancelling, or unavailable.
- [x] Show current model label only if the generic provider surface exposes it.
- [ ] Show last activity timestamp only if derived from runtime events or session state.
- [x] Keep provider selector UI functional without making chat own provider configuration or secrets.
- [x] Handle provider unavailable or misconfigured states with clear UI feedback.

### Tool Calls And Structured Content

- [ ] Define the runtime-event-to-transcript projection for tool-call started, updated, completed, and failed states.
- [ ] Render inline tool-call cards when runtime events expose tool-call data.
- [ ] Add a detail panel or expandable row for tool-call payload details if the visual source includes it.
- [ ] Keep tool-call rendering passive until the corresponding core runtime events are stable.
- [ ] Port generic structured message fallback rendering.
- [ ] Do not reintroduce compile-time cross-app widget imports.
- [ ] Keep concrete widget rendering disabled until the registry-driven widget host surface exists.
- [ ] Treat inter-agent/delegation cards as deferred unless generic inter-agent runtime events are already available.

### Prompt Preview And Periodic Controls

- [x] Keep prompt preview hidden or feature-gated until core and the Agents app expose an official resolved-prompt surface.
- [x] Do not let chat edit base prompts or role prompts directly.
- [x] Keep periodic task controls hidden or feature-gated until scheduling has an official core/app surface.
- [ ] If visual components are ported early, make them inert and clearly guarded by feature flags.

### Responsive And Accessibility Parity

- [ ] Verify mobile composer layout.
- [ ] Verify mobile attachment panel behavior.
- [ ] Verify mobile keyboard behavior and viewport resize.
- [ ] Verify transcript scrolling on iOS Safari and Chromium mobile.
- [ ] Verify keyboard navigation for composer, send, attachment, provider selector, and stop-turn controls.
- [x] Add accessible labels for icon-only buttons.
- [ ] Preserve focus after send, attachment selection, panel close, and stop-turn actions.
- [ ] Ensure color contrast remains acceptable after ported styling and v3 runtime overrides.

### Tests And Verification For UI/UX Parity

- [ ] Add frontend tests for optimistic user-message persistence.
- [ ] Add frontend tests for duplicate optimistic-message reconciliation.
- [ ] Add frontend tests for queued-message behavior.
- [ ] Add frontend tests for attachment panel open, close, select, remove, and validation behavior.
- [ ] Add frontend tests for Markdown/GFM rendering.
- [ ] Add frontend tests for runtime status badge rendering.
- [ ] Add frontend tests for stop-turn enabled and disabled states.
- [ ] Add frontend tests for transcript scroll behavior where feasible.
- [x] Keep `npm run build` passing for `apps/chat`.
- [x] Keep core/app import hygiene checks passing.
- [x] Scan v3 code for forbidden legacy path or module references after every porting pass.
- [ ] Verify the mounted app on the deployed host can create a chat, send a message, keep the user message visible, receive provider output, and scroll correctly.

### Recommended Execution Order

1. Message Markdown/rendering parity.
2. Active turn state, stop-turn control, and provider-working labels.
3. Optimistic message persistence and duplicate reconciliation.
4. Queued send behavior.
5. Attachment panel state, preview, validation, and gated submit payload.
6. Transcript scroll containment and scroll-to-bottom affordance.
7. Runtime/provider status badges from generic core surfaces.
8. Tool-call and structured-message fallback rendering.
9. Responsive and accessibility pass.
10. Frontend test coverage and deployed smoke verification.

## MCP Plan

The chat MCP server should expose chat app operations, not core runtime internals.

Recommended tools:

- `projects.list`
- `projects.create`
- `projects.rename`
- `projects.archive`
- `threads.list`
- `threads.get`
- `threads.create`
- `threads.rename`
- `threads.archive`
- `message.send`
- `turn.stop`

Implementation rule:

- `message.send` may call the core runtime API/service, but through the official generic runtime interface.
- MCP must not import provider-specific code.

## CLI Plan

The chat CLI should be useful for operator/debug workflows.

Recommended commands:

```text
chat projects list
chat projects create "Project name"
chat threads list
chat threads show <thread_id>
chat send <thread_id> "message"
chat stop <turn_id>
chat health
```

The CLI should use the same app backend/core runtime surfaces as the frontend.

## Skill Plan

`skills/chat-ops/SKILL.md` should describe how an agent uses the chat app safely.

It should include:

- How to list and select projects.
- How to list threads.
- How to send a message.
- How to inspect recent runtime events.
- How to stop a turn.
- What chat does not own: providers, secrets, memory, attachments, other apps.

## Tests And Verification

Core tests required:

- Runtime session create/list/get.
- Runtime turn queue/start/complete/fail/cancel.
- Runtime event append/list/stream ordering.
- Runtime interrupt semantics.
- Workspace isolation for runtime routes.
- Provider routing field exposure.
- No core import from `apps/chat`.

Chat app backend tests required:

- Contract validation.
- Install hook creates `data/chat`.
- Health hook detects readable/writable data path.
- Project CRUD persists under `data/chat`.
- Thread-to-project links persist under `data/chat`.
- Thread CRUD persists under `data/chat`.
- Runtime session binding is stored as app metadata.
- Import/export/migration, once enabled.

Chat frontend tests required:

- Project list rendering.
- New chat action creates/selects a thread.
- Thread list selection and ordering.
- AI usage/provider indicator rendering from generic runtime/provider status.
- Stream merge behavior.
- Pending turn rendering.
- Transcript conversion from runtime events.
- Composer draft persistence.
- Duplicate `client_message_id` handling.
- Tool call status rendering.
- App runs inside iframe with relative API paths.

Manual verification:

- Build base-shell.
- Build chat.
- Start core host.
- Open base-shell.
- Select Chat from app registry.
- Create a chat project inside Chat.
- Create a new chat inside Chat.
- See the thread in Chat's thread list, not in base-shell.
- Confirm the chat UI shows the active provider/runtime indicator, initially Codex.
- Create or select a runtime session.
- Send a message.
- See runtime events stream into transcript.
- Stop a running turn.
- Reload page and verify thread/session recovery.

## Implementation Order

1. Finish generic core runtime HTTP API.
2. Finish generic core runtime realtime updates.
3. Add runtime submit and interrupt semantics.
4. Replace smoke chat contract with real contract.
5. Add React/Vite build to `apps/chat`.
6. Port chat visual components and pure transcript/session libraries.
7. Implement app-owned projects, thread list, and new-chat UI/backend.
8. Implement v3 runtime client in chat frontend.
9. Implement AI usage/provider indicators from generic runtime/provider surfaces.
10. Implement small app backend for threads/preferences.
11. Wire MCP and CLI to app backend plus core runtime.
12. Port tests and add missing core tests.
13. Enable optional features one by one: attachments, prompt preview, schedules, widgets.

## Explicit Deferrals

These are intentionally out of the first port:

- Full inter-agent communication UI.
- Cross-app widget runtime.
- Attachment upload flow.
- Prompt editing.
- Periodic task scheduling.
- Memory integration.
- App-to-app direct communication.
- Token/usage accounting until core/provider emits generic usage metrics.

Each of these requires a separate generic surface or owning app. They should not be solved by hardcoding chat-specific access.

## Acceptance Criteria

The port is complete when:

- `apps/chat` is a real v3 app with `frontend/dist`, backend, CLI, MCP, skills, hooks, and app-owned storage.
- Core exposes generic runtime APIs sufficient for chat without importing chat.
- Chat can send a message to a runtime session and render ordered runtime updates.
- Chat can stop an active turn.
- Chat owns projects, thread list, new-chat action, and thread-to-project mapping.
- Chat shows active AI/provider/runtime indicators for the current thread using generic core status/events.
- Chat can reload and recover thread/runtime state.
- Chat data lives only under `data/chat`.
- Base shell can mount chat from the app registry with no hardcoded chat integration.
- Tests cover core runtime surfaces and chat app behavior.
