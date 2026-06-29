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
| `fusion_call_tool` | Call one discovered Autodesk tool after policy checks. |
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

Always call `fusion_list_tools` first and use the returned exact tool name and schema.

## Read-Only Smoke Tests

Status:

```bash
maverick app fusion-connector mcp call fusion_status --json
```

Open documents:

```bash
maverick app fusion-connector mcp call fusion_call_tool --json --arguments-json \
'{"fusion_tool_name":"fusion_mcp_read","tool_arguments":{"queryType":"document","operation":"open"}}'
```

Projects:

```bash
maverick app fusion-connector mcp call fusion_call_tool --json --arguments-json \
'{"fusion_tool_name":"fusion_mcp_read","tool_arguments":{"queryType":"projects"}}'
```

Screenshot:

```bash
maverick app fusion-connector mcp call fusion_call_tool --json --arguments-json \
'{"fusion_tool_name":"fusion_mcp_read","tool_arguments":{"queryType":"screenshot","width":640,"height":480,"direction":"iso-top-right"}}'
```

Do not dump large screenshot base64 into chat. Summarize it or write it to Storage.

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
