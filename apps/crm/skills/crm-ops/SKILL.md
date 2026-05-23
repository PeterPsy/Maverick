---
name: crm-ops
description: Use the `crm` Maverick app through its declared CLI and MCP surfaces.
---

# CRM Operations

Use CRM when the user asks to search, create, update, convert leads, configure pipeline stages, tag, archive, delete, bulk-edit, merge duplicates, summarize, report on sales metrics, inspect audit events, import, export, dedupe, save views, define typed custom fields, enrich records, generate account briefs, propose/approve CRM workflows, generate automation proposals, link external app references, or inspect workspace CRM records.

Use scoped discovery first:

```bash
maverick app crm cli list --json
maverick app crm mcp list --json
```

Prefer MCP tools for agent-facing record operations:

- `crm_search`
- `crm_get_record`
- `crm_create_lead`
- `crm_update_lead`
- `crm_convert_lead`
- `crm_create_contact`
- `crm_update_contact`
- `crm_create_account`
- `crm_update_account`
- `crm_create_deal`
- `crm_update_deal`
- `crm_move_deal`
- `crm_create_pipeline`
- `crm_update_pipeline`
- `crm_create_pipeline_stage`
- `crm_update_pipeline_stage`
- `crm_log_activity`
- `crm_create_task`
- `crm_update_task`
- `crm_create_note`
- `crm_update_note`
- `crm_archive_record`
- `crm_unarchive_record`
- `crm_delete_record`
- `crm_tag_record`
- `crm_untag_record`
- `crm_bulk_update`
- `crm_merge_records`
- `crm_timeline`
- `crm_audit_log`
- `crm_sales_reports`
- `crm_filter_records`
- `crm_find_duplicates`
- `crm_list_saved_views`
- `crm_save_view`
- `crm_delete_saved_view`
- `crm_apply_saved_view`
- `crm_schema`
- `crm_list_custom_fields`
- `crm_define_custom_field`
- `crm_archive_custom_field`
- `crm_set_custom_fields`
- `crm_list_automation_rules`
- `crm_create_automation_rule`
- `crm_update_automation_rule`
- `crm_record_enrichment`
- `crm_intelligent_next_actions`
- `crm_propose_workflows`
- `crm_run_automation_rules`
- `crm_list_workflow_proposals`
- `crm_approve_workflow_proposal`
- `crm_apply_workflow_proposal`
- `crm_link_external_ref`
- `crm_unlink_external_ref`
- `crm_list_external_refs`
- `crm_external_timeline`
- `crm_list_next_actions`
- `crm_summarize_account`
- `crm_account_brief`
- `crm_import_preview`
- `crm_import_commit`
- `crm_health`

Use CLI command `crm` for diagnostics, import/export smoke checks, and scripted workflows. Do not read or write CRM private data files directly when an official CRM surface can perform the operation.
