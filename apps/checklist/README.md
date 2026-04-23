# Checklist

Workspace-local Maverick v3 port of the Maverick 2 `checklists` app.

The app keeps the v2 product contract:

- legacy structured content kind: `design_checklist`
- v3 widget content kind: `checklist.design`
- MCP tool: `maverick_tasklist`
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

The port does not use Maverick 2 memory-store services. Checklist data is owned by this app under the v3 workspace data root.

## SDK Flow

```bash
./scripts/maverick app validate checklist --workspace default
./scripts/maverick app register-local checklist --workspace default
./scripts/maverick app install-local checklist --workspace default
./scripts/maverick app status checklist --workspace default
./scripts/maverick app package checklist --workspace default
```

## MCP Shape

Use `maverick_tasklist` with:

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

The response includes `chat_render`, which a chat host can render with the `design-checklist` widget. The v3 widget registry uses `checklist.design`; `legacy_kind` preserves the Maverick 2 `design_checklist` identifier.
