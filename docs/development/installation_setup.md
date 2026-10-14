# Installation setup verification

Historical evidence: the dated live checks below describe the predecessor
installation on its original server, before this rebrand. They do not establish
that `/projects/loopino` on this destination has been deployed or verified. New
Loopino source/build evidence and remaining deployment gates are recorded in
`loopino_phase1_status.md`; no live Nginx/systemd changes have been applied here.

The implementation is described by the published Developer Context document
`installation_address`. Settings → Installation and the top-level `/setup` page
share `packages/installation-ui`. The workspace Skills app seeds
`installation-ops` from Settings' bundled skill.

Verified on the live standalone installation on 2026-10-12/13:

- Official Settings and Base Shell frontend builds completed and emitted refresh
  events and asset manifests.
- The operator installer installed the systemd worker, discovered the migrated
  Core RootDirectory and assigned readable metadata to the Core account.
- A native CLI plan/apply adopted the existing installation. Both Certbot staging
  renewal tests passed, the backend restarted, and the durable job reached Ready.
- Fresh pinned HTTPS checks passed for the main host and random app-frame and
  sidecar hosts. The latter return the expected unauthenticated 401 responses.
  CLI and MCP verify both succeeded.
- Cloudflare's full record digest and all 20 records matched before/after adoption;
  existing main/wildcard certificates were reused without forced production orders.
- The owned Nginx configuration and initial private backup were migrated to the
  final hostname-scoped format. HTTPS remained healthy after its reload.
- Governed Browser inspection loaded standalone setup at 1440×1000 and Settings
  Installation at 390×844. Screenshots confirmed readable cards and mobile layout.
  Review setup from the isolated Settings frame returned HTTP 200 and a keep-only
  plan. The initial static-document CSP issue was reproduced and fixed with a
  trusted Root document route; public app HTML retains its inert CSP.

Focused tests cover argument schemas and admin gates, endpoint ownership and
serialization, generation/plan integrity, concurrent changes, DNS preservation,
interrupted writes, repeatable rollback, CA waiting, wrong destinations, TLS before
DNS cutover, separate active/staged virtual hosts and timer ownership restoration.
UI tests cover stable drafts/focus and credential clearing without browser storage.
The final focused runs passed 33 installation checks, 20 installer/contract/asset
checks and 15 Settings UI checks. Both frontend manifests were rebuilt through
the official operator CLI with the host's deployed SQLite runtime environment.
After the final backend restart, fresh authenticated inspection verified the final
wordmark and diagnostic labels at both desktop and mobile sizes. The Settings
page also loaded inside its isolated app frame on mobile. Its inspection/status
requests and standalone setup's Check connection request returned HTTP 200.
The final CLI inspection still reports Ready and fresh main/app HTTPS checks pass.
All temporary Browser sessions created for this verification were closed.

The broader fast run exposed five provider-profile tests using an unavailable
native model and a Storage migration test loading SQLite 3.46.1 instead of the
required 3.51.3+. These paths were not changed by this work. It also exposed two
installer-template failures; those were fixed by excluding the replaced legacy
TLS templates and rendering the new worker directly, and the focused installer
checks pass. The full fast suite is not claimed green.

An actual second-server data transfer was not performed. Destination identity and
cutover sequencing are verified with injected host/DNS tests; the live adoption
exercises real DNS access, renewal, Nginx, restart, API, MCP and UI. Data restore,
source write draining and provider-console registrations remain explicit operator
steps. Automatic DNS currently supports Cloudflare; manual mode is guided and
blocks automatic application/renewal claims.

Provider references:

- [Cloudflare token template format](https://developers.cloudflare.com/fundamentals/api/how-to/account-owned-token-template/)
- [Cloudflare wildcard precedence](https://developers.cloudflare.com/dns/manage-dns-records/reference/wildcard-dns-records/)
