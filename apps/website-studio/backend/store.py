"""Website Studio domain store."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import difflib
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlencode, urlparse
from uuid import uuid4

from database import REFERENCE_ENTITIES, connect, ensure_schema, now_timestamp
from github_publish import GitHubPublishConflict, _redact_secret_text, publish_to_github_pull_request
from maintenance import prune_site_operational_history
from safety import (
    asset_references_from_html,
    classify_source_tree,
    copy_tree_snapshot,
    detect_content_type,
    extract_zip_base64,
    preview_srcdoc_html,
    read_text_file,
    replace_tree_from_directory,
    resolve_site_path,
    runtime_diagnostic_html,
    safe_relative_path,
    sha256_text,
    slugify,
    snapshot_text_files,
    source_profile,
    validate_editable_text_path,
    validate_git_source,
    validate_source_tree_for_phase1,
    write_text_file,
)
from preview_runtime import (
    MAX_RENDERED_ROUTES,
    internal_routes_from_html,
    prepare_runtime_build,
    redact_runtime_log,
    render_runtime_preview,
    runtime_capability_status,
    rendered_route_warnings,
    route_specific_warnings,
    source_files_for_runtime_route,
)
from preview_delivery import prepare_preview_document_html, rewrite_preview_css, safe_preview_asset_path
from preview_observability import (
    acceptance_checks,
    asset_kind_for_path,
    build_selector_hints,
    preview_media_paths_from_html,
    summarize_asset_probe,
)
from publish_workflow import managed_static_platform_binding, working_branch_for_site
from visual_navigation import (
    component_candidates_from_selector_hints,
    component_matches_query,
    visual_sections_from_html,
    visual_sections_from_selector_hints,
)

IMPLEMENTED_SOURCE_PROVIDERS = {"manual", "zip", "git"}
DEFAULT_HISTORY_LIMIT = 20
MAX_HISTORY_LIMIT = 100
DEFAULT_WORKING_DIFF_LIMIT = 100
MAX_WORKING_DIFF_LIMIT = 250
COMPACT_LOG_CHARS = 1200
DEFAULT_RETAIN_BUILDS = 10
DEFAULT_RETAIN_PREVIEWS_PER_ROUTE = 3
DEFAULT_RETAIN_RUNTIME_SESSIONS = 20
DEFAULT_RETENTION_REVIEW_CADENCE = "run dry-run during routine workspace maintenance and prune after reviewing counts"
MAX_SOURCE_MAP_ASSET_INDEX = 120
PREVIEW_RUNTIME_VERSION = "preview-browser-stream-v6"
FILE_GATEWAY_SCHEMA = "maverick.app.file_gateway.v1"
FILE_GATEWAY_REUSE_INDEX_SCHEMA = "website-studio.file_gateway_reuse_index.v1"
PREVIEW_FILE_GATEWAY_TTL = timedelta(minutes=30)
PREVIEW_FILE_GATEWAY_REUSE_MIN_TTL = timedelta(minutes=5)
PREVIEW_FILE_GATEWAY_CACHE_CONTROL = f"private, max-age={int(PREVIEW_FILE_GATEWAY_TTL.total_seconds())}"
PREVIEW_MEDIA_RESPONSE_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Accept-Ranges": "bytes",
    "Cross-Origin-Resource-Policy": "cross-origin",
}


def list_sites(data_root: Path) -> list[dict[str, object]]:
    ensure_schema(data_root)
    active_site_id = get_active_site_id(data_root)
    with connect(data_root) as db:
        rows = db.execute("SELECT * FROM sites ORDER BY updated_at DESC").fetchall()
    sites = [_site_row(row, active_site_id=active_site_id) for row in rows]
    latest_builds = _latest_builds_by_site(data_root, [str(site["id"]) for site in sites])
    return [_site_with_latest_runtime_profile(site, latest_builds.get(str(site["id"]))) for site in sites]


def create_site(
    data_root: Path,
    *,
    display_name: object,
    slug: object = None,
    primary_domain: object = None,
    source_provider: object = "manual",
) -> dict[str, object]:
    name = str(display_name or "").strip()
    if not name:
        raise ValueError("display_name is required")
    clean_source_provider = _clean_source_provider(source_provider)
    site_id = f"site_{uuid4().hex[:16]}"
    clean_slug = _unique_slug(data_root, str(slug or slugify(name)))
    now = now_timestamp()
    ensure_schema(data_root)
    with connect(data_root) as db:
        db.execute(
            """
            INSERT INTO sites(id, display_name, slug, status, primary_domain, source_provider, created_at, updated_at)
            VALUES (?, ?, ?, 'draft', ?, ?, ?, ?)
            """,
            (site_id, name, clean_slug, str(primary_domain or "").strip(), clean_source_provider, now, now),
        )
    _write_starter_site(_source_root(data_root, site_id), name)
    rebuild_index(data_root, site_id)
    revision = create_revision(data_root, site_id, label="Initial working copy", source="create_site")
    _set_active_revision(data_root, site_id, revision["id"])
    _ensure_default_environment(data_root, site_id)
    set_active_site(data_root, site_id)
    _audit(data_root, site_id, "site.created", f"Created site {name}")
    return get_site(data_root, site_id)


def get_site(data_root: Path, site_id: object) -> dict[str, object]:
    clean_id = _required_id(site_id, "site_id")
    ensure_schema(data_root)
    with connect(data_root) as db:
        row = db.execute("SELECT * FROM sites WHERE id = ?", (clean_id,)).fetchone()
    if row is None:
        raise ValueError(f"site `{clean_id}` was not found")
    return _site_row(row, active_site_id=get_active_site_id(data_root))


def site_status(data_root: Path, site_id: object) -> dict[str, object]:
    site = get_site(data_root, site_id)
    counts = _site_inventory_counts(data_root, site["id"])
    diff_payload = diff_site(data_root, site["id"])
    profile = _cached_source_profile(data_root, site)
    runtime = runtime_status(data_root, site["id"])
    runtime_profile = runtime.get("source_profile") if isinstance(runtime.get("source_profile"), dict) else profile
    site_payload = dict(site)
    site_payload["source_profile"] = runtime_profile
    return {
        "site": site_payload,
        "page_count": counts["page_count"],
        "route_count": counts["route_count"],
        "asset_count": counts["asset_count"],
        "changed_files_count": len(diff_payload["files"]),
        "active_revision_id": site.get("active_revision_id"),
        "published_revision_id": site.get("published_revision_id"),
        "source_profile": runtime_profile,
        "runtime": runtime,
        "runtime_kind": runtime.get("runtime_kind") or runtime_profile.get("preview_runtime_kind") or "unavailable",
        "runtime_status": runtime.get("runtime_status") or runtime_profile.get("runtime_preview_status") or "blocked",
        "missing_requirements": runtime.get("missing_requirements") or runtime_profile.get("missing_requirements") or [],
        "latest_build_id": (runtime.get("latest_build") or {}).get("id") if isinstance(runtime.get("latest_build"), dict) else "",
        "latest_preview_id": (runtime.get("latest_preview") or {}).get("id") if isinstance(runtime.get("latest_preview"), dict) else "",
        "is_active": bool(site.get("is_active")),
    }


def bootstrap(data_root: Path, site_id: object = None, route: object = None) -> dict[str, object]:
    sites = list_sites(data_root)
    available = [site for site in sites if site.get("status") != "archived"]
    requested_site_id = str(site_id or "").strip()
    selected_site = next((site for site in available if site.get("id") == requested_site_id), None)
    persisted_site = next((site for site in available if site.get("is_active")), None)
    if selected_site is None:
        selected_site = persisted_site or (available[0] if available else None)
    if selected_site is None:
        return {
            "sites": sites,
            "active_site_id": "",
            "persisted_active_site_id": str((persisted_site or {}).get("id") or ""),
            "sitemap": {"site_id": "", "items": [], "routes": [], "assets": []},
            "latest_preview": None,
        }
    map_payload = sitemap(data_root, selected_site["id"], mode="routes-only")
    route_text = str(route or "").strip()
    if not route_text:
        first_page = next(iter(map_payload.get("items") or []), {})
        route_text = str(first_page.get("route") or "/") if isinstance(first_page, dict) else "/"
    latest_preview = _bootstrap_latest_preview(data_root, selected_site, route_text) if route_text else {}
    return {
        "sites": sites,
        "active_site_id": str(selected_site["id"]),
        "persisted_active_site_id": str((persisted_site or {}).get("id") or ""),
        "sitemap": map_payload,
        "latest_preview": latest_preview or None,
    }


def _bootstrap_latest_preview(data_root: Path, site: dict[str, object], route: str) -> dict[str, object]:
    profile = _cached_source_profile(data_root, site)
    if not str(site.get("source_version") or "").strip():
        site = get_site(data_root, site["id"])
    runtime_kind = str(profile.get("preview_runtime_kind") or "unavailable")
    if runtime_kind in {"php", "node_build"}:
        build = _latest_passed_runtime_build(data_root, str(site["id"]), runtime_kind)
        if not build:
            return {}
        return _latest_compatible_preview(
            data_root,
            site_id=site["id"],
            route=route,
            runtime_kind=runtime_kind,
            build_id=str(build.get("id") or ""),
        )
    return _latest_compatible_preview(
        data_root,
        site_id=site["id"],
        route=route,
        runtime_kind=runtime_kind,
        source_version=_source_version_for_site(site),
    )


def get_active_site_id(data_root: Path) -> str:
    state = load_view_state(data_root)
    return str(state.get("active_site_id") or "")


def set_active_site(data_root: Path, site_id: object) -> dict[str, object]:
    site = get_site(data_root, site_id)
    if site.get("status") == "archived":
        raise ValueError("archived sites cannot be selected as the active site")
    state = load_view_state(data_root)
    next_state = _write_view_state(
        data_root,
        dict(state.get("view_filter") or _default_view_filter()),
        active_site_id=str(site["id"]),
    )
    _audit(data_root, str(site["id"]), "site.selected", f"Selected active site {site['display_name']}")
    return {"site": get_site(data_root, site["id"]), "state": next_state}


def archive_site(data_root: Path, site_id: object) -> dict[str, object]:
    site = get_site(data_root, site_id)
    now = now_timestamp()
    with connect(data_root) as db:
        db.execute("UPDATE sites SET status = 'archived', archived_at = ?, updated_at = ? WHERE id = ?", (now, now, site["id"]))
    if get_active_site_id(data_root) == site["id"]:
        state = load_view_state(data_root)
        _write_view_state(data_root, dict(state.get("view_filter") or _default_view_filter()), active_site_id="")
    _audit(data_root, str(site["id"]), "site.archived", f"Archived site {site['display_name']}")
    return get_site(data_root, site["id"])


def restore_site(data_root: Path, site_id: object) -> dict[str, object]:
    site = get_site(data_root, site_id)
    now = now_timestamp()
    with connect(data_root) as db:
        db.execute("UPDATE sites SET status = 'draft', archived_at = NULL, updated_at = ? WHERE id = ?", (now, site["id"]))
    _audit(data_root, str(site["id"]), "site.restored", f"Restored site {site['display_name']}")
    return get_site(data_root, site["id"])


def rename_site(
    data_root: Path,
    site_id: object,
    *,
    display_name: object = None,
    slug: object = None,
    primary_domain: object = None,
) -> dict[str, object]:
    site = get_site(data_root, site_id)
    name = str(display_name if display_name is not None else site["display_name"]).strip()
    if not name:
        raise ValueError("display_name is required")
    raw_slug = str(slug if slug is not None else site["slug"]).strip() or slugify(name)
    clean_slug = _unique_slug(data_root, raw_slug, exclude_site_id=str(site["id"]))
    domain = str(primary_domain if primary_domain is not None else site.get("primary_domain") or "").strip()
    now = now_timestamp()
    with connect(data_root) as db:
        db.execute(
            "UPDATE sites SET display_name = ?, slug = ?, primary_domain = ?, updated_at = ? WHERE id = ?",
            (name, clean_slug, domain, now, site["id"]),
        )
    _audit(data_root, str(site["id"]), "site.renamed", f"Renamed site to {name}")
    return get_site(data_root, site["id"])


def duplicate_site(data_root: Path, site_id: object, *, display_name: object = None, slug: object = None) -> dict[str, object]:
    source_site = get_site(data_root, site_id)
    name = str(display_name or f"{source_site['display_name']} Copy").strip()
    duplicated = create_site(
        data_root,
        display_name=name,
        slug=slug,
        primary_domain="",
        source_provider=source_site.get("source_provider") or "manual",
    )
    with _site_mutation_lock(data_root, str(duplicated["id"])):
        source_root = _source_root(data_root, str(source_site["id"]))
        target_root = _source_root(data_root, str(duplicated["id"]))
        copy_tree_snapshot(source_root, target_root)
        rebuild_index(data_root, duplicated["id"])
        revision = create_revision(data_root, duplicated["id"], label="Duplicated working copy", source="duplicate_site")
        _set_active_revision(data_root, duplicated["id"], revision["id"])
        _update_site(
            data_root,
            duplicated["id"],
            source_provider=source_site.get("source_provider") or "manual",
            source_label=f"Duplicated from {source_site['slug']}",
            source_shape=classify_source_tree(target_root),
            source_artifact_ref_json=json.dumps(source_site.get("source_artifact_ref") or {}, sort_keys=True),
        )
    _audit(data_root, str(duplicated["id"]), "site.duplicated", f"Duplicated site {source_site['display_name']}", {"source_site_id": source_site["id"]})
    return get_site(data_root, duplicated["id"])


def import_zip(
    data_root: Path,
    *,
    site_id: object = None,
    display_name: object = None,
    archive_base64: object,
    source_artifact_ref: object = None,
) -> dict[str, object]:
    site = get_site(data_root, site_id) if site_id else None
    temp_root = data_root / ".tmp" / f"zip_import_{uuid4().hex}"
    try:
        import_result = extract_zip_base64(archive_base64, temp_root)
        if site is None:
            site = create_site(data_root, display_name=display_name or "Imported Website", source_provider="zip")
        with _site_mutation_lock(data_root, str(site["id"])):
            source_root = _source_root(data_root, str(site["id"]))
            if source_root.exists():
                shutil.rmtree(source_root)
            source_root.parent.mkdir(parents=True, exist_ok=True)
            temp_root.rename(source_root)
            index_payload = rebuild_index(data_root, site["id"])
            revision = create_revision(data_root, site["id"], label="ZIP import", source="zip_import")
            _set_active_revision(data_root, site["id"], revision["id"])
            artifact_ref = _source_artifact_ref(source_artifact_ref)
            profile = dict(index_payload.get("source_profile") or source_profile(source_root))
            _update_site(
                data_root,
                site["id"],
                source_provider="zip",
                source_label="ZIP import",
                source_shape=str(profile.get("source_shape") or import_result.get("source_shape") or "partial_source"),
                source_profile_json=json.dumps(profile, sort_keys=True),
                source_artifact_ref_json=json.dumps(artifact_ref, sort_keys=True),
            )
            set_active_site(data_root, site["id"])
            _audit(data_root, site["id"], "site.import_zip", f"Imported {import_result['files_extracted']} ZIP files", {"source_artifact_ref": artifact_ref})
    finally:
        if temp_root.exists():
            shutil.rmtree(temp_root)
    return {"site": get_site(data_root, site["id"]), "import": {**import_result, "source_profile": profile}, "revision": revision}


def import_git(
    data_root: Path,
    *,
    site_id: object = None,
    display_name: object = None,
    repository_url: object,
    branch: object = None,
    app_secrets: dict[str, object] | None = None,
    app_secret_errors: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    source, clean_branch = validate_git_source(repository_url, branch, data_root=data_root)
    site = get_site(data_root, site_id) if site_id else None
    temp_root = data_root / ".tmp" / f"git_import_{uuid4().hex}"
    clone_root = temp_root / "repo"
    try:
        auth_context = _git_import_auth_context(
            data_root,
            site,
            source,
            app_secrets=app_secrets or {},
            app_secret_errors=app_secret_errors or [],
        )
        _run_git_clone(source, clean_branch, clone_root, token=auth_context.get("token"))
        if isinstance(auth_context.get("connection"), dict):
            _mark_git_connection_runtime_grant(data_root, auth_context["connection"])
        _normalize_git_import_file_modes(clone_root)
        clone_git = clone_root / ".git"
        if clone_git.exists():
            shutil.rmtree(clone_git)
        validate_source_tree_for_phase1(clone_root)
        profile = source_profile(clone_root)
        source_shape = str(profile.get("source_shape") or classify_source_tree(clone_root))
        if site is None:
            site = create_site(data_root, display_name=display_name or _display_name_from_git_source(source), source_provider="git")
        with _site_mutation_lock(data_root, str(site["id"])):
            source_root = _source_root(data_root, str(site["id"]))
            if source_root.exists():
                shutil.rmtree(source_root)
            source_root.parent.mkdir(parents=True, exist_ok=True)
            clone_root.rename(source_root)
            index_payload = rebuild_index(data_root, site["id"])
            revision = create_revision(data_root, site["id"], label="Git import", source="git_import")
            _set_active_revision(data_root, site["id"], revision["id"])
            profile = dict(index_payload.get("source_profile") or profile)
            _update_site(
                data_root,
                site["id"],
                source_provider="git",
                source_label=_redacted_git_source_label(source, clean_branch),
                source_shape=source_shape,
                source_profile_json=json.dumps(profile, sort_keys=True),
                source_artifact_ref_json=json.dumps(_git_import_source_ref(data_root, site, source, clean_branch), sort_keys=True),
            )
            set_active_site(data_root, site["id"])
            _audit(data_root, site["id"], "site.import_git", "Imported Git repository", {"branch": clean_branch or ""})
    finally:
        if temp_root.exists():
            shutil.rmtree(temp_root)
    return {
        "site": get_site(data_root, site["id"]),
        "import": {
            "source_provider": "git",
            "branch": clean_branch or "",
            "source_label": _redacted_git_source_label(source, clean_branch),
            "source_shape": source_shape,
            "source_profile": profile,
        },
        "revision": revision,
    }


def sync_source(
    data_root: Path,
    site_id: object,
    *,
    branch: object = None,
    confirm: object = False,
    app_secrets: dict[str, object] | None = None,
    app_secret_errors: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    site = get_site(data_root, site_id)
    source, clean_branch = _sync_source_locator(site, branch)
    temp_root = data_root / ".tmp" / f"git_sync_{uuid4().hex}"
    clone_root = temp_root / "repo"
    try:
        auth_context = _git_import_auth_context(
            data_root,
            site,
            source,
            app_secrets=app_secrets or {},
            app_secret_errors=app_secret_errors or [],
        )
        _run_git_clone(source, clean_branch, clone_root, token=auth_context.get("token"))
        if isinstance(auth_context.get("connection"), dict):
            _mark_git_connection_runtime_grant(data_root, auth_context["connection"])
        _normalize_git_import_file_modes(clone_root)
        clone_git = clone_root / ".git"
        if clone_git.exists():
            shutil.rmtree(clone_git)
        validate_source_tree_for_phase1(clone_root)
        profile = source_profile(clone_root)
        source_shape = str(profile.get("source_shape") or classify_source_tree(clone_root))
        with _site_mutation_lock(data_root, str(site["id"])):
            current_diff = diff_site(data_root, site["id"])
            if current_diff["files"] and confirm is not True:
                conflicts = [{"path": item["path"], "status": item["status"]} for item in current_diff["files"][:100]]
                sync_run = _record_sync_run(
                    data_root,
                    site["id"],
                    source_provider="git",
                    status="blocked_local_changes",
                    branch=clean_branch,
                    files_changed_count=len(current_diff["files"]),
                    conflicts=conflicts,
                    source_profile=profile,
                    logs_summary="Sync blocked because the working tree has unpublished local changes.",
                )
                _audit(data_root, str(site["id"]), "source.sync_blocked", "Sync blocked by local working changes", {"sync_run_id": sync_run["id"]})
                return {
                    "blocked": True,
                    "status": "blocked_local_changes",
                    "detail": "sync_source detected local working changes; rerun with confirm=true only after reviewing or publishing the diff.",
                    "site": get_site(data_root, site["id"]),
                    "sync_run": sync_run,
                    "conflicts": conflicts,
                }
            source_root = _source_root(data_root, str(site["id"]))
            if source_root.exists():
                shutil.rmtree(source_root)
            source_root.parent.mkdir(parents=True, exist_ok=True)
            clone_root.rename(source_root)
            index_payload = rebuild_index(data_root, site["id"])
            revision = create_revision(data_root, site["id"], label="Git sync", source="git_sync")
            _set_active_revision(data_root, site["id"], revision["id"])
            profile = dict(index_payload.get("source_profile") or profile)
            _update_site(
                data_root,
                site["id"],
                source_provider="git",
                source_label=_redacted_git_source_label(source, clean_branch),
                source_shape=source_shape,
                source_profile_json=json.dumps(profile, sort_keys=True),
                source_artifact_ref_json=json.dumps(_git_import_source_ref(data_root, site, source, clean_branch), sort_keys=True),
            )
            sync_run = _record_sync_run(
                data_root,
                site["id"],
                source_provider="git",
                status="synced",
                branch=clean_branch,
                files_changed_count=0,
                conflicts=[],
                source_profile=profile,
                logs_summary="Git source synced into the Website Studio working copy.",
            )
        _audit(data_root, str(site["id"]), "source.synced", "Synced Git source", {"sync_run_id": sync_run["id"], "branch": clean_branch})
    finally:
        if temp_root.exists():
            shutil.rmtree(temp_root)
    return {
        "blocked": False,
        "status": "synced",
        "site": get_site(data_root, site["id"]),
        "sync_run": sync_run,
        "revision": revision,
        "sync": {
            "source_provider": "git",
            "branch": clean_branch or "",
            "source_label": _redacted_git_source_label(source, clean_branch),
            "source_shape": source_shape,
            "source_profile": profile,
        },
    }


def list_git_connections(data_root: Path, site_id: object = None) -> list[dict[str, object]]:
    ensure_schema(data_root)
    with connect(data_root) as db:
        if site_id:
            rows = db.execute(
                "SELECT * FROM git_connections WHERE site_id = ? ORDER BY updated_at DESC",
                (str(site_id),),
            ).fetchall()
        else:
            rows = db.execute("SELECT * FROM git_connections ORDER BY updated_at DESC").fetchall()
    return [_git_connection_row(row) for row in rows]


def prepare_git_connection(
    data_root: Path,
    *,
    site_id: object = None,
    display_name: object = None,
    repository_url: object,
    base_branch: object = None,
    auth_mode: object = "fine_grained_token",
    secret_logical_name: object = None,
    github_app_id: object = None,
    github_installation_id: object = None,
) -> dict[str, object]:
    owner, repo, normalized_url = _parse_github_repository(repository_url)
    branch = _clean_git_branch(base_branch or "main")
    mode = str(auth_mode or "fine_grained_token").strip()
    if mode != "fine_grained_token":
        raise ValueError("auth_mode must be fine_grained_token until GitHub App mode is implemented")
    logical_name = str(secret_logical_name or "github-token").strip()
    if logical_name not in _vault_requirements_for_git_mode(mode):
        raise ValueError(f"secret_logical_name must be one of {', '.join(_vault_requirements_for_git_mode(mode))}")

    site = get_site(data_root, site_id) if site_id else create_site(
        data_root,
        display_name=display_name or repo.replace("-", " ").replace("_", " ").title(),
        source_provider="git",
    )
    connection_id = _connection_id(owner, repo)
    now = now_timestamp()
    status = "pending_vault_grant"
    ensure_schema(data_root)
    with connect(data_root) as db:
        db.execute(
            """
            INSERT INTO git_connections(
              id, site_id, provider, owner, repo, repository_url, base_branch, auth_mode,
              secret_logical_name, github_app_id, github_installation_id, status, created_at, updated_at
            )
            VALUES (?, ?, 'github', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(provider, owner, repo) DO UPDATE SET
              site_id=excluded.site_id,
              repository_url=excluded.repository_url,
              base_branch=excluded.base_branch,
              auth_mode=excluded.auth_mode,
              secret_logical_name=excluded.secret_logical_name,
              github_app_id=excluded.github_app_id,
              github_installation_id=excluded.github_installation_id,
              status=excluded.status,
              updated_at=excluded.updated_at
            """,
            (
                connection_id,
                site["id"],
                owner,
                repo,
                normalized_url,
                branch,
                mode,
                logical_name,
                str(github_app_id or "").strip(),
                str(github_installation_id or "").strip(),
                status,
                now,
                now,
            ),
        )
    _update_site(
        data_root,
        site["id"],
        source_provider="git",
        source_label=f"github:{owner}/{repo}#{branch}",
        source_artifact_ref_json=json.dumps(
            {
                "provider": "github",
                "owner": owner,
                "repo": repo,
                "base_branch": branch,
                "connection_id": connection_id,
                "auth_mode": mode,
            },
            sort_keys=True,
        ),
    )
    set_active_site(data_root, site["id"])
    _audit(
        data_root,
        str(site["id"]),
        "git.connection.prepared",
        f"Prepared GitHub connection for {owner}/{repo}",
        {"connection_id": connection_id, "auth_mode": mode, "secret_logical_name": logical_name},
    )
    connection = get_git_connection(data_root, connection_id)
    return {
        "site": get_site(data_root, site["id"]),
        "connection": connection,
        "vault_requirements": _vault_requirement_payload(mode, logical_name, connection_id),
    }


def get_git_connection(data_root: Path, connection_id: object) -> dict[str, object]:
    clean_id = _required_id(connection_id, "connection_id")
    ensure_schema(data_root)
    with connect(data_root) as db:
        row = db.execute("SELECT * FROM git_connections WHERE id = ?", (clean_id,)).fetchone()
    if row is None:
        raise ValueError(f"git connection `{clean_id}` was not found")
    return _git_connection_row(row)


def activate_git_connection(
    data_root: Path,
    connection_id: object,
    *,
    grant_id: object = None,
    confirm_no_raw_secret: object = False,
) -> dict[str, object]:
    connection = get_git_connection(data_root, connection_id)
    if confirm_no_raw_secret is not True:
        raise ValueError("confirm_no_raw_secret=true is required; raw GitHub tokens must stay in Vault/Core Secrets")
    clean_grant = str(grant_id or "").strip()
    if not clean_grant:
        raise ValueError("grant_id is required to activate a GitHub connection")
    now = now_timestamp()
    with connect(data_root) as db:
        db.execute(
            "UPDATE git_connections SET status = 'grant_configured', updated_at = ? WHERE id = ?",
            (now, connection["id"]),
        )
    _audit(
        data_root,
        str(connection.get("site_id") or ""),
        "git.connection.activated",
        f"Activated GitHub connection for {connection['owner']}/{connection['repo']}",
        {"connection_id": connection["id"], "grant_id": clean_grant},
    )
    return {"connection": get_git_connection(data_root, connection["id"]), "grant_id": clean_grant}


def rebuild_index(data_root: Path, site_id: object) -> dict[str, object]:
    site = get_site(data_root, site_id)
    source_root = _source_root(data_root, str(site["id"]))
    now = now_timestamp()
    pages: list[dict[str, object]] = []
    html_files = sorted(source_root.rglob("*.html")) + sorted(source_root.rglob("*.htm"))
    ensure_schema(data_root)
    indexed_asset_paths = _source_asset_paths(source_root)
    with connect(data_root) as db:
        db.execute("UPDATE pages SET deleted_at = ? WHERE site_id = ?", (now, site["id"]))
        db.execute("UPDATE routes SET deleted_at = ? WHERE site_id = ?", (now, site["id"]))
        db.execute("UPDATE assets SET deleted_at = ? WHERE site_id = ?", (now, site["id"]))
        page_asset_refs: dict[str, list[str]] = {}
        indexed_routes: set[str] = set()
        for path in html_files:
            rel_path = path.relative_to(source_root).as_posix()
            route = _route_from_html_path(rel_path)
            indexed_routes.add(route)
            html = read_text_file(path)
            title = _html_title_from_text(html) or route
            page_id = f"page_{sha256_text(str(site['id']) + route)[:16]}"
            asset_refs = asset_references_from_html(html, page_path=rel_path)
            warnings = [f"missing asset `{ref}`" for ref in asset_refs if ref not in indexed_asset_paths]
            page_asset_refs[page_id] = asset_refs
            payload = (page_id, site["id"], route, title, "static", "draft", json.dumps([rel_path]), json.dumps(asset_refs), json.dumps(warnings), json.dumps(_html_seo(html), sort_keys=True), now)
            db.execute(
                """
                INSERT INTO pages(id, site_id, route, title, kind, status, source_files_json, asset_refs_json, warnings_json, seo_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  route=excluded.route,
                  title=excluded.title,
                  kind=excluded.kind,
                  status=excluded.status,
                  source_files_json=excluded.source_files_json,
                  asset_refs_json=excluded.asset_refs_json,
                  warnings_json=excluded.warnings_json,
                  seo_json=excluded.seo_json,
                  updated_at=excluded.updated_at,
                  deleted_at=NULL
                """,
                payload,
            )
            route_id = f"route_{sha256_text(str(site['id']) + route)[:16]}"
            db.execute(
                """
                INSERT INTO routes(id, site_id, route, page_id, kind, status, source_files_json, warnings_json, updated_at)
                VALUES (?, ?, ?, ?, 'static', ?, ?, ?, ?)
                ON CONFLICT(site_id, route) DO UPDATE SET
                  id=excluded.id,
                  page_id=excluded.page_id,
                  kind=excluded.kind,
                  status=excluded.status,
                  source_files_json=excluded.source_files_json,
                  warnings_json=excluded.warnings_json,
                  updated_at=excluded.updated_at,
                  deleted_at=NULL
                """,
                (route_id, site["id"], route, page_id, "broken" if warnings else "draft", json.dumps([rel_path]), json.dumps(warnings), now),
            )
        for route, kind, source_file, warnings in _extra_static_routes(source_root, indexed_routes):
            route_id = f"route_{sha256_text(str(site['id']) + kind + route)[:16]}"
            db.execute(
                """
                INSERT INTO routes(id, site_id, route, page_id, kind, status, source_files_json, warnings_json, updated_at)
                VALUES (?, ?, ?, '', ?, ?, ?, ?, ?)
                ON CONFLICT(site_id, route) DO UPDATE SET
                  id=excluded.id,
                  page_id=excluded.page_id,
                  kind=excluded.kind,
                  status=excluded.status,
                  source_files_json=excluded.source_files_json,
                  warnings_json=excluded.warnings_json,
                  updated_at=excluded.updated_at,
                  deleted_at=NULL
                """,
                (route_id, site["id"], route, kind, "redirect" if kind == "redirect" else "unmatched", json.dumps([source_file]), json.dumps(warnings), now),
            )
        referenced_by: dict[str, list[str]] = {}
        for page_id, refs in page_asset_refs.items():
            for ref in refs:
                referenced_by.setdefault(ref, []).append(page_id)
        for rel_path in sorted(indexed_asset_paths):
            asset_path = source_root / rel_path
            asset_id = f"asset_{sha256_text(str(site['id']) + rel_path)[:16]}"
            content_hash = _sha256_file(asset_path)
            db.execute(
                """
                INSERT INTO assets(id, site_id, path, kind, content_type, size_bytes, sha256, referenced_by_json, status, warnings_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  path=excluded.path,
                  kind=excluded.kind,
                  content_type=excluded.content_type,
                  size_bytes=excluded.size_bytes,
                  sha256=excluded.sha256,
                  referenced_by_json=excluded.referenced_by_json,
                  status=excluded.status,
                  warnings_json=excluded.warnings_json,
                  updated_at=excluded.updated_at,
                  deleted_at=NULL
                """,
                (
                    asset_id,
                    site["id"],
                    rel_path,
                    _asset_kind(asset_path),
                    detect_content_type(asset_path),
                    asset_path.stat().st_size,
                    content_hash,
                    json.dumps(referenced_by.get(rel_path, [])),
                    "referenced" if rel_path in referenced_by else "unlinked",
                    json.dumps([]),
                    now,
                ),
            )
        rows = db.execute(
            "SELECT * FROM pages WHERE site_id = ? AND deleted_at IS NULL ORDER BY route",
            (site["id"],),
        ).fetchall()
    profile = source_profile(source_root)
    source_version = _refresh_site_source_metadata(data_root, site["id"], profile)
    pages = [_page_row(row) for row in rows]
    return {"site_id": site["id"], "items": pages, "source_profile": profile, "source_version": source_version}


def sitemap(data_root: Path, site_id: object, *, mode: object = None) -> dict[str, object]:
    clean_site_id = _required_id(site_id, "site_id")
    mode_text = str(mode or "full").strip().lower().replace("_", "-")
    routes_only = mode_text in {"routes-only", "routes", "pages-routes"}
    ensure_schema(data_root)
    with connect(data_root) as db:
        page_rows = db.execute(
            "SELECT * FROM pages WHERE site_id = ? AND deleted_at IS NULL ORDER BY route",
            (clean_site_id,),
        ).fetchall()
        route_rows = db.execute(
            "SELECT * FROM routes WHERE site_id = ? AND deleted_at IS NULL ORDER BY route",
            (clean_site_id,),
        ).fetchall()
        asset_rows = []
        if not routes_only:
            asset_rows = db.execute(
                "SELECT * FROM assets WHERE site_id = ? AND deleted_at IS NULL ORDER BY path",
                (clean_site_id,),
            ).fetchall()
    return {
        "site_id": clean_site_id,
        "items": [_page_row(row) for row in page_rows],
        "routes": [_route_row(row) for row in route_rows],
        "assets": [_asset_row(row) for row in asset_rows],
    }


def _site_inventory_counts(data_root: Path, site_id: object) -> dict[str, int]:
    clean_site_id = _required_id(site_id, "site_id")
    ensure_schema(data_root)
    with connect(data_root) as db:
        page_count = db.execute(
            "SELECT COUNT(*) FROM pages WHERE site_id = ? AND deleted_at IS NULL",
            (clean_site_id,),
        ).fetchone()[0]
        route_count = db.execute(
            "SELECT COUNT(*) FROM routes WHERE site_id = ? AND deleted_at IS NULL",
            (clean_site_id,),
        ).fetchone()[0]
        asset_count = db.execute(
            "SELECT COUNT(*) FROM assets WHERE site_id = ? AND deleted_at IS NULL",
            (clean_site_id,),
        ).fetchone()[0]
    return {"page_count": int(page_count), "route_count": int(route_count), "asset_count": int(asset_count)}


def navigation_analyze(data_root: Path, site_id: object) -> dict[str, object]:
    """Return visual navigation, not the imported source inventory."""
    site = get_site(data_root, site_id)
    map_payload = sitemap(data_root, site["id"])
    pages = list(map_payload.get("items") or [])
    routes = list(map_payload.get("routes") or [])
    assets = list(map_payload.get("assets") or [])
    diff_payload = diff_site(data_root, site["id"])
    changed_paths = {str(item.get("path") or "") for item in diff_payload.get("files", []) if str(item.get("path") or "").strip()}
    runtime = runtime_status(data_root, site["id"])
    reports_by_route = _latest_preview_reports_by_route(data_root, site["id"])
    routes_by_page: dict[str, dict[str, object]] = {}
    for route_item in routes:
        page_id = str(route_item.get("page_id") or "")
        if page_id and page_id not in routes_by_page:
            routes_by_page[page_id] = route_item

    site_label = str(site.get("display_name") or site.get("slug") or site["id"])
    visual_page_entries = _canonical_visual_pages(
        pages,
        runtime_kind=str(runtime.get("runtime_kind") or ""),
        reports_by_route=reports_by_route,
        site_label=site_label,
    )
    visual_pages: list[dict[str, object]] = []
    flattened_components: list[dict[str, object]] = []
    for page, aliases in visual_page_entries:
        route_text = str(page.get("route") or "/")
        report = _preview_report_for_route(reports_by_route, route_text)
        report_id = str(report.get("id") or "")
        source_map = report.get("source_map") if isinstance(report.get("source_map"), dict) else {}
        source_files = _visual_source_files(page.get("source_files", []))
        section_items = _visual_sections_for_page(data_root, site["id"], page, source_map=source_map, report_id=report_id)
        sections = [item for item in section_items if item.get("kind") != "anchor"]
        anchors = [item for item in section_items if item.get("kind") == "anchor"]
        components = _components_from_report(source_map, route=route_text, page_id=str(page.get("id") or ""), report_id=report_id)
        flattened_components.extend(components)
        route_item = routes_by_page.get(str(page.get("id") or ""))
        visual_pages.append(
            {
                "id": page.get("id") or "",
                "kind": "page",
                "route": route_text,
                "canonical_route": _visual_route_key(route_text),
                "title": page.get("title") or route_text,
                "label": _visual_page_label(page, route_text, site_label=site_label),
                "aliases": aliases,
                "status": page.get("status") or "",
                "source_files": source_files[:20],
                "route_id": route_item.get("id") if route_item else "",
                "preview_report_id": report_id,
                "sections": sections,
                "anchors": anchors,
                "components": components,
                "warnings": _dedupe_strings(list(page.get("warnings") or []) + (list(route_item.get("warnings") or []) if route_item else []))[:50],
                "changed": _source_files_changed(source_files, changed_paths),
            }
        )

    page_route_keys: set[str] = set()
    for page, aliases in visual_page_entries:
        page_route_keys.add(_visual_route_key(str(page.get("route") or "/")))
        page_route_keys.update(_visual_route_key(alias) for alias in aliases)
    visual_routes: list[dict[str, object]] = []
    seen_visual_route_keys: set[str] = set()
    for route_item in routes:
        route_text = str(route_item.get("route") or "/")
        route_key = _visual_route_key(route_text)
        if route_key in page_route_keys or route_key in seen_visual_route_keys or not _route_is_visual(route_item):
            continue
        seen_visual_route_keys.add(route_key)
        report = _preview_report_for_route(reports_by_route, route_text)
        report_id = str(report.get("id") or "")
        source_map = report.get("source_map") if isinstance(report.get("source_map"), dict) else {}
        source_files = _visual_source_files(route_item.get("source_files", []))
        components = _components_from_report(source_map, route=route_text, page_id="", report_id=report_id)
        flattened_components.extend(components)
        visual_routes.append(
            {
                "id": route_item.get("id") or "",
                "kind": "route",
                "route": route_text,
                "canonical_route": route_key,
                "title": _route_label(route_text),
                "label": _route_label(route_text),
                "status": route_item.get("status") or "",
                "source_files": source_files[:20],
                "preview_report_id": report_id,
                "sections": [],
                "anchors": [],
                "components": components,
                "warnings": list(route_item.get("warnings") or [])[:50],
                "changed": _source_files_changed(source_files, changed_paths),
            }
        )

    latest_build = runtime.get("latest_build") if isinstance(runtime.get("latest_build"), dict) else {}
    latest_preview = runtime.get("latest_preview") if isinstance(runtime.get("latest_preview"), dict) else {}
    analysis_coverage = _navigation_analysis_coverage(visual_pages, visual_routes)
    warnings = _navigation_warnings(visual_pages, visual_routes, runtime, analysis_coverage=analysis_coverage)
    return {
        "site_id": site["id"],
        "model": "visual_navigation.v1",
        "generated_at": now_timestamp(),
        "site": {
            "id": site["id"],
            "display_name": site.get("display_name") or site.get("slug") or site["id"],
            "slug": site.get("slug") or "",
            "status": site.get("status") or "",
            "source_provider": site.get("source_provider") or "",
        },
        "pages": visual_pages,
        "routes": visual_routes,
        "components": flattened_components[:120],
        "analysis_coverage": analysis_coverage,
        "warnings": warnings,
        "status": {
            "runtime_kind": runtime.get("runtime_kind") or "",
            "runtime_status": runtime.get("runtime_status") or "unknown",
            "missing_requirements": list(runtime.get("missing_requirements") or [])[:50],
            "latest_build_id": latest_build.get("id") or "",
            "latest_build_status": latest_build.get("status") or "",
            "latest_preview_id": latest_preview.get("id") or "",
            "changed_files_count": len(changed_paths),
        },
        "inventory_summary": {
            "page_count": len(pages),
            "visible_page_count": len(visual_pages),
            "route_count": len(routes),
            "visible_route_count": len(visual_routes),
            "asset_count": len(assets),
            "source_inventory_hidden": True,
        },
        "navigation_policy": {
            "scope": "visual",
            "excludes_source_inventory": True,
            "excluded_categories": ["repository metadata", "server config", "backend admin source", "package manager metadata"],
        },
    }


def search(data_root: Path, query: object = "", site_id: object = None) -> list[dict[str, object]]:
    needle = f"%{str(query or '').strip()}%"
    ensure_schema(data_root)
    with connect(data_root) as db:
        site_rows = db.execute(
            "SELECT * FROM sites WHERE display_name LIKE ? OR slug LIKE ? ORDER BY updated_at DESC",
            (needle, needle),
        ).fetchall()
        if site_id:
            page_rows = db.execute(
                "SELECT * FROM pages WHERE site_id = ? AND deleted_at IS NULL AND (route LIKE ? OR title LIKE ?) ORDER BY route",
                (str(site_id), needle, needle),
            ).fetchall()
            route_rows = db.execute(
                "SELECT * FROM routes WHERE site_id = ? AND deleted_at IS NULL AND route LIKE ? ORDER BY route",
                (str(site_id), needle),
            ).fetchall()
            asset_rows = db.execute(
                "SELECT * FROM assets WHERE site_id = ? AND deleted_at IS NULL AND path LIKE ? ORDER BY path",
                (str(site_id), needle),
            ).fetchall()
        else:
            page_rows = db.execute(
                "SELECT * FROM pages WHERE deleted_at IS NULL AND (route LIKE ? OR title LIKE ?) ORDER BY route",
                (needle, needle),
            ).fetchall()
            route_rows = db.execute(
                "SELECT * FROM routes WHERE deleted_at IS NULL AND route LIKE ? ORDER BY route",
                (needle,),
            ).fetchall()
            asset_rows = db.execute(
                "SELECT * FROM assets WHERE deleted_at IS NULL AND path LIKE ? ORDER BY path",
                (needle,),
            ).fetchall()
    return (
        [_reference_payload("site", _site_row(row)) for row in site_rows]
        + [_reference_payload("page", _page_row(row)) for row in page_rows]
        + [_reference_payload("route", _route_row(row)) for row in route_rows]
        + [_reference_payload("asset", _asset_row(row)) for row in asset_rows]
    )


def read_file(data_root: Path, *, site_id: object, path: object) -> dict[str, object]:
    site = get_site(data_root, site_id)
    rel_path = safe_relative_path(path)
    validate_editable_text_path(rel_path)
    target = resolve_site_path(_source_root(data_root, str(site["id"])), rel_path)
    if not target.exists() or not target.is_file():
        raise ValueError(f"file `{rel_path}` was not found")
    content = read_text_file(target)
    return {
        "site_id": site["id"],
        "path": rel_path,
        "content": content,
        "hash": sha256_text(content),
        "revision_id": site.get("active_revision_id"),
    }


def write_file(data_root: Path, *, site_id: object, path: object, content: object, expected_hash: object = None) -> dict[str, object]:
    site = get_site(data_root, site_id)
    with _site_mutation_lock(data_root, str(site["id"])):
        current = None
        rel_path = safe_relative_path(path)
        content_size = len(str(content if content is not None else "").encode("utf-8"))
        validate_editable_text_path(rel_path, size_bytes=content_size)
        target = resolve_site_path(_source_root(data_root, str(site["id"])), rel_path)
        if target.exists():
            current = read_text_file(target)
        expected = str(expected_hash or "").strip()
        if current is None:
            if expected != "new":
                raise ValueError("expected_hash is required for new files; use `new`")
        elif not expected:
            raise ValueError("expected_hash is required for file writes")
        elif sha256_text(current) != expected:
            raise ValueError("stale write rejected: expected_hash does not match current file")
        write_text_file(target, content)
        rebuild_index(data_root, site["id"])
        changeset = _upsert_changeset(data_root, site["id"], f"Edited {rel_path}")
        _audit(data_root, str(site["id"]), "file.write", f"Edited {rel_path}", {"changeset_id": changeset["id"]})
        return {"file": read_file(data_root, site_id=site["id"], path=rel_path), "changeset": changeset}


def apply_text_patch(data_root: Path, *, site_id: object, path: object, old_text: object, new_text: object, expected_hash: object = None) -> dict[str, object]:
    if not str(expected_hash or "").strip():
        raise ValueError("expected_hash is required for file patches")
    file_payload = read_file(data_root, site_id=site_id, path=path)
    if expected_hash and file_payload["hash"] != str(expected_hash):
        raise ValueError("stale patch rejected: expected_hash does not match current file")
    content = str(file_payload["content"])
    old = str(old_text if old_text is not None else "")
    if old not in content:
        raise ValueError("old_text was not found in the selected file")
    return write_file(data_root, site_id=site_id, path=path, content=content.replace(old, str(new_text if new_text is not None else ""), 1), expected_hash=file_payload["hash"])


def diff_site(data_root: Path, site_id: object) -> dict[str, object]:
    site = get_site(data_root, site_id)
    base = _revision_snapshot(data_root, site.get("active_revision_id"))
    current = snapshot_text_files(_source_root(data_root, str(site["id"])))
    paths = sorted(set(base) | set(current))
    files: list[dict[str, object]] = []
    for rel_path in paths:
        before = base.get(rel_path)
        after = current.get(rel_path)
        if before == after:
            continue
        status = "modified" if before is not None and after is not None else "added" if after is not None else "deleted"
        patch = "\n".join(
            difflib.unified_diff(
                (before or "").splitlines(),
                (after or "").splitlines(),
                fromfile=f"a/{rel_path}",
                tofile=f"b/{rel_path}",
                lineterm="",
            )
        )
        files.append({"path": rel_path, "status": status, "patch": patch[:12000]})
    return {"site_id": site["id"], "base_revision_id": site.get("active_revision_id"), "files": files}


def build_preview(
    data_root: Path,
    site_id: object,
    route: object = "/",
    *,
    include_html: object = True,
    preview_origin: object = None,
) -> dict[str, object]:
    site = get_site(data_root, site_id)
    source_root = _source_root(data_root, str(site["id"]))
    profile = _cached_source_profile(data_root, site, source_root=source_root)
    if not str(site.get("source_version") or "").strip():
        site = get_site(data_root, site["id"])
    route_text = str(route or "/")
    include_preview_html = _truthy(include_html)
    if profile.get("preview_runtime_kind") in {"php", "node_build"}:
        return _build_runtime_preview(data_root, site, profile, route_text, include_html=include_preview_html, preview_origin=preview_origin)
    pages = sitemap(data_root, site["id"])["items"]
    page = next((item for item in pages if item["route"] == route_text), pages[0] if pages else None)
    preview_route = page["route"] if page else route_text
    runtime_kind = str(profile.get("preview_runtime_kind") or "unavailable")
    source_version = _source_version_for_site(site)
    cached_preview = _latest_compatible_preview(
        data_root,
        site_id=site["id"],
        route=preview_route,
        runtime_kind=runtime_kind,
        source_version=source_version,
    )
    if cached_preview:
        return _preview_response_from_record(data_root, site, cached_preview, include_html=include_preview_html, preview_origin=preview_origin)
    preview_id = f"preview_{uuid4().hex[:12]}"
    contract = _preview_contract(data_root, site, page=page, route=preview_route, preview_id=preview_id)
    contract["artifact_ref"] = {
        **(dict(contract.get("artifact_ref") or {}) if isinstance(contract.get("artifact_ref"), dict) else {}),
        "source_version": source_version,
    }
    if not page:
        _record_preview(data_root, site, contract)
        html = runtime_diagnostic_html("Preview runtime unavailable", contract["missing_requirements"] or ["site has no HTML page to preview"]) if include_preview_html else ""
        return {
            "preview_id": preview_id,
            "site_id": str(site["id"]),
            "environment_id": contract["environment_id"],
            "route": route_text,
            "page_id": "",
            "route_id": contract["route_id"],
            "runtime_kind": contract["runtime_kind"],
            "runtime_status": contract["runtime_status"],
            "preview_url": contract["preview_url"],
            "build_id": contract["build_id"],
            "missing_requirements": contract["missing_requirements"],
            "asset_refs": [],
            "warnings": contract["warnings"],
            "html": html,
        }
    rel_path = page["source_files"][0]
    html = read_file(data_root, site_id=site_id, path=rel_path)["content"] if include_preview_html else ""
    _record_preview(data_root, site, contract)
    return {
        "preview_id": preview_id,
        "site_id": str(site["id"]),
        "environment_id": contract["environment_id"],
        "route": page["route"],
        "page_id": page["id"],
        "route_id": contract["route_id"],
        "runtime_kind": contract["runtime_kind"],
        "runtime_status": contract["runtime_status"],
        "preview_url": contract["preview_url"],
        "build_id": contract["build_id"],
        "missing_requirements": contract["missing_requirements"],
        "asset_refs": page.get("asset_refs", []),
        "warnings": contract["warnings"],
        "html": preview_srcdoc_html(html, source_root=_source_root(data_root, str(site["id"])), page_path=rel_path) if include_preview_html else "",
    }


def _build_runtime_preview(
    data_root: Path,
    site: dict[str, object],
    profile: dict[str, object],
    route: str,
    *,
    include_html: bool = True,
    preview_origin: object = None,
) -> dict[str, object]:
    runtime_kind = str(profile.get("preview_runtime_kind") or "unavailable")
    build = _latest_passed_runtime_build(data_root, str(site["id"]), runtime_kind)
    if not build:
        build = validate_build(data_root, site["id"])
    if build.get("status") == "passed":
        cached_preview = _latest_compatible_preview(
            data_root,
            site_id=site["id"],
            route=route,
            runtime_kind=runtime_kind,
            build_id=str(build.get("id") or ""),
        )
        if cached_preview:
            return _preview_response_from_record(data_root, site, cached_preview, include_html=include_html, preview_origin=preview_origin)
    preview_id = f"preview_{uuid4().hex[:12]}"
    artifact_ref = dict(build.get("artifact_ref") or {}) if isinstance(build.get("artifact_ref"), dict) else {}
    result = render_runtime_preview(
        data_root,
        _source_root(data_root, str(site["id"])),
        route=route,
        source_profile=profile,
        artifact_ref=artifact_ref,
    )
    route_id = _route_id_for_route(data_root, site["id"], route)
    if result.get("status") == "ready":
        rendered = dict(result)
        rendered["route"] = route
        _upsert_runtime_route_index(data_root, site, rendered, profile)
        route_id = _route_id_for_route(data_root, site["id"], route)
    runtime_status = "ready" if result.get("status") == "ready" else str(result.get("status") or build.get("status") or "blocked")
    contract = {
        "preview_id": preview_id,
        "site_id": str(site["id"]),
        "environment_id": str(site.get("default_environment_id") or "env_preview"),
        "runtime_kind": runtime_kind,
        "preview_url": _preview_runtime_url(preview_id, route),
        "route": route,
        "route_id": route_id,
        "page_id": _page_id_for_route(data_root, site["id"], route),
        "build_id": str(build.get("id") or ""),
        "runtime_status": runtime_status,
        "warnings": [str(item) for item in result.get("warnings", [])][:100],
        "missing_requirements": [str(item) for item in result.get("missing_requirements", [])][:50],
        "artifact_ref": artifact_ref,
    }
    _record_preview(data_root, site, contract)
    html = str(result.get("html") or "")
    if include_html and result.get("status") == "ready":
        preview_record = {**contract, "id": preview_id}
        html = prepare_preview_document_html(
            html,
            preview_id=preview_id,
            page_path=result.get("page_path") or "index.html",
            preview_origin=preview_origin,
            stylesheet_loader=_preview_stylesheet_loader(data_root, preview_record),
            script_loader=_preview_script_loader(data_root, preview_record),
        )
    return {
        "preview_id": preview_id,
        "site_id": str(site["id"]),
        "environment_id": contract["environment_id"],
        "route": route,
        "page_id": contract["page_id"],
        "route_id": contract["route_id"],
        "runtime_kind": runtime_kind,
        "runtime_status": runtime_status,
        "preview_url": contract["preview_url"],
        "build_id": contract["build_id"],
        "missing_requirements": contract["missing_requirements"],
        "asset_refs": [],
        "warnings": contract["warnings"],
        "html": html,
    }


def _latest_compatible_preview(
    data_root: Path,
    *,
    site_id: object,
    route: object,
    runtime_kind: str,
    build_id: str = "",
    active_revision_id: str = "",
    source_version: str = "",
    source_fingerprint: str = "",
) -> dict[str, object]:
    """Return a ready preview matching the current runtime build or source tree."""
    route_text = str(route or "/")
    ensure_schema(data_root)
    with connect(data_root) as db:
        rows = db.execute(
            """
            SELECT * FROM previews
            WHERE site_id = ? AND route = ? AND runtime_kind = ?
            ORDER BY created_at DESC
            LIMIT 25
            """,
            (str(site_id), route_text, runtime_kind),
        ).fetchall()
    for row in rows:
        preview = _preview_row(row)
        if preview.get("status") not in {"ready", "static_fallback"}:
            continue
        if build_id and str(preview.get("build_id") or "") != build_id:
            continue
        if active_revision_id:
            artifact_ref = preview.get("artifact_ref") if isinstance(preview.get("artifact_ref"), dict) else {}
            if str(artifact_ref.get("active_revision_id") or "") != active_revision_id:
                continue
        if source_fingerprint:
            artifact_ref = preview.get("artifact_ref") if isinstance(preview.get("artifact_ref"), dict) else {}
            if str(artifact_ref.get("source_fingerprint") or "") != source_fingerprint:
                continue
        if source_version:
            artifact_ref = preview.get("artifact_ref") if isinstance(preview.get("artifact_ref"), dict) else {}
            if str(artifact_ref.get("source_version") or "") != source_version:
                continue
        return preview
    return {}


def _source_tree_fingerprint(source_root: Path) -> str:
    snapshot = snapshot_text_files(source_root)
    digest = hashlib.sha256()
    for rel_path in sorted(snapshot):
        digest.update(rel_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(snapshot[rel_path].encode("utf-8")).hexdigest().encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def _latest_preview_for_route(data_root: Path, *, site_id: object, route: object) -> dict[str, object]:
    row = _latest_route_row(data_root, table="previews", site_id=site_id, route=route)
    return _preview_row(row) if row else {}


def _latest_runtime_session_for_route(data_root: Path, *, site_id: object, route: object) -> dict[str, object]:
    row = _latest_route_row(data_root, table="runtime_sessions", site_id=site_id, route=route)
    return _runtime_session_row(row) if row else {}


def _latest_route_row(data_root: Path, *, table: str, site_id: object, route: object):
    if table not in {"previews", "runtime_sessions", "preview_reports"}:
        raise ValueError(f"unsupported route lookup table `{table}`")
    candidates = _route_lookup_candidates(route)
    ensure_schema(data_root)
    with connect(data_root) as db:
        row = db.execute(
            f"SELECT * FROM {table} WHERE site_id = ? AND route = ? ORDER BY created_at DESC LIMIT 1",
            (str(site_id), candidates[0]),
        ).fetchone()
        if row or len(candidates) == 1:
            return row
        placeholders = ",".join("?" for _ in candidates[1:])
        rows = db.execute(
            f"SELECT * FROM {table} WHERE site_id = ? AND route IN ({placeholders}) ORDER BY created_at DESC",
            (str(site_id), *candidates[1:]),
        ).fetchall()
    route_key = _visual_route_key(candidates[0])
    return next((row for row in rows if _visual_route_key(str(row["route"] or "/")) == route_key), None)


def _route_lookup_candidates(route: object) -> list[str]:
    raw_route = str(route or "/").strip() or "/"
    parsed = urlparse(raw_route)
    path = parsed.path or "/"
    if not path.startswith("/"):
        path = f"/{path}"
    path = re.sub(r"/+", "/", path).rstrip("/") or "/"
    key = _visual_route_key(path)
    aliases = [path]
    if key == "/":
        aliases.extend(["/", "/index", "/index.html", "/index.htm", "/index.php"])
    else:
        aliases.extend([key, f"{key}.html", f"{key}.htm", f"{key}.php", f"{key}/"])
    candidates: list[str] = []
    for alias in aliases:
        if alias not in candidates:
            candidates.append(alias)
    return candidates


def _preview_response_from_record(
    data_root: Path,
    site: dict[str, object],
    preview: dict[str, object],
    *,
    include_html: bool = True,
    preview_origin: object = None,
) -> dict[str, object]:
    document = preview_document(data_root, preview["id"], preview_origin=preview_origin) if include_html else {}
    page_id = str(preview.get("page_id") or "")
    asset_refs: list[object] = []
    if page_id:
        try:
            page = _get_page(data_root, page_id)
            asset_refs = list(page.get("asset_refs", []))
        except ValueError:
            asset_refs = []
    return {
        "preview_id": str(preview.get("id") or ""),
        "site_id": str(site["id"]),
        "environment_id": str(site.get("default_environment_id") or "env_preview"),
        "route": str(preview.get("route") or "/"),
        "page_id": page_id,
        "route_id": _route_id_for_route(data_root, site["id"], preview.get("route") or "/"),
        "runtime_kind": str(preview.get("runtime_kind") or "unavailable"),
        "runtime_status": str(preview.get("status") or "blocked"),
        "preview_url": str(preview.get("preview_url") or ""),
        "build_id": str(preview.get("build_id") or ""),
        "missing_requirements": list(preview.get("missing_requirements") or [])[:50],
        "asset_refs": asset_refs,
        "warnings": list(preview.get("warnings") or [])[:100],
        "html": str(document.get("html") or "") if include_html else "",
    }


def _latest_passed_runtime_build(data_root: Path, site_id: str, runtime_kind: str) -> dict[str, object]:
    ensure_schema(data_root)
    with connect(data_root) as db:
        rows = db.execute(
            "SELECT * FROM builds WHERE site_id = ? AND runtime_kind = ? AND status = 'passed' ORDER BY created_at DESC LIMIT 25",
            (site_id, runtime_kind),
        ).fetchall()
    source_version = _source_version_for_site(get_site(data_root, site_id))
    for row in rows:
        build = _build_row(row)
        artifact_ref = build.get("artifact_ref") if isinstance(build.get("artifact_ref"), dict) else {}
        if source_version and str(artifact_ref.get("source_version") or "") != source_version:
            continue
        return build
    return {}


def _route_id_for_route(data_root: Path, site_id: object, route: object) -> str:
    ensure_schema(data_root)
    with connect(data_root) as db:
        row = db.execute(
            "SELECT id FROM routes WHERE site_id = ? AND route = ? AND deleted_at IS NULL",
            (str(site_id), str(route or "/")),
        ).fetchone()
    return str(row["id"]) if row else ""


def _page_id_for_route(data_root: Path, site_id: object, route: object) -> str:
    ensure_schema(data_root)
    with connect(data_root) as db:
        row = db.execute(
            "SELECT id FROM pages WHERE site_id = ? AND route = ? AND deleted_at IS NULL",
            (str(site_id), str(route or "/")),
        ).fetchone()
    return str(row["id"]) if row else ""


def validate_build(data_root: Path, site_id: object) -> dict[str, object]:
    site = get_site(data_root, site_id)
    source_root = _source_root(data_root, str(site["id"]))
    profile = _cached_source_profile(data_root, site, source_root=source_root)
    if not str(site.get("source_version") or "").strip():
        site = get_site(data_root, site["id"])
    source_version = _source_version_for_site(site)
    map_payload = sitemap(data_root, site["id"])
    map_warnings: list[str] = []
    warnings: list[str] = []
    for item in map_payload.get("items", []):
        map_warnings.extend(route_specific_warnings(list(item.get("warnings") or [])))
    for item in map_payload.get("routes", []):
        map_warnings.extend(route_specific_warnings(list(item.get("warnings") or [])))
    runtime_kind = str(profile.get("preview_runtime_kind") or "unavailable")
    build_id = f"build_{uuid4().hex[:16]}"
    missing_requirements = [str(item) for item in profile.get("missing_requirements", []) if str(item).strip()] if isinstance(profile.get("missing_requirements"), list) else []
    artifact_ref: dict[str, object] = {}
    rendered_routes: list[dict[str, object]] = []
    if runtime_kind == "static_export":
        warnings.extend(map_warnings)
        status = "passed" if profile.get("static_preview_supported") else "blocked"
        logs_summary = "Static preview artifact prepared." if status == "passed" else "No runnable preview artifact is available without a supported runtime."
        artifact_ref = _create_static_build_artifact(data_root, site, build_id) if status == "passed" else {}
    elif runtime_kind in {"php", "node_build"}:
        runtime_build = prepare_runtime_build(data_root, str(site["id"]), source_root, build_id=build_id, source_profile=profile)
        status = str(runtime_build.get("status") or "blocked")
        artifact_ref = dict(runtime_build.get("artifact_ref") or {})
        warnings.extend(str(item) for item in runtime_build.get("warnings", []) if str(item).strip())
        missing_requirements = [str(item) for item in runtime_build.get("missing_requirements", []) if str(item).strip()]
        logs_summary = str(runtime_build.get("logs_summary") or "")
        if status == "passed":
            rendered_routes = _render_known_routes(data_root, site, profile, artifact_ref, map_payload)
            for rendered in rendered_routes:
                warnings.extend(route_specific_warnings(list(rendered.get("warnings") or [])))
            failed_routes = [item for item in rendered_routes if item.get("status") != "ready"]
            if rendered_routes and len(failed_routes) == len(rendered_routes):
                status = "failed"
                warnings.append("runtime build completed, but no indexed route rendered successfully")
        else:
            warnings.extend(map_warnings)
    else:
        warnings.extend(map_warnings)
        status = "blocked"
        logs_summary = "No runnable preview artifact is available without a supported runtime."
    if artifact_ref:
        artifact_ref = {**artifact_ref, "source_version": source_version}
    now = now_timestamp()
    with connect(data_root) as db:
        db.execute(
            """
            INSERT INTO builds(
              id, site_id, status, runtime_kind, preview_url, artifact_ref_json, source_profile_json,
              route_count, asset_count, warnings_json, missing_requirements_json, logs_summary, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                build_id,
                site["id"],
                status,
                runtime_kind,
                "",
                json.dumps(artifact_ref, sort_keys=True),
                json.dumps(profile, sort_keys=True),
                len(map_payload.get("routes", [])),
                len(map_payload.get("assets", [])),
                json.dumps(_dedupe_strings(warnings)[:100]),
                json.dumps(missing_requirements[:50]),
                logs_summary,
                now,
                now,
            ),
        )
    if rendered_routes:
        for rendered in rendered_routes:
            _upsert_runtime_route_index(data_root, site, rendered, profile)
    _refresh_site_source_metadata(data_root, site["id"], profile, bump_version=False)
    _audit(data_root, str(site["id"]), "build.validated", logs_summary, {"build_id": build_id, "status": status})
    return get_build(data_root, build_id)


def _render_known_routes(
    data_root: Path,
    site: dict[str, object],
    profile: dict[str, object],
    artifact_ref: dict[str, object],
    map_payload: dict[str, object],
) -> list[dict[str, object]]:
    routes: list[str] = []
    for item in map_payload.get("items", []):
        route = str(item.get("route") or "").strip()
        if route and route not in routes:
            routes.append(route)
    for item in map_payload.get("routes", []):
        route = str(item.get("route") or "").strip()
        if route and route not in routes:
            routes.append(route)
    if not routes:
        routes.append("/")
    rendered: list[dict[str, object]] = []
    seen: set[str] = set()
    while routes and len(rendered) < MAX_RENDERED_ROUTES:
        route = routes.pop(0)
        if route in seen:
            continue
        seen.add(route)
        result = render_runtime_preview(
            data_root,
            _source_root(data_root, str(site["id"])),
            route=route,
            source_profile=profile,
            artifact_ref=artifact_ref,
        )
        result["route"] = route
        rendered.append(result)
        raw_html = str(result.get("raw_html") or result.get("html") or "")
        if result.get("status") == "ready" and raw_html:
            for discovered in internal_routes_from_html(raw_html, base_route=route):
                if discovered not in seen and discovered not in routes and len(routes) + len(rendered) < MAX_RENDERED_ROUTES:
                    routes.append(discovered)
    return rendered


def _upsert_runtime_route_index(
    data_root: Path,
    site: dict[str, object],
    rendered: dict[str, object],
    profile: dict[str, object],
) -> None:
    route = str(rendered.get("route") or "/").strip() or "/"
    status = "rendered" if rendered.get("status") == "ready" else str(rendered.get("status") or "blocked")
    runtime_kind = str(rendered.get("runtime_kind") or profile.get("preview_runtime_kind") or "runtime")
    source_files = [str(item) for item in rendered.get("source_files", []) if str(item).strip()]
    if not source_files:
        source_files = source_files_for_runtime_route(_source_root(data_root, str(site["id"])), profile)
    warnings = route_specific_warnings(list(rendered.get("warnings") or []))
    if rendered.get("status") != "ready" and not warnings:
        warnings = [f"{runtime_kind} route did not render successfully"]
    now = now_timestamp()
    route_id = f"route_{sha256_text(str(site['id']) + runtime_kind + route)[:16]}"
    with connect(data_root) as db:
        page_id = ""
        raw_html = str(rendered.get("raw_html") or "")
        if rendered.get("status") == "ready":
            existing_page = db.execute(
                "SELECT id FROM pages WHERE site_id = ? AND route = ?",
                (site["id"], route),
            ).fetchone()
            page_id = str(existing_page["id"]) if existing_page else f"page_{sha256_text(str(site['id']) + runtime_kind + route)[:16]}"
            title = str(rendered.get("title") or route)
            db.execute(
                """
                INSERT INTO pages(id, site_id, route, title, kind, status, source_files_json, asset_refs_json, warnings_json, seo_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, ?)
                ON CONFLICT(site_id, route) DO UPDATE SET
                  title=excluded.title,
                  kind=excluded.kind,
                  status=excluded.status,
                  source_files_json=excluded.source_files_json,
                  warnings_json=excluded.warnings_json,
                  seo_json=excluded.seo_json,
                  updated_at=excluded.updated_at,
                  deleted_at=NULL
                """,
                (
                    page_id,
                    site["id"],
                    route,
                    title,
                    runtime_kind,
                    status,
                    json.dumps(source_files),
                    json.dumps(warnings[:100]),
                    json.dumps(_html_seo(raw_html), sort_keys=True),
                    now,
                ),
            )
        db.execute(
            """
            INSERT INTO routes(id, site_id, route, page_id, kind, status, source_files_json, warnings_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(site_id, route) DO UPDATE SET
              id=excluded.id,
              page_id=excluded.page_id,
              kind=excluded.kind,
              status=excluded.status,
              source_files_json=excluded.source_files_json,
              warnings_json=excluded.warnings_json,
              updated_at=excluded.updated_at,
              deleted_at=NULL
            """,
            (
                route_id,
                site["id"],
                route,
                page_id,
                runtime_kind,
                status,
                json.dumps(source_files),
                json.dumps(warnings[:100]),
                now,
            ),
        )


def list_builds(
    data_root: Path,
    site_id: object,
    *,
    limit: object = None,
    offset: object = 0,
    include_logs: object = False,
) -> dict[str, object]:
    site = get_site(data_root, site_id)
    clean_limit = _bounded_int(limit, default=DEFAULT_HISTORY_LIMIT, minimum=1, maximum=MAX_HISTORY_LIMIT)
    clean_offset = _bounded_int(offset, default=0, minimum=0, maximum=1_000_000)
    ensure_schema(data_root)
    with connect(data_root) as db:
        rows = db.execute(
            "SELECT * FROM builds WHERE site_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (site["id"], clean_limit + 1, clean_offset),
        ).fetchall()
    page_rows = rows[:clean_limit]
    return {
        "site_id": site["id"],
        "items": [_build_row(row, include_logs=_truthy(include_logs)) for row in page_rows],
        "pagination": _pagination(limit=clean_limit, offset=clean_offset, returned=len(page_rows), has_more=len(rows) > clean_limit),
    }


def maintenance_prune(
    data_root: Path,
    site_id: object = None,
    *,
    keep_builds: object = None,
    keep_previews_per_route: object = None,
    keep_runtime_sessions: object = None,
    dry_run: object = False,
) -> dict[str, object]:
    ensure_schema(data_root)
    clean_keep_builds = _bounded_int(keep_builds, default=DEFAULT_RETAIN_BUILDS, minimum=1, maximum=500)
    clean_keep_previews = _bounded_int(keep_previews_per_route, default=DEFAULT_RETAIN_PREVIEWS_PER_ROUTE, minimum=1, maximum=50)
    clean_keep_sessions = _bounded_int(keep_runtime_sessions, default=DEFAULT_RETAIN_RUNTIME_SESSIONS, minimum=1, maximum=500)
    is_dry_run = _truthy(dry_run)
    sites = [get_site(data_root, site_id)] if site_id else list_sites(data_root)
    summaries: list[dict[str, object]] = []
    totals = {"builds": 0, "previews": 0, "runtime_sessions": 0, "artifact_dirs": 0}
    for site in sites:
        summary = prune_site_operational_history(
            data_root,
            str(site["id"]),
            keep_builds=clean_keep_builds,
            keep_previews_per_route=clean_keep_previews,
            keep_runtime_sessions=clean_keep_sessions,
            dry_run=is_dry_run,
        )
        summaries.append(summary)
        for key in totals:
            totals[key] += int(summary.get(f"pruned_{key}", 0) or 0)
    return {
        "status": "dry_run" if is_dry_run else "pruned",
        "dry_run": is_dry_run,
        "policy": maintenance_policy_defaults(
            keep_builds=clean_keep_builds,
            keep_previews_per_route=clean_keep_previews,
            keep_runtime_sessions=clean_keep_sessions,
        ),
        "totals": totals,
        "sites": summaries,
    }


def maintenance_policy_defaults(
    *,
    keep_builds: int = DEFAULT_RETAIN_BUILDS,
    keep_previews_per_route: int = DEFAULT_RETAIN_PREVIEWS_PER_ROUTE,
    keep_runtime_sessions: int = DEFAULT_RETAIN_RUNTIME_SESSIONS,
) -> dict[str, object]:
    return {
        "keep_builds": keep_builds,
        "keep_previews_per_route": keep_previews_per_route,
        "keep_runtime_sessions": keep_runtime_sessions,
        "cadence": DEFAULT_RETENTION_REVIEW_CADENCE,
        "dry_run_first": True,
        "protected_records": [
            "source trees",
            "site records",
            "revision snapshots",
            "deployment artifacts",
            "publish requests",
            "approval events",
        ],
    }


def get_build(data_root: Path, build_id: object) -> dict[str, object]:
    clean_id = _required_id(build_id, "build_id")
    ensure_schema(data_root)
    with connect(data_root) as db:
        row = db.execute("SELECT * FROM builds WHERE id = ?", (clean_id,)).fetchone()
    if row is None:
        raise ValueError(f"build `{clean_id}` was not found")
    return _build_row(row)


def runtime_status(data_root: Path, site_id: object) -> dict[str, object]:
    site = get_site(data_root, site_id)
    source_root = _source_root(data_root, str(site["id"]))
    profile = _cached_source_profile(data_root, site, source_root=source_root)
    capability = runtime_capability_status(source_root, profile)
    ensure_schema(data_root)
    with connect(data_root) as db:
        build_row = db.execute("SELECT * FROM builds WHERE site_id = ? ORDER BY created_at DESC LIMIT 1", (site["id"],)).fetchone()
        preview_row = db.execute("SELECT * FROM previews WHERE site_id = ? ORDER BY created_at DESC LIMIT 1", (site["id"],)).fetchone()
        session_row = db.execute("SELECT * FROM runtime_sessions WHERE site_id = ? ORDER BY created_at DESC LIMIT 1", (site["id"],)).fetchone()
    latest_build = _build_row(build_row, include_logs=False) if build_row else None
    runtime_status_value = str(capability.get("runtime_status") or profile.get("runtime_preview_status") or "blocked")
    if latest_build and latest_build.get("status") in {"failed", "blocked"}:
        runtime_status_value = str(latest_build.get("status"))
    if latest_build and latest_build.get("status") == "passed" and not capability.get("missing_requirements"):
        runtime_status_value = "ready"
    missing_requirements = capability.get("missing_requirements") or []
    runtime_kind = str(capability.get("runtime_kind") or profile.get("preview_runtime_kind") or "unavailable")
    profile = _source_profile_with_runtime_status(
        profile,
        runtime_kind=runtime_kind,
        runtime_status=runtime_status_value,
        missing_requirements=missing_requirements,
    )
    if latest_build and isinstance(latest_build.get("source_profile"), dict):
        latest_build_status = "ready" if latest_build.get("status") == "passed" and not latest_build.get("missing_requirements") else str(latest_build.get("status") or runtime_status_value)
        latest_build["source_profile"] = _source_profile_with_runtime_status(
            latest_build["source_profile"],
            runtime_kind=str(latest_build.get("runtime_kind") or runtime_kind),
            runtime_status=latest_build_status,
            missing_requirements=latest_build.get("missing_requirements") or [],
        )
    return {
        "site_id": site["id"],
        "source_profile": profile,
        "runtime_kind": runtime_kind,
        "runtime_status": runtime_status_value,
        "missing_requirements": missing_requirements,
        "latest_build": latest_build,
        "latest_preview": _preview_row(preview_row) if preview_row else None,
        "latest_runtime_session": _runtime_session_row(session_row) if session_row else None,
        "latest_preview_report": _latest_preview_report(data_root, site["id"]),
    }


def preview_document(data_root: Path, preview_id: object, *, preview_origin: object = None, include_inventory: object = False) -> dict[str, object]:
    preview = get_preview(data_root, preview_id)
    site = get_site(data_root, preview["site_id"])
    details = [str(item) for item in preview.get("missing_requirements", []) if str(item).strip()]
    cache_key = _preview_document_cache_key(preview, site)
    cached_html = "" if str(preview_origin or "").strip() else _read_preview_document_cache(data_root, preview, cache_key)
    if cached_html:
        return _preview_document_payload(data_root, preview, cached_html, include_inventory=include_inventory)
    if preview.get("runtime_kind") in {"php", "node_build"}:
        profile = _cached_source_profile(data_root, site)
        result = render_runtime_preview(
            data_root,
            _source_root(data_root, str(site["id"])),
            route=str(preview.get("route") or "/"),
            source_profile=profile,
            artifact_ref=preview.get("artifact_ref") if isinstance(preview.get("artifact_ref"), dict) else {},
        )
        if result.get("status") == "ready":
            html = prepare_preview_document_html(
                str(result.get("html") or ""),
                preview_id=preview["id"],
                page_path=result.get("page_path") or "index.html",
                preview_origin=preview_origin,
                stylesheet_loader=_preview_stylesheet_loader(data_root, preview),
                script_loader=_preview_script_loader(data_root, preview),
            )
            if not str(preview_origin or "").strip():
                _write_preview_document_cache(data_root, preview, cache_key, html)
            return _preview_document_payload(data_root, preview, html, include_inventory=include_inventory)
        detail = [str(item) for item in result.get("missing_requirements", []) if str(item).strip()] or [str(item) for item in result.get("warnings", []) if str(item).strip()]
        html = runtime_diagnostic_html("Preview runtime unavailable", detail or details or ["preview route could not be rendered"])
        if not str(preview_origin or "").strip():
            _write_preview_document_cache(data_root, preview, cache_key, html)
        return _preview_document_payload(data_root, preview, html, include_inventory=include_inventory)
    if not preview.get("page_id"):
        html = runtime_diagnostic_html("Preview runtime unavailable", details or ["site has no HTML page to preview"])
        if not str(preview_origin or "").strip():
            _write_preview_document_cache(data_root, preview, cache_key, html)
        return _preview_document_payload(data_root, preview, html, include_inventory=include_inventory)
    try:
        page = _get_page(data_root, preview["page_id"])
        rel_path = page["source_files"][0]
        html = read_file(data_root, site_id=site["id"], path=rel_path)["content"]
        if preview.get("status") in {"ready", "static_fallback"}:
            html = prepare_preview_document_html(
                    html,
                    preview_id=preview["id"],
                    page_path=rel_path,
                    preview_origin=preview_origin,
                    stylesheet_loader=_preview_stylesheet_loader(data_root, preview),
                    script_loader=_preview_script_loader(data_root, preview),
            )
            if not str(preview_origin or "").strip():
                _write_preview_document_cache(data_root, preview, cache_key, html)
            return _preview_document_payload(data_root, preview, html, include_inventory=include_inventory)
    except (IndexError, ValueError) as error:
        details.append(str(error))
    html = runtime_diagnostic_html("Preview runtime unavailable", details or ["preview source could not be rendered"])
    if not str(preview_origin or "").strip():
        _write_preview_document_cache(data_root, preview, cache_key, html)
    return _preview_document_payload(data_root, preview, html, include_inventory=include_inventory)


def _preview_document_cache_key(preview: dict[str, object], site: dict[str, object]) -> str:
    artifact_ref = preview.get("artifact_ref") if isinstance(preview.get("artifact_ref"), dict) else {}
    payload = {
        "schema": "website-studio.preview-document-cache.v1",
        "runtime_version": PREVIEW_RUNTIME_VERSION,
        "preview_id": str(preview.get("id") or ""),
        "site_id": str(preview.get("site_id") or ""),
        "site_source_version": _source_version_for_site(site),
        "artifact_source_version": str(artifact_ref.get("source_version") or ""),
        "build_id": str(preview.get("build_id") or ""),
        "runtime_root": str(artifact_ref.get("runtime_root") or ""),
        "docroot": str(artifact_ref.get("docroot") or ""),
        "route": str(preview.get("route") or "/"),
        "page_id": str(preview.get("page_id") or ""),
        "runtime_kind": str(preview.get("runtime_kind") or ""),
        "status": str(preview.get("status") or ""),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _preview_document_cache_path(data_root: Path, preview: dict[str, object], cache_key: str) -> Path:
    preview_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(preview.get("id") or "preview")).strip("._") or "preview"
    return data_root / "run" / "preview-documents" / preview_id / f"{cache_key}.json"


def _read_preview_document_cache(data_root: Path, preview: dict[str, object], cache_key: str) -> str:
    path = _preview_document_cache_path(data_root, preview, cache_key)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    if payload.get("schema") != "website-studio.preview-document-cache.v1":
        return ""
    if str(payload.get("runtime_version") or "") != PREVIEW_RUNTIME_VERSION:
        return ""
    if str(payload.get("cache_key") or "") != cache_key:
        return ""
    html = payload.get("html")
    return html if isinstance(html, str) else ""


def _write_preview_document_cache(data_root: Path, preview: dict[str, object], cache_key: str, html: str) -> None:
    path = _preview_document_cache_path(data_root, preview, cache_key)
    payload = {
        "schema": "website-studio.preview-document-cache.v1",
        "runtime_version": PREVIEW_RUNTIME_VERSION,
        "cache_key": cache_key,
        "preview_id": str(preview.get("id") or ""),
        "created_at": now_timestamp(),
        "html": str(html or ""),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temp_path.replace(path)
    except OSError:
        return


def preview_report(
    data_root: Path,
    *,
    site_id: object = None,
    preview_id: object = None,
    route: object = "/",
    baseline_report_id: object = None,
    preview_origin: object = None,
    include_inventory: object = False,
) -> dict[str, object]:
    """Create a bounded report that lets agents reason about the real preview surface."""
    clean_preview_id = str(preview_id or "").strip()
    if not clean_preview_id:
        if not site_id:
            raise ValueError("site_id is required when preview_id is not supplied")
        preview_payload = build_preview(data_root, site_id, route or "/", include_html=False, preview_origin=preview_origin)
        clean_preview_id = str(preview_payload.get("preview_id") or "").strip()
    preview = get_preview(data_root, clean_preview_id)
    if site_id and str(preview.get("site_id") or "") != str(site_id):
        raise ValueError("preview_id does not belong to the selected site")
    site = get_site(data_root, preview["site_id"])
    document = preview_document(data_root, clean_preview_id, preview_origin=preview_origin, include_inventory=include_inventory)
    source_map = dict(document.get("source_map") or {})
    asset_probe = _preview_asset_probe(data_root, preview, document.get("html") or "", source_map)
    warnings = [str(item) for item in preview.get("warnings", []) if str(item).strip()]
    missing = [str(item) for item in preview.get("missing_requirements", []) if str(item).strip()]
    acceptance = acceptance_checks(
        runtime_status=str(preview.get("status") or "blocked"),
        missing_requirements=missing,
        warnings=warnings,
        asset_probe=asset_probe,
        source_map=source_map,
    )
    now = now_timestamp()
    report_id = f"report_{uuid4().hex[:16]}"
    components = component_candidates_from_selector_hints(
        source_map.get("selector_hints") if isinstance(source_map, dict) else [],
        route=str(preview.get("route") or "/"),
        page_id=str(source_map.get("page_id") or "") if isinstance(source_map, dict) else "",
        last_report_id=report_id,
    )
    report = {
        "id": report_id,
        "site_id": site["id"],
        "preview_id": preview["id"],
        "route": preview.get("route") or "/",
        "build_id": preview.get("build_id") or "",
        "runtime_kind": preview.get("runtime_kind") or "unavailable",
        "runtime_status": preview.get("status") or "blocked",
        "generated_at": now,
        "source_map": source_map,
        "navigation": {
            "route": preview.get("route") or "/",
            "page_id": source_map.get("page_id") if isinstance(source_map, dict) else "",
            "components": components,
        },
        "components": components,
        "asset_coverage": asset_probe,
        "warnings": warnings,
        "missing_requirements": missing,
        "acceptance": acceptance,
        "browser_probe": _browser_probe_contract(preview),
        "screenshot_checks": [
            {"viewport": "desktop", "status": "browser_probe_required", "width": 1440, "height": 920},
            {"viewport": "mobile", "status": "browser_probe_required", "width": 390, "height": 844},
        ],
    }
    baseline = _preview_report_row(data_root, baseline_report_id) if baseline_report_id else {}
    if baseline:
        report["comparison"] = _preview_report_comparison(baseline, report)
    _record_preview_report(data_root, report)
    return {"report": report}


def preview_media(data_root: Path, preview_id: object, path: object) -> dict[str, object]:
    preview = get_preview(data_root, preview_id)
    clean_path = safe_preview_asset_path(path)
    target, resolved_rel_path = _resolve_preview_asset_path(data_root, preview, clean_path)
    if target.suffix.lower() == ".css" and target.stat().st_size <= 2 * 1024 * 1024:
        css = target.read_text(encoding="utf-8", errors="replace")
        rewritten = rewrite_preview_css(css, preview_id=preview["id"], css_path=resolved_rel_path)
        target = _write_preview_css_cache(data_root, preview["id"], resolved_rel_path, rewritten)
        content_type = "text/css; charset=utf-8"
        etag = sha256_text(rewritten)
    else:
        content_type = detect_content_type(target)
        etag = _file_etag(target)
    return {
        "preview_id": str(preview["id"]),
        "path": resolved_rel_path,
        "file_response": {
            "path": str(target),
            "content_type": content_type,
            "file_name": target.name,
            "etag": etag,
            "download": False,
            "cache_control": PREVIEW_FILE_GATEWAY_CACHE_CONTROL,
            "headers": PREVIEW_MEDIA_RESPONSE_HEADERS,
        },
    }


def _replace_preview_media_urls_with_gateway(
    data_root: Path,
    preview: dict[str, object],
    html: str,
    *,
    gateway_urls: dict[str, str] | None = None,
) -> str:
    pattern = re.compile(
        r"(?P<prefix>(?:https?://[^\"'`\s<>)]+|__WEBSITE_STUDIO_PREVIEW_ORIGIN__)?/api/apps/website-studio/backend/media)\?(?P<query>[^\"'`\s<>)]+)",
        re.IGNORECASE,
    )
    replacements: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        original = match.group(0)
        if original in replacements:
            return replacements[original]
        query_text, separator, fragment = match.group("query").partition("#")
        params = parse_qs(query_text, keep_blank_values=True)
        rel_path = params.get("path", [""])[0]
        if not rel_path:
            return original
        try:
            media_payload = preview_media(data_root, preview["id"], rel_path)
            asset_path = str(media_payload.get("path") or rel_path)
            relative_gateway = _preview_file_gateway_url(
                data_root,
                preview,
                file_response=dict(media_payload.get("file_response") or {}),
                asset_path=asset_path,
                aliases=[rel_path],
                gateway_urls=gateway_urls,
            )
        except (OSError, ValueError):
            return original
        gateway = match.group("prefix").rsplit("/backend/media", 1)[0] + relative_gateway.removeprefix("/api/apps/website-studio")
        if separator:
            gateway = f"{gateway}#{fragment}"
        replacements[original] = gateway
        return gateway

    return pattern.sub(replace, html)


def _preview_file_gateway_url(
    data_root: Path,
    preview: dict[str, object],
    *,
    file_response: dict[str, object],
    asset_path: str,
    gateway_urls: dict[str, str] | None = None,
    aliases: list[str] | None = None,
) -> str:
    clean_asset_path = safe_preview_asset_path(asset_path)
    if gateway_urls is not None and clean_asset_path in gateway_urls:
        gateway = gateway_urls[clean_asset_path]
        _record_preview_file_gateway_aliases(gateway_urls, gateway, aliases)
        return gateway
    token = _reusable_preview_file_gateway_token(
        data_root,
        app_id="website-studio",
        file_response=file_response,
        asset_path=clean_asset_path,
    ) or _write_preview_file_gateway_manifest(
        data_root,
        app_id="website-studio",
        file_response=file_response,
        preview_id=str(preview.get("id") or ""),
        asset_path=clean_asset_path,
    )
    gateway = f"/api/apps/website-studio/backend/file/{token}"
    if gateway_urls is not None:
        gateway_urls[clean_asset_path] = gateway
        _record_preview_file_gateway_aliases(gateway_urls, gateway, aliases)
    return gateway


def _record_preview_file_gateway_aliases(gateway_urls: dict[str, str], gateway: str, aliases: list[str] | None) -> None:
    for alias in aliases or []:
        try:
            clean_alias = safe_preview_asset_path(alias)
        except ValueError:
            continue
        gateway_urls.setdefault(clean_alias, gateway)


def _write_preview_file_gateway_manifest(
    data_root: Path,
    *,
    app_id: str,
    file_response: dict[str, object],
    preview_id: str,
    asset_path: str,
) -> str:
    raw_path = str(file_response.get("path") or "").strip()
    if not raw_path:
        raise ValueError("file_response path is required")
    manifest_root = data_root / "run" / "file-gateway"
    manifest_root.mkdir(parents=True, exist_ok=True)
    token = "gw_" + secrets.token_urlsafe(32)
    while (manifest_root / f"{token}.json").exists():
        token = "gw_" + secrets.token_urlsafe(32)
    now = datetime.now(tz=UTC)
    manifest = {
        "schema": FILE_GATEWAY_SCHEMA,
        "app_id": app_id,
        "access": "public_capability",
        "preview_id": preview_id,
        "asset_path": asset_path,
        "created_at": now.isoformat(),
        "expires_at": (now + PREVIEW_FILE_GATEWAY_TTL).isoformat(),
        "allowed_paths": [str(Path(raw_path).resolve())],
        "file_response": file_response,
    }
    (manifest_root / f"{token}.json").write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    try:
        resolved_path = str(Path(raw_path).resolve())
    except OSError:
        resolved_path = ""
    if resolved_path:
        _write_preview_file_gateway_reuse_index_entry(
            manifest_root,
            token=token,
            app_id=app_id,
            file_response=file_response,
            asset_path=asset_path,
            resolved_path=resolved_path,
            expires_at=manifest["expires_at"],
        )
    return token


def _reusable_preview_file_gateway_token(
    data_root: Path,
    *,
    app_id: str,
    file_response: dict[str, object],
    asset_path: str,
) -> str:
    raw_path = str(file_response.get("path") or "").strip()
    if not raw_path:
        return ""
    manifest_root = data_root / "run" / "file-gateway"
    try:
        resolved_path = str(Path(raw_path).resolve())
    except OSError:
        return ""
    reuse_key = _preview_file_gateway_reuse_key(
        app_id=app_id,
        file_response=file_response,
        asset_path=asset_path,
        resolved_path=resolved_path,
    )
    now = datetime.now(tz=UTC)
    indexed_token = _read_preview_file_gateway_reuse_index(manifest_root, now=now).get(reuse_key, "")
    if indexed_token:
        manifest = _read_preview_file_gateway_manifest(manifest_root, indexed_token)
        if _preview_file_gateway_manifest_matches(
            manifest,
            app_id=app_id,
            file_response=file_response,
            asset_path=asset_path,
            resolved_path=resolved_path,
            now=now,
        ):
            return indexed_token
    return ""


def _read_preview_file_gateway_manifest(manifest_root: Path, token: str) -> dict[str, object]:
    try:
        payload = json.loads((manifest_root / f"{token}.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_preview_file_gateway_reuse_index(manifest_root: Path, *, now: datetime) -> dict[str, str]:
    return {key: entry["token"] for key, entry in _read_preview_file_gateway_reuse_index_entries(manifest_root, now=now).items()}


def _read_preview_file_gateway_reuse_index_entries(manifest_root: Path, *, now: datetime) -> dict[str, dict[str, str]]:
    try:
        payload = json.loads(_preview_file_gateway_reuse_index_path(manifest_root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("schema") != FILE_GATEWAY_REUSE_INDEX_SCHEMA:
        return {}
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        return {}
    result: dict[str, dict[str, str]] = {}
    for key, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        token = str(entry.get("token") or "")
        expires_at = _parse_gateway_timestamp(entry.get("expires_at"))
        if not token or expires_at is None or expires_at <= now + PREVIEW_FILE_GATEWAY_REUSE_MIN_TTL:
            continue
        result[str(key)] = {"token": token, "expires_at": expires_at.isoformat()}
    return result


def _write_preview_file_gateway_reuse_index_entry(
    manifest_root: Path,
    *,
    token: str,
    app_id: str,
    file_response: dict[str, object],
    asset_path: str,
    resolved_path: str,
    expires_at: object,
) -> None:
    now = datetime.now(tz=UTC)
    reuse_key = _preview_file_gateway_reuse_key(
        app_id=app_id,
        file_response=file_response,
        asset_path=asset_path,
        resolved_path=resolved_path,
    )
    entries = _read_preview_file_gateway_reuse_index_entries(manifest_root, now=now)
    entries[reuse_key] = {"token": token, "expires_at": str(expires_at or "")}
    payload = {"schema": FILE_GATEWAY_REUSE_INDEX_SCHEMA, "updated_at": now.isoformat(), "entries": entries}
    try:
        path = _preview_file_gateway_reuse_index_path(manifest_root)
        temp_path = path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        temp_path.replace(path)
    except OSError:
        return


def _preview_file_gateway_reuse_index_path(manifest_root: Path) -> Path:
    return manifest_root / "reuse-index.json"


def _preview_file_gateway_reuse_key(
    *,
    app_id: str,
    file_response: dict[str, object],
    asset_path: str,
    resolved_path: str,
) -> str:
    payload = {
        "schema": FILE_GATEWAY_REUSE_INDEX_SCHEMA,
        "app_id": app_id,
        "asset_path": asset_path,
        "resolved_path": resolved_path,
        "content_type": str(file_response.get("content_type") or ""),
        "etag": str(file_response.get("etag") or ""),
        "cache_control": str(file_response.get("cache_control") or ""),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _preview_file_gateway_manifest_matches(
    manifest: object,
    *,
    app_id: str,
    file_response: dict[str, object],
    asset_path: str,
    resolved_path: str,
    now: datetime,
) -> bool:
    if not isinstance(manifest, dict):
        return False
    if str(manifest.get("schema") or "") != FILE_GATEWAY_SCHEMA:
        return False
    if str(manifest.get("app_id") or "") != app_id:
        return False
    if str(manifest.get("access") or "") != "public_capability":
        return False
    expires_at = _parse_gateway_timestamp(manifest.get("expires_at"))
    if expires_at is None or expires_at <= now + PREVIEW_FILE_GATEWAY_REUSE_MIN_TTL:
        return False
    manifest_response = manifest.get("file_response")
    if not isinstance(manifest_response, dict):
        return False
    try:
        manifest_path = str(Path(str(manifest_response.get("path") or "")).resolve())
        allowed_paths = {str(Path(str(path)).resolve()) for path in manifest.get("allowed_paths") or []}
    except (OSError, TypeError, ValueError):
        return False
    if manifest_path != resolved_path or resolved_path not in allowed_paths:
        return False
    comparable_fields = ("content_type", "etag", "cache_control")
    if any(str(manifest_response.get(field) or "") != str(file_response.get(field) or "") for field in comparable_fields):
        return False
    manifest_asset_path = str(manifest.get("asset_path") or "").strip()
    return not manifest_asset_path or manifest_asset_path == asset_path


def _parse_gateway_timestamp(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _preview_document_payload(data_root: Path, preview: dict[str, object], html: str, *, include_inventory: object = False) -> dict[str, object]:
    gateway_urls: dict[str, str] = {}
    source_map = _preview_source_map(data_root, preview, html, include_inventory=include_inventory)
    html = _replace_preview_media_urls_with_gateway(data_root, preview, html, gateway_urls=gateway_urls)
    asset_gateway, unresolved = _preview_asset_gateway_map(data_root, preview, source_map, gateway_urls=gateway_urls)
    source_map["asset_gateway"] = asset_gateway
    source_map["asset_gateway_unresolved"] = unresolved
    return {
        "preview": preview,
        "html": html,
        "source_map": source_map,
        "observability": {
            "browser_report_event": "maverick.website-studio.preview-report",
            "browser_report_global": "__WEBSITE_STUDIO_PREVIEW_REPORT__",
            "covers": ["dom_snapshot", "computed_styles", "font_readiness", "asset_coverage", "console_log", "resource_log"],
        },
    }


def _preview_asset_gateway_map(
    data_root: Path,
    preview: dict[str, object],
    source_map: dict[str, object],
    *,
    gateway_urls: dict[str, str],
) -> tuple[dict[str, str], list[str]]:
    candidates = _preview_gateway_candidate_paths(data_root, preview, source_map)
    unresolved: list[str] = []
    for raw_path in candidates[:500]:
        try:
            clean_path = safe_preview_asset_path(raw_path)
        except ValueError:
            continue
        if clean_path in gateway_urls:
            continue
        try:
            media_payload = preview_media(data_root, preview["id"], clean_path)
            _preview_file_gateway_url(
                data_root,
                preview,
                file_response=dict(media_payload.get("file_response") or {}),
                asset_path=str(media_payload.get("path") or clean_path),
                aliases=[clean_path],
                gateway_urls=gateway_urls,
            )
        except (OSError, ValueError):
            if clean_path not in unresolved:
                unresolved.append(clean_path)
            continue
    return dict(sorted(gateway_urls.items())), unresolved


def _preview_gateway_candidate_paths(data_root: Path, preview: dict[str, object], source_map: dict[str, object]) -> list[str]:
    candidates = [str(item) for item in source_map.get("asset_refs", []) if _preview_gateway_asset_path_allowed(item)]
    try:
        clean_site_id = str(preview.get("site_id") or "")
        with connect(data_root) as db:
            rows = db.execute(
                """
                SELECT path FROM assets
                WHERE site_id = ?
                  AND deleted_at IS NULL
                  AND kind IN ('image', 'stylesheet', 'script', 'font', 'video', 'audio')
                ORDER BY path
                LIMIT 500
                """,
                (clean_site_id,),
            ).fetchall()
        candidates.extend(str(row["path"]) for row in rows)
    except Exception:
        pass
    return _dedupe_strings(candidates)


def _preview_gateway_asset_path_allowed(path: object) -> bool:
    try:
        clean = safe_preview_asset_path(path)
    except ValueError:
        return False
    return _asset_kind(Path(clean)) in {"image", "stylesheet", "script", "font", "video", "audio"}


def _preview_source_map(data_root: Path, preview: dict[str, object], html: object, *, include_inventory: object = False) -> dict[str, object]:
    site = get_site(data_root, preview["site_id"])
    source_root = _source_root(data_root, str(site["id"]))
    profile = _cached_source_profile(data_root, site, source_root=source_root)
    map_payload = sitemap(data_root, site["id"])
    route_text = str(preview.get("route") or "/")
    pages = list(map_payload.get("items") or [])
    routes = list(map_payload.get("routes") or [])
    assets = list(map_payload.get("assets") or [])
    page = next((item for item in pages if item.get("id") == preview.get("page_id")), None)
    if page is None:
        page = next((item for item in pages if item.get("route") == route_text), None)
    route_item = next((item for item in routes if item.get("route") == route_text), None)
    raw_source_files = _dedupe_strings(
        list(page.get("source_files") or []) if page else []
        + (list(route_item.get("source_files") or []) if route_item else [])
        + source_files_for_runtime_route(source_root, profile)
    )
    include_source_inventory = _truthy(include_inventory)
    source_files = _source_files_for_visual_context(raw_source_files, include_inventory=include_source_inventory)
    source_texts = _source_text_candidates(data_root, site["id"], source_files)
    media_paths = preview_media_paths_from_html(html)
    asset_refs = _dedupe_strings((list(page.get("asset_refs") or []) if page else []) + media_paths)
    selector_hints = build_selector_hints(
        html,
        source_files=source_files,
        source_texts=source_texts,
        asset_records=assets,
    )
    rendered_count = sum(1 for item in routes if item.get("status") in {"rendered", "draft", "active"})
    failed_count = sum(1 for item in routes if item.get("status") in {"failed", "broken", "blocked"})
    return {
        "site_id": site["id"],
        "preview_id": preview["id"],
        "route": route_text,
        "route_id": route_item.get("id") if route_item else "",
        "page_id": page.get("id") if page else "",
        "source_files": source_files[:20],
        "route_source_files": _source_files_for_visual_context(route_item.get("source_files", []) if route_item else [], include_inventory=include_source_inventory),
        "asset_refs": asset_refs[:200],
        "asset_summary": _asset_inventory_summary(assets),
        "asset_index": _compact_asset_index(assets, asset_refs, include_inventory=_truthy(include_inventory)),
        "selector_hints": selector_hints,
        "rendered_route_count": rendered_count,
        "failed_route_count": failed_count,
        "limitations": [
            "Element-level source mapping is candidate-based for PHP and built artifacts unless framework compiler metadata is available.",
            "Browser-only checks such as first paint, computed layout, and document.fonts readiness are emitted by the preview runtime probe.",
        ],
    }


def _source_text_candidates(data_root: Path, site_id: object, source_files: list[str]) -> dict[str, str]:
    source_root = _source_root(data_root, str(site_id))
    texts: dict[str, str] = {}
    for rel_path in source_files[:30]:
        try:
            target = resolve_site_path(source_root, rel_path)
            if target.exists() and target.is_file() and target.stat().st_size <= 512 * 1024:
                texts[rel_path] = target.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue
    return texts


def _preview_asset_probe(data_root: Path, preview: dict[str, object], html: object, source_map: dict[str, object]) -> dict[str, object]:
    media_paths = _dedupe_strings(preview_media_paths_from_html(html) + [str(item) for item in source_map.get("asset_refs", []) if str(item).strip()])
    assets = list(sitemap(data_root, preview["site_id"]).get("assets") or [])
    resolved: list[dict[str, object]] = []
    missing: list[str] = []
    errors: list[str] = []
    for media_path in media_paths:
        try:
            target, resolved_rel_path = _resolve_preview_asset_path(data_root, preview, media_path)
            content_type = detect_content_type(target)
            resolved.append(
                {
                    "path": resolved_rel_path,
                    "requested_path": media_path,
                    "kind": asset_kind_for_path(resolved_rel_path, content_type),
                    "content_type": content_type,
                    "size_bytes": target.stat().st_size,
                    "status": "ok",
                }
            )
        except (OSError, ValueError) as error:
            missing.append(media_path)
            errors.append(str(error))
    summary = summarize_asset_probe(assets, media_paths, resolved, missing)
    return {
        **summary,
        "resolved": resolved[:300],
        "missing": missing[:100],
        "errors": errors[:100],
        "status": "passed" if not missing and not errors else "failed",
    }


def _asset_inventory_summary(assets: list[object]) -> dict[str, object]:
    by_kind: dict[str, int] = {}
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        kind = str(asset.get("kind") or "file")
        by_kind[kind] = by_kind.get(kind, 0) + 1
    return {"indexed_asset_count": len(assets), "indexed_by_kind": dict(sorted(by_kind.items()))}


def _compact_asset_index(assets: list[object], asset_refs: list[str], *, include_inventory: bool = False) -> list[dict[str, object]]:
    referenced = set(asset_refs)
    compact: list[dict[str, object]] = []
    seen: set[str] = set()

    def append(asset: object) -> None:
        if len(compact) >= MAX_SOURCE_MAP_ASSET_INDEX:
            return
        if not isinstance(asset, dict):
            return
        path = str(asset.get("path") or "")
        if not path or path in seen:
            return
        seen.add(path)
        compact.append(
            {
                "id": asset.get("id") or "",
                "path": path,
                "kind": asset.get("kind") or "file",
                "content_type": asset.get("content_type") or "",
                "size_bytes": asset.get("size_bytes") or 0,
                "status": asset.get("status") or "",
            }
        )

    for asset in assets:
        path = str(asset.get("path") or "") if isinstance(asset, dict) else ""
        if path in referenced:
            append(asset)
    if include_inventory:
        for asset in assets:
            if len(compact) >= MAX_SOURCE_MAP_ASSET_INDEX:
                break
            append(asset)
    return compact


def _browser_probe_contract(preview: dict[str, object]) -> dict[str, object]:
    return {
        "preview_url": preview.get("preview_url") or "",
        "event_type": "maverick.website-studio.preview-report",
        "window_global": "__WEBSITE_STUDIO_PREVIEW_REPORT__",
        "message_source": "nested opaque-origin preview iframe",
        "checks": [
            "desktop/mobile screenshot nonblank",
            "DOM snapshot",
            "computed styles",
            "network/resource log",
            "console log",
            "document.fonts readiness",
            "image/video/font asset readiness",
        ],
    }


def _record_preview_report(data_root: Path, report: dict[str, object]) -> None:
    with connect(data_root) as db:
        db.execute(
            """
            INSERT INTO preview_reports(id, site_id, preview_id, route, status, report_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report["id"],
                report["site_id"],
                report["preview_id"],
                report["route"],
                "passed" if (report.get("acceptance") or {}).get("passed") else "failed",
                json.dumps(report, sort_keys=True),
                report["generated_at"],
            ),
        )


def _preview_report_row(data_root: Path, report_id: object) -> dict[str, object]:
    clean_id = _required_id(report_id, "report_id")
    with connect(data_root) as db:
        row = db.execute("SELECT * FROM preview_reports WHERE id = ?", (clean_id,)).fetchone()
    if row is None:
        raise ValueError(f"preview report `{clean_id}` was not found")
    payload = dict(row)
    payload["report"] = json.loads(payload.pop("report_json") or "{}")
    return payload


def _latest_preview_report(data_root: Path, site_id: object) -> dict[str, object] | None:
    ensure_schema(data_root)
    with connect(data_root) as db:
        row = db.execute(
            "SELECT * FROM preview_reports WHERE site_id = ? ORDER BY created_at DESC LIMIT 1",
            (str(site_id),),
        ).fetchone()
    return _preview_report_row(data_root, row["id"])["report"] if row else None


def _latest_preview_reports_by_route(data_root: Path, site_id: object) -> dict[str, dict[str, object]]:
    ensure_schema(data_root)
    with connect(data_root) as db:
        rows = db.execute(
            """
            SELECT report.*
            FROM preview_reports AS report
            JOIN (
                SELECT route, MAX(created_at) AS latest_created_at
                FROM preview_reports
                WHERE site_id = ?
                GROUP BY route
            ) AS latest
              ON latest.route = report.route
             AND latest.latest_created_at = report.created_at
            WHERE report.site_id = ?
            ORDER BY report.created_at DESC
            """,
            (str(site_id), str(site_id)),
        ).fetchall()
    reports: dict[str, dict[str, object]] = {}
    for row in rows:
        payload = dict(row)
        report = json.loads(payload.pop("report_json") or "{}")
        route = str(report.get("route") or payload.get("route") or "/")
        if route not in reports:
            reports[route] = report
    return reports


def _latest_preview_report_for_route(data_root: Path, site_id: object, route: object) -> dict[str, object] | None:
    row = _latest_route_row(data_root, table="preview_reports", site_id=site_id, route=route)
    if not row:
        return None
    payload = dict(row)
    report = json.loads(payload.pop("report_json") or "{}")
    report.setdefault("id", payload.get("id") or "")
    report.setdefault("site_id", payload.get("site_id") or "")
    report.setdefault("preview_id", payload.get("preview_id") or "")
    report.setdefault("route", payload.get("route") or "/")
    return report


def _preview_report_for_route(reports_by_route: dict[str, dict[str, object]], route: str) -> dict[str, object]:
    if route in reports_by_route:
        return reports_by_route[route]
    route_key = _visual_route_key(route)
    for report_route, report in reports_by_route.items():
        if _visual_route_key(report_route) == route_key:
            return report
    return {}


def _canonical_visual_pages(
    pages: list[dict[str, object]],
    *,
    runtime_kind: str,
    reports_by_route: dict[str, dict[str, object]],
    site_label: str,
) -> list[tuple[dict[str, object], list[str]]]:
    selected: dict[str, dict[str, object]] = {}
    aliases: dict[str, list[str]] = {}
    for page in pages:
        route = str(page.get("route") or "/")
        key = _visual_page_identity_key(page, route, site_label=site_label)
        aliases.setdefault(key, [])
        if route not in aliases[key]:
            aliases[key].append(route)
        current = selected.get(key)
        if current is None or _visual_page_rank(page, runtime_kind=runtime_kind, reports_by_route=reports_by_route) > _visual_page_rank(
            current,
            runtime_kind=runtime_kind,
            reports_by_route=reports_by_route,
        ):
            selected[key] = page
    entries = [(page, [alias for alias in aliases.get(key, []) if alias != str(page.get("route") or "/")]) for key, page in selected.items()]
    return sorted(entries, key=lambda item: _visual_route_sort_key(str(item[0].get("route") or "/")))


def _visual_page_identity_key(page: dict[str, object], route: str, *, site_label: str) -> str:
    route_key = _visual_route_key(route)
    if route_key == "/":
        return "route:/"
    label_key = _identity_slug(_visual_page_label(page, route, site_label=site_label))
    route_stem_key = _identity_slug(PurePosixPath(route_key).name or route_key)
    if label_key and route_stem_key and (label_key == route_stem_key or label_key.endswith(route_stem_key)):
        return f"page:{label_key}"
    if label_key in {"cookiepolicy", "privacypolicy", "terminiecondizioni", "termsandconditions"}:
        return f"page:{label_key}"
    return f"route:{route_key}"


def _visual_page_rank(page: dict[str, object], *, runtime_kind: str, reports_by_route: dict[str, dict[str, object]]) -> int:
    route = str(page.get("route") or "/")
    lower = route.lower()
    score = 0
    if route == "/":
        score += 1000
    if _preview_report_for_route(reports_by_route, route):
        score += 200
    if runtime_kind == "php" and lower.endswith(".php"):
        score += 80
    if lower.endswith((".html", ".htm")):
        score += 40
    if _visual_source_files(page.get("source_files", [])):
        score += 20
    if _navigation_compact(page.get("title"), 160) and not _navigation_compact(page.get("title"), 160).startswith("/"):
        score += 10
    return score


def _visual_route_key(route: str) -> str:
    parsed = urlparse(route or "/")
    path = parsed.path or "/"
    if not path.startswith("/"):
        path = f"/{path}"
    path = re.sub(r"/+", "/", path)
    lower = path.lower()
    if lower in {"/", "/index", "/index.html", "/index.htm", "/index.php"}:
        return "/"
    suffix = PurePosixPath(lower).suffix
    if suffix in {".html", ".htm", ".php"}:
        path = path[: -len(suffix)]
    return path.rstrip("/") or "/"


def _visual_route_sort_key(route: str) -> tuple[int, str]:
    key = _visual_route_key(route)
    return (0 if key == "/" else 1, key)


def _visual_page_label(page: dict[str, object], route: str, *, site_label: str) -> str:
    route_key = _visual_route_key(route)
    if route_key == "/":
        return "Home"
    raw_title = _navigation_compact(page.get("title"), 160)
    if raw_title and not raw_title.startswith("/"):
        title = raw_title.split("|", 1)[0].strip()
        if title and _identity_slug(title) != _identity_slug(site_label):
            return title[:90]
    return _route_label(route)


def _route_label(route: str) -> str:
    key = _visual_route_key(route)
    if key == "/":
        return "Home"
    name = PurePosixPath(key).name or key.strip("/")
    text = re.sub(r"[_-]+", " ", name).strip()
    return text[:1].upper() + text[1:] if text else key


def _identity_slug(value: str) -> str:
    stopwords = {"a", "and", "e", "i", "il", "la", "le", "lo", "the"}
    words = [word for word in re.findall(r"[a-z0-9]+", value.lower()) if word not in stopwords]
    return "".join(words)


def _navigation_compact(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _visual_sections_for_page(
    data_root: Path,
    site_id: object,
    page: dict[str, object],
    *,
    source_map: dict[str, object] | None = None,
    report_id: str = "",
) -> list[dict[str, object]]:
    source_map = source_map or {}
    source_files = _visual_source_files(page.get("source_files", [])) or _visual_source_files(source_map.get("source_files", []))
    source_root = _source_root(data_root, str(site_id))
    sections: list[dict[str, object]] = []
    for rel_path in source_files[:5]:
        if not rel_path.lower().endswith((".html", ".htm")):
            continue
        try:
            target = resolve_site_path(source_root, rel_path)
            if not target.is_file() or target.stat().st_size > 1024 * 1024:
                continue
            html = read_text_file(target)
        except (OSError, ValueError):
            continue
        sections.extend(
            visual_sections_from_html(
                html,
                route=str(page.get("route") or "/"),
                page_id=str(page.get("id") or ""),
                source_files=source_files,
                last_report_id=report_id,
            )
        )
        if len(sections) >= 32:
            break
    sections.extend(
        visual_sections_from_selector_hints(
            source_map.get("selector_hints") if isinstance(source_map, dict) else [],
            route=str(page.get("route") or "/"),
            page_id=str(page.get("id") or ""),
            source_files=source_files,
            last_report_id=report_id,
            limit=32,
        )
    )
    return _unique_visual_navigation_items(sections)[:32]


def _unique_visual_navigation_items(items: list[dict[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in items:
        selector = str(item.get("selector") or "")
        anchor = str(item.get("anchor") or "")
        label = str(item.get("label") or "")
        key = f"{item.get('kind') or ''}:{selector}:{anchor}:{_identity_slug(label)}"
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _source_file_values(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return _dedupe_strings([str(item or "").strip() for item in value if str(item or "").strip()])


def _visual_source_files(value: object) -> list[str]:
    return [path for path in _source_file_values(value) if not _is_hidden_source_inventory_file(path)][:20]


def _source_files_for_visual_context(value: object, *, include_inventory: bool = False, limit: int = 20) -> list[str]:
    files = _source_file_values(value)
    if include_inventory:
        return files[:limit]
    return _visual_source_files(files)[:limit]


def _is_hidden_source_inventory_file(path: str) -> bool:
    clean = path.strip().lstrip("/")
    lower = clean.lower()
    name = lower.rsplit("/", 1)[-1]
    if not clean:
        return True
    if lower.startswith(("backend-admin/", "admin/", "wp-admin/", ".git/", "node_modules/", "vendor/")):
        return True
    package_files = {
        ".gitignore",
        ".htaccess",
        ".npmrc",
        ".nvmrc",
        ".yarnrc",
        "bun.lockb",
        "composer.json",
        "composer.lock",
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "readme.md",
        "yarn.lock",
    }
    if name in package_files:
        return True
    config_prefixes = (
        "astro.config",
        "babel.config",
        "eslint.config",
        "esbuild.config",
        "next.config",
        "nuxt.config",
        "postcss.config",
        "prettier.config",
        "rollup.config",
        "stylelint.config",
        "svelte.config",
        "tailwind.config",
        "vite.config",
        "webpack.config",
    )
    if any(name == prefix or name.startswith(f"{prefix}.") for prefix in config_prefixes):
        return True
    if name in {"jsconfig.json", "tsconfig.json"} or name.startswith(("jsconfig.", "tsconfig.")):
        return True
    if name.startswith(("gulpfile.", "gruntfile.")):
        return True
    if name.endswith((".lock", ".log", ".env")):
        return True
    return False


def _navigation_analysis_coverage(pages: list[dict[str, object]], routes: list[dict[str, object]]) -> dict[str, object]:
    page_entries = [_coverage_entry(item, default_kind="page") for item in pages]
    route_entries = [_coverage_entry(item, default_kind="route") for item in routes]
    pages_without_report = [item for item in page_entries if not item["preview_report_id"]]
    routes_without_report = [item for item in route_entries if not item["preview_report_id"]]
    return {
        "visual_page_count": len(page_entries),
        "observed_page_count": len(page_entries) - len(pages_without_report),
        "pages_without_report_count": len(pages_without_report),
        "pages_without_report": pages_without_report[:50],
        "visual_route_count": len(route_entries),
        "observed_route_count": len(route_entries) - len(routes_without_report),
        "routes_without_report_count": len(routes_without_report),
        "routes_to_analyze": (pages_without_report + routes_without_report)[:50],
        "complete": not pages_without_report and not routes_without_report,
    }


def _coverage_entry(item: dict[str, object], *, default_kind: str) -> dict[str, object]:
    return {
        "id": item.get("id") or "",
        "kind": item.get("kind") or default_kind,
        "route": item.get("route") or "",
        "page_id": item.get("id") if default_kind == "page" else item.get("page_id") or "",
        "route_id": item.get("route_id") if default_kind == "page" else item.get("id") or "",
        "label": item.get("label") or item.get("title") or item.get("route") or "",
        "preview_report_id": item.get("preview_report_id") or "",
    }


def _analysis_coverage_warnings(analysis_coverage: dict[str, object]) -> list[dict[str, object]]:
    missing = list(analysis_coverage.get("routes_to_analyze") or [])
    if not missing:
        return []
    routes = [str(item.get("route") or "").strip() for item in missing if isinstance(item, dict) and str(item.get("route") or "").strip()]
    sample = ", ".join(routes[:5])
    suffix = f": {sample}" if sample else ""
    return [
        {
            "scope": "analysis_coverage",
            "route": "",
            "message": f"{len(missing)} visual route(s) are missing preview reports{suffix}",
        }
    ]


def _components_from_report(source_map: dict[str, object], *, route: str, page_id: str, report_id: str) -> list[dict[str, object]]:
    components = component_candidates_from_selector_hints(
        source_map.get("selector_hints") if isinstance(source_map, dict) else [],
        route=route or "/",
        page_id=page_id,
        last_report_id=report_id,
    )
    for component in components:
        component["source_files"] = _visual_source_files(component.get("source_files", []))
    return components


def _source_files_changed(source_files: list[str], changed_paths: set[str]) -> bool:
    return any(path in changed_paths for path in source_files)


def _route_is_visual(route: dict[str, object]) -> bool:
    status = str(route.get("status") or "").strip()
    kind = str(route.get("kind") or "").strip()
    return status in {"rendered", "ready", "draft", "active", "static_fallback"} and kind not in {"redirect", "sitemap"}


def _navigation_warnings(
    pages: list[dict[str, object]],
    routes: list[dict[str, object]],
    runtime: dict[str, object],
    *,
    analysis_coverage: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    warnings: list[dict[str, object]] = []
    for item in pages + routes:
        for warning in item.get("warnings", []) or []:
            text = str(warning or "").strip()
            if text:
                warnings.append({"scope": item.get("kind") or "page", "route": item.get("route") or "", "message": text})
    for requirement in runtime.get("missing_requirements", []) or []:
        text = str(requirement or "").strip()
        if text:
            warnings.append({"scope": "runtime", "route": "", "message": text})
    if analysis_coverage:
        warnings.extend(_analysis_coverage_warnings(analysis_coverage))
    return warnings[:100]


def _navigation_target_for_site(
    data_root: Path,
    site_id: object,
    *,
    component_id: str = "",
    selector: str = "",
    anchor: str = "",
    route: str = "",
) -> dict[str, object] | None:
    navigation = navigation_analyze(data_root, site_id)
    candidates: list[dict[str, object]] = []
    for page in navigation.get("pages", []) or []:
        if not isinstance(page, dict):
            continue
        candidates.extend(item for item in page.get("sections", []) or [] if isinstance(item, dict))
        candidates.extend(item for item in page.get("anchors", []) or [] if isinstance(item, dict))
        candidates.extend(item for item in page.get("components", []) or [] if isinstance(item, dict))
    for visual_route in navigation.get("routes", []) or []:
        if isinstance(visual_route, dict):
            candidates.extend(item for item in visual_route.get("components", []) or [] if isinstance(item, dict))
    for item in candidates:
        if route and str(item.get("route") or "") != route:
            continue
        if component_id and str(item.get("id") or "") == component_id:
            return item
        if selector and str(item.get("selector") or "") == selector:
            return item
        if anchor and str(item.get("anchor") or "") == anchor:
            return item
    return None


def _preview_report_comparison(baseline_row: dict[str, object], report: dict[str, object]) -> dict[str, object]:
    baseline = baseline_row.get("report") if isinstance(baseline_row.get("report"), dict) else {}
    before_acceptance = baseline.get("acceptance") if isinstance(baseline.get("acceptance"), dict) else {}
    after_acceptance = report.get("acceptance") if isinstance(report.get("acceptance"), dict) else {}
    before_assets = baseline.get("asset_coverage") if isinstance(baseline.get("asset_coverage"), dict) else {}
    after_assets = report.get("asset_coverage") if isinstance(report.get("asset_coverage"), dict) else {}
    return {
        "baseline_report_id": baseline.get("id") or baseline_row.get("id") or "",
        "acceptance_changed": before_acceptance.get("passed") != after_acceptance.get("passed"),
        "missing_asset_delta": int(after_assets.get("missing_count") or 0) - int(before_assets.get("missing_count") or 0),
        "resolved_asset_delta": int(after_assets.get("resolved_count") or 0) - int(before_assets.get("resolved_count") or 0),
        "runtime_status_before": baseline.get("runtime_status") or "",
        "runtime_status_after": report.get("runtime_status") or "",
    }


def _preview_stylesheet_loader(data_root: Path, preview: dict[str, object]):
    preview_id = str(preview.get("id") or preview.get("preview_id") or "")

    def load(asset_path: str) -> tuple[str, str] | None:
        target, resolved_rel_path = _resolve_preview_asset_path(data_root, preview, safe_preview_asset_path(asset_path))
        if target.suffix.lower() != ".css" or target.stat().st_size > 2 * 1024 * 1024:
            return None
        css = target.read_text(encoding="utf-8", errors="replace")
        rewritten = rewrite_preview_css(css, preview_id=preview_id, css_path=resolved_rel_path, with_origin_placeholder=True)
        return rewritten, resolved_rel_path

    return load


def _preview_script_loader(data_root: Path, preview: dict[str, object]):
    inlined_shared_scripts: set[str] = set()

    def load(asset_path: str) -> tuple[str, str] | None:
        target, resolved_rel_path = _resolve_preview_asset_path(data_root, preview, safe_preview_asset_path(asset_path))
        if target.suffix.lower() not in {".js", ".mjs"} or target.stat().st_size > 2 * 1024 * 1024:
            return None
        scripts: list[str] = []
        for dependency, dependency_rel_path in _shared_script_dependencies(target, resolved_rel_path):
            if dependency_rel_path in inlined_shared_scripts:
                continue
            scripts.append(dependency.read_text(encoding="utf-8", errors="replace"))
            inlined_shared_scripts.add(dependency_rel_path)
        scripts.append(target.read_text(encoding="utf-8", errors="replace"))
        script = "\n".join(scripts)
        return script, resolved_rel_path

    return load


def _shared_script_dependencies(target: Path, resolved_rel_path: str) -> list[tuple[Path, str]]:
    if target.suffix.lower() not in {".js", ".mjs"}:
        return []
    parent = target.parent
    if not parent.is_dir():
        return []
    base_dir = PurePosixPath(resolved_rel_path).parent
    candidates: list[tuple[int, str, Path]] = []
    for sibling in parent.iterdir():
        if sibling == target or not sibling.is_file() or sibling.suffix.lower() not in {".js", ".mjs"}:
            continue
        priority = _shared_script_priority(sibling.name)
        if priority is None:
            continue
        candidates.append((priority, sibling.name, sibling))
    return [(path, (base_dir / name).as_posix()) for _priority, name, path in sorted(candidates)]


def _shared_script_priority(name: str) -> int | None:
    lowered = name.lower()
    if lowered.startswith(("runtime", "manifest")) or ".runtime." in lowered or ".manifest." in lowered:
        return 0
    if lowered.startswith(("vendor", "vendors")) or ".vendor." in lowered or ".vendors." in lowered:
        return 1
    if lowered.startswith(("common", "commons")) or ".common." in lowered or ".commons." in lowered:
        return 2
    return None


def _resolve_preview_asset_path(data_root: Path, preview: dict[str, object], rel_path: str) -> tuple[Path, str]:
    site = get_site(data_root, preview["site_id"])
    source_root = _source_root(data_root, str(site["id"])).resolve()
    artifact_ref = preview.get("artifact_ref") if isinstance(preview.get("artifact_ref"), dict) else {}
    runtime_root = _preview_artifact_root(data_root, artifact_ref) or source_root
    runtime_root = runtime_root.resolve()
    profile = _cached_source_profile(data_root, site, source_root=source_root)
    docroot_rel = str(artifact_ref.get("docroot") or profile.get("php_docroot") or "").strip()
    docroot = (runtime_root / docroot_rel).resolve() if docroot_rel and docroot_rel != "." else runtime_root
    roots = [docroot, runtime_root, source_root]
    for alias in _preview_asset_aliases(rel_path, docroot_rel=docroot_rel):
        for root in roots:
            target = (root / alias).resolve()
            if _path_is_within(target, root) and target.is_file():
                return target, alias
    raise ValueError(f"preview asset `{rel_path}` was not found")


def _preview_artifact_root(data_root: Path, artifact_ref: dict[str, object]) -> Path | None:
    rel = str(artifact_ref.get("runtime_root") or "").strip()
    if not rel:
        return None
    root = (data_root / rel).resolve()
    allowed = data_root.resolve()
    if not _path_is_within(root, allowed):
        raise ValueError("runtime artifact root escaped the Website Studio data root")
    return root if root.exists() else None


def _preview_asset_aliases(rel_path: str, *, docroot_rel: str = "") -> list[str]:
    aliases: list[str] = []

    def add(value: str) -> None:
        try:
            clean = safe_relative_path(value)
        except ValueError:
            return
        if clean not in aliases:
            aliases.append(clean)

    add(rel_path)
    if docroot_rel and docroot_rel != "." and rel_path.startswith(f"{docroot_rel}/"):
        add(rel_path.removeprefix(f"{docroot_rel}/"))
    if rel_path.startswith("fonts/"):
        add(f"assets/{rel_path}")
    if rel_path.startswith("images/"):
        add(f"assets/{rel_path}")
    for prefix in ("assets/css/images/", "css/images/", "dist/css/images/"):
        if rel_path.startswith(prefix):
            add("assets/images/" + rel_path.removeprefix(prefix))
    return aliases


def _write_preview_css_cache(data_root: Path, preview_id: object, source_rel_path: str, css: str) -> Path:
    digest = sha256_text(str(preview_id) + "\0" + source_rel_path + "\0" + css)
    path = data_root / "run" / "preview-media" / str(preview_id) / f"{digest[:24]}.css"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(css, encoding="utf-8")
    return path


def _file_etag(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_mtime_ns:x}-{stat.st_size:x}"


def _path_is_within(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    resolved_root = root.resolve()
    return resolved == resolved_root or resolved_root in resolved.parents


def get_preview(data_root: Path, preview_id: object) -> dict[str, object]:
    clean_id = _required_id(preview_id, "preview_id")
    ensure_schema(data_root)
    with connect(data_root) as db:
        row = db.execute("SELECT * FROM previews WHERE id = ?", (clean_id,)).fetchone()
    if row is None:
        raise ValueError(f"preview `{clean_id}` was not found")
    return _preview_row(row)


def create_publish_request(
    data_root: Path,
    site_id: object,
    requested_by: object = "workspace",
    *,
    environment_id: object = None,
) -> dict[str, object]:
    site = get_site(data_root, site_id)
    diff_payload = diff_site(data_root, site_id)
    if not diff_payload["files"]:
        raise ValueError("publish_request requires at least one working file change")
    environment = get_environment(data_root, environment_id or site.get("default_environment_id") or "env_preview", site_id=site["id"])
    build = validate_build(data_root, site["id"])
    if build["status"] != "passed":
        raise ValueError("publish_request requires a passing static build validation")
    now = now_timestamp()
    request_id = f"pub_{uuid4().hex[:16]}"
    summary = f"{len(diff_payload['files'])} changed files"
    changeset = _upsert_changeset(data_root, site["id"], summary)
    with connect(data_root) as db:
        db.execute(
            """
            INSERT INTO publish_requests(id, site_id, changeset_id, status, diff_summary, requested_by, environment_id, build_id, created_at, updated_at)
            VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
            """,
            (request_id, site["id"], changeset["id"], summary, str(requested_by or "workspace"), environment["id"], build["id"], now, now),
        )
    _audit(data_root, str(site["id"]), "publish.requested", summary, {"publish_request_id": request_id, "build_id": build["id"]})
    return get_publish_request(data_root, request_id)


def list_changes(
    data_root: Path,
    site_id: object,
    status: object = None,
    *,
    limit: object = None,
    offset: object = 0,
    include_logs: object = False,
    diff_limit: object = None,
) -> dict[str, object]:
    site = get_site(data_root, site_id)
    status_filter = str(status or "").strip()
    clean_limit = _bounded_int(limit, default=DEFAULT_HISTORY_LIMIT, minimum=1, maximum=MAX_HISTORY_LIMIT)
    clean_offset = _bounded_int(offset, default=0, minimum=0, maximum=1_000_000)
    clean_diff_limit = _bounded_int(diff_limit, default=DEFAULT_WORKING_DIFF_LIMIT, minimum=1, maximum=MAX_WORKING_DIFF_LIMIT)
    include_full_logs = _truthy(include_logs)
    ensure_schema(data_root)
    with connect(data_root) as db:
        if status_filter:
            changeset_rows = _paged_rows(
                db,
                "SELECT * FROM changesets WHERE site_id = ? AND status = ? ORDER BY updated_at DESC",
                (site["id"], status_filter),
                limit=clean_limit,
                offset=clean_offset,
            )
            request_rows = _paged_rows(
                db,
                "SELECT * FROM publish_requests WHERE site_id = ? AND status = ? ORDER BY updated_at DESC",
                (site["id"], status_filter),
                limit=clean_limit,
                offset=clean_offset,
            )
        else:
            changeset_rows = _paged_rows(
                db,
                "SELECT * FROM changesets WHERE site_id = ? ORDER BY updated_at DESC",
                (site["id"],),
                limit=clean_limit,
                offset=clean_offset,
            )
            request_rows = _paged_rows(
                db,
                "SELECT * FROM publish_requests WHERE site_id = ? ORDER BY updated_at DESC",
                (site["id"],),
                limit=clean_limit,
                offset=clean_offset,
            )
        revision_rows = _paged_rows(
            db,
            "SELECT id, site_id, label, source, summary, created_at FROM revisions WHERE site_id = ? ORDER BY created_at DESC",
            (site["id"],),
            limit=clean_limit,
            offset=clean_offset,
        )
        approval_rows = _paged_rows(
            db,
            "SELECT * FROM approval_events WHERE site_id = ? ORDER BY created_at DESC",
            (site["id"],),
            limit=clean_limit,
            offset=clean_offset,
        )
        build_rows = _paged_rows(
            db,
            "SELECT * FROM builds WHERE site_id = ? ORDER BY created_at DESC",
            (site["id"],),
            limit=clean_limit,
            offset=clean_offset,
        )
        sync_rows = _paged_rows(
            db,
            "SELECT * FROM sync_runs WHERE site_id = ? ORDER BY created_at DESC",
            (site["id"],),
            limit=clean_limit,
            offset=clean_offset,
        )
        deployment_rows = _paged_rows(
            db,
            "SELECT * FROM deployments WHERE site_id = ? ORDER BY created_at DESC",
            (site["id"],),
            limit=clean_limit,
            offset=clean_offset,
        )
    diff_payload = diff_site(data_root, site["id"])
    diff_files = diff_payload["files"][:clean_diff_limit]
    return {
        "site_id": site["id"],
        "base_revision_id": site.get("active_revision_id"),
        "published_revision_id": site.get("published_revision_id"),
        "working_diff": [{"path": item["path"], "status": item["status"]} for item in diff_files],
        "working_diff_count": len(diff_payload["files"]),
        "working_diff_truncated": len(diff_payload["files"]) > len(diff_files),
        "changesets": [dict(row) for row in changeset_rows["rows"]],
        "publish_requests": [dict(row) for row in request_rows["rows"]],
        "revisions": [dict(row) for row in revision_rows["rows"]],
        "approval_events": [_approval_row(row) for row in approval_rows["rows"]],
        "builds": [_build_row(row, include_logs=include_full_logs) for row in build_rows["rows"]],
        "sync_runs": [_sync_run_row(row, include_logs=include_full_logs) for row in sync_rows["rows"]],
        "deployments": [_deployment_row(row) for row in deployment_rows["rows"]],
        "pagination": {
            "limit": clean_limit,
            "offset": clean_offset,
            "include_logs": include_full_logs,
            "sections": {
                "changesets": changeset_rows["pagination"],
                "publish_requests": request_rows["pagination"],
                "revisions": revision_rows["pagination"],
                "approval_events": approval_rows["pagination"],
                "builds": build_rows["pagination"],
                "sync_runs": sync_rows["pagination"],
                "deployments": deployment_rows["pagination"],
            },
        },
    }


def publish(
    data_root: Path,
    site_id: object,
    publish_request_id: object = None,
    approval_id: object = None,
    *,
    app_secrets: dict[str, object] | None = None,
    app_secret_errors: list[dict[str, object]] | None = None,
    github_transport: object = None,
) -> dict[str, object]:
    site = get_site(data_root, site_id)
    request = get_publish_request(data_root, publish_request_id) if publish_request_id else None
    if not request:
        return {"blocked": True, "status": "blocked", "detail": "Publishing requires a publish_request_id and a verified approval from the official approval surface."}
    if request["site_id"] != str(site["id"]):
        raise ValueError("publish request does not belong to the selected site")
    if request["status"] not in {"pending", "approved"}:
        raise ValueError(f"publish request `{request['id']}` is already {request['status']}")
    if not approval_id:
        return {"blocked": True, "status": "blocked", "detail": "Publishing requires a verified human approval.", "publish_request": request}
    build = get_build(data_root, request.get("build_id")) if request.get("build_id") else validate_build(data_root, site["id"])
    if build["status"] != "passed":
        raise ValueError("publish requires a passing build validation")
    environment = get_environment(data_root, request.get("environment_id") or site.get("default_environment_id") or "env_preview", site_id=site["id"])
    publish_target = _publish_target_for_environment(data_root, site, environment)
    use_github_publish = _should_publish_to_github(site, publish_target)
    github_context = (
        _github_publish_context(
            data_root,
            site,
            app_secrets=app_secrets or {},
            app_secret_errors=app_secret_errors or [],
        )
        if use_github_publish
        else {}
    )
    if github_context.get("blocked"):
        return {"blocked": True, "status": "blocked", "detail": str(github_context["detail"]), "publish_request": request, "build": build}
    try:
        approval = _consume_approval(data_root, site["id"], "publish", request["id"], approval_id)
    except ValueError as error:
        return {"blocked": True, "status": "blocked", "detail": f"{error}; use the official approval surface before publishing.", "publish_request": request}
    with _site_mutation_lock(data_root, str(site["id"])):
        source_ref = _publish_source_ref(site, request, publish_target=publish_target)
        if github_context:
            try:
                source_ref = publish_to_github_pull_request(
                    source_root=_source_root(data_root, str(site["id"])),
                    diff_files=diff_site(data_root, site["id"]).get("files", []),
                    site=site,
                    request=request,
                    connection=github_context["connection"],
                    token=str(github_context["token"]),
                    transport=github_transport if callable(github_transport) else None,
                )
            except GitHubPublishConflict as error:
                return {"blocked": True, "status": "blocked_github_branch_conflict", "detail": str(error), "publish_request": request, "build": build}
        revision = create_revision(data_root, site["id"], label="Published working copy", source="publish", summary=request["diff_summary"])
        _set_active_revision(data_root, site["id"], revision["id"])
        _update_site(data_root, site["id"], published_revision_id=revision["id"])
        if not github_context:
            source_ref = _publish_to_managed_static_artifact(data_root, site, request, revision, environment, publish_target)
        deployment = _create_deployment(
            data_root,
            site["id"],
            environment_id=str(environment["id"]),
            publish_request_id=request["id"],
            revision_id=revision["id"],
            status="published",
            mode=_publish_mode(source_ref),
            source_ref=source_ref,
        )
        now = now_timestamp()
        with connect(data_root) as db:
            db.execute(
                "UPDATE publish_requests SET status = 'published', approved_by = ?, approval_id = ?, updated_at = ? WHERE id = ?",
                (approval["approved_by"], approval["id"], now, request["id"]),
            )
            db.execute(
                "UPDATE changesets SET status = 'published', updated_at = ? WHERE id = ?",
                (now, request["changeset_id"]),
            )
    _audit(data_root, str(site["id"]), "publish.completed", request["diff_summary"], {"publish_request_id": request["id"], "deployment_id": deployment["id"]})
    return {
        "status": "published",
        "blocked": False,
        "publish_request": get_publish_request(data_root, request["id"]),
        "approval": approval,
        "build": build,
        "revision": revision,
        "deployment": deployment,
    }


def rollback(data_root: Path, site_id: object, revision_id: object, *, approval_id: object = None, confirm: object = False) -> dict[str, object]:
    if not approval_id or confirm is not True:
        return {
            "blocked": True,
            "status": "blocked",
            "detail": "Rollback requires approval_id and confirm=true because it replaces the selected working source tree.",
        }
    site = get_site(data_root, site_id)
    revision = get_revision(data_root, revision_id)
    if revision["site_id"] != site["id"]:
        raise ValueError("revision does not belong to the selected site")
    try:
        approval = _consume_approval(data_root, site["id"], "rollback", revision["id"], approval_id)
    except ValueError as error:
        return {"blocked": True, "status": "blocked", "detail": f"{error}; use the official approval surface before rollback.", "restored_revision": revision}
    with _site_mutation_lock(data_root, str(site["id"])):
        replace_tree_from_directory(_source_root(data_root, str(site["id"])), _revision_source_root(data_root, str(site["id"]), str(revision["id"])))
        rebuild_index(data_root, site["id"])
        rollback_revision = create_revision(data_root, site["id"], label=f"Rollback to {revision['id']}", source="rollback", summary=f"Restored revision {revision['id']}")
        _set_active_revision(data_root, site["id"], rollback_revision["id"])
        _update_site(data_root, site["id"], published_revision_id=rollback_revision["id"])
        deployment = _create_deployment(
            data_root,
            site["id"],
            environment_id=str(site.get("default_environment_id") or "env_preview"),
            publish_request_id="",
            revision_id=rollback_revision["id"],
            status="rolled_back",
            mode="rollback",
            source_ref={"restored_revision_id": str(revision["id"])},
        )
    _audit(data_root, str(site["id"]), "rollback.completed", f"Rolled back to {revision['id']}", {"deployment_id": deployment["id"]})
    return {
        "status": "rolled_back",
        "blocked": False,
        "approval": approval,
        "restored_revision": revision,
        "revision": rollback_revision,
        "deployment": deployment,
    }


def active_context(data_root: Path, site_id: object = None, page_id: object = None) -> dict[str, object]:
    site = _select_context_site(data_root, site_id)
    if not site:
        return {"active_view": "empty", "site_id": None}
    map_payload = sitemap(data_root, site["id"])
    pages = map_payload["items"]
    page = next((item for item in pages if item["id"] == page_id), pages[0] if pages else None)
    route = None
    if page:
        route = next((item for item in map_payload.get("routes", []) if item.get("page_id") == page["id"]), None)
    diff_payload = diff_site(data_root, site["id"])
    return _context_payload(data_root, site, page=page, route=route, asset=None, map_payload=map_payload, diff_payload=diff_payload)


def page_context(
    data_root: Path,
    site_id: object = None,
    *,
    page_id: object = None,
    route_id: object = None,
    route: object = None,
    asset_id: object = None,
    component_id: object = None,
    target_selector: object = None,
    target_anchor: object = None,
    include_inventory: object = False,
) -> dict[str, object]:
    site = _select_context_site(data_root, site_id)
    if not site:
        return {"active_view": "empty", "site_id": None}
    map_payload = sitemap(data_root, site["id"])
    pages = map_payload["items"]
    routes = map_payload.get("routes", [])
    assets = map_payload.get("assets", [])
    selected_page = None
    selected_route = None
    selected_asset = None
    selected_component = None
    clean_asset_id = str(asset_id or "").strip()
    if clean_asset_id:
        selected_asset = next((item for item in assets if item["id"] == clean_asset_id), None)
    clean_route_id = str(route_id or "").strip()
    clean_route = str(route or "").strip()
    if clean_route_id:
        selected_route = next((item for item in routes if item["id"] == clean_route_id), None)
    if selected_route is None and clean_route:
        selected_route = next((item for item in routes if item["route"] == clean_route), None)
    if selected_route is None and clean_route:
        clean_route_key = _visual_route_key(clean_route)
        selected_route = next((item for item in routes if _visual_route_key(str(item.get("route") or "/")) == clean_route_key), None)
    clean_page_id = str(page_id or "").strip()
    if clean_page_id:
        selected_page = next((item for item in pages if item["id"] == clean_page_id), None)
    clean_component_id = str(component_id or "").strip()
    clean_selector = str(target_selector or "").strip()
    clean_anchor = str(target_anchor or "").strip()
    if clean_component_id or clean_selector or clean_anchor:
        selected_component = _navigation_target_for_site(
            data_root,
            site["id"],
            component_id=clean_component_id,
            selector=clean_selector,
            anchor=clean_anchor,
            route=clean_route,
        )
        if selected_component:
            component_page_id = str(selected_component.get("page_id") or "")
            component_route = str(selected_component.get("route") or "")
            if selected_page is None and component_page_id:
                selected_page = next((item for item in pages if item["id"] == component_page_id), None)
            if selected_route is None and component_route:
                selected_route = next((item for item in routes if item["route"] == component_route), None)
    if selected_page is None and selected_route and selected_route.get("page_id"):
        selected_page = next((item for item in pages if item["id"] == selected_route.get("page_id")), None)
    if selected_page is None and clean_route:
        selected_page = next((item for item in pages if item["route"] == clean_route), None)
    if selected_page is None and clean_route:
        clean_route_key = _visual_route_key(clean_route)
        selected_page = next((item for item in pages if _visual_route_key(str(item.get("route") or "/")) == clean_route_key), None)
    diff_payload = diff_site(data_root, site["id"])
    return _context_payload(
        data_root,
        site,
        page=selected_page,
        route=selected_route,
        asset=selected_asset,
        component=selected_component,
        map_payload=map_payload,
        diff_payload=diff_payload,
        include_inventory=include_inventory,
    )


def _context_payload(
    data_root: Path,
    site: dict[str, object],
    *,
    page: dict[str, object] | None,
    route: dict[str, object] | None,
    asset: dict[str, object] | None,
    map_payload: dict[str, object],
    diff_payload: dict[str, object],
    component: dict[str, object] | None = None,
    include_inventory: object = False,
) -> dict[str, object]:
    active_view = "component" if component else "asset" if asset else "route" if route and not page else "page" if page else "site"
    preview_route = page["route"] if page else route.get("route") if route else "/"
    runtime = runtime_status(data_root, site["id"])
    preview = _context_preview_contract(data_root, site, page=page, route=preview_route, runtime=runtime)
    source_profile_payload = runtime.get("source_profile") if isinstance(runtime.get("source_profile"), dict) else source_profile(_source_root(data_root, str(site["id"])))
    runtime_kind = str(runtime.get("runtime_kind") or preview.get("runtime_kind") or "unavailable")
    runtime_status_value = str(runtime.get("runtime_status") or preview.get("runtime_status") or "blocked")
    missing_requirements = list(runtime.get("missing_requirements") or preview.get("missing_requirements") or [])[:50]
    include_source_inventory = _truthy(include_inventory)
    latest_preview = _latest_preview_for_route(data_root, site_id=site["id"], route=preview_route)
    latest_runtime_session = _latest_runtime_session_for_route(data_root, site_id=site["id"], route=preview_route)
    latest_preview_report = _latest_preview_report_for_route(data_root, site["id"], preview_route)
    page_source_files = _source_files_for_visual_context(page.get("source_files", []) if page else [], include_inventory=include_source_inventory)
    route_source_files = _source_files_for_visual_context(route.get("source_files", []) if route else [], include_inventory=include_source_inventory)
    component_source_files = _source_files_for_visual_context(component.get("source_files", []) if component else [], include_inventory=include_source_inventory)
    if active_view == "component":
        source_files = component_source_files
    elif active_view == "route":
        source_files = route_source_files
    elif active_view == "page":
        source_files = page_source_files
    else:
        source_files = []
    return {
        "active_view": active_view,
        "site_id": site["id"],
        "environment_id": "preview",
        "title": site["display_name"],
        "site": site,
        "source_profile": source_profile_payload,
        "runtime": _context_runtime(
            runtime,
            latest_preview=latest_preview,
            latest_runtime_session=latest_runtime_session,
            latest_preview_report=latest_preview_report,
            include_inventory=include_source_inventory,
        ),
        "page_id": page["id"] if page else None,
        "route_id": route["id"] if route else None,
        "asset_id": asset["id"] if asset else None,
        "component_id": component.get("id") if component else None,
        "route": page["route"] if page else route.get("route") if route else None,
        "preview_id": preview["preview_id"],
        "preview_url": preview["preview_url"],
        "runtime_kind": runtime_kind,
        "runtime_status": runtime_status_value,
        "missing_requirements": missing_requirements,
        "preview": preview,
        "source_files": source_files,
        "page_source_files": page_source_files,
        "route_source_files": route_source_files,
        "asset_path": asset.get("path") if asset else None,
        "component": component or None,
        "target_selector": component.get("selector") if component else None,
        "target_anchor": component.get("anchor") if component else None,
        "asset_refs": page.get("asset_refs", []) if page else [],
        "warnings": page.get("warnings", []) if page else [],
        "route_warnings": route.get("warnings", []) if route else [],
        "asset_warnings": asset.get("warnings", []) if asset else [],
        "routes": _context_routes(map_payload, include_inventory=include_source_inventory),
        "assets": _context_assets(map_payload, page=page, asset=asset, include_inventory=include_source_inventory),
        "visual_assets": _context_visual_assets(map_payload, preview_report=latest_preview_report),
        "context_policy": {
            "scope": "visual" if not include_source_inventory else "inventory",
            "inventory_included": include_source_inventory,
            "inventory_parameter": "include_inventory",
        },
        "changed_files_count": len(diff_payload["files"]),
        "changed_files": _context_changed_files(diff_payload, include_inventory=include_source_inventory),
        "current_revision_id": site.get("published_revision_id"),
        "working_revision_id": site.get("active_revision_id"),
    }


def _context_runtime(
    runtime: dict[str, object],
    *,
    latest_preview: dict[str, object] | None,
    latest_runtime_session: dict[str, object] | None,
    latest_preview_report: dict[str, object] | None,
    include_inventory: bool = False,
) -> dict[str, object]:
    payload = deepcopy(runtime)
    payload["latest_preview"] = deepcopy(latest_preview) if latest_preview else None
    payload["latest_runtime_session"] = deepcopy(latest_runtime_session) if latest_runtime_session else None
    payload["latest_preview_report"] = deepcopy(latest_preview_report) if latest_preview_report else None
    if include_inventory:
        return payload
    report = payload.get("latest_preview_report")
    if isinstance(report, dict):
        payload["latest_preview_report"] = _visual_preview_report_summary(report)
    return payload


def _visual_preview_report_summary(report: dict[str, object]) -> dict[str, object]:
    summary: dict[str, object] = {}
    for key in ("id", "site_id", "preview_id", "route", "runtime_kind", "runtime_status", "generated_at"):
        if key in report:
            summary[key] = report.get(key)
    acceptance = report.get("acceptance")
    if isinstance(acceptance, dict):
        summary["acceptance"] = {
            "passed": bool(acceptance.get("passed")),
            "checks": list(acceptance.get("checks") or [])[:20],
        }
    asset_coverage = report.get("asset_coverage")
    if isinstance(asset_coverage, dict):
        summary["asset_coverage"] = _visual_asset_coverage_summary(asset_coverage)
    source_map = report.get("source_map")
    if isinstance(source_map, dict):
        summary["source_map"] = _visual_source_map_summary(source_map)
    components = report.get("components")
    if isinstance(components, list):
        summary["components"] = [_visual_component_summary(item) for item in components if isinstance(item, dict)][:80]
    navigation = report.get("navigation")
    if isinstance(navigation, dict):
        nav_components = navigation.get("components")
        summary["navigation"] = {
            "route": navigation.get("route") or "",
            "page_id": navigation.get("page_id") or "",
            "components": [_visual_component_summary(item) for item in nav_components if isinstance(item, dict)][:80] if isinstance(nav_components, list) else [],
        }
    return summary


def _visual_source_map_summary(source_map: dict[str, object]) -> dict[str, object]:
    asset_refs = _dedupe_strings(list(source_map.get("asset_refs") or []))[:200] if isinstance(source_map.get("asset_refs"), list) else []
    return {
        "site_id": source_map.get("site_id") or "",
        "preview_id": source_map.get("preview_id") or "",
        "route": source_map.get("route") or "",
        "route_id": source_map.get("route_id") or "",
        "page_id": source_map.get("page_id") or "",
        "source_files": _visual_source_files(source_map.get("source_files", [])),
        "route_source_files": _visual_source_files(source_map.get("route_source_files", [])),
        "asset_refs": asset_refs,
        "asset_index": _visual_asset_records(source_map.get("asset_index"), referenced_paths=set(asset_refs), limit=80),
        "selector_hints": _visual_selector_hints(source_map.get("selector_hints")),
    }


def _visual_asset_coverage_summary(asset_coverage: dict[str, object]) -> dict[str, object]:
    return {
        "status": asset_coverage.get("status") or "",
        "preview_media_reference_count": asset_coverage.get("preview_media_reference_count") or 0,
        "resolved_count": asset_coverage.get("resolved_count") or 0,
        "missing_count": asset_coverage.get("missing_count") or 0,
        "image_count": asset_coverage.get("image_count") or 0,
        "font_count": asset_coverage.get("font_count") or 0,
        "video_count": asset_coverage.get("video_count") or 0,
        "resolved": _visual_asset_records(asset_coverage.get("resolved"), limit=80),
        "missing": _visual_asset_paths(asset_coverage.get("missing"), limit=50),
    }


def _visual_component_summary(component: dict[str, object]) -> dict[str, object]:
    keys = ("id", "kind", "label", "route", "page_id", "selector", "anchor", "tag", "confidence", "last_report_id", "asset_id", "asset_path")
    summary = {key: component.get(key) for key in keys if key in component}
    if isinstance(component.get("visibility"), dict):
        summary["visibility"] = deepcopy(component["visibility"])
    summary["source_files"] = _visual_source_files(component.get("source_files", []))
    return summary


def _visual_selector_hints(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    hints: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        hint = {
            "selector": item.get("selector") or "",
            "token": item.get("token") or "",
            "tag": item.get("tag") or "",
            "text": item.get("text") or "",
            "confidence": item.get("confidence") or "",
            "source_files": _visual_source_files(item.get("source_files", [])),
        }
        if item.get("asset_id"):
            hint["asset_id"] = item.get("asset_id")
        if item.get("asset_path") and not _is_hidden_source_inventory_file(str(item.get("asset_path") or "")):
            hint["asset_path"] = item.get("asset_path")
        hints.append(hint)
        if len(hints) >= 80:
            break
    return hints


def _visual_asset_paths(value: object, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    paths: list[str] = []
    for item in value:
        path = str(item or "").strip()
        if path and not _is_hidden_source_inventory_file(path) and path not in paths:
            paths.append(path)
        if len(paths) >= limit:
            break
    return paths


def _visual_asset_records(value: object, *, referenced_paths: set[str] | None = None, limit: int = 80) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    compact: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path or path in seen or _is_hidden_source_inventory_file(path):
            continue
        if referenced_paths is not None and path not in referenced_paths and str(item.get("status") or "") != "referenced":
            continue
        seen.add(path)
        compact.append(
            {
                "id": item.get("id") or "",
                "path": path,
                "requested_path": item.get("requested_path") or "",
                "kind": item.get("kind") or "file",
                "content_type": item.get("content_type") or "",
                "size_bytes": item.get("size_bytes") or 0,
                "status": item.get("status") or "",
            }
        )
        if len(compact) >= limit:
            break
    return compact


def _context_visual_assets(map_payload: dict[str, object], *, preview_report: dict[str, object] | None) -> list[dict[str, object]]:
    assets_by_path = {str(item.get("path") or ""): item for item in list(map_payload.get("assets") or []) if isinstance(item, dict)}
    compact: list[dict[str, object]] = []
    seen: set[str] = set()

    def append(record: dict[str, object]) -> None:
        path = str(record.get("path") or "").strip()
        if not path or path in seen or _is_hidden_source_inventory_file(path):
            return
        indexed = assets_by_path.get(path, {})
        seen.add(path)
        compact.append(
            {
                "id": indexed.get("id") or record.get("id") or "",
                "path": path,
                "requested_path": record.get("requested_path") or "",
                "kind": record.get("kind") or indexed.get("kind") or "file",
                "content_type": record.get("content_type") or indexed.get("content_type") or "",
                "size_bytes": record.get("size_bytes") or indexed.get("size_bytes") or 0,
                "status": record.get("status") or indexed.get("status") or "",
            }
        )

    report = preview_report or {}
    asset_coverage = report.get("asset_coverage") if isinstance(report.get("asset_coverage"), dict) else {}
    for record in _visual_asset_records(asset_coverage.get("resolved") if isinstance(asset_coverage, dict) else None, limit=80):
        append(record)

    source_map = report.get("source_map") if isinstance(report.get("source_map"), dict) else {}
    asset_refs = {str(item or "").strip() for item in (source_map.get("asset_refs", []) if isinstance(source_map, dict) else []) if str(item or "").strip()}
    for record in _visual_asset_records(source_map.get("asset_index") if isinstance(source_map, dict) else None, referenced_paths=asset_refs, limit=80):
        append(record)
    return compact[:80]


def _context_changed_files(diff_payload: dict[str, object], *, include_inventory: bool = False) -> list[dict[str, object]]:
    files = list(diff_payload.get("files") or [])
    if not include_inventory:
        files = [item for item in files if isinstance(item, dict) and not _is_hidden_source_inventory_file(str(item.get("path") or ""))]
    return [{"path": item["path"], "status": item["status"]} for item in files[:100] if isinstance(item, dict) and item.get("path")]


def _context_routes(map_payload: dict[str, object], *, include_inventory: bool = False) -> list[dict[str, object]]:
    routes = list(map_payload.get("routes") or [])
    if include_inventory:
        return routes[:100]
    visual_routes: list[dict[str, object]] = []
    seen: set[str] = set()
    for route in routes:
        if not isinstance(route, dict) or not _route_is_visual(route):
            continue
        route_text = str(route.get("route") or "/")
        route_key = _visual_route_key(route_text)
        if route_key in seen:
            continue
        seen.add(route_key)
        visual_routes.append(
            {
                "id": route.get("id") or "",
                "route": route_text,
                "canonical_route": route_key,
                "page_id": route.get("page_id") or "",
                "kind": route.get("kind") or "",
                "status": route.get("status") or "",
                "source_files": _visual_source_files(route.get("source_files", [])),
                "warnings": list(route.get("warnings") or [])[:50],
            }
        )
    return visual_routes[:100]


def _context_assets(
    map_payload: dict[str, object],
    *,
    page: dict[str, object] | None,
    asset: dict[str, object] | None,
    include_inventory: bool = False,
) -> list[dict[str, object]]:
    assets = list(map_payload.get("assets") or [])
    if include_inventory:
        return assets[:200]
    referenced_paths = {str(item or "").strip() for item in (page.get("asset_refs", []) if page else []) if str(item or "").strip()}
    selected_asset_id = str(asset.get("id") or "") if asset else ""
    compact: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in assets:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        asset_id = str(item.get("id") or "")
        if path not in referenced_paths and asset_id != selected_asset_id:
            continue
        if not path or path in seen:
            continue
        seen.add(path)
        compact.append(
            {
                "id": asset_id,
                "path": path,
                "kind": item.get("kind") or "file",
                "content_type": item.get("content_type") or "",
                "status": item.get("status") or "",
            }
        )
    return compact[:50]


def _context_preview_contract(
    data_root: Path,
    site: dict[str, object],
    *,
    page: dict[str, object] | None,
    route: object,
    runtime: dict[str, object],
) -> dict[str, object]:
    preview = _preview_contract(data_root, site, page=page, route=route)
    latest_for_route = _latest_preview_for_route(data_root, site_id=site["id"], route=route)
    persisted_preview = latest_for_route
    if persisted_preview:
        persisted_route = str(persisted_preview.get("route") or preview.get("route") or "/")
        preview.update(
            {
                "preview_id": str(persisted_preview.get("id") or ""),
                "preview_url": str(persisted_preview.get("preview_url") or ""),
                "build_id": str(persisted_preview.get("build_id") or ""),
                "route": persisted_route,
                "route_id": _route_id_for_route(data_root, site["id"], persisted_route),
                "page_id": str(persisted_preview.get("page_id") or ""),
                "runtime_kind": str(persisted_preview.get("runtime_kind") or preview.get("runtime_kind") or "unavailable"),
                "runtime_status": str(persisted_preview.get("status") or preview.get("runtime_status") or "blocked"),
                "warnings": list(persisted_preview.get("warnings") or preview.get("warnings") or [])[:100],
                "missing_requirements": list(persisted_preview.get("missing_requirements") or preview.get("missing_requirements") or [])[:50],
                "artifact_ref": dict(persisted_preview.get("artifact_ref") or {}) if isinstance(persisted_preview.get("artifact_ref"), dict) else {},
            }
        )
    if runtime.get("runtime_kind"):
        preview["runtime_kind"] = str(runtime.get("runtime_kind") or preview["runtime_kind"])
    if runtime.get("runtime_status"):
        preview["runtime_status"] = str(runtime.get("runtime_status") or preview["runtime_status"])
    if isinstance(runtime.get("missing_requirements"), list):
        preview["missing_requirements"] = list(runtime.get("missing_requirements") or [])[:50]
    return preview


def _preview_contract(
    data_root: Path,
    site: dict[str, object],
    *,
    page: dict[str, object] | None = None,
    route: object = "/",
    preview_id: str = "",
) -> dict[str, object]:
    source_root = _source_root(data_root, str(site["id"]))
    profile = _cached_source_profile(data_root, site, source_root=source_root)
    if not str(site.get("source_version") or "").strip():
        site = get_site(data_root, site["id"])
    route_text = str(route or "/")
    route_id = _route_id_for_route(data_root, site["id"], route_text) if route_text else ""
    runtime_kind = str(profile.get("preview_runtime_kind") or "unavailable")
    runtime_status = str(profile.get("runtime_preview_status") or "blocked")
    warnings = list(page.get("warnings", [])) if page else []
    missing_requirements = [str(item) for item in profile.get("missing_requirements", []) if str(item).strip()] if isinstance(profile.get("missing_requirements"), list) else []
    if runtime_kind == "static_export" and profile.get("static_preview_supported"):
        runtime_status = "ready"
    elif runtime_kind != "static_export" and profile.get("static_preview_supported"):
        runtime_status = "static_fallback"
        warnings.append(f"{runtime_kind} runtime is not available yet; serving sanitized static HTML fallback")
    if runtime_kind == "static_export" and profile.get("static_preview_supported"):
        warnings.append("serving static export in an isolated preview runtime")
    warnings = _dedupe_strings(warnings + rendered_route_warnings(source_root, profile))
    preview_url = _preview_runtime_url(preview_id, route_text) if preview_id else ""
    return {
        "preview_id": preview_id,
        "site_id": str(site["id"]),
        "environment_id": str(site.get("default_environment_id") or "env_preview"),
        "runtime_kind": runtime_kind,
        "preview_url": preview_url,
        "route": route_text,
        "route_id": route_id,
        "page_id": page["id"] if page else "",
        "build_id": "",
        "runtime_status": runtime_status,
        "warnings": warnings[:100],
        "missing_requirements": missing_requirements[:50],
        "artifact_ref": {
            "active_revision_id": str(site.get("active_revision_id") or ""),
            "source_version": _source_version_for_site(site),
        },
    }


def _record_preview(data_root: Path, site: dict[str, object], contract: dict[str, object]) -> None:
    preview_id = str(contract.get("preview_id") or "").strip()
    if not preview_id:
        return
    now = now_timestamp()
    with connect(data_root) as db:
        db.execute(
            """
            INSERT INTO previews(
              id, site_id, route, page_id, build_id, runtime_kind, preview_url,
              warnings_json, missing_requirements_json, artifact_ref_json, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                preview_id,
                str(site["id"]),
                str(contract.get("route") or "/"),
                str(contract.get("page_id") or ""),
                str(contract.get("build_id") or ""),
                str(contract.get("runtime_kind") or ""),
                str(contract.get("preview_url") or ""),
                json.dumps(list(contract.get("warnings") or [])[:100]),
                json.dumps(list(contract.get("missing_requirements") or [])[:50]),
                json.dumps(dict(contract.get("artifact_ref") or {}), sort_keys=True),
                str(contract.get("runtime_status") or "blocked"),
                now,
            ),
        )
    _record_runtime_session(data_root, site, contract, created_at=now)


def _record_runtime_session(data_root: Path, site: dict[str, object], contract: dict[str, object], *, created_at: str) -> None:
    preview_id = str(contract.get("preview_id") or "").strip()
    session_id = f"runtime_{uuid4().hex[:16]}"
    health = {
        "route": str(contract.get("route") or "/"),
        "runtime_kind": str(contract.get("runtime_kind") or "unavailable"),
        "runtime_status": str(contract.get("runtime_status") or "blocked"),
        "preview_url": str(contract.get("preview_url") or ""),
        "warnings": list(contract.get("warnings") or [])[:100],
    }
    with connect(data_root) as db:
        db.execute(
            """
            INSERT INTO runtime_sessions(
              id, site_id, preview_id, build_id, runtime_kind, status, preview_url,
              route, health_json, missing_requirements_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                str(site["id"]),
                preview_id,
                str(contract.get("build_id") or ""),
                str(contract.get("runtime_kind") or "unavailable"),
                str(contract.get("runtime_status") or "blocked"),
                str(contract.get("preview_url") or ""),
                str(contract.get("route") or "/"),
                json.dumps(health, sort_keys=True),
                json.dumps(list(contract.get("missing_requirements") or [])[:50]),
                created_at,
                created_at,
            ),
        )


def _preview_runtime_url(preview_id: str, route: str) -> str:
    if not preview_id:
        return ""
    return f"/apps/website-studio/preview-runtime/?{urlencode({'preview_id': preview_id, 'route': route or '/', 'runtime_version': PREVIEW_RUNTIME_VERSION})}"


def _paged_rows(db, query: str, params: tuple[object, ...], *, limit: int, offset: int) -> dict[str, object]:
    rows = db.execute(f"{query} LIMIT ? OFFSET ?", (*params, limit + 1, offset)).fetchall()
    page_rows = rows[:limit]
    return {
        "rows": page_rows,
        "pagination": _pagination(limit=limit, offset=offset, returned=len(page_rows), has_more=len(rows) > limit),
    }


def _pagination(*, limit: int, offset: int, returned: int, has_more: bool) -> dict[str, object]:
    return {
        "limit": limit,
        "offset": offset,
        "returned": returned,
        "has_more": has_more,
        "next_offset": offset + returned if has_more else None,
    }


def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
    if value is None or value == "":
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _compact_log(value: str, *, include_logs: bool) -> tuple[str, bool, int]:
    redacted = redact_runtime_log(value)
    if include_logs or len(redacted) <= COMPACT_LOG_CHARS:
        return redacted, False, len(redacted)
    return redacted[:COMPACT_LOG_CHARS].rstrip() + "\n...", True, len(redacted)


def _dedupe_strings(items: list[object]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def reference_manifest() -> dict[str, object]:
    metadata = {
        "site": {"display_name": "Website Site", "searchable": True},
        "page": {"display_name": "Website Page", "searchable": True},
        "route": {"display_name": "Website Route", "searchable": True},
        "component": {"display_name": "Website Component", "searchable": True},
        "asset": {"display_name": "Website Asset", "searchable": True},
        "revision": {"display_name": "Website Revision", "searchable": False},
        "publish_request": {"display_name": "Publish Request", "searchable": True},
    }
    return {
        "entity_types": [
            {
                "entity_type": entity,
                "display_name": metadata[entity]["display_name"],
                "searchable": metadata[entity]["searchable"],
                "resolvable": True,
                "summarizable": True,
                "deep_link_supported": True,
            }
            for entity in REFERENCE_ENTITIES
        ]
    }


def reference_search(data_root: Path, query: object = "", site_id: object = None) -> list[dict[str, object]]:
    items = search(data_root, query, site_id)
    items.extend(_component_reference_search(data_root, query, site_id))
    needle = f"%{str(query or '').strip()}%"
    ensure_schema(data_root)
    with connect(data_root) as db:
        if site_id:
            request_rows = db.execute(
                """
                SELECT * FROM publish_requests
                WHERE site_id = ? AND (id LIKE ? OR status LIKE ? OR diff_summary LIKE ?)
                ORDER BY updated_at DESC
                """,
                (str(site_id), needle, needle, needle),
            ).fetchall()
        else:
            request_rows = db.execute(
                """
                SELECT * FROM publish_requests
                WHERE id LIKE ? OR status LIKE ? OR diff_summary LIKE ?
                ORDER BY updated_at DESC
                """,
                (needle, needle, needle),
            ).fetchall()
    return items + [_reference_payload("publish_request", dict(row)) for row in request_rows]


def reference_resolve(data_root: Path, entity_type: object, entity_id: object) -> dict[str, object]:
    entity = str(entity_type or "site")
    if entity == "site":
        return _reference_payload("site", get_site(data_root, entity_id))
    if entity == "page":
        return _reference_payload("page", _get_page(data_root, entity_id))
    if entity == "route":
        return _reference_payload("route", _get_route(data_root, entity_id))
    if entity == "component":
        return _reference_payload("component", _get_component(data_root, entity_id))
    if entity == "asset":
        return _reference_payload("asset", _get_asset(data_root, entity_id))
    if entity == "revision":
        item = get_revision(data_root, entity_id)
        return _reference_payload("revision", {key: value for key, value in item.items() if key != "snapshot"})
    if entity == "publish_request":
        return _reference_payload("publish_request", get_publish_request(data_root, entity_id))
    raise ValueError(f"Unsupported entity_type `{entity}`")


def reference_summary(data_root: Path, entity_type: object, entity_id: object) -> dict[str, object]:
    item = reference_resolve(data_root, entity_type, entity_id)
    title = item.get("display_name") or item.get("title") or item.get("route") or item.get("path") or item.get("id")
    return {
        "entity_type": item["entity_type"],
        "entity_id": item["id"],
        "title": title,
        "summary": item.get("route") or item.get("path") or item.get("status") or "",
        "app_page": item.get("app_page", ""),
        "deep_link": item.get("deep_link", ""),
    }


def create_revision(data_root: Path, site_id: object, *, label: str, source: str, summary: str = "") -> dict[str, object]:
    revision_id = f"rev_{uuid4().hex[:16]}"
    now = now_timestamp()
    source_root = _source_root(data_root, str(site_id))
    snapshot = snapshot_text_files(source_root)
    copy_tree_snapshot(source_root, _revision_source_root(data_root, str(site_id), revision_id))
    with connect(data_root) as db:
        db.execute(
            "INSERT INTO revisions(id, site_id, label, source, summary, snapshot_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (revision_id, str(site_id), label, source, summary, json.dumps(snapshot, sort_keys=True), now),
        )
    return _public_revision(get_revision(data_root, revision_id))


def get_revision(data_root: Path, revision_id: object) -> dict[str, object]:
    clean_id = _required_id(revision_id, "revision_id")
    ensure_schema(data_root)
    with connect(data_root) as db:
        row = db.execute("SELECT * FROM revisions WHERE id = ?", (clean_id,)).fetchone()
    if row is None:
        raise ValueError(f"revision `{clean_id}` was not found")
    payload = dict(row)
    payload["snapshot"] = json.loads(payload.pop("snapshot_json") or "{}")
    payload["snapshot_path"] = str(_revision_source_root(data_root, payload["site_id"], payload["id"]))
    return payload


def _public_revision(revision: dict[str, object]) -> dict[str, object]:
    payload = {key: value for key, value in revision.items() if key != "snapshot"}
    snapshot = revision.get("snapshot")
    payload["snapshot_text_file_count"] = len(snapshot) if isinstance(snapshot, dict) else 0
    return payload


def get_publish_request(data_root: Path, request_id: object) -> dict[str, object]:
    clean_id = _required_id(request_id, "publish_request_id")
    ensure_schema(data_root)
    with connect(data_root) as db:
        row = db.execute("SELECT * FROM publish_requests WHERE id = ?", (clean_id,)).fetchone()
    if row is None:
        raise ValueError(f"publish request `{clean_id}` was not found")
    return dict(row)


def load_view_state(data_root: Path) -> dict[str, object]:
    path = data_root / "view_state.json"
    if not path.exists():
        return {"schema_version": "1", "active_site_id": "", "view_filter": _default_view_filter()}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raw = {}
    return {
        "schema_version": "1",
        "active_site_id": str(raw.get("active_site_id") or ""),
        "view_filter": raw.get("view_filter") if isinstance(raw.get("view_filter"), dict) else _default_view_filter(),
    }


def set_view_filter(data_root: Path, *, query: object = None, site_id: object = None, preserve_custom: bool = False) -> dict[str, object]:
    current = load_view_state(data_root)
    view_filter = dict(current.get("view_filter") or {}) if preserve_custom else _default_view_filter()
    view_filter.update({"mode": "search", "query": str(query or "").strip(), "site_id": str(site_id or ""), "updated_at": now_timestamp()})
    return _write_view_state(data_root, view_filter)


def set_custom_view(data_root: Path, *, title: object = None, refs: object = None) -> dict[str, object]:
    return _write_view_state(data_root, {"mode": "custom", "query": "", "site_id": "", "title": str(title or "Custom website view"), "refs": refs if isinstance(refs, list) else [], "updated_at": now_timestamp()})


def clear_custom_view(data_root: Path) -> dict[str, object]:
    return _write_view_state(data_root, _default_view_filter())


def list_environments(data_root: Path, site_id: object) -> list[dict[str, object]]:
    site = get_site(data_root, site_id)
    _ensure_default_environment(data_root, str(site["id"]))
    with connect(data_root) as db:
        rows = db.execute("SELECT * FROM environments WHERE site_id = ? ORDER BY kind, name", (site["id"],)).fetchall()
    return [_environment_row(row) for row in rows]


def configure_environment(
    data_root: Path,
    site_id: object,
    *,
    environment_id: object = None,
    name: object = None,
    kind: object = "preview",
    base_url: object = "",
    requires_approval: object = True,
) -> dict[str, object]:
    site = get_site(data_root, site_id)
    clean_kind = str(kind or "preview").strip()
    if clean_kind not in {"preview", "staging", "production", "custom"}:
        raise ValueError("environment kind must be preview, staging, production, or custom")
    clean_id = str(environment_id or f"env_{site['id']}_{clean_kind}").strip()
    if not clean_id.startswith("env_") or "/" in clean_id or "\\" in clean_id:
        raise ValueError("environment_id must start with env_ and stay path-safe")
    label = str(name or clean_kind.title()).strip()
    if not label:
        raise ValueError("environment name is required")
    now = now_timestamp()
    with connect(data_root) as db:
        db.execute(
            """
            INSERT INTO environments(id, site_id, name, kind, base_url, requires_approval, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              name=excluded.name,
              kind=excluded.kind,
              base_url=excluded.base_url,
              requires_approval=excluded.requires_approval,
              updated_at=excluded.updated_at
            """,
            (clean_id, site["id"], label, clean_kind, str(base_url or "").strip(), 1 if requires_approval is not False else 0, now, now),
        )
    if clean_kind == "preview" or not site.get("default_environment_id"):
        _update_site(data_root, site["id"], default_environment_id=clean_id)
    _audit(data_root, str(site["id"]), "environment.configured", f"Configured {label} environment", {"environment_id": clean_id})
    return get_environment(data_root, clean_id, site_id=site["id"])


def list_publish_targets(data_root: Path, site_id: object) -> list[dict[str, object]]:
    site = get_site(data_root, site_id)
    ensure_schema(data_root)
    with connect(data_root) as db:
        rows = db.execute("SELECT * FROM publish_targets WHERE site_id = ? ORDER BY updated_at DESC", (site["id"],)).fetchall()
    return [_publish_target_row(row) for row in rows]


def configure_publish_target(
    data_root: Path,
    site_id: object,
    *,
    environment_id: object = None,
    kind: object = "managed_static",
    status: object = "active",
    config: object = None,
) -> dict[str, object]:
    site = get_site(data_root, site_id)
    environment = get_environment(data_root, environment_id or site.get("default_environment_id") or "env_preview", site_id=site["id"])
    clean_kind = str(kind or "managed_static").strip()
    if clean_kind not in {"managed_static", "git_pull_request"}:
        raise ValueError("publish target kind must be managed_static or git_pull_request")
    clean_status = str(status or "active").strip()
    if clean_status not in {"active", "disabled"}:
        raise ValueError("publish target status must be active or disabled")
    config_payload = dict(config) if isinstance(config, dict) else {}
    if clean_kind == "managed_static":
        config_payload = {
            "provider": "maverick-managed-static",
            "runtime": "local_static_artifact",
            "platform_surface": "generic_static_hosting",
            "platform_binding_status": "pending_generic_surface",
            "public_url": "",
            "custom_domain": "",
            "certificate_status": "",
            "cache_policy": "",
            "cdn_status": "",
            "verification_status": "",
            **config_payload,
        }
    target_id = f"target_{site['id']}_{clean_kind}_{environment['kind']}"
    now = now_timestamp()
    with connect(data_root) as db:
        db.execute(
            """
            INSERT INTO publish_targets(id, site_id, environment_id, kind, status, config_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              environment_id=excluded.environment_id,
              kind=excluded.kind,
              status=excluded.status,
              config_json=excluded.config_json,
              updated_at=excluded.updated_at
            """,
            (target_id, site["id"], environment["id"], clean_kind, clean_status, json.dumps(config_payload, sort_keys=True), now, now),
        )
        db.execute(
            "UPDATE environments SET publish_target_id = ?, updated_at = ? WHERE id = ? AND site_id = ?",
            (target_id, now, environment["id"], site["id"]),
        )
    _audit(data_root, str(site["id"]), "publish_target.configured", f"Configured {clean_kind} publish target", {"target_id": target_id})
    return get_publish_target(data_root, target_id, site_id=site["id"])


def get_publish_target(data_root: Path, target_id: object, *, site_id: object | None = None) -> dict[str, object]:
    clean_id = _required_id(target_id, "publish_target_id")
    ensure_schema(data_root)
    with connect(data_root) as db:
        if site_id:
            row = db.execute("SELECT * FROM publish_targets WHERE id = ? AND site_id = ?", (clean_id, str(site_id))).fetchone()
        else:
            row = db.execute("SELECT * FROM publish_targets WHERE id = ?", (clean_id,)).fetchone()
    if row is None:
        raise ValueError(f"publish target `{clean_id}` was not found")
    return _publish_target_row(row)


def get_environment(data_root: Path, environment_id: object, *, site_id: object | None = None) -> dict[str, object]:
    clean_id = str(environment_id or "env_preview").strip()
    if site_id:
        _ensure_default_environment(data_root, str(site_id))
        if clean_id == "env_preview":
            site = get_site(data_root, site_id)
            clean_id = str(site.get("default_environment_id") or f"env_{site_id}_preview")
    ensure_schema(data_root)
    with connect(data_root) as db:
        if site_id:
            row = db.execute("SELECT * FROM environments WHERE id = ? AND site_id = ?", (clean_id, str(site_id))).fetchone()
        else:
            row = db.execute("SELECT * FROM environments WHERE id = ?", (clean_id,)).fetchone()
    if row is None:
        raise ValueError(f"environment `{clean_id}` was not found")
    return _environment_row(row)


def record_approval(
    data_root: Path,
    site_id: object,
    *,
    action: object,
    target_id: object,
    approved_by: object,
    approval_note: object = "",
    confirm: object = False,
    actor: dict[str, object] | None = None,
) -> dict[str, object]:
    site = get_site(data_root, site_id)
    clean_action = str(action or "").strip()
    if clean_action not in {"publish", "rollback"}:
        raise ValueError("approval action must be publish or rollback")
    clean_target = _required_id(target_id, "target_id")
    if confirm is not True:
        raise ValueError("confirm=true is required to create an approval event")
    policy = _approval_actor_policy(actor or {}, approved_by)
    if not policy["allowed"]:
        raise ValueError(str(policy["detail"]))
    approver = str(policy["approved_by"])
    if clean_action == "publish":
        request = get_publish_request(data_root, clean_target)
        if request["site_id"] != site["id"]:
            raise ValueError("publish request does not belong to the selected site")
    if clean_action == "rollback":
        revision = get_revision(data_root, clean_target)
        if revision["site_id"] != site["id"]:
            raise ValueError("revision does not belong to the selected site")
    approval_id = f"appr_{uuid4().hex[:16]}"
    now = now_timestamp()
    with connect(data_root) as db:
        db.execute(
            """
            INSERT INTO approval_events(id, site_id, action, target_id, status, approved_by, approval_note, created_at)
            VALUES (?, ?, ?, ?, 'approved', ?, ?, ?)
            """,
            (approval_id, site["id"], clean_action, clean_target, approver, str(approval_note or "").strip(), now),
        )
    _audit(data_root, str(site["id"]), "approval.recorded", f"Approved {clean_action} for {clean_target}", {"approval_id": approval_id})
    approval = get_approval(data_root, approval_id)
    approval["policy"] = policy
    return approval


def list_approvals(data_root: Path, site_id: object = None) -> list[dict[str, object]]:
    ensure_schema(data_root)
    with connect(data_root) as db:
        if site_id:
            rows = db.execute("SELECT * FROM approval_events WHERE site_id = ? ORDER BY created_at DESC", (str(site_id),)).fetchall()
        else:
            rows = db.execute("SELECT * FROM approval_events ORDER BY created_at DESC").fetchall()
    return [_approval_row(row) for row in rows]


def get_approval(data_root: Path, approval_id: object) -> dict[str, object]:
    clean_id = _required_id(approval_id, "approval_id")
    ensure_schema(data_root)
    with connect(data_root) as db:
        row = db.execute("SELECT * FROM approval_events WHERE id = ?", (clean_id,)).fetchone()
    if row is None:
        raise ValueError(f"approval `{clean_id}` was not found")
    return _approval_row(row)


def _approval_actor_policy(actor: dict[str, object], approved_by: object) -> dict[str, object]:
    user_id = str(actor.get("user_id") or "").strip()
    workspace_role = str(actor.get("workspace_role") or "").strip().lower()
    platform_role = str(actor.get("platform_role") or "").strip().lower()
    effective_mode = str(actor.get("effective_mode") or "").strip()
    if not user_id:
        return {"allowed": False, "detail": "approval requires an authenticated Maverick user actor"}
    allowed_roles = {"owner", "admin"}
    allowed_platform_roles = {"admin", "operator"}
    if workspace_role not in allowed_roles and platform_role not in allowed_platform_roles:
        return {
            "allowed": False,
            "detail": "approval requires workspace owner/admin or platform admin/operator role",
            "user_id": user_id,
            "workspace_role": workspace_role,
            "platform_role": platform_role,
        }
    explicit_approver = str(approved_by or "").strip()
    if explicit_approver and explicit_approver != user_id:
        return {
            "allowed": False,
            "detail": "approved_by must match the authenticated Maverick user actor",
            "user_id": user_id,
            "approved_by": explicit_approver,
        }
    return {
        "allowed": True,
        "approved_by": explicit_approver or user_id,
        "user_id": user_id,
        "workspace_role": workspace_role,
        "platform_role": platform_role,
        "effective_mode": effective_mode,
        "policy": "workspace_owner_or_admin_required",
    }


def _source_root(data_root: Path, site_id: str) -> Path:
    if not site_id or "/" in site_id or "\\" in site_id or site_id in {".", ".."}:
        raise ValueError(f"Invalid site_id `{site_id}`")
    return data_root / "sites" / site_id / "source"


def _revision_source_root(data_root: Path, site_id: str, revision_id: str) -> Path:
    if not revision_id or "/" in revision_id or "\\" in revision_id or revision_id in {".", ".."}:
        raise ValueError(f"Invalid revision_id `{revision_id}`")
    return data_root / "sites" / site_id / "revisions" / revision_id / "source"


@contextmanager
def _site_mutation_lock(data_root: Path, site_id: str) -> Iterator[None]:
    if not site_id or "/" in site_id or "\\" in site_id or site_id in {".", ".."}:
        raise ValueError(f"Invalid site_id `{site_id}`")
    lock_dir = data_root / ".locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    with (lock_dir / f"{site_id}.lock").open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _required_id(value: object, label: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        raise ValueError(f"{label} is required")
    return clean


def _clean_source_provider(value: object) -> str:
    provider = str(value or "manual").strip() or "manual"
    if provider not in IMPLEMENTED_SOURCE_PROVIDERS:
        supported = ", ".join(sorted(IMPLEMENTED_SOURCE_PROVIDERS))
        raise ValueError(f"source_provider must be one of {supported}; CMS and commerce providers are later phases")
    return provider


def _site_row(row, *, active_site_id: str = "") -> dict[str, object]:
    payload = dict(row)
    payload["source_artifact_ref"] = json.loads(payload.pop("source_artifact_ref_json", "{}") or "{}")
    payload["source_profile"] = json.loads(payload.pop("source_profile_json", "{}") or "{}")
    payload["is_active"] = bool(active_site_id and payload.get("id") == active_site_id and payload.get("status") != "archived")
    return payload


def _latest_builds_by_site(data_root: Path, site_ids: list[str]) -> dict[str, dict[str, object]]:
    clean_ids = [site_id for site_id in site_ids if site_id]
    if not clean_ids:
        return {}
    placeholders = ",".join("?" for _ in clean_ids)
    ensure_schema(data_root)
    with connect(data_root) as db:
        rows = db.execute(
            f"""
            SELECT builds.*
            FROM builds
            INNER JOIN (
                SELECT site_id, MAX(created_at) AS latest_created_at
                FROM builds
                WHERE site_id IN ({placeholders})
                GROUP BY site_id
            ) latest
              ON builds.site_id = latest.site_id
             AND builds.created_at = latest.latest_created_at
            ORDER BY builds.site_id ASC, builds.created_at DESC, builds.id DESC
            """,
            tuple(clean_ids),
        ).fetchall()
    latest: dict[str, dict[str, object]] = {}
    for row in rows:
        site_id = str(row["site_id"])
        if site_id not in latest:
            latest[site_id] = _build_row(row, include_logs=False)
    return latest


def _site_with_latest_runtime_profile(site: dict[str, object], latest_build: dict[str, object] | None) -> dict[str, object]:
    if not latest_build or not _build_matches_site_source(site, latest_build):
        return site
    profile = site.get("source_profile") if isinstance(site.get("source_profile"), dict) else {}
    site_payload = dict(site)
    site_payload["source_profile"] = _normalized_profile_for_build(latest_build, dict(profile))
    return site_payload


def _build_matches_site_source(site: dict[str, object], build: dict[str, object]) -> bool:
    site_source_version = str(site.get("source_version") or "").strip()
    artifact_ref = build.get("artifact_ref") if isinstance(build.get("artifact_ref"), dict) else {}
    build_source_version = str(artifact_ref.get("source_version") or "").strip()
    return bool(site_source_version and build_source_version and site_source_version == build_source_version)


def _cached_source_profile(
    data_root: Path,
    site: dict[str, object],
    *,
    source_root: Path | None = None,
) -> dict[str, object]:
    cached = site.get("source_profile") if isinstance(site.get("source_profile"), dict) else {}
    if cached:
        if not str(site.get("source_version") or "").strip():
            _refresh_site_source_metadata(data_root, site["id"], cached, bump_version=False)
        return dict(cached)
    root = source_root or _source_root(data_root, str(site["id"]))
    profile = source_profile(root)
    _refresh_site_source_metadata(data_root, site["id"], profile, bump_version=False)
    return profile


def _refresh_site_source_metadata(
    data_root: Path,
    site_id: object,
    profile: dict[str, object] | None = None,
    *,
    bump_version: bool = True,
) -> str:
    clean_site_id = str(site_id)
    payload = dict(profile or source_profile(_source_root(data_root, clean_site_id)))
    current = get_site(data_root, clean_site_id)
    fields: dict[str, object] = {
        "source_profile_json": json.dumps(payload, sort_keys=True),
        "source_shape": str(payload.get("source_shape") or ""),
    }
    if bump_version or not str(current.get("source_version") or "").strip():
        fields["source_version"] = f"src_{uuid4().hex[:16]}"
    _update_site(data_root, clean_site_id, **fields)
    if "source_version" in fields:
        return str(fields["source_version"])
    return _source_version_for_site(get_site(data_root, clean_site_id))


def _source_version_for_site(site: dict[str, object]) -> str:
    value = str(site.get("source_version") or "").strip()
    if value:
        return value
    revision = str(site.get("active_revision_id") or "").strip()
    updated = str(site.get("updated_at") or "").strip()
    return revision or updated or "unversioned"


def _environment_row(row) -> dict[str, object]:
    payload = dict(row)
    payload["requires_approval"] = bool(payload.get("requires_approval"))
    return payload


def _publish_target_row(row) -> dict[str, object]:
    payload = dict(row)
    payload["config"] = json.loads(payload.pop("config_json") or "{}")
    return payload


def _approval_row(row) -> dict[str, object]:
    return dict(row)


def _build_row(row, *, include_logs: bool = True) -> dict[str, object]:
    if row is None:
        return {}
    payload = dict(row)
    payload["source_profile"] = json.loads(payload.pop("source_profile_json") or "{}")
    payload["artifact_ref"] = json.loads(payload.pop("artifact_ref_json", "{}") or "{}")
    payload["warnings"] = _dedupe_strings(json.loads(payload.pop("warnings_json") or "[]"))[:100]
    payload["missing_requirements"] = _dedupe_strings(json.loads(payload.pop("missing_requirements_json", "[]") or "[]"))[:50]
    payload["source_profile"] = _normalized_profile_for_build(payload, payload["source_profile"])
    compact_log, truncated, original_chars = _compact_log(str(payload.get("logs_summary") or ""), include_logs=include_logs)
    payload["logs_summary"] = compact_log
    payload["logs_summary_truncated"] = truncated
    payload["logs_summary_chars"] = original_chars
    return payload


def _normalized_profile_for_build(build: dict[str, object], profile: dict[str, object]) -> dict[str, object]:
    runtime_kind = str(build.get("runtime_kind") or profile.get("preview_runtime_kind") or "unavailable")
    missing_requirements = build.get("missing_requirements") if isinstance(build.get("missing_requirements"), list) else []
    build_status = str(build.get("status") or "").strip()
    if build_status == "passed" and not missing_requirements:
        runtime_status = "ready"
    elif build_status in {"blocked", "failed"}:
        runtime_status = build_status
    else:
        runtime_status = str(profile.get("runtime_preview_status") or build_status or "blocked")
    return _source_profile_with_runtime_status(
        profile,
        runtime_kind=runtime_kind,
        runtime_status=runtime_status,
        missing_requirements=missing_requirements,
    )


def _preview_row(row) -> dict[str, object]:
    if row is None:
        return {}
    payload = dict(row)
    payload["warnings"] = _dedupe_strings(json.loads(payload.pop("warnings_json", "[]") or "[]"))[:100]
    payload["missing_requirements"] = _dedupe_strings(json.loads(payload.pop("missing_requirements_json", "[]") or "[]"))[:50]
    payload["artifact_ref"] = json.loads(payload.pop("artifact_ref_json", "{}") or "{}")
    payload["preview_url"] = _preview_runtime_url(str(payload.get("id") or ""), str(payload.get("route") or "/"))
    return payload


def _runtime_session_row(row) -> dict[str, object]:
    if row is None:
        return {}
    payload = dict(row)
    payload["health"] = json.loads(payload.pop("health_json", "{}") or "{}")
    payload["missing_requirements"] = _dedupe_strings(json.loads(payload.pop("missing_requirements_json", "[]") or "[]"))[:50]
    preview_id = str(payload.get("preview_id") or "")
    if preview_id:
        payload["preview_url"] = _preview_runtime_url(preview_id, str(payload.get("route") or "/"))
        if isinstance(payload.get("health"), dict):
            payload["health"]["preview_url"] = payload["preview_url"]
    return payload


def _source_profile_with_runtime_status(
    profile: dict[str, object],
    *,
    runtime_kind: str,
    runtime_status: str,
    missing_requirements: object,
) -> dict[str, object]:
    payload = dict(profile)
    clean_missing = _dedupe_strings(
        [str(item) for item in missing_requirements if str(item).strip()]
        if isinstance(missing_requirements, list)
        else []
    )[:50]
    payload["preview_runtime_kind"] = runtime_kind or str(payload.get("preview_runtime_kind") or "unavailable")
    payload["runtime_preview_status"] = runtime_status or str(payload.get("runtime_preview_status") or "blocked")
    payload["missing_requirements"] = clean_missing
    if payload["runtime_preview_status"] in {"ready", "static_fallback"}:
        payload["runtime_preview_supported"] = True
    return payload


def _deployment_row(row) -> dict[str, object]:
    payload = dict(row)
    payload["source_ref"] = json.loads(payload.pop("source_ref_json") or "{}")
    return payload


def _sync_run_row(row, *, include_logs: bool = True) -> dict[str, object]:
    payload = dict(row)
    payload["conflicts"] = json.loads(payload.pop("conflicts_json") or "[]")
    payload["source_profile"] = json.loads(payload.pop("source_profile_json") or "{}")
    compact_log, truncated, original_chars = _compact_log(str(payload.get("logs_summary") or ""), include_logs=include_logs)
    payload["logs_summary"] = compact_log
    payload["logs_summary_truncated"] = truncated
    payload["logs_summary_chars"] = original_chars
    return payload


def _ensure_default_environment(data_root: Path, site_id: str) -> None:
    ensure_schema(data_root)
    now = now_timestamp()
    environment_id = f"env_{site_id}_preview"
    with connect(data_root) as db:
        row = db.execute("SELECT id FROM environments WHERE site_id = ? AND kind = 'preview'", (site_id,)).fetchone()
        if row is None:
            db.execute(
                """
                INSERT INTO environments(id, site_id, name, kind, base_url, requires_approval, created_at, updated_at)
                VALUES (?, ?, 'Preview', 'preview', '', 1, ?, ?)
                """,
                (environment_id, site_id, now, now),
            )
        else:
            environment_id = row["id"]
        site_row = db.execute("SELECT default_environment_id FROM sites WHERE id = ?", (site_id,)).fetchone()
        if site_row and not site_row["default_environment_id"]:
            db.execute("UPDATE sites SET default_environment_id = ?, updated_at = ? WHERE id = ?", (environment_id, now, site_id))


def _consume_approval(data_root: Path, site_id: object, action: str, target_id: object, approval_id: object) -> dict[str, object]:
    approval = get_approval(data_root, approval_id)
    if approval["site_id"] != str(site_id):
        raise ValueError("approval does not belong to the selected site")
    if approval["action"] != action:
        raise ValueError(f"approval is for {approval['action']}, not {action}")
    if approval["target_id"] != str(target_id):
        raise ValueError("approval target does not match this operation")
    if approval["status"] != "approved":
        raise ValueError("approval is not approved")
    if approval.get("used_at"):
        raise ValueError("approval has already been used")
    used_at = now_timestamp()
    with connect(data_root) as db:
        db.execute("UPDATE approval_events SET used_at = ?, status = 'used' WHERE id = ?", (used_at, approval["id"]))
    approval = get_approval(data_root, approval["id"])
    return approval


def _create_deployment(
    data_root: Path,
    site_id: object,
    *,
    environment_id: str,
    publish_request_id: str,
    revision_id: str,
    status: str,
    mode: str,
    source_ref: dict[str, object],
) -> dict[str, object]:
    deployment_id = f"dep_{uuid4().hex[:16]}"
    now = now_timestamp()
    with connect(data_root) as db:
        db.execute(
            """
            INSERT INTO deployments(id, site_id, environment_id, publish_request_id, revision_id, status, mode, source_ref_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (deployment_id, str(site_id), environment_id, publish_request_id, revision_id, status, mode, json.dumps(source_ref, sort_keys=True), now, now),
        )
        db.execute("UPDATE environments SET last_deployment_id = ?, updated_at = ? WHERE site_id = ? AND id = ?", (deployment_id, now, str(site_id), environment_id))
    with connect(data_root) as db:
        row = db.execute("SELECT * FROM deployments WHERE id = ?", (deployment_id,)).fetchone()
    return _deployment_row(row)


def _publish_mode(source_ref: dict[str, object]) -> str:
    if source_ref.get("provider") == "github" and source_ref.get("status") == "pull_request_open":
        return "github_pull_request"
    if source_ref.get("provider") == "github":
        return "github_pr_prepared"
    if source_ref.get("provider") == "maverick-managed-static":
        return "maverick_managed_static"
    return "internal_static_snapshot"


def _publish_source_ref(site: dict[str, object], request: dict[str, object], *, publish_target: dict[str, object] | None = None) -> dict[str, object]:
    ref = site.get("source_artifact_ref") if isinstance(site.get("source_artifact_ref"), dict) else {}
    if ref.get("provider") == "github" and not (publish_target and publish_target.get("kind") == "managed_static"):
        return {
            "provider": "github",
            "connection_id": str(ref.get("connection_id") or ""),
            "base_branch": str(ref.get("base_branch") or "main"),
            "working_branch": working_branch_for_site(site, request),
            "publish_request_id": str(request.get("id") or ""),
            "note": "Remote push and PR creation require Vault/Core Secrets delivery in a trusted runtime.",
        }
    return {"provider": str(site.get("source_provider") or "manual"), "snapshot": "workspace_revision"}


def _should_publish_to_github(site: dict[str, object], publish_target: dict[str, object] | None) -> bool:
    ref = site.get("source_artifact_ref") if isinstance(site.get("source_artifact_ref"), dict) else {}
    if ref.get("provider") != "github":
        return False
    return not publish_target or publish_target.get("kind") == "git_pull_request"


def _publish_target_for_environment(data_root: Path, site: dict[str, object], environment: dict[str, object]) -> dict[str, object] | None:
    target_id = str(environment.get("publish_target_id") or "").strip()
    if target_id:
        target = get_publish_target(data_root, target_id, site_id=site["id"])
        if target["status"] != "active":
            raise ValueError(f"publish target `{target_id}` is {target['status']}")
        return target
    return None


def _create_static_build_artifact(data_root: Path, site: dict[str, object], build_id: str) -> dict[str, object]:
    artifact_root = data_root / "sites" / str(site["id"]) / "builds" / build_id / "public"
    copy_tree_snapshot(_source_root(data_root, str(site["id"])), artifact_root)
    entrypoint = "index.html" if (artifact_root / "index.html").exists() else ""
    return {
        "provider": "website-studio",
        "kind": "static_preview_artifact",
        "build_id": build_id,
        "artifact_root": artifact_root.relative_to(data_root).as_posix(),
        "entrypoint": entrypoint,
        "platform_surface": "website_studio_preview_runtime",
    }


def _publish_to_managed_static_artifact(
    data_root: Path,
    site: dict[str, object],
    request: dict[str, object],
    revision: dict[str, object],
    environment: dict[str, object],
    publish_target: dict[str, object] | None,
) -> dict[str, object]:
    target = publish_target or configure_publish_target(data_root, site["id"], environment_id=environment["id"], kind="managed_static")
    artifact_id = f"artifact_{uuid4().hex[:16]}"
    artifact_root = data_root / "sites" / str(site["id"]) / "deployments" / artifact_id / "public"
    copy_tree_snapshot(_source_root(data_root, str(site["id"])), artifact_root)
    relative_root = artifact_root.relative_to(data_root).as_posix()
    index_path = artifact_root / "index.html"
    artifact_url = f"/app/website-studio/sites/{site['id']}/deployments/{artifact_id}/"
    platform_binding_status = str((target.get("config") or {}).get("platform_binding_status") or "pending_generic_surface")
    target_config = target.get("config") if isinstance(target.get("config"), dict) else {}
    platform_binding = managed_static_platform_binding(
        status=platform_binding_status,
        artifact_url=artifact_url,
        public_url=str(target_config.get("public_url") or ""),
        custom_domain=str(target_config.get("custom_domain") or ""),
        certificate_status=str(target_config.get("certificate_status") or ""),
        cache_policy=str(target_config.get("cache_policy") or ""),
        cdn_status=str(target_config.get("cdn_status") or ""),
        verification_status=str(target_config.get("verification_status") or ""),
    )
    return {
        "provider": "maverick-managed-static",
        "status": "artifact_ready",
        "publish_target_id": str(target.get("id") or ""),
        "environment_id": str(environment.get("id") or ""),
        "publish_request_id": str(request.get("id") or ""),
        "revision_id": str(revision.get("id") or ""),
        "artifact_id": artifact_id,
        "artifact_root": relative_root,
        "entrypoint": "index.html" if index_path.exists() else "",
        "artifact_url": artifact_url,
        "public_url": platform_binding["public_url"],
        "custom_domain": platform_binding["custom_domain"],
        "platform_surface": "generic_static_hosting",
        "platform_binding_status": platform_binding_status,
        "platform_binding": platform_binding,
    }


def _github_publish_context(
    data_root: Path,
    site: dict[str, object],
    *,
    app_secrets: dict[str, object],
    app_secret_errors: list[dict[str, object]],
) -> dict[str, object]:
    ref = site.get("source_artifact_ref") if isinstance(site.get("source_artifact_ref"), dict) else {}
    if ref.get("provider") != "github":
        return {}
    connection_id = str(ref.get("connection_id") or "").strip()
    if not connection_id:
        return {"blocked": True, "detail": "GitHub publishing requires a configured Website Studio Git connection."}
    connection = get_git_connection(data_root, connection_id)
    if connection.get("status") != "grant_configured":
        return {
            "blocked": True,
            "detail": "GitHub publishing requires an active Vault/Core Secrets grant on the selected Git connection.",
            "connection": connection,
        }
    logical_name = str(connection.get("secret_logical_name") or "github-token").strip()
    if logical_name in _secret_error_names(app_secret_errors):
        return {"blocked": True, "detail": f"Core Secrets did not deliver `{logical_name}` to the Website Studio backend.", "connection": connection}
    token = str((app_secrets or {}).get(logical_name) or "").strip()
    if not token:
        return {"blocked": True, "detail": f"GitHub publish requires Vault/Core Secrets delivery for `{logical_name}`.", "connection": connection}
    return {"connection": connection, "token": token}


def _secret_error_names(app_secret_errors: list[dict[str, object]] | None) -> set[str]:
    names: set[str] = set()
    for item in app_secret_errors or []:
        if isinstance(item, dict) and item.get("logical_name"):
            names.add(str(item["logical_name"]))
    return names


def _select_context_site(data_root: Path, site_id: object = None) -> dict[str, object] | None:
    if site_id:
        site = get_site(data_root, site_id)
        return None if site.get("status") == "archived" else site
    sites = list_sites(data_root)
    active_id = get_active_site_id(data_root)
    return next(
        (
            item
            for item in sites
            if item["id"] == active_id and item.get("status") != "archived"
        ),
        next((item for item in sites if item.get("status") != "archived"), None),
    )


def _page_row(row) -> dict[str, object]:
    payload = dict(row)
    payload["source_files"] = json.loads(payload.pop("source_files_json") or "[]")
    payload["asset_refs"] = json.loads(payload.pop("asset_refs_json") or "[]")
    payload["warnings"] = json.loads(payload.pop("warnings_json") or "[]")
    payload["seo"] = json.loads(payload.pop("seo_json") or "{}")
    return payload


def _route_row(row) -> dict[str, object]:
    payload = dict(row)
    payload["source_files"] = json.loads(payload.pop("source_files_json") or "[]")
    payload["warnings"] = json.loads(payload.pop("warnings_json") or "[]")
    return payload


def _asset_row(row) -> dict[str, object]:
    payload = dict(row)
    payload["referenced_by"] = json.loads(payload.pop("referenced_by_json") or "[]")
    payload["warnings"] = json.loads(payload.pop("warnings_json") or "[]")
    return payload


def _reference_payload(entity_type: str, payload: dict[str, object]) -> dict[str, object]:
    item = {"entity_type": entity_type, **payload}
    app_page = _reference_app_page(entity_type, str(item.get("id") or ""))
    if app_page:
        item["app_page"] = app_page
        item["deep_link"] = f"/app/website-studio/{app_page}"
    return item


def _reference_app_page(entity_type: str, entity_id: str) -> str:
    if not entity_id:
        return ""
    segments = {
        "site": "sites",
        "page": "pages",
        "route": "routes",
        "component": "components",
        "asset": "assets",
        "revision": "revisions",
        "publish_request": "publish-requests",
    }
    segment = segments.get(entity_type)
    return f"{segment}/{entity_id}" if segment else ""


def _component_reference_search(data_root: Path, query: object = "", site_id: object = None) -> list[dict[str, object]]:
    components: list[dict[str, object]] = []
    sites = [get_site(data_root, site_id)] if site_id else [site for site in list_sites(data_root) if site.get("status") != "archived"]
    for site in sites[:25]:
        try:
            navigation = navigation_analyze(data_root, site["id"])
        except ValueError:
            continue
        for component in navigation.get("components", []) or []:
            if isinstance(component, dict) and component_matches_query(component, str(query or "")):
                components.append(_component_reference_payload(site, component))
                if len(components) >= 50:
                    return components
    return components


def _component_reference_payload(site: dict[str, object], component: dict[str, object]) -> dict[str, object]:
    return _reference_payload(
        "component",
        {
            "id": component.get("id") or "",
            "site_id": site.get("id") or "",
            "display_name": component.get("label") or component.get("selector") or component.get("id") or "",
            "label": component.get("label") or "",
            "route": component.get("route") or "",
            "selector": component.get("selector") or "",
            "source_files": list(component.get("source_files") or [])[:8],
            "confidence": component.get("confidence") or "",
            "last_report_id": component.get("last_report_id") or "",
        },
    )


def _get_component(data_root: Path, component_id: object) -> dict[str, object]:
    clean_id = _required_id(component_id, "component_id")
    for site in [item for item in list_sites(data_root) if item.get("status") != "archived"]:
        navigation = navigation_analyze(data_root, site["id"])
        for component in navigation.get("components", []) or []:
            if isinstance(component, dict) and component.get("id") == clean_id:
                return {
                    "id": clean_id,
                    "site_id": site["id"],
                    "display_name": component.get("label") or clean_id,
                    "label": component.get("label") or "",
                    "route": component.get("route") or "",
                    "selector": component.get("selector") or "",
                    "source_files": list(component.get("source_files") or [])[:8],
                    "confidence": component.get("confidence") or "",
                    "last_report_id": component.get("last_report_id") or "",
                }
    raise ValueError(f"component `{clean_id}` was not found")


def _source_asset_paths(source_root: Path) -> set[str]:
    if not source_root.exists():
        return set()
    assets: set[str] = set()
    for path in source_root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in {".html", ".htm"}:
            continue
        rel_path = path.relative_to(source_root).as_posix()
        assets.add(rel_path)
    return assets


def _asset_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg", ".ico"}:
        return "image"
    if suffix == ".css":
        return "stylesheet"
    if suffix in {".js", ".jsx", ".ts", ".tsx"}:
        return "script"
    if suffix in {".woff", ".woff2", ".ttf", ".otf"}:
        return "font"
    if suffix in {".mp4", ".webm", ".ogg", ".ogv", ".mov"}:
        return "video"
    if suffix in {".mp3", ".oga", ".wav"}:
        return "audio"
    return "file"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_artifact_ref(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    allowed = {"app_id", "file_id", "workspace_relative_path", "role", "relative_path", "name", "content_type", "sha256"}
    return {key: str(value.get(key) or "") for key in allowed if value.get(key)}


def _git_import_source_ref(data_root: Path, site: dict[str, object], source: str, branch: str) -> dict[str, object]:
    label = _redacted_git_source_label(source, branch)
    fallback = {"provider": "git", "source": source, "source_label": label, "branch": branch or ""}
    try:
        owner, repo, _normalized_url = _parse_github_repository(source)
    except ValueError:
        return fallback
    connection_id = _connection_id(owner, repo)
    try:
        connection = get_git_connection(data_root, connection_id)
    except ValueError:
        return fallback
    if connection.get("site_id") != site.get("id"):
        return fallback
    return {
        "provider": "github",
        "owner": owner,
        "repo": repo,
        "repository_url": f"https://github.com/{owner}/{repo}.git",
        "connection_id": connection_id,
        "base_branch": branch or str(connection.get("base_branch") or "main"),
        "auth_mode": str(connection.get("auth_mode") or "fine_grained_token"),
        "source_label": label,
    }


def _sync_source_locator(site: dict[str, object], branch: object = None) -> tuple[str, str]:
    if site.get("source_provider") != "git":
        raise ValueError("sync_source is currently supported only for Git-backed sites; CMS and commerce sync are later phases")
    ref = site.get("source_artifact_ref") if isinstance(site.get("source_artifact_ref"), dict) else {}
    provider = str(ref.get("provider") or "").strip()
    branch_value = str(branch or ref.get("base_branch") or ref.get("branch") or "").strip()
    clean_branch = _clean_git_branch(branch_value) if branch_value else ""
    if provider == "github":
        owner = str(ref.get("owner") or "").strip()
        repo = str(ref.get("repo") or "").strip()
        if not owner or not repo:
            raise ValueError("GitHub sync requires owner and repo in the site's source reference")
        return f"https://github.com/{owner}/{repo}.git", clean_branch
    if provider == "git":
        source = str(ref.get("source") or "").strip()
        if not source:
            raise ValueError("Git sync requires a retained source reference; re-import the repository to enable sync")
        return source, clean_branch
    raise ValueError("sync_source requires a Git source reference")


def _record_sync_run(
    data_root: Path,
    site_id: object,
    *,
    source_provider: str,
    status: str,
    branch: str,
    files_changed_count: int,
    conflicts: list[dict[str, object]],
    source_profile: dict[str, object],
    logs_summary: str,
) -> dict[str, object]:
    sync_id = f"sync_{uuid4().hex[:16]}"
    now = now_timestamp()
    with connect(data_root) as db:
        db.execute(
            """
            INSERT INTO sync_runs(
              id, site_id, source_provider, status, branch, files_changed_count,
              conflicts_json, source_profile_json, logs_summary, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sync_id,
                str(site_id),
                source_provider,
                status,
                branch,
                files_changed_count,
                json.dumps(conflicts[:100]),
                json.dumps(source_profile, sort_keys=True),
                logs_summary,
                now,
                now,
            ),
        )
        row = db.execute("SELECT * FROM sync_runs WHERE id = ?", (sync_id,)).fetchone()
    return _sync_run_row(row)


def _git_import_auth_context(
    data_root: Path,
    site: dict[str, object] | None,
    source: str,
    *,
    app_secrets: dict[str, object],
    app_secret_errors: list[dict[str, object]],
) -> dict[str, object]:
    try:
        owner, repo, _normalized_url = _parse_github_repository(source)
    except ValueError:
        return {}
    try:
        connection = get_git_connection(data_root, _connection_id(owner, repo))
    except ValueError:
        return {}
    if site is not None and connection.get("site_id") != site.get("id"):
        return {}
    logical_name = str(connection.get("secret_logical_name") or "github-token").strip()
    if logical_name in _secret_error_names(app_secret_errors):
        if connection.get("status") == "grant_configured":
            raise ValueError(f"Core Secrets did not deliver `{logical_name}` to the Website Studio backend for Git import.")
        return {}
    token = str((app_secrets or {}).get(logical_name) or "").strip()
    if not token and connection.get("status") == "grant_configured":
        raise ValueError(f"GitHub private import requires Vault/Core Secrets delivery for `{logical_name}`.")
    if not token:
        return {}
    return {"connection": connection, "token": token}


def _mark_git_connection_runtime_grant(data_root: Path, connection: dict[str, object]) -> None:
    if connection.get("status") == "grant_configured":
        return
    now = now_timestamp()
    with connect(data_root) as db:
        db.execute(
            "UPDATE git_connections SET status = 'grant_configured', updated_at = ? WHERE id = ?",
            (now, connection["id"]),
        )
    _audit(
        data_root,
        str(connection.get("site_id") or ""),
        "git.connection.runtime_secret_delivered",
        f"Core Secrets delivered GitHub credentials for {connection['owner']}/{connection['repo']}",
        {"connection_id": connection["id"], "secret_logical_name": connection.get("secret_logical_name") or "github-token"},
    )


def _git_connection_row(row) -> dict[str, object]:
    payload = dict(row)
    payload["secret_configured"] = bool(payload.get("secret_logical_name"))
    payload["vault_requirements"] = _vault_requirement_payload(str(payload["auth_mode"]), str(payload["secret_logical_name"]), str(payload["id"]))
    return payload


def _parse_github_repository(repository_url: object) -> tuple[str, str, str]:
    raw = str(repository_url or "").strip()
    if not raw:
        raise ValueError("repository_url is required")
    if raw.startswith("-"):
        raise ValueError("repository_url is invalid")
    owner = ""
    repo = ""
    parsed = urlparse(raw)
    if parsed.scheme == "https" and "@" in parsed.netloc:
        raise ValueError("repository_url must not include inline credentials")
    if parsed.scheme == "https" and parsed.netloc.lower() == "github.com":
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(parts) == 2:
            owner, repo = parts
    elif not parsed.scheme and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?", raw):
        owner, repo = raw.split("/", 1)
    if not owner or not repo:
        raise ValueError("repository_url must be a GitHub HTTPS URL or owner/repo")
    repo = repo.removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]+", repo):
        raise ValueError("repository owner or name contains unsupported characters")
    return owner, repo, f"https://github.com/{owner}/{repo}.git"


def _clean_git_branch(value: object) -> str:
    branch = str(value or "main").strip()
    if branch.startswith("-") or ".." in branch or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,180}", branch):
        raise ValueError("base_branch contains unsupported characters")
    return branch


def _connection_id(owner: str, repo: str) -> str:
    return f"git_{sha256_text(f'github/{owner}/{repo}')[:16]}"


def _vault_requirements_for_git_mode(auth_mode: str) -> list[str]:
    if auth_mode == "fine_grained_token":
        return ["github-token"]
    return []


def _vault_requirement_payload(auth_mode: str, logical_name: str, connection_id: str) -> dict[str, object]:
    required = _vault_requirements_for_git_mode(auth_mode)
    return {
        "auth_mode": auth_mode,
        "required_secrets": required,
        "selected_logical_name": logical_name,
        "resource_type": "git_connection",
        "resource_id": connection_id,
        "delivery_target": "maverick://app.backend/backend",
        "delivery_targets": [
            "maverick://app.backend/backend",
            "maverick://app.backend/cli/website-studio",
            "maverick://app.backend/mcp/website-import-git",
            "maverick://app.backend/mcp/website-publish",
        ],
        "status": "grant_required",
    }


def _get_page(data_root: Path, page_id: object) -> dict[str, object]:
    clean_id = _required_id(page_id, "page_id")
    ensure_schema(data_root)
    with connect(data_root) as db:
        row = db.execute("SELECT * FROM pages WHERE id = ? AND deleted_at IS NULL", (clean_id,)).fetchone()
    if row is None:
        raise ValueError(f"page `{clean_id}` was not found")
    return _page_row(row)


def _get_route(data_root: Path, route_id: object) -> dict[str, object]:
    clean_id = _required_id(route_id, "route_id")
    ensure_schema(data_root)
    with connect(data_root) as db:
        row = db.execute("SELECT * FROM routes WHERE id = ? AND deleted_at IS NULL", (clean_id,)).fetchone()
    if row is None:
        raise ValueError(f"route `{clean_id}` was not found")
    return _route_row(row)


def _get_asset(data_root: Path, asset_id: object) -> dict[str, object]:
    clean_id = _required_id(asset_id, "asset_id")
    ensure_schema(data_root)
    with connect(data_root) as db:
        row = db.execute("SELECT * FROM assets WHERE id = ? AND deleted_at IS NULL", (clean_id,)).fetchone()
    if row is None:
        raise ValueError(f"asset `{clean_id}` was not found")
    return _asset_row(row)


def _revision_snapshot(data_root: Path, revision_id: object) -> dict[str, str]:
    if not revision_id:
        return {}
    return get_revision(data_root, revision_id)["snapshot"]


def _unique_slug(data_root: Path, raw_slug: str, *, exclude_site_id: str | None = None) -> str:
    base = slugify(raw_slug)
    ensure_schema(data_root)
    with connect(data_root) as db:
        existing = {
            row["slug"]
            for row in db.execute("SELECT id, slug FROM sites").fetchall()
            if not exclude_site_id or row["id"] != exclude_site_id
        }
    slug = base
    counter = 2
    while slug in existing:
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def _write_starter_site(source_root: Path, display_name: str) -> None:
    write_text_file(
        source_root / "index.html",
        f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{display_name}</title>
    <link rel="stylesheet" href="assets/styles.css">
  </head>
  <body>
    <main>
      <h1>{display_name}</h1>
      <p>This working website source is managed by Website Studio.</p>
    </main>
  </body>
</html>
""",
    )
    write_text_file(source_root / "assets/styles.css", "body { font-family: system-ui, sans-serif; margin: 3rem; }\n")


def _route_from_html_path(rel_path: str) -> str:
    if rel_path in {"index.html", "index.htm"}:
        return "/"
    route = rel_path.rsplit(".", 1)[0]
    if route.endswith("/index"):
        route = route[: -len("/index")]
    return "/" + route.strip("/")


def _html_title(path: Path) -> str:
    return _html_title_from_text(read_text_file(path))


def _html_title_from_text(text: str) -> str:
    lower = text.lower()
    start = lower.find("<title>")
    end = lower.find("</title>")
    if start == -1 or end == -1 or end <= start:
        return ""
    return text[start + 7 : end].strip()


def _html_seo(text: str) -> dict[str, str]:
    seo: dict[str, str] = {}
    for match in re.finditer(r"(?is)<meta\b[^>]*>", text):
        attrs = _html_attrs(match.group(0))
        name = (attrs.get("name") or attrs.get("property") or "").lower()
        content = attrs.get("content", "").strip()
        if not content:
            continue
        if name in {"description", "og:title", "og:description"}:
            seo[name.replace(":", "_")] = content[:500]
    for match in re.finditer(r"(?is)<link\b[^>]*>", text):
        attrs = _html_attrs(match.group(0))
        if attrs.get("rel", "").lower() == "canonical" and attrs.get("href"):
            seo["canonical"] = attrs["href"].strip()[:500]
            break
    return seo


def _html_attrs(tag: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in re.finditer(r"(?is)\b([a-z0-9_-]+)\s*=\s*([\"'])(.*?)\2", tag):
        attrs[match.group(1).lower()] = match.group(3)
    return attrs


def _extra_static_routes(source_root: Path, indexed_routes: set[str]) -> list[tuple[str, str, str, list[str]]]:
    extras: list[tuple[str, str, str, list[str]]] = []
    seen = set(indexed_routes)
    for route in _routes_from_sitemap_xml(source_root / "sitemap.xml"):
        if route in seen:
            continue
        seen.add(route)
        extras.append((route, "sitemap", "sitemap.xml", ["route listed in sitemap.xml without matching HTML source"]))
    for route, target, status in _routes_from_redirects(source_root / "_redirects"):
        if route in seen:
            continue
        seen.add(route)
        extras.append((route, "redirect", "_redirects", [f"redirects to {target} ({status})"]))
    return extras


def _routes_from_sitemap_xml(path: Path) -> list[str]:
    if not path.exists() or path.stat().st_size > 1024 * 1024:
        return []
    try:
        root = ET.fromstring(read_text_file(path))
    except (ET.ParseError, ValueError):
        return []
    routes: list[str] = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "loc" or not element.text:
            continue
        route = _route_from_url_path(element.text.strip())
        if route and route not in routes:
            routes.append(route)
    return routes


def _routes_from_redirects(path: Path) -> list[tuple[str, str, str]]:
    if not path.exists() or path.stat().st_size > 256 * 1024:
        return []
    routes: list[tuple[str, str, str]] = []
    try:
        text = read_text_file(path)
    except ValueError:
        return []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2 or not parts[0].startswith("/"):
            continue
        route = _route_from_url_path(parts[0])
        target = parts[1]
        status = parts[2] if len(parts) > 2 and parts[2].isdigit() else "301"
        if route and route not in {item[0] for item in routes}:
            routes.append((route, target, status))
    return routes


def _route_from_url_path(value: str) -> str:
    path = value.strip()
    if not path:
        return ""
    if "://" in path:
        path = "/" + path.split("://", 1)[1].split("/", 1)[1] if "/" in path.split("://", 1)[1] else "/"
    path = path.split("?", 1)[0].split("#", 1)[0]
    if not path.startswith("/"):
        return ""
    return "/" + path.strip("/")


def _set_active_revision(data_root: Path, site_id: object, revision_id: object) -> None:
    _update_site(data_root, site_id, active_revision_id=str(revision_id))


def _update_site(data_root: Path, site_id: object, **fields: object) -> None:
    allowed = {
        "source_provider",
        "source_label",
        "source_shape",
        "source_profile_json",
        "source_version",
        "source_artifact_ref_json",
        "default_environment_id",
        "working_branch",
        "active_revision_id",
        "published_revision_id",
        "status",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return
    updates["updated_at"] = now_timestamp()
    sql = ", ".join(f"{key} = ?" for key in updates)
    with connect(data_root) as db:
        db.execute(f"UPDATE sites SET {sql} WHERE id = ?", [*updates.values(), str(site_id)])


def _upsert_changeset(data_root: Path, site_id: object, summary: str) -> dict[str, object]:
    site = get_site(data_root, site_id)
    diff_payload = diff_site(data_root, site["id"])
    now = now_timestamp()
    with connect(data_root) as db:
        row = db.execute(
            "SELECT * FROM changesets WHERE site_id = ? AND status = 'draft' ORDER BY updated_at DESC LIMIT 1",
            (site["id"],),
        ).fetchone()
        if row:
            db.execute(
                "UPDATE changesets SET summary = ?, files_changed_count = ?, updated_at = ? WHERE id = ?",
                (summary, len(diff_payload["files"]), now, row["id"]),
            )
            changeset_id = row["id"]
        else:
            changeset_id = f"chg_{uuid4().hex[:16]}"
            db.execute(
                """
                INSERT INTO changesets(id, site_id, base_revision_id, status, summary, files_changed_count, created_at, updated_at)
                VALUES (?, ?, ?, 'draft', ?, ?, ?, ?)
                """,
                (changeset_id, site["id"], site.get("active_revision_id"), summary, len(diff_payload["files"]), now, now),
            )
        changed = db.execute("SELECT * FROM changesets WHERE id = ?", (changeset_id,)).fetchone()
    return dict(changed)


def _audit(data_root: Path, site_id: str | None, event_type: str, summary: str, metadata: dict[str, object] | None = None) -> None:
    ensure_schema(data_root)
    with connect(data_root) as db:
        db.execute(
            "INSERT INTO audit_events(id, site_id, event_type, summary, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (f"audit_{uuid4().hex[:16]}", site_id, event_type, summary, json.dumps(metadata or {}, sort_keys=True), now_timestamp()),
        )


def _default_view_filter() -> dict[str, object]:
    return {"mode": "search", "query": "", "site_id": "", "refs": [], "updated_at": None}


def _write_view_state(data_root: Path, view_filter: dict[str, object], *, active_site_id: str | None = None) -> dict[str, object]:
    data_root.mkdir(parents=True, exist_ok=True)
    current = load_view_state(data_root)
    state = {
        "schema_version": "1",
        "active_site_id": str(current.get("active_site_id") if active_site_id is None else active_site_id),
        "view_filter": view_filter,
    }
    (data_root / "view_state.json").write_text(json.dumps(state, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return state


def _run_git_clone(source: str, branch: str, destination: Path, *, token: object = None) -> None:
    command = ["git", "clone", "--depth", "1"]
    if branch:
        command.extend(["--branch", branch])
    command.extend([source, str(destination)])
    clean_token = str(token or "").strip()
    askpass_path = _write_git_askpass(destination.parent) if clean_token else None
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=90,
            env=_git_import_env(token=clean_token, askpass_path=askpass_path),
        )
    except FileNotFoundError as error:
        raise ValueError("git executable is not available for Website Studio import") from error
    except subprocess.TimeoutExpired as error:
        raise ValueError("git import timed out") from error
    except subprocess.CalledProcessError as error:
        detail = _redact_git_clone_error(error.stderr or error.stdout or "git clone failed", clean_token)
        raise ValueError(f"git import failed: {detail.strip()[:400]}") from error


def _display_name_from_git_source(source: str) -> str:
    name = Path(source.rstrip("/")).name or "Git Website"
    return name.removesuffix(".git").replace("-", " ").replace("_", " ").strip().title() or "Git Website"


def _redacted_git_source_label(source: str, branch: str) -> str:
    label = _redact_secret_text(source)
    return f"{label}#{branch}" if branch else label


def _write_git_askpass(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "git-askpass.sh"
    path.write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "  *Username*) printf '%s\\n' \"${WEBSITE_STUDIO_GIT_USERNAME:-x-access-token}\" ;;\n"
        "  *) printf '%s\\n' \"${WEBSITE_STUDIO_GIT_TOKEN:-}\" ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    path.chmod(0o700)
    return path


def _normalize_git_import_file_modes(source_root: Path) -> None:
    for path in source_root.rglob("*"):
        if path.is_file() and not path.is_symlink():
            path.chmod(path.stat().st_mode & ~0o111)


def _redact_git_clone_error(value: str, token: str = "") -> str:
    text = _redact_secret_text(value)
    if token:
        text = text.replace(token, "<redacted>")
    return text


def _git_import_env(*, token: str = "", askpass_path: Path | None = None) -> dict[str, str]:
    env = {
        "GIT_ASKPASS": "true",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "PATH": os.environ.get("PATH", ""),
    }
    if token and askpass_path is not None:
        env["GIT_ASKPASS"] = str(askpass_path)
        env["WEBSITE_STUDIO_GIT_USERNAME"] = "x-access-token"
        env["WEBSITE_STUDIO_GIT_TOKEN"] = token
    for key in ("LANG", "LC_ALL", "TMPDIR"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env
