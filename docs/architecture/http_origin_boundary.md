# Unsafe HTTP origin boundary

Cookie-authenticated POST, PUT, PATCH and DELETE requests require an HTTP(S)
Origin, or a Referer only when Origin is absent. Core compares scheme, hostname
and effective port with the request authority. Empty, opaque (`null`), malformed
or foreign Origin values fail closed; a valid Referer cannot override them.
Credentials, paths, query strings and fragments are not valid Origin authority.

The HTTP server's trusted proxy configuration must resolve the public scheme
into the ASGI scope / WSGI `wsgi.url_scheme`. The guard does not trust raw
Forwarded or X-Forwarded-* headers. Default HTTP/HTTPS ports are normalized.
Non-cookie CLI calls without browser proof remain supported; authentication
and action authorization are independent requirements.

App-event WebSockets already require a session at handshake and filter events
to that session's workspace. This implementation evidence is not a completed
CSRF, proxy-deployment or long-lived session/revocation security audit, and does
not change Maverick's experimental production-readiness status.

Regression coverage: `tests/unit/api/test_http_origin.py`,
`tests/unit/api/test_http.py`, and the anonymous-handshake/workspace-filter
cases in `tests/integration/app_hosting/test_asgi_application.py`.
