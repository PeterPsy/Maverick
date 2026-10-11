# Browser

Browser provides read-only platform navigation through a user-shared Chrome
session and governed public-web research through an isolated Playwright Lab.
Platform workflows and saved collections belong to the Connectors app.
All browser, collection and speech components are open source; no scraping,
proxy, hosted-browser or remote transcription service is used.

## Connect a platform tab

Open Browser in the workspace shell. Download and extract Browser Companion 0.5.3,
then load its folder with Chrome's “Load unpacked” developer-mode action.
Use Chrome 120 or later. The official `https://maverick.loopino.ai` address is
preconfigured; other installations can change Connection settings in Companion.
Open a supported platform page in Chrome, log in directly if needed, and choose
**Share this tab** once. Allow Chrome access when asked. The service worker owns
the permission request and the remaining setup, so closing the popup during the
native dialog cannot discard the connection. The agent can navigate throughout
that platform; sharing a profile
does not restrict navigation to that profile. Platform home pages are supported.

To start empty, choose **Open agent tab** in Companion, even from Chrome's New
Tab page. On the new dedicated tab, click Companion in Chrome's toolbar again and
choose **Connect agent tab** once. This explicit
invocation grants Chrome's tab-capture permission for that tab. The popup asks
for the six supported platform hosts plus Maverick, not every website. By default
it reuses the most recently used Maverick shell tab at the chosen origin in the
same Chrome profile, including Chat or other apps, and opens Browser there.
Private/API routes, other origins and the source tab are excluded. Uncheck
the reuse option to open a separate bridge window. A new window is also necessary
when no matching Maverick tab exists, including Maverick in another profile,
browser or desktop application. Sign in if asked; the exact selected Browser
document connects automatically using the extension's explicit sharing generation.
There is no second Connect button to press. Automatic setup is attempted once
per generation; a failed attempt retains the manual retry control. Keep both tabs
open. The agent navigates the dedicated source tab, not the bridge.
It can navigate across Instagram, X, Reddit, Facebook, LinkedIn and YouTube, using your
usual Chrome platform sessions. It can read, scroll, collect content and analyze
images/video/audio; clicks, form entry, posting and messages have no command.
Sign in to platforms directly in Chrome. Other tabs are not shared.

The dedicated tab starts with an empty public URL. Its immutable approved
platform list is saved in the user-created connection lease and returned by
`browser_companion_status`. The backend and extension independently enforce the
same list and reviewed content routes. Existing platform-tab connections retain
their single-platform scope. Schema migration preserves existing sharing leases.

The connector shell opens a fresh authenticated isolated Browser frame in Chrome;
it works even when the original Maverick app uses another browser profile or the desktop application.
The hashed Companion ZIP is a public, immutable build asset under
`/apps/browser/assets/` and requires no Maverick cookie. Private iframe URLs
are never copied as connector addresses.
Installing the extension or opening the connector address manually does not
share a tab. Only an exact extension-bound document with explicit automatic-setup
status can start the lease; launch parameters and ready messages cannot authorize it.
If setup fails, the status explains how
to retry instead of remaining on “Connecting…”. After an extension update,
replace the extracted files and reload it in `chrome://extensions`.

Sharing is explicit and limited to one tab. Passwords, cookies, browser history,
forms, social writes and caller JavaScript are outside the tool surface. The
extension requests optional access to the selected Maverick origin, its isolated
frame namespace and the selected platform, or the six supported platforms for a
dedicated agent tab. It probes only app identity in the selected connector window and attaches to one exact Browser frame/document;
other tabs, shell frames and replaced documents cannot execute its fixed commands.
Within that selected Maverick shell tab, switching apps or returning to Browser
from the rail keeps the connection alive while its bound Browser iframe remains
mounted. The `connector=1` parameter starts setup; dropping it during native
navigation does not revoke sharing. Leaving the Maverick origin or loading a
non-shell route still stops the bridge. A full document reload requires reconnecting.
Closing either tab, leaving approved platform routes, or revoking sharing stops
capture. Reloading the connector requires a fresh user-owned connection.
Frame captures may bring the shared platform window to the foreground.

## Workspace management

Browser's main frontend contains Shared tabs, Activity and Browser Lab. The
Chrome setup guide opens automatically when no tab is connected and stays
collapsible. Activity supports search, status filters, cancellation and readable
results with copyable observed text, source links, captured images, video sample
times, audio playback and links to saved evidence in Storage. Collections show
items, scrolling budgets, per-page stop reasons and coverage;
technical JSON is rendered only on request. Browser Lab provides public-page
reading with automatic temporary-session cleanup, health and individual session
closure. Research sessions and their audit entries retain the invoking user.

The self-contained frontend disables the Maverick sidebar through
`presentation.sidebar_enabled: false`. Rail and App Store use their existing
native `language` globe, with the same theme, sizing and padding as other apps;
Browser does not override the shell icon with a separate raster tile.

Overview reads share one database transaction and fetch only operation metadata,
never stored media/input blobs. Pending counts include work beyond the recent
30-operation window, and active connections precede stopped ones. The frontend
preserves row/button identity and coalesces simultaneous refreshes.
Visible views poll every 3 seconds with pending
work, 10 seconds with connected tabs and 30 seconds when idle (Lab also uses 30
seconds). Hidden documents and frames hidden by the shell's
`maverick.app.visibility-changed` event pause overview polling, including data
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
An inline head script applies the initial `maverick_theme`/`maverick_color_scheme`
parameters before the first paint, including when the app bundle loads slowly.
Authenticated parent `maverick.shell.theme-changed` messages update the effective
theme. Media object URLs are released when a result closes; technical JSON
omits the encoded bytes already displayed by the image/audio view.

## Agent operations

Discover current tools through the official surfaces:

```bash
maverick app browser mcp list --json
maverick app browser cli inspect browser --json
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

`browser_session_create` automatically authenticates a temporary Maverick
context for the invoking runtime's human owner. Use `maverick_dev_inspector` and
navigate to the returned `platform_origin` plus `/app/<app-id>`. No user login
activation is required. The separate HttpOnly cookie expires within four hours,
cannot renew, never appears in tool results, and is discarded on close. Core
invalidates it when the user logs out, changes workspace or ends the runtime.
Sessions are bound to the user/workspace, so that user's other agents can operate
them. External websites use the separate Companion sharing flow. Standalone CLI
development smoke remains an anonymous development-target check.

The sealed installation-level app supports sandbox and full-access agents.
Temporary Maverick access uses the invoking runtime's user and current workspace;
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
maverick app browser cli run browser --action service.status --json
maverick app browser cli run browser --action service.stop --json
maverick app browser cli run browser --action service.start --json
maverick app browser cli run browser --action acceptance.smoke --json
```

Start/stop require an administrator. Stop disables automatic recovery and closes Lab
sessions. Installation-local infrastructure is under `runtime/browser/`, with a private
lifecycle socket, token file and rotated log. Keep credentials outside version control.

For manual foreground development, use `npm run broker:local` then `npm run broker`
in `apps/browser`. Stop the managed worker first to avoid competing listeners. Use
`hostmachine:<allowlisted-port>` and `maverick_dev_inspector` for approved development
UI interaction; external websites remain read-only.
Interactive tools resolve snapshot `eN` and iframe `fNeN` identities through Playwright's
`aria-ref` locator engine before clicking or filling a development target.
The same approved ports also accept `maverick.localhost` and exact Core-generated
`af-<24 hex>.sidecars.maverick.localhost` frames in admin inspector sessions.
Other localhost names and ports remain denied. The local proxy supports WebSocket
tunnels on the approved HTTP development ports.

## SDK Flow

Browser is a built-in app under the Maverick repository root. Validate its
source contract through the official SDK before rebuilding:

```bash
maverick core cli run core.app-sdk.validate --app-id browser --app-root /home/ubuntu/projects/maverick-v3/apps/browser --workspace default --json
```

Core invokes the declared install, migrate and recovery hooks to manage the
Browser runtime. Workspace-local app registration is not required for this
built-in source.

## Build and verification

```bash
maverick app browser frontend build --json
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
