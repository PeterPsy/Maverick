# External Apps V1: immutable static publishing

Date: 2026-09-19. Status: implementation decision; Internet deployment requires
operator DNS/TLS/ingress configuration and its own acceptance evidence.

The product specification is maintained through Storage at
`storage/generated/external-apps/external-apps-development-spec-simple-v1.md`.
This decision records repository boundaries and the concrete preflight choices.

The app declares portable `sandbox` compatibility (also admitted in full-access
workspaces by Core's existing compatibility rule). Private catalog, plans and
approval state are RAM-only in the browser, with a deny-persistence entry in
`docs/product/pwa_cache_resource_inventory.v2.json`.

## Ownership and scope

`apps/external-apps` is one sealed first-party app. Website Studio exports only
publishable static build output through `external.static-bundle.export` v1.
External Apps consumes the selected provider through dependency backend, never
through another app's files, imports or database. The initial transport is a
bounded ZIP/base64 response to the private dependency callback (2 MiB ZIP,
8 MiB expanded, 512 files). Build preparation remains Website Studio-owned.
PHP, SSR, external authentication and arbitrary backend execution are excluded.

## Publication authority

App-owned SQLite contains catalog, immutable release metadata, plans, operations
and audit. It contains no authoritative active-release pointer. One JSON binding
per public id, under `data/<local_app_id>/public/bindings/`, is the sole serving
authority. It identifies current/previous release, enabled/archived, generation
and operation id, without private source/actor/workspace metadata.

Every mutation acquires an interprocess lock, compares the expected generation,
persists an intent, fsyncs and atomically replaces the binding. A crash before
rename leaves the old binding; a crash after rename is reconciled against the
intent. An unverified interrupted activation is compensated conditionally, not
reported as verified. Suspend and compensation cannot overwrite newer mutations.
SQLite and a JSON projection are deliberately not claimed to share a transaction.

ZIPs and per-file inventories are validated before immutable promotion beneath
`public/artifacts/<sha256>/`. Plans pin these bytes; apply never rebuilds.
Runtime requests select current or explicitly retained previous release only.
Asset paths carry the release id to avoid mixed HTML/assets during cutover.
Temporary and unreferenced artifacts are never addressable through public URLs.

## Human confirmation and runtime policy

Publish/rollback approval is an exact-plan action on the authenticated app UI,
recorded on the plan. It is not a new approval framework and is not available
through CLI/MCP, dependency calls or runtime-session backend requests. The
agent-supplied `confirm` flag is not human authority. Current actor and selected
provider are revalidated at apply. Hosted runtime app-mutation restrictions remain
intact: an unadmitted profile hands the final operation to the UI, rather than
bypassing Core's pre-effect policy. This is not advertised as hosted Chat
end-to-end mutation support.

## Separate public process, no anonymous platform routes

Existing authenticated sidecar browser routes are not weakened. An app-owned,
operator-supervised public service listens on a Unix socket behind a dedicated
wildcard ingress. A private supervisor reads canonical app-hosting state without
bootstrapping the backend. It reconciles interrupted app-owned operations under
the same publication lock and OS operation leases before refreshing authority.
It projects only active, approved public mounts
and a short expiration to a confined child; no private catalog or credentials
are delivered. Workspace close/app disable/uninstall revoke serving within the
projection's maximum 10-second freshness window. App-level suspend is synchronous
at the next request admission. Supervisor loss expires serving fail-closed.

Each explicit deployment workspace has an opaque namespace and a read-only
`public/` mount. Host routing resolves the namespace without scanning workspace
directories. Linux production launch uses bubblewrap with no host network,
minimal read-only runtime/code mounts, no inherited secrets and only a shared
Unix-listener directory writable. Missing confinement fails closed. No operator
service is installed or detached by an agent without explicit operational setup.

TLS/DNS are installation-owned. Publishing never edits them. Cookies are
host-only; ingress strips credentials, has no independent response cache and
never routes public requests into Maverick's private ASGI application.
Only GET/HEAD, inventory files, strict canonical host/path validation and a
restricted static CSP are supported. ETags save bytes, but every reuse must
revalidate and every 304 checks current serving authority. No public worker.
Downloaded copies are not revocable. Health is separate from publication state.

## Verification and deployment gates

Before cutover, validate candidate integrity. Afterwards probe HTTPS without
redirects/cookies and check release identity and entrypoint bytes, not merely
status 200. Failed verification conditionally restores the previous binding.
The candidate may briefly be visible between switch and failed verification.

Required proofs include hostile ZIPs, immutable plan bytes, spoofed confirmation,
cross-workspace ownership, simultaneous mutations, interrupted activation,
suspend during verification, expired mount projections, old-release asset URLs,
and real Website Studio static/SPA output through hosted dependency callbacks.
Local isolated tests do not establish Internet DNS/TLS readiness. Backend restart
and live ingress changes require an explicit safe operational window; repository
implementation does not silently activate them.

## Implementation evidence (2026-09-19)

The implementation has isolated proofs for real Website static and Vite SPA
builds through Core dependency dispatch/callbacks, CLI/MCP reads, immutable bytes
after source edits, interprocess generation conflicts, failed/interrupted probes,
revocation and the actual bubblewrap Unix HTTP listener. Desktop/mobile Chromium
checks cover consent, cancellation, frame identity/theme and scope reset. The
frontend was built with Core's official build service against a temporary store,
not by registering an app or restarting the active backend.

App-specific and app-contract checks pass. The repository-wide fast suite was
also run; unrelated repository-convention failures in existing Core/test files
remain outside this change. No live ingress, TLS, DNS or supervisor was activated.
Internet acceptance and hosted Chat mutation admission remain the explicit gates
above, not implied by the local tests.

The [operator activation runbook](../../apps/external-apps/deployment/README.md)
now includes a bounded JSON-adapter systemd unit, DNS-01 certificate renewal,
shared-nginx virtual hosts without a default-server takeover, and an independent
stop path. A real foreground nginx fixture verifies ingress behavior without
modifying the running platform. A selected separate domain, certificate and
live app registration are still required before operational activation.
