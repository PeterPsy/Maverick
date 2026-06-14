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

This first Maverick implementation ships a small OpenDesign-compatible sidecar stub at `service/opendesign_stub.py`. It proves the Maverick sidecar lifecycle, loopback binding, technical token injection, route policy, and frontend proxy path without vendoring the full upstream repository into this change.

The upstream tag was inspected during implementation. A shallow checkout at the pinned commit is about 268 MB and includes web, daemon, desktop, deploy, Helm/chart, design-system, skill, and plugin trees. The daemon also depends on host-adjacent packages such as `node-pty`. Vendoring it directly into this app would therefore mix sandbox-safe surfaces with full-access surfaces the Maverick contract must keep blocked. The production replacement should be a curated sidecar bundle generated from that pinned upstream tag, with only the sandbox-compatible web/daemon routes exposed through the `route_policy` already declared here.

The production daemon replacement must preserve these boundaries:

- bind only to loopback
- use `OD_DATA_DIR` below the app data root
- use `OD_MEDIA_CONFIG_DIR` below the app data root
- receive only the technical `OD_API_TOKEN`
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

The app never accepts host absolute paths in sandbox mode. Export writes are
issued through Design Studio's `storage-write` dependency backend request so the
Storage app owns the generated file write path and inventory update. Design
Studio records the export as pending first, then marks it exported or failed from
the Storage callback result.

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

The sidecar is sandbox-compatible because it binds to loopback, receives a generated technical token, writes runtime data under the app data root, writes logs under `logs/apps/design-studio/`, and exposes only routes allowed by `route_policy`.

The core sidecar proxy uses the ASGI streaming path for Design Studio routes. Request bodies are forwarded to the sidecar as chunks instead of through the JSON app-backend body limit, responses are streamed back to the browser, and SSE responses are preserved without exposing the generated `OD_API_TOKEN` to the client.

The app intentionally does not declare provider secrets yet. Provider keys stay outside the sidecar until Maverick's provider proxy route handlers are implemented.

## Verification

Useful checks:

```bash
python3 -m unittest apps/design-studio/tests/test_design_studio_app.py
maverick app design-studio frontend build --json
maverick app design-studio mcp list --json
maverick app design-studio cli list --json
```

Current intentional omissions:

- the full OpenDesign daemon is not vendored yet
- provider proxy routes are declared as `handled_by_core` but not implemented as provider adapters yet
- full-access terminal, Local CLI, and host-folder import are not part of the sandbox MVP
