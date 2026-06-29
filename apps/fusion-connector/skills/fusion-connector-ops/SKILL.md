---
name: fusion-connector-ops
description: Use the `fusion-connector` Maverick app through its declared CLI and MCP surfaces.
---

# Fusion Connector Operations

Use the app's official CLI or MCP surfaces. Do not read or write another app's private data.

## Operating Model

Fusion Connector is headless. There is no Maverick frontend for v1.

Autodesk Fusion must be open on the same host as Maverick and its local Fusion MCP Server must be enabled. The default endpoint is:

```text
http://127.0.0.1:27182/mcp
```

The Autodesk account is managed by Fusion itself. Do not ask the user to connect an Autodesk account inside Maverick for this local-MCP workflow.

## Tool Use

Start every Fusion task with:

1. `fusion_status`
2. `fusion_list_tools`
3. `fusion_call_tool` using an exact tool name returned by `fusion_list_tools`

For mutating or unknown operations, ask the user for explicit confirmation before retrying with `confirm: true`.

Do not bypass the connector by trying to read Fusion files or app data directly. Do not expose the Fusion MCP endpoint beyond loopback.
