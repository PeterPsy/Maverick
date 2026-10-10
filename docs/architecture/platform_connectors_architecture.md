# Platform Connectors

Date: 2026-10-10

## Ownership

`apps/platform-connectors` owns the nine-source catalog, workflows, private saved
observations, references/views and native English UI. Browser owns Chrome sharing,
fixed read-only transport, queues, media capture and public Lab research. Storage
owns exports/evidence; Speech owns local transcription. Consumers do not read
provider-private data.

Agent-Reach was reviewed as a workflow/source inventory. Its shell installer,
unrestricted upstream agent servers and cookie configuration are not imported.
Native adapters use declared dependencies, authenticated actors and app-owned data.
Core has no platform-specific reader. A generic fix forwards the initiating user
to dependency providers/callbacks. Hosted execution registration and the PWA
inventory include Connectors. Browser's exact closure includes platform policy
JSON and its generated Chrome module.

## Readers

Shared Chrome reads cover Instagram, X/Twitter, Reddit, Facebook, and LinkedIn. Connectors constructs native search
and profile URLs. Instagram collection requests profile/Reels sections, then
opens discovered posts individually. Link discovery and read content remain
separate; profile/source context is retained.

RSS/Atom and GitHub use bounded public HTTP/API readers. YouTube uses app-owned pinned yt-dlp, timed captions and
bounded audio; matching shared Chrome is an explicit fallback. Web search delegates to Browser research. The app README maps all sources to implemented actions.

Public readers reject credentials/private IPs/mixed DNS answers, pin connections
with TLS SNI, revalidate redirects and strip cross-host authentication headers.
Body sizes, redirects, subprocesses and audio duration are bounded. ffmpeg receives
local bytes, never an unvalidated remote URL. No cookie ingestion is supported.

## Durable operations

Actor-owned SQLite operations record source, action, validated parameters, phase,
result and optional Browser operation id. The request ledger records unique ids,
aliases, phases and SHA-256 body fingerprints. Core delivers authenticated callbacks
on a trusted surface. The consumer checks ownership, original request/alias/body
and pending state; replayed/terminal callbacks cannot restart work.

Browser initially queues Chrome commands. Refresh polls them and dispatches the
next navigate/read/media step. A multi-step workflow reserves its shared tab within
Connectors, preventing interleaved navigation. Cancellation fences future results
and asks Browser to cancel claimed work. Partial results survive errors and remain
savable. Limits include 200 items, 40 scans, 200 detailed reads, 12 frames, 180 seconds
audio, 8 MiB results and 12 active runs per actor. Active work expires after 30
minutes; terminal history retains at most 200 runs/32 MiB per actor.

## Persistence and presentation

Private mode-0600 `data/platform-connectors/connectors.sqlite3` stores operations,
request fingerprints, cached connections, collections/items and view state.
Canonical URLs identify items; collections retain the original action for refresh
and persist independently of run retention. UI/CLI/MCP share ownership checks,
CRUD, pagination, exports, references and standard view filters/curation.

The native English UI defaults to Instagram with Explore, Collections and History.
Responsive app-owned navigation, cancellation, coverage and results work on desktop
and mobile. Shell messages require the exact parent. Source text is rendered as
text; external images are linked. PWA offline persistence excludes personal data.

Markdown/JSON exports go through Storage under
`storage/generated/platform-connectors/<run_id>/`; a matching verified identity
completes the export. Media evidence remains Storage-owned. Optional Speech is
requested with `local_only: true`; remote-engine callbacks are rejected. Lifecycle
hooks initialize schema and install pinned yt-dlp in app-owned `vendor/`.

## Verification and live acceptance

Tests cover source parsing, HTTP confinement, ownership, callback sequencing/replay,
bounded media, private references/views, collections and export identity. Browser
scope tests cover all platforms and parity. A real Chromium/MV3 fixture drives
shipped UI, extension, queue and Storage against intercepted Instagram-shaped pages;
it does not establish live source access.

Installed surfaces verified RSS, GitHub and Web. Public
YouTube acquisition encountered an anti-bot sign-in wall. Authenticated Instagram
and other Chrome sources need a human-shared session for final live acceptance.
Coverage and source constraints remain explicit in results.

## Native presentation

The English frontend uses app-owned copies of current Maverick Storage tokens:
neutral accent, native font stack, glass surfaces, 22px cards and 18px controls.
Source navigation uses consistent inline SVG icons; the compact app identity is
neutral line art with transparent padding matched to rail and App Store glyph
sizes. Main-panel scrolling and compact mobile source navigation preserve the
shell content offset. Connectors is a self-contained research workspace with
`presentation.sidebar_enabled: false`; no shared shell implementation is imported.

App Store now enriches summaries with public icon metadata from the existing
active workspace registry, matching public identities and preserving explicit
catalog logos. This generic frontend change aligns its Connectors icon with the
rail without Core icon maps or contract extensions.
