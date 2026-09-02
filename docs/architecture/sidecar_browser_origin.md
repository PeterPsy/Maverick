# Isolated Browser Origins For App Sidecars

Date: 2026-08-03
Status: Accepted (G1), implemented by WP2 and WP3
Owners: Maverick Core app hosting and app contract domains

## Context

An app-owned web sidecar can use absolute paths such as `/api/projects`. A
path-mounted proxy under the Maverick origin sends those requests to Maverick
instead of the sidecar and also shares the platform cookie origin. Rewriting an
upstream application is brittle and does not create a browser security
boundary.

This ADR defines a generic capability for sidecars declared by any app. It does
not add sidecar-product-specific routes to core.

## Decision

Browser-visible sidecars that require root-relative routes use an isolated
origin of the form:

```text
<opaque>.sidecars.<installation-domain>
```

The opaque label identifies one installed app/sidecar/workspace generation. It
is not a credential. In local mode Maverick itself must use a named loopback
host such as `maverick.localhost`; the label is placed beneath
`sidecars.maverick.localhost` and uses the core listener's port. Keeping the
platform and sidecar hosts under the same named `.localhost` site preserves the
`SameSite=Strict` main-session boundary. Bare `localhost` and IP-literal
platform hosts fail closed. Hosted installations
must provision wildcard DNS and TLS for `*.sidecars.<installation-domain>`.
Core fails closed when the declared isolated origin cannot be constructed or
served securely.

The sidecar origin routes `/`, `/_next`, `/api`, `/artifacts`, and `/frames`
through the generic sidecar policy. It does not mount Maverick API routes and
does not fall through to the normal platform host. Unknown routes are denied.

## Bootstrap And Session Protocol

1. On the authenticated Maverick origin, the mounted app requests a one-shot
   ticket. Core binds its hash to actor, workspace, local app id, sidecar id,
   exact sidecar host, and active bundle/data generation. Ticket TTL is no more
   than 30 seconds. Core also returns a distinct confirmation token and stores
   only its hash. That token can only query this launch's bootstrap state
   through the authenticated platform origin; it grants no sidecar access.
2. The app submits the ticket in an iframe-targeted form `POST` body to the
   reserved bootstrap endpoint on the sidecar origin. Tickets are never placed
   in a URL, fragment, browser storage, referrer, audit target, or log.
3. The sidecar router atomically consumes the ticket, verifies every binding,
   creates a distinct random session, and responds `303` to a clean relative
   URL. It sets a host-only, `HttpOnly`, `SameSite=Strict` main cookie with
   `Path=/`; hosted mode also requires `Secure`. If and only if the app declares
   sandboxed-frame resources, Core sets a second host-only
   `__Host-maverick_sidecar_resource_session` cookie with `HttpOnly`,
   `SameSite=None`, `Secure`, and `Path=/`. An opaque-origin child can send that
   second cookie, but Core accepts it only for `GET` or `HEAD` on an exactly
   declared resource path. It cannot authorize undeclared documents or
   arbitrary sidecar APIs. Both names carry the same random host-bound session
   value and have no `Domain` attribute. Only after the current target has been
   verified and the redirect is ready does Core mark the associated
   confirmation as ready.
4. The mounted app polls the authenticated platform confirmation endpoint and
   treats the native frame as ready only after both confirmation and the target
   frame load. An iframe `load` event alone is not evidence of success because
   browsers also emit it for internal TLS/network error documents. Pending,
   expired, actor-mismatched, workspace-mismatched, or instance-mismatched
   confirmations never produce readiness.
5. Default session activity may rotate the cookie. A dual-cookie
   sandbox-resource session keeps one value so its two browser cookie names
   cannot diverge; Core still enforces a five-minute idle TTL and one-hour
   absolute lifetime. Ticket replay and a session presented to another host,
   actor, workspace, app, sidecar, or generation are denied.
6. Logout, workspace switch, app disable/uninstall, sidecar restart, and active
   generation change revoke related sessions.

The browser never receives the sidecar technical token. Maverick session
cookies are neither copied nor forwarded upstream. Core strips sidecar
`Set-Cookie`, unsafe redirects, hop-by-hop headers, and technical authorization
material before a response reaches the browser.

## Request And Response Policy

The bootstrap `POST` is the sole exception to normal unsafe-method CSRF checks.
Every other unsafe request requires:

- the exact canonical `Host`;
- `Origin` equal to the sidecar origin;
- Fetch Metadata consistent with a same-origin request;
- a live sidecar session bound to the current generation; and
- an exact authorized method and route template.

Missing or ambiguous host, missing origin, cross-origin/cross-site requests,
encoded traversal, and unknown routes fail closed. Safe requests still require
the bound sidecar session.

Every authenticated sidecar response uses `Referrer-Policy: no-referrer` and a
no-store cache policy by default. A contract may additionally declare a bounded
set of canonical, non-API directory prefixes as `immutable_asset_prefixes`.
Successful GET/HEAD responses below those prefixes use a private one-year
immutable browser cache; errors, API responses, bootstrap responses, and every
undeclared path remain `no-store`. `private` is mandatory so a shared proxy
cannot bypass the sidecar session boundary. The opaque origin includes the app
binding generation, and apps must use content-addressed filenames below an
immutable prefix.

Responses also default to `Cross-Origin-Resource-Policy: same-origin`. Native
applications may render untrusted documents in an iframe sandbox that omits
`allow-same-origin`; those documents have an opaque origin, so the browser
cannot load even same-host images while that default applies. Such an app may
declare at most eight canonical literal paths or directory prefixes as
`sandboxed_frame_resource_prefixes`. Core changes only matching authenticated
responses to `Cross-Origin-Resource-Policy: cross-origin`. A value ending in
`/` matches that directory tree; any other value is an exact-path match.
`/.well-known`, the whole `/api` namespace, encoded or dynamic paths, and
duplicates are invalid. The declaration adds the separate resource cookie
because an opaque sandbox does not send the main `SameSite=Strict` cookie. Core
never accepts that second cookie outside matching `GET`/`HEAD` routes, does not
enable CORS, and retains actor, workspace, app, sidecar, generation, TTL, and
revocation checks. Because a cross-site document can cause the browser to send
a `SameSite=None` cookie, declared routes must contain only non-sensitive bytes
that are safe to embed cross-origin; user-private APIs and media are forbidden.

CSP is derived from contract data, defaults to
`default-src 'self'`, permits `connect-src` only to the same sidecar origin and
declared brokers, and sets `frame-ancestors` to the same isolated origin plus
the expected Maverick origin. The same-origin entry is required because the
policy is attached to every proxied document, including native application
previews embedded below the sidecar's top-level page. The exact Maverick origin
remains the only permitted external frame parent; wildcard frame parents and
arbitrary outbound origins are invalid.

## Ownership

Core owns hostname resolution, ticket/session storage, hashing, expiry,
revocation, CSRF/Fetch Metadata enforcement, security headers, route-policy
dispatch, upstream technical authentication, and audit correlation. The app
declares the generic capability and CSP requirements. The sidecar owns only its
application protocol and cannot choose workspace, app id, technical port, or
host paths from browser input.

## Proof

Run:

```bash
python3 -m unittest tests.architecture.test_sidecar_browser_origin_proof
```

The proof starts an actual local HTTP listener and demonstrates that a nested
`.localhost` host resolves to loopback, a body ticket is one-shot, the `303`
location is clean, the issued cookie is distinct and host-only, absolute
`/api/projects` reaches the sidecar surface, Maverick `/api/status` does not,
and unsafe requests without an exact origin/Fetch Metadata are denied. The
proof must not log the ticket or expose it in response headers.

Expected result: all tests pass. This proves the routing and bootstrap design is
implementable on the supported local host model; it is not the production
session store or router.

The production implementation is the generic ASGI host router in
`core/api/sidecar_browser.py` and the hashed, process-local authority in
`core/apps/sidecar_browser_sessions.py`. The authority deliberately has no
persistent secret material: restarting core constructs an empty store and
therefore revokes every ticket and sidecar session. The production integration
proof uses a real confined sidecar process and runs with:

```bash
python3 -W error::ResourceWarning -m unittest \
  tests.integration.app_hosting.test_sidecar_browser_origin \
  tests.unit.apps.test_sidecar_browser_sessions
```

It covers the absolute-path routing boundary, fail-closed local and hosted
configuration, one-shot/expired tickets, host-only cookie issuance, cookie
rotation bounds, CSRF and Fetch Metadata, response-header filtering, exact CSP
frame/connect policy, unbuffered SSE, logout and process-restart revocation,
fresh launch after browser-session idle expiry, cold launch after host restart,
sidecar relaunch after process restart, and redaction-safe success/failure audit
records. The cold-start case waits for the app-declared health budget; it does
not replace readiness with a fixed core timeout.

Exact route and canonicalization proof:

```bash
python3 -m unittest \
  tests.unit.apps.test_sidecar_route_policy \
  tests.contracts.app_contract.test_services
python3 apps/design-studio/service/sync_route_policy.py
```

Authorized API rules use literal segments and named `{parameter}` segments;
each ordinary parameter consumes exactly one segment. One named
`{*project_path}` splat may consume one or more canonical segments inside the
declared literal prefix and suffix. Unsafe authorized routes always name a
method. App-provided regex, prefix matching, unnamed/repeated splats, encoded
slash/backslash/dot traversal, double encoding, and ambiguous paths are
rejected. A separate `static_tree` form is restricted to GET/HEAD roots outside
`/api` for immutable web assets. Policy precedence remains blocked, then
handled-by-core, then pass-through, with unknown routes denied.

Local mode is the default and is available only when Maverick itself is
accessed through a named `.localhost` origin. Hosted mode is explicitly enabled
with:

```text
MAVERICK_SIDECAR_ORIGIN_MODE=hosted
MAVERICK_SIDECAR_INSTALLATION_DOMAIN=<installation-domain>
MAVERICK_SIDECAR_PLATFORM_ORIGIN=https://<platform-host>
```

The hosted listener must terminate wildcard TLS and route
`*.sidecars.<installation-domain>` to the same ASGI application. Missing,
invalid, non-HTTPS, or request-mismatched configuration fails closed before a
ticket is issued.

The self-hosted installer exposes this boundary explicitly through
`--hosted-sidecars`. Live preflight parses the externally provisioned DNS-01
certificate and unencrypted private key, requires a currently valid leaf SAN
for the exact `*.sidecars.<installation-domain>` wildcard, and verifies that
the public keys match. File existence or a certificate for one opaque hostname
is not sufficient. The installer renders the three core environment values
above and adds a dedicated Nginx wildcard server without `X-Frame-Options`.
Post-apply health verification opens reserved `sc-<opaque>` and `af-<opaque>`
origins with the normal system trust store and requires Core's unauthenticated
session denial from each; this checks wildcard DNS, hostname validation, TLS
termination, Nginx routing, and both Core host routers together. A failure does
not fall back to executable documents on the platform origin. The platform
server may retain
`X-Frame-Options: SAMEORIGIN`; that header must never be inherited by the
distinct sidecar server.

## Residual Risk And Closure

WP9 and WP10 are complete for Design Studio. The mounted frontend uses only the
form bootstrap, keeps a stable iframe target from its first browsing context,
and validates `postMessage` origin/source. The WP10 Chromium proof covers clean
redirects, credential leakage, restart session renewal, forbidden/core routes,
and distinct workspace A/B origins. The evidence is
`apps/design-studio/service/opendesign_product_acceptance_0_16_1.json`.

This closes the declared Design Studio browser-origin gate; it does not make
Maverick generally production-ready or remove the blockers in
`docs/security/production_readiness.md`.
