# Fusion Connector

Headless Maverick connector for Autodesk Fusion's local MCP server.

Fusion must be open with **Fusion MCP Server** enabled in Fusion preferences. The connector endpoint must resolve from the Maverick host. The default endpoint is:

```text
http://127.0.0.1:27182/mcp
```

This app intentionally has no frontend. It exposes CLI, MCP, and a bundled skill so users can operate Fusion from chat while Maverick keeps endpoint validation, policy checks, and audit records inside the app boundary.

For agent-to-agent handoff details, see `docs/agent-handoff.md`.

## Capabilities

- Check Fusion MCP reachability.
- Discover the dynamic tool list exposed by Fusion.
- Return a compact session brief with connection status, tool names, and open-document metadata in one call.
- Call one discovered Fusion MCP tool after allowlist/denylist and confirmation checks.
- Capture viewport screenshots to app-owned data without returning inline base64.
- Store connector config and audit records under `data/fusion-connector/state.json`.
- Keep endpoint targets loopback-only for v1.

Mutating or unknown Fusion tools require explicit confirmation with `confirm: true`. The default denylist blocks broad scripting and shell-like tool names.

## Mac To Ubuntu Tunnel

When Fusion runs on a Mac and Maverick runs on Ubuntu, open a reverse SSH tunnel from the Mac:

```bash
lsof -nP -iTCP:27182 -sTCP:LISTEN
ssh -i ~/.ssh/maverick_fusion_tunnel -N -T \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -R 127.0.0.1:27182:127.0.0.1:27182 \
  ubuntu@<maverick-ubuntu-host>
```

Keep the SSH process running while Maverick uses Fusion.

## MCP Workflow

```bash
maverick app fusion-connector mcp call fusion_session_brief --json
maverick app fusion-connector mcp call fusion_call_tool --json --arguments-json \
'{"fusion_tool_name":"<tool name from fusion_session_brief>","tool_arguments":{}}'
```

Use `fusion_status` and `fusion_list_tools` separately only when you need full tool schemas or are debugging connection state.

Capture a screenshot for agent verification without triggering output compaction:

```bash
maverick app fusion-connector mcp call fusion_capture_screenshot --json --arguments-json \
'{"width":960,"height":720,"direction":"iso-top-right"}'
```

The response returns metadata and paths under `data/fusion-connector/screenshots/`; it does not return inline image base64.

For mutating operations, ask the user first and then include:

```text
--confirm true
```

## CLI Workflow

```bash
maverick app fusion-connector cli run fusion-connector --json --action status
maverick app fusion-connector cli run fusion-connector --json --action session_brief
maverick app fusion-connector cli run fusion-connector --json --action list_tools --limit 100
maverick app fusion-connector cli run fusion-connector --json --action capture_screenshot --width 960 --height 720
maverick app fusion-connector cli run fusion-connector --json --action audit_recent --limit 20
```

For nested call arguments, prefer MCP with `--arguments-json`.

Update config:

```bash
maverick app fusion-connector mcp call fusion_config_set --json --arguments-json \
'{"confirm":true,"endpoint":"http://127.0.0.1:27182/mcp"}'
```

## Agent Handoff Notes

Use machine-readable discovery, not guessed commands:

```bash
maverick app fusion-connector mcp list --json
maverick app fusion-connector mcp inspect fusion_call_tool --json
maverick app fusion-connector cli inspect fusion-connector --json
```

Known Autodesk Fusion MCP tools observed in v1 testing:

- `fusion_mcp_read`
- `fusion_mcp_execute`
- `fusion_mcp_update`
- `fusion_mcp_electronics_read`

Read open documents:

```bash
maverick app fusion-connector mcp call fusion_session_brief --json
```

Capture a screenshot without dumping the full base64 payload into chat:

```bash
maverick app fusion-connector mcp call fusion_capture_screenshot --json --arguments-json \
'{"width":640,"height":480,"direction":"iso-top-right"}'
```

Undo after user confirmation:

```bash
maverick app fusion-connector mcp call fusion_call_tool --json --arguments-json \
'{"fusion_tool_name":"fusion_mcp_update","confirm":true,"tool_arguments":{"featureType":"undo"}}'
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
