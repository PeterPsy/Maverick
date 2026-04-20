---
name: dynamic-views
description: "Use when the user wants a custom persisted visual or interactive view rendered in chat or reopened later from the Dynamic Views library."
---

# Dynamic Views

Use Dynamic Views for custom visualizations, dashboards, cards, inspectors, and interactive embeds that should persist in the active Maverick workspace and render in chat.

Prefer the `app.dynamic-views.maverick_dynamic_views` MCP tool. Do not paste raw HTML, CSS, or JavaScript into the chat after the tool succeeds.

Successful create and read actions return `chat_render.kind: "dynamic.view.instance"` for the chat widget registry.

## Actions

- `create`: create a package and an instance. Put the render source under `payload.package`, data under `payload.data`, bindings under `payload.dataBindings`, and mode under `payload.snapshotMode`.
- `read` or `recall`: reopen an instance by `id`, `target_id`, or `instance_id`.
- `list`: list saved instances in the active workspace.
- `delete`: remove an instance by id.

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
      "javascript": "document.getElementById('root').textContent = JSON.stringify(window.MaverickDynamicView.data, null, 2);"
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

## Authoring Rules

- Keep packages self-contained and deterministic.
- Do not reference remote scripts, nested iframes, browser storage APIs, network APIs, cookies, or parent window access.
- Prefer `snapshotMode: "snapshot"` unless the user explicitly wants live data semantics.
- Use `dataBindings` when the view is grounded in a remembered source.
