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
maverick app fusion-connector mcp call fusion_session_brief --json
```

If `fusion_session_brief` returns `connected: false`, check that Fusion is open, MCP is enabled, and the tunnel is still running when Fusion is not on the same host.

`fusion_session_brief` is the fast path for routine CAD work. It returns connection state, compact tool names, and open-document metadata without dumping full tool descriptions into chat. Use `fusion_list_tools --limit 20` only when you need the full dynamic input schemas.

The current Autodesk Fusion MCP server commonly exposes these tools:

- `fusion_mcp_read`: read documents, projects, API docs, and screenshots.
- `fusion_mcp_execute`: execute scripts or document open/close/save operations.
- `fusion_mcp_update`: undo/redo.
- `fusion_mcp_electronics_read`: read Electronics documents.

Always use exact tool names returned by `fusion_session_brief` or `fusion_list_tools`; Autodesk can change the dynamic tool list.

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
```

Prefer the connector-owned screenshot capture tool for visual verification:

```bash
maverick app fusion-connector mcp call fusion_capture_screenshot --json --arguments-json \
'{"width":960,"height":720,"direction":"iso-top-right"}'
```

It writes a PNG under `data/fusion-connector/screenshots/` and returns metadata/path fields instead of inline base64. Raw screenshot responses can contain large base64 image data that may be compacted before the agent can inspect it.

For CAD-building tasks, avoid one large script. Use staged scripts with focused geometry changes, verify each stage, and pass `request_timeout_seconds` up to 30 seconds when the stage is expected to be slow. If a mutating call times out, do not immediately retry the same mutation; check `fusion_status` and `fusion_audit_recent` first because Fusion may still be executing.

Do not assume the active document can accept `addNewComponent`; some Fusion part documents only allow root-component bodies. Inspect or handle this case and use named root bodies with a stable prefix when component creation is not supported.

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
