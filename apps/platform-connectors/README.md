# Connectors

Connectors is a native English Maverick app for reading platform content and
keeping private, refreshable collections. Instagram is the default source.
Explore, Collections and History work on desktop and mobile; agents use the
same backend through declared CLI/MCP tools.

## Sources

| Source | Implemented reader |
| --- | --- |
| Instagram | Shared Chrome profiles, posts, Reels, native search, bounded collection with individual post reading, video frames and local audio transcription. |
| X / Twitter | Shared Chrome posts, threads, profiles, search, collections and videos. |
| Reddit | Shared Chrome communities, discussions, rendered comments, profiles, search and videos. |
| Facebook | Shared Chrome pages, posts, groups, search, collections and videos. |
| LinkedIn | Shared Chrome profiles, companies, posts, jobs, search and collections. |
| YouTube | Pinned yt-dlp metadata/search, timed captions and bounded local audio transcription; optional shared Chrome for public-reader access failures. |
| RSS / Atom | Public feeds, summaries, dates, authors, enclosures and deduplicated refreshes. |
| Web | Browser Lab public search and rendered page reading. |
| GitHub | Public API repository README, issues/PRs and comments, profiles/repositories, search and issue/PR/release/commit collections. |

Collections record observed content and links, never promise complete account
history or unloaded/collapsed content. Publishing and account actions are absent.

## Connect Instagram

Open Browser, download Chrome Companion, extract it and load the extension in
Chrome developer mode. Sign in directly to Instagram and share that tab through
the extension with the Browser connector address. Press **Connect** in the
dedicated connector window and keep it open.

Refresh connections in Connectors and choose the shared Instagram tab. Enter a
profile URL or username and collect posts. Profile and Reels share finite scan
budgets; discovered links are opened with **Open each result to read its content**
enabled. Profile context is displayed separately. A discovered link is labelled
**Link found** until opened content has been observed. **Inspect video** saves
frames and requests local transcription. View actual frame files before visual
claims.

Chrome scopes are platform-bound. Authentication, challenges, permissions and
sharing stay with the user. No passwords, cookies, arbitrary scripts, forms,
account actions or messaging surface is exposed.

## Collections and limits

Save terminal observations, including partial cancelled/failed results. Refresh
repeats the original action and merges canonical URLs. Collections support search,
rename, delete, pagination and Markdown/JSON Storage exports. Exports preserve
transcripts, timestamps and provenance and return verified file identities.

Limits: 200 links, 40 scan batches, 200 detailed reads, 12 frames, 180 seconds
audio, 8 MiB per operation result, 12 active operations per actor and one active
operation per shared tab. Active work expires after 30 minutes; terminal history
retains at most 200 operations/32 MiB per actor. Collections persist independently;
a single export supports at most 5,000 items.

## Agent operations

```bash
maverick app platform-connectors mcp list --json
maverick app platform-connectors mcp inspect connectors_run_start --json
maverick app platform-connectors cli inspect platform-connectors --json
```

Start with `connectors_connections_refresh` and `connectors_status`. Start a read
with `connectors_run_start`, then poll `connectors_run_refresh` until terminal.
`connectors_run_get` only reads cached state. Cancel with `connectors_run_cancel`.
Queued/waiting work does not establish observation. Collection reference/view tools
are owner-scoped. See the bundled `platform-connectors-ops` skill.

## SDK Flow

Created through the official SDK, the app is installation-level source under
`apps/platform-connectors`:

```bash
maverick core cli run core.app-sdk.validate --app-id platform-connectors --app-root /home/ubuntu/projects/maverick-v3/apps/platform-connectors --workspace default --json
maverick app platform-connectors frontend build --json
```

Install/upgrade hooks initialize SQLite and install `yt-dlp[default]==2026.8.19`
into app-owned `data/platform-connectors/vendor`. Shared Python environments and
browser profiles are untouched. PyPI access, Node and ffmpeg are needed for the
managed media reader. Health checks verify schema and reader version.

## Contract Notes

The source-available app runs in full-access workspaces. Required dependencies:
Browser `browser.lab`, Storage `file.content.write`. Optional: Speech
`speech.transcription`, requested with `local_only: true`; unavailable local
transcription is reported. Anonymous source quotas/sign-in walls remain source
constraints. Private GitHub repositories are outside the public reader.

Private mode-0600 SQLite lives in `data/platform-connectors/connectors.sqlite3`.
Operations, connections, collections and views are authenticated-user scoped.
The request ledger stores fingerprints, never raw media or export payloads.
Source content is untrusted. The PWA inventory excludes personal observations
from offline persistence. Whole-app export/import hooks are intentionally absent;
collection export uses governed Storage.

## Verification

```bash
python3 -m unittest discover -s apps/platform-connectors/tests -p 'test_*.py'
node --test apps/platform-connectors/tests/source-navigation.test.mjs
PLAYWRIGHT_BROWSERS_PATH=/home/ubuntu/.cache/ms-playwright node --test apps/platform-connectors/tests/sidebar.browser.test.mjs
python3 -m unittest discover -s apps/browser/tests -p 'test_browser*.py'
npm --prefix apps/browser test
PLAYWRIGHT_BROWSERS_PATH=/home/ubuntu/.cache/ms-playwright npm --prefix apps/browser run test:companion
```

The real Chromium/MV3 product fixture uses intercepted Instagram-shaped pages;
it does not prove live account access. Installed surfaces verified public RSS,
GitHub and Web reads. Public YouTube acquisition encountered
an anti-bot sign-in wall; shared Chrome is an explicit fallback. Authenticated
source acceptance needs a user-shared tab.

Architecture: [Platform Connectors](../../docs/architecture/platform_connectors_architecture.md).

## Native UI

Connectors uses the current Maverick Storage/Agents token values in app-owned
styles, a monochrome accent, glass surfaces and consistent SVG source icons.
Its transparent compact identity is optically centred and padded for the rail
and App Store. Sources and the privacy note live in the app-owned
`connectors-sidebar` widget hosted by Base Shell at `shell.sidebar.primary`.
The shell sidebar is enabled; source selection opens Explore and closes the mobile
drawer. Main-panel shortcuts and deep links keep the selected source aligned with
the sidebar without reloading the app. All copy is English.
The catalog contains nine sources; the seven additional sources removed from the
requested screenshot are absent from executable descriptors and readers.

GitHub requests one bounded API page (at most 100 entries); result coverage and
truncation report the remaining source scope. A missing or inaccessible README
retains repository metadata with `content_observed: false` and an explicit source
error, rather than marking the description as read README content.
