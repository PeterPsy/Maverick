# OpenWA operations

## Provider boundary

The native app runs through Loopino's official SDK entrypoints. Its persistent WhatsApp provider is a separate, operator-owned process bound only to `127.0.0.1:2785`. The current governed HTTP sidecar has no outbound network, so it cannot host a WhatsApp browser. The app does not change that policy.

`provider/local_gateway.py` launches the pinned provider with bubblewrap: private user, PID, IPC and UTS namespaces; read-only source/system mounts; a private writable data directory; and a temporary filesystem. It deliberately retains host networking for WhatsApp. This is filesystem/process isolation, not a network sandbox. The app validates and pins public remote gateway addresses separately.

Source belongs to `/projects/loopino/apps/openwa` on `design`, not the workspace app repository. The default workspace is bound to the registered platform source. PM2 uses the private `workspaces/default/data/openwa/supervisor` namespace and a minimal environment. Provider state remains under `workspaces/default/data/openwa/gateway`; app configuration and actor-scoped notification receipts remain in `data/openwa/app.sqlite`. The provider's linked-device profile is private engine-owned state. Do not expose or export it through app tools.

## Install and maintain

Run the source installer from the Loopino root repository. It is pinned and idempotent. Bootstrap is only for a fresh provider database; it refuses an initialized database. Skip both provisioning commands when restoring the already initialized default provider.

```bash
python3 apps/openwa/provider/install_upstream.py
python3 apps/openwa/provider/bootstrap_local.py
```

Use the installed app's native CLI for authorized provider maintenance. Only the trusted platform administrator in the default workspace can invoke these operations, and they require no API key delivery:

```bash
loopino app openwa cli run provider --action status --json
loopino app openwa cli run provider --action start --json
loopino app openwa cli run provider --action restart --json
loopino app openwa cli run provider --action stop --json
```

The `default` installation is already bootstrapped. Check provider readiness before use; do not bootstrap it again. Bootstrap creates the API key in memory, stores it through Core Secrets, grants the logical `openwa-api-key` to the declared app surfaces, and initializes the provider's hashed key record. It suppresses plaintext key-file creation and banner output. Ongoing provider launches need no raw key in their environment. Gateway credentials are managed directly in Vault. To switch providers, preserve the local provider credential, bind the new credential to `openwa-api-key`, and retain the declared backend/CLI/MCP grant targets before saving the new gateway URL. The app does not rotate or replace Core secrets from its settings screen.

The health hook verifies that `app.sqlite` exists and calls the configured gateway’s `/api/health/ready` with a bounded, credential-free request. An unavailable process, failing provider database or invalid readiness response reports `ok: false`; a linked phone is not required for provider readiness. Start/restart wait for `/api/health/ready`. PM2 restarts a crashed process with a five-second delay and a 600 MB memory limit.

Start/restart atomically persist recovery intent in private `provider-control.json`. The existing generic `backend_recovery` and `background_tick` hooks restore the dedicated supervisor after Loopino restarts or the supervisor disappears, while retaining the initialized database and linked-device profile. Background checks request a 30-second cadence; failures back off to 60 seconds. Missing intent never starts a provider or bootstraps a database. Stop persists disabled intent before stopping the dedicated process, and recovery rechecks it under the same lock. Read-only status does not spawn a supervisor. No system-wide startup unit is installed; recovery requires Loopino to be running. The host operator can also use `python3 apps/openwa/provider/manage.py <action>` when native app invocation is unavailable. Do not restart Loopino's shared backend or another PM2 namespace for OpenWA maintenance. A second workspace needs its own port, supervisor name and Core credential; these local scripts intentionally target default only.

## Source and local patches

The provider is OpenWA 0.24.0 at revision `8a45366a287750cf52c2658b0b783747cf51fad2`. Its downloaded source, dependencies and build live in ignored `provider/upstream/`; installation provenance is written there. The reviewed dependency tree is preserved in `provider/provider-package-lock.json` and installed with `npm ci`. Provider source uses `provider/` because generic app promotion excludes reserved runtime directories. See the accompanying license notice and [SOURCE_INVENTORY.md](SOURCE_INVENTORY.md).

The reproducible installer binds NestJS to loopback, suppresses bootstrap plaintext key files when `API_MASTER_KEY` is supplied, masks the key banner, and overrides `music-metadata` to 11.16.0 to address the dependency advisory found during installation. It builds the API without enabling the upstream dashboard, Docker manager, plugin console, Swagger or upstream MCP service. The Loopino app exposes only its own declared operations.

The provider uses the wwebjs engine, SQLite and bounded concurrent sessions. Its opt-in session-age send governor is disabled for this personal linked-device installation: linking an established account creates a young provider session, and synchronised outgoing history also spends that governor's daily allowance. This could refuse the first app send even though the user had sent nothing through Loopino. The upstream HTTP rate limits and typing delay retain their defaults. Optional Redis, queue and cache services are disabled for this installation.

## Verification and limits

```bash
python3 -m unittest discover -s apps/openwa/tests -v
loopino core cli run core.app-sdk.validate --app-root /projects/loopino/apps/openwa --json
loopino core cli run core.app-sdk.status --app-id openwa --workspace default --json
loopino app openwa cli run openwa --action sessions.list --json
```

The native and frontend regression suites cover provider readiness, transport status preservation, timeout/remount, quoted replies, uncertain/in-progress conflicts, recovery, concurrent refreshes, cancelled pages, gateway/credential changes, QR failures, shell theme/navigation and notification isolation. A cold first browser start can outlast one HTTP request; the app observes the live session state rather than starting a second job.

Browser sends persist one unresolved attempt per user/workspace/gateway/session/chat before dispatch, including exact text, quote, key and first-attempt time. Reopening or reloading restores it. Reading messages clears only read errors. `IDEMPOTENCY_KEY_IN_PROGRESS` permits a retry with the same key; `IDEMPOTENCY_OUTCOME_UNKNOWN` and other uncertain 409 sends produce deduplicated actor-scoped central inbox notices and explicit chat-check recovery. A new key requires confirming that the earlier message is missing; preparing it does not dispatch. Retries stop after 23 hours, before the provider’s 24-hour key expiry. Browser storage is device-local, and unavailable or invalid storage blocks sending. CLI/MCP callers must retain their supplied key and check the chat before choosing a new one. Incoming messages refresh in the visible app; background incoming-message push and OS push are not implemented.

HTTP 429 pacing refusals preserve the allowlisted `SEND_PACING_LIMITED` code and receive a distinct send-allowance explanation. Provider payload text stays redacted. Browser attempts retain response status/code so a limit refusal offers the same-key retry without uncertain-delivery recovery controls. Existing saved generic 429 warnings receive the same presentation without changing their text, retry key or first-attempt time. This presentation never clears a saved attempt or dispatches it automatically; expired keys still require recovery.

## Read scheduling and error recovery

Message lists deliberately omit inline media so polling stays bounded. `messages.image`
(MCP `openwa_messages_image`) reads one stored image through the authenticated provider
media endpoint using the exact session, chat and returned `waMessageId`. It returns
`mimetype`, `size_bytes` and `content_base64`; `max_bytes` defaults to and cannot exceed
4 MiB. Only JPEG, PNG, WebP and GIF are accepted. Redirects, active content, empty or
oversized bodies and missing media fail explicitly; provider error bodies and keys
are never forwarded. The image stays in browser memory and is not automatically
saved to Storage. Navigating away cancels the browser read. Revoked, expired or
never-stored media cannot be recovered by this operation. No provider restart or
private database access is required.
Native CLI callers consuming bytes must request `LOOPINO_RUNTIME_CLI_OUTPUT_PROFILE=full`
for that call; generic text compaction is not a binary transport. Consume the JSON
directly into an image viewer or Storage without logging the base64.

The image-read change passed 45 backend and 51 frontend tests, SDK validation
and the official frontend build. The selected real 134,856-byte JPEG was read
through the native CLI and rendered in the mounted app at 1440×1000 and 390×844.
No WhatsApp message was sent and the provider was not restarted.

The browser bounds every backend request to 28 seconds. Read-only requests accept cancellation signals and discard cancelled results. Polling waits for completion, coalesces repeated refresh requests into one follow-up read, and cancels on hiding, offline state, superseded queries or teardown. Status/resources use a 10-second interval, messages 8 seconds and linking QR 5 seconds. Failed reads exponentially increase that delay up to 60 seconds; a manual retry or visibility resume resets the delay. Resource and message polling stop when the gateway is unavailable; messages also require a ready session. Mutations use neither the read scheduler nor visibility cancellation. A send timeout retains the original attempt and warns that delivery may already have happened.

Query changes clear old rows immediately, while failed refreshes of the same query retain their rows. Resource errors have their own retry action and cannot be dismissed by unrelated successful status reads. Tab changes reset pagination in the same state update. Confirmed sends clear the attempt independently of message reads and return to the newest page. Synchronous dispatch guards prevent duplicate submissions before React can render the busy state.

Provider HTTP failures retain their actual status even when an intermediary returns HTML or an empty body; arbitrary provider text remains redacted. Empty 204/205 successes are accepted. Notification inbox reads use app-owned SQLite indices. Retention is bounded to 1,000 records per actor, so another actor's activity cannot prune an unresolved notice. These additive indices are created when opening existing databases and require no data reset.

## Native presentation and review evidence

The app owns a dedicated WhatsApp compact SVG and transparent PNG. The registry supplies that asset to rail and App Store; the native compact-image renderer uses its alpha silhouette with the surface's theme colour. The silhouette was visually inspected in the desktop rail and the OpenWA App Store card, including native light-on-dark and dark-on-light icon frames. The central inbox displayed the real "OpenWA connected" notice through the mounted backend.

The initial October 2026 review observed a ready linked session and a real chat list before the platform backend restart. After that restart, no provider process was listening on `127.0.0.1:2785`. The mounted app was inspected at desktop 1440×1000 and mobile 390×844, including the outage state, desktop dark/light themes, mobile shell clearance, and gateway settings. Tab focus cycled inside the dialog, and Escape restored focus to the settings button.

On October 13 the existing provider was restored from the root source without bootstrapping or changing its account. Its readiness probe and authenticated native session/chat reads succeeded: the saved session was ready and a bounded chat page returned successfully. Installation and the official frontend build now resolve the platform source in the design repository. The 37 native and 40 frontend tests passed, including recovery after supervisor loss, explicit-stop persistence, scope checks, credential-free supervision and CLI routing. Recovery regressions simulate process loss; Loopino's shared backend was not restarted to exercise them. Send regressions use simulated responses; no WhatsApp message was sent during this review.

The subsequent send-refusal investigation found a configured allowance of 40 against 96 counted outgoing rows, including synchronised history. The session-age governor was disabled, the dedicated provider restarted, and its live process configuration verified; the existing linked session returned ready. The 39 native and 45 frontend tests passed, including pacing-code redaction and same-key recovery for existing rate-limit warnings. The official frontend build and focused unused-import check passed. Actual WhatsApp sends were not used for verification.
