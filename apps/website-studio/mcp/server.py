"""MCP entrypoint for Website Studio."""

from __future__ import annotations

from pathlib import Path
import sys

from core.app_sdk.runtime import emit_json, read_entrypoint_payload

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from service import app_events_for_action, handle_action


TOOL_ACTIONS = {
    "website_manifest": "manifest",
    "website_sites_list": "sites_list",
    "website_site_status": "site_status",
    "website_site_create": "site_create",
    "website_site_archive": "site_archive",
    "website_site_restore": "site_restore",
    "website_site_rename": "site_rename",
    "website_site_duplicate": "site_duplicate",
    "website_import_git": "import_git",
    "website_import_zip": "import_zip",
    "website_sitemap": "sitemap",
    "website_search": "search",
    "website_read_file": "read_file",
    "website_write_file": "write_file",
    "website_apply_patch": "apply_patch",
    "website_diff": "diff",
    "website_build_preview": "build_preview",
    "website_publish_request": "publish_request",
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
status_code, result = handle_action(Path(payload.data_root), arguments)
if status_code < 400:
    result["app_events"] = app_events_for_action(str(arguments.get("action") or "sites_list"))
emit_json(result)
