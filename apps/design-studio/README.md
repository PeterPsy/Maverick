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

Design Studio starts `service/opendesign_launcher.py` as the declared sidecar command. The launcher looks for a curated OpenDesign bundle under `service/vendor/open-design/`, validates the sandbox runtime environment, writes only redaction-safe launcher status under `data/design-studio/opendesign/launcher-status.json`, and then starts the OpenDesign daemon through its built `apps/daemon/dist/cli.js`. A successful launch records `mode: curated-dist`.

The packaging recipe is declared in `service/opendesign_bundle.json` and implemented by `service/package_opendesign.py`. It copies only the pinned daemon/web/runtime packages and bundled design assets needed for the sandbox sidecar, narrows the generated pnpm workspace to the curated app/package set, then runs install and recursive pnpm build so OpenDesign workspace packages have runtime `dist/` output. Desktop, Electron-packaged, deploy, e2e, broad marketplace, and host-tool trees stay out of the Maverick bundle. Runtime sidecar startup does not build OpenDesign on demand.

The source-control policy is generated-artifact mode: commit `service/opendesign_bundle.json`, `service/package_opendesign.py`, docs, and smoke tests; do not commit `service/vendor/open-design/` or any `node_modules`. The currently materialized local bundle was built from `nexu-io/open-design` tag `open-design-v0.10.1`, commit `eb245799adf07e7727ad5f970485d809bad5780e`, and contains `apps/daemon/dist/cli.js`, `apps/web/out`, and `packages/*/dist`.

Fresh checkouts will not include the materialized Node bundle. Run packaging before declaring Phase 3 complete:

```bash
git clone --depth 1 --branch open-design-v0.10.1 https://github.com/nexu-io/open-design.git /tmp/maverick-open-design-src
python3 apps/design-studio/service/package_opendesign.py \
  --source /tmp/maverick-open-design-src \
  --force
python3 apps/design-studio/service/smoke_opendesign_sidecar.py
```

The launcher fails closed when the bundle is absent or not built. There is no runtime compatibility fallback.

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

The sidecar is sandbox-compatible because its mandatory generic
`process_policy` starts it under bubblewrap with an allowlisted environment,
read-only app bundle, writable validated app data root, isolated network
namespace, empty outbound list, resource/request limits, and an authenticated
Unix relay. Its loopback listener exists only inside that namespace; core never
publishes or falls back to a host TCP port. `HOME`, provider/runtime secrets,
cookies, Storage, operator paths, and other workspaces are absent. The generated
technical token uses the generic `${service.token}` substitution and is not the
relay capability.

The core sidecar proxy uses the ASGI streaming path for Design Studio routes. Request bodies are forwarded to the sidecar as chunks instead of through the JSON app-backend body limit, responses are streamed back to the browser, and SSE responses are preserved without exposing the generated `OD_API_TOKEN` to the client.

The sidecar also declares the generic isolated `browser_origin` capability.
Core, not Design Studio or OpenDesign, derives the opaque workspace/app/
generation host, issues the short-lived body-only bootstrap ticket, sets the
separate host-only session cookie, and applies the fixed
`self_hosted_web_app` CSP profile. Root-relative OpenDesign requests therefore
remain on the sidecar origin and never fall through to Maverick routes. Neither
Maverick cookies nor the generated `OD_API_TOKEN` cross the browser/upstream
boundary. The mounted frontend adopts this launch protocol in WP9.

The browser route policy is generated from the pinned 0.16.1 method/template
inventory and checked in CI with `service/sync_route_policy.py`. API rules are
exact and segment-aware; unsafe allows name their method, dynamic parameters
consume one segment, and prefix/regex/splat escalation is rejected. Only
GET/HEAD static trees outside `/api` cover `/_next`, assets, artifacts, and
frames. Known terminal/PTY, host-folder, external-open, deploy, connector/OAuth,
plugin install/upload, persistent MCP, telemetry, and other inventoried routes
are blocked explicitly; all other routes are denied by default.

The production confinement suite uses real bubblewrap and validates filesystem,
environment, network, authenticated relay, concurrency and descendant cleanup:

```bash
python3 -W error::ResourceWarning -m unittest \
  tests.integration.app_hosting.test_sidecar_execution \
  tests.integration.app_hosting.test_sidecar_browser_origin
```

Routes declared as `handled_by_core` are routed to the Design Studio backend with the `sidecar_core_handler` surface instead of reaching the OpenDesign sidecar. The implemented sandbox handlers cover:

- `GET /api/media/config`, returning sanitized Maverick-managed provider config without keys
- `POST /api/import/storage`, importing through the selected `storage-read` dependency backend
- `POST /api/export/storage`, exporting through the selected `storage-write` dependency backend
- `POST /api/provider/models`, mapping OpenDesign provider model discovery to the active Maverick workspace provider without forwarding provider routes to the sidecar

The contract declares `permissions.providers.model_proxy: true` with `credential_source: core-vault` and `deliver_secrets_to_app: false`. It does not declare app-scoped provider secret reads. Provider keys stay in Maverick/Vault-owned flows, are not delivered to the browser, Design Studio backend, or OpenDesign sidecar, and are not written into `OD_MEDIA_CONFIG_DIR`. Provider errors are returned in OpenDesign's provider-model response shape (`ok`, `kind`, `latencyMs`, `status`, `detail`) so the bundled UI can handle unavailable provider state without learning raw credentials.

## Verification

Useful checks:

```bash
python3 -m unittest apps/design-studio/tests/test_design_studio_app.py
python3 apps/design-studio/service/sync_route_policy.py
python3 apps/design-studio/service/smoke_opendesign_sidecar.py
maverick app design-studio frontend build --json
maverick app design-studio mcp list --json
maverick app design-studio cli list --json
```

Current intentional omissions:

- the curated OpenDesign bundle is materialized from the pinned upstream checkout by `service/package_opendesign.py`; the generated bundle and dependency installs stay out of source control
- provider proxying is limited to OpenDesign model discovery through Maverick's active workspace provider; generation/chat provider routes remain unavailable in sandbox mode
- full-access terminal, Local CLI, and host-folder import are not part of the sandbox MVP
