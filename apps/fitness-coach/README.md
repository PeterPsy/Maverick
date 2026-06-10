# Fitness Coach

Workspace-local Maverick v3 app for building reusable exercise libraries, composing workouts, validating start readiness, and running mobile-first workout sessions.

## Surfaces

- Frontend: React/Vite under `frontend/src`, mounted from `frontend/dist`.
- Backend: `backend/app.py`, with JSON state service in `backend/service.py`.
- MCP: `mcp/server.py`, limited to V1 workout/exercise CRUD, validation, duplicate, and runs list.
- CLI: `cli/app_cli.py`, command `fitness-coach` with actions matching MCP semantics.
- Hooks: install, migrate, and health check.
- Skill: `skills/fitness-coach-ops/SKILL.md`.
- Widgets: `fitness-coach-sidebar` and `fitness-coach-sidebar-footer` for `base-shell`.

## Storage Ownership

Fitness Coach owns only app-domain state under `data/fitness-coach/state.json`.

Storage remains the owner of files, Drive, uploads, previews, media streaming, provider secrets, and Drive localization. Fitness Coach persists stable Storage references such as `file_id`, `stable_storage_file_id`, `connection_id`, `drive_file_id`, display metadata, and source version metadata. It must not persist `stream_url`, raw Drive URLs, tokens, or local filesystem paths.

## Runtime Performance Path

The frontend uses backend action `app.bootstrap` for initial app state instead of independently loading workouts, exercises, view state, and runs. Bootstrap payloads may be cached in scoped `sessionStorage` as stale-while-revalidate data after removing runtime-only media fields such as `stream_url`, token fields, local paths, and secret requests. Recent runs are loaded after the initial screen so they do not block the setup editor.

Workout start is a single atomic `workout.start` backend action. The action accepts an optional updated workout payload, normalizes and validates it, persists the latest workout state, and marks `last_started_at` in one JSON state update. The frontend opens Work mode optimistically from the locally validated workout and reconciles the returned workout metadata when the backend responds.

Work mode media resolution keeps Storage as the owner. Local and Drive media use the Storage media route as the playback URL. Drive media starts playback from the route immediately while Storage `file.localize_status` / `file.localize` runs as a background warmup with runtime cache dedupe and abort support. Blob URLs are reserved for bounded local fallback and are revoked when the player cache is cleared.

Every workout start includes a fixed 15-second Preparation segment before the first editable workout block. The segment is rendered in setup and player views, behaves like a rest segment for timing and media warmup, and is not persisted in `workout.blocks`, draggable, editable, duplicated, or deletable.

## V1 Boundaries

Implemented V1 covers manual setup mode, exercise library, workout editor, work mode player, sidebar widgets, backend state, CLI/MCP CRUD, validation, and run summaries.

Phase 2.0 capabilities such as video analysis, workout generation from folders, media annotations, web suggestions, and async agent jobs are intentionally not declared in the contract.

## Repository Tracking

Fitness Coach follows the workspace-local app mode used by CRM and Mail: source code, tests, app contract, package lock, committed frontend `dist`, sidebar widget builds, hooks, MCP, CLI, and skill docs are tracked in Git.

Runtime state stays under workspace `data/fitness-coach` and is not committed. Local dependencies, caches, reports, logs, and temporary files are ignored by the app-local `.gitignore`.

The companion product specification is maintained through Storage at `storage/generated/fitness-coach/fitness-coach-app-spec.md`.

## Validate And Install

```bash
maverick app fitness-coach frontend build --json
maverick core cli run core.app-sdk.validate --app-id fitness-coach --json
maverick core cli run core.app-sdk.register-local --app-id fitness-coach --json
maverick core cli run core.app-sdk.install-local --app-id fitness-coach --json
maverick core cli run core.app-sdk.status --app-id fitness-coach --json
maverick app fitness-coach mcp list --json
maverick app fitness-coach cli list --json
```

## V1 Verification Record

Last full V1 verification: 2026-06-09.

- Backend unit and contract tests passed with `python3 -m unittest discover -s apps/fitness-coach/tests -p 'test_*.py'`.
- Python modules compiled with `python3 -m compileall apps/fitness-coach/backend apps/fitness-coach/cli apps/fitness-coach/mcp apps/fitness-coach/hooks apps/fitness-coach/tests`.
- Frontend tests passed with `npm test`.
- Official frontend build passed with `maverick app fitness-coach frontend build --json`.
- MCP and CLI discovery passed with `maverick app fitness-coach mcp list --json` and `maverick app fitness-coach cli list --json`.
- SDK validate, register-local, install-local, and status all passed for `fitness-coach`.
- Mobile Playwright smoke passed at 390x844 and 430x932 for setup, library, workout start, non-overlap, and media placeholder rendering.
- Drive smoke used Storage file `file_7b28509e085d4612ac3f9c5936f94958` and its containing Google Drive folder. The workout opened and started from stable Storage refs; media localization was blocked by a missing active Google Drive OAuth secret grant, and the UI handled that as a retryable media error without crashing.

## Performance Fix Verification

Performance-focused verification: 2026-06-10.

- Backend unit tests passed with `python3 -m unittest discover -s apps/fitness-coach/tests -p 'test_*.py'`.
- Python modules compiled with `python3 -m compileall apps/fitness-coach/backend apps/fitness-coach/cli apps/fitness-coach/mcp apps/fitness-coach/hooks apps/fitness-coach/tests`.
- Frontend tests passed with `npm test`.
- Official frontend build passed with `maverick app fitness-coach frontend build --json`.
- SDK validate, register-local, install-local, and status passed for `fitness-coach`.
- MCP and CLI discovery passed with `maverick app fitness-coach mcp list --json` and `maverick app fitness-coach cli list --json`.
- Browser app policy preflight blocked local Playwright smoke for `http://127.0.0.1:8014/app/fitness-coach` with `blocked_restricted_ip`; no browser-policy bypass was attempted.
