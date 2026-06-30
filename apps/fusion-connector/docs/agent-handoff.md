# Fusion Connector Agent Handoff

This document is the operational handoff for agents using `fusion-connector`.

## App State

- App id: `fusion-connector`
- Source mode: workspace-local, editable
- Frontend: none
- Runtime mode: full-access only
- Default Fusion endpoint from Maverick host: `http://127.0.0.1:27182/mcp`
- App-owned state: `data/fusion-connector/state.json`
- Bundled skill source: `apps/fusion-connector/skills/fusion-connector-ops/SKILL.md`

The Autodesk account is managed by Fusion, not by Maverick.

## Required Host Link

If Fusion runs on the same host as Maverick, no tunnel is needed.

If Fusion runs on a Mac and Maverick runs on Ubuntu, open a reverse SSH tunnel from the Mac:

```bash
lsof -nP -iTCP:27182 -sTCP:LISTEN
ssh -i ~/.ssh/maverick_fusion_tunnel -N -T \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -R 127.0.0.1:27182:127.0.0.1:27182 \
  ubuntu@<maverick-ubuntu-host>
```

Keep that SSH process running while using Fusion from Maverick.

## Maverick Discovery

Use scoped discovery every time rather than guessing:

```bash
maverick app fusion-connector mcp list --json
maverick app fusion-connector mcp call fusion_session_brief --json
maverick app fusion-connector mcp inspect fusion_call_tool --json
maverick app fusion-connector cli list --json
maverick app fusion-connector cli inspect fusion-connector --json
```

All executable surfaces require a trusted workspace context and full-access mode.

## Connector MCP Tools

| Tool | Purpose |
| --- | --- |
| `fusion_status` | Check whether Fusion MCP is reachable and list a compact tool preview. |
| `fusion_list_tools` | Discover Autodesk Fusion MCP tools and input schemas. |
| `fusion_session_brief` | Return compact connection, tool-name, and open-document context in one call. |
| `fusion_call_tool` | Call one discovered Autodesk tool after policy checks. |
| `fusion_capture_screenshot` | Save a viewport screenshot to app-owned data and return metadata instead of inline base64. |
| `fusion_config_get` | Read endpoint, timeout, allowlist, denylist, and confirmation policy. |
| `fusion_config_set` | Update config. Requires `confirm: true`. Endpoint remains loopback-only. |
| `fusion_audit_recent` | Read recent connector audit records. |
| `fusion_operations_manifest` | Compact app operations manifest. |
| `fusion_connector_reference_manifest` | Required empty reference manifest for this headless connector. |

## Autodesk Tools Observed In V1

The Fusion MCP server has a dynamic tool list. In v1 testing it exposed:

| Autodesk tool | Use |
| --- | --- |
| `fusion_mcp_read` | Read projects, open/recent/search documents, API docs, and screenshots. |
| `fusion_mcp_execute` | Execute Python script operations and document open/close/save operations. |
| `fusion_mcp_update` | Undo/redo. |
| `fusion_mcp_electronics_read` | Read Electronics design data when an Electronics document is active. |

For routine CAD tasks, start with `fusion_session_brief`. It reuses one MCP client to return connection state, compact tool names, and active open-document metadata without dumping full tool descriptions into chat. Follow with `fusion_list_tools` only when you need a full dynamic input schema. Always use an exact tool name returned by one of those discovery calls.

## Read-Only Smoke Tests

Status:

```bash
maverick app fusion-connector mcp call fusion_session_brief --json
```

Open documents:

```bash
maverick app fusion-connector mcp call fusion_session_brief --json
```

Projects:

```bash
maverick app fusion-connector mcp call fusion_call_tool --json --arguments-json \
'{"fusion_tool_name":"fusion_mcp_read","tool_arguments":{"queryType":"projects"}}'
```

Screenshot:

```bash
maverick app fusion-connector mcp call fusion_capture_screenshot --json --arguments-json \
'{"width":960,"height":720,"direction":"iso-top-right"}'
```

Prefer `fusion_capture_screenshot` over raw `fusion_mcp_read` screenshots. Raw screenshot calls return inline base64 that can be compacted before the agent can inspect it. The capture tool stores the PNG under `data/fusion-connector/screenshots/` and returns `app_data_relative_path`, `workspace_relative_path`, MIME type, dimensions, and byte size.

## Mutating Calls

Ask for explicit user confirmation before mutating calls. Then include `confirm: true`.

Minimal script shape:

```bash
maverick app fusion-connector mcp call fusion_call_tool --json --arguments-json \
'{"fusion_tool_name":"fusion_mcp_execute","confirm":true,"tool_arguments":{"featureType":"script","object":{"script":"import adsk.core\n\ndef run(_context: str):\n    print(adsk.core.Application.get().version)\n"}}}'
```

Undo:

```bash
maverick app fusion-connector mcp call fusion_call_tool --json --arguments-json \
'{"fusion_tool_name":"fusion_mcp_update","confirm":true,"tool_arguments":{"featureType":"undo"}}'
```

Do not save, close, overwrite, delete, or run arbitrary scripts unless the user explicitly approves the exact intended effect.

For CAD-building scripts, avoid one large monolithic script. Use staged scripts with focused bodies/features, pass a higher per-call `request_timeout_seconds` when needed, and verify each stage with `fusion_status`, `fusion_audit_recent`, or `fusion_capture_screenshot`. Autodesk Fusion may continue executing after the connector request times out, so follow a timeout with status/audit checks before retrying.

Do not assume the active Fusion document can accept a new component. Some part documents allow only the root component. Probe or handle that failure and fall back to named root bodies with a stable prefix instead of failing the whole build.

## CLI Surface

The CLI command is useful for simple actions:

```bash
maverick app fusion-connector cli run fusion-connector --json --action status
maverick app fusion-connector cli run fusion-connector --json --action list_tools --limit 20
maverick app fusion-connector cli run fusion-connector --json --action audit_recent --limit 20
```

Prefer MCP with `--arguments-json` for nested Fusion tool arguments.

## Policy And Audit

Read config:

```bash
maverick app fusion-connector mcp call fusion_config_get --json
```

Read audit:

```bash
maverick app fusion-connector mcp call fusion_audit_recent --json --limit 20
```

Default denylist intentionally blocks broad script-like tool names while allowing Autodesk's `fusion_mcp_execute` tool name. The connector still requires `confirm: true` for mutating or unknown tool calls.

Audit records distinguish connector transport success from Fusion semantic success when Autodesk returns JSON text:

- `ok`: connector call completed without a connector/transport exception.
- `fusion_success`: Fusion-reported operation result when present.
- `fusion_message`, `fusion_error`, `fusion_failure_reason`: bounded Fusion result details when present.
