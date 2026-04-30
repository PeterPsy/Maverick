---
name: dynamic-views
description: "Use when the user wants a custom persisted visual or interactive view rendered in chat or reopened later from the Dynamic Views library."
---

# Dynamic Views

Use Dynamic Views for custom visualizations, dashboards, cards, inspectors, and interactive embeds that should persist in the active Maverick workspace, render in chat, and reopen from the Dynamic Views library.

Prefer the `app.dynamic-views.dynamic-views` CLI command for agent work. Use the `app.dynamic-views.maverick_dynamic_views` MCP tool only when the caller specifically needs MCP transport or the CLI surface is unavailable. The same app behavior is also available through `/api/apps/dynamic-views/backend` for app/frontend flows.

Do not paste raw HTML, CSS, or JavaScript into chat after the CLI or tool succeeds. Successful `create`, `read`, and `recall` actions return `chat_render.kind: "dynamic.view.instance"` and a `chat_render.payload` that Chat can render through the registry-mounted Dynamic Views widget.

After creating or recalling a Dynamic View, always make the view visible in chat by returning either the raw `chat_render` object or a `{ "structured_content": ... }` envelope in the final agent message. Do not stop at "created id=..." unless the caller explicitly asked for an ID-only operation. If the current runtime cannot normalize that envelope into `runtime.output.structured`, treat that as a generic runtime/app-surface bridge gap, not as a reason to hardcode Dynamic Views behavior in Chat.

## Actions

- `create`: create a package and a persisted instance. Put title and summary under `payload`, render source under `payload.package`, data under `payload.data`, bindings under `payload.dataBindings`, and mode under `payload.snapshotMode`.
- `read` or `recall`: reopen one instance by `id`, `target_id`, or `instance_id`.
- `list`: list saved instances in the active workspace.
- `delete`: remove one instance by `id`, `target_id`, or `instance_id`.
- `health.check`: check app state from the Dynamic Views service.

## Renderer Contract

Dynamic Views currently supports only `sandbox_html_v1`.

The renderer receives this browser global inside the sandboxed iframe:

```js
window.MaverickDynamicView = {
  data: {},
  dataBindings: [],
  metadata: {
    id: "view_...",
    title: "View title",
    summary: "",
    snapshotMode: "snapshot",
    frameId: "view_..."
  }
};
```

Use `window.MaverickDynamicView.data` for input data. Use `window.MaverickDynamicView.dataBindings` only for source provenance or source snapshots.

## Create Payload

```json
{
  "action": "create",
  "payload": {
    "title": "Revenue Probe",
    "summary": "Mini dashboard for current revenue snapshot",
    "package": {
      "renderer": "sandbox_html_v1",
      "html": "<main><h1>Revenue Probe</h1><div id=\"root\"></div></main>",
      "css": "body { font-family: system-ui; }",
      "javascript": "document.getElementById('root').textContent = JSON.stringify(window.MaverickDynamicView.data, null, 2);",
      "tags": ["finance"],
      "dataSchema": {}
    },
    "data": {
      "headline": "Revenue",
      "value": 42
    },
    "dataBindings": [
      {
        "sourceType": "inline",
        "sourceRef": "revenue_probe_seed",
        "snapshot": {
          "headline": "Revenue",
          "value": 42
        }
      }
    ],
    "snapshotMode": "snapshot"
  }
}
```

The service also accepts snake_case equivalents for `data_bindings`, `snapshot_mode`, `source_type`, `source_ref`, and `data_schema`, but prefer the camelCase shape above because it is what the frontend widget payload uses.

## Authoring Rules

- Keep packages self-contained and deterministic.
- Do not reference remote scripts, nested iframes, browser storage APIs, network APIs, cookies, or parent window access.
- Avoid blocked JavaScript constructs: `import(`, `fetch(`, `XMLHttpRequest`, `WebSocket(`, `document.cookie`, `localStorage`, `sessionStorage`, `window.parent`, `window.top`, and `window.opener`.
- Keep combined HTML, CSS, and JavaScript below the app source size limit.
- Prefer `snapshotMode: "snapshot"` unless the user explicitly wants live data semantics.
- Use `dataBindings` when the view is grounded in a remembered source.
- Make the view responsive. The widget iframe clamps its height between roughly 260px and 960px and auto-resizes from document height reports.
- Return or reference the tool result instead of duplicating source code in the assistant response.
