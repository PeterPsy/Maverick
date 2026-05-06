# Maverick App SDK Frontend Guide

Date: 2026-04-21

SDK-generated frontends are mounted by the core through the app contract.

The contract entrypoint must point to:

```text
frontend/dist
```

Every SDK template that declares a frontend generates a React/Vite app. Source lives under:

```text
frontend/src/
```

Mounted frontends call their app backend through:

```text
/api/apps/<app_id>/backend
```

Do not call another app's private backend or private files directly. Use the owning app's official backend, CLI, or MCP surfaces.

## Shell Route Contract

Maverick has two different frontend URL families:

- `/app/<app_id>/<app_page>` is the user-facing shell route. It selects the active app in `base-shell` and may be copied, reloaded, or used as a deep link.
- `/apps/<app_id>/...` is the internal mounted frontend asset route used by shell iframes and direct app asset serving. Apps must not use it as the canonical user-facing navigation URL.

Apps that want a stable page URL should send the page segment through shell navigation messages:

```js
window.parent?.postMessage(
  {
    type: "maverick.app.open-app",
    app_id: "chat",
    params: { app_page: "threads/<thread_id>" }
  },
  window.location.origin
);
```

The shell renders that as `/app/chat/threads/<thread_id>` and sends the same `app_page` back to the mounted app with `maverick.app.navigate`.

App page segments are app-owned. The core and shell do not interpret page semantics beyond selecting the app and forwarding `app_page`; each app is responsible for mapping its own page segments to internal state.

## Rebuild Rule

If the app declares a frontend entrypoint, frontend updates should be published through:

```text
maverick app <app_id> frontend build --json
```

That is the official path that:

- runs the declared frontend build
- verifies the declared frontend artifact root
- emits `maverick.app.frontend-changed`
- lets mounted clients refresh without a manual full-page reload

Do not rely on ad hoc static servers or undocumented rebuild shortcuts.

Keep Vite HTML files as thin mount documents and put UI behavior in React source under `frontend/src`. The generated `package.json` build script runs `tsc --noEmit && vite build`, so frontend changes should type-check before mounted assets are refreshed.

## Live Update Rule

If app writes emit `app_events` such as `maverick.app.data-changed`, the mounted frontend should react to them without manual refresh.

Recommended pattern:

- listen for same-origin `postMessage` events such as `maverick.app.data-changed` when the app is mounted inside `base-shell`
- connect to the official app-event WebSocket at `/api/apps/events/ws` when the app also needs to refresh outside shell forwarding
- filter by `owner_app_id` and `resource`
- reload the affected view state through the app's own backend surface

Do not rely on stale startup-only fetches for stateful apps. If the app emits live change events, the frontend implementation should consume them.
