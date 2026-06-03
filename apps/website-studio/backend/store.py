"""Website Studio domain store."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import difflib
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from uuid import uuid4

from database import REFERENCE_ENTITIES, connect, ensure_schema, now_timestamp
from safety import (
    asset_references_from_html,
    classify_source_tree,
    copy_tree_snapshot,
    detect_content_type,
    extract_zip_base64,
    preview_srcdoc_html,
    read_text_file,
    resolve_site_path,
    safe_relative_path,
    sha256_text,
    slugify,
    snapshot_text_files,
    validate_editable_text_path,
    validate_git_source,
    validate_source_tree_for_phase1,
    write_text_file,
)


def list_sites(data_root: Path) -> list[dict[str, object]]:
    ensure_schema(data_root)
    with connect(data_root) as db:
        rows = db.execute("SELECT * FROM sites ORDER BY updated_at DESC").fetchall()
    return [_site_row(row) for row in rows]


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
            (site_id, name, clean_slug, str(primary_domain or "").strip(), str(source_provider or "manual"), now, now),
        )
    _write_starter_site(_source_root(data_root, site_id), name)
    rebuild_index(data_root, site_id)
    revision = create_revision(data_root, site_id, label="Initial working copy", source="create_site")
    _set_active_revision(data_root, site_id, revision["id"])
    _audit(data_root, site_id, "site.created", f"Created site {name}")
    return get_site(data_root, site_id)


def get_site(data_root: Path, site_id: object) -> dict[str, object]:
    clean_id = _required_id(site_id, "site_id")
    ensure_schema(data_root)
    with connect(data_root) as db:
        row = db.execute("SELECT * FROM sites WHERE id = ?", (clean_id,)).fetchone()
    if row is None:
        raise ValueError(f"site `{clean_id}` was not found")
    return _site_row(row)


def site_status(data_root: Path, site_id: object) -> dict[str, object]:
    site = get_site(data_root, site_id)
    pages = sitemap(data_root, site["id"])
    diff_payload = diff_site(data_root, site["id"])
    return {
        "site": site,
        "page_count": len(pages["items"]),
        "route_count": len(pages.get("routes", [])),
        "asset_count": len(pages.get("assets", [])),
        "changed_files_count": len(diff_payload["files"]),
        "active_revision_id": site.get("active_revision_id"),
        "published_revision_id": site.get("published_revision_id"),
    }


def archive_site(data_root: Path, site_id: object) -> dict[str, object]:
    site = get_site(data_root, site_id)
    now = now_timestamp()
    with connect(data_root) as db:
        db.execute("UPDATE sites SET status = 'archived', archived_at = ?, updated_at = ? WHERE id = ?", (now, now, site["id"]))
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
            rebuild_index(data_root, site["id"])
            revision = create_revision(data_root, site["id"], label="ZIP import", source="zip_import")
            _set_active_revision(data_root, site["id"], revision["id"])
            artifact_ref = _source_artifact_ref(source_artifact_ref)
            _update_site(
                data_root,
                site["id"],
                source_provider="zip",
                source_label="ZIP import",
                source_shape=import_result.get("source_shape") or "partial_source",
                source_artifact_ref_json=json.dumps(artifact_ref, sort_keys=True),
            )
            _audit(data_root, site["id"], "site.import_zip", f"Imported {import_result['files_extracted']} ZIP files", {"source_artifact_ref": artifact_ref})
    finally:
        if temp_root.exists():
            shutil.rmtree(temp_root)
    return {"site": get_site(data_root, site["id"]), "import": import_result, "revision": revision}


def import_git(
    data_root: Path,
    *,
    site_id: object = None,
    display_name: object = None,
    repository_url: object,
    branch: object = None,
) -> dict[str, object]:
    source, clean_branch = validate_git_source(repository_url, branch, data_root=data_root)
    site = get_site(data_root, site_id) if site_id else None
    temp_root = data_root / ".tmp" / f"git_import_{uuid4().hex}"
    clone_root = temp_root / "repo"
    try:
        _run_git_clone(source, clean_branch, clone_root)
        clone_git = clone_root / ".git"
        if clone_git.exists():
            shutil.rmtree(clone_git)
        validate_source_tree_for_phase1(clone_root)
        source_shape = classify_source_tree(clone_root)
        if site is None:
            site = create_site(data_root, display_name=display_name or _display_name_from_git_source(source), source_provider="git")
        with _site_mutation_lock(data_root, str(site["id"])):
            source_root = _source_root(data_root, str(site["id"]))
            if source_root.exists():
                shutil.rmtree(source_root)
            source_root.parent.mkdir(parents=True, exist_ok=True)
            clone_root.rename(source_root)
            rebuild_index(data_root, site["id"])
            revision = create_revision(data_root, site["id"], label="Git import", source="git_import")
            _set_active_revision(data_root, site["id"], revision["id"])
            _update_site(
                data_root,
                site["id"],
                source_provider="git",
                source_label=_redacted_git_source_label(source, clean_branch),
                source_shape=source_shape,
                source_artifact_ref_json=json.dumps({"provider": "git", "source_label": _redacted_git_source_label(source, clean_branch), "branch": clean_branch or ""}, sort_keys=True),
            )
            _audit(data_root, site["id"], "site.import_git", "Imported Git repository", {"branch": clean_branch or ""})
    finally:
        if temp_root.exists():
            shutil.rmtree(temp_root)
    return {
        "site": get_site(data_root, site["id"]),
        "import": {"source_provider": "git", "branch": clean_branch or "", "source_label": _redacted_git_source_label(source, clean_branch)},
        "revision": revision,
    }


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
                ON CONFLICT(id) DO UPDATE SET
                  route=excluded.route,
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
                ON CONFLICT(id) DO UPDATE SET
                  route=excluded.route,
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
    pages = [_page_row(row) for row in rows]
    return {"site_id": site["id"], "items": pages}


def sitemap(data_root: Path, site_id: object) -> dict[str, object]:
    rebuild_index(data_root, site_id)
    with connect(data_root) as db:
        page_rows = db.execute(
            "SELECT * FROM pages WHERE site_id = ? AND deleted_at IS NULL ORDER BY route",
            (_required_id(site_id, "site_id"),),
        ).fetchall()
        route_rows = db.execute(
            "SELECT * FROM routes WHERE site_id = ? AND deleted_at IS NULL ORDER BY route",
            (_required_id(site_id, "site_id"),),
        ).fetchall()
        asset_rows = db.execute(
            "SELECT * FROM assets WHERE site_id = ? AND deleted_at IS NULL ORDER BY path",
            (_required_id(site_id, "site_id"),),
        ).fetchall()
    return {
        "site_id": str(site_id),
        "items": [_page_row(row) for row in page_rows],
        "routes": [_route_row(row) for row in route_rows],
        "assets": [_asset_row(row) for row in asset_rows],
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
        [{"entity_type": "site", **_site_row(row)} for row in site_rows]
        + [{"entity_type": "page", **_page_row(row)} for row in page_rows]
        + [{"entity_type": "route", **_route_row(row)} for row in route_rows]
        + [{"entity_type": "asset", **_asset_row(row)} for row in asset_rows]
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


def build_preview(data_root: Path, site_id: object, route: object = "/") -> dict[str, object]:
    site = get_site(data_root, site_id)
    pages = sitemap(data_root, site["id"])["items"]
    route_text = str(route or "/")
    page = next((item for item in pages if item["route"] == route_text), pages[0] if pages else None)
    if not page:
        raise ValueError("site has no HTML page to preview")
    rel_path = page["source_files"][0]
    html = read_file(data_root, site_id=site_id, path=rel_path)["content"]
    preview_id = f"preview_{uuid4().hex[:12]}"
    _audit(data_root, str(site_id), "preview.build", f"Built static preview for {route_text}", {"preview_id": preview_id})
    return {
        "preview_id": preview_id,
        "site_id": str(site["id"]),
        "route": page["route"],
        "page_id": page["id"],
        "asset_refs": page.get("asset_refs", []),
        "warnings": page.get("warnings", []),
        "html": preview_srcdoc_html(html, source_root=_source_root(data_root, str(site["id"])), page_path=rel_path),
    }


def create_publish_request(data_root: Path, site_id: object, requested_by: object = "workspace") -> dict[str, object]:
    diff_payload = diff_site(data_root, site_id)
    now = now_timestamp()
    request_id = f"pub_{uuid4().hex[:16]}"
    summary = f"{len(diff_payload['files'])} changed files"
    changeset = _upsert_changeset(data_root, site_id, summary)
    with connect(data_root) as db:
        db.execute(
            """
            INSERT INTO publish_requests(id, site_id, changeset_id, status, diff_summary, requested_by, created_at, updated_at)
            VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)
            """,
            (request_id, str(site_id), changeset["id"], summary, str(requested_by or "workspace"), now, now),
        )
    _audit(data_root, str(site_id), "publish.requested", summary, {"publish_request_id": request_id})
    return get_publish_request(data_root, request_id)


def publish(data_root: Path, site_id: object, publish_request_id: object = None, approval_id: object = None) -> dict[str, object]:
    request = get_publish_request(data_root, publish_request_id) if publish_request_id else None
    if not approval_id:
        return {"blocked": True, "status": "blocked", "detail": "Publishing requires a verified human approval."}
    if request and request["site_id"] != str(site_id):
        raise ValueError("publish request does not belong to the selected site")
    return {
        "blocked": True,
        "status": "blocked",
        "detail": "Publishing is blocked until Website Studio can validate approval ids through an official approval surface.",
        "publish_request": request,
    }


def rollback(data_root: Path, site_id: object, revision_id: object, *, approval_id: object = None, confirm: object = False) -> dict[str, object]:
    if not approval_id or confirm is not True:
        return {
            "blocked": True,
            "status": "blocked",
            "detail": "Rollback requires approval_id and confirm=true because it replaces the selected working source tree.",
        }
    return {
        "blocked": True,
        "status": "blocked",
        "detail": "Rollback is blocked until Website Studio can validate approval ids through an official approval surface.",
    }


def active_context(data_root: Path, site_id: object = None, page_id: object = None) -> dict[str, object]:
    sites = list_sites(data_root)
    site = get_site(data_root, site_id) if site_id else (sites[0] if sites else None)
    if not site:
        return {"active_view": "empty", "site_id": None}
    map_payload = sitemap(data_root, site["id"])
    pages = map_payload["items"]
    page = next((item for item in pages if item["id"] == page_id), pages[0] if pages else None)
    diff_payload = diff_site(data_root, site["id"])
    return {
        "active_view": "page" if page else "site",
        "site_id": site["id"],
        "title": site["display_name"],
        "site": site,
        "page_id": page["id"] if page else None,
        "route": page["route"] if page else None,
        "source_files": page["source_files"] if page else [],
        "asset_refs": page.get("asset_refs", []) if page else [],
        "warnings": page.get("warnings", []) if page else [],
        "routes": map_payload.get("routes", [])[:100],
        "assets": map_payload.get("assets", [])[:200],
        "changed_files_count": len(diff_payload["files"]),
        "changed_files": [{"path": item["path"], "status": item["status"]} for item in diff_payload["files"][:100]],
        "current_revision_id": site.get("published_revision_id"),
        "working_revision_id": site.get("active_revision_id"),
    }


def reference_manifest() -> dict[str, object]:
    metadata = {
        "site": {"display_name": "Website Site", "searchable": True},
        "page": {"display_name": "Website Page", "searchable": True},
        "route": {"display_name": "Website Route", "searchable": True},
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
    return items + [{"entity_type": "publish_request", **dict(row)} for row in request_rows]


def reference_resolve(data_root: Path, entity_type: object, entity_id: object) -> dict[str, object]:
    entity = str(entity_type or "site")
    if entity == "site":
        return {"entity_type": "site", **get_site(data_root, entity_id)}
    if entity == "page":
        return {"entity_type": "page", **_get_page(data_root, entity_id)}
    if entity == "route":
        return {"entity_type": "route", **_get_route(data_root, entity_id)}
    if entity == "asset":
        return {"entity_type": "asset", **_get_asset(data_root, entity_id)}
    if entity == "revision":
        item = get_revision(data_root, entity_id)
        return {"entity_type": "revision", **{key: value for key, value in item.items() if key != "snapshot"}}
    if entity == "publish_request":
        return {"entity_type": "publish_request", **get_publish_request(data_root, entity_id)}
    raise ValueError(f"Unsupported entity_type `{entity}`")


def reference_summary(data_root: Path, entity_type: object, entity_id: object) -> dict[str, object]:
    item = reference_resolve(data_root, entity_type, entity_id)
    title = item.get("display_name") or item.get("title") or item.get("route") or item.get("path") or item.get("id")
    return {"entity_type": item["entity_type"], "entity_id": item["id"], "title": title, "summary": item.get("route") or item.get("path") or item.get("status") or ""}


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
    return get_revision(data_root, revision_id)


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
        return {"schema_version": "1", "view_filter": _default_view_filter()}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raw = {}
    return {"schema_version": "1", "view_filter": raw.get("view_filter") if isinstance(raw.get("view_filter"), dict) else _default_view_filter()}


def set_view_filter(data_root: Path, *, query: object = None, site_id: object = None, preserve_custom: bool = False) -> dict[str, object]:
    current = load_view_state(data_root)
    view_filter = dict(current.get("view_filter") or {}) if preserve_custom else _default_view_filter()
    view_filter.update({"mode": "search", "query": str(query or "").strip(), "site_id": str(site_id or ""), "updated_at": now_timestamp()})
    return _write_view_state(data_root, view_filter)


def set_custom_view(data_root: Path, *, title: object = None, refs: object = None) -> dict[str, object]:
    return _write_view_state(data_root, {"mode": "custom", "query": "", "site_id": "", "title": str(title or "Custom website view"), "refs": refs if isinstance(refs, list) else [], "updated_at": now_timestamp()})


def clear_custom_view(data_root: Path) -> dict[str, object]:
    return _write_view_state(data_root, _default_view_filter())


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


def _site_row(row) -> dict[str, object]:
    payload = dict(row)
    payload["source_artifact_ref"] = json.loads(payload.pop("source_artifact_ref_json", "{}") or "{}")
    return payload


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
    allowed = {"source_provider", "source_label", "source_shape", "source_artifact_ref_json", "active_revision_id", "published_revision_id", "status"}
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


def _write_view_state(data_root: Path, view_filter: dict[str, object]) -> dict[str, object]:
    data_root.mkdir(parents=True, exist_ok=True)
    state = {"schema_version": "1", "view_filter": view_filter}
    (data_root / "view_state.json").write_text(json.dumps(state, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return state


def _run_git_clone(source: str, branch: str, destination: Path) -> None:
    command = ["git", "clone", "--depth", "1"]
    if branch:
        command.extend(["--branch", branch])
    command.extend([source, str(destination)])
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=90,
            env=_git_import_env(),
        )
    except FileNotFoundError as error:
        raise ValueError("git executable is not available for Website Studio import") from error
    except subprocess.TimeoutExpired as error:
        raise ValueError("git import timed out") from error
    except subprocess.CalledProcessError as error:
        detail = _redact_secret_text(error.stderr or error.stdout or "git clone failed")
        raise ValueError(f"git import failed: {detail.strip()[:400]}") from error


def _display_name_from_git_source(source: str) -> str:
    name = Path(source.rstrip("/")).name or "Git Website"
    return name.removesuffix(".git").replace("-", " ").replace("_", " ").strip().title() or "Git Website"


def _redacted_git_source_label(source: str, branch: str) -> str:
    label = _redact_secret_text(source)
    return f"{label}#{branch}" if branch else label


def _redact_secret_text(value: str) -> str:
    return re.sub(r"(https?://)([^/@:\s]+):([^/@\s]+)@", r"\1***:***@", value)


def _git_import_env() -> dict[str, str]:
    env = {
        "GIT_ASKPASS": "true",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "PATH": os.environ.get("PATH", ""),
    }
    for key in ("LANG", "LC_ALL", "TMPDIR"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env
