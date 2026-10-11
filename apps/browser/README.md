# Browser

Browser 0.4 provides read-only platform navigation through a user-shared Chrome
session and governed public-web research through an isolated Playwright Lab.
Platform workflows and saved collections belong to the Connectors app.
All browser, collection and speech components are open source; no scraping,
proxy, hosted-browser or remote transcription service is used.

## Connect a platform tab

Open Browser in the workspace shell. Download and extract Browser Companion,
then load its folder with Chrome's “Load unpacked” developer-mode action. Copy
the connector address displayed by Browser. Use Chrome 120 or later. Open a supported platform page in Chrome, log in directly if needed, and use the extension popup to share
that tab. Paste the connector address there. In the dedicated Browser window
opened by the extension, press “Connect” and keep the window open during work.
Download and connector links use Browser's isolated origin, whose HttpOnly
app-frame cookie authenticates the dedicated window in the same Chrome profile.
The platform's `/apps/browser/` document and ZIP routes require isolation and
must not be used as setup links. Copy a fresh address from the mounted app after
signing in again or changing workspace. Theme parameters follow the connector.

Sharing is explicit and limited to one tab. Passwords, cookies, browser history,
forms, social writes and caller JavaScript are outside the tool surface. The
extension requests optional access to the selected Maverick origin and the selected platform;
only the selected tab and exact connector window can execute its fixed commands.
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
once per minute. Connection starts are deduplicated; stopping during setup revokes
any late lease instead of resurrecting sharing.
An operation becoming terminal between its status read and progress update
cancels/drains that worker task without revoking sharing or queued observations.
The initial `maverick_theme`/`maverick_color_scheme` parameters and authenticated
parent `maverick.shell.theme-changed` messages apply the platform's effective
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
and YouTube. Each connection
is bound to its platform. Switching platforms requires explicit sharing again.

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
python3 -m unittest discover -s apps/speech/tests -p 'test_local_transcription.py'
python3 -m unittest tests.unit.runtime_tools.test_browser_execution_closure
```

The build produces the app frontend, asset manifest and reproducible extension ZIP.
The architecture and acceptance evidence are recorded in
[`browser_reading_architecture.md`](../../docs/architecture/browser_reading_architecture.md).
Real Instagram verification requires the user's authenticated shared tab; fixture
coverage must not be represented as inspection of a real profile.
