# Design Studio

Design Studio is a Maverick app for bringing OpenDesign-style UI design workflows into a sandbox-first workspace.

It owns:

- a workspace frontend at `frontend/dist`
- a JSON backend at `backend/app_backend.py`
- CLI and MCP surfaces for project state, Storage import, and Storage export
- lifecycle hooks for app data setup and health checks
- a governed HTTP sidecar declaration under `services.http_sidecars`
- app data under `workspaces/<workspace_id>/data/design-studio/`

## OpenDesign Integration

The app contract is shaped for upstream `nexu-io/open-design` tag `open-design-v0.10.1`, commit `eb245799adf07e7727ad5f970485d809bad5780e`.

Design Studio now starts `service/opendesign_launcher.py` as the declared sidecar command. The launcher looks for a curated OpenDesign bundle under `service/vendor/open-design/`, validates the sandbox runtime environment, writes only redaction-safe launcher status under `data/design-studio/opendesign/launcher-status.json`, and then starts the OpenDesign daemon through its built `apps/daemon/dist/cli.js`.

The packaging recipe is declared in `service/opendesign_bundle.json` and implemented by `service/package_opendesign.py`. It copies only the pinned daemon/web/runtime packages and bundled design assets needed for the sandbox sidecar, then runs the recursive pnpm build so OpenDesign workspace packages have runtime `dist/` output; desktop, Electron-packaged, deploy, e2e, marketplace, and host-tool trees stay out of the Maverick bundle. Runtime sidecar startup does not build OpenDesign on demand.

Fresh checkouts may not include the materialized Node bundle. The declared app runtime sets `MAVERICK_OPENDESIGN_ALLOW_FALLBACK=0`, so the sidecar fails closed instead of pretending the real daemon is available. Developers may set `MAVERICK_OPENDESIGN_ALLOW_FALLBACK=1` only for diagnostics and focused tests. That fallback is no longer the declared primary sidecar and should not be treated as the production OpenDesign daemon.

The upstream tag was inspected during implementation. A full shallow checkout at the pinned commit includes web, daemon, desktop, deploy, Helm/chart, design-system, skill, and plugin trees. The daemon also depends on host-adjacent packages such as `node-pty`. Vendoring the full repository directly would mix sandbox-safe surfaces with full-access surfaces the Maverick contract must keep blocked. The curated bundle keeps the upstream pin while narrowing what is copied and what the proxy exposes.

The production daemon replacement must preserve these boundaries:

- bind only to loopback
- use `OD_DATA_DIR` below the app data root
- use `OD_MEDIA_CONFIG_DIR` below the app data root
- receive only the technical `OD_API_TOKEN`
- run with `OD_SANDBOX_MODE=1`
- keep provider keys in Maverick/Vault-owned flows
- keep host folder import, terminal, and pty routes blocked in sandbox mode

## Storage Boundary

Design sources enter through Storage workspace-relative paths:

```text
storage/uploaded/<file>
storage/generated/<file>
```

Exports are written under:

```text
storage/generated/design-studio/<project-id>/<export-id>/
```

The app never accepts host absolute paths in sandbox mode. Hosted imports are
issued through the `storage-read` dependency backend request, then materialized
under `data/design-studio/imports/` only after Storage returns bounded file
content. Export writes are issued through Design Studio's `storage-write`
dependency backend request so the Storage app owns the generated file write path
and inventory update. Design Studio records imports and exports as pending first,
then marks them imported/exported or failed from the Storage callback result.
Direct local CLI/MCP test entrypoints may use the mounted workspace Storage roots
as a development fallback, but hosted backend calls use the declared Storage
dependencies.

## SDK Flow

Design Studio is a first-party source-available platform app under `apps/design-studio`, not a workspace-local SDK-generated app. It still follows the same contract validation and hosted lifecycle expectations:

```bash
python3 -m unittest apps/design-studio/tests/test_design_studio_app.py
maverick app design-studio frontend build --json
maverick app design-studio cli list --json
maverick app design-studio mcp list --json
```

The app is installed into workspaces through the generic built-in app source registration and workspace binding flow. It must not be registered through app-specific bootstrap shortcuts.

## Contract Notes

The contract declares frontend, backend, CLI, MCP, lifecycle hooks, a bundled skill, referenceable `design_project` entities, standard view-state actions, Storage dependencies, and one app-owned HTTP sidecar.

The sidecar is sandbox-compatible because it binds to loopback, receives a generated technical token, writes runtime data under the app data root, writes logs under `logs/apps/design-studio/`, runs OpenDesign in sandbox mode, and exposes only routes allowed by `route_policy`.

The core sidecar proxy uses the ASGI streaming path for Design Studio routes. Request bodies are forwarded to the sidecar as chunks instead of through the JSON app-backend body limit, responses are streamed back to the browser, and SSE responses are preserved without exposing the generated `OD_API_TOKEN` to the client.

Routes declared as `handled_by_core` are routed to the Design Studio backend with the `sidecar_core_handler` surface instead of reaching the OpenDesign sidecar. The implemented sandbox handlers cover:

- `GET /api/media/config`, returning sanitized Maverick-managed provider config without keys
- `POST /api/import/storage`, importing through the selected `storage-read` dependency backend
- `POST /api/export/storage`, exporting through the selected `storage-write` dependency backend
- `/api/provider/*`, failing closed with `provider_proxy_not_configured` until real provider adapters are mapped

The app intentionally does not declare provider secrets yet. Provider keys stay outside the sidecar and are not written into `OD_MEDIA_CONFIG_DIR`; the current provider route handler proves the governed interception path and secret non-persistence, but it does not call external model providers yet.

## Verification

Useful checks:

```bash
python3 -m unittest apps/design-studio/tests/test_design_studio_app.py
maverick app design-studio frontend build --json
maverick app design-studio mcp list --json
maverick app design-studio cli list --json
```

Current intentional omissions:

- the curated OpenDesign bundle is materialized from the pinned upstream checkout by `service/package_opendesign.py`; dependency installs stay out of source control
- provider proxy routes are intercepted by core/app handlers, but real provider adapters are not implemented yet
- full-access terminal, Local CLI, and host-folder import are not part of the sandbox MVP
