# Chat

Workspace chat app that talks to the selected Maverick runtime provider.

## Conversation learning

Settings → Conversation learning controls a disabled-by-default, review-first loop
for completed work episodes. Idle delay schedules review; unfinished work remains
internal context. The reviewer filters already requested/in-progress development,
finds general Maverick limits, and retains durable sourced knowledge rather than
UI requirements. Changed sources hold implementation or Memory writes until
reassessment. Chat persists episode context, evidence, idle-delayed jobs, Memory
candidates, improvement proposals and audit history in `data/chat/learning.sqlite`.
One installation-wide generation lock and transactional attempt fencing prevent
overlapping analysis or late results overwriting new work. Memory writes use the
selected optional `learning-memory` provider through source ingestion; improvements
start visible implementation chats after acceptance. Memory candidates start their own source-verifying chat and save through the scoped `chat_learning_memory` MCP tool. Memory chats run serially; improvements default to four parallel chats. Generated conversations live in distinct Memory and Improvements projects and are excluded from analysis. See [Conversation Learning](../../docs/architecture/conversation_learning.md).

Administrators can use `maverick app chat cli run chat --action learning.read --json`
to inspect learning and `--action learning.discard_all` to dismiss unsaved proposals,
stop linked implementations and fence the consumed backlog, retaining its audit.

## Contract Notes

Native macOS/iOS dictation uses WebKit recording with OS microphone consent.
The native shells authorize the exact isolated app origins registered by the
authenticated shell, including their explicit microphone delegation. When OS
access is denied, Chat directs users to device privacy settings; browser/PWA
sessions retain browser-site guidance.

- Provider account telemetry (`account.updated`) is excluded from transcript cards and live activity labels, including saved history. Core drops these notifications before persistence and transport; Chat also filters historical steps. Authentication and plan metadata require no chat action.
- Frontend, backend, CLI, and MCP entrypoints are declared in `app_contract.json`.
- Chat exposes two Core-owned runners outside the Agents catalog. `Free Agent` is the ordinary workspace-capable default. `Research` has a dedicated composer toggle that appears when the workspace is effectively full-access and a compatible agentic provider is available. Each new Research chat creates a fresh session whose model-facing context contains only that conversation and web research: hosted API models receive the exact read-only Browser tools `web_search` and `web_open`, while native adapters provide equivalent native web-only surfaces. Codex and Antigravity models retain their selected model and reasoning effort in Research. Codex uses a private auth-only home, an empty sandboxed workdir, a persistent chat-scoped thread, and native live web search. Antigravity uses an auth-only home, an empty outer-sandbox workdir, and a fixed primary agent with only `search_web` and `read_url_content`; its customization directories and empty MCP configuration are mounted read-only. Neither path receives the Maverick platform prompt, `AGENTS.md`, workspace files, agent persona, skills, attachments, app references, shell, writes, or delegation. All models on a reviewed runtime inherit the profile: Codex CLI `0.153.4`/`0.159.2`, Antigravity CLI `1.1.27`, and the shared hosted API loop. Unknown native versions and new CLI adapters fail closed until they implement its isolation contract. Successful model selection clears any previous compatibility error. Core validates the contract at creation, turn admission, live-authority refresh, process initialization, and tool execution; model training and provider/service safety policies still apply.
- Chat's CLI and MCP inspect metadata lives in `cli/command_schemas.json` and `mcp/tool_schemas.json`; the no-argument CLI call and the `chat_operations_manifest` MCP tool return the compact `operations.manifest`.
- The contract declares the bundled `chat-ops` skill plus the `chat-sidebar`, `chat-sidebar-footer`, `chat-floating`, `chat-floating-dock`, and read-only `chat-runtime-text` widgets. `chat-runtime-text` is a Chat-owned preview widget and is not evidence that a Fleet app is installed.
- Runtime threads, message sends, and turn interrupts are core-owned runtime operations. Chat does not expose placeholder MCP tools for those operations; the Chat app persists projects and view-filter UI state under `data/chat/state.json`.
- The full app, floating chat, and floating dock share one composer admission path. Existing generic runtime chats submit with `delivery_policy=steer_or_queue`, so a message sent while Codex is working is admitted into the active turn and appears immediately as `runtime.message.steered`; provider rejection or a turn race becomes a server-side next turn. Only a concurrent browser upload or HTTP admission waits in the small local FIFO. The composer continues to expose Send and Stop independently while a runtime turn is active.
- Send and Stop preserve the current focus on pointer-down, like the mobile utility trigger, and execute only on click. This prevents the compact mobile/floating composer from moving the action between pointer-down and pointer-up, whether the editor is focused or a draft has already lost focus. Keyboard focus and activation remain available; the existing collapse/expansion rules are unchanged.
- Existing chats receive the core-owned usage projection in the runtime WebSocket snapshot and through live `runtime.usage.updated` events. The composer shows only the active-context percentage and non-cached tokens in `Mt` (millions of tokens). Its neutral dialog distinguishes non-cached usage, cached input, total processed tokens, cumulative root/delegated usage, token categories, source models, accuracy, cost when available, and metering coverage. Redundant root/delegated cards remain hidden when no delegated usage exists. Chat does not calculate provider limits, treat token counts as a bill, or reconstruct pre-metering provider lifetime totals in the browser.
- When a root chat already owns an active inter-agent orchestration, a same-turn message is also recorded as a bounded user directive with its own client-message idempotency key. It does not create a duplicate generalist-turn link, but the running orchestration still receives the new direction at its next safe delivery point.
- Runtime threads stamped with `source_app_id: design-studio` are retained only as historical, user-visible Chat records. Chat keeps their OpenDesign badge, filter, header, and transcript, but disables composition and performs no Design Studio-specific submit, retry, cancel, project, mode, settings, or tool operation. New work happens directly in native Design Studio; explicit Maverick delegation uses Design Studio's external CLI/MCP/backend bridge rather than Chat.
- Historical plain-hosted chats do not imitate Codex steering. Their messages can still leave every Chat surface immediately; Core accepts them as ordered next-turn work until that protocol declares same-turn input support.
- Chat project references remain app-owned. Chat conversation references carry only a stable Core thread id, display label, and deep link; the composer searches their metadata through the authorized runtime-thread catalog, and an agent follows the materialized reference with `core.runtime.transcript.read`. Drag/search never copies transcript text into the draft or app-owned state, while thread listing, transcript authorization, mutation, deletion, and cleanup remain Core runtime operations.
- Sidebar project names load independently of the runtime thread stream. A failed catalog read or revalidation retains any known names and its own visible error with `Reload project names`; thread updates cannot clear that failure. Returning to a visible tab or reconnecting retries only a failed, non-pending catalog read, through the approved read SDK rather than polling. Newer project mutation/read-receipt projections supersede older pending display reads. A healthy empty catalog is not treated as a transport failure.
- New runtime-thread titles are core-owned asynchronous metadata. When the first accepted user message is queued, the thread title is marked pending and Chat renders a skeleton title while the turn starts normally. A core background micro-task routes a dedicated hosted title model, Google AI Studio `gemini-3.1-flash-lite`, for a concrete title from the first user message, attachments, and app-reference labels; if hosted routing or generation is unavailable, the core falls back to Codex and then to a deterministic title so the skeleton is not left pending. Completed title jobs persist redaction-safe `title_generation_provider_id` and `title_generation_model_id` metadata on the thread. Non-pending titles, including user-renamed titles, are preserved.
- Draft chats keep a hidden runtime session prepared for the next new chat before the first send, including while the user is viewing an existing thread. Prepared sessions use `prepare_only`, stay out of the visible thread catalog until the first turn is submitted, and are replenished after a prepared draft is consumed. Chat resolves the selected provider's effective default reasoning effort before starting the preload, while Core fingerprints the resolved binding and its revisions; an omitted default and the same explicit default therefore cannot create parallel equivalent prepared sessions. Chat retains the returned `session_id` even when the two-second prewarm wait reports pending; a send waits for an in-flight prepare response or repeats the same idempotent preparation instead of creating a second session, then submits the first turn to that prepared session for promotion. Asynchronous title generation follows from the queued message and must not block message persistence or turn execution. Complete Storage references are pre-materialized immediately for both prepared drafts and existing runtime threads; the core's authorization-aware single-flight cache lets a concurrent worker wait for that same result instead of invoking Storage twice.
- Chat declares optional `agent-catalog`, `text-to-speech`, and `speech-to-text` dependencies on the `agent.catalog`, `speech.synthesis`, and `speech.transcription` interfaces. Before creating the first runtime session, Chat reads the selected agent's self-contained instructions and assigned `skill_ids`: non-empty assignments narrow the automatic catalog, while an empty custom-agent assignment exposes no skills. Speech synthesis and transcription require an explicit dependency selection from the core dependency resolver; Chat does not silently pick an unselected speech provider candidate. Existing runtime sessions keep their original agent metadata and cannot switch runner from the composer.
- Core retains `plain_hosted_chat` only for internal tests and compatibility with already-persisted sessions; Chat never offers it as a new model choice. Such sessions must not include skills, tool/MCP use, operative app references, or filesystem materialization. Storage-backed attachments may be sent only when their type matches the persisted hosted model's declared input modalities and the hosted provider bridge can serialize that modality. Plain-hosted attachment serialization enforces backend count, per-file, and aggregate inline byte limits before base64-encoding files, and Chat must not know provider secret values or credential bindings.
- New Free Agent chats receive the enabled workspace Skills catalog through `skill_activation_mode=implicit` and choose which skill instructions to read when needed. Custom agents receive only their assigned enabled skills; a custom agent with no assignments receives none. Research receives no skills. PC use retains the ordinary agent's skill catalog and adds native Mac tools without replacing workspace capabilities. Skills are managed in the Skills app rather than selected from the composer, while existing runtime sessions retain their persisted activation mode.
- New-chat model selection exposes only authorized direct agentic workspace profiles. The compact menu groups them as `CLI models` or `API models` and renders only model name and reasoning; provider routing, endpoint and upstream details remain server-owned diagnostics rather than composer copy. Antigravity effort-suffixed catalog aliases are projected as one model row with its supported High/Medium/Low selector. Selecting a model sends its `workspace_profile_binding_id` only with the new session and never changes the Settings default. Chat never reconstructs policy, classification or capability from model ids or UI labels. Contained remote profiles are never offered for a new chat. A pinned contained or quarantined session remains visible with its stable public reason and disables further composition; persisted plain-hosted sessions remain readable for compatibility but cannot be selected for new work.
- During a rolling frontend/backend update, an exact local Codex selection or materialized session without the newer effective-capability projection retains its established app-reference and local attachment behavior. Materialized bindings must carry the complete Codex app-server identity; incomplete, remote, contained, or unknown bindings keep references and attachments fail-closed.
- Tool calls paused in `waiting_for_tool_confirmation` remain busy and resumable. Chat loads the authoritative invocation summary, effect class, policy revision, bounded argument summary, digest, and expiry from Core, then submits an authenticated approve-once or deny decision with the exact invocation revision. The browser never receives a confirmation grant secret or private arguments, and provider-private payloads are never interpreted by Chat.
- Tool-call activity uses one deterministic, status-aware presenter for both the live runtime label and transcript rows. It derives bounded descriptions such as searched query plus target, file read, test run, build, Git operation, web query, or structured file change from redaction-safe public event fields; unknown commands and hosted handles receive humanized fallbacks. Technical commands and payloads remain behind the row disclosure, and Chat never interprets private hosted-tool arguments to manufacture a more specific label.
- The composer `@` picker uses the core app-reference API, so enabled reference providers such as Checklist and Storage can contribute app-owned records, files, and folders without Chat reading their storage directly. It also merges authorized Core runtime-thread metadata so existing chats are searchable and citeable without exposing their messages in search results. Typed searches try targeted app, checklist, chat, or file/folder searches first and fall back to one generic cross-app search only when needed; empty picker opens use recent chats plus the active app or generic file/folder references instead of immediately fanning out globally. The picker keeps a short workspace-scoped cache for repeated query and active-app combinations.
- The desktop composer keeps attachments, secondary controls and runtime badges on one row. Long model labels shrink with ellipsis rather than moving the attachment plus to another row. At mobile widths the composer keeps attachment and Utility on the left while dictation, Stop, and Send remain on the right. Utility opens an upward panel containing the same desktop-formatted secondary controls, including references, multi-agent mode, and agent/model/runtime selection. The fixed-right floating chat preserves that complete mobile control set instead of hiding its model/runtime controls, without exposing the unused page-area capture action. Choosing a secondary control replaces that panel with the control's own picker; closing or selecting from the picker returns to the Utility controls.
- The floating and full composer also accepts app reference drag payloads from Storage, Checklist, Mail, and Chat. Sidebar chats use the same compact drag-card behavior as Storage and become normal `@` thread references, using the same `[ref:<app_id>/<entity_type>/<entity_id>]` markers and runtime `app_references` payload as picker-created citations.
- A persisted collapsed floating window loads its Chat content only when opened. Later collapse retains the mounted composer and draft while suspending its runtime event streams and reconnects. Each floating window has its own visibility scope; the widget reads its initial host context once.
- Project deletion is destructive: the Chat backend requests core cleanup for every runtime thread with the project id, then commits the app-owned project removal only after cleanup succeeds.
- Chat full app and widgets render the bounded initial thread page and live deltas from `WS /ws/runtime/threads`, ordered by each thread's latest accepted user message; `GET /api/runtime/threads` exposes the same bounded catalog shape with cursor paging for explicit reads, sidebar idle backfill, and sidebar metadata search backfill, while create/rename/read/delete responses carry only changed-thread or removed-id deltas. A persistent surface that resumes with the same shared-source client identity receives the complete current snapshot again, and a cached display may seed only before that mounted surface has rendered an authoritative snapshot. Sidebar multi-select deletion sends an ordinary complete catalog selection in one keepalive request within Core's 500-thread bound. Selections beyond that bound are sent sequentially, but each successful chunk is applied immediately so a later transport failure leaves only unresolved chats selected for retry. The sidebar keeps No project first, then orders project sections by their newest visible chat, with empty or equally recent projects ordered by name. Transcripts render a bounded recent tail and live runtime events from `WS /ws/runtime/sessions/<session_id>`, with replay pages extended back to the current turn anchor when possible, then page in either direction over the same WebSocket. The active view retains at most 6,000 events / 32 MiB of estimated event, index and projection memory, with room left after eviction for subsequent batches. The live turn and one indivisible event may exceed that allowance. Evicted historical data remains accessible through earlier/newer pages and Jump to latest message; incoming control and usage updates continue while the user reads a historical window. Cold navigation entries also preserve whether newer history exists. Superseded history responses cannot move the view or overwrite live turn state. Hibernation records the visible message’s persisted event identity and pixel offset, then requests an anchored history window before restoring scroll and acknowledging resume. Active turns and in-flight history initialization stay mounted; hidden restoration pauses until the frame is visible again. Thread busyness is core runtime state derived from queued, active, terminal, and interrupted turn lifecycle events. Completed-response unread state is also core-owned: the runtime thread payload exposes `has_unread_completed_response`, while the sidebar Hot view anchors its 24-hour window to the newest visible chat in the current catalog instead of the browser clock and reevaluates immediately on every catalog change. The Unread view includes completed unread responses plus queued, active, or busy chats. Filtered views suppress project sections without matching chats, and the Unread view temporarily retains the most recently opened chat as the active row after marking it read until selection moves elsewhere. Chat marks a thread read through `POST /api/runtime/threads/<thread_id>/read` only when the user explicitly selects, opens, or clicks into that chat from the sidebar, floating-chat controls, or full chat surface.
- Sidebar feature filters and title badges distinguish OpenDesign, Senses, Research, macOS Device Use, and multi-agent chats. Core's compact thread catalog exposes only the non-sensitive `runtime_profile` and `device_use_enabled` classifiers needed for those views; Device Use bindings and tickets remain private. Filtered mobile views keep each project group at intrinsic height so a single matching group remains vertically scrollable.
- Structured provider runtime steps reuse Chat's expandable activity disclosure without being presented as tool calls. Chat projects one card for the current goal lifecycle, merges later objective, status, usage, and elapsed-time snapshots into that card, suppresses empty `thread.goal.updated` telemetry, and removes an active card when the provider clears the goal; terminal completed or blocked snapshots remain visible. The bounded merged provider payload stays behind a secondary technical-details disclosure. Ordinary progress labels remain compact and non-interactive.
- The collapsible Actions box contains `AgentTrace`, a live timeline that adds rows as tool events arrive and extends active spans from their retained start timestamp. Completed/error events freeze each span's end; a final output closes remaining active spans. Selecting a row opens the existing command, query, result, output, error and confirmation panels; their header has a close button, including for pending confirmations. The Chat timeline has no footer playback bar: drag directly in the graph or use its focusable playhead with arrows, Home and End to seek. Releasing the pointer or navigation key animates forward from the chosen point; reaching the end rejoins runtime updates. Opening and closing action details preserves the playhead position. The reusable component and standalone preview retain optional replay controls. Unknown timing remains a zero-length span rather than a fabricated duration. Only reported token counts, retries, parent links and cache hits appear. The same component works in participant transcripts; container queries keep its labels and graph usable on phones, and reduced motion disables automatic replay on mount.
- Chat already supports React 19, TypeScript, Tailwind 4, shadcn aliases, `lucide-react` and `motion`. Reusable UI lives at `frontend/src/components/ui` (`@/components/ui`), with shared theme utilities at `frontend/src/styles/tailwind.css`, native app styles under `frontend/src/styles`, and the supplied standalone trace preview at `frontend/src/components/ui/agent-trace/demo.tsx`. No images or additional providers are required.
- Multi-agent graph mode stays inside Chat. Every message is submitted first to
  the independent generalist runtime. When orchestration is requested, Chat
  sends only the accepted root turn id and policy intent to the core; the core
  creates an orchestrator-only board and waits for the generalist's terminal
  handoff before planning. After each worker output the orchestrator may add or
  cancel work or complete; every decision and task is persisted before the
  graph changes. Later Chat turns steer the active run through their completed
  generalist output, while the Agent nodes view also exposes a bounded direct
  steering input. Before those later turns reach the provider, core injects an
  authorized read-only snapshot of the linked run so the generalist can explain
  status, task progress, current quality gate, and safe artifacts without Chat
  copying participant events into the root transcript.
- Dynamic workers may select specialized agent types from Chat's resolved
  agent provider. The core lists a compact authorized catalog and materializes
  the selected agent instructions, explicit skills, provider, and skill catalog server-side. The
  default orchestration budget supports 17 participants and four concurrent
  workers; group policy supports 25 and six, while retaining headroom for
  adaptive follow-up work.
- Hosted backend restart recovery replays persisted plans, decisions, attempts,
  and task outputs. It creates a new recovery-generation hidden session only
  for interrupted non-terminal work and does not rerun completed tasks or
  enqueue generic participant `resume` prompts. Recorded decisions are applied
  idempotently before scheduling; existing workers reuse their persisted agent
  snapshots when the catalog is unavailable, and an older review cannot approve
  material work added later in the DAG.
- The primary transcript and Agent nodes use separate data sources. Participant
  runtime events are never projected onto the root runtime session. Agent nodes
  consumes `WS /ws/inter-agent/runs/<run_id>` plus bounded participant
  transcript endpoints for activity and replay; Chat's root message array is
  neither passed to nor filtered by the board.
- Static `group_chat`, handoff, and adapter modes remain low-level evaluation
  surfaces. Chat product orchestration uses the dynamic core-owned scheduler and
  the same Maverick-owned run, event, budget, replay, cancel, and Agent nodes
  contracts.
- Chat full app thread selection publishes shell deep links as `/app/chat/threads/<thread_id>`; scoped widgets keep their own local selection state and do not rewrite the browser URL.
- On reload, Chat restores the conversation requested by the shell route. Without an explicit conversation it starts with a draft, even when the catalog contains existing or quarantined threads. This initial draft does not rewrite the shell URL; incoming navigation takes precedence over catalog bootstrap. A confirmed missing thread falls back to a new draft with a visible unavailable-chat notice, while transport or authorization errors remain errors.
- Streaming presents the first nonempty text delta of each turn immediately, then combines subsequent presentation deltas per animation frame. Tool/control and terminal events flush pending updates in order without an extra frame delay.
- Assistant text keeps its runtime message identity and completion boundaries, preserving paragraph and list whitespace inside each message. Final answers already present in the stream are not appended again after progress updates. Replayed completed-item snapshots that repeat an existing streamed suffix are suppressed, including histories recorded before message identities were preserved.
- Transcript agent, structured and tool cards use their existing surfaces, gradients and shadows without backdrop blur, keeping scrolling and streaming cheaper to composite. The docked composer skips backdrop filtering at the actual scroll end, where bottom padding keeps content clear; scrolling into history restores its glass, and other overlays retain their blur.
- Agent Markdown links that use canonical `/app/<app_id>` deep links are routed through the parent shell so app switches never navigate the Chat iframe or create a nested shell. Workspace Storage files under `storage/generated/` or `storage/uploaded/`, including absolute workspace filesystem paths, are additionally normalized to workspace-relative Storage paths before Chat routes them to Storage. Chat forwards embedded widget open-app requests back to the shell and synthesizes the same `workspace.file.preview` widget for completed streamed output as for final output text.
- Message copy controls switch to a temporary check only after the text is written. Chat first uses the asynchronous Clipboard API, then falls back to a temporary selected textarea when a browser exposes that API but denies writes inside the isolated app frame. Base Shell also delegates `clipboard-write` to Chat-owned full-app and widget frames.
- Agent response footers expose a speaker control beside the copy action only when Chat resolves an enabled `speech.synthesis` provider and that provider reports synthesis availability. Chat removes fenced code blocks and normalizes the remaining collapsed Markdown before synthesis. Responses longer than 80 characters always receive a short initial chunk, including responses below the provider `max_text_chars`; later chunks remain sentence-oriented and capped at 450 characters or the provider limit. Buffered playback keeps at most two synthesis chunks in flight. Progressive playback gives the initial chunk exclusive priority, then opens up to two later requests only after the first browser audio bytes arrive; this avoids remote provider contention on tap-to-audio. Chat plays returned audio in order and aborts every obsolete fetch when the user stops playback, changes message, or leaves the transcript. When the provider explicitly advertises governed `audio/pcm` streaming and the browser exposes Web Audio `AudioWorklet`, Chat requests progressive PCM, converts signed 16-bit little-endian samples incrementally, resamples to the device context when needed, and starts a single worklet after a 60 ms jitter buffer so ordered text chunks share one playback timeline. On Apple mobile browsers Chat first requests the `playback` Audio Session category, so Web Audio remains audible with the hardware silent switch; when the browser cannot activate that category, Chat uses the buffered `HTMLAudio` compatibility path instead of starting an inaudible PCM stream. `base64 -> Blob -> HTMLAudio` also remains the fallback for local engines, unsupported browsers, and stream failures before playback starts. Chat emits redaction-safe `maverick:speech-playback-metrics` browser events and also records the same bounded observations through the selected Speech backend: tap-to-request, first browser chunk, tap-to-playing, server phases, generation id, outcome, underrun count, audio context state, and audio session category. It never receives the provider credential. Only one agent response can remain active. When the provider advertises a persistent TTS prewarm surface, Chat loads it as soon as capabilities resolve.
- The composer exposes microphone dictation only when Chat resolves an enabled `speech.transcription` provider and that provider reports transcription availability for Chat's inline default profile. Chat automatically prewarms the selected Speech worker when capabilities resolve. Composer dictation stays on bounded one-shot inline requests unless the provider explicitly reports `dictation_streaming_supported: true`; Deepgram Flux conversation streaming alone is not treated as dictation streaming. Every streaming chunk is marked with `dictation: true` so Speech keeps it in one provider session instead of treating MediaRecorder fragments as independent files. Streaming dictation inserts every ordered finalized delta through an optimistic composer snapshot, so multiple responses that settle before React renders cannot replace earlier phrases. One-shot dictation requests use the same dictation marker so provider-specific voice commands remain scoped to microphone dictation. Chat does not force the browser UI locale as the spoken language; Speech auto-detects the first request, then Chat reuses a high-confidence detected language such as `it` for one follow-up request before forcing a fresh auto-detection probe.
- Structured widget iframes allow the browser `fullscreen` feature so embedded app previews such as Storage file previews can enter native fullscreen from a user action. A cross-owner widget is launched through Core's parent-bound nested-frame endpoint rather than loading its frontend on Chat's origin: Chat validates the returned exact origin/parent/host/owner/widget attestation, POSTs the one-shot ticket into an `about:blank` frame, reveals it only after the exact-origin/source ready signal, and otherwise renders the generic structured-content fallback.
- `chat-floating` persists its open window list as browser UI state under `maverick.chat.floating-widget.state.v1:<workspace_id>`. It hydrates that workspace-scoped state before rendering or writing updates, migrates the older global fallback key only when the workspace key is empty, and never silently replaces a saved missing `threadId` with the first available thread.
- The base shell can move the selected floating chat into its fixed right dock through the generic `maverick.widget.dock.open` message. The dock mounts `chat-floating-dock` in the `shell.dock.right` slot, renders one chat frame, and writes the selected chat back as a collapsed overlay window when the dock closes. On mobile, base-shell hides the bottom-right overlay launcher and mounts the same `chat-floating-dock` widget in `shell.overlay.mobile.fullscreen` from the header Chat app icon, rendering one contextual chat below the persistent base-shell header instead of the desktop floating stack.
- Chat's app and widget frontends consume the base-shell theme protocol. Their HTML entries apply initial `maverick_theme` URL parameters before frontend bundles run, then runtime listeners accept `maverick.shell.theme-changed`, `maverick.app.navigate`, and `maverick.widget.context-changed` theme payloads so app-owned tokens render in dark or light mode without importing shell CSS.
- `chat-sidebar` owns only the shell sidebar's central chat/project list; `chat-sidebar-footer` owns the fixed shell footer action for starting a new chat.
- HTTP runtime event and thread reads are not used as frontend bootstrap or realtime fallbacks.
- The runtime text widget is read-only and renders compact transcript text for one `runtime_session_id`; it uses the same runtime-session websocket path as the full Chat app and does not create sessions or submit turns.
- Persisted `view_surfaces` cover runtime-thread/project browse filters and curated transcript selections; the widgets remain first-class embedded shell surfaces.

## SDK Flow

`chat` is an installation-level built-in app under `apps/chat`, not a workspace-local app project. Validate this source tree with an explicit app root:

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-id chat --app-root apps/chat --workspace default --json
```

`register-local`, `install-local`, and `package` operate on workspace-local app projects under `workspaces/<workspace_id>/apps/<app_id>/`; they are not the correct lifecycle for this built-in Chat app source.

## Sidebar components

The shell-hosted `chat-sidebar` uses the adapted dashboard sidebar in
`frontend/src/components/ui/dashboard-sidebar.tsx`. Its dropdown groups real
conversation views (all, recent, unread/active) and categories (Research,
Multi-agent, Device Use, Senses, OpenDesign), with live catalog counts. Search
still uses the existing title/project/transcript index. The view selector,
expand/collapse and new-project actions, and search trigger share one row,
without Chat or Projects headings. The selected view keeps the same inline icon
as its dropdown item, including on narrow sidebars. The selector and search use
soft background feedback on focus without bright outlines or focus rings.
Clicking search or pressing
Cmd/Ctrl K expands the field across the whole row and hides the selector. Leaving
the search field restores the compact row and retains the query, indicated on
the search trigger; Escape clears the query and closes search. The clear button
resets a query, or closes an empty field. Search and category views open their
matching groups. All conversations starts with every group closed,
including No project and projects arriving later from the catalog. Individual
toggles and expand/collapse all stay consistent with that default; runtime updates
retain manual choices. Returning to All conversations or clearing its search
restores the compact list. Each whole project header toggles an animated disclosure.
Closed project groups use compact 32px headers with 4px spacing.
The project toolbar can expand/collapse all groups or create a project even when
the current view is empty; successful creation returns to all conversations so
the new project is visible. Project menus expose rename, new chat and the existing
inline delete confirmation. Thread editing, selection, drag references, unread
states and Busy glow animations retain their existing runtime behavior. Thread
rows reveal compact checkbox and pencil controls on hover, keyboard focus or the
existing mobile long press. The timestamp does not intercept clicks on these
controls, and long presses do not select the row's title text.
When a conversation drag starts in the shell's mobile layout, the sidebar closes
to reveal the open chat's composer while preserving the drag reference. Desktop
drags keep the sidebar open; a long press that only reveals row controls does not
close it.
Editing opens one full-width panel with labeled title
and project fields, separate delete action, Cancel and Save. Enter saves and Escape
closes the panel with focus restored to the edit button. Save stays disabled for
empty or unchanged drafts; pending requests lock the fields, and failures retain
the draft for retry. Deletion requires an inline confirmation. Editing does not
show unrelated row actions or a bright focus outline. Collapsed
groups are inert and pause their hidden Busy animations.

Chat already uses React, TypeScript and Lucide. Tailwind v4 is built through
`@tailwindcss/vite`, with utilities and theme imports in
`frontend/src/components/ui/dashboard-sidebar.css`; preflight is omitted to
preserve existing Chat styles. Theme colors map to Chat's Maverick tokens.
`components.json` and the Vite/TypeScript `@` alias establish the shadcn structure:
`@/components/ui` resolves to `frontend/src/components/ui`, rather than a repository
root `/components/ui`. Keeping shared UI primitives there lets the component
generator and app imports agree on one location. `@/lib/utils` supplies `cn`.
After `npm install`, additional shadcn components can be added from `apps/chat`
with `npx shadcn@latest add <component>`; no TypeScript/Tailwind setup is needed.

## Browser E2E

Chat has an app-level Playwright harness for full-browser smoke coverage:

```bash
npm run test:e2e
```

The suite starts the Chat Vite frontend at `/apps/chat/`, mocks Chat's declared HTTP and WebSocket surfaces at the protocol boundary, covers normal runtime send, and covers selected-agent multi-agent graph flow. On a fresh machine, install the Chromium browser once with:

```bash
npx playwright install chromium
```

## Mac access as a chat capability

PC use is selected before the first message of a native Mac chat. New chats retain
their selected agent, project, model/effort, platform prompt and skill activation
mode, and expose attachments, references, dictation and multi-agent controls as
normal. Mac tools and native instructions are additive. Core enforces workspace
permissions independently of Full Mac authority. Turning PC use off or losing
the Mac connection leaves workspace submissions and app surfaces available; only
native calls fail closed. Collaborator sessions do not inherit the Mac binding.
Initial activation still requires the ready native/Core lease, and existing chats
without a Mac binding cannot acquire one. Isolated Research remains incompatible
with PC use; native model selection uses admitted Codex/Antigravity profiles.
