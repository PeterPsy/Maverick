# OpenWA for Loopino

A native Loopino app for WhatsApp sessions, contacts, conversations and text messaging, powered by [rmyndharis/OpenWA](https://github.com/rmyndharis/OpenWA). The app uses Loopino authentication, Core Secrets, the central notification inbox and declared CLI/MCP operations.

## Use the app

Open `/app/openwa`, select a session and choose **Manage session**. Start it and scan its QR from WhatsApp's **Linked devices**, or request a phone linking code. Once the session is ready, select a conversation to read and send messages. Unconfirmed sends and replies retain their exact text, quote and idempotency key in browser storage across reopening or reloading, scoped to the user, workspace, gateway, session and chat. Message refreshes never dismiss their warning.

Retry an unconfirmed send with **Retry same send**. If the provider reports an unknown outcome, check the chat and choose **I found the message**, or **Prepare a new send** and confirm that the message is missing. Preparing keeps the draft and requires another press of **Send**; it never sends automatically. Keys older than 23 hours require this recovery because the provider forgets them after 24 hours. Recovery is local to this browser; clearing its storage or switching devices does not restore the attempt.

An active send or retry shows **Sending…**, with recovery warnings hidden until its request settles. The attempt is still saved before dispatch. A failed request or a restored unconfirmed attempt shows the recovery warning; confirmed success clears the saved attempt and draft. Starting a retry replaces the previous failure explanation while keeping its exact text, quote, retry key and first-attempt time.

The default workspace has a dedicated local provider at `http://127.0.0.1:2785`. Administrators can configure another public HTTPS OpenWA gateway in the app after binding its key through Vault. API keys go through Core Secrets; app configuration stores only connection metadata. Remote private addresses, redirects and URL credentials are rejected.

The app supports session creation/start/stop/logout, QR and phone pairing, bounded chat/contact/message reads, image viewing, text sends/replies and read-only webhook/template inspection. Select **View image** on an image message to load it; captions remain visible. Incoming messages refresh while the conversation is visible and its session is ready. Connection and uncertain-send notifications appear in Loopino's central inbox.

Reads run one at a time per panel, schedule the next poll after completion, and stop when the app is hidden or offline. Repeated failures gradually increase the polling interval up to one minute; **Retry** and returning to the app refresh immediately. Every browser request has a 28-second deadline. Switching sessions, gateways, tabs or pages cancels obsolete reads and clears previous-query rows. A failed refresh of the current page retains its rows and presents a local retry action. Sending keeps its separate confirmation and recovery flow, including across navigation.

The interface uses app-owned Loopino dark/light tokens, neutral primary controls, compact session navigation and a search field labelled as filtering the current page. Connected indicators, unread counters and outgoing message surfaces use the monochrome palette; connected sessions omit the redundant `ready` badge, while linking and unavailable states remain visible. Text fields, including search, the composer and dialogs, indicate focus with a subtle neutral border. Keyboard focus on buttons and disclosure controls uses a thin inset line; controls have no external focus halo. Session navigation scrolls independently on desktop and horizontally on mobile. QR failures are visible and retryable; outdated QR images disappear on a failed refresh. A provider outage is presented separately from phone linking and disables unavailable session creation. Theme bootstrap runs before first paint, with live shell updates accepted only through the trusted parent relay.

Backspace deletes text in editable controls. On the page or a locked send draft it suppresses the browser's default history navigation, so deleting cannot leave the app. A locked attempt keeps its exact text until resolved through send recovery. Explicit browser navigation shortcuts retain their normal behavior.

## Integration

- Official SDK lifecycle and native React interface, with Loopino theme and mobile spacing.
- A dedicated WhatsApp silhouette in app-owned SVG and transparent PNG assets. Rail and App Store tint the same compact asset with their native theme colours, frames and spacing.
- Workspace-owned SQLite configuration and per-user notification receipts.
- Provider readiness included in the health hook, independently of whether a phone is linked.
- `whatsapp.workspace` and `notifications.inbox` contracts.
- Declared `openwa` and administrator-only `provider` CLI commands and 18 MCP tools, with effects and secret requirements. Provider maintenance does not request the WhatsApp API key. Core continues to decide whether a runtime may invoke them.
- A bundled `openwa-ops` skill. Sending requires authorization for the recipient and message; installation or account linking does not authorize messages.

The shared source lives under `apps/openwa` in the platform repository, registered as a forkable platform app. Inspect and preserve the active source branch (`loopino/phase1` for the clean installation); local `design` is historical predecessor evidence. Installation data remains in each workspace's `data/openwa`; moving the source does not reset an existing account. This local provider targets the `default` full-access workspace and runs independently of app entrypoints because WhatsApp needs persistent browser state and network access. An explicit provider start enables recovery through Loopino's backend recovery and background tick hooks; an explicit stop disables it. See [OPERATIONS.md](OPERATIONS.md) for lifecycle, isolation and verification limits.

## Validate

```bash
loopino core cli run core.app-sdk.validate --app-root /root/projects/loopino/apps/openwa --json
loopino core cli run core.app-sdk.status --app-id openwa --workspace default --json
python3 -m unittest discover -s apps/openwa/tests -v
cd apps/openwa && npm test
```

The provider is pinned to a specific upstream revision; license and local changes are recorded in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## SDK Flow

Validate shared source with `loopino core cli run core.app-sdk.validate --app-root apps/openwa --json`, then rebuild through `loopino app openwa frontend build --json`. The standard catalog packages this exact source with SDK validation and an immutable checksum manifest; tenant gateway configuration is excluded.

## Contract Notes

The app owns session navigation and disables the shell sidebar. Backend, CLI and MCP dispatch the same bounded actions with request-scoped credentials. Canonical `references.manifest` metadata works before gateway configuration and declares an empty entity set. Gateway login, pairing and real send/recovery behavior still require functional verification with newly entered credentials.
