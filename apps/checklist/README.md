# Checklist

Workspace-local Maverick Checklist app.

## Contract Notes

The app exposes the Maverick product contract:

- structured content kind: `checklist.design`
- widget content kind: `checklist.design`
- MCP tool: `checklist_tasklist`
- workspace board frontend
- chat-hosted iframe widget: `design-checklist`
- app-owned JSON state under `data/checklist/state.json`
- reference entity: `checklist`
- view surface: `main` with standard board state actions

Agents can now discover three CLI surfaces:

- `checklist`
- `checklist-reference`
- `checklist-view`

and the matching MCP/reference/view tools through scoped app discovery.

Checklist data is owned by this app under the workspace data root.

## SDK Flow

```bash
./scripts/maverick core cli run core.app-sdk.validate --app-id checklist --workspace default --json
./scripts/maverick core cli run core.app-sdk.register-local --app-id checklist --workspace default --json
./scripts/maverick core cli run core.app-sdk.install-local --app-id checklist --workspace default --json
./scripts/maverick core cli run core.app-sdk.status --app-id checklist --workspace default --json
./scripts/maverick core cli run core.app-sdk.package --app-id checklist --workspace default --json
```

## MCP Shape

Use `checklist_tasklist` with:

```json
{
  "action": "create",
  "payload": {
    "title": "Lancio agenzia",
    "summary": "Checklist iniziale",
    "sections": [
      {
        "id": "foundations",
        "title": "Fondamenta",
        "tasks": [
          {"id": "name", "title": "Definire nome", "checked": false}
        ]
      }
    ]
  }
}
```

The response includes `chat_render`, which a chat host can render with the `design-checklist` widget. The structured payload is intentionally minimal and carries only the checklist id; the widget resolves the full checklist state from the Checklist backend. The widget registry uses `checklist.design`.
