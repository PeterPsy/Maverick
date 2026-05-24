# Browser App Integration Report

Date: 2026-05-23

Status: P0 scope locked for implementation.

## Purpose

This report defines how Maverick should integrate browser capabilities for
web reading, agent assistance, and Maverick UI debugging.

The development direction is deliberately staged:

- first, build a Maverick Browser Lab that lets Maverick inspect the web and
  debug Maverick UI through an isolated Playwright/Chromium browser;
- later, add a Maverick Chrome Companion extension that can assist the user in
  their real Chrome profile after explicit consent.

Maverick should not embed arbitrary public web pages directly in app iframes.
The viable first implementation is a Browser app backend/controller plus a
persistent isolated browser broker sidecar, with core-governed egress policy
and a Maverick-safe MCP surface inspired by Playwright MCP.

An app backend can absolutely be the Maverick-facing surface that gives agents
browser capability. The important constraint is lifecycle: the app backend
should control policy, audit, and tool contracts, while a broker sidecar owns
long-lived Playwright/Chromium state.

## Verdict

Build the Browser app, but start with the lowest-risk useful slice:
**Browser Lab read-only web inspection plus Maverick development debugging**.

Accepted direction:

- Use Playwright/Chromium remotely through an isolated broker.
- Expose Browser app backend and MCP tools so Maverick agents can request
  web snapshots, screenshots, console logs, and network observations.
- Allow a read-only web mode first: navigate, snapshot, screenshot, extract,
  console logs, and network logs.
- Allow click/type early only for the Maverick development inspector use case,
  where targets are allowlisted Maverick dev URLs.
- Add Chrome Companion later as a separate high-trust integration for the
  user's real browser profile.

Non-negotiable corrections:

- The architecture is "Browser app + app backend/controller + isolated browser
  broker + core egress policy", not "normal app backend owns Chromium".
- The app should be install-level, sealed, and preferably built-in. It is too
  privileged to treat as an ordinary workspace-local custom app.
- The agent protocol should start from accessibility snapshots and element refs,
  not screenshot coordinates as the primary primitive.
- Read-only web access still needs egress controls. It can trigger SSRF-style
  requests, private-network access, redirects, file fetches, prompt injection,
  and unwanted side effects on external services.
- Persistent browser profiles must be opt-in, scoped, encrypted or
  grant-governed, and disabled by default.
- Arbitrary code evaluation tools must not be exposed to ordinary agents.
- Network egress enforcement is a blocker for broad non-dev web access, not a
  later hardening detail.

## P0 Scope Lock

P0 is now fixed as a Maverick-native Browser Lab app. It is not a Chrome
extension, not a workspace-local custom app, and not a general-purpose browser
automation surface.

Source and distribution:

- App id: `browser`.
- Source location: installation-level `apps/browser/` in the Maverick root.
- Workspace-local source is explicitly out of scope; do not create
  `workspaces/<workspace_id>/apps/browser/` for P0.
- Contract distribution must be:

```json
{
  "distribution": {
    "mode": "sealed",
    "source_access": "none"
  }
}
```

P0 product surface:

- Browser Lab read-only web inspection.
- Maverick development visual inspector.
- Thin Browser app backend/controller for policy, audit, MCP, session
  coordination, and explicit artifact handoff to Storage.
- Isolated Playwright/Chromium broker connection for browser execution.
- Workspace data owned by the app under `data/browser/`.

P0 allowed Browser Lab capabilities:

- create and close isolated sessions
- navigate only after egress policy approval
- capture accessibility snapshots
- capture screenshots without automatic persistence
- read console messages
- read redacted network request metadata
- list tabs
- wait for bounded page states

P0 allowed Maverick dev inspector capabilities:

- all Browser Lab read-only capabilities
- click, type, and key press only when the target URL is an admin-enabled
  Maverick dev allowlist entry
- initial dev allowlist begins with the local hosted Maverick shell at
  `http://hostmachine:8000`; additional ports or hostnames must be explicit
  policy entries, not implicit private-network access

P0 exclusions:

- no Chrome Companion provider or Chrome MV3 extension
- no introspection or control of the user's real browser/PWA session
- no persistent browser profiles
- no stored login state
- no file upload
- no automatic download persistence
- no arbitrary Playwright code execution
- no page JavaScript evaluation exposed to ordinary agents
- no coordinate-based vision actions
- no click/type on arbitrary public web targets

Implementation gate:

- Until the egress policy model is implemented and tested, P0 may expose only
  the Maverick dev inspector against admin-enabled allowlisted Maverick URLs.
- Broad read-only public web inspection remains part of P0, but it is blocked
  behind the egress policy from the next implementation step.

## Two-Level Browser Strategy

Maverick should eventually expose one conceptual browser capability with two
different trust levels.

### Level 1: Maverick Browser Lab

This is the first implementation target. It is a Maverick-controlled isolated
browser using Playwright/Chromium. It serves:

- read-only web observation;
- Maverick UI debugging and visual inspection;
- accessibility snapshots, DOM-derived extraction, screenshots, console logs,
  and network logs;
- bounded agent MCP/CLI tools;
- reproducible automation inside isolated sessions.

This is the correct surface for autonomous agent work.

### Level 2: Maverick Chrome Companion

This is a later Chrome extension installed in the user's real Chrome profile.
It can expose tab metadata, active-tab context, screenshots, DOM/text from
authorized tabs, and eventually user-approved actions in attached tabs.

This is the correct surface for contextual assistance: "help me with the page
I am looking at", "summarize my open tabs", or "use this already logged-in
session, but ask before acting".

The Companion is not equivalent to the Lab. It touches the user's real
cookies, logins, history, open tabs, and personal pages. Its default mode must
be metadata-only or explicit active-tab sharing, not background control of all
tabs.

## Current Maverick Constraints

Maverick already has the right app-hosting shape:

- apps declare frontend, backend, CLI, MCP, widgets, permissions, storage, and
  lifecycle through `app_contract.json`
- mounted frontends are served by the core under `/apps/<mount_app_id>/`
- user-facing app routes are selected by base-shell and rendered in iframes
- app backends and app MCP tools are invoked through core-managed entrypoints
- workspace data belongs under `workspaces/<workspace_id>/data/<app_id>/`

Relevant local source:

- `core/api/platform_host.py` routes mounted apps and app APIs.
- `core/api/app_mounts.py` serves frontend assets and invokes app backend
  entrypoints.
- `apps/base-shell/frontend/src/components/AppFrameHost.tsx` mounts apps in
  sandboxed iframes.
- `apps/base-shell/frontend/src/iframePolicy.ts` currently allows
  `allow-downloads allow-forms allow-popups allow-same-origin allow-scripts`.
- `core/shared/entrypoints.py` runs app entrypoints as JSON stdin/stdout
  subprocesses with timeouts.
- `core/mcp/app_tools.py` mounts app MCP tools through the same subprocess
  pattern and defaults to a 30 second app MCP timeout.

These constraints mean a Browser app can fit into the app model, but Chromium
itself must not live inside the normal request/response app backend or app MCP
entrypoint.

## Why Direct Web Iframes Are Rejected

Directly embedding public web pages inside Maverick app iframes fails both
product and security requirements:

- many sites intentionally block framing through `X-Frame-Options`
- modern sites may use CSP `frame-ancestors` to restrict allowed embedding
  parents
- even when a page renders, Maverick cannot reliably inspect or automate it from
  the host page because browser same-origin boundaries apply
- embedding arbitrary web in a same-origin Maverick iframe surface would expand
  a currently documented frontend isolation weakness

External references:

- MDN documents `X-Frame-Options` as controlling whether a browser may render a
  page in a frame or iframe:
  https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/X-Frame-Options
- MDN documents CSP `frame-ancestors` as the directive that restricts which
  parents may embed a page:
  https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/frame-ancestors

Therefore the Browser app frontend should render Maverick-owned UI only: URL
bar, tabs, status, screenshots or streamed frames, accessibility snapshots,
network/console logs, and controls. The actual web page should run in a remote
browser process.

## Recommended Runtime Shape

Use a Browser Context Broker model with provider-specific capabilities.

Initial provider:

- `playwright_lab`: isolated Maverick-controlled Playwright/Chromium sessions.

Later provider:

- `chrome_companion`: user Chrome tabs exposed through an installed extension.

The public tools can look coherent across providers, but every context must
carry explicit capability metadata. A Playwright Lab page, a read-only Chrome
tab, an attached Chrome tab, and a debugger-attached Chrome tab are different
security objects.

Common tool names may include:

- `browser.list_contexts`
- `browser.list_tabs`
- `browser.snapshot`
- `browser.screenshot`
- `browser.extract`
- `browser.console_messages`
- `browser.network_requests`
- `browser.navigate`
- `browser.click`
- `browser.type`
- `browser.attach_tab`
- `browser.detach_tab`

Each tool must consult provider capabilities and policy before executing.

Use three separate layers for the first Browser Lab implementation.

### 1. Frontend Maverick app

Responsibilities:

- browser UI
- tabs and session picker
- URL input and navigation state
- live visual surface through screenshot stream, video stream, or noVNC-like
  viewer
- accessibility snapshot viewer
- network and console log panes
- explicit save controls for screenshot, trace, video, PDF, and downloads
- human approval UI for sensitive actions

The frontend must not load arbitrary external pages in its own iframe.

### 2. Thin app backend/controller

Responsibilities:

- authenticate user and workspace context through Maverick
- expose Browser app backend operations and MCP tools
- enforce Browser app policy before forwarding commands
- map browser artifacts into workspace Storage
- publish app events for UI refresh
- write audit records for every navigation and interaction
- coordinate session lifecycle with the browser broker
- expose only bounded app backend operations

The backend is the correct Maverick-facing control plane. It should not be the
long-lived browser process owner.

### 3. Persistent browser broker sidecar

Responsibilities:

- run or connect to Playwright/Chromium
- own long-lived browser sessions and contexts
- enforce per-session cleanup
- provide cancellation and long-operation lifecycle
- stream page state back to the app
- implement network namespace, allow/deny policy, and download quarantine
- expose a small internal API to the Browser app controller

The broker may start as a local dev service but must evolve into a separately
supervised sidecar or container pool.

## Why The Current App Backend Is Not Enough

An app backend is the right place to expose browser capability to Maverick. It
is not the right lifecycle boundary for Chromium itself.

Maverick app backends are currently deterministic JSON entrypoint subprocesses.
`core/shared/entrypoints.py` starts a Python process, writes JSON stdin, reads
JSON stdout, and terminates the operation under a timeout. That is good for
ordinary backend actions. It is the wrong lifecycle for a browser.

Browser sessions require:

- persistent Chromium process state
- multiple tabs and contexts
- long navigation waits
- interactive cancellation
- streamed screenshots or events
- downloads and trace/video finalization
- cleanup independent of any single HTTP request

A throwaway prototype may launch Playwright inside one backend call, but the
development-guiding architecture should not. It would be slow, hard to cancel,
hard to audit continuously, and fragile around timeouts.

Likewise, app MCP tools in `core/mcp/app_tools.py` invoke the app MCP entrypoint
through the same subprocess mechanism. The current default timeout is 30
seconds. Browser actions such as login, slow navigation, `wait_for`, trace
collection, PDF export, or network-idle waits can exceed that. A Browser app can
and should declare MCP tools, but those tools should delegate to the persistent
broker and use explicit browser-session timeouts, cancellation, and status
records.

## Playwright MCP As Reference, Not Drop-In

Playwright now ships an official MCP server with a broad browser automation
surface. It includes core tools such as navigation, accessibility snapshots,
click, type, screenshot, wait, dialogs, file upload, console, network, tabs, and
close; optional capabilities add network mocking, storage state, testing
assertions, vision-mode mouse coordinates, PDF, tracing, video, and config.

Reference:

- https://playwright.dev/mcp/capabilities

Maverick should not expose that full toolset directly. It should use it as a
design reference and expose a governed subset.

Do expose early:

- `browser_session_create`
- `browser_session_close`
- `browser_navigate`
- `browser_snapshot`
- `browser_click`
- `browser_type`
- `browser_press_key`
- `browser_wait_for`
- `browser_take_screenshot`
- `browser_console_messages`
- `browser_network_requests`
- `browser_tabs`

Defer or restrict:

- file upload
- PDF export
- trace/video recording
- storage state save/restore
- route mocking
- coordinate-based vision tools
- cookie/localStorage mutation

Do not expose to ordinary agents:

- arbitrary Playwright code execution
- page JavaScript evaluation
- unrestricted storage-state import/export
- unrestricted local file upload

Playwright MCP lists `browser_run_code` and `browser_evaluate` in its core
capabilities. Those are useful for trusted test engineers and unsafe as default
workspace agent tools.

## Snapshot-First Agent Protocol

The primary agent protocol should be accessibility snapshots with refs, not
screenshot coordinates.

Playwright MCP uses accessibility snapshots and gives interactive elements refs
that can be used by click/type tools. Its docs also explain that refs are valid
until the page changes and should be refreshed after navigation or DOM updates.

Reference:

- https://playwright.dev/mcp/snapshots

Maverick should follow that model:

- every action returns a fresh snapshot when possible
- refs are session-local and snapshot-local
- screenshot is supplemental for visual context
- coordinate-based actions are disabled in P0 and enabled only for explicit
  vision workflows

This makes agent interaction cheaper, more deterministic, and easier to audit
than raw image clicking.

## Browser Profile Policy

Playwright MCP persists login state and cookies by default in its MCP profile
mode. It also supports an isolated mode with no saved state.

Reference:

- https://playwright.dev/mcp/configuration/user-profile

Maverick should invert the default:

- isolated sessions by default
- no automatic cookie or localStorage persistence
- no cross-workspace profile reuse
- no cross-user profile reuse
- persistent profiles only after explicit opt-in
- saved state stored as a governed workspace artifact or secret-adjacent record,
  not as an unmanaged host cache
- profile restore gated by policy and audit

If persistent auth state is implemented, it must be treated like sensitive
browser credential material. It should not be written into ordinary generated
files, logs, chat transcripts, or browser bundles.

## Deployment Options

### P0 development option

Use the official Playwright Docker image and `browserType.connect()` to a
Playwright server.

Playwright documents running a remote server in Docker with `run-server` and
connecting via `browserType.connect()`. The docs also call out that client and
server Playwright versions should match.

Reference:

- https://playwright.dev/docs/docker

This is suitable for a dev-only MVP, especially for the Maverick visual
inspector use case.

### CDP is not the default

Playwright supports `connectOverCDP`, but documents it as Chromium-only and
lower fidelity than the Playwright protocol connection.

Reference:

- https://playwright.dev/docs/api/class-browsertype

Use CDP only when a chosen broker requires it. Default to the Playwright
protocol when Maverick controls both ends.

### Browserless

Browserless is a reasonable ops candidate because its open-source deployment
supports Dockerized headless browsers, Playwright, REST APIs, session
management, health checks, and concurrency settings.

Reference:

- https://docs.browserless.io/enterprise/open-source

Before choosing it, verify whether the intended path uses native Playwright
protocol or CDP for the specific feature set Maverick needs. Do not assume
Browserless removes the need for Maverick-owned policy, audit, or workspace
isolation.

## Hardening Requirements

The Browser app introduces a high-risk boundary: a user or agent can ask a
server-side browser to visit the internet. That is network egress, credential
handling, file transfer, and prompt-injection exposure in one feature.

Read-only mode reduces risk, but it does not remove it. A read-only browser can
still contact internal hosts, follow redirects, load attacker-controlled
content, expose secrets in URLs or headers, trigger server-side side effects,
and feed prompt-injection text into agents.

P0 hardening:

- allow only `http` and `https` URLs
- block `file:`, `data:`, `blob:`, `chrome:`, `devtools:`, `about:`, and custom
  internal schemes unless a specific internal exception is documented
- block loopback, link-local, private IPv4 and IPv6 ranges, Docker bridge ranges,
  host gateway addresses, and cloud metadata endpoints
- protect against DNS rebinding by checking resolved IPs before navigation and
  after redirects
- add a separate admin-only dev mode for local Maverick targets such as
  `hostmachine:8000`
- deny browser permissions by default: camera, microphone, geolocation,
  notifications, clipboard, MIDI, USB, serial, and automatic downloads
- isolate service workers by context and clear them with the context
- disable automatic persistence of screenshots and frames
- store only explicitly saved screenshots, downloads, PDFs, traces, and videos
  under workspace Storage
- audit every navigate, click, type, wait, download, upload, profile restore, and
  artifact save
- redact URLs and request headers where secrets may appear
- treat page text and DOM-derived content as untrusted input when consumed by
  agents

P0 action policy:

- read-only web mode may navigate, snapshot, screenshot, extract visible text,
  and inspect console/network state
- read-only web mode must not click, type, submit forms, upload files, download
  automatically, persist cookies, or reuse login state
- click/type may be enabled in P0 only for allowlisted Maverick development
  inspector targets

Playwright's Docker documentation is also conservative about untrusted websites:
when crawling or testing untrusted sites, the browser should run as a separate
user inside Docker and use a seccomp profile.

Reference:

- https://playwright.dev/docs/docker

## Network Egress Gap

Maverick app contracts already include `permissions.network.outbound`, and the
parser validates entries as hostnames, host:port, or `*`.

Current local source:

- `core/apps/contract_parser_permissions.py`
- `core/apps/contract_validation.py`

However, this appears to be contract validation and serialization rather than a
general runtime network egress enforcement mechanism for app backends or
browser processes.

For a Browser app this is a blocker.

Required platform work:

- define a generic egress policy model that can apply to sidecars and app-owned
  network work
- enforce CIDR deny rules below DNS names
- enforce redirects against the same policy
- bind DNS approval to the browser connection path; a preflight DNS check is not
  sufficient if Chromium can later resolve or connect to a different address
- expose explicit dev-mode exceptions
- keep browser egress decisions auditable
- make `permissions.network.outbound` meaningful, or introduce a browser-specific
  governed network policy that is not confused with the existing declarative
  field

The Browser app must not ship with broad internet access in a non-dev workspace
until this is solved.

## First Product Shape: Browser Lab

The first useful implementation should combine two related but distinct modes.

### Read-only web inspection

Maverick can open public web pages in an isolated Browser Lab session and
observe them without acting on them.

Allowed capabilities:

- navigate to an allowed `http` or `https` URL
- capture accessibility snapshot
- capture screenshot
- extract visible text or bounded semantic page structure
- inspect console errors
- inspect network failures and request metadata after redaction
- close and clean up the session

Disallowed in this mode:

- click/type
- form submission
- login-state persistence
- file upload
- automatic download persistence
- arbitrary JavaScript evaluation
- unrestricted cookie or localStorage mutation

This mode lets Maverick understand what is happening on the web while keeping
the first implementation bounded.

### Maverick development visual inspector

The strongest first debugging use case is Maverick development inspection.
Here click/type can be useful earlier because targets are Maverick-owned dev
surfaces, not arbitrary third-party sites.

P0 should target only allowlisted Maverick dev URLs:

- local hosted Maverick shell
- app routes under `/app/<app_id>`
- direct mounted app assets under `/apps/<app_id>/` when needed
- app backend/API calls only as a consequence of user-visible UI interactions

Capabilities:

- navigate to an allowlisted Maverick route
- capture accessibility snapshot
- capture screenshot
- inspect console errors
- inspect network failures
- click/type through refs
- report layout overlap, missing controls, broken routes, failed fetches, and
  app ready-state problems

This gives immediate engineering value while building the isolation model before
opening the browser to broader web automation.

Important: the Browser Lab should not introspect the user's real browser or PWA
session. A browser-hosted PWA cannot safely control the host browser's DOM,
cookies, tabs, or extension state. Maverick should operate a separate remote
browser session until the later Chrome Companion integration exists.

## Chrome Companion Extension

Chrome Companion is a later provider, not part of the first Browser Lab MVP.

It should use progressive permissions:

- tab metadata, if authorized: URL, title, window, active/inactive state
- active-tab sharing after explicit user gesture
- content script access only through `activeTab` or optional per-domain host
  permissions
- actions only in an explicitly attached tab and with approval gates
- debugger/CDP mode only as a visible dev/power-user mode

The Companion must not background-scrape the content of every open tab. It must
show visible attachment/control state, support detach-all, and audit every
snapshot and action.

## Roadmap

### P0: Browser Lab read-only plus Maverick dev inspector

Scope:

- install-level sealed Browser app
- thin Browser app backend/controller
- local Playwright server sidecar
- `browserType.connect()` with pinned matching Playwright versions
- isolated browser sessions
- no persistent profiles
- no real login storage
- no file upload
- no automatic download persistence
- read-only web inspection for allowed public `http`/`https` URLs under egress
  policy
- Maverick development inspector with click/type only on allowlisted Maverick
  dev URLs
- accessibility snapshots
- screenshot capture
- console and network logs
- audit for navigate/snapshot/screenshot/extract/click/type/wait
- app MCP subset modeled after Playwright MCP but without code evaluation

### P1: Broker, artifacts, and controlled actions

Scope:

- persistent browser broker sidecar
- WebSocket or SSE for visual state and status updates
- explicit screenshot save to Storage
- explicit download save to Storage
- optional trace/video save to Storage
- session status records under Browser app data
- cancellation and timeout controls
- approval gates for click/type on non-Maverick web targets
- profile persistence only by explicit opt-in
- encrypted or governed storage-state handling

### P2: General web access under policy

Scope:

- container or network namespace per session or workspace
- enforce egress policy for DNS, redirects, and IP ranges
- quota and concurrency controls
- approval gates for login, form submission, personal data, payments, and
  account-changing actions
- prompt-injection policy for web content consumed by agents
- restricted file upload from explicitly selected workspace files
- expanded MCP capabilities only after policy review

### P3: Chrome Companion

Scope:

- Chrome MV3 extension
- secure pairing with Maverick
- tab metadata view
- active-tab snapshot and screenshot after user gesture
- optional per-domain permissions
- attached-tab mode with visible indicator and detach-all
- approval UI for click/type/navigate in real Chrome tabs
- optional debugger/CDP mode for dev and power users only
- full audit trail and revocation

## Open Questions

- Should the browser broker be a new generic core-managed sidecar type, or an
  app-owned service supervised by a generic sidecar framework?
- Should persistent browser auth state live in Browser app data, Core Secrets,
  or a new credential-adjacent store?
- Should `permissions.network.outbound` become enforceable for all app backends,
  or should browser egress use a separate policy model first?
- How should human approvals be represented for agent-driven browser actions?
- Which artifacts are retained by default, and what retention policy applies to
  screenshots, traces, videos, downloaded files, and network logs?
- What is the minimum safe read-only egress policy for public web inspection?
- Which additional Maverick dev hosts or ports, beyond the initial
  `http://hostmachine:8000` entry, should an admin be able to enable?
- What pairing, revocation, and audit model should Chrome Companion use?

## Decision Summary

Maverick should build browser capability in stages.

First, ship a Browser Lab:

- app frontend for the user experience
- thin app backend for policy, audit, MCP, and Storage integration
- persistent isolated browser broker sidecar for Playwright/Chromium
- read-only public web inspection under egress policy
- Maverick development inspector with click/type only on allowlisted Maverick
  dev URLs
- snapshot-first MCP protocol inspired by official Playwright MCP
- isolated sessions by default
- no ordinary-agent access to arbitrary code evaluation
- no persistent auth state unless explicitly opted in and governed

Then expand toward controlled web actions and, later, Chrome Companion.

Chrome Companion should be treated as a separate provider with a higher-risk
trust boundary because it touches the user's real Chrome profile. It is useful
for assisted context and already-logged-in pages, but it must default to
metadata or active-tab sharing, visible attachment, explicit approvals, audit,
and revocation.

This approach lets Maverick gain practical web visibility and debugging value
early without turning browser automation into an ungoverned side channel around
workspace isolation, app permissions, and core policy.
