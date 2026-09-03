# ADR-0013: App-Frame Session Lease Recovery

## Status

Accepted

## Context

Each isolated app or widget frame receives a host-bound, HttpOnly browser
session through a one-shot bootstrap POST. The session authority is held only
in Core memory, has a five-minute idle lifetime and a one-hour absolute
lifetime, and is revoked by a Core restart. Ordinary HTTP traffic touches and
rotates the session, but a long-lived WebSocket cannot refresh its browser
cookie. A frame that mainly uses WebSockets can therefore keep rendering while
its app-frame authority expires; later reconnect attempts are rejected before
the runtime WebSocket is accepted.

Transport retry alone cannot repair this state. The platform login may still
be valid, while the isolated-origin session that delegates it is no longer
valid.

## Decision

- Core reserves `POST /.well-known/maverick-app-frame-session` on every
  app-frame origin. A request must present the host-bound app-frame cookie, the
  exact isolated `Origin`, `Sec-Fetch-Site: same-origin`, current platform
  identity, current workspace membership, and current app generation.
- A successful lease request touches the idle deadline, rotates the opaque
  cookie when due, and returns an empty `204` response with private `no-store`
  policy. The endpoint never exposes the platform session token or application
  data and never extends the absolute session deadline.
- The Core-owned script injected ahead of app code probes the lease immediately
  and every two minutes while both the document and its shell-owned surface are
  visible. It suspends the timer while hidden and probes immediately on
  visibility, focus, online, and page-show hints.
- Network failures and non-authoritative server failures receive bounded retry
  and do not imply authentication loss. Only a definitive `401`, `403`, or
  `410` response asks the parent shell for new frame authority.
- The recovery request is posted to the exact platform origin and includes the
  frame's current relative route. Base Shell accepts it only from the exact
  registered iframe window and exact registered isolated origin. It then makes
  one single-flight browser-launch request and submits the new one-shot ticket
  back into the same iframe. Core remains authoritative for app visibility,
  generation, workspace ownership, and route ownership.
- A failed relaunch preserves the old registered origin so a later trusted
  recovery request can retry. Mere connectivity loss never causes a shell-wide
  remount, logout, or global offline state.

## Consequences

- Visible WebSocket-heavy frames keep their short idle lease alive without
  application-specific polling.
- Hidden frames are allowed to expire and recover when shown, avoiding
  nonessential background work.
- Core restarts and absolute app-frame expiry recover through the existing
  authenticated launch authority without weakening the one-shot ticket or
  HttpOnly-cookie boundaries.
- Each visible isolated frame adds at most one steady-state lease request every
  two minutes, plus bounded retries during transient failures.
- Base Shell source and its committed distribution must be rebuilt together
  under ADR-0004.
