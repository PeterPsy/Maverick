"""Operational retention for Website Studio."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

from database import connect, ensure_schema, now_timestamp


def prune_site_operational_history(
    data_root: Path,
    site_id: str,
    *,
    keep_builds: int,
    keep_previews_per_route: int,
    keep_runtime_sessions: int,
    dry_run: bool,
) -> dict[str, object]:
    """Prune build, preview, and runtime-session history for one site."""
    ensure_schema(data_root)
    with connect(data_root) as db:
        build_rows = db.execute("SELECT id FROM builds WHERE site_id = ? ORDER BY created_at DESC", (site_id,)).fetchall()
        preview_rows = db.execute(
            "SELECT id, route, runtime_kind, build_id FROM previews WHERE site_id = ? ORDER BY created_at DESC",
            (site_id,),
        ).fetchall()
        session_rows = db.execute(
            "SELECT id, preview_id FROM runtime_sessions WHERE site_id = ? ORDER BY created_at DESC",
            (site_id,),
        ).fetchall()
        publish_build_rows = db.execute(
            "SELECT DISTINCT build_id FROM publish_requests WHERE site_id = ? AND build_id != ''",
            (site_id,),
        ).fetchall()

    keep_build_ids = {str(row["id"]) for row in build_rows[:keep_builds]}
    keep_build_ids.update(str(row["build_id"]) for row in publish_build_rows if str(row["build_id"] or "").strip())

    keep_preview_ids: set[str] = set()
    preview_counts: dict[tuple[str, str], int] = {}
    preview_build_ids: set[str] = set()
    for row in preview_rows:
        key = (str(row["route"] or "/"), str(row["runtime_kind"] or ""))
        count = preview_counts.get(key, 0)
        preview_id = str(row["id"])
        build_id = str(row["build_id"] or "").strip()
        if count < keep_previews_per_route:
            keep_preview_ids.add(preview_id)
            preview_counts[key] = count + 1
            if build_id:
                preview_build_ids.add(build_id)
    keep_build_ids.update(preview_build_ids)

    keep_session_ids = {str(row["id"]) for row in session_rows[:keep_runtime_sessions]}
    keep_session_ids.update(str(row["id"]) for row in session_rows if str(row["preview_id"] or "") in keep_preview_ids)

    stale_preview_ids = [str(row["id"]) for row in preview_rows if str(row["id"]) not in keep_preview_ids]
    stale_session_ids = [str(row["id"]) for row in session_rows if str(row["id"]) not in keep_session_ids]
    stale_build_ids = [str(row["id"]) for row in build_rows if str(row["id"]) not in keep_build_ids]
    artifact_dirs = [_build_artifact_dir(data_root, site_id, build_id) for build_id in stale_build_ids]
    removable_artifact_dirs = [path for path in artifact_dirs if path.exists()]

    if not dry_run:
        with connect(data_root) as db:
            _delete_by_ids(db, "runtime_sessions", stale_session_ids)
            _delete_by_ids(db, "previews", stale_preview_ids)
            _delete_by_ids(db, "builds", stale_build_ids)
        for artifact_dir in removable_artifact_dirs:
            if _is_site_build_artifact_dir(data_root, site_id, artifact_dir):
                shutil.rmtree(artifact_dir)
        if stale_build_ids or stale_preview_ids or stale_session_ids:
            _record_prune_audit(
                data_root,
                site_id,
                {
                    "builds": len(stale_build_ids),
                    "previews": len(stale_preview_ids),
                    "runtime_sessions": len(stale_session_ids),
                    "artifact_dirs": len(removable_artifact_dirs),
                },
            )

    return {
        "site_id": site_id,
        "kept_builds": len(build_rows) - len(stale_build_ids),
        "kept_previews": len(preview_rows) - len(stale_preview_ids),
        "kept_runtime_sessions": len(session_rows) - len(stale_session_ids),
        "pruned_builds": len(stale_build_ids),
        "pruned_previews": len(stale_preview_ids),
        "pruned_runtime_sessions": len(stale_session_ids),
        "pruned_artifact_dirs": len(removable_artifact_dirs),
        "protected_build_ids": sorted(keep_build_ids),
    }


def _build_artifact_dir(data_root: Path, site_id: str, build_id: str) -> Path:
    if not build_id or "/" in build_id or "\\" in build_id or build_id in {".", ".."}:
        raise ValueError(f"Invalid build_id `{build_id}`")
    return data_root / "sites" / site_id / "builds" / build_id


def _is_site_build_artifact_dir(data_root: Path, site_id: str, path: Path) -> bool:
    try:
        path.resolve().relative_to((data_root / "sites" / site_id / "builds").resolve())
    except ValueError:
        return False
    return path.name not in {"", ".", ".."}


def _delete_by_ids(db, table: str, ids: list[str]) -> None:
    for item_id in ids:
        db.execute(f"DELETE FROM {table} WHERE id = ?", (item_id,))


def _record_prune_audit(data_root: Path, site_id: str, counts: dict[str, object]) -> None:
    ensure_schema(data_root)
    with connect(data_root) as db:
        db.execute(
            "INSERT INTO audit_events(id, site_id, event_type, summary, metadata_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                f"audit_{uuid4().hex[:16]}",
                site_id,
                "maintenance.pruned",
                "Pruned Website Studio operational history",
                json.dumps(counts, sort_keys=True),
                now_timestamp(),
            ),
        )
