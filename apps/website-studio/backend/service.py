"""Service layer for Website Studio."""

from __future__ import annotations

from pathlib import Path

from database import health_payload
from phase_acceptance import phase_1_3a_acceptance_verification
from store import (
    active_context,
    activate_git_connection,
    apply_text_patch,
    archive_site,
    bootstrap,
    build_preview,
    configure_environment,
    configure_publish_target,
    clear_custom_view,
    create_publish_request,
    create_site,
    diff_site,
    duplicate_site,
    get_environment,
    get_git_connection,
    get_site,
    import_git,
    import_zip,
    list_git_connections,
    list_changes,
    list_approvals,
    list_builds,
    list_environments,
    list_publish_targets,
    list_sites,
    load_view_state,
    maintenance_policy_defaults,
    maintenance_prune,
    navigation_analyze,
    page_context,
    prepare_git_connection,
    preview_document,
    preview_report,
    preview_media,
    publish,
    read_file,
    rebuild_index,
    reference_manifest,
    reference_resolve,
    reference_search,
    reference_summary,
    rename_site,
    restore_site,
    record_approval,
    rollback,
    runtime_status,
    search,
    set_active_site,
    set_custom_view,
    set_view_filter,
    sitemap,
    site_status,
    sync_source,
    validate_build,
    write_file,
    workspace_snapshot,
    _connection_id,
    _parse_github_repository,
    _publish_target_for_environment,
    _should_publish_to_github,
)
from preview_runtime import runtime_process_policy


MUTATING_ACTIONS = {
    "site_create",
    "site_archive",
    "site_restore",
    "site_rename",
    "site_duplicate",
    "site_set_active",
    "git_connection_prepare",
    "git_connection_activate",
    "environment_configure",
    "publish_target_configure",
    "approval_record",
    "import_zip",
    "import_git",
    "sync_source",
    "write_file",
    "apply_patch",
    "build_validate",
    "preview_report",
    "maintenance_prune",
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
            return 200, {
                "app_id": "website-studio",
                "status": "ready",
                **health_payload(data_root),
                "phase": "phase_3",
                "phase_status": "phase_3_app_orchestration_ready_platform_hosting_missing",
                "implemented_phases": ["phase_1", "phase_2", "phase_3_app_orchestration", "phase_3a_runtime_preview"],
                "phase_3a_runtime_status": "ready",
                "platform_hosting_status": "pending_generic_surface",
                "maintenance_policy": maintenance_policy_defaults(),
                "runtime_process_policy": runtime_process_policy(),
                "acceptance_verification": phase_1_3a_acceptance_verification(),
            }
        if action == "sites_list":
            return 200, {"items": list_sites(data_root)}
        if action == "bootstrap":
            return 200, bootstrap(data_root, payload.get("site_id"), payload.get("route"))
        if action == "workspace_snapshot":
            return 200, workspace_snapshot(
                data_root,
                payload.get("site_id"),
                route=payload.get("route"),
                known_versions=payload.get("known_versions"),
            )
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
        if action == "site_set_active":
            return 200, set_active_site(data_root, payload.get("site_id"))
        if action == "git_connections_list":
            return 200, {"items": list_git_connections(data_root, payload.get("site_id"))}
        if action == "git_connection_prepare":
            return 201, prepare_git_connection(
                data_root,
                site_id=payload.get("site_id"),
                display_name=payload.get("display_name"),
                repository_url=payload.get("repository_url"),
                base_branch=payload.get("base_branch") or payload.get("branch"),
                auth_mode=payload.get("auth_mode") or "fine_grained_token",
                secret_logical_name=payload.get("secret_logical_name"),
            )
        if action == "git_connection_activate":
            return 200, activate_git_connection(
                data_root,
                payload.get("connection_id"),
                grant_id=payload.get("grant_id"),
                confirm_no_raw_secret=payload.get("confirm_no_raw_secret"),
            )
        if action == "environments_list":
            return 200, {"items": list_environments(data_root, payload.get("site_id"))}
        if action == "environment_configure":
            return 200, {
                "environment": configure_environment(
                    data_root,
                    payload.get("site_id"),
                    environment_id=payload.get("environment_id"),
                    name=payload.get("name"),
                    kind=payload.get("kind") or "preview",
                    base_url=payload.get("base_url"),
                    requires_approval=payload.get("requires_approval") if "requires_approval" in payload else True,
                )
            }
        if action == "publish_targets_list":
            return 200, {"items": list_publish_targets(data_root, payload.get("site_id"))}
        if action == "publish_target_configure":
            return 200, {
                "publish_target": configure_publish_target(
                    data_root,
                    payload.get("site_id"),
                    environment_id=payload.get("environment_id"),
                    kind=payload.get("kind") or "managed_static",
                    status=payload.get("status") or "active",
                    config=payload.get("config"),
                )
            }
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
                    app_secrets=payload.get("_app_secrets") if isinstance(payload.get("_app_secrets"), dict) else {},
                    app_secret_errors=payload.get("_app_secret_errors") if isinstance(payload.get("_app_secret_errors"), list) else [],
                )
            }
        if action == "sync_source":
            result = sync_source(
                data_root,
                payload.get("site_id"),
                branch=payload.get("branch") or payload.get("base_branch"),
                confirm=payload.get("confirm"),
                app_secrets=payload.get("_app_secrets") if isinstance(payload.get("_app_secrets"), dict) else {},
                app_secret_errors=payload.get("_app_secret_errors") if isinstance(payload.get("_app_secret_errors"), list) else [],
            )
            return (409 if result.get("blocked") else 200), result
        if action == "sitemap":
            return 200, sitemap(data_root, payload.get("site_id"), mode=payload.get("mode"))
        if action == "navigation_analyze":
            return 200, navigation_analyze(data_root, payload.get("site_id"))
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
        if action == "list_changes":
            return 200, list_changes(
                data_root,
                payload.get("site_id"),
                payload.get("status"),
                limit=payload.get("limit"),
                offset=payload.get("offset"),
                include_logs=payload.get("include_logs"),
                diff_limit=payload.get("diff_limit"),
            )
        if action == "build_preview":
            return 200, build_preview(
                data_root,
                payload.get("site_id"),
                payload.get("route") or "/",
                include_html=payload.get("include_html") if "include_html" in payload else True,
                preview_origin=payload.get("_preview_origin"),
            )
        if action == "preview_document":
            return 200, preview_document(
                data_root,
                payload.get("preview_id"),
                preview_origin=payload.get("_preview_origin"),
                include_inventory=payload.get("include_inventory"),
            )
        if action == "preview_report":
            return 201, preview_report(
                data_root,
                site_id=payload.get("site_id"),
                preview_id=payload.get("preview_id"),
                route=payload.get("route") or "/",
                baseline_report_id=payload.get("baseline_report_id"),
                preview_origin=payload.get("_preview_origin"),
                include_inventory=payload.get("include_inventory"),
            )
        if action == "preview_media":
            return 200, preview_media(data_root, payload.get("preview_id"), payload.get("path"))
        if action == "runtime_status":
            return 200, runtime_status(data_root, payload.get("site_id"))
        if action == "build_validate":
            return 201, {"build": validate_build(data_root, payload.get("site_id"))}
        if action == "builds_list":
            return 200, list_builds(
                data_root,
                payload.get("site_id"),
                limit=payload.get("limit"),
                offset=payload.get("offset"),
                include_logs=payload.get("include_logs"),
            )
        if action == "maintenance_prune":
            return 200, maintenance_prune(
                data_root,
                payload.get("site_id"),
                keep_builds=payload.get("keep_builds"),
                keep_previews_per_route=payload.get("keep_previews_per_route"),
                keep_runtime_sessions=payload.get("keep_runtime_sessions"),
                dry_run=payload.get("dry_run"),
            )
        if action == "publish_request":
            return 201, {
                "publish_request": create_publish_request(
                    data_root,
                    payload.get("site_id"),
                    payload.get("requested_by") or "workspace",
                    environment_id=payload.get("environment_id"),
                )
            }
        if action == "approval_record":
            return 201, {
                "approval": record_approval(
                    data_root,
                    payload.get("site_id"),
                    action=payload.get("approval_action") or payload.get("target_action") or payload.get("publish_action") or payload.get("operation"),
                    target_id=payload.get("target_id") or payload.get("publish_request_id") or payload.get("revision_id"),
                    approved_by=payload.get("approved_by"),
                    approval_note=payload.get("approval_note"),
                    confirm=payload.get("confirm"),
                    actor=payload.get("_app_actor") if isinstance(payload.get("_app_actor"), dict) else {},
                )
            }
        if action == "approvals_list":
            return 200, {"items": list_approvals(data_root, payload.get("site_id"))}
        if action == "publish":
            result = publish(
                data_root,
                payload.get("site_id"),
                payload.get("publish_request_id"),
                payload.get("approval_id"),
                app_secrets=payload.get("_app_secrets") if isinstance(payload.get("_app_secrets"), dict) else {},
                app_secret_errors=payload.get("_app_secret_errors") if isinstance(payload.get("_app_secret_errors"), list) else [],
                github_transport=payload.get("_github_transport"),
            )
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
        if action == "active_context":
            return 200, active_context(data_root, payload.get("site_id"), payload.get("page_id"))
        if action == "page_context":
            return 200, page_context(
                data_root,
                payload.get("site_id"),
                page_id=payload.get("page_id"),
                route_id=payload.get("route_id"),
                route=payload.get("route"),
                asset_id=payload.get("asset_id"),
                component_id=payload.get("component_id") or payload.get("section_id") or payload.get("anchor_id"),
                target_selector=payload.get("target_selector") or payload.get("selector"),
                target_anchor=payload.get("target_anchor") or payload.get("anchor"),
                include_inventory=payload.get("include_inventory"),
            )
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


def resolve_secret_resource(data_root: Path, payload: dict[str, object]) -> dict[str, object]:
    """Resolve whether a CLI/MCP invocation needs Website Studio GitHub credentials."""
    try:
        if "github-token" not in _selector_logical_names(payload):
            return {"requires_secrets": False}
        action = str(payload.get("action") or "").strip()
        if action in {"import_git", "sync_source"}:
            return _resolve_git_import_secret_resource(data_root, payload)
        if action == "publish":
            return _resolve_publish_secret_resource(data_root, payload)
        return {"requires_secrets": False}
    except ValueError as error:
        return {"requires_secrets": False, "error": "validation_error", "detail": str(error)}


def _resolve_git_import_secret_resource(data_root: Path, payload: dict[str, object]) -> dict[str, object]:
    source = payload.get("repository_url")
    if not source and str(payload.get("action") or "").strip() == "sync_source":
        site_id = str(payload.get("site_id") or "").strip()
        if not site_id:
            return {"requires_secrets": False}
        site = get_site(data_root, site_id)
        ref = site.get("source_artifact_ref") if isinstance(site.get("source_artifact_ref"), dict) else {}
        if ref.get("provider") != "github":
            return {"requires_secrets": False, "provider": str(ref.get("provider") or site.get("source_provider") or "manual")}
        connection_id = str(ref.get("connection_id") or "").strip()
        if not connection_id:
            return {"requires_secrets": False, "provider": "github", "status": "missing_connection"}
        connection = get_git_connection(data_root, connection_id)
        return {
            "requires_secrets": connection.get("auth_mode") == "fine_grained_token",
            "provider": "github",
            "connection_id": connection.get("id"),
            "status": connection.get("status"),
        }
    if not source:
        return {"requires_secrets": False}
    try:
        owner, repo, _normalized_url = _parse_github_repository(source)
    except ValueError:
        return {"requires_secrets": False}
    try:
        connection = get_git_connection(data_root, _connection_id(owner, repo))
    except ValueError:
        return {"requires_secrets": False, "provider": "github", "owner": owner, "repo": repo}
    site_id = str(payload.get("site_id") or "").strip()
    if site_id and connection.get("site_id") != site_id:
        return {"requires_secrets": False, "provider": "github", "connection_id": connection.get("id"), "status": "site_mismatch"}
    return {
        "requires_secrets": connection.get("auth_mode") == "fine_grained_token",
        "provider": "github",
        "connection_id": connection.get("id"),
        "status": connection.get("status"),
    }


def _resolve_publish_secret_resource(data_root: Path, payload: dict[str, object]) -> dict[str, object]:
    site_id = str(payload.get("site_id") or "").strip()
    if not site_id:
        return {"requires_secrets": False}
    site = get_site(data_root, site_id)
    ref = site.get("source_artifact_ref") if isinstance(site.get("source_artifact_ref"), dict) else {}
    if ref.get("provider") != "github":
        return {"requires_secrets": False, "provider": str(site.get("source_provider") or "manual")}
    environment = get_environment(data_root, _publish_environment_id(site, payload), site_id=site["id"])
    publish_target = _publish_target_for_environment(data_root, site, environment)
    if not _should_publish_to_github(site, publish_target):
        return {"requires_secrets": False, "provider": "github", "publish_target": publish_target.get("kind") if publish_target else ""}
    connection_id = str(ref.get("connection_id") or "").strip()
    if not connection_id:
        return {"requires_secrets": False, "provider": "github", "status": "missing_connection"}
    connection = get_git_connection(data_root, connection_id)
    return {
        "requires_secrets": connection.get("auth_mode") == "fine_grained_token",
        "provider": "github",
        "connection_id": connection.get("id"),
        "status": connection.get("status"),
    }


def _publish_environment_id(site: dict[str, object], payload: dict[str, object]) -> object:
    explicit = str(payload.get("environment_id") or "").strip()
    if explicit:
        return explicit
    return site.get("default_environment_id") or "env_preview"


def _selector_logical_names(payload: dict[str, object]) -> set[str]:
    selector = payload.get("_app_secret_selector")
    if not isinstance(selector, dict):
        return set()
    return {str(name).strip().lower() for name in selector.get("logical_names", []) if str(name).strip()}


def app_events_for_action(action: str, payload: dict[str, object] | None = None) -> list[dict[str, str]]:
    if action not in MUTATING_ACTIONS:
        return []
    if action == "maintenance_prune" and _event_truthy((payload or {}).get("dry_run")):
        return []
    source_actions = {"import_zip", "import_git", "sync_source", "write_file", "apply_patch", "rollback", "site_duplicate"}
    navigation_actions = source_actions | {"site_create", "site_archive", "site_restore", "site_rename"}
    preview_actions = {"build_validate", "preview_report"}
    activity_actions = {"approval_record", "publish_request", "publish", "maintenance_prune", "git_connection_prepare", "git_connection_activate"}
    settings_actions = {"environment_configure", "publish_target_configure"}
    view_actions = {"clear_custom_view", "set_custom_view", "set_view_filter", "site_set_active"}
    resources = []
    if action in source_actions:
        resources.extend(["source", "working-state"])
    if action in navigation_actions:
        resources.append("navigation")
    if action in preview_actions:
        resources.append("preview")
    if action in activity_actions:
        resources.append("activity")
    if action in settings_actions:
        resources.append("settings")
    if action in view_actions or action in {"site_create", "site_archive", "site_restore", "import_zip", "import_git", "git_connection_prepare"}:
        resources.append("view-selection")
    if not resources:
        resources.append("activity")
    return [{"type": "maverick.app.data-changed", "owner_app_id": "website-studio", "resource": resource} for resource in resources]


def _event_truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
