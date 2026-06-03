"""Service layer for Website Studio."""

from __future__ import annotations

from pathlib import Path

from database import health_payload
from store import (
    active_context,
    apply_text_patch,
    archive_site,
    build_preview,
    clear_custom_view,
    create_publish_request,
    create_site,
    diff_site,
    duplicate_site,
    import_git,
    import_zip,
    list_sites,
    load_view_state,
    publish,
    read_file,
    rebuild_index,
    reference_manifest,
    reference_resolve,
    reference_search,
    reference_summary,
    rename_site,
    restore_site,
    rollback,
    search,
    set_custom_view,
    set_view_filter,
    sitemap,
    site_status,
    write_file,
)


MUTATING_ACTIONS = {
    "site_create",
    "site_archive",
    "site_restore",
    "site_rename",
    "site_duplicate",
    "import_zip",
    "import_git",
    "write_file",
    "apply_patch",
    "build_preview",
    "publish_request",
    "publish",
    "rollback",
    "clear_custom_view",
    "set_custom_view",
    "set_view_filter",
}


def handle_action(data_root: Path, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
    action = str(payload.get("action") or "sites_list")
    try:
        if action in {"status", "manifest"}:
            return 200, {"app_id": "website-studio", "status": "ready", **health_payload(data_root), "phase": "phase_1"}
        if action == "sites_list":
            return 200, {"items": list_sites(data_root)}
        if action == "site_create":
            return 201, {
                "site": create_site(
                    data_root,
                    display_name=payload.get("display_name") or payload.get("title"),
                    slug=payload.get("slug"),
                    primary_domain=payload.get("primary_domain"),
                    source_provider=payload.get("source_provider") or "manual",
                )
            }
        if action == "site_status":
            return 200, site_status(data_root, payload.get("site_id"))
        if action == "site_archive":
            return 200, {"site": archive_site(data_root, payload.get("site_id"))}
        if action == "site_restore":
            return 200, {"site": restore_site(data_root, payload.get("site_id"))}
        if action == "site_rename":
            return 200, {
                "site": rename_site(
                    data_root,
                    payload.get("site_id"),
                    display_name=payload.get("display_name"),
                    slug=payload.get("slug"),
                    primary_domain=payload.get("primary_domain"),
                )
            }
        if action == "site_duplicate":
            return 201, {"site": duplicate_site(data_root, payload.get("site_id"), display_name=payload.get("display_name"), slug=payload.get("slug"))}
        if action == "import_zip":
            return 201, {
                **import_zip(
                    data_root,
                    site_id=payload.get("site_id"),
                    display_name=payload.get("display_name"),
                    archive_base64=payload.get("archive_base64"),
                    source_artifact_ref=payload.get("source_artifact_ref"),
                )
            }
        if action == "import_git":
            return 201, {
                **import_git(
                    data_root,
                    site_id=payload.get("site_id"),
                    display_name=payload.get("display_name"),
                    repository_url=payload.get("repository_url"),
                    branch=payload.get("branch"),
                )
            }
        if action == "sitemap":
            return 200, sitemap(data_root, payload.get("site_id"))
        if action == "index":
            return 200, rebuild_index(data_root, payload.get("site_id"))
        if action == "search":
            return 200, {"items": search(data_root, payload.get("query") or "", payload.get("site_id"))}
        if action == "read_file":
            return 200, {"file": read_file(data_root, site_id=payload.get("site_id"), path=payload.get("path"))}
        if action == "write_file":
            return 200, {
                **write_file(
                    data_root,
                    site_id=payload.get("site_id"),
                    path=payload.get("path"),
                    content=payload.get("content"),
                    expected_hash=payload.get("expected_hash"),
                )
            }
        if action == "apply_patch":
            return 200, {
                **apply_text_patch(
                    data_root,
                    site_id=payload.get("site_id"),
                    path=payload.get("path"),
                    old_text=payload.get("old_text"),
                    new_text=payload.get("new_text"),
                    expected_hash=payload.get("expected_hash"),
                )
            }
        if action == "diff":
            return 200, diff_site(data_root, payload.get("site_id"))
        if action == "build_preview":
            return 200, build_preview(data_root, payload.get("site_id"), payload.get("route") or "/")
        if action == "publish_request":
            return 201, {"publish_request": create_publish_request(data_root, payload.get("site_id"), payload.get("requested_by") or "workspace")}
        if action == "publish":
            result = publish(data_root, payload.get("site_id"), payload.get("publish_request_id"), payload.get("approval_id"))
            return (403 if result.get("blocked") else 200), result
        if action == "rollback":
            result = rollback(
                data_root,
                payload.get("site_id"),
                payload.get("revision_id"),
                approval_id=payload.get("approval_id"),
                confirm=payload.get("confirm"),
            )
            return (403 if result.get("blocked") else 200), result
        if action in {"active_context", "page_context"}:
            return 200, active_context(data_root, payload.get("site_id"), payload.get("page_id"))
        if action == "reference_manifest":
            return 200, reference_manifest()
        if action == "reference_search":
            return 200, {"items": reference_search(data_root, payload.get("query") or "", payload.get("site_id"))}
        if action == "reference_resolve":
            return 200, {"item": reference_resolve(data_root, payload.get("entity_type") or "site", payload.get("id") or payload.get("entity_id"))}
        if action == "reference_summarize":
            return 200, {"summary": reference_summary(data_root, payload.get("entity_type") or "site", payload.get("id") or payload.get("entity_id"))}
        if action == "view_filter":
            return 200, {"state": load_view_state(data_root)}
        if action == "set_view_filter":
            return 200, {"state": set_view_filter(data_root, query=payload.get("query"), site_id=payload.get("site_id"), preserve_custom=bool(payload.get("preserve_custom")))}
        if action == "set_custom_view":
            return 200, {"state": set_custom_view(data_root, title=payload.get("title"), refs=payload.get("refs"))}
        if action == "clear_custom_view":
            return 200, {"state": clear_custom_view(data_root)}
    except ValueError as error:
        return 400, {"error": "validation_error", "detail": str(error)}
    return 400, {"error": "unsupported_action", "detail": f"Unsupported action `{action}`."}


def app_events_for_action(action: str) -> list[dict[str, str]]:
    if action not in MUTATING_ACTIONS:
        return []
    resource = "view-state" if action in {"clear_custom_view", "set_custom_view", "set_view_filter"} else "records"
    return [{"type": "maverick.app.data-changed", "owner_app_id": "website-studio", "resource": resource}]
