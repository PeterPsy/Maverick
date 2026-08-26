# Settings

Admin-only platform settings app for provider/runtime settings, users, workspace roles, workspace assignments, app visibility, and core persistence adapter operations.

## Contract Notes

- The app currently declares frontend, CLI, MCP, and base-shell sidebar widget surfaces.
- `settings` intentionally does not declare an app-owned backend or lifecycle hooks yet; authoritative admin state remains core-owned.
- Persistence adapter status, platform settings, provider/model selection, runtime-session cleanup, and backend restarts are core-owned admin surfaces. Settings presents those surfaces in the UI.
- The platform settings panel manages installation-published agentic definitions through workspace bindings. Platform and workspace admins can attach an eligible credential binding, choose the workspace default, restrict actors, tools, confirmations, and cost, and inspect the Core-owned egress/data policy, pinned engine/adapter/provider/model, certificate status and expiry, routing, health, and preview posture. The browser does not classify session data or patch allowed remote-data classes. Settings never edits a `certified` boolean and never rewrites existing sessions. Hosted text selection remains an independent `plain_hosted_chat`/`fast_model` path. Speech-to-text settings expose Deepgram audio transcription and conversation models as separate choices because file/one-shot transcription uses Nova-3 over `/v1/listen`, while realtime conversation uses Flux models over the WebSocket v2 Listen API.
- Phase-0 remote agentic release is visibly **NO-GO**. Settings keeps Google, OpenRouter, and future hosted-agentic definitions visible after suspension, preserves the exact `fake-data preview` warning label, and shows provider/upstream, data destination, effective egress policy and Core-classified data set, collection/ZDR policy, attestation unavailable, binding/profile state, and certificate eligibility. A contained disabled binding cannot be enabled from the browser; an already-enabled one can only be narrowed/disabled. No fake-data consent or data-class checkbox exists. Codex agentic and hosted text controls are unchanged. Quarantined runtime rows expose `recovery_required` with only an allowlisted public reason instead of arbitrary Core diagnostic detail.
- Agentic providers that declare `supports_subscription_usage` expose redaction-safe account limits in the same provider card. Settings loads those limits independently through the admin-only `GET /api/providers/usage` surface, supports manual refresh, and keeps the rest of the platform settings usable when the upstream usage service is unavailable. Codex credentials remain server-side; the browser receives only plan, percentage, reset-window, availability, and credit summary fields.
- The platform settings page also loads core-metered workspace token history from the admin-only `GET /api/usage/timeseries` surface. Charts default to non-cached tokens and retain explicit cached-input and processed-total details. Admins can select the metric, provider, model, and bounded hourly or daily range; the API returns gap-filled UTC buckets plus provider/model facets for the selected period. These charts describe locally observed runtime consumption across root and delegated sessions; cumulative lifetime counters observed when metering attaches to an existing provider thread establish a baseline instead of inflating the first bucket. The charts remain separate from provider subscription percentages and do not claim coverage before metering was enabled.
- Persistence migration UI must call the core dry-run endpoint before apply. The confirmation dialog exposes target JSON/Mongo connection fields, including Mongo username and password secret ref, and source cleanup is an explicit operator opt-in rather than the default migration behavior.
- The main app iframe owns the settings work surface and renders one page at a time: platform settings, users, workspace access, workspace apps, app links, or persistence.
- The app links page presents generic core app dependency selections for the active workspace, including intra-app provider catalogs such as `agent.catalog`. It calls `/api/apps/dependencies` and does not read another app's private storage.
- The `settings-sidebar` iframe declared for `shell.sidebar.primary` is a page navigator, matching the page-list pattern used by Docs Studio. Selected-user controls live inside the relevant Settings pages.
- The platform settings panel is rendered inside the main app work surface rather than as a shell modal or app-local overlay. It calls generic core settings/provider/runtime APIs and keeps the shell boundary app-agnostic.
- The app stores only admin UI preferences under `data/settings/preferences.json`.
- `reference_entities`, `data_events`, and persisted `view_surfaces` remain intentionally empty until the app grows app-owned administrative state instead of acting as a shell over core-managed records.

## Frontend Structure

The app remains a TypeScript/Vite work surface, with React mounted only for reusable UI components. Tailwind CSS 4 and the shadcn alias contract are configured in `components.json`; because Vite's source root is `frontend/src`, the canonical shadcn UI path for this app is `frontend/src/components/ui`. The subscription usage view uses `components/ui/gauge-1.tsx` with Maverick font and monochrome design tokens supplied by the surrounding app.

## SDK Flow

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-id settings --app-root apps/settings --workspace default --json
./scripts/maverick app settings frontend build --operator --json
python3 -m unittest discover -s apps/settings/tests -p 'test_*.py'
```

`settings` is an installation-level sealed app under `apps/settings`; it is not a workspace-local app project. Do not use `core.app-sdk.register-local` or `core.app-sdk.install-local` for this app unless it is intentionally copied into a workspace-local development project.
