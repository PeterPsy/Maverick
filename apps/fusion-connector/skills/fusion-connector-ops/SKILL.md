---
name: fusion-connector-ops
description: Use the `fusion-connector` Maverick app through its declared CLI and MCP surfaces.
---

# Fusion Connector Operations

Use the `fusion-connector` app's official CLI or MCP surfaces to inspect and modify Autodesk Fusion through Fusion's local MCP server.

## Operating Model

Fusion Connector is headless. There is no Maverick frontend for v1.

Autodesk Fusion must be open with Fusion MCP Server enabled. The connector endpoint must resolve from the Maverick host. The default endpoint is:

```text
http://127.0.0.1:27182/mcp
```

If Fusion is on a Mac and Maverick is on Ubuntu, keep a reverse SSH tunnel open from the Mac:

```bash
ssh -i ~/.ssh/maverick_fusion_tunnel -N -T \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -R 127.0.0.1:27182:127.0.0.1:27182 \
  ubuntu@<maverick-ubuntu-host>
```

The Autodesk account is managed by Fusion itself. Do not ask the user to connect an Autodesk account inside Maverick for this local-MCP workflow. Do not expose the Fusion MCP endpoint beyond loopback.

## Required Discovery

Start every Fusion task with:

```bash
maverick app fusion-connector mcp call fusion_status --json
maverick app fusion-connector mcp call fusion_list_tools --json --limit 20
```

If `fusion_status` returns `connected: false`, check that Fusion is open, MCP is enabled, and the tunnel is still running when Fusion is not on the same host.

The current Autodesk Fusion MCP server commonly exposes these tools:

- `fusion_mcp_read`: read documents, projects, API docs, and screenshots.
- `fusion_mcp_execute`: execute scripts or document open/close/save operations.
- `fusion_mcp_update`: undo/redo.
- `fusion_mcp_electronics_read`: read Electronics documents.

Always use exact tool names returned by `fusion_list_tools`; Autodesk can change the dynamic tool list.

## Calling Fusion Tools

Use `fusion_call_tool` with `--arguments-json` for nested arguments:

```bash
maverick app fusion-connector mcp call fusion_call_tool --json --arguments-json \
'{"fusion_tool_name":"fusion_mcp_read","tool_arguments":{"queryType":"document","operation":"open"}}'
```

Useful read-only checks:

```bash
maverick app fusion-connector mcp call fusion_call_tool --json --arguments-json \
'{"fusion_tool_name":"fusion_mcp_read","tool_arguments":{"queryType":"projects"}}'

maverick app fusion-connector mcp call fusion_call_tool --json --arguments-json \
'{"fusion_tool_name":"fusion_mcp_read","tool_arguments":{"queryType":"screenshot","width":640,"height":480,"direction":"iso-top-right"}}'
```

Screenshot responses can contain large base64 image data. Summarize or save them through Storage instead of dumping the full payload into chat.

For mutating or unknown operations, ask the user for explicit confirmation before retrying with `confirm: true`.

Example mutating call shape:

```bash
maverick app fusion-connector mcp call fusion_call_tool --json --arguments-json \
'{"fusion_tool_name":"fusion_mcp_execute","confirm":true,"tool_arguments":{"featureType":"script","object":{"script":"import adsk.core\n\ndef run(_context: str):\n    print(adsk.core.Application.get().version)\n"}}}'
```

Undo the last Fusion operation after user confirmation:

```bash
maverick app fusion-connector mcp call fusion_call_tool --json --arguments-json \
'{"fusion_tool_name":"fusion_mcp_update","confirm":true,"tool_arguments":{"featureType":"undo"}}'
```

Do not save, close, overwrite, delete, or run arbitrary scripts unless the user explicitly approves the exact intended effect.

## Connector Management

Inspect config:

```bash
maverick app fusion-connector mcp call fusion_config_get --json
```

Read audit:

```bash
maverick app fusion-connector mcp call fusion_audit_recent --json --limit 20
```

Audit records use `ok` for connector/transport success. When Autodesk returns JSON text, the connector also records bounded Fusion semantic fields: `fusion_success`, `fusion_message`, `fusion_error`, and `fusion_failure_reason`.

Update policy only with explicit approval:

```bash
maverick app fusion-connector mcp call fusion_config_set --json --arguments-json \
'{"confirm":true,"tool_denylist":["eval","filesystem","open_url","python","script","shell","terminal"]}'
```

Do not bypass the connector by reading Fusion files, editing another app's data, or calling the Fusion MCP endpoint directly unless debugging the connector itself.
