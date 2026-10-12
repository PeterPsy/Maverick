# Browser Reading and Shared Platform Transport

Date: 2026-10-12

## Implemented architecture

Browser extends the installation-level `apps/browser` app with an app-owned
Chrome Manifest V3 companion. Its fixed observation adapter reuses Browser's
rendered DOM reader. Platform workflows belong to `apps/platform-connectors`; Browser owns technical
transport and fixed observation adapters. Core remains app-agnostic. No commercial scraping, proxy, browser relay or speech service is
required. Browser's isolated Playwright Lab remains available for public research
and authorized Maverick development inspection.

The extension's user flow centers on a dedicated agent tab. Open agent tab
focuses the remembered agent tab even after sharing stops, or reuses an empty
extension-owned start page before creating one. A
second explicit toolbar invocation on that tab grants Chrome tab-capture access;
it can then connect without choosing an initial platform or profile. It asks for
the six exact supported platform host groups and Maverick, not all-web access.
The authenticated Browser UI records that approved platform list when creating
the backend lease. Only user connector actions can set it; subsequent heartbeats
and queued operations cannot change it. SQLite's versioned schema migration adds
an empty-list default so existing leases keep their single-platform ownership.
An empty public URL is accepted only for a dedicated agent connection. Read/media
operations require navigation first; tabs and navigation/collection work while empty.
Platform home pages are approved content routes. Sharing a profile never binds
navigation to that profile.
The official Maverick address is preconfigured in Companion; other installations
can change Connection settings. The popup sends the selected tab and destination
to the worker within its button gesture. The worker synchronously requests optional
permissions for the dedicated tab's approved platforms,
Maverick origin and isolated app-frame namespace, then completes setup even if
Chrome closes the popup during the native consent dialog. Concurrent requests are
deduplicated; denial never starts sharing. It then opens the stable
`/app/browser?connector=1` shell route. Companion defaults to reusing the most
recent Maverick shell tab at the exact chosen origin in the same Chrome profile,
with a fresh document for the new binding. It rechecks the candidate before
navigation, excludes the source tab, private/API routes and other origins. The
user's Connect action can move an existing Chat or other app tab to Browser. The popup
can disable reuse. A dedicated connector window remains the fallback when no
matching Maverick tab exists; desktop applications and other browser profiles
cannot be selected through Chrome's tabs API. The shared agent/platform tab is
the navigation target; Browser is the authenticated bridge. Chrome 120
or later is required. The connector uses ordinary Core-hosted backend calls and a
scoped content-script channel. Passwords, cookies, browser history, raw CDP,
selectors and arbitrary caller scripts are never exposed to agent tools.

The connector window must remain open. A 30-second extension alarm wakes its
poller when possible; alarms do not wake a sleeping computer and cannot guarantee
uninterrupted execution. Reloading requires fresh user setup. Closing either tab,
revoking sharing or leaving approved platform routes stops capture. Late connector
submissions cannot renew expired connections or complete expired operations.

## Management frontend

The self-contained workspace frontend disables the shell sidebar through its
presentation contract. It exposes Agent tab with readiness, current page,
Disconnect and collapsible Companion setup, plus Activity with search/status
filters, cancellation and readable results. Historical connections are collapsed;
metric cards and manual platform/profile/public-page selection are omitted.
The isolated Lab remains available through agent tools and operator lifecycle
surfaces. Its unused frontend form/session modules have been removed.
The existing shell/App Store `language` glyph owns Browser's native icon
presentation; no Browser-specific platform rendering branch or raster override
is added. The app header uses an inline vector and the favicon an app-owned SVG.
Companion packages its reproducible ZIP as a Vite-imported, hashed public
asset under `/apps/browser/assets/`, with immutable manifest/cache metadata.
Download uses the platform origin and requires no login or app-frame cookie.
The copied connector address uses the stable platform shell route, never an
expiring isolated-frame host. A fresh Chrome profile signs in normally; the
shell obtains its own authenticated Browser frame. Desktop-app cookies are not
transferred to Chrome. The selected Chrome workspace owns the connection.
Native `maverick.app.navigate` parameters enable Connect controls in that frame.
Companion binds the connector tab and probes only app identity across its frames.
Exactly one Core-generated Browser frame with the chosen platform origin is
required; commands then require that frame's exact origin, frame id and document
id. The selected shell tab can navigate between Maverick apps while retaining its
bound Browser document. Removing the launch parameter `connector=1` is also
allowed. That parameter enables setup UI; authority comes from the selected
tab, exact Browser origin/frame/document and sharing generation. Other shell
documents and non-shell/API routes remain outside the bridge. Full document
reload still requires a fresh user connection. A shell observer retries after
sign-in and iframe replacement, with the 30-second alarm as a wake-up fallback.
Other tabs, app frames, shell documents
and replaced connector documents cannot issue commands. Installations whose
app-frame domain differs from the platform host retain it in `frame_domain`.
Companion 0.5.4 uses app-owned copies of the native neutral light/dark tokens,
globe/control vectors, 22px cards and 18px controls in both popup and start page.
CSS follows Chrome's system color preference before first paint, without remote
assets or new permissions. The popup presents Open agent tab from ordinary
Chrome/platform pages and Connect agent tab only on its exact start page.
Reconnect agent tab is available on the remembered source after navigation or
Disconnect; the worker rechecks its identity and current route before capture.
Other platform tabs cannot become agent tabs. Settings and help are collapsed,
and errors use a visible accessible status region. The user no longer selects a
specific platform/profile or copies an address for the official installation.
Existing single-platform leases keep their original scope; the new popup cannot
create them. Installing Companion alone or opening
`/app/browser?connector=1` manually does not select a tab.

Companion 0.5.5 stores an opaque UUID and the source tab id as separate
`agentTab` session metadata. Stop/revocation removes only the sharing binding;
Open agent tab can still focus the source, including a login page requiring
direct user action. Commands and reconnect remain restricted to the supported
routes and require a fresh explicit capture grant. Closing the source forgets
its identity; extension reload/browser restart clear Chrome session metadata.
The UUID is navigation metadata, not a credential. It reaches `companion.connect`
only through the authenticated UI. The schema-v3 connection store atomically
revokes prior leases with the same UUID, user and workspace, cancels pending
operations and inserts the replacement before returning. Independent agent
tabs and principals remain isolated; older connections without identity retain
their original lease semantics. Replaced records retain `connection_replaced`
as their historical stop reason. A disconnected current source no longer leaves
its replaced lease advertising readiness or consuming an active connection slot.
The Core-owned Browser execution closure also includes the Companion identity
registry and reconnect validator, so changes to either source invalidate the
reviewed CLI/MCP read authority until its audit digest is refreshed.
The selected Browser document announces bridge readiness; the frontend probes
its worker status and enables Connect only after that response. A new user-selected
sharing generation requesting automatic setup starts the authenticated lease once,
after any human sign-in, without another Connect press. Launch URLs and ready
messages alone cannot start it. Automatic failure retains manual retry; repeated
ready/wake events do not create a retry loop. Late attachment
retries an in-flight or timed-out probe. Start failures leave “Connecting…” and
permit retry, without creating a backend lease for an unattached window.

Overview polling opens one SQLite transaction, sweeps leases once and selects
operation metadata without media/input payloads. Pending counts cover all the
actor's work beyond the recent 30-operation window and active connections precede
stopped ones. Rows and action buttons retain DOM identity across heartbeats.
Reads are serialized, concurrent invalidations
coalesce into one trailing read, hidden documents and shell-hidden frames pause
and failures back off. The frontend consumes authenticated parent
`maverick.app.visibility-changed` events and refreshes immediately on return;
data invalidations cannot restart reads while hidden. An inline HTML head script
applies initial shell theme parameters before the first paint, independently of
bundle loading; `maverick.shell.theme-changed` events update the effective theme.
Visible views refresh at 3 seconds for pending operations, 10 seconds for active
Chrome connections and 30 seconds when idle. Chrome transport
continues its independent heartbeat while management is hidden, renewing its
app-frame authentication at most once per minute. Renewal has a five-second
timeout and runs independently of the command loop; a hung renewal cannot prevent
subsequent heartbeats. The connector status shows the installed Companion version.
Setup is single-flight and
stopping it fences and revokes a late lease. Automatic revocation reports the
stopped state to the UI so reconnect controls become available again.
The stopped report retains the original error instead of replacing it with a
generic message. A bounded diagnostic reason is persisted on the owned lease and
exposed to management/agents; repeated stops preserve the first cause. Versioned
SQLite migration adds that field without changing existing scopes. Empty stopped
or offline tabs never advertise readiness for navigation.
The progress heartbeat captures the active command before awaiting its status.
An `operation_not_running` race cancels/drains that task without revoking the
connection or cancelling unrelated queued work. Bridge scope failures revoke on
the first response using their structured error code, independently of friendly
setup guidance. Successful observations publish their approved source URL in the
same transaction as completion, so a read immediately after first navigation does
not see the previous empty-tab heartbeat.

Public research carries the human actor through session creation, observations,
cleanup and audit. Session state retains broker activity and expiry timestamps
so management can omit expired sessions. Result text is escaped, source links
accept only HTTP(S), and raw JSON is rendered lazily with base64 media omitted.
Screenshot/video-frame views decode Companion `base64` and Lab `encoding:base64`
`data` as bounded raster blobs, released when the dialog closes. Video analysis
shows sample times, captured duration/audio and Storage links for saved frames;
it does not request another app's protected media routes. Collections expose
items, per-page progress, stop reasons and coverage independently of raw JSON.

Management verification includes 81 Python tests (including the built document
and public ZIP through Core's real ASGI app-frame bootstrap/authorization), 52 Node
tests, an offline Chromium UI fixture (row focus, errors, cancellation, filters, result escaping,
public-page form, 320/390px layout, image/video/collection rendering and blob
cleanup), a cross-origin shell fixture with platform-served bundles, a protected
document and public hashed ZIP, light first paint while the bundle is held pending,
initial/live themes, unattached-window guidance, late bridge readiness and
hidden-frame polling. A production-manifest Chrome popup fixture uses only
`activeTab` to identify the selected platform, with no pre-granted host access,
and covers Chrome/Maverick page rejection, an empty agent-tab launch, the six exact
optional platform host groups and invalid connector guidance.
The real Chromium/MV3 Companion fixture uses Core's actual immutable identity
and message relay plus the native iframe sandbox/CSP, with Connectors, empty-tab
connection, cross-platform navigation/capture and scope revocation. This fixture
starts with no Maverick cookies, downloads the archive before login and compares
it with the built package. The user then signs in through the shell, bootstraps
an isolated-origin Strict cookie and attaches Companion to the exact Browser
document. Direct platform app documents and unbootstrapped private frames are
rejected. Authenticated Maverick
inspection verified desktop/mobile hosting, a public-page read with automatic
cleanup, sidebar suppression and the native globe in the rail and App Store.
Review corrections were additionally checked on the mounted app: the isolated
connector document returned 200, initial light parameters applied, and switching
to Settings stopped Browser requests for an observed interval over 40 seconds.
After the fresh-profile correction and backend restart, an anonymous download
on `maverick.loopino.ai` returned 200 with ZIP MIME type and immutable cache
headers; its bytes matched the generated package. Authenticated inspection of
`/app/browser?connector=1` verified the stable copied address, setup instructions
and visible Connect controls in the mounted isolated Browser frame.
The 0.4.2 refinement was also inspected on the mounted shell: a manually opened
connector showed the current installation guide, kept Connect disabled and
explained how to share the platform tab. Its anonymous ZIP returned 200 and
matched the generated package. The complete fixture passed text/scroll, image,
video, audio, Storage evidence, cancellation recovery and Connectors workflows.
Companion 0.5.0 additionally passed an actual action-popup launch from Chrome New
Tab with production permissions, followed by an empty dedicated-tab connection in
the full fixture. That connection navigated across X and Instagram, read content,
captured the static X page, produced distinct sought video frames and recorded
audio. Leaving approved platforms revoked it. Mounted authenticated inspection
confirmed the new setup guide and readiness controls; an anonymous download
returned 200 and matched the generated 0.5.0 archive byte for byte.
The Companion fixture does not establish access to a real authenticated profile.
The 0.5.2 correction adds actor-owned stop diagnostics, migration from both earlier
schemas, exact-origin Browser-tab reuse and a regression for a hung authentication
renewal. The Chromium fixture verifies reuse without another Maverick window,
removal of the connector launch parameter and command delivery while the selected
shell navigates to Chat and hides its retained Browser document. Native mounted
inspection confirmed that the Browser rail action removes the launch parameter,
the updated stopped/offline guidance and the 0.5.2 setup/download. The public ZIP
returned 200 and matched the generated package. Live human-owned Chrome checks
observed an extension-unavailable stop and a later 0.5.1 heartbeat lapse; the tab
probe stayed queued and was cancelled without revoking the human's connection.
Those failed live probes are not successful page observations. The final release
still needs a fresh human connection before live platform access can be confirmed.
The 0.5.3 setup removes copy/paste on the official installation, owns consent in
the service worker and reuses Maverick even when another app is visible. A real
human-owned 0.5.2 connection completed a tabs probe on its empty agent tab, confirming
live transport; no real authenticated platform content was requested. The separate
Xvfb Chromium `--permissions` fixture uses the unmodified production manifest,
closes the action popup before granting Chrome's native permission dialog and
requires sharing and authenticated auto-connect to continue after that one click.
The normal fixture separately verifies reuse from Chat and automatic connection
without a Browser button press. Neither fixture proves access to Instagram accounts.
Final live inspection after the rebuild returned `app_frame_authority_stale` in
the isolated Browser document, so acceptance on the mounted installation remains
unconfirmed. The earlier human Chrome connection later became offline. The official
`core.recovery.restart_backend` attempt reported `restarted: false` because this
host has no systemd init; it reported backend health as true. No alternate process
restart was performed. Recovery of the live frame authority and a fresh 0.5.3
human connection remain necessary for final installed-flow verification.

## Ownership, transport and queues

Connection and operation metadata lives in workspace-owned SQLite at
`data/browser/companion.sqlite3`. Rows retain workspace/user ownership, hashed
connector secrets, finite queue deadlines, single-claim leases and callback state.
Only authenticated human backend setup can create a connection, poll commands or
submit observations. CLI/MCP projections never include connector credentials.

Agent reads enqueue an operation and return its id with `queued` status, rather
than claiming data has already been observed. `browser_operation_get` returns
progress and terminal results; `browser_operation_cancel` fences subsequent
completion. The connector retains its active operation until the extension has
finished audio cleanup and video restoration; a cancellation acknowledgement alone
does not release that operation. The worker's active-operation status also prevents
another claim after a local bridge timeout.
There are at most 16 pending operations per connection. Heartbeats
refresh the 120-second connection lease; claimed work requires progress within
60 seconds and has a 600-second total deadline. Terminal observations expire
after roughly one hour and are bounded to 256 records/64 MiB.

Authenticated results retain personal-data provenance and remain untrusted input.
A shared session's identity does not make its observations public-source evidence.
Every command is tied to the shared tab, approved URL and Chrome document id.
A page replacement during observation fails the operation. Explicit navigation
resets that document binding. Server Lab egress policy is not claimed to govern
the user's Chrome; Chrome loads ordinary platform subresources using its existing
session, while extension commands only target approved top-level platform routes.

## Observation and collection contract

The companion admits fixed navigate, snapshot, rendered-content, scroll,
screenshot, video-frame, tab and wait observations. Existing platform tabs bind
navigation to the platform inferred at sharing. Dedicated agent tabs permit
navigation across the user-approved list. Reviewed exact HTTPS
hosts, routes and retained source query keys live in `companion/platforms.json`,
with a generated Chrome module and a matching Python validator. Instagram,
X/Twitter, Reddit, Facebook, LinkedIn and YouTube are scoped independently. Login,
challenge, messages,
settings, credentials and normalization tricks are rejected. Authentication and
checkpoints remain user actions in Chrome. Likes, follows,
messages, posting, uploads and form filling have no companion command.

Rendered extraction omits form values and cookies, deduplicates URLs, retains only reviewed source query keys and removes
fragments and reports timestamp, coverage and truncation. Layout visibility
is not a viewport or occlusion guarantee. Scrolling selects a rendered scrollable
container or the document, with bounded steps and settling. A current scroll
boundary never proves that an infinite feed is complete.

The dependency-only `content.collect` observes one or two same-platform URLs,
deduplicates canonical content links across up to 40 batches and 200 items, and
reports page observations, timestamps, sections and stop reasons. It stops on
limits, rendered end, login, challenge or rate-limit indications. Sections split
remaining scan/item budgets, reserve capacity for later sections and report skipped
sections explicitly. An overall rendered end requires every requested section to
reach its observed boundary. Connectors constructs the Instagram profile/Reels
workflow and opens links individually before recording their content as read.
The former public Instagram collection tool has been removed.

Platform-tab screenshots use Chrome `captureVisibleTab` with the explicitly shared tab active,
rate limiting and before/after window/tab activation guards. Dedicated agent tabs
use `ImageCapture.grabFrame` on their already bound `tabCapture` video track; this
continues across platform navigation without requiring all-URL screenshot access
and handles static pages that emit no new video callback.
Both paths fence the source document before and after capture. Track letterboxing
is removed when cropping videos so their aspect ratio and rendered bounds remain
correct. Video frames require
the selected video to fit in the viewport; an offscreen document crops the captured
JPEG to its rendered bounds. Seeking waits for a newly presented decoded frame
at the requested time, reports the observed media time and restores prior video
playback state. A briefly muted playback may be needed to refresh Chrome's
compositor. A default single-frame capture seeks to zero when the selected video
has already ended; video analysis always prepares from zero. The original position,
including an ended position, remains part of the state restored afterward.
Captures can bring the shared platform window to the foreground.

`browser_video_analyze` samples 1–12 frames over a finite duration bounded to
180 seconds. Tab audio comes from Chrome `tabCapture`, with a worker-issued stream
id consumed by the extension's offscreen document. Audio is routed back to the
user's output and recorded as bounded Opus/WebM while the selected video plays.
Audio start/end times, sampled frame times and truncation describe actual coverage.
Media failures are explicit; one frame does not establish whole-video coverage.

## Media dependencies

With `save_evidence: true` (default), Browser hands validated JPEG/WebM bytes to
its declared Storage `file.content.write` dependency under
`storage/generated/browser/<operation_id>/`. Only verified callback identities
add file ids, paths and deep links and remove inline media bytes. Source URLs,
observation times and content hashes accompany saved evidence.

Audio is transcribed through the declared Speech dependency with `local_only: true`.
That finite transcription policy forces faster-whisper or whisper.cpp, excludes
remote vendor configuration/secrets and preserves workspace preferences. Browser
rejects a callback claiming a remote engine. Unavailable local transcription is
reported explicitly. Callbacks require the trusted Core dependency-callback
surface, matching workspace, request id, alias and original request. Cancelled,
expired or replayed callbacks cannot overwrite observations.

Agents must inspect actual images through Storage/native image tools before
making visual claims. Captions, transcripts and web page instructions remain
untrusted evidence, distinct from the agent's interpretation.

## Managed Lab lifecycle and audit

`browser_session_create` opts into Core's `platform_browser_sessions` app
capability and `platform_browser_session` MCP execution metadata. Core issues a
distinct four-hour `maverick_session` for the trusted runtime owner, current
workspace and configured platform origin. A digest of active human login session
IDs binds delegation to the user's current login generation. Only the private
entrypoint payload and broker receive the opaque cookie. The public result
exposes `platform_origin`, ownership and lifecycle metadata, never the cookie.

The broker installs a host-scoped HttpOnly cookie into the fresh RAM context.
Delegated policy permits the exact platform origin and Core-generated app-frame
hosts; sandbox agents receive no general loopback exemption. The broker enforces
user/workspace ownership on every session action. Other agents of that same
actor and workspace can use the context. Interactive actions still require
`maverick_dev_inspector` and a permitted active page and target URL.

HTTP session resolution and isolated app-frame validation recheck human login
generation, active user, active workspace and originating runtime. Delegated
cookies never renew. Workspace changes, human logout/password reset, runtime
termination and the four-hour limit invalidate access. Explicit close, idle/hard
expiry and broker shutdown log out the delegated cookie before destroying the
context and proxy. That logout revokes only its own app-frame leases and leaves
the user's human login and device sessions intact. Failed context creation
revokes the issued login. External sites remain anonymous unless separately
shared through Companion. Authenticated UI inspection uses MCP; standalone CLI
development smoke remains anonymous.

The isolated Playwright Lab retains governed DNS, redirect and subresource egress,
trusted caller policy, finite sessions and admin development-target exceptions.
Pinned Playwright 1.60.0 and the installation's supported Node runtime are used.
Core install, migration, background and recovery hooks manage Browser's worker
inside Core's service cgroup. The worker supervises and reaps broker/Playwright
children, restarts failed children and rotates bounded logs. A private Unix socket
provides status and stop. Administrator stop disables automatic recovery.
Readiness requires both supervised children to be alive and the broker connection
to succeed. Failed wrappers and shutdown cleanup terminate their entire process
groups, including a run-server grandchild that outlives its wrapper.

Installation-local infrastructure resides in `runtime/browser/`; credentials and
runtime state are excluded from Git. This deployment's backend filesystem namespace
cannot resolve app sources through host systemd units. The app-owned Core lifecycle
replaces that incompatible deployment path. Agent-owned builds and tests stay
foreground and terminate their descendants.

Core's reviewed execution closure includes Browser's Python controller, Node
broker, companion scope data and source/build artifacts, frontend, hooks and dependency pins.
Exact descriptor/execution audits must be refreshed after executable changes.
Only records for reviewed changed apps are updated; unrelated app digests remain
unchanged.

Authenticated development inspection uses the named `maverick.localhost` platform
host on the existing allowlisted ports 8000 and 8014, including Core-generated
`af-<24 hex>.sidecars.maverick.localhost` app frames. Only these exact labels inherit
the named host/port permission. All require the existing administrator inspector
authority; other localhost hosts, sidecar labels and ports remain denied. Core and
the Node proxy enforce the same target grammar. A proxy CONNECT to an allowlisted
HTTP dev port is resolved with its declared HTTP permission so plaintext WebSocket
connections work. Public HTTPS and other private destinations retain their checks.

## Open-source sources

- [Microsoft Playwright](https://github.com/microsoft/playwright), Apache-2.0:
  the existing pinned browser engine and reference extension source.
- [Playwright MCP](https://github.com/microsoft/playwright-mcp), Apache-2.0:
  reviewed as a connection reference; its unrestricted agent server is not enabled.
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper), MIT, and
  [whisper.cpp](https://github.com/ggml-org/whisper.cpp), MIT: existing local
  Maverick Speech engines. Browser does not introduce a remote speech provider.
- [Chrome tabCapture](https://developer.chrome.com/docs/extensions/reference/api/tabCapture),
  [offscreen](https://developer.chrome.com/docs/extensions/reference/api/offscreen),
  [tabs](https://developer.chrome.com/docs/extensions/reference/api/tabs) and
  [alarms](https://developer.chrome.com/docs/extensions/reference/api/alarms):
  platform APIs used by the app-owned adapter; this introduces no third-party relay.

Instaloader and mcp-chrome were evaluated as alternatives but are not dependencies.
The shipped companion is Maverick source, with pinned frontend dependencies.

## Acceptance and evidence

Focused tests cover actor/workspace separation, human-only setup, secret
projections, queue/lease expiry, cancellation, prohibited commands, strict URLs,
verified Storage/Speech callbacks and rejection of remote transcripts. A foreground
real Chromium/MV3 fixture test exercises content, nested scrolling, temporal video
frames, tab audio, Storage evidence, collection, revocation and desktop/mobile UI.
Its intercepted pages do not prove access to Instagram.

The official Speech surface has transcribed both a known WebM sample and the
extension's actual captured audio with local `faster-whisper`, despite the
workspace's remote-engine preference. The captured sample contains the expected
spoken phrase. This verifies finite tab audio capture and local processing.

An unauthenticated request to `https://www.instagram.com/martagiunti/` returned a
login redirect on 2026-10-06; isolated Chromium failed with `net::ERR_EMPTY_RESPONSE`.
Those observations established an access gap at that date, without diagnosing
its cause.

On 2026-10-12, the user's actual shared agent tab completed tab inspection,
navigation to `https://www.instagram.com/` and a bounded rendered-content read
from the signed-in feed. A second read about 40 minutes later also completed,
after the frontend rebuilds. This confirms the live Chrome transport and feed
access; it does not establish complete feed coverage or Reel/audio analysis.
The installed user extension was 0.5.3 during this check. The new 0.5.4 package
was verified separately in disposable Chromium: native dark/light action popup,
keyboard focus, restricted/ordinary page launch, empty-tab reuse, automatic
connection, cross-platform reading/capture, native consent after popup closure,
return to the already shared tab and reconnect preserving its page with no
duplicate tabs. Both app UI suites, 52 Node tests, 81 Python tests and focused
public-source/execution-closure checks passed. Mounted authenticated desktop
and 390px mobile inspection showed the new Agent tab/Activity UI and the live
Instagram connection. Anonymous download returned 200 with bytes matching the
generated 0.5.4 ZIP.

The 0.5.5 regression pass on 2026-10-12 completed 86 Browser Python tests,
54 Node tests, both desktop/mobile UI suites, the full Chromium media/Connectors
fixture, and the production-permission native-consent fixture. The latter two
now assert old-lease revocation, absence of false Connected state after Disconnect,
reuse of the navigated source and explicit reconnection without duplicate tabs.
Schema-v2 migration, pending-work cancellation, six successive reconnects at
capacity, and tab/actor/workspace isolation have focused backend coverage. The
anonymous public 0.5.5 ZIP returned 200 with bytes matching the built artifact.
The Browser execution-closure test and unused-import check passed. The global
CLI/MCP metadata suite retains three failures from unchanged HEAD descriptors
and baseline authority mismatches (including Agents/Storage); those surfaces
were not changed by this regression fix.

A full profile/media acceptance still requires verifying profile identity,
bounded feed collection, opening collected posts/Reels,
actual captions/images/frames/audio, Storage evidence and local transcription.
The resulting profile analysis must state observed sources, missing information
and coverage. Fixture success alone cannot complete that acceptance.

## Connectors dependency boundary

Connectors calls Browser only through `browser.lab` dependency requests. Core
forwards the authenticated initiating `user_id` to the provider and callback;
request-body identity fields do not authorize access. This keeps Chrome sessions
owned by the human actor. Public research reads rendered content rather than
only an accessibility snapshot and returns bounded text, links and provenance.
Platform workflows and their verification are documented in
[`platform_connectors_architecture.md`](platform_connectors_architecture.md).
