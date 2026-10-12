# OpenWA operations

## Provider boundary

The native app runs through Maverick's official SDK entrypoints. Its persistent WhatsApp provider is a separate, operator-owned process bound only to `127.0.0.1:2785`. The current governed HTTP sidecar has no outbound network, so it cannot host a WhatsApp browser. The app does not change that policy.

`runtime/local_gateway.py` launches the pinned provider with bubblewrap: private user, PID, IPC and UTS namespaces; read-only source/system mounts; a private writable data directory; and a temporary filesystem. It deliberately retains host networking for WhatsApp. This is filesystem/process isolation, not a network sandbox. The app validates and pins public remote gateway addresses separately.

PM2 uses the private `data/openwa/supervisor` namespace and a minimal environment. Provider state is under `data/openwa/gateway`; app configuration and actor-scoped notification receipts are in `data/openwa/app.sqlite`. The provider's linked-device profile is private engine-owned state. Do not expose or export it through app tools.

## Install and maintain

Run these commands from the workspace repository. The installer is pinned and idempotent. Bootstrap is only for a fresh provider database; it refuses an initialized database.

```bash
python3 apps/openwa/runtime/install_upstream.py
python3 apps/openwa/runtime/bootstrap_local.py
python3 apps/openwa/runtime/manage.py start
python3 apps/openwa/runtime/manage.py status
python3 apps/openwa/runtime/manage.py restart
python3 apps/openwa/runtime/manage.py stop
```

The `default` installation is already bootstrapped. Check provider readiness before use; do not bootstrap it again. Bootstrap creates the API key in memory, stores it through Core Secrets, grants the logical `openwa-api-key` to the declared app surfaces, and initializes the provider's hashed key record. It suppresses plaintext key-file creation and banner output. Ongoing provider launches need no raw key in their environment. Gateway credentials are managed directly in Vault. To switch providers, preserve the local provider credential, bind the new credential to `openwa-api-key`, and retain the declared backend/CLI/MCP grant targets before saving the new gateway URL. The app does not rotate or replace Core secrets from its settings screen.

The health hook verifies that `app.sqlite` exists and calls the configured gateway’s `/api/health/ready` with a bounded, credential-free request. An unavailable process, failing provider database or invalid readiness response reports `ok: false`; a linked phone is not required for provider readiness. Start/restart wait for `/api/health/ready`. PM2 restarts a crashed process with a delay and a memory limit. No system-wide startup unit is installed: after a host reboot, an operator must run `manage.py start`. Stop affects only this provider. A second workspace needs its own port, supervisor name and Core credential; the default scripts must be adapted before using them there.

## Source and local patches

The provider is OpenWA 0.24.0 at revision `8a45366a287750cf52c2658b0b783747cf51fad2`. Its downloaded source, dependencies and build live in ignored `runtime/upstream/`; installation provenance is written there. The reviewed dependency tree is preserved in `runtime/provider-package-lock.json` and installed with `npm ci`. See the accompanying license notice and [SOURCE_INVENTORY.md](SOURCE_INVENTORY.md).

The reproducible installer binds NestJS to loopback, suppresses bootstrap plaintext key files when `API_MASTER_KEY` is supplied, masks the key banner, and overrides `music-metadata` to 11.16.0 to address the dependency advisory found during installation. It builds the API without enabling the upstream dashboard, Docker manager, plugin console, Swagger or upstream MCP service. The Maverick app exposes only its own declared operations.

The provider uses the wwebjs engine, SQLite and bounded concurrent sessions. Sending pacing is enabled. Optional Redis, queue and cache services are disabled for this installation.

## Verification and limits

```bash
PYTHONPATH=../.. python3 -m unittest discover -s apps/openwa/tests -v
maverick core cli run core.app-sdk.validate --app-id openwa --json
maverick core cli run core.app-sdk.status --app-id openwa --workspace default --json
maverick app openwa cli run openwa --action sessions.list --json
```

The native and frontend regression suites cover provider readiness, transport status preservation, timeout/remount, quoted replies, uncertain/in-progress conflicts, recovery, concurrent refreshes, cancelled pages, gateway/credential changes, QR failures, shell theme/navigation and notification isolation. A cold first browser start can outlast one HTTP request; the app observes the live session state rather than starting a second job.

Browser sends persist one unresolved attempt per user/workspace/gateway/session/chat before dispatch, including exact text, quote, key and first-attempt time. Reopening or reloading restores it. Reading messages clears only read errors. `IDEMPOTENCY_KEY_IN_PROGRESS` permits a retry with the same key; `IDEMPOTENCY_OUTCOME_UNKNOWN` and other uncertain 409 sends produce deduplicated actor-scoped central inbox notices and explicit chat-check recovery. A new key requires confirming that the earlier message is missing; preparing it does not dispatch. Retries stop after 23 hours, before the provider’s 24-hour key expiry. Browser storage is device-local, and unavailable or invalid storage blocks sending. CLI/MCP callers must retain their supplied key and check the chat before choosing a new one. Incoming messages refresh in the visible app; background incoming-message push and OS push are not implemented.

## Read scheduling and error recovery

The browser bounds every backend request to 28 seconds. Read-only requests accept cancellation signals and discard cancelled results. Polling waits for completion, coalesces repeated refresh requests into one follow-up read, and cancels on hiding, offline state, superseded queries or teardown. Status/resources use a 10-second interval, messages 8 seconds and linking QR 5 seconds. Failed reads exponentially increase that delay up to 60 seconds; a manual retry or visibility resume resets the delay. Resource and message polling stop when the gateway is unavailable; messages also require a ready session. Mutations use neither the read scheduler nor visibility cancellation. A send timeout retains the original attempt and warns that delivery may already have happened.

Query changes clear old rows immediately, while failed refreshes of the same query retain their rows. Resource errors have their own retry action and cannot be dismissed by unrelated successful status reads. Tab changes reset pagination in the same state update. Confirmed sends clear the attempt independently of message reads and return to the newest page. Synchronous dispatch guards prevent duplicate submissions before React can render the busy state.

Provider HTTP failures retain their actual status even when an intermediary returns HTML or an empty body; arbitrary provider text remains redacted. Empty 204/205 successes are accepted. Notification inbox reads use app-owned SQLite indices. Retention is bounded to 1,000 records per actor, so another actor's activity cannot prune an unresolved notice. These additive indices are created when opening existing databases and require no data reset.

## Native presentation and review evidence

The app owns a dedicated WhatsApp compact SVG and transparent PNG. The registry supplies that asset to rail and App Store; the native compact-image renderer uses its alpha silhouette with the surface's theme colour. The silhouette was visually inspected in the desktop rail and the OpenWA App Store card, including native light-on-dark and dark-on-light icon frames. The central inbox displayed the real "OpenWA connected" notice through the mounted backend.

The October 2026 review observed a ready linked session and a real chat list before the platform backend restart. After that restart, no provider process was listening on `127.0.0.1:2785`. The updated mounted app was inspected at desktop 1440×1000 and mobile 390×844, including the outage state, desktop dark/light themes, mobile shell clearance, and gateway settings. Tab focus cycled inside the dialog, and Escape restored focus to the settings button. The 28 backend and 40 frontend tests passed, together with SDK validation, the official frontend build, the focused unused-import check and Git whitespace checks. Post-change live conversation reads and real delivery remain unverified until the operator restores the existing provider with the lifecycle commands above. Send regressions use simulated responses; no WhatsApp message was sent during this review.
