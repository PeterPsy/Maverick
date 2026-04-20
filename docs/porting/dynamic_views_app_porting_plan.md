# Dynamic Views App Porting Plan

Date: 2026-04-20

## 1. Architecture Alignment

- v3 docs read: `AGENTS.md`, `IMPLEMENTATION_TASKLIST.md`, `docs/architecture/core_architecture.md`, `docs/architecture/app_contract_architecture.md`, and `docs/architecture/workspace_root_architecture.md`.
- relevant core modules inspected: `core/api/platform_host.py`, `core/api/app_mounts.py`, `core/api/widget_api.py`, `core/apps/*`, `core/mcp/*`, `core/cli/*`, `core/skills/*`, `core/runtime/*`, `core/secrets/*`, and `core/observability/*`.
- target app role in v3: app-owned persisted dynamic view packages and instances, rendered in its own frontend and through a chat widget.
- app-store decision: sealed installation-level app under `apps/dynamic-views`, packageable into `/home/ubuntu/Maverick-App-Store`.
- core boundary: no Dynamic Views business logic was added to core; core only mounts the declared app surfaces and widget.

## 2. V2 App Inventory

- source path: `/home/ubuntu/maverick-v2/apps/dynamic_views`
- manifest: `app.manifest.json`, v2 integration manifest with `core_namespaced` storage and underscore content kind.
- frontend: React panels, iframe renderer, CSS tokens, shared UI primitives, and direct v2 API helpers.
- backend: FastAPI routes, Pydantic schemas, Mongo collections, v2 workspace file roots, package source validation, package/instance persistence, and chat render payload creation.
- MCP: represented through v2 app tool wiring, not a standalone v3 JSON entrypoint.
- CLI: not present in v2.
- skills: `backend/codex_skills/dynamic-views/SKILL.md`.
- lifecycle hooks: not present as v3 executable hooks.
- storage/data: Mongo collections plus generated package asset files.
- secrets/env: none required.
- tests: frontend frame/primitives tests only.
- external dependencies: FastAPI, Pydantic, PyMongo, React Query, v2 core contracts and workspace APIs.
- hardcoded paths/services: v2 `app.core.mongo`, `app.core.paths`, `app.core.workspace_cells`, `app.core.workspaces`, and compile-time chat widget imports.

## 3. Target V3 Contract

- app id: `dynamic-views`
- version: `0.1.0`
- distribution mode: `sealed`
- source access: `none`
- declared surfaces: frontend, backend, MCP, CLI, skill, install/migrate/health hooks, and chat widget.
- frontend mount: `frontend/dist`
- backend entrypoint: `backend/app_backend.py`
- MCP entrypoint: `mcp/server.py`
- CLI entrypoint: `cli/app_cli.py`
- skill assets: `skills/dynamic-views/SKILL.md`
- storage roots: `data/dynamic-views/state.json` and `data/dynamic-views/assets/`
- data schema version: `1`
- lifecycle hooks: install, migrate, health check.
- export/import: declared unsupported for first port, with storage shape transparent for future support.
- rollback: bundle/data rollback unsupported.
- widget content kind: `dynamic.view.instance`, because v3 contract validation requires stable dotted kinds.

## 4. File-By-File Port Map

| v2 path | v3 target | category | action | reason |
| --- | --- | --- | --- | --- |
| `README.md` | `docs/porting/dynamic_views_app_porting_plan.md` | `port-as-reference` | Capture purpose in v3 docs and contract. | V2 README is too small to carry as app docs. |
| `__init__.py` | none | `do-not-port` | Omit. | V3 app entrypoints are explicit scripts, not import packages. |
| `__pycache__/` | none | `build-artifact` | Omit. | Generated cache. |
| `app.manifest.json` | `apps/dynamic-views/app_contract.json` | `rewrite-for-v3` | Replace with v3 contract. | V2 manifest shape, permissions, mutability, and storage model do not match v3. |
| `app/primitives.tsx` | `frontend/src/main.tsx`, `frontend/src/styles/main.css` | `port-as-reference` | Recreate minimal local controls. | V3 app uses standalone dark design. |
| `backend/README.md` | this plan | `port-as-reference` | Capture backend responsibilities. | V3 backend is JSON entrypoint based. |
| `backend/__init__.py` | none | `do-not-port` | Omit. | No package import contract required. |
| `backend/mount.py` | none | `rewrite-for-v3` | Omit FastAPI mount. | Core mounts app backend entrypoint generically. |
| `backend/routes.py` | `backend/service.py`, `backend/app_backend.py` | `rewrite-for-v3` | Implement action-based JSON API. | V3 does not preserve v2 HTTP routes in app backend. |
| `backend/schemas.py` | `frontend/src/types.ts`, backend validation logic | `rewrite-for-v3` | Use explicit stdlib dict validation. | Avoid Pydantic dependency and v2 field aliases in backend. |
| `backend/security.py` | `backend/security.py` | `port-nearly-as-is` | Keep validation policy with v3 error type. | Source safety rules are app-owned and architecture-neutral. |
| `backend/service.py` | `backend/store.py`, `backend/service.py` | `rewrite-for-v3` | Replace Mongo/FastAPI/workspace-cell logic with JSON state under app data root. | V3 app data belongs under `data/dynamic-views`. |
| `backend/codex_skills/dynamic-views/SKILL.md` | `skills/dynamic-views/SKILL.md` | `rewrite-for-v3` | Update tool names and dotted content kind. | Skill must describe v3 MCP surface. |
| `chat/dynamic-view-widget.tsx` | `frontend/src/widgets/dynamic-view/main.tsx` | `rewrite-for-v3` | Convert to registry-mounted iframe widget. | Chat must not import app source at compile time. |
| `frontend/dynamic-view-frame.tsx` | `frontend/src/dynamicViewFrame.tsx` | `port-nearly-as-is` | Keep iframe srcdoc, resize, and sandbox semantics. | Renderer behavior is app-owned and valid in v3. |
| `frontend/dynamic-views-panel.tsx` | `frontend/src/main.tsx` | `rewrite-for-v3` | Rebuild as standalone app UI without React Query. | V3 frontend calls mounted app backend directly. |
| `frontend/styles/*.css` | `frontend/src/styles/main.css`, widget CSS | `port-as-reference` | Recreate dark theme consistent with v3 apps. | V2 visual tokens are not the current v3 shell theme. |
| `lib/api.ts` | `frontend/src/api.ts` | `rewrite-for-v3` | Use `/api/apps/dynamic-views/backend`. | V2 API routes are not preserved. |
| `lib/api-core.ts` | `frontend/src/api.ts` | `rewrite-for-v3` | Remove workspace localStorage header. | Core session owns active workspace. |
| `lib/workspace-session.ts` | none | `do-not-port` | Omit. | V3 active workspace is core session state. |
| `tests/*.test.ts` | `tests/test_dynamic_views_app.py` | `test-or-fixture` | Replace with contract/backend/mount/MCP/CLI tests. | V3 verification focuses on app contract and platform mounting. |
| `ui.tsx` | `frontend/src/main.tsx`, CSS | `port-as-reference` | Rebuild only needed controls. | Avoid shared v2 UI dependency. |

## 5. Core Gaps

No generic core gap blocks the port.

The only product mismatch is the v2 content kind `dynamic_view_instance`. V3 contract validation requires dotted content kinds, so the port intentionally emits and declares `dynamic.view.instance`.

## 6. Implementation Phases

1. Add v3 contract and app skeleton.
2. Implement app-owned JSON persistence, security validation, and action service.
3. Implement backend, MCP, CLI, install, migrate, and health entrypoints.
4. Implement frontend library/editor/preview.
5. Implement chat widget frontend with signed widget context.
6. Build production frontend and widget artifacts.
7. Add tests for contract, storage, source safety, platform mount, widget registry, MCP, and CLI.
8. Package into Maverick App Store and restart hosted services.

## 7. Verification

- contract parser: `tests.test_dynamic_views_app`
- app build: `npm run build` in `apps/dynamic-views`
- app tests: `python3 -m unittest tests.test_dynamic_views_app`
- registry tests: `python3 -m unittest tests.test_phase13_widgets`
- app integration tests: `python3 -m unittest tests.test_dynamic_views_app tests.test_phase13_widgets tests.test_gallery_app tests.test_gallery_widget`
- compile/import checks: `python3 -m compileall apps/dynamic-views tests/test_dynamic_views_app.py` and `python3 scripts/check_unused_imports.py`
- live route smoke: `/apps/dynamic-views/` and `/api/apps/dynamic-views/backend`
- app-store packaging: `/home/ubuntu/Maverick-App-Store/scripts/package_app.sh`
- catalog validation: `/home/ubuntu/Maverick-App-Store/scripts/validate_catalog.py`

## 8. Open Questions

None blocking.
