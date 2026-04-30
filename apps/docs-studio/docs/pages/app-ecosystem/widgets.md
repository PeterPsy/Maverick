# Widgets

Widgets are visual surfaces owned by the app that declares them. They can be embedded by a host app, but they do not create direct app-to-app data access.

## Ownership example

| Role | Owner |
| --- | --- |
| transcript container | `chat` |
| checklist renderer | `checklist` |
| registry and mount route | core |
| checklist data | `data/checklist` |

## Contract shape

```json
"widgets": [
  {
    "widget_id": "design-checklist",
    "host": "chat",
    "content_kinds": ["checklist.design"],
    "frontend": {
      "kind": "iframe",
      "mount": "frontend/dist/widgets/design-checklist",
      "spa_fallback": true
    },
    "actions": { "backend": true, "mcp": true, "cli": false }
  }
]
```

## Rules

- The embedding app must not import widget owner source.
- Widget state lives under `data/<widget_owner_app_id>`.
- If no widget is available, the host app should show a generic fallback.
