# Settings

Admin-only platform settings app for provider/runtime settings, users, workspace roles, workspace assignments, app visibility, and core persistence adapter operations.

## Contract Notes

- The app currently declares frontend, CLI, MCP, and base-shell sidebar widget surfaces.
- `settings` intentionally does not declare an app-owned backend or lifecycle hooks yet; authoritative admin state remains core-owned.
- Persistence adapter status, platform settings, provider/model selection, runtime-session cleanup, and backend restarts are core-owned admin surfaces. Settings presents those surfaces in the UI.
- The platform settings panel groups selectable agent models first into `CLI models` and `API models`, then by provider (for example Codex, Antigravity, and OpenRouter). A provider heading shows used and remaining subscription allowance when Core can report it; otherwise it states that the limit is not reported. Rows keep model and reasoning prominent, while binding, credential, default and policy controls remain available when a row is expanded. Plain hosted text has no Settings model family, while internal generation and historical sessions retain the lower-level compatibility path. Speech-to-text and synthesis remain separate: file/one-shot transcription uses Nova-3 over `/v1/listen`, realtime conversation uses Flux over WebSocket v2, and TTS keeps its own hosted choices.
- Settings uses Core's effective-capability and data-policy projections to gate remote controls. The compact model rows show availability, reasoning and activation, with credential, cost and workspace policy controls in the expanded row. Contained remote controls remain blocked by the server-owned posture; the effective snapshot is never a client capability override. No fake-data consent, data-class checkbox or client credential authority exists. Quarantined runtime rows expose `recovery_required` with only an allowlisted public reason instead of arbitrary Core diagnostic detail.
- During a frontend/backend rollout, missing effective-capability or attestation projections render as unavailable instead of aborting the settings panel. Remote agentic enablement fails closed until the active backend publishes an active effective-capability snapshot.
- The runtime inventory shows one card per exact model inside each execution family and model provider, rather than repeating historical or alternative profile definitions. The enabled workspace default takes precedence, then another enabled, selectable, enable-eligible or Full Workspace-available profile, and finally the highest naturally ordered revision. `/api/settings/platform` returns this compact Settings projection while the dedicated agentic administration APIs retain complete revision history. Binding IDs/CAS and existing session pins remain unchanged.
- A disabled native connection with a healthy installed runtime and an authenticated catalog offers `Enable <provider>` in its Models heading. This explicit platform-admin action uses `POST /api/providers/native/activate`, then reloads Settings. It restores the connection without changing workspace model switches. Runtime tokens and non-admin users cannot activate connections through this endpoint.
- Agentic providers that declare `supports_subscription_usage` expose a compact redaction-safe used/remaining percentage beneath the provider name. Settings loads those limits independently through the admin-only `GET /api/providers/usage` surface and keeps the rest of the platform settings usable when the upstream usage service is unavailable. Codex credentials remain server-side; the browser receives only plan, percentage, reset-window, availability, and credit summary fields.
- The platform settings page also loads core-metered workspace token history from the admin-only `GET /api/usage/timeseries` surface. A single chart defaults to non-cached tokens and retains explicit cached-input and processed-total details. Admins can select the metric, provider, and model above the chart, then choose a bounded time range from the button row below those filters; ranges through three days use hourly UTC buckets and longer ranges use daily UTC buckets. The chart describes locally observed runtime consumption across root and delegated sessions; cumulative lifetime counters observed when metering attaches to an existing provider thread establish a baseline instead of inflating the first bucket. It remains separate from provider subscription percentages and does not claim coverage before metering was enabled.
- Persistence migration UI must call the core dry-run endpoint before apply. The confirmation dialog exposes target JSON/Mongo connection fields, including Mongo username and password secret ref, and source cleanup is an explicit operator opt-in rather than the default migration behavior.
- The main app iframe owns the settings work surface and renders one page at a time: platform settings, users, workspace access, workspace apps, app links, or persistence.
- The app links page presents generic core app dependency selections for the active workspace, including intra-app provider catalogs such as `agent.catalog`. It calls `/api/apps/dependencies` and does not read another app's private storage.
- The `settings-sidebar` iframe declared for `shell.sidebar.primary` is a page navigator, matching the page-list pattern used by Docs Studio. Selected-user controls live inside the relevant Settings pages.
- The platform settings panel is rendered inside the main app work surface rather than as a shell modal or app-local overlay. It calls generic core settings/provider/runtime APIs and keeps the shell boundary app-agnostic. Initial `/api/settings/platform` loading excludes runtime-session projection; the cleanup inventory is fetched independently through `/api/settings/runtime-sessions` after the settings surface becomes usable.
- The app stores only admin UI preferences under `data/settings/preferences.json`.
- `reference_entities`, `data_events`, and persisted `view_surfaces` remain intentionally empty until the app grows app-owned administrative state instead of acting as a shell over core-managed records.

## Frontend Structure

The app remains a TypeScript/Vite work surface, with React mounted only for reusable UI components. Tailwind CSS 4 and the shadcn alias contract are configured in `components.json`; because Vite's source root is `frontend/src`, the canonical shadcn UI path for this app is `frontend/src/components/ui`.

## SDK Flow

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-id settings --app-root apps/settings --workspace default --json
./scripts/maverick app settings frontend build --operator --json
python3 -m unittest discover -s apps/settings/tests -p 'test_*.py'
```

`settings` is an installation-level sealed app under `apps/settings`; it is not a workspace-local app project. Do not use `core.app-sdk.register-local` or `core.app-sdk.install-local` for this app unless it is intentionally copied into a workspace-local development project.
