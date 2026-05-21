---
name: crm-ops
description: Use the `crm` Maverick app through its declared CLI and MCP surfaces.
---

# CRM Operations

Use CRM when the user asks to search, create, update, summarize, import, export, or inspect workspace CRM records.

Use scoped discovery first:

```bash
maverick app crm cli list --json
maverick app crm mcp list --json
```

Prefer MCP tools for agent-facing record operations:

- `crm_search`
- `crm_get_record`
- `crm_create_contact`
- `crm_update_contact`
- `crm_create_account`
- `crm_update_account`
- `crm_create_deal`
- `crm_update_deal`
- `crm_move_deal`
- `crm_log_activity`
- `crm_list_next_actions`
- `crm_summarize_account`
- `crm_import_preview`
- `crm_import_commit`
- `crm_health`

Use CLI command `crm` for diagnostics, import/export smoke checks, and scripted workflows. Do not read or write CRM private data files directly when an official CRM surface can perform the operation.
