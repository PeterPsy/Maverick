# Browser

Browser 0.3 provides read-only Instagram navigation through a user-shared Chrome
session and governed public-web research through an isolated Playwright Lab.
All browser, collection and speech components are open source; no scraping,
proxy, hosted-browser or remote transcription service is used.

## Connect Instagram

Open Browser in the workspace shell. Download and extract Browser Companion,
then load its folder with Chrome's “Load unpacked” developer-mode action. Copy
the connector address displayed by Browser. Use Chrome 120 or later. Open an Instagram profile, post or
Reel in Chrome, log in directly if needed, and use the extension popup to share
that tab. Paste the connector address there. In the dedicated Browser window
opened by the extension, press “Collega” and keep the window open during work.

Sharing is explicit and limited to one tab. Passwords, cookies, browser history,
forms, social writes and caller JavaScript are outside the tool surface. The
extension requests optional access to the selected Maverick origin and Instagram;
only the selected tab and exact connector window can execute its fixed commands.
Closing either tab, leaving approved Instagram routes, or revoking sharing stops
capture. Reloading the connector requires a fresh user-owned connection.
Frame captures may bring the shared Instagram window to the foreground.

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

`browser_instagram_collect` reads the profile and deduplicates rendered post/Reel
links across bounded scrolling: up to 200 items and 40 batches. Results include
observed times, source URLs and a stop reason. When Reels are requested, scan and
item budgets are shared between the profile and Reels sections; unused profile
capacity passes to Reels. The `sections` results identify observed and skipped
sections and their stop reasons. `section_limit` means at least one section was
only partially scanned, even if another reached its rendered end.
Open each collected link to inspect
its caption and media; unvisited posts are not analyzed. A rendered end or viewport
boundary does not prove complete feed coverage.

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

The sealed installation-level app is full-access only. Sandbox agents remain
excluded. Instagram navigation accepts only HTTPS `www.instagram.com` profile,
post, Reel and profile-Reels routes. Login, messages, settings, challenge routes,
credentials, arbitrary selectors and script execution are rejected. The user
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
maverick core cli run core.app-sdk.validate --app-id browser --app-root apps/browser --workspace default --json
```

Core invokes the declared install, migrate and recovery hooks to manage the
Browser runtime. Workspace-local app registration is not required for this
built-in source.

## Build and verification

```bash
maverick app browser frontend build --json
python3 -m unittest discover -s apps/browser/tests -p 'test_browser*.py'
npm --prefix apps/browser test
python3 -m unittest discover -s apps/speech/tests -p 'test_local_transcription.py'
python3 -m unittest tests.unit.runtime_tools.test_browser_execution_closure
```

The build produces the app frontend, asset manifest and reproducible extension ZIP.
The architecture and acceptance evidence are recorded in
[`browser_reading_architecture.md`](../../docs/architecture/browser_reading_architecture.md).
Real Instagram verification requires the user's authenticated shared tab; fixture
coverage must not be represented as inspection of a real profile.
