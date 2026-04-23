# Developer Kit App

Date: 2026-04-21

`developer-kit` is a sealed workspace-visible Maverick app for SDK workflows. It is intentionally not admin-only: every workspace user should be able to learn the SDK, generate app source, validate contracts, and package source artifacts.

It exposes:

- frontend: `apps/developer-kit/frontend/dist`

The frontend calls the authenticated workspace SDK API:

```text
POST /api/app-sdk
```

Supported UI actions:

- list templates
- create workspace-local source
- validate source
- register local project
- install local project
- inspect status
- package source

The Developer Kit app must not write app-hosting control-plane records directly or carry a parallel app-owned backend for SDK control-plane mutations.

Workspace policy for custom apps and installation is enforced by `/api/app-sdk`. The SDK and Developer Kit should remain generally visible and usable.
