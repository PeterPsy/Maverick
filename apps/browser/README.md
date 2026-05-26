# Browser

Browser is the Maverick Browser Lab app for governed read-only web inspection
and Maverick development UI inspection.

The P0 source is an installation-level sealed app under `apps/browser`. It is
not a workspace-local app and it does not include the later Chrome Companion
extension.

## Surfaces

- Frontend: workspace-launchable Browser Lab console with URL preflight,
  session status, screenshot, snapshot, console, and network panes.
- Backend: JSON controller for policy preflight, session metadata, tabs,
  bounded console/network observations, audit, and broker handoff.
- Broker: local development sidecar in `broker/` that connects to a Dockerized
  Playwright `run-server` through the Playwright protocol.
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
metadata, redacted tab URLs, bounded console/network observations, and bounded
audit records. Screenshots, downloads, traces, and other artifacts are not
persisted automatically. Storage persistence is allowed only through an explicit
future handoff action.

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

## P0 Playwright Broker

The P0 broker is a dev sidecar, not a normal app backend subprocess. Start the
Playwright server first:

```bash
cd apps/browser
npm run broker:docker
```

Then start the Browser broker:

```bash
cd apps/browser
npm ci --ignore-scripts
export MAVERICK_BROWSER_BROKER_TOKEN="$(openssl rand -hex 32)"
MAVERICK_BROWSER_PLAYWRIGHT_WS_ENDPOINT=ws://127.0.0.1:3100/ \
MAVERICK_BROWSER_PROXY_BIND_HOST=0.0.0.0 \
MAVERICK_BROWSER_PROXY_SERVER=http://hostmachine:9324 \
npm run broker
```

The `playwright` package is pinned in `package.json`; the Docker helper uses
the matching official image tag and `playwright run-server`. The broker refuses
to connect when `MAVERICK_BROWSER_PLAYWRIGHT_VERSION` does not match the local
client version.

The controller calls the broker at `MAVERICK_BROWSER_BROKER_URL`, defaulting to
`http://127.0.0.1:9323`, and every broker request must include the shared
`MAVERICK_BROWSER_BROKER_TOKEN`. Browser sessions are created with isolated
non-persistent contexts, `acceptDownloads: false`, no storage state, no user
data directory, no file upload support, and no automatic artifact persistence.
The controller records session metadata only after successful broker actions,
requires a known session before tab/snapshot/screenshot/log/wait/interactive
actions, derives trusted policy context from the platform caller, and audits
navigate, snapshot, screenshot, click, type, key press, and wait attempts.
The broker also enforces Browser P0 egress policy on Playwright requests so
redirects and subresources cannot bypass the backend preflight path. It starts a
credentialed proxy for browser contexts, advertised as
`MAVERICK_BROWSER_PROXY_SERVER` or `http://127.0.0.1:9324` by default, so DNS
resolution and outbound connects happen in the broker after policy approval.
Dockerized browsers must opt into a wider proxy bind and advertise
`http://hostmachine:9324` explicitly.
Screenshots are returned inline to the caller; a later controller step must hand
them to Storage only on explicit save.

Intentional P0 omissions:

- no Chrome Companion provider or extension
- no persistent browser profiles or stored login state
- no file upload
- no automatic download persistence
- no arbitrary Playwright code execution
- no page JavaScript evaluation
- no reference entities, widgets, skills, export, or import
