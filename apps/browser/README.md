# Browser

Browser is the Maverick Browser Lab app for governed read-only web inspection
and Maverick development UI inspection.

The P0 source is an installation-level sealed app under `apps/browser`. It is
not a workspace-local app and it does not include the later Chrome Companion
extension.

## Surfaces

- Frontend: workspace-launchable Browser Lab console with URL preflight,
  session status, screenshot, snapshot, console, and network panes.
- Backend: thin JSON controller for policy preflight, status, audit, and broker
  handoff.
- MCP: declared P0 Browser Lab tools for sessions, navigation, snapshots,
  screenshots, console logs, network logs, tabs, waits, and Maverick dev
  inspector actions.
- CLI: `browser` command for agent/operator status and policy preflight.
- Hooks: install, migrate, and health check hooks create and validate the app
  data root.

## Storage

Browser app-owned workspace data lives under:

```text
workspaces/<workspace_id>/data/browser/state.json
```

The P0 state file stores schema version, broker status, lightweight session
metadata, and bounded audit records. Screenshots, downloads, traces, and other
artifacts are not persisted automatically. Later implementation steps must save
artifacts through Storage only after an explicit user or agent action.

## SDK Flow

Browser is an installation-level sealed app, so it is not generated through the
workspace-local SDK create flow. Validate and inspect it through the generic
Maverick app surfaces:

```bash
maverick app browser frontend build --json
maverick app browser mcp list --json
maverick app browser cli list --json
python3 -m unittest apps/browser/tests/test_browser_app.py
```

If the app has not been registered/enabled in the current workspace yet, run the
generic built-in app bootstrap or app-hosting registration flow for
installation-level apps before using the scoped `maverick app browser ...`
commands.

## Contract Notes

Browser is declared as `sealed` with `source_access: none` because it controls a
privileged browser capability. It is `full-access` only in P0 because the
initial Playwright broker and Maverick development inspector are operator/dev
surfaces.

The app contract intentionally declares no app secret permissions and no broad
network permission. Browser navigation is governed by the core browser egress
policy, including DNS/redirect checks and explicit admin dev target exceptions.

The current Passo 3 implementation is fail-closed: policy preflight works, but
browser execution actions return `broker_unavailable` until the Playwright
broker is implemented. This prevents a scaffold from becoming an ungoverned web
egress path.

Intentional P0 omissions:

- no Chrome Companion provider or extension
- no persistent browser profiles or stored login state
- no file upload
- no automatic download persistence
- no arbitrary Playwright code execution
- no page JavaScript evaluation
- no reference entities, widgets, skills, export, or import
