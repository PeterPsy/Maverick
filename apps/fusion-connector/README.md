# Fusion Connector

Headless Maverick connector for Autodesk Fusion's local MCP server.

Fusion must be open on the same host as Maverick, with **Fusion MCP Server** enabled in Fusion preferences. The default endpoint is:

```text
http://127.0.0.1:27182/mcp
```

This app intentionally has no frontend. It exposes CLI, MCP, and a bundled skill so users can operate Fusion from chat while Maverick keeps endpoint validation, policy checks, and audit records inside the app boundary.

## Capabilities

- Check Fusion MCP reachability.
- Discover the dynamic tool list exposed by Fusion.
- Call one discovered Fusion MCP tool after allowlist/denylist and confirmation checks.
- Store connector config and audit records under `data/fusion-connector/state.json`.
- Keep endpoint targets loopback-only for v1.

Mutating or unknown Fusion tools require explicit confirmation with `confirm: true`. The default denylist blocks broad scripting and shell-like tool names.

## MCP Workflow

```bash
maverick app fusion-connector mcp call fusion_status --json
maverick app fusion-connector mcp call fusion_list_tools --json --limit 100
maverick app fusion-connector mcp call fusion_call_tool --json \
  --fusion_tool_name '<tool from fusion_list_tools>' \
  --tool_arguments_json '{}'
```

For mutating operations, ask the user first and then include:

```text
--confirm true
```

## CLI Workflow

```bash
maverick app fusion-connector cli run fusion-connector --json --action status
maverick app fusion-connector cli run fusion-connector --json --action list_tools --limit 100
maverick app fusion-connector cli run fusion-connector --json --action audit_recent --limit 20
```

Update config:

```bash
maverick app fusion-connector cli run fusion-connector --json \
  --action config_set \
  --confirm true \
  --endpoint http://127.0.0.1:27182/mcp
```

## Validate

```bash
maverick core cli run core.app-sdk.validate --app-id fusion-connector --json
```

## Workspace-Local Install

```bash
maverick core cli run core.app-sdk.register-local --app-id fusion-connector --workspace default --json
maverick core cli run core.app-sdk.install-local --app-id fusion-connector --workspace default --json
```
