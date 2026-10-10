# Platform Connectors

Date: 2026-10-10

## Ownership

`apps/platform-connectors` owns the nine-source catalog, workflows, private saved
observations, references, saved selections and backend/CLI/MCP operations for
agents. Browser owns Chrome sharing,
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
and persist independently of run retention. Backend/CLI/MCP share ownership checks,
CRUD, pagination, exports, references and standard view filters/curation.

Connectors is backend-only: `presentation.frontend_role` is `none`, the frontend
entrypoint is null, and widgets/mounted views are absent. It remains
installed and enabled for agents. Base Shell and App Store derive non-launchable
presentation from the generic contract. Chrome sign-in and tab sharing remain
in Browser/Chrome Companion. No frontend source, compiled assets, Node build chain
or app-owned shell navigation is retained.

Collection references expose owner-checked ids, summaries and resolved payloads
without app-page deep links. Core visual-reference entity/view declarations are
absent and the reference manifest is empty; collection search/resolve/summarize
remain direct agent tools. Saved query filters and curated selections remain
backend state available through agent tools. Storage exports/evidence retain their
Storage deep links. PWA offline persistence excludes personal observations.

Markdown/JSON exports go through Storage under
`storage/generated/platform-connectors/<run_id>/`; a matching verified identity
completes the export. Media evidence remains Storage-owned. Optional Speech is
requested with `local_only: true`; remote-engine callbacks are rejected. Lifecycle
hooks initialize schema and install pinned yt-dlp in app-owned `vendor/`.

## Verification and live acceptance

Tests cover source parsing, HTTP confinement, ownership, callback sequencing/replay,
bounded media, private references/views, collections and export identity. Browser
scope tests cover all platforms and parity. A real Chromium/MV3 fixture drives
the Connectors MCP entrypoint, Browser UI/extension, queue and Storage against
intercepted Instagram-shaped pages;
it does not establish live source access.

Installed surfaces verified RSS, GitHub and Web. Public
YouTube acquisition encountered an anti-bot sign-in wall. Authenticated Instagram
and other Chrome sources need a human-shared session for final live acceptance.
Coverage and source constraints remain explicit in results.
