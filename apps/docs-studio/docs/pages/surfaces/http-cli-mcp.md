# HTTP, CLI, and MCP

## HTTP

Core HTTP routes expose platform state and mounted app entrypoints. Examples:

- `/api/session`
- `/api/workspaces`
- `/api/apps`
- `/api/app-store/installations`
- `/api/runtime/status`
- `/api/providers/active`

App backend actions are mounted through:

```text
/api/apps/<app_id>/backend
```

## CLI discovery

```bash
loopino core cli list --json
loopino core cli inspect <command_id> --json
loopino app <app_id> cli list --json
loopino app <app_id> cli inspect <command_name> --json
```

## MCP discovery

```bash
loopino core mcp list --json
loopino core mcp inspect <tool_name> --json
loopino app <app_id> mcp list --json
loopino app <app_id> mcp inspect <tool_name> --json
```

## Invocation rule

Tool or command visibility is not sufficient authority. The core still enforces workspace context, install state, enablement, role policy, sandbox policy, and owner scoping.
