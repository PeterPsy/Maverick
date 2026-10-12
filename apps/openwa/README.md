# OpenWA for Maverick

A native Maverick app for WhatsApp sessions, contacts, conversations and text messaging, powered by [rmyndharis/OpenWA](https://github.com/rmyndharis/OpenWA). The app uses Maverick authentication, Core Secrets, the central notification inbox and declared CLI/MCP operations.

## Use the app

Open `/app/openwa`, select a session and choose **Manage session**. Start it and scan its QR from WhatsApp's **Linked devices**, or request a phone linking code. Once the session is ready, select a conversation to read and send messages. Unconfirmed sends and replies retain their exact text, quote and idempotency key in browser storage across reopening or reloading, scoped to the user, workspace, gateway, session and chat. Message refreshes never dismiss their warning.

Retry an unconfirmed send with **Retry same send**. If the provider reports an unknown outcome, check the chat and choose **I found the message**, or **Prepare a new send** and confirm that the message is missing. Preparing keeps the draft and requires another press of **Send**; it never sends automatically. Keys older than 23 hours require this recovery because the provider forgets them after 24 hours. Recovery is local to this browser; clearing its storage or switching devices does not restore the attempt.

The default workspace has a dedicated local provider at `http://127.0.0.1:2785`. Administrators can configure another public HTTPS OpenWA gateway in the app after binding its key through Vault. API keys go through Core Secrets; app configuration stores only connection metadata. Remote private addresses, redirects and URL credentials are rejected.

The app supports session creation/start/stop/logout, QR and phone pairing, bounded chat/contact/message reads, text sends/replies and read-only webhook/template inspection. Incoming messages refresh while the conversation is visible. Connection and uncertain-send notifications appear in Maverick's central inbox.

## Integration

- Official SDK lifecycle and native React interface, with Maverick theme and mobile spacing.
- A dedicated WhatsApp silhouette in app-owned SVG and transparent PNG assets. Rail and App Store tint the same compact asset with their native theme colours, frames and spacing.
- Workspace-owned SQLite configuration and per-user notification receipts.
- Provider readiness included in the health hook, independently of whether a phone is linked.
- `whatsapp.workspace` and `notifications.inbox` contracts.
- One declared CLI command and 17 MCP tools, with effects and secret requirements. Core continues to decide whether a runtime may invoke them.
- A bundled `openwa-ops` skill. Sending requires authorization for the recipient and message; installation or account linking does not authorize messages.

This installation targets the `default` full-access workspace. The local provider runs independently of the app entrypoints because WhatsApp needs persistent browser state and network access. See [OPERATIONS.md](OPERATIONS.md) for its lifecycle, isolation, reproducible installation and verification limits.

## Validate

```bash
maverick core cli run core.app-sdk.validate --app-id openwa --json
maverick core cli run core.app-sdk.status --app-id openwa --workspace default --json
PYTHONPATH=../.. python3 -m unittest discover -s apps/openwa/tests -v
cd apps/openwa && npm test
```

The provider is pinned to a specific upstream revision; license and local changes are recorded in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
