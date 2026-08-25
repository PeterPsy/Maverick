# Browser

Browser is the Maverick Browser Lab app for governed read-only web inspection
and Maverick development UI inspection.

The P0 source is an installation-level sealed app under `apps/browser`. It is
not a workspace-local app and it does not include the later Chrome Companion
extension.

## Surfaces

- Backend: JSON controller for policy preflight, session metadata, tabs,
  bounded console/network observations, audit, and broker handoff.
- Broker: local development sidecar in `broker/` that connects to a Dockerized
  Playwright `run-server` through the Playwright protocol.
- MCP: declared P0 Browser Lab tools for sessions, navigation, snapshots,
  screenshots, console logs, network logs, tabs, waits, and Maverick dev
  inspector actions.
- CLI: `browser` command for agent/operator status, policy preflight,
  acceptance smoke, and Maverick local-dev smoke.
- Skill: bundled `browser-ops` guidance for full-access agents using the
  governed Browser CLI/MCP surfaces.
- Hooks: install, migrate, and health check hooks create and validate the app
  data root.

Browser is backend-only in P0. It does not declare a workspace frontend,
mounted view, widgets, or user-launchable shell route; agents and operators use
the MCP and CLI surfaces.

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
surfaces. The derived CLI and MCP invocation policy is therefore
`requires_full_access: true` and `sandbox_agent_allowed: false`. Keep sandbox
agent access closed for P0; a later read-only sandbox mode needs a separate
policy review instead of a descriptor-only change.

The app contract intentionally declares no app secret permissions and no broad
network permission. Browser navigation is governed by the core browser egress
policy, including DNS/redirect checks and explicit admin dev target exceptions.
The static policy data for allowed schemes, restricted hosts/ranges, metadata
hosts, embedded IPv4 extraction, and admin dev targets lives in
`core/egress/policy_manifest.json`; both the Python core policy and the
Playwright broker consume that manifest to avoid drift.
The contract also intentionally declares `presentation.frontend_role: "none"`
and `entrypoints.frontend: null`, so Browser is discoverable as an agent-facing
capability but is not launchable from the workspace app rail.

Browser also declares `capabilities.skills: ["browser-ops"]` and
`entrypoints.skills_root: "skills"` so the Skills app can seed workspace-owned
runtime guidance for agents without making the Browser app user-launchable.

## Agent Usage

Full-access agents should use the bundled `browser-ops` skill before operating
Browser. The short version is:

```bash
maverick app browser cli inspect browser --json
maverick app browser mcp list --json
maverick app browser mcp inspect browser_session_create --json
```

Use the CLI for status, audit, preflight, and smoke checks. Use MCP for browser
sessions: create a read-only session, navigate, collect snapshot/screenshot/logs
as needed, then close the session. Use `maverick_dev_inspector` and the
interactive tools only for admin-approved Maverick development UI targets.
For local Maverick app URLs, do not use `127.0.0.1` directly. Use the exact
allowlisted `hostmachine:<port>` target with `mode=maverick_dev_inspector` from
an admin context.

## P0 Playwright Broker

The P0 broker is a dev sidecar, not a normal app backend subprocess. Start the
Playwright server first. The Docker path is preferred for isolation when Docker
is available:

```bash
cd apps/browser
npm run broker:docker
```

When Docker is not available on the host, use the local helper instead. It runs
the pinned Playwright package from `apps/browser/node_modules` and keeps the
same default WebSocket endpoint:

```bash
cd apps/browser
npm ci --ignore-scripts
npm run broker:local
```

Then start the Browser broker:

```bash
cd apps/browser
npm ci --ignore-scripts
MAVERICK_BROWSER_PLAYWRIGHT_WS_ENDPOINT=ws://127.0.0.1:3100/ \
MAVERICK_BROWSER_PROXY_BIND_HOST=0.0.0.0 \
MAVERICK_BROWSER_PROXY_SERVER=http://hostmachine:9324 \
npm run broker
```

If `MAVERICK_BROWSER_BROKER_TOKEN` is not set, the broker creates or reuses a
local token file at `runtime/browser/playwright-broker-token` with owner-only
permissions. Browser backend, CLI, MCP, and hook entrypoints read that same file
through `MAVERICK_BROWSER_BROKER_TOKEN_FILE` or the default path, so runtime
agents do not need the token copied into their environment. Set
`MAVERICK_BROWSER_BROKER_TOKEN` explicitly when an operator-managed supervisor
delivers the shared token another way.

The `playwright` package is pinned in `package.json`; the Docker helper uses
the matching official image tag and `playwright run-server`, while the local
helper refuses to run when the installed package version differs from the pin.
The broker refuses to connect when `MAVERICK_BROWSER_PLAYWRIGHT_VERSION` does
not match the local client version.

The controller calls the broker at `MAVERICK_BROWSER_BROKER_URL`, defaulting to
`http://127.0.0.1:9323`, and every broker request must include the shared
broker token from `MAVERICK_BROWSER_BROKER_TOKEN` or the local token file.
Browser sessions are created with isolated non-persistent contexts,
`acceptDownloads: false`, no storage state, no user data directory, no file
upload support, and no automatic artifact persistence. Every context also sets
Playwright `reducedMotion: "reduce"`, so pages that honor reduced-motion media
queries use their static rendering path during automation.
Session creation accepts bounded `viewport_width`, `viewport_height`, and
`mobile` fields. A mobile smoke without explicit dimensions uses `390x844`.
The controller records session metadata only after successful broker actions,
requires a known session before tab/snapshot/screenshot/log/wait/interactive
actions, derives trusted policy context from the platform caller, and audits
navigate, snapshot, screenshot, click, type, key press, and wait attempts.
The broker serializes actions per Browser session so observation requests do not
race an in-flight navigation on the same Playwright page context.
An authorized broker action updates that session's last-activity timestamp at
the start and end of the action; background page requests do not keep abandoned
sessions alive. A periodic reaper closes a session after 15 minutes idle or four
hours total by default. Closure is serialized behind in-flight work and removes
the Playwright context, its credentialed proxy policy, and its action queue.
Operators can override the defaults with
`MAVERICK_BROWSER_SESSION_IDLE_TTL_MS`,
`MAVERICK_BROWSER_SESSION_HARD_TTL_MS`, and
`MAVERICK_BROWSER_SESSION_REAPER_INTERVAL_MS` (30 seconds by default). Broker
health reports the configured lifecycle values and current session, proxy-policy,
and action-queue counts.
The broker also enforces Browser P0 egress policy on Playwright requests so
redirects and subresources cannot bypass the backend preflight path. It starts a
credentialed proxy for browser contexts, advertised as
`MAVERICK_BROWSER_PROXY_SERVER` or `http://127.0.0.1:9324` by default, so DNS
resolution and outbound connects happen in the broker after policy approval.
Dockerized browsers must opt into a wider proxy bind and advertise
`http://hostmachine:9324` explicitly.
Screenshots are returned inline to the caller; a later controller step must hand
them to Storage only on explicit save.

The app health hook is an active P0 readiness check. It calls the broker with
`/health?check=connect`, which requires the shared token and a reachable
Playwright `run-server`; a passive broker status response is not enough for the
app to report healthy.

After both sidecars are running, verify the real P0 path through the official
Browser CLI:

```bash
maverick app browser cli run browser --json --action acceptance.smoke
```

This creates an isolated session, navigates to
`MAVERICK_BROWSER_ACCEPTANCE_URL` or `https://example.com/`, collects a
snapshot, screenshot, console messages, network requests, and tabs, then closes
the session. The smoke output summarizes the screenshot size instead of
persisting or printing the base64 artifact.

For local Maverick app development, use the dedicated dev smoke so agents do
not invent loopback URLs:

```bash
maverick app browser cli run browser --json --action dev.smoke --app-id fitness-coach --port 8014 --mobile true
```

`dev.smoke` builds `http://hostmachine:<port>/app/<app_id>/<path>`, forces
`mode=maverick_dev_inspector`, requires admin authority, and only accepts
ports declared as admin dev targets. The built-in allowlist includes
`hostmachine:8000` and `hostmachine:8014`. If preflight sees
`blocked_restricted_ip` for `127.0.0.1`, use the suggested
`hostmachine:<allowlisted-port>` URL from the policy guidance instead of
opening loopback broadly.

Intentional P0 omissions:

- no Chrome Companion provider or extension
- no workspace-launchable frontend or mounted Browser Lab view
- no persistent browser profiles or stored login state
- no file upload
- no automatic download persistence
- no arbitrary Playwright code execution
- no page JavaScript evaluation
- no reference entities, widgets, export, or import
