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
maverick core cli list --json
maverick core cli inspect <command_id> --json
maverick app <app_id> cli list --json
maverick app <app_id> cli inspect <command_name> --json
```

## MCP discovery

```bash
maverick core mcp list --json
maverick core mcp inspect <tool_name> --json
maverick app <app_id> mcp list --json
maverick app <app_id> mcp inspect <tool_name> --json
```

## Invocation rule

Tool or command visibility is not sufficient authority. The core still enforces workspace context, install state, enablement, role policy, sandbox policy, and owner scoping.
