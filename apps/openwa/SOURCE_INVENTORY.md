# Source inventory and native mapping

Reviewed source: `https://github.com/rmyndharis/OpenWA`, revision `8a45366a287750cf52c2658b0b783747cf51fad2`, package version 0.24.0, MIT. This is the NestJS OpenWA project named by the user; it is distinct from the open-wa automation library.

| Upstream surface | Maverick integration |
| --- | --- |
| NestJS REST API and API-key roles/scopes | Explicit Python domain adapter; Core-authenticated actor and Core-delivered API key; public HTTPS with DNS/address validation or exact dedicated loopback origin |
| Persistent WhatsApp sessions, default wwebjs engine and Chromium | Dedicated operator-owned local provider, linked-device state under its private data root; native session management and pairing UI |
| Sessions, chats, contacts and stored messages | Declared CLI/MCP reads, bounded pagination and native session/conversation panels |
| Text send/reply and upstream idempotency | Explicit declared mutations with mandatory idempotency keys; stable UI draft retries and uncertain-delivery notices |
| Webhooks and message templates | Bounded read-only native inspection; no webhook test dispatch or configuration mutations |
| React dashboard and upstream login | Replaced by the native Maverick interface and platform authentication; upstream dashboard is disabled |
| SQLite main/auth database and business database; optional PostgreSQL, Redis, queues and object storage | SQLite local provider plus separate native app configuration/notification database; optional external services disabled |
| Optional upstream MCP, plugin console and Docker management | Disabled; only the Maverick app's declared tool surface is exposed |
| Notifications and domain failures | App-owned deduplication and actor-scoped receipts, discovered by the central Maverick inbox |
| Engine-wide Baileys alternative | Upstream capability; not enabled or offered as a per-session setting in this installation |
| Multi-tenant proposal | Upstream design draft; not treated as an implemented isolation guarantee |

The reviewed provider has a much larger API than the native adapter. Media sends, bulk campaigns, groups administration, plugin installation and Docker control are outside this app's declared scope. Adding a feature requires its own contract, permission/effect classification, UI workflow and behavior verification; there is no arbitrary REST forwarding tool.

The new app uses the official SDK lifecycle and exposes `whatsapp.workspace` v1, `notifications.inbox` v1, native frontend, backend, CLI, MCP and a persistent workspace operations skill. It has no durable reference entities or custom view-state surface; QR challenges and phone linking codes are ephemeral authentication material.

Verification records and current acceptance limits are in `OPERATIONS.md`.
