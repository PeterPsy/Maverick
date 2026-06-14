"""MCP entrypoint for Website Studio."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import app_events_for_action, handle_action, resolve_secret_resource


TOOL_ACTIONS = {
    "website_manifest": "manifest",
    "website_sites_list": "sites_list",
    "website_bootstrap": "bootstrap",
    "website_site_status": "site_status",
    "website_site_create": "site_create",
    "website_site_archive": "site_archive",
    "website_site_restore": "site_restore",
    "website_site_rename": "site_rename",
    "website_site_duplicate": "site_duplicate",
    "website_site_set_active": "site_set_active",
    "website_git_connections_list": "git_connections_list",
    "website_git_connection_prepare": "git_connection_prepare",
    "website_git_connection_activate": "git_connection_activate",
    "website_environments_list": "environments_list",
    "website_environment_configure": "environment_configure",
    "website_publish_targets_list": "publish_targets_list",
    "website_publish_target_configure": "publish_target_configure",
    "website_import_git": "import_git",
    "website_import_zip": "import_zip",
    "website_sync_source": "sync_source",
    "website_sitemap": "sitemap",
    "website_navigation_analyze": "navigation_analyze",
    "website_search": "search",
    "website_read_file": "read_file",
    "website_write_file": "write_file",
    "website_apply_patch": "apply_patch",
    "website_diff": "diff",
    "website_list_changes": "list_changes",
    "website_build_validate": "build_validate",
    "website_builds_list": "builds_list",
    "website_maintenance_prune": "maintenance_prune",
    "website_build_preview": "build_preview",
    "website_preview_document": "preview_document",
    "website_preview_report": "preview_report",
    "website_runtime_status": "runtime_status",
    "website_publish_request": "publish_request",
    "website_approval_record": "approval_record",
    "website_approvals_list": "approvals_list",
    "website_publish": "publish",
    "website_rollback": "rollback",
    "website_active_context": "active_context",
    "website_page_context": "page_context",
    "website_studio_reference_manifest": "reference_manifest",
    "website_studio_reference_search": "reference_search",
    "website_studio_reference_resolve": "reference_resolve",
    "website_studio_reference_summarize": "reference_summarize",
    "website_reference_manifest": "reference_manifest",
    "website_reference_search": "reference_search",
    "website_reference_resolve": "reference_resolve",
    "website_reference_summarize": "reference_summarize",
    "website_studio_view_filter": "view_filter",
    "website_studio_set_view_filter": "set_view_filter",
    "website_studio_set_custom_view": "set_custom_view",
    "website_studio_clear_custom_view": "clear_custom_view",
}


payload = read_entrypoint_payload()
arguments = dict(payload.arguments)
tool_name = str(payload.raw.get("tool_name") or "")
arguments.setdefault("action", TOOL_ACTIONS.get(tool_name, "sites_list"))
if payload.raw.get("surface") == "secret_selector":
    arguments["_app_secret_selector"] = payload.raw.get("app_secret_selector", {})
    emit_json(resolve_secret_resource(Path(payload.data_root), arguments))
    raise SystemExit(0)
arguments["_app_secrets"] = dict(payload.raw.get("app_secrets") or {})
arguments["_app_secret_errors"] = list(payload.raw.get("app_secret_errors") or [])
arguments["_app_actor"] = {
    "user_id": payload.user_id,
    "workspace_role": payload.workspace_role,
    "platform_role": payload.platform_role,
    "effective_mode": payload.effective_mode,
}
status_code, result = handle_action(Path(payload.data_root), arguments)
result["status_code"] = status_code
if status_code < 400:
    result.setdefault("app_id", payload.app_id)
    result.setdefault("workspace_id", payload.workspace_id)
    result.setdefault("tool_name", tool_name)
    result["app_events"] = app_events_for_action(str(arguments.get("action") or "sites_list"), arguments)
emit_json(result)
