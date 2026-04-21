# Developer Kit App

Date: 2026-04-21

`developer-kit` is a sealed workspace-visible Maverick app for SDK workflows. It is intentionally not admin-only: every workspace user should be able to learn the SDK, generate app source, validate contracts, and package source artifacts.

It exposes:

- frontend: `apps/developer-kit/frontend/dist`
- backend: `apps/developer-kit/backend/app_backend.py`

The backend supports:

- `templates`
- `create`
- `validate`
- `package`

Registration and installation of generated apps remain generic app-hosting operations. The frontend calls:

```text
POST /api/app-store/register-local
POST /api/app-store/install-local
```

The Developer Kit app must not write app-hosting control-plane records directly.

If a workspace policy later restricts registration or installation, that restriction belongs in the App Store/core app-hosting API authorization layer. The SDK and Developer Kit should remain generally visible and usable.
