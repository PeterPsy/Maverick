---
name: crm-ops
description: "Use the CRM app to retrieve and maintain workspace accounts, contacts, deals, activities, and CRM reference entities."
---

# CRM Ops

Use this skill when a task needs structured business context about companies, people, opportunities, or interactions.

Prefer the mounted CRM backend HTTP surface when the user is looking at the CRM UI or expects records to appear live. This calls the app through the running core process, so `maverick.app.data-changed` is published to mounted frontends:

```bash
curl -sS -X POST http://127.0.0.1:8014/api/apps/crm/backend \
  -H 'Content-Type: application/json' \
  -d '{"action":"search","query":"Acme Mario Rossi","limit":10}'
```

Use the CRM CLI for compact, low-context operations only when live UI update is not required or the command is running inside the same platform invocation path:

```bash
maverick app crm cli run crm --action search --query "Acme Mario Rossi"
maverick app crm cli run crm --action list_deals
maverick app crm cli run crm --action create_account --name "Acme Spa"
maverick app crm cli run crm --action set_custom_view --title "Acme pursuit" --refs '[{"app_id":"crm","entity_type":"deal","entity_id":"deal_123"}]'
```

Use MCP tools when the runtime already has the CRM server mounted or when a richer tool interface is preferable:

- `crm_search`
- `crm_get`
- `crm_create_account`
- `crm_create_contact`
- `crm_create_deal`
- `crm_add_activity`
- `crm_link_entities`
- `crm_reference_search`
- `crm_reference_resolve`
- `crm_reference_summarize`
- `crm_view_filter`
- `crm_set_view_filter`
- `crm_set_custom_view`
- `crm_clear_custom_view`

CRM is the structured source of truth for accounts, contacts, deals, and activities. Memory may link to CRM records, but it should not duplicate the full CRM record when a reference is enough.

Use official CRM surfaces for writes. Do not edit `data/crm/crm.sqlite` or CRM JSON state directly during normal operations. Do not bootstrap a separate Python `PlatformState` process for user-visible CRM writes, because its in-memory event bus is not the browser's running server. For user-visible writes, call `/api/apps/crm/backend` on the active core host or use an MCP/CLI surface wired through the active platform process.

Every successful CRM write should emit `maverick.app.data-changed` for the `records` resource so the mounted CRM UI updates live without polling.

Use the view actions when the user wants the CRM UI to show a curated set of accounts, contacts, deals, or activities selected from Memory or another app surface.
