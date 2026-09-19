# External Apps V1: immutable static publishing

Date: 2026-09-19. Status: implemented; public DNS/TLS/ingress activated for the
default workspace. Actual publication Internet acceptance remains a separate gate.

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

TLS/DNS are installation-owned. Publishing never obtains host privileges or
ACME keys. Ingress strips credentials and Set-Cookie, has no independent response
cache and never routes public requests into Maverick's private ASGI application.
Only GET/HEAD, inventory files, strict canonical host/path validation and a
restricted static CSP are supported. ETags save bytes, but every reuse must
revalidate and every 304 checks current serving authority. No public worker.
Downloaded copies are not revocable. Health is separate from publication state.

## Verification and deployment gates

Before cutover, validate candidate integrity and trusted TLS for the exact host.
Pending certificates leave both the approved plan and binding untouched; retry
uses the same plan. Afterwards probe HTTPS without
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
remain outside this change. That initial implementation did not activate live
ingress, TLS, DNS or a supervisor.
Internet acceptance and hosted Chat mutation admission remain the explicit gates
above, not implied by the local tests.

## Installation-derived public origins

The single portable naming rule is `<app>.apps.<installation-domain>`. The app
label retains its readable slug and opaque id, avoiding collisions across
workspaces. `deployment.configure` accepts `installation_domain`, not an arbitrary
public suffix; it derives `apps.` without changing the platform hostname. The
operator supplies the same canonical hostname as Maverick's installation (not a
request Host or isolated app-frame origin). The supervisor derives the suffix
independently and admits only matching app configuration. Domain changes are
explicit and rejected for nonempty catalogs: existing approved URLs are not
silently rewritten. Raw IPs, URLs, ports and wildcard input are rejected.

Separate subdomains are cross-origin but **same-site**. Static public documents
therefore receive `sandbox allow-scripts` without `allow-same-origin`, blocking
cookie tossing, document.domain and browser persistence. Anonymous CORS `*` on
public inventory responses permits ES modules/lazy chunks/fonts from the opaque
origin; it never permits credentials or private APIs. Existing CSP restrictions
on connections, forms, frames and workers remain. A real Chromium fixture proves
ES modules, lazy imports and history routing work while cookies/storage/domain
relaxation and fetch are blocked. This is intentionally a stateless static/SPA
contract, not arbitrary authenticated applications. Core session semantics and
chat are not changed to accommodate public hosting.

## Operator-owned exact TLS, no DNS-provider credentials

Wildcard DNS must already resolve `*.apps.<installation-domain>` to the ingress;
a different installation still needs DNS routing provisioned by its operator.
HTTP-01 cannot create DNS records and cannot issue a wildcard certificate. Instead,
a small root-owned systemd oneshot/timer uses Certbot webroot for **exact names**,
with a separate ACME state directory. One SAN lineage per workspace app namespace
batches up to the existing 100-app cap; the namespace base has its own lineage.
The timer also renews certificates within 30 days of expiry, with no Core restart.

The trusted supervisor adds bounded certificate intent to its short-lived mount
projection: only nonarchived catalog hosts with a ready unexpired plan or retained
published release. This exposes hostname metadata to certificate transparency,
not the bundle. The root worker revalidates freshness, live namespaces, exact name
patterns and caps. Incoming SNI/Host never triggers issuance. At most four orders
per pass, 2-minute success coalescing and 1-hour failure backoff bound work; CA rate
limits still apply. No DNS keys or certificate keys enter the app or public child.

Validated certificate/key pairs generate exact public nginx hosts. Only owned
configuration is replaced; nginx validation precedes graceful reload, with rollback
on failure and a persisted reload retry marker. Unknown names reject TLS in a
namespace-specific catch-all and never fall through to private Maverick. HTTP only
serves ACME challenges. Content still requires the existing binding/projection
checks; a valid certificate is not publication authority.

The [activation runbook](../../apps/external-apps/deployment/README.md) documents
installation, status, renewal and stop paths. The former sslip.io/DNS-01 profile is
superseded, not retained as a fallback. No general certificate framework, anonymous
Core route or changes to the private sidecar/app-frame authority are introduced.

On 2026-09-19 this deployment migrated its empty catalog to
`apps.maverick.loopino.ai`. HTTP-01 staging (base and a synthetic two-name SAN
batch), production base issuance and production renewal dry-run passed. The old
sslip.io lineage and its VM-scoped DNS-01 firewall/tag were removed; an ingress
tombstone prevents private fallback from retired names. Unknown new names reject
TLS. Stopping only the public service returns 503 while Core health stays 200;
resuming restores its 404 namespace response. Core PID/start time stayed unchanged
through this migration (a separately reported Core restart preceded it). The
first human-approved publication/external-browser acceptance gate remains open.
