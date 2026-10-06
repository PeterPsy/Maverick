# Platform login session lifecycle

Maverick login uses an opaque server-side session and an expiring `HttpOnly`,
`SameSite=Lax` cookie (`Secure` on HTTPS). New sessions have a 30-day idle
window. A verified top-level `GET /api/session` renews that window at most once
per day, bounded by 90 days from login. Expired, revoked, deleted sessions,
inactive users and missing workspace membership never gain access through
renewal. Logout and password reset retain authority: renewal uses a conditional
update without upsert and rereads persisted state before returning success.
Existing live sessions gain the same bounded window on their next verification.

The response synchronizes the persisted expiry into the cookie even when a
concurrent request already performed renewal. It also returns a SHA-256 opaque
`session_generation` derived from session identity. Generation changes at a new
login; extending expiry never changes it. The raw cookie is never included in
JSON. Isolated app-frame requests cannot renew or receive the platform cookie.
Their existing idle/absolute leases and exact-parent relaunch flow are separate.

Base Shell checks the session on foreground, connectivity restoration,
`pageshow`, the native `maverick.session-changed` hint, and every five minutes
while visible and online. Only a server response grants authorization.
Same-session renewal updates expiry and cache leases without remounting frames.
A changed user, workspace or generation enters the existing publication barrier.
Responses from an older login/logout transition are fenced out.

Transport failures, timeouts and retryable server responses retain recovery
state rather than publishing an anonymous session. Initial failures show
pending/retry state. Resource or frame `401/403` blocks the denied operation and
its private display copies, then confirms the platform session through a
single-flight, uncached request. Only an explicit anonymous session or platform
session `401` invokes global revocation and authenticated-frame teardown.
Permission denial, unavailable confirmation, malformed responses and offline
state cannot establish logout. Explicit logout still withdraws UI immediately.

The native iOS wrapper prepares persistent WebKit cookies and the origin-scoped,
device-only Keychain recovery copy before constructing the WebView. It verifies
platform login and persists renewed cookie expiry independently of Senses
availability, synchronizes URLSession cookies back to WebKit, and verifies again
on foreground activation. A terminated WebKit content process recovers cookies
before reloading. Keychain unavailability is transient; it must never delete a
valid recovery copy. Cookie-matched validation/invalidation prevents an old
request overwriting a newer login. Native hints carry no authentication data and
ask the shell to perform its own verification.
