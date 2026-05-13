# Checklist

Workspace-local Maverick Checklist app.

Checklist is now an agent-owned planning surface rather than a user-editable checkbox list. It still supports simple checklist records for compatibility, but the primary persisted schema represents `agent_plan` and `execution` checklists with task status, priority, dependencies, suggested tools, blocked reasons, agent references, agent dialog references, and subtasks.

The frontend renders agent plans as a read-only process board for users. The sidebar footer opens an `Agent Plans` grid view that shows all visible checklists as bounded, scrollable plan cards, while selecting a specific checklist opens its full read-only process board. Agents create and update the work state through MCP, CLI, or backend actions; the UI listens for app data-change events and reflects the current state instead of letting a user manually change task status.

## Contract Notes

The app exposes the Maverick product contract:

- structured content kind: `checklist.design`
- widget content kind: `checklist.design`
- MCP tool: `checklist_tasklist`
- agent-planning MCP tools: `checklist_set_task_status`, `checklist_set_subtask_status`, `checklist_next_actions`
- agent context fields: `agent_ref`, `source_ref`, and `agent_dialogs`
- workspace board frontend
- chat-hosted iframe widget: `design-checklist`
- base-shell sidebar widgets: `checklist-sidebar` for `shell.sidebar.primary` and `checklist-sidebar-footer` for `shell.sidebar.footer`
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

For an agent plan, include richer task fields:

```json
{
  "action": "create",
  "payload": {
    "mode": "agent_plan",
    "title": "Implementazione feature",
    "priority": "high",
    "sections": [
      {
        "id": "implementation",
        "title": "Implementation",
        "tasks": [
          {
            "id": "schema",
            "title": "Aggiornare schema dati",
            "description": "Portare la checklist a schema agent-ready.",
            "status": "in-progress",
            "priority": "critical",
            "dependencies": ["requirements"],
            "tools": ["shell", "file-system", "test-runner"],
            "blocked_reason": "",
            "agent_ref": "agent:implementer",
            "source_ref": "chat:thread-123",
            "agent_dialogs": [
              {
                "id": "dialog-1",
                "title": "Implementation handoff",
                "summary": "Agent explained the next implementation steps.",
                "ref": "chat:thread-123#turn-4",
                "agent_ref": "agent:implementer"
              }
            ],
            "subtasks": [
              {
                "id": "tests",
                "title": "Aggiungere test di migrazione",
                "status": "pending",
                "priority": "high",
                "tools": ["test-runner"],
                "agent_ref": "agent:tester",
                "source_ref": "chat:thread-123#turn-5",
                "agent_dialogs": ["chat:thread-123#turn-5"]
              }
            ]
          }
        ]
      }
    ]
  }
}
```

The response includes `chat_render`, which a chat host can render with the `design-checklist` widget. The structured payload is intentionally minimal and carries only the checklist id; the widget resolves the full checklist state from the Checklist backend. The widget registry uses `checklist.design`. The chat widget reports content-based pixel resize messages and expects the host to cap long checklists instead of letting them stretch the transcript indefinitely.
