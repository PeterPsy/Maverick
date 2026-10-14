# Mobile background and resume

Ordinary foreground transitions retain the existing shell, isolated app frames
and native WKWebView. Session verification may renew authentication and access
leases in place. A real principal/session/workspace change still withdraws the
previous authenticated frames. Visibility and reconnect refresh live reads
without navigating the document or clearing its composer.

The shell must not reload for an unsolicited service-worker `controllerchange`.
Another tab may activate an update, and WebKit may restore worker control on
resume. Only an explicit update request in the current document arms a reload.

The iOS app rechecks its auth gate on foreground without changing the WebView's
reload identity. WebKit process termination is an exceptional recovery: the
coordinator waits for an active scene, consumes the recovery once, and supplies
the WebView's current URL. AppState accepts only the configured platform origin,
then rehydrates cookies and reloads that actual SPA route. The initial native
launch URL may precede later in-app navigation and is only a fallback.

Chat saves composer text synchronously as it changes, because mobile process
termination may occur without `pagehide`, unload or a final background callback.
The store is app-owned localStorage on Core's isolated `af-*` origin, which is
bound to one user, workspace, app generation and platform session (and parent
origin for nested widgets). It never writes on the shared platform origin.
Workspace, stable floating-window id, project and conversation identify the
draft. Restoration waits for live dependencies and target-conversation resolution
and applies only to an empty composer. Submitting or clearing removes saved text.

This narrow exception to the original RAM-only composer policy retains at most
20 drafts, each at most 64 Ki characters, and expires them after 24 hours. It
persists no attachments, references, runtime authority, queue or deferred send.
Storage denial leaves the current editor usable. Authentication loss/new login
or app reinstallation changes the isolated origin and cannot reveal old drafts.
Local browser-data deletion also removes recovery text.

Regression coverage exercises unsolicited and explicit worker changes, controller
remount, empty/sent draft deletion, conversation/window/workspace separation,
live-initialization gating, shared-origin exclusion, expiry, bounds and storage
denial. Native tests cover ordinary foreground verification, current-route
recovery, other-origin rejection, deferred process recovery and retired sessions.
