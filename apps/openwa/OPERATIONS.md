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

The `default` installation is already bootstrapped and running. Do not bootstrap it again. Bootstrap creates the API key in memory, stores it through Core Secrets, grants the logical `openwa-api-key` to the declared app surfaces, and initializes the provider's hashed key record. It suppresses plaintext key-file creation and banner output. Ongoing provider launches need no raw key in their environment. Gateway credentials are managed directly in Vault. To switch providers, preserve the local provider credential, bind the new credential to `openwa-api-key`, and retain the declared backend/CLI/MCP grant targets before saving the new gateway URL. The app does not rotate or replace Core secrets from its settings screen.

Start/restart wait for `/api/health/ready`. PM2 restarts a crashed process with a delay and a memory limit. No system-wide startup unit is installed: after a host reboot, an operator must run `manage.py start`. Stop affects only this provider. A second workspace needs its own port, supervisor name and Core credential; the default scripts must be adapted before using them there.

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

The implementation was checked with 14 native tests, 40 focused upstream tests, SDK validation, production frontend/API builds, and dependency auditing with no remaining reported advisories. The live local provider created and started a real session and produced a valid PNG QR challenge. A cold first browser start can outlast one HTTP request; the app observes the live session state rather than starting a second job.

No phone was linked and no WhatsApp message was sent during installation. Linked-account reads and delivery still require that user step. Text retries reuse an idempotency key; an uncertain send generates a central inbox notice. Incoming messages refresh in the visible app; background incoming-message push and OS push are not implemented.

The rail's native conversation icon was inspected in both dark and light themes. The App Store's real renderer selects the same `forum` glyph from the app's `chat` view declaration. The central inbox displayed the real "OpenWA connected" notice through the mounted backend.

Native desktop/mobile app workflows and visual inspection inside the App Store remain blocked by Maverick's app-frame TLS service. On 12 October 2026 the browser returned the platform's `app_frame_tls_unavailable` response, including for the shared floating chat widget. This is independent of provider readiness; do not bypass the authenticated app frame with a direct asset URL.
