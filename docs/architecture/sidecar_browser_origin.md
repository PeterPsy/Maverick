# Isolated Browser Origins For App Sidecars

Date: 2026-08-03
Status: Accepted (G1)
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
is not a credential. In local mode the label is placed beneath
`sidecars.localhost` and uses the core listener's port. Hosted installations
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
   than 30 seconds.
2. The app submits the ticket in an iframe-targeted form `POST` body to the
   reserved bootstrap endpoint on the sidecar origin. Tickets are never placed
   in a URL, fragment, browser storage, referrer, audit target, or log.
3. The sidecar router atomically consumes the ticket, verifies every binding,
   creates a distinct random session, and responds `303` to a clean relative
   URL. It sets a host-only, `HttpOnly`, `SameSite=Strict` cookie with `Path=/`;
   hosted mode also requires `Secure`. No `Domain` attribute is permitted.
4. Session activity may rotate the cookie but cannot exceed a five-minute idle
   TTL or one-hour absolute lifetime. Ticket replay and a session presented to
   another host, actor, workspace, app, sidecar, or generation are denied.
5. Logout, workspace switch, app disable/uninstall, sidecar restart, and active
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
no-store cache policy. CSP is derived from contract data, defaults to
`default-src 'self'`, permits `connect-src` only to the same sidecar origin and
declared brokers, and sets `frame-ancestors` to the expected Maverick origin.
Wildcard frame parents and arbitrary outbound origins are invalid.

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

## Residual Risk And Closure

- WP2 implements and integration-tests the production ASGI router, durable
  revocation semantics, hosted wildcard configuration, headers, and unbuffered
  SSE.
- WP3 applies exact route-template matching and URL canonicalization.
- WP9 uses only the form bootstrap and verifies `postMessage` origin/source.
- WP10 runs Playwright, leakage searches, workspace A/B isolation, expiry,
  restart, logout, and hosted/local failure-path tests.

Until WP2 and WP3 pass, isolated browser-origin authority must not be enabled in
an app contract.
