# Browser Reading and Instagram Integration

Date: 2026-10-06

## Implemented architecture

Browser 0.3 extends the installation-level `apps/browser` app with an app-owned
Chrome Manifest V3 companion. Its fixed observation adapter reuses Browser's
rendered DOM reader. Instagram-specific behavior belongs to Browser; Core remains
app-agnostic. No commercial scraping, proxy, browser relay or speech service is
required. Browser's isolated Playwright Lab remains available for public research
and authorized Maverick development inspection.

The user shares one already authenticated Instagram tab from the extension popup.
The popup requests optional permissions for Instagram and the chosen Maverick
origin, then opens a dedicated authenticated Browser connector window. Chrome 120
or later is required. The connector uses ordinary Core-hosted backend calls and a
scoped content-script channel. Passwords, cookies, browser history, raw CDP,
selectors and arbitrary caller scripts are never exposed to agent tools.

The connector window must remain open. A 30-second extension alarm wakes its
poller when possible; alarms do not wake a sleeping computer and cannot guarantee
uninterrupted execution. Reloading requires fresh user setup. Closing either tab,
revoking sharing or leaving approved Instagram routes stops capture. Late connector
submissions cannot renew expired connections or complete expired operations.

## Ownership, transport and queues

Connection and operation metadata lives in workspace-owned SQLite at
`data/browser/companion.sqlite3`. Rows retain workspace/user ownership, hashed
connector secrets, finite queue deadlines, single-claim leases and callback state.
Only authenticated human backend setup can create a connection, poll commands or
submit observations. CLI/MCP projections never include connector credentials.

Agent reads enqueue an operation and return its id with `queued` status, rather
than claiming data has already been observed. `browser_operation_get` returns
progress and terminal results; `browser_operation_cancel` fences subsequent
completion. There are at most 16 pending operations per connection. Heartbeats
refresh the 120-second connection lease; claimed work requires progress within
60 seconds and has a 600-second total deadline. Terminal observations expire
after roughly one hour and are bounded to 256 records/64 MiB.

Authenticated results retain personal-data provenance and remain untrusted input.
A shared session's identity does not make its observations public-source evidence.
Every command is tied to the shared tab, approved URL and Chrome document id.
A page replacement during observation fails the operation. Explicit navigation
resets that document binding. Server Lab egress policy is not claimed to govern
the user's Chrome; Chrome loads ordinary Instagram subresources using its existing
session, while extension commands only target approved top-level Instagram routes.

## Observation and collection contract

The companion admits fixed navigate, snapshot, rendered-content, scroll,
screenshot, video-frame, tab and wait observations. Navigation accepts HTTPS
`www.instagram.com` profile, profile-Reels, post and Reel URLs. Login, challenge,
messages, settings, credentials and normalization tricks are rejected. The user
handles authentication or checkpoints directly in Chrome. Likes, follows,
messages, posting, uploads and form filling have no companion command.

Rendered extraction omits form values and cookies, deduplicates URLs, removes
queries/fragments and reports timestamp, coverage and truncation. Layout visibility
is not a viewport or occlusion guarantee. Scrolling selects a rendered scrollable
container or the document, with bounded steps and settling. A current scroll
boundary never proves that an infinite feed is complete.

`browser_instagram_collect` reads profile and optional Reels sections, deduplicates
canonical post/Reel URLs across up to 40 batches and 200 items, and reports source,
observation times and a stop reason. It stops on limits, rendered end, login,
challenge or rate-limit indications. Each collected post/Reel must be opened
separately before its full caption or media is analyzed. Unvisited, private and
unavailable content is excluded; missing counts and dates remain unknown.

Screenshots use Chrome `captureVisibleTab` with the explicitly shared tab active,
rate limiting and before/after window/tab activation guards. Video frames require
the selected video to fit in the viewport; an offscreen document crops the captured
JPEG to its rendered bounds. Seeking waits for a newly presented decoded frame
at the requested time, reports the observed media time and restores prior video
playback state. A briefly muted playback may be needed to refresh Chrome's
compositor. Captures can bring the shared Instagram window to the foreground.

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
broker, companion source/build artifacts, frontend, hooks and dependency pins.
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
Those observations establish an access gap, without diagnosing its cause. No real
Instagram feed or Reel has been inspected.

Final authenticated acceptance requires the user to share a logged-in tab, then
verify profile identity, bounded feed collection, opening collected posts/Reels,
actual captions/images/frames/audio, Storage evidence and local transcription.
The resulting profile analysis must state observed sources, missing information
and coverage. Fixture success alone cannot complete that acceptance.
