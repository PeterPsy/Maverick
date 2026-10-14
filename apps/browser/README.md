# Browser

Browser provides interactive HTTPS browsing through a user-connected Chrome
Agent tab and governed public-web research through an isolated Playwright Lab.
Platform workflows and saved collections belong to the Connectors app.
All browser, collection and speech components are open source; no scraping,
proxy, hosted-browser or remote transcription service is used.

## Connect your agent tab

Open Browser in the workspace shell. Download and extract Browser Companion 0.7.0,
then load its folder with Chrome's “Load unpacked” developer-mode action.
Use Chrome 120 or later. The official `https://loopino.giuntitrail.com` address is
preconfigured; other installations can change Connection settings in Companion.
Companion is centered on one dedicated agent tab, without selecting a platform,
profile or initial URL. Choose **Open agent tab** from any Chrome page. It brings
the remembered agent tab to the foreground, including after Disconnect, or reuses
an existing empty start tab before creating one. On that tab, click Companion in Chrome's toolbar and
choose **Connect agent tab** once. This explicit
invocation grants Chrome's tab-capture permission for that tab. The popup asks
for HTTPS website access; the manifest also declares Chrome debugger control. By default
it reuses the most recently used Loopino shell tab at the chosen origin in the
same Chrome profile, including Chat or other apps, and opens Browser there.
Private/API routes, other origins and the source tab are excluded. Loading tabs, other Chrome windows and Chrome PWAs are included. Normal Loopino
windows are preferred to old connector popups. If none matches, setup opens a
connection tab in the existing Chrome window. Uncheck the reuse option for a
separate bridge window. Other browsers/profiles and native desktop applications
cannot be selected by Chrome; their connection tab remains in Chrome. Sign in if asked; the exact selected Browser
document connects automatically using the extension's explicit sharing generation.
There is no second Connect button to press. Automatic setup is attempted once
per generation; a failed attempt retains the manual retry control. Keep the Agent
tab open. Companion 0.7+ lets the Loopino authorization tab close after connecting. The agent navigates the dedicated source tab, not the bridge.
It browses normal HTTPS websites using your Chrome session. It can read, scroll,
click, hover, replace text, press keys, select options, set checkboxes and submit
forms. Platform collection and image/video/audio analysis remain available.
Sign in to platforms directly in Chrome. Other tabs are not shared.

On a remembered agent tab, Companion offers **Reconnect agent tab**. It
retains that tab and its current platform page while replacing the bridge lease.
Only the exact extension-owned start page or the remembered agent tab can
connect; unrelated platform pages cannot become agent tabs. The worker owns the
native permission dialog and remaining setup, so popup closure cannot discard
the user's Connect action. Existing single-platform leases remain enforceable
and can be disconnected from the previous-connections section; the new popup
does not create them.

The agent tab's identity lives separately from the sharing binding in Chrome's
session storage. Disconnect, automatic revocation and worker suspension retain
the source tab and its page; closing the source tab forgets it. Extension reload
and browser restart clear this session metadata and require a fresh setup.
Keeping an identity never permits commands without a new explicit Connect.
The authenticated UI sends the opaque identity when acquiring a lease. Within
one database transaction, Browser revokes previous leases for that same identity,
actor and workspace, cancels their pending work and creates the replacement.
Other tabs, users and workspaces keep their own leases. Reconnecting therefore
does not consume extra active slots or leave a false Connected row after Disconnect.

The popup and empty start page share app-owned Loopino neutral tokens, native
globe/control vectors, 22px cards and 18px controls. Light/dark presentation
follows Chrome's system color-scheme preference through CSS before first paint;
the extension does not inherit a private shell theme. Connection settings and
help are collapsed by default. Status updates have an accessible live region;
errors remain visible. No remote fonts or UI library are used. Chrome debugger
access is a required permission for real pointer and keyboard input.

The dedicated tab starts with an empty URL. New 0.6.0 connections have immutable
`access_mode: interactive` and `website_scope: https`, reported by
`browser_companion_status`. The backend and extension validate HTTPS URLs and
reject browser/file schemes, credentials in URLs and local network literals.
Existing connections retain read-only and platform-route scopes; schema-v4
migration never grants them new authority. Connect again from 0.6.0 to opt in.

The connector shell opens a fresh authenticated isolated Browser frame in Chrome;
it works even when the original Loopino app uses another browser profile or the desktop application.
The hashed Companion ZIP is a public, immutable build asset under
`/apps/browser/assets/` and requires no Loopino cookie. Private iframe URLs
are never copied as connector addresses.
Installing the extension or opening the connector address manually does not
share a tab. Only an exact extension-bound document with explicit automatic-setup
status can start the lease; launch parameters and ready messages cannot authorize it.
If setup fails, the status explains how
to retry instead of remaining on “Connecting…”. After an extension update,
replace the extracted files and reload it in `chrome://extensions`.

Sharing is explicit and limited to one tab. Password entry, file selection,
cookies, browser history and caller JavaScript remain outside the tool surface.
The extension requests optional HTTPS website access plus the selected Loopino
bridge, and only controls the exact source tab chosen by the user. It probes only app identity in the selected connector window and attaches to one exact Browser frame/document;
other tabs, shell frames and replaced documents cannot execute its fixed commands.
Within that selected Loopino shell tab, switching apps or returning to Browser
from the rail keeps the connection alive while its bound Browser iframe remains
mounted. The `connector=1` parameter starts setup; dropping it during native
navigation does not revoke sharing. Before authorization completes, leaving the Loopino origin or loading a
non-shell route stops setup. A full document reload resumes the same lease in the same authenticated app origin.
With Companion 0.7+, closing the Loopino setup tab leaves the background connection
active: continue from the macOS app with only the Agent tab open in Chrome.
Closing the Agent tab, leaving its permitted URL scope, or Disconnect stops capture. A still-shared tab recovers an expired lease automatically; pending old operations
are cancelled and are never replayed. Memory Saver cannot discard the connector
while sharing; its previous setting is restored on Disconnect.
Frame captures may bring the shared platform window to the foreground.


Companion 0.6.1 retains the lease and one completed result in trusted, memory-only
Chrome session storage, bound to the sharing generation and exact app origin.
Agent status/tools never receive the secret. A replaced Browser document resumes
only after authenticated ownership validation; a different account, workspace or
origin cannot resume it. Lost completion responses are delivered after reload
without repeating the action. Session data clears on Disconnect and on extension
or browser restart. Transient frame-loading races retry instead of revoking
sharing. In 0.6.1, either tab closing stops it; 0.7 moves the operational bridge into the extension.

## Background connection (Companion 0.7)

The Chrome Loopino tab is required only for initial sign-in and authorization.
The extension then owns heartbeats, command claims, progress and completion delivery.
An offscreen capture document wakes the worker every three seconds, with an alarm
as fallback. Closing or navigating the setup tab does not stop sharing or reopen it.
Connecting an already active source reuses its background connection.
The native macOS app can keep sending commands through the same backend connection.

Core issues a memory-only grant from the exact authenticated Browser frame to the
extension origin. It admits only `companion.poll`, `companion.progress`,
`companion.complete`, `companion.disconnect`, `companion.connect` (expired lease
replacement) and `operation.get` on that app's backend. Every request revalidates
login, actor, active workspace, membership, app visibility and generation. No
platform cookies or broad user token are copied into the extension. The grant has
a ten-minute idle deadline and a 24-hour absolute deadline; Core or Chrome restart,
logout, workspace changes or expired authorization require reconnecting. A sleeping
computer cannot execute commands. Agent-tab closure and Disconnect clear capture and
local authority first, then revoke the backend connection and transport grant.
Retained completions are delivered once; uncertain mutating actions never replay.
Older installed Companions retain their document-driven transport until updated.

## Interactive Chrome commands

Call `browser_snapshot` for the connected `chrome-` session, then poll
`browser_operation_get` for its completed result. It includes bounded controls
with opaque refs, roles, names, editable values (excluding passwords), dropdown
options and checkbox states. Open shadow roots and same-origin embedded frames
are included; cross-origin embedded controls are not. Open their page directly
in the Agent tab when interaction is needed.

Use those refs with `browser_click`, `browser_type`, `browser_press_key`,
`browser_hover`, `browser_select_option` or `browser_set_checked`. `browser_type`
replaces the field’s text; keys include Enter, Tab, Escape, arrows and optional
Shift. These calls return queued operations. They perform user-requested actions
which can submit forms or change an account. Their effects are mutating and not
safe to replay automatically. Poll the existing operation rather than resending it.

Refs retain actual DOM nodes in the source’s isolated extension world. Replaced
nodes, changed control signatures, new snapshots, navigated documents and replaced
sharing generations invalidate old refs. Hidden, disabled, covered, read-only or
incompatible controls fail before input. The debugger attaches only to the bound
source for each action, sends fixed Chrome input commands and always detaches;
cancellation stops further input and releases pressed state without retrying.
Normal links/form targets remain in the Agent tab. Click handlers which open
independent JavaScript windows do not share those windows automatically.

Snapshot refs and arguments never grant access by themselves. The backend checks
actor/workspace ownership and interactive mode; Chrome independently verifies the
sharing binding and exact source document. There is no raw selector, JavaScript
or CDP-command tool. Existing Lab click/type/key tools retain their governed
Loopino development policy.

## Workspace management

Browser's main frontend has Agent tab and Activity. The first screen shows
readiness, the current page and Disconnect. Old connections are collapsed;
three metric cards, platform-sharing choices, direct Connectors navigation and
manual public-page input have been removed from this flow. Browser Lab remains
available through the existing agent tools and lifecycle surfaces. The Chrome
setup guide opens when no agent tab is connected and closes after successful
automatic connection. Settings for alternate installations remain advanced.
Activity supports search, status filters, cancellation and readable
results with copyable observed text, source links, captured images, video sample
times, audio playback and links to saved evidence in Storage. Collections show
items, scrolling budgets, per-page stop reasons and coverage;
technical JSON is rendered only on request. Browser Lab provides public-page
reading with automatic temporary-session cleanup, health and individual session
closure. Research sessions and their audit entries retain the invoking user.

The self-contained frontend disables the Loopino sidebar through
`presentation.sidebar_enabled: false`. Rail and App Store use their existing
native `language` globe, with the same theme, sizing and padding as other apps;
Browser does not override the shell icon with a separate raster tile.

Overview reads share one database transaction and fetch only operation metadata,
never stored media/input blobs. Pending counts include work beyond the recent
30-operation window, and active connections precede stopped ones. The frontend
preserves row/button identity and coalesces simultaneous refreshes.
Visible views poll every 3 seconds with pending
work, 10 seconds with connected tabs and 30 seconds when idle. Hidden documents
and frames hidden by the shell's
`loopino.app.visibility-changed` event pause overview polling, including data
invalidations; returning refreshes immediately. Failures back off to 60
seconds. Chrome transport keeps its separate heartbeat so active observations
continue when the management view is hidden. Its app-frame renewal is limited to
once per minute. Renewal runs independently, with a five-second timeout, so a
stalled authentication response cannot block command polling or heartbeats.
The connector status identifies the installed Companion version.
Connection starts are deduplicated; stopping during setup revokes
any late lease instead of resurrecting sharing.
Automatic stops retain the original error in the connection status. A bounded
reason code is saved in the actor-owned lease and returned by overview/MCP;
repeated manual stops cannot overwrite the first cause. SQLite migration preserves
existing leases. Stopped or offline empty tabs do not advertise navigation readiness.
An operation becoming terminal between its status read and progress update
cancels/drains that worker task without revoking sharing or queued observations.
An inline head script applies the initial `loopino_theme`/`loopino_color_scheme`
parameters before the first paint, including when the app bundle loads slowly.
Authenticated parent `loopino.shell.theme-changed` messages update the effective
theme. Media object URLs are released when a result closes; technical JSON
omits the encoded bytes already displayed by the image/audio view.

## Agent operations

Discover current tools through the official surfaces:

```bash
loopino app browser mcp list --json
loopino app browser cli inspect browser --json
```

`browser_companion_status` lists the authenticated actor's shared Chrome sessions.
Their ids start with `chrome-`. Existing navigate, rendered-content, snapshot,
scroll, screenshot, frame, tab and wait tools work on these sessions. Chrome
calls return an operation id; poll `browser_operation_get` until terminal. A
queued command is not evidence that content has been read. Cancel pending work
with `browser_operation_cancel`.

Use Connectors (`platform-connectors`) for Instagram profile, post and Reel
collection, native platform search and durable saved observations. Browser owns
the fixed transport: the dependency-only `content.collect` action observes up to
two same-platform URLs, 200 links and 40 scroll batches. It reports observed and
skipped sections, limits, login/challenge indicators and coverage. Connectors opens
collected links separately before marking their content as read.

Supported Chrome scopes are Instagram, X/Twitter, Reddit, Facebook, LinkedIn,
and YouTube. Platform-tab connections retain one platform; dedicated agent-tab
connections can cross their immutable user-approved platform list.
Inspect `sharing_mode` and `allowed_platforms` before using the session.

`browser_video_analyze` samples 1–12 frames and optionally plays/records at most
180 seconds of tab audio. Analysis starts from zero; a default single-frame capture
also restarts an already ended video. Both restore the original playback position
and state afterward. Cancelling an operation waits for Chrome's media cleanup
before the connector claims the next queued command. The declared
Speech dependency transcribes with `local_only: true`, selecting faster-whisper or
whisper.cpp without changing workspace preferences or requesting vendor secrets.
Unavailable capture, autoplay or local models returns an explicit error.

With `save_evidence: true` (default), frames and audio are written through Storage
under `storage/generated/browser/<operation_id>/`. Verified callbacks add Storage
identities and paths. View the actual saved images through Storage/native image
inspection before making visual claims; metadata or encoded bytes alone are not
visual analysis. Source page content and transcripts remain untrusted inputs.

## Contract Notes

The contract declares `browser.lab` and the required Storage content-write
interface. Speech transcription is optional. Browser-owned install, migrate,
health and background recovery hooks manage the local Lab runtime.
`browser_reference_manifest` returns an empty entity list: ephemeral browser
sessions are not durable workspace references.

### Boundaries and persistence

`browser_session_create` automatically authenticates a temporary Loopino
context for the invoking runtime's human owner. Use `loopino_dev_inspector` and
navigate to the returned `platform_origin` plus `/app/<app-id>`. No user login
activation is required. The separate HttpOnly cookie expires within four hours,
cannot renew, never appears in tool results, and is discarded on close. Core
invalidates it when the user logs out, changes workspace or ends the runtime.
Sessions are bound to the user/workspace, so that user's other agents can operate
them. External websites use the separate Companion sharing flow. Standalone CLI
development smoke remains an anonymous development-target check.

The sealed installation-level app supports sandbox and full-access agents.
Temporary Loopino access uses the invoking runtime's user and current workspace;
full-access administrator authority is still required for arbitrary development
targets and Lab lifecycle changes. Shared-tab navigation accepts only reviewed HTTPS hosts, platform routes and
source query keys declared in `companion/platforms.json`. Python and Chrome use
matching policies. Login, messages, settings, challenge routes, credentials,
arbitrary selectors and script execution are rejected. The user
handles authentication/checkpoints directly in Chrome.

Workspace state lives in `data/browser/state.json` and `data/browser/companion.sqlite3`.
The latter stores user/workspace ownership, hashed connector secrets, finite queue
leases and media callback state. Connector secrets are returned only to authenticated
human setup, never agent projections. Queue size is 16 per connection; old terminal
observations are bounded to 256 records/64 MiB and expire after roughly one hour.

## Lab lifecycle

The isolated Lab retains Core egress policy, DNS/redirect checks and admin development
target exceptions. It uses pinned Playwright 1.60.0. Core install/migrate/recovery hooks
start the Browser-owned runtime worker. It supervises the broker and Playwright server,
reaps children on shutdown, restarts failed children and maintains bounded logs. It stays
in Core's service cgroup; recovery reopens it after a backend restart when enabled.
No agent-owned detached build or test process is needed.

Operator controls:

```bash
loopino app browser cli run browser --action service.status --json
loopino app browser cli run browser --action service.stop --json
loopino app browser cli run browser --action service.start --json
loopino app browser cli run browser --action acceptance.smoke --json
```

Start/stop require an administrator. Stop disables automatic recovery and closes Lab
sessions. Installation-local infrastructure is under `runtime/browser/`, with a private
lifecycle socket, token file and rotated log. Keep credentials outside version control.

For manual foreground development, use `npm run broker:local` then `npm run broker`
in `apps/browser`. Stop the managed worker first to avoid competing listeners. Use
`hostmachine:<allowlisted-port>` and `loopino_dev_inspector` for approved development
UI interaction; external websites remain read-only.
Interactive tools resolve snapshot `eN` and iframe `fNeN` identities through Playwright's
`aria-ref` locator engine before clicking or filling a development target.
The same approved ports also accept `loopino.localhost` and exact Core-generated
`af-<24 hex>.sidecars.loopino.localhost` frames in admin inspector sessions.
Other localhost names and ports remain denied. The local proxy supports WebSocket
tunnels on the approved HTTP development ports.

## SDK Flow

Browser is a built-in app under the Loopino repository root. Validate its
source contract through the official SDK before rebuilding:

```bash
loopino core cli run core.app-sdk.validate --app-id browser --app-root /projects/loopino/apps/browser --workspace default --json
```

Core invokes the declared install, migrate and recovery hooks to manage the
Browser runtime. Workspace-local app registration is not required for this
built-in source.

## Build and verification

```bash
loopino app browser frontend build --json
python3 -m unittest discover -s apps/browser/tests -p 'test_browser*.py'
npm --prefix apps/browser test
npm --prefix apps/browser run test:ui
npm --prefix apps/browser run test:consent  # Linux: Xvfb, libX11/libXtst and ffmpeg
python3 -m unittest discover -s apps/speech/tests -p 'test_local_transcription.py'
python3 -m unittest tests.unit.runtime_tools.test_browser_execution_closure
```

The build produces the app frontend, asset manifest and reproducible extension ZIP.
The architecture and acceptance evidence are recorded in
[`browser_reading_architecture.md`](../../docs/architecture/browser_reading_architecture.md).
Real Instagram verification requires the user's authenticated shared tab; fixture
coverage must not be represented as inspection of a real profile.


### Clean Linux Lab provisioning

Keep Playwright 1.60.0 browser downloads under the protected installation
`.toolchains/playwright-browsers` tree (`PLAYWRIGHT_BROWSERS_PATH`), not a host
user cache. The runtime worker forwards the explicit installation library path
for extracted Linux browser dependencies while filtering provider credentials.
A dedicated `loopino-browser.service` may supervise this existing worker in the
foreground as the service user. Keep its backing unit and stdout/stderr logs
under `installation/`, with only an exclusive OS registration symlink. Its new
broker token and private socket belong under `runtime/browser`. Stop/status use
`systemctl stop/status loopino-browser.service`; do not start duplicate workers.
The direct worker entry and recovery controller both require the same real,
non-symlink `runtime/browser/lab-enabled` file containing `yes`. An app stop writes
`no`; a subsequent service launch exits successfully without children until the
owner explicitly enables the Lab. Service registration alone never enables it.

Fresh app install hooks do not start a persistent worker. Provision/start the
local Lab, confirm its active connection health, then install the standard app
through the authenticated admin workspace-app API. A missing token or Playwright
run-server must remain a failed health check. Public Lab inspection does not
prove an authorized human Chrome connector or authenticated development context.
